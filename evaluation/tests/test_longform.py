"""Offline tests for the long-form evaluation tooling. No real provider is ever called."""
from __future__ import annotations

import contextlib
import io
import json
import os
import pathlib
import random
import shutil
import tempfile
import unittest
from unittest import mock

import httpx

from evaluation.longform import meter as metering
from evaluation.longform import run as runner
from evaluation.longform import thresholds
from evaluation.longform.schema import SET_HASH_FILE, load
from evaluation.longform.score import normalise_issue, score_retrieval, score_run, score_screening
from evaluation.longform.textutil import locate, sentence_cover, sentences
from evaluation.longform.validate import cross_check, main as validate_main, validate

TEMPLATE = pathlib.Path(__file__).resolve().parents[1] / "longform" / "template"
CATEGORIES = ("attribute", "object_state", "relationship", "character_knowledge",
              "timeline", "event_status", "location_action", "world_rule")
DIGITS = "零一二三四五六七八九"


def cn(number: int) -> str:
    return "".join(DIGITS[int(d)] for d in str(number))


_POOL = "山水风雨云河桥灯门窗纸墨船帆市街井楼钟鼓茶盐铁铜石木竹花叶鸟鱼马车田园雪霜春夏秋冬晨夜光影"
_rng = random.Random(20261004)


def prose(length: int) -> str:
    """Non-repeating filler: random characters, so no 20-character passage recurs by accident."""
    return "".join(_rng.choice(_POOL) for _ in range(length))


def copy_template(root: pathlib.Path) -> pathlib.Path:
    target = root / "set"
    shutil.copytree(TEMPLATE, target)
    return target


def edit_labels(set_dir: pathlib.Path, change) -> None:
    path = set_dir / "labels.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    change(data)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def quiet(fn, *args):
    with contextlib.redirect_stdout(io.StringIO()) as out:
        code = fn(*args)
    return code, out.getvalue()


