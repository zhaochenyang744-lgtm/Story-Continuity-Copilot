"""v2.1: a model per assistant role (`provider.model_for`), what each task records of it, and the evaluation's check of it."""
from __future__ import annotations

import json
import os
import pathlib
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from app.provider import ASSISTANT_ROLES, DeepSeekProvider
from evaluation.assistant_a1 import run as a1_run
from evaluation.assistant_a2 import run as a2_run
from evaluation.models import REGISTERED_MODELS

from tests.scripted_chat import ScriptedChatProvider
from tests.test_assistant_provider import ENV, MESSAGES, TOOLS, FakeClient, completion, provider
from tests.test_assistant_v180 import Task04Case

ROLE_VARS = {role: f"CONTINUITY_MODEL_{role.upper()}" for role in ASSISTANT_ROLES}


class ModelForTests(unittest.TestCase):
    def models(self, **env):
        found = provider(FakeClient(), **env)
        return {role: found.model_for(role) for role in ASSISTANT_ROLES}

    def test_the_roles_are_the_four_named(self):
        self.assertEqual(ASSISTANT_ROLES, ("loop", "route", "requests", "plan"))
        self.assertEqual(ROLE_VARS, {"loop": "CONTINUITY_MODEL_LOOP", "route": "CONTINUITY_MODEL_ROUTE", "requests": "CONTINUITY_MODEL_REQUESTS",
                                     "plan": "CONTINUITY_MODEL_PLAN"})

    def test_every_layer_of_the_order_in_turn(self):
        # Only CONTINUITY_MODEL is set: every role uses it.
        self.assertEqual(self.models(), {role: "model-main" for role in ASSISTANT_ROLES})
        # CONTINUITY_ASSISTANT_MODEL takes over every role.
        self.assertEqual(self.models(CONTINUITY_ASSISTANT_MODEL="model-assistant"), {role: "model-assistant" for role in ASSISTANT_ROLES})
        # One role's own variable changes that role only, over both of the others.
        for role, name in ROLE_VARS.items():
            for assistant in ("", "model-assistant"):
                with self.subTest(role=role, assistant=assistant):
                    expected = {other: assistant or "model-main" for other in ASSISTANT_ROLES}
                    expected[role] = "model-own"
                    self.assertEqual(self.models(CONTINUITY_ASSISTANT_MODEL=assistant, **{name: "model-own"}), expected)

    def test_two_roles_can_differ_at_once(self):
        self.assertEqual(self.models(CONTINUITY_MODEL_ROUTE="model-r", CONTINUITY_MODEL_PLAN=" model-p "),
                         {"loop": "model-main", "route": "model-r", "requests": "model-main", "plan": "model-p"})

    def test_a_blank_variable_counts_as_unset(self):
        self.assertEqual(self.models(CONTINUITY_ASSISTANT_MODEL="model-assistant", CONTINUITY_MODEL_LOOP="  ", CONTINUITY_MODEL_ROUTE=""),
                         {role: "model-assistant" for role in ASSISTANT_ROLES})

    def test_an_unknown_role_is_refused(self):
        found = provider(FakeClient())
        for role in ("plans", "", "LOOP", None, "judge"):
            with self.subTest(role=role), self.assertRaises(ValueError):
                found.model_for(role)

    def test_assistant_model_stays_the_main_loops_model(self):
        self.assertEqual(provider(FakeClient()).assistant_model, "model-main")
        self.assertEqual(provider(FakeClient(), CONTINUITY_ASSISTANT_MODEL="model-assistant").assistant_model, "model-assistant")
        self.assertEqual(provider(FakeClient(), CONTINUITY_ASSISTANT_MODEL="model-assistant", CONTINUITY_MODEL_LOOP="model-loop").assistant_model, "model-loop")
        # An instance built without __init__ keeps the class defaults and still answers.
        bare = DeepSeekProvider.__new__(DeepSeekProvider)
        bare.model = "bare"
        self.assertEqual((bare.assistant_model, bare.model_for("route")), ("bare", "bare"))

    def test_the_review_model_is_not_a_role(self):
        # Only the assistant is configured per role: the checker keeps CONTINUITY_MODEL.
        found = provider(FakeClient(), CONTINUITY_MODEL_LOOP="model-loop", CONTINUITY_MODEL_ROUTE="model-route")
        self.assertEqual((found.model, found.model_label), ("model-main", "model-main"))
        self.assertEqual(found.request_body({}, "p")["model"], "model-main")


