"""Expand a roundup article into the individual stories it contains.

## The problem this solves

Several sources in this registry publish **one article per day** whose body is the whole day's
news. Their RSS carries a one-line summary of that article, so the collector stored one item per
day with ~46 characters of text. Measured on 2026-10-20: `ainewslog` had 480 such items with a
median body of 92 characters -- not enough to deduplicate, score, or display.

The full text is one request away, on the article page, and it is already structured:

    AI 日报 — 2026-10-19
    涵盖 20 条 AI 新闻
    🔥 今日焦点
    1. Anthropic、Google、OpenAI 或于本月推出新的前沿模型
    有报道称，...
    来源-reddit
    📰 重点报道
    基准测试与智能体评估                 <- section heading, carries no story
    LiveMACE 基准在动态演进市场中评估 LLM 智能体
    — 一个过程感知基准使用实时金融市场...
    来源-huggingface

## How the split works

Each story ends with a `来源-<credit>` line, so the credit line is the reliable delimiter: the
lines between two credit lines form one story. Inside that group the shape is either

    [title, body]                    numbered focus items
    [section, title, — body]         categorised items

and telling those apart is what the first version got wrong: it treated "基准测试与智能体评估"
(a section heading) as a story title, then desynchronised and returned 5 stories instead of 20.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class Story:
    title: str
    summary: str
    source: str


#: A numbered focus item: `1. Anthropic、Google、OpenAI 或于本月推出新的前沿模型`.
_NUMBERED = re.compile(r"^\s*\d{1,2}\s*[.、．]\s*(.+)$")

#: The body line that follows a title: `— 一个过程感知基准使用...`.
_DASH_BODY = re.compile(r"^\s*[—–]\s*(.+)$")

#: The credit line printed under each story. `来源-reddit`, `来源-huggingface`.
_CREDIT = re.compile(r"^\s*来源\s*[-－:：]\s*(.+)$")

#: A section marker: an emoji-prefixed heading like `🔥 今日焦点`.
_SECTION_MARK = re.compile(r"^\s*[🔥📰⚡🔬🛠📊💡🎯📌🗞]")

#: Lines that belong to the page chrome, not to any story.
_DATELINE = re.compile(r"^AI 日报\s*[—–-]\s*\d{4}-\d{2}-\d{2}")
_CHROME = re.compile(
    r"^(AI Daily|AI 日报|Toggle Menu|Pages|Back|daily|中文|English|首页)$"
)


def _text_lines(html: str) -> list[str]:
    """Visible text, one entry per line, with markup and scripts removed."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    for tag in soup.find_all(["p", "div", "li", "h1", "h2", "h3", "h4", "br", "tr"]):
        tag.insert_after("\n")
    return [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]


def _story_from_group(group: list[str]) -> Story | None:
    """One story from the lines between two credit lines."""
    lines = [ln for ln in group if not _SECTION_MARK.match(ln)]
    if not lines:
        return None

    # A section heading sits above the title and is followed by a `—` body two lines later.
    # Without this check the heading becomes the title and every later story shifts up one.
    if len(lines) >= 3 and _DASH_BODY.match(lines[2]):
        title, body_lines = lines[1], lines[2:]
    elif len(lines) >= 2 and _DASH_BODY.match(lines[1]):
        title, body_lines = lines[0], lines[1:]
    else:
        title, body_lines = lines[0], lines[1:]

    numbered = _NUMBERED.match(title)
    if numbered:
        title = numbered.group(1)

    body = " ".join(_DASH_BODY.match(x).group(1) if _DASH_BODY.match(x) else x for x in body_lines)
    title = title.strip()
    if _DATELINE.match(title) or len(title) < 6:
        return None
    return Story(title=title, summary=body.strip(), source="")


#: A bare date line: `Feb 13, 2026`.
_DATE_ONLY = re.compile(r"^[A-Z][a-z]{2}\s+\d{1,2},\s+\d{4}$")

#: Old-format section names. They are short, contain no verb, and end with a topic noun.
_OLD_SECTION = re.compile(
    r"^(生物信息学|LLM 推理|开源大模型|多模态|具身|推理与效率|开源与工具|AI 科学|模型竞争|社区|行业)[^。，]{0,20}$"
)


#: Old-format markers. An issue from early 2026 opens each story with `简介与背景：` and closes
#: it with `链接：`; there is no `来源-` line anywhere on the page.
_OLD_BODY = re.compile(r"^(简介与背景|影响与分析|背景与分析|影响|背景|简介)[:：]")
_OLD_LINK = re.compile(r"^链接[:：]\s*$")


def _split_old_format(lines: list[str], *, min_stories: int) -> list[Story]:
    """Stories from an issue that uses `简介与背景：` / `链接：` instead of `来源-`.

    Measured 2026-10-20: 2026-02 issues have this shape and 2026-10 issues do not. Without this
    branch the whole archive before the format change expanded to nothing.
    """
    stories: list[Story] = []
    title: str | None = None
    body: list[str] = []

    def flush() -> None:
        nonlocal title, body
        if title and len(title) >= 6:
            stories.append(Story(title=title, summary=" ".join(body).strip(), source=""))
        title, body = None, []

    for line in lines:
        if _CHROME.match(line) or _DATELINE.match(line) or _SECTION_MARK.match(line):
            continue
        if line in ("重点新闻", "今日焦点") or line.startswith("涵盖"):
            continue
        if _OLD_LINK.match(line):
            flush()
            continue
        if line.startswith("http"):
            continue
        if _OLD_BODY.match(line):
            body.append(_OLD_BODY.sub("", line).strip())
            continue
        if _DATE_ONLY.match(line) or _OLD_SECTION.match(line):
            continue
        if title is None:
            title = line.strip()
        else:
            body.append(line.strip())

    flush()
    # The issue summary (`A · B · C`) is not a story: no body, and it joins topics with `·`.
    stories = [s for s in stories if s.title.count("·") < 2]
    return stories if len(stories) >= min_stories else []


def split_article(html: str, *, min_stories: int = 3) -> list[Story]:
    """One `Story` per news item inside a roundup article.

    Returns an empty list when the page does not look like a roundup, so the caller keeps the
    original item instead of replacing it with a bad split.
    """
    lines = _text_lines(html)
    stories: list[Story] = []
    group: list[str] = []

    for line in lines:
        if _CHROME.match(line):
            continue

        credit = _CREDIT.match(line)
        if credit:
            story = _story_from_group(group)
            if story:
                story.source = credit.group(1).strip()
                stories.append(story)
            group = []
            continue

        if _SECTION_MARK.match(line):
            # A new section ends any group that never got a credit line.
            story = _story_from_group(group)
            if story:
                stories.append(story)
            group = []
            continue

        group.append(line)

    story = _story_from_group(group)
    if story:
        stories.append(story)

    if not stories:
        return _split_old_format(lines, min_stories=min_stories)
    return stories if len(stories) >= min_stories else []
