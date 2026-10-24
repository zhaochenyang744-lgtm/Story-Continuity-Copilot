"""Four required fault injections into isolated disposable copies; no model calls."""
from pathlib import Path
import hashlib
import importlib.util
import json
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def save(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def refresh_manifest(root):
    paths = [root / "tasks.json"]
    for folder in ("works", "materials"):
        paths.extend(p for p in (root / folder).rglob("*") if p.is_file())
    lines = [hashlib.sha256(p.read_bytes()).hexdigest() + "  " + p.relative_to(root).as_posix()
             for p in sorted(paths, key=lambda p: p.relative_to(root).as_posix())]
    (root / "set.sha256").write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def main():
    spec = importlib.util.spec_from_file_location("a3_dev_offline_check", ROOT / "check.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    baseline = module.validate(ROOT)
    if baseline.get("status") != "PASS":
        print(json.dumps({"status": "FAIL", "reason": "baseline_not_PASS", "errors": baseline.get("errors")}, ensure_ascii=False))
        return 1
    results = []
    parent = (ROOT / "authoring").resolve()
    for case in ("trace_state_below_five", "quote_one_character", "missing_thread_action", "source_one_character"):
        temporary = Path(tempfile.mkdtemp(prefix="a3-negative-", dir=parent)).resolve()
        # Validate the absolute disposable path before copy and recursive cleanup.
        assert temporary.parent == parent and temporary.name.startswith("a3-negative-")
        try:
            for folder in ("works", "materials"):
                shutil.copytree(ROOT / folder, temporary / folder)
            (temporary / "authoring").mkdir()
            for p in (ROOT / "authoring").iterdir():
                if p.is_file():
                    shutil.copy2(p, temporary / "authoring" / p.name)
            for name in ("README.md", "tasks.json", "set.sha256", "check.py"):
                shutil.copy2(ROOT / name, temporary / name)
            if case == "trace_state_below_five":
                p = temporary / "authoring/self-review.json"
                data = json.loads(p.read_text(encoding="utf-8"))
                target = next(t for t in data["trace_objects"] if len(t["states"]) == 5)
                del target["states"][2]
                save(p, data)
                expected = "trace_object:1:state_count"
            elif case == "quote_one_character":
                p = temporary / "authoring/self-review.json"
                data = json.loads(p.read_text(encoding="utf-8"))
                item = data["trace_objects"][0]["states"][0]
                item["quote"] = ("错" if item["quote"][0] != "错" else "异") + item["quote"][1:]
                save(p, data)
                expected = "quote_verbatim_unique"
            elif case == "missing_thread_action":
                p = temporary / "tasks.json"
                data = json.loads(p.read_text(encoding="utf-8"))
                task = next(t for t in data["tasks"] if t["suite"] == "thread_audit")
                task["expected_actions"].pop()
                save(p, data)
                # Rehash to prove the scope checker detects a missing gold item independently.
                refresh_manifest(temporary)
                expected = "complete_scope_actions"
            else:
                p = temporary / "works/w01.md"
                source = p.read_text(encoding="utf-8")
                heading_end = source.index("\n")
                hit = re.search(r"[\u3400-\u4dbf\u4e00-\u9fff]", source[heading_end:])
                index = heading_end + hit.start()
                source = source[:index] + ("异" if source[index] != "异" else "另") + source[index + 1:]
                p.write_text(source, encoding="utf-8", newline="\n")
                expected = "manifest:hash:works/w01.md"
            process = subprocess.run([sys.executable, "-X", "utf8", "-B", str(temporary / "check.py")],
                                     cwd=temporary, text=True, encoding="utf-8", capture_output=True, check=False)
            result = json.loads(process.stdout)
            detected = (process.returncode != 0 and result.get("status") == "FAIL"
                        and len(process.stdout.splitlines()) == 1 and not process.stderr
                        and any(expected in e for e in result.get("errors", [])))
            results.append({"case": case, "status": result.get("status"), "checker_exit_code": process.returncode,
                            "expected_error_fragment": expected, "target_detected": detected, "errors": result.get("errors", [])})
        finally:
            resolved = temporary.resolve()
            assert resolved.parent == parent and resolved.name.startswith("a3-negative-")
            assert not temporary.is_symlink() and not (getattr(temporary.lstat(), "st_file_attributes", 0) & 0x400)
            shutil.rmtree(temporary)
    output = {"status": "PASS" if all(r["target_detected"] for r in results) else "FAIL", "cases": results,
              "temporary_copies_removed": True, "model_calls": 0}
    save(ROOT / "authoring/negative-test-results.json", output)
    print(json.dumps(output, ensure_ascii=False, separators=(",", ":")))
    return int(output["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
