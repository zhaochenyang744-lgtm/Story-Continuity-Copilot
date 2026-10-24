"""Task 07b, second half: feedback, regenerating an answer, editing a question and resending it, adopting the author's
own wording, and the roll-out switch. Everything runs on a scripted model."""
from __future__ import annotations

import dataclasses
import json
import unittest

from app.stage13 import Stage13Settings
from app.text_content import written_chars

from tests.assistant_case import AssistantCase
from tests.scripted_chat import answer_call, call, turn
from tests.test_assistant import cite
from tests.test_assistant_limits import read
from tests.test_assistant_v180 import FINAL, Task04Case

NOT_FOUND = turn(answer_call("not_found", [], note="没查到。"))
FEEDBACK_COLUMNS = {"task_id", "user_id", "verdict", "reasons_json", "created_at", "updated_at"}


class FeedbackTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def url(self, task_id: str, project_id: str | None = None) -> str:
        return f"/api/projects/{project_id or self.project_id}/assistant/tasks/{task_id}/feedback"

    def test_a_verdict_is_set_changed_and_withdrawn(self):
        task = self.run_ask(read(9), cite(9))
        self.assertIsNone(task["feedback"])
        up = self.client.put(self.url(task["id"]), json={"verdict": "up"})
        self.assertEqual(up.status_code, 200, up.text)
        self.assertEqual(up.json()["data"]["feedback"], {"verdict": "up", "reasons": []})
        self.assertEqual(up.json()["data"]["id"], task["id"])
        self.assertEqual(self.task(task["id"])["feedback"], {"verdict": "up", "reasons": []})
        down = self.client.put(self.url(task["id"]), json={"verdict": "down", "reasons": ["wrong", "bad_source", "wrong"]})
        self.assertEqual(down.json()["data"]["feedback"], {"verdict": "down", "reasons": ["wrong", "bad_source"]})
        rows = self.rows("SELECT * FROM assistant_feedback")
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["user_id"], rows[0]["verdict"], json.loads(rows[0]["reasons_json"])), (self.user_id, "down", ["wrong", "bad_source"]))
        listed = self.client.get(f"/api/projects/{self.project_id}/assistant/tasks").json()["data"]["tasks"]
        self.assertEqual(listed[0]["feedback"]["verdict"], "down")
        again = self.client.put(self.url(task["id"]), json={"verdict": "up", "reasons": ["verbose"]})  # a thumbs up has no reasons
        self.assertEqual(again.json()["data"]["feedback"], {"verdict": "up", "reasons": []})
        for _ in range(2):
            gone = self.client.delete(self.url(task["id"]))
            self.assertEqual((gone.status_code, gone.json()["data"]["feedback"]), (200, None))
        self.assertEqual(self.rows("SELECT * FROM assistant_feedback"), [])
        self.assertIsNone(self.task(task["id"])["feedback"])

    def test_only_the_verdict_and_reasons_are_kept_and_nothing_else_is_taken(self):
        task = self.run_ask(read(9), cite(9, words="一句独特的回答文字。"))
        self.client.put(self.url(task["id"]), json={"verdict": "down", "reasons": ["verbose", "not_found"]})
        row = self.rows("SELECT * FROM assistant_feedback")[0]
        self.assertEqual(set(row), FEEDBACK_COLUMNS)
        self.assertNotIn("独特的回答", json.dumps(row, ensure_ascii=False))
        for body in ({"verdict": "meh"}, {"verdict": "down", "reasons": ["rude"]}, {"verdict": "down", "reasons": "wrong"}, {"reasons": ["wrong"]},
                     {"verdict": "down", "comment": "答案是……"}, {"verdict": "down", "reasons": ["wrong", "verbose", "not_found", "bad_source", "wrong"]}):
            response = self.client.put(self.url(task["id"]), json=body)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (400, "invalid_request"), body)
        self.assertEqual(self.task(task["id"])["feedback"], {"verdict": "down", "reasons": ["verbose", "not_found"]})

    def test_only_a_finished_answer_of_ones_own_work_takes_feedback(self):
        failed = self.run_ask(RuntimeError("boom"))
        response = self.client.put(self.url(failed["id"]), json={"verdict": "down"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "assistant_task_not_completed"))
        self.assertEqual(self.client.delete(self.url(failed["id"])).status_code, 409)
        self.assertEqual(self.client.put(self.url("atask-nope"), json={"verdict": "up"}).status_code, 404)
        done = self.run_ask(read(9), cite(9))
        evil = {"Origin": "http://evil.example"}
        self.assertEqual(self.client.put(self.url(done["id"]), json={"verdict": "up"}, headers=evil).status_code, 403)
        self.assertEqual(self.client.delete(self.url(done["id"]), headers=evil).status_code, 403)
        mine = self.project_id
        self.client.cookies.clear()
        self.register()
        self.assertEqual(self.client.put(self.url(done["id"], mine), json={"verdict": "up"}).status_code, 404)
        self.assertEqual(self.client.delete(self.url(done["id"], mine)).status_code, 404)
        self.client.cookies.clear()
        self.assertEqual(self.client.put(self.url(done["id"], mine), json={"verdict": "up"}).status_code, 401)
        self.assertEqual(self.rows("SELECT * FROM assistant_feedback"), [])

    def test_a_task_shows_the_viewers_own_verdict_only(self):
        task = self.run_ask(read(9), cite(9))
        with self.db.connection() as c:
            c.execute("INSERT INTO assistant_feedback(task_id,user_id,verdict,reasons_json,created_at,updated_at) VALUES(?,?,?,?,?,?)",
                      (task["id"], "someone-else", "down", '["wrong"]', "2026-10-15T00:00:00+00:00", "2026-10-15T00:00:00+00:00"))
        self.assertIsNone(self.task(task["id"])["feedback"])
        self.client.put(self.url(task["id"]), json={"verdict": "up"})
        self.assertEqual(self.task(task["id"])["feedback"], {"verdict": "up", "reasons": []})
        self.assertEqual(len(self.rows("SELECT * FROM assistant_feedback")), 2)

    def test_a_visitor_can_give_feedback_on_the_sample_work(self):
        self.client.cookies.clear()
        self.visitor()
        task = self.run_ask(read(9), cite(9))
        response = self.client.put(self.url(task["id"]), json={"verdict": "down", "reasons": ["not_found"]})
        self.assertEqual((response.status_code, response.json()["data"]["feedback"]), (200, {"verdict": "down", "reasons": ["not_found"]}))
        self.assertEqual(self.client.delete(self.url(task["id"])).status_code, 200)


class RegenerateTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        self.own_work()
    def url(self, task_id: str) -> str:
        return f"/api/projects/{self.project_id}/assistant/tasks/{task_id}/regenerate"

    def regenerate(self, task_id: str, *turns, expect: int | None = 202, headers: dict | None = None):
        if turns:
            self.provider.script(*turns)
        response = self.client.post(self.url(task_id), headers=headers or self.idem(), json={})
        if expect is not None:
            self.assertEqual(response.status_code, expect, response.text)
        return response

    def test_a_finished_answer_is_asked_again_with_the_same_question_and_context(self):
        first = self.run_ask(read(9), cite(9, words="第一次的回答。"), question="罗盘在谁手里？", page="writing", chapter_number=11, selection="温岚仍握着黄铜罗盘")
        created = self.regenerate(first["id"], read(9), cite(9, words="第二次的回答。")).json()["data"]
        self.assertEqual((created["status"], created["regenerated_from"], created["edited_from"]), ("queued", first["id"], None))
        again = self.task(created["id"])
        self.assertEqual((again["status"], again["question"], again["context"], again["regenerated_from"]), ("completed", first["question"], first["context"], first["id"]))
        self.assertEqual(again["answer"]["sentences"][0]["text"], "第二次的回答。")
        self.assertIn("罗盘在谁手里？", self.provider.calls[0]["messages"][-1]["content"])
        self.assertIn("温岚仍握着黄铜罗盘", self.provider.calls[0]["messages"][-1]["content"])
        # The earlier answer stays as it was; the new one is a task of its own, charged like a new question.
        old = self.task(first["id"])
        self.assertEqual((old["answer"]["sentences"][0]["text"], old["regenerated_from"]), ("第一次的回答。", None))
        self.assertEqual((again["usage"]["chars_charged"], self.usage()["check_chars_used"]), (500, 1000))
        listed = self.client.get(f"/api/projects/{self.project_id}/assistant/tasks").json()["data"]["tasks"]
        self.assertEqual([task["id"] for task in listed], [first["id"], created["id"]])
        self.assertEqual(self.rows("SELECT regenerated_from,edited_from FROM assistant_tasks ORDER BY created_at DESC LIMIT 1"),
                         [{"regenerated_from": first["id"], "edited_from": None}])

    def test_a_follow_up_keeps_its_place_and_a_replay_returns_the_same_task(self):
        first = self.run_ask(read(9), cite(9, words="甲。"), question="第一问")
        second = self.run_ask(read(9), cite(9, words="乙。"), question="第二问", follow_up_of=first["id"])
        headers = self.idem()
        created = self.regenerate(second["id"], read(9), cite(9, words="乙二。"), headers=headers).json()["data"]
        self.assertEqual(created["follow_up_of"], first["id"])
        self.assertEqual([(m["role"], m["content"]) for m in self.provider.calls[0]["messages"][1:3]], [("user", "作者的问题：第一问"), ("assistant", "甲。")])
        replay = self.regenerate(second["id"], expect=202, headers=headers).json()["data"]
        self.assertEqual(replay["id"], created["id"])
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 3)

    def test_only_a_finished_question_can_be_asked_again(self):
        failed = self.run_ask(RuntimeError("boom"))
        for task_id, code, status in ((failed["id"], "assistant_regenerate_invalid", 422), ("atask-nope", "resource_not_found", 404)):
            response = self.regenerate(task_id, expect=None)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (status, code))
        done = self.run_ask(read(9), cite(9))
        self.assertEqual(self.client.post(self.url(done["id"]), json={}, headers={**self.idem(), "Origin": "http://evil.example"}).status_code, 403)
        self.assertEqual(self.client.post(self.url(done["id"]), json={}).json()["error"]["code"], "missing_idempotency_key")
        self.client.delete(f"/api/projects/{self.project_id}/assistant/tasks", headers=self.idem())
        self.assertEqual(self.regenerate(done["id"], expect=None).status_code, 404)  # cleared from the conversation
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 2)

    def test_the_new_task_is_refused_like_any_new_question_when_the_characters_run_out(self):
        self.start(registered_check_chars=700)
        self.register()
        self.own_work()
        first = self.run_ask(read(9), cite(9))
        refused = self.regenerate(first["id"], expect=None)
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (429, "character_quota_exceeded"))
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 1)

    def test_a_visitor_can_ask_again_within_the_three_a_day(self):
        self.client.cookies.clear()
        self.visitor()
        first = self.run_ask(read(9), cite(9))
        created = self.regenerate(first["id"], read(9), cite(9)).json()["data"]
        self.regenerate(created["id"], read(9), cite(9))
        refused = self.regenerate(first["id"], expect=429)
        self.assertEqual(refused.json()["error"]["code"], "workflow_quota_exceeded")


class EditResendTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()
        self.own_work()
    def test_an_edited_question_is_a_new_task_that_points_back_and_leaves_the_old_one_alone(self):
        first = self.run_ask(read(9), cite(9, words="旧回答。"), question="苏岑知道罗盘被掉包了吗？")
        self.provider.script(read(9), cite(9, words="新回答。"))
        created = self.ask(question="苏岑知道罗盘被调包了吗？", edited_from=first["id"]).json()["data"]
        self.assertEqual((created["edited_from"], created["regenerated_from"], created["question"]), (first["id"], None, "苏岑知道罗盘被调包了吗？"))
        new = self.task(created["id"])
        self.assertEqual((new["status"], new["edited_from"], new["answer"]["sentences"][0]["text"]), ("completed", first["id"], "新回答。"))
        old = self.task(first["id"])
        self.assertEqual((old["question"], old["edited_from"], old["answer"]["sentences"][0]["text"]), ("苏岑知道罗盘被掉包了吗？", None, "旧回答。"))
        self.assertEqual(self.usage()["check_chars_used"], 1000)
        self.assertEqual(self.rows("SELECT edited_from FROM assistant_tasks ORDER BY created_at DESC LIMIT 1"), [{"edited_from": first["id"]}])

    def test_a_failed_question_can_be_edited_too(self):
        failed = self.run_ask(RuntimeError("boom"), question="一个没问成的问题")
        self.provider.script(read(9), cite(9))
        created = self.ask(question="换个问法", edited_from=failed["id"]).json()["data"]
        self.assertEqual(self.task(created["id"])["edited_from"], failed["id"])

    def test_the_origin_must_be_a_question_of_this_work_still_on_the_page(self):
        done = self.run_ask(read(9), cite(9))
        other = self.client.post("/api/projects", headers=self.idem(), json={"title": "第二部"}).json()["data"]["project"]["id"]
        for project, origin in ((self.project_id, "atask-nope"), (other, done["id"])):
            response = self.ask(project_id=project, edited_from=origin, expect=None)
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (422, "assistant_edit_invalid"))
        self.client.delete(f"/api/projects/{self.project_id}/assistant/tasks", headers=self.idem())
        self.assertEqual(self.ask(edited_from=done["id"], expect=None).json()["error"]["code"], "assistant_edit_invalid")
        recap = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks", headers=self.idem(),
                                 json={"kind": "recap", "context": {"page": "writing"}, "edited_from": done["id"]})
        self.assertEqual((recap.status_code, recap.json()["error"]["code"]), (400, "invalid_request"))
        self.assertEqual(len(self.rows("SELECT * FROM assistant_tasks")), 1)


