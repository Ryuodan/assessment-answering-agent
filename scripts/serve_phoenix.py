"""Start the Phoenix collector with its server settings from this project's .env (plan 044).

    ./serve-phoenix.sh                          # what the deployment's `phoenix` screen session runs
    python -m scripts.serve_phoenix             # the same, from this project's environment
    python -m scripts.serve_phoenix --check     # say what would be started, and start nothing

Phoenix runs in an environment of its own (it needs Python 3.12; this app runs
on 3.11), so it cannot read `.env` through `src.config` itself. This reads the
`PHOENIX_*` server settings through `src.config`, the one place configuration is
read, gives Phoenix those that are set, and replaces itself with
`phoenix serve`. `.env` is never sourced as shell code.
"""

from __future__ import annotations

import argparse
import os
import shutil
import sys
from collections.abc import Mapping
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

# What Phoenix inherits is the environment as it was, before the line below.
_INHERITED = dict(os.environ)
# The launcher needs the settings, not the tracing that importing them starts.
os.environ["PHOENIX_TRACING"] = "false"

from src.config import PROJECT_ROOT, Settings, settings


def working_dir(value: str) -> str:
    """`PHOENIX_WORKING_DIR` as Phoenix is given it: absolute, a relative one taken from the project."""
    if not value:
        return ""
    directory = Path(value).expanduser()
    return str(directory if directory.is_absolute() else (PROJECT_ROOT / directory).resolve())


def server_environment(config: Settings, inherited: Mapping[str, str]) -> dict[str, str]:
    """The environment `phoenix serve` starts with: the inherited one, plus each server setting that is set."""
    values = {
        "PHOENIX_HOST": config.phoenix_host,
        "PHOENIX_PORT": str(config.phoenix_port),
        "PHOENIX_GRPC_PORT": str(config.phoenix_grpc_port),
        "PHOENIX_WORKING_DIR": working_dir(config.phoenix_working_dir),
        "PHOENIX_HOST_ROOT_PATH": config.phoenix_host_root_path,
        "PHOENIX_ROOT_URL": config.phoenix_root_url,
    }
    return {**inherited, **{name: value for name, value in values.items() if value}}


def executable(config: Settings) -> Path:
    """The `phoenix` command: `PHOENIX_EXECUTABLE`, or the one on PATH."""
    configured = config.phoenix_executable.strip()
    found = Path(configured).expanduser() if configured else Path(shutil.which("phoenix") or "")
    if not (found.name and found.is_file() and os.access(found, os.X_OK)):
        raise SystemExit(
            "Phoenix's command was not found. Install it (docs/operations/tracing.md) "
            "and put it on PATH, or set PHOENIX_EXECUTABLE in .env."
        )
    return found.resolve()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--check", action="store_true", help="print what would be started, and start nothing")
    args = parser.parse_args()

    command = executable(settings)
    env = server_environment(settings, _INHERITED)
    if args.check:
        print(f"{command} serve")
        for name in sorted(set(env) - set(_INHERITED)):
            print(f"  {name}={env[name]}")
        return
    if env.get("PHOENIX_WORKING_DIR"):
        Path(env["PHOENIX_WORKING_DIR"]).mkdir(parents=True, exist_ok=True)
    os.chdir(PROJECT_ROOT)
    os.execve(str(command), [str(command), "serve"], env)


if __name__ == "__main__":
    main()
