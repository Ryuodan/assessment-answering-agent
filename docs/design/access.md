# Signing in and access

People, teams, access codes and sessions, and running it on a network.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

## Signing in, and what gets remembered

Signing in takes two things: an address that has been added to the system, and
the **access code** shared by that person's team. Neither alone is enough —
knowing a colleague's address does not get you in, and the code without a listed
address does not either.

**Access is managed from inside the application.** That is not a convenience:
whoever operates the host may not be whoever decides who uses the system, and an
allow-list in `.env` can only be changed by the former. A `users` row *is* the
allow-list. `ALLOWED_EMAILS` seeds it on a first run only, so someone removed in
the access panel stays removed across a restart.

The panel lives **inside the main page**, opened by the *Access* button that
appears in the header for administrators, because a deployment may expose only
the application's own address — an administrator who cannot reach a second URL
would otherwise have no way in. `/admin` still works as a deep link and serves
the same document. None of that is a security boundary: `/api/admin/*` checks
the role on every request, whatever page it came from, and a path is not a
permission.

`ADMIN_EMAIL` / `ADMIN_PASSWORD` are the exception, re-applied at every startup.
They are the **break-glass account** — the one thing the operator sets, and the
way back in when a password is lost or the last administrator is removed by
mistake. Because the environment always wins for that one account, its password
cannot be changed on the admin page; create a second administrator there for
everyday use. Administrators sign in with a password of their own instead of the
team code.

Until somebody is added, everything runs open and is attributed to
`local@localhost`, which is right on a laptop and wrong anywhere else. Adding
the first user is what closes the door — there is no separate flag that could
disagree with the user list.

That stand-in is an administrator with no password, and a row with no password
signs in with the team's code — so, left as it was, anyone who knew the code
could type `local@localhost` and be an administrator. The deployment's database
had exactly that row. It is now refused at sign-in like an unknown address, a
session for it is never honoured, and it is neither listed on the access panel
nor counted as an administrator (counted, it let the one real administrator
demote themselves). And once anybody has been added, startup deletes the row
outright, with its sessions; the events it recorded stay, because the history
is the history. It was never a person. All 140 of its conversations were runs of
`scripts/eval_assistant.py` against the deployment's own database, and that
script now works in a scratch database of its own unless `DB_PATH` names one.

**What this is and is not.** It is a good door lock: it keeps strangers out of a
publicly reachable service, it puts a name against every answer, and it can be
revoked in a click. It is not a safe. There is no email verification, and a
team's code is shared by everyone on it, so it identifies a group and attributes
to a name rather than proving an individual.

Codes and passwords are hashed with scrypt (RFC 7914's interactive parameters,
16 MB) rather than the SHA-256 used for session tokens — a token is 256 random
bits with nothing to guess, while a code someone types from memory is worth
attacking offline. Each hash carries its own cost parameters, so they can be
raised later without invalidating existing credentials. A generated code avoids
the characters that get misread aloud (`I`, `L`, `O`, `U`, `0`, `1`), and is
compared case- and dash-insensitively, because rejecting a correct code because
it was pasted lower-case is a support call rather than security.

Sign-in is throttled per address — ten failures inside fifteen minutes and that
account waits, which is what makes a typeable shared code safe. Per address
rather than per IP, because the thing being guessed is shared by a whole team
and an attacker with a proxy pool would otherwise spread the guesses. A correct
sign-in clears the count, so a typo an hour ago cannot lock someone out later.
Every failure returns the same sentence whether the address is unknown, the
account is suspended, or the code is simply wrong; a login form should not be a
way to find out who has an account.

**A refusal costs the same whether or not the address exists.** Returning the
same sentence is not enough if the clock says something different: before this
was fixed, refusing a known address took 50 ms because it reached the hash and
an unknown one 2.7 ms because it did not. Nineteen times is a working way to
enumerate the allow-list from outside. An unknown address is now verified
against a decoy hash, so both paths do the same work.

