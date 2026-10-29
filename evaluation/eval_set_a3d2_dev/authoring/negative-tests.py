"""Five task-mandated offline corruptions, restricted to verified local copies."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
FILES = [
    "README.md", "works/w01.md", "materials/w01-facts.json",
    "materials/w01-foreshadows.json", "tasks.json", "set.sha256", "check.py",
    "authoring/self-review.md", "authoring/self-review.json",
    "authoring/novelty-reference.json", "authoring/task-intents.json",
]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def reseal(root):
    files = sorted(["tasks.json", "works/w01.md", "materials/w01-facts.json", "materials/w01-foreshadows.json"])
    (root / "set.sha256").write_text("".join(digest(root / f) + "  " + f + "\n" for f in files),
                                     encoding="utf-8", newline="\n")


def main():
    baseline = {f: digest(ROOT / f) for f in FILES}
    records = []
    temporary = Path(tempfile.mkdtemp(prefix="negative-", dir=ROOT / "authoring")).resolve()
    # Verify the absolute recursive-cleanup target before any copying/mutation.
    assert temporary.is_relative_to((ROOT / "authoring").resolve())
    assert temporary.parent == (ROOT / "authoring").resolve()
    assert temporary.name.startswith("negative-")
    try:
        for name, expected in [
            ("state_below_five", "trace_object:1:state_count"),
            ("quote_one_character", "trace_object:1:state:1:quote_verbatim_unique"),
            ("tidy_action_deleted", "a3e-tidy-01:complete_scope_actions"),
            ("three_evidence_passages", "a3e-tidy-01:expected_actions:1:evidence_alignment_max_2"),
            ("source_one_character", "manifest:hash:works/w01.md"),
        ]:
            case = temporary / name
            for relative in FILES:
                target = case / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(ROOT / relative, target)
            if name in {"state_below_five", "quote_one_character"}:
                review = load(case / "authoring/self-review.json")
                if name == "state_below_five":
                    review["trace_objects"][0]["states"].pop()
                    assert len(review["trace_objects"][0]["states"]) == 4
                else:
                    item = review["trace_objects"][0]["states"][0]
                    item["quote"] = "错" + item["quote"][1:]
                write(case / "authoring/self-review.json", review)
            elif name in {"tidy_action_deleted", "three_evidence_passages"}:
                tasks = load(case / "tasks.json")
                tidy = next(t for t in tasks["tasks"] if t["id"] == "a3e-tidy-01")
                if name == "tidy_action_deleted":
                    tidy["expected_actions"].pop()
                else:
                    action = tidy["expected_actions"][0]
                    action["evidence_chapters"] = action["evidence_chapters"][:1] * 3
                    action["evidence_quotes"] = action["evidence_quotes"][:1] * 3
                write(case / "tasks.json", tasks)
                # Reseal data, so these prove semantic structure checks beyond hash failure.
                reseal(case)
            else:
                source = case / "works/w01.md"
                text = source.read_text(encoding="utf-8")
                index = text.index("\n\n") + 2
                source.write_text(text[:index] + "错" + text[index + 1:], encoding="utf-8", newline="\n")
            run = subprocess.run([sys.executable, "-X", "utf8", "-B", str(case / "check.py")],
                                 cwd=case / "authoring", capture_output=True, text=True, encoding="utf-8")
            result = json.loads(run.stdout)
            found = expected in result["errors"]
            records.append({"case": name, "exit_code": run.returncode, "status": result["status"],
                            "expected_error": expected, "expected_error_found": found,
                            "errors": result["errors"]})
            assert run.returncode != 0 and result["status"] == "FAIL" and found, name
    finally:
        assert temporary.is_relative_to((ROOT / "authoring").resolve()) and temporary.name.startswith("negative-")
        shutil.rmtree(temporary)
    assert baseline == {f: digest(ROOT / f) for f in FILES}, "canonical_files_changed"
    output = {"status": "PASS", "cases": records, "cases_detected": len(records),
              "canonical_files_unchanged": True, "temporary_copies_removed": not temporary.exists()}
    write(ROOT / "authoring/negative-tests.json", output)
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))


if __name__ == "__main__":
    main()
