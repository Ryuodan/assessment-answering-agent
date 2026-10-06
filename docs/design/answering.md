# Answering a question

How a question becomes an answer, and why each step is the way it is.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

## How it works

```
                          ┌──────────────────────────────┐
  guidelines (PDF/DOCX) ──▶ chunk ────────────────┐      │
                          │                       ▼      │
  previous assessments ──▶ extract Q/A pairs ──▶ Chroma  │  knowledge base
                          └──────────────────────────────┘
                                                  │
  new assessment ──▶ extract questions ──▶ fan out (one run per question)
                                                  │
                       ┌──────────────────────────┴───────────────────┐
                       │  retrieve ─▶ draft ─▶ review ─┬─▶ finalize   │
                       │      ▲                        │              │
                       │      └──── refined query ─────┘              │
                       └──────────────────────────────────────────────┘
                                                  │
                                     answers + confidence + citations
```

The parts worth calling out:

**Documents are converted by Docling, except when they should not be.** Every
upload is submitted to the hosted Docling service and comes back as Markdown
with tables intact, which is what keeps a question next to the answer cell that
belongs to it. Conversion goes through the *asynchronous* endpoint and is
polled: docling-serve caps synchronous requests at `DOCLING_SERVE_MAX_SYNC_WAIT`
seconds and answers 504 past it, so on a corpus holding real reference material
— a 161-page controls guide, a 173-page standard — the synchronous path fails
on exactly the documents worth having. If Docling is unreachable the loader
falls back to local pdfplumber / python-docx extraction, so an upload never
fails purely because a container is down — set `DOCLING_FALLBACK_LOCAL=false`
if you would rather it failed loudly.

**OCR is decided per document, not per deployment.** Forcing it on costs about
2.3x and, on a born-digital policy, changes nothing that matters: Docling
recognises table structure with a separate model that runs either way, so the
only text OCR adds is what it reads off the logos — page-footer email addresses
scattered through the chunks. Forcing it off would silently index a scanned
document as empty. So each PDF's text layer is sampled at upload and OCR is
switched on for that file alone when there is not enough text to work with.

**Arabic PDFs with a visual-order text layer are read locally instead.** Some
Arabic PDFs store the shapes the renderer draws, right-to-left, rather than the
letters an author typed. Docling reads those as disconnected fragments: it drops
most of each sentence and reverses embedded numbers, which is how a 12-character
minimum password length was once indexed as 21. Such files are detected at
upload (by their share of Arabic presentation forms) and read with pdfplumber
instead, then put back into logical order with the Unicode bidirectional
algorithm and NFKC. Latin and numeric runs survive the round trip intact —
`AES-256` and `NIST SP 800-63B` come back unchanged. The routing decision is
logged for every file.

**Previous answers are indexed as question/answer pairs, not as prose.** An LLM
pass pulls each answered row out of a completed assessment and stores the
question and answer together. A new question then matches on question wording,
and the answer your organisation actually gave travels with it. This is what
makes the output sound like you rather than like a policy document.

**They lead the prompt, but they do not get all of it.** Previous answers sort
ahead of guidelines because the drafter should read them first. For a while
that ordering also decided what fitted: the prompt was filled from the top of
the same list, so once a previous-answers bank was indexed, a dozen entries
scoring 0.20–0.48 pushed out policy clauses scoring 0.60, and a retrieval retry
that added three more pushed the guideline count to zero. The clause with the
answer had been retrieved and ranked thirteenth of thirty; the drafter never
saw it and wrote "the documentation does not state a period". The same question
answered correctly whenever no retry happened, which is what made it look like
run-to-run randomness rather than a rule. Selection is now separate from
ordering: `MAX_PRIOR_ANSWER_CHUNKS` of the `MAX_EVIDENCE_CHUNKS` slots may be
previous answers, the rest belong to the guidelines, and either kind may use
room the other does not need.

**A question is retrieved as its parts, not as one blob.** A question that asks
two things — "how quickly is access revoked, and how are we notified" — embeds
as a blend of both and ranks the clause for neither first. Before retrieving,
each question is split into several searches, one per thing it asks, phrased the
way a policy would state it and covering both languages for the key concept. Set
`QUERY_EXPANSION=false` to retrieve on the question's own wording alone.

