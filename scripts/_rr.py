import io, json, sys
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
d = json.loads(open("data/digests/2026-10-24.json", encoding="utf-8").read())
ev = d["digest"]["top_events"]
n = sum(1 for e in ev if (e.get("unique_facts") or {}).get("merged_titles"))
print("  events=%d  with merged_titles=%d" % (len(ev), n))
kimi = [e for e in ev if "kimi" in (e.get("title") or "").lower() or "3万亿" in (e.get("title") or "")]
print("  Kimi entries: %d" % len(kimi))
for k in kimi:
    print("   #%02d %s" % (ev.index(k)+1, (k.get("title") or "")[:50]))
