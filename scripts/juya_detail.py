import io, sys, re, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
import feedparser

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
raw = urllib.request.urlopen(urllib.request.Request("https://daily.juya.uk/rss.xml", headers=UA), timeout=60).read()
p = feedparser.parse(raw)
c = p.entries[0].get("content", [{}])[0].get("value", "")

# headings give the section structure
print("  === 所有 h2/h3 ===")
for m in re.finditer(r"<h([23])[^>]*>(.*?)</h\1>", c):
    print("    h%s: %s" % (m.group(1), re.sub(r"<[^>]+>", "", m.group(2)).strip()[:40]))

print()
print("  === 正文详情区（#1 附近）===")
i = c.find(">#1<")
j = c.find(">#2<")
k = c.find("id=\"s", j) if j > 0 else -1
seg = c[i:i+2200] if i > 0 else c[:1200]
print(seg[:2200])