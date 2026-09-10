"""FastAPI application: REST endpoints plus the single-page frontend.

Run with:  uvicorn src.api:app --reload
"""

from __future__ import annotations

import asyncio
import logging
import unicodedata
import uuid
from pathlib import Path
from urllib.parse import quote

from contextlib import asynccontextmanager

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src import (
    answer_memory, batches, conversations, events, forms, identity, progress, rewrite,
    runs, service, store, tools,
)
from src.agents import assistant
from src.identity import User
from src.config import configure_logging, settings
from src.documents import SUPPORTED_SUFFIXES
from src.extraction import detect_question_language
from src.export_docx import render_docx
from src.export_pdf import ExportError, ExportOptions, render_pdf, selected_answers
from src.models import (
    AnsweredQuestion, AssessmentResult, IngestResult, Language, Question, QuestionType,
    SourceType,
)

configure_logging()
logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).parent / "static"

# Whichever script carries more of a typed question carries the answer. The
# rule moved to `src.extraction` when the assistant needed it too; the name is
# kept because it is what this module and its tests call it.
_detect_language = detect_question_language


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

    replace_existing: bool = False
    """Answer questions that already have an answer, replacing what is there.

    Off unless the caller says otherwise, so that no scope, however broad, can
    quietly overwrite an answer the security team wrote into the file or a
    reviewer approved here.
    """


class ReviseBatchRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=2000)
    scope: ScopeRequest = Field(default_factory=ScopeRequest)


class SetAnswerRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=400)
    text: str = Field(max_length=20000)
    which: str = Field(default="answer", pattern="^(answer|brief)$")
    """Which of the two lengths is being edited. See `tools.set_answer`."""


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
    outcome = await _atool(tools.answer(
        user, batch_id, request.scope.to_scope(),
        replace_existing=request.replace_existing,
    ))
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
    _tool(lambda: tools.set_answer(
        user, batch_id, request.question_id, request.text, which=request.which,
    ))
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


class BlankAnswerRequest(BaseModel):
    """Which question to leave blank, or to stop leaving blank."""

    question_id: str = Field(min_length=1, max_length=400)
    blank: bool = True


@app.post("/api/forms/{batch_id}/blank")
def leave_an_answer_blank(
    batch_id: str, request: BlankAnswerRequest, user: User = Depends(current_user)
) -> dict:
    """Leave a question deliberately blank rather than unanswered, or undo that.

    The id travels in the body rather than the path: a question's id is the
    file's own -- `Human Resources!4` -- and a sheet name may contain anything
    a spreadsheet allows, slashes included.
    """
    _tool(lambda: tools.blank_answer(
        user, batch_id, request.question_id, blank=request.blank,
    ))
    return tools.inspect(user, batch_id)


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


class DetailRequest(BaseModel):
    """How long the answers in this questionnaire should be."""

    detail: str = Field(pattern="^(full|brief)$")


@app.post("/api/forms/{batch_id}/detail")
async def choose_answer_length(
    batch_id: str, request: DetailRequest, user: User = Depends(current_user)
) -> dict:
    """Switch a questionnaire between full and brief answers.

    Switching to brief derives the short form of every answer that does not
    have one yet -- one rewrite each, once. Switching back is instant, because
    the full answer was never replaced: both are stored against the question and
    the choice only says which one `fill` writes.
    """
    _tool(lambda: tools.set_detail(user, batch_id, request.detail))
    if request.detail == "brief":
        await _atool(tools.make_brief(user, batch_id))
    return tools.inspect(user, batch_id)


class PreferLengthRequest(BaseModel):
    """The length for one answer, overriding the questionnaire's default."""

    question_id: str = Field(min_length=1, max_length=400)
    prefer: str = Field(default="", pattern="^(full|brief|)$")


@app.post("/api/forms/{batch_id}/answers/length")
async def choose_one_answer_length(
    batch_id: str, request: PreferLengthRequest, user: User = Depends(current_user)
) -> dict:
    """Write this one answer full or brief, whatever the rest of the file does."""
    _tool(lambda: tools.prefer_length(user, batch_id, request.question_id, request.prefer))
    # Deriving on demand, for the one answer, so choosing "brief" on a file that
    # is set to full does not silently show the long text instead.
    if request.prefer == "brief":
        await _atool(tools.make_brief(
            user, batch_id, tools.Scope(ids=(request.question_id,)),
        ))
    return tools.inspect(user, batch_id)


