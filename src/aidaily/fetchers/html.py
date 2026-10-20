"""Generic HTML list fetcher.

Several registered sources are ordinary HTML pages rather than feeds or JSON APIs -- the
Chinese AI media sites among them. `resolve_adapter` mapped them to `JsonApiFetcher`, which
cannot read HTML, so they sat disabled with the note "adapter not implemented". That note was
accurate: the capability was missing, not the source.

Two extraction strategies, in order:

1. **Explicit selectors**, when the source declares them in `params` (`item_selector`,
   `title_selector`, `link_selector`, `date_selector`, `summary_selector`). A site with a
   stable, known markup should be pinned rather than guessed at.
2. **A structural heuristic** for everything else: collect anchors whose text reads like a
   headline, keep those pointing at the same site, and discard navigation.

The heuristic is deliberately conservative. A listing page yields every link on it --
menus, footers, tag clouds, "next page" -- and a digest that ingests a navigation link has
published a wrong story. So a candidate must look like an article path and carry a title of
a plausible length, and the fetcher reports how many candidates it rejected.
"""

from __future__ import annotations

import re
from urllib.parse import urljoin, urlparse

from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

#: Common subdomains that serve the same site's content. `aibase.com` lists articles on
#: `app.aibase.com`; `blog.` and `news.` are the same pattern elsewhere. Only these are
#: treated as the same site -- a bare registrable-domain match would also accept
#: `something-else.example.com` as "the same publisher", which is not true.
_CONTENT_SUBDOMAINS = {"", "www", "app", "blog", "news", "m", "mobile", "cn", "en"}


#: Trailing UI badges a listing page renders inside the link: `MiniMax M3.1 Flash NEW`.
_TITLE_BADGE = re.compile(r"\s+(?:NEW|新|HOT|更新|置顶)\s*$", re.I)

#: A date prefix and/or a category chip a listing page puts before the headline:
#: `Oct 18, 2026 Announcements Investing in the public benefit fund`,
#: `Product · Oct 12, 2026 Introducing The X Subscription`.
_TITLE_DATE = re.compile(
    r"^(?:[A-Z][a-z]{2,8}\.?\s+\d{1,2},\s*20\d\d|20\d\d-\d\d-\d\d)\s*(?:·\s*)?"
)
_TITLE_CHIP = re.compile(
    r"^(?:Announcements?|Product|Policy|Research|News|Company|Update|Blog)\s*(?:·\s*)?",
    re.I,
)


def clean_listing_title(text: str) -> str:
    """Strip listing-page chrome from a headline.

    A news index renders the date and a category chip inside the same anchor as the headline,
    and sometimes a NEW badge after it. Left in place they become part of the title, which then
    fails to match the same story from any other source -- the deduplicator never sees two
    headlines about one event because one of them starts with a date.

    Applied only to the HTML listing fetcher: RSS and JSON items carry a title field of their
    own and are not wrapped in page chrome.
    """
    title = " ".join((text or "").split())
    if not title:
        return ""
    title = _TITLE_BADGE.sub("", title)
    # Either a date or a chip may come first, and they may alternate; strip whichever matches
    # at the current position until neither does.
    for _ in range(4):
        before = title
        title = _TITLE_DATE.sub("", title)
        title = _TITLE_CHIP.sub("", title)
        title = _TITLE_DATE.sub("", title)
        title = _TITLE_CHIP.sub("", title)
        if title == before:
            break
    return title.strip()


def _same_site(a: str, b: str) -> bool:
    """Whether two hosts belong to one publisher's site tree.

    Compares the registrable domain and requires the subdomain to be a known content
    prefix. The first version required the hosts to be **identical**, which rejected every
    article on a site that lists them under `app.` -- the fetcher returned only navigation
    links and looked like it had simply found an empty page.
    """
    left = a.lower().split(":")[0]
    right = b.lower().split(":")[0]
    if left == right:
        return True

    def parts(host: str) -> tuple[str, str]:
        labels = host.split(".")
        if len(labels) < 2:
            return host, ""
        return labels[-2] + "." + labels[-1], ".".join(labels[:-2])

    l_domain, l_sub = parts(left)
    r_domain, r_sub = parts(right)
    if l_domain != r_domain:
        return False
    return l_sub in _CONTENT_SUBDOMAINS and r_sub in _CONTENT_SUBDOMAINS


#: Path segments that are navigation, not articles.
_NAV_SEGMENTS = {
    "about", "contact", "login", "signup", "signin", "register", "privacy", "terms",
    "tag", "tags", "category", "categories", "author", "authors", "page", "pages",
    "search", "feed", "rss", "sitemap", "archive", "archives", "index", "home",
    "关于", "联系", "登录", "注册", "标签", "分类", "作者", "搜索", "归档", "首页",
}

#: A headline is a phrase, not a word and not a paragraph.
_MIN_TITLE = 8
_MAX_TITLE = 160

#: Anchor texts that are interface chrome, not headlines. The path heuristic catches most
#: navigation, but a "View More" link pointing at `/cases` looks like an article path. Seen
#: in the first live extraction of aibase.com, where it came back as item one.
_NAV_TEXT = {
    "view more", "read more", "learn more", "see more", "more", "next", "previous",
    "back", "home", "menu", "close", "submit", "subscribe", "sign in", "sign up",
    "log in", "login", "register", "share", "follow", "contact us", "about us",
    "查看更多", "更多", "阅读全文", "阅读更多", "下一页", "上一页", "返回", "首页",
    "登录", "注册", "订阅", "关注", "联系我们", "关于我们", "分享",
}

