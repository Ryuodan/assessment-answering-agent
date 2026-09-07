"""Agents that read files by exploring them, rather than by rule.

Separate from `src.forms` on purpose. `forms` is the contract -- give it a path,
get a `DetectedForm` -- and everything in it is deterministic, offline and
testable against a fixture. What lives here produces the same `DetectedForm`
through a model that decides for itself what to look at next, which is a
different thing to reason about, to price and to trust.

Keeping them apart is what makes them comparable: both end at
`forms.xlsx.read_sheet`, so a difference between them is a difference in the
reading and never in the reader.
"""
