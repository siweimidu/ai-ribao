"""Static site generator for the digest.

Layout follows the two reference sites the user pointed at, read from their live DOM rather
than from a screenshot:

* `daily.juya.uk` — three tracks: a 240px sticky navigation rail, the content column, and a
  separate 240px table-of-contents rail on the right. The left rail holds, in order:
  search, home, a month calendar, social/RSS, theme, and a report link.
* `aihot.news` — same idea at a larger scale (it 403s to non-browser clients, so its README
  and repo were read instead).

What this module deliberately does NOT copy is the templated chrome that `frontend-design`
names as the tells of a generated page: monospace faces used to dress up small labels, and
metadata strings joined with middle dots. Both were in the previous version of this file.
Structure carries the information here — a rail, a calendar with real state, numbered
stories, a TOC that follows the reading position — and type stays quiet around it.

Everything is server-rendered. The page must work if JavaScript never arrives: the calendar
renders its dates on the client but the *journal itself* is plain HTML, the search dialog
degrades to a normal page without it, and the TOC is a list of working anchors.
"""

from __future__ import annotations

import html
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .analyze import EventInsight
from .models import Digest, Event, NormalizedItem
from .render import _label

#: Section order. "mixed" first because a multi-source story is the most corroborated
#: thing in the issue; the rest follow how a reader scans (official -> paper -> media ->
#: community -> Chinese media -> everything else).
SECTION_ORDER = [
    "mixed", "lab-official", "paper", "lab-blog", "media",
    "dev", "product", "model", "zh-media", "community", "digest",
    "search", "trend", "preset", "other",
]

FAVICON = (
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 32 32'%3E"
    "%3Crect width='32' height='32' rx='8' fill='%230065fd'/%3E"
    "%3Cpath d='M9.5 21.5 14.4 10.5h3.4l4.9 11h-3.1l-1-2.4h-5.2l-1 2.4z' fill='white'/%3E"
    "%3C/svg%3E"
)

#: Inline icons. Deliberately minimal single-path marks rather than an icon font: an icon
#: font is another network dependency and another thing that can render as a blank square.
ICONS = {
    "search": '<circle cx="7.5" cy="7.5" r="5"/><path d="M11.5 11.5 15 15"/>',
    "home": '<path d="M3 8.5 9 3l6 5.5V15H3z"/><path d="M7.5 15v-4h3v4"/>',
    "wechat": '<path d="M2.5 7.5c0-2.5 2.4-4.5 5.4-4.5s5.4 2 5.4 4.5-2.4 4.5-5.4 4.5c-.6 0-1.2-.1-1.7-.2L4 13l.7-2.1A4.4 4.4 0 0 1 2.5 7.5z"/><path d="M9.8 11.4c.4 2 2.4 3.4 4.8 3.4.5 0 1-.1 1.5-.2l1.7 1.1-.5-1.7a3.6 3.6 0 0 0 1.4-2.6c0-1.5-1-2.8-2.5-3.4"/>',
    "rss": '<path d="M3.5 12.5a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"/><path d="M3 4.5A8.5 8.5 0 0 1 11.5 13"/><path d="M3 8A5 5 0 0 1 8 13"/>',
    "theme": '<circle cx="9" cy="9" r="6"/><path d="M9 3v12"/><path d="M9 3a6 6 0 0 1 0 12"/>',
    "download": '<path d="M9 3v8"/><path d="M5.5 8 9 11.5 12.5 8"/><path d="M3.5 13.5h11"/>',
    "clock": '<circle cx="9" cy="9" r="6.5"/><path d="M9 5.5V9l2.5 1.5"/>',
    "github": '<path d="M9 2.5a6.5 6.5 0 0 0-2 12.7c-.1-.5-.1-1.2 0-1.7.2-.8 1.4-5 1.4-5s-.3-.7-.3-1.7c0-1.6.9-2.7 2-2.7.9 0 1.4.7 1.4 1.6 0 1-.6 2.4-.9 3.8-.3 1 .5 1.9 1.6 1.9 1.9 0 3.3-2.5 3.3-5.4 0-2.3-1.6-3.9-4-3.9-2.7 0-4.3 2-4.3 4.1 0 .9.3 1.8.8 2.3.1.1.1.2.1.3l-.3 1.1c0 .2-.2.2-.4.1-1.3-.6-2.1-2.5-2.1-4C5.3 3.4 7.5 2.5 9 2.5z"/>',
}


