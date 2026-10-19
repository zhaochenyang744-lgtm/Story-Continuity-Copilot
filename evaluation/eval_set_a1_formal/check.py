"""A1 offline structural validator. No imports from the application, no writes.

Only this set and the sibling A1 checker bytes are read. Output is aggregate-only.
Chinese length = Han characters; English length = alphabetic words with internal
apostrophes/hyphens. Copy thresholds are inclusive (8 characters / 6 words).
Names break comparison runs; removing them must not join unrelated prose.
Only --staged-dev may defer peer identity while dev is committed before formal.
"""
from pathlib import Path
from collections import Counter
import hashlib
import json
import re
import sys
import unicodedata

ROOT = Path(__file__).resolve().parent
ERRORS = []
QA_TYPES = {"answerable_single", "answerable_multi", "not_in_text", "conflicting"}
CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule"}
HAN = re.compile(r"[\u3400-\u9fff\U00020000-\U0002ebef]")
WORD = re.compile(r"[A-Za-z]+(?:['’-][A-Za-z]+)*")
CHAPTER = re.compile(r"^# ([^\n]+)\n(.*?)(?=^# |\Z)", re.M | re.S)
ZH_ORDINALS = ["一", "二", "三", "四", "五", "六", "七", "八", "九", "十", "十一", "十二"]
REFERENT = re.compile(r"她|他|它|这|那|此|\b(?:she|he|it|this|that|these|those|her|his|its)\b", re.I)
BELIEF = re.compile(r"认为|以为|觉得|相信|认定|记得|听说|据说|回忆|回想|回顾|"
                    r"\b(?:think(?:s|ing)?|thought|believ(?:e[ds]?|ing)|assum(?:e[ds]?|ing)|"
                    r"remember(?:s|ed|ing)?|hear(?:s|ing)?|heard|apparently|recall(?:s|ed|ing)?)\b", re.I)


def selection_rules(question, selection, names):
    return bool(REFERENT.search(question)), not any(
        n.casefold() in selection.casefold() and n.casefold() in question.casefold()
        for n in names)


def narrative_fact(text):
    # Apostrophes within English words are not dialogue delimiters.
    return not BELIEF.search(text) and not re.search(r'''[“”「」『』"]|(?:^|\s)['‘]''', text)


def require(condition, where, rule):
    if not condition:
        ERRORS.append(f"{where}: {rule}")
    return bool(condition)


def field(obj, key, typ, where):
    value = obj.get(key) if isinstance(obj, dict) else None
    ok = type(value) is typ
    require(ok, where, f"field_type:{key}")
    if ok and typ is str:
        require(bool(value.strip()), where, f"empty:{key}")
    return value if ok else typ()


def strings(obj, key, where, nonempty=True):
    values = field(obj, key, list, where)
    require(all(type(v) is str and bool(v.strip()) for v in values), where, f"string_list:{key}")
    if nonempty:
        require(bool(values), where, f"empty_list:{key}")
    return [v for v in values if type(v) is str]


def read_text(path):
    raw = path.read_bytes()
    require(not raw.startswith(b"\xef\xbb\xbf"), path.name, "bom")
    require(b"\r" not in raw, path.name, "non_lf")
    return raw.decode("utf-8")


def count(text, lang):
    return len(HAN.findall(text)) if lang == "zh" else len(WORD.findall(text))


def sentences(text):
    return len(re.findall(r"[^。！？.!?]+[。！？.!?]+|[^。！？.!?]+$", text.strip()))


def grams(text, names, lang):
    # Protect only declared proper names, not sentences containing those names.
    pattern = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    flags = re.I if lang == "en" else 0
    parts = re.split(pattern, text, flags=flags) if pattern else [text]
    size = 8 if lang == "zh" else 6
    output = set()
    for part in parts:
        if lang == "en":
            seq = WORD.findall(part.lower())
        else:
            seq = [c for c in part if not c.isspace() and unicodedata.category(c)[0] not in "PZ"]
        output.update(tuple(seq[i:i + size]) for i in range(len(seq) - size + 1))
    return output


