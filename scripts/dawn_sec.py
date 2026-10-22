import io, sys, re, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from bs4 import BeautifulSoup
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = ""
for _ in range(3):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://dailydawn.dev/zh/2026-10-22", headers=UA), timeout=45).read().decode("utf-8", "replace")
        break
    except Exception:
        time.sleep(2)

soup = BeautifulSoup(h, "lxml")
secs = soup.select(".dd-section")
print("  .dd-section: %d 个" % len(secs))
for s in secs[:3]:
    hd = s.find(["h2", "h3"])
    print()
    print("  --- %s ---" % (hd.get_text(strip=True) if hd else "?"))
    txt = " ".join(s.get_text(" ", strip=True).split())
    print("     %s" % txt[:260])
    links = [a.get("href") for a in s.find_all("a", href=True) if a.get("href", "").startswith("http")]
    print("     links: %s" % (links[:3] or "无"))