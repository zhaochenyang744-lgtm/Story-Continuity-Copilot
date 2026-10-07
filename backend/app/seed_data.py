"""Synthetic, public seed content for the Story Continuity application.

Since v1.7.0 every account has one sample work (示例作品). Its content lives in seed/sample_work.json, in
the format the content authors write (see the v1.7.0 sample-work task); this module validates it once at
import and exposes it under the names the database layer has always used.
"""

from __future__ import annotations

import json
import os
import pathlib
from typing import Any

SEED_ORIGIN = {
    "origin": "original_demo_specific_web_demo_stage1",
    "created_on": "2026-08-25",
    "restriction": "Synthetic public sample; no private author content or runtime account data is used.",
}

SAMPLE_WORK_PATH = pathlib.Path(__file__).with_name("seed") / "sample_work.json"
# Tests pin the sample work to a fixture (STORY_SAMPLE_WORK_FILE) so behaviour tests do not depend on the
# published sample text; production always reads the file above.
_override = os.environ.get("STORY_SAMPLE_WORK_FILE")

NATURE_CLASSIFICATION = {"confirmed_conflict": "conflict", "possible_conflict": "conflict", "state_change": "conflict", "insufficient_evidence": "insufficient_evidence"}
NATURE_EVIDENCE = {
    # nature: (relation, sufficiency, role)
    "confirmed_conflict": ("contradicts", "sufficient", "prior_state"),
    "possible_conflict": ("context", "sufficient", "current_context"),
    "state_change": ("context", "sufficient", "prior_state"),
    "insufficient_evidence": ("context", "insufficient", "missing_link"),
}
NATURE_ACTIONS = {
    "confirmed_conflict": ["edit", "apply_suggestion", "keep_intentional", "false_positive"],
    "possible_conflict": ["edit", "keep_intentional", "false_positive"],
    "state_change": ["edit", "keep_intentional", "false_positive"],
    "insufficient_evidence": [],
}
ROLE_TYPES = {"protagonist", "ally", "antagonist", "supporting", "other"}
# Built-in setting categories, by their Chinese name; anything else becomes an author category.
SETTING_TYPES = {"地点": "location", "规则": "rule", "组织": "organization", "物品": "object", "术语": "term"}


def _load(path: pathlib.Path = SAMPLE_WORK_PATH) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    passages = {item["id"]: (chapter["id"], item["text"]) for chapter in data["chapters"] for item in chapter["passages"]}
    for chapter in data["chapters"]:
        for item in chapter["passages"]:
            if item["text"] not in chapter["body"]:
                raise ValueError(f"sample work: passage {item['id']} is not verbatim in chapter {chapter['number']}")
    for issue in data["draft_issues"]:
        # Verbatim sentences are checked by the authoring tool (check.py); the legacy fixture abbreviates one.
        if issue["evidence_passage"] not in passages or issue["nature"] not in NATURE_CLASSIFICATION:
            raise ValueError(f"sample work: draft issue is inconsistent: {issue['sentence'][:30]}")
    for record in data["memory"]:
        if record["passage"] not in passages:
            raise ValueError(f"sample work: fact {record['subject']} cites an unknown passage")
    return data


SAMPLE_WORK = _load(pathlib.Path(_override) if _override else SAMPLE_WORK_PATH)

# Raised whenever the sample work changes (v2_database migrations re-create sample works from it).
DEMO_SEED_VERSION = int(SAMPLE_WORK.get("seed_version", 4))

PROJECT = {
    "id": "project-grey-harbor-echo",
    "title": SAMPLE_WORK["project"]["title"],
    "genre": SAMPLE_WORK["project"].get("genre", ""),
    "summary": SAMPLE_WORK["project"]["summary"],
    "data_origin": "demo-specific-original",
}

CHAPTERS = [
    (chapter["id"], chapter["number"], chapter["title"], chapter["summary"], [(item["id"], item["label"], item["text"]) for item in chapter["passages"]])
    for chapter in SAMPLE_WORK["chapters"]
]
CHAPTER_BODIES = {chapter["id"]: chapter["body"] for chapter in SAMPLE_WORK["chapters"]}
_chapter_by_number = {chapter["number"]: chapter["id"] for chapter in SAMPLE_WORK["chapters"]}

DRAFT = {
    "id": "draft-sample-current",
    "chapter_number": SAMPLE_WORK["draft"]["number"],
    "title": SAMPLE_WORK["draft"]["title"],
    "body": SAMPLE_WORK["draft"]["body"],
    "revision": 1,
    "status": "saved",
}

MEMORY_RECORDS = [
    (record.get("key") or f"sample-memory-{index}", record["type"], record["subject"], record["predicate"], record["value"], record["passage"])
    for index, record in enumerate(SAMPLE_WORK["memory"], 1)
]
_memory_by_passage = {}
for _key, *_rest, _passage in MEMORY_RECORDS:
    _memory_by_passage.setdefault(_passage, _key)


def _review_issue(issue: dict[str, Any]) -> dict[str, Any]:
    relation, sufficiency, role = NATURE_EVIDENCE[issue["nature"]]
    return {
        "claim_text": issue["sentence"],
        "classification": NATURE_CLASSIFICATION[issue["nature"]],
        "nature": issue["nature"],
        "category": issue["category"],
        "severity": issue["severity"],
        "explanation": issue["explanation"],
        "reasoning": issue["reasoning"],
        "evidence_span_id": issue["evidence_passage"],
        "evidence_relation": relation,
        "evidence_sufficiency": sufficiency,
        "evidence_role": role,
        "suggested_revision": issue.get("suggested_revision"),
        "available_actions": NATURE_ACTIONS[issue["nature"]],
        "related_memory_id": issue.get("related_memory") or _memory_by_passage.get(issue["evidence_passage"]) or MEMORY_RECORDS[0][0],
        "proposed_memory_change": issue.get("proposed_memory_change"),
    }


# Deterministic sample-work review material: authored fixture data, never stored or simulated Provider
# output. Identifiers are rebound to each new account's project-local chapters, spans, facts, draft and run.
DEMO_REVIEW_ISSUES = [_review_issue(issue) for issue in SAMPLE_WORK["draft_issues"]]

# A preset chapter check of the sample work, so a visitor can see what checking written chapters gives
# without running one. Labelled as a sample on the page.
DEMO_CHAPTER_CHECK = {
    "chapters": [_chapter_by_number[number] for number in SAMPLE_WORK["chapter_check_sample"]["chapters"]],
    "issues": [
        {"chapter": _chapter_by_number[issue["chapter"]], "sentence": issue["sentence"], "nature": issue["nature"], "category": issue["category"],
         "severity": issue["severity"], "explanation": issue["explanation"], "evidence_span": issue["evidence_passage"]}
        for issue in SAMPLE_WORK["chapter_check_sample"]["issues"]
    ],
}

CHARACTERS = [
    {**person, "role": person["role"] if person["role"] in ROLE_TYPES else "other", "aliases": list(person.get("aliases") or [])}
    for person in SAMPLE_WORK.get("characters", [])
]
SETTINGS = [{**item, "entry_type": SETTING_TYPES.get(item["category"])} for item in SAMPLE_WORK.get("settings", [])]
FORESHADOWS = list(SAMPLE_WORK.get("foreshadows", []))
PLANS = list(SAMPLE_WORK.get("plans", []))
