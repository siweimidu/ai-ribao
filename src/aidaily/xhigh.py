"""X 精选：从今天抓到的页面里取出 X 原帖，渲染成卡片。

**为什么从这个方向取帖，而不是自己去 X 搜索。**

X 没有可靠的公开搜索接口：关键词搜索要登录、要浏览器，还要处理限流。而「已经收进来的源」
本来就会把当天的原帖链出来 —— 实测 2026-11-10 的 aihot 日报页面上有 4 个不同的
`x.com/<user>/status/<id>`。这些是编辑挑过的帖子，不是关键词撞出来的噪声。

**卡片尺寸分两档。** 短帖走原生单页卡片，正文是 X 的正常字号；超过阈值的才摊成左右两页。
一刀切全都跨页，会把短帖也压成小字；一刀切都不跨页，长帖会变成一根竖条，缩到页面宽度后
根本看不清。分流看的是渲染出来的真实高度，不是猜字数。
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

#: 渲染器所在位置。装到用户级 skills 目录的那一份。
SKILL = Path.home() / ".agents" / "skills" / "x-post2image"
CLI = SKILL / "scripts" / "x-post2image.mjs"

#: 卡片统一尺寸。跨页原生输出 1080×H，单页 1200 宽；统一到 1080 宽、1000 高后并排才齐。
CARD_W = 1080
CARD_H = 1400

#: 超过这个高度（CSS px）的帖子改用跨页。原生单页卡片宽 600 CSS px，正文正常大小；
#: 再长就成了一根竖条，缩到页面宽度后字看不清 —— 那时候才摊成两页。
LONG_THRESHOLD_CHARS = 400

#: 一期最多几张卡。卡片是重内容（每张几十 KB + 一次外部请求），不是越多越好。
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
    layout: str = "single"


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


def _run(url: str, target: Path, layout: str) -> dict | None:
    """跑一次渲染，返回 CLI 的 JSON；失败返回 None。"""
    cmd = [
        "node", str(CLI), url,
        "--out", str(target),
        "--theme", "light",
        "--layout", layout,
        "--translate", "zh-CN",
        "--json",
    ]
    if layout == "spread":
        # 不传 --long-height：让渲染器按内容决定页高。写死高度会在内容少的帖子上
        # 补出上千像素空白（实测 Google/Higgsfield 两页下面空了一大片）。
        pass
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", timeout=180)
    except (OSError, subprocess.TimeoutExpired):
        return None
    if done.returncode != 0 or not target.exists():
        return None
    try:
        return json.loads(done.stdout)
    except ValueError:
        return {"url": url, "width": 0, "height": 0}


def render(post_id: str, url: str, out_dir: Path) -> XPost | None:
    """渲染一张卡片：短帖单页，长帖跨页。渲染失败返回 None，绝不编造。"""
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / f"{post_id}.png"

    payload = _run(url, target, "single")
    if payload is None:
        return None
    layout = "single"

    # **只用单页卡片。** 跨页那种两页并排的版式在真实帖子上问题太多：右页经常半空、
    # 长帖被压成一堆小字、原帖配图不显示。单页是 X 自己的版式，字号正常、配图在、
    # 头像和蓝 V 都对 —— 高度参差由页面布局吸收，不为整齐去牺牲可读性。

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
