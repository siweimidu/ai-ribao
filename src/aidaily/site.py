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
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo
from pathlib import Path

from .analyze import EventInsight
from .l3 import _publisher_of, _url_directness
from .ghcard import card_html as ghcard_html, STYLE as GHCARD_STYLE
from .github_meta import repo_of
from .models import Digest, Event, NormalizedItem
from .render import CATEGORY_LABELS, _label

#: Section order. "mixed" first because a multi-source story is the most corroborated
#: thing in the issue; the rest follow how a reader scans (official -> paper -> media ->
#: community -> Chinese media -> everything else).
SECTION_ORDER = [
    "mixed", "lab-official", "paper", "lab-blog", "media",
    "dev", "product", "model", "zh-media", "community", "digest",
    "search", "trend", "preset", "other",
]

#: The browser-tab icon, inlined as a data URI so there is no extra request and no file to 404.
#:
#: It is the **same geometry as the header mark**: a dot with two expanding arcs, a feed being
#: broadcast. It used to be a blue tile with the letter "A" -- a different logo from the one on
#: the page, and two hand-drawn versions of one mark is exactly how they drift apart.
FAVICON = (
    # `ai1.svg`: the background and the mark both react to `prefers-color-scheme`, so the
    # tab icon is legible on a light **and** a dark browser UI. A fixed white tile is the
    # exact problem `color-scheme` exists to solve.
    "data:image/svg+xml,"
    "%3Csvg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 1530 1530'%3E"
    "%3Cstyle%3E:root{color-scheme:light dark}rect{fill:%23FEFEFE}g{fill:%23231A15}"
    "@media(prefers-color-scheme:dark){rect{fill:%230B0D10}g{fill:%23F2F4F7}}%3C/style%3E"
    "%3Crect width='1530' height='1530' rx='765'/%3E"
    "%3Cg transform='translate(765 765) scale(2.65) translate(-765 -765)'%3E"
    "%3Cpath fill-rule='evenodd' d='M 494,818 L 626,504 L 711,503 L 800,711 L 803,711 "
    "L 1018,546 L 1032,538 L 1027,544 L 745,795 L 740,795 L 726,765 L 610,765 L 586,820 "
    "Z M 669,614 L 701,694 L 636,694 Z'/%3E"
    "%3Cpath d='M 871,713 L 867,712 L 560,989 L 587,971 L 781,825 L 783,1025 L 871,1024 "
    "Z'/%3E%3C/g%3E%3C/svg%3E"
)

