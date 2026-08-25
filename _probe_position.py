"""Does the drafter actually read past the top of a 38-chunk prompt?

Capacity is not the question -- the sources block is about 6,100 tokens against
a 131k window. The question is attention: if citations only ever come from the
first few sources, the later ones are being paid for and ignored, and "lost in
the middle" is real here.

Measured by mapping each answer's citations back to the position the cited
chunk occupied in the sources block it was shown.
"""
import json
from collections import Counter

def positions(path):
    answers = json.load(open(path, encoding="utf-8"))["answers"]
    hits, shown = Counter(), Counter()
    for a in answers:
        locators = {c for c in (a.get("citations") or [])}
        for index, e in enumerate(a["evidence"], start=1):
            shown[index] += 1
            if e.get("locator") in locators:
                hits[index] += 1
    return hits, shown, answers

hits, shown, answers = positions("eval/results/r21_depad1200_e38.json")
total_shown = sum(shown.values())
total_hits = sum(hits.values())
print(f"answers {len(answers)}   sources shown {total_shown}   cited {total_hits}\n")

bands = [(1, 5), (6, 10), (11, 15), (16, 20), (21, 30), (31, 60)]
print(f"{'position in prompt':22s}{'shown':>8s}{'cited':>8s}{'cite rate':>11s}")
for lo, hi in bands:
    s = sum(shown[i] for i in range(lo, hi + 1))
    h = sum(hits[i] for i in range(lo, hi + 1))
    if s:
        print(f"  {lo:2d}-{hi:<17d}{s:>8d}{h:>8d}{100*h/s:>10.1f}%")

deep = sum(h for i, h in hits.items() if i > 15)
print(f"\ncitations from beyond position 15: {deep} of {total_hits} ({100*deep/max(total_hits,1):.0f}%)")
