"""Juya's live feed is HTML with a story-by-story DOM, and must be split that way.

The plain-text splitter worked against a hand-copied fixture and did nothing in production. The
live feed's `content` is a **render of the issue page**:

* top stories: `<h3><a href="source">title</a> <code>#1</code></h3>` followed by that story's
  paragraphs and blockquotes;
* later sections: `<li>title <a href="source">↗</a> <code>#29</code></li>`.

Measured on the live 2026-10-15 entry: the old stripper produced **zero** numbered plain-text
lines from a 43 KB HTML body, so `looks_like_roundup` was False and the whole issue stayed one
item. The fixture used plain text, which is why the test passed and production did not.

These cases use the real HTML shapes, and the last one asserts the story the user asked about.
"""

from __future__ import annotations

from datetime import datetime, timezone

from aidaily.models import RawItem
from aidaily.roundup import looks_like_roundup, split_all, split_roundup

NOW = datetime(2026, 10, 15, 6, 0, tzinfo=timezone.utc)

#: The two DOM shapes, reduced to what the parser keys on: an `h3` story with its own body, and
#: ranked `li` entries whose rank is a sibling `<code>` element.
LIVE_HTML = """
<div><p><img src="https://assets.juya.uk/cover.png" /></p>
<h1>AI 早报 2026-10-15</h1>
<h2 id="s1">概览</h2>
<h3 id="s2">要闻</h3>
<ul>
  <li>Claude Code 桌面版更新优化多会话体验 <a href="https://x.com/ClaudeDevs/status/1" rel="noopener">↗</a> <code>#1</code></li>
  <li>Claude Code 新增闲置会话自动压缩 <a href="https://x.com/lydiahallie/status/2" rel="noopener">↗</a> <code>#2</code></li>
</ul>
<h3 id="s3">模型发布</h3>
<ul>
  <li>蚂蚁百灵开源 Ling-3.1-flash 模型 <a href="https://x.com/AntLingAGI/status/5" rel="noopener">↗</a> <code>#5</code></li>
  <li>昆仑万维发布并开源 Matrix-Game 4.0 <a href="https://matrix-game-v4-0.github.io/page/" rel="noopener">↗</a> <code>#6</code></li>
</ul>
<h3 id="s4">开发生态</h3>
<ul>
  <li>OpenCode Go 上线 Gemini 4 Argon <a href="https://x.com/opencode/status/7" rel="noopener">↗</a> <code>#7</code></li>
</ul>
<h3 id="s9">其他</h3>
<ul>
  <li>DeepSeek 网页及 API 出现中断 <a href="https://status.deepseek.com/incidents/7116348214287" rel="noopener">↗</a> <code>#29</code></li>
</ul>
<hr />
<h2 id="s10">要闻</h2>
<h3 id="s11"><a href="https://x.com/ClaudeDevs/status/1" rel="noopener">Claude Code 桌面版更新优化多会话体验</a> <code>#1</code></h3>
<blockquote><strong>Anthropic</strong> 更新了 <strong>Claude Code</strong> 桌面应用，重点改善多个会话并排运行的体验。</blockquote>
<p><strong>Anthropic</strong> 更新 <code>Claude Code</code> 桌面应用，围绕多会话并行改进会话启动。</p>
</div>
"""


def entry(title: str = "2026-10-15", body: str = LIVE_HTML) -> RawItem:
    return RawItem(
        source_id="rss:daily-juya-uk", title=title,
        url="https://daily.juya.uk/issues/2026-10-15/",
        published_at=NOW, summary="AI 早报 2026 10 15 视频版：YouTube", content_text=body,
        author=None, language="zh", metrics={},
        native_id="https://daily.juya.uk/issues/2026-10-15/",
    )


# =============================== detection =======================================
def test_live_html_is_recognised_as_a_roundup() -> None:
    """The old detector looked for plain-text `#N` lines and found none in real HTML."""
    assert looks_like_roundup(entry())


def test_a_date_titled_html_article_without_ranks_is_not_a_roundup() -> None:
    thin = "<div><h3>某条新闻</h3><p>正文</p></div>"
    assert not looks_like_roundup(entry(body=thin))


