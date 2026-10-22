"""Task 04 acceptance: full chapter sources, recap, edits and point checks; no network."""
import json
import unittest
from unittest.mock import patch

from app.assistant import INTERNAL_ID
from app.assistant_recap import validate
from app.assistant_tools import ToolContext, SourceRegistry, run_tool, ToolError, tools_for
from app.text_content import written_chars

from tests.assistant_case import AssistantCase
from tests.scripted_chat import call, turn, answer_call


FINAL = turn(answer_call("not_found", [], "已经查看原文。"))


def recap_answer(provider, messages):
    message = messages[-1]["content"] if messages[-1]["role"] == "user" and "candidates" in messages[-1]["content"] else messages[1]["content"]
    data = json.JSONDecoder().raw_decode(message[message.index('{"content_kind"'):])[0]["candidates"]
    # p26: every person with facts is written once, on the first fact (the lasting ones come first), as the server now asks.
    people = [{"summary": f"{person['name']}的状态。", "refs": [person["facts"][0]["ref"]]} for person in data["character_state"] if person["facts"]]
    return turn(call("recap", previous_ending=[{"summary": "上一章的最后一幕。", "refs": [data["previous_ending"][-1]["ref"]]}],
                     character_state=people, open_threads=[], plan=[]))


class Task04Case(AssistantCase):
    def setUp(self):
        self.start(registered_workflows=200, registered_check_chars=1000000)
        self.register()

    def post_task(self, kind, *, context=None, question=None, expect=202):
        body = {"kind": kind, "context": context or {"page": "writing"}}
        if question is not None:
            body["question"] = question
        response = self.client.post(f"/api/projects/{self.project_id}/assistant/tasks", headers=self.idem(), json=body)
        self.assertEqual(response.status_code, expect, response.text)
        return response

    def issue(self, nature=None):
        query = ("SELECT i.*,cl.text sentence FROM v2_issues i JOIN v2_run_claims cl ON cl.id=i.claim_span_id "
                 "WHERE i.project_id=?" + (" AND i.nature=?" if nature else "") + " ORDER BY i.rowid")
        return self.rows(query, self.project_id, *([nature] if nature else []))[0]

    def fix(self, *turns, issue=None, question=None):
        issue = issue or self.issue("confirmed_conflict")
        self.provider.script(*turns)
        r = self.post_task("fix_issue", context={"page": "writing", "issue_id": issue["id"]}, question=question)
        return self.task(r.json()["data"]["id"])

    def proposals_turn(self):
        before = self.issue("confirmed_conflict")["sentence"]
        return turn(call("propose_edit", kind="edit_this", before=before, after="苏岑摸了摸空着的内袋，罗盘仍在温岚手里。", rationale="只改物件位置。"),
                    call("propose_edit", kind="intentional", rationale="这是有意留下的疑点。"))

    def ctx(self, task):
        row = dict(self.engine.store.row(task["id"]))
        return ToolContext(self.db, self.project_id, row, json.loads(row["scope_json"]), SourceRegistry(self.engine.store, row["id"]))

    def save(self, body):
        draft = self.rows("SELECT * FROM v2_drafts WHERE project_id=? ORDER BY saved_at DESC LIMIT 1", self.project_id)[0]
        response = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=self.idem(),
                                     json={"base_revision": draft["revision"], "title": draft["title"], "body": body})
        self.assertEqual(response.status_code, 200, response.text)
        return draft["revision"] + 1

    def action(self, task, proposal, action, body=None, headers=None):
        return self.client.post(f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/proposals/{proposal['id']}/{action}",
                                headers=headers or self.idem(), json=body or {})


