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
