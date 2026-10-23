"""Offline A2 development-set structure, evidence, copy and integrity checks.

No product imports, network access or model calls. Novelty reads only historical
tasks.json files in this checkout, pruning the explicitly prohibited sets before
descent. The checker never treats static PASS as a semantic or model verdict.
"""
from __future__ import annotations

from collections import Counter
import difflib
import hashlib
import json
import os
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
EVALUATION_ROOT = ROOT.parent
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
HEADING = re.compile(r"^# (第([1-9][0-9]*)章 [^\r\n]+)$", re.MULTILINE)
PAGES = {"writing", "chapters", "materials", "plan", "overview"}
ROUTES = {"ask", "fix_issue", "recap", "check_passage", "out_of_scope", "change"}
KINDS = {"add_fact", "change_fact", "resolve_thread"}
MEMORY_TYPES = {"static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread"}
THREAD_STATUSES = {"planned", "planted", "developing", "resolved", "abandoned"}
FIX_CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge", "timeline", "event_status", "location_action", "world_rule"}
EXCLUDED_SETS = {
    "eval_set_a1_reserve", "eval_set_a1b_reserve", "eval_set_v13_authoring",
    "eval_set_a2_dev", "eval_set_a2_formal", "eval_set_a2s_formal",
}
REQUIRED_FILES = {
    "README.md", "works/w01.md", "materials/w01-facts.json", "materials/w01-foreshadows.json",
    "tasks.json", "set.sha256", "check.py", "authoring/self-review.md", "authoring/self-review.json",
}


def han_count(value):
    return len(HAN.findall(value))


def grams(value, names):
    """Punctuation is ignored; a proper name is a boundary, not a splice."""
    normalized = "".join(HAN.findall(value))
    for name in sorted(names, key=len, reverse=True):
        token = "".join(HAN.findall(name))
        if token:
            normalized = normalized.replace(token, "|")
    return {part[i:i + 8] for part in normalized.split("|") for i in range(len(part) - 7)}


def normalize_input(value):
    return "".join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith("P"))


def legacy_inputs(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {"input", "question", "request"} and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list)):
                yield from legacy_inputs(item)
    elif isinstance(value, list):
        for item in value:
            yield from legacy_inputs(item)


def is_link(path):
    # Windows junctions/reparse directories must not make traversal cross scope.
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


class Audit:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.errors = []
        self.copy_errors = []
        self.positions = []
        self.unique_positions = {}

    def require(self, ok, label):
        if not ok and label not in self.errors:
            self.errors.append(label)
        return bool(ok)

    def text(self, value, low=1, high=None):
        return isinstance(value, str) and bool(value.strip()) and len(value) >= low and (high is None or len(value) <= high)

    def member(self, value, choices):
        return isinstance(value, str) and value in choices

    def index(self, value, maximum):
        return type(value) is int and 1 <= value <= maximum

    def fields(self, value, required, optional, label):
        if not self.require(isinstance(value, dict), label + ":object"):
            return False
        self.require(set(required) <= value.keys(), label + ":missing_fields")
        self.require(value.keys() <= set(required) | set(optional), label + ":unknown_fields")
        return True

    def path(self, relative, label):
        if not self.require(isinstance(relative, str) and bool(relative) and "\\" not in relative, label + ":relative_path"):
            return None
        candidate = self.root / relative
        if not self.require(not Path(relative).is_absolute() and ".." not in Path(relative).parts, label + ":path_boundary"):
            return None
        if not self.require(candidate.resolve().is_relative_to(self.root), label + ":path_boundary"):
            return None
        current = self.root
        try:
            for part in Path(relative).parts:
                current = current / part
                if current.exists() and is_link(current):
                    self.require(False, label + ":reparse_point")
                    return None
        except OSError:
            self.require(False, label + ":path_io")
            return None
        return candidate

    def read(self, relative):
        path = self.path(relative, relative)
        if path is None:
            return ""
        try:
            raw = path.read_bytes()
            self.require(not raw.startswith(b"\xef\xbb\xbf"), relative + ":bom")
            self.require(b"\r" not in raw, relative + ":line_endings")
            return raw.decode("utf-8")
        except (OSError, UnicodeError):
            self.require(False, relative + ":read_utf8")
            return ""

    def load(self, relative, expected):
        try:
            value = json.loads(self.read(relative))
        except (ValueError, RecursionError):
            self.require(False, relative + ":json")
            return expected()
        return value if self.require(isinstance(value, expected), relative + ":type") else expected()

    def quote(self, chapter, quote, chapters, numbers, label):
        title = numbers.get(chapter) if type(chapter) is int else chapter if isinstance(chapter, str) else None
        valid_title = isinstance(title, str) and title in chapters
        self.require(valid_title, label + ":chapter")
        if not self.require(self.text(quote, 10, 60), label + ":quote_length") or not valid_title:
            return
        body = chapters[title]
        if self.require(body.count(quote) == 1, label + ":quote_verbatim_unique"):
            position = han_count(body[:body.index(quote)]) + 1
            self.positions.append(position)
            self.unique_positions[(title, quote)] = position

    def finish(self, counts=None):
        self.errors.extend(e for e in self.copy_errors if e not in self.errors)
        return {"status": "FAIL" if self.errors else "PASS", **(counts or {}),
                "copy_errors": len(self.copy_errors), "errors": self.errors,
                "scope": "this_set_and_permitted_historical_inputs", "model_calls": 0,
                "semantic_acceptance": False}