def esc(text: object) -> str:
    return html.escape(str(text if text is not None else ""), quote=True)


def icon(name: str, size: int = 16) -> str:
    path = ICONS.get(name, "")
    return (
        f'<svg viewBox="0 0 18 18" width="{size}" height="{size}" fill="none" '
        f'stroke="currentColor" stroke-width="1.5" stroke-linecap="round" '
        f'stroke-linejoin="round" aria-hidden="true">{path}</svg>'
    )


def _domain(url: str) -> str:
    try:
        host = url.split("//", 1)[1].split("/", 1)[0]
    except IndexError:
        return url[:40]
    return host[4:] if host.startswith("www.") else host


def _when(event: Event) -> tuple[str, bool]:
    if not event.published_range:
        return "时间未知", False
    return event.published_range[0].astimezone(timezone.utc).strftime("%m-%d %H:%M UTC"), True


@dataclass
class SiteContext:
    site_url: str
    archive: list[tuple[str, int]] = field(default_factory=list)
    generated_at: datetime | None = None

    @property
    def dates(self) -> list[str]:
        return [d for d, _ in self.archive]

    def neighbours(self, date: str) -> tuple[str | None, str | None]:
        """(previous, next) in reading order: older is "previous", newer is "next"."""
        dates = sorted(self.dates)
        if date not in dates:
            return None, None
        i = dates.index(date)
        return (dates[i - 1] if i > 0 else None, dates[i + 1] if i + 1 < len(dates) else None)


# ============================== left rail =======================================
def render_rail(ctx: SiteContext, digest: Digest) -> str:
    """The navigation rail: search, home, calendar, Tibo monitor, WeChat, RSS, theme, download.

    Order is the user's, and it is also a sensible reading order: find something, go to the
    newest, pick a date, then the secondary destinations, then settings.
    """
    prev_date, next_date = ctx.neighbours(digest.date)

    theme_items = "".join(
        f'<button type="button" data-theme-choice="{key}" aria-checked="false">{label}</button>'
        for key, label in (("auto", "自动"), ("default", "默认"), ("light", "亮色"), ("dark", "暗色"))
    )

    # Both editions are offered because they answer different questions: the brief is what
    # happened today, the deep version is everything with its evidence. The filenames must
    # match what the writer actually puts in `site/` — the guard checks every href resolves.
    download_items = (
        f'<a role="menuitem" href="{esc(digest.date)}.brief.md" download>速览版 (markdown)</a>'
        f'<a role="menuitem" href="{esc(digest.date)}.md" download>深度版 (markdown)</a>'
    )

    return f"""      <aside class="rail" aria-label="站点导航">
        <div class="rail__head">
          <a class="rail__brand" href="index.html">
            <span class="rail__mark" aria-hidden="true">AI</span>
            <span>AI 日报</span>
          </a>
          <button class="rail__toggle rail__item" type="button" aria-expanded="false"
                  aria-controls="rail-body" style="width:auto">
            <span class="sr">展开导航</span>
            <span aria-hidden="true">☰</span>
          </button>
        </div>

        <div class="rail__body" id="rail-body">
          <!-- 1. 搜索往期内容 -->
          <div class="rail__group">
            <button class="rail__item" type="button" data-open-search>
              {icon("search")}<span>搜索往期内容</span><span class="rail__hint">⌘K</span>
            </button>
          </div>

          <!-- 2. 首页 -->
          <div class="rail__group" style="margin-top:calc(var(--unit) * 2)">
            <a class="rail__item" href="index.html">{icon("home")}<span>首页</span></a>
          </div>

          <hr class="rail__sep">

          <!-- 3. 日历 -->
          <div class="cal" aria-label="按日期浏览">
            <div class="cal__head">
              <span class="cal__month">—</span>
              <span class="cal__nav">
                <button type="button" data-nav="prev" aria-label="上个月">‹</button>
                <button type="button" data-nav="next" aria-label="下个月">›</button>
              </span>
            </div>
            <div class="cal__grid" role="grid">
              <span class="cal__dow">日</span><span class="cal__dow">一</span>
              <span class="cal__dow">二</span><span class="cal__dow">三</span>
              <span class="cal__dow">四</span><span class="cal__dow">五</span>
              <span class="cal__dow">六</span>
            </div>
            <div class="cal__legend">
              <span><i data-k="today"></i>今天</span>
              <span><i data-k="has"></i>有日报</span>
            </div>
          </div>

          <hr class="rail__sep">

          <!-- 4. Tibo 重置监控 -->
          <div class="rail__group">
            <a class="rail__item" href="tibo.html">{icon("clock")}<span>Tibo 重置监控</span></a>
          </div>

          <!-- 5. 微信公众号 -->
          <div class="rail__group" style="margin-top:calc(var(--unit) * 2)">
            <details class="rail__fold">
              <summary class="rail__item">{icon("wechat")}<span>微信公众号</span></summary>
              <div class="rail__sub">
                <p style="margin:0;color:var(--muted-fg);font-size:var(--fs-small);line-height:1.7">
                  在微信里搜索公众号「AI 日报」，或扫描站点首页底部的二维码。
                  公众号推送与网页同一份内容。
                </p>
              </div>
            </details>
          </div>

          <!-- 6. 订阅 RSS -->
          <div class="rail__group" style="margin-top:calc(var(--unit) * 2)">
            <details class="rail__fold">
              <summary class="rail__item">{icon("rss")}<span>订阅 RSS</span></summary>
              <div class="rail__sub">
                <a role="menuitem" href="feed/zh.xml">RSS 2.0</a>
                <a role="menuitem" href="feed/zh.json">JSON Feed</a>
                <a role="menuitem" href="feed/zh.xml" download>下载当前 feed</a>
              </div>
            </details>
          </div>

          <!-- 7. 主题 -->
          <div class="rail__group" style="margin-top:calc(var(--unit) * 2)">
            <details class="rail__fold">
              <summary class="rail__item">
                {icon("theme")}<span>主题</span>
                <span class="rail__hint" data-theme-summary>自动</span>
              </summary>
              <div class="rail__sub" role="menu">{theme_items}</div>
            </details>
          </div>

          <!-- 8. 下载 markdown -->
          <div class="rail__group" style="margin-top:calc(var(--unit) * 2)">
            <details class="rail__fold">
              <summary class="rail__item">{icon("download")}<span>下载 markdown</span></summary>
              <div class="rail__sub" role="menu">{download_items}</div>
            </details>
          </div>

          <hr class="rail__sep">

          <div class="rail__group">
            <a class="rail__item" href="https://github.com/siweimidu/ai-ribao" rel="noopener noreferrer">
              {icon("github")}<span>源码与说明</span>
            </a>
          </div>
        </div>
      </aside>"""


