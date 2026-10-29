"""v2.1: a change task that ends without a card says why, in a line the program writes."""
from __future__ import annotations

from app.assistant import NO_CARD_LINES

from tests.scripted_chat import answer_call, call, turn
from tests.test_v200_changes import ChangeCase


class NoCardLineTests(ChangeCase):
    def ask(self, question, want=None, *turns):
        if want:
            self.provider.script_route({"items": [{"about": question, "ask": question, "want": want}]})
        return self.change_task(*(turns or (turn(answer_call("not_found", [], note="查过最后一章正文。")),)), question=question)

    def note(self, task):
        return (task.get("answer") or {}).get("note") or ""

    def test_a_request_to_delete_or_to_edit_prose_is_named(self):
        self.assertIn(NO_CARD_LINES["delete"], self.note(self.ask("罗盘那条事实删掉", "delete")))
        self.assertIn(NO_CARD_LINES["prose"], self.note(self.ask("最后一章那句改短些", "prose")))

    def test_nothing_found_in_the_text_is_named(self):
        self.assertIn(NO_CARD_LINES["no_evidence"], self.note(self.ask("罗盘那条线收了没有，收了就标上", "resolve_thread")))

    def test_a_record_already_there_is_named(self):
        # The thread is already resolved: proposing it again is refused as not open, and the task ends without a card.
        self.patch_thread(status="resolved", resolved_chapter_id=self.chapters[self.last])

        def propose(provider, messages):
            from tests.test_v200_changes import change_call, refs
            from tests.scripted_chat import tool_items
            thread = next(entry["ref"] for entry in tool_items(messages) if entry["text"].startswith("伏笔：罗盘下落"))
            return turn(change_call(action="resolve_thread", target=thread, evidence=[refs(messages, self.last)[0]], request_words="罗盘那条线"))

        task = self.ask("罗盘那条线最后一章已经收了", "resolve_thread", turn(call("list_threads"), call("read_chapter", chapter_number=self.last)), propose,
                        turn(answer_call("not_found", [], note="资料里这条伏笔已经是已回收。")))
        self.assertEqual(task["changes"], [])
        self.assertIn(NO_CARD_LINES["recorded"], self.note(task))

    def test_an_answer_that_claims_a_change_with_no_card_loses_the_claim(self):
        # A2 fifth formal run: "我已按第15章提出改动，等你确认" three times, with nothing on the card.
        from app.assistant import _without_claimed_proposal
        answer = {"status": "answered", "sentences": [
            {"text": "资料里现在记的是「在南穗辩护所举行」，这条与正文对不上，我已按第15章提出改动，等你确认。", "refs": ["R1"]},
            {"text": "我已提出改动，等你确认。", "refs": []},
            {"text": "第5章写覃蘅执已提出续约意向。", "refs": ["R2"]}]}
        self.assertEqual([s["text"] for s in _without_claimed_proposal(answer)["sentences"]],
                         ["资料里现在记的是「在南穗辩护所举行」，这条与正文对不上。", "第5章写覃蘅执已提出续约意向。"])
        self.assertIs(_without_claimed_proposal(answer["sentences"][2:] and {"sentences": answer["sentences"][2:]})["sentences"][0], answer["sentences"][2])
        self.assertIn("held", NO_CARD_LINES)

    def test_a_card_or_an_answer_with_no_reason_gets_no_line(self):
        from app.assistant import PENDING_LINE
        task = self.change_task(*self.resolving(words="罗盘那条线"), question="罗盘那条线最后一章已经收了")
        self.assertEqual(len(task["changes"]), 1)
        self.assertFalse(any(line in self.note(task) for line in NO_CARD_LINES.values()))
        # A card says in the program's words that nothing is written until the author confirms (A2 regression round 2).
        self.assertIn(PENDING_LINE, self.note(task))

    def test_a_new_fact_under_a_nickname_that_the_full_name_holds_is_refused(self):
        # A2 regression round 2, w01-no-01: "替绛穗记个身份条目，她就是这案子的辩护人" beside 简迭微's facts.
        from types import SimpleNamespace
        from app.assistant_actions import _said_under_full_name
        facts = [{"subject": "简迭微", "predicate": "身份", "value": "本案辩护人"}, {"subject": "简迭微", "predicate": "别名", "value": "别名绛穗"},
                 {"subject": "段泊循", "predicate": "身份", "value": "调查员"}]
        ctx = SimpleNamespace(memory=lambda: facts)
        self.assertTrue(_said_under_full_name(ctx, {"subject": "绛穗", "value": "绛穗是简迭微的别名，简迭微是本案辩护人"}))
        self.assertFalse(_said_under_full_name(ctx, {"subject": "绛穗", "value": "左手腕在第九章扭伤，暂不能提重物"}))
        self.assertFalse(_said_under_full_name(ctx, {"subject": "段泊循", "value": "本案辩护人"}))  # no nickname involved