class RecapTests(Task04Case):
    def test_first_chapter_refuses_without_spending(self):
        with self.db.connection() as c:
            c.execute("UPDATE v2_drafts SET chapter_number=1 WHERE project_id=?", (self.project_id,))
        response = self.post_task("recap", expect=422)
        self.assertEqual(response.json()["error"]["code"], "recap_nothing_before")
        self.assertEqual(self.rows("SELECT * FROM assistant_tasks"), [])
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_four_candidate_groups_and_no_draft_text_in_any_message(self):
        version = self.rows("SELECT author_context_version FROM v2_projects WHERE id=?", self.project_id)[0]["author_context_version"]
        r = self.client.post(f"/api/projects/{self.project_id}/author-intent/story-plans", headers=self.idem(),
                             json={"base_author_context_version": version, "title": "找罗盘", "summary": "温岚和苏岑再会", "target_chapter_number": 11})
        self.assertEqual(r.status_code, 201, r.text)
        span = self.rows("SELECT s.id,ch.id chapter_id FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE s.project_id=? AND ch.chapter_number=9", self.project_id)[0]
        r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(),
                             json={"base_foreshadow_version": 0, "title": "罗盘下落", "description": "罗盘未归", "status": "planted",
                                   "planted_chapter_id": span["chapter_id"], "planted_source_span_id": span["id"]})
        self.assertEqual(r.status_code, 201, r.text)
        self.save("温岚看见了绝不能发送的草稿密句。温岚回头。苏岑来了。")
        self.provider.script(turn(call("lookup_facts", name="温岚")), recap_answer)
        response = self.post_task("recap", context={"page": "writing", "selection": "同样不能发送的选区", "chapter_number": 99})
        task = self.task(response.json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        message = self.provider.calls[0]["messages"][1]["content"]
        material = json.JSONDecoder().raw_decode(message[message.index('{"content_kind"'):])[0]["candidates"]
        self.assertTrue(material["previous_ending"])
        self.assertEqual(material["previous_ending"][-1]["chapter"], 10)
        self.assertEqual(material["character_state"][0]["name"], "温岚")
        self.assertTrue(material["character_state"][0]["facts"])
        self.assertIsNotNone(material["character_state"][0]["last_appearance"])
        self.assertEqual(material["open_threads"][0]["source"]["chapter"], 9)
        self.assertEqual(material["plan"][0]["target_chapter_number"], 11)
        self.assertNotIn("绝不能发送", self.all_messages())
        self.assertNotIn("同样不能发送", self.all_messages())
        self.assertTrue(all("read_draft" not in c["tools"] and "get_issues" not in c["tools"] for c in self.provider.calls))
        self.assertEqual(task["answer"]["chapter_number"], 11)
        self.assertIn("本章草稿（写前回顾不看草稿）", task["coverage"]["not_checked"])
        # Every candidate shown to the model comes back as a source; the cited ones are marked.
        cited = set(task["answer"]["sections"]["previous_ending"][0]["refs"]) | {r for item in task["answer"]["sections"]["character_state"] for r in item["refs"]}
        self.assertEqual({ref for ref, source in task["sources"].items() if source["cited"]}, cited)
        self.assertGreater(len(task["sources"]), 1)

    def test_round_four_offers_only_recap_and_round_five_repairs_once(self):
        self.provider.script(turn(call("read_chapter", chapter_number=10)), turn(call("get_plans")), turn(call("get_plans")),
                             turn(call("recap", previous_ending=[], character_state=[], open_threads=[], plan=[])), recap_answer)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(self.provider.calls[-1]["tools"], ["recap"])
        self.assertEqual(self.provider.calls[-1]["tool_choice"], "required")
        self.assertEqual(self.provider.calls[3]["tools"], ["recap"])
        self.assertEqual(task["usage"]["steps"], 5)
        self.assertEqual(sum(s["kind"] == "repair" for s in task["steps"]), 1)

    def test_recap_uses_history_and_excludes_later_fact_sources(self):
        with self.db.connection() as c:
            c.execute("UPDATE v2_drafts SET chapter_number=9 WHERE project_id=?", (self.project_id,))
        self.provider.script(turn(call("lookup_facts", name="黄铜罗盘")), recap_answer)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        facts = self.rows("SELECT * FROM assistant_sources WHERE task_id=? AND kind='fact'", task["id"])
        self.assertTrue(all(f["chapter_number"] < 9 for f in facts))
        self.assertNotIn("draft", {s["kind"] for s in self.rows("SELECT * FROM assistant_sources WHERE task_id=?", task["id"])})

    def test_model_cannot_read_draft_or_future_sources(self):
        self.provider.script(turn(call("read_draft"), call("get_issues"), call("read_chapter", chapter_number=11), call("get_plans", chapter_number=12)), recap_answer)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        errors = [json.loads(m["content"])["error"] for m in self.provider.calls[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(errors, ["draft_not_in_scope", "draft_not_in_scope", "chapter_out_of_scope", "chapter_out_of_scope"])

    def test_historical_state_replaces_a_later_confirmed_state(self):
        with self.db.connection() as c:
            old = dict(c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND subject='温岚' LIMIT 1", (self.project_id,)).fetchone())
            later_span = c.execute("SELECT s.id FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE s.project_id=? AND ch.chapter_number=10 LIMIT 1", (self.project_id,)).fetchone()[0]
            current = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0]
            for row in c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=?", (self.project_id, current)).fetchall():
                new = dict(row)
                new.update(id=row["id"] + f"-v{current + 1}", version=current + 1)
                if row["id"] == old["id"]:
                    new.update(value="未来才知道的秘密状态", source_span_id=later_span)
                c.execute(f"INSERT INTO v2_memory_records({','.join(new)}) VALUES({','.join('?' for _ in new)})", tuple(new.values()))
            c.execute("UPDATE v2_projects SET current_memory_version=? WHERE id=?", (current + 1, self.project_id))
            c.execute("UPDATE v2_drafts SET chapter_number=10 WHERE project_id=?", (self.project_id,))
        self.provider.script(turn(call("lookup_facts", name="温岚")), recap_answer)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        self.assertNotIn("未来才知道的秘密状态", self.all_messages())
        self.assertIn(old["value"], self.all_messages())

    def test_twice_invalid_recap_refunds(self):
        bad = turn(call("recap", previous_ending=[], character_state=[], open_threads=[], plan=[]))
        self.provider.script(bad, bad)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        self.assertEqual(task["error_code"], "citation_validation_failed")
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_alias_matching_and_unresolved_threads_at_the_chapter_boundary(self):
        from app.assistant_recap import candidates
        person = self.rows("SELECT id FROM v2_characters WHERE project_id=? AND name='温岚'", self.project_id)[0]
        r = self.client.post(f"/api/projects/{self.project_id}/characters/{person['id']}/aliases", headers=self.idem(), json={"base_version": 0, "alias": "岚姐"})
        self.assertEqual(r.status_code, 201, r.text)
        self.save("岚姐走到窗边。岚姐叫来苏岑。")
        self.provider.script(recap_answer)
        task = self.task(self.post_task("recap").json()["data"]["id"])
        ctx = self.ctx(task)
        material = candidates(ctx)
        self.assertEqual(material["character_state"][0]["name"], "温岚")
        chapters = {r["chapter_number"]: r["id"] for r in self.rows("SELECT id,chapter_number FROM v2_chapters WHERE project_id=?", self.project_id)}
        for version, (title, planted, resolved, status) in enumerate((("之前已收", 2, 8, "resolved"), ("本章才收", 3, 10, "resolved"), ("未收线", 4, None, "developing"))):
            r = self.client.post(f"/api/projects/{self.project_id}/foreshadows", headers=self.idem(),
                json={"base_foreshadow_version": version, "title": title, "description": title, "status": status,
                      "planted_chapter_id": chapters[planted], "resolved_chapter_id": chapters[resolved] if resolved else None})
            self.assertEqual(r.status_code, 201, r.text)
        ctx.scope["chapter_number"], ctx.scope["max_chapter"] = 10, 9
        from app.assistant_recap import open_threads
        self.assertEqual({t["title"] for t in open_threads(ctx)}, {"本章才收", "未收线"})


class RecapValidationTests(unittest.TestCase):
    def test_section_citations_chapter_and_summary_rules(self):
        sources = {"R1": {"kind": "passage", "chapter_number": 10}, "R2": {"kind": "passage", "chapter_number": 9},
                   "R3": {"kind": "passage", "chapter_number": 11}, "R4": {"kind": "plan", "chapter_number": None},
                   "R5": {"kind": "draft", "chapter_number": 10}}
        good = {"previous_ending": [{"summary": "上章结尾。", "refs": ["R1"]}], "character_state": [], "open_threads": [],
                "plan": [{"summary": "准备出发。", "refs": ["R4"]}]}
        self.assertIsNotNone(validate(good, set(sources), sources, 11, INTERNAL_ID)[0])
        for section, ref in (("previous_ending", "R2"), ("previous_ending", "R3"), ("previous_ending", "R5"), ("plan", "R1"),
                             ("character_state", "R4"), ("open_threads", "R3"), ("open_threads", "R99")):
            bad = {**good, section: [{"summary": "概括", "refs": [ref]}]}
            with self.subTest(section=section, ref=ref):
                self.assertIsNone(validate(bad, set(sources), sources, 11, INTERNAL_ID)[0])
        for summary in ("字" * 41, "查 ch-123", ""):
            bad = {**good, "previous_ending": [{"summary": summary, "refs": ["R1"]}]}
            self.assertIsNone(validate(bad, set(sources), sources, 11, INTERNAL_ID)[0])


class FixTests(Task04Case):
    def test_issue_must_be_real_current_and_on_writing_page(self):
        for context, code in (({"page": "writing", "issue_id": "1"}, "assistant_issue_not_current"),
                              ({"page": "plan", "issue_id": self.issue()["id"]}, "assistant_context_invalid")):
            self.assertEqual(self.post_task("fix_issue", context=context, expect=422).json()["error"]["code"], code)
        issue = self.issue()
        self.save("已经变动的草稿。")
        self.assertEqual(self.post_task("fix_issue", context={"page": "writing", "issue_id": issue["id"]}, expect=422).json()["error"]["code"],
                         "assistant_issue_not_current")
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_fix_starts_with_issue_and_sources_and_keeps_two_kinds(self):
        task = self.fix(self.proposals_turn(), FINAL, question="保留苏岑视角")
        self.assertEqual(task["status"], "completed", task)
        initial = self.provider.calls[0]["messages"][1]["content"]
        self.assertIn(self.issue("confirmed_conflict")["sentence"], initial)
        self.assertIn("保留苏岑视角", initial)
        self.assertIn('"evidence"', initial)
        self.assertIn('"ref": "R', initial)
        self.assertEqual([p["proposal"] for p in task["proposals"]], ["P1", "P2"])
        self.assertEqual({p["kind"] for p in task["proposals"]}, {"edit_this", "intentional"})

    def test_issue_with_several_evidence_rows_does_not_lock_the_database(self):
        # Sources were registered while the evidence cursor was still open; the second row waited out the lock.
        issue = self.issue("confirmed_conflict")
        with self.db.connection() as c:
            c.execute("INSERT INTO v2_evidence(id,project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision) "
                      "SELECT id||'-second',project_id,issue_id,chapter_id,span_id,excerpt,relation,sufficiency,related_memory_ids_json,source_revision "
                      "FROM v2_evidence WHERE issue_id=? LIMIT 1", (issue["id"],))
        task = self.fix(self.proposals_turn(), FINAL, issue=issue)
        self.assertEqual(task["status"], "completed", task)
        self.assertGreaterEqual(self.provider.calls[0]["messages"][1]["content"].count('"chapter_title"'), 2)

    def test_only_one_proposal_repairs_then_fails_and_refunds(self):
        task = self.fix(turn(self.proposals_turn()["calls"][0]), FINAL, FINAL)
        self.assertEqual((task["status"], task["error_code"]), ("failed", "citation_validation_failed"))
        self.assertEqual(task["usage"]["chars_charged"], 0)
        self.assertIn("两种不同", self.all_messages())

    def test_repair_can_add_missing_kind(self):
        task = self.fix(turn(self.proposals_turn()["calls"][0]), FINAL,
                        turn(call("propose_edit", kind="intentional", rationale="有意留下疑问。")), FINAL)
        self.assertEqual(task["status"], "completed", task)

    def test_bad_proposals_are_tool_errors_and_do_not_consume_repair(self):
        sentence = self.issue("confirmed_conflict")["sentence"]
        body = self.rows("SELECT body FROM v2_drafts WHERE project_id=?", self.project_id)[0]["body"]
        unrelated = next(s for s in body.split("。") if s and s not in sentence and sentence not in s)
        task = self.fix(
            turn(call("propose_edit", kind="edit_this", before="不存在的原文", after="新句。", rationale="理由"),
                 call("propose_edit", kind="edit_this", before=unrelated, after="新句。", rationale="理由"),
                 call("propose_edit", kind="add_setup", chapter_number=11, after="补一句。", rationale="理由"),
                 call("propose_edit", kind="edit_this", before=sentence, after=sentence, rationale="理由")),
            self.proposals_turn(), FINAL)
        self.assertEqual(task["status"], "completed", task)
        errors = [s["error_code"] for s in self.rows("SELECT error_code FROM assistant_steps WHERE task_id=? AND error_code IS NOT NULL", task["id"])]
        self.assertEqual(errors, ["proposal_before_not_unique", "proposal_issue_not_overlapped", "proposal_chapter_invalid", "proposal_after_invalid"])
        self.assertFalse(any(s["kind"] == "repair" for s in task["steps"]))

    def test_after_that_keeps_the_whole_before_is_refused(self):
        # Adopting requires the saved draft to no longer hold `before`; words added around it never get there.
        sentence = self.issue("confirmed_conflict")["sentence"]
        task = self.fix(turn(call("propose_edit", kind="edit_this", before=sentence, after="其实，" + sentence, rationale="理由")),
                        self.proposals_turn(), FINAL)
        self.assertEqual(task["status"], "completed", task)
        errors = [s["error_code"] for s in self.rows("SELECT error_code FROM assistant_steps WHERE task_id=? AND error_code IS NOT NULL", task["id"])]
        self.assertEqual(errors, ["proposal_after_contains_before"])
        self.assertTrue(all(sentence not in p["after"] for p in task["proposals"] if p["kind"] == "edit_this"))

    def test_edit_this_may_name_its_own_chapter_only(self):
        task = self.fix(self.proposals_turn(), FINAL)
        ctx = self.ctx(task)
        n, sentence = ctx.scope["chapter_number"], ctx.scope["issue_sentence"]
        args = {"kind": "edit_this", "before": sentence, "after": "苏岑摸了摸内袋，罗盘还在温岚那里。", "rationale": "理由"}
        with self.assertRaises(ToolError) as caught:
            run_tool("propose_edit", "fix_issue", ctx, {**args, "chapter_number": n - 1})
        self.assertEqual(caught.exception.code, "edit_this_is_for_the_current_draft")
        with self.assertRaises(ToolError) as caught:
            run_tool("propose_edit", "fix_issue", ctx, {"kind": "add_setup", "chapter_number": n - 1, "rationale": "理由"})
        self.assertEqual(caught.exception.code, "proposal_after_missing")
        self.assertEqual(run_tool("propose_edit", "fix_issue", ctx, {**args, "chapter_number": n}).result, {"proposal": "P3"})

    def test_duplicate_before_and_fourth_proposal_refused(self):
        task = self.fix(self.proposals_turn(),
                        turn(call("propose_edit", kind="add_setup", chapter_number=9, after="她把罗盘交回苏岑。", rationale="补上交接。"),
                             call("propose_edit", kind="intentional", rationale="另一种解释。")), FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(len(task["proposals"]), 3)
        self.assertIn("proposal_limit_exceeded", self.all_messages())
        ctx = self.ctx(task)
        sentence = ctx.scope["issue_sentence"]
        with self.db.connection() as c:
            c.execute("UPDATE v2_draft_revisions SET body=? WHERE draft_id=? AND revision=?", (sentence + sentence, ctx.task["draft_id"], ctx.task["draft_revision"]))
        with self.assertRaises(ToolError) as caught:
            run_tool("propose_edit", "fix_issue", ctx, {"kind": "edit_this", "before": sentence, "after": "新句。", "rationale": "理由"})
        self.assertEqual(caught.exception.code, "proposal_before_not_unique")

    def test_state_change_explains_without_proposals(self):
        issue = self.issue()
        with self.db.connection() as c:
            c.execute("UPDATE v2_issues SET nature='state_change' WHERE id=?", (issue["id"],))
        task = self.fix(turn(call("propose_edit", kind="intentional", rationale="这不是错误。")), FINAL, issue=issue)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["proposals"], [])
        self.assertNotIn("propose_edit", self.provider.calls[0]["tools"])
        self.assertIn("no_edit_for_state_change", self.all_messages())
        self.assertIn("资料页确认", self.all_messages())

    def test_old_issue_is_not_accepted_after_a_newer_check(self):
        old = self.issue()
        with self.db.connection() as c:
            run = dict(c.execute("SELECT * FROM v2_runs WHERE id=?", (old["run_id"],)).fetchone())
            run["id"] = "run-newest-check"
            c.execute(f"INSERT INTO v2_runs({','.join(run)}) VALUES({','.join('?' for _ in run)})", tuple(run.values()))
        r = self.post_task("fix_issue", context={"page": "writing", "issue_id": old["id"]}, expect=422)
        self.assertEqual(r.json()["error"]["code"], "assistant_issue_not_current")

    def test_proposals_validate_the_task_draft_not_the_later_autosave(self):
        proposal_turn = self.proposals_turn()
        def changed(provider, messages):
            self.save("另一版稿子，不再包含原句。")
            return proposal_turn
        task = self.fix(changed, FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["proposals"][0]["draft_revision"], 1)


class PassageTests(Task04Case):
    def test_spends_extra_once_and_counts_review_usage(self):
        text = "苏岑手里的黄铜罗盘仍带着月牙裂纹。"
        task = self.run_ask(turn(call("check_passage", text=text)), turn(call("check_passage", text=text)), FINAL)
        self.assertEqual(task["status"], "completed", task)
        reservation = self.rows("SELECT reservation_id FROM assistant_tasks WHERE id=?", task["id"])[0]["reservation_id"]
        extra = self.rows("SELECT * FROM v2_character_usage WHERE id=?", f"chars-{reservation}-x1")
        self.assertEqual(extra[0]["characters"], written_chars(text))
        self.assertEqual(task["usage"]["chars_charged"], 500 + written_chars(text))
        self.assertEqual(len(self.provider.reviews), 1)
        self.assertIn("check_passage_limit_exceeded", self.all_messages())
        usage = self.rows("SELECT input_tokens,output_tokens,cost_cny FROM assistant_tasks WHERE id=?", task["id"])[0]
        self.assertEqual((usage["input_tokens"], usage["output_tokens"]), (317, 159))
        self.assertAlmostEqual(usage["cost_cny"], 0.05)
        self.assertTrue(all(e["chapter_number"] < 11 for r in self.provider.reviews for c in r.get("claims", []) for e in c["allowed_evidence"]))

    def test_quota_failure_returns_to_model_without_aborting(self):
        self.stage13.settings = __import__("dataclasses").replace(self.stage13.settings, registered_check_chars=500)
        task = self.run_ask(turn(call("check_passage", text="苏岑有一枚罗盘。")), FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertIn("character_quota_exceeded", self.all_messages())
        self.assertEqual(task["usage"]["chars_charged"], 500)
        self.assertEqual(self.provider.reviews, [])

    def test_failure_refunds_both_rows(self):
        task = self.run_ask(turn(call("check_passage", text="苏岑的罗盘不见了。")),
                           turn(answer_call("answered", [("错引。", ["R999"])])), turn(answer_call("answered", [("错引。", ["R999"])])))
        self.assertEqual(task["status"], "failed", task)
        self.assertEqual(self.rows("SELECT * FROM v2_character_usage"), [])
        self.assertEqual(task["usage"]["chars_charged"], 0)
        self.assertTrue(self.provider.reviews)

    def test_check_budget_stops_before_another_chat(self):
        self.provider.review_cost = 0.31
        task = self.run_ask(turn(call("check_passage", text="苏岑的黄铜罗盘在温岚手里。")), FINAL)
        self.assertEqual(task["error_code"], "assistant_budget_exhausted", task)
        self.assertEqual(len(self.provider.calls), 1)
        self.assertEqual(self.rows("SELECT * FROM v2_character_usage"), [])
        self.assertGreater(self.rows("SELECT cost_cny FROM assistant_tasks WHERE id=?", task["id"])[0]["cost_cny"], 0.3)

    def test_visitor_has_no_point_check(self):
        self.client.cookies.clear()
        self.visitor()
        task = self.run_ask(turn(call("check_passage", text="罗盘不见了。")), FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertNotIn("check_passage", self.provider.calls[0]["tools"])
        self.assertIn("assistant_check_visitor_forbidden", self.all_messages())
        self.assertEqual(self.provider.reviews, [])

    def test_check_returns_issue_and_registered_evidence(self):
        self.provider.review_issues = True
        task = self.run_ask(turn(call("check_passage", text="苏岑的黄铜罗盘在温岚手里。")), FINAL)
        self.assertEqual(task["status"], "completed", task)
        result = json.loads(next(m["content"] for m in self.provider.calls[-1]["messages"] if m["role"] == "tool"))
        self.assertEqual(result["status"], "issues", result)
        self.assertTrue(result["issues"][0]["evidence"])
        ref = result["issues"][0]["evidence"][0]["ref"]
        self.assertTrue(self.rows("SELECT * FROM assistant_sources WHERE task_id=? AND ref=?", task["id"], ref))

    def test_writing_boundary_and_nonwriting_all_chapters(self):
        with self.db.connection() as c:
            c.execute("UPDATE v2_drafts SET chapter_number=3 WHERE project_id=?", (self.project_id,))
        task = self.run_ask(turn(call("check_passage", text="苏岑的黄铜罗盘不在手中。")), FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertTrue(self.provider.reviews)
        self.assertTrue(all(e["chapter_number"] < 3 for r in self.provider.reviews for cl in r.get("claims", []) for e in cl["allowed_evidence"]))
        self.provider.reviews.clear()
        task = self.run_ask(turn(call("check_passage", text="苏岑在仓道交给温岚的黄铜罗盘不在手中。")), FINAL, page="chapters")
        self.assertEqual(task["status"], "completed", task)
        self.assertTrue(any(e["chapter_number"] == 9 for r in self.provider.reviews for cl in r.get("claims", []) for e in cl["allowed_evidence"]))

    def test_point_check_rejects_more_than_six_hundred_characters(self):
        task = self.run_ask(turn(call("check_passage", text="字" * 601)), FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertIn("invalid_arguments", self.all_messages())
        self.assertEqual(task["usage"]["chars_charged"], 500)
        self.assertEqual(self.provider.reviews, [])


class ProposalActionTests(Task04Case):
    def adopted(self):
        task = self.fix(self.proposals_turn(), FINAL)
        self.assertEqual(task["status"], "completed", task)
        proposal = task["proposals"][0]
        body = self.rows("SELECT body FROM v2_drafts WHERE project_id=?", self.project_id)[0]["body"]
        revision = self.save(body.replace(proposal["before"], proposal["after"]))
        r = self.action(task, proposal, "adopt", {"draft_revision": revision})
        self.assertEqual(r.status_code, 200, r.text)
        return task, proposal, revision

    def test_adopt_verifies_saved_text_and_does_not_write_draft_or_decisions(self):
        task = self.fix(self.proposals_turn(), FINAL)
        self.assertEqual(task["status"], "completed", task)
        proposal = task["proposals"][0]
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": 2}).json()["error"]["code"], "proposal_not_applied")
        decisions = self.rows("SELECT * FROM v2_decisions")
        issues = self.rows("SELECT * FROM v2_issues")
        revision = self.save(proposal["before"] + proposal["after"])
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": revision}).status_code, 409)
        revision = self.save(proposal["after"])
        drafts = self.rows("SELECT * FROM v2_drafts")
        idem = self.idem()
        r = self.action(task, proposal, "adopt", {"draft_revision": revision}, idem)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"]["adopted_draft_revision"], revision)
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": revision}, idem).json()["data"], r.json()["data"])
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": revision}).status_code, 409)
        self.assertEqual(self.rows("SELECT * FROM v2_drafts"), drafts)
        self.assertEqual(self.rows("SELECT * FROM v2_decisions"), decisions)
        self.assertEqual(self.rows("SELECT * FROM v2_issues"), issues)
        self.assertEqual(self.action(task, task["proposals"][1], "adopt", {"draft_revision": revision}).status_code, 409)

    def test_undo_and_dismiss_transitions(self):
        task, proposal, revision = self.adopted()
        self.assertEqual(self.action(task, proposal, "dismiss").status_code, 409)
        undone = self.action(task, proposal, "undo")
        self.assertEqual(undone.json()["data"]["status"], "proposed")
        self.assertIsNone(undone.json()["data"]["adopted_draft_revision"])
        self.assertEqual(self.action(task, proposal, "undo").status_code, 409)
        self.assertEqual(self.action(task, proposal, "dismiss").json()["data"]["status"], "dismissed")
        self.assertEqual(self.action(task, proposal, "adopt", {"draft_revision": revision}).status_code, 409)

    def test_recheck_spends_once_is_idempotent_and_persists(self):
        task, proposal, revision = self.adopted()
        previous = self.usage()["check_chars_used"]
        key = self.idem()
        r = self.action(task, proposal, "recheck", headers=key)
        self.assertEqual(r.status_code, 200, r.text)
        self.assertEqual(r.json()["data"], {"status": "clean", "issues": []})
        self.assertEqual(self.action(task, proposal, "recheck", headers=key).json()["data"], r.json()["data"])
        self.assertEqual(self.usage()["check_chars_used"], previous + written_chars(proposal["after"]))
        stored = self.rows("SELECT recheck_json FROM assistant_proposals WHERE id=?", proposal["id"])[0]["recheck_json"]
        self.assertEqual(json.loads(stored), r.json()["data"])
        self.assertEqual(len(self.rows("SELECT * FROM v2_usage_reservations WHERE workflow_kind='assistant_recheck'")), 1)
        self.assertEqual(len(self.provider.reviews), 1)
        self.assertEqual(self.task(task["id"])["proposals"][0]["recheck"], r.json()["data"])

    def test_recheck_with_issues_stores_inline_evidence(self):
        task, proposal, _ = self.adopted()
        self.provider.review_issues = True
        response = self.action(task, proposal, "recheck")
        self.assertEqual(response.status_code, 200, response.text)
        result = response.json()["data"]
        self.assertEqual(result["status"], "issues")
        self.assertTrue(result["issues"][0]["evidence"][0]["text"])
        self.assertEqual(self.task(task["id"])["proposals"][0]["recheck"], result)

    def test_duplicate_recheck_in_flight_does_not_charge_twice(self):
        task, proposal, _ = self.adopted()
        previous = self.usage()["check_chars_used"]
        review = self.provider.evaluate
        nested = []
        headers = self.idem()
        def while_running(request):
            nested.append(self.action(task, proposal, "recheck", headers=headers))
            nested.append(self.action(task, proposal, "recheck"))
            nested.append(self.action(task, proposal, "undo"))
            return review(request)
        with patch.object(self.provider, "evaluate", side_effect=while_running):
            response = self.action(task, proposal, "recheck", headers=headers)
        self.assertEqual(response.status_code, 200, response.text)
        self.assertEqual([r.json()["error"]["code"] for r in nested], ["proposal_recheck_running"] * 3)
        self.assertEqual(self.usage()["check_chars_used"], previous + written_chars(proposal["after"]))

    def test_recheck_failure_refunds_its_characters_and_replays_failure(self):
        task, proposal, _ = self.adopted()
        previous = self.usage()["check_chars_used"]
        self.provider.review_cost = 0.31
        headers = self.idem()
        r = self.action(task, proposal, "recheck", headers=headers)
        self.assertEqual((r.status_code, r.json()["error"]["code"]), (503, "assistant_budget_exhausted"), r.text)
        self.assertEqual(self.action(task, proposal, "recheck", headers=headers).status_code, 503)
        self.assertEqual(self.usage()["check_chars_used"], previous)
        self.assertEqual(len(self.provider.reviews), 1)

    def test_all_actions_require_csrf_key_and_ownership(self):
        task, proposal, revision = self.adopted()
        url = f"/api/projects/{self.project_id}/assistant/tasks/{task['id']}/proposals/{proposal['id']}"
        for action in ("adopt", "dismiss", "undo", "recheck"):
            body = {"draft_revision": revision} if action == "adopt" else {}
            self.assertEqual(self.client.post(url + "/" + action, json=body).json()["error"]["code"], "missing_idempotency_key")
            self.assertEqual(self.client.post(url + "/" + action, json=body, headers={**self.idem(), "Origin": "http://evil.example"}).status_code, 403)
        self.client.cookies.clear()
        self.register()
        for action in ("adopt", "dismiss", "undo", "recheck"):
            self.assertEqual(self.client.post(url + "/" + action, json={"draft_revision": revision} if action == "adopt" else {},
                                             headers=self.idem()).status_code, 404)

    def test_recheck_is_forbidden_for_visitors(self):
        self.client.cookies.clear()
        self.visitor()
        task, proposal, _ = self.adopted()
        response = self.action(task, proposal, "recheck")
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (403, "assistant_check_visitor_forbidden"))


class ChapterBodyTests(AssistantCase):
    def setUp(self):
        self.start()
        self.register()

    def test_reads_full_sample_chapter_with_chapter_offsets(self):
        task = self.run_ask(turn(call("read_chapter", chapter_number=9)),
                            turn(answer_call("not_found", [], "已读原文。")))
        chapter = self.rows("SELECT id,body FROM v2_chapters WHERE project_id=? AND chapter_number=9", self.project_id)[0]
        sources = self.rows("SELECT * FROM assistant_sources WHERE task_id=?", task["id"])
        self.assertGreater(len(chapter["body"]), 0)
        self.assertEqual("".join(s["text"] for s in sources).replace("\n", ""), chapter["body"].replace("\n", ""))
        for source in sources:
            self.assertEqual(source["object_id"], chapter["id"])
            self.assertEqual(chapter["body"][source["start"]:source["end"]], source["text"])

    def test_search_finds_text_absent_from_spans(self):
        with self.db.connection() as c:
            c.execute("UPDATE v2_chapters SET body=body||? WHERE project_id=? AND chapter_number=9", ("\n独角鲸悄悄经过。", self.project_id))
        task = self.run_ask(turn(call("search_text", query="独角鲸")), turn(answer_call("not_found", [], "已查。")))
        self.assertTrue(any("独角鲸" in s["text"] for s in self.rows("SELECT text FROM assistant_sources WHERE task_id=?", task["id"])))

    def test_empty_body_falls_back_and_keeps_fact_retrieval(self):
        with self.db.connection() as c:
            c.execute("UPDATE v2_chapters SET body='' WHERE project_id=? AND chapter_number=9", (self.project_id,))
        task = self.run_ask(turn(call("read_chapter", chapter_number=9)), FINAL)
        source = self.rows("SELECT * FROM assistant_sources WHERE task_id=?", task["id"])[0]
        chapter = self.rows("SELECT id FROM v2_chapters WHERE project_id=? AND chapter_number=9", self.project_id)[0]
        spans = self.rows("SELECT body FROM v2_source_spans WHERE chapter_id=? ORDER BY rowid", chapter["id"])
        self.assertEqual(source["text"], "\n".join(s["body"] for s in spans))
        self.assertEqual(source["object_id"], chapter["id"])
        row = dict(self.engine.store.row(task["id"]))
        ctx = ToolContext(self.db, self.project_id, row, json.loads(row["scope_json"]), SourceRegistry(self.engine.store, row["id"]))
        self.assertTrue(ctx.index()._fact_home)
        self.assertTrue(all(p.chapter_id in {ch["id"] for ch in ctx.chapters().values()} for p in ctx.index()._fact_home.values()))

    def test_existing_task_uses_historical_full_chapter_after_revision(self):
        def revise(provider, messages):
            with self.db.connection() as c:
                ch = c.execute("SELECT * FROM v2_chapters WHERE project_id=? AND chapter_number=9", (self.project_id,)).fetchone()
                c.execute("INSERT INTO v2_chapter_revision_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                          (self.project_id, ch["id"], 1, ch["title"], ch["summary"], ch["body"], "plain_text", "[]", None, "2026-10-11T00:00:00Z"))
                c.execute("UPDATE v2_chapters SET body='后来的新版本不能进入旧任务',source_revision=2 WHERE id=?", (ch["id"],))
            return turn(call("read_chapter", chapter_number=9))
        task = self.run_ask(revise, FINAL)
        self.assertEqual(task["status"], "completed", task)
        self.assertNotIn("后来的新版本", self.all_messages())
        self.assertIn("仓道入口很窄", self.all_messages())

    def test_visitor_sample_reads_full_body_instead_of_key_spans(self):
        self.client.cookies.clear()
        self.visitor()
        task = self.run_ask(turn(call("read_chapter", chapter_number=9)), FINAL)
        chapter = self.rows("SELECT id,body FROM v2_chapters WHERE project_id=? AND chapter_number=9", self.project_id)[0]
        result = json.loads(next(m["content"] for m in self.provider.calls[1]["messages"] if m["role"] == "tool"))
        self.assertEqual(result["total_chars"], len(chapter["body"]))
        spans = self.rows("SELECT body FROM v2_source_spans WHERE chapter_id=?", chapter["id"])
        self.assertGreater(result["total_chars"], sum(len(s["body"]) for s in spans))
        for source in self.rows("SELECT * FROM assistant_sources WHERE task_id=?", task["id"]):
            self.assertEqual((source["object_id"], source["text"]), (chapter["id"], chapter["body"][source["start"]:source["end"]]))

    def test_imported_work_still_reads_and_searches_the_complete_body(self):
        body = "港口雨停了。\n苏岑拿着一枚崭新的银色罗盘。"
        with self.db.connection() as c:
            project = self.db._create_project(c, self.user_id, "导入测试", "", "", "user_import",
                                              imported=[{"title": "雨后", "body": body}])
        task = self.run_ask(turn(call("read_chapter", chapter_number=1), call("search_text", query="银色罗盘")), FINAL, project_id=project)
        self.assertEqual(task["status"], "completed", task)
        results = [json.loads(m["content"]) for m in self.provider.calls[1]["messages"] if m["role"] == "tool"]
        self.assertEqual(results[0]["total_chars"], len(body))
        self.assertTrue(any("银色罗盘" in p["text"] for p in results[1]["passages"]))


class CheckSelectionIntentTests(Task04Case):
    """Task 05b: the selection bar's 查前文矛盾 is an ask about picked text that carries `intent: check_selection`."""
    LINE = "作者要你检查选中的这段文字和前文有没有矛盾：先用 check_passage 检查这段文字，再根据结果回答；没有发现问题也要说明查了什么。"
    PICKED = "苏岑的黄铜罗盘在温岚手里。"

    def post_raw(self, kind, context, question="这段和前文有没有矛盾？"):
        body = {"kind": kind, "context": context}
        if kind != "recap":
            body["question"] = question
        return self.client.post(f"/api/projects/{self.project_id}/assistant/tasks", headers=self.idem(), json=body)

    def test_intent_is_accepted_only_on_an_ask_with_a_selection(self):
        self.provider.script(turn(call("check_passage", text=self.PICKED)), FINAL)
        ok = self.post_raw("ask", {"page": "writing", "selection": self.PICKED, "intent": "check_selection"})
        self.assertEqual(ok.status_code, 202, ok.text)
        self.assertEqual(self.task(ok.json()["data"]["id"])["context"]["intent"], "check_selection")
        refused = [
            self.post_raw("ask", {"page": "writing", "intent": "check_selection"}),
            self.post_raw("ask", {"page": "writing", "selection": "   ", "intent": "check_selection"}),
            self.post_raw("recap", {"page": "writing", "selection": self.PICKED, "intent": "check_selection"}),
            self.post_raw("fix_issue", {"page": "writing", "issue_id": self.issue()["id"], "selection": self.PICKED, "intent": "check_selection"}, question="x"),
        ]
        for response in refused:
            self.assertEqual((response.status_code, response.json()["error"]["code"]), (422, "assistant_context_invalid"), response.text)
        # Only that one value is a known intent.
        unknown = self.post_raw("ask", {"page": "writing", "selection": self.PICKED, "intent": "rewrite"})
        self.assertEqual(unknown.status_code, 400, unknown.text)
        # A refusal creates no task and spends nothing.
        self.assertEqual(len(self.rows("SELECT id FROM assistant_tasks")), 1)

    def test_visitor_is_refused_with_a_403(self):
        self.client.cookies.clear()
        self.visitor()
        before = self.usage()
        response = self.post_raw("ask", {"page": "writing", "selection": self.PICKED, "intent": "check_selection"})
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (403, "assistant_check_visitor_forbidden"), response.text)
        self.assertEqual(self.rows("SELECT id FROM assistant_tasks"), [])
        self.assertEqual(self.usage(), before)
        # The same visitor can still ask about the passage without the intent.
        self.provider.script(FINAL)
        plain = self.post_raw("ask", {"page": "writing", "selection": self.PICKED})
        self.assertEqual(plain.status_code, 202, plain.text)

    def test_the_instruction_line_is_in_the_first_message_only_with_the_intent(self):
        self.provider.script(turn(call("check_passage", text=self.PICKED)), FINAL)
        response = self.post_raw("ask", {"page": "writing", "selection": self.PICKED, "intent": "check_selection"})
        task = self.task(response.json()["data"]["id"])
        self.assertEqual(task["status"], "completed", task)
        first = next(m["content"] for m in self.provider.calls[0]["messages"] if m["role"] == "user")
        self.assertIn(self.LINE, first)
        self.assertIn(f"「{self.PICKED}」", first)
        self.assertEqual(first.count(self.LINE), 1)
        self.assertLess(first.index(f"「{self.PICKED}」"), first.index(self.LINE))
        # The model may check the passage once, for the passage's own characters on top of the 500.
        self.assertEqual(task["usage"]["chars_charged"], 500 + written_chars(self.PICKED))
        self.assertIn("check_passage", self.provider.calls[0]["tools"])
        # Without the intent the line is absent.
        self.provider.script(FINAL)
        plain = self.post_raw("ask", {"page": "writing", "selection": self.PICKED})
        self.task(plain.json()["data"]["id"])
        self.assertNotIn(self.LINE, self.provider.calls[0]["messages"][-1]["content"])
