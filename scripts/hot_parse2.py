import io, sys, re, json, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

raw_path = r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html"
h = None
for attempt in range(4):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://aihot.news/hot", headers=UA), timeout=60).read().decode("utf-8", "replace")
        break
    except Exception as e:
        print("  attempt %d failed: %s" % (attempt + 1, str(e)[:44]))
        time.sleep(3)
if not h:
    h = open(raw_path, encoding="utf-8").read()
    print("  用缓存")
else:
    open(raw_path, "w", encoding="utf-8").write(h)

pat = re.compile(r'"rank":(\d+).{0,500}?"heat":([0-9.]+),"trend":"(\w+)","trendPct":([0-9.\-]+).{0,500}?"participantCount":(\d+),"sourceCount":(\d+)', re.S)
rows = pat.findall(h)
print("  解析到 %d 条热点" % len(rows))
for rank, heat, trend, pct, part, src in rows:
    print("    NO.%-3s heat=%-7s %-6s pct=%-6s 参与者=%-3s 来源=%s" % (rank, heat, trend, pct, part, src))