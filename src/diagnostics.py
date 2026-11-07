"""Read-only diagnostics: can this installation run, and what happened to a request.

    python -m src.cli doctor [--network] [--json]
    python -m src.cli inspect request <request-id>

Nothing here writes. No directory is created, the database is opened
read-only, and a network check is one GET with a short timeout, made only when
asked for. A secret is reported as set or not set, never shown. Each failed
check carries a FIX line saying what to do about it.
"""

from __future__ import annotations

import os
import sqlite3
import sys
from collections.abc import Iterator
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from src import config
from src.config import settings

OK, WARN, FAIL = "ok", "warn", "fail"
_TIMEOUT = 5.0


@dataclass(frozen=True)
class Check:
    """One finding: what was looked at, what was found, and what to do if it is wrong."""

    name: str
    status: str
    detail: str
    fix: str = ""

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


def _size(path: Path) -> int:
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def _mb(size: int) -> str:
    return f"{size / 1_048_576:.1f} MB"


def interpreter() -> Check:
    """Whether this is the project's own .venv; another interpreter imports the wrong packages."""
    venv = config.project_venv()
    inside = Path(sys.prefix).resolve() == venv.resolve()
    if inside:
        return Check("python.interpreter", OK, sys.executable)
    return Check(
        "python.interpreter",
        WARN,
        f"{sys.executable} is not the project's .venv ({venv})",
        "run through the project's interpreter: `uv run python -m ...` (D-008)",
    )


def env_file() -> Check:
    """Which env file the settings came from, and whether it exists."""
    path = config.env_file_in_use()
    if path is None:
        return Check("config.env_file", WARN, "no .env is read (ASSESSMENT_ANSWER_ENV_FILE is empty)")
    if not path.exists():
        return Check(
            "config.env_file", FAIL, f"{path} does not exist", "cp .env.example .env, then set GROQ_API_KEY in it"
        )
    return Check("config.env_file", OK, str(path))


def secrets() -> list[Check]:
    """Whether the keys the system needs are set. Never their values."""
    groq = bool(settings.groq_api_key)
    return [
        Check(
            "config.groq_api_key",
            OK if groq else FAIL,
            "set" if groq else "not set: nothing can be answered",
            "" if groq else "set GROQ_API_KEY in .env",
        ),
        Check(
            "config.eval_data_key",
            OK if settings.eval_data_key else WARN,
            "set" if settings.eval_data_key else "not set: the sealed eval data cannot be unlocked",
        ),
    ]


def storage() -> list[Check]:
    """Each storage path: present, writable, and how much it holds."""
    out: list[Check] = []
    for field in ("chroma_dir", "upload_dir", "filled_dir", "extracted_text_dir", "db_path", "organisation_path"):
        path: Path = getattr(settings, field)
        name = f"storage.{field}"
        if not path.exists():
            out.append(Check(name, WARN, f"{path} does not exist yet; the server creates it at startup"))
        elif not os.access(path if path.is_dir() else path.parent, os.W_OK):
            out.append(Check(name, FAIL, f"{path} is not writable", f"give the server's user write access to {path}"))
        else:
            out.append(Check(name, OK, f"{path} ({_mb(_size(path))})"))
    return out


def schema_version() -> int | None:
    """The database's schema version, read without opening it for writing; None when there is none yet."""
    path = settings.db_path
    if not path.exists():
        return None
    conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
    try:
        return int(conn.execute("PRAGMA user_version").fetchone()[0])
    finally:
        conn.close()


def database() -> Check:
    """The database's schema version and what it holds, read without opening it for writing."""
    path = settings.db_path
    if not path.exists():
        return Check("database", WARN, f"{path} does not exist yet; it is created on first start")
    try:
        conn = sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True)
        try:
            version = conn.execute("PRAGMA user_version").fetchone()[0]
            counts = {
                table: conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for table in ("teams", "users", "form_batches", "runs")
            }
        finally:
            conn.close()
    except sqlite3.Error as error:
        return Check("database", FAIL, f"{path}: {error}", "restore the file from a backup, or move it aside")
    summary = ", ".join(f"{count} {table}" for table, count in counts.items())
    return Check("database", OK, f"schema version {version}; {summary}")


def _probe(name: str, url: str, client: httpx.Client, headers: dict[str, str] | None = None) -> Check:
    try:
        response = client.get(url, headers=headers or {}, timeout=_TIMEOUT)
    except httpx.HTTPError as error:
        return Check(name, FAIL, f"{url}: {type(error).__name__}", f"check that {url} is reachable from this host")
    if response.status_code in (401, 403):
        return Check(name, FAIL, f"{url}: {response.status_code}", "the key in .env was refused; check it")
    if response.status_code >= 500:
        return Check(name, FAIL, f"{url}: {response.status_code}", "the service is up but failing; see its logs")
    return Check(name, OK, f"{url}: {response.status_code}")


def network(client: httpx.Client | None = None) -> list[Check]:
    """One GET to each configured service. Sends the configured keys, as the app itself does."""
    own = client is None
    client = client or httpx.Client()
    try:
        groq = (settings.groq_base_url or "https://api.groq.com").rstrip("/")
        out = [
            _probe(
                "network.groq",
                f"{groq}/openai/v1/models",
                client,
                {"Authorization": f"Bearer {settings.groq_api_key}"},
            ),
            _probe(
                "network.embeddings",
                f"{settings.embedding_base_url.rstrip('/')}/models",
                client,
                {"Authorization": f"Bearer {settings.embedding_api_key}"},
            ),
        ]
        if settings.docling_enabled:
            out.append(_probe("network.docling", f"{(settings.docling_base_url or '').rstrip('/')}/health", client))
        else:
            out.append(Check("network.docling", WARN, "DOCLING_BASE_URL is empty: local loaders only, no OCR"))
        return out
    finally:
        if own:
            client.close()


def doctor(with_network: bool = False, client: httpx.Client | None = None) -> list[Check]:
    """Every check, in the order a person would fix them."""
    checks = [interpreter(), env_file(), *secrets(), *storage(), database()]
    if with_network:
        checks += network(client)
    return checks


def request_lines(request_id: str, log: Path | None = None) -> Iterator[str]:
    """The lines of the server log that belong to one request, in either log format."""
    path = log or settings.server_log_path
    text_form, json_form = f"request_id={request_id}", f'"request_id": "{request_id}"'
    with path.open(encoding="utf-8", errors="replace") as lines:
        for line in lines:
            if text_form in line or json_form in line:
                yield line.rstrip("\n")
