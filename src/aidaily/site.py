"""Static site generator for the digest.

Design decisions, and why each is not a default:

* **The arc is `editorial`, not `broadside`.** A daily digest is read, not watched.
  Motion is spent on the reading act (the row you point at leans and breathes) rather
  than on an opening flourish.
* **Three different section shapes.** A page where every band is "headline + centred
  paragraph" reads as a template even with perfect type. The masthead is a two-column
  band, the event list is an indexed asymmetric grid, the archive is a dense table.
* **The type scale is ~5.3x, not ~1.5x.** Body is 15px; the display line runs to 80px.
  Pages with everything between 16 and 48px are the single most common tell of an
  undesigned page.
* **Only real numbers appear.** No "+47% conversion", no "trusted by 50,000 teams".
  Every figure printed here was counted by the run that produced it.
* **Text is never hidden behind motion.** The reduced-motion branch is the same page
  without the springs, and it is the branch that must survive being screenshotted.

Everything is server-rendered into one HTML file per day plus an index. No client-side
framework: the page has to work if JavaScript never arrives.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .analyze import EventInsight
from .models import Digest, Event, NormalizedItem

#: Category labels. The section a story lands in is decided by its *source*, not by the
#: model: a model-assigned category could move a story somewhere that misrepresents it.
CATEGORY_LABELS = {
    "lab-official": "官方发布",
    "lab-blog": "实验室博客",
    "zh-media": "中文媒体",
    "media": "科技媒体",
    "paper": "论文与研究",
    "digest": "行业简报",
    "community": "社区讨论",
    "dev": "开发者动态",
    "model": "模型与数据集",
    "product": "产品发布",
    "search": "检索聚合",
    "trend": "趋势信号",
    "preset": "预设源",
    "example": "示例源",
}

FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='7' fill='%230065fd'/%3E"
    "%3Cpath d='M9 21.5 14.2 10.5h3.6L23 21.5h-3.3l-1-2.3h-5.4l-1 2.3z' fill='white'/%3E"
    "%3C/svg%3E"
)


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def _domain(url: str) -> str:
    try:
        host = url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url[:40]
    return host[4:] if host.startswith("www.") else host


def _when(event: Event) -> tuple[str, bool]:
    """(display text, is_known). An unknown date says so rather than showing a guess."""
    if not event.published_range:
        return "时间未知", False
    when = event.published_range[0].astimezone(timezone.utc)
    return when.strftime("%m-%d %H:%M UTC"), True


def _facts_block(rows: list[str], kind: str, label: str) -> str:
    if not rows:
        return ""
    items = "".join(f"<li>{esc(r)}</li>" for r in rows[:5])
    return (
        f'<span class="fact-label">{esc(label)}</span>'
        f'<ul class="facts" data-kind="{kind}">{items}</ul>'
    )


def _row(
    index: int,
    event: Event,
    insight: EventInsight | None,
    *,
    enter: bool = False,
) -> str:
    title = (insight.title if insight and insight.title else event.title) or event.title
    first_url = event.all_urls[0] if event.all_urls else "#"
    when_text, known = _when(event)

    body = ""
    if insight:
        body += _facts_block(insight.facts, "fact", "事实")
        body += _facts_block(insight.inferences, "inference", "推断")
        body += _facts_block(insight.uncertainties, "uncertain", "不确定")
    if insight is None or insight.rule_based:
        body += '<span class="fact-label">本条为来源原文摘录（未调用大模型）</span>'

    level = event.evidence_level
    label = "多源交叉验证" if level == "multi_source" else "单一来源"
    if event.independent_source_count > 1:
        label += f" · {event.independent_source_count} 个独立来源"

    others = event.all_urls[1:6]
    more = ""
    if others:
        links = "".join(
            f'<a class="src-link" href="{esc(u)}" rel="noopener noreferrer">{esc(_domain(u))}</a>'
            for u in others
        )
        extra = len(event.all_urls) - 1 - len(others)
        more = links + (f'<span class="src-more">另有 {extra} 个来源</span>' if extra > 0 else "")

    when_cls = "" if known else " when-unknown"
    enter_cls = " enter" if enter else ""
    delay = ' data-delay="%d"' % (index * 70) if enter else ""

    return f"""      <li class="row{enter_cls}" data-rank="{index}" data-level="{esc(level)}"{delay}>
        <span class="row-index" aria-hidden="true">{index:02d}</span>
        <div>
          <h3 class="row-title"><a href="{esc(first_url)}" rel="noopener noreferrer">{esc(title)}</a></h3>
          {body}
        </div>
        <div class="sources">
          <span class="evidence" data-level="{esc(level)}">{esc(label)}</span>
          <span class="src-link{when_cls}">{esc(when_text)}</span>
          <a class="src-link" href="{esc(first_url)}" rel="noopener noreferrer">{esc(_domain(first_url))}</a>
          {more}
        </div>
      </li>"""


@dataclass
class SiteContext:
    site_url: str
    archive: list[tuple[str, int]]        # (date, event count), newest first
    generated_at: datetime


def render_day(
    digest: Digest,
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem],
    ctx: SiteContext,
) -> str:
    counts = digest.counts
    coverage = digest.source_coverage

    headline = digest.headline or (digest.top_events[0].title if digest.top_events else "AI 日报")
    lead = ""
    for event in digest.top_events[:1]:
        insight = insights.get(event.event_id)
        if insight and insight.facts:
            lead = insight.facts[0]
        elif event.member_item_ids:
            item = items_by_id.get(event.member_item_ids[0])
            if item is not None:
                lead = (item.summary or "")[:180]

    # --- 事件流：前三行入场，其余本来就在（slop B2） -------------------------
    rows = []
    for idx, event in enumerate(digest.top_events, start=1):
        rows.append(_row(idx, event, insights.get(event.event_id), enter=idx <= 3))
    stream = "\n".join(rows) if rows else '<li class="row"><div></div><div><p class="row-title">今日窗口内没有条目。</p></div><div></div></li>'

    # --- 归档表（第三种段落形态） --------------------------------------------
    archive_items = "".join(
        f'<li><a href="{esc(date)}.html"><span class="date">{esc(date)}</span>'
        f'<span class="count">{count} 条</span></a></li>'
        for date, count in ctx.archive[:60]
    )
    archive = (
        f'<section class="archive wrap"><h2>往期</h2><ul>{archive_items}</ul></section>'
        if archive_items else ""
    )

    # --- 警告：数据不全时显式声明，不留白 -----------------------------------
    warnings = ""
    if digest.warnings:
        lis = "".join(f"<li>{esc(w)}</li>" for w in digest.warnings)
        warnings = f'<div class="warn wrap"><strong>本期说明</strong><ul>{lis}</ul></div>'

    llm = digest.llm_usage or {}
    calls = llm.get("calls")
    tokens = llm.get("tokens")
    model_note = (
        f"大模型：{calls} 次调用 / {tokens:,} token" if calls else "本期未调用大模型"
    )

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(headline)} · AI 日报 {esc(digest.date)}</title>
<meta name="description" content="{esc(lead[:150])}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#0065fd">
<link rel="icon" href="{FAVICON}">
<link rel="canonical" href="{esc(ctx.site_url.rstrip('/'))}/{esc(digest.date)}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(headline)}">
<meta property="og:description" content="{esc(lead[:150])}">
<meta property="og:url" content="{esc(ctx.site_url.rstrip('/'))}/{esc(digest.date)}.html">
<meta property="og:site_name" content="AI 日报">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="AI 日报" href="feed/zh.xml">
<link rel="alternate" type="application/feed+json" title="AI 日报" href="feed/zh.json">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
</head>
<body>
<main class="wrap">

  <!-- 段落形态 1：信息带。左标题 + 右真实计数，不是居中的 hero（slop A1） -->
  <header class="masthead">
    <div class="enter" data-delay="0">
      <p class="eyebrow"><span class="dot" aria-hidden="true"></span>AI 日报 · {esc(digest.date)}</p>
      <h1>{esc(headline)}</h1>
      {f'<p class="sub">{esc(lead[:190])}</p>' if lead else ''}
    </div>
    <div class="tally enter" data-delay="120" role="group" aria-label="本期统计">
      <div><b class="count-up" data-to="{counts.get('events', 0)}">{counts.get('events', 0)}</b><span>事件</span></div>
      <div><b class="count-up" data-to="{coverage.active}">{coverage.active}</b><span>有内容的源</span></div>
      <div><b class="count-up" data-to="{counts.get('multi_source_events', 0)}">{counts.get('multi_source_events', 0)}</b><span>多源验证</span></div>
    </div>
  </header>

  <!-- 控制条：唯一的交互控制，带 aria-pressed 状态 -->
  <div class="bar">
    <span>筛选</span>
    <button class="chip" type="button" data-filter="multi" aria-pressed="false">仅多源验证</button>
    <button class="chip" type="button" data-filter="single" aria-pressed="false">仅单一来源</button>
    <span class="spacer"></span>
    <span id="filter-status" role="status" aria-live="polite">显示全部 {counts.get('events', 0)} 条</span>
  </div>

  {warnings}

  <!-- 段落形态 2：序号化的不等宽事件流（slop A2/A3） -->
  <ol class="stream">
{stream}
  </ol>

  <!-- 段落形态 3：等宽数字的密集归档表 -->
  {archive}

  <footer class="foot">
    <div class="notice">
      <p>本期从 {coverage.total} 个已注册信息源中采集，{coverage.active} 个源提供了窗口内的内容，
      {coverage.failed} 个失败，{coverage.skipped} 个跳过（未启用或需凭证）。
      共 {counts.get('items_after_window', 0)} 条条目进入分析，其中 {counts.get('items_merged_away', 0)} 条被判定为重复。</p>
      <p>{esc(model_note)}。摘要由 AI 从原始来源整理，事实、推断与不确定项已分列；
      <strong>每个条目的链接都来自采集记录，未经模型生成</strong>。请以原始来源为准。</p>
    </div>
    <div>
      <p>生成于 {digest.generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
      <p><a href="feed/zh.xml">RSS</a> · <a href="feed/zh.json">JSON Feed</a> · <a href="index.html">往期</a></p>
    </div>
  </footer>
</main>
<script src="assets/motion.js" defer></script>
</body>
</html>
"""


