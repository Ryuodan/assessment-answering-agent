"""FastAPI application: REST endpoints plus the single-page frontend.

Run with:  uvicorn src.api:app --reload
"""

from __future__ import annotations

import logging
import re
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src import batches, events, forms, identity, runs, service, store, tools
from src.identity import User
from src.config import configure_logging, settings
from src.documents import SUPPORTED_SUFFIXES
from src.export_docx import render_docx
from src.export_pdf import ExportError, ExportOptions, render_pdf, selected_answers
from src.models import AssessmentResult, IngestResult, Language, Question, QuestionType, SourceType

configure_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Whichever script carries more of a typed question carries the answer;
# see `_detect_language`.
_ARABIC = re.compile(r"[؀-ۿݐ-ݿ]")
_LATIN = re.compile(r"[A-Za-z]")


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    logger.info("Chat model: %s | Embeddings: %s", settings.groq_chat_model, settings.embedding_model)
    if not settings.groq_api_key:
        logger.warning("GROQ_API_KEY is not set — answering will fail until it is.")

    store.connect()  # applies the schema before the first request rather than during it
    identity.bootstrap()
    identity.purge_expired_sessions()
    identity.purge_old_attempts()
    if identity.sign_in_required():
        logger.info(
            "Sign-in required; %d user(s), %d admin(s).",
            len(identity.list_users()), identity.admin_count(),
        )
        if not identity.admin_count():
            logger.warning(
                "No administrator exists, so nobody can manage access. Set "
                "ADMIN_EMAIL and ADMIN_PASSWORD and restart."
            )
    else:
        logger.warning(
            "No users have been added — the API is open and every action will be "
            "attributed to %s. Add someone before exposing this beyond localhost.",
            identity.LOCAL_EMAIL,
        )
    yield


app = FastAPI(
    title="Assessment Answering Agent",
    description="Answers assessment questionnaires from your guidelines and previously answered assessments.",
    version="0.1.0",
    lifespan=lifespan,
)


@app.exception_handler(Exception)
async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
    """Turn an unexpected failure into a clean 500 rather than a traceback.

    Everything below this line talks to something that can be down -- Chroma,
    the embedding host, Groq, Docling, the disk. Without a handler FastAPI
    returns the default error page, which carries file paths from the server
    into the browser and tells the person nothing they can act on. The detail
    stays in the log, where it belongs.
    """
    logger.exception("Unhandled error on %s %s", request.method, request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Something went wrong on the server. The details are in its log."},
    )


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


def current_user(request: Request) -> User:
    """Who is making this request.

    Falls back to the local stand-in when no allow-list is configured, so a
    developer running the app on their own machine is not asked to sign in to a
    single-user service. Setting `ALLOWED_EMAILS` is what turns gating on —
    there is no second switch that could disagree with it.
    """
    user = identity.resolve(request.cookies.get(identity.SESSION_COOKIE))
    if user is not None:
        return user
    if not identity.sign_in_required():
        return identity.local_user()
    raise HTTPException(status_code=401, detail="Sign in to continue.")


class SignInRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=1, max_length=200)


def _user_payload(user: User) -> dict:
    return {
        "email": user.email,
        "team": user.team_id,
        "role": user.role,
        "is_admin": user.is_admin,
        "sign_in_required": identity.sign_in_required(),
    }


def current_admin(user: User = Depends(current_user)) -> User:
    """Refuse anyone who is not an administrator."""
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Administrator access is required.")
    return user


@app.post("/api/auth/session")
def sign_in(body: SignInRequest, request: Request, response: Response) -> dict:
    """Open a session for a known address and its access code."""
    try:
        token, user = identity.sign_in(body.email, body.code)
    except identity.AccessDenied as denied:
        raise HTTPException(status_code=403, detail=str(denied)) from denied

    response.set_cookie(
        identity.SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,      # the token is never needed by page scripts
        samesite="lax",
        # Secure follows the connection rather than a setting. A browser
        # silently discards a Secure cookie sent over http://, so tying this to
        # anything else produces a sign-in that appears to succeed and then
        # does nothing — the worst possible way for it to fail. Behind a
        # TLS-terminating proxy, run uvicorn with --proxy-headers so the
        # forwarded scheme is what is read here.
        secure=request.url.scheme == "https",
    )
    events.record(user, events.SIGNED_IN)
    return _user_payload(user)


