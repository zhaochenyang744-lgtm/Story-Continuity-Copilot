"""v1.9 runner acceptance: invented backends and local spent fixtures, no model network."""
import contextlib
import copy
import hashlib
import io
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import httpx
from evaluation.assistant_a1 import a1c, judge, run, score, supplemental
from evaluation.assistant_a1c import thresholds
from evaluation.eval_set_a1cy_dev import check

SET = 'eval_set_a1cy_dev'
PAIR = ','.join(run.A1C_FORMAL_SETS)  # since the fifth pair ran: the route-only retest alone (A1c SPEC addendum 16)
FIFTH = ['eval_set_a1c5_formal', 'eval_set_a1cs5_formal']


def args(*extra):
    return run.parser().parse_args(['--set', SET, '--run-id', 'offline-v190',
                                   '--assistant-rates', '2,8', '--judge-rates', '9,27', *extra])


def route_task(**extra):
    return {'id': 'route', 'work': 'w', 'suite': 'route', 'input': '帮我看看这里',
            'context': {'page': 'writing', 'selection': '她把书放下。'}, 'expected_route': 'check_passage', **extra}


def suggest_task(kind='thread_resolution', **extra):
    return {'id': 'suggest', 'work': 'w', 'suite': 'suggest', 'suggest_type': kind,
            'question': '这条线怎么接？', 'answer_points': [] if kind == 'creative_direction' else ['保留未知'],
            'forbidden_claims': ['编出人物'], 'evidence_chapters': [], **extra}


def assistant_view():
    return {'id': 'assistant-1', 'status': 'completed', 'kind': 'ask', 'usage': {'steps': 1},
            'elapsed_seconds': 2, 'token_usage': {'input_tokens': 100, 'output_tokens': 20},
            'steps': [], 'answer': {'status': 'answered', 'sentences': [{'text': '仍未查明', 'refs': ['R1']}]},
            'sources': {'R1': {'kind': 'fact', 'text': '仍未查明', 'anchor': 'MUST NOT REACH JUDGE'}}}


class FakeWork:
    """Endpoint double; never creates a product app or model provider."""
    def __init__(self, *unused, **kwargs):
        self.price = (2, 8)
        self.saved, self.route_bodies, self.assistant_bodies = [], [], []
        self.route_results = [{'status': 'completed', 'route': 'check_passage', 'source': 'rule', 'unsure': False, 'elapsed_seconds': .1}]
        self.check_result = {'status': 'completed', 'issues': [
            {'id': 'issue-1', 'nature': 'possible_conflict', 'sentence': '林禾只惯用右手。'}]}
        self.check_calls = 0
        self.initialization = {'status': 'completed'}
        self.lengths = {'1': 3000}
        self.journal = None

    def save(self, text): self.saved.append(text); return {'revision': len(self.saved)}
    def check(self): self.check_calls += 1; return copy.deepcopy(self.check_result)
    def route(self, body):
        self.route_bodies.append(copy.deepcopy(body))
        return copy.deepcopy(self.route_results[min(len(self.route_bodies)-1, len(self.route_results)-1)])
    def assistant(self, body):
        self.assistant_bodies.append(copy.deepcopy(body))
        return assistant_view()
    def chapter_lengths(self): return self.lengths
    def close(self): pass


