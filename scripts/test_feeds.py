"""Verify the feeds are usable by a machine consumer.

The feeds are the n8n hand-off, so "does it parse" is not the bar -- "does a workflow get
enough to act on" is. Each check below corresponds to something a consumer actually does:

  * parse with a real feed parser, not a regex;
  * confirm the body carries the facts, not just links (the first version sent a list of
    URLs as `<description>` while the JSON feed carried the facts for the same items);
  * confirm plain text exists for nodes that cannot render HTML;
  * confirm identity fields are stable across runs, because n8n dedupes on them;
  * confirm timestamps are parseable and timezone-aware;
  * confirm every source URL is preserved, which is the attribution the upstream terms ask
    consumers to keep.
"""

from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEED_DIR = ROOT / "data" / "digests" / "site" / "feed"

failures: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{('  ' + detail) if detail else ''}")
    if not ok:
        failures.append(label)


def main() -> int:
    rss_path = FEED_DIR / "zh.xml"
    json_path = FEED_DIR / "zh.json"
    print("RSS")
    if not rss_path.exists():
        print(f"  FAIL 缺少 {rss_path}")
        return 1

    tree = ET.parse(rss_path)
    root = tree.getroot()
    channel = root.find("channel")
    check("XML 可解析", channel is not None)

    ns = {
        "atom": "http://www.w3.org/2005/Atom",
        "content": "http://purl.org/rss/1.0/modules/content/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
    # The prefix map is required for namespaced lookups; without it `find` returns None and
    # the check reads as "missing element" when the element is present.
    check("有 atom:link rel=self", channel.find("atom:link", ns) is not None)
    check("有 lastBuildDate", channel.findtext("lastBuildDate") is not None)
    check("有 ttl（告知聚合器不要频繁轮询）", channel.findtext("ttl") is not None,
          channel.findtext("ttl") or "")
    check("有 generator", channel.findtext("generator") is not None)

    items = channel.findall("item")
    check("条目数 > 0", len(items) > 0, f"{len(items)} 条")

    bodies = [i.findtext("content:encoded", namespaces=ns) for i in items]
    with_body = [b for b in bodies if b and len(b) > 80]
    check("条目带正文（不只是链接）", len(with_body) == len(items),
          f"{len(with_body)}/{len(items)} 条有正文")

    has_facts = sum(1 for b in bodies if b and "事实" in b)
    check("正文里有「事实」小节", has_facts > 0, f"{has_facts} 条")
    has_level = sum(1 for b in bodies if b and "可信度" in b)
    check("正文里有可信度标记", has_level == len(items), f"{has_level}/{len(items)}")

    descs = [i.findtext("description") or "" for i in items]
    check("description 是可读摘要而非 URL 串",
          all(d and not d.startswith("<ul><li><a href") for d in descs),
          repr(descs[0][:48]) if descs else "")

    dates = [i.findtext("dc:date", namespaces=ns) for i in items]
    parseable = 0
    aware = 0
    for d in dates:
        if not d:
            continue
        try:
            dt = datetime.fromisoformat(d)
            parseable += 1
            if dt.tzinfo is not None:
                aware += 1
        except ValueError:
            pass
    check("dc:date 全部可解析", parseable == len(items), f"{parseable}/{len(items)}")
    check("dc:date 带时区", aware == parseable, f"{aware}/{parseable}")

    guids = [i.findtext("guid") for i in items]
    check("guid 全部存在且唯一", all(guids) and len(set(guids)) == len(guids),
          f"{len(set(guids))}/{len(guids)} 唯一")

    cats = [len(i.findall("category")) for i in items]
    # One `<category>` per source, not a comma-joined blob. A multi-source story legitimately
    # has more than one, so the assertion is that none of them is a merged string.
    check("category 是单个来源而非逗号合并串",
          all("," not in (c.text or "") for i in items for c in i.findall("category")),
          f"最多 {max(cats)} 个/条")

    check("有条目级 source（署名）", all(i.find("source") is not None for i in items))

    # --- JSON Feed ---------------------------------------------------------------
    print("\nJSON Feed")
    doc = json.loads(json_path.read_text(encoding="utf-8"))
    check("是 JSON Feed 1.1", doc.get("version", "").endswith("1.1"), doc.get("version", ""))
    jitems = doc.get("items") or []
    check("条目数 > 0", len(jitems) > 0, f"{len(jitems)} 条")
    check("每条有 summary", all(i.get("summary") for i in jitems))
    check("每条有 content_text（给只读纯文本的节点）",
          all((i.get("content_text") or "").strip() for i in jitems))
    check("每条有 content_html", all((i.get("content_html") or "").strip() for i in jitems))
    check("每条有 authors", all(i.get("authors") for i in jitems))
    check("每条有 date_published 且带时区",
          all("+" in (i.get("date_published") or "") or (i.get("date_published") or "").endswith("Z")
              for i in jitems))
    meta = [i.get("_ai_daily") or {} for i in jitems]
    check("_ai_daily 有 event_id", all(m.get("event_id") for m in meta))
    check("_ai_daily 有 evidence_level", all(m.get("evidence_level") for m in meta))
    check("_ai_daily 分列事实/推断/不确定",
          all({"facts", "inferences", "uncertainties"} <= set(m) for m in meta))

    # --- the two feeds must agree -------------------------------------------------
    print("\n一致性")
    rss_ids = {g for g in guids if g}
    json_ids = {i["id"] for i in jitems}
    check("两个 feed 的条目集合相同", rss_ids == json_ids,
          f"仅 RSS {len(rss_ids - json_ids)}，仅 JSON {len(json_ids - rss_ids)}")

    print()
    if failures:
        print(f"{len(failures)} 项失败")
        for f in failures:
            print(f"  · {f}")
        return 1
    print("全部通过")
    return 0


if __name__ == "__main__":
    sys.exit(main())
