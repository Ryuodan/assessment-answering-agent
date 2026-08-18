"""Application settings — the single source of truth for configuration.

Everything tunable lives here and is read from the environment (or `.env`).
Modules import the module-level `settings` singleton rather than reading
`os.environ` themselves, so there is exactly one place to look when a value
looks wrong.
"""

from __future__ import annotations

import logging
from pathlib import Path

from pydantic import Field
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

    # --- Embeddings (BGE-M3 behind an OpenAI-compatible endpoint) ----------
    embedding_base_url: str = "https://ds.t2.sa/text_embed/v1"
    embedding_model: str = "bge-m3"
    embedding_api_key: str = "unused"

    # --- Document conversion (Docling) -------------------------------------
    # Docling runs as a container on the testing server and converts PDF/DOCX
    # to Markdown. Host root only — the endpoint paths are appended. Set to ""
    # to skip it entirely and use the local pdfplumber / python-docx loaders.
    docling_base_url: str = "http://localhost:8092"
    # Conversion of a long scanned PDF is minutes, not seconds.
    docling_timeout: float = Field(default=180.0, gt=0)
    docling_do_ocr: bool = False
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
    top_k_guidelines: int = 5
    top_k_prior_answers: int = 5
    max_answer_attempts: int = Field(default=2, ge=1, le=5)
    max_concurrent_questions: int = Field(default=4, ge=1, le=32)
    review_confidence_threshold: float = Field(default=0.6, ge=0.0, le=1.0)

    chunk_size: int = 1800
    chunk_overlap: int = 150          # retained for the prose fallback only
    max_expanded_chars: int = 6000    # cap on parent-unit expansion per hit
    max_evidence_chunks: int = 14     # cap on accumulated evidence per question
    extraction_window: int = 8000

    log_level: str = "INFO"

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
