"""Which vendor is this endpoint? Answered from the base URL.

## Why this exists

The relay file is a flat list of `{baseUrl, key, label}`. Nothing in it says who the endpoint
belongs to, so every row had to carry an explicit `model` -- and the 167-row export the user
supplied carried none. The router's fallback model is `gemini-flash-lite-latest`, which
exactly one vendor on earth serves, so 140 third-party endpoints answered 404 and the rotation
had nothing usable to rotate to.

Recognising the vendor from the host fixes that at the source: a row pointing at
`api.deepseek.com` should default to a DeepSeek model, not to a Google one.

## What it is used for

* **Choosing a default model** when the row does not name one.
* **Labelling a credential** in logs and failure reports, so "which account hit its cap" has
  an answer.
* **Not guessing.** An unknown host returns `None` and the caller must supply a model or let
  the row fail loudly. Inventing a model name for an unrecognised gateway is how you get a
  silent 404 that looks like a missing credential.

## Ordering

Longest suffix match wins, so `api.deepseek.com` and `open.bigmodel.cn` do not collide with a
broader domain that happens to contain the same letters. Vendor identity matters more than
model freshness: a model the vendor has retired fails loudly and gets skipped, whereas the
wrong vendor silently 404s every call from that endpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from urllib.parse import urlparse


@dataclass(frozen=True)
class Vendor:
    id: str
    name: str
    #: Hosts that belong to this vendor. Suffix match against the URL's hostname.
    hosts: tuple[str, ...] = ()
    #: Model names to try, most preferred first. Used only when the row names no model.
    models: tuple[str, ...] = ()
    #: True when the vendor only serves its own models, so an OpenAI model name is a 404.
    first_party_only: bool = True
    notes: str = ""


#: Frontier labs and their own APIs. Ordered roughly by how likely a relay is to be one.
VENDORS: tuple[Vendor, ...] = (
    Vendor("openai", "OpenAI", ("api.openai.com", "openai.com"),
           ("gpt-4o-mini", "gpt-4o", "gpt-4.1-mini")),
    Vendor("anthropic", "Anthropic", ("api.anthropic.com", "anthropic.com"),
           ("claude-3-5-haiku-latest", "claude-3-5-sonnet-latest")),
    Vendor("google", "Google Gemini", ("generativelanguage.googleapis.com",),
           ("gemini-flash-lite-latest", "gemini-2.5-flash", "gemini-1.5-flash")),
    Vendor("deepseek", "DeepSeek", ("api.deepseek.com", "deepseek.com"),
           ("deepseek-chat", "deepseek-v3", "deepseek-reasoner")),
    Vendor("moonshot", "月之暗面 Kimi", ("api.moonshot.cn", "moonshot.cn", "api.moonshot.ai"),
           ("kimi-k2-0905-preview", "moonshot-v1-8k")),
    Vendor("zhipu", "智谱 GLM", ("open.bigmodel.cn", "bigmodel.cn", "api.z.ai"),
           ("glm-4-flash", "glm-4-air", "glm-4-plus")),
    Vendor("minimax", "MiniMax", ("api.minimaxi.com", "minimax.chat", "api.minimax.chat"),
           ("MiniMax-Text-01", "abab6.5s-chat")),
    Vendor("stepfun", "阶跃星辰 StepFun", ("api.stepfun.com", "stepfun.com"),
           ("step-2-mini", "step-1-8k")),
    Vendor("aliyun", "阿里通义千问", ("dashscope.aliyuncs.com", "aliyuncs.com"),
           ("qwen-turbo", "qwen-plus", "qwen2.5-7b-instruct")),
    Vendor("tencent", "腾讯混元", ("api.hunyuan.cloud.tencent.com", "hunyuan.tencent.com"),
           ("hunyuan-turbos-latest", "hunyuan-lite")),
    Vendor("bytedance", "字节豆包 / 火山方舟", ("ark.cn-beijing.volces.com", "volces.com"),
           ("doubao-pro-32k", "doubao-lite-4k")),
    Vendor("baidu", "百度文心", ("qianfan.baidubce.com", "baidubce.com"),
           ("ernie-speed-128k", "ernie-3.5-8k")),
    Vendor("siliconflow", "硅基流动", ("api.siliconflow.cn", "siliconflow.cn"),
           ("Qwen/Qwen2.5-7B-Instruct", "deepseek-ai/DeepSeek-V3")),
    Vendor("groq", "Groq", ("api.groq.com",),
           ("openai/gpt-oss-120b", "openai/gpt-oss-20b", "qwen/qwen3.8-27b")),
    # Agnes has two deployments with separate keys and separate model catalogues; both speak the
    # OpenAI wire format. Measured 2026-10-23: 9 models each, and `agnes-3.0-flash` answers on
    # both. Listed as one vendor because the caller only needs a working default, and the model
    # that exists on both is the one to name.
    Vendor("agnes", "Agnes", ("apihub.agnes-ai.com", "api.agnes-ai.cn", "agnes-ai.com"),
           ("agnes-3.0-flash", "agnes-2.5-flash", "agnes-2.5-pro")),
    Vendor("cerebras", "Cerebras", ("api.cerebras.ai",), ("llama3.1-8b",)),
    Vendor("mistral", "Mistral", ("api.mistral.ai",), ("mistral-small-latest",)),
    Vendor("cohere", "Cohere", ("api.cohere.ai", "api.cohere.com"), ("command-r7b-12-2024",)),
    Vendor("nvidia", "NVIDIA NIM", ("integrate.api.nvidia.com", "api.nvidia.com"),
           ("meta/llama-3.1-8b-instruct",)),
    Vendor("together", "Together AI", ("api.together.xyz", "together.xyz"),
           ("meta-llama/Llama-3.3-70B-Instruct-Turbo",)),
    Vendor("openrouter", "OpenRouter", ("openrouter.ai",),
           ("google/gemini-flash-1.5", "openai/gpt-4o-mini"), first_party_only=False),
    Vendor("huggingface", "Hugging Face", ("api-inference.huggingface.co", "huggingface.co"),
           ("Qwen/Qwen2.5-7B-Instruct",), first_party_only=False),
    Vendor("modelscope", "ModelScope 魔搭", ("api-inference.modelscope.cn", "modelscope.cn"),
           ("Qwen/Qwen2.5-7B-Instruct",), first_party_only=False),
    Vendor("cloudflare", "Cloudflare Workers AI",
           ("api.cloudflare.com",), ("@cf/meta/llama-3.1-8b-instruct",)),
    Vendor("github", "GitHub Models", ("models.inference.ai.azure.com", "models.github.ai"),
           ("gpt-4o-mini",), first_party_only=False),
    Vendor("pollinations", "Pollinations", ("text.pollinations.ai", "pollinations.ai"),
           ("openai",), first_party_only=False),
)

#: Aggregator hosts that resell many vendors. A row pointing here is *not* first-party and its
#: model must be discovered rather than assumed, so these are recorded to say so in the log.
AGGREGATOR_HINTS = (
    "newapi", "one-api", "oneapi", "relay", "proxy", "gateway", "api2d", "openai-proxy",
)


def identify(base_url: str) -> Vendor | None:
    """The vendor a base URL belongs to, or None when it is not recognised.

    Longest matching host suffix wins, so a reseller domain containing `openai` as a
    substring does not get mistaken for OpenAI itself.
    """
    if not base_url:
        return None
    try:
        host = (urlparse(base_url).hostname or "").lower()
    except ValueError:
        return None
    if not host:
        return None

    best: tuple[int, Vendor] | None = None
    for vendor in VENDORS:
        for pattern in vendor.hosts:
            if host == pattern or host.endswith("." + pattern):
                if best is None or len(pattern) > best[0]:
                    best = (len(pattern), vendor)
    return best[1] if best else None


def looks_like_aggregator(base_url: str) -> bool:
    """True when the host is a reseller rather than a lab's own API.

    Used to decide whether a discovered model list can be trusted to be first-party, and to
    label the credential honestly in a failure report.
    """
    host = (urlparse(base_url or "").hostname or "").lower()
    return any(hint in host for hint in AGGREGATOR_HINTS)


@dataclass
class Endpoint:
    """A relay row enriched with what the host says about it."""

    base_url: str
    key: str
    label: str = ""
    model: str = ""
    vendor: Vendor | None = None
    aggregator: bool = False

    @property
    def vendor_name(self) -> str:
        if self.vendor:
            return self.vendor.name
        if self.aggregator:
            return "中转站"
        return "未知"

    def default_model(self) -> str:
        """The model to use when the row names none.

        Empty when the vendor is unknown -- and empty means the caller must discover or fail,
        which is the honest outcome. Returning a guess would produce a 404 that reads like a
        missing credential.
        """
        if self.vendor and self.vendor.models:
            return self.vendor.models[0]
        return ""


def describe(base_url: str) -> tuple[str, bool, list[str]]:
    """`(vendor name, is aggregator, candidate models)` for a base URL."""
    vendor = identify(base_url)
    aggregator = looks_like_aggregator(base_url)
    models = list(vendor.models) if vendor else []
    name = vendor.name if vendor else ("中转站" if aggregator else "未知")
    return name, aggregator, models