def render_index(ctx: SiteContext, latest: Digest | None) -> str:
    items = "".join(
        f'<li><a href="{esc(date)}.html"><span class="date">{esc(date)}</span>'
        f'<span class="count">{count} 条</span></a></li>'
        for date, count in ctx.archive
    )
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>AI 日报 · 往期</title>
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{FAVICON}">
<link rel="alternate" type="application/rss+xml" title="AI 日报" href="feed/zh.xml">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
</head>
<body>
<main class="wrap">
  <header class="masthead">
    <div>
      <p class="eyebrow"><span class="dot" aria-hidden="true"></span>AI 日报</p>
      <h1>往期</h1>
      <p class="sub">每日自动聚合 AI 领域的信息源，去重、交叉验证，并区分事实与推断。</p>
    </div>
    <div class="tally" role="group" aria-label="归档统计">
      <div><b>{len(ctx.archive)}</b><span>期</span></div>
      <div><b>{sum(c for _, c in ctx.archive)}</b><span>事件</span></div>
    </div>
  </header>
  <section class="archive">
    <h2>全部期数</h2>
    <ul>{items or '<li><a href="#"><span class="date">暂无</span></a></li>'}</ul>
  </section>
  <footer class="foot">
    <div class="notice"><p>最新一期：{esc(latest.date) if latest else '暂无'} ·
      <a href="feed/zh.xml">RSS</a> · <a href="feed/zh.json">JSON Feed</a></p></div>
  </footer>
