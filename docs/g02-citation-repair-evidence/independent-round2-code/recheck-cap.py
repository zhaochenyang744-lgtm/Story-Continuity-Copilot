"""Replay the original distinct-12-item capacity counterexample without changing its fixtures."""
from pathlib import Path
old=Path(__file__).parent.parent/"independent-round1-code/cap-probe.py"
source=old.read_text(encoding="utf-8")
source=source.replace('Path(__file__).with_name("probe.py")','(Path(__file__).parent.parent/"independent-round1-code/probe.py")')
exec(compile(source,str(old),"exec"))
