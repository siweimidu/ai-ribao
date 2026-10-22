import io, sys, re
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
h = open(r"C:\Users\35238\AppData\Local\Temp\hot.html", encoding="utf-8").read()
u = h.replace(chr(92) + chr(34), chr(34))

# Only ONE record survives in the serialized slice; confirm the full record shape.
i = u.find('"heat"')
seg = u[max(0, i - 900):i + 420]
print("  === 那一条完整记录 ===")
print("  %s" % " ".join(seg.split())[:900])