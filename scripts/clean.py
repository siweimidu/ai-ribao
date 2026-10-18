import io, json, sys
from datetime import datetime, timezone
from pathlib import Path
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from aidaily.history import PublishedHistory
from aidaily.models import Event

root = Path(r"D:\Code\AI日报")
out = root / "data" / "digests"
dates = sorted(p.stem for p in out.glob("2026-*.json"))

for date in dates:
    tmp = root / "data" / "state" / "hd"
    tmp.mkdir(exist_ok=True)
    for f in tmp.glob("*.json"):
        f.unlink()
    for d in dates:
        if d < date:
            (tmp / (d + ".json")).write_text((out / (d + ".json")).read_text(encoding="utf-8"), encoding="utf-8")
    h = PublishedHistory(root / "data" / "state" / "hd.jsonl", window_days=7)
    h.rebuild_from_archives(tmp)
    h.load()

    payload = json.loads((out / (date + ".json")).read_text(encoding="utf-8"))
    ins = payload.get("insights") or {}
    doc = payload["digest"]

    drop = []
    for e in doc["top_events"]:
        t = (ins.get(e["event_id"]) or {}).get("title") or e["title"]
        rep = h.find_repeat(Event.model_validate(dict(e, title=t)), today=date,
                            now=datetime.now(timezone.utc))
        if rep is not None:
            drop.append((e["event_id"], rep.matched_on, rep.days_ago, t))

    for f in tmp.glob("*.json"):
        f.unlink()
    tmp.rmdir()
    (root / "data" / "state" / "hd.jsonl").unlink(missing_ok=True)

    print("  %s  %d 条，剔除 %d" % (date, len(doc["top_events"]), len(drop)))
    for _, kind, days, t in drop:
        print("      X %-8s %d天前  %s" % (kind, days, t[:50]))

    if not drop:
        continue
    ids = {i for i, _, _, _ in drop}
    doc["top_events"] = [e for e in doc["top_events"] if e["event_id"] not in ids]
    doc["counts"] = dict(doc.get("counts") or {})
    doc["counts"]["events"] = len(doc["top_events"])
    payload["sections"] = {c: [i for i in v if i not in ids]
                          for c, v in (payload.get("sections") or {}).items()}
    payload["sections"] = {c: v for c, v in payload["sections"].items() if v}
    payload["insights"] = {k: v for k, v in ins.items() if k not in ids}
    (out / (date + ".json")).write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")

h = PublishedHistory(root / "data" / "state" / "published_history.jsonl", window_days=7)
print()
print("历史重建：%d 条" % h.rebuild_from_archives(out))