@app.get("/api/auth/session")
def whoami(request: Request) -> dict:
    """The current user, or who would be required to sign in.

    Never 401s: the interface asks this on load to decide whether to show a
    sign-in screen, and an error response would make "signed out" look like a
    fault.
    """
    user = identity.resolve(request.cookies.get(identity.SESSION_COOKIE))
    if user is None and not identity.sign_in_required():
        user = identity.local_user()
    if user is None:
        # Same keys as the signed-in shape. A caller reading `is_admin` should
        # not have to know that the signed-out response omits it.
        return {
            "email": None, "team": None, "role": None,
            "is_admin": False, "sign_in_required": True,
        }
    return _user_payload(user)


@app.delete("/api/auth/session")
def sign_out(request: Request, response: Response) -> dict:
    """End the current session."""
    token = request.cookies.get(identity.SESSION_COOKIE)
    user = identity.resolve(token)
    identity.sign_out(token)
    response.delete_cookie(identity.SESSION_COOKIE)
    if user is not None:
        events.record(user, events.SIGNED_OUT)
    return {"signed_out": True}


# ---------------------------------------------------------------------------
# Administration
#
# Every route here changes who can reach the system, so every one records an
# event naming the administrator who did it. Being able to see that someone was
# added, and by whom, is the point of having a page rather than a config file.
# ---------------------------------------------------------------------------


class AddUserRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    team: str | None = None
    role: str = identity.MEMBER


class UpdateUserRequest(BaseModel):
    team: str | None = None
    role: str | None = None
    disabled: bool | None = None


class PasswordRequest(BaseModel):
    password: str | None = Field(default=None, max_length=200)


class TeamRequest(BaseModel):
    id: str = Field(min_length=1, max_length=64, pattern=r"^[a-z0-9][a-z0-9._-]*$")
    name: str = Field(default="", max_length=120)


def _guard(action) -> object:
    """Run an administrative action, turning a refusal into a 400."""
    try:
        return action()
    except identity.NotAllowed as refused:
        raise HTTPException(status_code=400, detail=str(refused)) from refused


@app.get("/api/admin/overview")
def admin_overview(admin: User = Depends(current_admin)) -> dict:
    return {
        "users": identity.list_users(),
        "teams": identity.list_teams(),
        "you": _user_payload(admin),
        "break_glass": identity.normalise(settings.admin_email) if settings.admin_email else None,
    }


@app.post("/api/admin/users")
def admin_add_user(body: AddUserRequest, admin: User = Depends(current_admin)) -> dict:
    user = _guard(lambda: identity.add_user(
        body.email, team_id=body.team, role=body.role, added_by=admin.email
    ))
    events.record(
        admin, events.USER_ADDED, subject_type="user", subject_id=user.email,
        team=user.team_id, role=user.role,
    )
    return {"user": user.email, "team": user.team_id, "role": user.role}


@app.patch("/api/admin/users/{email}")
def admin_update_user(email: str, body: UpdateUserRequest, admin: User = Depends(current_admin)) -> dict:
    address = identity.normalise(email)
    if body.role == identity.MEMBER or body.disabled:
        _refuse_last_admin(address)
    user = _guard(lambda: identity.update_user(
        address, team_id=body.team, role=body.role, disabled=body.disabled
    ))
    events.record(
        admin, events.USER_UPDATED, subject_type="user", subject_id=address,
        team=body.team, role=body.role, disabled=body.disabled,
    )
    return {"user": user.email, "team": user.team_id, "role": user.role}


@app.delete("/api/admin/users/{email}")
def admin_remove_user(email: str, admin: User = Depends(current_admin)) -> dict:
    address = identity.normalise(email)
    _refuse_last_admin(address)
    identity.remove_user(address)
    events.record(admin, events.USER_REMOVED, subject_type="user", subject_id=address)
    return {"removed": address}


