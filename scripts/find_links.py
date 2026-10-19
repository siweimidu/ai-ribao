import io, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
def get(url):
    req = urllib.request.Request(url, headers=UA)
    return urllib.request.urlopen(req, timeout=40).read().decode("utf-8", "replace")

h = get("https://aihot.news/about")
links = sorted(set(re.findall(r'href="(/[^"#?]*)"', h)))
print("  about 页内的站内链接：")
for l in links:
    print("    " + l)

# also grab the nav from the homepage to find the tibo path
h2 = get("https://aihot.news/")
nav = sorted(set(re.findall(r'href="(/[^"#?]*)"', h2)))
print()
print("  首页站内链接（前 40）：")
for l in nav[:40]:
    print("    " + l)