# =============================== extraction ======================================
def test_the_deepseek_outage_becomes_its_own_story_with_its_source_url() -> None:
    """The measured case. It was inside a 43 KB HTML blob that never split, so no scoring change
    could have surfaced it."""
    rows = split_roundup(entry())
    hit = next((r for r in rows if "DeepSeek 网页" in r.title), None)
    assert hit is not None, [r.title for r in rows]
    # The citation is the href Juya published, not a guessed issue anchor.
    assert hit.url == "https://status.deepseek.com/incidents/7116348214287"


def test_every_ranked_story_becomes_an_item() -> None:
    rows = split_roundup(entry())
    titles = [r.title for r in rows]
    assert "OpenCode Go 上线 Gemini 4 Argon" in titles
    assert "蚂蚁百灵开源 Ling-3.1-flash 模型" in titles


def test_the_rank_marker_is_not_part_of_the_title() -> None:
    """`#29` is the issue's numbering, not the story's name."""
    for row in split_roundup(entry()):
        assert "#" not in row.title, row.title
        assert "↗" not in row.title, row.title


def test_a_story_is_not_emitted_twice() -> None:
    """Claude Code appears in both the outline list and the detailed `h3` block."""
    rows = split_roundup(entry())
    titles = [r.title for r in rows]
    assert titles.count("Claude Code 桌面版更新优化多会话体验") == 1


def test_the_detailed_block_carries_its_body() -> None:
    """An outline entry is a headline; the `h3` block is a story with prose worth analysing."""
    rows = split_roundup(entry())
    row = next(r for r in rows if r.title == "Claude Code 桌面版更新优化多会话体验")
    assert "多会话并行" in (row.content_text or "")
    assert len(row.content_text or "") > len(row.title)


def test_the_issue_is_recorded_as_the_roundup_of_each_story() -> None:
    for row in split_roundup(entry()):
        assert (row.metrics or {}).get("roundup_of") == "https://daily.juya.uk/issues/2026-10-15/"
        assert (row.metrics or {}).get("roundup_index")


def test_an_ordinary_item_is_returned_unchanged() -> None:
    item = entry(title="DeepSeek 发布 V4", body="<p>正文</p>")
    assert split_roundup(item) == [item]


def test_split_all_is_safe_over_a_mixed_batch() -> None:
    ordinary = entry(title="DeepSeek 发布 V4", body="<p>正文</p>")
    out = split_all([ordinary, entry()])
    assert out[0] is ordinary
    assert len(out) > 1


def test_a_plain_text_roundup_still_splits() -> None:
    """Older cached items carry text, not HTML."""
    body = "\n".join([
        "Claude Code 桌面版更新优化多会话体验 ↗ #1",
        "蚂蚁百灵开源 Ling-3.1-flash 模型 ↗ #5",
        "DeepSeek 网页及 API 出现中断 ↗ #29",
        "昆仑万维发布并开源 Matrix-Game 4.0 ↗ #6",
        "OpenCode Go 上线 Gemini 4 Argon ↗ #7",
    ])
    rows = split_roundup(entry(body=body))
    assert len(rows) == 5
    assert any("DeepSeek" in r.title for r in rows)


def test_a_section_heading_is_not_a_story() -> None:
    """`<h3>要闻</h3>` precedes a ranked list, so `_rank_after` finds `#1` and the heading was
    emitted as a story called `要闻`. A section name is structure, not news."""
    titles = [r.title for r in split_roundup(entry())]
    for heading in ("要闻", "概览", "模型发布", "开发生态", "其他"):
        assert heading not in titles, f"{heading} 被当成新闻条目"


def test_a_split_failure_keeps_the_item_and_reports_it() -> None:
    """`split_all` must never lose an item, and must never swallow the reason silently.

    The failure is injected through `looks_like_roundup` because that is the first thing
    `split_roundup` calls -- patching it proves the `except` branch appends the original item and
    reports, rather than dropping it.
    """
    import aidaily.roundup as roundup_module

    seen: list[tuple[str, str]] = []
    original = roundup_module.looks_like_roundup

    def boom(_item):
        raise RuntimeError("boom")

    roundup_module.looks_like_roundup = boom
    try:
        bad = entry()
        out = split_all([bad], on_error=lambda i, e: seen.append((i.title, type(e).__name__)))
    finally:
        roundup_module.looks_like_roundup = original

    assert out == [bad], "条目在拆分失败时必须原样保留"
    assert seen == [("2026-10-15", "RuntimeError")], seen
