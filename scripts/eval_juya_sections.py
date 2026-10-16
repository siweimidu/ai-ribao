"""How well does the classifier reproduce 橘鸦's own section assignment?

This is the only measurement that matters for the claim "the ordering is close": the section is
the primary sort key, so classification accuracy *is* ordering accuracy at the coarse level.

Reports overall accuracy, a confusion matrix, and the specific mistakes -- because the failures
are the boundary decisions, and they are what would need a model rather than rules.
"""

from __future__ import annotations

import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aidaily.collect import read_items_jsonl  # noqa: E402
from aidaily.sections import SECTIONS, classify, rank_of  # noqa: E402

HEADLINE = re.compile(r"^(?P<title>.+?)\s*(?:↗|→|»)?\s*#(?P<n>\d{1,3})\s*$", re.M)
SECTION = re.compile(
    r"^(要闻|概览|模型发布|开发生态|产品应用|技术与洞察|行业动态|研究|政策|其他|"
    r"今日要闻|新闻|资讯|快讯|产品|技术)$"
)


def parse(body: str) -> list[tuple[int, str, str]]:
    out: list[tuple[int, str, str]] = []
    section = "(无栏目)"
    for raw_line in body.splitlines():
        line = raw_line.strip().lstrip("-*• \t")
        if not line:
            continue
        if SECTION.match(line):
            section = line
            continue
        m = HEADLINE.match(line)
        if m:
            out.append((int(m.group("n")), section, m.group("title").strip()))
    return out


def main() -> int:
    items = read_items_jsonl("data/raw/items.jsonl")
    juya = [i for i in items if i.source_id == "rss:daily-juya-uk"]

    pairs: list[tuple[str, str, str]] = []          # (true, predicted, title)
    for item in juya:
        rows = sorted(parse(item.content_text or ""), key=lambda r: r[0])
        if len(rows) < 8:
            continue
        for _, truth, title in rows:
            if truth == "(无栏目)":
                continue
            pairs.append((truth, classify(title), title))

    if not pairs:
        print("没有可评估的数据")
        return 1

    correct = sum(1 for t, p, _ in pairs if t == p)
    print(f"样本 {len(pairs)} 条，分类正确 {correct} 条 —— 准确率 {correct / len(pairs):.1%}\n")

    print("混淆矩阵（行=橘鸦实际，列=本分类器）")
    preds = list(SECTIONS)
    print(f"{'':<10}" + "".join(f"{p[:4]:>7}" for p in preds))
    conf: dict[tuple[str, str], int] = Counter()
    for t, p, _ in pairs:
        conf[(t, p)] += 1
    for truth in SECTIONS:
        row = [conf.get((truth, p), 0) for p in preds]
        if not any(row):
            continue
        print(f"{truth:<10}" + "".join(f"{v or '':>7}" for v in row))

    print("\n按栏目统计")
    for truth in SECTIONS:
        rows = [(p, t) for tt, p, t in pairs if tt == truth]
        if not rows:
            continue
        ok = sum(1 for p, _ in rows if p == truth)
        print(f"  {truth:<8} {ok:3}/{len(rows):3}  {ok / len(rows):>5.0%}")

    print("\n错误样本（最多 18 条）")
    wrong = [(t, p, title) for t, p, title in pairs if t != p]
    for truth, pred, title in wrong[:18]:
        print(f"  实际 {truth:<8} 判为 {pred:<8} {title[:56]}")

    # The ordering consequence: fraction of pairs whose relative order is preserved.
    import random
    random.seed(0)
    sample = random.sample(pairs, min(600, len(pairs)))
    agree = total = 0
    for i in range(len(sample)):
        for j in range(i + 1, len(sample)):
            t1, p1, _ = sample[i]
            t2, p2, _ = sample[j]
            if rank_of(t1) == rank_of(t2):
                continue
            total += 1
            a = rank_of(p1) < rank_of(p2)
            b = rank_of(t1) < rank_of(t2)
            if a == b:
                agree += 1
    if total:
        print(f"\n两两顺序一致率（分类结果 vs 橘鸦实际）: {agree / total:.1%}  ({total} 组)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