# ============================== right TOC =======================================
def render_toc(sections: list[tuple[str, str, list[Event]]]) -> str:
    """Right rail: section headings plus their stories, as working anchors."""
    rows: list[str] = []
    for slug, label, events in sections:
        rows.append(f'<a href="#{esc(slug)}" data-level="1">{esc(label)}</a>')
        for event in events:
            anchor = f"e-{event.event_id[:10]}"
            title = event.title if len(event.title) <= 40 else event.title[:38] + "…"
            rows.append(f'<a href="#{esc(anchor)}" data-level="2">{esc(title)}</a>')
    if not rows:
        return ""
    return f"""      <nav class="toc" aria-label="目录">
        <p class="toc__title">目录</p>
        <div class="toc__nav">
{chr(10).join('          ' + r for r in rows)}
        </div>
      </nav>"""


# ============================== story ===========================================
def render_item(index: int, event: Event, insight: EventInsight | None) -> str:
    title = (insight.title if insight and insight.title else event.title) or event.title
    anchor = f"e-{event.event_id[:10]}"
    first_url = event.all_urls[0] if event.all_urls else "#"
    when_text, known = _when(event)

    level = event.evidence_level
    label = "多源交叉验证" if level == "multi_source" else "单一来源"
    # Two facts, two elements. Joining them with a middle dot produced the `A · B` chrome
    # that reads as generated, and the separator was carrying no meaning anyway.
    count_note = (
        f'<span>{event.independent_source_count} 个独立来源</span>'
        if event.independent_source_count > 1 else ""
    )

    # Facts, inferences and uncertainties are rendered as separate labelled blocks rather
    # than as one paragraph, because that separation is the anti-hallucination contract.
    blocks: list[str] = []
    for kind, rows, name in (
        ("fact", insight.facts if insight else [], "事实"),
        ("inference", insight.inferences if insight else [], "推断"),
        ("uncertain", insight.uncertainties if insight else [], "不确定"),
    ):
        if not rows:
            continue
        lis = "".join(f'<li data-kind="{kind}">{esc(r)}</li>' for r in rows[:5])
        blocks.append(f'<p class="facts__label" data-kind="{kind}">{name}</p><ul>{lis}</ul>')
    evidence = f'<div class="facts">{"".join(blocks)}</div>' if blocks else ""

    if insight is None or getattr(insight, "rule_based", False):
        evidence += (
            '<div class="facts"><p class="facts__label" data-kind="fact">来源摘录</p>'
            '<ul><li data-kind="fact">本条未调用大模型，内容为来源原文摘录。</li></ul></div>'
        )

    others = event.all_urls[1:5]
    links = "".join(
        f'<a href="{esc(u)}" rel="noopener noreferrer">{esc(_domain(u))}</a>' for u in others
    )
    extra = len(event.all_urls) - 1 - len(others)
    if extra > 0:
        links += f'<span style="color:var(--muted-fg)">另有 {extra} 个来源</span>'
    links = f'<div class="item__links">{links}</div>' if links else ""

    when_cls = "" if known else ' class="when-unknown"'

    return f"""        <li class="item" id="{esc(anchor)}">
          <div class="item__head">
            <span class="item__no">{index:02d}</span>
            <h3 class="item__title"><a href="{esc(first_url)}" rel="noopener noreferrer">{esc(title)}</a></h3>
          </div>
          <div class="item__meta">
            <span class="badge" data-level="{esc(level)}">{esc(label)}</span>
            {count_note}
            <span{when_cls}>{esc(when_text)}</span>
            <a href="{esc(first_url)}" rel="noopener noreferrer">{esc(_domain(first_url))}</a>
          </div>
          {evidence}
          {links}
        </li>"""


