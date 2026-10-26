"""A3 runner and scorer offline (v2.1 B): the development set's work prepared for real, a scripted model that finds what was
planted, an invented judge, a runner process killed mid-step and the task taken up again; no network."""
from __future__ import annotations

import json
import pathlib
import re
import tempfile
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from evaluation.assistant_a3 import run, score
from evaluation.assistant_a3.judge import QUESTIONS, Judge

from tests.scripted_chat import ScriptedChatProvider, call, turn

DEV = "eval_set_a3_dev"


class FixedJudge:
    FAVOURABLE = {"a2_after_point": "yes", "a2_same_new_fact": "yes", "a2_same_new_thread": "yes", "citation_support": "supported",
                  "safe_followed_injection": "no", "safe_claimed_material_change": "no", "a3_point_found": "yes", "a3_contradiction_real": "yes"}

    def __init__(self, **verdicts):
        self.verdicts, self.asked = verdicts, []

    def ask(self, row, name, key, material, choices):
        self.asked.append((name, key))
        return {"reason": "test", "verdict": self.verdicts.get(name, self.FAVOURABLE[name])}


def step_text(messages):
    """What a step showed: the threads by title, and every passage by number with its chapter and text."""
    user = messages[1]["content"]
    threads = {title: ref for ref, title in re.findall(r"\[(R\d+)\] 伏笔：([^（]+)（", user)}
    passages, current, ref = {}, None, None
    for line in user.splitlines():
        heading = re.match(r"## 第 (\d+) 章", line)
        if heading:
            current, ref = int(heading.group(1)), None
            continue
        found = re.match(r"\[(R\d+)\] (.*)", line)
        if found and current is not None:
            ref = found.group(1)
            passages[ref] = (current, found.group(2))
        elif ref:  # a passage runs over several paragraphs
            passages[ref] = (current, passages[ref][1] + line)
    return threads, passages


def audit_model(data):
    """A thread audit that finds exactly the planted resolutions and the thread given up, each at its planted passage."""
    review, threads = data["review"], data["works"][0]["threads"]
    settled = [(p["foreshadow"], p["chapter"], p["quote"], "resolved") for p in review["resolved_unmarked"]]
    settled += [(p["foreshadow"], p["chapter"], p["quote"], "abandoned") for p in review["abandoned_in_text"]]

    def decide(provider, messages):
        shown, passages = step_text(messages)
        items = []
        for number, chapter, quote, verdict in settled:
            title = threads[number - 1]["title"]
            ref = next((ref for ref, (n, text) in passages.items() if n == chapter and quote[:12] in "".join(text.split())), None)
            if title in shown and ref:
                items.append({"thread": shown[title], "verdict": verdict, "refs": [ref], "note": "正文写到了。"})
        return turn(call("report_threads", threads=items))
    return decide


def child_provider():
    """The runner process's model in these tests (run.CHILD_PROVIDER)."""
    return ScriptedChatProvider([audit_model(run.load_set(DEV))] * 40)


def long_row(task, **long):
    base = {"questions": [], "runner_seconds": 60.0, "max_chapter": 30, "paid": [], "steps": [], "calls": [], "sources": {}, "passage_chapters": {}}
    return {"task": task, "set": DEV, "run_number": 1, "finished": True, "auto": {}, "judgments": [], "execution_errors": [],
            "assistant": {"id": "atask-1", "status": "completed", "answer": {"status": "answered", "sentences": [], "sections": {}}},
            "changes": [], "long": {**base, **long}}


PLAN = {"type": "thread_audit", "target": None, "output": "list", "chapters": [12, 20], "produces": ["abandon_thread", "resolve_thread"],
        "steps": [{"kind": "read", "chapters": [12, 16], "produces": ["resolve_thread", "abandon_thread"]},
                  {"kind": "read", "chapters": [17, 20], "produces": ["resolve_thread", "abandon_thread"]}, {"kind": "report", "produces": []}]}


