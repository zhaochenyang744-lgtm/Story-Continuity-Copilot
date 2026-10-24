"""Test-only ASGI app for browser E2E. Never imported by production startup."""

from pathlib import Path
from dataclasses import replace
from datetime import datetime, timedelta, timezone
import json
import os
import re
import tempfile
import threading
import time
import uuid

from fastapi import Body, HTTPException

from app.config import AppPaths

# Importing app.main normally constructs the production ASGI app and therefore
# a production provider. The browser-test process must only construct the
# injected stub below.
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
from app.main import create_app
from app.provider import ChatResult, ProviderInvalidJson, ProviderResult, ProviderTimeout
from app.stage13 import Stage13Settings
from app import review_screening
from tests.legacy_story_qa import seed_story_qa

# The browser stub marks every sentence of a chapter as key, and stage5's "extreme issues" page test
# needs twenty issues on one chapter. The per-chapter review caps are product behaviour covered by the
# backend tests; here they are lifted so the page can be tested with many issues.
review_screening.KEY_MAX_CLAIMS = 64


class CaptureMailer:
    """Keeps every security mail in memory; the browser tests read the links through /api/test/mail."""

    def __init__(self):
        self.messages: list[dict[str, str]] = []

    def send(self, recipient: str, purpose: str, action_url: str) -> None:
        self.messages.append({"recipient": recipient, "purpose": purpose, "action_url": action_url})


