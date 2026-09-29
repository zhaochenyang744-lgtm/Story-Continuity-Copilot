"""Static validation of the full-source, chapter-title authoring format.

Uses only the standard library. Does not call providers, evaluate a model,
convert cases, or decide whether gold answers are semantically correct.
"""
from collections import Counter
import json
from pathlib import Path
import re
import sys

CATEGORIES = {"attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule"}
CLASSES = {"conflict", "no_conflict", "insufficient_evidence"}
CORPUS_FIELDS = {"key", "title", "language", "source"}
CASE_FIELDS = {"id", "corpus", "draft", "expected_class", "category", "evidence",
               "designated_regression", "note"}


def chapters(source):
    matches = list(re.finditer(r"^# ([^\r\n]+)\r?$", source, re.M))
    if not matches or source[:matches[0].start()].strip():
        raise ValueError("source must begin with a level-one chapter heading")
    result = {}
    for i, match in enumerate(matches):
        title = match[1].strip()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(source)
        body = source[match.end():end].strip()
        if title in result:
            raise ValueError("duplicate chapter title: " + title)
        if not body or len(body) > 300:
            raise ValueError(f"chapter {title!r}: body length {len(body)}, expected 1..300")
        if re.search(r"^#{2,6}\s", body, re.M):
            raise ValueError("use level-one headings only")
        result[title] = body
    if not 6 <= len(result) <= 10:
        raise ValueError(f"expected 6..10 chapters, got {len(result)}")
    return result


def main(path):
    errors = []
    def require(condition, message):
        if not condition:
            errors.append(message)
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        works = data["corpora"]
        cases = data["cases"]
        require(set(data) == {"version", "author", "corpora", "cases"}, "top-level fields")
        require(4 <= len(works) <= 6, "expected 4..6 works")
        index = {}
        languages = Counter()
        for work in works:
            key = work["key"]
            require(set(work) == CORPUS_FIELDS, f"{key}: corpus fields")
            require(key not in index, f"duplicate corpus key: {key}")
            require(work["language"] in {"zh", "en"}, f"{key}: language")
            require(bool(work["title"].strip()), f"{key}: empty title")
            index[key] = chapters(work["source"])
            languages[work["language"]] += 1
            require(not any(x in work["source"] + work["title"] for x in
                            ("灰港", "纸月", "零号花园", "雾港", "白塔")), f"{key}: excluded old name")
        require(abs(languages["zh"] - languages["en"]) <= 1, "language balance")
        require(len(cases) == 36, "expected 36 cases")
        require(len({c["id"] for c in cases}) == len(cases), "duplicate case IDs")
        require(len({c["draft"] for c in cases}) == len(cases), "duplicate drafts")
        counts = Counter(c["expected_class"] for c in cases)
        require(set(counts) == CLASSES and all(counts[c] == 12 for c in CLASSES), "class counts must be 12 each")
        categories = set()
        designated = []
        for case in cases:
            cid = case["id"]
            require(set(case) == CASE_FIELDS, f"{cid}: case fields")
            require(case["corpus"] in index, f"{cid}: missing corpus")
            require(isinstance(case["designated_regression"], bool), f"{cid}: regression flag must be Boolean")
            draft = case["draft"]
            require(isinstance(draft, str) and bool(draft.strip()), f"{cid}: empty draft")
            require("\n" not in draft.strip(), f"{cid}: draft must be one paragraph")
            sentences = [s for s in re.split(r"[。！？!?]+|\.(?=\s|$)", draft) if s.strip()]
            require(1 <= len(sentences) <= 3, f"{cid}: draft must contain 1..3 sentences")
            require(not re.search(r"接上一题|上一题|previous case|previous question", draft, re.I), f"{cid}: dependent draft")
            evidence = case["evidence"]
            require(isinstance(evidence, list) and bool(evidence), f"{cid}: empty evidence")
            require(len(evidence) == len(set(evidence)), f"{cid}: duplicate evidence")
            for title in evidence:
                require(title in index.get(case["corpus"], {}), f"{cid}: unknown chapter TITLE {title!r}")
            if case["expected_class"] == "conflict":
                categories.add(case["category"])
                require(case["category"] in CATEGORIES, f"{cid}: invalid conflict category")
            else:
                require(case["category"] is None, f"{cid}: non-conflict category must be null")
            if case["designated_regression"]:
                designated.append(cid)
                require(case["expected_class"] == "conflict", f"{cid}: regression must be conflict")
        require(categories == CATEGORIES, "conflicts must cover all eight categories")
        require(len(designated) == 3, "expected exactly three designated regressions")
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        errors.append(str(error))
    for error in errors:
        print("ERROR", error)
    if errors:
        print(f"{len(errors)} ERROR")
        return 1
    print(f"PASS: {len(works)} works, {sum(len(x) for x in index.values())} chapters, {len(cases)} cases")
    print(f"Classes: {dict(counts)}; categories: {len(categories)}; designated: {designated}")
    print("0 ERROR, 0 WARN. Semantic gold, named-entity linkage and product temporal compatibility require separate review.")
    return 0


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).with_name("cases.json")))
