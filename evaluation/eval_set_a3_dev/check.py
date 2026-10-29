"""Offline A3 development-set audit; standard library, this set only.

Historical comparison uses the authoring snapshot, never opens other sets.
PASS establishes structural/integrity checks, not semantic or model acceptance.
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
# Frozen after the author collected every permitted historical tasks.json.
# No historical file is reopened by this checker.  The digest prevents an
# edited or truncated local comparison snapshot from silently passing novelty.
NOVELTY_REFERENCE_SHA256 = "6cdd6c1cdf933164195f0b6b3513075b5b844e7b952eefeccf1b4aebfb076096"
TASK_INTENTS_SHA256 = "29414c6f15bda04d44e702488629870039f235ff255d069d842dc657fcbe927c"
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
HEADING = re.compile(r"^# (第([1-9][0-9]*)章 [^\r\n]+)$", re.MULTILINE)
PAGES = {"writing", "chapters", "materials", "plan", "overview"}
ROUTES = {"ask", "recap", "check_passage", "out_of_scope", "change", "long_task"}
KINDS = {"add_fact", "change_fact", "resolve_thread", "abandon_thread"}
MEMORY_TYPES = {"static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread"}
THREAD_STATUSES = {"planned", "planted", "developing", "resolved", "abandoned"}
LONG_SUITES = {"trace", "thread_audit", "tidy", "ask", "narrowed"}
PROHIBITED = {"eval_set_a1_reserve", "eval_set_a1b_reserve", "eval_set_v13_authoring"}
REQUIRED_FILES = {
    "README.md", "works/w01.md", "materials/w01-facts.json", "materials/w01-foreshadows.json",
    "tasks.json", "set.sha256", "check.py", "authoring/self-review.md", "authoring/self-review.json",
    "authoring/novelty-reference.json", "authoring/task-intents.json",
}


def han_count(value):
    return len(HAN.findall(value))


def normalize_input(value):
    return "".join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith("P"))


def grams(value, names):
    """Proper names form boundaries; removing names must not splice fragments."""
    text = "".join(HAN.findall(value))
    for name in sorted(names, key=len, reverse=True):
        token = "".join(HAN.findall(name))
        if token:
            text = text.replace(token, "|")
    return {part[i:i + 8] for part in text.split("|") for i in range(len(part) - 7)}


def sentence_selection(selection, draft):
    """A selection is one or more whole sentences, never a sentence suffix."""
    endings = "。！？"
    if not isinstance(selection, str) or not selection or selection[-1] not in endings:
        return False
    for match in re.finditer(re.escape(selection), draft):
        preceding = draft[:match.start()].rstrip()
        if not preceding or preceding[-1] in endings:
            return True
    return False


def is_link(path):
    return path.is_symlink() or bool(getattr(path.lstat(), "st_file_attributes", 0) & 0x400)


class Audit:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.errors = []
        self.positions = []
        self.unique_positions = {}
        self.copy_errors = []

    def require(self, condition, label):
        if not condition and label not in self.errors:
            self.errors.append(label)
        return bool(condition)

    @staticmethod
    def text(value, low=1, high=None):
        return isinstance(value, str) and bool(value.strip()) and len(value) >= low and (high is None or len(value) <= high)

    @staticmethod
    def index(value, maximum=30):
        return type(value) is int and 1 <= value <= maximum

    @staticmethod
    def member(value, choices):
        return isinstance(value, str) and value in choices

    def fields(self, value, required, optional, label):
        if not self.require(isinstance(value, dict), label + ":object"):
            return False
        self.require(set(required) <= value.keys(), label + ":missing_fields")
        self.require(value.keys() <= set(required) | set(optional), label + ":unknown_fields")
        return True

    def path(self, relative, label):
        if not self.require(isinstance(relative, str) and bool(relative) and "\\" not in relative,
                            label + ":relative_path"):
            return None
        candidate = self.root / relative
        if not self.require(not Path(relative).is_absolute() and ".." not in Path(relative).parts
                            and candidate.resolve().is_relative_to(self.root), label + ":path_boundary"):
            return None
        current = self.root
        for part in Path(relative).parts:
            current = current / part
            if current.exists() and is_link(current):
                self.require(False, label + ":reparse_point")
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

    def quote(self, chapter, quote, chapters, numbers, label, integer=False):
        if integer:
            self.require(self.index(chapter), label + ":chapter_number")
        title = numbers.get(chapter) if type(chapter) is int else chapter if isinstance(chapter, str) else None
        valid_title = isinstance(title, str) and title in chapters
        self.require(valid_title, label + ":chapter")
        if not self.require(self.text(quote, 10, 60), label + ":quote_length") or not valid_title:
            return None
        body = chapters[title]
        if self.require(body.count(quote) == 1, label + ":quote_verbatim_unique"):
            position = han_count(body[:body.index(quote)]) + 1
            self.positions.append(position)
            self.unique_positions[(title, quote)] = position
            return (next((n for n, t in numbers.items() if t == title), None), quote)
        return None

    def finish(self, counts=None):
        for error in self.copy_errors:
            self.require(False, error)
        return {"status": "FAIL" if self.errors else "PASS", **(counts or {}),
                "copy_errors": len(self.copy_errors), "errors": self.errors,
                "scope": "this_set_only_with_local_historical_snapshot", "model_calls": 0,
                "semantic_acceptance": False}


def validate(root=ROOT):
    audit = Audit(root)
    try:
        return _validate(audit)
    except Exception as exc:
        audit.require(False, "malformed_data:" + type(exc).__name__)
        return audit.finish()


def _validate(audit):
    root, require = audit.root, audit.require
    for relative in sorted(REQUIRED_FILES):
        path = audit.path(relative, "structure:" + relative)
        require(path is not None and path.is_file(), "structure:" + relative)
    for folder in ("works", "materials", "authoring"):
        require((root / folder).is_dir(), "structure:" + folder)

    expected_paths = ["tasks.json"]
    for folder in ("works", "materials"):
        start = root / folder
        if not start.is_dir() or is_link(start):
            require(False, "structure:" + folder + ":directory")
            continue
        for base, directories, files in os.walk(start, followlinks=False):
            safe = []
            for name in sorted(directories):
                if is_link(Path(base) / name):
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
                require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest,
                        "manifest:hash:" + relative)
            except OSError:
                require(False, "manifest:read:" + relative)
    require(manifest_paths == expected_paths, "manifest:sorted_complete_coverage")

    data = audit.load("tasks.json", dict)
    audit.fields(data, {"version", "set_id", "author", "works", "tasks"}, set(), "top")
    require(data.get("version") == "a3-1", "version")
    require(data.get("set_id") == "a3-dev", "set_id")
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
    require(work.get("materials") == {"facts": "materials/w01-facts.json", "foreshadows": "materials/w01-foreshadows.json"}, "work:materials")
    draft = work.get("shared_draft")
    if not audit.fields(draft, {"chapter_title", "body"}, set(), "work:shared_draft"):
        draft = {}
    require(isinstance(draft.get("chapter_title"), str) and bool(re.fullmatch(r"第31章 [^\r\n]+", draft["chapter_title"])), "draft:chapter_title")
    draft_body = draft.get("body") if isinstance(draft.get("body"), str) else ""
    draft_length = han_count(draft_body)
    require(600 <= draft_length <= 1000, "draft:han_length")

    source = audit.read("works/w01.md")
    headings = list(HEADING.finditer(source))
    require(source.startswith("# 第1章 "), "chapters:first_heading")
    require(len(headings) == len(re.findall(r"^# ", source, re.MULTILINE)) == 30, "chapters:count_and_format")
    require([int(m[2]) for m in headings] == list(range(1, 31)), "chapters:sequential_numbers")
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
    require(30 <= len(facts) <= 45, "facts:count")
    require(9 <= len(threads) <= 14, "foreshadows:count")
    fact_pairs, statuses, titles = set(), Counter(), set()
    for i, fact in enumerate(facts, 1):
        label = "fact:" + str(i)
        if not audit.fields(fact, {"memory_type", "subject", "predicate", "value", "chapter"}, set(), label):
            continue
        require(audit.member(fact.get("memory_type"), MEMORY_TYPES), label + ":memory_type")
        for field, maximum in (("subject", 20), ("predicate", 20), ("value", 60)):
            require(audit.text(fact.get(field), 1, maximum), label + ":" + field)
        require(audit.index(fact.get("chapter")), label + ":chapter")
        if isinstance(fact.get("subject"), str) and isinstance(fact.get("predicate"), str):
            pair = (fact["subject"], fact["predicate"])
            require(pair not in fact_pairs, label + ":duplicate_subject_predicate")
            fact_pairs.add(pair)
    for i, thread in enumerate(threads, 1):
        label = "foreshadow:" + str(i)
        if not audit.fields(thread, {"title", "description", "status", "planted_chapter"}, {"resolved_chapter"}, label):
            continue
        require(audit.text(thread.get("title"), 1, 30), label + ":title")
        if isinstance(thread.get("title"), str):
            require(thread["title"] not in titles, label + ":duplicate_title")
            titles.add(thread["title"])
        require(audit.text(thread.get("description"), 20, 200), label + ":description")
        status, planted = thread.get("status"), thread.get("planted_chapter")
        require(audit.member(status, THREAD_STATUSES), label + ":status")
        if isinstance(status, str):
            statuses[status] += 1
        require(audit.index(planted), label + ":planted_chapter")
        if status == "resolved":
            resolved = thread.get("resolved_chapter")
            require(audit.index(resolved) and audit.index(planted) and resolved >= planted, label + ":resolved_chapter")
        else:
            require("resolved_chapter" not in thread, label + ":unexpected_resolved_chapter")

    review = audit.load("authoring/self-review.json", dict)
    ledger_fields = {"trace_objects", "resolved_unmarked", "still_open", "abandoned_in_text", "stale_facts",
                     "missing_facts", "decoys", "decision_points", "same_input_groups", "characters"}
    audit.fields(review, ledger_fields, set(), "review")
    lists = {}
    for key in sorted(ledger_fields):
        value = review.get(key)
        lists[key] = value if require(isinstance(value, list), "review:" + key + ":array") else []
    characters, character_names, aliases = lists["characters"], set(), set()
    characters_with_aliases = 0
    require(len(characters) >= 10, "characters:min")
    for i, character in enumerate(characters, 1):
        label = "character:" + str(i)
        if not audit.fields(character, {"name", "aliases"}, set(), label):
            continue
        name, nicknames = character.get("name"), character.get("aliases")
        if require(audit.text(name), label + ":name"):
            require(name not in character_names, label + ":duplicate")
            character_names.add(name)
            require(name in names and name in source, label + ":registered_in_source")
        if not require(isinstance(nicknames, list) and all(audit.text(n) for n in nicknames), label + ":aliases"):
            continue
        characters_with_aliases += bool(nicknames)
        require(len(set(nicknames)) == len(nicknames), label + ":duplicate_alias")
        for alias in nicknames:
            require(alias != name and alias not in aliases, label + ":alias_distinct")
            require(alias in names and alias in source, label + ":alias_registered_in_source")
            aliases.add(alias)
    require(len(character_names) >= 10, "characters:distinct_min")
    require(characters_with_aliases >= 3, "characters:with_aliases_min")
    require(not character_names & aliases, "characters:aliases_are_not_other_people")

    trace_objects = lists["trace_objects"]
    require(len(trace_objects) == 3, "trace_objects:count")
    trace_names, contradiction_pairs, contradiction_refs = set(), set(), set()
    trace_state_count = contradiction_count = 0

    def endpoint(item, label):
        if not audit.fields(item, {"chapter", "quote"}, set(), label):
            return None
        return audit.quote(item.get("chapter"), item.get("quote"), chapters, numbers, label, integer=True)

    def pair_points(item, text_key, label):
        if not audit.fields(item, {"a", "b", text_key}, set(), label):
            return None
        require(audit.text(item.get(text_key), 1, 40), label + ":" + text_key)
        a, b = endpoint(item.get("a"), label + ":a"), endpoint(item.get("b"), label + ":b")
        if a and b:
            require(a[0] != b[0], label + ":different_chapters")
            return tuple(sorted((a, b)))
        return None

    for i, obj in enumerate(trace_objects, 1):
        label = "trace_object:" + str(i)
        if not audit.fields(obj, {"name", "states", "contradictions"}, set(), label):
            continue
        name = obj.get("name")
        if require(audit.text(name), label + ":name"):
            require(name not in trace_names, label + ":duplicate_name")
            trace_names.add(name)
        states = obj.get("states")
        if not require(isinstance(states, list), label + ":states_array"):
            states = []
        require(5 <= len(states) <= 9, label + ":state_count")
        trace_state_count += len(states)
        state_chapters, state_refs = [], set()
        for j, state in enumerate(states, 1):
            slabel = label + ":state:" + str(j)
            if not audit.fields(state, {"chapter", "state", "quote"}, set(), slabel):
                continue
            require(audit.text(state.get("state"), 1, 30), slabel + ":state")
            chapter = state.get("chapter")
            if audit.index(chapter):
                state_chapters.append(chapter)
            ref = audit.quote(chapter, state.get("quote"), chapters, numbers, slabel, integer=True)
            if ref:
                require(ref not in state_refs, slabel + ":duplicate_state")
                state_refs.add(ref)
        require(state_chapters == sorted(state_chapters), label + ":states_chapter_order")
        require(bool(state_chapters) and max(state_chapters) - min(state_chapters) >= 15, label + ":span_15_chapters")
        contradictions = obj.get("contradictions")
        if not require(isinstance(contradictions, list), label + ":contradictions_array"):
            contradictions = []
        require(1 <= len(contradictions) <= 2, label + ":contradiction_count")
        contradiction_count += len(contradictions)
        for j, item in enumerate(contradictions, 1):
            pair = pair_points(item, "what", label + ":contradiction:" + str(j))
            if pair:
                require(pair not in contradiction_pairs, label + ":duplicate_contradiction")
                contradiction_pairs.add(pair)
                contradiction_refs.update(pair)

    minima = {"resolved_unmarked": 3, "still_open": 4, "stale_facts": 3, "missing_facts": 6, "decoys": 3}
    for key, minimum in minima.items():
        require(len(lists[key]) >= minimum, "review:" + key + ":count")
    require(len(lists["abandoned_in_text"]) == 1, "review:abandoned_in_text:count")
    require(len(lists["decision_points"]) == 2, "review:decision_points:count")
    action_basis, stale_ids, decoy_ids = {}, set(), set()
    missing_pairs, thread_ids = set(), {key: set() for key in ("resolved_unmarked", "still_open", "abandoned_in_text")}
    for key in ("resolved_unmarked", "still_open", "abandoned_in_text"):
        for i, item in enumerate(lists[key], 1):
            label = "review:" + key + ":" + str(i)
            fields = {"foreshadow"} if key == "still_open" else {"foreshadow", "chapter", "quote"}
            if not audit.fields(item, fields, set(), label):
                continue
            target = item.get("foreshadow")
            if require(audit.index(target, len(threads)), label + ":foreshadow_index"):
                require(target not in thread_ids[key], label + ":duplicate_foreshadow")
                thread_ids[key].add(target)
                thread = threads[target - 1]
                require(isinstance(thread, dict) and thread.get("status") in {"planted", "developing"}, label + ":unresolved_status")
                if key != "still_open":
                    planted = thread.get("planted_chapter") if isinstance(thread, dict) else None
                    chapter = item.get("chapter")
                    require(audit.index(planted) and audit.index(chapter) and chapter >= planted, label + ":after_planting")
            if key != "still_open":
                ref = audit.quote(item.get("chapter"), item.get("quote"), chapters, numbers, label, integer=True)
                if type(target) is int:
                    action_basis[("resolve_thread" if key == "resolved_unmarked" else "abandon_thread", target)] = ref
    require(not (thread_ids["resolved_unmarked"] & thread_ids["still_open"]
                 or thread_ids["resolved_unmarked"] & thread_ids["abandoned_in_text"]
                 or thread_ids["still_open"] & thread_ids["abandoned_in_text"]), "review:thread_categories_disjoint")
    for key in ("stale_facts", "decoys"):
        for i, item in enumerate(lists[key], 1):
            label = "review:" + key + ":" + str(i)
            chapter_field = "changed_chapter" if key == "stale_facts" else "chapter"
            if not audit.fields(item, {"fact", chapter_field, "quote"}, set(), label):
                continue
            target, chapter = item.get("fact"), item.get(chapter_field)
            ids = stale_ids if key == "stale_facts" else decoy_ids
            if require(audit.index(target, len(facts)), label + ":fact_index"):
                require(target not in ids, label + ":duplicate_fact")
                ids.add(target)
                if key == "stale_facts":
                    old = facts[target - 1]
                    old_chapter = old.get("chapter") if isinstance(old, dict) else None
                    require(audit.index(chapter) and audit.index(old_chapter) and chapter > old_chapter, label + ":later_change")
            ref = audit.quote(chapter, item.get("quote"), chapters, numbers, label, integer=True)
            if key == "stale_facts" and type(target) is int:
                action_basis[("change_fact", target)] = ref
    require(not stale_ids & decoy_ids, "review:stale_decoy_disjoint")
    for i, item in enumerate(lists["missing_facts"], 1):
        label = "review:missing_facts:" + str(i)
        if not audit.fields(item, {"subject", "predicate", "chapter", "quote"}, set(), label):
            continue
        valid = all(require(audit.text(item.get(key), 1, 20), label + ":" + key) for key in ("subject", "predicate"))
        pair = (item.get("subject"), item.get("predicate")) if valid else None
        if pair:
            require(pair not in fact_pairs, label + ":already_in_facts")
            require(pair not in missing_pairs, label + ":duplicate_missing")
            missing_pairs.add(pair)
        ref = audit.quote(item.get("chapter"), item.get("quote"), chapters, numbers, label, integer=True)
        if pair:
            action_basis[("add_fact", *pair)] = ref
    decisions, decision_pairs = [], set()
    for i, item in enumerate(lists["decision_points"], 1):
        label = "decision_point:" + str(i)
        pair = pair_points(item, "question", label)
        if pair:
            require(pair not in decision_pairs, label + ":duplicate_pair")
            require(pair not in contradiction_pairs and not set(pair) & contradiction_refs, label + ":not_trace_contradiction")
            decision_pairs.add(pair)
        decisions.append(pair)

    raw_tasks = data.get("tasks")
    if not require(isinstance(raw_tasks, list), "tasks:array"):
        raw_tasks = []
    tasks = [task for task in raw_tasks if isinstance(task, dict)]
    require(len(tasks) == len(raw_tasks), "tasks:objects")
    require(len(tasks) == 18, "tasks:count")
    ids = {}
    for i, task in enumerate(tasks, 1):
        tid = task.get("id")
        if require(audit.text(tid) and tid.startswith("a3d-"), "task:" + str(i) + ":id"):
            require(tid not in ids, "task:duplicate_id:" + tid)
            ids[tid] = task
    intents_path = audit.path("authoring/task-intents.json", "task_intents")
    try:
        require(intents_path is not None and hashlib.sha256(intents_path.read_bytes()).hexdigest()
                == TASK_INTENTS_SHA256, "task_intents:frozen_sha256")
    except OSError:
        require(False, "task_intents:frozen_sha256")
    intents = audit.load("authoring/task-intents.json", dict)
    long_ids = {tid for tid, task in ids.items() if task.get("suite") in LONG_SUITES}
    require(set(intents) == long_ids, "task_intents:complete_long_task_ids")
    reference_grams = set().union(*(grams(body, names) for body in chapters.values())) if chapters else set()
    suites, routes, action_kinds = Counter(), Counter(), Counter()
    scoped = full_book = colloquial = route_colloquial = acceptable_count = 0
    all_inputs, route_tasks, task_action_counts = [], [], {}
    context_fields = {"chapter_number", "selection"}

    def copy_check(value, label):
        if isinstance(value, str) and grams(value, names) & reference_grams:
            audit.copy_errors.append("copy:" + label)

    def chapter_range(value, label):
        valid = isinstance(value, list) and len(value) == 2 and all(audit.index(n) for n in value) and value[0] <= value[1]
        require(valid, label + ":chapter_range")
        return tuple(value) if valid else (1, 30)

    def in_scope(ref, bounds):
        return ref is not None and bounds[0] <= ref[0] <= bounds[1]

    def action_items(items, bounds, label):
        if not require(isinstance(items, list), label + ":array"):
            return set()
        markers = set()
        for j, action in enumerate(items, 1):
            alabel = label + ":" + str(j)
            if not audit.fields(action, {"kind", "target", "after_points", "evidence_chapters", "evidence_quotes"}, set(), alabel):
                continue
            kind, target = action.get("kind"), action.get("target")
            require(audit.member(kind, KINDS), alabel + ":kind")
            if isinstance(kind, str):
                action_kinds[kind] += 1
            marker = None
            if kind == "add_fact":
                if audit.fields(target, {"subject", "predicate"}, set(), alabel + ":target"):
                    valid = all(require(audit.text(target.get(key), 1, 20), alabel + ":target:" + key) for key in ("subject", "predicate"))
                    if valid:
                        marker = (kind, target["subject"], target["predicate"])
            elif kind in {"change_fact", "resolve_thread", "abandon_thread"}:
                require(audit.index(target, len(facts) if kind == "change_fact" else len(threads)), alabel + ":target_index")
                if type(target) is int:
                    marker = (kind, target)
                if kind == "change_fact":
                    require(target not in decoy_ids if type(target) is int else False, alabel + ":not_decoy")
            basis = action_basis.get(marker) if marker else None
            require(marker is not None and marker in action_basis, alabel + ":target_matches_review")
            if marker:
                require(marker not in markers, alabel + ":duplicate_target")
                markers.add(marker)
                require(in_scope(basis, bounds), alabel + ":target_in_scope")
            points = action.get("after_points")
            require(isinstance(points, list) and 1 <= len(points) <= 3 and all(audit.text(p, 1, 30) for p in points), alabel + ":after_points")
            if isinstance(points, list):
                for k, point in enumerate(points, 1):
                    copy_check(point, alabel + ":after_point:" + str(k))
            refs, quotes = action.get("evidence_chapters"), action.get("evidence_quotes")
            if not require(isinstance(refs, list) and isinstance(quotes, list) and 1 <= len(refs) == len(quotes), alabel + ":evidence_alignment"):
                continue
            evidence_refs = []
            for k, (chapter, quote) in enumerate(zip(refs, quotes), 1):
                elabel = alabel + ":evidence:" + str(k)
                require(isinstance(chapter, str) and chapter in chapters, elabel + ":full_chapter_title")
                ref = audit.quote(chapter, quote, chapters, numbers, elabel)
                if ref:
                    require(in_scope(ref, bounds), elabel + ":in_scope")
                    evidence_refs.append(ref)
            require(len(set(evidence_refs)) == len(evidence_refs), alabel + ":duplicate_evidence")
            require(basis is not None and basis in evidence_refs, alabel + ":evidence_matches_target_point")
        return markers

    for i, task in enumerate(tasks, 1):
        tid = task.get("id") if isinstance(task.get("id"), str) else "task:" + str(i)
        suite = task.get("suite")
        if isinstance(suite, str):
            suites[suite] += 1
        require(audit.member(suite, LONG_SUITES | {"route"}), tid + ":suite")
        require(task.get("work") == "w01", tid + ":work")
        require(audit.text(task.get("why")), tid + ":why")
        context = task.get("context")
        if not audit.fields(context, {"page"}, context_fields, tid + ":context"):
            context = {}
        page = context.get("page")
        require(audit.member(page, PAGES), tid + ":context:page")
        if "chapter_number" in context:
            require(audit.index(context["chapter_number"], 31), tid + ":chapter_number")
        if "selection" in context:
            selection = context["selection"]
            require(page == "writing" and audit.text(selection, 1, 80)
                    and sentence_selection(selection, draft_body), tid + ":selection_sentence_in_draft")
        field, low, high = ("input", 4, 60) if suite == "route" else ("request", 8, 100)
        require(audit.text(task.get(field), low, high), tid + ":" + field)
        if isinstance(task.get(field), str):
            all_inputs.append((tid, task[field]))
            copy_check(task[field], tid + ":" + field)
        common = {"id", "suite", "work", "context", "why", field}
        if suite == "route":
            audit.fields(task, common | {"expected_route"}, {"also_acceptable"}, tid)
            route_tasks.append(task)
            route = task.get("expected_route")
            require(audit.member(route, ROUTES), tid + ":expected_route")
            if isinstance(route, str):
                routes[route] += 1
            alternatives = task.get("also_acceptable", [])
            acceptable_count += "also_acceptable" in task
            require(isinstance(alternatives, list) and len(alternatives) <= 1 and all(audit.member(v, ROUTES) and v != route for v in alternatives), tid + ":also_acceptable")
            if route == "check_passage":
                require("selection" in context, tid + ":check_requires_selection")
            if route == "long_task" and isinstance(task.get("input"), str) and not any(word in task["input"] for word in ("清点", "梳理", "整理")):
                route_colloquial += 1
            continue
        if suite not in LONG_SUITES:
            continue
        fields = {"scope", "author_replies"}
        extras = {"trace": {"trace_object", "allowed_actions"}, "thread_audit": {"expected_actions"},
                  "tidy": {"expected_actions"}, "ask": {"decision_point", "expected_actions"},
                  "narrowed": {"plan_edit", "expected_actions", "allowed_actions"}}[suite]
        audit.fields(task, common | fields | extras, set(), tid)
        bounds = (1, 30)
        if task.get("scope") is None:
            full_book += 1
        else:
            scoped += 1
            bounds = chapter_range(task.get("scope"), tid + ":scope")
        if isinstance(task.get("request"), str) and not any(word in task["request"] for word in ("清点", "梳理", "整理")):
            colloquial += 1
        replies = task.get("author_replies")
        if not audit.fields(replies, {"decision"} if suite == "ask" else set(), set(), tid + ":author_replies"):
            replies = {}
        intent = intents.get(tid)
        if not audit.fields(intent, {"operation"}, {"trace_object"}, tid + ":intent"):
            intent = {}
        operation = intent.get("operation")
        require(audit.member(operation, {"trace", "thread_audit", "tidy", "decision"}), tid + ":intent:operation")
        if suite != "narrowed":
            require(operation == ("decision" if suite == "ask" else suite), tid + ":intent_matches_suite")
        if suite == "narrowed":
            require(task.get("scope") is None, tid + ":narrowed_initially_whole_book")
            edit = task.get("plan_edit")
            if audit.fields(edit, {"chapters"}, set(), tid + ":plan_edit"):
                bounds = chapter_range(edit.get("chapters"), tid + ":plan_edit")
                require(bounds != (1, 30), tid + ":plan_edit_strict_subset")
            require(operation in {"trace", "thread_audit", "tidy"}, tid + ":narrowed_operation")
        if suite == "trace" or operation == "trace":
            target = task.get("trace_object") if suite == "trace" else intent.get("trace_object")
            require(audit.index(target, len(trace_objects)), tid + ":trace_object")
            if "trace_object" in intent:
                require(intent["trace_object"] == target, tid + ":trace_intent_target")
        expected = action_items(task.get("expected_actions", []), bounds, tid + ":expected_actions")
        allowed = action_items(task.get("allowed_actions", []), bounds, tid + ":allowed_actions")
        require(not expected & allowed, tid + ":expected_allowed_disjoint")
        task_action_counts[tid] = len(expected)
        if operation in {"thread_audit", "tidy"}:
            kinds = {"resolve_thread", "abandon_thread"} if operation == "thread_audit" else {"add_fact", "change_fact"}
            complete = {marker for marker, ref in action_basis.items() if marker[0] in kinds and in_scope(ref, bounds)}
            require(expected == complete, tid + ":complete_scope_actions")
            require(not allowed, tid + ":no_extra_allowed_actions")
        elif operation == "trace":
            require(not expected, tid + ":trace_no_expected_actions")
        if suite == "ask":
            target = task.get("decision_point")
            if require(audit.index(target, len(decisions)), tid + ":decision_point"):
                pair = decisions[target - 1]
                require(pair is not None and all(in_scope(ref, bounds) for ref in pair), tid + ":decision_in_scope")
            in_range = [pair for pair in decisions if pair and all(in_scope(ref, bounds) for ref in pair)]
            require(len(in_range) == 1, tid + ":exactly_one_decision_in_scope")
            reply = replies.get("decision")
            require(audit.text(reply, 1, 40), tid + ":decision_reply")
            choices = set(re.findall(r"(?:^|[\s，,。；;：:])([ab])(?=$|[\s，,。；;：:])", reply.lower())) if isinstance(reply, str) else set()
            require(len(choices) == 1, tid + ":decision_reply_selects_a_or_b")
            # This authored set chooses narrative-only decisions, independently frozen
            # in task-intents: the reply does not authorize material changes.
            require(task.get("expected_actions") == [], tid + ":narrative_decision_has_no_material_actions")
    require(suites == Counter({"trace": 2, "thread_audit": 2, "tidy": 1, "ask": 2, "narrowed": 1, "route": 10}), "tasks:suite_distribution")
    # This set satisfies both the dev task sheet's 3/2 and SPEC 3.2's 4/3.
    require(scoped >= 4, "tasks:scoped_min")
    require(full_book >= 3, "tasks:full_book_min")
    require(colloquial >= 4, "tasks:colloquial_min")
    require(routes["long_task"] == 4 and routes["change"] == 2 and routes["ask"] == 2
            and sum(routes[key] for key in ("recap", "check_passage", "out_of_scope")) == 2, "route:distribution")
    require(route_colloquial >= 2, "route:colloquial_long_task_min")
    require(acceptable_count <= 2, "route:also_acceptable_max")
    groups, group_keys = lists["same_input_groups"], set()
    require(len(groups) >= 1, "route:same_input_groups_min")
    for i, group in enumerate(groups, 1):
        label = "same_input_group:" + str(i)
        if not require(isinstance(group, list) and len(group) >= 2 and all(isinstance(tid, str) for tid in group), label + ":ids"):
            continue
        require(len(set(group)) == len(group), label + ":unique_ids")
        key = tuple(sorted(group))
        require(key not in group_keys, label + ":duplicate_group")
        group_keys.add(key)
        paired = [ids.get(tid) for tid in group]
        if not require(all(isinstance(t, dict) and t.get("suite") == "route" for t in paired), label + ":route_tasks"):
            continue
        require(all(isinstance(t.get("input"), str) for t in paired) and len({t.get("input") for t in paired}) == 1, label + ":identical_input")
        require(len({t.get("expected_route") for t in paired}) >= 2, label + ":different_routes")
        require(len({json.dumps(t.get("context"), ensure_ascii=False, sort_keys=True) for t in paired}) >= 2, label + ":different_context")

    positions, unique_positions = audit.positions, list(audit.unique_positions.values())
    require(bool(positions) and 2 * sum(p > 1500 for p in positions) >= len(positions), "evidence:after_1500_half")
    # A1c section 2 is inherited as the prose-writing rule.  Apply its deeper
    # placement bar to distinct quotes too, so repeated task citations cannot
    # make a shallow authoring ledger appear to satisfy it.
    require(bool(unique_positions) and 3 * sum(p > 2500 for p in unique_positions) >= len(unique_positions),
            "evidence:unique_after_2500_third")
    snapshot_path = audit.path("authoring/novelty-reference.json", "novelty_snapshot")
    try:
        require(snapshot_path is not None and hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
                == NOVELTY_REFERENCE_SHA256, "novelty_snapshot:frozen_sha256")
    except OSError:
        require(False, "novelty_snapshot:frozen_sha256")
    snapshot = audit.load("authoring/novelty-reference.json", dict)
    audit.fields(snapshot, {"sources", "names", "excluded_sets"}, set(), "novelty_snapshot")
    excluded = snapshot.get("excluded_sets")
    require(isinstance(excluded, list) and all(isinstance(v, str) for v in excluded) and PROHIBITED <= set(excluded), "novelty:prohibited_sets_excluded")
    historical_names = snapshot.get("names")
    if not require(isinstance(historical_names, list) and all(audit.text(n) for n in historical_names), "novelty:historical_names"):
        historical_names = []
    overlap = set(names) & set(historical_names)
    require(not overlap, "novelty:proper_name_overlap")
    historical, source_paths = [], set()
    sources = snapshot.get("sources")
    if not require(isinstance(sources, list) and bool(sources), "novelty:sources"):
        sources = []
    for i, item in enumerate(sources, 1):
        label = "novelty_source:" + str(i)
        if not audit.fields(item, {"path", "sha256", "inputs"}, {"names"}, label):
            continue
        path = item.get("path")
        valid = isinstance(path, str) and path.endswith("/tasks.json") and not Path(path).is_absolute() and ".." not in Path(path).parts and "\\" not in path
        require(valid, label + ":path")
        if valid:
            require(not set(Path(path).parts) & PROHIBITED and "eval_set_a3_dev" not in Path(path).parts, label + ":permitted_source")
            require(path not in source_paths, label + ":duplicate_source")
            source_paths.add(path)
        require(isinstance(item.get("sha256"), str) and bool(re.fullmatch(r"[0-9a-f]{64}", item["sha256"])), label + ":sha256")
        inputs = item.get("inputs")
        if require(isinstance(inputs, list) and all(audit.text(value) for value in inputs), label + ":inputs"):
            for value in inputs:
                require(value == normalize_input(value), label + ":inputs_are_normalized")
                historical.append((path, value))
        if "names" in item:
            require(isinstance(item["names"], list) and all(audit.text(n) for n in item["names"]), label + ":names")
    require(bool(historical), "novelty:historical_inputs_min")
    novelty_errors, max_similarity = [], 0.0
    for tid, message in all_inputs:
        normalized = normalize_input(message)
        for path, previous in historical:
            maximum = 2 * min(len(normalized), len(previous)) / (len(normalized) + len(previous)) if normalized or previous else 1.0
            if maximum < 0.8:
                continue
            ratio = difflib.SequenceMatcher(None, normalized, previous).ratio()
            max_similarity = max(max_similarity, ratio)
            if ratio >= 0.8:
                error = "novelty:" + tid + ":" + str(path)
                novelty_errors.append(error)
                require(False, error)
    return audit.finish({
        "works": len(work_list) if isinstance(work_list, list) else 0, "chapters": len(chapters),
        "chapter_han_min": min(chapter_lengths.values(), default=0), "chapter_han_max": max(chapter_lengths.values(), default=0),
        "source_han": sum(chapter_lengths.values()), "draft_han": draft_length, "names": len(names),
        "characters": len(character_names), "characters_with_aliases": characters_with_aliases,
        "facts": len(facts), "foreshadows": len(threads), "foreshadow_statuses": dict(sorted(statuses.items())),
        "trace_objects": len(trace_objects), "trace_states": trace_state_count, "trace_contradictions": contradiction_count,
        "resolved_unmarked": len(thread_ids["resolved_unmarked"]), "still_open": len(thread_ids["still_open"]),
        "abandoned_in_text": len(thread_ids["abandoned_in_text"]), "stale_facts": len(stale_ids),
        "missing_facts": len(missing_pairs), "decoys": len(decoy_ids), "decision_points": len(decisions),
        "tasks": len(tasks), "long_tasks": sum(suites[s] for s in LONG_SUITES), "suites": dict(sorted(suites.items())),
        "routes": dict(sorted(routes.items())), "scoped_tasks": scoped, "full_book_tasks": full_book,
        "colloquial_long_tasks": colloquial, "colloquial_route_long_tasks": route_colloquial,
        "action_entries": dict(sorted(action_kinds.items())), "task_action_counts": task_action_counts,
        "same_input_groups": len(groups), "evidence_occurrences": len(positions),
        "evidence_after_1500": sum(p > 1500 for p in positions), "evidence_after_2500": sum(p > 2500 for p in positions),
        "evidence_unique": len(unique_positions), "evidence_unique_after_1500": sum(p > 1500 for p in unique_positions),
        "evidence_position_min": min(positions, default=0), "evidence_position_max": max(positions, default=0),
        "proper_name_overlap": len(overlap), "novelty_files": len(source_paths), "novelty_historical_inputs": len(historical),
        "novelty_errors": len(novelty_errors), "novelty_max_tested_similarity": round(max_similarity, 6),
        "novelty_excluded_sets": sorted(excluded) if isinstance(excluded, list) else [],
    })


def main():
    result = validate()
    print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    return int(result["status"] != "PASS")


if __name__ == "__main__":
    raise SystemExit(main())
