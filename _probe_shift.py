"""How common is the merged-cell / shifted-column failure, corpus-wide?

Detected by signature, not by eye:
  * doubled  - one cell holding the same phrase twice ("Immediate Immediate"),
               which is two columns collapsed into one;
  * ragged   - a body row whose cell count differs from the header's;
  * leading  - a row whose first cell is empty while later cells carry content,
               the shape a displaced row-label leaves behind.
"""
import json, re
from collections import Counter
import src.chunking as ck
import src.service as service
from src.config import settings

names = json.load(open("_indexed_docs.json", encoding="utf-8"))

def doubled(cell: str) -> bool:
    words = cell.split()
    n = len(words)
    return n >= 2 and n % 2 == 0 and words[: n // 2] == words[n // 2 :]

tally = Counter()
examples = {"doubled": [], "ragged": [], "leading": []}
per_doc = Counter()

for n in names:
    cache = service._extracted_text_cache_path(settings.upload_dir / n)
    if not cache.exists():
        continue
    lines = ck.strip_bidi(cache.read_text(encoding="utf-8")).splitlines()
    i = 0
    while i < len(lines):
        if not ck._TABLE_ROW.match(lines[i]):
            i += 1
            continue
        j = i
        while j < len(lines) and ck._TABLE_ROW.match(lines[j]):
            j += 1
        rows = [r for r in ck.compact_table(lines[i:j]) if not ck._TABLE_SEP.match(r.strip())]
        tally["tables"] += 1
        if rows:
            width = len(ck._cells(rows[0]))
            tally["rows"] += len(rows)
            for r in rows:
                cells = ck._cells(r)
                if len(cells) != width:
                    tally["ragged"] += 1
                    if len(examples["ragged"]) < 3: examples["ragged"].append((n, r[:110]))
                if any(doubled(c) for c in cells if c):
                    tally["doubled"] += 1; per_doc[n] += 1
                    if len(examples["doubled"]) < 6: examples["doubled"].append((n, r[:110]))
                if len(cells) > 2 and not cells[0] and any(cells[1:]):
                    tally["leading"] += 1
                    if len(examples["leading"]) < 3: examples["leading"].append((n, r[:110]))
        i = j

print(f"tables            {tally['tables']:,}")
print(f"rows              {tally['rows']:,}")
for k in ("ragged", "doubled", "leading"):
    print(f"{k:18s}{tally[k]:,}  ({100*tally[k]/max(tally['rows'],1):.2f}% of rows)")
print("\ndocuments with the most doubled-cell rows:")
for n, c in per_doc.most_common(6):
    print(f"  {c:4d}  {n[:66]}")
print("\nexamples:")
for kind, rows in examples.items():
    for n, r in rows:
        print(f"  [{kind}] {n[:34]:34s} {r}")