</main>
</body>
</html>
"""


def render_404(ctx: SiteContext) -> str:
    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>找不到这一期 · AI 日报</title>
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
</head>
<body>
<main class="wrap">
  <header class="masthead">
    <div>
      <p class="eyebrow"><span class="dot" aria-hidden="true"></span>404</p>
      <h1>找不到这一期</h1>
      <p class="sub">这一期可能还没有生成，或者日期写错了。归档里所有已发布的期数都能点开。</p>
    </div>
  </header>
  <section class="archive">
    <h2>去往期索引</h2>
    <ul><li><a href="index.html"><span class="date">全部期数</span><span class="count">→</span></a></li></ul>
  </section>
</main>
</body>
</html>
"""


def load_archive(site_dir: Path) -> list[tuple[str, int]]:
    """Read existing day pages so the archive survives a fresh render.

    The count comes from the page itself when it is available; a missing count is shown
    as 0 rather than guessed, because a wrong number here is indistinguishable from a
    real one.
    """
    out: list[tuple[str, int]] = []
    if not site_dir.exists():
        return out
    for path in sorted(site_dir.glob("*.html"), reverse=True):
        if path.stem in ("index", "404"):
            continue
        count = 0
        try:
            text = path.read_text(encoding="utf-8")
            marker = 'class="count-up" data-to="'
            idx = text.find(marker)
            if idx != -1:
                tail = text[idx + len(marker):]
                count = int(tail.split('"', 1)[0])
        except (OSError, ValueError):
            count = 0
        out.append((path.stem, count))
    return out


def write_site(
    digest: Digest,
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem],
    out_dir: Path,
    *,
    site_url: str,
    assets_dir: Path | None = None,
) -> dict[str, object]:
    """Write the day page, the index, the 404, and copy the assets."""
    site = out_dir / "site"
    site.mkdir(parents=True, exist_ok=True)

    if assets_dir and assets_dir.exists():
        target = site / "assets"
        target.mkdir(parents=True, exist_ok=True)
        for src in assets_dir.iterdir():
            if src.is_file():
                (target / src.name).write_bytes(src.read_bytes())

    archive = load_archive(site)
    generated_at = digest.generated_at
    ctx = SiteContext(site_url=site_url, archive=archive, generated_at=generated_at)

    day_html = render_day(digest, insights, items_by_id, ctx)
    (site / f"{digest.date}.html").write_text(day_html, encoding="utf-8")

    # Rebuild the archive list including today, newest first, de-duplicated.
    merged: dict[str, int] = {date: count for date, count in archive}
    merged[digest.date] = int(digest.counts.get("events", 0))
    ctx.archive = sorted(merged.items(), reverse=True)

    (site / "index.html").write_text(render_index(ctx, digest), encoding="utf-8")
    (site / "404.html").write_text(render_404(ctx), encoding="utf-8")
    # A manifest so the deploy step can report size without walking the tree.
    manifest = {
        "date": digest.date,
        "pages": len(ctx.archive),
        "bytes": len(day_html.encode("utf-8")),
        "assets": sorted(p.name for p in (site / "assets").glob("*")) if (site / "assets").exists() else [],
    }
    (site / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return manifest
