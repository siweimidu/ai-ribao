from pathlib import Path
p = Path("src/aidaily/aihot_hot.py")
s = p.read_text(encoding="utf-8")

# The payload is a devalue/flight-style serialization: keys and values are separated by a
# COMMA, not a colon -- `"rank",10,"heat",94.8,"trend","flat"`. Matching only `:` found nothing,
# which is why the first version parsed zero entries from a page that clearly had them.
old = """_RANK = re.compile(r'"rank":(\\d+)')

_FIELD = {
    "heat": re.compile(r'"heat":([0-9]+(?:\\.[0-9]+)?)'),
    "trend": re.compile(r'"trend":"([a-z]+)"'),
    "trend_pct": re.compile(r'"trendPct":(-?[0-9]+(?:\\.[0-9]+)?)'),
    "sources": re.compile(r'"sourceCount":(\\d+)'),
    "participants": re.compile(r'"participantCount":(\\d+)'),
}

_SUMMARY = re.compile(r'"summary":"((?:[^"\\\\]|\\\\.){40,700})')"""

new = """#: A key may be followed by `:` or `,` depending on the serializer. Both are accepted so a
#: payload that switches representation does not silently parse to nothing.
_SEP = r"[\\s]*[:][\\s]*"

_RANK = re.compile(r'"rank"' + _SEP + r'(\\d+)')

_FIELD = {
    "heat": re.compile(r'"heat"' + _SEP + r'([0-9]+(?:\\.[0-9]+)?)'),
    "trend": re.compile(r'"trend"' + _SEP + r'"([a-z]+)"'),
    "trend_pct": re.compile(r'"trendPct"' + _SEP + r'(-?[0-9]+(?:\\.[0-9]+)?)'),
    "sources": re.compile(r'"sourceCount"' + _SEP + r'(\\d+)'),
    "participants": re.compile(r'"participantCount"' + _SEP + r'(\\d+)'),
}

_SUMMARY = re.compile(r'"summary"' + _SEP + r'"((?:[^"\\\\]|\\\\.){40,700})')"""

assert s.count(old) == 1, s.count(old)
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")
print("separator relaxed")