import io, sys, re, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = ""
for _ in range(3):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://dailydawn.dev/zh/2026-10-22", headers=UA), timeout=45).read().decode("utf-8", "replace")
        break
    except Exception as e:
        print("  retry %s" % str(e)[:36]); time.sleep(2)

print("  bytes=%d" % len(h))
print()
# Find the story sections: each has a numbered heading and a body with links.
for pat in (r'<h2[^>]*>([\s\S]{0,120}?)</h2>', r'<h3[^>]*>([\s\S]{0,90}?)</h3>'):
    ms = re.findall(pat, h)
    print("  %s -> %d" % (pat[:22], len(ms)))
    for m in ms[:6]:
        print("      %s" % " ".join(re.sub(r"<[^>]+>", " ", m).split())[:70])
    print()

links = re.findall(r'href="(https?://[^"]+)"', h)
ext = [u for u in links if "dailydawn.dev" not in u]
print("  外部链接 %d 个，前 6:" % len(ext))
for u in ext[:6]:
    print("    %s" % u[:78])