class CardReviewTests(ChangeCase):
    """The card's second reader (`assistant_review`): one small call per fact or thread item after the runs agree."""

    def resolve(self, verdict):
        split = {"items": [{"about": "罗盘那条线", "ask": "最后一章已经收了", "want": "resolve_thread"}]}
        self.provider.script_route(split, {"verdict": verdict, "reason": "r"})
        return self.change_task(*self.resolving(words="罗盘那条线"), question="罗盘那条线最后一章已经收了")

    def test_a_thread_the_passage_does_not_close_leaves_the_card(self):
        # A2 sixth formal run, w02-no-04: marked resolved on the author's word when the passage settles another thing.
        task = self.resolve("open")
        self.assertEqual(task["changes"], [])
        self.assertIn(NO_CARD_LINES["not_closed"], task["answer"]["note"])
        review = self.provider.route_calls[1]["messages"][-1]["content"]
        self.assertIn("罗盘下落", review)
        self.assertIn("罗盘那条线最后一章已经收了", review)
        self.assertIn(f"第 {self.last} 章", review)

    def test_a_closed_thread_or_an_unclear_answer_stays(self):
        for verdict in ("closed", "unclear", "maybe"):
            with self.subTest(verdict):
                self.assertEqual([item["kind"] for item in self.resolve(verdict)["changes"]], ["resolve_thread"])

    def test_a_fact_is_asked_against_the_facts_of_every_name_of_its_subject(self):
        from app.assistant_review import FACT_KINDS, parse, question
        memory = [{"subject": "柴闻序", "predicate": "alias", "value": "朋友叫他杉栖"},
                  {"subject": "柴闻序", "predicate": "occupation", "value": "修表匠"},
                  {"subject": "别人", "predicate": "occupation", "value": "船工"}]
        item = {"kind": "change_fact", "after_json": '{"subject": "柴闻序", "predicate": "alias", "value": "杉栖就是柴闻序，不是另一个人"}',
                "before_json": '{"value": "朋友叫他杉栖"}', "evidence_json": "[]", "target_id": "x"}
        text = question(None, memory, "杉栖就是柴闻序这一层对应，也替我收进事实库", item)
        self.assertIn("原来：朋友叫他杉栖", text)
        self.assertIn("修表匠", text)
        self.assertNotIn("船工", text)
        under_nickname = dict(item, kind="add_fact", after_json='{"subject": "杉栖", "predicate": "occupation", "value": "修表"}')
        self.assertIn("修表匠", question(None, memory, "杉栖是修表的，记一笔", under_nickname))  # the nickname reaches the full name's facts
        self.assertIsNone(question(None, memory[2:], "杉栖是修表的，记一笔", under_nickname))  # nothing it could already say
        self.assertEqual((parse('{"verdict": "said"}', "add_fact"), parse('{"verdict": "closed"}', "add_fact"), parse("x", "change_fact")),
                         ("said", None, None))
        self.assertIn("change_fact", FACT_KINDS)
