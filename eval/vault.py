"""Sealed evaluation data: encrypted in git, plaintext only where the key is.

    uv run poe eval-status            # which files are sealed, unlocked, in step
    uv run poe eval-unlock            # decrypt into eval/ (needs EVAL_DATA_KEY in .env)
    uv run poe eval-seal              # re-encrypt what changed, after editing a plaintext
    uv run python -m eval.vault keygen  # create the first key and write it into .env

`eval/house_set.json` and `eval/answer_memory.json` hold named customers'
questions and the team's real answers (D-005). Git holds only
`eval/sealed/<name>.enc`: AES-256-GCM with a random nonce, the file name bound
in as associated data so two sealed files cannot be swapped. The plaintext
paths are gitignored. `eval/sealed/manifest.json` records the SHA-256 of each
plaintext, so `uv run poe arch` (ARCH-SEALED) can tell a stale seal without the
key, and sealing an unchanged file is a no-op rather than a new ciphertext.

The key is 32 random bytes, URL-safe base64, in `.env` as EVAL_DATA_KEY. It is
never printed: not by keygen, not in an error. Losing it loses the sealed data.
"""

from __future__ import annotations

import argparse
import base64
import binascii
import hashlib
import json
import secrets
import sys
from dataclasses import dataclass
from pathlib import Path

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

EVAL_DIR = Path(__file__).resolve().parent
SEALED_DIR = EVAL_DIR / "sealed"
NAMES = ("house_set.json", "answer_memory.json")
MANIFEST = "manifest.json"
MAGIC = b"AASEAL1\n"
NONCE_BYTES = 12
KEY_SETTING = "EVAL_DATA_KEY"

_NO_KEY_FIX = (
    f"add {KEY_SETTING}=<key> to .env (ask whoever holds it); to create the very first key, "
    "run `uv run python -m eval.vault keygen`"
)


class VaultError(Exception):
    """A failure with what to do about it. Never carries the key."""

    def __init__(self, message: str, fix: str):
        super().__init__(message)
        self.message = message
        self.fix = fix

    def __str__(self) -> str:
        return f"{self.message}\n  FIX: {self.fix}"


def new_key() -> str:
    return base64.urlsafe_b64encode(secrets.token_bytes(32)).decode("ascii")