def _refuse_last_admin(email: str) -> None:
    """Stop the only administrator locking everybody out.

    Recoverable via ADMIN_EMAIL / ADMIN_PASSWORD and a restart — but that needs
    whoever runs the host, which is exactly the dependency this page exists to
    remove.
    """
    user = identity.find_user_any(email)
    if user and user.is_admin and identity.admin_count() <= 1:
        raise HTTPException(
            status_code=400,
            detail="This is the only administrator. Promote someone else first.",
        )


@app.post("/api/admin/users/{email}/password")
def admin_set_password(email: str, body: PasswordRequest, admin: User = Depends(current_admin)) -> dict:
    """Give an admin their own password, or clear it back to the team code."""
    address = identity.normalise(email)
    if identity.find_user_any(address) is None:
        raise HTTPException(status_code=404, detail=f"No user {address}.")
    if address == identity.normalise(settings.admin_email):
        raise HTTPException(
            status_code=400,
            detail="This account's password comes from the environment and would be "
                   "restored on the next restart. Create a second administrator instead.",
        )
    identity.set_password(address, body.password or None)
    events.record(
        admin, events.PASSWORD_SET, subject_type="user", subject_id=address,
        cleared=not body.password,
    )
    return {"user": address, "has_password": bool(body.password)}


@app.post("/api/admin/teams")
def admin_add_team(body: TeamRequest, admin: User = Depends(current_admin)) -> dict:
    identity.ensure_team(body.id, name=body.name)
    events.record(admin, events.TEAM_ADDED, subject_type="team", subject_id=body.id, name=body.name)
    return {"team": body.id}


@app.delete("/api/admin/teams/{team_id}")
def admin_remove_team(team_id: str, admin: User = Depends(current_admin)) -> dict:
    _guard(lambda: identity.delete_team(team_id))
    events.record(admin, events.TEAM_REMOVED, subject_type="team", subject_id=team_id)
    return {"removed": team_id}


@app.post("/api/admin/teams/{team_id}/access-code")
def admin_rotate_code(team_id: str, admin: User = Depends(current_admin)) -> dict:
    """Issue a new access code. The plaintext is returned exactly once.

    Everyone on the team has to be given the new one — rotating is what you do
    when somebody leaves, so the old code ceasing to work is the feature.
    """
    if not any(team["id"] == team_id for team in identity.list_teams()):
        raise HTTPException(status_code=404, detail=f"No team {team_id!r}.")
    code = identity.set_access_code(team_id)
    events.record(admin, events.CODE_ROTATED, subject_type="team", subject_id=team_id)
    return {"team": team_id, "access_code": code}


@app.get("/admin", response_class=HTMLResponse)
def admin_page() -> FileResponse:
    """A deep link to the access panel, which lives inside the app itself.

    The same document as `/`, because a deployment may only expose the
    application's own address — an administrator who cannot reach a second URL
    would otherwise have no way in. Nothing is protected by living at a separate
    path anyway: `/api/admin/*` is what checks the role, and it does so whatever
    page the request came from. This route exists only so the link still works
    where that path *is* reachable.
    """
    return FileResponse(STATIC_DIR / "index.html")


# ---------------------------------------------------------------------------
# Questionnaires
#
# Thin: each route resolves the caller, turns the request into a `Scope`, and
# calls one operation in `src.tools`. Everything that decides anything lives
# there, so the agent in a later phase reaches exactly the same behaviour
# without going through HTTP.
# ---------------------------------------------------------------------------


class ScopeRequest(BaseModel):
    """Which questions an operation applies to."""

    ids: list[str] = Field(default_factory=list, max_length=2000)
    part: str = Field(default="", max_length=200)
    matching: str = Field(default="", max_length=200)
    unanswered_only: bool = False

    def to_scope(self) -> tools.Scope:
        return tools.Scope(
            ids=tuple(self.ids), part=self.part,
            matching=self.matching, unanswered_only=self.unanswered_only,
        )


