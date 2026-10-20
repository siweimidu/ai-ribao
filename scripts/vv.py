import io, sys
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

# Exercise every analyzer path that formats a date, the way publish does.
from aidaily.analyze import _materials, _DISPLAY_TZ
from aidaily.models import NormalizedItem
from datetime import datetime, timezone

ts = datetime(2026, 10, 19, 21, 47, tzinfo=timezone.utc)
item = NormalizedItem(
    item_id="i1", source_id="rss:x", title="测试", title_norm="测试",
    url="https://example.com/a", canonical_url="https://example.com/a",
    published_at=ts, fetched_at=ts, first_seen_at=ts, updated_at=ts,
    summary="摘要", content_text="正文", content_sha256="0" * 64, simhash=0, language="zh",
)
out = _materials([item])
print("  _materials 正常运行：")
for line in out.splitlines()[:2]:
    print("    " + line[:80])
print()
print("  含北京时间: %s" % ("北京时间" in out))
print("  含 UTC: %s" % ("UTC" in out))