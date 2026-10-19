"""Offline A1c structure checks; never imports product code or another set.

PASS is not semantic acceptance. Diagnostics expose IDs/counts only.
Quote positions are 1-based positions of the first Han character, excluding
chapter headings. Distribution counts unique (work, chapter, exact quote) pairs
in task self-review, including FIX, RECAP and the first question of follow-ups.
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
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")
PRONOUN = re.compile(r"她|他|它|那|这|此")
HEDGES = re.compile(r"认为|以为|觉得|相信|认定|记得|听说|据说|似乎|好像|think|believe|assume|remember|heard|apparently", re.I)
CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule"}
QA_TYPES = {"answerable_single", "answerable_multi", "not_in_text", "conflicting"}
ERRORS = []
COPY_ERRORS = 0
POSITIONS = {}
WORKS = {}
SOURCES = {}
REVIEWS = {}
DEV = True
SET = None


def require(ok, label):
    if not ok:
        ERRORS.append(label)


def integer(value):
    return isinstance(value, int) and not isinstance(value, bool)


def text(value):
    return isinstance(value, str) and bool(value.strip())


def strings(value, nonempty=False):
    return isinstance(value, list) and (not nonempty or bool(value)) and all(text(x) for x in value)


def objects(value, label):
    if not isinstance(value, list) or not all(isinstance(x, dict) for x in value):
        require(False, label + ":object_list")
        return []
    return value


def read_utf8(path):
    raw = path.read_bytes()
    require(not raw.startswith(b"\xef\xbb\xbf"), "encoding:bom")
    require(b"\r" not in raw, "encoding:cr")
    return raw.decode("utf-8")


def local_path(relative):
    if not text(relative) or Path(relative).is_absolute():
        raise ValueError("invalid_relative_path")
    path = (ROOT / relative).resolve()
    if not path.is_relative_to(ROOT):
        raise ValueError("path_escape")
    return path


def chapter_number(title):
    if not isinstance(title, str):
        return 0
    match = re.match(r"第([零〇一二三四五六七八九十百\d]+)章(?:\s|$)", title)
    if not match:
        return 0
    token = match.group(1)
    if token.isdigit():
        return int(token)
    digits = dict(zip("零〇一二三四五六七八九", [0, 0, 1, 2, 3, 4, 5, 6, 7, 8, 9]))
    value = pending = 0
    for char in token:
        if char in digits:
            pending = digits[char]
        else:
            value += (pending or 1) * {"十": 10, "百": 100}[char]
            pending = 0
    return value + pending


def parse_work(work):
    key = work["key"]
    expected = 30
    require(work.get("language") == "zh" and work.get("purpose") == "general", key + ":work_type")
    require(text(work.get("title")), key + ":title")
    if "kind" in work:
        require(work["kind"] == "long", key + ":kind")
    relative = work.get("source_file")
    if not text(relative) or not relative.startswith("works/") or not relative.endswith(".md"):
        raise ValueError("invalid_work_path")
    source = read_utf8(local_path(relative))
    hits = list(re.finditer(r"^# (.+)$", source, re.M))
    require(len(hits) == expected, key + ":chapter_count")
    require(bool(hits) and not source[:hits[0].start()].strip(), key + ":preamble")
    chapters, numbers, lengths = {}, {}, []
    for i, hit in enumerate(hits):
        title = hit.group(1)
        body = source[hit.end():hits[i + 1].start() if i + 1 < len(hits) else len(source)].strip()
        label = f"{key}:chapter:{i+1}"
        require(title not in chapters, label + ":duplicate_title")
        require(chapter_number(title) == i + 1, label + ":number")
        count = len(HAN.findall(body))
        require(2500 <= count <= 3500, label + f":length:{count}")
        chapters[title], numbers[title] = body, i + 1
        lengths.append(count)
    names = work.get("names")
    require(strings(names, True), key + ":names")
    if strings(names):
        require(len(names) == len(set(names)) and all(len(n) >= 2 for n in names), key + ":names_unique")
        require(all(n in source for n in names), key + ":names_in_source")
    plans = objects(work.get("plans"), key + ":plans")
    targets = {16, 31}
    counts = Counter(p.get("chapter") for p in plans)
    require(set(counts) == targets and all(1 <= n <= 2 for n in counts.values()), key + ":plan_distribution")
    for plan in plans:
        require(integer(plan.get("chapter")) and text(plan.get("text")), key + ":plan_fields")
    threads = objects(work.get("foreshadows"), key + ":threads")
    require(len(threads) >= 4, key + ":thread_count")
    for thread in threads:
        planted = thread.get("planted_chapter")
        require(text(thread.get("title")) and integer(planted) and 1 <= planted <= expected, key + ":thread_fields")
        require(thread.get("status") in {"open", "resolved"}, key + ":thread_status")
        if thread.get("status") == "resolved":
            end = thread.get("resolved_chapter")
            require(integer(end) and integer(planted) and planted < end <= expected, key + ":thread_resolution")
        else:
            require("resolved_chapter" not in thread, key + ":open_resolution")
    for status in ("open", "resolved"):
        require(sum(t.get("status") == status for t in threads) >= 1, key + ":thread_" + status)
    draft = work.get("shared_draft", {})
    body, fact = draft.get("body"), draft.get("draft_only_fact")
    require(text(body) and 800 <= len(HAN.findall(body)) <= 1200, key + ":shared_draft_length")
    require(chapter_number(draft.get("chapter_title")) == expected + 1, key + ":shared_draft_chapter")
    require(text(fact) and fact in body and fact not in source, key + ":draft_only_fact")
    return {"source": source, "chapters": chapters, "numbers": numbers, "lengths": lengths}


def refs(value, wk, label, nonempty=False):
    require(strings(value, nonempty), label + ":evidence_type")
    if not strings(value):
        return []
    require(len(set(value)) == len(value), label + ":evidence_duplicate")
    require(all(v in SOURCES[wk]["chapters"] for v in value), label + ":evidence_unknown")
    return [SOURCES[wk]["numbers"][v] for v in value if v in SOURCES[wk]["numbers"]]


def quote_position(wk, chapter, quote, label, record=False):
    body = SOURCES[wk]["chapters"].get(chapter, "")
    if not text(quote):
        require(False, label + ":quote_type")
        return 0
    require(10 <= len(quote) <= 60, label + ":quote_length")
    # Overlapping occurrences count too; an ambiguous locator must fail.
    starts = [m.start() for m in re.finditer("(?=" + re.escape(quote) + ")", body)]
    first_han = HAN.search(quote)
    require(len(starts) == 1 and first_han is not None, label + ":quote_unique_source")
    if len(starts) != 1 or first_han is None:
        return 0
    position = len(HAN.findall(body[:starts[0] + first_han.start()])) + 1
    if record:
        POSITIONS[(wk, chapter, quote)] = position
    return position


def grams(value, names):
    normalized = "".join(HAN.findall(value))
    for name in sorted(names, key=len, reverse=True):
        normalized_name = "".join(HAN.findall(name))
        if normalized_name:
            normalized = normalized.replace(normalized_name, "|")
    return {part[i:i+8] for part in normalized.split("|") for i in range(len(part)-7)}


def check_copy(task, evidence):
    global COPY_ERRORS
    wk, tid = task["work"], task["id"]
    reference = set()
    names = WORKS[wk]["names"]
    for chapter in evidence:
        reference |= grams(SOURCES[wk]["chapters"].get(chapter, ""), names)
    fields = [(f, task[f]) for f in ("question", "first_question", "selection", "draft", "draft_opening") if f in task]
    if task["suite"] in {"qa", "follow_up"}:
        fields.append(("shared_draft", WORKS[wk]["shared_draft"]["body"]))
    for field, value in fields:
        if isinstance(value, str) and grams(value, names) & reference:
            COPY_ERRORS += 1
            require(False, tid + ":copy:" + field)


def validate_qa(task, follow=False):
    tid, wk = task["id"], task["work"]
    question = task.get("question")
    require(text(question), tid + ":question")
    require(isinstance(task.get("paraphrased"), bool), tid + ":paraphrased")
    require(strings(task.get("answer_points")), tid + ":answer_points")
    require(strings(task.get("forbidden_claims")), tid + ":forbidden_claims")
    qt = task.get("qa_type")
    if not follow:
        require(qt in QA_TYPES, tid + ":qa_type")
    answered = follow or qt != "not_in_text"
    nums = refs(task.get("evidence_chapters"), wk, tid, answered)
    if answered:
        require(strings(task.get("answer_points"), True), tid + ":empty_answer")
        quotes = task.get("evidence_quotes")
        require(strings(quotes, True) and len(quotes) == len(task["evidence_chapters"]), tid + ":quote_alignment")
        positions = [quote_position(wk, c, q, tid) for c, q in zip(task["evidence_chapters"], quotes)]
        require(isinstance(task.get("deep"), bool), tid + ":deep_type")
        require(task.get("deep") is any(p > 1500 for p in positions), tid + ":deep_position")
    else:
        require(task.get("answer_points") == [], tid + ":not_in_text_answer")
    if qt == "answerable_single" and not follow:
        require(len(nums) == 1, tid + ":single_evidence")
    if qt in {"answerable_multi", "conflicting"} and not follow:
        require(len(nums) >= 2, tid + ":multiple_evidence")
        if qt == "answerable_multi":
            require(bool(nums) and max(nums) - min(nums) >= 10, tid + ":chapter_gap")
    if "selection" in task:
        selection = task["selection"]
        require(text(selection) and len(selection) <= 80 and selection in WORKS[wk]["shared_draft"]["body"], tid + ":selection")
        require(isinstance(selection, str) and bool(re.search(r"[。！？]", selection)), tid + ":selection_sentence")
        residue = selection
        for name in sorted(WORKS[wk]["names"], key=len, reverse=True):
            residue = residue.replace(name, "")
        require(bool(HAN.search(residue)), tid + ":selection_only_name")
        require(bool(PRONOUN.search(question)), tid + ":selection_pronoun")
        require(not any(n in selection and n in question for n in WORKS[wk]["names"]), tid + ":selection_names")
    if follow:
        require(text(task.get("first_question")) and strings(task.get("first_answer_points"), True), tid + ":first_question")
        require(bool(PRONOUN.search(question)), tid + ":follow_pronoun")
        require(not any(n in question for n in WORKS[wk]["names"]), tid + ":follow_names")


def validate_fix(task):
    tid, wk = task["id"], task["work"]
    draft, conflict = task.get("draft"), task.get("conflict_sentence")
    require(text(draft) and len(draft) <= 200, tid + ":draft_length")
    require(1 <= len(re.findall(r"[^。！？]+[。！？]", draft)) <= 3, tid + ":draft_sentences")
    require(text(conflict) and conflict in draft, tid + ":conflict_substring")
    require(not HEDGES.search(conflict) and not any(c in conflict for c in '“”「」『』"'), tid + ":conflict_narration")
    for match in re.finditer(re.escape(conflict), draft):
        prefix = draft[:match.start()]
        require(not any(prefix.count(a) > prefix.count(b) for a, b in (("“", "”"), ("「", "」"), ("『", "』"))) and prefix.count('"') % 2 == 0, tid + ":conflict_quote_context")
        same_sentence = re.split(r"[。！？\n]", prefix)[-1]
        require(not HEDGES.search(same_sentence) and not re.search(r"(?:说|问|道|喊|答|嚷|声称|表示)[：:]", same_sentence), tid + ":conflict_reported_context")
    require(task.get("category") in CATEGORIES, tid + ":category")
    require(text(task.get("fix_idea")), tid + ":fix_idea")
    refs(task.get("evidence_chapters"), wk, tid, True)
    source = "".join(SOURCES[wk]["chapters"].get(c, "") for c in task["evidence_chapters"])
    require(any(n in conflict and n in source for n in WORKS[wk]["names"]), tid + ":fix_shared_name")


def validate_recap(task):
    tid, wk = task["id"], task["work"]
    k = task.get("upto_chapter")
    require(integer(k) and k in {15, 30}, tid + ":recap_k")
    opening = task.get("draft_opening")
    require(text(opening) and 2 <= len(re.findall(r"[^。！？]+[。！？]", opening)) <= 4, tid + ":opening_sentences")
    mentions = objects(task.get("must_mention"), tid + ":mentions")
    require(3 <= len(mentions) <= 5, tid + ":mention_count")
    require(len({m.get("id") for m in mentions}) == len(mentions), tid + ":mention_ids")
    require(sum(m.get("kind") == "previous_ending" for m in mentions) == 1, tid + ":previous_ending_count")
    evidence = []
    for mention in mentions:
        kind = mention.get("kind")
        require(text(mention.get("id")) and text(mention.get("text")), tid + ":mention_fields")
        require(kind in {"previous_ending", "character_state", "open_thread", "plan"}, tid + ":mention_kind")
        nums = refs(mention.get("evidence_chapters"), wk, tid, kind != "plan")
        require(all(n <= k for n in nums), tid + ":future_evidence")
        if kind == "previous_ending":
            require(k in nums, tid + ":ending_evidence")
        if kind == "plan":
            require(any(p["chapter"] == k+1 for p in WORKS[wk]["plans"]), tid + ":recap_plan")
        evidence.extend(mention["evidence_chapters"])
    negatives = objects(task.get("must_not"), tid + ":must_not")
    require(2 <= len(negatives) <= 4, tid + ":must_not_count")
    require(any(m.get("kind") == "draft_only" for m in negatives), tid + ":draft_only_missing")
    for negative in negatives:
        require(negative.get("kind") in {"stale_state", "resolved_thread", "draft_only", "later_chapter"} and text(negative.get("text")), tid + ":must_not_fields")
    return evidence


def review_quote_list(value, wk, label):
    result = []
    for quote in objects(value, label):
        chapter, content = quote.get("chapter"), quote.get("text")
        position = quote_position(wk, chapter, content, label, record=True)
        require(integer(quote.get("han_position")) and quote["han_position"] == position, label + ":recorded_position")
        result.append((chapter, content, position))
    require(len({(c, q) for c, q, _ in result}) == len(result), label + ":duplicate_quote")
    return result


def review_task(task):
    tid, wk = task["id"], task["work"]
    record = REVIEWS.get(tid, {})
    require(text(record.get("rationale")), tid + ":review_rationale")
    require(record.get("copy_check") == "pass", tid + ":review_copy")
    quotes = review_quote_list(record.get("evidence_quotes"), wk, tid)
    evidence = list(task.get("evidence_chapters", []))
    if task["suite"] == "recap":
        for mention in task["must_mention"]:
            if mention["kind"] != "plan":
                evidence.extend(mention["evidence_chapters"])
                if mention["kind"] == "previous_ending":
                    require(any(c in mention["evidence_chapters"] and SOURCES[wk]["numbers"].get(c) == task["upto_chapter"] and p > 1500 for c, _, p in quotes), tid + ":recap_ending_deep")
    require(set(evidence) <= {c for c, _, _ in quotes}, tid + ":review_evidence_coverage")
    if "evidence_quotes" in task:
        require(set(zip(task["evidence_chapters"], task["evidence_quotes"])) <= {(c, q) for c, q, _ in quotes}, tid + ":review_task_quote_alignment")
    if task.get("paraphrased"):
        paraphrase = record.get("paraphrase", {})
        require(text(paraphrase.get("source")) and text(paraphrase.get("question")), tid + ":review_paraphrase")
    if task.get("qa_type") == "answerable_multi":
        require(text(record.get("multi_chapter_necessity")), tid + ":review_multi_necessity")
    if task["suite"] == "follow_up":
        first_refs = record.get("first_evidence_chapters")
        refs(first_refs, wk, tid + ":first", True)
        first_quotes = review_quote_list(record.get("first_evidence_quotes"), wk, tid + ":first")
        require(set(first_refs) == {c for c, _, _ in first_quotes}, tid + ":first_evidence_coverage")
        evidence.extend(first_refs)
    check_copy(task, evidence)


def numbered_quote(wk, number, quote, label):
    matches = [c for c, n in SOURCES[wk]["numbers"].items() if integer(number) and n == number]
    require(len(matches) == 1 and text(quote) and quote in SOURCES[wk]["chapters"].get(matches[0] if matches else "", ""), label)


def review_works(review):
    records = objects(review.get("works"), "review:works")
    require(len(records) == len(WORKS) and {r.get("key") for r in records} == set(WORKS), "review:work_keys")
    for record in records:
        wk = record["key"]
        chars = objects(record.get("characters"), wk + ":characters")
        require(len(chars) >= 8, wk + ":character_count")
        require(len({c.get("name") for c in chars}) == len(chars), wk + ":character_unique")
        for char in chars:
            require(char.get("name") in WORKS[wk]["names"] and strings(char.get("aliases")), wk + ":character_fields")
            require(all(a in WORKS[wk]["names"] for a in char["aliases"]), wk + ":alias_names")
        require(sum(bool(c.get("aliases")) for c in chars) >= 3, wk + ":alias_count")
        transfers = objects(record.get("transfers"), wk + ":transfers")
        for transfer in transfers:
            require(text(transfer.get("object")), wk + ":transfer_object")
            numbered_quote(wk, transfer.get("chapter"), transfer.get("quote"), wk + ":transfer_quote")
        require(len({t.get("object") for t in transfers}) >= 3, wk + ":transfer_count")
        require(len({t.get("object") for t in transfers if integer(t.get("chapter")) and t["chapter"] > 15}) >= 1, wk + ":late_transfers")
        states = objects(record.get("states"), wk + ":states")
        require(len(states) >= 4, wk + ":state_count")
        distant = 0
        for state in states:
            before, after = state.get("before_chapter"), state.get("after_chapter")
            require(integer(before) and integer(after) and before < after, wk + ":state_order")
            numbered_quote(wk, before, state.get("before_quote"), wk + ":state_before")
            numbered_quote(wk, after, state.get("after_quote"), wk + ":state_after")
            distant += integer(before) and integer(after) and after - before >= 10
        require(distant >= 2, wk + ":distant_states")
        require(isinstance(record.get("threads"), list) and len(record["threads"]) == len(WORKS[wk]["foreshadows"]), wk + ":review_threads")
        conflicts = objects(record.get("intentional_conflicts"), wk + ":conflicts")
        require(2 <= len(conflicts) <= 3, wk + ":intentional_count")
        for conflict in conflicts:
            chapters, quotes = conflict.get("chapters"), conflict.get("quotes")
            require(isinstance(chapters, list) and len(chapters) == 2 and len(set(chapters)) == 2 and strings(quotes, True) and len(quotes) == 2, wk + ":conflict_pair")
            for number, quote in zip(chapters, quotes):
                numbered_quote(wk, number, quote, wk + ":conflict_quote")
    independent = review.get("independent_review", {})
    require(independent.get("reviewer_not_author") is True, "review:independent_reviewer")
    require(independent.get("status") == "completed", "review:independent_status")
    require(integer(independent.get("unresolved_unintentional_conflicts")) and independent["unresolved_unintentional_conflicts"] == 0, "review:unresolved_conflicts")
    require(independent.get("reviewed_chapter_counts") == {wk:len(s["chapters"]) for wk, s in SOURCES.items()}, "review:chapter_coverage")
    require(isinstance(independent.get("findings"), list), "review:findings")


def manifest_checks():
    expected = sorted(["tasks.json"] + [p.relative_to(ROOT).as_posix() for p in (ROOT / "works").rglob("*") if p.is_file()])
    actual = []
    for index, line in enumerate(read_utf8(ROOT / "set.sha256").splitlines()):
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        require(match is not None, f"manifest:line:{index+1}")
        if match:
            digest, relative = match.groups()
            actual.append(relative)
            # Only admitted manifest targets may be opened, even inside this set.
            require(relative in expected, f"manifest:unexpected:{index+1}")
            if relative in expected:
                path = local_path(relative)
                require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, f"manifest:hash:{index+1}")
    require(actual == expected, "manifest:coverage_and_order")


def work_distribution_checks(works):
    require(len(works) == (1 if DEV else 2), "work_count")
    require(len({w.get("source_file") for w in works}) == len(works), "work_source_unique")
    for i, work in enumerate(works):
        for other in works[i+1:]:
            require(not set(work.get("names", [])) & set(other.get("names", [])), "work_names_disjoint")


def task_distribution_checks(tasks):
    """Per-work requirements cannot be offset by excesses in the other work."""
    count = 1 if DEV else 2
    expected_suites = Counter({"qa":9, "recap":2, "fix":2, "follow_up":2})
    expected_qa = Counter({"answerable_single":2, "answerable_multi":3, "not_in_text":2, "conflicting":2})
    require(Counter(t.get("suite") for t in tasks) == Counter({k:v*count for k, v in expected_suites.items()}), "task_distribution")
    qa = [t for t in tasks if t.get("suite") == "qa"]
    require(Counter(t.get("qa_type") for t in qa) == Counter({k:v*count for k, v in expected_qa.items()}), "qa_distribution")
    require(sum(t.get("paraphrased") is True for t in qa)*2 >= len(qa), "qa_paraphrase_count")
    answerable = [t for t in qa if t.get("qa_type", "").startswith("answerable")]
    require(sum(t.get("paraphrased") is True for t in answerable)*2 >= len(answerable), "answerable_paraphrase_count")
    require(sum("selection" in t for t in qa) >= 3, "qa_selection_count")
    if not DEV:
        require(len({t.get("category") for t in tasks if t.get("suite") == "fix"}) >= 3, "fix_categories")
    deep_counts = {}
    for wk in WORKS:
        own = [t for t in tasks if t.get("work") == wk]
        require(Counter(t.get("suite") for t in own) == expected_suites, wk + ":task_distribution")
        require(Counter(t.get("qa_type") for t in own if t.get("suite") == "qa") == expected_qa, wk + ":qa_distribution")
        require(sorted(t.get("upto_chapter") for t in own if t.get("suite") == "recap") == [15, 30], wk + ":recap_distribution")
        eligible = [t for t in own if t.get("suite") == "follow_up" or (t.get("suite") == "qa" and t.get("qa_type", "").startswith("answerable"))]
        deep_counts[wk] = sum(t.get("deep") is True for t in eligible)
        require(DEV or deep_counts[wk] >= 5, wk + ":deep_answerable_count")
    require(DEV or sum(deep_counts.values()) >= 12, "deep_answerable_count")
    return deep_counts


def position_distribution_checks():
    counts = {}
    for wk in WORKS:
        positions = [position for (key, _, _), position in POSITIONS.items() if key == wk]
        after_1500 = sum(p > 1500 for p in positions)
        after_2500 = sum(p > 2500 for p in positions)
        require(bool(positions) and after_1500*2 >= len(positions), wk + ":quote_distribution_1500")
        require(bool(positions) and after_2500*3 >= len(positions), wk + ":quote_distribution_2500")
        counts[wk] = {"evidence_quotes_unique":len(positions), "evidence_after_1500":after_1500, "evidence_after_2500":after_2500}
    return counts


def main():
    global DEV, SET, WORKS, SOURCES, REVIEWS
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--staged-dev", action="store_true", help="Check this dev directory only; never read formal.")
    args = parser.parse_args()
    if args.staged_dev and ROOT.name != "eval_set_a1c_dev":
        print("FAIL staged_dev_requires_dev_path")
        return 1
    data = json.loads(read_utf8(ROOT / "tasks.json"))
    SET = data.get("set_id")
    require(SET in {"a1c-dev", "a1c-formal"}, "set_id")
    DEV = SET == "a1c-dev"
    require(ROOT.name == "eval_set_" + str(SET).replace("-", "_"), "set_directory")
    require(not args.staged_dev or DEV, "staged_dev_set_id")
    require(data.get("version") == "a1c-1", "version")
    require(text(data.get("author")), "author")
    works = objects(data.get("works"), "works")
    work_distribution_checks(works)
    require(all(text(w.get("key")) for w in works), "work_key_type")
    WORKS = {w["key"]:w for w in works}
    require(len(WORKS) == len(works), "work_keys")
    SOURCES = {w["key"]:parse_work(w) for w in works}
    review = json.loads(read_utf8(ROOT / "authoring" / "self-review.json"))
    records = objects(review.get("tasks"), "review:tasks")
    REVIEWS = {r["id"]:r for r in records}
    tasks = objects(data.get("tasks"), "tasks")
    require(len(REVIEWS) == len(records) == len(tasks) and set(REVIEWS) == {t.get("id") for t in tasks}, "review:task_ids")
    require(len({t.get("id") for t in tasks}) == len(tasks), "task_ids")
    for task in tasks:
        tid, wk, suite = task["id"], task["work"], task["suite"]
        require(text(tid) and tid.startswith("a1cd-" if DEV else "a1cf-"), "task_prefix")
        require(text(task.get("note")), tid + ":note")
        require(wk in WORKS, tid + ":work")
        if wk not in WORKS:
            continue
        if suite in {"qa", "follow_up"}:
            validate_qa(task, suite == "follow_up")
        elif suite == "fix":
            validate_fix(task)
        elif suite == "recap":
            validate_recap(task)
        review_task(task)
    deep_counts = task_distribution_checks(tasks)
    deep_count = sum(deep_counts.values())
    review_works(review)
    position_counts = position_distribution_checks()
    positions = list(POSITIONS.values())
    after_1500 = sum(p > 1500 for p in positions)
    after_2500 = sum(p > 2500 for p in positions)
    manifest_checks()
    require((ROOT / "README.md").is_file(), "readme_missing")
    for path in ROOT.rglob("*"):
        if path.is_file() and path.suffix in {".json", ".md", ".py", ".sha256"}:
            local_path(path.relative_to(ROOT).as_posix())
            read_utf8(path)
    lengths = [n for s in SOURCES.values() for n in s["lengths"]]
    result = {"status":"FAIL" if ERRORS else "PASS", "set_id":SET, "works":len(works), "chapters":len(lengths), "chapter_han_min":min(lengths, default=0), "chapter_han_max":max(lengths, default=0), "total_han":sum(lengths), "tasks":len(tasks), "deep_answerable_follow_up":deep_count, "evidence_quotes_unique":len(positions), "evidence_after_1500":after_1500, "evidence_after_2500":after_2500, "errors":len(ERRORS), "copy_errors":COPY_ERRORS, "scope":"this_set_only", "semantic_acceptance":False, "model_calls":0}
    result["per_work"] = [{"work":wk, "chapters":len(SOURCES[wk]["lengths"]), "chapter_han_min":min(SOURCES[wk]["lengths"], default=0), "chapter_han_max":max(SOURCES[wk]["lengths"], default=0), "total_han":sum(SOURCES[wk]["lengths"]), "tasks":sum(t.get("work") == wk for t in tasks), "deep_answerable_follow_up":deep_counts[wk], **position_counts[wk]} for wk in WORKS]
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    for error in ERRORS:
        print("ERROR " + error)
    return int(bool(ERRORS))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (KeyError, TypeError, ValueError, OSError, IndexError, AttributeError) as exc:
        # Exception payloads may contain source text; never print them.
        print("FAIL malformed_or_missing_input exception=" + type(exc).__name__)
        sys.exit(1)
