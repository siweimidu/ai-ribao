"""One vendor, many stories: the message key has to tell them apart.

Measured on the committed history, 2026-10-21:

    m:61e7a9a44ec34ad4 -> 31 headlines

Every one was a different DeepSeek story -- a five-hour outage, a ban by US Homeland Security,
a search API, a model launch, a Times award. The key was `(actors, event_types)` and nothing
more, so everything one company did inside a week shared an identity.

That produced both failure modes at once: repeats still shipped (the comparison that had to
catch them was a fuzzy title match against 31 candidates), and the key itself carried no
information, so it could not be used to group anything.
"""

from __future__ import annotations

from aidaily.samestory import message_key, same_message


def test_the_same_vendor_produces_different_keys_for_different_stories() -> None:
    """The regression that started this: 31 stories, one key."""
    stories = [
        "DeepSeek 近五小时停服，年度最严重之一",
        "DeepSeek 开放自研搜索 API",
        "DeepSeek 开源自研推理框架 DeepInfer",
        "DeepSeek 整合多支团队成立产品部",
        "美国国土安全部下令文职机构清除 DeepSeek 及基于其开发的产品",
    ]
    keys = {tuple(tuple(sorted(part)) for part in message_key(t)) for t in stories}
    assert len(keys) == len(stories), f"{len(stories)} stories collapsed to {len(keys)} keys"


def test_a_shared_subject_word_merges_one_event() -> None:
    """The pair that shipped twice: a launch and a report about the same launch."""
    assert same_message(
        "DeepSeek 开源自研推理框架 DeepInfer",
        "DeepSeek 以 Apache 2.0 开源生产推理引擎 DeepInfer",
    )


def test_a_shared_modifier_alone_does_not_merge() -> None:
    """`自研` ("in-house") appears in half the headlines about any vendor.

    Both stories are about DeepSeek and both say 自研; they are a framework release and a
    search API. Sharing only a modifier is not sharing a subject.
    """
    assert not same_message(
        "DeepSeek 开源自研推理框架 DeepInfer",
        "DeepSeek 开放自研搜索 API",
    )


def test_one_short_shared_word_is_not_enough() -> None:
    """代理 is a category, not a subject.

    "Microsoft 推出针对失控 AI 代理的新安全控制" is a product launch; "Microsoft称人工智能代理类似
    内部威胁" is a comment on a threat model. They share 代理 and nothing else.
    """
    assert not same_message(
        "Microsoft 推出针对失控 AI 代理的新安全控制",
        "Microsoft称人工智能代理类似内部威胁",
    )


def test_a_long_shared_word_is_enough_on_its_own() -> None:
    """A product name is specific by itself; that is the difference from a category."""
    assert same_message(
        "DeepSeek 开源自研推理框架 DeepInfer",
        "DeepSeek DeepInfer 已在 GitHub 开源，采用 Apache 2.0",
    )


def test_a_masthead_prefix_does_not_change_the_identity() -> None:
    """Newsletters prefix their own name; that must not make an old story new."""
    plain = message_key("OpenAI 发布 GPT-6")
    prefixed = message_key("AI 日报：OpenAI 发布 GPT-6")
    assert plain == prefixed
