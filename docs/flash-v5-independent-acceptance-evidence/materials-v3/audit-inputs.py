"""Standard-library-only independent material audit; no product imports or calls."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
EXPECTED_HEAD = "7d811cc9a3fb76f3cfbe60492399d6c0fc9e07b2"
V3 = ROOT / "evaluation/current_contract_compare_v3"
V2 = ROOT / "evaluation/current_contract_compare_v2"
OUTPUTS = (HERE / "case-matrix.json", HERE / "inputs-audit.json")


def read(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def text_digest(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def canonical_digest(value) -> str:
    return text_digest(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))


def write_x(path: Path, payload) -> None:
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())


def require(condition: bool, message: str) -> None:
    if not condition:
        raise AssertionError(message)


def audit() -> tuple[dict, dict]:
    require(HERE.relative_to(ROOT).as_posix() == "docs/flash-v5-independent-acceptance-evidence/materials-v3", "unexpected_audit_location")
    head = subprocess.check_output(["git", "-c", "core.longpaths=true", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    require(head == EXPECTED_HEAD, "code_baseline_changed")
    manifest = read(V3 / "frozen-inputs.json")
    v2_manifest = read(V2 / "frozen-inputs.json")
    expected = dict(manifest["source_hashes"])
    expected["evaluation/current_contract_compare_v3/frozen-inputs.json"] = "0afd9630d22aecc44d1fbc8a955787d12d1286b31ec85a3e0985dff132da8baf"
    corpus_paths = sorted((V2 / "corpora").glob("*.json"))
    require(len(corpus_paths) == 4, "corpus_count")
    for path in corpus_paths:
        relative = path.relative_to(ROOT).as_posix()
        expected[relative] = v2_manifest["source_hashes"][relative]
    expected.update({
        "backend/app/brief_citations.py": "a0a3a31251860265c29b09a95e85b27f05d92dc1a0e6bcc0a9d1736a57b28ccc",
        "backend/app/v2_database.py": "2485b997c32dda446325fe1535df0342330b09afdd53b9619137ad824a17e754",
    })
    before = {relative: digest(ROOT / relative) for relative in sorted(expected)}
    require(before == {relative: expected[relative] for relative in sorted(expected)}, "frozen_input_hash_mismatch")
    own_sources = {name: digest(HERE / name) for name in ("audit-inputs.py", "manual-expectations.json", "review.md")}
    cases_doc = read(V3 / "cases.json")
    cases = cases_doc["cases"]
    v2_cases = {c["case_id"]: c for c in read(V2 / "cases.json")["cases"]}
    captures_list = read(V2 / "actual-inputs.json")["rows"]
    captures = {row["case_id"]: row for row in captures_list}
    notes_list = read(HERE / "manual-expectations.json")["case_notes"]
    notes = {row["case_id"]: row for row in notes_list}
    corpora = {path.stem: read(path) for path in corpus_paths}
    require(len(cases) == len(captures_list) == len(captures) == len(notes_list) == len(notes) == 24, "case_count_or_duplicate")
    require({c["case_id"] for c in cases} == set(notes), "manual_case_coverage")
    require(Counter(c["expected_class"] for c in cases) == {"conflict": 8, "no_conflict": 8, "insufficient_evidence": 8}, "class_balance")
    rows = []
    checks = []
    for case in cases:
        cid = case["case_id"]
        note = notes[cid]
        corpus = corpora[case["corpus_key"]]
        sources = {x["source_label"]: x for x in corpus["chapters"]}
        by_span = {f"fixture-span-{case['corpus_key']}-{x['chapter_number']}": x for x in corpus["chapters"]}
        old = v2_cases[case["lineage"]["v2_case_id"]]
        capture = captures[old["case_id"]]
        request = capture["business_request"]
        for field in ("target_draft", "corpus_key", "target_claim_ordinal", "expected_class", "allowed_outcomes", "temporal_policy"):
            require(case[field] == old[field], cid + ":v2_inheritance:" + field)
        require(note["expected_class"] == case["expected_class"] and note["category"] == case["decision_category"], cid + ":manual_class_category")
        labels = [[x["source_label"] for x in group] for group in case["minimum_sufficient_evidence_sets"]]
        optional = [x["source_label"] for x in case["recommended_context"]]
        require(note["minimum_labels"] == labels and note["optional_labels"] == optional, cid + ":manual_source_policy")
        require(request["draft"]["body"] == case["target_draft"], cid + ":draft_capture")
        require(len(request["claims"]) == 1 and request["claims"][0]["text"] == case["target_draft"], cid + ":claim_capture")
        claim = request["claims"][0]
        selected = claim["allowed_evidence"]
        require(len({span["id"] for span in selected}) == len(selected), cid + ":duplicate_selected")
        selected_labels = set()
        for span in selected:
            source = by_span[span["id"]]
            require(span["label"] == source["source_label"] and span["body"] == source["body"], cid + ":selected_source_content")
            require(span["chapter_id"] == f"fixture-chapter-{case['corpus_key']}-{source['chapter_number']}", cid + ":selected_chapter_binding")
            require(span["prompt_excerpt"] == source["body"], cid + ":short_source_excerpt")
            selected_labels.add(span["label"])
        for group in case["minimum_sufficient_evidence_sets"] + [case["recommended_context"]]:
            for item in group:
                source = sources[item["source_label"]]
                require(item["chapter_number"] == source["chapter_number"] and item["body_sha256"] == text_digest(source["body"]), cid + ":gold_source_binding")
                require(item["source_label"] in selected_labels, cid + ":declared_source_not_selected")
        require(any(set(group) <= selected_labels for group in labels), cid + ":minimum_not_selected")
        require(len({row["id"] for row in request["memory"]}) == len(request["memory"]), cid + ":duplicate_memory")
        for memory in request["memory"]:
            source = by_span[memory["source_span_id"]]
            require(memory["value"] == source["body"], cid + ":memory_source_content")
        declared_labels = {label for group in labels for label in group} | set(optional)
        checks.append({"case_id": cid, "v2_case_id": old["case_id"], "draft_claim_exact": True,
                       "manual_gold_agree": True, "minimum_selected": True, "all_selected_body_and_excerpt_match_corpus": True,
                       "selected_count": len(selected), "memory_count": len(request["memory"]), "memory_values_source_bound": True})
        rows.append({
            "case_id": cid, "v2_case_id": old["case_id"], "corpus_key": case["corpus_key"], "corpus_title": corpus["title"],
            "material_status": "seen_development_reviewed_before_v5_results", "draft": case["target_draft"],
            "expected_class": case["expected_class"], "expected_nature": case["expected_nature"], "category_axis": case["category_axis"],
            "decision_category": case["decision_category"], "category_policy": case["category_policy"], "category_candidates": case["category_candidates"],
            "allowed_outcomes": case["allowed_outcomes"], "temporal_policy": case["temporal_policy"],
            "minimum_source_sets": [[sources[label] for label in group] for group in labels],
            "optional_sources": [sources[label] for label in optional],
            "issue_evidence_relation_if_emitted": case["evidence_relation"], "issue_evidence_sufficiency_if_emitted": case["evidence_sufficiency"],
            "no_issue_requires_no_emitted_citations": "no_issue" in case["allowed_outcomes"],
            "raw_temporal_relation_if_issue": "explicit_later_transition" if "state_change" in case["allowed_outcomes"] else
                "timeless_rule" if case["expected_class"] == "conflict" and case["temporal_policy"] == "timeless_rule" else
                "explicit_overlap" if case["expected_class"] == "conflict" else "unknown",
            "capture_origin": "frozen_v2_actual_inputs_not_v5_dispatch", "captured_claim_id": claim["id"],
            "captured_selected_sources": selected,
            "captured_selected_but_not_declared_for_issue": [span["label"] for span in selected if span["label"] not in declared_labels],
            "captured_memory": request["memory"], "captured_business_request_canonical_sha256": canonical_digest(request),
            "independent_manual_note": note,
            "future_result_review": {"raw_first": "pending_actual_result", "raw_repair": "pending_actual_result", "final_product": "pending_actual_result",
                "category_adjudication": "pending_per_answer_manual_adjudication" if case["category_policy"] == "manual_variant" else "fixed_gold_still_needs_per_answer_review"},
        })
    after = {relative: digest(ROOT / relative) for relative in sorted(expected)}
    require(after == before, "inputs_changed_during_audit")
    require(own_sources == {name: digest(HERE / name) for name in own_sources}, "own_sources_changed_during_audit")
    created_at = datetime.now(timezone.utc).isoformat()
    matrix = {"schema_version": "flash-v5-independent-v3-material-matrix-v1", "prepared_at": created_at,
              "baseline_commit": head, "scope": "24 comparison cases only; excludes six G02 cases", "rows": rows}
    report = {"schema_version": "flash-v5-independent-v3-input-audit-v1", "prepared_at": created_at, "baseline_commit": head,
              "mode": "standard_library_static_material_read_and_hash_only", "provider_calls": 0, "api_calls": 0,
              "database_connections": 0, "case_count": len(rows), "class_counts": dict(Counter(row["expected_class"] for row in rows)),
              "corpus_count": len(corpora), "chapter_count": sum(len(c["chapters"]) for c in corpora.values()),
              "case_checks": checks, "frozen_files_checked": len(before), "hashes_before": before, "hashes_after": after,
              "own_source_hashes": own_sources, "material_check_result": "pass", "model_result_review_status": "not_started",
              "limitations": ["Seen development material, not a blind or held-out set.", "Historical V2 capture is not a V5 dispatch snapshot.",
                  "Companion category requires per-answer human adjudication.", "World-rule display metadata retains optional roster text; formal source policy is authoritative.",
                  "V2 early 24/8 first-failure chain is not reconstructed.", "No runner or new model outcome has been validated by this audit."]}
    return matrix, report


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true", help="Create the two review artifacts once; never overwrite.")
    args = parser.parse_args()
    if args.write:
        require(not any(path.exists() for path in OUTPUTS), "review_outputs_already_exist")
        (HERE / "audit-create-only-reservation").mkdir(exist_ok=False)
    try:
        matrix, report = audit()
        if args.write:
            write_x(OUTPUTS[0], matrix)
            report["case_matrix_file_sha256"] = digest(OUTPUTS[0])
            write_x(OUTPUTS[1], report)
        print(json.dumps({"material_check_result": report["material_check_result"], "case_count": report["case_count"],
                          "class_counts": report["class_counts"], "frozen_files_checked": report["frozen_files_checked"],
                          "provider_calls": 0, "api_calls": 0, "database_connections": 0, "written": args.write}, ensure_ascii=False))
    except Exception as exc:
        if args.write:
            write_x(HERE / "first-failure.json", {"time": datetime.now(timezone.utc).isoformat(), "error_type": type(exc).__name__, "error": str(exc), "scope": "this independent material audit only"})
        raise


if __name__ == "__main__":
    main()
