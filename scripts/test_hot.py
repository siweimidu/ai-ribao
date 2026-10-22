import io, sys
sys.path.insert(0, r"D:\Code\AI日报\src")
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
from aidaily.aihot_hot import parse_hot

h = open(r"C:\Users\35238\AppData\Local\Temp\aihot_hot.html", encoding="utf-8").read()
entries = parse_hot(h)
print("  解析到 %d 条" % len(entries))
print()
for e in entries:
    print("  NO.%-3d heat=%-7.1f sources=%-2d participants=%-3d trend=%s %s" % (
        e.rank, e.heat, e.sources, e.participants, e.trend, e.summary[:52]))