def synthetic_dev_set(root: pathlib.Path) -> pathlib.Path:
    """A dev-profile set built from numbered filler sentences; every quote is unique by construction."""
    set_dir = root / "dev"
    (set_dir / "works").mkdir(parents=True)
    works, targets, selections = [], [], []
    links = ("handoff", "authorization", "provenance", "outcome")
    trap_kinds = ("state_change", "compatible_new_detail", "rule_exception", "similar_name")
    counter = {"conflict": 0, "gap": 0, "trap": 0, "item": 0}
    target_chapters = {0: range(4, 9), 1: range(3, 11), 2: range(4, 8)}  # 5 + 8 + 4 = 17 targets
    for w in range(3):
        key = f"work_{chr(97 + w)}{chr(97 + w)}{chr(97 + w)}"
        chapters = []
        for c in range(1, 11):
            # About 2,300 characters in 70 sentences, every sentence unique across all works.
            body = "".join(f"甲乙{cn(w)}号城第{cn(c)}章第{cn(s)}句里，{prose(18)}。" for s in range(70))
            chapters.append(f"# 第{cn(c)}章 标题{cn(w)}{cn(c)}\n\n{body}")
        (set_dir / "works" / f"{key}.md").write_text("\n\n".join(chapters) + "\n", encoding="utf-8")
        works.append({"key": key, "title": f"作品{cn(w)}", "file": f"works/{key}.md", "origin": "original", "source_note": None})
        quote = lambda chap, s, w=w: f"甲乙{cn(w)}号城第{cn(chap)}章第{cn(s)}句里"
        first = f"第{cn(1)}章 标题{cn(w)}{cn(1)}"
        work_targets = []
        for c in target_chapters[w]:
            title = f"第{cn(c)}章 标题{cn(w)}{cn(c)}"
            items, traps = [], []
            if c != target_chapters[w][-1]:  # the last target of each work stays clean
                for slot in (0, 1):
                    counter["item"] += 1
                    item_id = f"w{w}-i{counter['item']}"
                    evidence = [{"chapter": first, "quote": quote(1, slot)}]
                    if counter["item"] % 3 == 0:
                        items.append({"id": item_id, "class": "insufficient_evidence", "category": None,
                                      "missing_link": links[counter["gap"] % 4], "issue_quotes": [quote(c, 10 + slot * 10)],
                                      "evidence": evidence, "designated_regression": False, "designated_basis": None,
                                      "explanation": "缺一环。"})
                        counter["gap"] += 1
                    else:
                        designated = counter["conflict"] == 0
                        items.append({"id": item_id, "class": "conflict", "category": CATEGORIES[counter["conflict"] % 8],
                                      "missing_link": None, "issue_quotes": [quote(c, 10 + slot * 10)], "evidence": evidence,
                                      "designated_regression": designated,
                                      "designated_basis": {"type": "timeless_rule", "anchor": "号城"} if designated else None,
                                      "explanation": "前后矛盾。"})
                        counter["conflict"] += 1
                counter["trap"] += 1
                traps.append({"id": f"w{w}-p{counter['trap']}", "kind": trap_kinds[counter["trap"] % 4],
                              "quotes": [quote(c, 40)], "evidence": [{"chapter": first, "quote": quote(1, 3)}],
                              "explanation": "不矛盾。"})
            targets.append({"id": f"w{w}-t{c}", "work": key, "chapter": title, "smoke": w == 0 and c in (4, 5, 6),
                            "items": items, "traps": traps})
            work_targets.append(title)
        if w == 0:
            selections.append({"id": "sel-5", "work": key, "chapters": work_targets})
        if w == 1:
            selections.append({"id": "sel-8", "work": key, "chapters": work_targets})
    labels = {"format": "longform-eval/1", "set_id": "lf-synthetic", "kind": "dev", "language": "zh",
              "authoring": {"model": "test", "date": "2026-10-04"}, "works": works, "targets": targets,
              "selections": selections, "subsets": {}}
    (set_dir / "labels.json").write_text(json.dumps(labels, ensure_ascii=False, indent=2), encoding="utf-8")
    (set_dir / "authoring").mkdir()
    (set_dir / "authoring" / "self-review.json").write_text(json.dumps({"targets": [
        {"target_id": t["id"], "unintended_issues_checked": True, "notes": ""} for t in targets]}), encoding="utf-8")
    return set_dir


class TextTests(unittest.TestCase):
    def test_sentences_keep_closing_quotes_and_unpunctuated_lines(self):
        body = "他说：“走吧。”然后转身！\n没有标点的一行\n她问：“真的吗？”他点头。"
        self.assertEqual([body[s:e] for s, e in sentences(body)],
                         ["他说：“走吧。”", "然后转身！", "没有标点的一行", "她问：“真的吗？”", "他点头。"])

    def test_locate_requires_a_unique_quote_and_cover_widens_to_sentences(self):
        body = "灯亮了。灯亮了。风停了，人走了。"
        self.assertIsNone(locate(body, "灯亮了"))
        span = locate(body, "人走")
        self.assertEqual(body[slice(*sentence_cover(body, span))], "风停了，人走了。")


class ValidatorTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="lf-test-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def errors(self, set_dir, structure_only=True):
        return validate(load(set_dir), structure_only=structure_only)[0]

    def test_template_passes_structure_only_and_fails_the_full_rules(self):
        self.assertEqual(self.errors(TEMPLATE), [])
        full = self.errors(TEMPLATE, structure_only=False)
        self.assertTrue(any("expected 3 works" in e for e in full))

    def test_synthetic_dev_set_passes_the_full_profile(self):
        set_dir = synthetic_dev_set(self.tmp)
        self.assertEqual(self.errors(set_dir, structure_only=False), [])
        (set_dir / "authoring" / "self-review.json").write_text('{"targets": []}', encoding="utf-8")
        self.assertTrue(any("self-review" in e for e in self.errors(set_dir, structure_only=False)))

    def test_templated_prose_is_rejected(self):
        set_dir = synthetic_dev_set(self.tmp)
        template = "他先绕到后窗，看见窗棂的一格被风吹得晃动，就拿碎布塞住缝隙。屋里原本有些拥挤，两个人把闲置的凳子挪开。"
        for work in (set_dir / "works").glob("*.md"):
            text = work.read_text(encoding="utf-8")
            work.write_text(text.replace("句里，", "句里，" + template), encoding="utf-8")
        errors = self.errors(set_dir, structure_only=False)
        self.assertTrue(any("repeat elsewhere in the work" in e for e in errors))
        self.assertTrue(any("reappears in another chapter" in e for e in errors))
        self.assertTrue(any("share" in e and "passages" in e for e in errors))

    def test_labelled_sentences_must_not_all_stand_alone(self):
        set_dir = synthetic_dev_set(self.tmp)
        lf = load(set_dir)
        for key in lf.works:
            path = set_dir / "works" / f"{key}.md"
            text = path.read_text(encoding="utf-8")
            # Put every sentence on its own line: each labelled sentence becomes its own paragraph.
            path.write_text(text.replace("。", "。\n"), encoding="utf-8")
        self.assertTrue(any("stand alone" in e for e in self.errors(set_dir, structure_only=False)))

    def test_evidence_must_come_from_an_earlier_chapter(self):
        set_dir = copy_template(self.tmp)
        edit_labels(set_dir, lambda d: d["targets"][0]["items"][0]["evidence"].__setitem__(
            0, {"chapter": "第四章 雾散以后", "quote": "柏绍的手腕也好了一些"}))
        self.assertTrue(any("not earlier than the target" in e for e in self.errors(set_dir)))

    def test_duplicate_quote_overlap_and_bad_category_are_reported_without_text(self):
        set_dir = copy_template(self.tmp)

        def change(d):
            item = d["targets"][0]["items"][0]
            item["category"] = "mood"
            d["targets"][0]["traps"][0]["quotes"] = ["她看见杂货铺的掌柜正踮着脚"]  # same sentence as tpl-001
            d["targets"][0]["items"][1]["evidence"][0]["quote"] = "柏绍"  # too short, and not unique
        edit_labels(set_dir, change)
        errors = self.errors(set_dir)
        self.assertTrue(any("category" in e for e in errors))
        self.assertTrue(any("share a sentence" in e for e in errors))
        self.assertTrue(any("quote must be one line" in e for e in errors))
        self.assertFalse(any("掌柜" in e or "柏绍" in e for e in errors))

    def test_banned_names_and_cross_set_overlap(self):
        set_dir = copy_template(self.tmp)
        other = self.tmp / "other"
        shutil.copytree(set_dir, other)
        self.assertTrue(cross_check(load(set_dir), load(other)))
        work = set_dir / "works" / "qingyan_lamps.md"
        work.write_text(work.read_text(encoding="utf-8").replace("青檐镇", "灰港镇"), encoding="utf-8")
        self.assertTrue(any("reuses a name" in e for e in self.errors(set_dir)))

    def test_private_test_work_must_stay_outside_the_repository(self):
        inside = pathlib.Path(__file__).resolve().parents[1] / "longform" / f"_tmp_private_{os.getpid()}"
        try:
            shutil.copytree(TEMPLATE, inside)
            edit_labels(inside, lambda d: d["works"][0].update(origin="private_test", source_note="私人测试用"))
            self.assertTrue(any("outside the repository" in e for e in self.errors(inside)))
        finally:
            shutil.rmtree(inside, ignore_errors=True)
        outside = copy_template(self.tmp)
        edit_labels(outside, lambda d: d["works"][0].update(origin="private_test", source_note="私人测试用"))
        self.assertEqual(self.errors(outside), [])
        edit_labels(outside, lambda d: d["works"][0].update(source_note=None))
        self.assertTrue(any("needs source_note" in e for e in self.errors(outside)))

    def test_freeze_survives_crlf_and_detects_edits(self):
        set_dir = copy_template(self.tmp)
        code, _ = quiet(validate_main, [str(set_dir), "--structure-only", "--freeze"])
        self.assertEqual(code, 0)
        self.assertTrue((set_dir / SET_HASH_FILE).exists())
        work = set_dir / "works" / "qingyan_lamps.md"
        work.write_bytes(work.read_bytes().replace(b"\n", b"\r\n"))
        self.assertEqual(quiet(validate_main, [str(set_dir), "--structure-only", "--require-frozen"])[0], 0)
        work.write_text(work.read_text(encoding="utf-8") + "多一句。", encoding="utf-8")
        self.assertEqual(quiet(validate_main, [str(set_dir), "--structure-only", "--require-frozen"])[0], 1)


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.lf = load(TEMPLATE)
        self.body = self.lf.targets[0].chapter.body
        self.clean_body = self.lf.targets[1].chapter.body

    def span(self, text, body=None):
        return locate(body or self.body, text)

    def test_position_and_nature_scoring(self):
        records = {
            "tpl-t01": {"status": "completed", "sentence_count": 5, "undecided_count": 0, "issues": [
                normalise_issue("confirmed_conflict", "world_rule", self.span("灯罩上还滴着新油"), [1]),
                normalise_issue("insufficient_evidence", "event_status", self.span("可柏绍从来没提过")),
                normalise_issue("possible_conflict", "object_state", self.span("苗禾提着锡油壶")),
                normalise_issue("state_change", "object_state", self.span("她把灯芯剪短")),
            ]},
            "tpl-t02": {"status": "completed", "sentence_count": 4, "undecided_count": 1, "issues": [
                normalise_issue("possible_conflict", "timeline", self.span("第二天雾散了", self.clean_body)),
            ]},
        }
        result = score_run(self.lf, records)
        self.assertEqual(result["conflict_recall"], 1.0)
        self.assertEqual(result["insufficient_evidence_recall"], 1.0)
        self.assertEqual(result["designated"]["confirmed_with_category"], 1)
        self.assertEqual(result["trap_false_positive_rate"], 1.0)
        self.assertEqual(result["spurious_cards_per_target"], 0.5)
        self.assertEqual(result["clean_target_zero_card_rate"], 0.0)
        self.assertEqual(result["undecided_sentence_rate"], 1 / 9)
        self.assertEqual(result["diagnostics"]["state_change_cards"], 1)

    def test_conflict_takes_precedence_over_a_gap_and_missing_records_fail(self):
        records = {"tpl-t01": {"status": "completed", "issues": [
            normalise_issue("insufficient_evidence", None, self.span("可柏绍从来没提过")),
            normalise_issue("possible_conflict", "relationship", self.span("掌柜笑着说")),
        ]}}
        result = score_run(self.lf, records)
        self.assertEqual(result["insufficient_evidence_recall"], 0.0)
        self.assertEqual(result["insufficient_evidence_reported_as_conflict"], 1)
        self.assertEqual(result["completed_targets"], 1)
        self.assertEqual(result["terminal"].get("missing:None"), 1)

    def test_retrieval_and_screening_offline(self):
        target = self.lf.targets[0]
        rule = self.lf.works["qingyan_lamps"][0].body
        lend = self.lf.works["qingyan_lamps"][1].body
        rule_span = locate(rule, "任何人都不得私自给铜灯添油")
        lend_span = locate(lend, "他把备用的锡油壶借给了徒弟苗禾")
        query = {"start": 0, "end": len(target.chapter.body), "results": [
            {"chapter_index": 2, "start": lend_span[0], "end": lend_span[1]},
            {"chapter_index": 4, "start": 0, "end": 5},  # a later chapter: a leak, never a hit
            {"chapter_index": 1, "start": rule_span[0], "end": rule_span[1]},
        ]}
        result = score_retrieval(self.lf, {"targets": {"tpl-t01": {"queries": [query]}}}, ks=(1, 2))
        self.assertEqual(result["later_chapter_leaks"], 1)
        self.assertEqual(result["recall_all_evidence"][1], 0.5)  # only the gap's evidence is first
        self.assertEqual(result["recall_all_evidence"][2], 1.0)
        flag = sentence_cover(target.chapter.body, locate(target.chapter.body, "灯罩上还滴着新油"))
        screening = score_screening(self.lf, {"targets": {"tpl-t01": {"flagged": [{"start": flag[0], "end": flag[1]}]}}})
        self.assertEqual(screening["conflict_recall"], 1.0)
        self.assertEqual(screening["insufficient_evidence_recall"], 0.0)
        self.assertLess(screening["flagged_text_share"], 0.5)


