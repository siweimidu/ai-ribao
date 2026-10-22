import io, sys, re, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = urllib.request.urlopen(urllib.request.Request("https://aihot.news/hot", headers=UA), timeout=45).read().decode("utf-8", "replace")

for m in list(re.finditer("热度", h))[:3]:
    s = max(0, m.start() - 300)
    seg = h[s:m.start() + 40]
    print("  ---")
    print("  %s" % " ".join(seg.split())[:340])
    print()