import io, re, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
v = int(time.time())
base = "https://siweimidu.github.io/ai-ribao/"
for date in ("2026-10-16", "2026-10-17", "2026-10-18"):
    r = urllib.request.Request("%s%s.html?v=%d" % (base, date, v), headers={"User-Agent": "Mozilla/5.0"})
    h = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")
    titles = [re.sub(r"<[^>]+>", "", t).strip()
              for t in re.findall(r'class="item__title"><a[^>]*>(.*?)</a>', h, re.S)]
    gem = [t for t in titles if "gemini" in t.lower()]
    print("  %s  共 %d 条，Gemini %d 条" % (date, len(titles), len(gem)))
    for t in gem:
        print("      %s" % t[:56])