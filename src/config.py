"""Application settings — the single source of truth for configuration.

Everything tunable lives here and is read from the environment (or `.env`).
Modules import the module-level `settings` singleton rather than reading
`os.environ` themselves, so there is exactly one place to look when a value
looks wrong.
"""

from __future__ import annotations

import hashlib
import os
import re
from pathlib import Path

from typing import Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from src.logs import configure as configure_logs
from src.logs import get_logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
logger = get_logger(__name__)


def _env_file() -> Path | None:
    """The env file settings are read from, besides the environment itself.

    `ASSESSMENT_ANSWER_ENV_FILE` names it; set but empty means none. Unset, it is
    the project's `.env`. The test suite sets it empty, so a developer's `.env`
    cannot change what the tests see (TD-011, tests/conftest.py). It is not a
    setting itself, being what decides where the settings come from.
    """
    named = os.environ.get("ASSESSMENT_ANSWER_ENV_FILE")
    if named is None:
        return PROJECT_ROOT / ".env"
    return Path(named) if named.strip() else None


def env_file_in_use() -> Path | None:
    """The env file this process reads its settings from, or None (for `doctor`)."""
    return _env_file()


def project_venv() -> Path:
    """Where `uv sync` builds the project's environment (for `doctor`)."""
    return PROJECT_ROOT / ".venv"


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=_env_file(),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM (Groq) --------------------------------------------------------
    groq_api_key: str = ""
    # Used for extraction, drafting and review.
    groq_chat_model: str = "openai/gpt-oss-120b"
    groq_reasoning_format: Literal["parsed", "hidden", "raw", ""] = Field(
        default="parsed",
        description="Groq's reasoning_format: parsed, hidden, raw, or '' to send nothing",
    )
    """How a reasoning model's thinking comes back.

    Groq defaults to `raw`, which puts the thinking inside the message as
    `<think>...</think>` -- so a deployment pointed at a reasoning model
    (qwen3, minimax-m2, deepseek-r1) had "<think>The user wants me to rewrite
    the answer..." written where the answer belongs. `parsed` keeps it beside
    the message instead, where the traces can still show it; `hidden` drops it.
    Empty sends nothing, for a gateway that rejects the parameter.
    """

    # ME-Central-1 regional endpoint. Host root only — the groq client appends
    # `/openai/v1` to it. Set to "" to fall back to the global api.groq.com.
    groq_base_url: str | None = "https://api.me-central-1.groqcloud.com"
    llm_temperature: float = 0.0
    # Grading model for eval/. Deliberately not the drafting model: a system
    # should not mark its own homework.
    eval_judge_model: str = "openai/gpt-oss-120b"

    # --- Sealed evaluation data ---------------------------------------------
    # Key for eval/sealed/ (eval/vault.py): URL-safe base64 of 32 bytes. Read
    # only by the evaluation tooling, never by the application. Empty means the
    # house set and the answer memory cannot be unlocked on this machine.
    eval_data_key: str = ""

    # --- Tracing (LangSmith) -----------------------------------------------
    # Every LLM call, retrieval and graph step recorded as a trace.
    #
    # Off unless deliberately switched on, and the reason is data residency
    # rather than cost. A trace carries the prompt, and the prompt carries the
    # policy chunks retrieved to answer the question. LangSmith has no Saudi
    # region -- `langsmith_endpoint` chooses between the EU and the US -- so
    # enabling this transfers internal policy text, and the client
    # questionnaires being answered, outside Saudi Arabia. That is a decision
    # for whoever owns the documents, not a default worth inheriting.
    langsmith_tracing: bool = False
    langsmith_endpoint: str = "https://eu.api.smith.langchain.com"
    langsmith_api_key: str = ""
    langsmith_project: str = "Cyber-Assessment-Answering-Agent"

    # --- Tracing (Phoenix, on this machine) --------------------------------
    # The same traces, kept locally. Phoenix is an OpenTelemetry collector with
    # a UI that understands LLM spans, and it runs wherever this does, so the
    # data-residency objection to LangSmith does not apply: nothing crosses a
    # border, or leaves the host at all.
    #
    # Still off by default, because a trace is a copy of the policy text and
    # the customer's questionnaire in a second store with no access control in
    # front of it. Local is not the same as harmless -- see docs/operations/tracing.md.
    phoenix_tracing: bool = False
    phoenix_endpoint: str = "http://localhost:6006/v1/traces"
    phoenix_project: str = "assessment-answer"

    # --- Embeddings (BGE-M3 behind an OpenAI-compatible endpoint) ----------
    embedding_base_url: str = "https://ds.t2.sa/text_embed/v1"
    embedding_model: str = "bge-m3"
    embedding_api_key: str = "unused"
    # Seconds one embedding request may take before it is retried (twice) and then
    # fails. Ingestion sends 64 chunks per request, so this bounds one batch, not a
    # whole file. Without it the client waited for ever: a stalled host held a run
    # for 53 minutes (TD-034, plan 017).
    embedding_timeout: float = Field(default=300.0, gt=0)

    # --- Document conversion (Docling) -------------------------------------
    # Docling runs as a container on the testing server and converts PDF/DOCX
    # to Markdown. Host root only — the endpoint paths are appended. Set to ""
    # to skip it entirely and use the local pdfplumber / python-docx loaders.
    docling_base_url: str = "http://localhost:8092"
    # Per-HTTP-request timeout: submitting a file, polling a task, fetching a
    # result. Each is short; the conversion itself is not one request.
    docling_timeout: float = Field(default=180.0, gt=0)
    # Total budget for one document's conversion, across all the polls it takes.
    # A 161-page standard runs well past the 300s cap the Docling server puts on
    # synchronous requests, which is why conversion is submitted asynchronously.
    docling_conversion_timeout: float = Field(default=2400.0, gt=0)
    # Force OCR on every document. Off by default: on a born-digital PDF it
    # costs ~2.3x and adds only whatever text sits inside the logos, while
    # table structure comes from a separate model that runs regardless.
    docling_do_ocr: bool = False
    # Turn OCR on automatically for a PDF with no usable text layer, so a
    # scanned upload is still read without making OCR everyone's default.
    docling_ocr_auto: bool = True
    docling_image_export_mode: Literal["placeholder", "embedded", "referenced"] = "placeholder"
    # Docling emits Markdown with no page information at all, so a citation
    # could name a clause but never a page. Given a placeholder it inserts one
    # between pages, which `docling_client` then rewrites into the numbered
    # markers the chunker already understands. Something that cannot occur in a
    # policy: it is matched literally.
    docling_page_break_placeholder: str = "<!-- docling-page-break -->"
    # Build a real heading hierarchy from bookmarks, numbering and styles.
    # Off in Docling by default, and the consequence is severe here: 85 of 86
    # documents came back with every heading at one level, which leaves the
    # chunker a flat list where it expects a tree. A chapter with no
    # sub-levels cannot be divided by its own subsections, which is how this
    # corpus ended up with units of 40, 100 and 113 parts. See src/chunking.py.
    docling_heading_hierarchy: bool = True
    # When Docling is unreachable, fall back to the local loaders rather than
    # failing the upload. Set false to make a broken Docling loud instead.
    docling_fallback_local: bool = True

    @property
    def docling_enabled(self) -> bool:
        return bool(self.docling_base_url.strip())

    # --- Reading questionnaires -------------------------------------------
    # How hard to work at understanding an uploaded questionnaire: 'rules',
    # 'assisted', 'agent', 'hybrid' or 'guarded'. Described, measured and
    # compared in `src.forms.reading`.
    #
    # 'guarded' by default -- the agent, floored by the rules. Measured over six
    # questionnaires in shapes nobody had written a rule for, the agent read
    # 292 of 292 against the rules' 272; measured over the nineteen we already
    # had, it quietly dropped a whole sheet. Running both and taking the better
    # reading per sheet costs one deterministic pass on top of the agent, which
    # is milliseconds and nothing.
    detection_strategy: Literal["rules", "assisted", "agent", "hybrid", "guarded"] = "guarded"

    # A sheet the rules cannot read is offered to a model, which proposes a
    # layout the ordinary reader then extracts from -- see `forms.llm_layout`.
    # Off by default: the rules read every sample workbook we have, so this
    # costs a call per unreadable sheet for files we have not seen yet. The
    # 'assisted' strategy turns it on for one reading without changing this.
    detection_assist: bool = False
    # A sheet where the rules found questions on fewer than this share of the
    # rows below the header is also offered, because "7 questions on a sheet of
    # 133 rows" is a wrong column rather than a short questionnaire. The
    # model's reading is taken only if it finds more, so assistance can add
    # questions but never remove them.
    detection_assist_coverage: float = Field(default=0.25, ge=0.0, le=1.0)
    detection_assist_min_rows: int = 20

    # The Excel agent reads a workbook through tools instead, exploring it
    # before committing to a layout. Built to be compared against the two above
    # rather than to replace them; see `src.agents.excel_agent`.
    excel_agent_max_steps: int = Field(default=24, ge=4, le=80)

    # --- Storage -----------------------------------------------------------
    chroma_dir: Path = PROJECT_ROOT / "chroma_db"
    collection_name: str = "assessment_knowledge"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    # Cache for document text shown in the interface.
    extracted_text_dir: Path = PROJECT_ROOT / "data" / "extracted"

    filled_dir: Path = PROJECT_ROOT / "data" / "filled"
    """Where a filled copy of a questionnaire is written, one directory per batch.

    Separate from the uploads, which are the originals a person compares
    against, and separate per batch, because two people can open the same
    questionnaire and each has their own answers to write into it.
    """

    # --- Retrieval + answering --------------------------------------------
    # Guideline chunks retrieved per search query.
    top_k_guidelines: int = 8
    # Previous answers retrieved per question.
    top_k_prior_answers: int = 5

    # Split a multi-part question into one search per part before retrieving.
    # Costs one extra LLM call per question; turn it off to retrieve on the
    # question's own wording alone.
    query_expansion: bool = True
    # The verbatim question always occupies the first slot, so this is one
    # more than the number of decomposed angles. Four left only three angles
    # for a question needing five different policies, which is most of what
    # multi-document recall was losing.
    max_search_queries: int = Field(default=6, ge=1, le=8)

    # Fuse a BM25 pass with the dense search, to catch the exact figures
    # embeddings blur — "72 hours", "90 days", "12 characters". Off by default
    # because it measured worse on the T2 corpus: 71.4% against 73.6% for dense
    # alone. It does what it claims (it moved the PDPL 72-hour clause from rank
    # 11 to rank 1) but it also promotes the wrong section of the right
    # document, and on the golden set it lost more than it won. Turn it on for a
    # corpus whose questions are mostly exact-figure lookups, and re-run
    # `eval/` to check. See src/lexical.py.
    hybrid_search: bool = False
    # How much the BM25 ranking counts against the dense one. Below 1.0 it can
    # promote a chunk dense also found but ranked low, without letting a
    # keyword-only match displace a semantically better hit.
    lexical_weight: float = Field(default=0.4, ge=0.0, le=1.0)

    # Cross-encoder reranking of the retrieved evidence, once per question.
    # See src/rerank.py; the model is downloaded on first use (~2.3 GB).
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_max_length: int = 1024
    reranker_batch_size: int = 16
    # Draft/review rounds per question. Evidence accumulates across rounds
    # rather than being replaced, so a third attempt adds material to the
    # drafter's context instead of trading one retrieval for another.
    max_answer_attempts: int = Field(default=3, ge=1, le=5)
    # Questions answered at once. Raise carefully: Groq rate limits apply.
    max_concurrent_questions: int = Field(default=4, ge=1, le=32)
    # Rewordings reaching the model at once: preferences, skills, "make them
    # shorter", and the brief form, each one call per answer. Unbounded, 80 at
    # once lost 44 to Groq's rate limit and every lost one stayed as it was.
    max_concurrent_rewrites: int = Field(default=8, ge=1, le=64)

    # Stored files per person: the questionnaires they uploaded and the filled
    # copies written from them. Under the limit nothing is removed; over it, the
    # files of the work they have not used longest go first -- never a document
    # the team's knowledge base was built from, and never anything used in the
    # last STORAGE_KEEP_DAYS days, whatever the limit says. Per person, because
    # that is who a questionnaire belongs to, so a new colleague brings their
    # own allowance. 0 turns the limit off.
    storage_limit_per_user_mb: int = Field(default=2048, ge=0)
    # Nothing used this recently is removed, even over the limit.
    storage_keep_days: int = Field(default=30, ge=1)
    # Below this, an answer is flagged for review.
    review_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    # 1200, not the 1800 this carried while Markdown tables still held Docling's
    # alignment padding. De-padding changed what the number buys: at 1800 a chunk
    # held 1,118 characters of content instead of 950, the corpus became coarser
    # than the retriever was tuned for, and measured accuracy fell 4.4 points.
    # 1200 restores the granularity and still holds more content than 1800 did.
    chunk_size: int = 1200
    chunk_overlap: int = 150  # retained for the prose fallback only
    max_expanded_chars: int = 12000  # cap on parent-unit expansion, per question
    # Expansion completes a split unit so the drafter never sees three items of
    # a nine-item series and calls it the list. That is right for a clause
    # series; it is wrong for a chapter. 79% of units in this corpus are a
    # single chunk and 96% are six parts or fewer, but the remaining few run to
    # 40, 100, even 113 parts — a whole standard with no internal headings to
    # divide on. Expanding one of those filled all fourteen prompt slots from a
    # single document and pushed every other policy out. Above this many parts
    # the hit is returned on its own, which is not contextless: every part
    # repeats the unit's stem.
    max_expanded_parts: int = Field(default=6, ge=1)
    # Cap on accumulated evidence per question. 38 rather than 30 because the
    # smaller chunks above put less text in each slot: at 30 the drafter saw
    # about a fifth less material than before, and four documents per run were
    # retrieved and then cut before reaching it.
    max_evidence_chunks: int = 38
    # How many of those chunks may be previous answers. They sort first, so
    # without a ceiling they take the whole prompt and the policies that
    # actually answer the question never reach the drafter — see
    # `select_evidence`. Raise it for a corpus where the previous answers are
    # the authority; lower it to make the drafter lean on the guidelines.
    max_prior_answer_chunks: int = Field(default=4, ge=0)

    # Keep a retrieved unit only if it scores within this fraction of the best
    # hit for the question, so a simple lookup is answered from six chunks and
    # a synthesis question still gets forty. 0 disables it and the budget alone
    # decides. Judged on the agreement-weighted score, so a clause several
    # independent searches converged on survives a floor that its raw cosine
    # would not — the two precision signals available for free, combined.
    #
    # Set it high or not at all: BGE-M3 cosines on policy prose bunch tightly,
    # and on this corpus the median retrieved chunk still scores 94% of the
    # best hit, so anything below ~0.90 discards nothing.
    evidence_score_floor: float = Field(default=0.0, ge=0.0, le=1.0)
    # Never prune below this many chunks, whatever the floor says. A question
    # whose best hit is itself weak would otherwise be answered from one chunk.
    min_evidence_chunks: int = Field(default=8, ge=1)

    # Grade each retrieved chunk against the question with an LLM, and use the
    # verdicts to re-order the evidence. Cosine cannot do this job on policy
    # prose: even the five best-ranked chunks are only about a third on-target,
    # and every threshold tried on the score itself cost two to four points of
    # recall for each point of precision. A grader reads query and chunk
    # together, which is the interaction an embedding discards.
    relevance_filter_enabled: bool = False
    # Chunks per grading call. One call per chunk would be ~2,000 calls for a
    # 42-question run and trips Groq's rate limit; a dozen per call makes it
    # three calls per question, issued concurrently.
    relevance_filter_batch: int = Field(default=12, ge=1)
    # Chunks always kept regardless of the verdicts. The grader is one more
    # thing that can be wrong, and a false negative on the only chunk carrying
    # the answer leaves nothing to recover from.
    relevance_filter_keep: int = Field(default=8, ge=0)
    # Blank uses GROQ_CHAT_MODEL. A smaller model is faster and cheaper, but
    # verify it on Arabic before trusting it: this corpus is half Arabic, and
    # small models degrade there first.
    relevance_filter_model: str = ""
    # Characters of each chunk shown to the grader. Enough to judge relevance,
    # short enough that a dozen fit in one call.
    relevance_filter_snippet: int = Field(default=700, ge=100)
    # Move graded-relevant material to the front, rather than only deleting
    # off-target material from the back. Without this the grader can never put
    # a good chunk sitting at position 25 into the top eight -- and the drafter
    # cites about eight sources however many it is shown, so the back of the
    # prompt is the one place a change cannot matter. The keep floor still
    # protects those chunks from deletion; it no longer pins them in place.
    relevance_filter_promote: bool = True

    # How much a chunk gains for each extra search that independently returned
    # it. Query expansion runs several deliberately overlapping searches per
    # question, so agreement between them is a relevance signal that costs
    # nothing extra to collect. A chunk found by 3 of 4 searches is scored
    # `1 + 2 * weight` times its similarity. 0 disables it; with query
    # expansion off it has no effect either way. See graph/state.py.
    query_agreement_weight: float = Field(default=0.15, ge=0.0, le=1.0)
    extraction_window: int = 2000

    incomplete_list_confidence_cap: float = Field(default=0.5, ge=0.0, le=1.0)

    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    # How log lines are written: "text" for a person at a terminal, "json" for
    # one object per line where a log collector reads them (src/logs.py).
    log_format: str = Field(default="text", pattern="^(text|json)$")

    # --- Identity and history (Phase 0) ------------------------------------
    # One SQLite file holds users, teams, sessions, the event log and answered
    # runs. SQLite rather than a server because the whole point of this store is
    # that it is always there: no second process to start, no connection string
    # to get wrong, and a single file to copy when someone wants a backup.
    db_path: Path = PROJECT_ROOT / "data" / "app.db"
    # Who this deployment answers on behalf of (src/organisation.py): a JSON file
    # an administrator edits; when it is missing, the built-in profile is used.
    organisation_path: Path = PROJECT_ROOT / "data" / "organisation.json"
    # Where serve.sh writes the server's output; `python -m src.cli inspect request` reads it.
    server_log_path: Path = PROJECT_ROOT / "logs" / "server.log"

    # Members to create on a FIRST run only, comma-separated. Access is
    # administered on the admin page once the system is running -- this exists
    # so a deployment that predates the admin page keeps working, and so a new
    # one can start with its team already listed. Removing someone on the page
    # is not undone by a restart. A plain string rather than `list[str]`
    # deliberately: pydantic-settings tries to JSON-decode list-typed fields, so
    # `ALLOWED_EMAILS=a@t2.sa,b@t2.sa` raises a parse error instead of doing the
    # obvious thing. Read `allowed_emails_set`, never this.
    allowed_emails: str = ""
    # Products added to the default team the first time the server starts,
    # comma-separated. Applied once: the Products page is authoritative after
    # that, so a product deleted there stays deleted (plan 020).
    seed_products: str = ""

    # The break-glass administrator, re-applied at every startup. This is the
    # one account the environment owns, and the way back in when a password is
    # lost or the last admin is removed by accident -- so it is also the only
    # account whose password cannot be changed from the admin page. Create a
    # second admin there for everyday use.
    admin_email: str = ""
    admin_password: str = ""

    # A shared access code is only as strong as the number of guesses allowed
    # against it. Counted per address, because the code is shared by a team and
    # an attacker with a proxy pool would otherwise spread guesses across it.
    sign_in_max_attempts: int = Field(default=10, ge=1)
    sign_in_lockout_minutes: int = Field(default=15, ge=1)
    # Everyone who signs in joins this team until there is a reason to have two.
    # Teams exist in the schema from the start because retrofitting a tenant
    # column onto rows that already exist is the migration nobody enjoys.
    default_team: str = "cybersecurity"
    # How long a sign-in lasts. Sessions are rows, so this is also how long a
    # revoked-by-deletion session stays revoked.
    session_ttl_days: int = Field(default=30, ge=1)

    @property
    def allowed_emails_set(self) -> frozenset[str]:
        """The first-run seed list, lower-cased and stripped.

        Empty is the ordinary case once a system has been set up: the users
        table is the allow-list, and this only ever plants the first entries in
        it.
        """
        return frozenset(part.strip().casefold() for part in self.allowed_emails.split(",") if part.strip())

    @field_validator("log_level", mode="before")
    @classmethod
    def _log_level_in_any_case(cls, value: object) -> object:
        """`LOG_LEVEL=info` worked before the vocabulary was enforced, so case is not an error."""
        return value.upper() if isinstance(value, str) else value

    @field_validator(
        "chroma_dir",
        "upload_dir",
        "filled_dir",
        "extracted_text_dir",
        "db_path",
        "organisation_path",
        "server_log_path",
    )
    @classmethod
    def _anchor_to_project(cls, value: Path) -> Path:
        """Resolve a relative path against the project, not the process's cwd.

        `.env` naturally holds `CHROMA_DIR=./chroma_db`, which means something
        different depending on where the process was launched from. Started
        from the repository root rather than the application directory, the API
        created an empty database beside the wrong folder and reported an empty
        knowledge base — no error, no warning, just nothing indexed. A service
        that silently loses its corpus because of a launch directory is not one
        to put in front of an assessor.
        """
        return value if value.is_absolute() else (PROJECT_ROOT / value).resolve()

    def user_upload_dir(self, team_id: str | None, email: str) -> Path:
        """Where one person's questionnaires are kept.

        A questionnaire arrives from another company, usually under an NDA, and
        belongs to the person working on it -- so it is not in a folder the
        whole team's files share. Policies still are: the knowledge base is the
        team's, and every answer is drafted from it.

        The folder is named from the address so it can be read by a person
        looking at the disk, with a hash after it so two addresses can never
        collide and nothing in an address can shape a path.
        """
        if not email or not email.strip():
            raise ValueError("A person's upload directory needs their address.")
        settled = email.strip().casefold()
        readable = re.sub(r"[^a-z0-9._-]+", "-", settled).strip("-.")[:40] or "person"
        fingerprint = hashlib.sha256(settled.encode("utf-8")).hexdigest()[:10]
        return self.team_upload_dir(team_id).parent / "people" / f"{readable}-{fingerprint}" / "uploads"

    def team_upload_dir(self, team_id: str | None = None) -> Path:
        """Where one team's uploads live: its policies and its questionnaires.

        The default team keeps `upload_dir` itself, where everything uploaded
        before teams had their own already is. Another team's files go under
        `teams/<team>/uploads` beside it, so no team can list, open or preview
        another's documents by name. The id is checked before it becomes part
        of a path: team ids come from the admin page, and `../x` is not a team.
        """
        team = team_id or self.default_team
        if team == self.default_team:
            return self.upload_dir
        if not re.fullmatch(r"[a-z0-9][a-z0-9._-]{0,63}", team) or ".." in team:
            raise ValueError(f"{team!r} cannot name a directory.")
        return self.upload_dir.parent / "teams" / team / "uploads"

    def ensure_directories(self) -> None:
        """Create the directories the app writes to. Safe to call repeatedly."""
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.filled_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_text_dir.mkdir(parents=True, exist_ok=True)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)


