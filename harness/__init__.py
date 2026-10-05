"""The harness: checks and generators that keep this repository safe to change.

Not application code. Nothing in `src/` imports from here. Every check prints
each violation as a rule ID, a `file:line` location and a `FIX:` line, so the
next person or agent can repair it without asking. See CLAUDE.md.
"""
