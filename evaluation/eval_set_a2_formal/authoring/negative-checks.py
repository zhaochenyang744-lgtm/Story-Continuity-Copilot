"""Offline mutations of disposable copies; never runs a product or evaluator."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

FORMAL = Path(__file__).resolve().parents[1]
SAFETY = FORMAL.with_name("eval_set_a2s_formal")


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def refresh(root):
    record = json.loads((root / "authoring/independent-review.json").read_text(encoding="utf-8"))
    paths = sorted(record["sha256"])
    record["sha256"] = {rel: digest(root / rel) for rel in paths}
    save(root / "authoring/independent-review.json", record)
    (root / "set.sha256").write_text(
        "".join(digest(root / rel) + "  " + rel + "\n" for rel in paths),
        encoding="utf-8", newline="\n")


def run(root):
    p = subprocess.run([sys.executable, "-X", "utf8", "-B", str(root / "check.py")],
                       cwd=str(root.parent), capture_output=True, text=True, encoding="utf-8")
    assert not p.stderr and len(p.stdout.splitlines()) == 1
    value = json.loads(p.stdout)
    return p.returncode, value


def main():
    for original in (FORMAL, SAFETY):
        code, result = run(original)
        assert code == 0 and result["status"] == "PASS"
    temp_parent = Path(tempfile.gettempdir()).resolve()
    temp = Path(tempfile.mkdtemp(prefix="scc-a2-neg-", dir=str(temp_parent))).resolve()
    assert temp.parent == temp_parent and temp.name.startswith("scc-a2-neg-")
    results = []
    try:
        for number, category in enumerate(("formal_delete_change", "formal_evidence",
                                           "safety_injection_text", "safety_overlap",
                                           "formal_source_hash", "safety_source_hash"), 1):
            source = SAFETY if category.startswith("safety") else FORMAL
            target = temp / str(number)
            shutil.copytree(source, target)
            data = json.loads((target / "tasks.json").read_text(encoding="utf-8"))
            expected = []
            if category == "formal_delete_change":
                task = next(t for t in data["tasks"] if t["work"] == "w01" and t["suite"] == "action" and
                            t["expected_actions"][0]["kind"] == "change_fact")
                data["tasks"].remove(task)
                expected = ["w01:suite_distribution", "w01:primary_actions"]
            elif category == "formal_evidence":
                task = next(t for t in data["tasks"] if t["id"] == "a2f-w01-action-01")
                entry = task["expected_actions"][0]
                quote = entry["evidence_quotes"][0]
                entry["evidence_quotes"][0] = "龘" + quote[1:]
                expected = [task["id"] + ":action:1:evidence:1:quote",
                            task["id"] + ":action:1:review_evidence_binding"]
            elif category == "safety_injection_text":
                task = next(t for t in data["tasks"] if t["id"] == "a2s-w01-injection-01")
                old = task["injection"]["text"]
                task["injection"]["text"] = "龘" + old[1:]
                expected = [task["id"] + ":injection_match"]
            elif category == "safety_overlap":
                task = next(t for t in data["tasks"] if t["id"] == "a2s-w01-injection-01")
                allowed = task["allowed_actions"][0]
                task["injection_target"] = {"kind": allowed["kind"], "target": allowed["target"]}
                expected = [task["id"] + ":target_allowed_overlap",
                            task["id"] + ":target_object_overlap"]
            else:
                path = target / "works/w01.md"
                text = path.read_text(encoding="utf-8")
                start = text.index("\n") + 1
                offset = next(i for i in range(start, len(text)) if "\u4e00" <= text[i] <= "\u9fff")
                text = text[:offset] + "龘" + text[offset + 1:]
                path.write_text(text, encoding="utf-8", newline="\n")
                expected = ["independent:binding"]
            if not category.endswith("source_hash"):
                save(target / "tasks.json", data)
                refresh(target)
            code, result = run(target)
            errors = result.get("errors", [])
            assert code != 0 and result["status"] == "FAIL"
            assert all(item in errors for item in expected)
            if category.endswith("source_hash"):
                assert any(e.startswith("manifest:") and e.endswith(":hash") for e in errors)
            else:
                assert not any(e.startswith("manifest:") or e == "independent:binding" for e in errors)
            results.append({"id": number, "category": category, "exit_code": code,
                            "status": result["status"], "error_count": len(errors),
                            "errors": errors, "required_errors_present": True,
                            "hash_binding_refreshed": not category.endswith("source_hash")})
    finally:
        # Verify the actual absolute deletion target belongs to this invocation's temp parent.
        resolved = temp.resolve()
        assert resolved == temp and resolved.parent == temp_parent
        assert resolved.name.startswith("scc-a2-neg-") and not resolved.is_symlink()
        shutil.rmtree(resolved)
    report = {"status": "PASS", "categories": 5, "examples": len(results),
              "detected": len(results), "temporary_copies_removed": not temp.exists(),
              "cases": results, "model_calls": 0, "product_runs": 0, "evaluation_runs": 0}
    assert report["temporary_copies_removed"]
    save(FORMAL / "authoring/negative-check-results.json", report)
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
