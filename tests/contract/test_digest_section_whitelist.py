"""A section the whitelist does not name must not vanish silently."""

from __future__ import annotations

from aidaily import digest_split as D

ISSUE = (
    '<h3 id="s7">前瞻与传闻</h3>'
    '<ul><li>马斯克称 Grok 4.8 推出较慢但不会令人失望 '
    '<a href="https://x.com/elonmusk/status/2116036703538606301">↗</a> '
    '<code>#14</code></li>'
    '<li>据报道 Anthropic 是 SpaceX 最大单一客户 <code>#15</code></li></ul>'
)


def test_the_measured_section_is_parsed() -> None:
    """2026-10-31: this section was not whitelisted and the Musk story never entered."""
    stories = D.split_digest(ISSUE)
    assert any("Grok 4.8" in s.title for s in stories)


def test_an_unknown_section_is_recorded_not_dropped() -> None:
    D.SKIPPED_SECTIONS.clear()
    D.split_digest('<h3>某个新栏目</h3><ul><li>x <a href="https://e.com/a">↗</a></li></ul>')
    assert "某个新栏目" in D.SKIPPED_SECTIONS


def test_a_numbered_row_without_a_link_is_recognised() -> None:
    """「据报道 Anthropic 是 SpaceX 最大单一客户 <code>#15</code>」 has no source link."""
    assert D._ROW_NO_LINK.search("<li>标题文字够长了 <code>#15</code></li>")