def main():
    data = json.loads(read_text(ROOT / "tasks.json"))
    require(type(data) is dict, "root", "object")
    require(field(data, "version", str, "root") == "a1-1", "root", "version")
    sid = field(data, "set_id", str, "root")
    require(sid in {"a1-dev", "a1-formal"}, "root", "set_id")
    formal = sid == "a1-formal"
    factor = 2 if formal else 1
    field(data, "author", str, "root")
    works = field(data, "works", list, "root")
    tasks = field(data, "tasks", list, "root")
    require(len(works) == (5 if formal else 2), "works", "count")
    book, chapter_maps, source_files, summaries = {}, {}, [], []
    for w in works:
        require(type(w) is dict, "works", "object")
        key = field(w, "key", str, "work")
        require(bool(re.fullmatch(r"[a-z][a-z0-9_]*", key)), "work", "key_format")
        require(key not in book, "work", "unique_key")
        book[key] = w
        field(w, "title", str, key)
        lang = field(w, "language", str, key)
        purpose = field(w, "purpose", str, key)
        require(lang in {"zh", "en"}, key, "language")
        require(purpose in {"general", "safety"}, key, "purpose")
        names = strings(w, "names", key)
        require(len(names) == len(set(names)), key, "unique_names")
        source = field(w, "source_file", str, key)
        require(bool(re.fullmatch(r"works/[a-z0-9_]+\.md", source)), key, "source_path")
        path = (ROOT / source).resolve()
        require(path.is_relative_to(ROOT / "works"), key, "source_scope")
        if not path.is_relative_to(ROOT / "works"):
            continue
        source_files.append(source)
        text = read_text(path)
        parts = CHAPTER.findall(text)
        expected = 6 if purpose == "safety" else 12
        require(len(parts) == expected, key, "chapter_count")
        titles = [title for title, _ in parts]
        require(len(titles) == len(set(titles)), key, "unique_chapter_titles")
        chapter_maps[key] = dict(parts)
        for i, title in enumerate(titles):
            prefix = f"Chapter {i + 1} " if lang == "en" else f"第{ZH_ORDINALS[i]}章 "
            require(title.startswith(prefix), key, "chapter_number")
        sizes = [count(body, lang) for _, body in parts]
        low, high = ((400, 600) if purpose == "safety" else (600, 900)) if lang == "zh" else (350, 550)
        require(all(low <= n <= high for n in sizes), key, "chapter_length")
        for name in names:
            require(name in text, key, "name_not_in_source")
        summaries.append({"language": lang, "purpose": purpose, "chapters": len(parts),
                          "length_min": min(sizes, default=0), "length_max": max(sizes, default=0)})
        if purpose == "general":
            plans = field(w, "plans", list, key)
            counts = Counter()
            for p in plans:
                counts[field(p, "chapter", int, key)] += 1
                field(p, "text", str, key)
            require(set(counts) == {7, 13} and all(1 <= n <= 2 for n in counts.values()), key, "plans")
            shadows = field(w, "foreshadows", list, key)
            require(len(shadows) >= 2, key, "foreshadow_count")
            early, opened = False, False
            for f in shadows:
                field(f, "title", str, key)
                planted = field(f, "planted_chapter", int, key)
                state = field(f, "status", str, key)
                require(1 <= planted <= 12, key, "planted_range")
                require(state in {"open", "resolved"}, key, "foreshadow_status")
                if state == "resolved":
                    resolved = field(f, "resolved_chapter", int, key)
                    require(planted <= resolved <= 12, key, "resolved_range")
                    early |= resolved < 9
                else:
                    opened = True
                    require("resolved_chapter" not in f, key, "open_has_resolution")
            require(early and opened, key, "foreshadow_coverage")
            draft = field(w, "shared_draft", dict, key)
            title = field(draft, "chapter_title", str, key)
            require(title.startswith("Chapter 13 " if lang == "en" else "第十三章 "), key, "draft_chapter")
            body = field(draft, "body", str, key)
            field(draft, "draft_only_fact", str, key)
            dl, dh = (300, 500) if lang == "zh" else (180, 300)
            require(dl <= count(body, lang) <= dh, key, "shared_draft_length")
            require(not any(grams(body, names, lang) & grams(b, names, lang) for _, b in parts), key, "copy:shared_draft")
        else:
            require(lang == "zh", key, "safety_language")
            require("plans" not in w and "foreshadows" not in w, key, "safety_metadata")
    require(Counter((w["language"], w["purpose"]) for w in works) ==
            (Counter({("zh", "general"): 3, ("en", "general"): 1, ("zh", "safety"): 1}) if formal
             else Counter({("zh", "general"): 2})), "works", "composition")
    all_work_files = sorted(p.relative_to(ROOT).as_posix() for p in (ROOT / "works").rglob("*") if p.is_file())
    require(sorted(source_files) == all_work_files, "works", "unreferenced_or_duplicate_file")
    ids, suites, qtypes, per_work, categories = set(), Counter(), Counter(), Counter(), Counter()
    selections, answerable, paraphrases, latest = 0, 0, 0, 0
    recap_pairs, safe_forms, safe_works, injected_chapters = Counter(), Counter(), set(), set()
    for t in tasks:
        tid = field(t, "id", str, "task")
        require(tid not in ids, tid, "unique_id")
        ids.add(tid)
        key = field(t, "work", str, tid)
        suite = field(t, "suite", str, tid)
        field(t, "note", str, tid)
        require(key in book, tid, "work_reference")
        require(suite in {"qa", "recap", "fix", "safe"}, tid, "suite")
        suites[suite] += 1
        if key not in book:
            continue
        w, chapters = book[key], chapter_maps[key]
        lang, names = w["language"], w["names"]
        refs = []
        if suite != "recap":
            refs = strings(t, "evidence_chapters", tid)
            require(len(refs) == len(set(refs)), tid, "unique_evidence")
            require(all(r in chapters for r in refs), tid, "chapter_reference")
        inputs = []
        is_qa = suite == "qa" or (suite == "safe" and "question" in t)
        is_fix = suite == "fix" or (suite == "safe" and "draft" in t)
        if suite == "safe":
            require(is_qa != is_fix, tid, "safe_task_form")
        if is_qa:
            qt = field(t, "qa_type", str, tid)
            require(qt in QA_TYPES, tid, "qa_type")
            question = field(t, "question", str, tid)
            require(sentences(question) == 1, tid, "question_sentence_count")
            inputs.append(question)
            paraphrased = field(t, "paraphrased", bool, tid)
            points = strings(t, "answer_points", tid, nonempty=qt != "not_in_text")
            strings(t, "forbidden_claims", tid)
            if qt == "not_in_text":
                require(not points, tid, "not_in_text_points")
            if qt == "conflicting":
                require(len(refs) == 2, tid, "conflicting_two_chapters")
            if qt == "answerable_single":
                require(len(refs) == 1, tid, "single_one_chapter")
            if qt == "answerable_multi":
                require(len(refs) >= 2, tid, "multi_two_chapters")
            if "selection" in t:
                selection = field(t, "selection", str, tid)
                require(len(selection) <= 80, tid, "selection_length")
                require(selection in w.get("shared_draft", {}).get("body", ""), tid, "selection_substring")
                referent, excludes_names = selection_rules(question, selection, names)
                require(referent, tid, "selection_referent")
                require(excludes_names, tid, "selection_repeats_name")
                inputs.append(selection)
                selections += suite == "qa"
            if suite == "qa":
                require(w["purpose"] == "general", tid, "qa_general")
                qtypes[qt] += 1
                per_work[key] += 1
                if qt.startswith("answerable_"):
                    answerable += 1
                    paraphrases += paraphrased
                if qt == "answerable_multi" and re.search(r"现在|最后|目前|如今|current|now|finally|end of", question, re.I):
                    latest += 1
        if is_fix:
            draft = field(t, "draft", str, tid)
            conflict = field(t, "conflict_sentence", str, tid)
            cat = field(t, "category", str, tid)
            field(t, "fix_idea", str, tid)
            require(cat in CATEGORIES, tid, "category")
            require(conflict in draft, tid, "conflict_substring")
            require(sentences(conflict) == 1, tid, "conflict_one_sentence")
            require(narrative_fact(conflict), tid, "conflict_not_narrative_fact")
            require(len(draft) <= 200 and 1 <= sentences(draft) <= 3, tid, "fix_length")
            require(any(n in conflict and any(n in chapters.get(r, "") for r in refs) for n in names), tid, "fix_shared_entity")
            inputs.append(draft)
            if suite == "fix":
                categories[cat] += 1
        if suite == "recap":
            k = field(t, "upto_chapter", int, tid)
            require(k in {6, 12} and w["purpose"] == "general", tid, "recap_cutoff")
            recap_pairs[(key, k)] += 1
            opening = field(t, "draft_opening", str, tid)
            require(2 <= sentences(opening) <= 4, tid, "opening_sentences")
            inputs.append(opening)
            refs = list(chapters)[:k]
            mentions = field(t, "must_mention", list, tid)
            banned = field(t, "must_not", list, tid)
            require(3 <= len(mentions) <= 5, tid, "mention_count")
            require(2 <= len(banned) <= 4, tid, "must_not_count")
            kinds, mids = [], []
            for m in mentions:
                mids.append(field(m, "id", str, tid))
                kind = field(m, "kind", str, tid)
                kinds.append(kind)
                field(m, "text", str, tid)
                require(kind in {"previous_ending", "character_state", "open_thread", "plan"}, tid, "mention_kind")
                mr = strings(m, "evidence_chapters", tid, nonempty=kind != "plan")
                require(all(r in refs for r in mr), tid, "recap_future_evidence")
                if kind == "previous_ending":
                    require(list(chapters)[k - 1] in mr, tid, "ending_cutoff_reference")
                if kind == "plan":
                    require(not mr, tid, "plan_uses_metadata")
            require(len(mids) == len(set(mids)), tid, "unique_mention_ids")
            require(kinds.count("previous_ending") == 1, tid, "previous_ending_count")
            banned_kinds = []
            for b in banned:
                kind = field(b, "kind", str, tid)
                banned_kinds.append(kind)
                field(b, "text", str, tid)
                require(kind in {"stale_state", "resolved_thread", "draft_only", "later_chapter"}, tid, "must_not_kind")
                require(not (k == 12 and kind == "later_chapter"), tid, "no_unwritten_future_gold")
            require("draft_only" in banned_kinds, tid, "draft_only_gold")
        if suite == "safe":
            safe_works.add(key)
            require(w["purpose"] == ("safety" if formal else "general"), tid, "safe_work_purpose")
            if "injection" in t:
                inj = field(t, "injection", dict, tid)
                loc = field(inj, "location", str, tid)
                txt = field(inj, "text", str, tid)
                if loc == "draft":
                    safe_forms["draft"] += 1
                    require(is_fix and txt in t.get("draft", ""), tid, "draft_injection_substring")
                else:
                    safe_forms["source"] += 1
                    require(loc in chapters and txt in chapters.get(loc, ""), tid, "source_injection_substring")
                    require(loc in refs, tid, "injected_chapter_used")
                    injected_chapters.add((key, loc))
            else:
                safe_forms["direct"] += 1
                require(is_qa, tid, "direct_is_qa")
                field(t, "expected_behaviour", str, tid)
        for i, value in enumerate(inputs):
            require(not any(grams(value, names, lang) & grams(chapters.get(r, ""), names, lang) for r in refs), tid, f"copy:input_{i}")
    require(suites == Counter({"qa": 12 * factor, "recap": 4 * factor, "fix": 6 * factor, "safe": 3 * factor}), "tasks", "suite_distribution")
    require(qtypes == Counter({q: 3 * factor for q in QA_TYPES}), "qa", "type_distribution")
    require(all(per_work[w["key"]] == 6 for w in works if w["purpose"] == "general"), "qa", "per_work_count")
    require(selections >= 6, "qa", "selection_minimum")
    require(paraphrases * 2 >= answerable, "qa", "paraphrase_minimum")
    require(latest >= (3 if formal else 2), "qa", "latest_state_minimum")
    require(len(categories) >= 6, "fix", "category_coverage")
    require(recap_pairs == Counter({(w["key"], k): 1 for w in works if w["purpose"] == "general" for k in (6, 12)}), "recap", "pairs")
    require(safe_forms == (Counter(source=3, draft=2, direct=1) if formal else Counter(source=1, draft=1, direct=1)), "safe", "forms")
    require(len(safe_works) == 1, "safe", "single_work")
    if not formal:
        for t in tasks:
            if t.get("suite") != "safe":
                used = list(t.get("evidence_chapters", []))
                used += [r for m in t.get("must_mention", []) for r in m.get("evidence_chapters", [])]
                require(not any((t["work"], r) in injected_chapters for r in used), t["id"], "dev_injection_evidence_isolation")
    review = json.loads(read_text(ROOT / "authoring" / "self-review.json"))
    r_tasks = field(review, "tasks", list, "review")
    require(Counter(r.get("id") for r in r_tasks) == Counter(t["id"] for t in tasks), "review", "task_coverage")
    task_map = {t["id"]: t for t in tasks}
    for r in r_tasks:
        tid = r["id"]
        field(r, "rationale", str, tid)
        if "revised_in_02b" in r:
            require(field(r, "revised_in_02b", bool, tid), tid, "revision_flag")
            field(r, "revision_note", str, tid)
        require(field(r, "copy_check", str, tid) == "PASS", tid, "review_copy_status")
        quotes = field(r, "evidence_quotes", list, tid)
        require(1 <= len(quotes) <= 2, tid, "review_quote_count")
        if tid in task_map:
            t = task_map[tid]
            for q in quotes:
                chapter = field(q, "chapter", str, tid)
                quote = field(q, "text", str, tid)
                require(quote in chapter_maps[t["work"]].get(chapter, ""), tid, "quote_not_exact")
            if book[t["work"]]["language"] == "zh":
                require(sum(sentences(q["text"]) for q in quotes) <= 2, tid, "quote_two_sentence_limit")
            if t.get("paraphrased"):
                p = field(r, "paraphrase", dict, tid)
                field(p, "source_terms", str, tid)
                field(p, "question_terms", str, tid)
    r_works = field(review, "works", list, "review")
    require(Counter(r.get("key") for r in r_works) == Counter(book.keys()), "review", "work_coverage")
    for r in r_works:
        key = r["key"]
        for name in ("characters", "transfers", "states", "threads", "inconsistencies"):
            field(r, name, list, key)
        if book[key]["purpose"] == "general":
            require(len(r["characters"]) >= 4, key, "review_character_count")
            require(sum(bool(c.get("aliases")) for c in r["characters"]) >= 2, key, "review_alias_count")
            require(len(r["transfers"]) >= 2 and any(x.get("chapter", 0) > 6 for x in r["transfers"]), key, "review_transfers")
            require(len(r["states"]) >= 2 and len(r["threads"]) >= 2, key, "review_states_threads")
            require(1 <= len(r["inconsistencies"]) <= 2, key, "review_inconsistencies")
        else:
            require(len(r["characters"]) >= 3, key, "review_safety_characters")
        for conflict in r["inconsistencies"]:
            entities = strings(conflict, "entities", key)
            for q in field(conflict, "quotes", list, key):
                require(q["text"] in chapter_maps[key].get(q["chapter"], ""), key, "inconsistency_exact_quote")
            for t in tasks:
                if t["work"] == key and (t["suite"] == "fix" or t["suite"] == "safe"):
                    require(not any(e in t.get("draft", "") for e in entities), t["id"], "dedicated_entity_isolation")
    expected_files = ["tasks.json"] + all_work_files
    expected_files.sort()
    manifest = read_text(ROOT / "set.sha256").splitlines()
    parsed = []
    for line in manifest:
        m = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if require(bool(m), "hash", "line_format"):
            digest, rel = m.groups()
            parsed.append(rel)
            if require(rel in expected_files, "hash", "path_scope"):
                require(hashlib.sha256((ROOT / rel).read_bytes()).hexdigest() == digest, "hash", "digest_mismatch")
    require(parsed == expected_files, "hash", "coverage_and_order")
    for rel in ("README.md", "check.py"):
        read_text(ROOT / rel)
    sibling = ROOT.parent / ("eval_set_a1_dev" if formal else "eval_set_a1_formal") / "check.py"
    if "--staged-dev" not in sys.argv:
        require(sibling.exists() and sibling.read_bytes() == Path(__file__).read_bytes(), "checker", "byte_identity")
    else:
        require(not formal, "checker", "staging_is_dev_only")
    result = {"status": "FAIL" if ERRORS else "PASS", "set_id": sid,
              "tasks": len(tasks), "suites": dict(suites), "qa_types": dict(qtypes),
              "selections": selections, "answerable_paraphrased": paraphrases,
              "latest_state_questions": latest, "fix_categories": dict(categories),
              "safe_forms": dict(safe_forms), "works": summaries,
              "copy_errors": sum(": copy:" in e for e in ERRORS), "errors": len(ERRORS)}
    print(json.dumps(result, ensure_ascii=True, sort_keys=True))
    for err in ERRORS:
        print(err)
    return int(bool(ERRORS))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except (OSError, ValueError, KeyError, TypeError, IndexError) as exc:
        print(json.dumps({"status": "FAIL", "errors": len(ERRORS) + 1,
                          "structural_exception": type(exc).__name__}))
        sys.exit(1)
