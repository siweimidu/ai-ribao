import io, sys, re, time, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}

h = ""
for _ in range(3):
    try:
        h = urllib.request.urlopen(urllib.request.Request("https://dailydawn.dev/zh/2026-10-22", headers=UA), timeout=45).read().decode("utf-8", "replace")
        break
    except Exception as e:
        print("  retry %s" % str(e)[:40]); time.sleep(2)

print("  bytes=%d" % len(h))
txt = re.sub(r"<script[\s\S]*?</script>", " ", h)
txt = re.sub(r"<style[\s\S]*?</style>", " ", txt)
txt = re.sub(r"<[^>]+>", "\n", txt)
lines = [x.strip() for x in txt.splitlines() if x.strip()]
print("  行数=%d" % len(lines))
print()
for x in lines[:45]:
    print("  %s" % x[:96])