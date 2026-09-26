"""Independent final checks; no real Provider calls or historical writes."""
import datetime
import hashlib
import json
import os
import pathlib
import subprocess
import sys

ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent

def read(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def save(name, value):
    with (OUT / name).open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")

historical = read(ROOT / "evaluation/current_flash_v2/independent-round2/root-results-before.json")
run = ROOT / "evaluation/current_flash_v3/runs/offline-equivalence-20260926-01"
before = {str(p.relative_to(ROOT)).replace("\\", "/"): sha(p) for p in run.rglob("*") if p.is_file()}
save("root-results-before.json", before)
source_mismatches = [p for p, expected in read(run / "start.json")["source_hashes"].items() if sha(ROOT / p) != expected]
assert not source_mismatches, source_mismatches
comparisons = []
for p in sorted((run / "cases").glob("*.json")):
    case = read(p)
    old = read(ROOT / case["v2_case_file"])["business_requests"][0]["business_request"]
    current = case["v3_business_request"]
    digest = hashlib.sha256(json.dumps(current, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    assert old == current
    assert digest == case["v2_business_request_sha256"] == case["v3_business_request_sha256"]
    comparisons.append({"case_id": case["case_id"], "equal": True, "sha256": digest})
assert len(comparisons) == 4

env = dict(os.environ)
env.update(CONTINUITY_PROVIDER="offline", CONTINUITY_API_KEY="synthetic-independent-no-network", PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=".;backend")
checks = [
    ("root-freeze-verify.txt", [sys.executable, "-B", "-m", "evaluation.current_flash_v2.run", "verify"]),
    ("root-offline-tests.txt", [sys.executable, "-B", "-m", "pytest", "-q", "-p", "no:cacheprovider", "evaluation/current_flash_v3/test_offline.py"]),
]
for filename, command in checks:
    result = subprocess.run(command, cwd=ROOT, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, encoding="utf-8", errors="replace")
    with (OUT / filename).open("x", encoding="utf-8") as stream:
        stream.write(result.stdout)
    print(filename, result.returncode, flush=True)
    assert result.returncode == 0, filename

history_bad = [entry["path"] for entry in historical if sha(ROOT / entry["path"]) != entry["sha256"]]
current_bad = [p for p, expected in before.items() if sha(ROOT / p) != expected]
changed = subprocess.check_output(["git", "-c", "core.longpaths=true", "diff", "--name-only", "HEAD"], cwd=ROOT, encoding="utf-8").splitlines()
assert changed == ["evaluation/README.md"], changed
assert not history_bad and not current_bad
head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, encoding="utf-8").strip()
assert head == "c3bd54ab019447354e8b1387e16b9aca3258b4c9"
save("root-verification.json", {
    "timestamp": datetime.datetime.now(datetime.timezone.utc).isoformat(),
    "head": head, "preserved_v1_v2_result_files": len(historical),
    "preserved_v3_result_files": len(before), "source_hash_mismatches": source_mismatches,
    "historical_result_mismatches": history_bad, "v3_result_mismatches": current_bad,
    "exact_business_request_comparisons": comparisons,
    "independent_v2_freeze_check": "passed", "independent_v3_offline_tests": 3,
    "product_diff": [], "independent_real_provider_dispatches": 0,
    "status": "evaluation_evidence_accepted_product_quality_has_open_findings",
})
print("Independent V3 final checks passed.")
