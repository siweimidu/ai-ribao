import io, sys
from pathlib import Path
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
p = Path('src/aidaily/site.py')
s = p.read_text(encoding='utf-8')

s = s.replace('    coverage = _render_source_coverage(ordered_body)',
              '    source_cover = _render_source_coverage(ordered_body)', 1)

old = '{chr(10).join(body)}' + chr(10) + chr(10) + '    {untranslated_block}'
new = '{chr(10).join(body)}' + chr(10) + chr(10) + '    {source_cover}' + chr(10) + chr(10) + '    {untranslated_block}'
assert s.count(old) == 1, s.count(old)
s = s.replace(old, new, 1)
p.write_text(s, encoding='utf-8')
print('  template wired')