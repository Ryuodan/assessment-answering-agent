# Time, cost and storage

Where the time of a request goes, what it costs, and how storage is kept within a limit.

Moved from the README (plan 009); the text is as it was written there, with links re-pointed.

## Where the time goes

Measured by wrapping each graph node and each remote call, rather than
estimated.

**Answering one question: about 13 seconds, three quarters of it Groq.**

| stage | median | share |
|---|---|---|
| plan | 4.0 s | 38% |
| retrieve | 0.7 s | 6% |
| rerank | 0.00 s | — (off) |
| draft | 2.4 s | 19% |
| review | 3.0 s | 24% |
| finalize | 0.00 s | — |

The planner is the largest single item, larger than drafting: it is a
structured-output call, and Groq's tool-calling overhead is fixed while the
prompt is too short to amortise it. Retrieve looks cheap and is not idle --
54 vector searches summing to 81.9 s of service time compress into 12.8 s of
wall clock, which is the concurrency inside that node doing its job.

Retrieve was 2.24 s until an empty collection stopped being searched. The query
is embedded *before* the source-type filter is applied, so asking a
prior-answers collection holding zero chunks still cost a full remote round
trip -- five or six per question, against the slowest and least reliable
dependency in the system. `retrieve` now consults the cached per-type counts
first. That also meant the evidence split could no longer be positional:
`results[0::2]` and `[1::2]` assumed every query produced exactly one search of
each kind, which is false the moment one is skipped, and would have labelled
guideline chunks as prior answers.

**Indexing is 99.8% embedding, and none of it is ours to fix.**

| stage | share |
|---|---|
| extract (cache hit) | 0.1% |
| chunk | 0.1% |
| embed + store | 99.8% |

293 ms per chunk. The client already batches at 64 per request, and the
endpoint is flat at roughly 5.1 texts/s no matter how it is asked:

```
embed_documents(  1)   757 ms/text        1 parallel batch    5.1 texts/s
embed_documents( 64)   197 ms/text        2 parallel batches  5.3 texts/s
embed_documents(128)   198 ms/text        8 parallel batches  5.1 texts/s
```

It is serialised server-side, so neither larger batches nor more connections
help. 2,698 chunks is about nine minutes of pure embedding; the rest of a
24-minute re-index is per-document overhead. The only levers are fewer chunks
or a faster embedding service.

Extraction is the other order of magnitude: **0.002 s from cache against 61.6 s
through Docling**, which is why `data/extracted` is worth keeping alongside the
index rather than regenerating.

**`MAX_CONCURRENT_QUESTIONS` buys latency and nothing else.** Twelve real
questions, same corpus, same models:

```
concurrency 1:  121.1 s (10.1 s each)   0 errors   0 rate limits   mean confidence 0.83
concurrency 4:   36.0 s ( 3.0 s each)   0 errors   0 rate limits   mean confidence 0.84
```

Answer order, question-to-answer mapping and citation counts are unchanged,
because `asyncio.gather` returns in argument order regardless of completion
order and each question owns its state. `tests/test_concurrency.py` pins that
at 1, 2, 4 and 8 with completion order deliberately reversed -- the arrangement
a collector that appended results as they arrived would get wrong while looking
correct serially -- along with the cap actually being honoured, a failure
staying contained, and the document fan-out reading the same setting through
LangGraph's `max_concurrency`.

## Keeping storage within a limit

Questionnaires arrive from other companies and are confidential, and every one
uploaded used to stay on the server for good, with its filled copy beside it.
Each person now has a **storage limit**, `STORAGE_LIMIT_PER_USER_MB` (2 GB by
default) -- per person because that is who a questionnaire belongs to. The rule
is deliberately lopsided:

* **Under the limit, nothing is touched**, however old it is.
* **Over it, the work they have not come back to longest goes first** -- the
  uploaded questionnaire, its filled copy, and the text read out of it -- until
  they are under again. Between a file and its filled copy the copy goes first,
  because pressing *Fill* writes it again and nothing brings back an upload.

Two things are never removed, whatever the limit says:

* **A document the team's knowledge base was built from.** Policies belong to
  the team rather than to whoever uploaded them, and count against nobody.
* **Anything used in the last `STORAGE_KEEP_DAYS` days** (30). A questionnaire
  uploaded a year ago and answered this week is in use: "last used" is the
  later of the file's own date and the last change to any batch reading it --
  anybody's batch, since two people can be reading one file from before uploads
  were kept per person.

The second rule is what makes a forgotten limit harmless. The limit is a number
somebody chose for the usage they had then; if somebody's workload grows and
nobody raises it, they simply stay over the limit, and the log says so and names
the setting, rather than a questionnaire disappearing from under the person
answering it. A new colleague brings their own allowance, so nothing has to be
raised because the team grew.

The answers themselves are never removed -- only files. A batch whose upload
has gone keeps every answer, and says, when somebody presses *Fill*, that the
file has to be uploaded again. Every removal is recorded as a `files_removed`
event against the person, naming the files.

Everybody is checked when the server starts and every hour after -- everybody
who can sign in, and everybody a questionnaire is recorded against, which is not
the same list: somebody removed from the access panel leaves their files behind,
and those still age out. Under the limit a check costs two directory listings;
the index is only opened when there is something to decide.
`STORAGE_LIMIT_PER_USER_MB=0` turns it off. At the time of writing the whole
deployment stores 125 MB.

## Cost of a request

A 16-way concurrent burst of 48 requests took 30.8 seconds and now takes 7.8.
Almost all of it was bookkeeping rather than work:

| | before | after |
|---|---|---|
| search, median | 10.97 s | **2.37 s** |
| search, p95 | 12.69 s | **2.93 s** |
| `/api/knowledge` | 7.22 s | **2.08 s** |

Three things were being recomputed that never change between writes. Counting
chunks per source type and listing indexed file names were a full metadata scan
each -- 216 ms and 207 ms against a search that itself takes 45 ms, so nine
tenths of a search was overhead, and `stats()` repeated the same scan on every
page load. They share one cached catalog now, invalidated exactly where the
lexical index already was. Separately, the literal matcher was building a BM25
index it never consults, 511 ms of tokenising per process for a substring
query; the chunk map it actually wants is now cached on its own. Both builds
are locked, so a concurrent burst builds once rather than once per thread.

The caching is only as good as its invalidation, so `tests/test_store_caches.py`
exercises every write path: a new document appears immediately, a deleted one
disappears, a re-upload replaces rather than duplicates, and a document added
after the first search is visible to the next one.