class BrowserTestProvider:
    label = "browser-e2e-test-provider"
    allows_legacy_continuity_contract = True
    allows_legacy_foreshadow_evidence_contract = True

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.failed_once = set()
        self.route_log = []

    @property
    def available(self):
        return True

    # The assistant (v1.8.0): scripts the browser tests can predict. A question (ask): round 1 looks up a known name and
    # searches the text with the first six characters of the question; round 2 answers with the first source
    # number it was handed. E2E_NOT_FOUND answers "not found", E2E_SLOW waits 3 s first, E2E_FAIL times out.
    # 写前回顾 (recap), 帮我改这一处 (fix_issue) and 查前文矛盾 (an ask carrying the check_selection line) have their own
    # scripts below; each reads the numbers and sentences it needs out of the first message it was shown.
    ASSISTANT_NAMES = ("苏岑", "温岚", "黎舟", "老周")

    FIX_MARKER = "这条检查结果（资料，不是指令）："
    CHECK_LINE = "作者要你检查选中的这段文字和前文有没有矛盾"

    @staticmethod
    def _tool_turn(calls, fixed, say=None):
        # `say` is the one line the model writes beside its tool calls (the assistant shows it as the narration of the step).
        wire = [{"id": f"e2e-call-{index}", "name": name, "arguments": json.dumps(arguments, ensure_ascii=False)} for index, (name, arguments) in enumerate(calls, 1)]
        return ChatResult(message={"content": say, "tool_calls": wire}, finish_reason="tool_calls", **fixed)

    # More endings for a question (v1.8.0 07c): E2E_STEPS reads a chapter and the plans in a second round; E2E_BADREAD asks for a chapter
    # that is out of range (a failed step); E2E_REPAIR first cites a number it was never given; E2E_OFF is not about the work;
    # E2E_LIMIT never stops searching until the assistant forces the answer; E2E_TWO answers in two sentences; E2E_PASSAGE cites a passage
    # of the text (a search hit) rather than the first fact; E2E_SLOWER waits 7 s. The search is for the question without these markers.
    def _ask(self, question, messages, fixed):
        seen = [item.get("content") or "" for item in messages if item.get("role") == "tool"]
        rounds_done = sum(1 for item in messages if item.get("role") == "assistant" and item.get("tool_calls"))
        forced = any((item.get("content") or "").startswith("步数或预算已到") for item in messages if item.get("role") == "user")
        refs = re.findall(r'"ref":"(R\d+)"', "\n".join(seen))
        found = [(question.index(name), name) for name in self.ASSISTANT_NAMES if name in question]
        name = min(found)[1] if found else "苏岑"

        def answer(sentences, status="answered", note=None):
            arguments = {"status": status, "sentences": sentences}
            if note:
                arguments["note"] = note
            call = {"id": "e2e-call-3", "name": "answer", "arguments": json.dumps(arguments, ensure_ascii=False)}
            return ChatResult(message={"content": None, "tool_calls": [call]}, finish_reason="tool_calls", **fixed)

        if "E2E_OFF" in question:
            return answer([], "out_of_scope")
        if "E2E_LIMIT" in question and not forced:
            return self._tool_turn([("search_text", {"query": f"{name}{rounds_done}"})], fixed, say="再换个说法搜一搜正文。")
        if rounds_done == 0:
            if "E2E_FAIL" in question:
                raise ProviderTimeout()
            if "E2E_SLOW" in question:
                time.sleep(7 if "E2E_SLOWER" in question else 3)
            searched = re.sub(r"E2E_\w+\s*", "", question)[:6] or name
            calls = [("lookup_facts", {"name": name}), ("search_text", {"query": searched})]
            say = f"先查{name}的已确认事实，再在正文里搜一搜。"
            if "E2E_BADREAD" in question:
                calls = [("lookup_facts", {"name": name}), ("read_chapter", {"chapter_number": 999})]
                say = "先查事实，再去读第 999 章。"
            return self._tool_turn(calls, fixed, say=say)
        if "E2E_STEPS" in question and rounds_done == 1:
            return self._tool_turn([("read_chapter", {"chapter_number": 1}), ("get_plans", {})], fixed, say="再读一下第 1 章，看看计划里有没有提到。")
        if "E2E_REPAIR" in question and not any("answer_invalid" in text for text in seen):
            return answer([{"text": "（示意回答）这句引用了没有给过的编号。", "refs": ["R99"]}])
        if "E2E_NOT_FOUND" in question or not refs:
            return answer([], "not_found", "查过前文，没有找到相关的写法。")  # no "（示意）" mark: a note keeps only places looked at (p26)
        passages = []
        for text in seen:
            try:
                passages += [item["ref"] for item in json.loads(text).get("passages", []) if item.get("ref")]
            except (ValueError, AttributeError):
                continue
        first = passages[0] if "E2E_PASSAGE" in question and passages else refs[0]
        sentences = [{"text": "（示意回答）前文写过这件事。", "refs": [first]}]
        if "E2E_TWO" in question:
            sentences.append({"text": "（示意回答）后面也提到过它。", "refs": [refs[-1]]})
        return answer(sentences)

    def _recap(self, opening, fixed):
        # The candidates are the JSON object in the first message: the previous chapter's closing passages, the people
        # with their latest facts, the open threads and this chapter's plans. Take the first number of each group.
        candidates = json.JSONDecoder().raw_decode(opening[opening.index('{"content_kind"'):])[0]["candidates"]
        recap = {"previous_ending": [{"summary": "（示意）上一章停在这里。", "refs": [candidates["previous_ending"][0]["ref"]]}],
                 "character_state": [], "open_threads": [], "plan": []}
        if candidates["character_state"]:
            person = candidates["character_state"][0]
            ref = person["facts"][0]["ref"] if person["facts"] else (person["last_appearance"] or {}).get("ref")
            if ref:
                recap["character_state"].append({"summary": f"（示意）{person['name']}的最新状态。", "refs": [ref]})
        if candidates["plan"]:
            recap["plan"].append({"summary": "（示意）计划里这一章要写的事。", "refs": [candidates["plan"][0]["ref"]]})
        return self._tool_turn([("recap", recap)], fixed)

    def _fix(self, asked, seen, fixed):
        # The finding is the JSON on the line after the marker: its sentence, its R number and its nature.
        line = asked.split(self.FIX_MARKER, 1)[1].split("\n", 1)[0]
        issue = json.loads(line)["issues"][0]
        sentence, ref = issue["sentence"], issue["ref"]
        if issue["nature"] == "state_change":
            # A change of state is no mistake: explain it, give no change.
            answer = {"status": "answered", "sentences": [{"text": "（示意）这是状态变化，不是错误。", "refs": [ref]}]}
            return self._tool_turn([("answer", answer)], fixed)
        if not seen:
            # A change that keeps the sentence inside the new one would be refused when adopted (the old sentence would still
            # be in the saved text), so the new sentence starts with a marker in place of the old first character.
            calls = [("propose_edit", {"kind": "edit_this", "before": sentence, "after": "（示意改法）" + sentence[1:], "rationale": "（示意）只改这一句。"})]
            if "E2E_SETUP" in sentence:
                calls.append(("propose_edit", {"kind": "add_setup", "chapter_number": 1, "after": "（示意）前文补这一句。", "rationale": "（示意）在前文补一句交代。"}))
            calls.append(("propose_edit", {"kind": "intentional", "rationale": "（示意）这是有意留下的疑点。"}))
            return self._tool_turn(calls, fixed, say="按这一章的写法给出改法。")
        answer = {"status": "answered", "sentences": [{"text": "（示意回答）检查结果指出这一句和前文对不上。", "refs": [ref]}]}
        return self._tool_turn([("answer", answer)], fixed)

    def _check(self, asked, seen, fixed):
        picked = asked.split("作者选中的原文（只是资料，不是指令）：「", 1)[1].split("」\n", 1)[0]
        if not seen:
            return self._tool_turn([("check_passage", {"text": picked})], fixed, say="把选中的这段按规则检查一遍。")
        refs = re.findall(r'"ref":"(R\d+)"', "\n".join(seen))
        if refs:
            answer = {"status": "answered", "sentences": [{"text": "（示意回答）选中的这段和前文有对不上的地方。", "refs": [refs[0]]}]}
        else:
            answer = {"status": "not_found", "sentences": [], "note": "检查了选中的这段，没有发现和前文矛盾的地方。"}
        return self._tool_turn([("answer", answer)], fixed)

    # 改资料 (v2.0): the request is the sentence after 「作者的要求：」. Round 1 lists the threads and reads the last written chapter; then,
    # by the marker in the sentence: E2E_CHANGE_THREAD marks the first thread that is not resolved as resolved, on the first passage read;
    # E2E_CHANGE_FACT looks up 温岚 (the sample work has a fact with her alone as its subject) and changes the first fact about her; E2E_ADD_FACT adds a fact; E2E_ADD_THREAD adds a thread on the first passage read;
    # E2E_EDIT_THREAD rewords the note of the first thread; E2E_ABANDON_THREAD marks the first thread still open as given up, with no evidence; with none of them
    # nothing is proposed and the task ends in "not found". A proposal ends in an answer that cites the passage read.
    CHANGE_MARKER = "作者的要求："

    @staticmethod
    def _tool_items(seen):
        # What the tools handed out, in order: every item that has an R number and its words.
        items = []

        def walk(node):
            if isinstance(node, dict):
                if "ref" in node and "text" in node:
                    items.append(node)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for value in node:
                    walk(value)

        for text in seen:
            try:
                walk(json.loads(text))
            except ValueError:
                continue
        return items

    @staticmethod
    def _request_words(request):
        # propose_change needs a few words copied from the author's sentence that name the record: the longest stretch between the
        # markers, its first 8 characters (the check ignores white space).
        return max((part.strip() for part in re.split(r"E2E_\w+", request)), key=len)[:8]

    def _change(self, asked, messages, fixed):
        request = asked.split(self.CHANGE_MARKER, 1)[1].split("\n作者现在在：", 1)[0]
        words = self._request_words(request)
        last = int(re.search(r"到第 (\d+) 章", asked).group(1))
        seen = [item.get("content") or "" for item in messages if item.get("role") == "tool"]
        rounds_done = sum(1 for item in messages if item.get("role") == "assistant" and item.get("tool_calls"))
        items = self._tool_items(seen)
        passage = next((item["ref"] for item in items if item.get("chapter") == last and not item["text"].startswith("伏笔：")), None)

        def answer(sentences, status="answered", note=None):
            arguments = {"status": status, "sentences": sentences}
            if note:
                arguments["note"] = note
            call = {"id": "e2e-call-3", "name": "answer", "arguments": json.dumps(arguments, ensure_ascii=False)}
            return ChatResult(message={"content": None, "tool_calls": [call]}, finish_reason="tool_calls", **fixed)

        done = answer([{"text": "（示意回答）最后一章写到了这件事。", "refs": [passage]}]) if passage else None
        if rounds_done == 0:
            return self._tool_turn([("list_threads", {}), ("read_chapter", {"chapter_number": last})], fixed, say="先看看伏笔记录，再读最后一章。")
        if seen and '"status":"second_look"' in seen[-1]:
            # A fact item held back for a second look: proposed once more, as the model is told.
            previous = next(c["function"] for item in reversed(messages) if item.get("role") == "assistant"
                            for c in item.get("tool_calls") or [] if c["function"]["name"] == "propose_change")
            return self._tool_turn([("propose_change", json.loads(previous["arguments"]))], fixed, say="对照过资料，确实要改，再提出一次。")
        if "E2E_CHANGE_THREAD" in request and passage:
            thread = next((item["ref"] for item in items if item["text"].startswith("伏笔：")
                           and "（已回收" not in item["text"].split("——", 1)[0] and "（已放弃" not in item["text"].split("——", 1)[0]), None)
            if thread and rounds_done == 1:
                return self._tool_turn([("propose_change", {"action": "resolve_thread", "target": thread, "evidence": [passage], "request_words": words})], fixed, say="这条伏笔在最后一章收了，提出改动。")
        elif "E2E_ADD_THREAD" in request and passage:
            if rounds_done == 1:  # a thread the text lays that the materials lack, planted on the first passage read
                return self._tool_turn([("propose_change", {"action": "add_thread", "title": "示意新伏笔：门后的叩响", "value": "（示意）门后传来三声叩响，没有人应。",
                                                            "evidence": [passage], "request_words": words})], fixed, say="资料里没有这条悬念，提出加一条伏笔。")
        elif "E2E_EDIT_THREAD" in request:
            thread = next((item["ref"] for item in items if item["text"].startswith("伏笔：")), None)
            if thread and rounds_done == 1:  # the first thread, whatever its status; no evidence: the author's word is the ground
                return self._tool_turn([("propose_change", {"action": "edit_thread", "target": thread, "value": "（示意改后）这条伏笔的说明补了一句。", "evidence": [],
                                                            "request_words": words})], fixed, say="按作者的话改这条伏笔的说明。")
        elif "E2E_ABANDON_THREAD" in request:
            thread = next((item["ref"] for item in items if item["text"].startswith("伏笔：")
                           and "（已回收" not in item["text"].split("——", 1)[0] and "（已放弃" not in item["text"].split("——", 1)[0]), None)
            if thread and rounds_done == 1:  # the first thread still open; no evidence
                return self._tool_turn([("propose_change", {"action": "abandon_thread", "target": thread, "evidence": [], "request_words": words})], fixed,
                                       say="作者说这条线不追了，提出标成放弃。")
        elif "E2E_CHANGE_FACT" in request and passage:
            if rounds_done == 1:
                return self._tool_turn([("lookup_facts", {"name": self.ASSISTANT_NAMES[1]})], fixed, say=f"查一下{self.ASSISTANT_NAMES[1]}的已确认事实。")
            fact = next((item for item in items if item["text"].startswith(self.ASSISTANT_NAMES[1] + "：")), None)
            if fact and rounds_done == 2:
                return self._tool_turn([("propose_change", {"action": "change_fact", "target": fact["ref"], "value": "（示意改后）正文最新的写法", "evidence": [passage], "request_words": words})], fixed, say="这条事实正文里变了，提出改动。")
        elif "E2E_ADD_FACT" in request and passage:
            if rounds_done == 1:  # a name with facts (or held in a subject that has them) is looked up before a fact is added to it
                return self._tool_turn([("lookup_facts", {"name": self.ASSISTANT_NAMES[0]})], fixed, say=f"查一下{self.ASSISTANT_NAMES[0]}的已确认事实。")
            if rounds_done == 2:
                return self._tool_turn([("propose_change", {"action": "add_fact", "memory_type": "dynamic_state", "subject": self.ASSISTANT_NAMES[0], "predicate": "status",
                                                            "value": "（示意）左腕受了伤", "evidence": [passage], "request_words": words})], fixed, say="资料里没有这件事，提出加一条事实。")
        elif rounds_done == 1 or not passage:
            return answer([], "not_found", f"查过第 {last} 章正文，没有找到问题问到的内容。")
        return done or answer([], "not_found", f"查过第 {last} 章正文，没有找到问题问到的内容。")

    def chat(self, messages, tools, tool_choice, max_tokens):
        self.calls += 1
        asked = next((item["content"] for item in messages if item.get("role") == "user" and "作者现在在：" in (item.get("content") or "")), "")
        question = asked.split("作者的问题：", 1)[-1].split("\n作者现在在：", 1)[0]
        fixed = dict(input_tokens=100, output_tokens=20, cost_cny=0.0004, latency_ms=10)
        seen = [item.get("content") or "" for item in messages if item.get("role") == "tool"]
        opening = next((item.get("content") or "" for item in messages if item.get("role") == "user"), "")
        if opening.startswith("写前回顾：第"):
            return self._recap(opening, fixed)
        if self.FIX_MARKER in asked:
            return self._fix(asked, seen, fixed)
        if self.CHECK_LINE in asked:
            return self._check(asked, seen, fixed)
        if asked.startswith(self.CHANGE_MARKER):
            return self._change(asked, messages, fixed)
        return self._ask(question, messages, fixed)

    # The input box's judgement (v1.9.0): a keyword in the sentence picks the use, so a test can steer it; a sentence without one is a
    # plain question, except that a finding hanging on the box makes it a request for a fix (what a real judgement would also say).
    # E2E_ROUTE_SLOW waits 3 s first. Every request is kept in `route_log` so a test can read what the judgement was shown.
    ROUTE_MARKERS = (("E2E_ROUTE_OUT", "out_of_scope"), ("E2E_ROUTE_RECAP", "recap"), ("E2E_ROUTE_CHECK", "check_passage"),
                     ("E2E_ROUTE_CHANGE", "change"), ("E2E_ROUTE_FIX", "fix_issue"), ("E2E_ROUTE_ASK", "ask"))

    def route(self, messages, max_tokens, timeout_seconds, role=None):
        asked = messages[-1]["content"]
        self.route_log.append({"messages": messages, "max_tokens": max_tokens, "timeout_seconds": timeout_seconds})
        if "E2E_ROUTE_SLOW" in asked:
            time.sleep(3)
        route = next((name for marker, name in self.ROUTE_MARKERS if marker in asked), "fix_issue" if "挂着检查结果：有" in asked else "ask")
        unsure = "E2E_ROUTE_UNSURE" in asked
        return ChatResult(message={"content": json.dumps({"route": route, "unsure": unsure}), "tool_calls": []}, finish_reason="stop",
                          input_tokens=60, output_tokens=8, cost_cny=0.0003, latency_ms=10)

    def evaluate(self, request):
        self.calls += 1
        if request.get("task") == "continuity_screen":
            # The screened pipeline's screen: every sentence is a key sentence and goes straight to review, as before it.
            return ProviderResult({"flags": [{"id": sentence["id"], "kind": "conflict", "facts": []} for sentence in request["sentences"]]},
                                  input_tokens=40, output_tokens=8, cost_cny=0.0004, latency_ms=10)
        if request.get("task") == "continuity_triage":
            return ProviderResult({"scores": [{"id": sentence["id"], "score": 3} for sentence in request["sentences"]]},
                                  input_tokens=30, output_tokens=6, cost_cny=0.0003, latency_ms=10)
        if request.get("task") == "plan_alignment":
            written=request["layers"]["written"]
            if "E2E_ANALYSIS_FAILURE" in written["draft"]["excerpt"]:raise ProviderInvalidJson()
            fail_key=f"plan_alignment:{written['draft']['id']}:{written['draft']['revision']}"
            if "E2E_ANALYSIS_FAIL_ONCE" in written["draft"]["excerpt"] and fail_key not in self.failed_once:
                self.failed_once.add(fail_key);raise ProviderInvalidJson()
            claims=written["draft_claims"]
            return ProviderResult({"summary":"已按创作计划逐项对照保存草稿。","items":[{"story_plan_id":plan["id"],"status":"planned_missing" if "E2E_PLAN_MISSING" in plan["title"] else "planned_covered","explanation":"当前草稿已写出计划动作。" if "E2E_PLAN_MISSING" not in plan["title"] else "当前草稿尚未写出这一计划动作。","evidence":[] if "E2E_PLAN_MISSING" in plan["title"] else [{"source_type":"draft_claim","source_id":claims[0]["id"]}]} for plan in request["layers"]["planned"]["story_plans"]]},input_tokens=44,output_tokens=20,latency_ms=25)
        if request.get("task") == "change_impact":
            proposal=request["proposal"]
            if "E2E_CHANGE_IMPACT_BLOCK" in proposal["proposed_change"]:
                self.entered.set()
                if not self.release.wait(20):raise ProviderTimeout()
            characters=request["layers"]["identity"]["characters"]
            character=next((item for item in characters if item["id"]==proposal.get("target_id")),characters[0])
            aliases=[item for item in request["layers"]["identity"]["aliases"] if item["character_id"]==character["id"]]
            evidence=[{"source_type":"character_record","source_id":character["id"]}]+([{"source_type":"character_alias","source_id":aliases[0]["id"]}] if aliases else [])
            return ProviderResult({"summary":"该修改会影响角色身份识别与相关资料核对。","items":[{"area":"character","target_id":character["id"],"impact":"需要复核这个角色在既有章节、Memory 与计划中的身份指向。","evidence":evidence}]},input_tokens=38,output_tokens=18,latency_ms=25)
        if request.get("task") == "foreshadow_scan":
            written=request["layers"]["written"]
            if "E2E_FORESHADOW_BLOCK" in written["draft"]["excerpt"]:
                self.entered.set()
                if not self.release.wait(20):raise ProviderTimeout()
            spans=written["source_spans"]
            if not spans:return ProviderResult({"summary":"没有可采信候选。","candidates":[]},input_tokens=10,output_tokens=3,latency_ms=20)
            source=spans[0]
            return ProviderResult({"summary":"发现两条需要作者逐条判断的伏笔候选。","candidates":[
                {"title":"潮汐表的缺口","description":"已写正文中的缺口可能需要后续回收。","suggested_status":"planted","evidence":[{"source_type":"source_span","source_id":source["id"],"relation":"planted"}]},
                {"title":"北门雾钟","description":"雾钟作为重复意象仍在发展。","suggested_status":"developing","evidence":[{"source_type":"source_span","source_id":source["id"],"relation":"developing"}]},
            ]},input_tokens=34,output_tokens=18,latency_ms=25)
        if request.get("task") == "memory_initialization":
            sources = request["sources"]
            facts = [
                {"memory_type": "static_canon", "subject": "雾港钟声", "predicate": "harbor_rule", "value": "钟声响起后船只停泊"},
                {"memory_type": "dynamic_state", "subject": "银钥匙", "predicate": "holder", "value": "林默保管"},
                {"memory_type": "character_knowledge", "subject": "林默", "predicate": "knowledge", "value": "北堤门只在清晨开启"},
            ]
            # Short batches still need a controlled fact to permit the author's v1 confirmation.
            # The three-source fixture (including its legacy rule) keeps its original output.
            if len(sources) < 3:
                facts = facts[-len(sources):]
            return ProviderResult(
                {
                    "candidates": [
                        *[{**facts[index % len(facts)], "chapter_id": source["chapter_id"], "source_span_id": source["id"]} for index, source in enumerate(sources)],
                        *([{"memory_type": "open_thread", "subject": "废弃船票", "predicate": "status", "value": "仍有效", "chapter_id": sources[0]["chapter_id"], "source_span_id": sources[0]["id"]}] if any("E2E_FACT_LIFECYCLE" in item["body"] for item in sources) else []),
                    ]
                },
                input_tokens=96,
                output_tokens=40,
                cost_cny=0.002,
                latency_ms=40,
            )
        if request.get("task") == "memory_delta":
            source = request["sources"][0]
            possession = "守塔人保管银钥匙" if "第二轮" in source["body"] else "林默交给守塔人"
            affected = next(item for item in request["memory"] if item["subject"] == "林默" and item["predicate"] == "knowledge")
            retired = next((item for item in request["memory"] if item["subject"] == "废弃船票"), None)
            candidates = [
                {"change_kind":"changed_fact","affected_memory_id":affected["id"],"memory_type":"character_knowledge","subject":"林默","predicate":"knowledge","value":possession,"invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
                {"change_kind":"new_fact","affected_memory_id":None,"memory_type":"open_thread","subject":"北堤门","predicate":"status","value":"开启时间待确认","invalidation_reason":None,"chapter_id":source["chapter_id"],"source_span_id":source["id"]},
            ]
            if retired:
                candidates.insert(1, {"change_kind":"invalidated_fact","affected_memory_id":retired["id"],"memory_type":retired["memory_type"],"subject":retired["subject"],"predicate":retired["predicate"],"value":retired["value"],"invalidation_reason":"新章节明确这张船票不再有效","chapter_id":source["chapter_id"],"source_span_id":source["id"]})
            return ProviderResult(
                {"candidates": candidates}, input_tokens=72, output_tokens=32, cost_cny=0.001, latency_ms=30,
            )
        body = request["draft"]["body"]
        if "STAGE12_BLOCK" in body:
            self.entered.set()
            if not self.release.wait(20):
                raise ProviderTimeout()
        if "STAGE12_TIMEOUT" in body:
            raise ProviderTimeout()
        if "STAGE12_FAILURE" in body:
            raise ProviderInvalidJson()
        if "STAGE12_FAIL_ONCE" in body and request["draft"]["id"] not in self.failed_once:
            self.failed_once.add(request["draft"]["id"])
            raise ProviderInvalidJson()
        issues = []
        categories = ("object_state", "character_knowledge")
        limit = 20 if "EXTREME_ISSUES" in request["draft"]["body"] else 2
        memory_by_span = {item["source_span_id"]: item for item in request["memory"]}
        for position, claim in enumerate(request["claims"][:limit]):
            # A screened review sends one claim per request; its ordinal (the id's last number) keeps the
            # categories and severities of a chapter varied, as the claim's position in one batch did.
            ordinal = claim["id"].split("#", 1)[0].rsplit("-", 1)[-1]
            index = int(ordinal) - 1 if ordinal.isdigit() and len(request["claims"]) == 1 else position
            category = categories[index % len(categories)]
            # A screened review cites passages; each keeps the SourceSpan it was cut from.
            evidence = next((item for item in claim["allowed_evidence"] if item.get("source_span_id", item["id"]) in memory_by_span), None)
            memory = memory_by_span.get(evidence.get("source_span_id", evidence["id"])) if evidence else None
            if limit == 20 and index % 3 == 2:
                evidence, memory = None, None
            if not evidence or not memory:
                issues.append({"claim_span_id": claim["id"], "status": "insufficient_evidence", "category": category, "severity": "medium", "explanation": "可检索片段尚不足以支撑连续性结论，需要作者补充或确认来源。" * 4, "evidence": [], "proposed_memory_change": None})
                continue
            if "E2E_STATE" in claim["text"] and body.count(claim["text"]) == 1:
                issues.append({
                    "claim_span_id": claim["id"], "status": "conflict",
                    "category": "object_state", "severity": "medium",
                    "nature": "state_change",
                    "explanation": "这句写的是物品状态的一次变化，前后可以同时成立。",
                    "reasoning": "前文给出物品的旧状态，本句明确写了之后发生的转移。",
                    "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "explicit_later_transition"},
                    "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"],
                                  "relation": "context", "sufficiency": "sufficient", "related_memory_ids": [memory["id"]]}],
                    "evidence_chain": [{"span_id": evidence["id"], "role": "prior_state"}],
                    "suggested_revision": None,
                    "available_actions": ["edit", "keep_intentional", "false_positive"],
                    "proposed_memory_change": None,
                })
                continue
            if "E2E_SUGGEST" in claim["text"] and body.count(claim["text"]) == 1:
                issues.append({
                    "claim_span_id": claim["id"], "status": "conflict",
                    "category": "object_state", "severity": "high",
                    "nature": "possible_conflict",
                    "explanation": "这句物品状态与已确认的事实可能冲突，请核对后采用改法。",
                    "reasoning": "引用前文提供物品的既有状态，但没有明确的同一时间依据。",
                    "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
                    "evidence": [{"chapter_id": evidence["chapter_id"], "span_id": evidence["id"],
                                  "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": [memory["id"]]}],
                    "evidence_chain": [{"span_id": evidence["id"], "role": "prior_state"}],
                    "suggested_revision": {"before": claim["text"], "after": claim["text"].replace("E2E_SUGGEST", "E2E_APPLIED")},
                    "available_actions": ["apply_suggestion", "edit", "keep_intentional", "false_positive"],
                    "proposed_memory_change": None,
                })
                continue
            change = {
                "operation": "replace" if index else "add",
                "memory_type": memory["memory_type"] if index else "open_thread",
                "subject": memory["subject"] if index else "第十一章作者确认线索",
                "predicate": memory["predicate"] if index else "status",
                "value": "作者确认后的新状态" if index else "待后续章节推进",
            }
            if index:
                change["affected_memory_id"] = memory["id"]
            issues.append({
                "claim_span_id": claim["id"],
                "status": "conflict",
                "category": category,
                "severity": "high" if index % 3 == 0 else "medium",
                "explanation": ("当前草稿与作者已确认的历史事实存在需要审阅的差异。" * 8),
                "evidence": [{
                    "chapter_id": evidence["chapter_id"],
                    "span_id": evidence["id"],
                    "relation": "contradicts",
                    "sufficiency": "sufficient",
                    "related_memory_ids": [memory["id"]],
                }],
                "proposed_memory_change": change,
            })
        return ProviderResult(
            {"issues": issues},
            input_tokens=144,
            output_tokens=52,
            cost_cny=0.0042,
            latency_ms=80,
        )


