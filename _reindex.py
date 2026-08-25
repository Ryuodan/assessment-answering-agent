"""Re-index the indexed documents from cached text, at the configured chunk size."""
import asyncio, json, time
from src import service
from src.config import settings
from src.models import SourceType

names = json.load(open("_indexed_docs.json", encoding="utf-8"))

async def main():
    print(f"chunk_size={settings.chunk_size}", flush=True)
    service.clear_knowledge()
    started, total, failed = time.time(), 0, []
    for i, n in enumerate(names, 1):
        try:
            r = await service.ingest(settings.upload_dir / n, SourceType.GUIDELINE)
            total += r.chunks_indexed
            if r.error:
                failed.append((n, r.error))
        except Exception as exc:
            failed.append((n, str(exc)[:120]))
        if i % 10 == 0 or i == len(names):
            print(f"[{i:3d}/{len(names)}] {total:6,} chunks {time.time()-started:6.0f}s", flush=True)
    print(f"DONE {total:,} chunks in {time.time()-started:.0f}s")
    for n, e in failed:
        print("FAILED", n, e)

asyncio.run(main())
