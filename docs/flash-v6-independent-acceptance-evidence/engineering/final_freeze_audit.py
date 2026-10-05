"""Read-only JSON/source/AST verification; never imports product or connects DB."""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
import sys

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPECTED = "f0e2cb3d5c44a1a92000f703423a0d26ea1fab5aef750b7a3393102ea98ed696"


def lp(path):
    return Path("\\\\?\\" + str(path)) if sys.platform == "win32" and not str(path).startswith("\\\\?\\") else path


def read(path):
    return json.loads(lp(path).read_text(encoding="utf-8"))


def sha(path):
    return hashlib.sha256(lp(path).read_bytes()).hexdigest()


def create(name, payload):
    with lp(HERE / name).open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2, sort_keys=True)


def source_ast(relative):
    return ast.parse(lp(ROOT / relative).read_text(encoding="utf-8"))


def module_path(name):
    if name == "app" or name.startswith("app."):
        candidate = ROOT / "backend" / Path(*name.split("."))
    elif name == "evaluation" or name.startswith("evaluation."):
        candidate = ROOT / Path(*name.split("."))
    else:
        return None
    for path in (candidate.with_suffix(".py"), candidate / "__init__.py"):
        if path.is_file():
            return path.relative_to(ROOT).as_posix()
    return None


def module_name(relative):
    parts = relative.removesuffix(".py").split("/")
    if parts[0] == "backend":
        parts = parts[1:]
    if parts[-1] == "__init__":
        parts = parts[:-1]
    return ".".join(parts)


def closure():
    queue = ["evaluation/current_flash_v6/" + name + ".py" for name in
             ("run", "freeze", "live_guard", "score", "inputs", "build_cases")]
    visited, edges = set(), {}
    while queue:
        path = queue.pop()
        if path in visited:
            continue
        visited.add(path)
        name = module_name(path)
        names = set()
        for node in ast.walk(source_ast(path)):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    package = name.split(".") if path.endswith("/__init__.py") else name.split(".")[:-1]
                    root = package[:len(package) - node.level + 1]
                    target = ".".join(root + ([node.module] if node.module else []))
                else:
                    target = node.module or ""
                names.add(target)
                names.update(target + "." + alias.name for alias in node.names if alias.name != "*")
        paths = {p for n in names if (p := module_path(n)) is not None}
        for n in names:
            pieces = n.split(".")
            for i in range(1, len(pieces)):
                p = module_path(".".join(pieces[:i]))
                if p and p.endswith("/__init__.py"):
                    paths.add(p)
        edges[path] = sorted(paths)
        queue.extend(paths - visited)
    return sorted(visited), edges