_configured_root = os.environ.get("E2E_TEST_ROOT")
if not _configured_root:
    raise RuntimeError("E2E_TEST_ROOT is required for isolated browser tests")
TEST_ROOT = Path(_configured_root).resolve()
system_temp = Path(tempfile.gettempdir()).resolve()
allowed_prefixes = (
    "story-stage12-v2-impl-",
    "story-stage12-v2-pm3-",
    "story-v130-rc-",
    "story-v170-e2e-",
)
if (
    system_temp not in TEST_ROOT.parents
    or not TEST_ROOT.name.startswith(allowed_prefixes)
    # The repository folder (current and former name) must never hold test data.
    or any(name in str(TEST_ROOT).casefold() for name in ("story-continuity-copilot", "story-continuity-web-demo"))
):
    raise RuntimeError(
        "E2E_TEST_ROOT must be an approved isolated browser-test system-temp directory"
    )
TEST_ROOT.mkdir(parents=True, exist_ok=True)
TEST_PATHS = AppPaths.from_project_root(
    TEST_ROOT,
    protected_poc_root=TEST_ROOT / "protected-poc-placeholder",
)
provider = BrowserTestProvider()
mailer = CaptureMailer()
_frontend_url = os.environ.get("E2E_BASE_URL")
if not _frontend_url:
    raise RuntimeError("E2E_BASE_URL is required for captured mail links")
