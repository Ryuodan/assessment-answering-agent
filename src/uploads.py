"""Uploaded files on disk: which folders hold them, how one is named, and how they go.

A knowledge-base file lives in its team's folder, or in its product's (plan
027); a questionnaire in the folder of the person who uploaded it. This module
is the part of that every caller shares -- the service saving an upload, a
product taking its files with it when it is deleted, the storage limit removing
old work -- so none of them reaches into another for it.

The text read out of a file is cached beside the uploads, keyed by the file's
path, and is as confidential as the file: whatever removes a file removes its
cached text too.
"""

from __future__ import annotations

import hashlib
import shutil
from collections.abc import Iterable
from pathlib import Path

from src.config import settings
from src.documents import SUPPORTED_SUFFIXES
from src.logs import get_logger

logger = get_logger(__name__)

# Bumped whenever the extraction code changes in a way that alters its output,
# so cached text from an older, worse extractor is not silently reused.
EXTRACTION_VERSION = "7"


def document_files(directory: Path) -> list[Path]:
    """The documents in one folder that the app can read, by name. None when there is no folder."""
    if not directory.is_dir():
        return []
    return sorted(path for path in directory.iterdir() if path.is_file() and path.suffix.lower() in SUPPORTED_SUFFIXES)


def extracted_text_cache_path(path: Path) -> Path:
    """Where the text read out of `path` is cached, under the converter settings in force now."""
    cache_input = "\0".join(
        (
            EXTRACTION_VERSION,
            str(path.resolve()),
            settings.docling_base_url,
            str(settings.docling_do_ocr),
            str(settings.docling_ocr_auto),
            settings.docling_image_export_mode,
            str(settings.docling_heading_hierarchy),
            # Part of the key, not just the version: a text extracted without
            # page markers and one extracted with them are different documents
            # as far as chunk metadata is concerned.
            settings.docling_page_break_placeholder,
        )
    )
    cache_key = hashlib.sha256(cache_input.encode("utf-8")).hexdigest()[:24]
    return settings.extracted_text_dir / f"{cache_key}.txt"


def knowledge_folders(team_id: str | None) -> list[Path]:
    """Every folder a team's knowledge-base files are in: the team's own, then each product's."""
    root = settings.products_upload_root(team_id)
    products = sorted(path for path in root.iterdir() if path.is_dir()) if root.is_dir() else []
    return [settings.team_upload_dir(team_id), *products]


def save(directory: Path, name: str, content: bytes, others: Iterable[Path] = ()) -> Path:
    """Write `content` into `directory` as `name`, numbered when the name is taken by other content.

    Taken means a file of that name with different bytes, here or in any of
    `others`. Identical content keeps the one name, in each folder it is saved to.
    """
    directory.mkdir(parents=True, exist_ok=True)
    folders = list(dict.fromkeys([directory, *others]))
    destination = directory / name
    stem, suffix = destination.stem, destination.suffix
    attempt = 1
    while any(_differs(folder / destination.name, content) for folder in folders):
        attempt += 1
        destination = directory / f"{stem} ({attempt}){suffix}"
    destination.write_bytes(content)
    return destination


def _differs(path: Path, content: bytes) -> bool:
    return path.exists() and path.read_bytes() != content


def holds(path: Path, content: bytes) -> bool:
    """Whether the file at `path` is still there and holds exactly `content`.

    The size first, so a person's other questionnaires are not read whole to
    learn that they differ. A file the storage limit removed holds nothing.
    """
    try:
        return path.is_file() and path.stat().st_size == len(content) and path.read_bytes() == content
    except OSError:
        return False


def remove(paths: Iterable[Path], folder: Path | None = None) -> list[str]:
    """Delete files and the text read out of each, then `folder` with whatever is left in it.

    Returns the names of the files still there afterwards. Never raises: it is
    called after the decision to delete has been committed, when a file that
    cannot go (open in another program, say) is something to report, not a
    reason to stop removing the rest.
    """
    left: list[str] = []
    for path in paths:
        try:
            extracted_text_cache_path(path).unlink(missing_ok=True)
            path.unlink(missing_ok=True)
        except OSError:
            logger.warning("uploads.remove_failed", file=str(path), exc_info=True)
            left.append(path.name)
    if folder is not None and folder.exists():
        try:
            shutil.rmtree(folder)
        except OSError:
            logger.warning("uploads.remove_failed", folder=str(folder), exc_info=True)
            left += [name for name in _still_in(folder) if name not in left]
    return left


def _still_in(folder: Path) -> list[str]:
    try:
        return [path.name for path in folder.rglob("*") if path.is_file()] or [folder.name]
    except OSError:
        return [folder.name]
