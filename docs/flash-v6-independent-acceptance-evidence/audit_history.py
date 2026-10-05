"""Read-only historical integrity audit; output receipt is create-only."""
import argparse
import datetime
import hashlib
import json
import os
import pathlib
import subprocess

HERE = pathlib.Path(__file__).resolve().parent
if os.name == "nt" and not str(HERE).startswith("\\\\?\\"):
    HERE = pathlib.Path("\\\\?\\" + str(HERE))
ROOT = HERE.parents[1]
EXPECTED_BASELINE = "41acb413c34db0870a9daa1766ed119cefc7d6389f0bb4a49cbc04ca01831183"


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt")
    args = parser.parse_args()
    if pathlib.Path(args.receipt).name != args.receipt or not args.receipt.endswith(".json"):
        raise SystemExit("new receipt basename required")
    destination = HERE / args.receipt
    if destination.exists():
        raise SystemExit("receipt already exists")
    baseline_path = HERE / "BASELINE.json"
    if sha(baseline_path) != EXPECTED_BASELINE:
        raise SystemExit("baseline manifest changed")
    baseline = json.loads(baseline_path.read_text(encoding="utf-8"))
    checks = []
    for name, base, files in (
        ("historical_artifacts", ROOT, baseline["protected_old_artifacts"]),
        ("recoverable_v5_bytes", ROOT / baseline["snapshot_root"], baseline["snapshot_files"]),
    ):
        changed = []
        for relative, expected in files.items():
            path = base / relative
            actual = sha(path) if path.is_file() else None
            if actual != expected:
                changed.append({"path": relative, "expected": expected, "actual": actual})
        checks.append({"group": name, "count": len(files), "changed": changed})
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    result = {"time": datetime.datetime.now(datetime.timezone.utc).isoformat(),
              "checks": checks, "git_head": head, "head_unchanged": head == baseline["git_head"],
              "provider_calls": 0, "database_connections": 0,
              "current_product_changes": "authorized; reviewed separately from historical preservation"}
    with destination.open("x", encoding="utf-8") as output:
        json.dump(result, output, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False))
    if not result["head_unchanged"] or any(item["changed"] for item in checks):
        raise SystemExit(1)
