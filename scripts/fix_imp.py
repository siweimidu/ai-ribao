from pathlib import Path
p = Path("scripts/test_extract.py")
s = p.read_text(encoding="utf-8")
s = s.replace("from aidaily.extract import extract_body", "from aidaily.fulltext import extract_body")
p.write_text(s, encoding="utf-8")
print("fixed")