import io, sys, time, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
raw = b""
for _ in range(3):
    try:
        raw = urllib.request.urlopen(urllib.request.Request("https://dailydawn.dev/feed.xml", headers=UA), timeout=45).read()
        break
    except Exception as e:
        print("  retry %s" % str(e)[:40]); time.sleep(2)

p = feedparser.parse(raw)
print("  entries=%d" % len(p.entries))
e = p.entries[0]
print("  title: %s" % (e.get("title") or "")[:70])
print("  link : %s" % (e.get("link") or ""))
print("  keys : %s" % sorted(e.keys()))
body = e.get("content", [{}])[0].get("value", "") if e.get("content") else ""
print("  content: %d chars | %s" % (len(body), " ".join(body.split())[:400]))
print("  summary: %s" % (e.get("summary") or "")[:300])