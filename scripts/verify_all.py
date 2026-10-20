import io, re, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

v = int(time.time())
base = "https://siweimidu.github.io/ai-ribao/"

def get(u):
    r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
    return urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")

# 1) item labels on the 10-20 page
h = get(base + "2026-10-20.html?v=%d" % v)
i = h.find('class="item"')
t = re.sub(r"<[^>]+>", "\n", h[i:i + 600])
lines = [x.strip() for x in t.splitlines() if x.strip()][:7]
print("  1) 条目标签：")
for x in lines:
    print("     " + x[:60])
print()

# 2) footer
m = re.search(r"<p>生成于[^<]*</p>", h)
print("  2) 页脚： %s" % (m.group(0) if m else "(未找到)"))
print()

# 3) RSS pubDate
xml = get(base + "feed/zh.xml?v=%d" % v)
stamps = re.findall(r"<pubDate>(.*?)</pubDate>", xml)[:2]
print("  3) RSS pubDate：")
for s in stamps:
    print("     %s" % s)

from email.utils import parsedate_to_datetime
if stamps:
    p = parsedate_to_datetime(stamps[0])
    print("     解析后 UTC: %s" % p.astimezone(__import__("datetime").timezone.utc).isoformat())