"""Replay the unchanged first-round synthetic cases against current stable source; new output directory."""
from pathlib import Path
old=Path(__file__).parent.parent/"independent-round1-code/probe.py"
source=old.read_text(encoding="utf-8")
needle='"温岚还未掌握暗号。")],'
assert source.count(needle)==1
source=source.replace(needle,'"温岚还未掌握暗号。"])],')
# Preserve original expectations; compare hashes against the new documented freeze, not V4.
source=source.replace('evaluation/current_flash_v4/frozen-inputs.json','evaluation/current_contract_compare_v1/frozen-inputs.json')
source=source.replace('"matches_v4_freeze"','"matches_current_comparison_freeze"')
exec(compile(source,str(old),"exec"))
