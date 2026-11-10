"""X 卡片渲染：一律用最新版 x-post2image，版式交给它自己判断。

规范（SKILL.md）：正文 ≥ 360 字自动切成 X 官方风格长卡；长卡高过 1400px 再自动变左右多页；
内容更多时才扩到三张。**所以不传 `--layout`、不传 `--long-height`** —— 任何手写的分支和
固定页高都会盖掉规范里的判断，前面就是那样把两张顶成了三张、又把三张压回两张。
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

#: 渲染器：用户级 skills 目录里的最新版本。
CLI = Path.home() / ".agents" / "skills" / "x-post2image" / "scripts" / "x-post2image.mjs"

#: 卡片统一宽度。单页原生 1200，跨页 1604；统一到 1080 后页面里才齐。
CARD_W = 1080

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
    layout: str = "auto"


def extract_posts(html: str) -> list[tuple[str, str]]:
    """页面里出现过的原帖，按 id 去重并保持出现顺序。"""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for user, status in _X_STATUS.findall(html or ""):
        if status in seen:
            continue
        seen.add(status)
        out.append((user, status))
    return out


def render(post_id: str, url: str, out_dir: Path) -> XPost | None:
    """渲染一张卡片。版式交给渲染器，失败返回 None，绝不编造。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{post_id}.png"
    cmd = [
        "node", str(CLI), url,
        "--out", str(target),
        "--theme", "light",
        "--translate", "zh-CN",
        "--json",
    ]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=300)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or not target.exists():
        return None
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        payload = {"url": url}

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
        layout=str(payload.get("layout") or "auto"),
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