def key_bytes(key: str) -> bytes:
    """The raw key, or a VaultError that does not repeat what it was given."""
    if not key.strip():
        raise VaultError(f"{KEY_SETTING} is not set", _NO_KEY_FIX)
    try:
        raw = base64.urlsafe_b64decode(key.strip().encode("ascii"))
    except (binascii.Error, UnicodeEncodeError, ValueError):
        raw = b""
    if len(raw) != 32:
        raise VaultError(
            f"{KEY_SETTING} is not a key this vault can use (expected 32 bytes of URL-safe base64)",
            f"copy the key again, whole, into .env as {KEY_SETTING}=...; it is 44 characters long",
        )
    return raw


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True)
class Vault:
    plain_dir: Path = EVAL_DIR
    sealed_dir: Path = SEALED_DIR
    names: tuple[str, ...] = NAMES

    # --- the manifest ------------------------------------------------------

    def manifest(self) -> dict[str, str]:
        path = self.sealed_dir / MANIFEST
        if not path.exists():
            return {}
        recorded: dict[str, str] = json.loads(path.read_text(encoding="utf-8"))["sha256"]
        return recorded

    def _write_manifest(self, hashes: dict[str, str]) -> None:
        document = {
            "about": "SHA-256 of each plaintext sealed in this folder; see eval/vault.py. Do not edit by hand.",
            "sha256": dict(sorted(hashes.items())),
        }
        (self.sealed_dir / MANIFEST).write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8", newline="\n")

    def sealed_path(self, name: str) -> Path:
        return self.sealed_dir / f"{name}.enc"

    # --- crypto ------------------------------------------------------------

    def _decrypt(self, name: str, key: bytes) -> bytes:
        path = self.sealed_path(name)
        if not path.exists():
            raise VaultError(
                f"{path.name} is missing from {self.sealed_dir.name}/",
                "restore it with `git checkout -- eval/sealed`, or seal the plaintext again with `uv run poe eval-seal`",
            )
        blob = path.read_bytes()
        if not blob.startswith(MAGIC) or len(blob) < len(MAGIC) + NONCE_BYTES + 16:
            raise VaultError(f"{path.name} is not a sealed file", "restore it with `git checkout -- eval/sealed`")
        nonce = blob[len(MAGIC) : len(MAGIC) + NONCE_BYTES]
        try:
            return AESGCM(key).decrypt(nonce, blob[len(MAGIC) + NONCE_BYTES :], name.encode("utf-8"))
        except InvalidTag:
            raise VaultError(
                f"could not decrypt {path.name}: the key is not the one it was sealed with, or the file was altered",
                f"check {KEY_SETTING} in .env against the key the team uses; if the file was altered, restore it "
                "with `git checkout -- eval/sealed`",
            ) from None

    def _encrypt(self, name: str, plaintext: bytes, key: bytes) -> bytes:
        nonce = secrets.token_bytes(NONCE_BYTES)
        return MAGIC + nonce + AESGCM(key).encrypt(nonce, plaintext, name.encode("utf-8"))

    # --- the operations ----------------------------------------------------

    def seal(self, key: str, *, force: bool = False) -> list[str]:
        """Encrypt each plaintext that changed. `force` re-encrypts all (a new key)."""
        raw = key_bytes(key)
        hashes = self.manifest()
        if force:
            missing = [name for name in self.names if not (self.plain_dir / name).exists()]
            if missing:
                raise VaultError(
                    f"--force re-encrypts everything, but {', '.join(missing)} has no plaintext here",
                    "unlock with the old key first (`uv run poe eval-unlock`), then seal with --force",
                )
        else:
            # One key for the whole folder: sealing a changed file under a key the
            # others were not sealed with would leave the folder half unreadable.
            for name in self.names:
                if self.sealed_path(name).exists():
                    self._decrypt(name, raw)
        self.sealed_dir.mkdir(parents=True, exist_ok=True)
        report: list[str] = []
        for name in self.names:
            plain = self.plain_dir / name
            if not plain.exists():
                report.append(f"{name}: no plaintext here, sealed copy kept")
                continue
            data = plain.read_bytes()
            if not force and hashes.get(name) == digest(data) and self.sealed_path(name).exists():
                report.append(f"{name}: unchanged")
                continue
            self.sealed_path(name).write_bytes(self._encrypt(name, data, raw))
            hashes[name] = digest(data)
            report.append(f"{name}: sealed")
        self._write_manifest(hashes)
        return report

    def unlock(self, key: str, *, dest: Path | None = None, force: bool = False) -> list[str]:
        """Decrypt every sealed file into `dest` (the plaintext folder by default).

        Everything is decrypted and checked before anything is written, so a bad
        key or a tampered file leaves the folder as it was.
        """
        raw = key_bytes(key)
        target_dir = dest or self.plain_dir
        hashes = self.manifest()
        decrypted: dict[str, bytes] = {}
        for name in self.names:
            data = self._decrypt(name, raw)
            if hashes.get(name) != digest(data):
                raise VaultError(
                    f"{name} decrypted, but does not match the manifest",
                    "restore the folder with `git checkout -- eval/sealed`; if that does not help, the files and "
                    "manifest were committed out of step, so seal again from a good plaintext",
                )
            decrypted[name] = data
        report: list[str] = []
        for name, data in decrypted.items():
            target = target_dir / name
            if target.exists() and target.read_bytes() != data and not force:
                raise VaultError(
                    f"{target.name} here differs from the sealed copy; refusing to overwrite it",
                    "if your copy is the newer one, run `uv run poe eval-seal`; to replace it with the sealed "
                    "version, run `uv run poe eval-unlock --force`",
                )
        target_dir.mkdir(parents=True, exist_ok=True)
        for name, data in decrypted.items():
            target = target_dir / name
            if target.exists() and target.read_bytes() == data:
                report.append(f"{name}: already unlocked")
                continue
            target.write_bytes(data)
            report.append(f"{name}: unlocked")
        return report

    def status(self) -> list[str]:
        """Each file's state, without the key."""
        hashes = self.manifest()
        lines: list[str] = []
        for name in self.names:
            sealed = self.sealed_path(name).exists() and name in hashes
            plain = self.plain_dir / name
            if not plain.exists():
                state = "sealed, locked (run `uv run poe eval-unlock`)" if sealed else "missing"
            elif not sealed:
                state = "plaintext only, not sealed (run `uv run poe eval-seal`)"
            elif digest(plain.read_bytes()) == hashes[name]:
                state = "sealed, unlocked, in step"
            else:
                state = "sealed, unlocked, CHANGED since sealing (run `uv run poe eval-seal`)"
            lines.append(f"{name}: {state}")
        return lines


