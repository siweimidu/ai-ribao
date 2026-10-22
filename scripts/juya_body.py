import io, sys, re, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
raw = urllib.request.urlopen(urllib.request.Request("https://daily.juya.uk/rss.xml", headers=UA), timeout=60).read()
p = feedparser.parse(raw)
e = p.entries[0]
c = e.get("content", [{}])[0].get("value", "")
print("  entry title: %s" % e.get("title"))
print("  content 长度: %d" % len(c))
print()
print("  === content 开头 2500 字符 ===")
print(c[:2500])