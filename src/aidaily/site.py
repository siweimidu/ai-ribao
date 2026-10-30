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

#: The leaderboard's committed JSON, addressed on raw.githubusercontent rather than the site.
#:
#: The page is rendered from this file, so every row on screen is already in it -- the URL
#: exists for programs that want the table without parsing HTML. A site-relative path would
#: work for a browser and for nothing else, which is the opposite of the audience.
LEADERBOARD_JSON_URL = (
    "https://raw.githubusercontent.com/siweimidu/ai-ribao/main/data/state/leaderboard.json")


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
    "chart": '<path d="M3 15V9"/><path d="M7.5 15V5"/><path d="M12 15V7.5"/><path d="M16 15H2"/>',
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


def _repository_age_label(
    event: Event, items_by_id: dict[str, NormalizedItem] | None
) -> str:
    """`Trending · 9 个月前创建`, or empty when the age is unknown.

    Returns empty rather than a guess: a wrong age on a repository card is worse than no age,
    because the reader uses it to decide whether the story is news.
    """
    created = ""
    for item_id in event.member_item_ids:
        item = (items_by_id or {}).get(item_id)
        if item is not None:
            created = str((item.metrics or {}).get("repo_created") or "")
            if created:
                break
    if not created:
        return ""
    try:
        when = datetime.fromisoformat(created[:10]).replace(tzinfo=timezone.utc)
    except ValueError:
        return ""
    days = max(0, (datetime.now(timezone.utc) - when).days)
    if days < 30:
        span = f"{max(1, days)} 天前"
    elif days < 365:
        span = f"{days // 30} 个月前"
    else:
        span = f"{days // 365} 年前"
    return f"Trending，{span}创建"