class ProgramTests(unittest.TestCase):
    def test_reads_and_items_outside_the_approved_plan_are_counted(self):
        task = {"id": "t", "suite": "thread_audit", "request": "x"}
        steps = [{"ordinal": i, "spec": s, "status": "done", "attempt": 1, "chars_read": 0, "output": {}} for i, s in enumerate(PLAN["steps"], 1)]
        r = long_row(task, approved=PLAN, plan_shown=PLAN, steps=steps, passage_chapters={"R1": 12, "R2": 20})
        self.assertEqual(score.out_of_plan(r), [])
        r["long"]["passage_chapters"]["R3"] = 21
        r["changes"] = [{"id": "c1", "kind": "change_fact", "evidence": [{"chapter_number": 11}]}]
        self.assertEqual(score.out_of_plan(r), ["read_outside:R3", "kind_outside:c1", "evidence_outside:c1"])
        r = long_row({**task, "plan_edit": {"chapters": [18, 20]}}, approved=PLAN, plan_shown={**PLAN, "chapters": [1, 30]}, steps=steps)
        self.assertEqual(score.out_of_plan(r), ["approved_plan_differs", "plan_edit_not_applied"])

    def test_a_resumed_task_is_exact_only_with_every_step_once_and_every_call_paid_once(self):
        steps = [{"ordinal": 1, "spec": PLAN["steps"][0], "status": "done", "attempt": 2, "chars_read": 10, "output": {"changes": ["c1"]}},
                 {"ordinal": 2, "spec": PLAN["steps"][1], "status": "done", "attempt": 1, "chars_read": 5, "output": {"changes": []}},
                 {"ordinal": 3, "spec": PLAN["steps"][2], "status": "done", "attempt": 0, "chars_read": 0, "output": {}}]
        calls = [{"step": 0, "cost_cny": .01}, {"step": 1, "cost_cny": .02}, {"step": 1, "cost_cny": .02}, {"step": 2, "cost_cny": .02}]
        r = long_row({"id": "t", "suite": "thread_audit"}, steps=steps, calls=calls, chars_read=15, interrupt={"step": 1, "killed": True},
                     paid=[{"cost_cny": c["cost_cny"]} for c in calls], task_row={"status": "completed", "cost_cny": .07, "steps_used": 3})
        r["changes"] = [{"id": "c1", "kind": "resolve_thread", "target_id": "f1", "after": {}}]
        self.assertTrue(score.resume_check(r)["ok"])
        r["long"]["paid"] = r["long"]["paid"][:-1]
        self.assertFalse(score.resume_check(r)["calls_paid_once"])
        r["long"]["paid"] = [{"cost_cny": c["cost_cny"]} for c in calls]
        r["changes"].append({"id": "c2", "kind": "resolve_thread", "target_id": "f1", "after": {}})
        self.assertFalse(score.resume_check(r)["no_card_twice"])
        self.assertIsNone(score.resume_check(long_row({"id": "t", "suite": "trace"})))

    def test_the_author_picks_the_side_of_the_decision_point_and_leaves_anything_else_to_the_assistant(self):
        data = run.load_set(DEV)
        task = next(t for t in data["tasks"] if t["id"] == "a3d-ask-01")
        points = score.planted(data["review"], "w01")
        question = {"options": [{"key": "a", "chapter": 13, "quote": "x"}, {"key": "b", "chapter": 11, "quote": "y"}]}
        self.assertEqual(run.author_choice(task, question, points), ("b", True))  # 选 a = the chapter 11 passage
        self.assertEqual(run.author_choice(task, {"options": [{"key": "a", "chapter": 3}, {"key": "b", "chapter": 9}]}, points), ("you_decide", False))
        trace = next(t for t in data["tasks"] if t["suite"] == "trace")
        self.assertEqual(run.author_choice(trace, question, points), ("you_decide", False))

    def test_planted_points_are_found_by_work_in_any_of_the_review_shapes(self):
        flat = {"trace_objects": [1]}
        self.assertIs(score.planted(flat, "w01"), flat)
        self.assertEqual(score.planted({"w02": {"trace_objects": [2]}}, "w02"), {"trace_objects": [2]})
        self.assertEqual(score.planted({"works": [{"key": "w02", "trace_objects": [3]}]}, "w02"), {"key": "w02", "trace_objects": [3]})
        with self.assertRaisesRegex(ValueError, "planted_points_unresolved"):
            score.planted({"works": {}}, "w03")


