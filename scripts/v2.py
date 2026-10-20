import io, json, re, sys, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

v = int(time.time())
u = "https://siweimidu.github.io/ai-ribao/index.html?v=%d" % v
r = urllib.request.Request(u, headers={"User-Agent": "Mozilla/5.0"})
h = urllib.request.urlopen(r, timeout=30).read().decode("utf-8", "replace")

m = re.search(r'id="calendar-data">(.*?)</script>', h, re.S)
d = json.loads(m.group(1)) if m else {}
print("  线上 today = %s" % d.get("today"))
print("  线上 dates = %s" % d.get("dates"))
print()
print("  前端用实时日期: %s" % ("const nowLocal = new Date();" in h or "nowLocal" in h))