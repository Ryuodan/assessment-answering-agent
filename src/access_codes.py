"""Where a team access code generated at startup is shown: never the log (TD-029).

On an upgrade where a team has no access code, `identity.bootstrap` generates
one, because otherwise nobody could sign in. The database keeps only its hash,
so the plaintext has to reach a person some other way. By the user's decision
it is shown in two places, and only there:

* **The Access panel.** The code is kept in this process's memory and listed
  with its team for administrators until a new code is issued for that team
  (or the server restarts, after which an administrator issues one).
* **The console.** It is written to the terminal device itself, not to stdout
  or stderr: `serve.sh` pipes those into `logs/server.log`. Where there is no
  terminal (a service manager), the Access panel is the only place.

The log records that a code was generated and where it was shown, never the code.
"""

from __future__ import annotations

import os

_waiting: dict[str, str] = {}
CONSOLE = "CONOUT$" if os.name == "nt" else "/dev/tty"


def _to_console(text: str) -> bool:
    try:
        with open(CONSOLE, "w", encoding="utf-8") as terminal:
            terminal.write(text + "\n")
        return True
    except OSError:
        return False


def announce(team_id: str, code: str) -> str:
    """Keep the code for the Access panel and show it on the console; returns where it went."""
    _waiting[team_id] = code
    shown_on_console = _to_console(
        f"\nAccess code generated for team {team_id!r}: {code}\n"
        "Give it to the team, or issue a new one on the Access panel. It is not written to the log.\n"
    )
    return "access panel, console" if shown_on_console else "access panel"


def waiting(team_id: str) -> str | None:
    """The generated code still to be read for this team, for administrators only."""
    return _waiting.get(team_id)


def forget(team_id: str) -> None:
    """A new code was issued: the generated one no longer works and is not shown."""
    _waiting.pop(team_id, None)
