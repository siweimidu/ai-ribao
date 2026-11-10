"""X 精选：从今天抓到的页面里取出 X 原帖，渲染成卡片，供网站的一个栏位使用。

**为什么从这个方向取帖，而不是自己去 X 搜索。**

X 没有可靠的公开搜索接口：关键词搜索要登录、要浏览器，还要处理限流。而「已经收进来的源」
本来就会把当天的原帖链出来 —— 实测 2026-11-10 的 aihot 日报页面上有 4 个不同的
`x.com/<user>/status/<id>`。这些是编辑挑过的帖子，不是关键词撞出来的噪声。

所以这一层的职责很窄：**找出今天页面里出现过的原帖，渲染卡片，给出摘要与来源链接。**
发现（看哪些页面）由既有采集决定，不是这里重新发明一遍。
"""

from __future__ import annotations

import io
import json
import re
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

#: 页面里出现的 X 原帖链接。只认 status，不认主页、话题页和转推短链。
_X_STATUS = re.compile(
    r"https?://(?:www\.|mobile\.)?(?:x|twitter)\.com/([A-Za-z0-9_]{1,20})/status/(\d{6,25})"
)

#: 渲染器所在位置。装到用户级 skills 目录的那一份。
SKILL = Path.home() / ".agents" / "skills" / "x-post2image"
CLI = SKILL / "scripts" / "x-post2image.mjs"

#: 卡片统一尺寸。spread 的原生输出就是 1080×900，短帖补边到同一高度，并排时才齐。
CARD_W = 1080
CARD_H = 900

#: 一期最多几张卡。卡片是重内容（每张 40 KB 上下 + 一次外部请求），不是越多越好。
MAX_CARDS = 4


@dataclass(slots=True)
class XPost:
    """一张渲染好的帖子卡片。"""

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


def render(post_id: str, url: str, out_dir: Path, *, timeout: int = 120) -> XPost | None:
    """把一条帖子渲染成 PNG，返回它的元数据。渲染失败返回 None，绝不编造。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{post_id}.png"
    # `--layout spread` 是参考站那种「两页并排」的横版：长帖被摊成左右两栏，
    # 高度靠 `--long-height` 固定，短帖只占一页。默认的 single 会把长帖拉成一根竖条，
    # 缩到页面宽度后字小到看不清。
    cmd = [
        "node",
        str(CLI),
        url,
        "--out",
        str(target),
        "--theme",
        "light",
        "--layout",
        "spread",
        "--long-height",
        str(CARD_H),
        "--translate",
        "zh-CN",
        "--json",
    ]
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=timeout)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or not target.exists():
        return None
    try:
        payload = json.loads(done.stdout)
    except ValueError:
        payload = {}
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
    )


def collect(pages: list[str], out_dir: Path, *, limit: int = MAX_CARDS) -> list[XPost]:
    """从若干页面 HTML 里取帖并渲染，最多 `limit` 张。"""
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
    payload = [p.__dict__ if hasattr(p, "__dict__") else {
        "url": p.url, "author": p.author, "handle": p.handle, "text": p.text,
        "translated": p.translated, "image": p.image, "width": p.width,
        "height": p.height, "likes": p.likes, "reposts": p.reposts, "views": p.views,
    } for p in posts]
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    page = Path(sys.argv[1]).read_text(encoding="utf-8") if len(sys.argv) > 1 else ""
    print("  页面里的原帖:", len(extract_posts(page)))