Two details of that decide whether it works, and both were wrong. The budget
included the verbatim question in its count, so `MAX_SEARCH_QUERIES=4` bought
*three* decomposed angles — and a question like "walk us through offboarding"
needs asset return, access revocation and post-departure monitoring from five
different policies. Measured by kind: questions expecting one document retrieve
it 92% of the time, questions expecting three or more only 43%.

And the planner was quietly defeating its own bilingual instruction. Asked for
an Arabic query "in addition to" the English one, it wrote them on a single
line — `asset return policy OR سياسة إرجاع الأصول`. Queries are embedded, not
keyword-matched, so that string is searched *as itself*: a blend that means
nothing in either language and matches neither clause, while consuming one of
the few slots available. The prompt now forbids joining phrasings and the
budget is six. Together those took documents never retrieved at all from 26 to
19, and eliminated OR-merging entirely.

**Expansion completes a series, not a chapter.** A retrieval hit inside a split
unit pulls in its siblings, so the drafter never sees three items of a
nine-item list and reports them as the list. That is right for a clause series
and wrong for a standard with no internal headings to divide on: 79% of units
in this corpus are a single chunk and 96% are six parts or fewer, but the
remaining few run to 40, 100 and 113 parts, and between them hold 61% of all
the text. One hit inside one of those returned fourteen chunks from a single
document, filled every slot in the drafting prompt, and pushed every other
policy out — measured at a mean of 8.7 of 14 slots going to one document, and
all 14 on four of the golden questions. `MAX_EXPANDED_PARTS` draws the line;
past it the hit is returned alone, which is not contextless, because every part
repeats the unit's stem. Capping it moved document recall from 49.3% to 60.9%
and clause recall from 34.9% to 47.7%, and took evidence lost to the prompt
budget from eight documents to none.

**A heading is not a retrievable section.** Sectioning splits on every heading,
so a heading immediately followed by another one — "## Contents",
"## Definitions", "## KEY TASKS" — became a unit whose entire content was its
own title. 105 such chunks were indexed from this corpus, the shortest eleven
characters long. They embed close to any query using the same word and consume
a slot to say nothing.

Fixing it took two changes at two levels, and the first alone was almost
useless. Merging the heading into the section it introduces cut those chunks
from 105 to 98 — because the unit is then divided *again* by the packer, and
when the block after a heading is too large to fit, the packer flushed
everything accumulated so far as its own group. The heading it had just been
given came straight back out as "part 1 of N". Ninety-two of the ninety-eight
survivors were that. The heading now leads the first piece of the split
instead, which took the count to **16**, and consolidated the corpus from 3,153
chunks to 2,940.

**A figure placeholder is text to an embedding model.** Docling marks every
figure it does not export with `<!-- image -->`. There were 1,304 of them in
this corpus, in 841 of 2,695 chunks, and a cover page that was nothing but a
logo became a chunk whose entire body was that placeholder — retrievable,
citable, and drawn in the interface as an empty card.

It is stripped in `parse_blocks`, before the document is parsed at all, which is
safe because the placeholder is always alone on its line and always followed by
a blank one. Every ingestion path reaches it, so an uploaded document is cleaned
on the way in; `scripts/selfcheck.py` re-checks the index on disk, which is what
catches a document indexed by an older build.

Do not expect much from it, and that was the point of measuring first. The
placeholders are 0.75% of indexed characters, and embedding 24 real chunks with
and without them moved the vector by a median cosine of 0.997. Measured on the
retrieval eval with the query plans held fixed, three of 42 cases moved at all:
clause recall 61.1% → 63.1%, MRR 0.689 → 0.702, mean first rank 3.95 → 3.58,
document recall unchanged at 72.5%. The one regression is TC-022, an
out-of-bounds case whose target document the reference itself marks at 0.4
confidence. The corpus went from 2,695 chunks to 2,668 — the 27 that went were
heading-only fragments that a figure had been separating from their own body.
No unique word was lost from any of the 80 documents.

