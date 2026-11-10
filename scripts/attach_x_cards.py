"""把 X 卡片挂到对应的那条消息上。

不是另起一个「X 精选」栏位 —— 读者看到「Anthropic 发布 Fable 5.2 与 Mythos 5.2」这条，
推文图就应该长在这条下面。所以这里做的是**匹配并写入 unique_facts**，渲染层照原样贴进条目。

匹配只用两个强信号：**带数字的产品名**（Fable 5.2 / TPU 8i / GPT-6.2）和**作者名**。
普通词重叠会把几条相关的推文都引到同一篇报道上 —— 实测过，两张卡都挂到了同一条「魔方」新闻。
一条事件最多挂一张卡，分数并列时宁可不挂。
"""

from __future__ import annotations

import io
import json
import re
import sys
from pathlib import Path

sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

DAY = sys.argv[1] if len(sys.argv) > 1 else "2026-11-10"
DIGEST = Path(f"data/digests/{DAY}.json")
STATE = Path("data/state/x-highlights.json")
ASSETS = Path("data/digests/site/assets/x")

#: 带数字的产品名：Fable 5.2 / TPU 8i / GPT-6.2。
_PRODUCT = re.compile(r"[A-Za-z][A-Za-z0-9.\-]{1,20}\s?\d+(?:\.\d+)?")

#: 低于这个分数不挂。宁可缺一张图，也不要把推文贴到不相干的消息上。
MIN_SCORE = 5


def products(text: str) -> set[str]:
    return {m.group(0).lower().replace(" ", "") for m in _PRODUCT.finditer(text or "")}


def event_text(event: dict) -> str:
    facts = event.get("unique_facts") or {}
    body = " ".join(str(v) for values in facts.values() for v in (values or []))
    return f"{event.get('title') or ''} {body}"


def main() -> None:
    if not DIGEST.exists() or not STATE.exists():
        print("  缺少输入:", DIGEST, STATE)
        return
    digest = json.loads(DIGEST.read_text(encoding="utf-8"))
    events = digest["digest"]["top_events"]
    cards = json.loads(STATE.read_text(encoding="utf-8"))
    print(f"  卡片 {len(cards)} 张，事件 {len(events)} 条")

    taken: set[int] = set()
    attached = 0
    for card in cards:
        said = f"{card.get('author', '')} {card.get('text', '')} {card.get('translated', '')}"
        want = products(said)
        first = (str(card.get("author") or "").split() or [""])[0].lower()
        scored: list[tuple[int, int]] = []
        for index, event in enumerate(events):
            if index in taken:
                continue
            text = event_text(event)
            score = len(want & products(text)) * 5
            if first and first in text.lower():
                score += 3
            if score:
                scored.append((score, index))
        scored.sort(reverse=True)
        if not scored or scored[0][0] < MIN_SCORE:
            print("  跳过（没有足够相似的条目）:", card.get("author"), scored[:1])
            continue
        if len(scored) > 1 and scored[0][0] == scored[1][0]:
            print("  跳过（分数并列，不确定是哪条）:", card.get("author"))
            continue
        score, index = scored[0]
        taken.add(index)
        event = events[index]
        facts = event.get("unique_facts") or {}
        # 文件名就是推文 id，内容换了文件名不变，浏览器会一直用缓存里那张旧图
        # （实测：卡片已换成单页，线上还在显示旧的跨页版）。加内容指纹强制刷新。
        image = ASSETS / str(card.get("image") or "")
        stamp = image.stat().st_size if image.exists() else 0
        facts["x_card"] = [f"{card.get('image')}?v={stamp}"]
        facts["x_url"] = [card.get("url") or ""]
        facts["x_author"] = [card.get("author") or ""]
        event["unique_facts"] = facts
        attached += 1
        print(
            "  %-18s -> #%03d %s（分数 %d）"
            % (str(card.get("author"))[:18], index + 1, (event.get("title") or "")[:32], score)
        )

    DIGEST.write_text(json.dumps(digest, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"  已挂上 {attached} 张卡片 -> {DIGEST.name}")


main()