Sessions are rows rather than signed tokens, so deleting a row revokes access
immediately and there is no signing secret to rotate. Only a SHA-256 of the
token is stored. Suspending or removing someone ends their sessions in the same
transaction, and a promotion reaches a live session because the role is read per
request rather than frozen in at sign-in. The cookie is `HttpOnly`, and `Secure`
follows the connection's own scheme — a browser silently discards a `Secure`
cookie sent over `http://`, and a sign-in that appears to succeed and then does
nothing is the worst way for this to fail. Behind a TLS-terminating proxy, run
uvicorn with `--proxy-headers`.

Every administrative action records an event naming who did it. Being able to
see that someone was added, and by whom, is most of the reason to have a page
rather than a config file.

### Setting it up, and upgrading into it

A new deployment needs one thing from whoever runs the host: `ADMIN_EMAIL` and
`ADMIN_PASSWORD`. Sign in on the ordinary sign-in screen with those — an
administrator types their password where everyone else types a team code — then
open *Access*, add the team, issue its code, and add people. Nothing after that
needs the operator again.

Upgrading an installation that predates this is the case worth knowing about.
Its users survive the migration as members, which means sign-in is already
required — but no team has an access code yet, so on its own that would lock
everybody out. Startup notices and issues one, and shows it in two places, never
in the log (TD-029): on the **console** the server was started from (written to
the terminal itself, so `serve.sh`'s `tee` into `logs/server.log` does not catch
it), and on the **Access panel**, beside its team, until an administrator issues
a new code. The log only says that one was generated and where it was shown:

```
WARNING  src.identity identity.access_code_generated team=cybersecurity shown_on="access panel, console"
```

Nobody is promoted to administrator automatically, because guessing which of
several existing accounts should be able to revoke the others is not a decision
to make silently. Set `ADMIN_EMAIL` / `ADMIN_PASSWORD` and restart; the log says
so if no administrator exists.

