# Evaluation

How answers are measured, against which sets, and what the measurements changed.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

`eval/` scores the system two ways, against two different standards, and they
are meant to be read as a pair.

**The facts set** — `eval/golden_set.json` — pairs questions with the core facts
a correct answer must state, verified against the source documents by a human.
It measures whether an answer is *right and complete*.

**The house set** — `eval/house_set.json` — holds 135 questions from five real
questionnaires the security team filled in themselves, paired with **the answer
they actually wrote**. It measures whether we write what *they* would have
written. See `eval/house.py`.

The house set and the answer memory (`eval/answer_memory.json`) are sealed in
git, because they are customers' questions and the team's real answers: run
`uv run poe eval-unlock` before any of the commands below (see
[SECURITY.md](../../SECURITY.md#sealed-eval-data)).

The two pull in opposite directions and that is the point. Measuring only fact
coverage is what produced answers with a median of 152 words against a team
median of 11: the drafting prompt was told completeness is a correctness
requirement, because completeness was the only thing being scored. A system
that does well on the house set and badly on the facts set is terse and wrong,
which is worse. Neither number means much alone.

## Two lengths, and why neither is the standard

The team's answers run to a median of eleven words against our 152, and the
obvious conclusion -- that they want short answers -- is wrong. They prefer
detailed ones; eleven words is what you write when a questionnaire has 183 rows
and it is due on Thursday. So length is a choice rather than a target, and it is
made per questionnaire *and* per answer: 183 rows can go brief while the one the
assessor will actually read stays full.

Every answer card offers **Full | Brief** for itself, whether or not a brief
form exists yet; choosing Brief there shortens that one answer on the spot. The
choice used to appear only once a brief form existed -- that is, only after the
whole questionnaire had been switched to Brief at least once, so the
per-answer control was reachable only through the bulk one it exists to avoid.

The brief form is **derived from the full one**, never drafted beside it. It
goes through `src.rewrite`, which re-retrieves nothing and cannot introduce a
claim the sources do not carry, and both are stored -- so switching is instant
in both directions and the two cannot disagree about what this organisation
says. Editing the full answer discards the brief, because the brief was
condensed from words that no longer exist.

Two consequences worth knowing. The compliance dropdown is resolved from the
**full** answer whatever length is being written: a condensed answer can lose
the sentence the verdict came from, and the rating must not change because
somebody chose shorter prose. And the evaluation never scores the brief form
against the team's short answers, however tempting the symmetry -- see
`eval/house.py`.

## What the team's answers actually look like

Harvested from 17 filled questionnaires: 1,055 question/answer pairs, of which
832 are usable once the dropdown option lists, unticked checkboxes, owner
columns and CR numbers are separated out from the answers.

| | the team | this system |
|---|---|---|
| median words | 11 | 152 |
| opens with a verdict | 67% | 5% |
| names a clause or section | 0.1% | 60% |
| contains a list | 0.1% | 50% |
| says the documentation does not cover it | **0 of 1,055** | 19% |
| question-mirroring | 50% | 13% |

Their answer is one move: restate the question as an assertion and stop. *"Are
offsite backups containing BAB data encrypted?"* becomes *"Yes, offsite backups
containing data are encrypted."* Half the content words come from the question.

The last row is the one that matters most. In 1,055 answers the team never once
wrote that the documentation does not cover something — when they do not know,
they leave the cell blank or route it to the team that does.

## Splitting the team's answers

135 pairs are held out to grade against; the other 698 are the answer memory.
The split is **by file**, because a questionnaire asks the same control a dozen
ways and a graded question whose twin sits in the memory measures retrieval
rather than drafting. Every one of the five held-out questionnaires is a
customer whose form the memory has never seen, and no held-out question appears
in it: measured across all 135, the closest remembered *question* sits at a
median cosine of 0.76 and a maximum of 0.93, with none above 0.95 and none
identical. Sixteen of the 135 are close enough (≥ 0.88) that the memory has
effectively been asked before, and the summary reports those separately from
the other 119 — a single average over the two would hide which of them a number
came from.

That is also the measured basis for expecting an answer memory to help at all:
most held-out questions have a neighbour in the 0.7–0.9 band, which is close
enough to inform an answer and not close enough to copy one.

```bash
python -m scripts.run_both_evals --label "what changed" --sample 30
python -m scripts.run_house_eval --sample 30      # the house set alone
```

`run_both_evals` runs both suites and reads them as a pair: the house set is the
number to move, the facts set is a floor that must not fall. A change that
improves one while dropping the other has traded correctness for brevity, and
the runner says so rather than leaving it to be discovered later.

## Dev and final, failures, and comparing runs

*Added 2026-10-06 by plan 013, after the text above was written.*

The 135 held-out pairs are now split once more, by questionnaire. Three of the
five questionnaires (82 cases) are `dev`, to tune against. The other two (53)
are `final`, to confirm a change. `eval/splits.json` names them by a hash of
their file names. Every run of the final split needs `--reason`, and is
appended to `eval/final_runs.jsonl`, so how often it has been looked at is
on record. All five were tuned against before this split existed, so `final`
is held out from that day on, not unseen (TD-014).

```bash
python -m scripts.run_house_eval --all                                        # the dev split
python -m scripts.run_house_eval --all --split final --reason "confirming X"  # recorded
python -m scripts.compare_runs eval/results/a.json eval/results/b.json --noise eval/results/noise_baseline.json
python -m scripts.measure_noise --repeats 3 --label baseline                   # real model calls
uv run poe eval-contamination
```

Before any model call, each runner checks the cases for **contamination**. It
looks for 10 consecutive words of a question or a reference answer anywhere
in `src/`, and for a question that is, normalised, already a question in the
answer memory. A leak stops the run unless it is recorded in `KNOWN` in
`eval/contamination.py`, against a tech-debt item. A recorded leak's case is
left out and the run says so. The first check found one, TD-033; plan 017
replaced the prompt's example, and the check has found none since.

A question that failed to be answered, or whose judge failed, is an
**infrastructure failure**, not an answer. It is left out of every number and
counted on its own line. Before this plan, a failed answer was judged as
"(no answer)" and scored as a refusal, and a failed judge was filed as
`unanswerable`. A run with more than 5% failures is marked NOT COMPARABLE:
rate limits do not fail questions at random, so the cases that remain are a
different sample.

**Comparing two runs.** `scripts/compare_runs.py` compares runs case by case
and lists which cases got better, which got worse, and which stayed the same.
Given the noise file from `scripts/measure_noise.py`, it reports a move on a
case that already varied between identical runs as within noise. The noise
itself is measured in plan 014.

## Run-to-run noise on the house set

*Measured 2026-10-06 by plan 014.*

The dev split was run twice, with identical code, settings, corpus and
memory, using `scripts/measure_noise.py`. 81 cases were run; HOUSE-096 was
left out (TD-033). A third run hung on the embedding host and was stopped
(TD-034). That leaves two runs, not three: enough for a range and for the
cases that moved, but only a rough standard deviation.

| Run | Scored | Failures (answering) | Agreement | Form | Contradicts | Held back |
|---|---|---|---|---|---|---|
| 1 | 79 | 2 | 83.5% | 96.2% | 11 | 32 |
| 2 | 77 | 4 | 87.0% | 97.8% | 8 | 28 |

On the 75 cases both runs scored, so that the different failures do not
count, agreement was **82.7% and 86.7%: four points apart with nothing
changed**. 12 of those 75 cases scored differently between the two runs.
Seven of them moved by 5 points, the full width of the scale. In 7 cases the
judge said "contradicts the team" in one run and not in the other. Every
failure was a Groq tokens-per-minute limit, and no question failed in both
runs.

What this means for reading a change on the dev split:

- **Two single runs that differ by less than about 5 points of agreement
  (`smallest_real_difference`: 4.9) show nothing.** That is twice the
  standard deviation of two runs, and the gap measured with the cases held
  fixed was 4.0. A real improvement smaller than that needs repeated runs of
  both versions, compared case by case.
- **The number of "contradicts" verdicts is not stable either.** It was 11
  and 8 between identical runs. A change in it of a few cases is not
  evidence about safety.
- **Use `scripts/compare_runs.py --noise eval/results/noise_baseline.json`.**
  The noise file lists the 12 cases that moved on their own, and their moves
  are reported as within noise.

Where the noise comes from was not separated here. The drafter runs at
temperature 0.2 (`src/graph/nodes.py`) and the judge at 0. The facts set's
judge alone moved 3.8 points over four gradings of one file (above), so the
judge is likely part of it. Re-judging one run's answers several times would
separate the two for a fraction of a run's cost.

## The two measurements that matter

```bash
python -m scripts.run_house_eval --set held-out  --all    # what happens on the next questionnaire
python -m scripts.run_house_eval --set in-memory --all    # how faithfully it reuses what it holds
python -m scripts.eval_to_xlsx eval/results/heldout_full.json    # one row per question, for a person
```

**Held out — 135 questions, five questionnaires the memory has never seen.**
This is the estimate of real-world performance: agreement with the team's own
answer **86.7%**, form 90.4%, 12 contradictions.

The number that decides whether it can be trusted is not that one. It is what
happens either side of the confidence gate:

| | cases | agreement | contradicts the team |
|---|---|---|---|
| would be written as it stands | 72 | **95.8%** | **1** |
| held back for a person to read | 63 | 76.2% | 11 |

Eleven of the twelve disagreements are in the half the system refuses to write.
The one that gets through is a question about security guards where the team
wrote "Yes" for offices and data centres together and ours said guards at the
data centres and controlled access at the offices — a disagreement by being
more specific, which is the mildest kind available.

Two things this run found, both since fixed: eleven answers in 135 referred to
our own records in the prose ("as confirmed in our prior answer"), which is
internal bookkeeping in a customer's file; and one reported a disagreement
between two remembered answers *to the assessor* rather than through
`contradicts_memory`. The prompt now bans both, and `strip_source_markers`
learned the `【1†source】` shape this model reaches for.

**In memory — all 698 questions the memory holds, answered again.** Not
generalisation: the pair is in the corpus, so this is the ceiling. Agreement
**95.9%** (691 graded; 7 references are not answers and are excluded), form
98.0%, 24 contradictions. Either side of the gate: 409 would be written at
99.5% agreement with one contradiction; 289 are held back at 90.0% with the
other 23.

The diagnostic that makes the pair readable is whether retrieval found the
entry for the question being asked:

| | cases | agreement |
|---|---|---|
| cited its own memory entry | 613 | **98.7%** |
| did not | 85 | 72.7% |

So the pipeline reuses what it holds almost perfectly *when it finds it*, and
misses its own answer 11% of the time — which is where the remaining work is,
and it is in retrieval rather than in drafting. Read against the held-out
86.7%, generalising to a customer the memory has never seen costs about nine
points.

## What moved it

| | baseline | + who we are | + ours vs external |
|---|---|---|---|
| agreement with the team | 42.1% | **70.7%** | 69.3% |
| form (verdict first, no hedging) | 41.5% | 86.7% | **87.8%** |
| facts (the floor) | -- | 76.7% | **79.5%** |
| says "the documentation does not cover this" | 39.3% | 6.7% | 10.0% |
| cites an internal clause | 57.1% | 13.3% | 23.3% |

The first column is the system measured against the team's own answers before
any of this. The jump is almost entirely one sentence: a questionnaire says
"Does the Third-party..." and means *us*. Without being told, the drafter read
it as somebody else's supplier, searched our Third-Party Cybersecurity Policy --
which says what we require *of* vendors -- found nothing about a third party's
own controls, and answered "the documentation does not state that...". That is
why the hedging rate collapsed when the organisation profile arrived: most of it
was never hedging, it was answering the wrong question.

Answers are written to `--out` **before** the judging runs. Answering is the
minutes and the money; judging is neither, and the first run of this harness
threw away thirty answers because the judge refused one schema.

`eval/golden_set.json` holds 42 cases across seven categories. The first 28
cover T2's own policies. The rest were added with the NCA ECC guide and the
SDAIA PDPL material, and cover two things the internal policies alone cannot:
**Regulatory Reference**, answered from the standards themselves, and
**Cross-Source Synthesis**, where a correct answer has to combine T2's policy
with the regulation — the breach question, for instance, has three separate
notification duties with three different deadlines, one internal and two
regulatory.

```bash
python -m eval.run_eval answer --out eval/results/current.json
python -m eval.run_eval score  eval/results/current.json --notes "what changed"
python -m eval.run_eval score  eval/results/current.json --baseline eval/results/previous.json
python -m eval.run_eval history
```

Every scored run is appended to `eval/history.jsonl` with the settings that
produced it — model, top-k, which retrieval passes were on, attempt budget — so
a later comparison can tell a real improvement from a configuration difference.
`history` prints them oldest first.

`answer` asks the live system every golden question. `score` grades any answers
file — including runs archived from an earlier version of the system — so a
change is measured against its predecessor on one rubric by one judge.

Three things keep the judge honest. It grades on a different model from the one
that wrote the answer. It is given the facts rather than asked to recall them,
so it checks whether the answer says what was already established rather than
what the policy says. And because the fact lists are known to be incomplete, a
specific the answer asserts that no listed fact covers is recorded as an
`unverified_claim` for a human to check, never scored as a fabrication.

The report also carries the calibration numbers: the spread of confidence
across the run and its correlation with the score. Confidence that does not move
with correctness is worse than no confidence at all, because it makes the review
queue meaningless.

## Measuring retrieval, separately from the answer

The judge reads the answer text and nothing else, so a low score cannot be
attributed: "the retriever never found the clause" and "the drafter was handed
the clause and ignored it" produce the same number. That blindness is not
theoretical — a change that dropped the guideline count in the drafting prompt
to *zero* on retried questions moved the graded accuracy by less than a point.

```bash
python -m eval.run_eval retrieval
python -m eval.run_eval retrieval --plans eval/results/plans.json --label with-agreement
python -m eval.run_eval retrieval --baseline eval/results/before.retrieval.json
```

It scores what retrieval found against `eval/retrieval_targets.json` — the
documents and clauses the golden set's `source_reference` names — by running
the real planning, retrieval, reranking and selection nodes. **No model grades
anything**, so a pass costs almost nothing and is deterministic once the
queries are fixed, which makes it the right tool for settling retrieval
settings that the judge's three-point noise cannot resolve.

Two design points are load-bearing:

**The targets are resolved once, into a file you can read.** Matching a prose
reference to a filename at scoring time would mean the metric partly measures
the string matcher. It does: the first version of that matcher reported eleven
broken references in the golden set, and every one of them was the matcher's
fault — CamelCase filenames tokenising as one word, an English document title
against an Arabic-only filename, a Jaccard variant that preferred a short
wrong filename to a long right one. Resolved and checked once, all 149 clauses
the golden set names were found in the corpus, in the documents it attributes
them to. The references are sound; it was the automation around them that was
not, which is exactly the failure that would have produced confident nonsense.

**`--plans` pins the expanded queries.** The planner is an LLM and rewrites its
searches slightly on every run, which moved document recall by several points
between two passes of an unchanged system — more than most settings worth
testing. Reuse one plan file across a sweep and the comparison is a comparison.

Three numbers matter more than recall@k. **Prompt recall** is whether the
material reached the drafter, which is the only place it can affect an answer.
**Selection loss** is material that was retrieved and then cut — the failure
the generation eval hides most completely. **Never retrieved** is the
retriever's own miss. Cases whose expected answer is "nothing documents this"
have nothing to retrieve and are excluded rather than counted as misses.

## Running a measurement pass

Settings that change a score are read from the environment, so a pass is one
command with the variable set in front of it, and the history file records
which one produced which numbers:

```bash
python -m eval.run_eval answer --out eval/results/baseline.json
python -m eval.run_eval score eval/results/baseline.json --label baseline --notes "42-case set, expanded corpus"

RERANKER_ENABLED=true python -m eval.run_eval answer --out eval/results/reranked.json
python -m eval.run_eval score eval/results/reranked.json --label reranked --notes "cross-encoder on"

GROQ_CHAT_MODEL=openai/gpt-oss-120b python -m eval.run_eval answer --out eval/results/gptoss.json
python -m eval.run_eval score eval/results/gptoss.json --label gptoss --notes "gpt-oss-120b drafter"
```

Then `python -m eval.run_eval history` to see them side by side, or
`score ... --baseline eval/results/baseline.json` for a per-case diff.

Two things worth knowing before reading the numbers.

**Score one answers file more than once before believing its total.** The same
unmodified `r18_docling.json`, graded four times by the same judge against the
same golden set, scored 79.0, 75.2, 77.6 and 77.1 — a spread of 3.8 points with
nothing changing but the judge. A single grading of a single run is not a
measurement at this resolution, and quoting one as though it were produces
confident claims that the next pass contradicts.

What *is* stable is the **paired** difference. Across four gradings of the same
two files, the delta between them stayed between -4.4 and -5.7 and never
changed sign, while each file's absolute level wandered by more than two
points. So grade both files in the same pass, repeat the pass, and read the
difference — never the level. Roughly 1.5 points of per-case movement also
comes from the drafter itself, which runs at temperature 0.2.

And the reranker adds about 30 seconds per question on CPU, so that pass takes
an extra twenty minutes or so.

## What the golden set currently says

Measured on the T2 policy corpus, 28 cases, judged by `openai/gpt-oss-120b`:

Measured on the **42-case set against the full 80-document corpus**. Every run
is in `eval/history.jsonl`; accuracy is only comparable within one judge column,
because judges differ in severity far more than configurations do.

| Drafter | Reranker | Accuracy (gpt-oss judge) | Fact recall | Contradictions |
| --- | --- | --- | --- | --- |
| minimax-m2.7 | off | 64.3% | 52.7% | 12 |
| gpt-oss-120b | off | 61.4% | 46.2% | 13 |
| minimax-m2.7 | on | 70.5% | 63.1% | 5 |
| gpt-oss-120b | on | 74.8% | 57.0% | 5 |
| gpt-oss-120b, after the grounding and citation fixes | on | 73.3% / 76.2% | 55.6% | 5 |

Two later runs stand apart from the rows above, because they were measured
after a previous-answers bank was added to the corpus and with the reranker
off, which is the configuration the system now runs in. They are comparable to
each other and to nothing else in this table:

| Previous answers in the prompt | Accuracy | Fact recall | Contradictions | Calibration |
| --- | --- | --- | --- | --- |
| uncapped (the old behaviour) | 56.2% | 36.2% | 15 | 0.284 |
| capped at 4 of 14 | 57.1% | **47.0%** | 12 | 0.396 |

**Accuracy is flat and fact recall is not**, which is the interesting part: the
answers changed from confidently thin to substantially complete without the
rubric total moving much. Guideline citations went from 70 to 120 across the
set, previous-answer citations from 51 to 26, and the number of answers
claiming the documentation does not cover the question fell from 4 to 1.

The per-case diff says where the movement came from. Splitting the 42 cases by
whether the change actually altered what the drafter saw:

| | cases | net score change |
| --- | --- | --- |
| sources identical — the cap did nothing | 18 | **−5** |
| sources changed — the cap did something | 24 | **+7** |

Five points of loss on cases whose input never changed is the noise floor,
measured rather than assumed, and it is worth more than the totals: one case
scored 5 and then 1 on byte-identical citations and a near-identical answer. So
per-category swings on a single run of this set mean very little. `Regulatory
Reference` fell 51.4% to 34.3%, and four of those six points are one case whose
sources were unchanged — but not all of it, and there is a plausible mechanism
for the rest: with ten guideline slots instead of two, lower-ranked internal
policy chunks reach the prompt and can dilute an answer that should come from
the regulation alone. Worth watching if regulatory questions matter most; the
reranker addresses exactly that ordering problem.

## What retrieval actually does

The first measurement of retrieval on its own, on the 80-document corpus with
the reranker off. Of 69 documents the golden set says an answer needs:

| | documents |
| --- | --- |
| reached the drafting prompt | 35 |
| retrieved, then cut before the prompt | 7 |
| **never retrieved at all** | **27** |

Document recall into the prompt is 50.7%, clause recall 32.9%, MRR 0.62, and
22 of 40 scorable cases had every source they needed. **The dominant failure is
recall, not ordering** — 27 documents are never found, and no amount of
reranking, fusion or agreement-weighting can promote a chunk that was never
returned. That is the number to attack, and it is one the generation eval could
never have shown, because an answer written without the right document reads
like a drafting failure.

Retrieval also degrades gracefully across categories in a way worth knowing:
`Direct Extraction` reaches 90% document recall, while `Synthesis` and
`Scenario-Based` — the questions that expect four or five different policies —
sit near 27%. A 14-slot prompt filled from `k=5` searches simply cannot hold
five documents' worth of clauses, so those questions are budget-bound rather
than retrieval-bound.

## What the measurements changed

Those numbers were the starting point. Working from them rather than from
intuition produced this, on the same corpus with the queries pinned:

| | Document recall | Clause recall | Lost to the budget | Never retrieved |
| --- | --- | --- | --- | --- |
| before | 47.8% | 32.2% | 11 | 25 |
| **after** | **66.7%** | **58.4%** | 4 | **19** |

Five changes, in order of how much they mattered.

**Capping unit expansion** was most of it, and it was invisible until retrieval
was measured directly: the prompt was being filled with one document's chapter.

**Widening the net only helped once the leak was fixed.** Raising
`TOP_K_GUIDELINES` on its own made things *worse* — retrieved recall rose from
60.9% to 71.0% while prompt recall fell from 49.3% to 42.0%, because everything
extra was cut before the drafter saw it. With expansion capped, the same change
is a small gain. The order of operations was the whole point: a lever that
looks harmful can be a lever whose benefit is being thrown away downstream.

**Fixing the query planner** — six queries instead of four, and one phrasing
per line — is what finally moved *never retrieved*, from 26 to 19. Nothing
about ranking or budget can recover a document no search ever asked for.

**Raising the prompt budget** to 30 chunks absorbs what the wider net finds.
This one has to be re-derived whenever retrieval changes, and the pattern
repeated exactly: after the planner fix, evidence lost to the budget jumped
from 1 document to 9, and lifting the budget converted that into recall.

**Capping how much of the prompt previous answers may take**, if a
previous-answers bank is indexed — see `MAX_PRIOR_ANSWER_CHUNKS` above.

Every one of those was found by measuring, and two of them looked like
*regressions* until the stage after them was fixed. That is the argument for
scoring retrieval in stages rather than end to end: `retrieved` and `in the
prompt` moving in opposite directions is the signal, and a graded accuracy
number cannot show it.

What is left is a pure recall problem: 19 of 69 expected documents are never
retrieved at all, almost all of them on questions expecting four or five
policies at once. `HYBRID_SEARCH=true` recovers roughly one and remains off,
having measured worse on the graded set. That is the next thing to attack, and
it will not be fixed by ranking.

## Does better retrieval produce better answers?

Graded end to end against a control on the same corpus:

| | Accuracy | Fact recall | Contradictions | Flagged | Sources per answer |
| --- | --- | --- | --- | --- | --- |
| before | 57.6% | 48.7% | 12 | 16 | 1.43 |
| after the retrieval work | 73.3% | 60.6% | 4 | 11 | 1.98 |
| **after extraction and numbering** | **79.0%** | **61.6%** | **4** | 13 | — |

The last row is the heading hierarchy and the dashed control ids together, on a
re-indexed corpus. Split the usual way: 7 cases whose citations were unchanged
contributed **−1**, and the 35 whose citations changed contributed **+13**.
`Scenario-Based` gained 25 points and `Cross-Source Synthesis` 20; citations
carrying a clause reference went from 108 to 173. Confidence also began
correlating with correctness again, from −0.02 to 0.26, having collapsed when
absence questions came to dominate the low-confidence band.

Split the usual way, by whether the change altered what the answer was built
from:

| | cases | net score change |
| --- | --- | --- |
| citations identical — nothing changed for this case | 11 | **+1** |
| citations differed | 31 | **+32** |

That is the shape a real improvement makes, and it is worth contrasting with
the query-agreement change measured above, where six of fourteen points came
from cases the change never touched. Here the untouched cases contribute +1.
Five independent measurements agree: clause recall up 26 points, fact recall
up 12, distinct sources per answer up 38%, contradictions down to a third, and
answers citing nothing at all down from 7 to 3.

By category, `Regulatory Reference` went 37.1% to 94.3% and `Cross-Lingual /
Arabic` 66.7% to 90.0% — both dominated by the documents that were being
crowded out of the prompt. `Out of Bounds` did not move, which is the right
answer: those questions are correct when they report an absence, and nothing
here changes whether an absence is real.

Two costs, both worth stating. Given five sources where it previously had one,
the drafter sometimes writes a broader answer and loses a specific reference —
the dilution risk that comes with a 30-chunk prompt. And input tokens per
question roughly doubled, for the drafting and the review call alike.

**Confidence stopped correlating with correctness, and the reason is not what
it looks like.** The correlation fell from 0.38 to about zero. Answers the
system was confident about score 3.62 on average; answers it was *not*
confident about score 3.67 — statistically indistinguishable. But five of the
nine low-confidence answers are `Out of Bounds` questions, where the correct
answer is that the documentation does not cover the topic, and the drafting
prompt explicitly instructs a confidence at or below 0.3 for exactly that case.
Retrieval improving meant more of those absences were identified correctly, and
each correct one is a low-confidence, high-scoring point that flattens the
correlation.

So the number is measuring the wrong thing rather than reporting a broken
system, and the fix is not to make the model more confident about admitting
ignorance. A reviewer arguably *should* see "we have nothing documenting this"
near the top of the queue before it goes back to an assessor. What the
correlation cannot distinguish — and a human reading the queue can — is
"uncertain because the sources are thin" from "certain that the sources are
silent". The remaining genuine miscalibration is narrower: one answer scored 5
at a confidence of 0.20 because the grounding reviewer judged it ungrounded
despite three good citations.

**Query agreement was measured and is close to neutral.** With the expanded
queries pinned so the comparison is exact:

| `QUERY_AGREEMENT_WEIGHT` | Document recall | Clause recall | Cases fully covered |
| --- | --- | --- | --- |
| 0 | 50.7% | 32.9% | 22 |
| 0.10 / 0.20 / 0.30 | 49.3% | 34.9% | 23 |

Clause recall up two points, document recall down one and a half, and the
effect saturates immediately — 0.10, 0.20 and 0.30 produce byte-identical
results, so only a handful of chunks are close enough for the lift to reorder
them. It is on by default because the finer-grained measure improves and it
costs nothing, but it is not a lever: with 37 chunks retrieved into 14 slots,
reordering rarely changes membership.

Graded end to end against a control that differs only in that weight, it looks
much better than it is — and this is the clearest example in the project of why
the generation eval cannot settle a retrieval question:

| | Accuracy | Fact recall | Calibration |
| --- | --- | --- | --- |
| `QUERY_AGREEMENT_WEIGHT=0` | 57.6% | 48.7% | 0.384 |
| `QUERY_AGREEMENT_WEIGHT=0.15` | 64.3% | 45.9% | 0.557 |

A 6.7-point gain, with fact recall moving the other way. Splitting the 42 cases
by whether the change altered the citations at all:

| | cases | net score change |
| --- | --- | --- |
| citations identical — the weight did nothing | 21 | **+6** |
| citations differed — the weight did something | 21 | +8 |

**Six of the fourteen points came from cases the change provably did not
touch.** One of them scored 1 and then 5 on identical citations. So the noise
floor on this set runs to about six points in whichever direction it happens to
fall — the prior-answer cap measured it at −5 on eighteen unchanged cases —
and an +8 on the half that did change is not distinguishable from it. The
honest reading is that query agreement's effect on graded accuracy is **not
measurable here**, which is exactly what the retrieval numbers predicted.

That is the argument for the retrieval harness in one table. It has no judge,
no drafting temperature and no mixture-of-experts routing, so with the queries
pinned it resolves a two-point change that a 42-case graded run cannot see
through a six-point fog.

**Judge variance is about three points, so read the table with that in mind.**
The last row is one answers file scored twice by the same judge: 73.3% and
76.2%. Nothing about the system changed between them. Retrieval breadth shows
the same picture — `TOP_K_GUIDELINES` of 5 and 8 both scored exactly 160/210
with the reranker on, so the smaller value is the better default: same answers,
fewer chunks to rerank. Only differences larger than that spread are worth
acting on, which in this project means the reranker and nothing else.

**The reranker is the finding.** Same drafter, same settings, only the
cross-encoder differs: +13.4 points for gpt-oss-120b and +6.2 for
minimax-m2.7, with contradictions of a golden fact more than halved. It matters
most on the regulatory questions, which went 45.7% to 88.6% — dense scores on
this corpus bunch between 0.32 and 0.36, so on eighty documents the right chunk
routinely lands just outside the cutoff, and ordering within that band carries
almost no information. It costs about 30 seconds per question on CPU and
roughly a second on a GPU, which is the real decision to make about it.

**The drafter matters much less than it looks.** The two models sit 2.9 to 4.3
points apart depending on the judge, inside the noise band. minimax-m2.7 covers
more expected facts (63.1% against 57.0%) while gpt-oss-120b scores slightly
higher on the rubric.

A caution about that comparison, and the reason for the second judge: the
default judge *is* gpt-oss-120b, so scoring its own answers is self-marking.
Re-scoring both reranked runs with `llama-3.3-70b-versatile` narrowed the gap
from 4.3 to 2.9 points, so there is a real but modest self-preference. Note also
that the neutral judge scored the identical answers at 86.7% and 83.8% — twelve
points more generous across the board. That is judge severity, not quality, and
it is why the history file records which judge produced each row.

Hybrid search is the one change that did not survive measurement, and it is off
for that reason (measured on the earlier 28-case set). It does what it was added to do — it moved the PDPL 72-hour
breach-reporting clause from rank 11 to rank 1, a miss the human evaluation
called the highest-stakes in the set — but it promotes the wrong section of the
right document about as often, and it cost the password-length question that
the Arabic fix had just recovered. Six wins, five regressions is a coin flip,
and the coin lands on the failure mode that matters most here: a confident "the
policy does not specify". The code, the flag and its tests are kept because the
trade-off is corpus-dependent, not because it is dormant.

## Remembered answers as their own evidence (plan 027)

Every answer the memory files itself is indexed under the same name, "Answer
memory", chunk 0. That covers approved answers, answers added by hand, edited
answers and moved answers. Evidence was de-duplicated by name and chunk, so
only one remembered answer per question ever reached the drafter, and a shared
one could hide a product's own. The fix keys previous answers by their entry
id as well (`Evidence.key`).

The live index could not show the effect, because its 694 shared answers came
from the bulk import, which gives each a distinct name and chunk. So the dev
split was run on a copy in which those 694 answers were re-filed as the app
files remembered answers: the same entry ids, text and vectors. Two runs, one
on each code version, on the same copy, 82 cases each, none failed:

| | before (`3f6d505`) | after (`92d4b7e`) |
|---|---|---|
| agreement with the team | 81.7% | 84.1% |
| where the memory had been asked something similar (16) | 87.5% | 91.2% |
| where it had not (66) | 80.3% | 82.4% |
| contradicts | 13 | 11 |

Item by item: 3 better, 0 worse, 74 the same, 5 within noise. The 2.4 points
are below the 4.9 that one run each needs (above), so this shows no harm and a
consistent direction, not a proven gain. The tests prove the mechanism
(`tests/test_previous_answers.py`). The live index and database were hashed
before and after and are unchanged.

## Confidence shown for held answers (plan 030)

From plan 030, an answer a check holds for review shows a capped score: no more
than the review threshold (`REVIEW_CONFIDENCE_THRESHOLD`, 0.6), and no more than
0.3 when the reviewer found it not grounded, the top of the reviewer's own scale
for that (`verification.held_confidence`). Before, only an unsupported clause
or a partial source lowered the score. An answer held for resting on previous
answers alone, for sources that disagree, or for failing the review kept the
rating the models gave it, and one held answer in eight showed "High".

What this does to comparisons across the change:

- **Confidence figures before and after are not comparable.** The spread of
  confidence, its correlation with the judge's score (the calibration numbers in
  the report), and any count by confidence band all move, because held answers
  that scored high now show at most 0.6. Compare runs on the same side of the
  change, or apply the cap to the earlier run's held answers first.
- **Agreement and the release decision are comparable.** The cap only lowers
  the score of an answer that is already held, so the same answers are written
  and held as before. `tests/characterization/test_answer_pipeline.py` and
  `tests/test_honest_confidence.py` pin that.

Applied to the runs on file, with no new model calls: of 134 answered held-out
questions, 19 held answers showed more than 0.6 and now show at most 0.6. On
the two dev-split runs of plan 027 it is 7 and 11 of 82. No answer's decision
changes. Up to 15, 13 and 12 more, held between 0.3 and 0.6, drop to 0.3 if the
reviewer found them not grounded. The files do not record which check held an
answer, so that count is an upper bound. The "why the confidence is low"
sentence still explains the models' rating, so it is unchanged.
