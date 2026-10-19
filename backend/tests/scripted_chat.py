"""A scripted stand-in for the assistant's chat model (v1.8.0 tests): no network, no key.

`ScriptedChatProvider(turns)` answers each `chat` call with the next scripted turn and records every request
(messages, tools, tool_choice) so a test can assert what the model was shown. A turn is built with `turn(...)`,
may be an exception (raised), or a callable `(provider, messages) -> turn` for turns that depend on what the
tools returned so far, such as an answer citing the numbers handed out earlier.
"""
from __future__ import annotations

import copy
import itertools
import json
from typing import Any

from app.provider import ChatResult, ProviderResult


def call(name: str, /, **arguments: Any) -> dict[str, Any]:
    return {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}


def raw_call(name: str, arguments: str) -> dict[str, Any]:
    return {"name": name, "arguments": arguments}


def turn(*calls: dict[str, Any], content: str | None = None, cost: float | None = 0.01, input_tokens: int = 100,
         output_tokens: int = 50, finish_reason: str = "tool_calls") -> dict[str, Any]:
    return {"content": content, "calls": list(calls), "cost": cost, "input_tokens": input_tokens, "output_tokens": output_tokens, "finish_reason": finish_reason}


def text(content: str, **kwargs: Any) -> dict[str, Any]:
    return turn(content=content, finish_reason="stop", **kwargs)


def answer_call(status: str, sentences: list[tuple[str, list[str]]], note: str | None = None) -> dict[str, Any]:
    arguments: dict[str, Any] = {"status": status, "sentences": [{"text": words, "refs": refs} for words, refs in sentences]}
    if note is not None:
        arguments["note"] = note
    return call("answer", **arguments)


def tool_items(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every item with a `ref` in the tool results of a conversation, in the order they were returned."""
    items: list[dict[str, Any]] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if "ref" in node and "text" in node:
                items.append(node)
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    for message in messages:
        if message.get("role") == "tool":
            try:
                walk(json.loads(message["content"]))
            except ValueError:
                pass
    return items


def ref_of_chapter(messages: list[dict[str, Any]], chapter: int) -> str:
    return next(item["ref"] for item in tool_items(messages) if item.get("chapter") == chapter)


class ScriptedChatProvider:
    available = True
    continuity_contract_version = "v6"
    label = "scripted"
    model_label = "scripted-assistant"
    assistant_model = "scripted-assistant"

    def __init__(self, turns: list[Any] | None = None):
        self.turns = list(turns or [])
        self.calls: list[dict[str, Any]] = []
        self._ids = itertools.count(1)
        self.reviews = []
        self.review_cost = 0.02
        self.review_issues = False

    def script(self, *turns: Any) -> "ScriptedChatProvider":
        self.turns = list(turns)
        self.calls = []
        return self

    def evaluate(self, request: dict[str, Any]) -> Any:
        """The actual screened engine runs against these deterministic review responses."""
        self.reviews.append(copy.deepcopy(request))
        if request.get("task") == "continuity_screen":
            payload = {"flags": [{"id": s["id"], "kind": "conflict", "facts": []} for s in request["sentences"]]}
        elif request.get("task") == "continuity_triage":
            payload = {"scores": [{"id": s["id"], "score": 0} for s in request["sentences"]]}
        else:
            from tests.test_lf_screened_review import issue
            issues = [issue(c, c["allowed_evidence"][0]) for c in request["claims"] if self.review_issues and c["allowed_evidence"]]
            payload = {"issues": issues, "claim_verdicts": [
                {"claim_span_id": c["id"], "verdict": "reviewed_issue" if any(i["claim_span_id"] == c["id"] for i in issues) else "no_issue",
                 "basis": "依据早前段落判断。"} for c in request["claims"]]}
        return ProviderResult(payload, input_tokens=17, output_tokens=9, cost_cny=self.review_cost)

    def chat(self, messages: list[dict[str, Any]], tools: list[dict[str, Any]], tool_choice: Any, max_tokens: int) -> ChatResult:
        self.calls.append({"messages": copy.deepcopy(messages), "tools": [tool["function"]["name"] for tool in tools], "tool_choice": tool_choice, "max_tokens": max_tokens})
        if not self.turns:
            raise AssertionError("the scripted model was asked for more turns than were scripted")
        scripted = self.turns.pop(0)
        if callable(scripted):
            scripted = scripted(self, messages)
        if isinstance(scripted, BaseException):
            raise scripted
        calls = [{"id": f"call_{next(self._ids)}", "name": item["name"], "arguments": item["arguments"]} for item in scripted["calls"]]
        return ChatResult({"content": scripted["content"], "tool_calls": calls}, scripted["input_tokens"], scripted["output_tokens"],
                          scripted["cost"], scripted["finish_reason"], 5)