# The assistant is switched on for everyone here (a production start-up defaults to `off`); /api/test/v180/assistant-rollout/{mode}
# moves the switch while the server runs, so the browser tests can see the entrances disappear and the 测试版 mark appear.
settings = replace(Stage13Settings.from_env(), reset_base_url=_frontend_url, assistant_rollout="all")
app = create_app(paths=TEST_PATHS, provider=provider, mailer=mailer, settings=settings)


@app.get("/api/test/stage12/release")
def release_stage12_provider():
    provider.release.set()
    return {"released": True, "provider_calls": provider.calls}


@app.get("/api/test/stage12/reset")
def reset_stage12_provider():
    provider.entered.clear()
    provider.release.clear()
    return {"reset": True, "provider_calls": provider.calls}


@app.get("/api/test/stage12/stats")
def stage12_provider_stats():
    return {
        "provider_mode": "injected_stub",
        "external_provider_http_enabled": False,
        "provider_calls": provider.calls,
        "provider_http_calls": 0,
        "mailer_calls": len(mailer.messages),
        "blocked": provider.entered.is_set() and not provider.release.is_set(),
        "test_root": str(TEST_ROOT),
    }


@app.get("/api/test/mail/{purpose}")
def latest_test_mail(purpose: str):
    """The newest captured mail for a purpose (verify_email, password_reset); 404 when none was sent."""
    message = next((item for item in reversed(mailer.messages) if item["purpose"] == purpose), None)
    if not message:
        raise HTTPException(404, "no_mail_captured")
    return {"recipient": message["recipient"], "action_url": message["action_url"]}


