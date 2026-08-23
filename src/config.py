"""Application settings — the single source of truth for configuration.

Everything tunable lives here and is read from the environment (or `.env`).
Modules import the module-level `settings` singleton rather than reading
`os.environ` themselves, so there is exactly one place to look when a value
looks wrong.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

PROJECT_ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    """Runtime configuration, populated from environment variables / `.env`."""

    model_config = SettingsConfigDict(
        env_file=PROJECT_ROOT / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- LLM (Groq) --------------------------------------------------------
    groq_api_key: str = ""
    groq_chat_model: str = "minimaxai/minimax-m2.7"
    # ME-Central-1 regional endpoint. Host root only — the groq client appends
    # `/openai/v1` to it. Set to "" to fall back to the global api.groq.com.
    groq_base_url: str | None = "https://api.me-central-1.groqcloud.com"
    llm_temperature: float = 0.0
    # Grading model for eval/. Deliberately not the drafting model: a system
    # should not mark its own homework.
    eval_judge_model: str = "openai/gpt-oss-120b"

    # --- Embeddings (BGE-M3 behind an OpenAI-compatible endpoint) ----------
    embedding_base_url: str = "https://ds.t2.sa/text_embed/v1"
    embedding_model: str = "bge-m3"
    embedding_api_key: str = "unused"

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
    docling_image_export_mode: str = "placeholder"
    # When Docling is unreachable, fall back to the local loaders rather than
    # failing the upload. Set false to make a broken Docling loud instead.
    docling_fallback_local: bool = True

    @property
    def docling_enabled(self) -> bool:
        return bool(self.docling_base_url.strip())

    # --- Storage -----------------------------------------------------------
    chroma_dir: Path = PROJECT_ROOT / "chroma_db"
    collection_name: str = "assessment_knowledge"
    upload_dir: Path = PROJECT_ROOT / "data" / "uploads"
    extracted_text_dir: Path = PROJECT_ROOT / "data" / "extracted"

    # --- Retrieval + answering --------------------------------------------
    top_k_guidelines: int = 8
    top_k_prior_answers: int = 5

    # Split a multi-part question into one search per part before retrieving.
    # Costs one extra LLM call per question; turn it off to retrieve on the
    # question's own wording alone.
    query_expansion: bool = True
    max_search_queries: int = Field(default=4, ge=1, le=8)

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
    max_concurrent_questions: int = Field(default=4, ge=1, le=32)
    review_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    chunk_size: int = 1800
    chunk_overlap: int = 150          # retained for the prose fallback only
    max_expanded_chars: int = 12000    # cap on parent-unit expansion per hit
    max_evidence_chunks: int = 14     # cap on accumulated evidence per question
    # How many of those chunks may be previous answers. They sort first, so
    # without a ceiling they take the whole prompt and the policies that
    # actually answer the question never reach the drafter — see
    # `select_evidence`. Raise it for a corpus where the previous answers are
    # the authority; lower it to make the drafter lean on the guidelines.
    max_prior_answer_chunks: int = Field(default=4, ge=0)
    extraction_window: int = 8000

    incomplete_list_confidence_cap: float = Field(default=0.5, ge=0.0, le=1.0)

    log_level: str = "INFO"

    @field_validator("chroma_dir", "upload_dir", "extracted_text_dir")
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

    def ensure_directories(self) -> None:
        """Create the directories the app writes to. Safe to call repeatedly."""
        self.chroma_dir.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)
        self.extracted_text_dir.mkdir(parents=True, exist_ok=True)


settings = Settings()


def configure_logging() -> None:
    """Apply the configured log level once, at process start."""
    logging.basicConfig(
        level=getattr(logging, settings.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    # Chroma and httpx are chatty at INFO; they only matter when debugging.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("chromadb").setLevel(logging.WARNING)
