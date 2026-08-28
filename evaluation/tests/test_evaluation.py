from __future__ import annotations

import copy
import hashlib
import json
import pathlib
import sqlite3
import tempfile
import unittest

from evaluation.metrics import aggregate, prediction_for_target, stability
from evaluation.run_eval import ApiResponseScanner, EVALUATION_FIXTURE_MODE, FormalCheckpoint, assert_manifest_approved, assert_outputs_safe, bad_case, build_run_config, execute_formal_run, repeat_case, run_case, runner_account_name, source_hashes_for_config
from evaluation.validate_eval_set import load_cases, validate_case_set
from evaluation.validate_eval_set_v2_candidate import load_candidate, validate_candidate_case_set, validate_candidate_manifest, validate_semantic_review
from evaluation.validate_eval_set_v2 import validate_formal_freeze
from evaluation.validate_eval_set_v3 import validate_formal_freeze as validate_v3_formal_freeze
from evaluation.validate_eval_set_v4 import validate_formal_freeze as validate_v4_formal_freeze
from evaluation.validate_eval_set_v4_candidate import load_v4_candidate, prior_decision_signature, validate_v4_candidate_case_set, validate_v4_candidate_manifest, validate_v4_corpus_memory_types, validate_v4_semantic_review
from evaluation.post_run_integrity import validate_retained_integrity
from evaluation.validate_release_bundle import validate_release_bundle
from evaluation.validate_eval_set_v3_candidate import load_v3_candidate, validate_v3_candidate_case_set, validate_v3_candidate_manifest, validate_v3_semantic_review
from evaluation.v2_fixture_loader import V4_CORPUS_PATHS, fixture_runtime, load_corpus, load_fixture
from evaluation.v2_fixture_preflight import EmptyIssueProvider, preflight_candidate, preflight_v3_candidate, preflight_v4_candidate
from evaluation.scan_v2_fixtures import scan as scan_v2_fixtures

from fastapi.testclient import TestClient
from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult


