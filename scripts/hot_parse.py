import io, sys, re, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = urllib.request.urlopen(urllib.request.Request("https://aihot.news/hot", headers=UA), timeout=45).read().decode("utf-8", "replace")

# Each hot entry has rank/heat/trendPct/participantCount/sourceCount near each other.
pat = re.compile(r'"rank":(\d+).{0,400}?"heat":([0-9.]+),"trend":"(\w+)","trendPct":([0-9.\-]+).{0,400}?"participantCount":(\d+),"sourceCount":(\d+)', re.S)
rows = pat.findall(h)
print("  解析到 %d 条热点" % len(rows))
for rank, heat, trend, pct, part, src in rows:
    print("    NO.%-3s heat=%-6s %-6s pct=%-5s 参与者=%-3s 来源=%s" % (rank, heat, trend, pct, part, src))

print()
# The story title is nearby too; try to pull it.
for m in list(pat.finditer(h))[:3]:
    seg = h[max(0, m.start() - 700):m.start()]
    titles = re.findall(r'"(?:title|headline)":"([^"]{8,90})"', seg)
    print("  rank %s 附近标题: %s" % (m.group(1), titles[-2:] if titles else "无"))