class RequestBodyTests(unittest.TestCase):
    ENV = {"CONTINUITY_ASSISTANT_MODEL": "model-assistant", "CONTINUITY_MODEL_LOOP": "model-loop", "CONTINUITY_MODEL_ROUTE": "model-route",
           "CONTINUITY_MODEL_REQUESTS": "model-requests"}

    def sent(self, call, env=None):
        client = FakeClient(completion(content='{"route": "ask"}'))
        call(provider(client, **(env if env is not None else self.ENV)))
        return client.posts[0]["json"]

    def test_chat_uses_the_loops_model(self):
        self.assertEqual(self.sent(lambda p: p.chat(MESSAGES, TOOLS, "auto", 100))["model"], "model-loop")

    def test_route_uses_the_route_model_unless_told_a_role(self):
        self.assertEqual(self.sent(lambda p: p.route(MESSAGES, 100, 5))["model"], "model-route")
        self.assertEqual(self.sent(lambda p: p.route(MESSAGES, 100, 5, role="route"))["model"], "model-route")
        self.assertEqual(self.sent(lambda p: p.route(MESSAGES, 100, 5, role="requests"))["model"], "model-requests")

    def test_route_keeps_its_other_settings(self):
        body = self.sent(lambda p: p.route(MESSAGES, 100, 5, role="requests"))
        self.assertEqual((body["response_format"], body["thinking"], body["temperature"], body["max_tokens"], body["messages"]),
                         ({"type": "json_object"}, {"type": "disabled"}, 0, 100, MESSAGES))

    def test_nothing_set_for_a_role_sends_the_one_model_of_today(self):
        for call in (lambda p: p.chat(MESSAGES, TOOLS, "auto", 100), lambda p: p.route(MESSAGES, 100, 5),
                     lambda p: p.route(MESSAGES, 100, 5, role="requests")):
            self.assertEqual(self.sent(call, env={})["model"], "model-main")
            self.assertEqual(self.sent(call, env={"CONTINUITY_ASSISTANT_MODEL": "model-assistant"})["model"], "model-assistant")

    def test_an_unknown_role_sends_nothing(self):
        client = FakeClient(completion(content="{}"))
        with self.assertRaises(ValueError):
            provider(client).route(MESSAGES, 100, 5, role="plans")
        self.assertEqual(client.posts, [])

    def test_the_usage_guard_passes_the_role_on(self):
        from app.stage13 import UsageGuardProvider, provider_usage
        client = FakeClient(completion(content="{}"), completion(content="{}"))
        guard = UsageGuardProvider(provider(client, **self.ENV), SimpleNamespace(reserve_provider_attempt=lambda *args: None))
        with provider_usage("u", "r"):
            guard.route(MESSAGES, 100, 5, role="requests")
            guard.route(MESSAGES, 100, 5)
        self.assertEqual([post["json"]["model"] for post in client.posts], ["model-requests", "model-route"])


class RoleModels(ScriptedChatProvider):
    """The scripted assistant, with a model of its own for each role."""
    MODELS = {"loop": "m-loop", "route": "m-route", "requests": "m-requests", "plan": "m-plan"}

    def model_for(self, role):
        return self.MODELS[role]


class TaskModelsTests(Task04Case):
    def setUp(self):
        super().setUp()
        self.own_work()

    def made(self, kind, routed=False):
        payload = {"kind": kind, "question": "罗盘现在在谁手里", "context": {"page": "materials" if kind == "change" else "writing"},
                   "follow_up_of": None, "edited_from": None, "routed": routed, "route_source": "model" if routed else None,
                   "routed_input": "罗盘现在在谁手里" if routed else None}
        view, _, _ = self.engine.create(self.user_id, self.project_id, payload, "key-" + self.idem()["Idempotency-Key"])
        return view

    def stored(self, task_id):
        row = self.rows("SELECT models_json, model_label FROM assistant_tasks WHERE id=?", task_id)[0]
        return json.loads(row["models_json"]) if row["models_json"] else None, row["model_label"]

    def use_roles(self):
        scripted = RoleModels()
        self.provider = scripted
        self.engine.provider = scripted
        return scripted

    def test_a_question_records_the_loop_only(self):
        self.use_roles()
        view = self.made("ask")
        self.assertEqual(view["models"], {"loop": "m-loop"})
        self.assertEqual(self.stored(view["id"])[0], {"loop": "m-loop"})

    def test_a_routed_question_adds_the_route_model(self):
        self.use_roles()
        view = self.made("ask", routed=True)
        self.assertEqual(view["models"], {"loop": "m-loop", "route": "m-route"})

    def test_a_change_task_adds_the_requests_model(self):
        self.use_roles()
        self.assertEqual(self.made("change")["models"], {"loop": "m-loop", "requests": "m-requests"})
        self.assertEqual(self.made_after_done("change", routed=True)["models"], {"loop": "m-loop", "requests": "m-requests", "route": "m-route"})

    def made_after_done(self, kind, routed):
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET status='completed'")
        return self.made(kind, routed)

    def test_the_plan_model_is_not_recorded_yet(self):
        self.use_roles()
        for kind in ("ask", "change"):
            self.assertNotIn("plan", self.made_after_done(kind, True)["models"])

    def test_the_label_stays_the_loops_model(self):
        self.use_roles()
        self.provider.assistant_model = "label-model"
        view = self.made("ask")
        self.assertEqual(self.stored(view["id"])[1], "label-model")
        self.assertEqual(view["models"], {"loop": "m-loop"})

    def test_a_stand_in_without_model_for_leaves_the_column_empty(self):
        self.assertFalse(hasattr(SimpleNamespace(), "model_for"))
        self.engine.provider = SimpleNamespace(assistant_model="plain", model_label="plain", available=True)
        view = self.made("change", routed=True)
        self.assertIsNone(view["models"])
        self.assertEqual(self.stored(view["id"]), (None, "plain"))

    def test_the_scripted_stand_in_answers_with_its_one_model(self):
        view = self.made("ask", routed=True)
        self.assertEqual(view["models"], {"loop": "scripted-assistant", "route": "scripted-assistant"})

    def test_a_task_is_listed_with_its_models(self):
        self.use_roles()
        view = self.made("ask")
        listed = self.client.get(f"/api/projects/{self.project_id}/assistant/tasks/{view['id']}").json()["data"]
        self.assertEqual(listed["models"], {"loop": "m-loop"})

    def test_an_old_database_gets_the_column(self):
        with self.db.connection() as c:
            c.execute("ALTER TABLE assistant_tasks DROP COLUMN models_json")
            self.assertNotIn("models_json", {row[1] for row in c.execute("PRAGMA table_info(assistant_tasks)")})
        self.engine.store.initialize()
        with self.db.connection() as c:
            self.assertIn("models_json", {row[1] for row in c.execute("PRAGMA table_info(assistant_tasks)")})

    def test_a_task_made_before_the_column_has_no_models(self):
        view = self.made("ask")
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET models_json=NULL WHERE id=?", (view["id"],))
        self.assertIsNone(self.task(view["id"])["models"])

    def test_the_request_splitting_asks_for_its_role(self):
        self.provider.script_route({"items": []})
        roles = []
        original = self.provider.route

        def route(messages, max_tokens, timeout_seconds, role=None):
            roles.append(role)
            return original(messages, max_tokens, timeout_seconds, role=role)

        self.provider.route = route
        from app import assistant_requests
        assistant_requests.call_model(self.provider, "罗盘那条线收了")
        self.assertEqual(roles, ["requests"])
        from app import assistant_route
        self.provider.script_route({"route": "ask", "unsure": False})
        assistant_route.call_model(self.provider, [{"role": "user", "content": "x"}])
        self.assertEqual(roles, ["requests", None])


