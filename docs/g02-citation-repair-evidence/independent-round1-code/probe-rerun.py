"""Preserve first probe's syntax-failure evidence; fix only its list delimiter in memory."""
from pathlib import Path
source=Path(__file__).with_name("probe.py").read_text(encoding="utf-8")
needle='"温岚还未掌握暗号。")],'
assert source.count(needle)==1
source=source.replace(needle,'"温岚还未掌握暗号。"])],')
exec(compile(source,str(Path(__file__).with_name("probe.py")),"exec"))