#: Inline icons.
#:
#: `brand` is the user-supplied logo (`ai2.svg`), drawn on the same 18x18 grid as the rest: the
#: source art is on a 1530-unit canvas, so it is scaled by 18/1530 and re-centred. The outer tile
#: comes from CSS, which lets the mark inherit the theme instead of carrying its own white box.
ICONS = {
    "search": '<circle cx="7.5" cy="7.5" r="5"/><path d="M11.5 11.5 15 15"/>',
    "home": '<path d="M3 8.5 9 3l6 5.5V15H3z"/><path d="M7.5 15v-4h3v4"/>',
    "wechat": '<path d="M2.5 7.5c0-2.5 2.4-4.5 5.4-4.5s5.4 2 5.4 4.5-2.4 4.5-5.4 4.5c-.6 0-1.2-.1-1.7-.2L4 13l.7-2.1A4.4 4.4 0 0 1 2.5 7.5z"/><path d="M9.8 11.4c.4 2 2.4 3.4 4.8 3.4.5 0 1-.1 1.5-.2l1.7 1.1-.5-1.7a3.6 3.6 0 0 0 1.4-2.6c0-1.5-1-2.8-2.5-3.4"/>',
    "rss": '<path d="M3.5 12.5a1 1 0 1 0 0-2 1 1 0 0 0 0 2z"/><path d="M3 4.5A8.5 8.5 0 0 1 11.5 13"/><path d="M3 8A5 5 0 0 1 8 13"/>',
    "brand": '<g transform="translate(9 9) scale(0.0314) translate(-765 -765)" '
             'fill="currentColor">'
             '<path fill-rule="evenodd" d="M 494,818 L 626,504 L 711,503 L 800,711 '
             'L 803,711 L 1018,546 L 1032,538 L 1027,544 L 745,795 L 740,795 '
             'L 726,765 L 610,765 L 586,820 Z M 669,614 L 701,694 L 636,694 Z"/>'
             '<path d="M 871,713 L 867,712 L 560,989 L 587,971 L 781,825 '
             'L 783,1025 L 871,1024 Z"/></g>',
    "list": '<path d="M6 5h7"/><path d="M6 9h7"/><path d="M6 13h7"/><path d="M3.5 5h.01"/><path d="M3.5 9h.01"/><path d="M3.5 13h.01"/>',
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


def _og_image(digest: Digest) -> str:
    """The image a shared link should show: the lead story one, else empty.

    Only published stories carry `image_url`, so this cannot leak an unfetched URL. An empty
    string is correct rather than a placeholder: a wrong card is worse than no card, and every
    consumer falls back to the title when the property is absent or blank.
    """
    for event in digest.top_events:
        if event.image_urls:
            return event.image_urls[0]
    return ""


def _when(event: Event) -> tuple[str, bool]:
    if not event.published_range:
        return "时间未知", False
    # Beijing time, matching the archive's own dates.
    #
    # This printed UTC, so a story published at 05:47 Beijing on the 20th was labelled
    # "10-19 21:47 UTC". The reader sees "10-19" and concludes that the 20th's issue is full of
    # yesterday's news -- when every event in it is a Beijing-20th event. A date shown to a
    # Chinese reader has to be the date that reader would call it.
    when = event.published_range[0].astimezone(_SITE_TZ)
    return when.strftime("%m-%d %H:%M"), True


#: The site is Chinese and the digest dates are Beijing dates, so "today" must be a Beijing
#: date. `datetime.now(timezone.utc).astimezone()` uses the *build machine's* zone, which on a
#: GitHub runner is UTC -- eight hours behind. A build between 16:00 and 24:00 UTC produced a
#: page whose "today" was the previous day.
#:
#: The browser recomputes this anyway (see the calendars in `motion.js`); this is the value used
#: when scripting is off, and it must not disagree with the live one.
_SITE_TZ = ZoneInfo("Asia/Shanghai")


def _site_today() -> str:
    return datetime.now(_SITE_TZ).date().isoformat()



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
def rail_rss_copy(ctx: SiteContext, *, compact: bool = False) -> str:
    """The subscribe control: copies the feed address, never navigates to it.

    One function because the same control lives in three rails, and duplicating it is what
    let the first "copy instead of navigate" fix miss two of them -- `tibo.html` went on
    opening a wall of XML for a while after the home page was fixed.

    `compact` is for the secondary pages, whose rail is a short list of destinations rather
    than a full navigation panel.
    """
    base = esc(ctx.site_url.rstrip("/"))
    if compact:
        return (
            f'<button class="rail__item" type="button" data-copy="{base}/feed/zh.xml">'
            f'{icon("rss")}<span>复制订阅地址</span></button>'
        )
    return f"""<div class="rail__sub rail__sub--rss" role="menu">
                <button type="button" class="rail__btn" data-copy="{base}/feed/zh.xml">
                  <span class="rail__btn-k">RSS</span>复制订阅地址
                </button>
                <button type="button" class="rail__btn" data-copy="{base}/feed/zh.json">
                  <span class="rail__btn-k">JSON</span>复制订阅地址
                </button>
                <p class="rail__fine">
                  或在浏览器中查看
                  <a href="feed/zh.xml">RSS</a>
                  <a href="feed/zh.json">JSON</a>
                </p>
              </div>"""


def render_rail(ctx: SiteContext, digest: Digest, *, dated: bool = True) -> str:
    """The navigation rail: search, home, calendar, Tibo monitor, WeChat, RSS, theme, download.

    Order is the user's, and it is also a sensible reading order: find something, go to the
    newest, pick a date, then the secondary destinations, then settings.
    """
    prev_date, next_date = ctx.neighbours(digest.date)

    theme_items = "".join(
        f'<button type="button" data-theme-choice="{key}" aria-checked="false">{label}</button>'
        # 自动 and 默认 removed: a first visit is light, and after the reader picks a theme
        # that choice is stored and reused. Four ways to say "let the site decide" were three
        # too many.
        for key, label in (
            ("light", "亮色"),
            ("dark", "暗色"),
            # Claude's palette: a warm paper background rather than the usual neutral grey,
            # with its terracotta accent. Named after the product rather than described by its
            # colours, because that is how someone asks for it.
            ("claude-light", "Claude 亮色"),
            ("claude-dark", "Claude 暗色"),
        )
    )

    # **One edition, one link.**
    #
    # This offered "速览版" and "深度版" behind a fold. Both parts were wrong: the reader
    # thinks of the digest as one thing, so offering two names for the same day asks them to
    # choose between synonyms; and a fold makes them open a panel to reach a file they have
    # already decided to download. The full `.md` is the one kept -- it is the edition the
    # page itself renders -- and `download` tells the browser to save rather than navigate.
    download_items = (
        f'<a class="rail__item" href="{esc(digest.date)}.md" download>'
        f'{icon("download")}<span>下载 Markdown</span></a>'
    )
    download_block = (
        '<div class="rail__group" style="margin-top:calc(var(--unit) * 2)">'
        + download_items + "</div>"
    ) if dated else ""

    return f"""      <aside class="rail" aria-label="站点导航">
        <button class="rail__grip" type="button" data-resize="rail"
                aria-label="拖动调整左栏宽度" title="拖动调整宽度（双击恢复默认）"></button>
        <div class="rail__head">
          <a class="rail__brand" href="index.html">
            <span class="rail__mark" aria-hidden="true">{icon("brand", 18)}</span>
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
              <span>搜索往期内容</span>
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

          <!-- 微信公众号：暂无账号，先不放入口。留一个不能用的按钮比没有更糟。 -->

          <!-- 6. 订阅 RSS -->
          <div class="rail__group" style="margin-top:calc(var(--unit) * 2)">
            <details class="rail__fold">
              <summary class="rail__item">{icon("rss")}<span>订阅 RSS</span></summary>
              {rail_rss_copy(ctx)}
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

          <!-- 8. 下载 markdown（仅在有具体日期的页面上显示）
               首页的 rail 用的是最新一期，在这里放下载按钮等于让读者先猜自己要看哪一天。
               先把日期选出来，日期页再给出那一天的 markdown。 -->
          {download_block}

          <hr class="rail__sep">

          <div class="rail__group">
            <a class="rail__item" href="sources.html">{icon("rss")}<span>信息源</span></a>
            <a class="rail__item" href="https://github.com/siweimidu/ai-ribao" target="_blank" rel="noopener noreferrer">
              {icon("github")}<span>源码与说明</span>
            </a>
          </div>
        </div>
      </aside>"""


# ============================== right TOC =======================================
def _looks_chinese(text: str) -> bool:
    """True when a title has any CJK at all.

    Deliberately loose: "Gemini 4 Argon 全面开放" and "OpenAI 发布 GPT-6" are Chinese
    headlines that carry Latin proper nouns, which is what the digest is supposed to look
    like. What this filters is a title that is *entirely* foreign.
    """
    return any("\u4e00" <= ch <= "\u9fff" for ch in (text or ""))


def render_toc(
    events: list[Event],
    insights: dict[str, EventInsight] | None = None,
    items_by_id: dict[str, NormalizedItem] | None = None,
) -> str:
    """Right rail: an overview link plus every story of the day, in rank order.

    Three things this replaced, all of them the user's report:

    * **No section headings.** The page already groups by section; repeating that structure
      in the rail meant scrolling past eight group labels to reach the stories. The rail is
      for finding a story, so it is one flat list in rank order.
    * **No English.** A title that has not been translated yet is *skipped* rather than
      shown: the rail is the column the reader scans constantly, and it is the one place an
      English line cannot be avoided. The story is still on the page below.
    * **An 概览 entry at the top**, pointing at the day's summary, so the rail answers "what
      happened today" before "where is that one story".
    """
    insights = insights or {}
    rows: list[str] = ['<a href="#overview" class="toc__overview">概览</a>']

    for index, event in enumerate(events, start=1):
        insight = insights.get(event.event_id)
        title = _display_title(event, insight, items_by_id)
        if not _looks_chinese(title):
            continue
        anchor = f"e-{event.event_id[:10]}"
        label = title if len(title) <= 42 else title[:40] + "…"
        rows.append(
            f'<a href="#{esc(anchor)}">'
            f'<span class="toc__no">{index:02d}</span>{esc(label)}</a>'
        )

    if len(rows) == 1:
        return ""
    return f"""      <nav class="toc" aria-label="目录">
        <button class="toc__grip" type="button" data-resize="toc"
                aria-label="拖动调整目录宽度" title="拖动调整宽度（双击恢复默认）"></button>
        <p class="toc__title">今日目录</p>
        <div class="toc__nav">
{chr(10).join('          ' + r for r in rows)}
        </div>
      </nav>"""


# ============================== story ===========================================
def _display_title(
    event: Event,
    insight: EventInsight | None,
    items_by_id: dict[str, NormalizedItem] | None = None,
) -> str:
    """The best Chinese title available for an event.

    Order of preference:

    1. the model's title, when it is Chinese;
    2. **a Chinese member title**, when the model gave a foreign one (or none).

    Step 2 exists because of a real failure: on a day when the quota ran out mid-run, the
    top-ranked event was the Gemini 4 Argon launch -- and because its analysis had fallen back
    to the source's English wording, the page moved it into the collapsed "待翻译" block. The
    single biggest story of the day became the least visible thing on the page.

    A story carried by several sources often has a Chinese-language member: the same launch
    reported by a Chinese outlet. Choosing that title shows the reader the story in their own
    language, using a headline a real publisher wrote rather than one this code invented.
    """
    # A merged event records every headline it absorbed; prefer the longest one first, because
    # it is the phrasing that names what happened rather than a bare product string.
    merged = (event.unique_facts or {}).get("merged_titles") or []
    # Longest first: absorbed headlines are recorded in merge order, and the first is
    # often a bare product string while a later one says what happened. Length is a crude
    # but reliable proxy here, because every candidate describes the same release.
    candidates: list[str] = sorted((t for t in merged if t), key=len, reverse=True)
    if insight and insight.title:
        candidates.append(insight.title)
    candidates.append(event.title)
    if items_by_id:
        for item_id in event.member_item_ids:
            item = items_by_id.get(item_id)
            if item and item.title:
                candidates.append(item.title)

    for title in candidates:
        if _looks_chinese(title):
            return title.strip()
    # Nothing Chinese anywhere: return the model's title or the event's, unchanged, so the
    # caller can route it to the untranslated block.
    return (candidates[0] or "").strip()


def render_item(
    index: int,
    event: Event,
    insight: EventInsight | None,
    items_by_id: dict[str, NormalizedItem] | None = None,
    repo_meta: dict[str, dict] | None = None,
) -> str:
    title = _display_title(event, insight, items_by_id)
    anchor = f"e-{event.event_id[:10]}"
    # The archived `all_urls` was written by whatever ordering the pipeline used at the time,
    # and until 2026-10-21 that was a plain string sort -- which put the aggregator first on
    # every event it carried, so the title link opened `aihot.news/items/...` instead of the
    # original report. Sorting again here means an old issue renders correctly without being
    # regenerated, and the link can never disagree with the sources listed underneath.
    ordered_urls = sorted(event.all_urls or [], key=lambda u: (_url_directness(u), u))
    first_url = ordered_urls[0] if ordered_urls else "#"

    # The story image, when one was fetched. `loading=lazy` because a long issue has dozens
    # and none of the below-the-fold ones should block the first paint. Width and height are
    # not set: the aspect ratio varies per publisher, and a wrong pair causes layout shift.
    # Pictures in a horizontally scrolling row, each at its own proportions.
    #
    # The reference layout does exactly this and it is the right call: a story often has a wide
    # hero, a tall diagram and a long terminal screenshot, and cropping all three into one 16:9
    # frame destroys the information the reader wanted. `width:auto` plus a max-height keeps each
    # one legible; the row scrolls when they do not fit.
    image_html = ""
    if event.image_urls:
        thumbs = "".join(
            f'<a href="{esc(url)}" target="_blank" rel="noopener noreferrer">'
            f'<img src="{esc(url)}" alt="" loading="lazy" decoding="async"></a>'
            for url in event.image_urls
        )
        image_html = f'<div class="item__images">{thumbs}</div>'
    # **A repository story gets a repository card instead of a headline and a picture.**
    #
    # The card already carries the name, the description, the figures and the language bar, so
    # repeating a title above it would say the same thing twice. It also solves a real problem:
    # GitHub own Social Preview is a fixed grey template that ignores the site theme, and the
    # `og:image` on a repository page is often a generic banner rather than anything about the
    # project.
    #
    # The metadata is optional. `repo_meta` is filled when the run could reach the API; when it
    # is missing the item falls back to the ordinary headline, which is exactly what it looked
    # like before this feature existed.
    repo = None
    card = ""
    for candidate in ordered_urls:
        slug = repo_of(candidate)
        if slug:
            repo = slug
            break
    if repo and repo_meta and repo in repo_meta:
        data = repo_meta[repo]
        card = ghcard_html(
            full_name=data["full_name"],
            description=data["description"],
            stars=data["stars"],
            forks=data["forks"],
            contributors=data.get("contributors"),
            discussions=data.get("discussions"),
            languages=data.get("languages"),
            license_=data.get("license", ""),
            href=f"https://github.com/{repo}",
        )

    when_text, known = _when(event)

    # Recompute the publisher count from `source_ids` rather than trusting the archived number.
    #
    # The stored `independent_source_count` was computed by whatever version of the pipeline
    # produced that issue. Before 2026-10-20 it counted **feeds**, so an event carried by three
    # AIHOT sections claimed three independent sources -- and the page printed that claim next to
    # a list of links that were all `aihot.news`. A reader could see the contradiction.
    #
    # Recomputing here means an old issue renders honestly without being regenerated, and the
    # badge can never again disagree with the links underneath it.
    independent = len({_publisher_of(s, {}) for s in event.source_ids}) or event.independent_source_count

    level = event.evidence_level if independent > 1 else "single_source"
    label = "多源交叉验证" if level == "multi_source" else "单一来源"
    # Two facts, two elements. Joining them with a middle dot produced the `A · B` chrome
    # that reads as generated, and the separator was carrying no meaning anyway.
    count_note = f"<span>{independent} 个独立来源</span>" if independent > 1 else ""

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
        # One rounded panel per block. The reference layout puts every factual block in its own
        # card inside the story card, which is what makes a long entry scannable: each block has a
        # visible boundary, so "how much is established" is legible at a glance instead of being
        # inferred from a paragraph.
        blocks.append(
            f'<div class="factcard" data-kind="{kind}">'
            f'<p class="facts__label" data-kind="{kind}">{name}</p><ul>{lis}</ul></div>'
        )
    evidence = f'<div class="facts">{"".join(blocks)}</div>' if blocks else ""

    if insight is None or getattr(insight, "rule_based", False):
        evidence += (
            '<div class="facts"><div class="factcard" data-kind="fact">'
            '<p class="facts__label" data-kind="fact">来源摘录</p>'
            '<ul><li data-kind="fact">本条未调用大模型，内容为来源原文摘录。</li></ul></div></div>'
        )

    # Sources are shown by **publisher**, not by URL.
    #
    # The previous version listed `event.all_urls[1:5]` and called the remainder "另有 N 个来源".
    # Measured on 2026-10-21 that produced six `aihot.news` links followed by "另有 6 个来源" --
    # one publisher, twelve feeds, presented as if twelve outlets had corroborated the story.
    # The count that matters (`independent_source_count`) already collapses feeds by publisher;
    # the label did not, so the page contradicted its own evidence badge.
    #
    # One link per distinct host, first occurrence wins: that is what a reader can act on. URLs
    # are de-duplicated too, because one publisher often surfaces the same story through several
    # of its own feeds.
    # **Mirrors are not sources.**
    #
    # A story carried by arstechnica, cnbc and engadget, plus aihot.news relaying it, has three
    # sources and one copy. Listing the aggregator among them credits it with reporting it did
    # not do -- and its page is not where a reader who wants the original should land.
    #
    # `_url_directness` already ranks these for the title link; the same judgement applies here.
    # When every URL is a mirror the row stays empty, which is honest: there is no publisher to
    # name.
    seen_hosts: set[str] = set()
    per_host: list[str] = []
    for url in ordered_urls:
        if _url_directness(url) != 0:
            continue
        host = _domain(url)
        if host in seen_hosts:
            continue
        seen_hosts.add(host)
        per_host.append(url)

    others = per_host[1:5]
    links = "".join(
        f'<a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(_domain(u))}</a>'
        for u in others
    )
    extra_urls = per_host[5:]
    if extra_urls:
        # The remainder used to be a dead `<span>`, so "另有 3 家其他来源" was a claim a reader
        # could neither verify nor click. A `<details>` keeps the row short by default and makes
        # the rest reachable: one line per hidden publisher, each a real link.
        hidden = "".join(
            f'<li><a href="{esc(u)}" target="_blank" rel="noopener noreferrer">{esc(_domain(u))}</a></li>'
            for u in extra_urls
        )
        links += (
            f'<details class="item__more"><summary>另有 {len(extra_urls)} 家其他来源</summary>'
            f'<ul>{hidden}</ul></details>'
        )
    links = f'<div class="item__links">{links}</div>' if links else ""

    # A repository story is rendered as the card itself: repeating a headline above it would say
    # the same thing twice, and the card already carries the name, the description and the
    # figures. The number stays so the reader can still count entries and follow anchors.
    if card:
        head_html = (
            f'<div class="item__head item__head--card">'
            f'<span class="item__no">{index:02d}</span>'
            f'<div class="item__cardwrap">{card}</div>'
            '</div>'
        )
        image_html = ""
    else:
        head_html = (
            '<div class="item__head">'
            f'<span class="item__no">{index:02d}</span>'
            f'<h3 class="item__title"><a href="{esc(first_url)}" target="_blank" rel="noopener noreferrer">{esc(title)}</a></h3>'
            '</div>'
        )

    when_cls = "" if known else ' class="when-unknown"'

    return f"""        <li class="item" id="{esc(anchor)}">
          {head_html}
          {image_html}
          <div class="item__meta">
            <span class="badge" data-level="{esc(level)}">{esc(label)}</span>
            {count_note}
            <span{when_cls}>{esc(when_text)}</span>
            <a href="{esc(first_url)}" target="_blank" rel="noopener noreferrer">{esc(_domain(first_url))}</a>
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
# ============================== overview ========================================
def _render_overview(
    digest: Digest,
    insights: dict[str, EventInsight],
    translated_ids: set[str] | None = None,
    items_by_id: dict[str, NormalizedItem] | None = None,
) -> str:
    """The day at a glance: the top stories, one line each, before the full list.

    This is the "概览" the user asked for. It answers "what happened today" in a few
    seconds, which the full sectioned list cannot: by the time a reader has scrolled eight
    groups they have read more than they wanted to.

    Built from the same ranked events as the body, so the overview can never disagree with
    the list below it. Every line is a real headline from the digest, not a generated
    summary -- a summary here would be a second, unchecked claim about the day.
    """
    translated_ids = translated_ids or set()
    rows: list[str] = []
    for index, event in enumerate(digest.top_events, start=1):
        if len(rows) >= 8:
            break
        # Only items that made it into the body, so the overview never links to an anchor
        # that was moved into the untranslated block.
        if translated_ids and event.event_id not in translated_ids:
            continue
        insight = insights.get(event.event_id)
        title = _display_title(event, insight, items_by_id)
        if not _looks_chinese(title):
            continue
        anchor = f"e-{event.event_id[:10]}"

        # The first supporting fact, when there is one, is what makes the line informative
        # rather than a second headline.
        detail = ""
        if insight and insight.facts:
            fact = insight.facts[0].strip()
            if fact and fact != title and len(fact) <= 120:
                detail = fact
        rows.append(
            f'<li><a href="#{esc(anchor)}">'
            f'<span class="ov__no">{index:02d}</span>'
            f"<span><b>{esc(title)}</b>"
            + (f'<span class="ov__detail">{esc(detail)}</span>' if detail else "")
            + "</span></a></li>"
        )

    if not rows:
        return ""

    counts = digest.counts
    multi = counts.get("multi_source_events", 0)
    return f"""      <section class="section overview" id="overview">
        <h2 class="section__title">概览<span class="section__count">今日要闻</span></h2>
        <ol class="ov">{''.join(rows)}</ol>
        <p class="ov__foot">今日共 {counts.get('events', 0)} 条事件，
        其中 {multi} 条经多个独立来源交叉验证。下面是完整列表。</p>
      </section>"""


def render_day(
    digest: Digest,
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem],
    ctx: SiteContext,
    repo_meta: dict[str, dict] | None = None,
) -> str:
    toc = render_toc(digest.top_events, insights, items_by_id)

    # One flat list, in heat order.
    #
    # It used to be grouped by **source category** -- 实验室博客, 科技媒体, 中文媒体, 社区讨论,
    # 其它 -- which is an ordering by where a story came from, not by whether it matters. The
    # measured result: `Gemini 4 Argon 全面开放` sat at **position 18 of the body**, under
    # three sections of unrelated news, on the day it was the biggest story in the industry.
    # That is precisely the "把无关紧要的东西放在前面" the user reported.
    #
    # The reference sites agree: daily.juya.uk renders one numbered list with no grouping at
    # all. The ranker already computes the order; the page's job is to show it.
    #
    # The page must also read as Chinese. When model quota runs out mid-run the items past
    # the cut fall back to the source's own words -- for an English feed, an English sentence
    # rendered as the digest's own writing. So untranslated items are collected into one
    # collapsed block at the end: visible, labelled, reachable, but not mixed into the digest
    # as though it were finished work. Nothing is dropped -- the source stays in the registry
    # and the item stays in the archive.
    translated_ids: set[str] = set()
    untranslated: list[tuple[int, Event]] = []
    rows: list[str] = []
    counter = 0

    for event in digest.top_events:
        counter += 1
        insight = insights.get(event.event_id)
        title = _display_title(event, insight, items_by_id)
        if not _looks_chinese(title):
            untranslated.append((counter, event))
            continue
        translated_ids.add(event.event_id)
        rows.append(render_item(counter, event, insight, items_by_id, repo_meta))

    body: list[str] = []
    if rows:
        body.append(
            f"""      <section class="section" id="all">
        <h2 class="section__title">全部消息<span class="section__count">{len(rows)} 条</span></h2>
        <ol class="stream">
{chr(10).join(rows)}
        </ol>
      </section>"""
        )

    untranslated_block = ""
    if untranslated:
        items = "".join(
            f'<li><span class="untranslated__no">{n:02d}</span>'
            f'<a href="{esc((e.all_urls or ["#"])[0])}" target="_blank" rel="noopener noreferrer">{esc(e.title)}</a>'
            f'<span class="untranslated__src">{esc(_domain((e.all_urls or [""])[0]))}</span></li>'
            for n, e in untranslated
        )
        untranslated_block = f"""      <details class="untranslated" id="untranslated">
        <summary>本期待翻译条目（{len(untranslated)} 条）</summary>
        <p>这些条目的来源是外文，且本期模型额度用完、未能逐条译成中文，
        因此只在这里保留原文与出处，不混进上面的正文。
        <strong>点开即离开本站、前往原文</strong>。</p>
        <ol>{items}</ol>
      </details>"""

    overview = _render_overview(digest, insights, translated_ids, items_by_id)

    # The headline shown at the top of the page.
    #
    # Taken from the highest-ranked event **as displayed**, not from `digest.headline`.
    # That field is written once when the digest is generated, so after any re-rank it
    # describes the previous ordering: a measured run had the body leading with Gemini 4
    # Argon while the h1 still announced an Apple smart speaker. Two elements on one page
    # disagreeing about what the day's top story is looks like a bug to the reader, and it
    # is one.
    headline = _display_title(
        digest.top_events[0], insights.get(digest.top_events[0].event_id), items_by_id
    ) if digest.top_events else (digest.headline or digest.date)

    lead = ""
    for event in digest.top_events[:1]:
        insight = insights.get(event.event_id)
        if insight and insight.facts:
            lead = insight.facts[0]
        elif event.member_item_ids:
            item = items_by_id.get(event.member_item_ids[0])
            if item is not None:
                lead = (item.summary or "")[:200]

    # 本期说明 was removed on request: the run metadata (key counts, provider list, rubric
    # calibration) is operator information, not something a reader of the day's news wants above
    # the first headline. It stays in the archived JSON, where `check` and the audit tools read it.
    warnings = ""

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
        "today": _site_today(),
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
<link rel="image_src" href="{esc(_og_image(digest))}">
<meta property="og:image" content="{esc(_og_image(digest))}">
<meta name="twitter:card" content="summary_large_image">
<link rel="alternate" type="application/rss+xml" title="AI 日报" href="feed/zh.xml">
<link rel="alternate" type="application/feed+json" title="AI 日报" href="feed/zh.json">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
  <!-- Theme read before first paint.
       `motion.js` is deferred, so it runs after the document parses -- which means the
       browser has already painted the default light theme and then repaints with the saved
       one. That repaint is the flash seen on every navigation. This inline block runs while
       the head is still parsing, so the attribute is set before anything is drawn. It is
       intentionally duplicated by motion.js (which owns the UI); here it only needs to be
       fast and to survive JS being disabled afterwards. -->
  <script>(function(){{try{{var t=localStorage.getItem('aidaily-theme');if(t&&t!=='auto'&&t!=='default'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>

<div class="shell">
{render_rail(ctx, digest)}

  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date enter">{esc(digest.date)}　第 {len(ctx.archive)} 期</p>
      <h1 class="issue__title enter">{esc(headline)}</h1>
      {f'<p class="issue__lead enter">{esc(lead[:200])}</p>' if lead else ''}
      {_stats(digest)}
    </header>

    {warnings}

    {overview}

{chr(10).join(body)}

    {untranslated_block}

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
<p>生成于 {digest.generated_at.astimezone(_SITE_TZ).strftime('%Y-%m-%d %H:%M')} 北京时间</p>
    </footer>
  </main>

{toc}
</div>

<dialog class="search" id="search-dialog" aria-label="搜索往期内容">
  <div class="search__form">
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
def _archive_row(date: str, count: int, *, latest: bool = False) -> str:
    """One issue in the archive list.

    The date and the count are separate elements with their own alignment rather than two
    inline spans, which is what made them collide: `2026-10-14224 条` on one line. The date
    is a fixed-width column so a list of issues reads as a table, and the count is right
    aligned so the numbers line up down the column.
    """
    weekday = ""
    try:
        d = datetime.strptime(date, "%Y-%m-%d").date()
        # Monday is 0 in Python; the label string starts at 日, so shift by one and wrap.
        weekday = "日一二三四五六"[(d.weekday() + 1) % 7]
    except ValueError:
        weekday = ""

    # The badge cell is always emitted, empty when there is no badge.
    #
    # It used to be conditional, which meant a row with a badge had five children and a row
    # without had four. With a four-track grid the count then landed in an implicit fifth track
    # on the badge row and in the fourth on every other row -- visible as a ragged right edge.
    # Reserving the cell costs no width (`auto` collapses) and keeps every count aligned.
    # `hidden` would not work: a hidden element is not a grid item at all, so the cell
    # disappears and the count slides into its place.
    badge = '<span class="issue-row__badge">最新</span>' if latest else '<span class="issue-row__badge"></span>'
    return (
        f'<li><a class="issue-row" href="{esc(date)}.html">'
        f'<span class="issue-row__date">{esc(date)}</span>'
        f'<span class="issue-row__week">周{esc(weekday)}</span>'
        f"{badge}"
        f'<span class="issue-row__count">{count} 条</span>'
        f"</a></li>"
    )


def render_index(ctx: SiteContext, latest: Digest | None) -> str:
    """Archive list, grouped by month so that a year of issues stays scannable."""
    by_month: dict[str, list[tuple[str, int]]] = {}
    for date, count in ctx.archive:
        by_month.setdefault(date[:7], []).append((date, count))

    newest = max(ctx.archive, key=lambda x: x[0])[0] if ctx.archive else None

    groups = []
    for month in sorted(by_month, reverse=True):
        rows = "".join(
            _archive_row(d, c, latest=(d == newest))
            for d, c in sorted(by_month[month], reverse=True)
        )
        groups.append(
            f'<section class="section"><h2 class="section__title">{esc(month)}'
            f'<span class="section__count">{len(by_month[month])} 期</span></h2>'
            f'<ol class="issue-list">{rows}</ol></section>'
        )

    calendar_data = {
        "dates": ctx.dates,
        "current": latest.date if latest else None,
        "today": _site_today(),
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
  <!-- Theme read before first paint.
       `motion.js` is deferred, so it runs after the document parses -- which means the
       browser has already painted the default light theme and then repaints with the saved
       one. That repaint is the flash seen on every navigation. This inline block runs while
       the head is still parsing, so the attribute is set before anything is drawn. It is
       intentionally duplicated by motion.js (which owns the UI); here it only needs to be
       fast and to survive JS being disabled afterwards. -->
  <script>(function(){{try{{var t=localStorage.getItem('aidaily-theme');if(t&&t!=='auto'&&t!=='default'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<div class="shell">
{render_rail(ctx, latest, dated=False) if latest else ''}
  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date enter">全部往期</p>
      <h1 class="issue__title enter">AI 日报</h1>
      <p class="issue__lead enter">每日自动聚合 AI 领域的信息源，去重、交叉验证，并区分事实与推断。</p>
      <div class="stats stats--pair enter">
        <div><b>{len(ctx.archive)}</b><span>期已发布</span></div>
        <div><b>{sum(c for _, c in ctx.archive)}</b><span>条事件</span></div>
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


def render_event_calendar(events: list[dict]) -> str:
    """A month calendar of reset events, with the selected day's detail beside it.

    Same visual language as the navigation calendar in the rail, but a different job: that
    one answers "which day do I want to read", this one answers "what happened that day".
    So the cells are larger, carry per-event markers, and sit next to a detail panel.

    The grid is rendered on the client from inlined JSON. Dates and events are server data,
    but the month being shown is a viewing state -- rendering twelve months of markup for a
    page that shows one would be waste.
    """
    by_day: dict[str, list[dict]] = {}
    for event in events:
        day = (event.get("created_at") or "")[:10]
        if day:
            by_day.setdefault(day, []).append(event)

    if not by_day:
        return (
            '<div class="ecal__card"><p class="ecal__empty">还没有可显示的记录。</p></div>'
        )

    # Newest first so the page opens on the most recent activity rather than on an empty
    # current month.
    days = sorted(by_day, reverse=True)
    latest = days[0]

    return f"""      <div class="ecal" id="event-calendar">
        <div class="ecal__card">
          <div class="ecal__head">
            <span class="ecal__month" data-ecal-month>—</span>
            <span class="ecal__nav">
              <button type="button" data-ecal-nav="prev" aria-label="上个月">‹</button>
              <button type="button" data-ecal-nav="next" aria-label="下个月">›</button>
            </span>
          </div>
          <div class="ecal__grid" data-ecal-grid role="grid">
            <span class="ecal__dow">日</span><span class="ecal__dow">一</span>
            <span class="ecal__dow">二</span><span class="ecal__dow">三</span>
            <span class="ecal__dow">四</span><span class="ecal__dow">五</span>
            <span class="ecal__dow">六</span>
          </div>
          <div class="ecal__legend">
            <span><i data-kind="direct_reset"></i>额度重置</span>
            <span><i data-kind="reset_credit"></i>重置卡</span>
            <span><i data-kind="today"></i>今天</span>
          </div>
        </div>
        <div class="ecal__panel" data-ecal-panel aria-live="polite">
          <div class="ecal__empty">选择一个有记录的日期。</div>
        </div>
      </div>"""


def _ecal_event(event: dict) -> dict:
    """The shape the calendar needs, trimmed so the inlined JSON stays small."""
    return {
        "d": (event.get("created_at") or "")[:10],
        "t": event.get("title") or "",
        "l": event.get("label") or "",
        "k": event.get("kind") or "",
        "s": event.get("status") or "",
        "sc": event.get("scope") or "",
        "sch": event.get("schedule_label") or "",
        "at": (event.get("created_at") or "")[11:16],
        "posts": [
            {"stage": p.get("stage") or "", "text": p.get("text") or "",
             "orig": p.get("original") or "", "url": p.get("url") or ""}
            for p in (event.get("posts") or [])[:3]
        ],
    }


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
        "today": _site_today(),
    }

    event_calendar = render_event_calendar(events) if events else ""
    event_payload = json.dumps(
        [_ecal_event(e) for e in events] if events else [], ensure_ascii=False
    )

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
                + (f'<a href="{esc(p.get("url"))}" target="_blank" rel="noopener noreferrer" style="font-size:var(--fs-small);color:var(--muted-fg)">在原站查看 ↗</a>' if p.get("url") else "")
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
            + (f'<a href="{esc(a.get("url"))}" target="_blank" rel="noopener noreferrer" style="font-size:var(--fs-small);color:var(--muted-fg)">在原站查看 ↗</a>' if a.get("url") else "")
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
          <a href="{esc(attribution.get('url') or '')}" target="_blank" rel="noopener noreferrer">{esc(attribution.get('name') or '')}</a>
          的公开接口。{esc(attribution.get('note') or '')}</p>
          {policy_note}
          <p><a href="{esc(str(policy.get('terms_url') or 'https://aihot.news/terms'))}" target="_blank" rel="noopener noreferrer">完整使用规则</a></p>
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
  <!-- Theme read before first paint.
       `motion.js` is deferred, so it runs after the document parses -- which means the
       browser has already painted the default light theme and then repaints with the saved
       one. That repaint is the flash seen on every navigation. This inline block runs while
       the head is still parsing, so the attribute is set before anything is drawn. It is
       intentionally duplicated by motion.js (which owns the UI); here it only needs to be
       fast and to survive JS being disabled afterwards. -->
  <script>(function(){{try{{var t=localStorage.getItem('aidaily-theme');if(t&&t!=='auto'&&t!=='default'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<div class="shell">
  <aside class="rail" aria-label="站点导航">
    <button class="rail__grip" type="button" data-resize="rail"
            aria-label="拖动调整左栏宽度" title="拖动调整宽度（双击恢复默认）"></button>
    <a class="rail__brand" href="index.html"><span class="rail__mark" aria-hidden="true">{icon("brand", 18)}</span><span>AI 日报</span></a>
    <hr class="rail__sep">
    <div class="rail__group">
      <a class="rail__item" href="index.html">{icon("home")}<span>首页</span></a>
      <a class="rail__item" href="tibo.html" aria-current="page">{icon("clock")}<span>Tibo 重置监控</span></a>
      {rail_rss_copy(ctx, compact=True)}
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
      <h2 class="section__title">重置日历<span class="section__count">{len(events)} 条记录</span></h2>
      {event_calendar}
    </section>
    <section class="section" id="sec-list">
      <h2 class="section__title">重置记录<span class="section__count">{len(events)} 条</span></h2>
      {event_list}
    </section>
    {activity_block}
    <nav class="pager"><a href="index.html"><span>返回</span>往期索引</a></nav>
  </main>
</div>
<script type="application/json" id="calendar-data">{json.dumps(calendar_data, ensure_ascii=False)}</script>
<script type="application/json" id="tibo-events">{event_payload}</script>
<script src="assets/motion.js" defer></script>
</body>
</html>
"""


def load_health(state_dir: Path) -> dict[str, dict]:
    """The last collection verdict per source, from `data/state/collect.jsonl`.

    The registry's own `health_status` field is written by the build script and is always
    `unverified` -- it is a schema placeholder, not a measurement. The page showed
    "本轮采集成功 0" because it read that field. The actual result of the last run lives in
    the append-only collect log, so the page reads the newest row per source from there.

    Returns {} when the log is missing, and the page then says so rather than claiming a
    status it does not have.
    """
    path = state_dir / "collect.jsonl"
    if not path.exists():
        return {}
    newest: dict[str, dict] = {}
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = row.get("source_id")
            if not sid:
                continue
            # Rows are appended in run order, so the last one wins.
            newest[sid] = row
    except OSError:
        return {}
    return newest


def state_html(label: str) -> str:
    """Render a source state as a badge, splitting an item count into its own element.

    `state_of` returns `"正常|277"` for a source that collected 277 items. The two facts get
    separate elements rather than one string joined by a middle dot, which this project's
    own design rule bans as template chrome.
    """
    name, _, count = label.partition("|")
    state = {
        "正常": "ok", "采集失败": "failed", "待凭证": "credential",
        "未启用": "disabled",
    }.get(name, "unknown")
    tail = f'<span class="source-row__items">{esc(count)} 条</span>' if count else ""
    return (
        f'<span class="source-row__state" data-state="{state}">'
        f"<span>{esc(name)}</span>{tail}</span>"
    )


def render_sources(
    ctx: SiteContext,
    sources: list[dict],
    digest: Digest | None = None,
    health: dict[str, dict] | None = None,
) -> str:
    """Where the information comes from.

    The user asked for a page showing the sources, so this is the registry rendered for a
    reader rather than for a maintainer: grouped by what kind of source it is, with the
    live state of each one.

    Three things it deliberately does not do:

    * **It does not hide broken sources.** The project's rule is that a source is never
      deleted, and a page listing only the working ones would misrepresent the pipeline's
      actual coverage -- including the ones waiting on credentials.
    * **It does not invent a count.** The headline numbers come from the same registry the
      collector reads.
    * **It does not show credentials.** A source needing a key shows the *name* of the
      environment variable, never a value.
    """
    # Order groups the way a reader thinks about provenance, not alphabetically.
    group_order = [
        ("lab-official", "官方一手"),
        ("lab-blog", "实验室与团队博客"),
        ("paper", "论文与研究"),
        ("media", "科技媒体"),
        ("zh-media", "中文媒体"),
        ("news", "新闻聚合"),
        ("social", "社交媒体"),
        ("community", "社区讨论"),
        ("dev", "开发者动态"),
        ("digest", "编辑精选与简报"),
        ("product", "产品发布"),
        ("model", "模型与数据集"),
        ("dataset", "数据集"),
        ("mixed", "综合来源"),
        ("search", "检索聚合"),
        ("trend", "趋势信号"),
        ("preset", "预设源"),
        ("example", "示例源"),
        ("other", "其它"),
    ]
    known = {key for key, _ in group_order}

    by_group: dict[str, list[dict]] = {}
    for spec in sources:
        by_group.setdefault(spec.get("category") or "other", []).append(spec)

    # Any category not in the list still gets rendered, under its own name. A fixed
    # grouping table silently dropped 11 of 81 sources the first time -- exactly the
    # "sources are never deleted" rule this project runs on, applied to its own UI.
    for category in sorted(set(by_group) - known):
        group_order.insert(-1, (category, CATEGORY_LABELS.get(category, category)))

    def state_of(spec: dict) -> tuple[str, str]:
        """(label, machine state) for one source.

        Precedence: a credential wait and a deliberate disable are *stated* facts about the
        source, while a collection verdict is a measurement. A disabled source that happened
        to succeed once should still read as disabled.
        """
        if spec.get("needs_credential"):
            return "待凭证", "credential"
        if not spec.get("enabled", True):
            return "未启用", "disabled"

        row = (health or {}).get(spec.get("source_id") or "")
        if row:
            verdict = (row.get("verdict") or "").lower()
            items = row.get("items")
            if verdict in ("ok", "success"):
                # Two facts, two elements -- the CSS gives them separate styling. Joined
                # with a middle dot they were flagged by this project's own rule against
                # `A · B` metadata chrome, which is a template tell in the rendered page.
                return (f"正常|{items}" if isinstance(items, int) else "正常|"), "ok"
            if verdict in ("failed", "error", "timeout"):
                return "采集失败", "failed"
            if verdict == "skipped":
                return "已跳过", "unknown"
            return "已探测", "unknown"

        return "本轮未采集", "unknown"

    groups_html = []
    for key, label in group_order:
        rows = by_group.get(key)
        if not rows:
            continue
        items = []
        for spec in sorted(rows, key=lambda s: (s.get("priority", 9), s.get("name") or "")):
            state_label, state = state_of(spec)
            meta_bits = [
                f'级别 {spec.get("priority", "—")}',
                spec.get("language") or "—",
                spec.get("source_type") or "—",
            ]
            repo = (spec.get("repositories") or [None])[0]
            if repo:
                meta_bits.append(f"来自 {repo}")
            if spec.get("added_locally"):
                meta_bits.append("本地增补")
            cred = spec.get("needs_credential")
            if cred:
                # The variable *name* only. A value here would be a credential leak on a
                # public page, which is the one thing this project forbids outright.
                meta_bits.append(f"需要 {cred}")
            # The whole row is the link. A source row exists to be visited, and making the
            # reader hunt for the URL text (which is one line of 10px grey type) is the
            # difference between a list and a doorway. Links open in a new tab: the reader is
            # browsing a digest, and replacing it with a source page throws away their place --
            # the back button is not the same as never having left.
            link = spec.get("url") or ""
            inner = (
                f'<div>'
                f'<div class="source-row__name">{esc(spec.get("name") or spec.get("source_id"))}</div>'
                f'<div class="source-row__meta">'
                + "".join(f"<span>{esc(b)}</span>" for b in meta_bits)
                + "</div>"
                f'<div class="source-row__url">{esc(link)}</div>'
                f"</div>"
                + state_html(state_label)
            )
            if link.startswith(("http://", "https://")):
                items.append(
                    f'<li><a class="source-row" href="{esc(link)}"'
                    f' target="_blank" rel="noopener noreferrer">{inner}</a></li>'
                )
            else:
                # A source with no http URL (an `external` push, say) is not clickable; keep it
                # as a row rather than rendering a dead link.
                items.append(f'<li><div class="source-row">{inner}</div></li>')
        groups_html.append(
            f'<section class="section" id="src-{esc(key)}">'
            f'<h2 class="section__title">{esc(label)}'
            f'<span class="section__count">{len(rows)} 个</span></h2>'
            f'<ul class="source-list">{"".join(items)}</ul></section>'
        )

    total = len(sources)
    enabled = sum(1 for s in sources if s.get("enabled", True))
    ok = sum(1 for s in sources if state_of(s)[1] == "ok")
    need_cred = sum(1 for s in sources if s.get("needs_credential"))
    probed = sum(1 for s in sources if (s.get("source_id") or "") in (health or {}))

    toc = [
        (f"src-{key}", label)
        for key, label in group_order
        if by_group.get(key)
    ]

    calendar_data = {
        "dates": ctx.dates,
        "current": None,
        "today": _site_today(),
    }

    return f"""<!doctype html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>信息源 · AI 日报</title>
<meta name="description" content="AI 日报的全部信息源与各自的采集状态">
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
  <!-- Theme read before first paint.
       `motion.js` is deferred, so it runs after the document parses -- which means the
       browser has already painted the default light theme and then repaints with the saved
       one. That repaint is the flash seen on every navigation. This inline block runs while
       the head is still parsing, so the attribute is set before anything is drawn. It is
       intentionally duplicated by motion.js (which owns the UI); here it only needs to be
       fast and to survive JS being disabled afterwards. -->
  <script>(function(){{try{{var t=localStorage.getItem('aidaily-theme');if(t&&t!=='auto'&&t!=='default'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
</head>
<body>
<a class="skip" href="#main">跳到正文</a>
<div class="shell">
  <aside class="rail" aria-label="站点导航">
    <button class="rail__grip" type="button" data-resize="rail"
            aria-label="拖动调整左栏宽度" title="拖动调整宽度（双击恢复默认）"></button>
    <a class="rail__brand" href="index.html"><span class="rail__mark" aria-hidden="true">{icon("brand", 18)}</span><span>AI 日报</span></a>
    <hr class="rail__sep">
    <div class="rail__group">
      <a class="rail__item" href="index.html">{icon("home")}<span>首页</span></a>
      <a class="rail__item" href="tibo.html">{icon("clock")}<span>Tibo 重置监控</span></a>
      <a class="rail__item" href="sources.html" aria-current="page">{icon("list")}<span>信息源</span></a>
    </div>
  </aside>
  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date">采集范围</p>
      <h1 class="issue__title">信息源</h1>
      <p class="issue__lead">日报里的每一条都来自下面这些源。源的清单不会删除，
      失效的也保留并标出状态 —— 这样覆盖率是看得见的。</p>
      <div class="stats">
        <div><b>{total}</b><span>已注册源</span></div>
        <div><b>{enabled}</b><span>已启用</span></div>
        <div><b>{probed}</b><span>本轮采集</span></div>
        <div><b>{ok}</b><span>采集成功</span></div>
        <div><b>{need_cred}</b><span>待凭证</span></div>
      </div>
      {'' if health else '<p class="issue__date" style="margin-top:calc(var(--unit) * 3)">没有找到本轮采集记录，各源状态显示为「本轮未采集」。</p>'}
    </header>

    <nav class="notice" aria-label="按类别跳转">
      <p>按类别：{" · ".join(f'<a href="#{esc(slug)}">{esc(label)}</a>' for slug, label in toc)}</p>
    </nav>

    {''.join(groups_html)}

    <footer class="foot">
      <p>源的清单由 <code>sources/registry.yaml</code> 与 <code>sources/local.yaml</code>
      生成，前者来自对六个参考仓库的静态审计，后者登记之后新增的源。
      两处都遵循同一条规则：<strong>源只增不删</strong>，停用要写明理由。</p>
      <p>需要凭证的源只显示环境变量名，不显示取值。</p>
    </footer>
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
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
  <!-- Theme read before first paint.
       `motion.js` is deferred, so it runs after the document parses -- which means the
       browser has already painted the default light theme and then repaints with the saved
       one. That repaint is the flash seen on every navigation. This inline block runs while
       the head is still parsing, so the attribute is set before anything is drawn. It is
       intentionally duplicated by motion.js (which owns the UI); here it only needs to be
       fast and to survive JS being disabled afterwards. -->
  <script>(function(){{try{{var t=localStorage.getItem('aidaily-theme');if(t&&t!=='auto'&&t!=='default'){{document.documentElement.setAttribute('data-theme',t);}}}}catch(e){{}}}})();</script>
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
#: Page names that are not issues. Anything that is not an ISO date and not in this set is
#: still treated as an issue, so a new *issue* page can never be missed -- but a new
#: non-issue page has to be added here, which is why the check is by shape first.
NON_ISSUE_PAGES = {"index", "404", "tibo", "sources"}

_ISSUE_NAME = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def load_archive(digest_dir: Path) -> list[tuple[str, int]]:
    """Rebuild the archive from the **digests on disk**, never from pages already written.

    Reading the site's own HTML made the archive depend on render order. Pages are only
    re-rendered when their own digest changes, so a page written early keeps the date list it
    was born with forever: measured on the published site, `2026-10-14.html` embedded
    `dates=['2026-10-14']` and `2026-10-15.html` embedded `['2026-10-15', '2026-10-14']` --
    from the 14th the reader could not reach the 15th or the 16th, and from the 15th not the
    16th. The rail calendar looked broken on every page except the newest one.

    The digests directory is the source of truth: every page must see every issue. Counts come
    from each digest; a file that will not parse contributes a 0 rather than being dropped,
    because a missing row would make the calendar hide that day entirely.

    Matched by ISO-date filename shape, not by an exclusion list: the exclusion list is what
    broke when `sources.html` was added and the site reported two issues on a day with one.
    """
    out: list[tuple[str, int]] = []
    if not digest_dir.exists():
        return out
    for path in sorted(digest_dir.glob("????-??-??.json"), reverse=True):
        try:
            doc = json.loads(path.read_text(encoding="utf-8"))
            count = len(((doc.get("digest") or {}).get("top_events")) or [])
        except (OSError, ValueError):
            count = 0
        out.append((path.stem, count))
    return out


def _load_archive_from_html(site_dir: Path) -> list[tuple[str, int]]:
    """The previous HTML-based scan, kept for reference and not called.

    Deleting it would hide why it was wrong; the failure mode is subtle enough that the next
    person to touch archive loading should meet the explanation.
    """
    out: list[tuple[str, int]] = []
    if not site_dir.exists():
        return out
    for path in sorted(site_dir.glob("*.html"), reverse=True):
        if path.stem in NON_ISSUE_PAGES or not _ISSUE_NAME.match(path.stem):
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


def _rerender_archived_issue(
    site: Path, out_dir: Path, date: str, ctx: SiteContext,
    repo_meta: dict[str, dict] | None = None,
) -> int:
    """Rebuild one past issue page from its archived JSON. Returns 1 when written.

    The archive stores the digest with `sections` excluded and the layout beside it as
    `{category: [event_id]}`; validating `digest` alone yields a Digest whose sections are empty,
    which would silently move every story to 「其它」. That reattachment is the reason this helper
    exists rather than a one-line model_validate.

    A missing or unreadable archive is skipped, not raised: one damaged file must not stop the
    day's publish. The count is reported in the manifest so the skip is visible.
    """
    path = out_dir / f"{date}.json"
    if not path.exists():
        return 0
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        doc = dict(payload["digest"])
        by_id = {e["event_id"]: e for e in doc.get("top_events", [])}
        doc["sections"] = {
            category: [by_id[eid] for eid in ids if eid in by_id]
            for category, ids in (payload.get("sections") or {}).items()
        }
        past = Digest.model_validate(doc)
        # The archived insights carry the model-written title, the facts and the evidence level.
        # Passing {} (as the first version did) left every headline empty, and the renderer then
        # skipped the stories it could not title -- measured: 2026-10-14 went from 21 stories to 6.
        archived_insights = {
            event_id: EventInsight(**raw)
            for event_id, raw in (payload.get("insights") or {}).items()
        }
    except Exception:
        return 0

    # `items_by_id` must not be empty: `render_day` looks each event's members up there and drops
    # those it cannot find, so passing {} silently shrank 2026-10-14 from 21 stories to 6. A
    # placeholder item per member is enough for rendering -- the page only reads title, url and
    # summary from them -- and keeps the archive the single source of truth.
    items_by_id: dict[str, NormalizedItem] = {}
    for event in past.top_events:
        for member_id in event.member_item_ids:
            if member_id in items_by_id:
                continue
            url = event.all_urls[0] if event.all_urls else ""
            items_by_id[member_id] = NormalizedItem(
                item_id=member_id,
                source_id=event.source_ids[0] if event.source_ids else "unknown",
                title=event.title,
                title_norm=event.title.lower(),
                url=url,
                fetched_at=event.first_seen_at,
                first_seen_at=event.first_seen_at,
                updated_at=event.last_updated_at,
                content_sha256="0" * 64,
                simhash=0,
            )

    (site / f"{date}.html").write_text(
        render_day(past, archived_insights, items_by_id, ctx, repo_meta), encoding="utf-8"
    )
    return 1

def write_site(
    digest: Digest,
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem],
    out_dir: Path,
    *,
    site_url: str,
    assets_dir: Path | None = None,
    tibo: dict | None = None,
    sources: list[dict] | None = None,
    repo_meta: dict[str, dict] | None = None,
) -> dict[str, object]:
    site = out_dir / "site"
    site.mkdir(parents=True, exist_ok=True)

    if assets_dir and assets_dir.exists():
        target = site / "assets"
        target.mkdir(parents=True, exist_ok=True)
        for src in assets_dir.iterdir():
            if src.is_file():
                (target / src.name).write_bytes(src.read_bytes())

    # The digests directory, not the site directory: every page must see every issue,
    # regardless of the order pages happen to be (re)written in. The HTML scan is unioned in
    # because `write_site` is also called directly with a bare digest (tests, one-off renders)
    # in cases where no digest JSON exists for a page that *was* just written -- dropping that
    # source made the index lose the row for the very page it had just rendered.
    archive = load_archive(out_dir)
    merged = {date: count for date, count in archive}
    for date, count in _load_archive_from_html(site):
        merged.setdefault(date, count)
    merged[digest.date] = int(digest.counts.get("events", 0))
    ctx = SiteContext(
        site_url=site_url,
        archive=sorted(merged.items(), reverse=True),
        generated_at=digest.generated_at,
    )

    day_html = render_day(digest, insights, items_by_id, ctx, repo_meta)
    (site / f"{digest.date}.html").write_text(day_html, encoding="utf-8")

    # **Re-render every earlier issue too.**
    #
    # Only the current day was ever written, so a change to the template reached that day and
    # nothing else: 2026-10-14..16 kept a 「本期说明」 block long after it was removed, and kept a
    # calendar built before the fix. The page is generated from the archived digest, not from the
    # live one, so each past issue can be rebuilt exactly -- `load_archived_issue` does that.
    #
    # Cost is bounded by the archive (a few pages per run); the alternative is stale pages, which
    # is what this bug was.
    rebuilt = 0
    for past_date, _ in ctx.archive:
        if past_date == digest.date:
            continue
        rebuilt += _rerender_archived_issue(site, out_dir, past_date, ctx, repo_meta)


    (site / "index.html").write_text(render_index(ctx, digest), encoding="utf-8")
    (site / "tibo.html").write_text(render_tibo(ctx, tibo), encoding="utf-8")
    (site / "sources.html").write_text(
        render_sources(ctx, sources or [], digest, health=load_health(out_dir.parent / "state")),
        encoding="utf-8",
    )
    (site / "404.html").write_text(render_404(ctx), encoding="utf-8")

    manifest = {
        "date": digest.date,
        "pages": len(ctx.archive),
        "rebuilt_archived": rebuilt,
        "bytes": len(day_html.encode("utf-8")),
        "assets": sorted(p.name for p in (site / "assets").glob("*")) if (site / "assets").exists() else [],
    }
    (site / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    return manifest
