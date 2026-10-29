import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
p = Path('src/aidaily/site.py')
s = p.read_text(encoding='utf-8')
block = Path('scripts/cover.txt').read_text(encoding='utf-8')
anchor = 'def render_day('
i = s.index(anchor)
s = s[:i] + block.lstrip(chr(10)) + chr(10) + chr(10) + s[i:]
old = '    overview = _render_overview(digest, insights, ordered_body, items_by_id)'
new = ('    overview = _render_overview(digest, insights, ordered_body, items_by_id)' + chr(10) + '    coverage = _render_source_coverage(ordered_body)')
assert s.count(old) == 1
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('  added')