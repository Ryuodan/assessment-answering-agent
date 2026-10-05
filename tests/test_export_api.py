"""The two document export endpoints, exercised through the app.

The unit tests cover what goes on the page. These cover the response around it,
which is where an Arabic file name broke a download that rendered perfectly.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from src.api import app, attachment_headers

ARABIC_NAME = "تقييم الأمن السيبراني.pdf"


def _payload(source_name: str = "vendor review.pdf", needs_review: bool = False) -> dict:
    return {
        "run_id": "r",
        "source_name": source_name,
        "language": "en",
        "questions_found": 1,
        "answers": [
            {
                "question": {
                    "id": "1",
                    "text": "Do you encrypt data at rest?",
                    "question_type": "free_text",
                    "options": [],
                    "language": "en",
                },
                "answer": "Yes, AES-256 is applied.",
                "rationale": "From the cryptography policy.",
                "confidence": 0.9,
                "needs_review": needs_review,
                "review_reasons": [],
                "confidence_reason": "",
                "evidence": [],
                "attempts": 1,
                "citations": ["T2 - Cryptography Policy.pdf §3.5.1"],
            }
        ],
    }


# --- the header ------------------------------------------------------------


def test_an_ascii_name_is_offered_directly():
    header = attachment_headers("report.pdf")["Content-Disposition"]
    assert 'filename="report.pdf"' in header


def test_a_non_ascii_name_survives_as_the_encoded_parameter():
    header = attachment_headers("تقييم.pdf")["Content-Disposition"]
    assert "filename*=UTF-8''" in header
    assert "%D8%AA" in header


def test_the_header_is_always_encodable_as_a_header():
    """HTTP header values are latin-1; anything else raises inside Starlette."""
    for name in ("تقييم الأمن السيبراني.answers.pdf", "évaluation.docx", "报告.pdf"):
        attachment_headers(name)["Content-Disposition"].encode("latin-1")


def test_a_name_with_no_ascii_left_still_has_a_usable_fallback():
    header = attachment_headers("تقييم.answers.pdf")["Content-Disposition"]
    assert 'filename="assessment.answers.pdf"' in header


# --- the endpoints ---------------------------------------------------------


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_an_export_of_an_arabic_assessment_succeeds(fmt):
    """It returned 500 for every Arabic file name, which is most of the corpus."""
    with TestClient(app) as client:
        response = client.post(f"/api/assessments/export/{fmt}", json=_payload(ARABIC_NAME))

    assert response.status_code == 200
    assert len(response.content) > 1000
    assert "filename*=UTF-8''" in response.headers["content-disposition"]


@pytest.mark.parametrize(
    ("fmt", "media_type"),
    [
        ("pdf", "application/pdf"),
        ("docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    ],
)
def test_each_format_is_served_with_its_own_media_type(fmt, media_type):
    with TestClient(app) as client:
        response = client.post(f"/api/assessments/export/{fmt}", json=_payload())

    assert response.status_code == 200
    assert response.headers["content-type"] == media_type


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_exporting_nothing_is_refused_with_an_explanation(fmt):
    with TestClient(app) as client:
        response = client.post(f"/api/assessments/export/{fmt}", json=_payload(needs_review=True))

    assert response.status_code == 422
    assert "flagged for review" in response.json()["detail"]


@pytest.mark.parametrize("fmt", ["pdf", "docx"])
def test_the_flagged_option_is_honoured_by_both_formats(fmt):
    with TestClient(app) as client:
        response = client.post(f"/api/assessments/export/{fmt}?include_flagged=true", json=_payload(needs_review=True))

    assert response.status_code == 200