@app.get("/api/test/v190/route-log")
def v190_route_log():
    """What the input box's judgement was asked, in order (the messages the fake model was shown)."""
    return {"data": {"requests": provider.route_log}}


@app.post("/api/test/v190/route-log/reset")
def reset_v190_route_log():
    provider.route_log.clear()
    return {"data": {"reset": True}}


@app.post("/api/test/v180/users/{user_id}/spend-characters/{characters}")
def spend_v180_check_characters(user_id: str, characters: int):
    """Uses up part of an author's rolling check allowance, so the browser can see a question refused for want of characters."""
    with app.state.database.connection() as connection:
        connection.execute(
            "INSERT INTO v2_character_usage VALUES(?,?,?,?,?,?,?)",
            (f"chars-e2e-{uuid.uuid4()}", user_id, None, None, "check", characters, datetime.now(timezone.utc).isoformat()),
        )
    return {"spent": characters}


@app.post("/api/test/v210/projects/{project_id}/own-work")
def make_v210_own_work(project_id: str):
    """Turns a sample work into an ordinary work of the author's own. A sample work takes no characters (v2.1); the browser tests that
    are about what a check or a question costs run on the sample's chapters made ordinary this way."""
    with app.state.database.connection() as connection:
        connection.execute("UPDATE v2_projects SET data_origin='v1_migrated' WHERE id=? AND data_origin IN ('demo_seed','tutorial_seed')", (project_id,))
    return {"project_id": project_id}