class AnswerBatchRequest(BaseModel):
    scope: ScopeRequest = Field(default_factory=ScopeRequest)


class ReviseBatchRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    scope: ScopeRequest = Field(default_factory=ScopeRequest)


class SetAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=400)
    text: str = Field(max_length=20000)


def _tool(action):
    """Run a tool call, turning its refusals into readable HTTP errors."""
    try:
        return action()
    except tools.ToolError as refused:
        raise HTTPException(status_code=400, detail=str(refused)) from refused
    except forms.FormatError as unreadable:
        raise HTTPException(status_code=422, detail=str(unreadable)) from unreadable


@app.post("/api/forms")
async def open_questionnaire(
    file: UploadFile = File(...), user: User = Depends(current_user)
) -> dict:
    """Read an uploaded questionnaire and report what can be answered in it.

    Nothing is answered here. The point of the separation is that a person sees
    which sheets were used, which were skipped and why, and what each column was
    taken to be, *before* a run that costs minutes.
    """
    # Checked against what `forms` can read, not against the knowledge base's
    # list: the two accept different things. Policies come in as PDF or Word;
    # questionnaires are mostly spreadsheets, which the knowledge-base check
    # would have refused before the parser ever saw them.
    name = file.filename or "questionnaire"
    if Path(name).suffix.lower() not in forms.SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"{Path(name).suffix or 'That file'} is not a questionnaire this can read. "
                   f"Supported: {', '.join(forms.SUPPORTED)}.",
        )
    path = service.save_upload(name, await file.read())
    # In a thread: reading a workbook is a CPU-bound XML parse, and under the
    # assisted and agent strategies it is also a network call. Either way it is
    # not something to do on the event loop of a server answering other people.
    batch = await run_in_threadpool(lambda: _tool(lambda: tools.open_form(user, path)))
    return tools.inspect(user, batch.id)


@app.get("/api/forms")
def list_questionnaires(user: User = Depends(current_user), limit: int = 25) -> dict:
    return {"forms": batches.recent(user.team_id, limit=limit)}


@app.get("/api/forms/{batch_id}")
def get_questionnaire(batch_id: str, user: User = Depends(current_user)) -> dict:
    return _tool(lambda: tools.inspect(user, batch_id))


@app.post("/api/forms/{batch_id}/answer")
async def answer_questionnaire(
    batch_id: str, request: AnswerBatchRequest, user: User = Depends(current_user)
) -> dict:
    """Answer a selection. Long: a large questionnaire is minutes of work.

    `/api/assessments/progress/{batch_id}` reports how far it has got while this
    request is still open — the batch id is the run id, so it can be watched
    from the moment the call is made.
    """
    outcome = await _atool(tools.answer(user, batch_id, request.scope.to_scope()))
    return {**vars(outcome), "batch": tools.inspect(user, batch_id)}


@app.post("/api/forms/{batch_id}/revise")
async def revise_questionnaire(
    batch_id: str, request: ReviseBatchRequest, user: User = Depends(current_user)
) -> dict:
    outcome = await _atool(
        tools.revise(user, batch_id, request.instruction, request.scope.to_scope())
    )
    return {**vars(outcome), "batch": tools.inspect(user, batch_id)}


@app.post("/api/forms/{batch_id}/answers")
def write_answer_by_hand(
    batch_id: str, request: SetAnswerRequest, user: User = Depends(current_user)
) -> dict:
    _tool(lambda: tools.set_answer(user, batch_id, request.question_id, request.text))
    return tools.inspect(user, batch_id)


class ColumnRoleRequest(BaseModel):
    sheet: str = Field(min_length=1, max_length=200)
    column: str = Field(min_length=1, max_length=3, pattern=r"^[A-Za-z]{1,3}$")
    role: str = Field(min_length=1, max_length=20)


class QuestionChange(BaseModel):
    id: str = Field(min_length=1, max_length=400)
    skip: bool | None = None
    text: str = Field(default="", max_length=4000)


class QuestionChanges(BaseModel):
    changes: list[QuestionChange] = Field(min_length=1, max_length=2000)


