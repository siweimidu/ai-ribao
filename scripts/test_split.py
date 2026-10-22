import io, sys, time, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser
from aidaily.digest_split import split_digest

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
raw = None
for _ in range(3):
    try:
        raw = urllib.request.urlopen(urllib.request.Request("https://daily.juya.uk/rss.xml", headers=UA), timeout=60).read()
        break
    except Exception as e:
        print("  retry: %s" % str(e)[:40]); time.sleep(3)

p = feedparser.parse(raw)
e = p.entries[0]
body = e.get("content", [{}])[0].get("value", "")
print("  entry: %s" % e.get("title"))
print("  body : %d chars" % len(body))

stories = split_digest(body)
print("  拆出 %d 条" % len(stories))
print()
for s in stories[:8]:
    print("  [%s] %s" % (s.section, s.title[:52]))
    print("      %s" % s.url[:76])