class OfflineTests(unittest.TestCase):
    def setUp(self):
        network = patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('network forbidden'))
        network.start()
        self.addCleanup(network.stop)

    def test_route_expected_alternative_mismatch_and_execution_error(self):
        for actual, errors, expected in [('check_passage', [], True), ('ask', [], True),
                                         ('recap', [], False), ('check_passage', ['issue_from_check_miss'], False)]:
            with self.subTest(actual=actual, errors=errors):
                row = run.new_record(route_task(also_acceptable=['ask']))
                row.update(route_result={'route': actual}, execution_errors=errors)
                self.assertEqual(score.decide(row), expected)
                self.assertNotIn('assistant_not_completed', row['failure_reasons'])
                self.assertEqual(list(judge.questions(row)), [])

    def test_route_preserves_context_and_never_starts_task(self):
        work = FakeWork()
        task = route_task(context={'page': 'writing', 'selection': '她把书放下。', 'chapter_number': 31})
        row = run.run_task(work, task, '她把书放下。窗开着。')
        self.assertEqual(work.saved, ['她把书放下。窗开着。'])
        self.assertEqual(work.route_bodies, [{'input': task['input'], 'context': task['context']}])
        self.assertEqual(work.assistant_bodies, [])
        self.assertTrue(score.decide(row))
        self.assertEqual(row['route_seconds'], .1)

    def test_route_nonwriting_page_does_not_save_draft(self):
        work = FakeWork()
        run.run_task(work, route_task(context={'page': 'plan'}), '草稿')
        self.assertEqual(work.saved, [])
        self.assertEqual(work.route_bodies[0]['context']['page'], 'plan')

    def test_issue_from_prepares_fix_draft_and_uses_same_overlap_rule(self):
        work = FakeWork()
        task = route_task(context={'page': 'writing', 'issue_from': 'fix'}, expected_route='fix_issue')
        fix = {'id': 'fix', 'work': 'w', 'suite': 'fix', 'draft': '林禾只惯用右手。她坐下。',
               'conflict_sentence': '林禾只惯用右手。'}
        work.route_results[0]['route'] = 'fix_issue'
        row = run.run_task(work, task, '共享草稿', task_lookup={'fix': fix})
        self.assertTrue(score.decide(row))
        self.assertEqual(work.saved, [fix['draft']])
        self.assertEqual(work.route_bodies[0]['context'], {'page': 'writing', 'issue_id': 'issue-1'})
        self.assertEqual(work.check_calls, 1)

    def test_issue_from_miss_and_wrong_work_remain_in_denominator(self):
        for missing in (True, False):
            work = FakeWork()
            work.check_result = {'status': 'completed', 'issues': []}
            t = route_task(context={'page': 'writing', 'issue_from': 'fix'}, expected_route='fix_issue')
            fix = {'id': 'fix', 'work': 'w' if missing else 'other', 'suite': 'fix',
                   'draft': '林禾只惯用右手。', 'conflict_sentence': '林禾只惯用右手。'}
            row = run.run_task(work, t, '', task_lookup={'fix': fix})
            self.assertEqual(row['execution_errors'], ['issue_from_check_miss' if missing else 'issue_from_invalid'])
            row.update(set=SET, run_number=1)
            metrics, _ = a1c.calculate([row], [{'set': SET, 'id': t['id'], 'suite': 'route'}], 1)
            self.assertEqual(metrics['route_accuracy'], 0)
            self.assertEqual(work.route_bodies, [])

    def test_issue_check_retries_infrastructure_failure(self):
        work = FakeWork()
        work.check = Mock(side_effect=[{'status': 'timed_out'}, work.check_result])
        fix = {'id': 'fix', 'suite': 'fix', 'work': 'w', 'draft': '林禾只惯用右手。', 'conflict_sentence': '林禾只惯用右手。'}
        row = run.run_task(work, route_task(context={'page': 'writing', 'issue_from': 'fix'}), '', task_lookup={'fix': fix})
        self.assertEqual(work.check.call_count, 2)
        self.assertEqual(len(row['initial_check_retries']), 1)
        self.assertEqual(len(work.route_bodies), 1)

    def wire_work(self, responses):
        work = run.Work.__new__(run.Work)
        work.ledger, work.base = None, '/api/projects/p'
        work.response = Mock(side_effect=responses)
        work.save = Mock()
        return work

    def test_every_4xx_is_terminal_even_with_retryable_error_code(self):
        for status in (400, 401, 403, 404, 409, 422, 429):
            with self.subTest(status=status):
                work = self.wire_work([httpx.Response(status, json={'error': {'code': 'provider_unavailable'}})])
                row = run.run_task(work, route_task(), '她把书放下。')
                self.assertEqual(work.response.call_count, 1)
                self.assertFalse(score.decide(row))
                self.assertEqual(row['execution_errors'], [f'route_http_{status}:provider_unavailable'])

    def test_route_5xx_timeout_and_network_error_retry_once(self):
        good = httpx.Response(200, json={'data': {'route': 'check_passage', 'source': 'model', 'unsure': True}})
        for first in (httpx.Response(503, json={'error': {'code': 'provider_unavailable'}}),
                      httpx.ReadTimeout('offline'), httpx.ConnectError('offline')):
            with self.subTest(first=type(first).__name__):
                work = self.wire_work([first, good])
                row = run.run_task(work, route_task(), '她把书放下。')
                self.assertTrue(score.decide(row))
                self.assertEqual(len(row['route_attempts']), 2)
                self.assertGreaterEqual(row['route_seconds'], 0)

    def test_route_double_failure_and_invalid_response_are_wrong(self):
        for responses, count in [
            ([httpx.Response(500, json={}), httpx.Response(500, json={})], 2),
            ([httpx.Response(200, json={'route': 'made_up', 'source': 'rule', 'unsure': False})], 1)]:
            work = self.wire_work(responses)
            row = run.run_task(work, route_task(), '她把书放下。')
            self.assertFalse(score.decide(row))
            self.assertEqual(work.response.call_count, count)

    def test_journal_persists_timeout_then_resume_replays_before_retry(self):
        work = run.Work.__new__(run.Work)
        work.base, work.ledger = '/api/projects/p', None
        work.journal, work.cursor, work.persist = [], 0, Mock()
        work.client = Mock()
        work.client.request.side_effect = [httpx.ReadTimeout('offline'),
            httpx.Response(200, json={'data': {'route': 'check_passage', 'source': 'rule', 'unsure': False}})]
        task = route_task(context={'page': 'overview'})
        row = run.new_record(task)
        # Simulate a crash after first attempt is checkpointed.
        def stop():
            if len(row.get('route_attempts', [])) == 1: raise KeyboardInterrupt()
        with self.assertRaises(KeyboardInterrupt): run.run_task(work, task, '', row, stop)
        self.assertEqual(work.journal[0]['status'], 503)
        work.cursor = 0
        run.run_task(work, task, '', row)
        self.assertTrue(score.decide(row))
        self.assertEqual(work.client.request.call_count, 2)
        self.assertEqual(len(row['route_attempts']), 2)
        self.assertEqual(work.cursor, 2)

    def test_non_json_gateway_error_retries_with_real_journal(self):
        work = run.Work.__new__(run.Work)
        work.base, work.ledger = '/api/projects/p', None
        work.journal, work.cursor, work.persist = [], 0, Mock()
        work.client = Mock()
        work.client.request.side_effect = [httpx.Response(502, text='<html>gateway unavailable</html>'),
            httpx.Response(200, json={'route': 'ask', 'source': 'model', 'unsure': False})]
        row = run.run_task(work, route_task(context={'page': 'overview'}, expected_route='ask'), '')
        self.assertTrue(score.decide(row))
        self.assertEqual(work.journal[0]['status'], 502)
        self.assertEqual(work.client.request.call_count, 2)

    def test_crash_after_response_before_attempt_preserves_measured_latency(self):
        work = run.Work.__new__(run.Work)
        work.base, work.ledger = '/api/projects/p', None
        work.journal, work.cursor = [], 0
        work.client = Mock()
        work.client.request.return_value = httpx.Response(200, json={'route': 'ask', 'source': 'model', 'unsure': False})
        def crash_after_response():
            if work.journal and 'status' in work.journal[-1]:
                raise KeyboardInterrupt()
        work.persist = crash_after_response
        task = route_task(context={'page': 'overview'}, expected_route='ask')
        row = run.new_record(task)
        with patch.object(run.time, 'perf_counter', side_effect=[100, 101, 105]), self.assertRaises(KeyboardInterrupt):
            run.run_task(work, task, '', row)
        self.assertEqual(row['route_attempts'], [])
        self.assertEqual(work.journal[0]['elapsed_seconds'], 4)
        work.persist, work.cursor = Mock(), 0
        run.run_task(work, task, '', row)
        self.assertEqual(row['route_seconds'], 4)
        self.assertTrue(score.decide(row))
        self.assertEqual(work.client.request.call_count, 1)

    def test_suggest_uses_ask_and_preserves_selection(self):
        work = FakeWork()
        task = suggest_task(selection='她把书放下。')
        row = run.run_task(work, task, '她把书放下。')
        self.assertEqual(work.assistant_bodies, [{'kind': 'ask', 'question': task['question'],
            'context': {'page': 'writing', 'selection': task['selection']}}])
        self.assertEqual(row['assistant_seconds'], 2)
        self.assertEqual(work.route_bodies, [])

    def test_three_grounded_suggest_types_use_exact_qa_material(self):
        for kind in ('thread_resolution', 'conflict_options', 'open_whereabouts'):
            row = run.new_record(suggest_task(kind))
            row['assistant'] = assistant_view()
            qa = copy.deepcopy(row)
            qa['task']['suite'] = 'qa'
            self.assertEqual(list(judge.questions(row)), list(judge.questions(qa)))
            citation = next(x for x in judge.questions(row) if x[0] == 'citation_support')
            self.assertEqual(citation[2]['sources'], [{'kind': 'fact', 'text': '仍未查明'}])

    def test_suggest_decline_missing_points_still_count(self):
        row = run.new_record(suggest_task())
        row['assistant'] = {**assistant_view(), 'answer': {'status': 'out_of_scope', 'sentences': []}}
        self.assertNotIn('point:0', [x[1] for x in judge.questions(row)])
        row['auto']['answer_status'] = 'out_of_scope'
        self.assertFalse(score.decide(row))
        self.assertEqual(a1c.calculate([row], [], 1)[1]['suggest_answer_points_recall'], 0)

    def test_creative_uses_registered_question_once_and_no_points_or_citations(self):
        row = run.new_record(suggest_task('creative_direction', answer_points=['ignored']))
        row['assistant'] = assistant_view()
        questions = list(judge.questions(row))
        self.assertEqual(sum(q[0] == 'suggest_invents_plot' for q in questions), 1)
        self.assertFalse(any(q[0] in ('qa_answer_points', 'citation_support') for q in questions))
        provider = Mock()
        provider._send.return_value = SimpleNamespace(payload={'verdict': 'yes', 'reason': 'offline'})
        j = judge.Judge(provider, 'fake')
        name, key, material, choices = questions[0]
        j.ask(row, name, key, material, choices)
        content = provider._send.call_args.args[0]['messages'][0]['content']
        self.assertIn(thresholds.PRE_REGISTRATION['judging']['suggest_invents_plot'], content)
        self.assertEqual(choices, ['yes', 'no'])

    def test_suggest_citation_judging_carries_the_advice_clause_note_and_qa_does_not(self):
        # SPEC addendum 14: on suggest tasks only, "可以从这一段接上" is the advice, not a claim about the story.
        provider = Mock()
        provider._send.return_value = SimpleNamespace(payload={'verdict': 'supported', 'reason': 'offline'})
        j = judge.Judge(provider, 'fake')
        note = thresholds.PRE_REGISTRATION['judging']['suggest_advice_clause']
        suggest = run.new_record(suggest_task())
        suggest['assistant'] = assistant_view()
        name, key, material, choices = next(q for q in judge.questions(suggest) if q[0] == 'citation_support')
        j.ask(suggest, name, key, material, choices)
        body = provider._send.call_args.args[0]
        self.assertIn(note, body['messages'][0]['content'])
        self.assertIn('addendum 14', body['messages'][1]['content'])
        qa = {**suggest, 'task': {**suggest['task'], 'suite': 'qa'}}
        j.ask(qa, name, key, material, choices)
        body = provider._send.call_args.args[0]
        self.assertNotIn(note, body['messages'][0]['content'])
        self.assertNotIn('addendum 14', body['messages'][1]['content'])

    def test_suggest_process_note_and_coverage_judging_matches_qa(self):
        row = run.new_record(suggest_task(forbidden_claims=[]))
        row['assistant'] = assistant_view()
        row['assistant']['answer']['note'] = '查过第一章。'
        row['assistant']['steps'] = [
            {'kind': 'say', 'round': 1, 'summary': '我会读第一章。'},
            {'kind': 'tool', 'round': 1, 'tool_name': 'read_chapter', 'arguments': {'chapter_number': 1}}]
        qa = copy.deepcopy(row); qa['task']['suite'] = 'qa'
        self.assertEqual(list(judge.questions(row)), list(judge.questions(qa)))
        self.assertIn('process_matches_action', [q[0] for q in judge.questions(row)])

    def test_suggest_enters_exactly_seven_legacy_checks(self):
        qa = {'id': 'qa', 'suite': 'qa', 'qa_type': 'answerable_single', 'answer_points': [],
              'forbidden_claims': [], 'deep': True}
        rows = []
        expected = [{'set': SET, 'id': 'qa', 'suite': 'qa'}]
        for n in (1, 2, 3):
            row = run.new_record(qa)
            row.update(set=SET, run_number=n, assistant=assistant_view())
            row['auto']['answer_status'] = 'answered'
            row['assistant']['answer']['note'] = '查过第一章。'
            row['assistant']['steps'] = [{'kind': 'tool', 'tool_name': 'read_chapter', 'arguments': {'chapter_number': 1}}]
            row['judgments'] = [{'question': 'citation_support', 'key': 'citation:0', 'verdict': 'supported'},
                {'question': 'process_matches_action', 'key': 'process', 'verdict': 'yes'},
                {'question': 'process_or_note_asserts_story', 'key': 'note', 'verdict': 'no'}]
            rows.append(row)
        old, _ = a1c.calculate(copy.deepcopy(rows), expected, 3)
        for n in (1, 2, 3):
            row = run.new_record(suggest_task('creative_direction'))
            row.update(set=SET, run_number=n, assistant=assistant_view())
            row['assistant'].update(elapsed_seconds=100, usage={'steps': 9},
                token_usage={'input_tokens': 1000000, 'output_tokens': 0},
                coverage={'not_checked': [supplemental.FORCED_FINISH_NOTE]})
            row['assistant']['answer']['note'] = '查过第一章。provider_timeout'
            row['judgments'] = [{'question': 'suggest_invents_plot', 'key': 'invents_plot', 'verdict': 'yes'},
                {'question': 'process_matches_action', 'key': 'process', 'verdict': 'no'},
                {'question': 'process_or_note_asserts_story', 'key': 'note', 'verdict': 'yes'}]
            rows.append(row)
        expected.append({'set': SET, 'id': 'suggest', 'suite': 'suggest'})
        new, _ = a1c.calculate(rows, expected, 3)
        seven = {'budget_compliance_rate', 'latency_p90_seconds', 'forced_finish_rate', 'internal_leak_rate',
                 'process_matches_action', 'process_or_note_asserts_story', 'coverage_claims_true_rate'}
        changed = {k for k, _, _ in thresholds._CHECKS if old[k] != new[k]}
        self.assertEqual(changed, seven)
        self.assertEqual(new['latency_p90_seconds'], 100)
        for k in seven - {'latency_p90_seconds'}: self.assertEqual(new[k], .5, k)
        self.assertEqual(new['pass3_rate'], 1)
        self.assertEqual(new['citation_support_rate'], 1)

    def test_citation_pool_weights_sentences_not_tasks_and_excludes_creative(self):
        rows = []
        for count, kind, supported in [(1, 'thread_resolution', True), (3, 'conflict_options', False),
                                        (10, 'creative_direction', True)]:
            row = run.new_record(suggest_task(kind, id=kind))
            row['assistant'] = assistant_view()
            row['judgments'] = [{'question': 'citation_support', 'key': f'citation:{i}',
                                 'verdict': 'supported' if supported else 'unsupported'} for i in range(count)]
            rows.append(row)
        metrics, _ = a1c.calculate(rows, [], 1)
        self.assertEqual(metrics['suggest_citation_support_rate'], .25)

    def test_new_metrics_pool_attempts_and_keep_route_out_of_old_checks(self):
        rows, expected = [], []
        for n in (1, 2, 3):
            r = run.new_record(route_task())
            r.update(set=SET, run_number=n, route_result={'route': 'check_passage' if n < 3 else 'ask',
                'source': 'rule' if n == 1 else 'model', 'unsure': n == 3}, route_seconds=n, route_cost_cny=n/100)
            # Poison values must not enter any legacy assistant metric.
            r['assistant'] = {**assistant_view(), 'elapsed_seconds': 999, 'usage': {'steps': 99}}
            r['judgments'] = [{'question': 'process_matches_action', 'key': 'bad', 'verdict': 'no'}]
            rows.append(r)
            s = run.new_record(suggest_task())
            s.update(set=SET, run_number=n, assistant=assistant_view())
            s['judgments'] = [{'question': 'qa_answer_points', 'key': 'point:0', 'verdict': 'stated' if n < 3 else 'missing'},
                {'question': 'citation_support', 'key': 'citation:0', 'verdict': 'supported' if n < 3 else 'unsupported'},
                {'question': 'process_matches_action', 'key': 'process', 'verdict': 'yes'}]
            rows.append(s)
            c = run.new_record(suggest_task('creative_direction', id='creative'))
            c.update(set=SET, run_number=n, assistant=assistant_view())
            c['judgments'] = [{'question': 'suggest_invents_plot', 'key': 'invents_plot', 'verdict': 'yes' if n == 1 else 'no'}]
            rows.append(c)
        expected = [{'set': SET, 'id': r['task']['id'], 'suite': r['task']['suite']} for r in rows[:3]]
        m, extra = a1c.calculate(rows, expected, 3)
        self.assertEqual(m['route_accuracy'], 2/3)
        self.assertEqual(m['suggest_citation_support_rate'], 2/3)
        self.assertEqual(extra['suggest_answer_points_recall'], 2/3)
        self.assertEqual(extra['suggest_invents_plot_rate'], 1/3)
        self.assertEqual(extra['route_rule_rate'], 1/3)
        self.assertEqual(extra['route_unsure_rate'], 1/3)
        self.assertEqual(extra['route_cost_cny_total'], .06)
        self.assertEqual(extra['route_latency_seconds_distribution']['max'], 3)
        self.assertEqual(m['process_matches_action'], 1)
        self.assertEqual(m['budget_compliance_rate'], 1)
        self.assertEqual(m['latency_p90_seconds'], 2)
        for key in ('qa_answerable_accuracy', 'citation_support_rate', 'pass3_rate'):
            self.assertIsNone(m[key])

    def test_historical_fourth_report_all_18_values_exactly_unchanged(self):
        path = run.ROOT / 'evaluation/assistant_a1/fixtures/fourth-rescored-metric-inputs.json'
        report = json.loads(path.read_text(encoding='utf-8'))
        old = copy.deepcopy(report['metrics'])
        self.assertEqual(len(old), 18)
        score.refresh(report)
        # A1c SPEC addendum 15 (2026-10-22) changes one value on purpose: the coverage checker split no 、-list, so a plan listed
        # beside chapter text ("查了第13章计划、郁采澈的事实、第12章正文") was checked as a claim of having read chapter 13.
        old['coverage_claims_true_rate'] = 0.9920634920634921
        self.assertEqual({k: report['metrics'][k] for k in old}, old)
        self.assertEqual(len(report['threshold_result']['checks']), 18)
        self.assertTrue(all(report['threshold_result']['checks'].values()))

    def test_fifth_set_context_adds_two_gates_and_markdown_rows(self):
        for sets, count in [([SET], 18), (['eval_set_a1c4_formal'], 18), (FIFTH, 20)]:
            report = {'protocol_version': 2, 'sets': sets, 'records': [], 'expected_cases': [],
                      'runs': 3, 'complete': False}
            score.refresh(report)
            self.assertEqual(len(report['threshold_result']['checks']), count)
            text = score.markdown(report)
            self.assertEqual('| route_accuracy |' in text, count == 20)
            self.assertEqual('| suggest_citation_support_rate |' in text, count == 20)
        # The route-only retest is judged on route_accuracy alone (A1c SPEC addendum 16, item 45).
        report = {'protocol_version': 2, 'sets': list(run.A1C_FORMAL_SETS), 'records': [], 'expected_cases': [], 'runs': 3, 'complete': False}
        score.refresh(report)
        self.assertEqual(list(report['threshold_result']['checks']), ['route_accuracy'])

    def test_audit_all_wrong_seeded_right_includes_route_and_suggest(self):
        rows = []
        for n in range(20):
            for task in (route_task(id=f'r{n}'), suggest_task(id=f's{n}')):
                row = run.new_record(task)
                row.update(set=SET, run_number=1, correct=n != 0, audit_wrong=n == 0,
                           route_result={'route': 'check_passage'})
                rows.append(row)
        report = {'protocol_version': 2, 'sets': [SET], 'records': rows}
        audit = score.audit(report)
        self.assertEqual(audit, score.audit(report))
        self.assertEqual(audit['seeds'][SET], 20261016)
        self.assertEqual(len(audit['items']), 2 + 8)  # ceil(38 * .2)
        self.assertTrue({'r0', 's0'} <= {i['id'] for i in audit['items']})
        sampled = [i for i in audit['items'] if i['correct']]
        self.assertEqual({i['task']['suite'] for i in sampled}, {'route', 'suggest'})
        routed = next(i for i in sampled if i['task']['suite'] == 'route')
        self.assertEqual(routed['expected_route'], 'check_passage')
        self.assertEqual(routed['route_result'], {'route': 'check_passage'})

    def test_formal_only_runs_pair_and_dirty_guards_never_read_sealed_data(self):
        for options, error in [
            (['--set', PAIR, '--only', 'x'], 'formal_only'),
            (['--set', PAIR, '--runs', '1'], 'three_runs'),
            (['--set', f'{PAIR},{FIFTH[1]}', '--runs', '3'], 'both_sets')]:
            with tempfile.TemporaryDirectory() as d, patch.object(run, 'git', return_value=''), \
                    patch.object(run, 'validate_set'), patch.object(run, 'load_set', side_effect=AssertionError('sealed')):
                with self.assertRaisesRegex(ValueError, error):
                    run.preflight(args(*options), SimpleNamespace(available=True, model='deepseek-flash', assistant_model='deepseek-flash', model_for=lambda role: 'deepseek-flash'), Path(d))
        with patch.object(run, 'git', return_value=' M evaluation/assistant_a1/run.py'), \
                self.assertRaisesRegex(ValueError, 'dirty'):
            run.preflight(args('--set', PAIR, '--runs', '3'), None)

    def test_route_ledger_classification_budget_and_estimate(self):
        ledger = run.Ledger(1, (2, 8), (9, 27))
        ledger.phase = 'route'
        reservation = ledger.reserve({'model': 'fake', 'max_tokens': 100})
        ledger.settle(reservation, {'usage': {'prompt_tokens': 1000, 'completion_tokens': 100}})
        self.assertEqual(ledger.totals()['route']['cost_cny'], .0028)
        self.assertEqual(ledger.totals()['assistant']['cost_cny'], 0)
        ledger.max_cny = ledger.spent
        with self.assertRaises(run.ProviderDispatchDenied): ledger.reserve({'max_tokens': 100})
        estimate = run.budget_estimate({SET: {'works': [{'key': 'w', 'source': '# 一\n文字'}],
            'tasks': [route_task(), suggest_task()]}}, args('--runs', '3'))
        self.assertEqual(estimate['route_calls'], 3)
        self.assertEqual(estimate['suggest_tasks'], 3)
        self.assertAlmostEqual(estimate['route_estimated_cny'], .0084)
        self.assertGreater(estimate['estimated_cny'], 1.8)

    def test_three_pass_execute_resume_and_budget_stop_with_fake_backend(self):
        data = {'manifest_sha256': 'invented', 'works': [{'key': 'w', 'title': 'test',
            'source': '# 第一章\n仅测试。', 'shared_draft': {'body': '她把书放下。'}}],
            'tasks': [route_task(), suggest_task()]}
        provider = SimpleNamespace(assistant_model='deepseek-flash', model='deepseek-flash', model_for=lambda role: 'deepseek-flash')
        fake_judge = Mock()
        fake_judge.ask.side_effect = lambda row, name, key, material, choices: {
            'verdict': 'supported' if name == 'citation_support' else 'absent' if key.startswith('forbidden:') else 'stated' if name == 'qa_answer_points' else 'no',
            'reason': 'offline'}
        with tempfile.TemporaryDirectory() as d, patch.object(run, 'Work', FakeWork), \
                patch.object(run, 'git', return_value='test-commit'), contextlib.redirect_stdout(io.StringIO()):
            options = args('--runs', '3', '--max-cny', '.2')
            out = run.paths(SET, options.run_id, Path(d))
            first = run.execute(options, data, provider, fake_judge, run.Ledger(.2, (2, 8), (9, 27)), out)
            self.assertFalse(first['complete'])
            self.assertEqual(first['stop_reason'], 'budget_stop')
            self.assertEqual(len(first['records']), 1)
            options.resume, options.max_cny = True, 10
            result = run.execute(options, data, provider, fake_judge, run.Ledger(10, (2, 8), (9, 27)), out)
            self.assertTrue(result['complete'])
            self.assertEqual(len(result['records']), 6)
            self.assertEqual(len({(r['task']['id'], r['run_number']) for r in result['records']}), 6)
            self.assertEqual(result['metrics']['route_accuracy'], 1)
            self.assertEqual(result['metrics']['suggest_citation_support_rate'], 1)
            self.assertTrue(all(len(r['route_attempts']) == 1 for r in result['records'] if r['task']['suite'] == 'route'))
            self.assertEqual(result['time_band_estimated_cny'], 0)

    def test_support_items_prepare_issue_from_and_are_not_run(self):
        # A1c SPEC addendum 16: the retest copies the FIX items its route items point at, marked support.
        data = {'manifest_sha256': 'invented', 'works': [{'key': 'w', 'title': 'test',
            'source': '# 第一章\n仅测试。', 'shared_draft': {'body': '她把书放下。'}}],
            'tasks': [route_task(), {'id': 'fix-support', 'work': 'w', 'suite': 'fix', 'support': True, 'draft': '她把书放下。',
                                     'conflict_sentence': '她把书放下。', 'category': 'x', 'evidence_chapters': [], 'fix_idea': 'x'}]}
        provider = SimpleNamespace(assistant_model='deepseek-flash', model='deepseek-flash', model_for=lambda role: 'deepseek-flash')
        with tempfile.TemporaryDirectory() as d, patch.object(run, 'Work', FakeWork),                 patch.object(run, 'git', return_value='test-commit'), contextlib.redirect_stdout(io.StringIO()):
            options = args('--runs', '1')
            result = run.execute(options, data, provider, Mock(), run.Ledger(10, (2, 8), (9, 27)), run.paths(SET, options.run_id, Path(d)))
        self.assertEqual([r['task']['id'] for r in result['records']], [route_task()['id']])
        self.assertEqual(result['expected_tasks'], 1)
        estimate = run.budget_estimate({SET: data}, args('--runs', '3'))
        self.assertEqual(estimate['route_calls'], 3)

    def test_dev_checker_and_mutation_rejections(self):
        self.assertEqual(check.validate()['status'], 'PASS')
        import shutil
        with tempfile.TemporaryDirectory() as d:
            target = Path(d) / 'dev'
            shutil.copytree(check.ROOT, target)
            original = json.loads((target / 'tasks.json').read_text(encoding='utf-8'))
            for mutation, expected in [
                (lambda t: t['context'].update(selection='不在共享草稿中的句子。'), ':selection'),
                (lambda t: t['context'].update(page='plan', issue_from='a1cyd-w02-fix-01'), ':writing_context'),
                (lambda t: t.update(also_acceptable=['ask', 'recap']), ':also_acceptable'),
                (lambda t: t.update(expected_route='recap'), ':route_distribution'),
                (lambda t: t.update(input='短'), ':input')]:
                data = copy.deepcopy(original)
                task = next(t for t in data['tasks'] if t['id'] == 'a1cyd-w01-route-07')
                mutation(task)
                (target / 'tasks.json').write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
                errors = check.validate(target)['errors']
                self.assertTrue(any(expected in e for e in errors), errors)
                self.assertIn('manifest:tasks.json', errors)


