import io, json, sys
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from aidaily.config import load_config
from aidaily.models import Digest, NormalizedItem
from aidaily.rank import rank_events
from aidaily.registry import apply_overrides, load_overrides, load_registry

root = Path(r"D:\Code\AI日报")
out = root / "data" / "digests"
path = out / "2026-10-17.json"
payload = json.loads(path.read_text(encoding="utf-8"))
ins = payload.get("insights") or {}
doc = dict(payload["digest"])
by_id = {e["event_id"]: e for e in doc.get("top_events", [])}
doc["sections"] = {c: [by_id[i] for i in ids if i in by_id] for c, ids in (payload.get("sections") or {}).items()}
digest = Digest.model_validate(doc)

cfg = load_config(env={})
specs, _ = apply_overrides(load_registry(), load_overrides())

items = []
for e in digest.top_events:
    for mid in e.member_item_ids:
        items.append(NormalizedItem(
            item_id=mid, source_id=e.source_ids[0] if e.source_ids else "x",
            title=e.title, title_norm=e.title.lower(),
            url=e.all_urls[0] if e.all_urls else "",
            fetched_at=e.first_seen_at, first_seen_at=e.first_seen_at,
            updated_at=e.last_updated_at, content_sha256="0"*64, simhash=0))

ordered = rank_events(digest.top_events, items, specs, now=digest.generated_at)
print("重排后前 8：")
for i, r in enumerate(ordered[:8], 1):
    t = (ins.get(r.event.event_id) or {}).get("title") or r.event.title
    print("  %2d. %6.2f src=%-2d %s" % (i, r.score, len(r.event.source_ids), t[:52]))
print()
print("事件数 %d → %d" % (len(digest.top_events), len(ordered)))