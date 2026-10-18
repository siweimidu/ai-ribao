import io, re, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
v = int(time.time())
u = "https://siweimidu.github.io/ai-ribao/2026-10-17.html?v=%d" % v
r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
h = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")
ts = [re.sub(r"<[^>]+>", "", x).strip()
      for x in re.findall(r'class="item__title"><a[^>]*>(.*?)</a>', h, re.S)]
print("线上 2026-10-17 前 6 条：")
for i, t in enumerate(ts[:6], 1):
    print("  %d. %s" % (i, t[:58]))
print()
print("总条数: %d" % len(ts))