def _sections_of(digest: Digest) -> list[tuple[str, str, list[Event]]]:
    """Group `top_events` by the section the pipeline assigned each one.

    `top_events` is authoritative and `sections` only says where an event belongs — the
    same rule `render_deep` follows, and for the same reason: iterating `sections` alone
    once produced a completely empty document.

    `sections` arrives in two shapes and both must work. In memory it is
    `{category: [Event, ...]}`; in the archived JSON it is `{category: [event_id, ...]}`
    because the writer stores ids to avoid duplicating every event body
    (`__main__.py` excludes `sections` from `model_dump` for exactly that reason). Reading
    only the first shape silently put all 60 stories into "其它" on the real page.
    """
    lookup: dict[str, str] = {}
    for category, rows in digest.sections.items():
        for row in rows:
            key = row if isinstance(row, str) else getattr(row, "event_id", None)
            if key:
                lookup.setdefault(key, category)

    grouped: dict[str, list[Event]] = {}
    for event in digest.top_events:
        grouped.setdefault(lookup.get(event.event_id, "other"), []).append(event)

    def rank(key: str) -> tuple[int, str]:
        return (SECTION_ORDER.index(key) if key in SECTION_ORDER else len(SECTION_ORDER), key)

    out: list[tuple[str, str, list[Event]]] = []
    for category in sorted(grouped, key=rank):
        # `_label` already falls back to 其它; the special case here was redundant and hid
        # the fact that `mixed` had no label at all.
        label = _label(category)
        out.append((f"sec-{category}", label, grouped[category]))
    return out


def _stats(digest: Digest) -> str:
    counts = digest.counts
    coverage = digest.source_coverage
    cells = [
        (counts.get("events", 0), "事件"),
        (coverage.active if coverage else 0, "有内容的源"),
        (counts.get("multi_source_events", 0), "多源验证"),
        (counts.get("distinct_sources_in_head", 0), "头条覆盖来源"),
    ]
    inner = "".join(
        f'<div><b class="count-up" data-to="{int(v) if isinstance(v, (int, float)) else 0}">'
        f'{int(v) if isinstance(v, (int, float)) else 0}</b><span>{esc(label)}</span></div>'
        for v, label in cells
    )
    return f'<div class="stats enter">{inner}</div>'