def _when(event: Event, items_by_id: dict[str, NormalizedItem] | None = None) -> tuple[str, bool]:
    if not event.published_range:
        # "时间未知" is honest but useless on a repository story: the reader asks "how old is
        # this news", and for GitHub Trending the answer is "the project is nine months old but
        # it trended this morning". Saying the age is more informative than saying nothing, and
        # it is the fact that decides whether the entry belongs in the issue at all.
        age = _repository_age_label(event, items_by_id)
        if age:
            return age, True
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
def rail_rss_copy(
    ctx: SiteContext,
    *,
    compact: bool = False,
    data_copy: str = "",
    label: str = "",
    icon_name: str = "rss",
    title: str = "",
) -> str:
    """The subscribe control: copies the address, never navigates to it.

    One function because the same control lives in three rails, and duplicating it is what
    let the first "copy instead of navigate" fix miss two of them -- `tibo.html` went on
    opening a wall of XML for a while after the home page was fixed.

    `compact` is for the secondary pages, whose rail is a short list of destinations rather
    than a full navigation panel.

    On the leaderboard the rail's one control is the ranking's own JSON, not the RSS feed: a
    reader on that page is looking at the table, and the copyable thing next to it is the
    table. Passing `data_copy`/`label` keeps the single implementation while letting each page
    say what its own control does -- the alternative was a second copy button that would drift
    from this one, which is exactly the bug the docstring above records.
    """
    base = esc(ctx.site_url.rstrip("/"))
    target = esc(data_copy) if data_copy else f"{base}/feed/zh.xml"
    text = esc(label) if label else "复制订阅地址"
    hint = f' title="{esc(title)}"' if title else ""
    if compact:
        return (
            f'<button class="rail__item" type="button" data-copy="{target}"{hint}>'
            f'{icon(icon_name)}<span>{text}</span></button>'
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

    # **Order is the user's, and it is not alphabetical.**
    #
    # Claude light and Claude dark lead because Claude light is the default: the first button
    # should be the one already in effect, so the list starts where the reader is. The plain
    # light/dark pair follows, then the three additional palettes.
    theme_items = "".join(
        f'<button type="button" data-theme-choice="{key}" aria-checked="false">{label}</button>'
        # 自动 and 默认 removed: a first visit is Claude light, and after the reader picks a
        # theme that choice is stored and reused. Four ways to say "let the site decide" were
        # three too many.
        for key, label in (
            # Claude's palette: a warm paper background rather than the usual neutral grey,
            # with its terracotta accent. Named after the product rather than described by its
            # colours, because that is how someone asks for it.
            ("claude-light", "Claude 亮色"),
            ("claude-dark", "Claude 暗色"),
            # Named by what they are rather than by their lightness: "亮色" next to
            # "Claude 亮色" reads as the same choice offered twice. This pair is the neutral
            # one -- no warm paper, no terracotta -- so the name says so.
            ("light", "标准亮色"),
            ("dark", "标准暗色"),
            # Reviewed and chosen by the user from nine candidates. Each is a whole palette
            # rather than a hue rotation: a dark theme needs a different contrast ratio and a
            # different accent lightness to stay readable.
            ("cinnabar", "宣纸朱砂"),
            ("indigo", "冷白靛紫"),
            ("midnight", "深蓝冷青"),
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
            <a class="rail__item" href="leaderboard.html">{icon("chart")}<span>模型榜</span></a>
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


def _body_order(
    events: list[Event],
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem] | None,
) -> tuple[list[tuple[int, Event]], list[tuple[int, Event]]]:
    """The body order and the untranslated order, numbered once.

    **One function decides which events the page shows and in what order.**

    Three call sites each kept their own counter -- the body, the rail and the overview -- and
    each one incremented at a different point in the skip test. Measured 2026-10-27: the rail
    ended at 99 and the last story in the body carried 106, because the body counted every
    event it scanned while the rail counted only the ones it rendered. Numbers that exist in
    one list and not the other are worse than no numbers: they look like a missing story.

    Returning the lists here means every consumer numbers the same elements in the same order.
    """
    # **Never render the same event twice.**
    #
    # Measured 2026-10-27: `top_events` held 106 rows for 97 stories. The page emitted two
    # `<li id="e-...">` sharing one id, and every `href="#e-..."` resolves to the
    # *first* match -- so clicking entry 32 landed on entry 3. The same duplicate made the
    # rail highlight the wrong row while scrolling.
    #
    # The selection stage now dedupes by `event_id` (see `rank.select_diverse`). This guard
    # keeps already-published digests correct too: they are re-rendered from JSON that still
    # carries the duplicates, and rewriting published data is not a renderer job.
    shown: list[tuple[int, Event]] = []
    untranslated: list[tuple[int, Event]] = []
    seen_ids: set[str] = set()
    for event in events:
        if event.event_id in seen_ids:
            continue
        seen_ids.add(event.event_id)
        insight = insights.get(event.event_id)
        title = _display_title(event, insight, items_by_id)
        # A repository slug is not foreign reporting: it has no Chinese form and never will,
        # so routing it to the untranslated block reads as "we could not handle this" when the
        # entry is complete. Measured 2026-10-23: the repository the reader asked about was in
        # that collapsed block rather than the issue body.
        if not _looks_chinese(title) and not _is_repository_story(event):
            untranslated.append((len(untranslated) + 1, event))
            continue
        shown.append((len(shown) + 1, event))
    return shown, untranslated

def render_toc(
    ordered: list[tuple[int, Event]],
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

    # **The rail is built from the same numbered list the body renders.**
    #
    # Two reports, opposite directions: on 2026-10-26 the rail stopped at 19 of 21 stories, and
    # on 2026-10-27 it listed 99 while the body numbered up to 106. Both were one mistake --
    # the rail ran its own loop over `events` with its own counter instead of reading the list
    # the body produced. It takes `ordered` now, so the numbers are the body numbers by
    # construction and there is nothing left to keep in sync.
    for number, event in ordered:
        insight = insights.get(event.event_id)
        title = _display_title(event, insight, items_by_id)
        anchor = f"e-{event.event_id}"
        label = title if len(title) <= 42 else title[:40] + "…"
        rows.append(
            f'<a href="#{esc(anchor)}">'
            f'<span class="toc__no">{number:02d}</span>{esc(label)}</a>'
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
#: A GitHub repository URL, e.g. `https://github.com/owner/name`.
#:
#: Deliberately narrow. `github.com/trending`, `/topics/x` and `github.com/features/y` are not
#: repositories, and treating them as one would suppress the rewrite for a story that merely
#: links to GitHub.
#: First path segments GitHub reserves for its own pages. `github.com/topics/llm` has the
#: same two-segment shape as a repository but is a topic listing.
_GITHUB_RESERVED = {
    "topics", "features", "about", "pricing", "enterprise", "sponsors", "collections",
    "trending", "explore", "marketplace", "login", "join", "site", "security", "settings",
    "orgs", "users", "apps", "notifications", "issues", "pulls", "search", "readme",
}

_REPO_URL = re.compile(r"^https?://(?:www\.)?github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/?$")


def _is_repository_story(event: Event) -> bool:
    """True when the event is about one repository rather than about news."""
    for url in event.all_urls or []:
        match = _REPO_URL.match((url or "").strip())
        if match and match.group(1).lower() not in _GITHUB_RESERVED:
            return True
    return False


#: A digest issue's own label, e.g. `2026-10-29 AI 日报 · `.
_CONTAINER_PREFIX = re.compile(
    r"^\s*\d{4}[-/年.]\d{1,2}[-/月.]\d{1,2}\s*(?:AI\s*)?(?:日报|早报|晚报|周报)\s*[\u00b7\-—|｜:：]\s*"
)


def _strip_container(title: str) -> str:
    """Drop a digest issue label glued to the front of a headline."""
    return _CONTAINER_PREFIX.sub("", (title or "").strip()).strip()


def _is_compound(title: str) -> bool:
    """True when a headline states more than one thing.

    **A title reports one event.** Measured 2026-10-29, the lead read:

        2026-10-29 AI 日报 · Gemini 4 Carbon 登顶智能榜单、主打网络安全；微软首次披露 Azure
        收入，来自 OpenAI 的收入达百亿美元

    Two unrelated stories in one line. It happened because an aggregated issue title was merged
    into the Gemini event, and the merge kept the longest string -- which is exactly the
    container title, since it names everything.

    A semicolon or a full stop inside a headline is the tell. Commas and 、 are fine; they join
    clauses of one story.
    """
    text = (title or "").strip()
    if not text:
        return False
    if "；" in text or ";" in text:
        return True
    if "。" in text:
        return True
    return False


def _first_clause(title: str) -> str:
    """The leading claim, for when every candidate turned out to be compound."""
    text = (title or "").strip()
    for mark in ("；", ";", "。"):
        if mark in text:
            head = text.split(mark)[0].strip()
            if head:
                return head
    return text


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

    # **A repository story keeps its own title.**
    #
    # The model rewrites every headline into Chinese, and for a repository that produces
    # `anthropics/knowledge-work-plugins：Claude Cowork 知识工作插件` -- the slug glued to a
    # translation of the description with a full-width colon between them. It reads as a
    # malformed label, not a headline, and it repeats what the card below already shows.
    #
    # The slug is the identity of a repository, so it stays; the description belongs in the
    # summary, where it already is. Falling through to `event.title` gives exactly that.
    if _is_repository_story(event):
        return event.title.strip()

    if insight and insight.title:
        candidates.append(insight.title)
    candidates.append(event.title)
    if items_by_id:
        for item_id in event.member_item_ids:
            item = items_by_id.get(item_id)
            if item and item.title:
                candidates.append(item.title)

    # One title, one event: strip issue labels and refuse compounds.
    cleaned = [_strip_container(c) for c in candidates]
    singles = [c for c in cleaned if c and not _is_compound(c)]
    pool = singles or [_first_clause(c) for c in cleaned]
    for title in pool:
        if _looks_chinese(title):
            return title.strip()
    # Nothing Chinese anywhere: return the model's title or the event's, unchanged, so the
    # caller can route it to the untranslated block.
    return (pool[0] if pool else "").strip()


def render_item(
    index: int,
    event: Event,
    insight: EventInsight | None,
    items_by_id: dict[str, NormalizedItem] | None = None,
    repo_meta: dict[str, dict] | None = None,
) -> str:
    title = _display_title(event, insight, items_by_id)
    anchor = f"e-{event.event_id}"
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
        # **Click opens the picture in place, not a new tab.**
        #
        # The row used to be anchors that opened a new browser tab, so reading an issue
        # meant a pile of tabs and a back button per picture. A `<button>` that the lightbox
        # keeps the reader on the page and keeps the scroll position.
        #
        # The `src` is still the real image, so nothing changes for a reader with JavaScript off
        # beyond the click doing nothing -- the pictures are already visible in the row.
        thumbs = "".join(
            f'<button type="button" class="item__thumb" data-full="{esc(url)}" '
            f'aria-label="放大图片">'
            f'<img src="{esc(url)}" alt="" loading="lazy" decoding="async"></button>'
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
    # **Only when the story *is* the repository.**
    #
    # Scanning every URL meant any story that merely *linked* to GitHub was rendered as that
    # repository: measured on 2026-10-21, `OpenAI: Patch the Planet` -- a coordinated-disclosure
    # write-up -- carried one `github.com/php/php-src/releases/tag/php-8.2.35` link among nine
    # sources, and the page showed it as a PHP repo card with the OpenAI headline gone.
    #
    # The repository has to be the primary subject: its URL must be the first (most direct) one,
    # or the title must name the repository itself, which is what the trending fetcher emits
    # (`vllm-project/vllm`). A bare link in the reference list does not qualify.
    repo = None
    card = ""
    primary_url = ordered_urls[0] if ordered_urls else ""
    repo = repo_of(primary_url) if primary_url else None
    if repo is None:
        # The trending fetcher titles a repository story with its own slug (`vllm-project/vllm`)
        # and links to it, but a rewrite can leave the title as the bare slug while the first URL
        # points at a release page. Accept that form only when the metadata confirms it is a
        # repository we actually fetched -- otherwise `OpenAI/vLLM` style titles would match.
        candidate = repo_of(f"https://github.com/{title.strip()}")
        if candidate and (not repo_meta or candidate in repo_meta):
            repo = candidate
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

    when_text, known = _when(event, items_by_id)
    # **A repository is not an untranslated story.**
    #
    # The "待翻译" block exists for foreign-language reporting that the model had no quota to
    # translate. A repository slug is not foreign reporting: `anthropics/knowledge-work-plugins`
    # has no Chinese form and never will, so judging it by `_looks_chinese` moves the entry out
    # of the issue body and into a collapsed block that reads as "we could not handle this".
    # Measured 2026-10-23: the entry the reader asked about was in that block, not the body.
    repository = _is_repository_story(event)

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

    # The official walkthrough, when one was verified for this story.
    _video = (event.unique_facts or {}).get("video") if isinstance(event.unique_facts, dict) else None
    video_html = ""
    if isinstance(_video, dict) and _video.get("url"):
        video_html = (
            '<p class="item__video"><a href="'
            + esc(str(_video["url"]))
            + '" target="_blank" rel="noopener noreferrer">官方视频：'
            + esc(str(_video.get("title") or ""))[:60]
            + "</a></p>"
        )

    when_cls = "" if known else ' class="when-unknown"'

    return f"""        <li class="item" id="{esc(anchor)}">
          {head_html}
          {image_html}
          {video_html}
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
    ordered: list[tuple[int, Event]],
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
    rows: list[str] = []
    # **The overview reads the body list, so its numbers are the body numbers.**
    #
    # It used to run its own loop over `digest.top_events` with `enumerate`, skipping entries
    # that did not reach the body. The counter advanced before the skip, so the first visible
    # line read `03` on the 2026-10-26 issue -- two stories that looked missing and were not.
    #
    # `ordered` is already numbered by `_body_order`. Taking the first eight of it needs no
    # counter and cannot drift.
    for number, event in ordered[:8]:
        insight = insights.get(event.event_id)
        title = _display_title(event, insight, items_by_id)
        anchor = f"e-{event.event_id}"

        # The first supporting fact, when there is one, is what makes the line informative
        # rather than a second headline.
        detail = ""
        if insight and insight.facts:
            fact = insight.facts[0].strip()
            if fact and fact != title and len(fact) <= 120:
                detail = fact
        rows.append(
            f'<li><a href="#{esc(anchor)}">'
            f'<span class="ov__no">{number:02d}</span>'
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


def _untranslated_reason(digest: Digest) -> str:
    """Why these entries are untranslated, in this issue's own words.

    **The sentence used to be a constant:** 「本期模型额度用完、未能逐条译成中文」. It was not
    a judgement, it was a guess rendered as fact -- and on 2026-10-27 it was wrong twice over:
    the run had spent 8% of its token budget across 23 working providers, and the real cause was
    that the pipeline selected a second time after analysis, so 17 entries were published
    without ever being sent to a model. Telling the reader "quota exhausted" about a run that
    was nowhere near its quota is a false statement on the page.

    So the reason is read from the digest: the budget, when it was actually reached; the
    warning the analyzer recorded, when the model was unavailable; and otherwise a statement of
    what is observable -- the source headline is in a language this issue did not translate.
    """
    warnings = " ".join(digest.warnings or ())
    usage = digest.llm_usage or {}

    calls = usage.get("calls") or 0
    max_calls = usage.get("max_calls") or 0
    tokens = usage.get("tokens") or 0
    max_tokens = usage.get("max_tokens") or 0

    # Only claim exhaustion when the numbers say so.
    if max_calls and calls >= max_calls:
        return f"本期调用数已达上限（{calls}/{max_calls} 次），未能逐条译成中文，"
    if max_tokens and tokens >= max_tokens:
        return f"本期 token 用量已达上限（{tokens:,}/{max_tokens:,}），未能逐条译成中文，"

    if "未配置大模型" in warnings or "未找到任何可用的模型密钥" in warnings:
        return "本期未配置可用的大模型密钥，未能逐条译成中文，"
    # Two wordings reach here: the analyzer own summary and the older per-batch note.
    if (
        "降级为规则摘录" in warnings
        or "降级为原文摘录" in warnings
        or "部分模型调用失败" in warnings
    ):
        return "本期部分模型调用失败，这些条目未能译成中文，"

    # No budget or failure explains it. Say what is actually true rather than invent a cause.
    return "这些条目的原始标题为外文，本期未能译成中文，"


#: Short names for the sources the user asked to collect in full.
_NAMED_LABEL = {
    "rss:daily-juya-uk": "橘鸦",
    "rss:ainewslog-com": "AINewsLog",
    "rss:hex2077": "hex2077",
    "rss:hex2077-dev-rss-zh-cn": "hex2077 中文",
    "api:aibase-ai-news": "aibase",
    "api:aibase-daily-news": "aibase 日报",
    "rss:aihot-news-picks": "aihot 精选",
    "rss:aihot-news-full": "aihot 全量",
    "rss:aihot-news-daily": "aihot 日报",
}


def _render_source_coverage(ordered: list) -> str:
    """How many entries each named source contributed to this issue.

    **The question 「为什么看不见」 needed an answer on the page, not in a build log.** A source
    that delivered 662 items and produced 0 events looked identical to a source that was never
    collected -- the reader could not tell, and neither could I without digging through the
    archive.

    Every named source is listed with its count, including the zeroes. A zero is the useful
    line: it says the source ran and nothing survived, which is a defect to look at rather than
    an invisible absence.
    """
    counts: dict[str, int] = {}
    for _number, event in ordered:
        for sid in getattr(event, "source_ids", ()) or ():
            if sid in _NAMED_LABEL:
                counts[sid] = counts.get(sid, 0) + 1

    parts = [
        f"<li><b>{esc(_NAMED_LABEL[sid])}</b> {counts[sid]} 条</li>"
        for sid in _NAMED_LABEL
        if sid in counts
    ]
    # Weekly sources are not listed at all.
    #
    # They used to get their own line -- 「按规则不收录周刊：hex2077」 -- explaining that the
    # absence was intentional. The reader does not need it: a name that will never appear is
    # noise on a page whose job is to show what did. `WEEKLY_SOURCES` still drives admission;
    # it just no longer prints.
    from .unfiltered import WEEKLY_SOURCES

    missing: list[str] = []
    for sid in _NAMED_LABEL:
        if sid in counts or sid in WEEKLY_SOURCES or sid == "rss:hex2077-dev-rss-zh-cn":
            continue
        missing.append(_NAMED_LABEL[sid])

    zero = ""
    if missing:
        zero = (
            '<p class="src-cover__zero">本期未收录：' + esc("、".join(missing)) + "</p>"
        )
    if not parts:
        return ""
    return (
        '      <section class="section src-cover" id="coverage">\n'
        '        <h2 class="section__title">具名源收录'
        '<span class="section__count">全部条目均已打分排序</span></h2>\n'
        '        <ul class="src-cover__list">' + "".join(parts) + "</ul>\n"
        "        " + zero + "\n"
        "      </section>"
    )


def render_day(
    digest: Digest,
    insights: dict[str, EventInsight],
    items_by_id: dict[str, NormalizedItem],
    ctx: SiteContext,
    repo_meta: dict[str, dict] | None = None,
) -> str:
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
    # **One decision, shared by the body, the rail and the overview.**
    #
    # Each used to run its own loop with its own counter, incrementing at a different point in
    # the skip test. Measured 2026-10-27: the rail ended at 99 and the last story in the body
    # carried 106, so seven numbers existed only in the body. Numbers that appear in one list
    # and not the other look like missing stories.
    #
    # `_body_order` returns both lists, already numbered.
    ordered_body, untranslated = _body_order(digest.top_events, insights, items_by_id)
    for number, event in ordered_body:
        insight = insights.get(event.event_id)
        translated_ids.add(event.event_id)
        rows.append(render_item(number, event, insight, items_by_id, repo_meta))

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
        <p>{_untranslated_reason(digest)}这些条目只在这里保留原文与出处，不混进上面的正文。
        <strong>点开即离开本站、前往原文</strong>。</p>
        <ol>{items}</ol>
      </details>"""

    overview = _render_overview(digest, insights, ordered_body, items_by_id)
    source_cover = _render_source_coverage(ordered_body)
    # The rail is built here, after the body decided which events it shows.
    # It used to be built before the loop, from `top_events` -- which is why it once
    # listed 11 entries that the body had moved into the collapsed 待翻译 block.
    toc = render_toc(ordered_body, insights, items_by_id)

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
<html lang="zh-CN" data-theme="claude-light">
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

    {source_cover}

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
<div class="lightbox" id="lightbox" hidden>
  <button type="button" class="lightbox__close" aria-label="关闭">×</button>
  <img class="lightbox__img" alt="">
</div>
<script>
// Click a picture and it opens in place. No new tab, no scroll jump, no history entry.
// Escape, the close button, or a click on the backdrop dismisses it.
(function () {{
  var box = document.getElementById("lightbox");
  if (!box) return;
  var img = box.querySelector(".lightbox__img");
  function open(src) {{
    img.src = src;
    box.hidden = false;
    document.body.classList.add("is-lightbox");
  }}
  function close() {{
    box.hidden = true;
    img.removeAttribute("src");
    document.body.classList.remove("is-lightbox");
  }}
  document.addEventListener("click", function (e) {{
    var thumb = e.target.closest(".item__thumb");
    if (thumb) {{ e.preventDefault(); open(thumb.dataset.full); return; }}
    if (e.target === box || e.target.closest(".lightbox__close")) close();
  }});
  document.addEventListener("keydown", function (e) {{
    if (e.key === "Escape" && !box.hidden) close();
  }});
}})();
</script>
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
<html lang="zh-CN" data-theme="claude-light">
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


def _fmt_price(value: float | None) -> str:
    """A price per million tokens, or an em dash.

    "Not measured" and "free" are different facts and must not both render as 0.
    """
    if value is None:
        return '<span class="lb__na">—</span>'
    if value == 0:
        return "免费"
    return f"${value:,.2f}"


def _fmt_ctx(tokens: int | None) -> str:
    if not tokens:
        return '<span class="lb__na">—</span>'
    if tokens >= 1_000_000:
        return f"{tokens / 1_000_000:.1f}M"
    return f"{tokens // 1000}k"


def _fmt_score(value: float | None) -> str:
    if value is None:
        return '<span class="lb__na">—</span>'
    return f"{value:.1f}"

def render_leaderboard(
    ctx: "SiteContext",
    models: list,
    *,
    fetched_at: str = "",
    error: str = "",
) -> str:
    """The model leaderboard page.

    Ranked by the intelligence index: that is the column the source treats as the headline
    and the only one every model carries. Price and context sit beside it, because a
    ranking that ignored cost would put a $10/M model above a $2/M one with no way to see
    why.

    The table is the page. The counts, the source note and the legend exist to make the
    table readable, so they stay compact and the rows stay dense.
    """
    live = [m for m in models if not m.deprecated]
    reasoning = sum(1 for m in live if m.reasoning)
    open_weights = sum(1 for m in live if m.open_weights)
    priced = sum(1 for m in live if m.price_input is not None)

    if error:
        body = (
            '<div class="lb__empty">'
            "<p>模型榜暂时取不到数据。</p>"
            f'<p class="lb__err">{esc(error)}</p>'
            "<p>数据来自 artificialanalysis.ai 的公开榜单；取不到时这一页留空，"
            "不会用旧数据冒充新的。</p>"
            "</div>"
        )
    elif not live:
        body = '<div class="lb__empty"><p>还没有模型数据。</p></div>'
    else:
        rows = []
        for index, model in enumerate(live, 1):
            badges = []
            if model.reasoning:
                badges.append('<span class="lb__tag lb__tag--think">推理</span>')
            if model.open_weights:
                badges.append('<span class="lb__tag lb__tag--open">开源</span>')
            if model.estimated:
                badges.append('<span class="lb__tag lb__tag--est">估</span>')

            color = model.creator_color or "var(--muted-fg)"
            rows.append(
                "<tr>"
                f'<td class="lb__rank">{index}</td>'
                '<td class="lb__model">'
                f'<a href="{esc(model.href)}" target="_blank" rel="noopener noreferrer">'
                f"{esc(model.name)}</a>"
                # The variant in small type: it distinguishes two rows that would otherwise
                # read as the same model, without widening the name column.
                + (f'<span class="lb__variant">{esc(model.variant)}</span>' if model.variant else "")
                + f'{"".join(badges)}'
                "</td>"
                f'<td class="lb__creator"><i style="background:{esc(color)}"></i>'
                f"{esc(model.creator)}</td>"
                f'<td class="lb__num lb__num--hero">{_fmt_score(model.intelligence)}</td>'
                f'<td class="lb__num">{_fmt_ctx(model.context)}</td>'
                f'<td class="lb__num">{_fmt_price(model.price_input)}</td>'
                f'<td class="lb__num">{_fmt_price(model.price_output)}</td>'
                "</tr>"
            )

        body = (
            '<div class="lb__scroll">'
            '<table class="lb">'
            "<thead><tr>"
            '<th class="lb__rank">#</th>'
            "<th>模型</th><th>厂商</th>"
            '<th class="lb__num">智能指数</th>'
            '<th class="lb__num">上下文</th>'
            '<th class="lb__num">输入 $/M</th>'
            '<th class="lb__num">输出 $/M</th>'
            "</tr></thead>"
            f'<tbody>{"".join(rows)}</tbody>'
            "</table>"
            "</div>"
        )
    stats = (
        '<div class="lb__stats">'
        f"<div><b>{len(live)}</b><span>在榜模型</span></div>"
        f"<div><b>{reasoning}</b><span>推理模型</span></div>"
        f"<div><b>{open_weights}</b><span>开源权重</span></div>"
        f"<div><b>{priced}</b><span>公开定价</span></div>"
        "</div>"
    )

    fetched_note = f"抓取于 {esc(fetched_at)}。" if fetched_at else ""

    # **The table has a machine-readable twin, and nothing on the page said so.**
    #
    # `data/state/leaderboard.json` is what this page is rendered from, and it has been
    # committed for as long as the page has existed. Anyone wiring the ranking into a
    # workflow (n8n, a spreadsheet, a bot) had to open devtools or guess the path.
    #
    # The raw.githubusercontent address, not a site-relative one: the JSON exists to be
    # fetched by something that has no page to resolve a relative path against. It is also
    # the URL a reader can paste into a browser to check for themselves.
    json_copy = (
        '<div class="lb__api">'
        '<button type="button" class="lb__api-btn" data-copy="'
        f'{esc(LEADERBOARD_JSON_URL)}" ' 
        'title="复制模型榜原始数据的 JSON 地址">'
        f'{icon("download", 14)}<span>复制 JSON 地址</span>'
        "</button>"
        f'<a class="lb__api-link" href="{esc(LEADERBOARD_JSON_URL)}" ' 
        'target="_blank" rel="noopener noreferrer">查看</a>'
        '<span class="lb__api-note">模型榜原始数据，供程序取用</span>'
        "</div>"
    )

    return f"""<!doctype html>
<html lang="zh-CN" data-theme="claude-light">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>模型榜 · AI 日报</title>
<meta name="color-scheme" content="light dark">
<link rel="icon" href="{FAVICON}">
<link rel="stylesheet" href="assets/tokens.css">
<link rel="stylesheet" href="assets/components.css">
  <link rel="preconnect" href="https://fonts.googleapis.com">
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Noto+Serif+SC:wght@400;600;700;900&family=IBM+Plex+Mono:wght@400;500&display=swap">
  <link rel="stylesheet" href="https://cdn.jsdelivr.net/npm/misans@4.0.0/lib/Normal/MiSans-Regular.min.css">
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
      <a class="rail__item" href="leaderboard.html" aria-current="page">{icon("chart")}<span>模型榜</span></a>
      <button class="rail__item" type="button" data-copy="{esc(LEADERBOARD_JSON_URL)}" title="复制模型榜原始数据的 JSON 地址">{icon("download")}<span>复制 JSON 地址</span></button>
    </div>
  </aside>
  <main class="content" id="main">
    <header class="issue__head">
      <p class="issue__date">Artificial Analysis · 智能指数排名</p>
      <h1 class="issue__title">模型榜</h1>
      <p class="issue__lead">按智能指数排序；价格与上下文并列，方便看清「更强」和「更贵」不是一回事。</p>
      {stats}
      {json_copy}
    </header>
    {body}
    <footer class="lb__foot">
      <p>数据来自 <a href="https://artificialanalysis.ai/leaderboards/models" target="_blank" rel="noopener noreferrer">Artificial Analysis</a> 的公开榜单，每次构建抓取一次。{fetched_note}</p>
      <p>「智能指数」是该站自建的合成指标，不是任何单一基准；「估」表示该分数为估算值。价格单位为每百万 token，以该站公布为准。</p>
    </footer>
  </main>
</div>
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
<html lang="zh-CN" data-theme="claude-light">
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
<html lang="zh-CN" data-theme="claude-light">
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
<html lang="zh-CN" data-theme="claude-light">
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

    # **The leaderboard is fetched, not derived.** It is not part of the digest: no selection,
    # no ranking of ours, just the public table rendered in this site clothes. A failed fetch
    # renders the page with an explanation instead of a table, which is honest and keeps the
    # navigation link from 404ing.
    leaderboard_models = []
    leaderboard_error = ""
    leaderboard_at = ""
    try:
        from .leaderboard import load_models, snapshot_path

        leaderboard_models = load_models(Path(__file__).resolve().parents[2])
        snapshot = snapshot_path(Path(__file__).resolve().parents[2])
        if snapshot.exists():
            import json as _json

            leaderboard_at = str(_json.loads(snapshot.read_text(encoding="utf-8")).get("fetched_at") or "")[:10]
    except Exception as exc:  # noqa: BLE001
        leaderboard_error = f"{type(exc).__name__}: {exc}"[:160]
    (site / "leaderboard.html").write_text(
        render_leaderboard(ctx, leaderboard_models, fetched_at=leaderboard_at, error=leaderboard_error),
        encoding="utf-8",
    )
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
