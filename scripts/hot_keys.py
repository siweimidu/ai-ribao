import io, sys, re, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = urllib.request.urlopen(urllib.request.Request("https://aihot.news/hot", headers=UA), timeout=45).read().decode("utf-8", "replace")

# Look for event-like JSON keys
for key in ("eventId", "event_id", "heatValue", "independentSources", "sourceCount", "trend", "rank"):
    n = len(re.findall(key, h))
    if n:
        i = h.find(key)
        print("  %-22s %3d  ctx=%s" % (key, n, " ".join(h[max(0,i-120):i+120].split())[:200]))
        print()