def deepseek_response(content: dict, *, prompt=1000, completion=300, hit=200, reasoning=250, finish="stop"):
    return {"id": "x", "model": "deepseek-flash", "system_fingerprint": "fp-test",
            "choices": [{"index": 0, "finish_reason": finish,
                         "message": {"role": "assistant", "content": json.dumps(content, ensure_ascii=False),
                                     "reasoning_content": "secret thinking"}}],
            "usage": {"prompt_tokens": prompt, "completion_tokens": completion, "total_tokens": prompt + completion,
                      "prompt_cache_hit_tokens": hit, "prompt_cache_miss_tokens": prompt - hit,
                      "completion_tokens_details": {"reasoning_tokens": reasoning}}}


def fake_model(request: httpx.Request) -> httpx.Response:
    """Answers like DeepSeek: Memory candidates for an import, no_issue for every claim on review."""
    body = json.loads(request.content)
    prompt = json.loads(body["messages"][0]["content"])
    if "source_spans" in prompt:
        span = prompt["source_spans"][0]
        content = {"candidates": [{"memory_type": "event_timeline", "subject": "测试", "predicate": "event_occurred",
                                   "value": "测试事件", "chapter_id": span["chapter_id"], "source_span_id": span["source_span_id"]}]}
    elif "current_claims" in prompt:
        content = {"issues": [], "claim_verdicts": [{"claim_span_id": c["id"], "verdict": "no_issue", "basis": "无冲突。"}
                                                    for c in prompt["current_claims"]]}
    else:
        content = {}
    return httpx.Response(200, json=deepseek_response(content))


