"""What decides the order *within* a section?

The section analysis settled the coarse structure: 橘鸦 orders by section, with a partial order
that never inverts. Within a section there are often 10-15 stories, so something still decides
their order, and that is the only place a score could live.

This measures candidate signals against the observed within-section rank, using rank
correlation rather than eyeballing:

* **title length** -- a terse headline is usually a shipped thing, a long one an explainer;
* **first-party** -- does the headline name a lab that ships models (OpenAI, Anthropic, Google,
  Meta, DeepSeek, Qwen, …), as opposed to a third party discussing one;
* **release verb** -- 发布/推出/上线/开放/开源 versus 分析/报告/认为/称;
* **a number in the title** -- versions, parameter counts, prices;
* **CJK vs latin** -- an original-language source versus a translated digest;
* **source domain** -- whether juya cited the vendor's own site or a news outlet.

Spearman against the within-section rank, per section, then pooled. A signal that is real shows
a consistent sign across sections; one that is noise flips.
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from aidaily.collect import read_items_jsonl  # noqa: E402

HEADLINE = re.compile(r"^(?P<title>.+?)\s*(?:↗|→|»)?\s*#(?P<n>\d{1,3})\s*$", re.M)
SECTION = re.compile(
    r"^(要闻|概览|模型发布|开发生态|产品应用|技术与洞察|行业动态|研究|政策|其他|"
    r"今日要闻|新闻|资讯|快讯|产品|技术)$"
)

LABS = re.compile(
    r"(?<![a-z])(openai|anthropic|google|deepmind|meta|microsoft|nvidia|apple|amazon|"
    r"deepseek|qwen|alibaba|moonshot|kimi|zhipu|glm|minimax|stepfun|bytedance|baidu|"
    r"mistral|cohere|stability|hugging ?face|xai|grok)(?![a-z])|"
    r"阿里|腾讯|字节|百度|华为|智谱|月之暗面|阶跃星辰|面壁|零一万物|蚂蚁|昆仑万维",
    re.I,
)
RELEASE = re.compile(
    r"发布|推出|上线|开放|开源|宣布|正式|内测|公测|发售|可用|"
    r"releas|launch|ship|announc|open-?source|available|unveil",
    re.I,
)
SOFT = re.compile(
    r"分析|报告|认为|称|指出|研究|实测|体验|评测|质疑|争议|回应|"
    r"report|analys|argues?|opinion|review|test|claim",
    re.I,
)
NUMBER = re.compile(r"\d")

CJK = re.compile(r"[\u4e00-\u9fff]")


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


def spearman(pairs: list[tuple[float, float]]) -> float:
    """Rank correlation with average ranks for ties. Returns 0.0 for a degenerate input."""
    if len(pairs) < 4:
        return 0.0

    def ranks(values: list[float]) -> list[float]:
        order = sorted(range(len(values)), key=lambda i: values[i])
        out = [0.0] * len(values)
        i = 0
        while i < len(order):
            j = i
            while j + 1 < len(order) and values[order[j + 1]] == values[order[i]]:
                j += 1
            avg = (i + j) / 2 + 1
            for k in range(i, j + 1):
                out[order[k]] = avg
            i = j + 1
        return out

    xs = ranks([p[0] for p in pairs])
    ys = ranks([p[1] for p in pairs])
    n = len(xs)
    mx, my = sum(xs) / n, sum(ys) / n
    num = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = sum((x - mx) ** 2 for x in xs) ** 0.5
    dy = sum((y - my) ** 2 for y in ys) ** 0.5
    return num / (dx * dy) if dx and dy else 0.0


FEATURES = {
    "标题长度": lambda t: float(len(t)),
    "含大厂名": lambda t: 1.0 if LABS.search(t) else 0.0,
    "含发布动词": lambda t: 1.0 if RELEASE.search(t) else 0.0,
    "含分析动词": lambda t: 1.0 if SOFT.search(t) else 0.0,
    "含数字": lambda t: 1.0 if NUMBER.search(t) else 0.0,
    "含中文": lambda t: 1.0 if CJK.search(t) else 0.0,
}


def main() -> int:
    items = read_items_jsonl("data/raw/items.jsonl")
    juya = [i for i in items if i.source_id == "rss:daily-juya-uk"]

    # (section -> list of (within-section position, title))
    per_section: dict[str, list[tuple[int, str]]] = defaultdict(list)
    for item in juya:
        rows = sorted(parse(item.content_text or ""), key=lambda r: r[0])
        if len(rows) < 8:
            continue
        counter: Counter[str] = defaultdict(int)  # type: ignore[name-defined]
        for _, section, title in rows:
            counter[section] += 1
            per_section[section].append((counter[section], title))

    print("栏目内部：位置 vs 特征 的 Spearman 相关（负 = 越靠前越多）\n")
    header = f"{'栏目':<10}{'条数':>5}" + "".join(f"{k:>11}" for k in FEATURES)
    print(header)
    for section in sorted(per_section, key=lambda s: -len(per_section[s])):
        rows = per_section[section]
        if len(rows) < 5:
            continue
        cells = []
        for fn in FEATURES.values():
            cells.append(spearman([(float(pos), fn(t)) for pos, t in rows]))
        line = f"{section:<10}{len(rows):>5}" + "".join(f"{c:>11.2f}" for c in cells)
        print(line)

    print("\n合并（所有栏目一起，位置已按栏目内序号）")
    pooled = [(float(p), t) for rows in per_section.values() for p, t in rows]
    for name, fn in FEATURES.items():
        print(f"    {name:<10} {spearman([(a, fn(t)) for a, t in pooled]):>6.2f}")

    print("\n各栏目首条 vs 末条的特征占比")
    for section, rows in sorted(per_section.items(), key=lambda kv: -len(kv[1])):
        if len(rows) < 5:
            continue
        first, last = rows[0][1], rows[-1][1]
        print(f"  {section}")
        for name, fn in FEATURES.items():
            print(f"      {name:<8} 首={fn(first):.0f} 末={fn(last):.0f}   首条: {first[:44]}")
            break
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
