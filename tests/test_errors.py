"""The error hierarchy's promises: one status per code, codes that stay codes."""

from __future__ import annotations

import re

import pytest

from harness.gen import error_codes
from src import errors

FRAMEWORK_CODES = {"route_not_found": 404, "method_not_allowed": 405, "validation_failed": 422, "internal_error": 500}


def test_every_class_has_its_own_code():
    classes, _ = error_codes()
    codes = [cls.code for cls in classes]
    assert len(codes) == len(set(codes)), sorted(code for code in codes if codes.count(code) > 1)


def test_a_code_always_means_the_same_status():
    """A client branches on the code; one code answering 400 here and 404 there would lie to it."""
    classes, sites = error_codes()
    status_of_class = {cls.__name__: cls.status for cls in classes}
    seen: dict[str, int] = dict(FRAMEWORK_CODES)
    for cls in classes:
        assert seen.setdefault(cls.code, cls.status) == cls.status, cls.code
    for code, name, where in sites:
        assert seen.setdefault(code, status_of_class[name]) == status_of_class[name], (code, where)


def test_codes_are_snake_case_identifiers():
    classes, sites = error_codes()
    for code in [cls.code for cls in classes] + [code for code, _, _ in sites] + list(FRAMEWORK_CODES):
        assert re.fullmatch(r"[a-z][a-z0-9_]*", code), code


def test_a_raise_site_may_name_a_more_specific_code():
    error = errors.NotFound("No run 'x'.", code="run_not_found")
    assert (error.status, error.code, error.message, str(error)) == (404, "run_not_found", "No run 'x'.", "No run 'x'.")
    assert errors.NotFound("No run.").code == "not_found", "the override must not leak into the class"


@pytest.mark.parametrize(("cls", "builtin"), [(errors.PreferenceError, ValueError), (errors.ExportError, RuntimeError)])
def test_domain_errors_keep_the_builtin_bases_callers_catch(cls, builtin):
    assert issubclass(cls, builtin) and issubclass(cls, errors.AppError)


def test_the_api_answers_every_app_error_the_same_way():
    from fastapi.testclient import TestClient

    from src.api import app

    response = TestClient(app).get("/api/runs/does-not-exist")
    assert response.status_code == 404
    assert response.json() == {"detail": "No run 'does-not-exist'.", "code": "run_not_found"}
