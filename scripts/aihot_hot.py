import io, sys, re, json, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = urllib.request.urlopen(urllib.request.Request("https://aihot.news/hot", headers=UA), timeout=45).read().decode("utf-8", "replace")
print("  bytes=%d" % len(h))

for pat in (r'"heat":\s*(\d+)', r'"score":\s*(\d+)', r'热度', r'"hot"'):
    print("    %-24s %d" % (pat[:22], len(re.findall(pat, h))))

apis = sorted(set(re.findall(r'"(/api/[^"]+)"', h)))
print("  API 端点: %s" % apis[:10])

# Where does the hot list live in the markup?
txt = re.sub(r"<script[\s\S]*?</script>", " ", h)
txt = re.sub(r"<[^>]+>", "\n", txt)
lines = [x.strip() for x in txt.splitlines() if x.strip()]
start = next((i for i, x in enumerate(lines) if "热度" in x), 0)
print()
print("  === 热度附近 30 行 ===")
for x in lines[max(0, start - 12):start + 22]:
    print("    %s" % x[:80])