class AdoptEditTests(Task04Case):
    EDITED = "苏岑摸了摸空着的内袋，罗盘还锁在温岚的抽屉里。"

    def setUp(self):
        super().setUp()
        self.own_work()

    def finished(self, *extra_calls):
        task = self.fix(turn(*self.proposals_turn()["calls"], *extra_calls), FINAL)
        self.assertEqual(task["status"], "completed", task)
        return task, task["proposals"][0]

    def saved(self, proposal, replacement):
        body = self.rows("SELECT body FROM v2_drafts WHERE project_id=?", self.project_id)[0]["body"]
        return self.save(body.replace(proposal["before"], replacement))

    def test_the_authors_own_wording_is_what_gets_adopted_and_marked(self):
        task, proposal = self.finished()
        revision = self.saved(proposal, self.EDITED)
        # The assistant's own sentence is not what the draft now holds.
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": revision}).json()["error"]["code"], "proposal_not_applied")
        response = self.action(task, proposal, "adopt", {"draft_revision": revision, "after": self.EDITED})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual((data["status"], data["after"], data["after_edited"], data["edited_by_author"], data["adopted_draft_revision"]),
                         ("adopted", proposal["after"], self.EDITED, True, revision))
        shown = self.task(task["id"])["proposals"]
        self.assertEqual((shown[0]["after_edited"], shown[0]["edited_by_author"]), (self.EDITED, True))
        self.assertEqual((shown[1]["after_edited"], shown[1]["edited_by_author"]), (None, False))
        self.assertEqual(self.rows("SELECT after_edited,edited_by_author FROM assistant_proposals WHERE id=?", proposal["id"]),
                         [{"after_edited": self.EDITED, "edited_by_author": 1}])

    def test_the_recheck_reads_the_adopted_wording_and_undo_forgets_it(self):
        task, proposal = self.finished()
        revision = self.saved(proposal, self.EDITED)
        self.action(task, proposal, "adopt", {"draft_revision": revision, "after": self.EDITED})
        before = self.usage()["check_chars_used"]
        recheck = self.action(task, proposal, "recheck")
        self.assertEqual(recheck.status_code, 200, recheck.text)
        self.assertEqual(self.usage()["check_chars_used"], before + written_chars(self.EDITED))
        self.assertIn(self.EDITED, json.dumps(self.provider.reviews, ensure_ascii=False))
        undone = self.action(task, proposal, "undo").json()["data"]
        self.assertEqual((undone["status"], undone["after_edited"], undone["edited_by_author"]), ("proposed", None, False))

    def test_an_unchanged_sentence_is_not_marked_as_hand_edited(self):
        task, proposal = self.finished()
        revision = self.saved(proposal, proposal["after"])
        data = self.action(task, proposal, "adopt", {"draft_revision": revision, "after": proposal["after"]}).json()["data"]
        self.assertEqual((data["status"], data["after_edited"], data["edited_by_author"]), ("adopted", None, False))

    def test_a_sentence_that_breaks_the_rules_is_refused_and_nothing_changes(self):
        task, proposal = self.finished()
        revision = self.saved(proposal, self.EDITED)
        before = proposal["before"]
        bad = {"": "proposal_after_missing", "   ": "proposal_after_missing", before: "proposal_after_invalid",
               "其实，" + before: "proposal_after_contains_before", "他摸着 span-1a2b3c 内袋。": "proposal_text_internal_id",
               "长" * (len(before) * 2 + 61): "proposal_after_invalid"}
        for after, code in bad.items():
            response = self.action(task, proposal, "adopt", {"draft_revision": revision, "after": after})
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (422, code), after)
        still = self.task(task["id"])["proposals"][0]
        self.assertEqual((still["status"], still["after_edited"], still["edited_by_author"]), ("proposed", None, False))
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": revision, "after": self.EDITED}).status_code, 200)

    def test_the_reworded_sentence_must_really_be_in_the_saved_draft(self):
        task, proposal = self.finished()
        revision = self.saved(proposal, proposal["after"])
        response = self.action(task, proposal, "adopt", {"draft_revision": revision, "after": self.EDITED})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (409, "proposal_not_applied"))
        self.assertEqual(self.action(task, proposal, "adopt", {"after": self.EDITED}).status_code, 400)  # the saved revision is still needed
        self.assertEqual(self.task(task["id"])["proposals"][0]["status"], "proposed")

    def test_a_setup_for_an_earlier_chapter_may_be_reworded_within_a_hundred_and_twenty_characters(self):
        setup = call("propose_edit", kind="add_setup", chapter_number=9, after="她把罗盘交回苏岑。", rationale="补上交接。")
        task, _ = self.finished(setup)
        proposal = next(p for p in task["proposals"] if p["kind"] == "add_setup")
        for after, code in (("", "proposal_after_missing"), ("长" * 121, "proposal_after_invalid"), ("她收好了 claim-ab12cd。", "proposal_text_internal_id")):
            response = self.action(task, proposal, "adopt", {"after": after})
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (422, code), after)
        adopted = self.action(task, proposal, "adopt", {"after": "她把罗盘悄悄交回了苏岑。"})
        self.assertEqual(adopted.status_code, 200, adopted.text)
        data = adopted.json()["data"]
        self.assertEqual((data["status"], data["after"], data["after_edited"], data["edited_by_author"]), ("adopted", "她把罗盘交回苏岑。", "她把罗盘悄悄交回了苏岑。", True))
        self.assertEqual(self.action(task, proposal, "undo").json()["data"]["after_edited"], None)
        self.action(task, proposal, "adopt", {"after": "她把罗盘交回苏岑。"})
        self.assertEqual(self.action(task, proposal, "recheck").status_code, 409)  # only a change to this chapter is checked again