class ApproveRequest(BaseModel):
    """One answer a person has read and accepted as it stands."""

    question_id: str = Field(min_length=1, max_length=400)
    approved: bool = True


@app.post("/api/forms/{batch_id}/approve")
def approve_an_answer(
    batch_id: str, request: ApproveRequest, tasks: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict:
    """Release one answer for writing, with the reviewer's name on it.

    Approving an answer somebody *wrote* also teaches the answer memory, which
    is where the team's own answers come from once the imported questionnaires
    run out; approving a draft nobody changed teaches it nothing, and
    `remembered` comes back empty. The sweep for what a new entry supersedes or
    contradicts runs after the response: it is model calls, and a reviewer
    clicking through twenty answers should not wait for any of them.
    """
    entry_id = _tool(lambda: tools.approve_answer(
        user, batch_id, request.question_id, approved=request.approved,
    ))
    if entry_id:
        tasks.add_task(_scan_memory)
    return {**tools.inspect(user, batch_id), "remembered": entry_id}


class FillRequest(BaseModel):
    """How much of the questionnaire to write."""

    include_unreviewed: bool = False
    """Write answers nobody has confirmed as well.

    Off by default, and deliberately awkward to turn on. Measured against the
    security team's own answers, every answer that contradicted them came back
    flagged and under 0.50 confidence -- so the default holds back exactly the
    ones that would embarrass the organisation, and turning it off is a thing
    somebody should have to mean.
    """


@app.post("/api/forms/{batch_id}/fill")
def fill_questionnaire(
    batch_id: str,
    request: FillRequest | None = None,
    user: User = Depends(current_user),
) -> dict:
    """Write the confirmed answers into a copy of the original, and report the rest."""
    include = bool(request and request.include_unreviewed)
    filled = _tool(lambda: tools.fill(user, batch_id, include_unreviewed=include))
    return {
        "file": filled.path.name,
        "written": filled.written,
        "created": filled.created,
        "replaced": filled.replaced,
        "intact": filled.intact,
        "skipped": filled.skipped,
        "blank": filled.blank,
        "held_back": filled.held_back,
        "because": filled.because,
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


async def _ingest_files(
    files: list[UploadFile], source_type: SourceType, authority: str = "ours",
) -> list[IngestResult]:
    """Save and index a batch of uploads. Shared by both ingestion endpoints."""
    if not files:
        raise HTTPException(status_code=400, detail="No files were uploaded.")

    results = []
    for upload in files:
        _check_suffix(upload.filename or "")
        path = service.save_upload(upload.filename or "upload", await upload.read())
        results.append(await service.ingest(path, source_type, authority))
    return results


# ---------------------------------------------------------------------------
# Knowledge base
# ---------------------------------------------------------------------------


# Every route here takes a session. The corpus has no owner -- it is what the
# organisation is bound by, and everyone on the team works from the same one --
# but "shared" is not "public": these read the policies out, index documents
# into them, and one of them empties the lot. Who did each of those is recorded,
# so a shared corpus is still an attributable one.


@app.get("/api/knowledge")
def get_knowledge(user: User = Depends(current_user)) -> dict:
    """What is currently indexed."""
    return service.knowledge_stats()


@app.post("/api/knowledge/guidelines")
async def upload_guidelines(
    files: list[UploadFile] = File(...),
    authority: str = Form(default="ours"),
    user: User = Depends(current_user),
) -> list[IngestResult]:
    """Index policy and guideline documents.

    `authority` is "ours" for something this organisation wrote and is bound by,
    "external" for a law, regulation or framework it is subject to. The drafter
    is told which, because our policy says what we *do* and a regulation says
    what we are *required* to do -- and answering the second as though it were
    the first claims a control we may not have.
    """
    if authority not in ("ours", "external"):
        raise HTTPException(status_code=400, detail="authority must be 'ours' or 'external'.")
    results = await _ingest_files(files, SourceType.GUIDELINE, authority)
    _record_indexing(user, results, authority=authority)
    return results


@app.post("/api/knowledge/prior-assessments")
async def upload_prior_assessments(
    tasks: BackgroundTasks,
    files: list[UploadFile] = File(...),
    user: User = Depends(current_user),
) -> list[IngestResult]:
    """Index previously answered assessments as question/answer pairs.

    Every pair becomes an answer-memory entry, and the sweep that works out what
    each one supersedes or contradicts runs after the response rather than
    inside it -- a file of sixty answers is sixty comparisons, and an upload
    that takes four minutes reads as an upload that has hung.
    """
    results = await _ingest_files(files, SourceType.PRIOR_ANSWER)
    _record_indexing(user, results)
    tasks.add_task(_scan_memory)
    return results


def _record_indexing(user: User, results: list[IngestResult], **payload) -> None:
    """One event per file that actually went in."""
    for result in results:
        if result.error or not result.chunks_indexed:
            continue
        events.record(
            user, events.DOCUMENT_INDEXED, subject_type="document",
            subject_id=result.source_name, chunks=result.chunks_indexed,
            source_type=result.source_type.value, **payload,
        )


@app.delete("/api/knowledge/sources/{source_name}")
def remove_source(source_name: str, user: User = Depends(current_user)) -> dict:
    """Remove one indexed file."""
    service.delete_source(source_name)
    events.record(
        user, events.SOURCE_REMOVED, subject_type="document", subject_id=source_name,
    )
    return {"deleted": source_name}


@app.delete("/api/knowledge")
def clear_knowledge(user: User = Depends(current_user)) -> dict:
    """Empty the knowledge base."""
    service.clear_knowledge()
    events.record(user, events.SOURCE_REMOVED, subject_type="document", subject_id="*", all=True)
    return {"cleared": True}


# ---------------------------------------------------------------------------
# The answer memory
#
# Shared by the whole team, like the knowledge base and for the same reason:
# what this organisation has said before is one fact about the organisation, not
# a private note. Who added or approved each entry is recorded on it, so a
# shared record is still an attributable one.
# ---------------------------------------------------------------------------


def _memory_payload(entry) -> dict:
    return {
        "entry_id": entry.entry_id,
        "question": entry.question,
        "answer": entry.answer,
        "section": entry.section,
        "from_file": entry.from_file,
        "origin": entry.origin,
        "approved_by": entry.approved_by,
        "approved_on": entry.approved_on,
        "superseded_by": entry.superseded_by,
        "stands": entry.stands,
    }


@app.get("/api/memory")
def list_memory(
    query: str = "",
    standing: str = "",
    origin: str = "",
    limit: int = 100,
    offset: int = 0,
    user: User = Depends(current_user),
) -> dict:
    """What we have said before, newest first."""
    keep = {"yes": True, "no": False}.get(standing.lower())
    found = answer_memory.entries(
        query=query, standing=keep, origin=origin,
        limit=max(1, min(limit, 500)), offset=max(0, offset),
    )
    return {
        "entries": [_memory_payload(entry) for entry in found],
        "total": answer_memory.count(query=query, standing=keep, origin=origin),
        "stats": answer_memory.stats(),
    }


@app.get("/api/memory/conflicts")
def list_memory_conflicts(user: User = Depends(current_user)) -> dict:
    """Pairs that disagree, with both answers, for somebody to decide between."""
    pairs = []
    for conflict in answer_memory.conflicts():
        first, second = answer_memory.get(conflict.entry_id), answer_memory.get(conflict.other_id)
        if first is None or second is None:
            continue
        pairs.append({
            "because": conflict.because,
            "raised_at": conflict.raised_at,
            "entry": _memory_payload(first),
            "other": _memory_payload(second),
        })
    return {"conflicts": pairs}


class MemoryEntryRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)
    section: str = Field(default="", max_length=400)


@app.post("/api/memory")
def add_memory_entry(
    body: MemoryEntryRequest, tasks: BackgroundTasks, user: User = Depends(current_user)
) -> dict:
    """Teach the memory an answer by hand."""
    entry = answer_memory.record(
        body.question, body.answer, section=body.section, origin="manual",
        approved_by=user.email, team_id=user.team_id,
    )
    events.record(
        user, events.MEMORY_ADDED, subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry.entry_id, question=entry.question[:200],
    )
    tasks.add_task(_scan_memory)
    return _memory_payload(entry)


class MemoryEditRequest(BaseModel):
    question: str | None = Field(default=None, max_length=4000)
    answer: str | None = Field(default=None, max_length=20000)


# `:path` on every one of these, and it is not cosmetic. An approved answer's id
# is `approved::<batch>::<question id>`, and a question id carries the shape of
# the questionnaire it came from -- `Cybersecurity Governance/Q1` in the Word
# forms. `encodeURIComponent` sends that slash as `%2F`, the server decodes it
# before routing, and a plain `{entry_id}` never matches a value with a slash in
# it: every attempt to correct or forget those entries returned 404, and the
# page left the card on screen because nothing had happened to it.
@app.patch("/api/memory/{entry_id:path}")
def edit_memory_entry(
    entry_id: str, body: MemoryEditRequest, tasks: BackgroundTasks,
    user: User = Depends(current_user),
) -> dict:
    """Correct an entry. Not a supersession: nothing changed its mind.

    A corrected answer is compared again, because correcting one is one of the
    ways it comes to contradict another.
    """
    entry = answer_memory.update(entry_id, question=body.question, answer=body.answer)
    if entry is None:
        raise HTTPException(status_code=404, detail="No such entry in the answer memory.")
    events.record(
        user, events.MEMORY_EDITED, subject_type=tools.SUBJECT_MEMORY, subject_id=entry_id,
    )
    tasks.add_task(_scan_memory)
    return _memory_payload(entry)


@app.delete("/api/memory/{entry_id:path}")
def remove_memory_entry(entry_id: str, user: User = Depends(current_user)) -> dict:
    """Forget an entry: the row, its vector, and the conflicts it raised."""
    if not answer_memory.remove(entry_id):
        raise HTTPException(status_code=404, detail="No such entry in the answer memory.")
    events.record(
        user, events.MEMORY_REMOVED, subject_type=tools.SUBJECT_MEMORY, subject_id=entry_id,
    )
    return {"deleted": entry_id}


@app.post("/api/memory/{entry_id:path}/restore")
def restore_memory_entry(entry_id: str, user: User = Depends(current_user)) -> dict:
    """Put a superseded entry back into use, when the later answer was wrong."""
    if answer_memory.get(entry_id) is None:
        raise HTTPException(status_code=404, detail="No such entry in the answer memory.")
    answer_memory.restore(entry_id)
    events.record(
        user, events.MEMORY_EDITED, subject_type=tools.SUBJECT_MEMORY,
        subject_id=entry_id, restored=True,
    )
    return _memory_payload(answer_memory.get(entry_id))


class ResolveConflictRequest(BaseModel):
    entry_id: str = Field(min_length=1, max_length=400)
    other_id: str = Field(min_length=1, max_length=400)
    resolution: str = Field(pattern="^(keep_this|keep_other|keep_both)$")


@app.post("/api/memory/conflicts/resolve")
def resolve_memory_conflict(
    body: ResolveConflictRequest, user: User = Depends(current_user)
) -> dict:
    """Say which of two disagreeing answers is our position, or that neither loses."""
    for entry_id in (body.entry_id, body.other_id):
        if answer_memory.get(entry_id) is None:
            raise HTTPException(status_code=404, detail="No such entry in the answer memory.")
    answer_memory.apply_resolution(
        body.entry_id, body.other_id, resolution=body.resolution, by=user.email,
    )
    events.record(
        user, events.MEMORY_RESOLVED, subject_type=tools.SUBJECT_MEMORY,
        subject_id=body.entry_id, other_id=body.other_id, resolution=body.resolution,
    )
    return {"resolved": True}


@app.post("/api/memory/scan")
async def scan_memory_now(limit: int = 50, user: User = Depends(current_user)) -> dict:
    """Compare everything that has arrived since the last sweep, and report it.

    The same sweep that runs by itself after an upload or an approval, exposed
    so a person can ask for it — after importing eleven questionnaires at once,
    "has anything I just added contradicted us" is a question with an answer,
    and waiting for a background task to have got round to it is not one.

    Bounded, and it says how much is left. A sweep is one model call per entry
    and a backlog can be hundreds: a button that returns in twenty seconds
    saying what it found and what remains is a button somebody will press again,
    and one that hangs for four minutes is one they will reload the page on.
    """
    findings = await answer_memory.scan_pending(limit=max(1, min(limit, 500)))
    return {
        "scanned": True,
        "found": [
            {"kind": f.kind, "other_id": f.other_id, "because": f.because,
             "other_question": f.other_question}
            for f in findings
        ],
        "stats": answer_memory.stats(),
    }


async def _scan_memory() -> None:
    """The sweep as a background task: never raises, never blocks a response."""
    try:
        found = await answer_memory.scan_pending(limit=200)
    except Exception:  # noqa: BLE001 - a background sweep must not take the app down
        logger.exception("The answer-memory sweep failed")
        return
    if found:
        logger.info("Answer memory: %d finding(s) from the sweep", len(found))


@app.get("/memory", include_in_schema=False)
def memory_page() -> FileResponse:
    """The answer memory, managed on a page of its own.

    Not a panel in the workbench: the workbench is organised around one
    questionnaire in front of you, and this is about everything the organisation
    has ever said, which is a different job done at a different time — usually
    after somebody notices an answer they disagree with.
    """
    return FileResponse(STATIC_DIR / "memory.html")


@app.get("/api/search")
async def search_knowledge(
    q: str = "",
    mode: str = "hybrid",
    limit: int = 20,
    source: str = "",
    user: User = Depends(current_user),
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
def get_documents(user: User = Depends(current_user)) -> dict:
    """The documents somebody has uploaded, for the interface to open."""
    documents = service.list_documents()
    return {"documents": documents, "uploaded_count": len(documents)}


def _resolve_document(origin: str, category: str, name: str) -> Path:
    try:
        return service.resolve_document(origin, category, name)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document '{name}' was not found.") from exc


@app.get("/api/documents/{origin}/{category}/{name}/file")
def view_document(
    origin: str, category: str, name: str, user: User = Depends(current_user)
) -> FileResponse:
    """Open or download the original PDF/DOCX document."""
    path = _resolve_document(origin, category, name)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@app.get("/api/documents/{origin}/{category}/{name}/preview")
def preview_document(
    origin: str, category: str, name: str, user: User = Depends(current_user)
) -> Response:
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
async def view_extracted_text(
    origin: str, category: str, name: str, user: User = Depends(current_user)
) -> dict:
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
async def extract_assessment(
    file: UploadFile = File(...), user: User = Depends(current_user),
) -> dict:
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


class ReviseAnswersRequest(BaseModel):
    """Answers to reword, handed straight back rather than stored."""

    answers: list[AnsweredQuestion] = Field(min_length=1, max_length=200)
    instruction: str = Field(min_length=1, max_length=2000)
    language: Language | None = None
    run_id: str | None = None


@app.post("/api/assessments/revise")
async def revise_answer_list(
    request: ReviseAnswersRequest, user: User = Depends(current_user)
) -> dict:
    """Reword answers the caller is holding, with no questionnaire behind them.

    The batch route does this for a file, keyed to the cells the answers belong
    in. Questions typed by hand have no cells and no batch, so the answers come
    in and go back out; the caller keeps them, exactly as it does for
    `/answer-questions`. Both routes run the same rewrite, so an instruction
    behaves the same whichever list it is given.
    """
    run_id = request.run_id or uuid.uuid4().hex[:12]
    progress.start(run_id, stage="rewriting")
    progress.set_total(run_id, len(request.answers))

    async def one(answered: AnsweredQuestion) -> AnsweredQuestion:
        try:
            return await rewrite.rewrite(answered, request.instruction, request.language)
        finally:
            progress.advance(run_id)

    try:
        revised = list(await asyncio.gather(*(one(a) for a in request.answers)))
    finally:
        progress.finish(run_id)

    return {"run_id": run_id, "answers": [answer.model_dump() for answer in revised]}


@app.get("/api/assessments/progress/{run_id}")
def assessment_progress(run_id: str, user: User = Depends(current_user)) -> dict:
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
    user: User = Depends(current_user),
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
    user: User = Depends(current_user),
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
# The assistant
# ---------------------------------------------------------------------------


class SayRequest(BaseModel):
    message: str = Field(min_length=1, max_length=8000)
    conversation_id: str = Field(default="", max_length=64)

    run_id: str = Field(default="", max_length=64)
    """A name the caller picked for this turn, so it can watch it happen.

    Minted by the page rather than here, because a first turn -- the slow one,
    where a file is read and answered -- has no conversation and no batch yet
    to be named after. `/api/assessments/progress/{run_id}` reports on it.
    """


def _conversation(conversation_id: str, user: User):
    conversation = conversations.load(conversation_id, team_id=user.team_id)
    if conversation is None:
        raise HTTPException(status_code=404, detail="That conversation no longer exists.")
    return conversation


def _turn_response(turn, conversation, user: User) -> dict:
    return {
        "reply": turn.reply,
        "conversation_id": conversation.id,
        "title": conversation.title,
        "batch_id": turn.batch_id,
        "steps": turn.steps,
        "sources": turn.sources,
        "refreshed": turn.refreshed,
        "stopped_early": turn.stopped_early,
        "seconds": round(turn.seconds, 1),
        "tokens": turn.input_tokens + turn.output_tokens,
        "answers": assistant.answers_for(user, conversation) if turn.refreshed else None,
    }


@app.get("/api/chat")
def list_conversations(user: User = Depends(current_user), limit: int = 30) -> dict:
    return {"conversations": conversations.recent(user.team_id, limit=limit)}


@app.post("/api/chat")
async def say_to_assistant(request: SayRequest, user: User = Depends(current_user)) -> dict:
    """One exchange with the assistant.

    Long: a message can mean "answer 183 questions", which is minutes of work.
    The conversation is saved by the assistant itself before this returns, so a
    request that times out at a proxy has still recorded what it did.
    """
    if not assistant.configured():
        raise HTTPException(status_code=503, detail="No model is configured for the assistant.")
    conversation = (
        _conversation(request.conversation_id, user) if request.conversation_id
        else assistant.start(user, request.message)
    )
    turn = await assistant.say(
        user, conversation, request.message, run_id=request.run_id,
    )
    return _turn_response(turn, conversation, user)


@app.post("/api/chat/upload")
async def say_with_a_file(
    message: str = Form(""),
    conversation_id: str = Form(""),
    run_id: str = Form(""),
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> dict:
    """A message with a questionnaire attached.

    Separate from the plain message route because it is multipart, not because
    it does anything different: the file is saved, the assistant is told it is
    there, and it decides to open it like any other operation.
    """
    if not assistant.configured():
        raise HTTPException(status_code=503, detail="No model is configured for the assistant.")
    name = file.filename or "questionnaire"
    if Path(name).suffix.lower() not in forms.SUPPORTED:
        raise HTTPException(
            status_code=400,
            detail=f"{Path(name).suffix or 'That file'} is not a questionnaire this can read. "
                   f"Supported: {', '.join(forms.SUPPORTED)}.",
        )
    path = service.save_upload(name, await file.read())
    conversation = (
        _conversation(conversation_id, user) if conversation_id
        else assistant.start(user, message or f"Read {name}")
    )
    turn = await assistant.say(
        user, conversation, message or f"Read {name} and tell me what is in it.",
        upload=path, run_id=run_id,
    )
    return _turn_response(turn, conversation, user)


@app.get("/api/chat/{conversation_id}")
def get_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict:
    """One conversation, as a transcript plus whatever answers it has produced.

    The stored messages are LangChain's, tool calls included, because the agent
    resumes from them. What comes back here is the readable half of that -- who
    said what -- because a person scrolling their own conversation has no use
    for a serialised tool call.
    """
    conversation = _conversation(conversation_id, user)
    transcript = []
    for message in conversation.messages:
        kind = getattr(message, "type", "")
        if kind == "human":
            # Their own words, without the note that told the agent a file had
            # arrived -- that is not something anybody said.
            transcript.append({"role": "you", "text": assistant.spoken(str(message.content))})
        elif kind == "ai" and not getattr(message, "tool_calls", None):
            text = message.content
            if isinstance(text, list):
                text = "".join(b.get("text", "") for b in text if isinstance(b, dict))
            if str(text).strip():
                # What the turn did, stored on the reply itself when it was made.
                drawn = (message.additional_kwargs or {}).get(assistant.UI_KEY) or {}
                transcript.append({
                    "role": "assistant",
                    "text": str(text).strip(),
                    "steps": drawn.get("steps", []),
                    "sources": drawn.get("sources", []),
                })
    return {
        "id": conversation.id,
        "title": conversation.title,
        "batch_id": conversation.batch_id,
        "messages": transcript,
        "answers": assistant.answers_for(user, conversation),
    }


@app.delete("/api/chat/{conversation_id}")
def forget_conversation(conversation_id: str, user: User = Depends(current_user)) -> dict:
    _conversation(conversation_id, user)
    conversations.delete(conversation_id)
    return {"deleted": conversation_id}


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.groq_chat_model}


# The pages were single files with everything inline until the answer card had
# to be shared between two of them. `/static` serves that one script and
# whatever else the pages come to share; the directory holds nothing else.
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    """The assistant, and the front door.

    A separate document from the workbench rather than a mode inside it. The
    two are different shapes -- one is a conversation, the other a workbench
    with every control on it -- and interleaving them would mean every control
    needing to know which mode it was in. They share the answer cards, which is
    the part worth sharing, and a link in each header.

    The conversation is what a person should meet first: it needs nothing
    explained, and everything the workbench does can be asked for in a
    sentence. The workbench is where you go when you want the controls.
    """
    return FileResponse(STATIC_DIR / "chat.html")


@app.get("/workbench", include_in_schema=False)
def workbench_page() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/chat", include_in_schema=False)
def chat_page() -> RedirectResponse:
    """Where the assistant used to live. Kept so old links and bookmarks work."""
    return RedirectResponse("/", status_code=308)
