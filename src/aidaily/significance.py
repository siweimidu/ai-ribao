"""What counts as important news.

The digest's ranking had no notion of *significance*. It measured source category, body
length, engagement and recency -- and on a real day that put "企业微信升级 5.0.12" (a chat
app point release) and "Grok Bot 邮件多智能体用例" (a feature walkthrough) in the top
twelve, while `Gemini 4 Argon: Built to solve your hardest problems` -- the launch of a
frontier model, announced by its own lab -- sat at **position 58 of 60**.

The weights were per *source category*, so a lab blog scored 1.5 no matter what it said.
Significance is a property of the **content**, not of who published it: a new model release
matters more than a post about a chat app, and that is true whether it appears on
deepmind.google, on Hacker News, or in someone's digest.

This module scores that property directly, from the title and the corroboration, and stays
deliberately narrow: it recognises the few things that are unambiguously major (a new
frontier model, an official launch, a major funding or safety event) and returns 1.0 for
everything else, so it can only ever *lift* a story, never bury one.

Nothing here calls a model. It runs at ranking time, on every event, and must stay cheap and
deterministic -- a signal that is sometimes wrong is far better than one that is sometimes
absent, because absence is what produced this bug.
"""

from __future__ import annotations

import re

#: Laboratories and model families whose releases are, by themselves, major news.
#: Not exhaustive by design: an unlisted lab's release still scores through the release
#: patterns below, just without the front-of-list bonus.
FRONTIER_LABS = (
    "openai", "anthropic", "google", "deepmind", "gemini", "meta", "llama",
    "microsoft", "nvidia", "mistral", "qwen", "alibaba", "deepseek", "xai", "grok",
    "amazon", "apple", "hugging face", "huggingface", "moonshot", "kimi", "zhipu",
    "baidu", "ernie", "bytedance", "doubao", "tencent", "cohere", "stability",
)

#: A model release. `GPT-6`, `Gemini 4 Argon`, `Claude Opus 5.5`, `Llama 4`, `Qwen3`.
_MODEL_NAME = re.compile(
    r"\b(?:gpt|claude|gemini|llama|qwen|grok|mistral|mixtral|deepseek|kimi|ernie|"
    r"phi|gemma|command|nova|o[1-9])\b[\s\-]?[\d.]*",
    re.IGNORECASE,
)

#: Verbs that mean "this is a release", in both languages.
_RELEASE_VERBS = (
    "发布", "推出", "上线", "开放", "开源", "宣布", "面世", "登场", "亮相",
    "introducing", "announcing", "launch", "launches", "releases", "released",
    "unveils", "ships", "debuts", "open-sources", "generally available",
)

#: Words that mean the story is *about the model being new*, not about its use.
_NEWNESS = (
    "新模型", "新一代", "全新", "旗舰", "首次", "首个",
    "new model", "next-generation", "next generation", "frontier", "flagship",
    "first", "state of the art", "sota", "general availability", "ga release",
)

#: Things that are explicitly *not* the day's headline news, however well-sourced.
#: Without this, a lab's "we shipped v2.1.299" outranks a competitor's launch, because both
#: carry the lab's category weight.
_MINOR_PATTERNS = (
    # Point releases and patch versions: `v2.1.299`, `1.2.3`. A version with three numeric
    # parts is a patch; a model generation is a single number ("GPT-6", "Llama 4").
    r"\bv?\d+\.\d+\.\d+\b",
    r"更新日志", r"changelog", r"patch notes", r"hotfix", r"版本更新", r"小版本",
    r"\bcli\b.*\b(v?\d|release)", r"\bsdk\b.*\b(v?\d|release)",
    # Hiring, offices, events, marketing.
    r"招聘", r"hiring", r"we'?re hiring", r"办公室", r"办事处",
    r"发布会预告", r"meetup", r"webinar", r"podcast", r"播客",
    # Tutorials, explainers, listicles.
    r"教程", r"入门", r"指南", r"怎么做", r"how to", r"tutorial", r"guide",
    r"盘点", r"汇总", r"周报", r"月报",
    # Opinion and commentary.
    r"观点", r"评论", r"为什么", r"opinion", r"why ", r"thoughts on",
)

_MINOR = re.compile("|".join(_MINOR_PATTERNS), re.IGNORECASE)

#: URL path fragments that mean "the lab is announcing this itself".
#: A first-party announcement page is a stronger signal than the lab's name appearing in a
#: headline: "Gemini 4 Argon: Built to solve your hardest problems" is DeepMind's own launch
#: page and contains no release verb at all.
_ANNOUNCEMENT_PATHS = (
    "/blog/introducing", "/blog/announcing", "/introducing-", "/announcing-",
    "/news/", "/blog/", "/research/", "/index/",
)

