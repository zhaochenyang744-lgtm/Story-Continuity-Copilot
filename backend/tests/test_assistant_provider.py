"""`DeepSeekProvider.chat` and its quota guard (v1.8.0 task 03). A fake HTTP client stands in for the network."""
from __future__ import annotations

import json
import os
import unittest
from unittest.mock import patch

import httpx

from app.provider import ChatResult, DeepSeekProvider, ProviderFailure, ProviderTimeout, ProviderUnavailable

from tests.assistant_case import AssistantCase

ENV = {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": "model-main", "CONTINUITY_BASE_URL": "https://provider.invalid/v1",
       "CONTINUITY_API_KEY": "unit-test-placeholder"}
TOOLS = [{"type": "function", "function": {"name": "answer", "description": "d", "parameters": {"type": "object", "properties": {}}}}]
MESSAGES = [{"role": "system", "content": "s"}, {"role": "user", "content": "u"}]


def completion(tool_calls=None, content=None, cost=0.0123):
    message = {"role": "assistant", "content": content}
    if tool_calls is not None:
        message["tool_calls"] = [{"id": f"call_{index}", "type": "function", "function": {"name": name, "arguments": json.dumps(arguments, ensure_ascii=False)}}
                                 for index, (name, arguments) in enumerate(tool_calls, 1)]
    return {"choices": [{"message": message, "finish_reason": "tool_calls" if tool_calls else "stop"}],
            "usage": {"prompt_tokens": 321, "completion_tokens": 45, **({"cost_cny": cost} if cost is not None else {})}}


class FakeResponse:
    def __init__(self, payload, status=200):
        self.payload, self.status = payload, status

    def raise_for_status(self):
        if self.status >= 400:
            raise httpx.HTTPStatusError("bad", request=httpx.Request("POST", "https://provider.invalid"), response=httpx.Response(self.status))

    def json(self):
        return self.payload


class FakeClient:
    """One scripted behaviour per HTTP call: a payload, a (payload, status), or an exception to raise."""

    def __init__(self, *script):
        self.script, self.posts = list(script), []

    def __call__(self):
        return self

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, url, headers=None, json=None):
        self.posts.append({"url": url, "headers": headers, "json": json})
        step = self.script.pop(0)
        if isinstance(step, BaseException):
            raise step
        return FakeResponse(*step) if isinstance(step, tuple) else FakeResponse(step)


def provider(client, **env):
    with patch.dict(os.environ, {**ENV, **env}):
        return DeepSeekProvider(client_factory=client)


