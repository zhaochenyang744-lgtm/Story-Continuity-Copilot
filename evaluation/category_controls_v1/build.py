"""Deterministic business requests and scoring policy for the category controls.

Requests use the same one-claim shape as the prepared V7 inputs; ids are derived
from the control id so every rebuild is byte-identical. Gold stays out of the
request: only claim, selected spans, Memory and the engine schema are sent.
"""
from __future__ import annotations

import json
import pathlib

from app.engine import _continuity_schema

HERE = pathlib.Path(__file__).resolve().parent
CASES = HERE / "cases.json"


def controls():
    data = json.loads(CASES.read_text(encoding="utf-8"))
    if data.get("version") != "category-controls-v1" or len(data["cases"]) != 20:
        raise RuntimeError("category_controls_v1_drift")
    return data["cases"]


def span_id(control, label):
    return f"cc-span-{control['id']}-{label}"


def request_for(control):
    spans = [{"id": span_id(control, s["label"]), "chapter_id": f"cc-chapter-{control['id']}-{s['label']}",
              "body": s["body"], "label": s["label"], "prompt_excerpt": s["body"]} for s in control["spans"]]
    memory = [{"id": f"cc-memory-{control['id']}-{s['label']}", "memory_type": s["memory_type"],
               "subject": s["subject"], "predicate": s["predicate"], "value": s["body"],
               "source_span_id": span_id(control, s["label"])} for s in control["spans"]]
    return {"draft": {"id": f"cc-draft-{control['id']}", "revision": 1, "body": control["claim"]},
            "claims": [{"id": f"cc-claim-{control['id']}", "text": control["claim"], "allowed_evidence": spans}],
            "memory": memory, "output_schema": _continuity_schema()}


def policy(control):
    """Same rule shape as evaluation.current_flash_v7.score.policy."""
    expected = control["expected"]
    ids = lambda labels: {span_id(control, label) for label in labels}
    outcomes = {"no_issue"} if expected["outcome"] == "no_issue" else {expected["outcome"]}
    return {"allowed_outcomes": outcomes, "minimum": [ids(group) for group in expected["required"]],
            "optional": ids(expected.get("optional", [])), "premises": ids(expected.get("premises", [])),
            "category": expected["category"], "category_candidates": set(), "manual_variant": False,
            "temporal_relations": set(expected.get("temporal_relations", []))}
