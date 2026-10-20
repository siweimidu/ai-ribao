import io, re, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

v = int(time.time())
u = "https://siweimidu.github.io/ai-ribao/2026-10-20.html?v=%d" % v
r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
h = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")

i = h.find('class="item"')
seg = h[i:i + 600]
t = re.sub(r"<[^>]+>", "\n", seg)
lines = [x.strip() for x in t.splitlines() if x.strip()][:8]
print("  线上 2026-10-20 第一个条目：")
for x in lines:
    print("    " + x[:70])
print()
stray = re.findall(r"<span>\d{2}-\d{2} \d{2}:\d{2} UTC</span>", h)
print("  条目标签里残留 UTC: %d 处" % len(stray))