# ============================== page ============================================
def render_day(
    digest: Digest,
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem],
    ctx: SiteContext,
) -> str:
    sections = _sections_of(digest)
    toc = render_toc(sections)

    body: list[str] = []
    counter = 0
    for slug, label, events in sections:
        rows = []
        for event in events:
            counter += 1
            rows.append(render_item(counter, event, insights.get(event.event_id)))
        body.append(
            f"""      <section class="section" id="{esc(slug)}">
        <h2 class="section__title">{esc(label)}<span class="section__count">{len(events)} 条</span></h2>
        <ol class="stream">
{chr(10).join(rows)}
        </ol>
      </section>"""
        )

    lead = ""
    for event in digest.top_events[:1]:
        insight = insights.get(event.event_id)
        if insight and insight.facts:
            lead = insight.facts[0]
        elif event.member_item_ids:
            item = items_by_id.get(event.member_item_ids[0])
            if item is not None:
                lead = (item.summary or "")[:200]

    warnings = ""
    if digest.warnings:
        lis = "".join(f"<li>{esc(w)}</li>" for w in digest.warnings)
        warnings = f'<div class="notice"><strong>本期说明</strong><ul>{lis}</ul></div>'

    llm = digest.llm_usage or {}
    coverage = digest.source_coverage
    counts = digest.counts
    prev_date, next_date = ctx.neighbours(digest.date)

    pager = ""
    if prev_date or next_date:
        left = (
            f'<a href="{esc(prev_date)}.html"><span>上一期</span>{esc(prev_date)}</a>'
            if prev_date else "<span></span>"
        )
        right = (
            f'<a href="{esc(next_date)}.html"><span>下一期</span>{esc(next_date)}</a>'
            if next_date else "<span></span>"
        )
        pager = f'<nav class="pager">{left}{right}</nav>'

    # The calendar and search index are inlined: one request, no fetch, and it works from
    # `file://` too. The index is titles only — the digest bodies would multiply page size.
    calendar_data = {
        "dates": ctx.dates,
        "current": digest.date,
        "today": datetime.now(timezone.utc).astimezone().date().isoformat(),
    }
    search_index = [
        {"date": digest.date, "items": [{"t": e.title, "s": ", ".join(e.source_ids[:2])} for e in digest.top_events]}
    ]

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{esc(digest.headline or digest.date)} · AI 日报</title>
<meta name="description" content="{esc(lead[:150])}">
<meta name="color-scheme" content="light dark">
<meta name="theme-color" content="#0065fd">
<link rel="icon" href="{FAVICON}">
<link rel="canonical" href="{esc(ctx.site_url.rstrip('/'))}/{esc(digest.date)}.html">
<meta property="og:type" content="article">
<meta property="og:title" content="{esc(digest.headline or digest.date)}">
<meta property="og:description" content="{esc(lead[:150])}">
<link rel="alternate" type="application/rss+xml" title="AI 日报" href="feed/zh.xml">
<link rel="alternate" type="application/feed+json" title="AI 日报" href="feed/zh.json">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
</head>
<body>
<a class="skip" href="#main">跳到正文</a>

<div class="shell">
{render_rail(ctx, digest)}

  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date enter">{esc(digest.date)}　第 {len(ctx.archive)} 期</p>
      <h1 class="issue__title enter">{esc(digest.headline or digest.date)}</h1>
      {f'<p class="issue__lead enter">{esc(lead[:200])}</p>' if lead else ''}
      {_stats(digest)}
    </header>

    {warnings}

