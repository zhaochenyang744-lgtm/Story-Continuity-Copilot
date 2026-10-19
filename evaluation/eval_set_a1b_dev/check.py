"""Offline A1b structural validator. Never imports product code or another set.

PASS certifies the checks below, not semantic correctness or model performance.
All diagnostics deliberately contain identifiers/counts only, never story text.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parent
ERRORS: list[str] = []
COPY_ERRORS = 0
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule"}
QA_TYPES = {"answerable_single", "answerable_multi", "not_in_text", "conflicting"}
PRONOUN = re.compile(r"她|他|它|那|这|此")
HEDGES = re.compile(r"认为|以为|觉得|相信|认定|记得|听说|据说|似乎|好像|think|believe|assume|remember|heard|apparently", re.I)


def require(ok, label):
    if not ok:
        ERRORS.append(label)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def strings(value, nonempty=False):
    return isinstance(value, list) and (not nonempty or bool(value)) and all(isinstance(x, str) and x.strip() for x in value)


def read_utf8(path):
    raw = path.read_bytes()
    require(not raw.startswith(b"\xef\xbb\xbf"), f"encoding:bom:{path.name}")
    require(b"\r" not in raw, f"encoding:cr:{path.name}")
    return raw.decode("utf-8")


def local_path(relative):
    require(isinstance(relative, str), "path:type")
    p = (ROOT / str(relative)).resolve()
    if not p.is_relative_to(ROOT):
        raise ValueError("path_escape")
    return p


def chapter_number(title):
    m = re.match(r"第([零〇一二三四五六七八九十百\d]+)章(?:\s|$)", title)
    if not m:
        return 0
    token = m.group(1)
    if token.isdigit():
        return int(token)
    digits = dict(zip("零〇一二三四五六七八九", [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
    value, pending = 0, 0
    for char in token:
        if char in digits:
            pending = digits[char]
        else:
            value += (pending or 1) * {"十": 10, "百": 100}[char]
            pending = 0
    return value + pending


def parse_work(work):
    key, kind = work["key"], work["kind"]
    require(work.get("language") == "zh", f"{key}:language")
    require(work.get("purpose") == ("safety" if kind == "safety" else "general"), f"{key}:purpose")
    require(isinstance(work.get("title"), str) and bool(work["title"]), f"{key}:title")
    relative = work["source_file"]
    require(relative.startswith("works/") and relative.endswith(".md"), f"{key}:source_file")
    source = read_utf8(local_path(relative))
    hits = list(re.finditer(r"^# (.+)$", source, re.M))
    expected = 100 if kind == "long" else 12 if kind == "general" else (6 if SET == "a1b-dev" else 8)
    require(len(hits) == expected, f"{key}:chapter_count")
    require(not source[:hits[0].start()].strip() if hits else False, f"{key}:source_preamble")
    chapters = {}
    lengths = []
    numbers = {}
    for i, hit in enumerate(hits):
        title = hit.group(1)
        body = source[hit.end(): hits[i + 1].start() if i + 1 < len(hits) else len(source)].strip()
        require(title not in chapters, f"{key}:duplicate_title:{i+1}")
        require(chapter_number(title) == i + 1, f"{key}:chapter_number:{i+1}")
        count = len(HAN.findall(body))
        low, high = (600, 900) if kind == "general" else (400, 600) if kind == "safety" else (400, 700)
        require(low <= count <= high, f"{key}:length:{i+1}:{count}")
        require("“" in body and "”" in body, f"{key}:dialogue:{i+1}")
        chapters[title] = body
        numbers[title] = i + 1
        lengths.append(count)
    names = work.get("names")
    require(strings(names, True), f"{key}:names")
    if strings(names):
        require(len(set(names)) == len(names) and all(len(n) >= 2 for n in names), f"{key}:names_unique")
        require(all(n in source for n in names), f"{key}:names_in_source")
    for field in ("plans", "foreshadows", "extra_facts"):
        if field in work:
            require(isinstance(work[field], list), f"{key}:{field}_type")
    for p in work.get("plans", []):
        require(isinstance(p, dict) and integer(p.get("chapter")) and 1 <= p["chapter"] <= expected+1 and isinstance(p.get("text"), str) and bool(p["text"]), f"{key}:plan_fields")
    for f in work.get("extra_facts", []):
        require(kind == "safety" and isinstance(f, dict) and all(isinstance(f.get(x), str) and bool(f[x]) for x in ("subject", "value")), f"{key}:extra_fact_fields")
    for t in work.get("foreshadows", []):
        require(isinstance(t, dict) and isinstance(t.get("title"), str) and bool(t["title"]) and integer(t.get("planted_chapter")) and 1 <= t["planted_chapter"] <= expected and t.get("status") in {"open", "resolved"}, f"{key}:foreshadow_fields")
        if "description" in t:
            require(isinstance(t["description"], str) and bool(t["description"]), f"{key}:foreshadow_description")
        if t.get("status") == "resolved":
            require(integer(t.get("resolved_chapter")) and t["planted_chapter"] < t["resolved_chapter"] <= expected, f"{key}:foreshadow_resolution")
    if kind != "safety":
        draft = work.get("shared_draft", {})
        body = draft.get("body", "")
        require(isinstance(body, str) and 300 <= len(HAN.findall(body)) <= 500, f"{key}:shared_draft_length")
        require(chapter_number(draft.get("chapter_title", "")) == expected + 1, f"{key}:shared_draft_chapter")
        fact = draft.get("draft_only_fact", "")
        require(isinstance(fact, str) and bool(fact) and fact in body and fact not in source, f"{key}:draft_only_fact")
        plans = work.get("plans", [])
        require(isinstance(plans, list), f"{key}:plans_type")
        pc = Counter(p.get("chapter") for p in plans)
        targets = {51, 101} if kind == "long" else {7, 13}
        require(set(pc) == targets and all(1 <= pc[k] <= 2 for k in targets), f"{key}:plans_count")
        for p in plans:
            require(isinstance(p.get("text"), str) and bool(p["text"]), f"{key}:plan_text")
        threads = work.get("foreshadows", [])
        require(isinstance(threads, list) and len(threads) >= (5 if kind == "long" else 2), f"{key}:threads_count")
        early = 0
        opened = 0
        for t in threads:
            planted = t.get("planted_chapter")
            require(integer(planted) and 1 <= planted <= expected, f"{key}:thread_planted")
            require(isinstance(t.get("title"), str) and bool(t["title"]), f"{key}:thread_title")
            status = t.get("status")
            require(status in {"open", "resolved"}, f"{key}:thread_status")
            if status == "resolved":
                end = t.get("resolved_chapter", 0)
                require(integer(end) and planted < end <= expected, f"{key}:thread_resolved")
                early += end < (60 if kind == "long" else 9)
            else:
                opened += 1
                require("resolved_chapter" not in t, f"{key}:open_thread_resolution")
        require(early >= (2 if kind == "long" else 1) and opened >= (2 if kind == "long" else 1), f"{key}:thread_distribution")
    return {"source": source, "chapters": chapters, "numbers": numbers, "lengths": lengths}


def grams(text, names, language="zh"):
    if language == "en":
        tokens = re.findall(r"[a-z]+", text.lower())
        return {tuple(tokens[i:i+6]) for i in range(len(tokens)-5)}
    normalized = "".join(HAN.findall(text))
    for name in sorted(names, key=len, reverse=True):
        normalized = normalized.replace("".join(HAN.findall(name)), "|")
    return {part[i:i+8] for part in normalized.split("|") for i in range(len(part)-7)}


def refs(value, wk, label, nonempty=False):
    require(strings(value, nonempty), f"{label}:evidence_type")
    if not strings(value):
        return []
    require(len(value) == len(set(value)), f"{label}:evidence_duplicate")
    require(all(x in SOURCES[wk]["chapters"] for x in value), f"{label}:evidence_unknown")
    return [SOURCES[wk]["numbers"][x] for x in value if x in SOURCES[wk]["numbers"]]


def check_copy(task, evidence):
    global COPY_ERRORS
    work = WORKS[task["work"]]
    corpus = SOURCES[work["key"]]["chapters"]
    reference = set()
    for title in evidence:
        if title in corpus:
            reference |= grams(corpus[title], work["names"])
    fields = [(k, task[k]) for k in ("question", "first_question", "selection", "draft", "draft_opening") if k in task]
    if task["suite"] in {"qa", "follow_up"}:
        fields.append(("shared_draft", work.get("shared_draft", {}).get("body", "")))
    for field, value in fields:
        if isinstance(value, str) and grams(value, work["names"]) & reference:
            COPY_ERRORS += 1
            ERRORS.append(f"{task['id']}:copy:{field}")


def validate_qa(task, safe=False, follow=False):
    tid, wk = task["id"], task["work"]
    require(isinstance(task.get("question"), str) and bool(task["question"]), f"{tid}:question")
    require(isinstance(task.get("paraphrased"), bool), f"{tid}:paraphrased")
    require(strings(task.get("answer_points")), f"{tid}:answers")
    require(strings(task.get("forbidden_claims"), True), f"{tid}:forbidden_claims")
    nums = refs(task.get("evidence_chapters"), wk, tid)
    if not follow:
        qt = task.get("qa_type")
        require(qt in QA_TYPES, f"{tid}:qa_type")
        if qt == "not_in_text":
            require(task.get("answer_points") == [], f"{tid}:not_in_text_answers")
        else:
            require(strings(task.get("answer_points"), True) and bool(nums), f"{tid}:answerable_empty")
        if not safe and qt in {"answerable_multi", "conflicting"}:
            require(len(set(nums)) >= 2, f"{tid}:multiple_evidence")
            gap = max(nums)-min(nums) if nums else 0
            require(gap >= (30 if qt == "answerable_multi" else 20), f"{tid}:distance:{gap}")
    if "selection" in task:
        selection = task["selection"]
        draft = WORKS[wk].get("shared_draft", {}).get("body", "")
        require(isinstance(selection, str) and 0 < len(selection) <= 80 and selection in draft, f"{tid}:selection")
        require(bool(PRONOUN.search(task["question"])), f"{tid}:selection_pronoun")
        overlap = [n for n in WORKS[wk]["names"] if n in selection and n in task["question"]]
        require(not overlap, f"{tid}:selection_names")
    if follow:
        first = task.get("first_question", "")
        require(isinstance(first, str) and bool(first), f"{tid}:first_question")
        require(strings(task.get("first_answer_points"), True), f"{tid}:first_answer_points")
        refs(FIRST_REFS.get(tid), wk, f"{tid}:first", True)
        require(bool(PRONOUN.search(task["question"])), f"{tid}:follow_pronoun")
        # Stronger than checking only shared names: no work proper name in follow-up.
        require(not any(n in task["question"] for n in WORKS[wk]["names"]), f"{tid}:follow_names")
        require(bool(nums) and strings(task.get("answer_points"), True), f"{tid}:follow_empty")


def validate_fix(task, safe=False):
    tid, wk = task["id"], task["work"]
    draft, conflict = task.get("draft", ""), task.get("conflict_sentence", "")
    require(isinstance(draft, str) and 0 < len(draft) <= 200, f"{tid}:draft_length")
    require(1 <= len(re.findall(r"[^。！？]+[。！？]", draft)) <= 3, f"{tid}:draft_sentences")
    require(isinstance(conflict, str) and bool(conflict) and conflict in draft, f"{tid}:conflict_substring")
    require(not HEDGES.search(conflict) and not any(c in conflict for c in '“”「」\"'), f"{tid}:conflict_narration")
    if conflict and conflict in draft:
        starts = [m.start() for m in re.finditer(re.escape(conflict), draft)]
        quoted = any(any(draft[:pos].count(left) > draft[:pos].count(right) for left, right in (("“", "”"), ("「", "」"), ("『", "』"))) or draft[:pos].count('"') % 2 for pos in starts)
        require(not quoted, f"{tid}:conflict_quote_context")
        prefixes = [re.split(r"[。！？\n]", draft[:pos])[-1] for pos in starts]
        require(not any(HEDGES.search(p) or re.search(r"(?:说|问|道|喊|答|嚷|嘀咕|声称|表示)[：:]", p) for p in prefixes), f"{tid}:conflict_reported_context")
    require(task.get("category") in CATEGORIES, f"{tid}:category")
    require(isinstance(task.get("fix_idea"), str) and bool(task["fix_idea"]), f"{tid}:fix_idea")
    nums = refs(task.get("evidence_chapters"), wk, tid, True)
    text = "".join(SOURCES[wk]["chapters"].get(c, "") for c in task.get("evidence_chapters", []))
    require(any(n in conflict and n in text for n in WORKS[wk]["names"]), f"{tid}:fix_shared_name")
    if not safe:
        require(nums and all(101-n >= 40 for n in nums), f"{tid}:fix_distance")


def validate_recap(task, safe=False):
    tid, wk = task["id"], task["work"]
    k = task.get("upto_chapter")
    require(integer(k) and 1 <= k <= len(SOURCES[wk]["chapters"]) if safe else k in {50, 100}, f"{tid}:recap_k")
    draft = task.get("draft_opening", "")
    require(isinstance(draft, str) and 2 <= len(re.findall(r"[^。！？]+[。！？]", draft)) <= 4, f"{tid}:opening_sentences")
    mentions = task.get("must_mention", [])
    require(isinstance(mentions, list) and 3 <= len(mentions) <= 5, f"{tid}:must_mention_count")
    require(sum(x.get("kind") == "previous_ending" for x in mentions) == 1, f"{tid}:previous_ending_count")
    require(len({x.get("id") for x in mentions}) == len(mentions), f"{tid}:mention_ids")
    all_refs = []
    for m in mentions:
        require(isinstance(m.get("id"), str) and isinstance(m.get("text"), str) and bool(m["text"]), f"{tid}:mention_fields")
        kind = m.get("kind")
        require(kind in {"previous_ending", "character_state", "open_thread", "plan"}, f"{tid}:mention_kind")
        nums = refs(m.get("evidence_chapters"), wk, tid, kind != "plan")
        require(all(n <= k for n in nums), f"{tid}:future_evidence")
        if kind == "previous_ending":
            require(k in nums, f"{tid}:ending_evidence")
        if kind == "plan":
            require(any(p["chapter"] == k+1 for p in WORKS[wk].get("plans", [])), f"{tid}:missing_plan")
        all_refs.extend(m.get("evidence_chapters", []))
    negatives = task.get("must_not", [])
    require(isinstance(negatives, list) and 2 <= len(negatives) <= 4, f"{tid}:must_not_count")
    require(any(m.get("kind") == "draft_only" for m in negatives), f"{tid}:draft_only_missing")
    for m in negatives:
        require(m.get("kind") in {"stale_state", "resolved_thread", "draft_only", "later_chapter"}, f"{tid}:must_not_kind")
        require(isinstance(m.get("text"), str) and bool(m["text"]), f"{tid}:must_not_text")
    return all_refs


def validate_injection(task):
    tid, wk = task["id"], task["work"]
    injection = task.get("injection", {})
    location, text = injection.get("location"), injection.get("text")
    require(isinstance(location, str) and isinstance(text, str) and bool(text), f"{tid}:injection_fields")
    work = WORKS[wk]
    kind = task.get("safe_kind")
    required = {"injection_fact":"fact", "injection_plan":"plan", "injection_foreshadow":"foreshadow", "injection_title":"title", "jailbreak_question":"question", "system_prompt_request":"question", "off_topic":"question"}
    if kind in required:
        require(location == required[kind], f"{tid}:injection_location_kind")
    if location == "fact":
        values = [f.get("value", "") for f in work.get("extra_facts", [])]
    elif location == "plan":
        values = [p.get("text", "") for p in work.get("plans", [])]
    elif location == "foreshadow":
        values = [p.get("description", p.get("title", "")) for p in work.get("foreshadows", [])]
    elif location == "title":
        values = list(SOURCES[wk]["chapters"])
    elif location in {"draft", "question"}:
        values = [task.get(location, "")]
    else:
        values = [body for title, body in SOURCES[wk]["chapters"].items() if location == title or (chapter_number(location) and chapter_number(location) == chapter_number(title))]
    require(any(isinstance(v, str) and isinstance(text, str) and text in v for v in values), f"{tid}:injection_absent")
    if kind in {"off_topic", "system_prompt_request"}:
        require(task.get("expected_status") == "out_of_scope", f"{tid}:out_of_scope")
    require(isinstance(task.get("expected_behaviour"), str) and bool(task["expected_behaviour"]), f"{tid}:expected_behaviour")


def review_checks(review, tasks):
    records = review.get("tasks", [])
    require(isinstance(records, list) and len(records) == len(tasks), "review:task_count")
    by_id = {x.get("id"): x for x in records}
    require(set(by_id) == {t["id"] for t in tasks}, "review:task_ids")
    for t in tasks:
        tid, wk = t["id"], t["work"]
        r = by_id.get(tid, {})
        require(isinstance(r.get("rationale"), str) and bool(r["rationale"]), f"{tid}:review_rationale")
        require(r.get("copy_check") == "pass", f"{tid}:review_copy")
        quotes = r.get("evidence_quotes", [])
        require(isinstance(quotes, list), f"{tid}:review_quotes")
        sentence_count = 0
        for q in quotes:
            title, text = q.get("chapter"), q.get("text", "")
            require(isinstance(text, str) and bool(text) and text in SOURCES[wk]["chapters"].get(title, ""), f"{tid}:review_quote_source")
            sentence_count += max(1, len(re.findall(r"[。！？]", text)))
        require(sentence_count <= 2, f"{tid}:review_quote_limit")
        if t.get("paraphrased"):
            p = r.get("paraphrase", {})
            require(isinstance(p.get("source"), str) and bool(p["source"]) and isinstance(p.get("question"), str) and bool(p["question"]), f"{tid}:review_paraphrase")
        if t["suite"] == "qa" and t.get("qa_type") == "answerable_multi":
            require(isinstance(r.get("multi_chapter_necessity"), str) and bool(r["multi_chapter_necessity"]), f"{tid}:review_multi")
        if WORKS[wk]["kind"] == "long":
            references = list(t.get("evidence_chapters", []))
            references.extend(r.get("first_evidence_chapters", []))
            for mention in t.get("must_mention", []):
                references.extend(mention.get("evidence_chapters", []))
            ns = [SOURCES[wk]["numbers"][c] for c in references if c in SOURCES[wk]["numbers"]]
            gap = (min(101-n for n in ns) if t["suite"] == "fix" else max(ns)-min(ns)) if ns else 0
            require(r.get("chapter_gap") == gap, f"{tid}:review_gap")
    works = review.get("works", [])
    require(isinstance(works, list) and {w.get("key") for w in works} == set(WORKS), "review:work_ids")
    for r in works:
        wk = r["key"]
        kind = WORKS[wk]["kind"]
        chars = r.get("characters", [])
        minimum = 10 if kind == "long" else 4 if kind == "general" else 3
        require(isinstance(chars, list) and len(chars) >= minimum, f"{wk}:character_count")
        require(len({c.get("name") for c in chars}) == len(chars), f"{wk}:character_unique")
        for c in chars:
            require(c.get("name") in WORKS[wk]["names"] and strings(c.get("aliases")), f"{wk}:character_fields")
            require(all(a in WORKS[wk]["names"] for a in c.get("aliases", [])), f"{wk}:alias_names")
        if kind != "safety":
            require(sum(bool(c.get("aliases")) for c in chars) >= (4 if kind == "long" else 2), f"{wk}:alias_count")
            transfers = r.get("transfers", [])
            require(len({x.get("object") for x in transfers}) >= (4 if kind == "long" else 2), f"{wk}:transferred_objects")
            require(len({x.get("object") for x in transfers if x.get("chapter", 0) > (50 if kind == "long" else 6)}) >= (2 if kind == "long" else 1), f"{wk}:late_transfers")
            states = r.get("states", [])
            require(len(states) >= (6 if kind == "long" else 2), f"{wk}:state_count")
            require(all(integer(s.get("before_chapter")) and integer(s.get("after_chapter")) and 1 <= s["before_chapter"] < s["after_chapter"] <= len(SOURCES[wk]["chapters"]) for s in states), f"{wk}:state_chapters")
            if kind == "long":
                require(sum(s["after_chapter"]-s["before_chapter"] >= 30 for s in states) >= 3, f"{wk}:distant_states")
            require(len(r.get("threads", [])) == len(WORKS[wk]["foreshadows"]), f"{wk}:review_threads")
            conflicts = r.get("intentional_conflicts", [])
            require((3 <= len(conflicts) <= 4) if kind == "long" else (1 <= len(conflicts) <= 2), f"{wk}:intentional_conflicts")
            for c in conflicts:
                numbers = c.get("chapters", [])
                quotes = c.get("quotes", [])
                require(len(numbers) == len(quotes) == 2, f"{wk}:conflict_pair")
                if kind == "long":
                    require(max(numbers)-min(numbers) >= 20, f"{wk}:conflict_distance")
                for n, quote in zip(numbers, quotes):
                    matching = [body for title, body in SOURCES[wk]["chapters"].items() if SOURCES[wk]["numbers"][title] == n]
                    require(isinstance(quote, str) and bool(quote) and any(quote in b for b in matching), f"{wk}:conflict_quote")
    independent = review.get("independent_review", {})
    require(independent.get("reviewer_not_author") is True, "review:independent_reviewer")
    require(independent.get("status") == "completed", "review:independent_status")
    require(independent.get("unresolved_unintentional_conflicts") == 0, "review:unresolved_conflicts")
    require(independent.get("reviewed_chapter_counts") == {wk:len(SOURCES[wk]["chapters"]) for wk in WORKS}, "review:chapter_coverage")
    require(isinstance(independent.get("findings"), list), "review:findings")


def manifest_checks():
    paths = sorted(["tasks.json"] + [p.relative_to(ROOT).as_posix() for p in (ROOT / "works").rglob("*") if p.is_file()])
    actual = []
    for line in read_utf8(ROOT / "set.sha256").splitlines():
        m = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(m is not None, "manifest:line_format")
        if m:
            digest, relative = m.groups()
            actual.append(relative)
            path = local_path(relative)
            require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"manifest:hash:{relative}")
    require(actual == paths, "manifest:coverage_and_order")


def main():
    global SET, WORKS, SOURCES, FIRST_REFS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-dev", action="store_true", help="Validate only this dev directory; never opens formal.")
    args = parser.parse_args()
    if args.staged_dev and ROOT.name != "eval_set_a1b_dev":
        print("FAIL staged-dev requires the dev checker path")
        return 1
    data = json.loads(read_utf8(ROOT / "tasks.json"))
    SET = data.get("set_id")
    require(SET in {"a1b-dev", "a1b-formal"}, "set_id")
    require(ROOT.name == "eval_set_" + str(SET).replace("-", "_"), "set_directory")
    require(data.get("version") == "a1b-1", "version")
    require(isinstance(data.get("author"), str) and bool(data["author"]), "author")
    expected_kinds = Counter({"long":1, "safety":1}) if SET == "a1b-dev" else Counter({"long":1, "general":1, "safety":1})
    works = data.get("works", [])
    require(isinstance(works, list) and Counter(w.get("kind") for w in works) == expected_kinds, "work_distribution")
    WORKS = {w["key"]:w for w in works}
    require(len(WORKS) == len(works), "work_keys")
    SOURCES = {w["key"]:parse_work(w) for w in works}
    review = json.loads(read_utf8(ROOT / "authoring" / "self-review.json"))
    FIRST_REFS = {r.get("id"):r.get("first_evidence_chapters", []) for r in review.get("tasks", [])}
    tasks = data.get("tasks", [])
    dev = SET == "a1b-dev"
    expected_suites = Counter({"qa":10 if dev else 20, "recap":2, "fix":3, "follow_up":6 if dev else 10, "safe":6 if dev else 12})
    require(isinstance(tasks, list) and Counter(t.get("suite") for t in tasks) == expected_suites, "task_distribution")
    require(len({t.get("id") for t in tasks}) == len(tasks), "task_ids")
    prefix = "a1bd-" if dev else "a1bf-"
    qa_counts = Counter()
    safe_counts = Counter()
    follow_works = Counter()
    evidence_positions = set()
    for task in tasks:
        tid, wk, suite = task["id"], task["work"], task["suite"]
        require(isinstance(tid, str) and tid.startswith(prefix), "task_prefix")
        require(isinstance(task.get("note"), str) and bool(task["note"]), f"{tid}:note")
        require(wk in WORKS, f"{tid}:work")
        if wk not in WORKS:
            continue
        kind = WORKS[wk]["kind"]
        require(kind == "safety" if suite == "safe" else kind in {"long", "general"} if suite == "follow_up" else kind == "long", f"{tid}:suite_work_kind")
        evidence = list(task.get("evidence_chapters", []))
        if suite == "qa":
            validate_qa(task)
            qa_counts[task.get("qa_type")] += 1
        elif suite == "follow_up":
            validate_qa(task, follow=True)
            evidence.extend(FIRST_REFS.get(tid, []))
            follow_works[kind] += 1
        elif suite == "fix":
            validate_fix(task)
        elif suite == "recap":
            evidence.extend(validate_recap(task))
        elif suite == "safe":
            safe_counts[task.get("safe_kind")] += 1
            if task.get("safe_kind") == "add_setup_lure":
                validate_fix(task, safe=True)
            elif "upto_chapter" in task:
                require(task.get("safe_kind") in {"injection_plan", "injection_foreshadow"}, f"{tid}:safe_recap_kind")
                evidence.extend(validate_recap(task, safe=True))
            else:
                validate_qa(task, safe=True)
            validate_injection(task)
        check_copy(task, evidence)
        if kind == "long":
            evidence_positions.update(SOURCES[wk]["numbers"][c] for c in evidence if c in SOURCES[wk]["numbers"])
    require(qa_counts == Counter(dict(zip(["answerable_single", "answerable_multi", "not_in_text", "conflicting"], [3,3,2,2] if dev else [5,7,4,4]))), "qa_distribution")
    safe_expected = {"injection_fact":1, "injection_plan":1, "jailbreak_question":1, "system_prompt_request":1, "add_setup_lure":1, "off_topic":1} if dev else {"injection_fact":2, "injection_plan":1, "injection_foreshadow":1, "injection_title":1, "jailbreak_question":2, "system_prompt_request":1, "add_setup_lure":1, "off_topic":3}
    require(safe_counts == Counter(safe_expected), "safe_distribution")
    require(follow_works == Counter({"long":6} if dev else {"long":5, "general":5}), "follow_distribution")
    qa = [t for t in tasks if t["suite"] == "qa"]
    require(sum(t.get("paraphrased") is True for t in qa)*2 >= len(qa), "qa_paraphrase_count")
    answerable = [t for t in qa if t.get("qa_type", "").startswith("answerable")]
    require(sum(t.get("paraphrased") is True for t in answerable)*2 >= len(answerable), "answerable_paraphrase_count")
    require(sum("selection" in t for t in qa) >= 3, "qa_selection_count")
    require(sum(t.get("qa_type") == "answerable_multi" and bool(re.search(r"现在|如今|目前|最后|最新|当前|到结尾", t.get("question", ""))) for t in qa) >= 3, "multi_latest_state_count")
    require(sorted(t.get("upto_chapter") for t in tasks if t["suite"] == "recap") == [50,100], "recap_distribution")
    require(len({t.get("category") for t in tasks if t["suite"] == "fix"}) == 3, "fix_distinct_categories")
    require({(n-1)//25 for n in evidence_positions} == {0,1,2,3}, "long_evidence_spread")
    review_checks(review, tasks)
    manifest_checks()
    for p in ROOT.rglob("*"):
        if p.is_file() and p.suffix in {".json", ".md", ".py", ".sha256"}:
            read_utf8(p)
    result = {"status":"FAIL" if ERRORS else "PASS", "set_id":SET, "works":len(works), "chapters":sum(len(x["chapters"]) for x in SOURCES.values()), "tasks":len(tasks), "errors":len(ERRORS), "copy_errors":COPY_ERRORS, "scope":"this_set_only", "semantic_acceptance":False, "model_calls":0}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    for error in ERRORS:
        print("ERROR " + error)
    return 1 if ERRORS else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, TypeError, ValueError, OSError, IndexError) as exc:
        # Do not print exception payloads: they could contain protected text.
        print("FAIL malformed_or_missing_input exception=" + type(exc).__name__)
        sys.exit(1)
