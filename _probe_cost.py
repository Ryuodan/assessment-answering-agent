"""Does the relevance grader actually save anything?

The prompt shrinks, but every retrieved chunk is paid for again at the grader.
Counted in tokens, not characters, because Arabic tokenizes at roughly a third
the density of English and this corpus is half Arabic -- a character count
would flatter whichever side carries more Arabic.
"""
import json
import tiktoken
from src.config import settings
from src.prompts import RELEVANCE_SYSTEM

enc = tiktoken.get_encoding("cl100k_base")
def toks(text: str) -> int:
    return len(enc.encode(text))

# Measured per-question figures from the retrieval passes.
BASE_PROMPT_CHARS, BASE_CHUNKS = 30_456, 33.4      # e38, no grader
GRAD_PROMPT_CHARS, GRAD_CHUNKS = 18_365, 20.2      # grader, keep 8
RETRIEVED = 37.5                                   # graded every round
ATTEMPTS_BASE, ATTEMPTS_GRAD = 1.05, 1.10
SOURCES_PER_ATTEMPT = 2                            # draft and review both carry it

# Token density measured on this corpus's own chunk text, English and Arabic.
sample = json.load(open("eval/results/r21_depad1200_e38.json", encoding="utf-8"))["answers"]
snips = [e["snippet"] for a in sample for e in a["evidence"]]
density = sum(toks(s) for s in snips) / max(sum(len(s) for s in snips), 1)
print(f"measured token density on this corpus: {density:.3f} tokens/char "
      f"({1/density:.2f} chars per token)\n")

def sources_tokens(chars, attempts):
    return chars * density * SOURCES_PER_ATTEMPT * attempts

base = sources_tokens(BASE_PROMPT_CHARS, ATTEMPTS_BASE)
grad = sources_tokens(GRAD_PROMPT_CHARS, ATTEMPTS_GRAD)

# Grader input: every retrieved chunk, truncated, once per retrieval round,
# plus the system prompt on every batch.
batches = -(-int(RETRIEVED) // settings.relevance_filter_batch)
grader_in = (
    RETRIEVED * settings.relevance_filter_snippet * density
    + batches * toks(RELEVANCE_SYSTEM)
) * ATTEMPTS_GRAD

print(f"{'per question':34s}{'tokens':>12s}")
print(f"{'sources in draft+review, no grader':34s}{base:>12,.0f}")
print(f"{'sources in draft+review, grader':34s}{grad:>12,.0f}")
print(f"{'  saved on drafting':34s}{base-grad:>12,.0f}")
print(f"{'grader input (%d batches)' % batches:34s}{-grader_in:>12,.0f}")
print(f"{'  NET':34s}{base-grad-grader_in:>+12,.0f}")
print()
verdict = "saves" if base - grad - grader_in > 0 else "COSTS"
print(f"=> the grader {verdict} {abs(base-grad-grader_in):,.0f} tokens per question")
print(f"   over 42 questions: {abs(base-grad-grader_in)*42:,.0f} tokens")
