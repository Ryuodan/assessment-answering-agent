"""Every error the application raises on purpose, and what it means to a client.

One hierarchy (plan 004, D-013). Each error carries:

* `message` -- written to be shown to a person. Never the text of another
  exception: that is logged, and the message says what happened in words.
* `code` -- stable and machine-readable: a client or a test branches on it, and
  it does not change when the wording does. A class has a default; a raise site
  may name a more specific one (`NotFound("No run 'x'.", code="run_not_found")`).
* `status` -- the HTTP status the API answers with. Only `src/api.py` reads it.

    AppError                 500  internal_error
    +-- Invalid              400  invalid_request     the request cannot be carried out as asked
    +-- SignInRequired       401  sign_in_required
    +-- Forbidden            403  forbidden
    +-- NotFound             404  not_found           absent, or somebody else's (which reads the same)
    +-- Conflict             409  conflict            would clash with something that exists: a taken name
    +-- UnsupportedFile      415  unsupported_file
    +-- Unprocessable        422  unprocessable       understood, but cannot be used: an unreadable file
    +-- Unavailable          503  unavailable         something this depends on is not there

Domain errors derive from these (`tools.ToolError`, `forms.FormatError`, ...).
`docs/generated/errors.md` lists them all with their codes; ARCH-ERROR keeps new
error classes inside this hierarchy.
"""

from __future__ import annotations


class AppError(Exception):
    """An error the application raised on purpose, with a message safe to show."""

    code: str = "internal_error"
    status: int = 500

    def __init__(self, message: str, *, code: str | None = None) -> None:
        super().__init__(message)
        self.message = message
        if code is not None:
            self.code = code


class Invalid(AppError):
    """The request cannot be carried out as asked."""

    code = "invalid_request"
    status = 400


class SignInRequired(AppError):
    """Nobody is signed in, and this needs somebody."""

    code = "sign_in_required"
    status = 401


class Forbidden(AppError):
    """Signed in, but not allowed to do this."""

    code = "forbidden"
    status = 403


class NotFound(AppError):
    """Absent -- or belonging to somebody else, which is deliberately the same answer."""

    code = "not_found"
    status = 404


class Conflict(AppError):
    """The request would clash with something that already exists, such as a name in use."""

    code = "conflict"
    status = 409


class UnsupportedFile(AppError):
    """A file of a type this cannot take."""

    code = "unsupported_file"
    status = 415


class Unprocessable(AppError):
    """Understood, but cannot be used: an unreadable file, nothing to export."""

    code = "unprocessable"
    status = 422


class Unavailable(AppError):
    """Something this depends on -- a model, a converter -- is not there."""

    code = "unavailable"
    status = 503


# --- Domain errors -----------------------------------------------------------
# Defined here so the whole hierarchy is in one file; each module that raises
# one imports it back, so `tools.ToolError` and the like still resolve.


# Raised by src.documents.
class UnsupportedDocumentError(Unprocessable, ValueError):
    """Raised for a file type the app cannot read."""

    code = "document_unreadable"


# Raised by src.export_pdf.
class ExportError(Unavailable, RuntimeError):
    """The PDF could not be produced."""

    code = "export_unavailable"


# Raised by src.forms.xlsx_package.
class FormatError(Unprocessable):
    """The file is not a workbook this can read. The message is safe to show."""

    code = "questionnaire_unreadable"


# Raised by src.forms.
class UnsupportedForm(Invalid):
    """The file is not a questionnaire format this can read."""

    code = "questionnaire_type_unsupported"


# Raised by src.identity.
class AccessDenied(Forbidden):
    """Sign-in was refused. The message is safe to show the person."""

    code = "access_denied"


# Raised by src.identity.
class NotAllowed(Invalid):
    """An administrative action the caller may not perform."""

    code = "not_allowed"


# Raised by src.products.
class ProductNotFound(NotFound):
    """No such product in this team."""

    code = "product_not_found"


# Raised by src.products.
class ProductNameTaken(Conflict):
    """The team already has a product of that name, whatever its case."""

    code = "product_name_taken"


# Raised by src.preferences.
class PreferenceError(Invalid, ValueError):
    """A preference or skill that cannot be saved as given. Safe to show."""

    code = "preference_invalid"


# Raised by src.service.
class NotADocument(Invalid, ValueError):
    """A name that is not a policy document, asked to be removed as one. Safe to show."""

    code = "not_a_document"


# Raised by src.tools.
class ToolError(Invalid):
    """An operation could not be performed. The message is safe to show."""

    code = "operation_refused"


# Raised by src.tools, for a questionnaire that is absent or somebody else's.
class QuestionnaireNotFound(NotFound, ToolError):
    """No such questionnaire for this person: absent, or a colleague's (TD-026).

    A NotFound, so the API answers 404 like every other missing thing; also a
    ToolError, so the chat assistant still reports it to the model as a refusal.
    """

    code = "questionnaire_not_found"
