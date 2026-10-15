"""Verify the candidate sources the user supplied.

The user said plainly: "这些信息源很多我没有亲自核验需要你核验一下，我只要和AI相关的".
So this does three things per URL and reports all three, rather than only whether it
resolves:

1. **Reachable?** HTTP status, final URL after redirects, content type, size.
2. **Is it a feed?** Parses as RSS/Atom/JSON Feed, and how many entries it yields. A page
   that returns 200 HTML is not a feed even though it is "up" -- and the collector would
   report a healthy fetch that contributes nothing.
3. **Is it about AI?** Title/entry keywords. The AIHOT and AI-daily feeds are AI by
   definition; a personal blog is not, and the user asked for AI only.

Results go to JSON so the registry edit can be driven from evidence rather than retyped by
hand, and a compact table is printed for review.

Telegram channels are included: they are HTML, not feeds, and they are unreachable from
mainland China but fine from GitHub's runners. Both facts are reported rather than guessed.
"""

from __future__ import annotations

import asyncio
import json
import re
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "data" / "state" / "source_verification.json"

#: label -> (url, kind). `kind` only affects the report wording; the checks are the same.
CANDIDATES: list[tuple[str, str, str]] = [
    # --- AIHOT feeds ---
    ("AIHOT 精选", "https://aihot.news/feed.xml", "feed"),
    ("AIHOT 日报", "https://aihot.news/feed/daily.xml", "feed"),
    ("AIHOT 全文", "https://aihot.news/feed/full.xml", "feed"),
    ("AIHOT 全部动态", "https://aihot.news/feed/all.xml", "feed"),
    ("AIHOT 周报", "https://aihot.news/feed/weekly.xml", "feed"),
    ("AIHOT 月报", "https://aihot.news/feed/monthly.xml", "feed"),
    ("AIHOT 模型分类", "https://aihot.news/feed/category/ai-models.xml", "feed"),
    ("AIHOT 产品分类", "https://aihot.news/feed/category/ai-products.xml", "feed"),
    ("AIHOT 行业分类", "https://aihot.news/feed/category/industry.xml", "feed"),
    ("AIHOT 论文分类", "https://aihot.news/feed/category/paper.xml", "feed"),
    ("AIHOT 教程分类", "https://aihot.news/feed/category/tip.xml", "feed"),
    ("AIHOT 观点分类", "https://aihot.news/feed/category/opinion.xml", "feed"),
    # --- 微信公众号 ---
    ("机器之心 xlab", "https://wechat2rss.xlab.app/feed/51e92aad2728acdd1fda7314be32b16639353001.xml", "feed"),
    ("机器之心 bestblogs", "https://wechat2rss.bestblogs.dev/feed/8d97af31b0de9e48da74558af128a4673d78c9a3.xml", "feed"),
    ("机器之心 decemberpei", "https://decemberpei.cyou/rssbox/wechat-jiqizhixin.xml", "feed"),
    ("新智元 xlab", "https://wechat2rss.xlab.app/feed/ede30346413ea70dbef5d485ea5cbb95cca446e7.xml", "feed"),
    ("新智元 decemberpei", "https://decemberpei.cyou/rssbox/wechat-xinzhiyuan.xml", "feed"),
    ("量子位", "https://decemberpei.cyou/rssbox/wechat-liangziwei.xml", "feed"),
    ("DeepSeek", "https://wechat2rss.bestblogs.dev/feed/1709da4f538d4ce4fb6d7a8ba1a5a1c297919601.xml", "feed"),
    ("智谱", "https://wechat2rss.bestblogs.dev/feed/433d2134dca54d80804daf32e8be546155be3300.xml", "feed"),
    ("腾讯混元", "https://wechat2rss.bestblogs.dev/feed/306ce19a1ca590c9c2df781789e828d1acfa1356.xml", "feed"),
    ("DeepTech深科技", "https://decemberpei.cyou/rssbox/wechat-shenkeji.xml", "feed"),
    ("PaperWeekly", "https://decemberpei.cyou/rssbox/wechat-paperweekly.xml", "feed"),
    ("计算机视觉life", "https://decemberpei.cyou/rssbox/wechat-jisuanjishijuelife.xml", "feed"),
    ("AI前线", "https://decemberpei.cyou/rssbox/wechat-aiqianxian.xml", "feed"),
    ("夕小瑶科技说", "https://decemberpei.cyou/rssbox/wechat-xixiaoyaokejishuo.xml", "feed"),
    ("海外独角兽", "https://decemberpei.cyou/rssbox/wechat-haiwaidujiaoshou.xml", "feed"),
    ("甲子光年", "https://decemberpei.cyou/rssbox/wechat-jiaziguangnian.xml", "feed"),
    ("集智俱乐部", "https://decemberpei.cyou/rssbox/wechat-jizhijvlebu.xml", "feed"),
    ("我爱计算机视觉", "https://wechat2rss.xlab.app/feed/b81ffcfff1107b5265cd7e39de610dc7ca72caf4.xml", "feed"),
    # --- 个人博客 ---
    ("宝玉 baoyu.io", "https://baoyu.io/feed.xml", "feed"),
    ("宝玉 s.baoyu.io", "https://s.baoyu.io/feed.xml", "feed"),
    ("謝懿Shine", "https://xieyi.org/rss.xml", "feed"),
    ("Kaichao You", "https://youkaichao.github.io/feed.xml", "feed"),
    ("范叶亮", "https://leovan.me/cn/index.xml", "feed"),
    ("Yi's blog", "https://wangyi.ai/atom.xml", "feed"),
    ("Changkun's Blog", "https://changkun.de/blog/posts/index.xml", "feed"),
    # --- 其他 AI 日报 ---
    ("CloudFlare-AI-Insight-Daily", "https://justlovemaki.github.io/CloudFlare-AI-Insight-Daily/rss.xml", "feed"),
    ("高军AI日报", "https://freelander.github.io/AI-Daily/rss.xml", "feed"),
    ("AI Daily Digest (vercel)", "https://ai-daily-zeta.vercel.app/rss.xml", "feed"),
    ("Builders Digest", "https://imhw.github.io/ai-daily/rss.xml", "feed"),
    ("unclejoeyao AI早报", "https://unclejoeyao666.github.io/ai-daily-news/rss.xml", "feed"),
    ("Ken AI日报", "https://ken-chy129.github.io/news/rss.xml", "feed"),
    ("yanxiuzi AI brief", "https://yanxiuzi.github.io/ai-brief/rss.xml", "feed"),
    ("lhdbot AI新闻日报", "https://lhdbot.github.io/ai-news/rss.xml", "feed"),
    ("tianyaxiang AI News", "https://tianyaxiang.github.io/ai-news/rss.xml", "feed"),
    ("zhalice AI Daily", "https://ai-daily-zeta.vercel.app/feed.xml", "feed"),
    ("RollingTheRock AI晨报", "https://ai-daily-digest-xi.vercel.app/rss.xml", "feed"),
    ("vigor AI Daily Digest", "https://vigorx777.github.io/ai-daily-digest/rss.xml", "feed"),
    ("LeeFeee AI行业日报", "https://leefeee.github.io/ai-daily/rss.xml", "feed"),
    ("hex2077 AI日刊", "https://hex2077.dev/rss.xml", "feed"),
    ("ai.hubtoday", "https://ai.hubtoday.app/rss.xml", "feed"),
    ("Park AI日报", "https://park-ai-intel.com/rss.xml", "feed"),
    ("yeekal AI Daily", "https://yeekal.com/daily/rss.xml", "feed"),
    ("daily.ai225", "https://daily.ai225.com/rss.xml", "feed"),
    ("podrss AI播报", "https://podrss.1874.run/rss.xml", "feed"),
    ("aihot.news/daily", "https://aihot.news/daily", "page"),
    # --- Telegram 频道 ---
    ("TG AI_News_CN", "https://t.me/AI_News_CN", "telegram"),
    ("TG aipluscn", "https://t.me/aipluscn", "telegram"),
    ("TG ai_copilot_channel", "https://t.me/ai_copilot_channel", "telegram"),
    ("TG rollerrolling", "https://t.me/rollerrolling", "telegram"),
    ("TG followbun", "https://t.me/followbun", "telegram"),
]

