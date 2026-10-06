"""Run the app against a throwaway database, with sign-in switched off.

    python -m scripts.dev_server            # http://127.0.0.1:8124
    python -m scripts.dev_server --port 9000 --db data/scratch.db

The deployment's own database has real users in it, and a database with users in
it requires a session — which is right, and makes clicking through the interface
to check something a matter of finding an access code first. This starts the
same application over a scratch database with no users, so it runs in the
local-user ("open") mode of docs/design/access.md: every action is attributed to
`local@localhost` and nothing asks you to sign in.

The knowledge base is **shared with the deployment**, deliberately: an empty
corpus would exercise the pages against nothing, and the point of clicking
through is to see it working on the real policies. The answer memory adopts what
is already indexed the first time it is read, so a scratch database still opens
with the whole of it.

Two things follow from that sharing, and both have bitten:

* **Writes land in the real corpus.** Indexing a document here, or approving an
  answer, puts it in the deployment's Chroma collection — the scratch database
  scopes the *record*, not the index. Clean up what you add.
* **Do not run this beside the real server, or beside a script that writes to
  the index.** Chroma's local client is one process: two of them against one
  persist directory produce `Error finding id` from the reader while the writer
  is working.

Nothing here is for production. `src.api:app` under uvicorn is that.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8124)
    parser.add_argument("--db", default="data/dev.db", help="the scratch database")
    parser.add_argument("--reload", action="store_true")
    args = parser.parse_args()

    # Set before anything imports `src.config`: environment beats the .env file,
    # which is where the real users and the real database come from.
    os.environ["DB_PATH"] = args.db
    os.environ["ALLOWED_EMAILS"] = ""
    os.environ["ADMIN_EMAIL"] = ""
    os.environ["ADMIN_PASSWORD"] = ""

    import uvicorn

    print(f"Open mode on http://127.0.0.1:{args.port} — database {args.db}")
    uvicorn.run("src.api:app", port=args.port, reload=args.reload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
