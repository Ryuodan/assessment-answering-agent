"""FastAPI application: REST endpoints plus the single-page frontend.

Run with:  uvicorn src.api:app --reload
"""

from __future__ import annotations

import asyncio
import unicodedata
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import quote

from contextlib import asynccontextmanager, suppress

from fastapi import BackgroundTasks, Depends, FastAPI, File, Form, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse, Response
from pydantic import BaseModel, Field
from starlette.concurrency import run_in_threadpool

from src import web
from src.logs import get_logger
from src import (
    batches,
    events,
    forms,
    identity,
    llm,
    preferences,
    products,
    progress,
    rewrite,
    runs,
    service,
    storage,
    store,
    tools,
)
from src.routes import admin as admin_routes
from src.routes import knowledge as knowledge_routes
from src.routes import memory as memory_routes
from src.routes import chat as chat_routes
from src.routes import forms as form_routes
from src.routes.memory import scan_memory as _scan_memory
from src.routes.knowledge import check_suffix
from src.routes import products as product_routes
from src.routes.auth import current_user, user_payload
from src.routes.pages import STATIC_DIR as STATIC_DIR, RevalidatedStatic, page
from src.identity import User
from src.config import configure_logging, settings
from src.errors import (
    Invalid,
    NotFound,
    Unprocessable,
)
from src.extraction import detect_question_language
from src.export_docx import render_docx
from src.export_pdf import ExportOptions, render_pdf, selected_answers
from src.models import (
    AnsweredQuestion,
    AssessmentResult,
    Language,
    Question,
    QuestionType,
)

configure_logging()
logger = get_logger(__name__)


# Whichever script carries more of a typed question carries the answer. The
# rule moved to `src.extraction` when the assistant needed it too; the name is
# kept because it is what this module and its tests call it.
_detect_language = detect_question_language


@asynccontextmanager
async def lifespan(_: FastAPI):
    settings.ensure_directories()
    logger.info("startup.models", chat_model=settings.groq_chat_model, embedding_model=settings.embedding_model)
    if not settings.groq_api_key:
        logger.warning("startup.no_model_key", setting="GROQ_API_KEY", effect="answering will fail")

    store.connect()  # applies the schema before the first request rather than during it
    identity.bootstrap()
    products.seed()  # SEED_PRODUCTS, the first time only (plan 020)
    identity.purge_expired_sessions()
    identity.purge_old_attempts()
    if identity.sign_in_required():
        logger.info(
            "startup.sign_in_required",
            users=len(identity.list_users()),
            admins=identity.admin_count(),
        )
        if not identity.admin_count():
            logger.warning("startup.no_administrator", fix="set ADMIN_EMAIL and ADMIN_PASSWORD and restart")
    else:
        logger.warning(
            "startup.open_access",
            acting_as=identity.LOCAL_EMAIL,
            fix="add someone before exposing this beyond localhost",
        )
    housekeeping = asyncio.create_task(storage.keep_within_limits())
    try:
        yield
    finally:
        housekeeping.cancel()
        with suppress(asyncio.CancelledError):
            await housekeeping
        await llm.close_clients()


app = FastAPI(
    title="Assessment Answering Agent",
    description="Answers assessment questionnaires from your guidelines and previously answered assessments.",
    version="0.1.0",
    lifespan=lifespan,
)
web.install(app)


# ---------------------------------------------------------------------------
# Identity
# ---------------------------------------------------------------------------