class ChatTests(unittest.TestCase):
    def test_the_request_has_tools_and_no_json_mode_and_thinking_is_off(self):
        client = FakeClient(completion([("answer", {"status": "not_found", "sentences": [], "note": "没有"})]))
        result = provider(client).chat(MESSAGES, TOOLS, "required", 1500)
        body = client.posts[0]["json"]
        self.assertEqual(client.posts[0]["url"], "https://provider.invalid/v1/chat/completions")
        self.assertEqual(body["model"], "model-main")
        self.assertEqual((body["tools"], body["tool_choice"], body["messages"], body["max_tokens"]), (TOOLS, "required", MESSAGES, 1500))
        self.assertEqual((body["thinking"], body["temperature"]), ({"type": "disabled"}, 0))
        self.assertNotIn("response_format", body)
        self.assertEqual(client.posts[0]["headers"]["Authorization"], "Bearer unit-test-placeholder")
        self.assertIsInstance(result, ChatResult)
        self.assertEqual(result.message["content"], None)
        self.assertEqual([(c["id"], c["name"], json.loads(c["arguments"])["status"]) for c in result.message["tool_calls"]], [("call_1", "answer", "not_found")])
        self.assertEqual((result.input_tokens, result.output_tokens, result.cost_cny, result.finish_reason), (321, 45, 0.0123, "tool_calls"))
        self.assertIsInstance(result.latency_ms, int)

    def test_the_assistant_has_its_own_model_setting(self):
        client = FakeClient(completion(content="好"), completion(content="好"))
        self.assertEqual(provider(client, CONTINUITY_ASSISTANT_MODEL="model-assistant").chat(MESSAGES, TOOLS, "auto", 100).message,
                         {"content": "好", "tool_calls": []})
        self.assertEqual(client.posts[0]["json"]["model"], "model-assistant")
        with patch.dict(os.environ, {"CONTINUITY_ASSISTANT_MODEL": "  "}):
            provider(client).chat(MESSAGES, TOOLS, "auto", 100)
        self.assertEqual(client.posts[1]["json"]["model"], "model-main")

    def test_a_response_without_a_cost_leaves_it_unknown(self):
        result = provider(FakeClient(completion(content="好", cost=None))).chat(MESSAGES, TOOLS, "auto", 100)
        self.assertIsNone(result.cost_cny)

    def test_a_timeout_is_retried_once_like_send(self):
        client = FakeClient(httpx.ReadTimeout("slow"), completion(content="好"))
        chat = provider(client)
        result = chat.chat(MESSAGES, TOOLS, "auto", 100)
        self.assertEqual((result.message["content"], len(client.posts), chat.request_attempts, chat.successful_responses), ("好", 2, 2, 1))
        client = FakeClient(httpx.ReadTimeout("slow"), httpx.ReadTimeout("slow"), completion(content="好"))
        with self.assertRaises(ProviderTimeout):
            provider(client).chat(MESSAGES, TOOLS, "auto", 100)
        self.assertEqual(len(client.posts), 2)

    def test_failures_and_the_request_cap_behave_like_send(self):
        for payload in (({}, 500), ({"choices": []}, 200), ({"choices": [{"message": {"tool_calls": [{"function": {}}]}}]}, 200)):
            with self.assertRaises(ProviderFailure):
                provider(FakeClient(payload)).chat(MESSAGES, TOOLS, "auto", 100)
        client = FakeClient(completion(content="一"), completion(content="二"))
        chat = provider(client)
        chat.request_cap = 1
        chat.chat(MESSAGES, TOOLS, "auto", 100)
        with self.assertRaises(ProviderFailure):
            chat.chat(MESSAGES, TOOLS, "auto", 100)
        self.assertEqual(len(client.posts), 1)

    def test_an_unconfigured_provider_is_unavailable(self):
        with patch.dict(os.environ, {"CONTINUITY_PROVIDER": ""}):
            with self.assertRaises(ProviderUnavailable):
                DeepSeekProvider(client_factory=FakeClient()).chat(MESSAGES, TOOLS, "auto", 100)

    def test_json_requests_still_use_the_original_path(self):
        from app.provider import ProviderResult
        client = FakeClient(httpx.ReadTimeout("slow"), {"choices": [{"message": {"content": "{\"flags\": []}"}, "finish_reason": "stop"}], "usage": {"prompt_tokens": 3, "completion_tokens": 4}})
        chat = provider(client)
        result = chat._send({"model": "m", "messages": MESSAGES, "thinking": {"type": "disabled"}})
        self.assertEqual((result.payload, result.input_tokens, len(client.posts)), ({"flags": []}, None, 2))  # usage stays unknown after a timeout
        self.assertIsInstance(result, ProviderResult)


class GuardedTaskTests(AssistantCase):
    """Through the usage guard every HTTP call of a task reserves one provider attempt, a retried call included."""

    def test_each_http_dispatch_reserves_an_attempt(self):
        read_chapter = completion([("read_chapter", {"chapter_number": 9})])
        final = completion([("answer", {"status": "answered", "sentences": [{"text": "苏岑把罗盘交给了温岚。", "refs": ["R1"]}]})])
        client = FakeClient(httpx.ReadTimeout("slow"), read_chapter, final)
        self.start(provider=provider(client))
        self.register()
        response = self.ask()
        task = self.task(response.json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(len(client.posts), 3)
        self.assertEqual(len(self.rows("SELECT * FROM v2_provider_attempts")), 3)
        row = self.rows("SELECT input_tokens,output_tokens,cost_cny,model_label FROM assistant_tasks")[0]
        self.assertEqual((row["input_tokens"], row["output_tokens"], round(row["cost_cny"], 4), row["model_label"]), (642, 90, 0.0246, "model-main"))
        self.assertEqual(task["sources"]["R1"]["chapter_number"], 9)

    def test_a_quota_stop_in_the_middle_ends_the_task_without_an_answer(self):
        client = FakeClient(completion([("read_chapter", {"chapter_number": 9})]), completion([("read_chapter", {"chapter_number": 8})]))
        self.start(provider=provider(client), registered_provider_attempts=1)
        self.register()
        task = self.task(self.ask().json()["data"]["id"])
        self.assertEqual((task["status"], task["error_code"]), ("failed", "provider_attempt_quota_exceeded"))
        self.assertEqual(len(client.posts), 1)
        self.assertEqual(self.usage()["check_chars_used"], 0)


if __name__ == "__main__":
    unittest.main()
