import io, re, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0"}
v = int(time.time())
url = "https://siweimidu.github.io/ai-ribao/2026-10-18.html?v=%d" % v
h = urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40).read().decode("utf-8", "replace")
print("  页面大小: %d bytes" % len(h))
print("  含 toc: %s" % ("toc__nav" in h))
print("  含橘鸦: %s" % ("橘鸦" in h))
m = re.search(r'href="([^"]*components\.css[^"]*)"', h)
print("  CSS: %s" % (m.group(1) if m else "?"))