class EvaluationUtilityTests(unittest.TestCase):
    def _synthetic_retained_integrity(self, root: pathlib.Path) -> pathlib.Path:
        artifact_root = root / 'evaluation' / 'results'
        artifact_root.mkdir(parents=True)
        artifacts = []
        for index in range(7):
            path = artifact_root / f'synthetic-result-{index}.json'
            path.write_text(json.dumps({'index': index}, separators=(',', ':')), encoding='utf-8')
            artifacts.append({'path': path.relative_to(root).as_posix(), 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size})
        workspace_root = root / 'evaluation' / 'fixture-workspaces' / 'synthetic'
        sqlite_files = []
        for index in range(15):
            path = workspace_root / f'{index:024x}' / 'runtime' / 'data' / 'demo.sqlite3'
            path.parent.mkdir(parents=True)
            connection = sqlite3.connect(path)
            try:
                connection.execute('CREATE TABLE v2_runs(status TEXT NOT NULL)')
                connection.execute("INSERT INTO v2_runs(status) VALUES('completed')")
                connection.commit()
            finally:
                connection.close()
            sqlite_files.append({'workspace_key': f'{index:024x}', 'sha256': hashlib.sha256(path.read_bytes()).hexdigest(), 'size': path.stat().st_size, 'run_status': {'completed': 1}})
        payload = {
            'schema_version': 'scc-evaluation-post-run-integrity-v1',
            'evaluation': 'synthetic-strict-validator-contract',
            'integrity_status': 'retained_baseline',
            'raw_provider_content_retained': False,
            'retained_artifacts': {'count': 7, 'files': artifacts},
            'fixture_workspaces': {'root': 'evaluation/fixture-workspaces/synthetic', 'sqlite_count': 15, 'sqlite_files': sqlite_files, 'run_status_totals': {'completed': 15}},
        }
        integrity_path = artifact_root / 'synthetic-integrity.json'
        integrity_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding='utf-8')
        return integrity_path

    def _fixture_config(self, temporary: pathlib.Path):
        repo = pathlib.Path(__file__).resolve().parents[2]
        return build_run_config(
            'scc-web-demo-eval-v2-fixture-contract',
            'evaluation/case_sets/eval-set-v2.json',
            'evaluation/manifests/eval-set-v2-manifest.json',
            'fixture-contract-output',
            str((temporary / 'checkpoint.json').relative_to(repo)).replace('\\', '/'),
        )

    def _v3_fixture_config(self, temporary: pathlib.Path):
        repo = pathlib.Path(__file__).resolve().parents[2]
        return build_run_config(
            'scc-web-demo-eval-v3-first-formal',
            'evaluation/case_sets/eval-set-v3.json',
            'evaluation/manifests/eval-set-v3-manifest.json',
            'eval-v3-first-formal',
            str((temporary / 'eval-v3-first-formal-checkpoint.json').relative_to(repo)).replace('\\', '/'),
        )

    def _v4_fixture_config(self, temporary: pathlib.Path):
        repo = pathlib.Path(__file__).resolve().parents[2]
        return build_run_config(
            'scc-web-demo-eval-v4-fixture-contract',
            'evaluation/case_sets/eval-set-v4.json',
            'evaluation/manifests/eval-set-v4-manifest.json',
            'fixture-v4-contract-output',
            str((temporary / 'checkpoint.json').relative_to(repo)).replace('\\', '/'),
        )

    def test_frozen_case_set_structure_and_hash_are_valid(self):
        result=validate_case_set()
        self.assertEqual((result['case_count'],result['class_counts'],result['nearby_distractor_cases']),(15,{'conflict':5,'no_conflict':5,'insufficient_evidence':5},5))

    def test_v2_candidate_structure_manifest_and_v1_separation_are_valid(self):
        result = validate_candidate_case_set()
        manifest = validate_candidate_manifest(result)
        self.assertEqual(result['status'], 'candidate_for_controller_review')
        self.assertEqual((result['case_count'], result['class_counts'], result['corpus_counts']), (15, {'conflict': 5, 'no_conflict': 5, 'insufficient_evidence': 5}, {'calibration_spire': 5, 'cloud_post': 5, 'crystal_archive': 5}))
        self.assertEqual((result['multiple_direct_evidence_cases'], result['relationship_knowledge_boundary_cases']), (2, 2))
        self.assertGreaterEqual(result['nearby_distractor_cases'], 5)
        self.assertEqual(manifest['status'], 'candidate_for_controller_review')
        self.assertTrue(validate_semantic_review()['manual_review_required'])

    def test_v3_candidate_structure_manifest_and_prior_overlap_guard_are_valid(self):
        result = validate_v3_candidate_case_set()
        manifest = validate_v3_candidate_manifest(result)
        self.assertEqual((result['case_count'], result['class_counts'], result['corpus_counts']), (15, {'conflict': 5, 'no_conflict': 5, 'insufficient_evidence': 5}, {'brine_station': 5, 'basalt_theatre': 5, 'stair_post': 5}))
        self.assertEqual((result['multiple_direct_evidence_cases'], result['nearby_distractor_cases']), (2, 10))
        self.assertEqual(manifest['status'], 'candidate_for_controller_review')
        self.assertTrue(validate_v3_semantic_review()['manual_review_required'])
        overlapping = copy.deepcopy(load_v3_candidate())
        overlapping['cases'][0]['target_draft'] = load_cases()['cases'][0]['target_draft']
        with self.assertRaisesRegex(ValueError, 'v3_candidate_exact_prior_overlap'):
            validate_v3_candidate_case_set(overlapping)
        named_overlap = copy.deepcopy(load_v3_candidate())
        named_overlap['cases'][0]['proper_nouns'] = [load_cases()['cases'][0]['target_draft'][:4]]
        with self.assertRaisesRegex(ValueError, 'v3_candidate_proper_noun_overlap'):
            validate_v3_candidate_case_set(named_overlap)
        north_dike = next(case for case in load_v3_candidate()['cases'] if case['case_id'] == 'eval-v3-brine-insufficient-north-dike')
        self.assertEqual(north_dike['proper_nouns'], ['北堤'])

    def test_v3_candidate_preflight_hits_expected_evidence_without_provider_calls(self):
        result = preflight_v3_candidate()
        self.assertEqual((result['case_count'], result['retrieval_expected_evidence_hit_at_5'], result['resolvable_expected_evidence'], result['fake_provider_calls'], result['real_provider_calls']), (15, 15, 15, 15, 0))
        self.assertTrue(all(row['isolated_project'] for row in result['rows']))

    def test_v4_candidate_structure_manifest_and_prior_overlap_guard_are_valid(self):
        result = validate_v4_candidate_case_set()
        manifest = validate_v4_candidate_manifest(result)
        self.assertEqual((result['case_count'], result['class_counts'], result['corpus_counts']), (15, {'conflict': 5, 'no_conflict': 5, 'insufficient_evidence': 5}, {'mist_jetty': 5, 'eave_cabin': 5, 'mica_office': 5}))
        self.assertGreaterEqual(result['multiple_direct_evidence_cases'], 2)
        self.assertGreaterEqual(result['nearby_distractor_cases'], 5)
        self.assertEqual(manifest['status'], 'candidate_for_controller_review')
        self.assertTrue(validate_v4_semantic_review()['manual_review_required'])
        overlapping = copy.deepcopy(load_v4_candidate())
        overlapping['cases'][0]['target_draft'] = load_v3_candidate()['cases'][0]['target_draft']
        with self.assertRaisesRegex(ValueError, 'v4_candidate_exact_prior_overlap'):
            validate_v4_candidate_case_set(overlapping)
        prior = load_v3_candidate()['cases'][0]
        reused_shape = copy.deepcopy(load_v4_candidate())
        reused_shape['cases'][0]['claim_shape'] = prior['claim_shape']
        with self.assertRaisesRegex(ValueError, 'v4_candidate_prior_claim_shape_overlap'):
            validate_v4_candidate_case_set(reused_shape)
        reused_signature = copy.deepcopy(load_v4_candidate())
        reused_signature['cases'][0]['decision_signature'] = prior_decision_signature(prior)
        with self.assertRaisesRegex(ValueError, 'v4_candidate_prior_decision_signature_overlap'):
            validate_v4_candidate_case_set(reused_signature)
        corpora = {key: load_corpus(key, V4_CORPUS_PATHS) for key in V4_CORPUS_PATHS}
        self.assertEqual(validate_v4_corpus_memory_types(corpora), {'mist_jetty': 4, 'eave_cabin': 4, 'mica_office': 4})
        illegal_memory_type = copy.deepcopy(corpora)
        illegal_memory_type['mist_jetty']['memory'][0]['memory_type'] = 'fact'
        with self.assertRaisesRegex(ValueError, 'v4_candidate_corpus_memory_type_invalid'):
            validate_v4_corpus_memory_types(illegal_memory_type)
        self.assertEqual(validate_v4_formal_freeze()['status'], 'approved_for_formal_run')
        with self.assertRaisesRegex(ValueError, 'formal_v4_assets_must_use_frozen_paths'):
            validate_v4_formal_freeze(pathlib.Path('evaluation/case_sets/eval-set-v4-candidate.json'))

    def test_v4_candidate_preflight_hits_expected_evidence_without_provider_calls(self):
        result = preflight_v4_candidate()
        self.assertEqual((result['case_count'], result['retrieval_expected_evidence_hit_at_5'], result['resolvable_expected_evidence'], result['fake_provider_calls'], result['real_provider_calls']), (15, 15, 15, 15, 0))
        self.assertTrue(all(row['isolated_project'] for row in result['rows']))

    def test_v2_formal_freeze_is_accepted_and_fixed_path_guard_rejects_copies(self):
        result = validate_formal_freeze()
        self.assertEqual((result['status'], result['semantic_review_entries']), ('approved_for_formal_run', 15))
        repo = pathlib.Path(__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, 'formal_v2_assets_must_use_frozen_paths'):
            validate_formal_freeze(repo / 'evaluation' / 'case_sets' / 'eval-set-v2-candidate.json')

    def test_v3_formal_freeze_is_accepted_and_fixed_path_guard_rejects_copies(self):
        result = validate_v3_formal_freeze()
        self.assertEqual((result['status'], result['semantic_review_entries']), ('approved_for_formal_run', 15))
        repo = pathlib.Path(__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, 'formal_v3_assets_must_use_frozen_paths'):
            validate_v3_formal_freeze(repo / 'evaluation' / 'case_sets' / 'eval-set-v3-candidate.json')

    def test_release_bundle_is_self_consistent_and_strict_validation_fails_closed_on_tamper(self):
        release = validate_release_bundle()
        self.assertEqual((release['formal_result_files'], release['workspace_records'], release['run_status_totals']), (7, 15, {'completed': 21}))
        with tempfile.TemporaryDirectory(prefix='scc-strict-integrity-') as temporary_name:
            root = pathlib.Path(temporary_name)
            integrity_path = self._synthetic_retained_integrity(root)
            self.assertEqual(validate_retained_integrity(root, integrity_path)['run_status_totals'], {'completed': 15})
            artifact = root / 'evaluation' / 'results' / 'synthetic-result-0.json'
            artifact.write_text('{"tampered":true}', encoding='utf-8')
            with self.assertRaisesRegex(ValueError, 'post_run_artifact_hash_mismatch'):
                validate_retained_integrity(root, integrity_path)

    def test_v2_multiple_evidence_requires_two_conflicts_not_a_no_conflict(self):
        payload = copy.deepcopy(load_candidate())
        for case in payload['cases']:
            if case['case_id'] == 'eval-v2-archive-conflict-tube-early-shelf':
                case.pop('requires_multiple_direct_evidence')
            if case['case_id'] == 'eval-v2-spire-no-conflict-mirror-seal':
                case['requires_multiple_direct_evidence'] = True
                case['expected_evidence'].append({'chapter_number': 1, 'source_label': '闸门准则'})
        with self.assertRaisesRegex(ValueError, 'candidate_multiple_direct_evidence_requirement_failed'):
            validate_candidate_case_set(payload)

    def test_generic_runner_parameters_keep_v1_outputs_and_candidate_unapproved(self):
        with self.assertRaisesRegex(RuntimeError, 'frozen_v1_output_path_refused'):
            assert_outputs_safe(build_run_config('scc-web-demo-eval-v1', 'evaluation/case_sets/eval-set-v1.json', 'evaluation/manifests/eval-set-v1-manifest.json', 'first-formal'))
        with self.assertRaisesRegex(RuntimeError, 'frozen_v1_checkpoint_path_refused'):
            assert_outputs_safe(build_run_config('scc-web-demo-eval-v2', 'evaluation/case_sets/eval-set-v2-candidate.json', 'evaluation/manifests/eval-set-v2-candidate-manifest.json', 'eval-v2-formal', 'evaluation/results/first-formal-checkpoint.json'))
        config = build_run_config('scc-web-demo-eval-v2', 'evaluation/case_sets/eval-set-v2-candidate.json', 'evaluation/manifests/eval-set-v2-candidate-manifest.json', 'eval-v2-formal', 'evaluation/results/eval-v2-formal-checkpoint.json')
        self.assertTrue(str(config.checkpoint_path).endswith('evaluation\\results\\eval-v2-formal-checkpoint.json'))
        self.assertIn('evaluation/case_sets/eval-set-v2-candidate.json', {key.replace('\\', '/') for key in source_hashes_for_config(config)})
        with self.assertRaisesRegex(RuntimeError, 'evaluation_manifest_not_approved_for_formal_run'):
            assert_manifest_approved({'status': 'candidate_for_controller_review'})
        for value in ('../outside.json', 'C:/temp/outside.json'):
            with self.subTest(value=value):
                with self.assertRaisesRegex(ValueError, 'evaluation_path_'):
                    build_run_config('scc-web-demo-eval-v2', value, 'evaluation/manifests/eval-set-v2-candidate-manifest.json', 'eval-v2-formal')

    def test_v2_fixture_preflight_uses_isolated_projects_and_hits_all_expected_evidence(self):
        result = preflight_candidate()
        self.assertEqual((result['case_count'], result['retrieval_expected_evidence_hit_at_5'], result['resolvable_expected_evidence'], result['fake_provider_calls']), (15, 15, 15, 15))
        self.assertTrue(all(row['isolated_project'] for row in result['rows']))
        self.assertEqual((preflight_candidate('cloud_post')['selected_corpus_key'], preflight_candidate('cloud_post')['case_count']), ('cloud_post', 5))

    def test_fixture_loader_rolls_back_and_corpora_cannot_cross(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix='scc-fixture-rollback-'))
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root/'protected'), provider=EmptyIssueProvider(), executor=lambda fn,*args: fn(*args))
        with self.assertRaisesRegex(RuntimeError, 'fixture_injected_failure'):
            load_fixture(app.state.database, 'calibration_spire', fail_after='project')
        with app.state.database.connection() as connection:
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_users').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_projects').fetchone()[0], 0)
            self.assertEqual(connection.execute('SELECT COUNT(*) FROM v2_source_spans').fetchone()[0], 0)
        with fixture_runtime('calibration_spire', EmptyIssueProvider()) as first, fixture_runtime('cloud_post', EmptyIssueProvider()) as second:
            self.assertEqual(first.client.get(f'/api/projects/{second.identity.project_id}').status_code, 404)
            self.assertEqual(second.client.get(f'/api/projects/{first.identity.project_id}').status_code, 404)

    def test_evaluation_only_fixture_sensitive_scan_is_clean(self):
        result = scan_v2_fixtures()
        self.assertEqual((result['source_files'], result['temporary_databases'], result['unresolved']), (9, 9, 0))

    def test_prediction_rule_and_metric_boundaries(self):
        conflict={'issues':[{'claim_span_id':'claim-run-1','classification':'conflict','category':'attribute','severity':'high'}]}
        insufficient={'issues':[{'claim_span_id':'claim-run-1','classification':'insufficient_evidence','category':'attribute','severity':'low'}]}
        self.assertEqual(prediction_for_target(conflict,1)[0],'conflict')
        self.assertEqual(prediction_for_target(insufficient,1)[0],'insufficient_evidence')
        self.assertEqual(prediction_for_target({'issues':[]},1)[0],'no_conflict')
        rows=[]
        for expected,predicted in [('conflict','conflict'),('no_conflict','conflict'),('insufficient_evidence','insufficient_evidence')]:
            rows.append({'expected_class':expected,'predicted_class':predicted,'retrieval_hit_at_5':True,'cited_evidence_count':1,'cited_evidence_expected_count':1,'resolvable_evidence_count':1,'schema_valid':True,'latency_ms':10,'input_tokens':1,'output_tokens':1,'cost_cny':None})
        result=aggregate(rows)
        self.assertEqual(result['confusion_matrix']['no_conflict']['conflict'],1)
        self.assertAlmostEqual(result['no_conflict_false_positive_rate'],1.0)
        self.assertEqual(result['cost'],'unavailable')

    def test_stability_keeps_free_text_separate(self):
        rows=[{'predicted_class':'conflict','category_severity':['attribute','high'],'evidence_ids':['e1'],'explanation_sha256':'a'},{'predicted_class':'conflict','category_severity':['attribute','high'],'evidence_ids':['e1'],'explanation_sha256':'b'}]
        result=stability(rows)
        self.assertTrue(result['class_decision_stability'])
        self.assertTrue(result['category_severity_stability'])
        self.assertTrue(result['evidence_id_set_stability'])
        self.assertFalse(result['exact_explanation_text_stability'])

    def test_terminal_failure_is_classified_as_schema_root_cause(self):
        result = bad_case({'case_id':'failed-case','expected_class':'insufficient_evidence','predicted_class':'no_conflict','expected_category':None,'predicted_category':None,'terminal_status':'failed','terminal_error_code':'insufficient_evidence_upgraded','retrieval_hit_at_5':True,'cited_evidence_count':0,'resolvable_evidence_count':0})
        self.assertEqual(result['root_cause'], 'schema')

    def test_case_sessions_remain_isolated_for_stability_repeats(self):
        class EmptyIssueProvider:
            label='runner-contract-provider'; model_label='runner-contract-model'; available=True
            def __init__(self): self.calls=0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        provider = EmptyIssueProvider()
        root = pathlib.Path(tempfile.mkdtemp(prefix='scc-runner-sessions-'))
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root/'protected'), provider=provider, executor=lambda fn,*args: fn(*args))
        cases = load_cases()['cases']
        selected = [cases[0], cases[len(cases)//2], cases[-1]]
        scanner = ApiResponseScanner()
        checkpoint = FormalCheckpoint(root/'checkpoint.json', 'runner-session-fixture')
        clients = [TestClient(app) for _ in selected]
        try:
            contexts = {}
            initial = {}
            for case, client in zip(selected, clients):
                result, contexts[case['case_id']] = run_case(checkpoint, client, case, scanner)
                self.assertTrue(result['idempotency_replay_same_run'])
                initial[case['case_id']] = result['run_id']
            for case, client in zip(selected, clients):
                replay = repeat_case(client, case, contexts[case['case_id']], scanner)
                self.assertTrue(replay['idempotency_replay_same_run'])
                self.assertNotEqual(replay['run_id'], initial[case['case_id']])
        finally:
            for client in clients: client.close()
        self.assertEqual(provider.calls, 6)

    def test_checkpoint_recovers_each_crash_window_without_duplicate_side_effects(self):
        class EmptyIssueProvider:
            label='checkpoint-contract-provider'; model_label='checkpoint-contract-model'; available=True
            def __init__(self): self.calls=0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        case = load_cases()['cases'][0]
        for boundary in ('after_account_created','after_draft_saved','after_check_posted','after_run_terminal'):
            with self.subTest(boundary=boundary):
                provider = EmptyIssueProvider()
                root = pathlib.Path(tempfile.mkdtemp(prefix='scc-runner-resume-'))
                app = create_app(AppPaths.from_project_root(root, protected_poc_root=root/'protected'), provider=provider, executor=lambda fn,*args: fn(*args))
                checkpoint_path = root / 'evaluation-checkpoint.json'
                checkpoint = FormalCheckpoint(checkpoint_path, 'fixture-case-set')

                def interrupt(name):
                    if name == boundary: raise RuntimeError('simulated_interrupt')

                with TestClient(app) as client:
                    with self.assertRaisesRegex(RuntimeError, 'simulated_interrupt'):
                        run_case(checkpoint, client, case, ApiResponseScanner(), interrupt)
                with app.state.database.connection() as connection:
                    account_count = connection.execute('SELECT COUNT(*) FROM v2_users WHERE account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                    project_count = connection.execute('SELECT COUNT(*) FROM v2_projects p JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                    first_run_id = connection.execute('SELECT r.id FROM v2_runs r JOIN v2_projects p ON p.id=r.project_id JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=?',(runner_account_name(case['case_id']),)).fetchone()
                resumed = FormalCheckpoint(checkpoint_path, 'fixture-case-set')
                with TestClient(app) as client:
                    result, state = run_case(resumed, client, case, ApiResponseScanner())
                with app.state.database.connection() as connection:
                    final_account_count = connection.execute('SELECT COUNT(*) FROM v2_users WHERE account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                    final_project_count = connection.execute('SELECT COUNT(*) FROM v2_projects p JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                    final_revision = connection.execute('SELECT d.revision FROM v2_drafts d JOIN v2_projects p ON p.id=d.project_id JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=? AND p.seed_key=?',(runner_account_name(case['case_id']),case['seed_key'])).fetchone()[0]
                    final_runs = connection.execute('SELECT COUNT(*) FROM v2_runs r JOIN v2_projects p ON p.id=r.project_id JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                self.assertEqual((account_count,project_count),(1,3))
                self.assertEqual((final_account_count,final_project_count,final_revision,final_runs),(1,3,2,1))
                self.assertEqual(provider.calls,1)
                if first_run_id is not None: self.assertEqual(result['run_id'],first_run_id[0])
                self.assertEqual((state['state'],result['run_id']),('completed',state['run_id']))
                raw = checkpoint_path.read_text(encoding='utf-8')
                self.assertNotIn(case['target_draft'],raw)
                self.assertNotIn('scc_local_session',raw)

    def test_fixture_runner_uses_formal_chain_for_three_corpora_and_full_dry_run(self):
        class EmptyIssueProvider:
            label = 'fixture-runner-contract-provider'
            model_label = 'fixture-runner-contract-model'
            available = True
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        repo = pathlib.Path(__file__).resolve().parents[2]
        cases = load_candidate()['cases']
        representatives = [next(case for case in cases if case['corpus_key'] == key) for key in ('calibration_spire', 'cloud_post', 'crystal_archive')]
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='fixture-runner-contract-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work-three', provider=provider, write_artifacts=False, run_stability=False, cases_override=representatives)
            self.assertEqual((len(outcome['report']['formal_case_results']), provider.calls), (3, 3))
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in outcome['report']['formal_case_results']))
            self.assertIn('evaluation/fixtures/eval-v2-corpus-manifest.json', {key.replace('\\', '/') for key in outcome['source_hashes']})
            self.assertIn('evaluation/v2_fixture_loader.py', {key.replace('\\', '/') for key in outcome['source_hashes']})
            self.assertFalse(any((temporary / ('fixture-contract-output-' + suffix)).exists() for suffix in ('results.json', 'report.md')))

        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='fixture-runner-all-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work-all', provider=provider, write_artifacts=False, run_stability=False)
            rows = outcome['report']['formal_case_results']
            self.assertEqual((len(rows), provider.calls), (15, 15))
            self.assertEqual(len({row['run_id'] for row in rows}), 15)
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in rows))

    def test_v3_fixture_runner_uses_approved_assets_for_three_corpora_and_full_dry_run(self):
        class EmptyIssueProvider:
            label = 'v3-fixture-runner-contract-provider'
            model_label = 'v3-fixture-runner-contract-model'
            available = True
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        repo = pathlib.Path(__file__).resolve().parents[2]
        cases = load_v3_candidate()['cases']
        representatives = [next(case for case in cases if case['corpus_key'] == key) for key in ('brine_station', 'basalt_theatre', 'stair_post')]
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v3-fixture-runner-contract-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._v3_fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work-three', provider=provider, write_artifacts=False, run_stability=False, cases_override=representatives)
            self.assertEqual((len(outcome['report']['formal_case_results']), provider.calls), (3, 3))
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in outcome['report']['formal_case_results']))
            source_paths = {key.replace('\\', '/') for key in outcome['source_hashes']}
            self.assertIn('evaluation/fixtures/eval-v3-corpus-manifest.json', source_paths)
            self.assertIn('evaluation/fixtures/eval-v3-stair-post.json', source_paths)

        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v3-fixture-runner-all-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._v3_fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work-all', provider=provider, write_artifacts=False, run_stability=False)
            rows = outcome['report']['formal_case_results']
            self.assertEqual((len(rows), provider.calls), (15, 15))
            self.assertEqual(len({row['run_id'] for row in rows}), 15)
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in rows))

    def test_v4_fixture_runner_uses_approved_assets_without_mutating_prior_formal_evidence(self):
        class EmptyIssueProvider:
            label = 'v4-fixture-runner-contract-provider'
            model_label = 'v4-fixture-runner-contract-model'
            available = True
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        repo = pathlib.Path(__file__).resolve().parents[2]
        cases = load_v4_candidate()['cases']
        representatives = [next(case for case in cases if case['corpus_key'] == key) for key in ('mist_jetty', 'eave_cabin', 'mica_office')]
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v4-fixture-runner-contract-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._v4_fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work-three', provider=provider, write_artifacts=False, run_stability=False, cases_override=representatives)
            self.assertEqual((len(outcome['report']['formal_case_results']), provider.calls), (3, 3))
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in outcome['report']['formal_case_results']))
            source_paths = {key.replace('\\', '/') for key in outcome['source_hashes']}
            self.assertIn('evaluation/fixtures/eval-v4-corpus-manifest.json', source_paths)
            self.assertIn('evaluation/fixtures/eval-v4-mist-jetty.json', source_paths)
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v4-fixture-runner-all-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._v4_fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work-all', provider=provider, write_artifacts=False, run_stability=False)
            rows = outcome['report']['formal_case_results']
            self.assertEqual((len(rows), provider.calls), (15, 15))
            self.assertEqual(len({row['run_id'] for row in rows}), 15)
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in rows))
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v4-fixture-runner-once-only-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            protected = build_run_config('scc-web-demo-eval-v4-first-formal', 'evaluation/case_sets/eval-set-v4.json', 'evaluation/manifests/eval-set-v4-manifest.json', 'eval-v4-first-formal', 'evaluation/results/eval-v4-first-formal-checkpoint.json')
            blocked_provider = EmptyIssueProvider()
            blocked_work = temporary / 'work'
            with self.assertRaisesRegex(RuntimeError, 'formal_evaluation_artifacts_already_exist'):
                execute_formal_run(protected, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=blocked_work, provider=blocked_provider, write_artifacts=True, run_stability=False)
            self.assertEqual(blocked_provider.calls, 0)
            self.assertFalse(blocked_work.exists())

    def test_fixture_runner_recovers_all_crash_windows_without_duplicate_fixture_side_effects(self):
        class EmptyIssueProvider:
            label = 'fixture-recovery-provider'
            model_label = 'fixture-recovery-model'
            available = True
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        repo = pathlib.Path(__file__).resolve().parents[2]
        case = load_candidate()['cases'][0]
        for boundary in ('after_account_created', 'after_draft_saved', 'after_check_posted', 'after_run_terminal', 'after_terminal_before_completed'):
            with self.subTest(boundary=boundary), tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='fixture-runner-resume-') as temporary_name:
                temporary = pathlib.Path(temporary_name)
                config = self._fixture_config(temporary)
                work = temporary / 'work'
                provider = EmptyIssueProvider()
                def interrupt(name):
                    if name == boundary: raise RuntimeError('fixture_simulated_interrupt')
                with self.assertRaisesRegex(RuntimeError, 'fixture_simulated_interrupt'):
                    execute_formal_run(config, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=work, provider=provider, write_artifacts=False, run_stability=False, cases_override=[case], fault_hook=interrupt)
                outcome = execute_formal_run(config, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=work, provider=provider, write_artifacts=False, run_stability=False, cases_override=[case])
                self.assertEqual((len(outcome['report']['formal_case_results']), provider.calls), (1, 1))
                case_root = work / hashlib.sha256(f"{config.evaluation_id}:{case['case_id']}".encode('utf-8')).hexdigest()[:24]
                database = case_root / 'runtime' / 'data' / 'demo.sqlite3'
                with sqlite3.connect(database) as connection:
                    counts = tuple(connection.execute(query).fetchone()[0] for query in (
                        'SELECT COUNT(*) FROM v2_users',
                        'SELECT COUNT(*) FROM v2_projects',
                        'SELECT COUNT(*) FROM v2_draft_revisions',
                        'SELECT COUNT(*) FROM v2_runs',
                    ))
                    revision = connection.execute('SELECT revision FROM v2_drafts').fetchone()[0]
                connection.close()
                self.assertEqual((counts, revision), ((1, 1, 2, 1), 2))

    def test_fixture_runner_rejects_candidate_and_invalid_fixture_inputs_before_side_effects(self):
        class EmptyIssueProvider:
            label = 'fixture-negative-provider'
            model_label = 'fixture-negative-model'
            available = True
            def evaluate(self, request): return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        repo = pathlib.Path(__file__).resolve().parents[2]
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='fixture-runner-negative-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            candidate = build_run_config('scc-web-demo-eval-v2-fixture-negative', 'evaluation/case_sets/eval-set-v2-candidate.json', 'evaluation/manifests/eval-set-v2-candidate-manifest.json', 'fixture-negative-output', str((temporary / 'candidate-checkpoint.json').relative_to(repo)).replace('\\', '/'))
            work = temporary / 'work'
            with self.assertRaisesRegex(RuntimeError, 'evaluation_manifest_not_approved'):
                execute_formal_run(candidate, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=work, provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
            self.assertFalse(work.exists())
            v3_candidate = build_run_config('scc-web-demo-eval-v3-fixture-negative', 'evaluation/case_sets/eval-set-v3-candidate.json', 'evaluation/manifests/eval-set-v3-candidate-manifest.json', 'fixture-v3-negative-output', str((temporary / 'v3-candidate-checkpoint.json').relative_to(repo)).replace('\\', '/'))
            v3_work = temporary / 'v3-work'
            with self.assertRaisesRegex(RuntimeError, 'evaluation_manifest_not_approved'):
                execute_formal_run(v3_candidate, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=v3_work, provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
            self.assertFalse(v3_work.exists())
            v4_candidate = build_run_config('scc-web-demo-eval-v4-fixture-negative', 'evaluation/case_sets/eval-set-v4-candidate.json', 'evaluation/manifests/eval-set-v4-candidate-manifest.json', 'fixture-v4-negative-output', str((temporary / 'v4-candidate-checkpoint.json').relative_to(repo)).replace('\\', '/'))
            v4_work = temporary / 'v4-work'
            with self.assertRaisesRegex(RuntimeError, 'evaluation_manifest_not_approved'):
                execute_formal_run(v4_candidate, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=v4_work, provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
            self.assertFalse(v4_work.exists())
            approved = self._fixture_config(temporary)
            with self.assertRaisesRegex(RuntimeError, 'fixture_mode_requires_work_root_and_rejects_base_url'):
                execute_formal_run(approved, runtime_mode=EVALUATION_FIXTURE_MODE, base_url='http://127.0.0.1:8066', fixture_work_root_path=work, provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
            with self.assertRaisesRegex(RuntimeError, 'fixture_work_root_forbidden'):
                execute_formal_run(approved, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=repo / 'runtime', provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
