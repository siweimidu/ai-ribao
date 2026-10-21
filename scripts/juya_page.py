import io, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read().decode("utf-8", "replace")

# Find today's issue page
idx = get("https://daily.juya.uk/")
links = re.findall(r'href="(/[^"]*2026-10-21[^"]*)"', idx)
print("  首页指向 10-21 的链接: %s" % links[:4])
if not links:
    links = re.findall(r'href="(/[^"#?]+)"', idx)[:12]
    print("  首页链接样例: %s" % links)

if links:
    url = "https://daily.juya.uk" + links[0]
    print()
    print("  抓取 %s" % url)
    page = get(url)
    txt = re.sub(r"<script[\s\S]*?</script>", " ", page)
    txt = re.sub(r"<style[\s\S]*?</style>", " ", txt)
    txt = re.sub(r"<[^>]+>", "\n", txt)
    lines = [l.strip() for l in txt.splitlines() if l.strip()]
    print("  %d 行，前 30 行：" % len(lines))
    for l in lines[:30]:
        print("    %s" % l[:82])