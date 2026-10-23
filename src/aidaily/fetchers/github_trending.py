"""GitHub Trending fetcher.

Reimplemented rather than copied: the upstream project this behaviour comes from
(TangSY/dailydawn) ships **no licence**, so under default copyright its code cannot be
reused. The facts it encodes -- the URL, the selectors GitHub's markup uses, and the
deliberate absence of a publication date -- are not copyrightable, and are reproduced
here in our own implementation.

`published_at` is intentionally None. Trending is a *star-delta window*, not a
publication event: a repository created in 2019 can top the list because it gained
stars today. Attaching the fetch time would make the digest claim the project "was
released today".
"""

from __future__ import annotations

import re

from ..http import HttpClient
from ..models import RawItem, SourceSpec
from .base import BaseFetcher, SourceResult

def _headline(full_name: str, description: str) -> str:
    """`owner/repo — what it does`, or the slug alone when there is no description.

    The em dash rather than a colon because repository descriptions frequently contain colons
    themselves, and two colons in one line read as a mistake.
    """
    text = " ".join(description.split())
    if not text:
        return full_name
    # A description long enough to wrap gets cut at a word boundary; the full text still
    # reaches the reader through `summary`.
    if len(text) > 90:
        cut = text[:90].rsplit(" ", 1)[0]
        text = (cut or text[:90]).rstrip(",.;:") + "…"
    return f"{full_name} — {text}"


_DIGITS = re.compile(r"\D+")


class GitHubTrendingFetcher(BaseFetcher):
    name = "GitHubTrendingFetcher"

    async def fetch(self, spec: SourceSpec) -> SourceResult:
        res = await self.http.get(spec.url, timeout_s=getattr(spec, "timeout_s", None) or None)
        base = self.from_http(spec, res)
        if not base.ok or res.verdict == "not_modified":
            return base
        base.items = self._parse(spec, res.text)
        return base

    def _parse(self, spec: SourceSpec, html: str, limit: int = 25) -> list[RawItem]:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "lxml")
        out: list[RawItem] = []

        for row in soup.select("article.Box-row")[:limit]:
            anchor = row.select_one("h2 a")
            if anchor is None or not anchor.get("href"):
                continue
            full_name = str(anchor["href"]).strip("/")
            if full_name.count("/") != 1:
                continue

            description_el = row.select_one("p")
            description = description_el.get_text(" ", strip=True) if description_el else ""

            stars_today = 0
            stars_el = row.select_one("span.d-inline-block.float-sm-right")
            if stars_el is not None:
                digits = _DIGITS.sub("", stars_el.get_text())
                stars_today = int(digits) if digits else 0

            lang_el = row.select_one("[itemprop='programmingLanguage']")
            language = lang_el.get_text(strip=True) if lang_el is not None else ""

            out.append(
                RawItem(
                    source_id=spec.source_id,
                    # **The title has to say what the repository is.**
                    #
                    # It used to be `full_name` alone, so the issue showed a row headed
                    # `anthropics/knowledge-work-plugins` and nothing else -- a reader had to
                    # open it to learn that it is a set of Claude Cowork plugins. The
                    # description was already fetched and already went into `summary`; it just
                    # was not in the one field a reader sees first.
                    title=_headline(full_name, description),
                    url=f"https://github.com/{full_name}",
                    published_at=None,       # by design: a window, not a date
                    summary=description[:2000],
                    content_text=None,
                    author=full_name.split("/")[0],
                    language=spec.language,
                    metrics={"stars_today": stars_today, "language": language},
                    native_id=full_name,
                )
            )
        return out