#: URL fragments that are the *act* of releasing, stated by the publisher's own URL scheme.
#: `deepmind.google/blog/introducing-gemini-4-argon/` says "introducing" in the path even
#: when the headline does not. Treating this as a release verb is what lets the biggest
#: story of the day -- a launch post titled after the product rather than the act -- rank
#: as a launch.
_RELEASE_PATHS = ("introducing", "announcing", "launch", "release", "generally-available",
                  "now-available", "available-now", "unveil", "debut")

#: Domains that *are* the lab, so a post there is first-party rather than coverage.
_LAB_DOMAINS = (
    "openai.com", "anthropic.com", "deepmind.google", "blog.google", "ai.google",
    "ai.meta.com", "microsoft.com", "nvidia.com", "mistral.ai", "huggingface.co",
    "qwen.ai", "deepseek.com", "x.ai", "research.google", "github.blog",
)

#: An application or service *using* a model, not the model itself. `llama.cpp` is a runtime
#: and "上线 OpenRouter" is a hosting listing; neither is a frontier release, and without
#: this the model-family regex matched the word "llama" and scored them 3.2.
_APPLICATION_MARKERS = (
    ".cpp", "desktop app", "桌面应用", "插件", "plugin", "extension", "扩展",
    "wrapper", "客户端", "openrouter", "ollama", "lm studio", "vllm",
    "集成", "integration", "上线", "上架", "部署", "教程",
)


def _is_first_party(urls: tuple[str, ...] | list[str]) -> bool:
    for url in urls or ():
        low = url.lower()
        if not any(domain in low for domain in _LAB_DOMAINS):
            continue
        if any(frag in low for frag in _ANNOUNCEMENT_PATHS):
            return True
    return False


def _is_application(title: str, urls: tuple[str, ...] | list[str]) -> bool:
    haystack = title.lower() + " " + " ".join((urls or ())).lower()
    return any(marker in haystack for marker in _APPLICATION_MARKERS)


#: The digest is an **AI** daily. A frontier lab shipping a television is a real product
#: launch and irrelevant here, and the release detector alone scored it 2.2 -- "Apple
#: unveils the new Apple TV 4K" hit the `unveils` release path and the `apple` lab name.
#: This gate requires something AI-specific before any promotion applies.
_AI_TERMS = (
    "ai", "a.i.", "人工智能", "大模型", "模型", "机器学习", "深度学习", "神经网络",
    "llm", "agent", "智能体", "推理", "训练", "算力", "算法", "芯片", "gpu",
    "transformer", "diffusion", "rag", "prompt", "微调", "fine-tun", "多模态",
    "chatbot", "copilot", "neural", "inference", "embedding", "token",
)

_AI_PATTERN = re.compile(r"(?<![a-z])ai(?![a-z])|" + "|".join(
    re.escape(t) for t in _AI_TERMS if t != "ai"
), re.IGNORECASE)


def _is_ai_related(title: str, urls: tuple[str, ...] | list[str], labs: list[str]) -> bool:
    """Whether the story is about AI at all.

    A named frontier lab is *not* sufficient: Apple, Microsoft and Amazon all ship plenty of
    non-AI products, and the lab list exists to recognise AI announcements from those
    companies rather than to treat everything they publish as AI news.

    The URL is checked as well as the title, because a first-party path like
    `/blog/introducing-gemini-4-argon/` is AI content even when the headline is terse.
    """
    haystack = title + " " + " ".join(urls or ())
    if _AI_PATTERN.search(haystack):
        return True
    # A model-family name is itself AI evidence ("GPT-6", "Llama 4").
    if _MODEL_NAME.search(title):
        return True
    # Otherwise the lab must be one that only does AI.
    ai_only = {
        "openai", "anthropic", "deepmind", "gemini", "llama", "mistral", "qwen",
        "deepseek", "xai", "grok", "huggingface", "hugging face", "moonshot", "kimi",
        "zhipu", "ernie", "cohere", "stability", "doubao",
    }
    return any(lab in ai_only for lab in labs)