class SignInRequest(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    code: str = Field(min_length=1, max_length=200)


@app.post("/api/auth/session")
def sign_in(body: SignInRequest, request: Request, response: Response) -> dict:
    """Open a session for a known address and its access code."""
    token, user = identity.sign_in(body.email, body.code)

    response.set_cookie(
        identity.SESSION_COOKIE,
        token,
        max_age=settings.session_ttl_days * 86400,
        httponly=True,  # the token is never needed by page scripts
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
    return user_payload(user)


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
            "email": None,
            "team": None,
            "role": None,
            "is_admin": False,
            "sign_in_required": True,
        }
    return user_payload(user)


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
# Administration: people, teams and access codes, in src/routes/admin.py
# ---------------------------------------------------------------------------

app.include_router(admin_routes.router)
app.include_router(product_routes.router)  # products, src/routes/products.py


@app.get("/admin", response_class=HTMLResponse)
def adminpage() -> HTMLResponse:
    """A deep link to the access panel, which lives inside the app itself.

    The same document as `/`, because a deployment may only expose the
    application's own address — an administrator who cannot reach a second URL
    would otherwise have no way in. Nothing is protected by living at a separate
    path anyway: `/api/admin/*` is what checks the role, and it does so whatever
    page the request came from. This route exists only so the link still works
    where that path *is* reachable.
    """
    return page("index.html")


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
            ids=tuple(self.ids),
            part=self.part,
            matching=self.matching,
            unanswered_only=self.unanswered_only,
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


@app.post("/api/forms")
async def open_questionnaire(
    file: UploadFile = File(...), product: str = Form(""), user: User = Depends(current_user)
) -> dict:
    """Read an uploaded questionnaire, for a `product` or General, and report what can be answered in it.

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
        raise forms.UnsupportedForm(
            f"{Path(name).suffix or 'That file'} is not a questionnaire this can read. "
            f"Supported: {', '.join(forms.SUPPORTED)}."
        )
    product_id = products.chosen(user.team_id, product)  # before the file is kept
    path = service.save_upload(name, await file.read(), user.team_id, owner=user.email)
    # In a thread: reading a workbook is a CPU-bound XML parse, and under the
    # assisted and agent strategies it is also a network call. Either way it is
    # not something to do on the event loop of a server answering other people.
    batch = await run_in_threadpool(lambda: tools.open_form(user, path, product_id=product_id))
    return tools.inspect(user, batch.id)


@app.get("/api/forms")
def list_questionnaires(user: User = Depends(current_user), limit: int = 25) -> dict:
    return {"forms": batches.recent(user.team_id, actor_email=user.email, limit=limit)}


@app.get("/api/forms/{batch_id}")
def get_questionnaire(batch_id: str, user: User = Depends(current_user)) -> dict:
    return tools.inspect(user, batch_id)


@app.post("/api/forms/{batch_id}/answer")
async def answer_questionnaire(batch_id: str, request: AnswerBatchRequest, user: User = Depends(current_user)) -> dict:
    """Answer a selection. Long: a large questionnaire is minutes of work.

    `/api/assessments/progress/{batch_id}` reports how far it has got while this
    request is still open — the batch id is the run id, so it can be watched
    from the moment the call is made.
    """
    outcome = await tools.answer(
        user,
        batch_id,
        request.scope.to_scope(),
        replace_existing=request.replace_existing,
    )
    return {**vars(outcome), "batch": tools.inspect(user, batch_id)}


@app.post("/api/forms/{batch_id}/revise")
async def revise_questionnaire(batch_id: str, request: ReviseBatchRequest, user: User = Depends(current_user)) -> dict:
    outcome = await tools.revise(user, batch_id, request.instruction, request.scope.to_scope())
    return {**vars(outcome), "batch": tools.inspect(user, batch_id)}


@app.post("/api/forms/{batch_id}/answers")
def write_answer_by_hand(batch_id: str, request: SetAnswerRequest, user: User = Depends(current_user)) -> dict:
    tools.set_answer(
        user,
        batch_id,
        request.question_id,
        request.text,
        which=request.which,
    )
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
def leave_an_answer_blank(batch_id: str, request: BlankAnswerRequest, user: User = Depends(current_user)) -> dict:
    """Leave a question deliberately blank rather than unanswered, or undo that.

    The id travels in the body rather than the path: a question's id is the
    file's own -- `Human Resources!4` -- and a sheet name may contain anything
    a spreadsheet allows, slashes included.
    """
    tools.blank_answer(
        user,
        batch_id,
        request.question_id,
        blank=request.blank,
    )
    return tools.inspect(user, batch_id)


@app.get("/api/forms/{batch_id}/columns")
def get_column_roles(batch_id: str, user: User = Depends(current_user)) -> dict:
    """Which column each sheet's answers go into, and why detection thinks so."""
    return {"sheets": tools.column_roles(user, batch_id)}


@app.post("/api/forms/{batch_id}/columns")
def set_column_role(batch_id: str, body: ColumnRoleRequest, user: User = Depends(current_user)) -> dict:
    """Move a sheet's answers to a different column, or stop writing one."""
    return tools.set_column_role(user, batch_id, body.sheet, body.column, body.role)


@app.patch("/api/forms/{batch_id}/questions")
def correct_questions(batch_id: str, body: QuestionChanges, user: User = Depends(current_user)) -> dict:
    """Set questions aside, bring them back, or correct their wording."""
    return tools.set_questions(user, batch_id, [change.model_dump(exclude_none=True) for change in body.changes])


class DetailRequest(BaseModel):
    """How long the answers in this questionnaire should be."""

    detail: str = Field(pattern="^(full|brief)$")


@app.post("/api/forms/{batch_id}/detail")
async def choose_answer_length(batch_id: str, request: DetailRequest, user: User = Depends(current_user)) -> dict:
    """Switch a questionnaire between full and brief answers.

    Switching to brief derives the short form of every answer that does not
    have one yet -- one rewrite each, once. Switching back is instant, because
    the full answer was never replaced: both are stored against the question and
    the choice only says which one `fill` writes.
    """
    tools.set_detail(user, batch_id, request.detail)
    if request.detail == "brief":
        await tools.make_brief(user, batch_id)
    return tools.inspect(user, batch_id)


class ChooseProductRequest(BaseModel):
    product: str = Field(default="", max_length=64)
    """A product's id, or "" for General."""


@app.post("/api/forms/{batch_id}/product")
def choose_questionnaire_product(
    batch_id: str, request: ChooseProductRequest, user: User = Depends(current_user)
) -> dict[str, Any]:
    """Refused unless it is the questionnaire's own product: a product is fixed when the file is opened.

    Another product is 409 `product_locked` (TD-040); another team's is 404 `product_not_found` first.
    """
    tools.set_product(user, batch_id, request.product)
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
    tools.prefer_length(user, batch_id, request.question_id, request.prefer)
    # Deriving on demand, for the one answer, so choosing "brief" on a file that
    # is set to full does not silently show the long text instead.
    if request.prefer == "brief":
        await tools.make_brief(
            user,
            batch_id,
            tools.Scope(ids=(request.question_id,)),
        )
    return tools.inspect(user, batch_id)


class ApproveRequest(BaseModel):
    """One answer a person has read and accepted as it stands."""

    question_id: str = Field(min_length=1, max_length=400)
    approved: bool = True


@app.post("/api/forms/{batch_id}/approve")
def approve_an_answer(
    batch_id: str,
    request: ApproveRequest,
    tasks: BackgroundTasks,
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
    entry_id = tools.approve_answer(
        user,
        batch_id,
        request.question_id,
        approved=request.approved,
    )
    if entry_id:
        tasks.add_task(_scan_memory)
    return {**tools.inspect(user, batch_id), "remembered": entry_id}


app.include_router(form_routes.router)  # filling, src/routes/forms.py


OOXML_TYPES = {
    ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    ".xlsm": "application/vnd.ms-excel.sheet.macroEnabled.12",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
}


@app.get("/api/forms/{batch_id}/file")
def download_filled_questionnaire(batch_id: str, user: User = Depends(current_user)) -> FileResponse:
    """The filled copy. Produced by `/fill`, which must have run first."""
    batch = tools._require(user, batch_id, reading=True)  # a deleted product's too (plan 027)
    filled = tools._filled_path(batch)
    if not filled.exists():
        raise NotFound("Fill the questionnaire first.", code="filled_file_missing")
    # The real type, so a browser hands it to Excel or Word rather than to
    # whatever it does with an unknown blob; `attachment_headers` still forces
    # the download and carries the Arabic file name.
    return FileResponse(
        filled,
        filename=filled.name,
        headers=attachment_headers(filled.name),
        media_type=OOXML_TYPES.get(filled.suffix.lower(), "application/octet-stream"),
    )


# ---------------------------------------------------------------------------
# History
# ---------------------------------------------------------------------------


@app.get("/api/runs")
def list_runs(user: User = Depends(current_user), limit: int = 25) -> dict:
    """The team's answered runs, newest first."""
    return {"runs": [vars(summary) for summary in runs.recent(user.team_id, actor_email=user.email, limit=limit)]}


@app.get("/api/runs/{run_id}")
def get_run(run_id: str, user: User = Depends(current_user)) -> dict:
    """One run with its answers.

    Scoped to the caller's team, so an id belonging to another team reads as
    absent rather than forbidden.
    """
    stored = runs.load(run_id, team_id=user.team_id, actor_email=user.email)
    if stored is None:
        raise NotFound(f"No run '{run_id}'.", code="run_not_found")
    return {
        **vars(stored.summary),
        "answers": [answer.model_dump() for answer in stored.answers],
        "history": [vars(event) for event in events.for_subject(runs.SUBJECT, run_id)],
    }


@app.get("/api/events")
def list_events(user: User = Depends(current_user), limit: int = 50, kind: str | None = None) -> dict:
    """Recent activity for the team."""
    return {"events": [vars(event) for event in events.recent(user.team_id, limit=limit, kind=kind)]}


# ---------------------------------------------------------------------------
# Knowledge base: the shared one, or a product's, in src/routes/knowledge.py
# ---------------------------------------------------------------------------

app.include_router(knowledge_routes.router)


# ---------------------------------------------------------------------------
# The answer memory: the shared one, or a product's, in src/routes/memory.py
# ---------------------------------------------------------------------------

app.include_router(memory_routes.router)


# ---------------------------------------------------------------------------
# Preferences and skills
#
# Personal, unlike everything above: how one reviewer likes an answer worded is
# a fact about that reviewer, not about the organisation. So every route here
# acts on the signed-in person's own record and nobody else's, and a skill id
# that belongs to a colleague answers exactly as one that does not exist.
#
# Nothing here reaches the drafter. See `src.preferences`.
# ---------------------------------------------------------------------------


def _skill_payload(skill: preferences.Skill) -> dict:
    return {
        "skill_id": skill.skill_id,
        "name": skill.name,
        "description": skill.description,
        "instruction": skill.instruction,
        "builtin": skill.builtin,
        "updated_at": skill.updated_at,
    }


@app.get("/preferences", include_in_schema=False)
def preferencespage() -> HTMLResponse:
    return page("preferences.html")


@app.get("/api/preferences")
def get_preferences(user: User = Depends(current_user)) -> dict:
    """Preferences, what they add up to, and every skill this person can use."""
    from src import organisation

    mine = preferences.load(user.email)
    return {
        "preferences": mine.as_dict(),
        "instruction": mine.instruction(),
        "recommended": preferences.recommended(organisation.load().short_name).as_dict(),
        "skills": [_skill_payload(skill) for skill in preferences.skills(user.email)],
        "limits": {
            "also": preferences.MAX_ALSO,
            "refer_to": preferences.MAX_REFER_TO,
            "name": preferences.MAX_NAME,
            "description": preferences.MAX_DESCRIPTION,
            "instruction": preferences.MAX_INSTRUCTION,
            "skills": preferences.MAX_SKILLS,
        },
    }


class PreferencesRequest(BaseModel):
    default_length: str | None = Field(default=None, pattern="^(full|brief)$")
    verdict_first: bool | None = None
    refer_to: str | None = Field(default=None, max_length=preferences.MAX_REFER_TO)
    policy_references: str | None = Field(default=None, pattern="^(keep|citations_only)$")
    tone: str | None = Field(default=None, pattern="^(as_drafted|formal|plain)$")
    also: str | None = Field(default=None, max_length=preferences.MAX_ALSO)


@app.put("/api/preferences")
def save_preferences(body: PreferencesRequest, user: User = Depends(current_user)) -> dict:
    saved = preferences.save(user.email, **body.model_dump())
    events.record(
        user,
        events.PREFERENCES_CHANGED,
        subject_type="preferences",
        subject_id=user.email,
        rewords=saved.rewords,
        **{k: v for k, v in saved.as_dict().items() if k != "also"},
    )
    return get_preferences(user)


@app.post("/api/preferences/compose")
def compose_preferences(body: PreferencesRequest, user: User = Depends(current_user)) -> dict:
    """What a set of choices would tell the rewrite, without saving them.

    So the page can show the instruction as the choices change, and try it on a
    sample, from the one place that assembles it -- a copy of that logic in the
    browser would drift from the one that actually runs.
    """
    try:
        candidate = preferences.Preferences(
            **{
                **preferences.load(user.email).as_dict(),
                **{k: v for k, v in body.model_dump().items() if v is not None},
            }
        )
    except TypeError as bad:
        raise preferences.PreferenceError("Those preferences could not be applied.") from bad
    return {"instruction": candidate.instruction()}


class TryStyleRequest(BaseModel):
    instruction: str = Field(min_length=1, max_length=preferences.MAX_INSTRUCTION)
    question: str = Field(min_length=1, max_length=4000)
    answer: str = Field(min_length=1, max_length=20000)


@app.post("/api/preferences/try")
async def try_a_style(body: TryStyleRequest, user: User = Depends(current_user)) -> dict:
    """What an instruction does to one answer, before it is let loose on all of them.

    Preferences are applied to every answer somebody drafts and a skill to a
    whole selection, so a badly worded one reaches a questionnaire at once.
    This is the same rewrite over one sample, stored nowhere, so the person sees
    the effect first.
    """
    sample = AnsweredQuestion(
        question=Question(
            id="sample",
            text=body.question,
            language=detect_question_language(body.question),
        ),
        answer=body.answer,
        confidence=1.0,
    )
    reworded = await rewrite.rewrite(sample, body.instruction, note="Tried out.")
    return {
        "before": body.answer,
        "after": reworded.answer,
        "changed": reworded is not sample and reworded.answer.strip() != body.answer.strip(),
        "failed": reworded is sample,
    }


class SkillRequest(BaseModel):
    name: str = Field(min_length=1, max_length=preferences.MAX_NAME)
    description: str = Field(default="", max_length=preferences.MAX_DESCRIPTION)
    instruction: str = Field(min_length=1, max_length=preferences.MAX_INSTRUCTION)


class SkillEditRequest(BaseModel):
    name: str | None = Field(default=None, max_length=preferences.MAX_NAME)
    description: str | None = Field(default=None, max_length=preferences.MAX_DESCRIPTION)
    instruction: str | None = Field(default=None, max_length=preferences.MAX_INSTRUCTION)


@app.post("/api/skills")
def add_skill(body: SkillRequest, user: User = Depends(current_user)) -> dict:
    skill = preferences.add_skill(
        user.email,
        body.name,
        body.instruction,
        body.description,
    )
    events.record(
        user,
        events.SKILL_ADDED,
        subject_type="skill",
        subject_id=skill.skill_id,
        name=skill.name,
    )
    return _skill_payload(skill)


@app.patch("/api/skills/{skill_id}")
def edit_skill(skill_id: str, body: SkillEditRequest, user: User = Depends(current_user)) -> dict:
    skill = preferences.update_skill(
        user.email,
        skill_id,
        name=body.name,
        description=body.description,
        instruction=body.instruction,
    )
    if skill is None:
        raise NotFound("You have no skill like that.", code="skill_not_found")
    events.record(
        user,
        events.SKILL_EDITED,
        subject_type="skill",
        subject_id=skill_id,
        name=skill.name,
    )
    return _skill_payload(skill)


@app.delete("/api/skills/{skill_id}")
def remove_skill(skill_id: str, user: User = Depends(current_user)) -> dict:
    if not preferences.remove_skill(user.email, skill_id):
        raise NotFound("You have no skill like that.", code="skill_not_found")
    events.record(user, events.SKILL_REMOVED, subject_type="skill", subject_id=skill_id)
    return {"deleted": skill_id}


@app.post("/api/skills/{skill_id}/copy")
def copy_skill(skill_id: str, user: User = Depends(current_user)) -> dict:
    """A skill of your own, starting from a built-in one or another of yours."""
    skill = preferences.copy_skill(user.email, skill_id)
    if skill is None:
        raise NotFound("You have no skill like that.", code="skill_not_found")
    events.record(
        user,
        events.SKILL_ADDED,
        subject_type="skill",
        subject_id=skill.skill_id,
        name=skill.name,
        copied_from=skill_id,
    )
    return _skill_payload(skill)


class ApplySkillRequest(BaseModel):
    scope: ScopeRequest = Field(default_factory=ScopeRequest)
    include_written: bool = False


@app.post("/api/forms/{batch_id}/skills/{skill_id}")
async def apply_a_skill(
    batch_id: str, skill_id: str, body: ApplySkillRequest, user: User = Depends(current_user)
) -> dict:
    """Reword a selection of a questionnaire's answers with one of your skills."""
    skill, outcome = await tools.apply_skill(
        user,
        batch_id,
        skill_id,
        body.scope.to_scope(),
        include_written=body.include_written,
    )
    return {
        "skill": _skill_payload(skill),
        **vars(outcome),
        "batch": tools.inspect(user, batch_id),
    }


class RestoreDraftRequest(BaseModel):
    question_id: str = Field(min_length=1, max_length=400)


@app.post("/api/forms/{batch_id}/answers/draft")
def put_back_the_draft(batch_id: str, body: RestoreDraftRequest, user: User = Depends(current_user)) -> dict:
    """Undo a house style on one answer: the draft goes back as it was written."""
    tools.restore_draft(user, batch_id, body.question_id)
    return tools.inspect(user, batch_id)


@app.get("/memory", include_in_schema=False)
def memorypage() -> HTMLResponse:
    """The answer memory, managed on a page of its own.

    Not a panel in the workbench: the workbench is organised around one
    questionnaire in front of you, and this is about everything the organisation
    has ever said, which is a different job done at a different time — usually
    after somebody notices an answer they disagree with.
    """
    return page("memory.html")


@app.get("/api/search")
async def search_knowledge(
    q: str = "",
    mode: str = "hybrid",
    limit: int = 20,
    source: str = "",
    product: str = "",
    user: User = Depends(current_user),
) -> dict:
    """Search the indexed corpus directly.

    Separate from answering: this is for a person checking what the corpus
    actually says, so it returns the chunks that matched rather than an answer
    written from them. With a `product`, its knowledge base is searched too.
    """
    scope = {"product_id": products.chosen(user.team_id, product)} if product else {}
    if mode not in ("semantic", "keyword", "hybrid"):
        raise Unprocessable(f"unknown search mode '{mode}'", code="search_mode_unknown")
    return await service.search_knowledge(
        q,
        mode=mode,
        limit=limit,
        source_name=source,
        team_id=user.team_id,
        **scope,
    )


# ---------------------------------------------------------------------------
# Document library and previews
# ---------------------------------------------------------------------------


@app.get("/api/documents")
def get_documents(user: User = Depends(current_user)) -> dict:
    """The documents somebody has uploaded, for the interface to open."""
    documents = service.list_documents(user.team_id, owner=user.email)
    return {"documents": documents, "uploaded_count": len(documents)}


def _resolve_document(origin: str, category: str, name: str, user: User) -> Path:
    try:
        return service.resolve_document(origin, category, name, user.team_id, owner=user.email)
    except ValueError as exc:
        raise Invalid(str(exc), code="document_path_invalid") from exc
    except FileNotFoundError as exc:
        raise NotFound(f"Document '{name}' was not found.", code="document_not_found") from exc


@app.get("/api/documents/{origin}/{category}/{name}/file")
def view_document(origin: str, category: str, name: str, user: User = Depends(current_user)) -> FileResponse:
    """Open or download the original PDF/DOCX document."""
    path = _resolve_document(origin, category, name, user)
    return FileResponse(path, filename=path.name, content_disposition_type="inline")


@app.get("/api/documents/{origin}/{category}/{name}/preview")
def preview_document(origin: str, category: str, name: str, user: User = Depends(current_user)) -> Response:
    """Return a browser preview: the original PDF or safe HTML converted from DOCX."""
    path = _resolve_document(origin, category, name, user)
    if path.suffix.lower() == ".pdf":
        return FileResponse(path, filename=path.name, content_disposition_type="inline")

    try:
        preview = service.docx_preview_html(path)
    except Exception as exc:  # noqa: BLE001 - normalize malformed Word files for the web client
        logger.exception("document.preview_failed", document=path.name)
        raise Unprocessable(
            f"Could not preview '{path.name}': it could not be read as a Word document.", code="preview_failed"
        ) from exc

    return HTMLResponse(
        preview,
        headers={
            "Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'",
            "X-Content-Type-Options": "nosniff",
        },
    )


@app.get("/api/documents/{origin}/{category}/{name}/text")
async def view_extracted_text(origin: str, category: str, name: str, user: User = Depends(current_user)) -> dict:
    """Extract and return the document text, using the persistent extraction cache."""
    path = _resolve_document(origin, category, name, user)
    try:
        text = await service.extracted_document_text(path)
    except Exception as exc:  # noqa: BLE001 - normalize converter failures for the web client
        logger.exception("document.extraction_failed", document=path.name)
        raise Unprocessable(f"Could not extract text from '{path.name}'.", code="extraction_failed") from exc
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
        logger.exception("run.save_failed", run_id=result.run_id, effect="the answers were still returned")


async def _save_assessment(file: UploadFile, user: User) -> Path:
    """An uploaded assessment, checked for its type and kept as the person's own."""
    check_suffix(file.filename or "")
    return service.save_upload(file.filename or "assessment", await file.read(), user.team_id, owner=user.email)


def _export_options(
    result: AssessmentResult, include_flagged: bool, include_citations: bool, include_reasoning: bool
) -> ExportOptions:
    """The export's options, refusing an export that would hold no answer."""
    options = ExportOptions(
        include_flagged=include_flagged, include_citations=include_citations, include_reasoning=include_reasoning
    )
    if not selected_answers(result, options):
        raise Unprocessable(
            "No answer met the confidence threshold. Enable 'answers flagged for review' to export drafts.",
            code="nothing_to_export",
        )
    return options


@app.post("/api/assessments/answer")
async def answer_assessment(
    file: UploadFile = File(...),
    language: Language | None = Form(default=None),
    run_id: str | None = Form(default=None),
    product: str = Form(default=""),
    user: User = Depends(current_user),
) -> AssessmentResult:
    """Answer a new assessment.

    `language` forces the output language ("ar" or "en"); omit it to answer each
    question in the language it was asked.

    `run_id` is chosen by the caller so it can watch the run while this request
    is still open — answering a long assessment is minutes of silence, and the
    identifier has to be known before the work starts to be of any use.

    `product` answers it from that product's knowledge base beside the shared one.
    """
    scope = {"product_id": products.chosen(user.team_id, product)} if product else {}
    path = await _save_assessment(file, user)

    result = await service.answer_assessment(
        path,
        language=language,
        run_id=run_id,
        team_id=user.team_id,
        **scope,
    )
    if not result.answers:
        raise Unprocessable(f"No questions could be extracted from '{result.source_name}'.", code="no_questions_found")
    result.answers = await tools.in_house_style(
        user,
        result.answers,
        run_id=run_id or "",
        language=language,
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
    product: str = Field(default="", max_length=64)
    """A product's id to answer them for, beside the shared knowledge base; "" for General."""


@app.post("/api/assessments/extract")
async def extract_assessment(
    file: UploadFile = File(...),
    user: User = Depends(current_user),
) -> dict:
    """Pull the questions out of an assessment without answering them.

    The first half of `/answer`, separated so the questions can be reviewed and
    corrected before a run that costs minutes. Extraction is the step most
    likely to need a human eye: a numbered list can lose an item to a page
    break, and a row of guidance can read as a question.
    """
    path = await _save_assessment(file, user)

    language, questions = await service.extract_assessment_questions(path)
    if not questions:
        raise Unprocessable(f"No questions could be extracted from '{path.name}'.", code="no_questions_found")
    return {
        "source_name": path.name,
        "language": language,
        "questions": [question.model_dump() for question in questions],
    }


@app.post("/api/assessments/answer-questions")
async def answer_question_list(request: AnswerQuestionsRequest, user: User = Depends(current_user)) -> AssessmentResult:
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

    scope = {"product_id": products.chosen(user.team_id, request.product)} if request.product else {}
    answers = await service.answer_questions(
        questions,
        language=request.language,
        run_id=request.run_id,
        team_id=user.team_id,
        **scope,
    )
    # Every answer somebody drafts gets their house style, however it was asked
    # for -- a typed question in the workbench as much as a spreadsheet row.
    answers = await tools.in_house_style(
        user,
        answers,
        run_id=request.run_id or "",
        language=request.language,
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
async def revise_answer_list(request: ReviseAnswersRequest, user: User = Depends(current_user)) -> dict:
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
        raise NotFound(f"No run in progress with id '{run_id}'.", code="run_not_in_progress")
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
    return {"Content-Disposition": f"attachment; filename=\"{fallback}\"; filename*=UTF-8''{quote(filename, safe='')}"}


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
    options = _export_options(result, include_flagged, include_citations, include_reasoning)

    content = render_pdf(result, options)

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
    options = _export_options(result, include_flagged, include_citations, include_reasoning)

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

app.include_router(chat_routes.router)  # the assistant, src/routes/chat.py


# ---------------------------------------------------------------------------
# Frontend
# ---------------------------------------------------------------------------


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": settings.groq_chat_model}


# The pages were single files with everything inline until the answer card had
# to be shared between two of them. `/static` serves that one script and
# whatever else the pages come to share; the directory holds nothing else.
app.mount("/static", RevalidatedStatic(directory=STATIC_DIR), name="static")


@app.get("/", include_in_schema=False)
def index() -> HTMLResponse:
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
    return page("chat.html")


@app.get("/workbench", include_in_schema=False)
def workbenchpage() -> HTMLResponse:
    return page("index.html")


@app.get("/chat", include_in_schema=False)
def chatpage() -> RedirectResponse:
    """Where the assistant used to live. Kept so old links and bookmarks work."""
    # Relative, so it stays inside the prefix the app is served under.
    return RedirectResponse("./", status_code=308)