AI_TERMS = re.compile(
    r"(?<![a-z])(ai|a\.i\.|llm|gpt|claude|gemini|llama|qwen|deepseek|agent|transformer|"
    r"diffusion|rag|openai|anthropic|deepmind|nvidia|copilot|chatgpt|machine learning|"
    r"neural|model|inference|embedding)(?![a-z])|"
    r"人工智能|大模型|机器学习|深度学习|神经网络|智能体|算力|模型|算法|芯片|推理|训练",
    re.IGNORECASE,
)

UA = "Mozilla/5.0 (compatible; ai-ribao-source-check/1.0; +https://github.com/siweimidu/ai-ribao)"


def looks_like_ai(text: str) -> tuple[bool, int]:
    """(is_ai, hits). Counted, not boolean: one stray "AI" in a nav bar is not a topic."""
    hits = len(AI_TERMS.findall(text or ""))
    return hits >= 3, hits


async def check(client: httpx.AsyncClient, label: str, url: str, kind: str) -> dict:
    record: dict = {"label": label, "url": url, "kind": kind}
    try:
        resp = await client.get(url, headers={"User-Agent": UA}, follow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        record.update(ok=False, error=f"{type(exc).__name__}: {str(exc)[:90]}")
        return record

    body = resp.text or ""
    record.update(
        status=resp.status_code,
        final_url=str(resp.url),
        content_type=resp.headers.get("content-type", "").split(";")[0],
        bytes=len(resp.content),
        ok=resp.status_code == 200,
    )

    # Feed parsing decides "usable" -- a 200 HTML page is not a feed.
    entries: list[dict] = []
    try:
        import feedparser

        parsed = feedparser.parse(body)
        entries = list(parsed.entries or [])
        record["feed_format"] = "feed"
        record["feed_title"] = (parsed.feed or {}).get("title", "")[:80]
        record["entries"] = len(entries)
    except Exception as exc:  # noqa: BLE001
        record["feed_error"] = f"{type(exc).__name__}: {str(exc)[:80]}"

    if not entries and kind == "feed":
        # JSON Feed, or an HTML page where a feed was expected.
        try:
            doc = json.loads(body)
            if isinstance(doc, dict) and doc.get("items"):
                entries = doc["items"]
                record.update(feed_format="jsonfeed", entries=len(entries),
                              feed_title=str(doc.get("title", ""))[:80])
        except Exception:  # noqa: BLE001
            pass

    if entries:
        # Sample the title **and** the summary.
        #
        # The first version used `title or summary`, so any feed whose item titles are dates
        # never had its body inspected. That misclassified CloudFlare-AI-Insight-Daily -- an
        # AI digest whose entries are titled "2026-10-15日刊" -- as "not about AI" when its
        # descriptions are entirely AI news.
        sample = " ".join(
            str(e.get("title") or "") + " " + str(e.get("summary") or "")[:400]
            for e in entries[:12]
        )
        is_ai, hits = looks_like_ai(sample)
        record.update(is_ai=is_ai, ai_hits=hits, sample_title=str(
            entries[0].get("title") or "")[:90])
        record["usable"] = True
    elif record.get("status") == 200 and kind in ("page", "telegram"):
        is_ai, hits = looks_like_ai(body[:20000])
        record.update(is_ai=is_ai, ai_hits=hits, usable=False,
                      note="HTML 页面，非 feed；需 HtmlFetcher")
    else:
        record["usable"] = False

    return record


async def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    targets = [c for c in CANDIDATES if not only or only in c[0]]
    print(f"核验 {len(targets)} 个候选源\n")

    sem = asyncio.Semaphore(8)

    async def guarded(client, label, url, kind):
        async with sem:
            return await check(client, label, url, kind)

    # 45s, not 30s. Several hosts here are legitimately slow rather than down: measured
    # `hex2077.dev/rss.xml` at 20.5s for 255KB and `wechat2rss.xlab.app` at 10.7s for 173KB.
    # A short timeout turned both into "unreachable", which is a measurement error that
    # would have led to dropping working sources.
    async with httpx.AsyncClient(timeout=45, http2=False) as client:
        records = await asyncio.gather(
            *(guarded(client, label, url, kind) for label, url, kind in targets)
        )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(records, ensure_ascii=False, indent=1), encoding="utf-8")

    usable = [r for r in records if r.get("usable")]
    ai_ok = [r for r in usable if r.get("is_ai")]
    print(f"{'状态':<10}{'条目':>5}{'AI':>4}  源")
    for r in records:
        if r.get("usable"):
            state = "✅ 可用" if r.get("is_ai") else "⚠️ 非AI"
            n = r.get("entries", 0)
        elif r.get("status") == 200:
            state = "⚠️ 非feed"
            n = 0
        else:
            state = f"❌ {r.get('status') or r.get('error','')[:18]}"
            n = 0
        print(f"{state:<10}{n:>5}{r.get('ai_hits', 0):>4}  {r['label'][:44]}")

    print()
    print(f"  可用 feed {len(usable)} · 其中与 AI 相关 {len(ai_ok)}")
    print(f"  明细: {OUT.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
