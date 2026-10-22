"""An index page is not a story.

Measured on 2026-10-22: `2026-10-22日刊` from hex2077 entered the digest. It is the table of
contents for that site own issue -- clicking it leaves this site and lands on someone else
digest.

The rubric had already called it 噪音 (multiplier 0.30) and its heat was 0.31. It published
anyway, because both of those are *demotions* and nothing applied a structural test.

`is_container_title` reads the string rather than a score, so no ranking can override it, and it
is narrow enough that a story carrying a date still publishes.
"""

from __future__ import annotations

from aidaily.pipeline import is_container_title


def test_a_bare_date_is_a_container() -> None:
    assert is_container_title("2026-10-22")
    assert is_container_title("2026-10-22日刊")
    assert is_container_title("2026年10月22日")


def test_an_issue_number_is_a_container() -> None:
    assert is_container_title("第 42 期")
    assert is_container_title("42刊")


def test_a_month_is_a_container() -> None:
    assert is_container_title("2026-10")


def test_a_story_that_contains_a_date_is_not_a_container() -> None:
    """The test must not swallow real headlines."""
    assert not is_container_title("OpenAI ships GPT-6 on 2026-10-22")
    assert not is_container_title("2026物理AI与世界模型大会")


def test_an_ordinary_headline_is_not_a_container() -> None:
    assert not is_container_title("Anthropic推出Claude Duet人工智能代理")
    assert not is_container_title("腾讯混元 WorkForge：可验证长周期智能体训练环境框架")


def test_an_empty_title_is_not_a_container() -> None:
    assert not is_container_title("")
    assert not is_container_title("   ")