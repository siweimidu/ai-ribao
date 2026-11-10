"""把那几个会露出 X 原帖的页面取回来，渲染今天的卡片。"""

from __future__ import annotations

import io
import sys
import urllib.request
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
sys.path.insert(0, "src")

from aidaily.xhigh import collect, dump, extract_posts  # noqa: E402

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
PAGES = [
    "https://aihot.news/daily",
    "https://daily.juya.uk/",
]

html_pages: list[str] = []
for url in PAGES:
    try:
        html_pages.append(urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40)
                          .read().decode("utf-8", "replace"))
        print("  取到:", url)
    except Exception as exc:  # noqa: BLE001
        print("  跳过:", url, type(exc).__name__)

total = sum(len(extract_posts(h)) for h in html_pages)
print("  页面里的原帖合计:", total)

out_dir = Path("data/digests/site/assets/x")
posts = collect(html_pages, out_dir, limit=4)
print("  渲染成功:", len(posts))
for post in posts:
    print("   ", post.image, post.width, "x", post.height, "|", post.author[:18], "|", post.text[:34])

dump(posts, Path("data/state/x-highlights.json"))
print("  已写入 data/state/x-highlights.json")