def validate(root=ROOT, evaluation_root=EVALUATION_ROOT):
    audit = Audit(root)
    try:
        return _validate(audit, Path(evaluation_root).resolve())
    except Exception as exc:
        # Malformed authoring data must still give the specified one-line result.
        audit.require(False, "malformed_data:" + type(exc).__name__)
        return audit.finish()


def _validate(audit, evaluation_root):
    root, require = audit.root, audit.require
    for relative in sorted(REQUIRED_FILES):
        path = audit.path(relative, relative)
        require(path is not None and path.is_file(), "structure:" + relative)
    for folder in ("works", "materials", "authoring"):
        require((root / folder).is_dir(), "structure:" + folder)

    # Inventory before reading a manifest, with no descent through links.
    expected_paths = ["tasks.json"]
    for folder in ("works", "materials"):
        start = root / folder
        if not start.is_dir() or is_link(start):
            require(False, "structure:" + folder + ":directory")
            continue
        for base, directories, files in os.walk(start, followlinks=False):
            safe = []
            for name in sorted(directories):
                child = Path(base) / name
                if is_link(child):
                    require(False, "structure:reparse_point")
                else:
                    safe.append(name)
            directories[:] = safe
            for name in sorted(files):
                path = Path(base) / name
                if is_link(path):
                    require(False, "structure:reparse_point")
                else:
                    expected_paths.append(path.relative_to(root).as_posix())
    expected_paths.sort()
    manifest_paths = []
    for line_number, line in enumerate(audit.read("set.sha256").splitlines(), 1):
        match = re.fullmatch(r"([0-9a-f]{64})  ([^\r\n]+)", line)
        if not require(match is not None, "manifest:format:" + str(line_number)):
            continue
        digest, relative = match.groups()
        manifest_paths.append(relative)
        path = audit.path(relative, "manifest")
        require(relative in expected_paths, "manifest:unexpected_file:" + relative)
        if path is not None:
            try:
                require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, "manifest:hash:" + relative)
            except OSError:
                require(False, "manifest:read:" + relative)
    require(manifest_paths == expected_paths, "manifest:sorted_complete_coverage")

    data = audit.load("tasks.json", dict)
    audit.fields(data, {"version", "set_id", "author", "works", "tasks"}, set(), "top")
    require(data.get("version") == "a2-1", "version")
    require(data.get("set_id") == "a2-dev", "set_id")
    require(data.get("author") == "evaluation authoring", "author")
    work_list = data.get("works")
    require(isinstance(work_list, list) and len(work_list) == 1, "works:count")
    work = work_list[0] if isinstance(work_list, list) and work_list and isinstance(work_list[0], dict) else {}
    audit.fields(work, {"key", "title", "language", "source_file", "purpose", "kind", "names", "materials", "shared_draft"}, set(), "work")
    for key, value in {"key": "w01", "language": "zh", "source_file": "works/w01.md", "purpose": "general", "kind": "long"}.items():
        require(work.get(key) == value, "work:" + key)
    require(audit.text(work.get("title")), "work:title")
    names = work.get("names")
    if not require(isinstance(names, list) and all(audit.text(n) for n in names), "work:names"):
        names = []
    require(len(set(names)) == len(names), "work:names_unique")
    materials = work.get("materials")
    require(materials == {"facts": "materials/w01-facts.json", "foreshadows": "materials/w01-foreshadows.json"}, "work:materials")
    draft = work.get("shared_draft")
    if not audit.fields(draft, {"chapter_title", "body"}, set(), "work:shared_draft"):
        draft = {}
    require(audit.text(draft.get("chapter_title")) and bool(re.fullmatch(r"第21章 [^\r\n]+", draft.get("chapter_title", ""))), "draft:chapter_title")
    draft_body = draft.get("body") if isinstance(draft.get("body"), str) else ""
    draft_length = han_count(draft_body)
    require(600 <= draft_length <= 1000, "draft:han_length")

    source = audit.read("works/w01.md")
    headings = list(HEADING.finditer(source))
    require(source.startswith("# 第1章 "), "chapters:first_heading")
    require(len(headings) == len(re.findall(r"^# ", source, re.MULTILINE)) == 20, "chapters:count_and_format")
    require([int(m[2]) for m in headings] == list(range(1, 21)), "chapters:sequential_numbers")
    chapters, numbers = {}, {}
    for i, match in enumerate(headings):
        title = match[1]
        require(title not in chapters, "chapters:duplicate_title")
        chapters[title] = source[match.end():headings[i + 1].start() if i + 1 < len(headings) else len(source)]
        numbers[int(match[2])] = title
    chapter_lengths = {title: han_count(body) for title, body in chapters.items()}
    for title, length in chapter_lengths.items():
        require(2500 <= length <= 3500, "chapter:han_length:" + title.split(" ")[0])
    for name in names:
        require(name in source or name in draft_body, "work:name_not_in_text:" + name)

    facts = audit.load("materials/w01-facts.json", list)
    threads = audit.load("materials/w01-foreshadows.json", list)
    require(25 <= len(facts) <= 40, "facts:count")
    require(8 <= len(threads) <= 12, "foreshadows:count")
    fact_pairs = set()
    for i, fact in enumerate(facts, 1):
        label = "fact:" + str(i)
        if not audit.fields(fact, {"memory_type", "subject", "predicate", "value", "chapter"}, set(), label):
            continue
        require(audit.member(fact.get("memory_type"), MEMORY_TYPES), label + ":memory_type")
        for field, maximum in (("subject", 20), ("predicate", 20), ("value", 60)):
            require(audit.text(fact.get(field), 1, maximum), label + ":" + field)
        require(audit.index(fact.get("chapter"), 20), label + ":chapter")
        if isinstance(fact.get("subject"), str) and isinstance(fact.get("predicate"), str):
            pair = (fact["subject"], fact["predicate"])
            require(pair not in fact_pairs, label + ":duplicate_subject_predicate")
            fact_pairs.add(pair)
    statuses = Counter()
    titles = set()
    for i, thread in enumerate(threads, 1):
        label = "foreshadow:" + str(i)
        if not audit.fields(thread, {"title", "description", "status", "planted_chapter"}, {"resolved_chapter"}, label):
            continue
        require(audit.text(thread.get("title"), 1, 30), label + ":title")
        if isinstance(thread.get("title"), str):
            require(thread["title"] not in titles, label + ":duplicate_title")
            titles.add(thread["title"])
        require(audit.text(thread.get("description"), 20, 200), label + ":description")
        status = thread.get("status")
        require(audit.member(status, THREAD_STATUSES), label + ":status")
        if isinstance(status, str):
            statuses[status] += 1
        planted = thread.get("planted_chapter")
        require(audit.index(planted, 20), label + ":planted_chapter")
        if status == "resolved":
            resolved = thread.get("resolved_chapter")
            require(audit.index(resolved, 20) and audit.index(planted, 20) and resolved >= planted, label + ":resolved_chapter")
        else:
            require("resolved_chapter" not in thread, label + ":unexpected_resolved_chapter")
    require(statuses["resolved"] >= 1, "foreshadows:resolved_min")
    require(statuses["planted"] + statuses["developing"] >= 4, "foreshadows:open_status_min")

    review = audit.load("authoring/self-review.json", dict)
    characters = review.get("characters")
    if not require(isinstance(characters, list), "review:characters:array"):
        characters = []
    require(len(characters) >= 8, "review:characters:min")
    character_names, all_aliases = set(), set()
    characters_with_aliases = 0
    for i, character in enumerate(characters, 1):
        label = "review:character:" + str(i)
        if not audit.fields(character, {"name", "aliases"}, set(), label):
            continue
        name, aliases = character.get("name"), character.get("aliases")
        if require(audit.text(name), label + ":name"):
            require(name not in character_names, label + ":duplicate_name")
            character_names.add(name)
            require(name in names and name in source, label + ":name_registered_and_in_source")
        if not require(isinstance(aliases, list) and all(audit.text(a) for a in aliases), label + ":aliases"):
            continue
        characters_with_aliases += bool(aliases)
        require(len(set(aliases)) == len(aliases), label + ":duplicate_alias")
        for alias in aliases:
            require(alias != name and alias not in all_aliases, label + ":alias_distinct")
            require(alias in names and alias in source, label + ":alias_registered_and_in_source")
            all_aliases.add(alias)
    require(len(character_names) >= 8, "review:characters:distinct_min")
    require(characters_with_aliases >= 3, "review:characters:with_aliases_min")
    require(not character_names & all_aliases, "review:characters:aliases_are_not_other_people")
    for name in ("stale_facts", "missing_facts", "resolved_unmarked", "same_input_groups"):
        require(isinstance(review.get(name), list), "review:" + name + ":array")
    stale_list = review.get("stale_facts") if isinstance(review.get("stale_facts"), list) else []
    missing_list = review.get("missing_facts") if isinstance(review.get("missing_facts"), list) else []
    resolved_list = review.get("resolved_unmarked") if isinstance(review.get("resolved_unmarked"), list) else []
    require(len(stale_list) >= 5, "review:stale_min")
    require(len(missing_list) >= 6, "review:missing_min")
    require(len(resolved_list) >= 4, "review:resolved_unmarked_min")
    stale_ids, missing_pairs, resolved_ids = set(), set(), set()
    for i, item in enumerate(stale_list, 1):
        label = "review:stale:" + str(i)
        if not audit.fields(item, {"fact", "changed_chapter", "quote"}, set(), label):
            continue
        fact_id = item.get("fact")
        if require(audit.index(fact_id, len(facts)), label + ":fact_index"):
            require(fact_id not in stale_ids, label + ":duplicate_fact")
            stale_ids.add(fact_id)
            old = facts[fact_id - 1]
            old_chapter = old.get("chapter") if isinstance(old, dict) else None
            require(audit.index(item.get("changed_chapter"), 20) and audit.index(old_chapter, 20)
                    and item["changed_chapter"] > old_chapter, label + ":later_change")
        audit.quote(item.get("changed_chapter"), item.get("quote"), chapters, numbers, label)
    for i, item in enumerate(missing_list, 1):
        label = "review:missing:" + str(i)
        if not audit.fields(item, {"subject", "predicate", "chapter", "quote"}, set(), label):
            continue
        valid = all(require(audit.text(item.get(f), 1, 20), label + ":" + f) for f in ("subject", "predicate"))
        if valid:
            pair = (item["subject"], item["predicate"])
            require(pair not in fact_pairs, label + ":already_in_facts")
            require(pair not in missing_pairs, label + ":duplicate_missing")
            missing_pairs.add(pair)
        require(audit.index(item.get("chapter"), 20), label + ":chapter_number")
        audit.quote(item.get("chapter"), item.get("quote"), chapters, numbers, label)
    for i, item in enumerate(resolved_list, 1):
        label = "review:resolved:" + str(i)
        if not audit.fields(item, {"foreshadow", "chapter", "quote"}, set(), label):
            continue
        thread_id = item.get("foreshadow")
        if require(audit.index(thread_id, len(threads)), label + ":foreshadow_index"):
            require(thread_id not in resolved_ids, label + ":duplicate_foreshadow")
            resolved_ids.add(thread_id)
            thread = threads[thread_id - 1]
            require(isinstance(thread, dict) and thread.get("status") in {"planted", "developing"}, label + ":unresolved_record")
            planted = thread.get("planted_chapter") if isinstance(thread, dict) else None
            require(audit.index(item.get("chapter"), 20) and audit.index(planted, 20)
                    and item["chapter"] >= planted, label + ":resolution_after_planting")
        audit.quote(item.get("chapter"), item.get("quote"), chapters, numbers, label)
    # At least three open records remain genuinely unresolved in the author ledger.
    remaining_open = sum(isinstance(t, dict) and t.get("status") in {"planted", "developing"}
                         and i not in resolved_ids for i, t in enumerate(threads, 1))
    require(remaining_open >= 3, "foreshadows:still_unresolved_min")

    raw_tasks = data.get("tasks")
    if not require(isinstance(raw_tasks, list), "tasks:array"):
        raw_tasks = []
    tasks = [t for t in raw_tasks if isinstance(t, dict)]
    require(len(tasks) == len(raw_tasks), "tasks:objects")
    ids = {}
    for i, task in enumerate(tasks, 1):
        tid = task.get("id")
        if require(audit.text(tid) and tid.startswith("a2d-"), "task:" + str(i) + ":id"):
            require(tid not in ids, "task:duplicate_id:" + tid)
            ids[tid] = task
    reference_grams = set().union(*(grams(body, names) for body in chapters.values())) if chapters else set()
    suites, primary_kinds, action_kinds, no_types, routes = Counter(), Counter(), Counter(), Counter(), Counter()
    action_pages = set()
    multi_actions = paraphrased = vague = acceptable_count = 0
    input_records = []
    route_tasks = []
    colloquial_change = ask_like_change = 0
    all_action_targets = []

    def copy_check(value, label):
        if isinstance(value, str) and grams(value, names) & reference_grams:
            audit.copy_errors.append("copy:" + label)

    def evidence(item, label):
        refs, quotes = item.get("evidence_chapters"), item.get("evidence_quotes")
        if not require(isinstance(refs, list) and isinstance(quotes, list) and 1 <= len(refs) == len(quotes), label + ":evidence_alignment"):
            return
        for j, (chapter, quote) in enumerate(zip(refs, quotes), 1):
            audit.quote(chapter, quote, chapters, numbers, label + ":evidence:" + str(j))

    for i, task in enumerate(tasks, 1):
        tid = task.get("id") if isinstance(task.get("id"), str) else "task:" + str(i)
        suite = task.get("suite")
        if isinstance(suite, str):
            suites[suite] += 1
        require(task.get("work") == "w01", tid + ":work")
        require(audit.member(suite, {"action", "no_action", "route", "fix"}), tid + ":suite")
        if suite == "fix":
            require(task.get("support") is True, tid + ":support_fix_required")
            require(audit.text(task.get("draft"), 1, 200), tid + ":draft")
            require(audit.text(task.get("conflict_sentence")) and isinstance(task.get("draft"), str)
                    and task["conflict_sentence"] in task["draft"], tid + ":conflict_sentence")
            require(audit.member(task.get("category"), FIX_CATEGORIES), tid + ":category")
            require(audit.text(task.get("fix_idea")), tid + ":fix_idea")
            refs = task.get("evidence_chapters")
            require(isinstance(refs, list) and bool(refs) and all(isinstance(c, str) and c in chapters for c in refs), tid + ":fix_evidence")
            continue
        require("support" not in task, tid + ":unexpected_support")
        require(audit.text(task.get("why")), tid + ":why")
        context = task.get("context")
        if not audit.fields(context, {"page"}, {"chapter_number", "selection", "issue_from"}, tid + ":context"):
            context = {}
        page = context.get("page")
        require(audit.member(page, PAGES), tid + ":context:page")
        if "chapter_number" in context:
            require(audit.index(context["chapter_number"], 21), tid + ":chapter_number")
        if "selection" in context:
            selection = context["selection"]
            require(page == "writing" and audit.text(selection, 1, 80) and selection in draft_body and "。" in selection,
                    tid + ":selection")
        issue_id = context.get("issue_from")
        if "issue_from" in context:
            fix = ids.get(issue_id) if isinstance(issue_id, str) else None
            require(page == "writing" and isinstance(fix, dict) and fix.get("suite") == "fix"
                    and fix.get("support") is True and fix.get("work") == "w01", tid + ":issue_from")
            require(suite == "route", tid + ":issue_from_route_only")
        field = "input" if suite == "route" else "request"
        low, high = (4, 60) if suite == "route" else (6, 80)
        require(audit.text(task.get(field), low, high), tid + ":" + field)
        require(("request" not in task) if suite == "route" else ("input" not in task), tid + ":input_field")
        if isinstance(task.get(field), str):
            input_records.append((tid, task[field]))
            copy_check(task[field], tid + ":" + field)

        if suite == "action":
            if isinstance(page, str):
                action_pages.add(page)
            require(type(task.get("paraphrased")) is bool, tid + ":paraphrased")
            require(type(task.get("vague")) is bool, tid + ":vague")
            paraphrased += task.get("paraphrased") is True
            vague += task.get("vague") is True
            if task.get("paraphrased") is True and isinstance(task.get("request"), str):
                require(not any(s in task["request"] for s in ("记进事实", "改事实", "标成已回收", "记一下伏笔")), tid + ":paraphrase_label")
            actions = task.get("expected_actions")
            if not require(isinstance(actions, list) and bool(actions), tid + ":actions"):
                continue
            multi_actions += len(actions) == 2
            if isinstance(actions[0], dict) and isinstance(actions[0].get("kind"), str):
                primary_kinds[actions[0]["kind"]] += 1
            within_targets = set()
            for j, action in enumerate(actions, 1):
                label = tid + ":action:" + str(j)
                if not audit.fields(action, {"kind", "target", "after_points", "evidence_chapters", "evidence_quotes"}, set(), label):
                    continue
                kind, target = action.get("kind"), action.get("target")
                require(audit.member(kind, KINDS), label + ":kind")
                if isinstance(kind, str):
                    action_kinds[kind] += 1
                marker = None
                if kind == "change_fact":
                    require(audit.index(target, len(facts)) and target in stale_ids, label + ":target_stale_fact")
                    if type(target) is int:
                        marker = (kind, target)
                elif kind == "resolve_thread":
                    require(audit.index(target, len(threads)) and target in resolved_ids, label + ":target_resolved_unmarked")
                    if type(target) is int:
                        marker = (kind, target)
                elif kind == "add_fact":
                    if audit.fields(target, {"subject", "predicate"}, set(), label + ":target"):
                        good = all(require(audit.text(target.get(f), 1, 20), label + ":target:" + f) for f in ("subject", "predicate"))
                        if good:
                            pair = (target["subject"], target["predicate"])
                            require(pair in missing_pairs, label + ":target_missing_fact")
                            marker = (kind, *pair)
                if marker is not None:
                    require(marker not in within_targets, label + ":duplicate_action_target")
                    within_targets.add(marker)
                    all_action_targets.append(marker)
                points = action.get("after_points")
                require(isinstance(points, list) and 1 <= len(points) <= 3
                        and all(audit.text(p, 1, 30) for p in points), label + ":after_points")
                if isinstance(points, list):
                    for k, point in enumerate(points, 1):
                        copy_check(point, label + ":after_point:" + str(k))
                evidence(action, label)
        elif suite == "no_action":
            kind = task.get("no_action_type")
            require(audit.member(kind, {"already_recorded", "no_evidence", "prose_edit", "unsupported_kind"}), tid + ":no_action_type")
            if isinstance(kind, str):
                no_types[kind] += 1
            targets = task.get("request_targets")
            if audit.fields(targets, {"facts", "foreshadows"}, set(), tid + ":request_targets"):
                for key, maximum in (("facts", len(facts)), ("foreshadows", len(threads))):
                    values = targets.get(key)
                    if require(isinstance(values, list), tid + ":targets:" + key + ":array"):
                        require(all(audit.index(v, maximum) for v in values), tid + ":targets:" + key + ":index")
                        require(len({v for v in values if type(v) is int}) == len(values), tid + ":targets:" + key + ":unique")
                if kind == "already_recorded":
                    require(isinstance(targets.get("facts"), list) and bool(targets["facts"]), tid + ":already_recorded_fact")
            require("expected_actions" not in task, tid + ":unexpected_actions")
        elif suite == "route":
            route_tasks.append(task)
            route = task.get("expected_route")
            require(audit.member(route, ROUTES), tid + ":expected_route")
            if isinstance(route, str):
                routes[route] += 1
            alternatives = task.get("also_acceptable", [])
            if "also_acceptable" in task:
                acceptable_count += 1
            require(isinstance(alternatives, list) and len(alternatives) <= 1
                    and all(audit.member(v, ROUTES) and v != route for v in alternatives), tid + ":also_acceptable")
            if route == "check_passage":
                require("selection" in context, tid + ":check_requires_selection")
            if route == "fix_issue":
                require("issue_from" in context, tid + ":fix_requires_issue")
            message = task.get("input", "")
            if isinstance(message, str):
                if route == "change" and not any(s in message for s in ("记进事实", "改事实", "标成已回收", "记一下伏笔")):
                    colloquial_change += 1
                if route == "ask" and ("？" in message or "?" in message) and any(s in message for s in ("事实", "资料", "伏笔", "记", "改", "收", "吗", "谁", "哪")):
                    ask_like_change += 1
    require(suites["action"] == 12 and suites["no_action"] == 6 and suites["route"] == 10, "tasks:suite_distribution")
    require(len(tasks) == 28 + suites["fix"], "tasks:count")
    require(primary_kinds == Counter({"add_fact": 4, "change_fact": 4, "resolve_thread": 4}), "actions:primary_distribution")
    require(multi_actions >= 2, "actions:two_change_min")
    require(paraphrased >= 6, "actions:paraphrased_min")
    require(vague >= 2, "actions:vague_min")
    require(len(action_pages) >= 3, "actions:page_coverage")
    require(no_types == Counter({"already_recorded": 2, "no_evidence": 2, "prose_edit": 1, "unsupported_kind": 1}), "no_action:distribution")
    require(routes["change"] == 4 and routes["ask"] == 3, "route:change_ask_distribution")
    others = {r: n for r, n in routes.items() if r in ROUTES - {"change", "ask"} and n > 0}
    require(sum(others.values()) == 3 and len(others) >= 2, "route:other_distribution")
    require(acceptable_count <= 2, "route:acceptable_max")
    require(colloquial_change >= 2, "route:colloquial_change_min")
    require(ask_like_change >= 2, "route:question_shape_min")
    groups = review.get("same_input_groups") if isinstance(review.get("same_input_groups"), list) else []
    require(bool(groups), "route:same_input_groups_min")
    group_keys = set()
    for i, group in enumerate(groups, 1):
        label = "route:same_input_group:" + str(i)
        if not require(isinstance(group, list) and len(group) >= 2 and all(isinstance(tid, str) for tid in group), label + ":ids"):
            continue
        require(len(set(group)) == len(group), label + ":unique_ids")
        key = tuple(sorted(group))
        require(key not in group_keys, label + ":duplicate_group")
        group_keys.add(key)
        paired = [ids.get(tid) for tid in group]
        if not require(all(isinstance(t, dict) and t.get("suite") == "route" for t in paired), label + ":route_ids"):
            continue
        require(all(isinstance(t.get("input"), str) for t in paired)
                and len({t.get("input") for t in paired if isinstance(t.get("input"), str)}) == 1, label + ":same_input")
        require(len({t.get("expected_route") for t in paired if isinstance(t.get("expected_route"), str)}) >= 2, label + ":different_route")
        require(len({json.dumps(t.get("context"), ensure_ascii=False, sort_keys=True) for t in paired}) >= 2, label + ":different_context")

    # The ledger and task evidence are both counted, not only the most convenient.
    positions = audit.positions
    unique_positions = list(audit.unique_positions.values())
    require(bool(positions) and 2 * sum(p > 1500 for p in positions) >= len(positions), "evidence:after_1500_half")
    require(bool(unique_positions) and 2 * sum(p > 1500 for p in unique_positions) >= len(unique_positions), "evidence:unique_after_1500_half")

    # Historical task inputs only; prohibited sets are pruned before traversal.
    historical = []
    novelty_files = 0
    if require(evaluation_root.is_dir(), "novelty:evaluation_root"):
        for base, directories, files in os.walk(evaluation_root, followlinks=False):
            directories[:] = sorted(name for name in directories if name not in EXCLUDED_SETS
                                    and not is_link(Path(base) / name)
                                    and (Path(base) / name).resolve() != root)
            if "tasks.json" not in files:
                continue
            path = Path(base) / "tasks.json"
            if is_link(path):
                require(False, "novelty:linked_tasks")
                continue
            try:
                old = json.loads(path.read_text(encoding="utf-8-sig"))
            except (OSError, UnicodeError, ValueError, RecursionError):
                require(False, "novelty:historical_json:" + path.relative_to(evaluation_root).as_posix())
                continue
            novelty_files += 1
            for message in legacy_inputs(old):
                normalized = normalize_input(message)
                if normalized:
                    historical.append((path.relative_to(evaluation_root).as_posix(), normalized))
    require(novelty_files > 0, "novelty:no_historical_tasks")
    novelty_errors = []
    max_similarity = 0.0
    for tid, message in input_records:
        normalized = normalize_input(message)
        for path, previous in historical:
            # Length bounds skip only pairs whose theoretical maximum is <0.8.
            maximum = 2 * min(len(normalized), len(previous)) / (len(normalized) + len(previous)) if normalized or previous else 1.0
            if maximum < 0.8:
                continue
            ratio = difflib.SequenceMatcher(None, normalized, previous).ratio()
            max_similarity = max(max_similarity, ratio)
            if ratio >= 0.8:
                code = "novelty:" + tid + ":" + path
                novelty_errors.append(code)
                require(False, code)
    return audit.finish({
        "works": len(work_list) if isinstance(work_list, list) else 0,
        "chapters": len(chapters), "chapter_han_min": min(chapter_lengths.values(), default=0),
        "chapter_han_max": max(chapter_lengths.values(), default=0), "source_han": sum(chapter_lengths.values()),
        "draft_han": draft_length, "names": len(names), "characters": len(character_names),
        "characters_with_aliases": characters_with_aliases, "facts": len(facts),
        "stale_facts": len(stale_ids), "missing_facts": len(missing_pairs),
        "foreshadows": len(threads), "foreshadow_statuses": dict(sorted(statuses.items())),
        "resolved_unmarked": len(resolved_ids), "still_unresolved": remaining_open,
        "tasks": len(tasks), "scored_tasks": len(tasks) - suites["fix"], "suites": dict(sorted(suites.items())),
        "primary_actions": dict(sorted(primary_kinds.items())), "action_entries": dict(sorted(action_kinds.items())),
        "two_action_tasks": multi_actions, "paraphrased_actions": paraphrased, "vague_actions": vague,
        "action_pages": sorted(action_pages), "no_action_types": dict(sorted(no_types.items())),
        "routes": dict(sorted(routes.items())), "same_input_groups": len(groups),
        "evidence_occurrences": len(positions), "evidence_after_1500": sum(p > 1500 for p in positions),
        "evidence_after_2500": sum(p > 2500 for p in positions),
        "evidence_unique": len(unique_positions), "evidence_unique_after_1500": sum(p > 1500 for p in unique_positions),
        "evidence_position_min": min(positions, default=0), "evidence_position_max": max(positions, default=0),
        "novelty_files": novelty_files, "novelty_historical_inputs": len(historical),
        "novelty_errors": len(novelty_errors), "novelty_max_tested_similarity": round(max_similarity, 6),
        "novelty_excluded_sets": sorted(EXCLUDED_SETS),
    })


def main():
    result = validate()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