@app.get("/api/forms/{batch_id}/columns")
def get_column_roles(batch_id: str, user: User = Depends(current_user)) -> dict:
    """Which column each sheet's answers go into, and why detection thinks so."""
    return {"sheets": _tool(lambda: tools.column_roles(user, batch_id))}


@app.post("/api/forms/{batch_id}/columns")
def set_column_role(
    batch_id: str, body: ColumnRoleRequest, user: User = Depends(current_user)
) -> dict:
    """Move a sheet's answers to a different column, or stop writing one."""
    return _tool(lambda: tools.set_column_role(user, batch_id, body.sheet, body.column, body.role))


@app.patch("/api/forms/{batch_id}/questions")
def correct_questions(
    batch_id: str, body: QuestionChanges, user: User = Depends(current_user)
) -> dict:
    """Set questions aside, bring them back, or correct their wording."""
    return _tool(lambda: tools.set_questions(
        user, batch_id, [change.model_dump(exclude_none=True) for change in body.changes]
    ))


@app.post("/api/forms/{batch_id}/fill")
def fill_questionnaire(batch_id: str, user: User = Depends(current_user)) -> dict:
    """Write the answers into a copy of the original and report what changed."""
    filled = _tool(lambda: tools.fill(user, batch_id))
    return {
        "file": filled.path.name,
        "written": filled.written,
        "created": filled.created,
        "replaced": filled.replaced,
        "intact": filled.intact,
        "skipped": filled.skipped,
        "blank": filled.blank,
    }


OOXML_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@app.get("/api/forms/{batch_id}/file")
def download_filled_questionnaire(batch_id: str, user: User = Depends(current_user)) -> FileResponse:
    """The filled copy. Produced by `/fill`, which must have run first."""
    batch = _tool(lambda: tools._require(user, batch_id))
    filled = tools._filled_path(batch)
    if not filled.exists():
        raise HTTPException(status_code=404, detail="Fill the questionnaire first.")
    # The real type, so a browser hands it to Excel or Word rather than to
    # whatever it does with an unknown blob; `attachment_headers` still forces
    # the download and carries the Arabic file name.
    return FileResponse(
        filled, filename=filled.name, headers=attachment_headers(filled.name),
        media_type=OOXML_TYPES.get(filled.suffix.lower(), "application/octet-stream"),
    )


async def _atool(coroutine):
    """`_tool`, for the operations that are asynchronous."""
    try:
        return await coroutine
    except tools.ToolError as refused:
        raise HTTPException(status_code=400, detail=str(refused)) from refused
    except forms.FormatError as unreadable:
        raise HTTPException(status_code=422, detail=str(unreadable)) from unreadable


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@app.get("/api/runs")
def list_runs(user: User = Depends(current_user), limit: int = 25) -> dict:
    """The team's answered runs, newest first."""
    return {"runs": [vars(summary) for summary in runs.recent(user.team_id, limit=limit)]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(current_user)) -> dict:
    """One run with its answers.

    Scoped to the caller's team, so an id belonging to another team reads as
    absent rather than forbidden.
    """
    stored = runs.load(run_id, team_id=user.team_id)
    if stored is None:
        raise HTTPException(status_code=404, detail=f"No run '{run_id}'.")
    return {
        **vars(stored.summary),
        "answers": [answer.model_dump() for answer in stored.answers],
        "history": [vars(event) for event in events.for_subject(runs.SUBJECT, run_id)],
    }


@app.get("/api/events")
def list_events(user: User = Depends(current_user), limit: int = 50, kind: str | None = None) -> dict:
    """Recent activity for the team."""
    return {"events": [vars(event) for event in events.recent(user.team_id, limit=limit, kind=kind)]}


def _check_suffix(filename: str) -> None:
    if Path(filename).suffix.lower() not in SUPPORTED_SUFFIXES:
        raise HTTPException(
            status_code=415,
            detail=f"'{filename}' is not supported. Upload {' or '.join(SUPPORTED_SUFFIXES)}.",
        )