if __name__ == '__main__':
    unittest.main()


class CoverageListItemsTests(unittest.TestCase):
    """A1c SPEC addendum 15: each item of a 、-list in the note is its own claim."""
    @staticmethod
    def view(note, *searches):
        steps = [{'kind': 'tool', 'tool_name': 'search_text', 'args_json': json.dumps({'query': 'x', 'chapter_from': lo, 'chapter_to': hi})}
                 for lo, hi in searches]
        steps.append({'kind': 'tool', 'tool_name': 'get_plans', 'args_json': json.dumps({'chapter_number': 13})})
        return {'max_chapter': 12, 'steps': steps, 'answer': {'note': note}}

    def test_a_plan_listed_beside_chapter_text_is_not_a_claim_about_that_chapters_text(self):
        self.assertEqual(supplemental.coverage_claims(self.view('查过第 13 章计划、郁采澈的事实、第 10 至 12 章正文。', (10, 12))), [True])

    def test_untrue_text_is_still_caught_beside_a_listed_plan(self):
        self.assertEqual(supplemental.coverage_claims(self.view('查过第13到30章正文、第31章计划。', (13, 30))), [True])
        self.assertEqual(supplemental.coverage_claims(self.view('查过第 9 章正文、第 13 章计划。', (10, 12))), [False])
        # "第3、第4章" stays one item (the 、 follows a bare number).
        self.assertEqual(supplemental.ITEM_BREAK.split('查过第3、第4章正文、第13章计划'), ['查过第3、第4章正文', '第13章计划'])