def _url_says_release(urls: tuple[str, ...] | list[str]) -> bool:
    """True when the publisher's own URL path states a release.

    `/blog/introducing-gemini-4-argon/` is DeepMind saying they introduced it. This is a
    publisher's own description of their own page, not an inference about meaning.
    """
    for url in urls or ():
        low = url.lower()
        if any(frag in low for frag in _RELEASE_PATHS):
            return True
    return False
    """True when the publisher's own URL path states a release.

    `/blog/introducing-gemini-4-argon/` is DeepMind saying they introduced it. This is a
    publisher's own description of their own page, not an inference about meaning.
    """
    for url in urls or ():
        low = url.lower()
        if any(frag in low for frag in _RELEASE_PATHS):
            return True
    return False


def _has_any(text: str, needles: tuple[str, ...]) -> bool:
    low = text.lower()
    return any(n in low for n in needles)


def significance(
    title: str,
    *,
    independent_sources: int = 0,
    body_chars: int = 0,
    urls: tuple[str, ...] | list[str] = (),
) -> tuple[float, dict]:
    """How major a story is, as a multiplier ≥ 1.0 plus the reasons.

    Returns `(multiplier, components)`. **The floor is 1.0**: this signal can only promote a
    story, never demote one. That asymmetry is deliberate -- a missed promotion costs one
    position, while a wrong demotion silently hides real news, which is the failure this
    module was written to fix.

    The bands, in order of how unambiguous they are:

    * **3.2** — a frontier lab shipping a named model, either stated in the title or
      published on the lab's own announcement page. `Gemini 4 Argon` by Google. This is the
      day's headline whenever it happens.
    * **2.2** — a model release by anyone, or a frontier lab's official announcement.
    * **1.5** — other first-party news from a frontier lab, plus anything corroborated by
      three or more independent sources.
    """
    text = (title or "").strip()
    low = text.lower()
    reasons: dict[str, float] = {}

    has_model = bool(_MODEL_NAME.search(text))
    has_release = _has_any(text, _RELEASE_VERBS) or _url_says_release(urls)
    has_new = _has_any(text, _NEWNESS)
    lab_hits = [lab for lab in FRONTIER_LABS if lab in low]
    is_minor = bool(_MINOR.search(text))
    first_party = _is_first_party(urls)
    is_app = _is_application(text, urls)
    is_ai = _is_ai_related(text, urls, lab_hits)

    score = 1.0

    # An application or runtime that merely mentions a model family is not a model release.
    if is_app:
        has_model = False

    # Nothing may be promoted unless the story is about AI. Apple shipping a television is
    # a genuine product launch and not this digest's subject; without this gate the release
    # path and the lab name together scored it 2.2 and put it in the top ten.
    if not is_ai:
        return 1.0, {
            "significance": 1.0,
            "not_ai": 1.0,
            "sig_model": float(has_model),
            "sig_release": float(has_release),
            "sig_lab": float(bool(lab_hits)),
            "sig_first_party": float(first_party),
        }

    if has_model and has_release and (lab_hits or first_party):
        score = 3.2
        reasons["frontier_model_release"] = 3.2
    elif has_model and has_release and has_new:
        # No lab named, but it is explicitly a new model being shipped.
        score = 2.8
        reasons["model_launch"] = 2.8
    elif has_model and (has_release or has_new):
        score = 2.2
        reasons["model_release"] = 2.2
    elif lab_hits and has_release:
        score = 2.2
        reasons["lab_announcement"] = 2.2
    elif first_party and (has_release or has_new):
        # The lab's own announcement page. Catches launch posts whose headline describes the
        # product rather than the act -- "Gemini 4 Argon: Built to solve your hardest
        # problems" contains no release verb, and it is the day's biggest story.
        score = 2.2
        reasons["first_party_announcement"] = 2.2
    elif lab_hits and has_new:
        score = 1.5
        reasons["lab_new_thing"] = 1.5

    # Corroboration is independent evidence that a story matters: several outlets decided
    # it was worth covering. Applied as a floor so it can raise a 1.0 but not lower a 3.2.
    if independent_sources >= 3:
        floor = 1.6
        if floor > score:
            score = floor
            reasons["widely_reported"] = floor

    # A minor marker cancels the *promotion* but never drops below 1.0. A point release from
    # a frontier lab is still a lab announcement; it is just not the headline.
    if is_minor and score > 1.0:
        score = 1.0
        reasons = {"minor": 1.0}
    elif is_minor:
        reasons["minor"] = 1.0

    if is_app and score < 2.2:
        reasons["application_not_model"] = 1.0

    return score, {
        "significance": round(score, 3),
        **reasons,
        "sig_model": float(has_model),
        "sig_release": float(has_release),
        "sig_lab": float(bool(lab_hits)),
        "sig_first_party": float(first_party),
    }
