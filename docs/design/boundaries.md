# Boundaries

Every place data enters the application from outside, what it is parsed into,
and where a gap remains. Written for plan 007 (2026-10-06) from a survey of the
code; the counts were measured then. The rule this serves: data becomes a typed,
validated model where it arrives, so a malformed value fails there, naming
itself, rather than somewhere inside. ARCH-JSON stops new code from decoding raw
JSON outside three named exemptions.

| Boundary | Where it arrives | Parsed into | Gaps |
|---|---|---|---|
| HTTP request bodies | `src/api.py`, `src/routes/` | 33 pydantic request models, covering the 35 JSON bodies of the 77 operations; FastAPI answers a mismatch with 422 `validation_failed` | none |
| HTTP query, path and form parameters | `src/api.py` | typed by FastAPI from the signatures | three are checked by hand (`mode` on search, `authority` on upload, the upload's suffix), kept so their errors keep their own codes (`search_mode_unknown`, `authority_invalid`, `document_type_unsupported`), which the error snapshots pin |
| Uploaded files (5 multipart routes) | `src/service.py`, `src/documents.py`, `src/forms/` | questionnaires into `DetectedForm`; policies into text and `Chunk`s; an unreadable file is `FormatError` or `UnsupportedDocumentError` (422) | the file libraries themselves (pdfplumber, python-docx, the stdlib zip reader) are trusted to parse; hostile files are tested in `tests/test_forms_hostile.py` |
| Configuration | `src/config.py` | `Settings` (pydantic-settings): types, ranges, patterns, and `Literal` vocabularies for `DETECTION_STRATEGY`, `GROQ_REASONING_FORMAT`, `LOG_LEVEL`, `DOCLING_IMAGE_EXPORT_MODE`; an invalid value stops startup naming the setting | free-text settings (model names, URLs, project names) are not checked beyond being strings |
| The organisation profile file | `src/organisation.py` | `Organisation` (pydantic), read with `model_validate_json`; a malformed file falls back to the built-in profile and logs `organisation.profile_unreadable` | none |
| Docling's responses | `src/docling_client.py` | `_Task` and `_Result` models; a reply of another shape is a `DoclingError`, so the local fallback applies (before plan 007 it could be an `AttributeError` that escaped it) | none |
| Model output | `src/llm.py` `structured_llm`, used in `graph/nodes.py`, `extraction.py`, `relevance.py`, `answer_memory.py`, `forms/llm_layout.py` | pydantic schemas (`DraftedAnswer`, `AnswerReview`, ...); a failed tool call is recovered by decoding the provider's error and validating it against the same schema | the query planner and the rewording step read plain text, by design: their output is a list of lines or an answer, checked by their own tests (`tests/test_graph.py`, `tests/test_rewrite.py`) |
| The embedding host | `src/embeddings.py` | LangChain's `OpenAIEmbeddings` client, which returns float vectors | not validated by this code |
| Records read back from SQLite | `src/batches.py`, `src/runs.py`, `src/store.py` | questionnaires and answers with `model_validate_json`; other columns decoded by `store`, an exemption from ARCH-JSON because the application wrote them | none |
| Conversations read back | `src/conversations.py` | LangChain messages, rebuilt with `messages_from_dict`; an unreadable history starts the conversation again | an exemption from ARCH-JSON: LangChain's own format |
| Sealed evaluation data | `eval/vault.py` | decrypted, then checked against the manifest's SHA-256 before anything is written | outside `src/`, so not under ARCH-JSON |
