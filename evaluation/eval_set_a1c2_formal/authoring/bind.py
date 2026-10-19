"""Bind manually written task data to actual chapter titles and quote positions.

No prose or question generation. All strings come unchanged from lead-authored
JSON. This authoring-only utility validates locators, checks copy rules and
serializes the delivery schema. It never reads another dataset.
"""
import copy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def main():
    data = read(ROOT / "tasks.json")
    design = read(ROOT / "authoring/task-design.json")
    work_review = read(ROOT / "authoring/work-design.json")
    spec = importlib.util.spec_from_file_location("local_checker", ROOT / "check.py")
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    tasks, reviews, hashes = [], [], {}
    private_fields = {"n", "chapters", "quotes", "first_chapters", "first_quotes", "rationale", "necessity"}
    for work in data["works"]:
        wk = work["key"]
        source_path = ROOT / work["source_file"]
        source = source_path.read_text(encoding="utf-8")
        parts = re.split(r"^# (.+)$", source, flags=re.M)
        assert len(parts) == 61, wk + ":source_not_complete"
        titles = {n: parts[n * 2 - 1] for n in range(1, 31)}
        bodies = {n: parts[n * 2].strip() for n in range(1, 31)}
        hashes[wk] = hashlib.sha256(source_path.read_bytes()).hexdigest()

        def quotes(numbers, texts):
            assert len(numbers) == len(texts)
            result = []
            for n, q in zip(numbers, texts):
                body = bodies[n]
                starts = list(re.finditer("(?=" + re.escape(q) + ")", body))
                assert len(starts) == 1 and 10 <= len(q) <= 60, f"{wk}:quote:{n}"
                first = HAN.search(q)
                position = len(HAN.findall(body[:starts[0].start() + first.start()])) + 1
                result.append({"chapter": titles[n], "text": q, "han_position": position})
            return result

        for entry in design[wk]:
            tid = f"a1c2f-{wk}-{entry['n']:02}"
            task = {k: copy.deepcopy(v) for k, v in entry.items() if k not in private_fields}
            task.update(id=tid, work=wk)
            task["evidence_chapters"] = [titles[n] for n in entry["chapters"]]
            task["evidence_quotes"] = entry["quotes"]
            if task["suite"] == "recap":
                for mention in task["must_mention"]:
                    mention["evidence_chapters"] = [titles[n] for n in mention.pop("chapters")]
            qrecords = quotes(entry["chapters"], entry["quotes"])
            record = {"id": tid, "rationale": entry["rationale"], "evidence_quotes": qrecords}
            if task.get("paraphrased"):
                record["paraphrase"] = {"source": " / ".join(entry["quotes"]), "question": task["question"]}
            if task.get("qa_type") == "answerable_multi":
                record["multi_chapter_necessity"] = entry["necessity"]
            evidence_numbers = list(entry["chapters"])
            if task["suite"] == "follow_up":
                record["first_evidence_chapters"] = [titles[n] for n in entry["first_chapters"]]
                record["first_evidence_quotes"] = quotes(entry["first_chapters"], entry["first_quotes"])
                evidence_numbers.extend(entry["first_chapters"])
            reference = set().union(*(checker.grams(bodies[n], work["names"]) for n in evidence_numbers))
            fields = {k: task[k] for k in ("question", "first_question", "selection", "draft", "draft_opening") if k in task}
            if task["suite"] in {"qa", "follow_up"}:
                fields["shared_draft"] = work["shared_draft"]["body"]
            for name, value in fields.items():
                assert not checker.grams(value, work["names"]) & reference, tid + ":copy:" + name
            record["copy_check"] = "pass"
            tasks.append(task)
            reviews.append(record)
    data["tasks"] = tasks
    write(ROOT / "tasks.json", data)
    task_hash = hashlib.sha256((ROOT / "tasks.json").read_bytes()).hexdigest()
    independent = {"reviewer_not_author": True, "status": "pending", "findings": []}
    independent_path = ROOT / "authoring/independent-review.json"
    if independent_path.exists():
        independent = read(independent_path)
        assert independent["reviewed_source_sha256"] == hashes, "review:source_binding"
        assert independent["reviewed_tasks_sha256"] == task_hash, "review:task_binding"
    review = {"set_id": data["set_id"], "tasks": reviews, "works": work_review, "independent_review": independent}
    write(ROOT / "authoring/self-review.json", review)
    files = sorted(["tasks.json"] + [p.relative_to(ROOT).as_posix() for p in (ROOT / "works").rglob("*") if p.is_file()])
    manifest = "".join(hashlib.sha256((ROOT / p).read_bytes()).hexdigest() + "  " + p + "\n" for p in files)
    (ROOT / "set.sha256").write_text(manifest, encoding="utf-8", newline="\n")
    print(json.dumps({"bound_tasks": len(tasks), "manifest_entries": len(files), "independent_status": independent["status"]}))


if __name__ == "__main__":
    main()