Everything else lands in one SQLite file at `DB_PATH`: users, teams, sessions,
an append-only event log, and every answered run with its evidence. Storing the
evidence is the expensive choice — a large run is a few megabytes — and it is
the right one, because an answer whose supporting chunks were thrown away cannot
be audited, and auditing is most of why anyone reopens a run. A run belongs to
the person who made it, like the questionnaire it answered -- see [A person's
work is their own](#a-persons-work-is-their-own).

Writing that history never costs answers. A run takes minutes, so a failure to
save it is logged loudly and the answers are still returned — losing the history
is bad, losing the work is worse.

### Each team's knowledge base and memory are its own

Batches and conversations were always a team's. The two things every answer is
drafted *from* were not: one Chroma collection and one table of remembered
answers served the whole deployment. With a second team, its questionnaires
would have been answered from the first team's policies and would have quoted
the first team's answers -- and any member of either team could correct, forget
or remove the other's. Now each team has its own:

* **Knowledge base.** A Chroma collection per team. The default team keeps
  `COLLECTION_NAME` unchanged, so nothing is re-indexed; any other team's
  collection is named from it, the team id and a hash of the id, which keeps
  every name inside Chroma's 63 characters.
* **Answer memory.** Rows are keyed by `(team_id, entry_id)`. The team had to be
  part of the key rather than a column beside it: an imported entry is named
  `<file>::<n>`, so two teams importing files of the same name would have
  overwritten each other's answers. The sweep compares an entry only with its
  own team's, and a disagreement belongs to the team whose answers disagree.
* **Documents.** The default team's uploads stay in `UPLOAD_DIR`; another
  team's go to `data/teams/<team>/uploads`, and the document list opens only
  the team's own. Because a team id now names a directory, it is limited to
  lower-case letters, digits, `.`, `_` and `-`, and the admin page refuses
  anything else.

Another team's entry, document or source answers **404**, not 403: to anyone
outside the team it does not exist. The CLI takes `--team` on every command and
defaults to `DEFAULT_TEAM`.

**Upgrading** is migration 10, which gives every remembered answer that has no
team to `DEFAULT_TEAM` -- on this deployment all 698 answers, to `cybersecurity`,
the team the system was set up for. The existing collection is already that
team's, so the upgrade is a restart. `tests/test_team_isolation.py` holds the
boundary from both sides, through the routes a person uses.

### A person's work is their own

Inside a team, three things were shared that should not have been: the
**conversations**, the **questionnaires** with their answers and files, and the
**answered runs**. Every member's history listed every member's, and any of them
could be opened by id. A questionnaire arrives from another company, usually
under an NDA; a conversation is what somebody said while they were working --
half-formed instructions, corrections, the file they were sent. None of that is
the team's to read.

Each of those now belongs to the person who created it, and a colleague's reads
as absent rather than forbidden -- which ids exist is not something to learn
from an error message. Three lookups carry it, and everything else goes through
them: `conversations.load`, `batches.load` (behind `tools._require`, the single
gate every operation on a questionnaire passes) and `runs.load`.

Uploads follow. A questionnaire is saved under the person who uploaded it --
`data/people/<name>-<hash>/uploads`, or `data/teams/<team>/people/…` for a
second team -- while a **policy for the knowledge base still goes to the team's
folder**, because that is who it answers for. A policy for one product's
knowledge base goes to that product's folder, beside the team's
(`<uploads parent>/products/<product id>/`), so that it can be deleted with the
product (plan 027, D-019). Every member of the team may list and open it. The document list shows a person
their own files and the team's; `resolve_document` applies the same rule, so a
colleague's questionnaire cannot be opened by typing its name.

Files uploaded before the split are still in the team's folder, and the batch
that reads one says whose it is: claimed by somebody, it is theirs alone;
claimed by nobody -- a policy, or anything put there by hand -- it stays the
team's. Nothing had to be moved.

What stays shared is what the team is bound by: the **knowledge base** and the
**answer memory**. One person approving an answer is still how the next person
answering that question gets it, and who approved it is still recorded on it.
`tests/test_private_work.py` holds the line from both sides.

## Facing a network

Three properties were established by attack rather than by reading, and the
tests that establish them are in `tests/test_hostile_input.py`.

**Nothing a caller names reaches the filesystem.** `/api/documents/{origin}/
{category}/{name}` puts three caller-controlled segments into a path.
`resolve_document` refuses any name that is not its own basename, insists on a
supported suffix, and compares the resolved parent against the resolved base,
so `../../.env`, its URL-encoded and doubled forms, and the Windows-separator
variants all end at a 400. Uploads are reduced to a basename before writing,
which is checked by asserting that every file written lands in the upload
directory itself rather than by trusting the reduction.

**A broken dependency is a sentence, not a stack trace.** Every route here
talks to something that can be down -- Chroma, the embedding host, Groq,
Docling, the disk. An unhandled exception handler turns any of them into a
clean 500 with the detail in the log, because FastAPI's default page carries
server paths into the browser. Search goes further and degrades: literal
matching needs no network, so when the embedding host stops answering the
results still come back, flagged `degraded` so the interface can say which half
ran rather than implying the corpus is empty.

**Concurrency was where the real bug was.** `get_store()` was an `lru_cache`,
which does not hold a lock while the wrapped function runs, so two threadpool
requests both constructed a `KnowledgeStore` and raced through Chroma's
process-wide client registry -- a bare `KeyError` on the persist directory, and
a 500 for whichever request lost. It surfaced only when the search drawer began
loading its file list at the same moment the page asked for knowledge stats.
Under a lock now, and asserted by having eight threads construct it at once.
Its caches had the same shape of problem: cleared before a write and not after,
so anyone who opened the knowledge base while a long policy was being embedded
rebuilt the catalog without it, and the new document stayed missing from the
list until the next upload.

**Server text is never markup on the page.** The workbench wrote its status
messages as HTML, and those messages carry what the server said -- file names
and the text of errors. A name typed as markup, which an upload through the API
can carry, ran as a page for whoever next read the message. Status lines are
text now, and a test uploads exactly such a name.
