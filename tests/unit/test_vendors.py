"""Recognising a vendor from its base URL.

The relay file is a flat list of `{baseUrl, key, label}` with no vendor field, and the export
the user supplied named no model either. The router's fallback model is
`gemini-flash-lite-latest`, which exactly one vendor serves, so 140 third-party endpoints
answered 404 and there was nothing usable to rotate to.

Recognising the host fixes that at the source. The equally important half is knowing when
**not** to: an unrecognised gateway must return `None` so the caller discovers or fails
loudly, because inventing a model name produces a 404 that reads like a broken credential.
"""

from __future__ import annotations

import pytest

from aidaily.vendors import Endpoint, describe, identify, looks_like_aggregator


@pytest.mark.parametrize(("url", "expected"), [
    ("https://api.deepseek.com/v1", "deepseek"),
    ("https://api.moonshot.cn/v1", "moonshot"),
    ("https://open.bigmodel.cn/api/paas/v4", "zhipu"),
    ("https://api.stepfun.com/v1", "stepfun"),
    ("https://api.minimaxi.com/v1", "minimax"),
    ("https://dashscope.aliyuncs.com/compatible-mode/v1", "aliyun"),
    ("https://api.hunyuan.cloud.tencent.com/v1", "tencent"),
    ("https://ark.cn-beijing.volces.com/api/v3", "bytedance"),
    ("https://api.siliconflow.cn/v1", "siliconflow"),
    ("https://generativelanguage.googleapis.com/v1beta/openai", "google"),
    ("https://api.openai.com/v1", "openai"),
    ("https://api.anthropic.com/v1", "anthropic"),
    ("https://api.groq.com/openai/v1", "groq"),
    ("https://openrouter.ai/api/v1", "openrouter"),
    ("https://api-inference.modelscope.cn/v1", "modelscope"),
])
def test_known_vendors_are_recognised(url: str, expected: str) -> None:
    vendor = identify(url)
    assert vendor is not None, f"未识别：{url}"
    assert vendor.id == expected


@pytest.mark.parametrize("url", [
    "https://api.hcnsec.cn/v1",
    "https://tokenrhythm.studio/v1",
    "https://ai.121628.xyz/v1",
    "https://api.camel-hub.cn",
])
def test_unknown_hosts_are_not_guessed(url: str) -> None:
    """Returning None is the feature. A guessed model 404s and looks like a bad key."""
    assert identify(url) is None


def test_a_longer_suffix_wins() -> None:
    """`api.deepseek.com` must not be matched by a broader pattern that also fits."""
    assert identify("https://api.deepseek.com/v1").id == "deepseek"
    assert identify("https://open.bigmodel.cn/api/paas/v4").id == "zhipu"


def test_a_reseller_domain_containing_a_vendor_name_is_not_that_vendor() -> None:
    """Substring matching on the whole URL would call this OpenAI."""
    assert identify("https://my-openai-proxy.example.com/v1") is None


@pytest.mark.parametrize("url", [
    "https://newapi.example.com/v1",
    "https://one-api.example.com/v1",
    "https://some-relay.example.com/v1",
    "https://gateway.example.com/v1",
])
def test_aggregators_are_labelled_as_such(url: str) -> None:
    assert looks_like_aggregator(url)


def test_a_first_party_host_is_not_an_aggregator() -> None:
    assert not looks_like_aggregator("https://api.deepseek.com/v1")


def test_describe_reports_all_three_pieces() -> None:
    name, aggregator, models = describe("https://api.deepseek.com/v1")
    assert name == "DeepSeek"
    assert aggregator is False
    assert models and "deepseek" in models[0].lower()


def test_describe_marks_an_unknown_host_without_models() -> None:
    """No vendor and no models: the caller must discover or fail, not assume."""
    name, aggregator, models = describe("https://api.hcnsec.cn/v1")
    assert name == "未知"
    assert aggregator is False
    assert models == []


def test_the_marker_only_certifies_its_own_models() -> None:
    """A relay that resells many vendors cannot be defaulted to a first-party model name.

    `openrouter` is marked `first_party_only=False`, which is what tells the caller its model
    list must be discovered rather than assumed.
    """
    openrouter = identify("https://openrouter.ai/api/v1")
    deepseek = identify("https://api.deepseek.com/v1")
    assert openrouter is not None and deepseek is not None
    assert openrouter.first_party_only is False
    assert deepseek.first_party_only is True


def test_endpoint_defaults_to_the_vendor_model() -> None:
    vendor = identify("https://api.moonshot.cn/v1")
    endpoint = Endpoint(base_url="https://api.moonshot.cn/v1", key="k", vendor=vendor)
    assert endpoint.vendor_name == "月之暗面 Kimi"
    assert endpoint.default_model()
    assert "kimi" in endpoint.default_model().lower() or "moonshot" in endpoint.default_model().lower()


def test_endpoint_without_a_vendor_has_no_default() -> None:
    endpoint = Endpoint(base_url="https://api.hcnsec.cn/v1", key="k", label="白嫖额度1")
    assert endpoint.vendor_name == "未知"
    assert endpoint.default_model() == "", "未知端点不得凭空给一个模型名"


def test_an_empty_or_broken_url_is_handled() -> None:
    for url in ("", "not a url", "ftp://x", "https://"):
        assert identify(url) is None
