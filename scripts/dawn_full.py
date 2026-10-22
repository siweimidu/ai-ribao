from pathlib import Path
import yaml

# dailydawn publishes a 30-40 character teaser per issue and the real analysis on the page.
# Without the body, every dailydawn story scores as "no substance" and sinks regardless of merit.
TARGETS = ("rss:dailydawn-feed-xml",)

p = Path("sources/local.yaml")
doc = yaml.safe_load(p.read_text(encoding="utf-8"))
srcs = doc.get("sources") or doc

n = 0
for s in srcs:
    if s.get("source_id") in TARGETS:
        s["site_fulltext"] = True
        notes = s.get("notes") or ""
        if "fulltext" not in notes:
            s["notes"] = (notes + "；RSS 只给 30-40 字摘要，正文在页面，开 site_fulltext 抓取。").strip("；")
        n += 1
        print("  enabled for %s" % s.get("source_id"))

if n:
    doc["sources"] = srcs
    p.write_text(yaml.safe_dump(doc, allow_unicode=True, sort_keys=False), encoding="utf-8")
else:
    print("  none matched; checking registry")
    for name in ("sources/registry.yaml",):
        d = yaml.safe_load(Path(name).read_text(encoding="utf-8"))
        for s in (d.get("sources") or d):
            if "dailydawn" in (s.get("url") or ""):
                print("    %s site_fulltext=%s" % (s.get("source_id"), s.get("site_fulltext")))