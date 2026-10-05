"""Check both original result inventories; append, never replace, evidence."""
import datetime
import hashlib
import json
import pathlib

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
checks = []
for version, round_name in [("v1", "independent-round1"), ("v2", "independent-round2")]:
    inventory = ROOT / f"evaluation/current_flash_{version}/{round_name}/root-results-before.json"
    entries = json.loads(inventory.read_text(encoding="utf-8-sig"))
    mismatches = [e["path"] for e in entries if hashlib.sha256((ROOT / e["path"]).read_bytes()).hexdigest() != e["sha256"]]
    checks.append({"version": version, "files": len(entries), "mismatches": mismatches})
    assert not mismatches
assert [x["files"] for x in checks] == [53, 12]
result = {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "scope_note": "root-verification.json checked the V2 inventory (12 files) only; this final supplement checks both V1 and V2 inventories, 65 original files in total. The first record is retained unchanged.",
    "checks": checks,
    "preserved_original_result_files": sum(x["files"] for x in checks),
    "mismatches": [],
    "provider_dispatches": 0,
}
with (OUT / "root-integrity-final.json").open("x", encoding="utf-8") as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
    stream.write("\n")
print(json.dumps(result, ensure_ascii=False))