PROVIDER_ENV = {"CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": "deepseek-flash",
                "CONTINUITY_BASE_URL": "http://fake-provider.test", "CONTINUITY_API_KEY": "test-only",
                "CONTINUITY_REVIEW_THINKING": "high", "CONTINUITY_REVIEW_CONCURRENCY": "1"}


class MeterTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="lf-meter-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def post(self, meter, body, handler, kind="review"):
        token = metering._call_kind.set(kind)
        try:
            with mock.patch.object(metering, "TRANSPORT", httpx.MockTransport(handler)):
                with meter.client_factory() as client:
                    return client.post("http://fake-provider.test/chat/completions", json=body)
        finally:
            metering._call_kind.reset(token)

    def test_usage_split_purpose_and_price(self):
        meter = metering.Meter()
        body = {"model": "m", "messages": [{"role": "user", "content": "x"}], "reasoning_effort": "high", "max_tokens": 16000}
        self.post(meter, body, lambda r: httpx.Response(200, json=deepseek_response({})))
        self.post(meter, body, lambda r: httpx.Response(200, json=deepseek_response({}, finish="length")))
        self.post(meter, body, lambda r: httpx.Response(200, json=deepseek_response({})), kind="review_repair")
        summary = meter.summary()
        self.assertEqual(summary["tokens"], {"input_miss": 2400, "input_hit": 600, "reasoning": 750, "visible_output": 150})
        self.assertEqual(set(summary["by_purpose"]), {"review", "length_retry", "contract_repair"})
        self.assertAlmostEqual(summary["cost_cny"]["total"], 3 * (1000 * 2.0 + 300 * 8.0) / 1e6)
        self.assertEqual(meter.fingerprints, ["fp-test"])

    def test_budget_cap_refuses_before_sending(self):
        meter = metering.Meter(budget_cny=0.05)
        body = {"model": "m", "messages": [{"role": "user", "content": "x"}], "max_tokens": 16000}  # reserve 0.128
        sent = []
        with self.assertRaises(metering.BudgetExceeded):
            self.post(meter, body, lambda r: sent.append(r) or httpx.Response(200, json=deepseek_response({})))
        self.assertEqual(sent, [])
        self.assertEqual(meter.stop_reason, "budget_cap")

    def test_failed_dispatch_is_charged_its_reserve(self):
        meter = metering.Meter()
        body = {"model": "m", "messages": [{"role": "user", "content": "x"}], "max_tokens": 1000}

        def boom(request):
            raise httpx.ReadTimeout("slow", request=request)
        with self.assertRaises(httpx.ReadTimeout):
            self.post(meter, body, boom)
        self.assertAlmostEqual(meter.spent_cny, (1 * 2.0 + 1000 * 8.0) / 1e6)
        self.assertEqual(meter.summary()["unknown_usage_dispatches"], 1)

    def test_replay_maps_fresh_ids_and_never_stores_reasoning(self):
        first, second = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        body = lambda ident: {"model": "m", "messages": [{"role": "user", "content": f"claim span-{ident}"}], "max_tokens": 10}
        recorder = metering.Meter(replay="record", cache_dir=self.tmp)
        self.post(recorder, body(first), lambda r: httpx.Response(200, json=deepseek_response({"claim": f"span-{first}"})))
        stored = next(self.tmp.rglob("*.json")).read_text(encoding="utf-8")
        self.assertNotIn("secret thinking", stored)
        self.assertNotIn(first, stored)
        player = metering.Meter(replay="replay", cache_dir=self.tmp)
        response = self.post(player, body(second), lambda r: self.fail("replay must not hit the network"))
        content = json.loads(response.json()["choices"][0]["message"]["content"])
        self.assertEqual(content, {"claim": f"span-{second}"})
        self.assertEqual(player.spent_cny, 0)
        with self.assertRaises(metering.ReplayMiss):
            self.post(player, {"model": "m", "messages": [{"role": "user", "content": "new"}]}, lambda r: self.fail())

    def test_id_only_lists_compare_as_sets_but_text_order_still_matters(self):
        a, b = "11111111-2222-3333-4444-555555555555", "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
        body = lambda payload: {"messages": [{"role": "user", "content": json.dumps(payload)}]}
        spans = [{"id": f"span-{a}"}, {"id": f"span-{b}"}]
        first = body({"spans": spans, "allowed": [f"span-{a}", f"span-{b}"]})
        swapped = body({"spans": spans, "allowed": [f"span-{b}", f"span-{a}"]})
        self.assertEqual(metering.request_key(first)[0], metering.request_key(swapped)[0])
        reordered_text = body({"spans": spans, "claims": ["第一句", "第二句"]})
        self.assertNotEqual(metering.request_key(reordered_text)[0],
                            metering.request_key(body({"spans": spans, "claims": ["第二句", "第一句"]}))[0])


class RunnerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = pathlib.Path(tempfile.mkdtemp(prefix="lf-run-"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_template_run_end_to_end_with_a_fake_model(self):
        with mock.patch.dict(os.environ, PROVIDER_ENV), \
                mock.patch.object(metering, "TRANSPORT", httpx.MockTransport(fake_model)), \
                mock.patch.object(metering, "DEFAULT_CACHE_DIR", self.tmp / "cache"):
            code, out = quiet(runner.main, ["--set", str(TEMPLATE), "--run-id", "t1", "--allow-incomplete-set",
                                            "--results-dir", str(self.tmp), "--replay", "record"])
            self.assertEqual(code, 0, out)
            report = json.loads((self.tmp / "longform-lf-template-t1.json").read_text(encoding="utf-8"))
            self.assertEqual(report["targets_run"], ["tpl-t01", "tpl-t02"])
            self.assertEqual(report["quality"]["completed_targets"], 2)
            self.assertEqual(report["quality"]["conflict_recall"], 0.0)  # the fake model finds nothing
            self.assertEqual(report["quality"]["clean_target_zero_card_rate"], 1.0)
            check = report["cost_time"]["check_totals"]
            self.assertGreater(check["dispatches"], 0)
            self.assertEqual(set(check["by_purpose"]), {"review"})
            self.assertIn("memory_initialization", report["cost_time"]["setup_totals"]["by_purpose"])
            self.assertTrue(report["cost_time"]["timing_valid"])
            self.assertEqual(report["cost_time"]["selections"][0]["complete"], True)
            self.assertIsNone(report["threshold_result"])
            with self.assertRaises(FileExistsError):
                runner.main(["--set", str(TEMPLATE), "--run-id", "t1", "--allow-incomplete-set", "--results-dir", str(self.tmp)])
            # The recorded run replays without the network; the timings are then marked invalid.
            with mock.patch.object(metering, "TRANSPORT", httpx.MockTransport(lambda r: self.fail("network"))):
                code, out = quiet(runner.main, ["--set", str(TEMPLATE), "--run-id", "t2", "--allow-incomplete-set",
                                                "--results-dir", str(self.tmp), "--replay", "replay"])
            self.assertEqual(code, 0, out)
            replayed = json.loads((self.tmp / "longform-lf-template-t2.json").read_text(encoding="utf-8"))
            self.assertFalse(replayed["cost_time"]["timing_valid"])
            self.assertEqual(replayed["meter"]["spent_cny"], 0)

    def test_budget_cap_stops_the_run_and_formal_refuses_now(self):
        with mock.patch.dict(os.environ, PROVIDER_ENV), \
                mock.patch.object(metering, "TRANSPORT", httpx.MockTransport(fake_model)):
            code, _ = quiet(runner.main, ["--set", str(TEMPLATE), "--run-id", "cap", "--allow-incomplete-set",
                                          "--results-dir", str(self.tmp), "--budget-cny", "0.01"])
            self.assertEqual(code, 0)
            report = json.loads((self.tmp / "longform-lf-template-cap.json").read_text(encoding="utf-8"))
            self.assertEqual(report["stopped_early"], "budget_cap")
            self.assertLessEqual(report["meter"]["spent_cny"], 0.01)
            with self.assertRaises(RuntimeError) as raised:
                runner.main(["--set", str(TEMPLATE), "--run-id", "f", "--mode", "formal", "--results-dir", str(self.tmp)])
            self.assertIn("longform_set_invalid", str(raised.exception))
            set_dir = synthetic_dev_set(self.tmp)
            with self.assertRaises(RuntimeError) as raised:
                runner.main(["--set", str(set_dir), "--run-id", "f", "--mode", "formal", "--results-dir", str(self.tmp)])
            self.assertNotIn("thresholds_not_approved", str(raised.exception))
            for reason in ("set_kind_is_not_formal", "set_not_frozen", "prompt_version_not_pinned",
                           "concurrency_not_production"):
                self.assertIn(reason, str(raised.exception))


class ThresholdTests(unittest.TestCase):
    def test_bar_is_approved_and_missing_values_are_not_a_pass(self):
        self.assertTrue(thresholds.APPROVED)
        self.assertEqual(thresholds.APPROVED_ON, "2026-10-04")
        result = thresholds.evaluate({})
        self.assertFalse(result["passed"])
        self.assertIsNone(result["checks"]["conflict_recall"])

    def test_sequential_selection_cannot_pass_time(self):
        report = {"cost_time": {"selection_mode": "sequential_sum", "timing_valid": True,
                                "selections": [{"id": "s", "chapters": 5, "seconds": 10, "cost_cny": 0.5}]}}
        checks = thresholds.evaluate_selections(report)["checks"]["s"]
        self.assertIsNone(checks["seconds"])
        self.assertTrue(checks["cost"])


if __name__ == "__main__":
    unittest.main()