settings = Settings()


def configure_tracing() -> bool:
    """Publish the tracing settings into the environment LangChain reads.

    LangChain and the LangSmith client look at `os.environ` directly. Settings
    here come from `.env` via pydantic-settings, which populates this object and
    *not* the environment, and nothing in the app calls `load_dotenv`. So
    putting `LANGSMITH_TRACING=true` in `.env` and stopping there switches
    nothing on: the value reaches `settings.langsmith_tracing` and no library
    ever asks. This is the bridge, and it runs at import so every entry point --
    the API, the CLI, eval/ -- is covered without each having to remember.

    A variable already set in the real environment wins, so a shell export or a
    container's own configuration is never overwritten by the file. Returns
    whether tracing ended up on, which is what the log line reports.
    """
    if not settings.langsmith_tracing:
        return False
    if not settings.langsmith_api_key:
        logger.warning("tracing.langsmith_not_started", setting="LANGSMITH_API_KEY", reason="the key is empty")
        return False

    for name, value in (
        ("LANGSMITH_TRACING", "true"),
        ("LANGSMITH_ENDPOINT", settings.langsmith_endpoint),
        ("LANGSMITH_API_KEY", settings.langsmith_api_key),
        ("LANGSMITH_PROJECT", settings.langsmith_project),
    ):
        os.environ.setdefault(name, value)
    return True