_DATE_PATTERNS = (
    re.compile(r"(\d{4})[-/年](\d{1,2})[-/月](\d{1,2})"),           # 2026-10-14 / 2026年10月14日
    re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})[T ](\d{1,2}):(\d{2})"),
)


class HtmlFetcher(BaseFetcher):
    name = "HtmlFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        res = await self.http.get(spec.url)
        base = self.from_http(spec, res)
        if not base.ok or res.verdict == "not_modified":
            return base

        params = spec.params or {}
        if params.get("item_selector"):
            base.items = self._parse_explicit(spec, res.text, params)
        else:
            base.items = self._parse_structural(spec, res.text, base)

        if not base.items and base.ok:
            # Saying nothing found is not an error -- a listing page can be empty -- but it
            # must be visible, because "0 items" and "the selectors stopped matching" look
            # identical from the outside.
            base.detail = f"{base.detail} [no candidates matched]".strip()
        return base

    # ---------------------------------------------------------------- explicit

    def _parse_explicit(self, spec: SourceSpec, html: str, params: dict) -> list[RawItem]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        item_sel = params["item_selector"]
        title_sel = params.get("title_selector")
        link_sel = params.get("link_selector", "a")
        date_sel = params.get("date_selector")
        summary_sel = params.get("summary_selector")
        limit = int(params.get("limit") or 30)

        out: list[RawItem] = []
        seen_urls: set[str] = set()
        for node in soup.select(item_sel)[:limit]:
            # `select_one` searches **descendants only**, so an `item_selector` that is itself
            # an anchor (a[href^='/blog/']) matches the node but then finds no link inside it,
            # and the source silently yields zero items. Fall back to the node itself.
            link_el = node.select_one(link_sel)
            if link_el is None and node.name == "a" and node.get("href"):
                link_el = node
            if link_el is None or not link_el.get("href"):
                continue
            title_el = node.select_one(title_sel) if title_sel else link_el
            title = clean_listing_title(title_el.get_text(" ", strip=True)) if title_el else ""
            if not title:
                continue
            url = urljoin(spec.url, str(link_el["href"]))
            if url in seen_urls:
                continue
            seen_urls.add(url)
            summary = ""
            if summary_sel:
                summary_el = node.select_one(summary_sel)
                summary = summary_el.get_text(" ", strip=True) if summary_el else ""
            published = None
            if date_sel:
                date_el = node.select_one(date_sel)
                if date_el is not None:
                    published = self._parse_date(date_el.get_text(" ", strip=True))
            out.append(RawItem(
                source_id=spec.source_id, title=title[:300], url=url,
                published_at=published, summary=summary[:2000], content_text=None,
                author=None, language=spec.language, metrics={}, native_id=url,
            ))
        return out

    # -------------------------------------------------------------- structural

    def _parse_structural(self, spec: SourceSpec, html: str, base: SourceResult) -> list[RawItem]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        host = urlparse(spec.url).netloc.lower()

        # Strip the chrome before looking for headlines: a nav bar full of short links is
        # the single largest source of false candidates on a listing page.
        for tag in soup(["nav", "header", "footer", "aside", "script", "style", "form"]):
            tag.decompose()

        seen: set[str] = set()
        out: list[RawItem] = []
        rejected = 0

        for anchor in soup.find_all("a", href=True):
            href = str(anchor["href"]).strip()
            if not href or href.startswith(("#", "mailto:", "javascript:")):
                continue
            url = urljoin(spec.url, href)
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                continue
            # Same publisher only: an outbound link is a citation, not an entry in this
            # feed. Subdomains of the same registrable domain count, because that is where
            # listing pages commonly point.
            if not _same_site(parsed.netloc, host):
                continue

            title = anchor.get_text(" ", strip=True)
            if not (_MIN_TITLE <= len(title) <= _MAX_TITLE):
                rejected += 1
                continue
            if title.lower().strip(" .。>»→") in _NAV_TEXT:
                rejected += 1
                continue

            segments = [s for s in parsed.path.split("/") if s]
            if not segments:
                rejected += 1          # the site root
                continue
            if any(seg.lower() in _NAV_SEGMENTS for seg in segments):
                rejected += 1
                continue

            key = parsed._replace(query="", fragment="").geturl()
            if key in seen:
                continue
            seen.add(key)

            # A date is often rendered next to the headline rather than inside the anchor.
            published = self._parse_date(title)
            if published is None:
                parent_text = anchor.parent.get_text(" ", strip=True) if anchor.parent else ""
                published = self._parse_date(parent_text[:200])

            out.append(RawItem(
                source_id=spec.source_id, title=title[:300], url=url,
                published_at=published, summary="", content_text=None,
                author=None, language=spec.language, metrics={}, native_id=key,
            ))
            if len(out) >= 40:
                break

        if rejected:
            base.detail = f"{base.detail} [rejected {rejected} nav/short links]".strip()
        return out

    # ------------------------------------------------------------------- util

    @staticmethod
    def _parse_date(text: str):
        from datetime import datetime, timezone

        for pattern in _DATE_PATTERNS:
            match = pattern.search(text or "")
            if not match:
                continue
            parts = [int(g) for g in match.groups() if g is not None]
            try:
                if len(parts) >= 5:
                    return datetime(parts[0], parts[1], parts[2], parts[3], parts[4],
                                    tzinfo=timezone.utc)
                if len(parts) >= 3:
                    return datetime(parts[0], parts[1], parts[2], tzinfo=timezone.utc)
            except ValueError:
                # 2026-13-45 is a parse failure, not a date; try the next pattern.
                continue
        return None
