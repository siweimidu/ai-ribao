import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

h = open(r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html", encoding="utf-8").read()

for name, pat in (
    ("colon rank", r'"rank":(\d+)'),
    ("comma rank", r'"rank",(\d+)'),
    ("colon heat", r'"heat":([0-9.]+)'),
    ("comma heat", r'"heat",([0-9.]+)'),
):
    print("  %-14s %s -> %d" % (name, pat, len(re.findall(pat, h))))

print()
i = h.find('"rank"')
print("  实际文本: %s" % h[i:i+90])