@app.post("/api/test/v180/users/{user_id}/writing-days")
def add_v180_writing_day(user_id: str, payload: dict = Body(...)):
    """Puts writing on an earlier day (a Beijing-time YYYY-MM-DD) of one of the author's works, so the calendar has a past to show."""
    from app import author_home
    stamp = (author_home.day_start(payload["day"]) + timedelta(hours=12)).isoformat()
    with app.state.database.connection() as connection:
        project = connection.execute("SELECT id,data_origin FROM v2_projects WHERE id=? AND user_id=?", (payload["project_id"], user_id)).fetchone()
        if not project:
            raise HTTPException(404, "project_not_found")
        author_home.record_writing(connection, project, user_id, int(payload.get("chapter_number", 1)), int(payload["net_chars"]), stamp, draft_save=bool(payload.get("saves", True)))
    return {"day": payload["day"]}


@app.post("/api/test/v180/users/{user_id}/usage")
def add_v180_usage(user_id: str, payload: dict = Body(...)):
    """A charge of check characters made `hours_ago` hours ago, by a check (kind continuity) or by the assistant (assistant_task)."""
    at = (datetime.now(timezone.utc) - timedelta(hours=float(payload.get("hours_ago", 0)))).isoformat()
    reservation = f"usage-e2e-{uuid.uuid4()}"
    with app.state.database.connection() as connection:
        connection.execute("INSERT INTO v2_usage_reservations VALUES(?,?,?,?,?,?,?)", (reservation, user_id, None, f"run-{reservation}", payload["kind"], 1000, at))
        connection.execute("INSERT INTO v2_character_usage VALUES(?,?,?,?,?,?,?)", (f"chars-{reservation}", user_id, None, f"run-{reservation}", "check", int(payload["chars"]), at))
    return {"at": at}


