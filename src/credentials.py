"""Hashing and generating the secrets people type.

Two kinds of secret pass through here — a team's shared access code and an
admin's password — and both are low-entropy enough that a fast hash would be
worth attacking. So both go through scrypt, which is deliberately slow and
memory-hard, rather than the plain SHA-256 that session tokens use. A session
token is 256 random bits and has nothing to guess; a code someone can type from
memory does.

scrypt comes from `hashlib`, so this adds no dependency. The parameters are
stored alongside each hash, which is what makes them changeable later without
invalidating every existing credential.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets

# RFC 7914's interactive-login parameters: 16 MB and a few tens of milliseconds
# per verification. Slow enough to make guessing an access code expensive,
# fast enough that signing in feels immediate.
#
# Higher costs are tempting but not free here: OpenSSL refuses scrypt above a
# 32 MB working set unless `maxmem` is raised, so n = 2**16 fails outright on a
# stock build. `maxmem` is passed anyway, with headroom, so these can be raised
# later without hitting that wall — the parameters travel with each hash, so
# old credentials keep verifying.
SCRYPT_N = 2 ** 14
SCRYPT_R = 8
SCRYPT_P = 1
SCRYPT_MAXMEM = 128 * 1024 * 1024

# No I, L, O, U, 0 or 1. Someone reads this code off a screen and types it into
# another machine, or reads it down a phone; the pairs that get confused when
# that happens are simply not in the alphabet.
CODE_ALPHABET = "ABCDEFGHJKMNPQRSTVWXYZ23456789"
CODE_GROUPS = 4
CODE_GROUP_SIZE = 4


def _b64(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")


def _unb64(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


def hash_secret(secret: str) -> str:
    """Hash a code or password for storage.

    The result carries its own parameters — `scrypt$n$r$p$salt$hash` — so a
    later change to the cost can be rolled out without a migration, and old
    hashes keep verifying against the settings they were made with.
    """
    if not secret:
        raise ValueError("Refusing to hash an empty secret.")
    salt = secrets.token_bytes(16)
    derived = hashlib.scrypt(
        secret.encode("utf-8"), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=32, maxmem=SCRYPT_MAXMEM,
    )
    return f"scrypt${SCRYPT_N}${SCRYPT_R}${SCRYPT_P}${_b64(salt)}${_b64(derived)}"


def verify_secret(secret: str, stored: str) -> bool:
    """Check a typed secret against a stored hash.

    False for anything unusable — no secret given, nothing stored, a hash from
    a format this version does not know — because every one of them means the
    same thing to the caller, and telling them apart would leak which accounts
    have credentials set.
    """
    if not secret or not stored:
        return False
    try:
        scheme, n, r, p, salt, expected = stored.split("$")
        if scheme != "scrypt":
            return False
        derived = hashlib.scrypt(
            secret.encode("utf-8"),
            salt=_unb64(salt),
            n=int(n),
            r=int(r),
            p=int(p),
            dklen=len(_unb64(expected)),
            maxmem=SCRYPT_MAXMEM,
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(derived, _unb64(expected))


def generate_code() -> str:
    """A fresh access code, e.g. `K7QM-9XTP-3JHR-WNBD`.

    Sixteen characters from a thirty-character alphabet is about 78 bits, which
    is far past anything guessable — the grouping is there to make it
    transcribable, not to weaken it.
    """
    raw = "".join(
        secrets.choice(CODE_ALPHABET) for _ in range(CODE_GROUPS * CODE_GROUP_SIZE)
    )
    return "-".join(
        raw[index : index + CODE_GROUP_SIZE]
        for index in range(0, len(raw), CODE_GROUP_SIZE)
    )


def normalise_code(code: str) -> str:
    """What a person typed, reduced to what was meant.

    Case, spaces and dashes all vary between someone reading a code aloud and
    someone pasting it, and none of them carry meaning. Rejecting a correct
    code because it arrived lower-case would be a support call, not security.
    """
    return "".join(code.split()).replace("-", "").replace("–", "").upper()