async def _ingest_files(files: list[UploadFile], source_type: SourceType) -> list[IngestResult]:
    """Save and index a batch of uploads. Shared by both ingestion endpoints."""
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    results = []
    for upload in files:
        _check_suffix(upload.filename or "")
        path = service.save_upload(upload.filename or "upload", await upload.read())
        results.append(await service.ingest(path, source_type))
    return results


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


@app.get("/api/knowledge")
def get_knowledge() -> dict:
    """What is currently indexed."""
    return service.knowledge_stats()


@app.post("/api/knowledge/guidelines")
async def upload_guidelines(files: list[UploadFile] = File(...)) -> list[IngestResult]:
    """Index policy and guideline documents."""
    return await _ingest_files(files, SourceType.GUIDELINE)


@app.post("/api/knowledge/prior-assessments")
async def upload_prior_assessments(files: list[UploadFile] = File(...)) -> list[IngestResult]:
    """Index previously answered assessments as question/answer pairs."""
    return await _ingest_files(files, SourceType.PRIOR_ANSWER)


@app.delete("/api/knowledge/sources/{source_name}")
def remove_source(source_name: str) -> dict:
    """Remove one indexed file."""
    service.delete_source(source_name)
    return {"deleted": source_name}


@app.delete("/api/knowledge")
def clear_knowledge() -> dict:
    """Empty the knowledge base."""
    service.clear_knowledge()
    return {"cleared": True}


@app.get("/api/search")
async def search_knowledge(
    q: str = "",
    mode: str = "hybrid",
    limit: int = 20,
    source: str = "",
) -> dict:
    """Search the indexed corpus directly.

    Separate from answering: this is for a person checking what the corpus
    actually says, so it returns the chunks that matched rather than an answer
    written from them.
    """
    if mode not in ("semantic", "keyword", "hybrid"):
        raise HTTPException(status_code=422, detail=f"unknown search mode '{mode}'")
    return await service.search_knowledge(q, mode=mode, limit=limit, source_name=source)


# ---------------------------------------------------------------------------
# Document library and previews
# ---------------------------------------------------------------------------


@app.get("/api/documents")
def get_documents() -> dict:
    """List uploaded files and the bundled documents available for trial runs."""
    documents = service.list_documents()
    return {
        "documents": documents,
        "uploaded_count": sum(document["origin"] == "uploaded" for document in documents),
        "trial_count": sum(document["origin"] == "trial" for document in documents),
    }


