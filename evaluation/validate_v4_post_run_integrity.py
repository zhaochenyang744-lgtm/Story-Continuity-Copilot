"""Strict, read-only validation for retained V4 formal-run evidence."""
from __future__ import annotations

import json
import pathlib

from evaluation.post_run_integrity import validate_retained_integrity


ROOT = pathlib.Path(__file__).resolve().parents[1]
INTEGRITY_PATH = ROOT / "evaluation" / "results" / "v4-first-formal-post-run-integrity.json"
EXPECTED_ARTIFACTS = {
    "evaluation/results/eval-v4-first-formal-api-corpus-scan.json": "6753f8ef01d56f80fe1a72e306fa46f3be7f46bf3ca3535a4fd163719f0f4e05",
    "evaluation/results/eval-v4-first-formal-bad-cases.json": "5f5facc431fa0509a04baec7d61bf84803df1ec6db9d6fe638dde7762afc1f99",
    "evaluation/results/eval-v4-first-formal-checkpoint.json": "5238cedb7904460f56ce848cff32455cd74cb04dedad70b597334e5d7208df07",
    "evaluation/results/eval-v4-first-formal-report.md": "b86c7d8dad984a435d9ea891b3f0c074d906a79b96b4a249b46c428deec78384",
    "evaluation/results/eval-v4-first-formal-results.json": "74c769a2d93769154670458b00698bf7e018a49177e82cb9324c8cf80ea2ab00",
    "evaluation/results/eval-v4-first-formal-run-manifest.json": "c0ae38391c900ed1c08c3d55d152a9baf45a2aa629f3502d4553ee0c9e5bef49",
    "evaluation/results/eval-v4-first-formal-stability.json": "87996cfdc68cd3c4f8aa10ea29774b357a051f32e5a53981b29e86a00a472c69",
}


def validate(
    root: pathlib.Path = ROOT,
    integrity_path: pathlib.Path = INTEGRITY_PATH,
) -> dict:
    """Require the retained V4 files and all 15 recorded SQLite workspaces."""
    return validate_retained_integrity(
        root,
        integrity_path,
        expected_evaluation="scc-web-demo-eval-v4-first-formal",
        expected_artifacts=EXPECTED_ARTIFACTS,
        expected_workspace_root="evaluation/fixture-workspaces/scc-web-demo-eval-v4-first-formal",
        expected_run_status_totals={"completed": 21},
    )


if __name__ == "__main__":
    print(json.dumps(validate(), ensure_ascii=False, indent=2))
