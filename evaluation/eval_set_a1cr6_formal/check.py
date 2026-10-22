"""Offline structural checker for the sealed A1cr6 route-only retest set.

Adapted from eval_set_a1cy_dev/check.py. This module has no product imports,
network access, model calls, or evaluation execution. Errors contain codes and
validated identifiers only; source prose and question text are never printed.
"""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata


ROOT = Path(__file__).resolve().parent
REPOSITORY = ROOT.parents[1]
BASELINE = REPOSITORY / "evaluation" / "eval_set_a1c5_formal"
ROUTES = ("ask", "fix_issue", "recap", "check_passage", "out_of_scope")
PAGES = {"writing", "chapters", "materials", "plan", "overview"}
WORKS = ("w01", "w02")
BUTTONS = ("写前回顾", "帮我改这一处", "检查这段", "查前文矛盾")
REQUIRED_FIELDS = {"id", "work", "suite", "note", "input", "context", "expected_route", "why"}
EXPECTED_COUNTS = {"ask": 5, "fix_issue": 3, "recap": 3, "check_passage": 3, "out_of_scope": 1}
FILES = {"README.md", "check.py", "set.sha256", "tasks.json", "works/w01.md", "works/w02.md"}
ROUTE_ID = re.compile(r"a1cr6-w0[12]-route-(?:0[1-9]|1[0-5])\Z")
SUPPORT_ID = re.compile(r"a1c5f-w0[12]-fix-\d{2}\Z")


def normalize(value):
    """Remove all Unicode whitespace and punctuation, keeping other symbols."""
    return "".join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith("P"))


def canonical(value):
    # Unlike Python equality, JSON equality distinguishes true from 1.
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def sentence_selection(selection, body):
    if not isinstance(selection, str) or not selection or not isinstance(body, str):
        return False
    if selection not in body or not re.search(r"[。！？][”’\"']?\s*\Z", selection):
        return False
    start = body.find(selection)
    before = body[:start].rstrip()
    return not before or bool(re.search(r"[。！？][”’\"']?\Z", before))


def is_ambiguous(task):
    why = task.get("why")
    return isinstance(why, str) and any(marker in why for marker in ("拿不准", "歧义"))


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate_key")
        result[key] = value
    return result