class RolloutTests(AssistantCase):
    def session_assistant(self) -> dict:
        return self.client.get("/api/auth/session").json()["data"]["user"]["assistant"]

    def create(self, expect: int | None = None):
        self.provider.script(NOT_FOUND)
        return self.ask(expect=expect)

    def test_the_default_is_off_and_the_test_settings_open_everything(self):
        self.assertEqual(Stage13Settings.for_test().assistant_rollout, "all")
        for source in (None, {}, {"CONTINUITY_ASSISTANT_ROLLOUT": ""}):
            self.assertEqual(self.from_env(source or {}).assistant_rollout, "off")
        self.assertEqual(self.from_env({}).assistant_allowlist, ())

    @staticmethod
    def from_env(extra: dict):
        import os
        from unittest.mock import patch
        base = {"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3000", "BACKEND_ORIGIN": "http://127.0.0.1:8000",
                "TRUSTED_HOSTS": "127.0.0.1:8000,testserver", "TRUSTED_ORIGINS": "http://127.0.0.1:3000,http://testserver"}
        clean = {key: value for key, value in os.environ.items() if not key.startswith("CONTINUITY_")}
        with patch.dict(os.environ, {**clean, **base, **extra}, clear=True):
            return Stage13Settings.from_env()

    def test_the_environment_is_read_and_a_wrong_stage_is_refused(self):
        settings = self.from_env({"CONTINUITY_ASSISTANT_ROLLOUT": " Allowlist ", "CONTINUITY_ASSISTANT_ALLOWLIST": " Zhao , wang ,, zhao"})
        self.assertEqual((settings.assistant_rollout, settings.assistant_allowlist), ("allowlist", ("zhao", "wang")))
        for stage in ("off", "registered", "all"):
            self.assertEqual(self.from_env({"CONTINUITY_ASSISTANT_ROLLOUT": stage}).assistant_rollout, stage)
        with self.assertRaises(RuntimeError) as caught:
            self.from_env({"CONTINUITY_ASSISTANT_ROLLOUT": "everyone"})
        self.assertEqual(str(caught.exception), "assistant_rollout_invalid")

    def test_off_lets_nobody_in(self):
        self.start(assistant_rollout="off")
        self.register()
        self.assertEqual(self.session_assistant(), {"available": False, "beta": False})
        response = self.create()
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (403, "assistant_not_available"))
        self.assertEqual(self.rows("SELECT * FROM assistant_tasks"), [])
        self.assertEqual(self.provider.calls, [])
        self.assertEqual(self.usage()["check_chars_used"], 0)
        self.client.cookies.clear()
        self.visitor()
        self.assertEqual(self.session_assistant(), {"available": False, "beta": False})
        self.assertEqual(self.create().json()["error"]["code"], "assistant_not_available")

    def test_allowlist_lets_in_the_named_accounts_only(self):
        self.start(assistant_rollout="allowlist", assistant_allowlist=("someone-else",))
        self.register()
        self.assertEqual(self.session_assistant(), {"available": False, "beta": False})
        self.assertEqual(self.create().json()["error"]["code"], "assistant_not_available")
        name = self.client.get("/api/auth/session").json()["data"]["user"]["account_name"]
        # The settings are frozen: start again with the account named (in another case on purpose).
        self.start(assistant_rollout="allowlist", assistant_allowlist=(name.casefold(),))
        self.register_as(name)
        self.assertEqual(self.session_assistant(), {"available": True, "beta": False})
        self.assertEqual(self.create(202).json()["data"]["status"], "queued")
        self.client.cookies.clear()
        self.visitor()
        self.assertEqual(self.session_assistant(), {"available": False, "beta": False})
        self.assertEqual(self.create().json()["error"]["code"], "assistant_not_available")

    def register_as(self, name: str) -> None:
        import uuid
        data = self.client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": name, "display_name": "Assistant", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        self.user_id = data["user"]["id"]
        self.project_id = data["onboarding"]["tutorial"]["project_id"]

    def test_registered_opens_to_registered_authors_marked_beta_but_not_visitors(self):
        self.start(assistant_rollout="registered")
        self.register()
        self.assertEqual(self.session_assistant(), {"available": True, "beta": True})
        self.assertEqual(self.create(202).json()["data"]["status"], "queued")
        self.client.cookies.clear()
        self.visitor()
        self.assertEqual(self.session_assistant(), {"available": False, "beta": False})
        self.assertEqual(self.create().json()["error"]["code"], "assistant_not_available")

    def test_all_opens_to_visitors_too_on_the_sample_work_only(self):
        self.start(assistant_rollout="all")
        self.register()
        self.assertEqual(self.session_assistant(), {"available": True, "beta": False})
        self.client.cookies.clear()
        self.visitor()
        self.assertEqual(self.session_assistant(), {"available": True, "beta": False})
        self.assertEqual(self.create(202).json()["data"]["status"], "queued")
        other = self.client.post("/api/projects", headers=self.idem(), json={"title": "我的作品"}).json()["data"]["project"]["id"]
        self.assertEqual(self.ask(project_id=other, expect=403).json()["error"]["code"], "assistant_visitor_sample_only")

    def test_every_response_that_describes_the_account_says_whether_the_assistant_is_open(self):
        self.start(assistant_rollout="registered")
        data = self.client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": "reg-user", "display_name": "R", "password": "valid-password-99", "recovery_email": "reg@example.test"}).json()["data"]
        self.assertEqual(data["user"]["assistant"], {"available": True, "beta": True})
        login = self.client.post("/api/auth/login", json={"account_name": "reg-user", "password": "valid-password-99"}).json()["data"]
        self.assertEqual(login["user"]["assistant"], {"available": True, "beta": True})
        profile = self.client.patch("/api/auth/profile", headers=self.idem(), json={
            "display_name": "R2", "avatar_preset": login["user"]["avatar_preset"], "base_profile_revision": login["user"]["profile_revision"]})
        self.assertEqual(profile.status_code, 200, profile.text)
        self.assertEqual(profile.json()["data"]["user"]["assistant"], {"available": True, "beta": True})

    def test_a_stage_that_is_closed_still_lets_old_answers_be_read(self):
        self.start()
        self.register()
        done = self.run_ask(read(9), cite(9))
        closed = Stage13Settings.for_test()
        self.assertEqual(closed.assistant_access("anyone", "registered"), {"available": True, "beta": False})
        self.engine.settings = dataclasses.replace(closed, assistant_rollout="off")
        self.assertEqual(self.task(done["id"])["status"], "completed")
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/assistant/tasks").status_code, 200)


if __name__ == "__main__":
    unittest.main()