The wider question this settles: chunk cleaning is not where the headroom is.
Every safely strippable category together — whitespace, TOC leaders, running
titles, classification banners, page-number lines — is 2.04% of characters,
and the table pipes and separator rows that look like noise are load-bearing
for the formatted view. Meanwhile 83% of what reaches the drafting prompt is
off-target. The problem is which chunks are selected, not what is inside them.

Worth knowing before copying this: measured on its own, the chunking work cost
about two points of document recall and three of clause recall. Larger, fewer
chunks carry more per embedding and discriminate slightly less. It stays
because an eleven-character chunk being ranked, cited and shown to a user as a
source is a correctness problem rather than a tuning one, and because the query
and budget changes below more than repaid it.

**Chunks are whole sections, not single clauses — and never larger than that.**
Retrieval units follow the document's own structure, then adjacent units are
merged until they approach `CHUNK_SIZE`, and anything with no structure left to
split on is hard-wrapped at the nearest clean boundary. That last step matters
on converted standards: a single-cell Markdown table holding an entire section
has no rows to divide by, and it produced 9,000-character chunks that would
have crowded everything else out of the drafting prompt. Clause-scoped chunks cite beautifully and answer badly: with
§3.4.3 and §3.4.4 in separate chunks, a question about how quickly access is
revoked retrieved 3.4.4 alone and concluded the policy specified no timeframe.
It does — in 3.4.3, one clause away. Every chunk still records the *range* of
clauses it covers, so a citation stays precise.

**The relevance score is a cosine, and for a long time it was not.** Chroma's
`l2` space returns the *squared* euclidean distance; LangChain's converter
divides by `sqrt(2)` on the assumption that it is an unsquared norm. For
unit-length BGE-M3 vectors that yields `sqrt(2) * cos - 0.414`, an affine
squash — so a chunk matching at cosine 0.72 was displayed as 0.60, and one at
0.65 as 0.50. Nothing ranked differently, because the transform is strictly
increasing and no code compared a score against a fixed threshold, but every
person reading the number was reading a good match as a mediocre one. The
cosine is now recovered in `_evidence()` and the store's own figure kept
alongside it as `raw_score`. Note also that absolute values are not
comparable between embedding models: on this corpus BGE-M3 scores unrelated
text at cosine 0.33 and gibberish at 0.27, so 0.65 is a wide margin, not a
weak one.

**Several searches agreeing on a chunk is a signal, and it is free.** Query
expansion issues one search per thing the question asks, in both languages,
and those searches are written to converge. A chunk three of them return
independently has been arrived at three ways; `QUERY_AGREEMENT_WEIGHT` lifts
it proportionally. It costs nothing — the searches have already run — and it
is inert where it would mean nothing: with query expansion off every chunk has
one hit and the multiplier is exactly 1, and with the reranker on the
cross-encoder's ordering is used instead. Measured on the golden set it is a
small effect (see below), which is worth knowing before relying on it.

**Two numbering conventions, both of which have to be read.** T2's own
policies number clauses with dots — 3.4.1. The NCA and SDAIA publications
number controls with dashes — 1-1-1 — and the ECC implementation guide, the
largest document in this corpus, uses nothing else: 352 dashed control ids and
not one dotted clause. Recognising only dots left all 843 of its chunks with no
clause identifier at all, so its citations gave a file name and no reference,
and the mechanical check that a named clause is actually supported could not
evaluate a single claim drawn from it. Corpus-wide only a quarter of chunks
carried an identifier. Both notations are read now, each kept in the separator
its own document uses, because the identifier is something a reader looks up in
that document — and a control table's chunk carries the *range* of rows it
holds, since citing the first of nine rows looks precise and is not.

**Half of every Markdown table Docling emits is alignment padding.** Docling
pads each cell to the width of the widest cell in its column, so a table
carrying one 200-character definition pads all of its other rows to match.
Across this corpus that padding is 47% of all table text -- 7.07M characters of
table holding 3.73M characters of content, and one 18-row table measuring
40,320 characters to hold 8,323.