def functions(relative):
    return {node.name: ast.dump(node, include_attributes=False) for node in source_ast(relative).body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def main():
    manifest_path = ROOT / "evaluation/current_flash_v6/frozen-inputs.json"
    manifest = read(manifest_path)
    actual = {name: sha(ROOT / name) for name in manifest["source_hashes"]}
    hashes_match = actual == manifest["source_hashes"] and sha(manifest_path) == EXPECTED
    assert hashes_match, "frozen_files_changed"
    deps, edges = closure()
    missing = [name for name in deps if name not in actual]
    policy_files = ["evaluation/current_flash_v6/" + name for name in
                    ("SCORING-POLICY.md", "SCORING-ADDENDUM.md", "SCORING-ADDENDUM-02.md",
                     "SCORING-ADDENDUM-03.md", "INPUT-ADAPTATION.md")]
    cases = read(ROOT / "evaluation/current_flash_v6/cases-v2.json")["cases"]
    prep = ROOT / "evaluation/current_flash_v6/runs/prep-v6-02"
    captures = []
    for case in cases:
        folder = prep / "cases" / f"{case['ordinal']:02d}"
        request = read(folder / "requests/01.json")
        body = request["business_request"]
        payload_digest = hashlib.sha256(json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        captures.append({"case_id": case["case_id"], "request_digest_matches": payload_digest == request["business_request_sha256"],
                         "single_full_claim": len(body["claims"]) == 1 and body["claims"][0]["text"] == case["saved_draft"] and body["draft"]["body"] == case["saved_draft"],
                         "request_count": len(list((folder / "requests").glob("*.json")))})
    old_manifest = read(ROOT / "evaluation/current_flash_v5/frozen-inputs.json")
    inherited = {name: {"current": actual.get(name), "v5_frozen": old_manifest["source_hashes"][name],
                         "unchanged": actual.get(name) == old_manifest["source_hashes"][name]}
                 for name in ("evaluation/current_flash_v5/inputs.py", "evaluation/current_flash_v5/journal.py")}
    current_functions = functions("evaluation/current_flash_v6/run.py")
    v5_functions = functions("evaluation/current_flash_v5/run.py")
    identical_helpers = {name: current_functions[name] == v5_functions[name] for name in
                         ("_models_preflight", "_attempts", "usage_ledger", "workspace_inventory", "_service_failure", "_auth_or_model_rejection")}
    input_prior = read(HERE / "input-probe-runs/input-binding-02/after.json")["sha256"]
    inherited_input = {key: actual.get(relative) == input_prior[key] for key, relative in
                       {"inputs": "evaluation/current_flash_v6/inputs.py", "build_cases": "evaluation/current_flash_v6/build_cases.py",
                        "v5_inputs": "evaluation/current_flash_v5/inputs.py", "v5_journal": "evaluation/current_flash_v5/journal.py",
                        "case_document": "evaluation/current_flash_v6/cases-v2.json", "matrix": "docs/flash-v6-independent-acceptance-evidence/semantics/control-matrix.json",
                        "adaptation": "evaluation/current_flash_v6/INPUT-ADAPTATION.md"}.items()}
    enum_prior = read(HERE / "enum-probe-runs/core-enum-fix-02/after.json")
    previous_engine = source_ast("docs/flash-v6-independent-acceptance-evidence/core-snapshot-02/backend/app/engine.py")
    current_engine = source_ast("backend/app/engine.py")
    provenance = None
    for tree in (previous_engine, current_engine):
        cls = next(n for n in tree.body if isinstance(n, ast.ClassDef) and n.name == "ContinuityEngine")
        if tree is current_engine:
            node = next(n for n in cls.body if isinstance(n, ast.FunctionDef) and n.name == "provenance")
            provenance = [n.value for n in ast.walk(node) if isinstance(n, ast.Constant) and n.value == "continuity-issue-v6-joint-evidence-coverage"]
        cls.body = [n for n in cls.body if not (isinstance(n, ast.FunctionDef) and n.name == "provenance")]
    engine_only_provenance_changed = ast.dump(previous_engine, include_attributes=False) == ast.dump(current_engine, include_attributes=False)
    core_unchanged = {name: value["expected"] == actual.get(name) for name, value in enum_prior["source_hashes"].items()
                      if name in actual and name != "backend/app/engine.py"}

    guard_results = read(HERE / "guard-probe-runs/guard-order-01/results.json")
    third = next(r for r in guard_results["controls"] if r["control"] == "dependency_digest_drift_before_import")
    normalized_reads = [name.replace("\\", "/") for name in third["material_hash_reads"]]
    observed_guard_rejection = ("backend/app/engine.py" in normalized_reads and
                               "RuntimeError: v6_frozen_hash_mismatch:backend/app/engine.py" in third["traceback"] and
                               not any(third["boundary_attempts"].values()))
    adjudication = {"original_result_preserved": True, "automatic_groups_passed": 2,
                    "third_group_automatic_status": third["status"],
                    "probe_error": "Windows path stored with backslashes, assertion used forward slashes",
                    "original_trace_proves_intended_dependency_rejection_before_import": observed_guard_rejection,
                    "reruns": 0, "boundary_attempts": third["boundary_attempts"],
                    "scope": "adjudication of saved evidence; no new guard execution"}
    create("guard-order-01-adjudication.json", adjudication)
    passed = (not missing and all(name in actual for name in policy_files) and
              all(c["request_digest_matches"] and c["single_full_claim"] and c["request_count"] == 1 for c in captures) and
              all(v["unchanged"] for v in inherited.values()) and all(inherited_input.values()) and
              engine_only_provenance_changed and bool(provenance) and all(core_unchanged.values()) and
              observed_guard_rejection and all(r["status"] == "pass" for r in guard_results["controls"][:2]) and
              len(cases) == 34 and all(c["family"] == "comparison" for c in cases) and
              manifest["maximum_generation_post_attempts"] == 136 and manifest["maximum_models_get_attempts"] == 1)
    result = {"status": "pass" if passed else "fail", "manifest_sha256": EXPECTED,
              "all_frozen_hashes_match": hashes_match, "frozen_file_count": len(actual),
              "repository_python_dependency_closure": deps, "dependency_edges": edges, "missing_dependencies": missing,
              "policy_files_frozen": {name: name in actual for name in policy_files}, "captures": captures,
              "unchanged_v5_inheritance": inherited, "unchanged_v5_helper_ast": identical_helpers,
              "input_probe_inheritance": inherited_input, "engine_logic_same_as_enum_accepted_snapshot_except_provenance": engine_only_provenance_changed,
              "current_schema_v6_confirmed": bool(provenance), "other_core_sources_inherited": core_unchanged,
              "limits": {"logical_cases": 34, "max_post": 136, "max_models_get": 1, "contract_evaluations_per_case": manifest["contract_evaluations_cap_per_case"], "transport_retries": manifest["transport_retries"], "max_tokens": manifest["max_tokens"], "timeout_seconds": manifest["timeout_seconds"]},
              "guard_adjudication": adjudication, "product_imports": 0, "provider_calls": 0, "database_connections": 0,
              "limitations": ["Repo-local Python dependency closure, not a lock of third-party runtime packages.", "No live launch; controller must invoke verified CLI with pinned SHA and fresh identity."]}
    create("final-freeze-audit-01.json", result)
    print(json.dumps({"status": result["status"], "frozen_file_count": len(actual), "repo_python_dependencies": len(deps), "missing_dependencies": missing, "identical_helpers": identical_helpers, "capture_count": len(captures), "guard_adjudicated": observed_guard_rejection}, ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
