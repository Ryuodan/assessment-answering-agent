"""Hashing the secrets people type.

The suite runs scrypt at a fraction of its real cost so it is not two minutes
long, which means the production parameters need asserting somewhere. Here.
"""

from __future__ import annotations

import pytest

from src import credentials


# --- the real cost ---------------------------------------------------------


def test_the_shipped_parameters_are_the_interactive_ones():
    """RFC 7914's interactive figures: 16 MB, a few tens of milliseconds.

    Asserted because `conftest` lowers the cost for every other test, so a
    change to the default would otherwise pass the whole suite unnoticed.
    """
    import inspect

    source = inspect.getsource(credentials)
    assert "SCRYPT_N = 2 ** 14" in source
    assert "SCRYPT_R = 8" in source
    assert 128 * (2 ** 14) * 8 < credentials.SCRYPT_MAXMEM, (
        "maxmem must leave room for the parameters, or OpenSSL refuses outright"
    )


# --- round trip ------------------------------------------------------------


def test_a_secret_verifies_against_its_own_hash():
    stored = credentials.hash_secret("a-shared-access-code")
    assert credentials.verify_secret("a-shared-access-code", stored)


def test_the_wrong_secret_does_not():
    stored = credentials.hash_secret("a-shared-access-code")
    assert not credentials.verify_secret("a-shared-access-cod", stored)


def test_the_same_secret_hashes_differently_each_time():
    """Salted, so two teams choosing the same code do not look alike."""
    first = credentials.hash_secret("same-code")
    second = credentials.hash_secret("same-code")
    assert first != second
    assert credentials.verify_secret("same-code", first)
    assert credentials.verify_secret("same-code", second)


def test_the_plaintext_never_appears_in_the_hash():
    assert "hunter2" not in credentials.hash_secret("hunter2")


def test_arabic_secrets_work():
    stored = credentials.hash_secret("رمز-الدخول")
    assert credentials.verify_secret("رمز-الدخول", stored)


def test_the_hash_carries_its_parameters():
    scheme, n, r, p, salt, digest = credentials.hash_secret("x").split("$")
    assert scheme == "scrypt"
    assert (int(n), int(r), int(p)) == (credentials.SCRYPT_N, credentials.SCRYPT_R, credentials.SCRYPT_P)
    assert salt and digest


def test_a_hash_made_at_another_cost_still_verifies(monkeypatch):
    """What makes raising the cost later safe."""
    monkeypatch.setattr(credentials, "SCRYPT_N", 2 ** 9)
    stored = credentials.hash_secret("a-shared-access-code")
    monkeypatch.setattr(credentials, "SCRYPT_N", 2 ** 10)
    assert credentials.verify_secret("a-shared-access-code", stored)


# --- refusals --------------------------------------------------------------


def test_hashing_nothing_is_refused():
    """An empty hash would otherwise become a credential that matches nothing —
    or, worse, one that a bug could match everything against."""
    with pytest.raises(ValueError, match="empty"):
        credentials.hash_secret("")


@pytest.mark.parametrize(
    "secret, stored",
    [
        ("", "scrypt$256$8$1$abc$def"),
        ("x", ""),
        ("x", "not-a-hash"),
        ("x", "bcrypt$256$8$1$abc$def"),
        ("x", "scrypt$abc$8$1$abc$def"),
        ("x", "scrypt$256$8$1"),
    ],
)
def test_anything_unusable_verifies_as_false(secret, stored):
    """Never raises: a malformed row is a failed sign-in, not a 500."""
    assert credentials.verify_secret(secret, stored) is False


# --- generated codes -------------------------------------------------------


def test_a_generated_code_has_the_advertised_shape():
    code = credentials.generate_code()
    groups = code.split("-")
    assert len(groups) == credentials.CODE_GROUPS
    assert all(len(group) == credentials.CODE_GROUP_SIZE for group in groups)


def test_generated_codes_avoid_the_characters_that_get_misread():
    """Someone reads this down a phone. I/1, L/1, O/0 and U/V are not in it."""
    for _ in range(50):
        assert not set(credentials.generate_code()) & set("ILOU01")


def test_generated_codes_do_not_repeat():
    assert len({credentials.generate_code() for _ in range(200)}) == 200


@pytest.mark.parametrize(
    "typed",
    ["ABCD-EFGH", "abcd-efgh", "ABCDEFGH", "abcd efgh", "  ABCD-EFGH  ", "ABCD–EFGH"],
)
def test_normalising_accepts_how_a_person_types_a_code(typed):
    assert credentials.normalise_code(typed) == "ABCDEFGH"


def test_normalising_does_not_merge_distinct_codes():
    assert credentials.normalise_code("ABCD") != credentials.normalise_code("ABCE")
