import io, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")

for url in ("https://aihot.news/daily", "https://aihot.news/"):
    try:
        h = get(url)
    except Exception as e:
        print("  %s ERROR %s" % (url, e))
        continue
    print("=== %s  (%d bytes) ===" % (url, len(h)))
    t = re.sub(r"<script[\s\S]*?</script>", " ", h)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", "\n", t)
    lines = [x.strip() for x in t.splitlines() if x.strip()]
    for x in lines[:70]:
        print("  " + x[:100])
    print()