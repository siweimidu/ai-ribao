import io, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

v = int(time.time())
u = "https://siweimidu.github.io/ai-ribao/assets/motion.js?v=%d" % v
r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
js = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")
print("  motion.js 大小: %d bytes" % len(js))
print("  含 nowLocal（实时计算）: %s" % ("const nowLocal = new Date();" in js))
print("  含 data.today（写死值）  : %s" % ("const today = data.today;" in js))