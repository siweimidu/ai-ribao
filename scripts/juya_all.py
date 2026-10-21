import io, re, sys, urllib.request
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/126 Safari/537.36"}
def get(u):
    return urllib.request.urlopen(urllib.request.Request(u, headers=UA), timeout=45).read().decode("utf-8", "replace")

page = get("https://daily.juya.uk/latest/")
txt = re.sub(r"<script[\s\S]*?</script>", " ", page)
txt = re.sub(r"<style[\s\S]*?</style>", " ", txt)
txt = re.sub(r"<[^>]+>", "\n", txt)
lines = [l.strip() for l in txt.splitlines() if l.strip()]

# Section headers and numbered headlines
sections = {"要闻", "开发生态", "模型发布", "产品应用", "行业动态", "技术与洞察", "其他"}
entries = []
cur = "?"
for l in lines:
    if l in sections:
        cur = l
        continue
    m = re.match(r"^(.+?)\s*#(\d+)$", l)
    if m:
        entries.append((m.group(2), cur, m.group(1).strip()))

print("  juya 10-21 共 %d 条：" % len(entries))
for num, sec, title in entries:
    print("    %s [%s] %s" % (num.rjust(2), sec, title[:64]))