def require(path: Path) -> Path:
    """The path of a plaintext eval file, or an error saying how to unlock it."""
    if not path.exists():
        raise FileNotFoundError(
            f"{path.name} is sealed and not unlocked here.\n  FIX: run `uv run poe eval-unlock` "
            f"(needs {KEY_SETTING} in .env)"
        )
    return path


def write_key(env_path: Path) -> str:
    """Create a key and put it in `env_path`. Returns a message without the key.

    Appends rather than rewriting, so nothing else in the file is touched; an
    existing empty `EVAL_DATA_KEY=` line is filled in place.
    """
    text = env_path.read_text(encoding="utf-8") if env_path.exists() else ""
    lines = text.splitlines(keepends=True)
    for index, line in enumerate(lines):
        name, _, value = line.partition("=")
        if name.strip() == KEY_SETTING:
            if value.strip():
                raise VaultError(
                    f"{env_path.name} already has {KEY_SETTING}",
                    "keep it; to rotate it, unlock with the old key, replace the line with an empty "
                    f"{KEY_SETTING}=, run keygen, then `uv run poe eval-seal --force`",
                )
            ending = line[len(line.rstrip("\r\n")) :] or "\n"
            lines[index] = f"{KEY_SETTING}={new_key()}{ending}"
            env_path.write_text("".join(lines), encoding="utf-8", newline="")
            break
    else:
        newline = "\r\n" if "\r\n" in text else "\n"
        block = [
            "",
            "# Key for the sealed eval data in eval/sealed/ (eval/vault.py). Back it up somewhere",
            "# safe: without it the sealed files cannot be decrypted.",
            f"{KEY_SETTING}={new_key()}",
        ]
        lead = "" if not text or text.endswith(("\n", "\r")) else newline
        with env_path.open("a", encoding="utf-8", newline="") as handle:
            handle.write(lead + newline.join(block) + newline)
    return f"wrote a new {KEY_SETTING} to {env_path.name} (not shown); back it up somewhere safe"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status", help="show each file's state (no key needed)")
    unlock = commands.add_parser("unlock", help="decrypt the sealed files into eval/")
    unlock.add_argument("--force", action="store_true", help="replace local copies that differ")
    unlock.add_argument("--to", type=Path, help="decrypt into this folder instead of eval/")
    seal = commands.add_parser("seal", help="encrypt the plaintexts that changed")
    seal.add_argument("--force", action="store_true", help="re-encrypt everything (after a new key)")
    commands.add_parser("keygen", help="create a key and write it into .env")
    args = parser.parse_args(argv)

    vault = Vault()
    try:
        if args.command == "status":
            report = vault.status()
        elif args.command == "keygen":
            from src.config import PROJECT_ROOT

            report = [write_key(PROJECT_ROOT / ".env")]
        else:
            from src.config import settings

            if args.command == "unlock":
                report = vault.unlock(settings.eval_data_key, dest=args.to, force=args.force)
            else:
                report = vault.seal(settings.eval_data_key, force=args.force)
    except VaultError as error:
        print(error, file=sys.stderr)
        return 1
    print("\n".join(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
