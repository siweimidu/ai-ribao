import io, sys, re, time, urllib.request
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.fulltext import extract_body
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = b""
for _ in range(3):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://dailydawn.dev/zh/2026-10-22", headers=UA), timeout=45).read()
        break
    except Exception:
        time.sleep(2)

print("  bytes=%d" % len(h))
body = extract_body(h.decode("utf-8", "replace"))
print("  extract_body -> %s chars" % (len(body) if body else 0))
if body:
    print("  开头: %s" % body[:400])