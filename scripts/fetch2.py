import io, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")

def text_of(h):
    t = re.sub(r"<script[\s\S]*?</script>", " ", h)
    t = re.sub(r"<style[\s\S]*?</style>", " ", t)
    t = re.sub(r"<[^>]+>", "\n", t)
    return [x.strip() for x in t.splitlines() if x.strip()]

for url in ("https://aihot.news/tibo", "https://aihot.news/about", "https://aihot.news/models"):
    try:
        h = get(url)
    except Exception as e:
        print("  %s ERROR %s" % (url, e))
        continue
    lines = text_of(h)
    print("=== %s  (%d bytes, %d 行) ===" % (url, len(h), len(lines)))
    for x in lines[:55]:
        print("  " + x[:96])
    print()