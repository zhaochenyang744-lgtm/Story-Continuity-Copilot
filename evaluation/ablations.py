"""The switches a development run turns the assistant's crutches off with (`app.assistant_crutches`), and the variants it tries.

Each switch names a crutch and undoes it in this process only: a module constant or function of the product replaced, never
a setting the product reads. A switch is also put in the environment (`EVALUATION_ABLATE`), so a process the run starts (A3's
runner process, `assistant_a3/child.py`) switches off the same ones (`from_env`). A variant is a change the product may take
up, run the same way before it is turned on (v2.2 rule cleanup, Desktop/v2.2任务/02-规则清理方案.md).
"""
from __future__ import annotations

import dataclasses
import importlib
import os
import re

ENV = "EVALUATION_ABLATE"
NEVER = re.compile(r"(?!)")


def _set(module, name, value):
    def apply():
        setattr(importlib.import_module(module), name, value)
    return apply


def _settings(**changes):
    """The product's settings for the run with `changes`, in both runners' settings functions."""
    def apply():
        from evaluation.assistant_a2 import run as a2
        made = a2.settings
        a2.settings = lambda price: dataclasses.replace(made(price), **changes)
    return apply


def _no_split(provider, question):
    raise RuntimeError("request list switched off")


def _no_review():
    from app.assistant import AssistantEngine
    AssistantEngine._review = lambda self, task_id, answer: answer


def _any_request_words():
    """The author's words are taken as given: not checked against the sentence, and two items may share them."""
    actions = importlib.import_module("app.assistant_actions")
    actions._request_words = lambda ctx, value: "".join(value.split()) if isinstance(value, str) else ""
    actions._shared = lambda question, one, other: False


def _all(*steps):
    def apply():
        for step in steps:
            step()
    return apply


# Change tasks (the A2 path). The word lists (prose_subject, read_only, give_up, fact_not_thread) were switched off in g1 and
# taken out in v2.1 A.
A2 = {
    "consensus": _settings(assistant_change_runs=1),
    "request_list": _set("app.assistant_requests", "call_model", _no_split),
    "second_look": _set("app.assistant_actions", "_second_look", lambda ctx, action, args, proposal, request_words: None),
    "author_value": _set("app.assistant_actions", "_author_value_missing", lambda ctx, args, proposal: None),
    "value_numbers": _set("app.assistant_actions", "numbers_in", lambda text: set()),  # change_value_not_in_evidence
    "card_review": _no_review,
    "request_words": _any_request_words,
    "alias": _set("app.assistant_actions", "_said_under_full_name", lambda ctx, after: False),
    "negated": _set("app.assistant_actions", "NEGATED_CLAUSE", NEVER),
    "title_shared": _set("app.assistant_actions", "TITLE_SHARED", 10 ** 6),
}
# Long tasks (the A3 path).
A3 = {
    "step_window": _set("app.long_tasks", "WINDOW_CHAPTERS", 10 ** 6),
    "step_repair": _set("app.long_tasks", "STEP_TRIES", 1),
    "first_time": _set("app.long_task_kinds", "NOT_YET", NEVER),
    "no_news": _all(_set("app.long_task_kinds", "NO_NEWS", NEVER), _set("app.long_task_kinds", "THREAD_TALK", NEVER)),
}
ABLATIONS = {**A2, **A3}
VARIANTS = {
    "early_agree": _settings(assistant_change_early_agree=True),  # two runs that agree, no third
    "window8": _set("app.long_tasks", "WINDOW_CHAPTERS", 8),
}


def apply(names):
    unknown = [name for name in names if name not in ABLATIONS and name not in VARIANTS]
    if unknown:
        raise ValueError(f"unknown_ablation:{','.join(unknown)}")
    for name in names:
        (ABLATIONS.get(name) or VARIANTS[name])()
    os.environ[ENV] = ",".join(names)


def from_env():
    names = [name for name in os.environ.get(ENV, "").split(",") if name]
    for name in names:
        (ABLATIONS.get(name) or VARIANTS[name])()
    return names
