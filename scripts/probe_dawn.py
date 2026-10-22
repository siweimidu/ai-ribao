import io, sys, time, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36",
      "Accept": "application/rss+xml, application/xml;q=0.9, */*;q=0.8"}

def get(url, tries=3):
    for i in range(tries):
        try:
            return urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=45).read()
        except Exception as e:
            print("    retry%d %s" % (i + 1, str(e)[:44]))
            time.sleep(2)
    return b""

print("  === dailydawn ===")
raw = get("https://dailydawn.dev/feed.xml")
if raw:
    p = feedparser.parse(raw)
    print("    bytes=%d entries=%d" % (len(raw), len(p.entries or [])))
    for e in (p.entries or [])[:3]:
        body = e.get("content", [{}])[0].get("value", "") if e.get("content") else (e.get("summary") or "")
        print("    title: %s" % (e.get("title") or "")[:60])
        print("    link : %s" % (e.get("link") or "")[:64])
        print("    body : %d chars | %s" % (len(body), " ".join(body.split())[:100]))
        print()

print("  === aihot /hot 重试 ===")
r = get("https://aihot.news/hot", tries=2)
print("    bytes=%d  head=%s" % (len(r), r[:90]))