def _resolve_document(origin: str, category: str, name: str) -> Path:
    try:
        return service.resolve_document(origin, category, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document '{name}' was not found.") from exc


@app.get("/api/documents/{origin}/{category}/{name}/file")
def view_document(origin: str, category: str, name: str) -> FileResponse:
    """Open or download the original PDF/DOCX document."""
    path = _resolve_document(origin, category, name)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@app.get("/api/documents/{origin}/{category}/{name}/preview")
def preview_document(origin: str, category: str, name: str) -> Response:
    """Return a browser preview: the original PDF or safe HTML converted from DOCX."""
    path = _resolve_document(origin, category, name)
    if path.suffix.lower() == ".pdf":
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    try:
        preview = service.docx_preview_html(path)
    except Exception as exc:  # noqa: BLE001 - normalize malformed Word files for the web client
        logger.exception("Could not preview %s", path.name)
        raise HTTPException(status_code=422, detail=f"Could not preview '{path.name}': {exc}") from exc

    return HTMLResponse(
        preview,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/documents/{origin}/{category}/{name}/text")
async def view_extracted_text(origin: str, category: str, name: str) -> dict:
    """Extract and return the document text, using the persistent extraction cache."""
    path = _resolve_document(origin, category, name)
    try:
        text = await service.extracted_document_text(path)
    except Exception as exc:  # noqa: BLE001 - normalize converter failures for the web client
        logger.exception("Could not extract text from %s", path.name)
        raise HTTPException(status_code=422, detail=f"Could not extract text from '{path.name}': {exc}") from exc
    return {"name": path.name, "text": text, "characters": len(text)}


# ---------------------------------------------------------------------------
# Answering
# ---------------------------------------------------------------------------


def _persist_run(user: User, result: AssessmentResult) -> None:
    """Save a finished run and record that it happened.

    Never raises. A run costs minutes; losing the answers because the history
    could not be written would be a far worse failure than losing the history,
    so this logs and returns. The log is loud because silently stopping keeping
    history is exactly the sort of thing nobody notices for a month.
    """
    try:
        runs.save(user, result)
        events.record(
            user,
            events.RUN_FINISHED,
            subject_type=runs.SUBJECT,
            subject_id=result.run_id,
            source_name=result.source_name,
            questions=result.questions_found,
            needs_review=result.needs_review_count,
            errors=sum(1 for answer in result.answers if answer.error),
        )
    except Exception:
        logger.exception("Could not save run %s; the answers were still returned.", result.run_id)


@app.post("/api/assessments/answer")
async def answer_assessment(
    file: UploadFile = File(...),
    language: Language | None = Form(default=None),
    run_id: str | None = Form(default=None),
    user: User = Depends(current_user),
) -> AssessmentResult:
    """Answer a new assessment.

    `language` forces the output language ("ar" or "en"); omit it to answer each
    question in the language it was asked.

    `run_id` is chosen by the caller so it can watch the run while this request
    is still open — answering a long assessment is minutes of silence, and the
    identifier has to be known before the work starts to be of any use.
    """
    _check_suffix(file.filename or "")
    path = service.save_upload(file.filename or "assessment", await file.read())

    result = await service.answer_assessment(path, language=language, run_id=run_id)
    if not result.answers:
        raise HTTPException(
            status_code=422,
            detail=f"No questions could be extracted from '{result.source_name}'.",
        )
    _persist_run(user, result)
    return result


class QuestionRequest(BaseModel):
    """A question to answer, as the interface holds it.

    Deliberately narrower than `Question`: the interface is allowed to say what
    is asked and in which language, and nothing else. Identifiers are assigned
    here so a caller cannot collide two questions on one id, which would make
    the answers ambiguous to match back.
    """

    text: str = Field(min_length=1)
    section: str | None = None
    question_type: QuestionType = QuestionType.FREE_TEXT
    options: list[str] = Field(default_factory=list)
    language: Language | None = None


class AnswerQuestionsRequest(BaseModel):
    questions: list[QuestionRequest] = Field(min_length=1, max_length=200)
    language: Language | None = None
    run_id: str | None = None
    source_name: str = "questions"


@app.post("/api/assessments/extract")
async def extract_assessment(file: UploadFile = File(...)) -> dict:
    """Pull the questions out of an assessment without answering them.

    The first half of `/answer`, separated so the questions can be reviewed and
    corrected before a run that costs minutes. Extraction is the step most
    likely to need a human eye: a numbered list can lose an item to a page
    break, and a row of guidance can read as a question.
    """
    _check_suffix(file.filename or "")
    path = service.save_upload(file.filename or "assessment", await file.read())

    language, questions = await service.extract_assessment_questions(path)
    if not questions:
        raise HTTPException(
            status_code=422,
            detail=f"No questions could be extracted from '{path.name}'.",
        )
    return {
        "source_name": path.name,
        "language": language,
        "questions": [question.model_dump() for question in questions],
    }


@app.post("/api/assessments/answer-questions")
async def answer_question_list(
    request: AnswerQuestionsRequest, user: User = Depends(current_user)
) -> AssessmentResult:
    """Answer a list of questions supplied directly, with no document involved.

    Serves three cases the document endpoint cannot: questions typed by hand,
    questions extracted from a file and then corrected, and a second batch
    added once an earlier one has been answered. The caller keeps the answers
    and decides how to merge them, so this returns only what it was asked for.
    """
    questions = [
        Question(
            id=str(index + 1),
            text=item.text.strip(),
            section=item.section,
            question_type=item.question_type,
            options=item.options,
            language=item.language or _detect_language(item.text),
        )
        for index, item in enumerate(request.questions)
    ]

    answers = await service.answer_questions(
        questions, language=request.language, run_id=request.run_id
    )
    result = AssessmentResult(
        run_id=request.run_id or uuid.uuid4().hex[:12],
        source_name=request.source_name,
        language=request.language or questions[0].language,
        questions_found=len(questions),
        answers=answers,
    )
    _persist_run(user, result)
    return result


def _detect_language(text: str) -> Language:
    """Which language a typed question is in, when the caller did not say.

    The document flow gets this from the extraction model, which reads a whole
    window. A single typed question has no such context, and asking a model
    would add a second of latency to decide something visible in the string.

    Counted rather than merely detected: an English question often carries an
    Arabic gloss — "Do you use MFA (متعدد العوامل)?" — and the presence of one
    Arabic letter would answer the whole thing in Arabic. Whichever script
    carries the question carries the answer.
    """
    arabic = len(_ARABIC.findall(text))
    latin = len(_LATIN.findall(text))
    return "ar" if arabic > latin else "en"


@app.get("/api/assessments/progress/{run_id}")
def assessment_progress(run_id: str) -> dict:
    """How far a run has got: questions found, answered, and left to answer."""
    state = service.run_progress(run_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"No run in progress with id '{run_id}'.")
    return state


def attachment_headers(filename: str) -> dict[str, str]:
    """`Content-Disposition` for a download, safe for a non-ASCII file name.

    HTTP header values are latin-1, so an Arabic assessment name raised
    UnicodeEncodeError inside Starlette and the download failed with a 500 —
    on precisely the corpus this system exists to serve. RFC 6266 answers it
    with two parameters: a transliterated `filename` that any client can read,
    and a percent-encoded `filename*` that modern browsers prefer.
    """
    stripped = unicodedata.normalize("NFKD", filename).encode("ascii", "ignore").decode()
    fallback = stripped.replace('"', "").strip() or "assessment"
    if fallback.startswith("."):
        fallback = f"assessment{fallback}"
    return {
        "Content-Disposition":
            f'attachment; filename="{fallback}"; filename*=UTF-8\'\'{quote(filename, safe="")}'
    }


@app.post("/api/assessments/export/pdf")
def export_pdf(
    result: AssessmentResult,
    include_flagged: bool = False,
    include_citations: bool = True,
    include_reasoning: bool = False,
) -> Response:
    """Render an answered assessment as a PDF.

    The result is posted back rather than looked up, because the interface lets
    a reviewer edit answers before exporting and those edits are the point.

    By default the file carries only answers that were not flagged for review:
    what goes back to an assessor should not silently include drafts the system
    itself was unsure of.
    """
    options = ExportOptions(
        include_flagged=include_flagged,
        include_citations=include_citations,
        include_reasoning=include_reasoning,
    )
    if not selected_answers(result, options):
        raise HTTPException(
            status_code=422,
            detail="No answer met the confidence threshold. Enable 'answers flagged for review' to export drafts.",
        )

    try:
        content = render_pdf(result, options)
    except ExportError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    filename = f"{Path(result.source_name).stem or 'assessment'}.answers.pdf"
    return Response(
        content=content,
        media_type="application/pdf",
        headers=attachment_headers(filename),
    )


@app.post("/api/assessments/export/docx")
def export_docx(
    result: AssessmentResult,
    include_flagged: bool = False,
    include_citations: bool = True,
    include_reasoning: bool = False,
) -> Response:
    """Render an answered assessment as a Word document.

    Same selection rule and same options as the PDF export; the difference is
    that the reviewer can carry on editing in the file. Arabic is laid out by
    Word rather than by us, which makes this the better format for an Arabic
    questionnaire.
    """
    options = ExportOptions(
        include_flagged=include_flagged,
        include_citations=include_citations,
        include_reasoning=include_reasoning,
    )
    if not selected_answers(result, options):
        raise HTTPException(
            status_code=422,
            detail="No answer met the confidence threshold. Enable 'answers flagged for review' to export drafts.",
        )

    content = render_docx(result, options)
    filename = f"{Path(result.source_name).stem or 'assessment'}.answers.docx"
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers=attachment_headers(filename),
    )


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.groq_chat_model}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")