def start_phoenix_tracing() -> bool:
    """Send OpenTelemetry spans to a Phoenix collector on this machine.

    A different mechanism from `configure_tracing`, not a second destination
    for the same one. LangSmith is read out of the environment by LangChain
    itself, so switching it on is a matter of publishing variables; Phoenix is
    OpenTelemetry, and something in this process has to build a tracer provider
    and patch LangChain to emit spans into it. That is what this does, and it
    runs at import for the same reason the other one does -- the API, the CLI,
    the eval harness and the scripts all get it without each remembering to ask.

    The imports are inside the function and the failure is a warning rather
    than a crash: the packages are an optional extra, and an application that
    refuses to start because its *observability* is missing has the priority
    backwards. `uv pip install -e ".[phoenix]"` installs them -- `uv pip`,
    because the project's `.venv` is built by uv and has no pip of its own.

    Nothing is started here. Phoenix itself -- the collector and its UI -- is a
    separate process that the operator runs; if it is not listening, the
    exporter drops spans in a background thread and says so, and answering
    carries on.
    """
    if not settings.phoenix_tracing:
        return False

    try:
        from openinference.instrumentation.langchain import LangChainInstrumentor
        from phoenix.otel import register
    except ImportError as error:
        logger.warning(
            "tracing.phoenix_not_started",
            reason=f"packages missing ({error})",
            fix='uv pip install -e ".[phoenix]"',
        )
        return False

    provider = register(
        endpoint=settings.phoenix_endpoint,
        project_name=settings.phoenix_project,
        # One span at a time blocks the caller on every LLM call; a batch
        # processor hands them to a background thread, which is what a server
        # answering somebody else's questionnaire needs.
        batch=True,
        # `register` prints its configuration to stdout. This process logs.
        verbose=False,
        set_global_tracer_provider=True,
    )
    LangChainInstrumentor().instrument(tracer_provider=provider)
    return True


_TRACING_ON = configure_tracing()
_PHOENIX_ON = start_phoenix_tracing()


def configure_logging() -> None:
    """Configure logging once, at process start: level, format, and what to redact."""
    configure_logs(
        settings.log_level,
        settings.log_format,
        secrets=[
            settings.groq_api_key,
            settings.langsmith_api_key,
            settings.embedding_api_key,
            settings.admin_password,
            settings.eval_data_key,
        ],
    )

    if _TRACING_ON:
        logger.warning(
            "tracing.langsmith_on",
            project=settings.langsmith_project,
            endpoint=settings.langsmith_endpoint,
            note="prompts, and the policy text in them, leave the country",
        )
    if _PHOENIX_ON:
        logger.info(
            "tracing.phoenix_on",
            project=settings.phoenix_project,
            endpoint=settings.phoenix_endpoint,
            note="traces stay on this machine and are as sensitive as the corpus",
        )