def validate(root=ROOT):
    root = Path(root).resolve()
    errors = []

    def require(ok, code):
        if not ok:
            errors.append(code)
        return bool(ok)

    def load_json(path, code):
        try:
            value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=unique_object)
        except (OSError, UnicodeError, ValueError):
            errors.append(code)
            return {}
        if not isinstance(value, dict):
            errors.append(code + ":object")
            return {}
        return value

    def read_bytes(path, code):
        try:
            return path.read_bytes()
        except OSError:
            errors.append(code)
            return None

    present = set()
    if require(root.is_dir(), "structure:root"):
        for index, path in enumerate(sorted(root.rglob("*"))):
            name = path.relative_to(root).as_posix()
            if path.is_symlink():
                errors.append("structure:symlink:" + str(index))
                continue
            # Python's normal module execution may create this cache directory.
            if name == "__pycache__" and path.is_dir():
                continue
            if path.parent == root / "__pycache__" and path.is_file() and path.suffix == ".pyc":
                continue
            if path.is_dir():
                require(name == "works", "structure:directory:" + str(index))
            elif path.is_file():
                present.add(name)
        require(present == FILES, "structure:files")

    manifest_checked = 0
    manifest_names = []
    manifest = read_bytes(root / "set.sha256", "manifest:read")
    if manifest is not None:
        try:
            lines = manifest.decode("utf-8").splitlines()
        except UnicodeError:
            errors.append("manifest:encoding")
            lines = []
        for index, line in enumerate(lines, 1):
            match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
            if not require(match is not None, "manifest:format:" + str(index)):
                continue
            digest, name = match.groups()
            manifest_names.append(name)
            if not require(name in {"tasks.json", "works/w01.md", "works/w02.md"}, "manifest:path:" + str(index)):
                continue
            path = root / name
            if not require(path.resolve().is_relative_to(root), "manifest:escape:" + str(index)):
                continue
            content = read_bytes(path, "manifest:file:" + str(index))
            if content is not None:
                manifest_checked += 1
                require(hashlib.sha256(content).hexdigest() == digest, "manifest:digest:" + str(index))
        require(manifest_names == ["tasks.json", "works/w01.md", "works/w02.md"], "manifest:coverage")

    baseline = load_json(BASELINE / "tasks.json", "baseline:tasks")
    data = load_json(root / "tasks.json", "tasks:json")
    require(set(data) == {"version", "set_id", "author", "works", "tasks"}, "tasks:top_fields")
    require(data.get("version") == "a1c-1", "tasks:version")
    require(data.get("set_id") == "a1cr6-formal", "tasks:set_id")
    require(data.get("author") == "evaluation authoring", "tasks:author")

    works_list = data.get("works")
    works = {}
    if require(isinstance(works_list, list), "works:list"):
        require(len(works_list) == 2, "works:count")
        require(canonical(works_list) == canonical(baseline.get("works")), "works:metadata_copy")
        for index, work in enumerate(works_list):
            if not require(isinstance(work, dict), "works:object:" + str(index)):
                continue
            key = work.get("key")
            if require(isinstance(key, str) and key in WORKS, "works:key:" + str(index)):
                require(key not in works, "works:duplicate:" + key)
                works[key] = work
    require(set(works) == set(WORKS), "works:keys")
    copied_works = 0
    for wk in WORKS:
        actual = read_bytes(root / "works" / (wk + ".md"), "works:read:" + wk)
        original = read_bytes(BASELINE / "works" / (wk + ".md"), "baseline:work:" + wk)
        equal = actual is not None and original is not None and actual == original
        copied_works += int(equal)
        require(equal, "works:byte_copy:" + wk)

    baseline_tasks = baseline.get("tasks", [])
    if not require(isinstance(baseline_tasks, list), "baseline:task_list"):
        baseline_tasks = []
    original_fix = {t["id"]: t for t in baseline_tasks if isinstance(t, dict)
                    and t.get("suite") == "fix" and isinstance(t.get("id"), str)}
    tasks = data.get("tasks")
    if not require(isinstance(tasks, list), "tasks:list"):
        tasks = []
    ids = set()
    support = {}
    route_tasks = []
    for index, task in enumerate(tasks):
        code = "task:" + str(index + 1)
        if not require(isinstance(task, dict), code + ":object"):
            continue
        tid = task.get("id")
        valid_id = isinstance(tid, str) and (ROUTE_ID.fullmatch(tid) or SUPPORT_ID.fullmatch(tid))
        require(bool(valid_id), code + ":id")
        if valid_id:
            code = tid
            require(tid not in ids, code + ":duplicate")
            ids.add(tid)
        wk = task.get("work")
        require(isinstance(wk, str) and wk in WORKS, code + ":work")
        if task.get("suite") == "fix":
            require(task.get("support") is True, code + ":support_flag")
            old = original_fix.get(tid) if isinstance(tid, str) else None
            copy = {k: v for k, v in task.items() if k != "support"}
            require(old is not None and canonical(copy) == canonical(old), code + ":support_copy")
            if isinstance(tid, str):
                support[tid] = task
            continue
        if not require(task.get("suite") == "route", code + ":suite"):
            continue
        route_tasks.append((task, code))
        require(REQUIRED_FIELDS <= set(task) <= REQUIRED_FIELDS | {"also_acceptable"}, code + ":fields")
        require(isinstance(tid, str) and bool(ROUTE_ID.fullmatch(tid))
                and isinstance(wk, str) and tid.startswith("a1cr6-" + wk + "-route-"), code + ":route_id")
        for field in ("note", "why"):
            require(isinstance(task.get(field), str) and bool(task[field].strip()), code + ":" + field)
        text = task.get("input")
        require(isinstance(text, str) and 4 <= len(text) <= 60 and bool(normalize(text)), code + ":input")
        route = task.get("expected_route")
        require(isinstance(route, str) and route in ROUTES, code + ":expected_route")
        if "also_acceptable" in task:
            acceptable = task["also_acceptable"]
            require(isinstance(acceptable, list) and len(acceptable) <= 1
                    and all(isinstance(value, str) and value in ROUTES and value != route for value in acceptable),
                    code + ":also_acceptable")
        context = task.get("context")
        if not require(isinstance(context, dict), code + ":context"):
            continue
        require({"page"} <= set(context) <= {"page", "selection", "issue_from"}, code + ":context_fields")
        require(isinstance(context.get("page"), str) and context["page"] in PAGES, code + ":page")
        if "selection" in context or "issue_from" in context:
            require(context.get("page") == "writing", code + ":writing_context")
        if "selection" in context:
            selection = context["selection"]
            work = works.get(wk, {}) if isinstance(wk, str) else {}
            draft = work.get("shared_draft", {})
            body = draft.get("body", "") if isinstance(draft, dict) else ""
            require(sentence_selection(selection, body), code + ":selection")
        if route == "fix_issue":
            require("issue_from" in context, code + ":fix_requires_issue")
        if route == "check_passage":
            require("selection" in context, code + ":check_requires_selection")

    referenced = set()
    for task, code in route_tasks:
        context = task.get("context")
        if not isinstance(context, dict) or "issue_from" not in context:
            continue
        reference = context["issue_from"]
        fixture = support.get(reference) if isinstance(reference, str) else None
        require(fixture is not None and fixture.get("support") is True and fixture.get("suite") == "fix"
                and fixture.get("work") == task.get("work"), code + ":issue_from")
        if isinstance(reference, str):
            referenced.add(reference)
    require(set(support) == referenced, "support:referenced_only")

    per_work = {}
    for wk in WORKS:
        own = [task for task, _ in route_tasks if task.get("work") == wk]
        expected_ids = {f"a1cr6-{wk}-route-{index:02d}" for index in range(1, 16)}
        actual_ids = {task.get("id") for task in own if isinstance(task.get("id"), str)}
        require(actual_ids == expected_ids and len(own) == 15, wk + ":route_ids")
        counts = {route: sum(task.get("expected_route") == route for task in own) for route in ROUTES}
        require(counts == EXPECTED_COUNTS, wk + ":route_distribution")
        acceptable_count = sum("also_acceptable" in task for task in own)
        require(acceptable_count <= 2, wk + ":acceptable_count")
        suggestions = sum(task.get("expected_route") == "ask" and not is_ambiguous(task)
                          and "建议" in task.get("note", "")
                          for task in own if isinstance(task.get("note"), str))
        ambiguous = sum(task.get("expected_route") == "ask" and is_ambiguous(task) for task in own)
        require(suggestions >= 1, wk + ":ask_suggestion")
        require(ambiguous == 1, wk + ":ambiguous_ask")
        nonwriting_recap = sum(task.get("expected_route") == "recap"
                              and isinstance(task.get("context"), dict)
                              and isinstance(task["context"].get("page"), str)
                              and task["context"].get("page") in PAGES - {"writing"} for task in own)
        require(nonwriting_recap >= 2, wk + ":nonwriting_recap")
        repairs = sum(task.get("expected_route") == "check_passage"
                      and isinstance(task.get("context"), dict) and "issue_from" not in task["context"]
                      and any(word in task.get("input", "") for word in ("改", "问题", "报错", "错"))
                      for task in own if isinstance(task.get("input"), str))
        require(repairs >= 1, wk + ":repair_without_issue")
        groups = defaultdict(list)
        for task in own:
            if isinstance(task.get("input"), str):
                groups[task["input"]].append(task)
        paired = sum(any(a.get("expected_route") != b.get("expected_route")
                         and canonical(a.get("context")) != canonical(b.get("context"))
                         for i, a in enumerate(group) for b in group[i + 1:]) for group in groups.values())
        require(paired >= 2, wk + ":same_input_groups")
        nonbuttons = sum(not any(button in task["input"] for button in BUTTONS)
                         for task in own if isinstance(task.get("input"), str))
        require(nonbuttons * 2 >= len(own), wk + ":non_button_inputs")
        per_work[wk] = {"route": len(own), "routes": counts,
                        "regular_ask": counts["ask"] - ambiguous, "ambiguous_ask": ambiguous,
                        "ask_suggestion": suggestions, "support": sum(t.get("work") == wk for t in support.values()),
                        "also_acceptable": acceptable_count, "same_input_groups": paired,
                        "non_button_inputs": nonbuttons, "nonwriting_recap": nonwriting_recap,
                        "repair_without_issue": repairs}

    old_inputs = []
    novelty_files = 0
    for index, path in enumerate(sorted((REPOSITORY / "evaluation").rglob("tasks.json"))):
        # Never compare new items with this set, including validate(temp_copy).
        if path.resolve() in {(ROOT / "tasks.json").resolve(), (root / "tasks.json").resolve()}:
            continue
        old = load_json(path, "novelty:json:" + str(index + 1))
        old_tasks = old.get("tasks")
        if not require(isinstance(old_tasks, list), "novelty:tasks:" + str(index + 1)):
            continue
        selected = [task for task in old_tasks if isinstance(task, dict)
                    and (path.resolve() == (BASELINE / "tasks.json").resolve() or task.get("suite") == "route")
                    and isinstance(task.get("input"), str)]
        if selected:
            novelty_files += 1
            old_inputs.extend(normalize(task["input"]) for task in selected)
    novelty_errors = 0
    for task, code in route_tasks:
        if not isinstance(task.get("input"), str):
            continue
        current = normalize(task["input"])
        exact = current in old_inputs
        similar = not exact and any(SequenceMatcher(None, current, old).ratio() >= 0.8 for old in old_inputs)
        if exact or similar:
            novelty_errors += 1
            errors.append(code + (":novelty_exact" if exact else ":novelty_similarity"))
    return {"status": "FAIL" if errors else "PASS", "works": len(works), "tasks": len(tasks),
            "route": len(route_tasks), "support": len(support), "per_work": per_work,
            "manifest_files": manifest_checked, "byte_identical_works": copied_works,
            "novelty_source_files": novelty_files, "novelty_reference_inputs": len(old_inputs),
            "novelty_checked_inputs": sum(isinstance(task.get("input"), str) for task, _ in route_tasks),
            "novelty_errors": novelty_errors, "error_count": len(errors), "errors": errors,
            "model_calls": 0, "evaluation_runs": 0, "semantic_acceptance": False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT, help="Validate a temporary set copy against the original repository.")
    args = parser.parse_args()
    try:
        result = validate(args.root)
    except Exception as exc:
        # Even malformed nested values must produce one redacted JSON line.
        result = {"status": "FAIL", "error_count": 1, "errors": ["checker:internal:" + type(exc).__name__],
                  "model_calls": 0, "evaluation_runs": 0}
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
