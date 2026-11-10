"""X 卡片渲染。

**为什么用 x-post2image-2page 而不是主版本。**
主版本 2.1.5 的跨页在长文上会自动扩到三张（实测同一篇 1604×687，三页并排）；
而页面上要的是**两张横排**。2.1.0 的跨页给 1080×900，正是两张。所以渲染走 2.1.0 那份，
主版本仍然装着、也仍然是最新的 —— 等上游支持「最多两页」再切回去。

规则和 skill 一致：
  · 短帖（≤ 400 字）→ 单页原生卡片，字号正常；
  · 长帖 → 跨页两栏，页高 900。
"""

from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

#: 页面里出现的 X 原帖链接。只认 status，不认主页、话题页和转推短链。
_X_STATUS = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status/(\d{6,25})"
)

#: 渲染器：两页版（见模块开头）。
CLI = Path.home() / ".agents" / "skills" / "x-post2image-2page" / "scripts" / "x-post2image.mjs"

#: 卡片统一宽度。
CARD_W = 1080

#: 跨页的页高。900 是两页版里唯一稳定给出「两张」的值。
SPREAD_HEIGHT = 900

#: 超过这个字数按跨页渲染。
LONG_THRESHOLD_CHARS = 400

#: 一期最多几张卡。
MAX_CARDS = 4


@dataclass(slots=True)
class XPost:
    url: str
    author: str = ""
    handle: str = ""
    text: str = ""
    translated: str = ""
    image: str = ""
    width: int = 0
    height: int = 0
    likes: str = ""
    reposts: str = ""
    views: str = ""
    layout: str = "single"


def extract_posts(html: str) -> list[tuple[str, str]]:
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for user, status in _X_STATUS.findall(html or ""):
        if status in seen:
            continue
        seen.add(status)
        out.append((user, status))
    return out


def _run(url: str, target: Path, layout: str) -> dict | None:
    cmd = [
        "node", str(CLI), url,
        "--out", str(target),
        "--theme", "light",
        "--layout", layout,
        "--translate", "zh-CN",
        "--json",
    ]
    if layout == "spread":
        cmd.extend(["--long-height", str(SPREAD_HEIGHT)])
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=240)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or not target.exists():
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"url": url}


def render(post_id: str, url: str, out_dir: Path) -> XPost | None:
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{post_id}.png"

    payload = _run(url, target, "single")
    if payload is None:
        return None
    layout = "single"

    if len(payload.get("text") or "") > LONG_THRESHOLD_CHARS:
        spread = _run(url, target, "spread")
        if spread is not None:
            payload = spread
            layout = "spread"

    author = payload.get("author") or {}
    if isinstance(author, dict):
        name = author.get("name") or ""
        handle = author.get("handle") or author.get("screen_name") or ""
    else:
        name, handle = str(author), ""
    metrics = payload.get("metrics") or {}
    translation = payload.get("translation") or {}
    return XPost(
        url=payload.get("url") or url,
        author=name,
        handle=handle,
        text=(payload.get("text") or "").strip(),
        translated=(translation.get("text") or "").strip() if isinstance(translation, dict) else "",
        image=target.name,
        width=int(payload.get("width") or 0),
        height=int(payload.get("height") or 0),
        likes=str(metrics.get("likes") or ""),
        reposts=str(metrics.get("reposts") or ""),
        views=str(metrics.get("views") or ""),
        layout=layout,
    )


def collect(pages: list[str], out_dir: Path, *, limit: int = MAX_CARDS) -> list[XPost]:
    posts: list[XPost] = []
    seen: set[str] = set()
    for html in pages:
        for _user, status in extract_posts(html):
            if status in seen:
                continue
            seen.add(status)
            rendered = render(status, f"https://x.com/i/status/{status}", out_dir)
            if rendered is not None:
                posts.append(rendered)
            if len(posts) >= limit:
                return posts
    return posts


def dump(posts: list[XPost], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    rows = [
        {
            "url": p.url, "author": p.author, "handle": p.handle, "text": p.text,
            "translated": p.translated, "image": p.image, "width": p.width,
            "height": p.height, "likes": p.likes, "reposts": p.reposts,
            "views": p.views, "layout": p.layout,
        }
        for p in posts
    ]
    path.write_text(json.dumps(rows, ensure_ascii=False, indent=1), encoding="utf-8")
