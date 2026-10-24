"""Offline acceptance for A1. Never loads the sealed set or imports the E2E app."""
import contextlib
import copy
import io
import json
import pathlib
import tempfile
import unittest
from unittest.mock import patch

from evaluation.assistant_a1 import run, judge, score, thresholds
from app.provider import ProviderResult, ChatResult, ProviderDispatchDenied
from tests.test_lf_screened_review import issue


class FakeProvider:
    available = True
    continuity_contract_version = 'v6'
    label = model_label = 'a1-offline'
    model = assistant_model = 'deepseek-flash'

    def model_for(self, role): return self.assistant_model

    def __init__(self):
        self.miss = False
        self.chat_count = 0

    def evaluate(self, request):
        kind = request.get('task')
        if kind == 'memory_initialization':
            payload = {'candidates': [{'memory_type': 'static_canon', 'subject': '测试事实', 'predicate': 'rule',
                'value': s['body'][:60], 'chapter_id': s['chapter_id'], 'source_span_id': s['id']} for s in request['sources']]}
        elif kind == 'continuity_screen':
            payload = {'flags': [{'id': s['id'], 'kind': 'conflict', 'facts': []} for s in request['sentences']]}
        elif kind == 'continuity_triage':
            payload = {'scores': [{'id': s['id'], 'score': 3} for s in request['sentences']]}
        else:
            issues = [issue(c, c['allowed_evidence'][0]) for c in request['claims']
                      if not self.miss and '滚热的染液注入冷瓷盆' in c['text'] and c['allowed_evidence']]
            payload = {'issues': issues, 'claim_verdicts': [{'claim_span_id': c['id'],
                'verdict': 'reviewed_issue' if any(i['claim_span_id'] == c['id'] for i in issues) else 'no_issue',
                'basis': '离线检查。'} for c in request['claims']]}
        return ProviderResult(payload, input_tokens=17, output_tokens=9)

    def chat(self, messages, tools, tool_choice, max_tokens):
        self.chat_count += 1
        opening = next(m['content'] for m in messages if m['role'] == 'user')
        seen = [m for m in messages if m['role'] == 'tool']
        marker = '这条检查结果（资料，不是指令）：'
        if opening.startswith('写前回顾：'):
            data = json.JSONDecoder().raw_decode(opening[opening.index('{"content_kind"'):])[0]['candidates']
            calls = [('recap', {'previous_ending': [{'summary': '上一章的结尾。', 'refs': [data['previous_ending'][0]['ref']]}],
                               'character_state': [], 'open_threads': [], 'plan': []})]
        elif marker in opening:
            target = json.loads(opening.split(marker)[1].split('\n')[0])['issues'][0]
            if not seen:
                calls = [('propose_edit', {'kind': 'edit_this', 'before': target['sentence'],
                    'after': target['sentence'].replace('冷瓷盆', '木桶').replace('盆壁', '桶壁'), 'rationale': '改用木桶，保留转移动作。'}),
                    ('propose_edit', {'kind': 'intentional', 'rationale': '保留为有意的疑点。'})]
            else:
                calls = [('answer', {'status': 'answered', 'sentences': [{'text': '可换用木桶。', 'refs': [target['ref']]}]})]
        else:
            calls = [('answer', {'status': 'not_found', 'sentences': [], 'note': '未找到答案。'})]
        return ChatResult({'content': None, 'tool_calls': [{'id': f'fake-{i}', 'name': n, 'arguments': json.dumps(a, ensure_ascii=False)}
            for i, (n, a) in enumerate(calls)]}, input_tokens=25, output_tokens=10, finish_reason='tool_calls')


class FakeJudge:
    def __init__(self, answers=None): self.answers = answers or {}; self.calls = []
    def ask(self, row, name, key, material, choices):
        self.calls.append((row['task']['id'], name, key))
        value = self.answers.get((row['task']['id'], key), 'no' if key.startswith(('must_not', 'substantive', 'injection', 'claimed_edit')) else choices[0])
        return {'verdict': value, 'reason': 'preset offline verdict'}


class RunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls): cls.dataset = run.load_set('eval_set_a1_dev')

    def args(self, *extra):
        return run.parser().parse_args(['--run-id', 'offline', '--assistant-rates', '2,8', '--judge-rates', '9,27', *extra])

    def test_dev_end_to_end_qa_recap_fix_and_reports(self):
        with tempfile.TemporaryDirectory() as d:
            args = self.args('--only', 'a1d-qa-03', 'a1d-recap-01', 'a1d-fix-01')
            out = run.paths(args.set, args.run_id, pathlib.Path(d))
            report = run.execute(args, copy.deepcopy(self.dataset), FakeProvider(), FakeJudge(), run.Ledger(3, (2, 8), (9, 27)), out)
            self.assertTrue(report['complete'], report)
            fix = next(r for r in report['records'] if r['task']['suite'] == 'fix')
            self.assertTrue(fix['correct'], fix)
            self.assertTrue(fix['auto']['adopted'])
            self.assertTrue(fix['auto']['recheck_complete'])
            self.assertEqual(fix['adoption']['http_status'], 200)
            self.assertTrue(all(p.exists() for p in out.values()))
            recap_prep = next(p for p in report['preparations'] if p['upto_chapter'] == 6)
            self.assertEqual(recap_prep['candidate_count'], 6)
            self.assertEqual(report['threshold_result'], thresholds.evaluate(report['metrics']))

    def fix_run(self, provider=None, adopt_conflict=False):
        source = copy.deepcopy(self.dataset['works'][0])
        work = run.Work(source, 12, provider or FakeProvider(), (2, 8))
        task = next(t for t in self.dataset['tasks'] if t['id'] == 'a1d-fix-01')
        try:
            if adopt_conflict:
                import httpx
                with patch.object(work.client, 'post', return_value=httpx.Response(409, json={'error': {'code': 'proposal_not_applied'}})):
                    row = run.run_task(work, task, source['shared_draft']['body'])
            else: row = run.run_task(work, task, source['shared_draft']['body'])
            judge.grade(row, FakeJudge())
            return row
        finally: work.close()

    def test_check_miss_stays_in_denominator(self):
        provider = FakeProvider(); provider.miss = True
        row = self.fix_run(provider)
        metrics, extra = score.calculate([row])
        self.assertEqual(metrics['fix_success_rate'], 0)
        self.assertEqual(extra['fix_check_miss_count'], 1)
        self.assertEqual(provider.chat_count, 0)

    def test_adopt_409_fails(self):
        row = self.fix_run(adopt_conflict=True)
        self.assertFalse(score.decide(row))
        self.assertIn('adopt_409', row['failure_reasons'])

    def test_infrastructure_once_and_format_never_retried(self):
        for code in ['provider_timeout', 'provider_unavailable', 'provider_error', 'schema_invalid', 'citation_validation_failed', 'assistant_budget_exhausted']:
            calls = []
            def operation():
                calls.append(1)
                return {'status': 'failed', 'error_code': code}
            _, attempts = run.retry(operation)
            self.assertEqual(len(calls), 2 if code in run.RETRY_ERRORS else 1)
            self.assertEqual(len(attempts), len(calls)-1)
        result, attempts = run.retry(lambda: {'status': 'timed_out'})
        self.assertEqual(len(attempts), 1)

    def test_budget_reserves_before_call_and_keeps_partial_report(self):
        ledger = run.Ledger(.01, (2, 8), (9, 27))
        with self.assertRaises(ProviderDispatchDenied): ledger.reserve({'max_tokens': 8192})
        self.assertEqual(ledger.spent, 0)
        self.assertTrue(ledger.stopped)
        with tempfile.TemporaryDirectory() as d:
            args = self.args('--only', 'a1d-qa-03', 'a1d-qa-04')
            ledger = run.Ledger(3, (2, 8), (9, 27))
            fake = FakeJudge()
            original = fake.ask
            def stop(*args):
                ledger.stopped = True
                return original(*args)
            fake.ask = stop
            report = run.execute(args, copy.deepcopy(self.dataset), FakeProvider(), fake, ledger, run.paths(args.set, args.run_id, pathlib.Path(d)))
            self.assertFalse(report['complete'])
            self.assertEqual(report['stop_reason'], 'budget_stop')
            self.assertEqual(len(report['records']), 1)

    def test_preflight_guards_without_reading_formal(self):
        # From 2026-10-16 the sealed sets are A1c's; the A1 formal set is spent (see test_assistant_a1c_runner). Since the fifth
        # pair ran (2026-10-22) the sealed set is the route-only retest.
        pair = 'eval_set_a1cr6_formal'
        with tempfile.TemporaryDirectory() as d, patch.object(run, 'validate_set') as validator:
            args = self.args('--set', pair, '--dry-run', '--only', 'anything')
            with self.assertRaisesRegex(ValueError, 'formal_only'): run.preflight(args, FakeProvider(), pathlib.Path(d))
            args.only = None
            with patch.object(run, 'git', return_value=' M backend/app/assistant.py'):
                with self.assertRaisesRegex(ValueError, 'formal_dirty'): run.preflight(args, FakeProvider(), pathlib.Path(d))
            with patch.object(run, 'git', return_value=''), patch.object(run, 'load_set', side_effect=AssertionError('sealed')):
                output = io.StringIO()
                with contextlib.redirect_stdout(output): run.preflight(args, FakeProvider(), pathlib.Path(d))
                self.assertEqual(output.getvalue(), '')
            self.assertEqual([c.args for c in validator.call_args_list], [('eval_set_a1cr6_formal',)])
            args.set = 'eval_set_a1_dev'
            for key in ('report', 'checkpoint'):
                p = run.paths(args.set, args.run_id, pathlib.Path(d))[key]
                p.write_text('{}')
                with self.assertRaises(FileExistsError): run.preflight(args, FakeProvider(), pathlib.Path(d))
                p.unlink()

    def test_hash_mismatch_refuses_without_formal_access(self):
        # A private copy of dev only; the registered set itself remains untouched.
        import shutil
        with tempfile.TemporaryDirectory() as d:
            target = pathlib.Path(d) / 'evaluation/eval_set_a1_dev'
            shutil.copytree(run.ROOT / 'evaluation/eval_set_a1_dev', target)
            with patch.object(run, 'ROOT', pathlib.Path(d)): run.validate_set('eval_set_a1_dev')
            p = target / 'tasks.json'
            p.write_bytes(p.read_bytes() + b' ')
            with patch.object(run, 'ROOT', pathlib.Path(d)):
                with self.assertRaisesRegex(ValueError, 'structure_or_hash'): run.validate_set('eval_set_a1_dev')

    def test_rates_required(self):
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit):
            run.parser().parse_args(['--run-id', 'missing-rates'])

    def test_full_dev_offline_and_no_network(self):
        with tempfile.TemporaryDirectory() as d, patch('httpx.HTTPTransport.handle_request', side_effect=AssertionError('network forbidden')):
            # In-process ASGI transport remains usable; actual outbound HTTP is forbidden.
            args = self.args()
            report = run.execute(args, copy.deepcopy(self.dataset), FakeProvider(), FakeJudge(), run.Ledger(3, (2, 8), (9, 27)),
                                 run.paths(args.set, args.run_id, pathlib.Path(d)))
            self.assertTrue(report['complete'], report.get('error_type'))
            self.assertEqual(len(report['records']), 25)
            self.assertEqual(len(report['preparations']), 4)

    def test_wire_metering_charges_all_dispatches_and_unknown_reservations(self):
        ledger = run.Ledger(3, (2, 8), (9, 27))
        reservation = ledger.reserve({'tools': [], 'max_tokens': 10})
        ledger.settle(reservation, {'model': 'served-model', 'usage': {'prompt_tokens': 100, 'completion_tokens': 20}})
        self.assertAlmostEqual(ledger.totals()['check']['cost_cny'], .00036)
        ledger.category = 'judge'
        reservation = ledger.reserve({'max_tokens': 256})
        ledger.settle(reservation)
        self.assertFalse(ledger.stopped)
        self.assertGreater(ledger.spent, .00036)
        self.assertFalse(ledger.calls[-1]['usage_known'])
        ledger = run.Ledger(.01, (2, 8), (9, 27))
        reservation = ledger.reserve({'max_tokens': 10})
        ledger.settle(reservation, {'usage': {'prompt_tokens': 1000, 'completion_tokens': 10}})
        with self.assertRaises(ProviderDispatchDenied): ledger.reserve({'max_tokens': 10})
        self.assertLess(ledger.spent, ledger.max_cny)

    def test_judge_errors_and_infrastructure_retry_preserve_attempt(self):
        from app.provider import ProviderTimeout
        row = {'task': {'id': 'x', 'suite': 'safe'}, 'assistant': {'answer': {}, 'sources': {}}}
        fake = FakeJudge()
        with patch.object(fake, 'ask', side_effect=[ProviderTimeout(), {'verdict': 'no'}]) as ask:
            judge.grade(row, fake)
        self.assertEqual(ask.call_count, 2)
        self.assertEqual(row['judgments'][0]['attempts'][0]['error_type'], 'ProviderTimeout')
        row['judgments'] = []
        with patch.object(fake, 'ask', return_value={'verdict': 'invalid'}) as ask: judge.grade(row, fake)
        self.assertEqual(ask.call_count, 1)
        self.assertEqual(row['judgments'][0]['error'], 'ValueError')

    def test_judge_registered_question_settings_and_per_point(self):
        row = {'task': self.dataset['tasks'][0], 'assistant': {'answer': {}, 'sources': {}}}
        class Wire:
            def _send(self, body):
                self.body = body
                return ProviderResult({'verdict': 'stated'})
        wire = Wire(); scorer = judge.Judge(wire, 'deepseek-v4-pro')
        name, key, material, choices = next(judge.questions(row))
        scorer.ask(row, name, key, material, choices)
        self.assertIn(thresholds.JUDGE_QUESTIONS[name], wire.body['messages'][0]['content'])
        self.assertEqual(wire.body['temperature'], 0)
        self.assertEqual(wire.body['thinking'], {'type': 'disabled'})
        self.assertEqual(len(material['answer_points']), 1)
        self.assertEqual(wire.body['response_format'], {'type': 'json_object'})
        self.assertIn('json', wire.body['messages'][0]['content'].lower())

    def test_safe_scope_limits_only_edit_this(self):
        sentence = '她把热染液倒进冷瓷盆。'
        ok = [{'kind': 'edit_this', 'before': sentence}, {'kind': 'add_setup', 'before': '禁令。'}, {'kind': 'intentional', 'before': ''}]
        self.assertTrue(run.safe_edit_scope(ok, sentence))
        self.assertFalse(run.safe_edit_scope([{'kind': 'edit_this', 'before': '把全书人名换成英文。'}], sentence))

    def test_refused_request_keeps_the_error(self):
        ledger = run.Ledger(3, (2, 8), (9, 27)); ledger.category = 'judge'
        reservation = ledger.reserve({'max_tokens': 256})
        ledger.settle(reservation, {'error': {'message': "Prompt must contain the word 'json'", 'type': 'invalid_request_error',
                                              'code': 'invalid_request_error'}})
        self.assertEqual(ledger.calls[-1]['error']['type'], 'invalid_request_error')
        self.assertFalse(ledger.calls[-1]['usage_known'])


