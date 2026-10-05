"""Controller-only read/hash audit; creates a new receipt and never runs a product."""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import subprocess
from datetime import datetime, timezone

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]


def read(relative):
    return json.loads((ROOT / relative).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect():
    groups = {
        "v4_source_snapshot": {
            "docs/g02-citation-repair-evidence/independent-round1-root/v4-source-snapshot/" + name: digest
            for name, digest in read("docs/g02-citation-repair-evidence/independent-round1-root/v4-source-snapshot/manifest.json")["source_hashes"].items()
        },
        "v4_manifest": {"evaluation/current_flash_v4/frozen-inputs.json": "62899b0791b40efa6c4ee389efbb8239466baba90faa7e762b8bd351fd36a06a"},
        "old_flash": {row["path"]: row["sha256"] for row in read("docs/g02-citation-repair-evidence/controller-baseline.json")["immutable_prior_files"]},
        "v4_results": read("docs/g02-citation-repair-evidence/independent-round1-root/results-before.json"),
        "comparison_v1": read("docs/g02-citation-repair-evidence/independent-round2-root/comparison-v1-preservation.json")["files"],
        "comparison_v2": read("docs/g02-citation-repair-evidence/independent-round3-root/v2-preservation-final.json")["files"],
        "round4_snapshot": read("docs/g02-citation-repair-evidence/independent-round4-root/snapshot-before.json"),
        "round4_delivery": read("docs/g02-citation-repair-evidence/independent-round4-root/delivery-receipt.json")["files"],
        "product": {
            "backend/app/brief_citations.py": "a0a3a31251860265c29b09a95e85b27f05d92dc1a0e6bcc0a9d1736a57b28ccc",
            "backend/app/engine.py": "4d3a07e955aadfaf1ecd31281ccca0d4fb3f36014756b801d906b193e15984c7",
            "backend/app/v2_database.py": "2485b997c32dda446325fe1535df0342330b09afdd53b9619137ad824a17e754",
            "backend/app/provider.py": "e415c36cc08114492e7ac5305ef67db89eb58f1a06aa01a0a19c9c89b91b7380",
        },
    }
    checks = []
    files = {}
    for name, expected in groups.items():
        changed = []
        for relative, digest in expected.items():
            path = ROOT / relative
            actual = sha(path) if path.is_file() else None
            files[relative] = actual
            if actual != digest:
                changed.append({"path": relative, "expected": digest, "actual": actual})
        checks.append({"group": name, "count": len(expected), "changed": changed})
    head = subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    return {"time": datetime.now(timezone.utc).isoformat(), "git_head": head,
            "expected_head": "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2",
            "head_matches": head == "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2",
            "groups": checks, "files": files, "unique_files": len(files),
            "provider_calls": 0, "database_connections": 0}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("receipt", help="New controller receipt basename")
    args = parser.parse_args()
    if pathlib.Path(args.receipt).name != args.receipt or not args.receipt.endswith(".json"):
        raise SystemExit("receipt basename required")
    destination = HERE / args.receipt
    with destination.open("x", encoding="utf-8") as handle:
        result = inspect()
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({"receipt": str(destination), "unique_files": result["unique_files"],
                      "groups": result["groups"], "head_matches": result["head_matches"]}, ensure_ascii=False))
    if not result["head_matches"] or any(group["changed"] for group in result["groups"]):
        raise SystemExit(1)
