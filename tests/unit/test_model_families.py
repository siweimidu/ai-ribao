"""Every model family the user listed must register as AI-relevant.

The list was supplied explicitly, so this file is a contract: one case per family, plus the
disambiguation that keeps ordinary English words from certifying a story as AI news.

## Why the disambiguation exists

Five of the names are also ordinary English words. Measured before the fix:

    fable of the bees            1.00   ← would have been published as AI news
    a musing on life             1.00
    mythos in literature         1.00
    reflection on the year       1.00
    agnes of rome                1.00

The same mistake as the bare-`AI` case this module already documents: one ambiguous token is not
evidence of the subject. They now require an AI cue alongside.
"""

from __future__ import annotations

import pytest

from aidaily.focus import MODEL_FAMILIES, _headline_focus

#: (headline, family) — one per family in the user's list, written the way a headline would.
CASES: list[tuple[str, str]] = [
    ("GPT-5 发布并开放 API", "gpt"),
    ("gpt-oss 开源权重发布", "gpt"),
    ("Claude 4 Opus 上线", "claude"),
    ("Gemini 3 向订阅者开放", "gemini"),
    ("DeepSeek V5 开源", "deepseek"),
    ("通义千问 Qwen4 发布", "qwen"),
    ("MiniMax 海螺新版本", "minimax"),
    ("Grok 5 发布", "grok"),
    ("Kimi K3 上线", "kimi"),
    ("智谱 GLM-6 发布", "glm"),
    ("Mistral Large 3 开源", "mistral"),
    ("豆包 3.0 上线", "doubao"),
    ("腾讯混元大模型开源", "hunyuan"),
    ("小米 MiMo 模型发布", "mimo"),
    ("阶跃星辰 Step 6 发布", "step"),
    ("讯飞星火大模型升级", "spark"),
    ("文心一言 ERNIE 5 发布", "ernie"),
    ("Gemma 3 开源", "gemma"),
    ("商汤日日新 SenseNova 6", "sensenova"),
    ("面壁 MiniCPM 5 发布", "minicpm"),
    ("通义万相 Wan3 发布", "wan"),
    ("华为盘古大模型升级", "pangu"),
    ("美团 LongCat 开源", "longcat"),
    ("Llama 5 发布", "llama"),
    ("Veo 3 视频生成开放", "veo"),
    ("Midjourney v7 发布", "midjourney"),
    ("DALL·E 4 上线", "dalle"),
    ("Stable Diffusion 4 发布", "stable diffusion"),
    ("FLUX 2 开源", "flux"),
    ("Runway Gen-4 发布", "runway"),
    ("Pika 2 上线", "pika"),
    ("可灵 Kling 5 发布", "kling"),
    ("Seedance 2.0 发布", "seedance"),
    ("Vidu 3 上线", "vidu"),
    ("Sora 3 发布", "sora"),
    ("Nemotron 4 发布", "nemotron"),
    ("Command R++ 发布", "command"),
    ("Mythos 模型发布", "mythos"),
    ("Fable 新模型上线", "fable"),
    ("Muse 开源权重", "muse"),
    ("Reflection 大模型评测", "reflection"),
    ("Agnes 发布 2.0 模型", "agnes"),
]


@pytest.mark.parametrize(("headline", "family"), CASES)
def test_every_listed_family_is_recognised(headline: str, family: str) -> None:
    assert family in MODEL_FAMILIES or family in {
        "mythos", "fable", "muse", "reflection", "agnes",
    }, f"{family} 不在词表里"
    assert _headline_focus(headline) >= 0.70, f"{headline} 被判为不相关"


def test_the_family_table_covers_the_requested_names() -> None:
    """A name silently missing from the table is the failure this guards against."""
    required = {
        "gpt", "claude", "gemini", "deepseek", "qwen", "minimax", "grok", "kimi", "glm",
        "mistral", "doubao", "hunyuan", "mimo", "step", "spark", "ernie", "gemma",
        "sensenova", "minicpm", "wan", "pangu", "longcat", "veo", "midjourney", "dalle",
        "stable diffusion", "flux", "runway", "pika", "kling", "seedance", "vidu", "llama",
    }
    missing = required - set(MODEL_FAMILIES)
    assert not missing, f"词表缺少：{sorted(missing)}"


# =============================== disambiguation ==================================
@pytest.mark.parametrize("text", [
    "fable of the bees",
    "a musing on life",
    "mythos in literature",
    "reflection on the year",
    "agnes of rome",
])
def test_an_ordinary_english_phrase_is_not_ai_news(text: str) -> None:
    """Measured before the fix: all five scored 1.00 and would have been published."""
    assert _headline_focus(text) < 0.70, f"{text} 被误判为 AI 新闻"


@pytest.mark.parametrize("text", [
    "Fable 发布新模型",
    "Muse 开源权重",
    "Mythos 模型评测",
])
def test_the_same_name_with_an_ai_cue_does_count(text: str) -> None:
    assert _headline_focus(text) >= 0.70


# =============================== no over-matching ================================
@pytest.mark.parametrize("text", [
    "a glamorous party",          # `glm` inside `glamorous`
    "sparkling water",            # `spark` inside `sparkling`
    "command of the language",    # `command` alone is not the model
    "phi beta kappa",             # `phi` inside a society name
])
def test_ordinary_words_do_not_trigger_the_vocabulary(text: str) -> None:
    assert _headline_focus(text) < 0.70, f"{text} 被误判"