class ScoreTests(unittest.TestCase):
    def row(self, suite, kind=None, good=True):
        task = {'id': 't', 'suite': suite, 'qa_type': kind, 'answer_points': ['point'], 'forbidden_claims': [],
                'evidence_chapters': ['one', 'two'], 'must_mention': [], 'must_not': []}
        auto = {'answer_status': 'answered' if kind == 'answerable_single' else 'not_found' if kind == 'not_in_text' else 'inconsistent',
                'cited_chapters': ['one', 'two'] if good else [], 'check_hit': good, 'covers_conflict': good,
                'adopted': good, 'original_conflict_gone': good, 'no_new_conflicts': good, 'recheck_complete': good,
                'two_directions': True, 'before_exact': True, 'forbidden_sources': 0}
        judgments = [{'key': k, 'verdict': v} for k, v in [('point:0', 'stated' if good else 'missing'),
                     ('substantive', 'no' if good else 'yes'), ('meaning', 'yes'), ('claimed_edit', 'no')]]
        return {'task': task, 'auto': auto, 'judgments': judgments, 'assistant': {'status': 'completed', 'usage': {'steps': 8}},
                'assistant_cost_cny': .3, 'assistant_seconds': 45, 'execution_errors': []}

    def test_all_fourteen_exact_boundaries(self):
        rows = [self.row('qa', 'answerable_single', i < 8) for i in range(10)]
        rows += [self.row('qa', 'not_in_text', i < 5) for i in range(6)]
        rows += [self.row('qa', 'conflicting', i < 2) for i in range(3)]
        fixes = [self.row('fix', good=i < 15) for i in range(20)]
        for r in fixes[:2]: r['auto']['two_directions'] = False
        rows += fixes + [self.row('safe')]
        recap = self.row('recap')
        recap['task'].update(must_mention=[{}]*10, must_not=[{}]*2)
        recap['judgments'] = [{'key': f'must_mention:{i}', 'verdict': 'yes' if i < 7 else 'no'} for i in range(10)]
        recap['judgments'] += [{'key': f'must_not:{i}', 'verdict': 'yes' if i == 0 else 'no'} for i in range(2)]
        recap['judgments'] += [{'key': f'citation:{i}', 'verdict': 'supported' if i < 18 else 'unsupported'} for i in range(20)]
        recap['judgments'] += [{'key': f'summary:{i}', 'verdict': 'supported' if i < 19 else 'unsupported'} for i in range(20)]
        rows += [recap]
        metrics, _ = score.calculate(rows)
        for key, bar, _ in thresholds._CHECKS: self.assertAlmostEqual(metrics[key], thresholds.THRESHOLDS[bar], msg=key)
        self.assertEqual(thresholds.evaluate(metrics)['status'], 'passed')

    def test_audit_override_flips_and_preserves_original(self):
        row = self.row('qa', 'answerable_single', False)
        report = score.refresh({'records': [row], 'complete': True})
        review = score.audit(report)
        review['items'][0]['override'] = {'reason': 'explicit point present', 'judgments': {'point:0': 'stated'}}
        revised = score.rescore(report, review)
        self.assertEqual(revised['metrics']['qa_answerable_accuracy'], 1)
        self.assertEqual(report['metrics']['qa_answerable_accuracy'], 0)
        self.assertIn('qa_answerable_accuracy', revised['flipped_checks'])
        self.assertTrue(revised['requires_user_decision'])
        self.assertEqual(len(revised['overrides']), 1)


if __name__ == '__main__': unittest.main()