class TraceTests(unittest.TestCase):
    """States and contradictions found in a trace report by chapter, then by the judge; a disagreement that is none of them is
    asked whether it is real."""

    def setUp(self):
        data = run.load_set(DEV)
        self.points = score.planted(data["review"], "w01")
        self.task = next(t for t in data["tasks"] if t["id"] == "a3d-trace-01")
        obj = self.points["trace_objects"][0]
        self.sources = {f"S{s['chapter']}": {"kind": "passage", "chapter_number": s["chapter"], "text": s["quote"]} for s in obj["states"]}
        conflict = obj["contradictions"][0]
        self.sources.update({"Ca": {"kind": "passage", "chapter_number": conflict["a"]["chapter"], "text": conflict["a"]["quote"]},
                             "Cb": {"kind": "passage", "chapter_number": conflict["b"]["chapter"], "text": conflict["b"]["quote"]},
                             "X1": {"kind": "passage", "chapter_number": 2, "text": "无关的一句"}, "X2": {"kind": "passage", "chapter_number": 3, "text": "另一句"}})
        self.states = [{"text": f"第 {s['chapter']} 章：{s['state']}", "refs": [f"S{s['chapter']}"]} for s in obj["states"]]
        self.texts = {}
        for source in self.sources.values():
            self.texts[source["chapter_number"]] = self.texts.get(source["chapter_number"], "") + score.squeeze(source["text"])

    def row(self, conflicts):
        r = long_row(self.task, sources=self.sources)
        r["assistant"]["answer"]["sections"] = {score.STATE_SECTION: self.states, score.CONFLICT_SECTION: conflicts}
        return r

    def test_everything_planted_found_and_an_invented_disagreement_counted(self):
        r = self.row([{"text": "第 10 章和第 22 章：铭牌两说", "refs": ["Ca", "Cb"]}, {"text": "第 2 章和第 3 章：编出来的", "refs": ["X1", "X2"]}])
        judge = FixedJudge(a3_contradiction_real="no")
        score.grade(r, judge, self.points, self.texts)
        self.assertEqual(r["auto"]["trace_found"], [True] * 6)
        self.assertEqual(r["auto"]["trace_false_contradictions"], [False, True])
        self.assertEqual([k for n, k in judge.asked if n == "a3_contradiction_real"], ["real:6"])
        self.assertEqual(r["auto"]["report_evidence"], [True] * 7)

    def test_a_disagreement_is_shown_to_the_judge_as_two_passages_each_holding_one_side(self):
        r = self.row([{"text": "第 10 章和第 22 章：铭牌两说", "refs": ["Ca", "Cb"], "claim": "铭牌末三位一处六三九，一处九三六"}])
        score.grade(r, FixedJudge(), self.points, self.texts)
        material = next(j["material"] for j in r["judgments"] if j["key"] == f"report:{len(self.states)}")
        self.assertEqual(material["sentence"]["text"], "原文有两处说法不同，第 10 章一处、第 22 章一处：铭牌末三位一处六三九，一处九三六")

    def test_a_state_in_another_chapter_is_not_found_without_asking(self):
        self.states[0]["refs"] = ["X1"]
        r = self.row([])
        judge = FixedJudge()
        score.grade(r, judge, self.points, self.texts)
        self.assertEqual(r["auto"]["trace_found"], [False, True, True, True, True, False])
        self.assertNotIn(("a3_point_found", "state:0:0"), judge.asked)

    def test_a_quote_not_in_the_text_is_not_support(self):
        self.sources["S1"] = {**self.sources["S1"], "text": "原文里没有的一句"}
        r = self.row([])
        score.grade(r, FixedJudge(), self.points, self.texts)
        self.assertEqual(r["auto"]["report_evidence"][0], False)

    def test_the_metrics_and_the_registered_bar(self):
        r = self.row([{"text": "第 10 章和第 22 章：铭牌两说", "refs": ["Ca", "Cb"]}])
        score.grade(r, FixedJudge(), self.points, self.texts)
        report = {"records": [r], "card_checks": [], "sets": [DEV], "runs": 1, "complete": True, "set": DEV, "run_id": "t", "provider_calls": []}
        score.refresh(report)
        m = report["metrics"]
        self.assertEqual((m["trace_recall"], m["trace_false_contradiction_rate"], m["out_of_plan_actions"], m["no_needless_ask_rate"]), (1.0, 0.0, 0, 1.0))
        self.assertEqual(m["latency_p90_minutes"], 1.0)
        self.assertTrue(report["gate_decision"].startswith("not_a_formal_run:"))
        self.assertIn("| trace_recall | 1.000 |", score.markdown(report))

    def test_the_judge_asks_the_registered_question(self):
        sent = []
        provider = SimpleNamespace(_send=lambda body: sent.append(body) or SimpleNamespace(payload={"reason": "r", "verdict": "yes"}))
        Judge(provider, "deepseek-v4-pro").ask({}, "a3_point_found", "k", {"x": 1}, ["yes", "no"])
        self.assertIn(QUESTIONS["a3_point_found"], sent[0]["messages"][0]["content"])


class SetTests(unittest.TestCase):
    def test_the_dev_set_alone_or_the_formal_pair_together(self):
        self.assertEqual(run.set_names("eval_set_a3d2_dev"), ["eval_set_a3d2_dev"])
        with self.assertRaises(ValueError):  # addendum 1: the first dev set used its three runs
            run.set_names(DEV)
        self.assertEqual(run.set_names("eval_set_a3s_formal,eval_set_a3_formal"), ["eval_set_a3s_formal", "eval_set_a3_formal"])
        for bad in ("eval_set_a3_formal", f"{DEV},eval_set_a3_formal", "eval_set_a2_dev"):
            with self.assertRaises(ValueError):
                run.set_names(bad)
        self.assertFalse(run.readable("eval_set_a3_formal") or run.readable("eval_set_a3s_formal"))

    def test_a_formal_run_needs_three_passes_and_no_selection(self):
        provider = SimpleNamespace(available=True, assistant_model="deepseek-flash", model="deepseek-flash", model_for=lambda role: "deepseek-flash")
        with tempfile.TemporaryDirectory() as folder, patch.object(run, "git", return_value=""):
            args = run.parser().parse_args(["--set", "eval_set_a3_formal,eval_set_a3s_formal", "--run-id", "t", "--assistant-rates", "1,2", "--judge-rates", "1,2"])
            with self.assertRaisesRegex(ValueError, "formal_requires_three_runs"):
                run.preflight(args, provider, pathlib.Path(folder))
            args.runs, args.only = 3, ["x"]
            with self.assertRaisesRegex(ValueError, "formal_only_forbidden"):
                run.preflight(args, provider, pathlib.Path(folder))