class PreflightTests(unittest.TestCase):
    """The evaluation refuses to start on a model it was not registered with, role by role."""

    def provider(self, **models):
        found = {**REGISTERED_MODELS, **models}
        return SimpleNamespace(available=True, model="deepseek-flash", assistant_model=found["loop"], model_for=lambda role: found[role])

    def preflight(self, module, provider, flags=()):
        with tempfile.TemporaryDirectory() as folder, patch.object(module, "git", return_value=""):
            args = module.parser().parse_args(["--run-id", "models", "--assistant-rates", "1,2", "--judge-rates", "1,2", *flags])
            return module.preflight(args, provider, pathlib.Path(folder))

    def test_the_registered_models_are_deepseek_flash(self):
        self.assertEqual(REGISTERED_MODELS, {"loop": "deepseek-flash", "route": "deepseek-flash", "requests": "deepseek-flash"})

    def test_all_registered_passes(self):
        for module in (a1_run, a2_run):
            with self.subTest(module=module.__name__):
                self.preflight(module, self.provider())

    def test_one_role_off_the_registration_is_refused(self):
        for module in (a1_run, a2_run):
            for role in REGISTERED_MODELS:
                with self.subTest(module=module.__name__, role=role), self.assertRaisesRegex(ValueError, "assistant_model_configuration_invalid"):
                    self.preflight(module, self.provider(**{role: "another-model"}))

    def test_the_plan_role_is_not_checked(self):
        for module in (a1_run, a2_run):
            self.preflight(module, SimpleNamespace(available=True, model="deepseek-flash", assistant_model="deepseek-flash",
                                                   model_for=lambda role: "deepseek-flash" if role in REGISTERED_MODELS else "other"))

    def test_the_review_model_and_availability_are_still_checked(self):
        for module in (a1_run, a2_run):
            with self.subTest(module=module.__name__):
                with self.assertRaisesRegex(ValueError, "assistant_model_configuration_invalid"):
                    self.preflight(module, SimpleNamespace(**{**vars(self.provider()), "model": "another-model"}))
                with self.assertRaisesRegex(ValueError, "assistant_model_configuration_invalid"):
                    self.preflight(module, SimpleNamespace(**{**vars(self.provider()), "available": False}))

    def test_the_provider_from_the_environment_is_checked_through_model_for(self):
        env = {**ENV, "CONTINUITY_MODEL": "deepseek-flash"}
        for module in (a1_run, a2_run):
            with patch.dict(os.environ, env):
                self.preflight(module, DeepSeekProvider())
            with patch.dict(os.environ, {**env, "CONTINUITY_MODEL_REQUESTS": "another-model"}), \
                    self.assertRaisesRegex(ValueError, "assistant_model_configuration_invalid"):
                self.preflight(module, DeepSeekProvider())
            with patch.dict(os.environ, {**env, "CONTINUITY_MODEL_PLAN": "another-model"}):
                self.preflight(module, DeepSeekProvider())


if __name__ == "__main__":
    unittest.main()
