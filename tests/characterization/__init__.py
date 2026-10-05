"""Characterization tests: what the important paths do today, input to output.

They pin current behaviour, including behaviour that may be wrong, so that a
refactor cannot change it silently. A failing snapshot means behaviour changed:
if that was intended, run `uv run poe snapshots`, review the diff, and say why in
the commit. Suspected bugs seen here are recorded in docs/plans/tech-debt.md.
"""