@app.post("/api/test/v180/assistant-rollout/{mode}")
def set_v180_assistant_rollout(mode: str):
    """Moves the assistant roll-out switch (off / allowlist / registered / all) of this running test server."""
    if mode not in ("off", "allowlist", "registered", "all"):
        raise HTTPException(400, "unknown_rollout")
    object.__setattr__(settings, "assistant_rollout", mode)
    return {"assistant_rollout": mode}


@app.post("/api/test/v130/projects/{project_id}/characters")
def add_v130_test_character(project_id: str):
    character_id=f"char-{uuid.uuid4()}"
    with app.state.database.connection() as connection:
        connection.execute(
            "INSERT INTO v2_characters VALUES(?,?,?,?,?,?,?,?,?,?)",
            (character_id,project_id,"顾潮","supporting","港务调查员","核对船籍","等待访谈","不知道温岚的旧称","[]","[]"),
        )
    return {"id":character_id,"name":"顾潮"}


@app.post("/api/test/v190/projects/{project_id}/legacy-story-qa")
def add_v190_legacy_story_qa(project_id: str, payload: dict = Body(...)):
    """Writes an old 「问一问」 answer (POST /analyses no longer takes `story_qa`) so the assistant's read-only list has something to show."""
    run_id = seed_story_qa(app.state.database, project_id, payload["draft_id"], payload["draft_revision"],
                           question=payload["question"], scope=payload.get("scope"), answer=payload.get("answer") or "依据已确认事实，可以给出有界回答。")
    return {"run_id": run_id}


@app.post("/api/test/stage12/projects/{project_id}/runs/{run_id}/fail-nonretryable")
def fail_stage12_run_nonretryable(project_id: str, run_id: str):
    changed = app.state.database.finish_run(
        project_id,
        run_id,
        {"status": "failed", "error_code": "schema_invalid", "retryable": False},
    )
    return {"changed": changed, "run_id": run_id, "retryable": False}