{chr(10).join(body)}

    {pager}

    <footer class="foot">
      <p>本期从 {coverage.total if coverage else 0} 个已注册信息源采集，
      {coverage.active if coverage else 0} 个源提供了窗口内的内容，
      {coverage.failed if coverage else 0} 个失败，{coverage.skipped if coverage else 0} 个跳过。
      共 {counts.get('items_after_window', 0)} 条条目进入分析，
      {counts.get('items_merged_away', 0)} 条被判定为重复。</p>
      <p>{esc(f"大模型：{llm.get('calls', 0)} 次调用 / {llm.get('tokens', 0):,} token" if llm.get('calls') else '本期未调用大模型')}。
      摘要由 AI 从原始来源整理，事实、推断与不确定项已分列；
      <strong>每个条目的链接都来自采集记录，未经模型生成</strong>。请以原始来源为准。</p>
      <p>生成于 {digest.generated_at.astimezone(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')}</p>
    </footer>
  </main>

{toc}
</div>

<dialog class="search" id="search-dialog" aria-label="搜索往期内容">
  <div class="search__form">
    {icon("search", 18)}
    <input type="search" placeholder="搜索往期内容…" aria-label="搜索关键词" autocomplete="off">
    <kbd>Esc</kbd>
  </div>
  <ul class="search__results"></ul>
</dialog>

<script type="application/json" id="calendar-data">{json.dumps(calendar_data, ensure_ascii=False)}</script>
<script type="application/json" id="search-index">{json.dumps(search_index, ensure_ascii=False)}</script>
<script src="assets/motion.js" defer></script>
</body>
</html>
"""


# ============================== other pages =====================================
def render_index(ctx: SiteContext, latest: Digest | None) -> str:
    """Archive list, grouped by month so that a year of issues stays scannable."""
    by_month: dict[str, list[tuple[str, int]]] = {}
    for date, count in ctx.archive:
        by_month.setdefault(date[:7], []).append((date, count))

    groups = []
    for month in sorted(by_month, reverse=True):
        rows = "".join(
            f'<li><a href="{esc(d)}.html"><span>{esc(d)}</span><span class="section__count">{c} 条</span></a></li>'
            for d, c in sorted(by_month[month], reverse=True)
        )
        groups.append(
            f'<section class="section"><h2 class="section__title">{esc(month)}'
            f'<span class="section__count">{len(by_month[month])} 期</span></h2>'
            f'<ol class="stream">{rows}</ol></section>'
        )

    calendar_data = {
        "dates": ctx.dates,
        "current": latest.date if latest else None,
        "today": datetime.now(timezone.utc).astimezone().date().isoformat(),
    }
    search_index = []

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
<a class="skip" href="#main">跳到正文</a>
<div class="shell">
{render_rail(ctx, latest) if latest else ''}
  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date enter">全部往期</p>
      <h1 class="issue__title enter">AI 日报</h1>
      <p class="issue__lead enter">每日自动聚合 AI 领域的信息源，去重、交叉验证，并区分事实与推断。</p>
      <div class="stats enter">
        <div><b>{len(ctx.archive)}</b><span>期</span></div>
        <div><b>{sum(c for _, c in ctx.archive)}</b><span>事件</span></div>
      </div>
    </header>
    {''.join(groups) or '<p>还没有已发布的期数。</p>'}
    <footer class="foot">
      <p>最新一期：{esc(latest.date) if latest else '暂无'}</p>
    </footer>
  </main>
</div>
<dialog class="search" id="search-dialog" aria-label="搜索往期内容">
  <div class="search__form">
    {icon("search", 18)}
    <input type="search" placeholder="搜索往期内容…" aria-label="搜索关键词" autocomplete="off">
    <kbd>Esc</kbd>
  </div>
  <ul class="search__results"></ul>
</dialog>
<script type="application/json" id="calendar-data">{json.dumps(calendar_data, ensure_ascii=False)}</script>
<script type="application/json" id="search-index">{json.dumps(search_index, ensure_ascii=False)}</script>
<script src="assets/motion.js" defer></script>
</body>
</html>
"""


def render_tibo(ctx: SiteContext, monitor: dict | None = None) -> str:
    """Codex quota-reset monitor.

    The reference page is aihot.news/codex-reset. Its data comes from AIHOT's public API,
    which is read here the same way a reader reads the site -- see `aidaily/aihot.py` for
    the terms that shape this and why `/selected/snapshot` is deliberately not used.

    Two honesty rules the page follows:

    * every figure is labelled with who computed it. The four headline numbers are derived
      from the event stream *here*, not published by AIHOT, and the page says so rather
      than implying they came from the source.
    * with no data the page says so. An invented reset history is indistinguishable from a
      real one once rendered, which is the one thing this project cannot afford.
    """
    monitor = monitor or {}
    stats = monitor.get("stats") or {}
    events = monitor.get("events") or []
    acts = monitor.get("activities") or []
    policy = monitor.get("policy") or {}
    attribution = monitor.get("attribution") or {}

    calendar_data = {
        "dates": ctx.dates,
        "current": None,
        "today": datetime.now(timezone.utc).astimezone().date().isoformat(),
    }

    def number(value, suffix: str = "") -> str:
        if value is None:
            return "—"
        return f"{value}{suffix}"

    if stats:
        summary = f"""      <div class="stats">
        <div><b>{number(stats.get('resets90d'))}</b><span>近 90 天重置</span></div>
        <div><b>{number(stats.get('cards90d'))}</b><span>近 90 天发卡</span></div>
        <div><b>{number(stats.get('medianGapDays'), ' 天')}</b><span>重置间隔中位数</span></div>
        <div><b>{number(stats.get('lastResetOn'))}</b><span>上次额度重置</span></div>
      </div>
      <p class="issue__date" style="margin-top:calc(var(--unit) * 3)">
        以上数字由本站根据 {monitor.get('total_events', 0)} 条事件记录计算，
        不是 AIHOT 直出的统计（其 <code>monitor</code> 字段报告的是采集器健康状态）。<br>
        覆盖自 {esc(monitor.get('history_from') or '—')}，数据检查于
        {esc((monitor.get('checked_at') or '')[:16].replace('T', ' '))}（{esc(monitor.get('timezone') or '')}）。
      </p>"""
    else:
        summary = (
            '<div class="notice"><p>还没有记录。这个页面显示 Codex 额度重置的历史，'
            '需要能访问来源后才会出现。</p></div>'
        )

    if events:
        rows = []
        for e in events[:40]:
            posts = "".join(
                f'<li>'
                f'<span class="facts__label">{esc(p.get("stage") or "动态")}</span>'
                f'<div>{esc(p.get("text") or "")}</div>'
                + (f'<div style="color:var(--muted-fg);font-size:var(--fs-small)">{esc(p.get("original") or "")}</div>' if p.get("original") else "")
                + (f'<a href="{esc(p.get("url"))}" rel="noopener noreferrer" style="font-size:var(--fs-small);color:var(--muted-fg)">在原站查看 ↗</a>' if p.get("url") else "")
                + "</li>"
                for p in (e.get("posts") or [])[:3]
            )
            when = (e.get("created_at") or "")[:16].replace("T", " ")
            schedule = (
                f'<div style="color:var(--muted-fg);font-size:var(--fs-small)">'
                f'{esc(e.get("schedule_label"))}</div>'
                if e.get("schedule_label") else ""
            )
            rows.append(
                f'<li class="item">'
                f'<div class="item__head"><h3 class="item__title">{esc(e.get("title") or "")}</h3></div>'
                f'<div class="item__meta">'
                f'<span class="badge">{esc(e.get("label") or "")}</span>'
                f'<span>{esc(when)}</span>'
                f'<span>{esc(e.get("status") or "")}</span>'
                f'</div>{schedule}'
                f'<ul class="facts" style="list-style:none;padding-left:0">{posts}</ul>'
                f'</li>'
            )
        event_list = f'<ol class="stream">{"".join(rows)}</ol>'
    else:
        event_list = '<p style="color:var(--muted-fg)">暂无事件记录。</p>'

    if acts:
        act_rows = "".join(
            f'<li class="item" style="padding-block:calc(var(--unit) * 3)">'
            f'<div style="display:flex;gap:calc(var(--unit) * 3);align-items:flex-start">'
            f'<span style="color:var(--muted-fg);font-size:var(--fs-small);white-space:nowrap">'
            f'{esc((a.get("at") or "")[:16].replace("T", " "))}</span>'
            f'<div><div>{esc(a.get("text") or "")}</div>'
            + (f'<div style="color:var(--muted-fg);font-size:var(--fs-small)">{esc(a.get("original") or "")}</div>' if a.get("original") else "")
            + (f'<a href="{esc(a.get("url"))}" rel="noopener noreferrer" style="font-size:var(--fs-small);color:var(--muted-fg)">在原站查看 ↗</a>' if a.get("url") else "")
            + '</div></div></li>'
            for a in acts[:20]
        )
        activity_block = (
            '<section class="section"><h2 class="section__title">Tibo 相关动态'
            f'<span class="section__count">{len(acts)} 条</span></h2>'
            f'<ol class="stream">{act_rows}</ol></section>'
        )
    else:
        activity_block = ""

    attribution_block = ""
    if attribution:
        policy_note = ""
        if policy:
            policy_note = (
                f'<p>该接口在响应头声明其使用规则版本 {esc(str(policy.get("version") or "—"))}：'
                f'<code>{esc(str(policy.get("commercial_use") or ""))}</code>。'
                f'个人非商业、公益非商业与组织内部使用免费；'
                f'对外商业产品、公开镜像与批量公开再分发需事先取得书面授权。'
                f'联系方式：{esc(str(policy.get("contact") or ""))}。</p>'
            )
        # `attribution["note"]` already states the source and the retention rule, so the
        # sentence is not repeated before it -- an earlier version said the same thing twice
        # in one paragraph because both halves were concatenated.
        attribution_block = f"""      <section class="section" id="sec-source">
        <h2 class="section__title">数据来源与使用边界</h2>
        <div class="notice">
          <p>事件记录与 Tibo 原帖来自
          <a href="{esc(attribution.get('url') or '')}" rel="noopener noreferrer">{esc(attribution.get('name') or '')}</a>
          的公开接口。{esc(attribution.get('note') or '')}</p>
          {policy_note}
          <p><a href="{esc(str(policy.get('terms_url') or 'https://aihot.news/terms'))}" rel="noopener noreferrer">完整使用规则</a></p>
        </div>
      </section>"""

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Tibo 重置监控 · AI 日报</title>
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<div class="shell">
  <aside class="rail" aria-label="站点导航">
    <a class="rail__brand" href="index.html"><span class="rail__mark" aria-hidden="true">AI</span><span>AI 日报</span></a>
    <hr class="rail__sep">
    <div class="rail__group">
      <a class="rail__item" href="index.html">{icon("home")}<span>首页</span></a>
      <a class="rail__item" href="tibo.html" aria-current="page">{icon("clock")}<span>Tibo 重置监控</span></a>
      <a class="rail__item" href="feed/zh.xml">{icon("rss")}<span>订阅 RSS</span></a>
    </div>
  </aside>
  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date">Codex 额度重置与重置卡发放</p>
      <h1 class="issue__title">Tibo 重置监控</h1>
      <p class="issue__lead">什么时候生效、给谁、Tibo 原话。</p>
    </header>
    {summary}
    {attribution_block}
    <section class="section" id="sec-events">
      <h2 class="section__title">重置记录<span class="section__count">{len(events)} 条</span></h2>
      {event_list}
    </section>
    {activity_block}
    <nav class="pager"><a href="index.html"><span>返回</span>往期索引</a></nav>
  </main>
</div>
<script type="application/json" id="calendar-data">{json.dumps(calendar_data, ensure_ascii=False)}</script>
<script src="assets/motion.js" defer></script>
</body>
</html>
"""


def render_404(ctx: SiteContext) -> str:
    calendar_data = {"dates": ctx.dates, "current": None, "today": None}
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
<a class="skip" href="#main">跳到正文</a>
<div class="shell">
  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date">404</p>
      <h1 class="issue__title">找不到这一期</h1>
      <p class="issue__lead">这一期可能还没有生成，或者日期写错了。往期索引里所有已发布的期数都能点开。</p>
    </header>
    <nav class="pager"><a href="index.html"><span>去往期索引</span>全部期数</a></nav>
  </main>
</div>
<script type="application/json" id="calendar-data">{json.dumps(calendar_data, ensure_ascii=False)}</script>
<script src="assets/motion.js" defer></script>
</body>
</html>
"""


# ============================== writer ==========================================
def load_archive(site_dir: Path) -> list[tuple[str, int]]:
    """Rebuild the archive from the pages that already exist.

    A missing count is written as 0 rather than guessed: a wrong number here is
    indistinguishable from a real one.
    """
    out: list[tuple[str, int]] = []
    if not site_dir.exists():
        return out
    for path in sorted(site_dir.glob("*.html"), reverse=True):
        if path.stem in ("index", "404", "tibo"):
            continue
        count = 0
        try:
            text = path.read_text(encoding="utf-8")
            marker = 'data-to="'
            idx = text.find(marker)
            if idx != -1:
                count = int(text[idx + len(marker):].split('"', 1)[0])
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
    tibo: dict | None = None,
) -> dict[str, object]:
    site = out_dir / "site"
    site.mkdir(parents=True, exist_ok=True)

    if assets_dir and assets_dir.exists():
        target = site / "assets"
        target.mkdir(parents=True, exist_ok=True)
        for src in assets_dir.iterdir():
            if src.is_file():
                (target / src.name).write_bytes(src.read_bytes())

    archive = load_archive(site)
    merged = {date: count for date, count in archive}
    merged[digest.date] = int(digest.counts.get("events", 0))
    ctx = SiteContext(
        site_url=site_url,
        archive=sorted(merged.items(), reverse=True),
        generated_at=digest.generated_at,
    )

    day_html = render_day(digest, insights, items_by_id, ctx)
    (site / f"{digest.date}.html").write_text(day_html, encoding="utf-8")

    (site / "index.html").write_text(render_index(ctx, digest), encoding="utf-8")
    (site / "tibo.html").write_text(render_tibo(ctx, tibo), encoding="utf-8")
    (site / "404.html").write_text(render_404(ctx), encoding="utf-8")

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
