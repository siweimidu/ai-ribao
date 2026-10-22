import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
h = open(r"C:\Users\35238\AppData\Local\Temp\hot.html", encoding="utf-8").read()

# The payload embeds escaped quotes (\"rank\") inside a JS string literal.
u = h.replace(chr(92) + chr(34), chr(34))
print("  反转义后 bytes=%d" % len(u))

for pat, label in ((r'"rank",(\d+)', "rank"), (r'"heat",([0-9.]+)', "heat"),
                   (r'"sourceCount",(\d+)', "sources"), (r'"trendPct",(-?[0-9.]+)', "trendPct"),
                   (r'"participantCount",(\d+)', "participants")):
    m = re.findall(pat, u)
    print("  %-14s %d  %s" % (label, len(m), m[:4]))