class WorkTests(unittest.TestCase):
    """The development set's work prepared for real; thread audits the author's way, one with its runner process killed."""

    @classmethod
    def setUpClass(cls):
        cls.data = run.load_set(DEV)
        cls.source = cls.data["works"][0]
        cls.points = score.planted(cls.data["review"], "w01")
        cls.provider = ScriptedChatProvider()
        cls.recorder = run.Recorder(cls.provider)
        cls.folder = tempfile.TemporaryDirectory(prefix="a3-test-")
        cls.work = run.Work(cls.source, len(run.chapters(cls.source["source"])), cls.recorder, (1, 2), root=pathlib.Path(cls.folder.name) / "w")
        cls.texts = {i: score.squeeze(text.split("\n", 1)[1]) for i, text in enumerate(run.chapters(cls.source["source"]), 1)}

    @classmethod
    def tearDownClass(cls):
        cls.work.close()
        cls.folder.cleanup()

    def audit(self, task_id, number=2, interrupt=None):
        task = next(t for t in self.data["tasks"] if t["id"] == task_id)
        self.provider.script_route({"type": "thread_audit", "target": None, "chapters": task["scope"], "output": "list"})
        self.provider.script(*[audit_model(self.data)] * 10)
        r = run.new_record(task)
        r.update(set=DEV, run_number=number, label=f"{number}:{DEV}:{task_id}")
        run.run_long(self.work, task, r, self.points, self.recorder, interrupt)
        return task, r

    def test_a_thread_audit_finds_the_planted_threads_and_its_card_confirms_and_undoes_a_group_at_a_time(self):
        task, r = self.audit("a3d-thread-01")
        self.assertEqual(r["assistant"]["status"], "completed", r["assistant"].get("error_code"))
        self.assertEqual(r["long"]["plan_shown"], r["long"]["approved"])
        self.assertEqual(sorted((c["kind"], c["index"]) for c in r["changes"]),
                         [("abandon_thread", 4), ("resolve_thread", 1), ("resolve_thread", 2), ("resolve_thread", 3)])
        score.grade(r, FixedJudge(), self.points, self.texts)
        self.assertEqual((r["auto"]["card_item_correct"], r["auto"]["unrequested"], r["auto"]["out_of_plan"]), ([True] * 4, [], []))
        self.assertEqual(r["auto"]["needless_questions"], 0)
        self.assertTrue(all(r["auto"]["card_evidence"]))
        check = run.check_card(self.work, r, self.recorder)
        self.assertEqual(sorted(check["groups"]), [1, 3])  # the thread given up alone
        self.assertEqual((check["confirm_exact"], check["undo_exact"], check["start_matches_prepared"]), (True, True, True), check)

    def test_a_runner_process_killed_mid_step_and_the_task_taken_up_again(self):
        with patch.object(run, "CHILD_PROVIDER", "tests.test_v210_a3_eval:child_provider"):
            task, r = self.audit("a3d-thread-02", number=1, interrupt=lambda row: run.Interrupt(self.work, None, self.recorder, row, f"{DEV}:a3d-thread-02"))
        interrupt = r["long"]["interrupt"]
        self.assertTrue(interrupt["killed"], interrupt)
        self.assertEqual(interrupt["at"], "after_call")
        self.assertEqual(r["assistant"]["status"], "completed", r["assistant"].get("error_code"))
        score.grade(r, FixedJudge(), self.points, self.texts)
        self.assertEqual(r["auto"]["resume"], {**{k: True for k in r["auto"]["resume"] if k != "ok"}, "ok": True})
        self.assertEqual(sorted((c["kind"], c["index"]) for c in r["changes"]), [("abandon_thread", 4), ("resolve_thread", 1), ("resolve_thread", 2)])
        self.assertEqual(r["auto"]["card_item_correct"], [True] * 3)
        killed = next(s for s in r["long"]["steps"] if s["ordinal"] == interrupt["step"])
        self.assertEqual(killed["attempt"], 2)
        self.assertEqual(len([c for c in r["long"]["calls"] if c["step"] == interrupt["step"]]), 2)  # the dead runner's call is paid, once


if __name__ == "__main__":
    unittest.main()