The cost is not cosmetic, because the padding is charged three times: against
`CHUNK_SIZE`, so tables that fit comfortably were split anyway; into the
embedding, so half of a table chunk's vector was runs of spaces; and again in
the drafting prompt, where thirty evidence chunks share one context window. The
vulnerability-scanning frequency table is the case that exposed it. It measures
~2,000 characters padded and ~700 unpadded, so it was cut into four pieces, and
each piece carried only row one of the table as its repeated header -- which in
that table is Docling's flattening of a merged cell, `| | Systems | Systems |
...`, naming no column at all. The drafter was shown six columns called
"Systems" and no row saying which frequency belonged to which kind of system.

Padding is now stripped when the table is parsed, so every stage downstream
counts and stores content rather than whitespace. Nothing but whitespace is
removed -- every cell, every pipe and every duplicated spanning label survives,
asserted as a property test on the non-whitespace characters, and verified
across all 80 documents at 0 rows dropped and 0 cells altered. Where the header
*is* a spanned label, the rows beneath it are carried onto every piece too, up
to the first that really names the columns.

The corpus went from 3,034 chunks to 1,720 and from 2.90M characters of stored
content to 1.92M -- which is de-duplication, not loss: a split table repeated
its header on every piece. Measured the same way against the source text, the
new index covers *more* of it than the old, 1.22% of source 5-grams absent
against 2.61%.

**Docling is asked for a heading hierarchy, which it does not build by
default.** `do_pdf_heading_hierarchy` is off in Docling, and the consequence
here was severe: 85 of 86 documents came back with every heading at one level.
The chunker sections on heading depth, so a flat document gives it a list where
it expects a tree, and a chapter with no sub-levels cannot be divided by its own
subsections. Turning it on produced real trees — one policy went from 34
headings all at level 2 to `{2: 2, 3: 6, 4: 26}`.

The crude measure said this changed nothing: chunks trapped in oversized units
moved only from 1,925 to 1,887, and on the ECC guide the count went marginally
*up*. Measured on retrieval instead it was worth 5.8 points of document recall
and 10.8 of clause recall, because better sectioning produces chunks whose text
is more coherent and which therefore embed better. The lesson is about the
metric, not the setting: unit-size statistics are a proxy, and the proxy was
wrong.

**Precision was the wrong lever, and it took four experiments to establish.**
Recall had been measured all along; precision had not, so `eval/retrieval.py`
now reports it alongside, alongside a budget curve computed from a single pass.
On this corpus only 17% of the chunks reaching the drafter sit on a clause the
question asked about, and even the five best-ranked are barely a third — so the
prompt looked badly polluted and cutting it looked obviously right.

It was not. Four ways of raising precision were measured, each scored on
generation with three paired judge passes:

| intervention | precision | accuracy |
|---|---|---|
| relative score floor (0.85) | +3.8 | not run: cost 8.7 recall first |
| smaller per-query `top_k` (5) | +1.0 | not run: cost 4.7 clause recall |
| LLM relevance grader, floor 8 | +4.2 | **-1.3** |
| LLM relevance grader, floor 16 | +2.7 | **-1.9** |

The grader bought more precision than anything else, cut the prompt by 40% with
recall almost intact, and still lost accuracy — in six paired passes across two
settings, never once positive. Raising the protected floor made it worse, which
rules out "the floor was too low".

The conclusion is that the drafter is not much distracted by off-target policy
text, and that the material the metric scores as noise is doing some work: a
definitions section, a neighbouring control, the regulation a policy
implements. `eval/retrieval_targets.json` names only each question's *primary*
sources, so measured precision is a lower bound, and this result says the gap
between it and the truth is wide. Treat the precision figure as a comparator
between configurations, never as a thing to maximise.

The grader survives behind `RELEVANCE_FILTER_ENABLED`, off. It is worth
retrying against a larger golden set, where "relevant" could be defined well
enough for the metric to tell a useful neighbour from a useless one.

**Agreement was counted once per copy, not once per search.** `retrieve` stamps
each chunk with how many of the round's searches returned it, but a chunk six
queries agree on comes back in six batches, and the state reducer sums
`query_hits` when it de-duplicates: six copies each stamped with six
accumulated to thirty-six. The multiplier meant to top out at 1.75 reached 6.4,
and since cosines on policy prose span only 1.5x end to end, ranking was decided
by how many phrasings found a chunk rather than by how well it matched. Fixed by
collapsing duplicates in `retrieve`; measured afterwards, retrieval was
unchanged, because the evidence budget is rarely the binding constraint --
roughly 37 distinct chunks are retrieved and 38 are allowed through, so almost
nothing was being cut and ordering had little to decide.

**The search drawer, and two views of a chunk.** `GET /api/search` runs the
same retrieval the drafter uses, but returns the passages rather than an answer
written from them, so a person can check what the corpus actually says. Three
modes, because the two methods fail in opposite ways: `semantic` finds material
that means the same thing in either language, `keyword` finds the literal
string -- which is what you want when checking whether a policy really says
"90 days" -- and `hybrid` fuses them by reciprocal rank rather than by score,
since a BM25 rank and a cosine are not comparable numbers. A lexical hit is
flagged `is_lexical` so its figure is never read as a similarity. Units are not
expanded here: the answering path completes a split series so the drafter never
mistakes a fragment for the whole list, but a search result should be the chunk
that actually matched.

Chunks render either as the raw Markdown the parser produced or laid out, and
the toggle sits next to the text in both the search drawer and an answer's
citations. The formatted view earns its keep now that tables survive chunking
intact -- but it is also where this feature failed once before, by splitting a
row on the pipe and discarding the first and last field, which is right only
when a row has both an opening and a closing pipe. 1,081 of 3,044 chunks lost
up to 92% of their words and nothing caught it, because a prettier panel still
looks correct.

So `renderChunk` verifies itself: it compares the word multiset of what it
produced against the source text and falls back to raw if one word went
missing. Building that guard found its own bug -- reading the rendered text off
`textContent` concatenates adjacent table cells, so a header row of six cells
reading "Systems" came back as the single word "SystemsSystemsSystems...", and
the check reported a loss on 185 of 194 real chunks. Every one was a false
alarm, and left alone it would have silently disabled the formatted view
entirely. Measured against 246 real chunks -- 136 with tables, 10 Arabic --
after the fix: none loses a word.

**A citation names the file, not just a code.** Answers cite
`T2 - سياسة إدارة كلمات المرور..pdf [PRO-PMP-2024] §5–5.2`, because the internal
document code alone is not something a reader can find in a folder of eighty
files. The code stays alongside it, since assessors ask for it.

**A card lists its sources once.** Under *Sources cited* each citation opens its
clause, with its relevance, the formatted or raw text and a button to open the
document. The card also had an *All n retrieved source(s)* list, which read as
though it held everything the search found. It did not: `finalize` keeps only
the chunks the answer cites, so it showed the same sources a second time --
true of all 1,817 answers stored when it was removed.

**Every answer is reviewed before you see it.** A second model call checks each
claim against the retrieved sources and can send the question back for one more
retrieval round with a differently-worded query. Answers that stay ungrounded,
or that land below the confidence threshold, come back flagged rather than
silently accepted — the failure mode that matters in compliance work is a
confident wrong answer, not a missing one. A mechanical check runs alongside it:
any clause the prose names must appear in something the drafter actually read.

That last distinction is load-bearing. Checking against what the drafter
*listed* as used, rather than what it read, flagged correct answers: asked how
often penetration testing runs, the drafter read both halves of a split policy
section, wrote a correct sentence citing §3.1.20 from the second half, and
listed only the first. The clause existed and was on screen. Support is now
judged against everything retrieved, and the chunk that backs a named clause is
attached to the answer's evidence — so the reader can check it instead of
taking the citation on trust, and "1 supporting source" no longer appears under
an answer built on two.

**Not knowing is a valid answer.** When the knowledge base does not cover a
question, the agent says so and scores itself low instead of inventing a
certification you do not hold.

## A reasoning model's thinking is not the answer

Groq returns a reasoning model's working **inside the message** unless it is
told otherwise: `reasoning_format` defaults to `raw`, which is
`<think>...</think>` in front of the answer. Nothing set it, so a deployment
pointed at a reasoning model -- qwen3, minimax-m2, deepseek-r1 -- answered the
Brief button with *"&lt;think&gt;The user wants me to rewrite the answer to be
more concise..."*. Against `openai/gpt-oss-120b` the same code is fine, because
that model's reasoning comes back in a field of its own.

**Drafting was never affected.** A drafted answer arrives as the arguments of a
tool call, and thinking cannot reach those -- verified against gpt-oss-120b,
qwen3 and minimax-m2, all three clean. What used the model's *plain text* was
rewording (`src/rewrite.py`), the assistant's replies, and query planning --
and query planning already stripped the tags.

So the damage was rewording, which is the Brief button, a house style, a skill,
"make these shorter" and translation. Three things follow from it, and the
third is the one nobody would have noticed:

* The answer card shows the thinking, which is how it was found.
* **`fill` writes it into the customer's file.** A reworded answer is not
  re-reviewed -- that is the point of rewording -- so it keeps the confidence
  the drafted answer earned, is not held back, and goes into the cell.
* **The compliance dropdown is set from it.** The verdict is read from what the
  answer opens with; with thinking in front, the opening verdict is hidden and
  the fallback phrase scan reads the reasoning's words instead. Reasoning about
  a yes talks through the alternatives, so an answer whose prose says *Yes* set
  the customer's dropdown to *Not Applicable*.

The answer memory was not reached: rewording sets `by_hand=False`, and only an
answer a person wrote and approved is remembered.

Two locks now. `GROQ_REASONING_FORMAT` (default `parsed`) asks the provider to
keep the thinking beside the message rather than in it, which is the real fix;
and `formatting.without_reasoning` takes the tags out of anything that arrives
with them anyway -- for a gateway that drops the parameter, or a model that
emits them regardless. It is applied where plain text becomes an answer, where
an answer becomes a cell, and where an answer becomes a verdict. A reply cut off
mid-thought has no answer in it at all, and yields "": the rewording fails and
the answer it was given stays, which is the rule that path already had.

Answers stored while this was broken keep the thinking, and
`python -m scripts.strip_thinking` takes it out (reporting first; `--apply` to
write). An answer that is *only* thinking is reported and left alone: there is
nothing underneath to keep, and a silently blanked answer is worse than an
obviously wrong one.

## A tool call in the model's own dialect

Looking into that turned up something worse on the same deployment, and it is
not about reasoning at all. Qwen-trained models write a tool call as XML:

```
<tool_call><function=AnswerReview><parameter=grounded>
True
</parameter>...
```

Every value there is text, so a boolean field arrives as `"True"` and Groq
refuses the whole call -- *parameters for tool AnswerReview did not match
schema: `/grounded`: expected boolean, but got string*. Against `qwen3.6-27b`
**every review call failed**, under every reasoning format, which means every
question came back unanswered: the drafted answer is thrown away because the
review it has to pass never returns. `minimax-m2` and `gpt-oss-120b` are
unaffected, and drafting alone survives on all three -- `DraftedAnswer` has no
boolean field to trip over, which is why this hid behind the reasoning bug.

`llm._recover_from_tool_use_failed` already pulled a result out of a refused
call when the arguments were valid JSON under the wrong tool name. It now also
reads this dialect, handing the values to the schema as text -- pydantic reads
"True" as true and "0.92" as 0.92 -- and parsing a value that is JSON in its
own right. Measured again on qwen3.6: three review calls in three recovered,
and a question that could not be answered at all now comes back with its
citations. A payload that is not a tool call in any dialect still re-raises;
recovery must not invent a result.

## Language handling

By default each question is answered in the language it was asked in, so a form
that mixes Arabic and English comes back mixed the same way. Pass `language=ar`
or `language=en` to force one language for the whole assessment — the agent will
answer an English question in Arabic from Arabic or English sources, and vice
versa, because BGE-M3 embeds both into one space.

## One embedding per query

Guidelines and prior answers are not two stores. They are one Chroma
collection, `assessment_knowledge`, told apart by a `source_type` filter on the
metadata. Asking for each separately therefore sent the same text to the
embedding service twice and got the same 1024 numbers back -- with query
expansion, two round trips per query and half of the embedding work in a run,
against the slowest and least reliable dependency the system has.

`KnowledgeStore.search_types` embeds the text once and runs one local Chroma
query per source type against that vector. Still one query per type rather than
a single unfiltered one, because the types have different budgets
(`TOP_K_GUIDELINES` against `TOP_K_PRIOR_ANSWERS`): a single search returns the
best `k` regardless of kind, and on a corpus that is almost entirely guidelines
that means prior answers never appear at all.

Two things about this were easy to get wrong, so both are pinned by tests.
The by-vector call returns **raw distances** -- lower is nearer -- where the
by-string call LangChain would otherwise use returns **relevance**, higher is
nearer. Swapping one for the other without applying
`_select_relevance_score_fn` would invert the ranking and silently corrupt the
cosine figure shown to a reader, since `cosine_from_relevance` is calibrated
against that exact scale. And moving the embedding out of Chroma and into this
class meant the fake vector store the suite runs on no longer intercepted it,
so every retrieval test started reaching the network; `_embed_query` exists as
a seam for that reason and the fake answers it.

## Page numbers

Docling emits Markdown with no page information whatsoever, so until now a
citation could name a clause but never a page. It will insert a fixed
placeholder between pages if given one, and the local pdfplumber loader already
emits `--- page N ---` markers that the chunker reads. `docling_client` asks for
the placeholder and rewrites it into those markers, so page numbers reach chunk
metadata without the chunker learning a second convention -- verified against a
nine-page policy, where eight placeholders became nine markers and every one of
its fourteen chunks came out with a page.

Chunks record `page` and `page_end`, because running over a page break is
ordinary -- a table continues, a clause carries on -- and citing only where the
text starts sends a reader to the wrong half of it. The locator shows the page
beside the clause rather than instead of it:

```
T2 - Vulnerabilities Management Policy.pdf §3.1.1 (Page: 3)
T2 - Cybersecurity Incident and Threat Management Policy.docx.pdf §3.1.6 (Pages: 5–6)
T2 -   سياسة إدارة كلمات المرور..pdf [PRO-PMP-2024] §5–5.2 (Page: 4)
```

A clause number says what to look for; the page says where to open the file,
and on a 161-page standard that is the difference between a citation someone
can check and one that merely identifies the text. Because `locator` is a
computed field on `Evidence`, this reaches the citation chips, the retrieved
sources list, the search drawer and both exports without any of them changing.
A document indexed before page markers existed reports no page rather than a
guessed one: an invented page number makes an uncheckable citation look
checkable.

This changes what extraction produces, so `_EXTRACTION_VERSION` is `7` and the
placeholder is part of the cache key. Adopting it means re-extracting the
corpus (Docling, about an hour) and re-indexing (embedding, about 25 minutes).

## Our policy, or a law we are subject to

Sixty-four percent of the indexed corpus -- 1,698 chunks of 2,668 -- is Saudi
national regulation: the PDPL and its implementing regulation, the NCA's ECC
implementation guide, SDAIA's data and AI material. All of it was being handed
to the drafter under a heading that said these documents "state what the
organisation's position is", so it read them as ours and wrote answers like
"PDP.3.2 requires the Entity to develop and document breach management
procedures" as though that described what we do -- at 0.90 confidence, destined
for a customer's file.

Deleting the regulation would fix that and lose more: "are you compliant with
PDPL?" is a real question and needs the law to answer it. So the distinction is
recorded instead. Each source arrives labelled `OUR POLICY` or `EXTERNAL
REQUIREMENT (not our document)`, and the prompt draws the line: our policy says
what we *do*, a regulation says what we are *required* to do, and only the first
supports a claim about us. Where the law requires something no policy of ours
covers, that gap is the honest answer and is exactly what an assessment is for.

Uploads **ask** rather than infer, because a file name is not evidence: the
`DataClassificationPolicy.pdf` in this corpus is the regulator's, not ours, and
reads exactly like one of ours. `scripts/classify_corpus.py` backfilled what was
already indexed -- metadata only, since the text has not changed and so the
vectors have not either -- with a dry run first, and it names the three scanned
files it will not guess about rather than quietly deciding.
