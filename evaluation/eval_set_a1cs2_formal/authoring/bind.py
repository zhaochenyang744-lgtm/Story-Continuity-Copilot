"""Bind literal, manually authored cases to exact source titles and positions.

No prose/question generation and no other set reads. This validates locators,
copy distances and hash bindings, then serializes the existing manually written
strings into the delivery schema.
"""
from pathlib import Path
import copy
import hashlib
import importlib.util
import json
import re

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    data = read(ROOT / "tasks.json")
    work = data["works"][0]
    design = read(ROOT / "authoring/task-design.json")["tasks"]
    assert sorted(t["n"] for t in design) == list(range(1, 13)), "case_count"
    path = ROOT / work["source_file"]
    source = path.read_text(encoding="utf-8")
    parts = re.split(r"^# (.+)$", source, flags=re.M)
    assert len(parts) == 25, "source_not_complete"
    titles = {n: parts[n * 2 - 1] for n in range(1, 13)}
    bodies = {n: parts[n * 2].strip() for n in range(1, 13)}
    spec = importlib.util.spec_from_file_location("this_checker", ROOT / "check.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    tasks, records = [], []
    for entry in sorted(design, key=lambda t: t["n"]):
        task = {k: copy.deepcopy(v) for k, v in entry.items() if k not in {"n", "chapters", "quotes", "rationale", "metadata", "injection_chapter"}}
        task.update(id=f"a1cs2f-safe-{entry['n']:02}", work=work["key"])
        task["evidence_chapters"] = [titles[n] for n in entry["chapters"]]
        task["evidence_quotes"] = entry["quotes"]
        if "injection_chapter" in entry:
            task["injection"]["location"] = titles[entry["injection_chapter"]]
        assert len(entry["chapters"]) == len(entry["quotes"])
        positions = []
        reference = set()
        for n, q in zip(entry["chapters"], entry["quotes"]):
            body = bodies[n]
            matches = list(re.finditer("(?=" + re.escape(q) + ")", body))
            first = HAN.search(q)
            assert len(matches) == 1 and first and 10 <= len(q) <= 60, task["id"] + ":quote"
            positions.append(len(HAN.findall(body[:matches[0].start() + first.start()])) + 1)
            reference |= checker.grams(body, work["names"])
        assert task["deep"] is any(p > 1500 for p in positions), task["id"] + ":deep"
        location, instruction = task["injection"]["location"], task["injection"]["text"]
        if location in {"fact", "plan"}:
            containers = [f["value"] for f in work["extra_facts"]] if location == "fact" else [p["text"] for p in work["plans"]]
            for container in containers:
                reference |= checker.grams(container.replace(instruction, ""), work["names"])
        fields = {k: task[k] for k in ("question", "draft", "selection", "draft_opening") if k in task}
        if "conflict_sentence" not in task:
            fields["shared_draft"] = work["shared_draft"]["body"]
        for field, value in fields.items():
            assert not checker.grams(value, work["names"]) & reference, task["id"] + ":copy:" + field
        records.append({"id": task["id"], "rationale": entry["rationale"], "copy_check": "pass", "evidence_han_positions": positions, "evidence_metadata": entry.get("metadata", [])})
        tasks.append(task)
    data["tasks"] = tasks
    write(ROOT / "tasks.json", data)
    source_hash = hashlib.sha256(path.read_bytes()).hexdigest()
    task_hash = hashlib.sha256((ROOT / "tasks.json").read_bytes()).hexdigest()
    independent_path = ROOT / "authoring/independent-review.json"
    independent = {"reviewer_not_author": True, "status": "pending", "findings": []}
    if independent_path.exists():
        independent = read(independent_path)
        assert independent["reviewed_source_sha256"] == source_hash, "review_source_binding"
        assert independent["reviewed_tasks_sha256"] == task_hash, "review_task_binding"
    review = {"set_id": data["set_id"], "characters": work["names"][:6], "tasks": records, "independent_review": independent}
    write(ROOT / "authoring/self-review.json", review)
    files = sorted(["tasks.json"] + [p.relative_to(ROOT).as_posix() for p in (ROOT / "works").rglob("*") if p.is_file()])
    (ROOT / "set.sha256").write_text("".join(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() + "  " + p + "\n" for p in files), encoding="utf-8", newline="\n")
    print(json.dumps({"bound_tasks": len(tasks), "manifest_entries": len(files), "independent_status": independent["status"]}))


if __name__ == "__main__":
    main()
