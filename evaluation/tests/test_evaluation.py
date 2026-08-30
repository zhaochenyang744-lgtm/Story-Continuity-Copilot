from __future__ import annotations

import copy
import hashlib
import json
import os
import pathlib
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

from evaluation.metrics import aggregate, prediction_for_target, stability
from evaluation.run_eval import ApiResponseScanner, EVALUATION_FIXTURE_MODE, FormalCheckpoint, assert_manifest_approved, assert_outputs_safe, bad_case, build_run_config, execute_formal_run, gate, repeat_case, run_case, runner_account_name, source_hashes_for_config
from evaluation.validate_eval_set import load_cases, validate_case_set
from evaluation.validate_eval_set_v2_candidate import load_candidate, validate_candidate_case_set, validate_candidate_manifest, validate_semantic_review
from evaluation.validate_eval_set_v2 import validate_formal_freeze
from evaluation.validate_eval_set_v3 import validate_formal_freeze as validate_v3_formal_freeze
from evaluation.validate_eval_set_v4 import validate_formal_freeze as validate_v4_formal_freeze
from evaluation.validate_eval_set_v5 import validate_formal_freeze as validate_v5_formal_freeze
from evaluation.validate_v5_first_formal_results import validate as validate_v5_first_formal_results
from evaluation.validate_v6_first_formal_results import validate as validate_v6_first_formal_results
from evaluation.validate_v7_first_formal_results import validate as validate_v7_first_formal_results
from evaluation.validate_v8_first_formal_results import validate as validate_v8_first_formal_results
from evaluation.scan_v7_retained import scan as scan_v7_retained
from evaluation.validate_v5_invalid_config_archive import validate as validate_v5_invalid_config_archive
from evaluation.validate_eval_set_v4_candidate import load_v4_candidate, prior_decision_signature, validate_v4_candidate_case_set, validate_v4_candidate_manifest, validate_v4_corpus_memory_types, validate_v4_semantic_review
from evaluation.validate_eval_set_v5_candidate import load_v5_candidate, validate_v5_candidate_case_set, validate_v5_candidate_manifest, validate_v5_corpora, validate_v5_formal_plan, validate_v5_semantic_review
from evaluation.validate_eval_set_v6_candidate import load_v6_candidate, validate_all as validate_v6_all, validate_v6_candidate_case_set, validate_v6_candidate_manifest, validate_v6_corpora, validate_v6_formal_plan, validate_v6_semantic_review
from evaluation.validate_eval_set_v6 import validate_formal_freeze as validate_v6_formal_freeze
from evaluation.validate_eval_set_v7_candidate import load_v7_candidate, validate_all as validate_v7_all, validate_v7_candidate_case_set, validate_v7_formal_plan, validate_v7_semantic_review
from evaluation.validate_eval_set_v7 import validate_formal_freeze as validate_v7_formal_freeze
from evaluation.validate_eval_set_v8_candidate import load_v8_candidate, validate_all as validate_v8_all, validate_v8_candidate_case_set
from evaluation.validate_eval_set_v8 import validate_formal_freeze as validate_v8_formal_freeze, validate_formal_readiness as validate_v8_formal_readiness
from evaluation.v8_fixture_preflight import preflight_v8_candidate
from evaluation.execute_v8_first_formal import assert_real_execution_preconditions as assert_v8_real_execution_preconditions, fake_only_dry_run as v8_fake_only_dry_run
from evaluation import execute_v8_first_formal as v8_runner
from evaluation.freeze_v7_formal_inputs import freeze as freeze_v7_formal_inputs
from evaluation.execute_v7_first_formal import assert_real_execution_preconditions as assert_v7_real_execution_preconditions, assert_zero_formal_output_paths as assert_v7_zero_formal_output_paths, build_v7_run_config, fake_only_dry_run as v7_fake_only_dry_run, planned_provider_call_count
from evaluation.post_run_integrity import validate_retained_integrity
from evaluation.validate_release_bundle import validate_release_bundle
from evaluation.validate_eval_set_v3_candidate import load_v3_candidate, validate_v3_candidate_case_set, validate_v3_candidate_manifest, validate_v3_semantic_review
from evaluation.v2_fixture_loader import V4_CORPUS_PATHS, V5_CORPUS_PATHS, V6_CORPUS_PATHS, V7_CORPUS_PATHS, fixture_runtime, load_corpus, load_fixture
from evaluation.v2_fixture_preflight import EmptyIssueProvider, preflight_candidate, preflight_v3_candidate, preflight_v4_candidate
from evaluation.v5_fixture_preflight import preflight_v5_candidate
from evaluation.v6_fixture_preflight import preflight_v6_candidate
from evaluation.v7_fixture_preflight import DeterministicV7NoIssueProvider, preflight_v7_candidate
from evaluation.scan_v2_fixtures import scan as scan_v2_fixtures

from fastapi.testclient import TestClient
from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderFailure, ProviderResult


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

    def _v5_fixture_config(self, temporary: pathlib.Path):
        repo = pathlib.Path(__file__).resolve().parents[2]
        return build_run_config(
            'scc-web-demo-eval-v5-fixture-contract',
            'evaluation/case_sets/eval-set-v5.json',
            'evaluation/manifests/eval-set-v5-manifest.json',
            'fixture-v5-contract-output',
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

    def test_v5_candidate_structure_lineage_manifest_and_plan_are_valid(self):
        result = validate_v5_candidate_case_set()
        manifest = validate_v5_candidate_manifest(result)
        self.assertEqual((result['case_count'], result['class_counts']), (24, {'conflict': 8, 'no_conflict': 8, 'insufficient_evidence': 8}))
        self.assertEqual(result['corpus_counts'], {'ember_observatory': 6, 'reed_foundry': 6, 'glass_marsh': 6, 'copper_orchard': 6})
        self.assertEqual(result['conflict_categories'], ['attribute', 'character_knowledge', 'event_status', 'location_action', 'object_state', 'relationship', 'timeline', 'world_rule'])
        self.assertEqual((result['challenge_counts']['requires_multiple_direct_evidence'], result['challenge_counts']['ambiguous_evidence'], result['challenge_counts']['conflicting_sources'], result['challenge_counts']['insufficient_evidence'], result['challenge_counts']['category_mismatch_regression']), (8, 8, 4, 8, 3))
        self.assertEqual(validate_v5_corpora()['chapter_counts'], {key: 8 for key in V5_CORPUS_PATHS})
        self.assertTrue(validate_v5_semantic_review()['manual_review_required'])
        self.assertEqual((manifest['status'], validate_v5_formal_plan()['status']), ('candidate_for_controller_review', 'not_run'))

    def test_v5_formal_freeze_is_byte_identical_signed_and_not_executed(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        result = validate_v5_formal_freeze()
        self.assertEqual((result['status'], result['semantic_review_entries'], result['frozen_file_count']), ('approved_for_formal_run', 24, 8))
        self.assertTrue(result['case_set_byte_identical_to_candidate'])
        self.assertEqual((result['controller_candidate_gate_passed'], result['real_provider_authorization_received'], result['formal_run_executed'], result['provider_calls']), (True, False, False, 0))
        self.assertEqual((repo / 'evaluation/case_sets/eval-set-v5-candidate.json').read_bytes(), (repo / 'evaluation/case_sets/eval-set-v5.json').read_bytes())
        manifest = json.loads((repo / 'evaluation/manifests/eval-set-v5-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['approval'], {'controller_candidate_gate_passed': True, 'real_provider_authorization_received': False, 'approval_scope': 'evaluation_input_freeze_only'})
        with self.assertRaisesRegex(ValueError, 'formal_v5_assets_must_use_frozen_paths'):
            validate_v5_formal_freeze(repo / 'evaluation/case_sets/eval-set-v5-candidate.json')

    def test_v5_invalid_archive_and_first_valid_formal_are_separate_and_frozen(self):
        invalid = validate_v5_invalid_config_archive()
        valid = validate_v5_first_formal_results()
        self.assertFalse(invalid['counts_toward_v5_model_quality_gate'])
        self.assertEqual((invalid['provider_run_records'], invalid['successful_provider_responses']), (30, 0))
        self.assertEqual((valid['status'], valid['formal_case_count'], valid['provider_run_count'], valid['provider_successful_result_count']), ('gate_failed', 24, 30, 30))
        self.assertEqual(valid['terminal_status_counts'], {'completed': 30})

    def test_v5_candidate_preflight_hits_all_expected_evidence_in_isolated_temporary_projects(self):
        result = preflight_v5_candidate()
        self.assertEqual((result['case_count'], result['retrieval_expected_evidence_hit_at_5'], result['evidence_parseable'], result['source_lineage_resolved'], result['account_project_isolated']), (24, 24, 24, 24, 24))
        self.assertEqual((result['provider_calls'], result['real_provider_calls'], result['fake_provider_calls'], result['formal_run_executed']), (0, 0, 24, False))
        self.assertFalse(result['fake_provider_quality_scored'])

    def test_v6_candidate_assets_remain_valid_after_the_formal_run(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        result = validate_v6_candidate_case_set()
        self.assertEqual((result['case_count'], result['class_counts']), (24, {'conflict': 8, 'no_conflict': 8, 'insufficient_evidence': 8}))
        self.assertEqual(result['corpus_counts'], {key: 6 for key in V6_CORPUS_PATHS})
        self.assertEqual(result['conflict_categories'], ['attribute', 'character_knowledge', 'event_status', 'location_action', 'object_state', 'relationship', 'timeline', 'world_rule'])
        self.assertGreaterEqual(result['challenge_counts']['requires_multiple_direct_evidence'], 8)
        self.assertGreaterEqual(result['challenge_counts']['conflicting_sources'], 4)
        self.assertGreaterEqual(result['challenge_counts']['ambiguous_evidence'] + result['challenge_counts']['insufficient_evidence'], 8)
        self.assertGreaterEqual(result['challenge_counts']['category_mismatch_regression'], 3)
        self.assertEqual(validate_v6_corpora()['chapter_counts'], {key: 8 for key in V6_CORPUS_PATHS})
        self.assertTrue(validate_v6_semantic_review()['manual_review_required'])
        manifest = validate_v6_candidate_manifest(result)
        whole = validate_v6_all()
        self.assertEqual(manifest['canonical_sha256'], result['canonical_sha256'])
        if (repo / 'evaluation/results/v6-first-formal-post-run-integrity.json').exists():
            self.assertEqual((whole['lifecycle'], whole['formal_run_executed'], whole['provider_calls'], whole['formal_plan']['status']), ('post_run', True, 30, 'gate_failed'))
            self.assertTrue(validate_v6_first_formal_results()['valid'])
        else:
            self.assertEqual((whole['lifecycle'], whole['formal_run_executed'], whole['provider_calls'], whole['formal_plan']['status']), ('pre_run', False, 0, 'not_run'))
        with self.assertRaisesRegex(RuntimeError, 'evaluation_manifest_not_approved'):
            assert_manifest_approved(json.loads((repo / 'evaluation/manifests/eval-set-v6-candidate-manifest.json').read_text(encoding='utf-8')))

    def test_v6_formal_freeze_remains_valid_and_rejects_rerun_after_formal_execution(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        self.assertEqual((repo / 'evaluation/case_sets/eval-set-v6-candidate.json').read_bytes(), (repo / 'evaluation/case_sets/eval-set-v6.json').read_bytes())
        manifest = json.loads((repo / 'evaluation/manifests/eval-set-v6-manifest.json').read_text(encoding='utf-8'))
        self.assertEqual(manifest['approval']['approval_scope'], 'evaluation_input_freeze_only')
        if (repo / 'evaluation/results/v6-first-formal-post-run-integrity.json').exists():
            result = validate_v6_formal_freeze()
            self.assertEqual((result['lifecycle'], result['formal_result_status'], result['formal_run_executed'], result['provider_calls']), ('post_run', 'gate_failed', True, 30))
            self.assertTrue(validate_v6_first_formal_results()['valid'])
            config = build_run_config('scc-web-demo-eval-v6-first-formal', 'evaluation/case_sets/eval-set-v6.json', 'evaluation/manifests/eval-set-v6-manifest.json', 'eval-v6-first-formal')
            with self.assertRaisesRegex(RuntimeError, 'formal_evaluation_artifacts_already_exist'):
                assert_outputs_safe(config)
        else:
            result = validate_v6_formal_freeze()
            self.assertEqual((result['status'], result['semantic_review_entries'], result['frozen_file_count']), ('approved_for_formal_run', 24, 8))
            self.assertTrue(result['case_set_byte_identical_to_candidate'])
            self.assertEqual((result['controller_candidate_gate_passed'], result['real_provider_authorization_received'], result['formal_run_executed'], result['provider_calls']), (True, False, False, 0))
        with self.assertRaisesRegex(ValueError, 'formal_v6_assets_must_use_frozen_paths'):
            validate_v6_formal_freeze(repo / 'evaluation/case_sets/eval-set-v6-candidate.json')

    def test_v6_candidate_preflight_is_fake_only_and_hits_all_required_evidence(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        if (repo / 'evaluation/results/v6-first-formal-post-run-integrity.json').exists():
            with self.assertRaisesRegex(RuntimeError, 'v6_candidate_preflight_refuses_completed_formal_run'):
                preflight_v6_candidate()
            self.assertTrue(validate_v6_first_formal_results()['valid'])
        else:
            result = preflight_v6_candidate()
            self.assertEqual((result['case_count'], result['retrieval_expected_evidence_hit_at_5'], result['evidence_parseable'], result['source_lineage_resolved'], result['account_project_isolated']), (24, 24, 24, 24, 24))
            self.assertEqual((result['provider_calls'], result['real_provider_calls'], result['fake_provider_calls'], result['formal_run_executed'], result['quality_scored']), (0, 0, 24, False, False))
            self.assertTrue(all(row['account_project_isolated'] for row in result['rows']))

    def test_v6_negative_case_manifest_lineage_challenge_and_false_run_fields_fail_closed(self):
        duplicate = copy.deepcopy(load_v6_candidate())
        duplicate['cases'][1]['case_id'] = duplicate['cases'][0]['case_id']
        with self.assertRaisesRegex(ValueError, 'v6_candidate_duplicate_case_or_semantic_identifier'):
            validate_v6_candidate_case_set(duplicate)
        wrong_category = copy.deepcopy(load_v6_candidate())
        wrong_category['cases'][0]['expected_category'] = 'not-a-category'
        with self.assertRaisesRegex(ValueError, 'v6_candidate_conflict_category_or_multiple_evidence_invalid'):
            validate_v6_candidate_case_set(wrong_category)
        missing_evidence = copy.deepcopy(load_v6_candidate())
        missing_evidence['cases'][0]['expected_evidence'][0]['chapter_number'] = 999
        with self.assertRaisesRegex(ValueError, 'v6_candidate_expected_evidence_unresolvable'):
            validate_v6_candidate_case_set(missing_evidence)
        cross_corpus = copy.deepcopy(load_v6_candidate())
        cross_corpus['cases'][0]['source_lineage'][0]['corpus_key'] = 'velvet_signal_yard'
        with self.assertRaisesRegex(ValueError, 'v6_candidate_cross_corpus_or_missing_source_lineage'):
            validate_v6_candidate_case_set(cross_corpus)
        weak_challenges = copy.deepcopy(load_v6_candidate())
        for case in weak_challenges['cases']:
            case['challenge_tags'] = [tag for tag in case['challenge_tags'] if tag != 'conflicting_sources']
        with self.assertRaisesRegex(ValueError, 'v6_candidate_challenge_coverage_invalid'):
            validate_v6_candidate_case_set(weak_challenges)
        prior_reuse = copy.deepcopy(load_v6_candidate())
        prior_reuse['cases'][0]['case_id'] = load_v5_candidate()['cases'][0]['case_id']
        with self.assertRaisesRegex(ValueError, 'v6_candidate_prior_identifier_or_core_fact_reuse'):
            validate_v6_candidate_case_set(prior_reuse)
        false_case = copy.deepcopy(load_v6_candidate())
        false_case['formal_run_executed'] = True; false_case['provider_calls'] = 1
        with self.assertRaisesRegex(ValueError, 'v6_candidate_formal_or_provider_field_false_report'):
            validate_v6_candidate_case_set(false_case)
        repo = pathlib.Path(__file__).resolve().parents[2]
        manifest = json.loads((repo / 'evaluation/manifests/eval-set-v6-candidate-manifest.json').read_text(encoding='utf-8'))
        bad_hash = copy.deepcopy(manifest); bad_hash['case_set']['canonical_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'v6_candidate_manifest_hash_or_scope_invalid'):
            validate_v6_candidate_manifest(manifest=bad_hash)
        plan = json.loads((repo / 'evaluation/manifests/eval-v6-first-formal-plan.json').read_text(encoding='utf-8'))
        plan['formal_run_executed'] = True; plan['provider_calls'] = 1
        with self.assertRaisesRegex(ValueError, 'v6_formal_plan_post_run_state_invalid'):
            validate_v6_formal_plan(plan)

    def test_bad_case_merges_evidence_coverage_dimensions_into_one_safe_record(self):
        result = {
            'case_id': 'synthetic-case', 'expected_class': 'conflict', 'predicted_class': 'no_conflict',
            'expected_category': 'timeline', 'predicted_category': None, 'terminal_status': 'completed',
            'terminal_error_code': None, 'retrieval_hit_at_5': True, 'cited_evidence_count': 1,
            'resolvable_evidence_count': 1, 'expected_evidence_count': 2,
            'cited_expected_evidence_unique_count': 1, 'requires_multiple_direct_evidence': True,
            'expected_evidence_full_set_cited': False,
        }
        record = bad_case(result)
        self.assertEqual(record['case_id'], 'synthetic-case')
        self.assertEqual(record['failure_dimensions'], ['classification_mismatch', 'category_mismatch', 'expected_evidence_recall_incomplete', 'multi_direct_evidence_full_set_miss'])
        self.assertEqual(record['category'], {'expected': 'timeline', 'predicted': None})
        self.assertNotIn('target_draft', record)
        self.assertNotIn('raw_provider_body', json.dumps(record))

    def test_v6_post_run_validator_cli_regression(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        if not (repo / 'evaluation/results/v6-first-formal-post-run-integrity.json').exists():
            self.skipTest('V6 formal result is not present in this workspace')
        for module in ('evaluation.validate_eval_set_v6', 'evaluation.validate_v6_first_formal_results'):
            completed = subprocess.run([sys.executable, '-m', module], cwd=repo, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)

    def test_v7_candidate_contract_remains_valid_after_formal_input_freeze(self):
        result = validate_v7_candidate_case_set()
        self.assertEqual((result['case_count'], result['class_counts'], result['corpus_counts']), (24, {'conflict': 8, 'no_conflict': 8, 'insufficient_evidence': 8}, {key: 6 for key in V7_CORPUS_PATHS}))
        self.assertEqual(result['conflict_categories'], ['attribute', 'character_knowledge', 'event_status', 'location_action', 'object_state', 'relationship', 'timeline', 'world_rule'])
        self.assertEqual(result['challenge_counts']['conflicting_sources'], 8)
        self.assertEqual(result['challenge_counts']['category_mismatch_regression'], 3)
        self.assertEqual(result['category_boundary_pairs'], [['event_status', 'timeline'], ['location_action', 'object_state'], ['relationship', 'world_rule']])
        self.assertTrue(validate_v7_semantic_review()['manual_review_completed'])
        whole = validate_v7_all()
        if whole['formal_run_executed']:
            self.assertEqual((whole['status'], whole['provider_calls'], whole['formal_plan']['status']), ('formal_run_completed', 30, 'gate_failed'))
            formal = validate_v7_formal_freeze()
            self.assertEqual((formal['lifecycle'], formal['formal_result_status'], formal['formal_result_count'], formal['formal_workspace_count']), ('post_run', 'gate_failed', 8, 24))
            with self.assertRaisesRegex(RuntimeError, 'formal_evaluation_artifacts_already_exist'):
                assert_outputs_safe(build_v7_run_config())
            self.assertTrue(validate_v7_first_formal_results()['valid'])
            return
        self.assertEqual((whole['status'], whole['provider_calls'], whole['real_provider_calls'], whole['formal_plan']['formal_inputs_frozen'], whole['formal_plan']['status']), ('formal_inputs_frozen', 0, 0, True, 'awaiting_real_provider_authorization'))
        formal = validate_v7_formal_freeze()
        self.assertEqual((formal['status'], formal['semantic_review_entries'], formal['frozen_file_count'], formal['formal_result_count'], formal['formal_workspace_count']), ('awaiting_real_provider_authorization', 24, 8, 0, 0))
        self.assertTrue(formal['case_set_byte_identical_to_candidate'])
        self.assertTrue(formal['semantic_review_byte_identical_to_candidate'])
        repo = pathlib.Path(__file__).resolve().parents[2]
        with self.assertRaisesRegex(ValueError, 'formal_v7_assets_must_use_frozen_paths'):
            validate_v7_formal_freeze(repo / 'evaluation/case_sets/eval-set-v7-candidate.json')
        with self.assertRaisesRegex(RuntimeError, 'v7_formal_freeze_target_exists'):
            freeze_v7_formal_inputs()

    def test_v7_negative_case_boundary_evidence_and_false_formal_fields_fail_closed(self):
        wrong_category = copy.deepcopy(load_v7_candidate())
        wrong_category['cases'][0]['expected_category'] = 'not-a-category'
        with self.assertRaisesRegex(ValueError, 'v7_candidate_conflict_category_or_multiple_evidence_invalid'):
            validate_v7_candidate_case_set(wrong_category)
        missing_direct = copy.deepcopy(load_v7_candidate())
        missing_direct['cases'][0]['expected_evidence'] = missing_direct['cases'][0]['expected_evidence'][1:]
        missing_direct['cases'][0]['source_lineage'] = missing_direct['cases'][0]['source_lineage'][1:]
        with self.assertRaisesRegex(ValueError, 'v7_candidate_rubric_evidence_contract_invalid'):
            validate_v7_candidate_case_set(missing_direct)
        false_joint_declaration = copy.deepcopy(load_v7_candidate())
        false_joint_declaration['cases'][0]['each_expected_evidence_individually_insufficient'] = False
        with self.assertRaisesRegex(ValueError, 'v7_candidate_conflict_category_or_multiple_evidence_invalid'):
            validate_v7_candidate_case_set(false_joint_declaration)
        review_path = pathlib.Path(__file__).resolve().parents[2] / 'evaluation/v7-candidate-semantic-review.json'
        review = json.loads(review_path.read_text(encoding='utf-8'))
        missing_reason = copy.deepcopy(review)
        missing_reason['entries'][0]['evidence_a_alone_insufficient_reason'] = ''
        from evaluation.validate_eval_set_v7_candidate import validate_v7_semantic_review
        with self.assertRaisesRegex(ValueError, 'v7_semantic_review_joint_evidence_declaration_invalid'):
            validate_v7_semantic_review(review=missing_reason)
        plan = json.loads((pathlib.Path(__file__).resolve().parents[2] / 'evaluation/manifests/eval-v7-first-formal-plan.json').read_text(encoding='utf-8'))
        plan['formal_run_executed'] = True; plan['provider_calls'] = 1
        with self.assertRaisesRegex(ValueError, 'v7_formal_plan_post_run_state_invalid'):
            validate_v7_formal_plan(plan)

    def test_v7_fake_preflight_hits_all_required_evidence_in_isolated_temporary_projects(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        if (repo / 'evaluation/results/v7-first-formal-post-run-integrity.json').exists():
            with self.assertRaisesRegex(RuntimeError, 'v7_candidate_preflight_refuses_completed_formal_run'):
                preflight_v7_candidate()
            self.assertTrue(validate_v7_first_formal_results()['valid'])
            return
        result = preflight_v7_candidate()
        self.assertEqual((result['case_count'], result['retrieval_expected_evidence_hit_at_5'], result['evidence_parseable'], result['source_lineage_resolved'], result['account_project_isolated']), (24, 24, 24, 24, 24))
        self.assertEqual((result['provider_calls'], result['real_provider_calls'], result['fake_provider_calls'], result['quality_scored']), (0, 0, 24, False))

    def test_v7_formal_pre_execution_contract_is_fake_only_and_requires_explicit_authorization(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        if (repo / 'evaluation/results/v7-first-formal-post-run-integrity.json').exists():
            self.assertTrue(validate_v7_first_formal_results()['valid'])
            return
        result = v7_fake_only_dry_run()
        self.assertEqual((result['formal_status'], result['planned_provider_calls'], result['fake_provider_calls'], result['real_provider_calls'], result['quality_scored']), ('awaiting_real_provider_authorization', 30, 24, 0, False))
        with self.assertRaisesRegex(RuntimeError, 'v7_real_provider_authorization_required'):
            assert_v7_real_execution_preconditions()

    def test_v7_cli_runs_from_repo_root_without_test_pythonpath_or_provider_side_effects(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        plan_path = repo / 'evaluation/manifests/eval-v7-first-formal-plan.json'
        plan = json.loads(plan_path.read_text(encoding='utf-8'))
        result_paths = [repo / value for value in plan['planned_output_paths'].values()]
        workspace = repo / 'evaluation/fixture-workspaces/scc-web-demo-eval-v7-first-formal'
        if (repo / 'evaluation/results/v7-first-formal-post-run-integrity.json').exists():
            environment = os.environ.copy(); environment.pop('PYTHONPATH', None)
            for key in ('CONTINUITY_PROVIDER', 'CONTINUITY_MODEL', 'CONTINUITY_BASE_URL', 'CONTINUITY_API_KEY'):
                environment.pop(key, None)
            for module, expected in (
                ('evaluation.validate_eval_set_v7', '"lifecycle": "post_run"'),
                ('evaluation.validate_eval_set_v7_candidate', '"lifecycle": "post_run"'),
                ('evaluation.validate_v7_first_formal_results', '"status": "gate_failed"'),
            ):
                completed = subprocess.run([sys.executable, '-m', module], cwd=repo, env=environment, capture_output=True, text=True)
                self.assertEqual(completed.returncode, 0, completed.stderr)
                self.assertIn(expected, completed.stdout)
            execute = subprocess.run([sys.executable, '-m', 'evaluation.execute_v7_first_formal', '--execute'], cwd=repo, env=environment, capture_output=True, text=True)
            self.assertNotEqual(execute.returncode, 0)
            self.assertIn('v7_first_formal_must_have_zero_prior_outputs', execute.stderr)
            self.assertTrue(validate_v7_first_formal_results()['valid'])
            return
        self.assertFalse(any(path.exists() for path in result_paths)); self.assertFalse(workspace.exists())
        environment = os.environ.copy(); environment.pop('PYTHONPATH', None)
        for key in ('CONTINUITY_PROVIDER', 'CONTINUITY_MODEL', 'CONTINUITY_BASE_URL', 'CONTINUITY_API_KEY'):
            environment.pop(key, None)
        command = [sys.executable, '-m', 'evaluation.execute_v7_first_formal']
        dry_run = subprocess.run(command, cwd=repo, env=environment, capture_output=True, text=True)
        self.assertEqual(dry_run.returncode, 0, dry_run.stderr)
        summary = json.loads(dry_run.stdout)
        self.assertEqual((summary['planned_provider_calls'], summary['real_provider_calls']), (30, 0))
        execute = subprocess.run([*command, '--execute'], cwd=repo, env=environment, capture_output=True, text=True)
        self.assertNotEqual(execute.returncode, 0)
        self.assertIn('v7_real_provider_authorization_required', execute.stderr)
        current = json.loads(plan_path.read_text(encoding='utf-8'))
        self.assertEqual((current['provider_calls'], current['formal_run_executed']), (0, False))
        self.assertFalse(any(path.exists() for path in result_paths)); self.assertFalse(workspace.exists())

    def test_v7_real_execution_preconditions_and_fake_30_call_assembly_never_touch_formal_paths(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        if (repo / 'evaluation/results/v7-first-formal-post-run-integrity.json').exists():
            self.assertTrue(validate_v7_first_formal_results()['valid'])
            return
        plan = json.loads((repo / 'evaluation/manifests/eval-v7-first-formal-plan.json').read_text(encoding='utf-8'))
        formal_results = [repo / value for value in plan['planned_output_paths'].values()]
        formal_workspace = repo / 'evaluation/fixture-workspaces/scc-web-demo-eval-v7-first-formal'
        self.assertFalse(any(path.exists() for path in formal_results))
        self.assertFalse(formal_workspace.exists())
        for field, value in (('formal_run_executed', True), ('provider_calls', 1)):
            invalid = copy.deepcopy(plan); invalid[field] = value
            with self.assertRaisesRegex(RuntimeError, 'v7_real_provider_authorization_required'):
                assert_v7_real_execution_preconditions(plan=invalid)
        authorized = copy.deepcopy(plan); authorized['real_provider_authorization_received'] = True; authorized['status'] = 'approved_for_formal_run'
        formal_for_authorized_plan = validate_v7_formal_freeze(plan_payload=authorized)
        self.assertEqual((formal_for_authorized_plan['status'], formal_for_authorized_plan['real_provider_authorization_received']), ('approved_for_formal_run', True))
        config, formal = assert_v7_real_execution_preconditions(plan=authorized)
        self.assertEqual((config.evaluation_id, config.case_set_path, config.manifest_path, config.result_prefix, planned_provider_call_count(), formal['formal_result_count'], formal['formal_workspace_count']), ('scc-web-demo-eval-v7-first-formal', repo / 'evaluation/case_sets/eval-set-v7.json', repo / 'evaluation/manifests/eval-set-v7-manifest.json', 'eval-v7-first-formal', 30, 0, 0))
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = pathlib.Path(temporary)
            fake_config = build_v7_run_config(checkpoint_path=temporary_root / 'checkpoint.json')
            provider = DeterministicV7NoIssueProvider()
            outcome = execute_formal_run(fake_config, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary_root / 'workspaces', provider=provider, write_artifacts=False, formal_run_kind='v7_fake_contract', abort_after_first_transport_failure=True)
            execution = outcome['report']['run_metadata']['provider_execution']
            self.assertEqual((provider.calls, execution['provider_run_records'], execution['actual_provider_http_attempts']), (30, 30, 30))
        self.assertFalse(any(path.exists() for path in formal_results))
        self.assertFalse(formal_workspace.exists())

    def test_v7_pre_execution_rejects_injected_output_workspace_and_freeze_failures_before_provider_setup(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        if (repo / 'evaluation/results/v7-first-formal-post-run-integrity.json').exists():
            self.assertTrue(validate_v7_first_formal_results()['valid'])
            return
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            output = root / 'fixed-output.json'; output.write_text('{}', encoding='utf-8')
            with self.assertRaisesRegex(RuntimeError, 'v7_first_formal_must_have_zero_prior_outputs'):
                assert_v7_zero_formal_output_paths(output_paths=(output,), workspace=root / 'workspace')
            output.unlink(); workspace = root / 'workspace'; workspace.mkdir()
            with self.assertRaisesRegex(RuntimeError, 'v7_first_formal_must_have_zero_prior_outputs'):
                assert_v7_zero_formal_output_paths(output_paths=(output,), workspace=workspace)
        repo = pathlib.Path(__file__).resolve().parents[2]
        authorized = json.loads((repo / 'evaluation/manifests/eval-v7-first-formal-plan.json').read_text(encoding='utf-8'))
        authorized['real_provider_authorization_received'] = True; authorized['status'] = 'approved_for_formal_run'
        with self.assertRaisesRegex(RuntimeError, 'formal_v7_case_set_not_byte_identical_to_candidate'):
            assert_v7_real_execution_preconditions(plan=authorized, formal_validator=lambda **_: (_ for _ in ()).throw(RuntimeError('formal_v7_case_set_not_byte_identical_to_candidate')))
        for auth, status in ((True, 'awaiting_real_provider_authorization'), (False, 'approved_for_formal_run')):
            invalid = copy.deepcopy(authorized); invalid['real_provider_authorization_received'] = auth; invalid['status'] = status
        with self.assertRaisesRegex(ValueError, 'v7_formal_plan_frozen_authorization_state_invalid'):
            validate_v7_formal_plan(invalid)
        manifest = json.loads((repo / 'evaluation/manifests/eval-set-v7-manifest.json').read_text(encoding='utf-8'))
        manifest['approval']['real_provider_authorization_received'] = True
        with self.assertRaisesRegex(ValueError, 'formal_v7_manifest_approval_or_execution_boundary_invalid'):
            validate_v7_formal_freeze(manifest_payload=manifest)
        integrity = json.loads((repo / 'evaluation/manifests/eval-set-v7-freeze-integrity.json').read_text(encoding='utf-8'))
        integrity['real_provider_authorization_received'] = True
        with self.assertRaisesRegex(ValueError, 'formal_v7_freeze_integrity_schema_invalid'):
            validate_v7_formal_freeze(integrity_payload=integrity)

    def test_v7_retained_scan_detects_temporary_result_and_sqlite_sensitive_fields(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = pathlib.Path(temporary)
            payload = root / 'retained.json'
            payload.write_text(json.dumps({'raw_provider_body': 'sk-abcdef123456'}), encoding='utf-8')
            database = root / 'demo.sqlite3'
            connection = sqlite3.connect(database)
            try:
                connection.execute('CREATE TABLE retained (api_key TEXT, note TEXT)')
                connection.execute('INSERT INTO retained VALUES (?, ?)', ('nonempty-but-not-echoed', 'safe'))
                connection.commit()
            finally:
                connection.close()
            result = scan_v7_retained(result_paths=(payload,), database_paths=(database,))
        self.assertEqual((result['result_files'], result['retained_sqlite_count']), (1, 1))
        self.assertFalse(result['clean'])
        self.assertGreaterEqual(result['secret_value_hits'], 1)
        self.assertGreaterEqual(result['nonzero_sensitive_fields'], 2)

    def test_v8_candidate_is_isolated_not_run_and_fake_preflight_complete(self):
        result = validate_v8_all()
        self.assertEqual((result['lifecycle'], result['status'], result['formal_run_executed'], result['provider_calls'], result['real_provider_calls'], result['case_set']['class_counts']), ('post_run', 'gate_failed', True, 30, 30, {'conflict': 8, 'no_conflict': 8, 'insufficient_evidence': 8}))
        self.assertEqual(result['case_set']['designated_category_mismatch_case_ids'], ['v8-dusk-viaduct-conflict-relationship', 'v8-flint-garden-conflict-location_action', 'v8-opal-nursery-conflict-timeline'])
        self.assertEqual((result['formal_plan']['formal_input_count'], result['formal_plan']['formal_result_count'], result['formal_plan']['formal_workspace_count']), (8, 8, 24))
        readiness = validate_v8_formal_readiness()
        self.assertEqual((readiness['lifecycle'], readiness['formal_result_status'], readiness['formal_input_count'], readiness['formal_result_count'], readiness['formal_workspace_count']), ('post_run', 'gate_failed', 8, 8, 24))
        preflight = preflight_v8_candidate()
        self.assertEqual((preflight['case_count'], preflight['retrieval_expected_evidence_hit_at_5'], preflight['evidence_parseable'], preflight['source_lineage_resolved'], preflight['account_project_isolated'], preflight['real_provider_calls'], preflight['quality_scored']), (24, 24, 24, 24, 24, 0, False))
        mutated = copy.deepcopy(load_v8_candidate()); mutated['cases'][0]['expected_evidence'][0]['body_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'v8_candidate_expected_evidence_unresolvable'):
            validate_v8_candidate_case_set(mutated)
        extra_designated = copy.deepcopy(load_v8_candidate()); extra_designated['cases'][1]['challenge_tags'].append('category_mismatch_regression')
        with self.assertRaisesRegex(ValueError, 'v8_candidate_quota_or_boundary_coverage_invalid'):
            validate_v8_candidate_case_set(extra_designated)
        missing_designated = copy.deepcopy(load_v8_candidate()); missing_designated['cases'][0]['challenge_tags'].remove('category_mismatch_regression')
        with self.assertRaisesRegex(ValueError, 'v8_candidate_quota_or_boundary_coverage_invalid'):
            validate_v8_candidate_case_set(missing_designated)

    def test_v8_post_run_freeze_and_execute_gates_remain_offline_and_fail_closed(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        formal = validate_v8_formal_freeze()
        self.assertEqual((formal['lifecycle'], formal['formal_result_status'], formal['formal_input_count'], formal['formal_result_count'], formal['formal_workspace_count'], formal['provider_calls']), ('post_run', 'gate_failed', 8, 8, 24, 30))
        dry_run = v8_fake_only_dry_run()
        self.assertEqual((dry_run['formal_status'], dry_run['planned_provider_calls'], dry_run['real_provider_calls'], dry_run['quality_scored']), ('formal_run_completed', 30, 0, False))
        result_paths = [repo / value for value in json.loads((repo / 'evaluation/manifests/eval-v8-first-formal-plan.json').read_text(encoding='utf-8'))['planned_output_paths'].values()]
        workspace_paths = sorted((repo / 'evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal').glob('*/runtime/data/demo.sqlite3'))
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in [*result_paths, *workspace_paths]}
        with mock.patch.object(v8_runner, 'DeepSeekProvider', side_effect=AssertionError('provider_must_not_initialize')):
            with self.assertRaisesRegex(RuntimeError, 'v8_first_formal_must_have_zero_prior_outputs'):
                assert_v8_real_execution_preconditions()
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})
        self.assertTrue((repo / 'evaluation/case_sets/eval-set-v8.json').exists())
        self.assertTrue((repo / 'evaluation/manifests/eval-set-v8-manifest.json').exists())
        self.assertTrue((repo / 'evaluation/manifests/eval-set-v8-freeze-integrity.json').exists())
        self.assertEqual(len(workspace_paths), 24)

    def test_v8_prompt_version_mismatch_rejects_before_provider_or_sqlite_initialization(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        workspace_paths = sorted((repo / 'evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal').glob('*/runtime/data/demo.sqlite3'))
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in workspace_paths}
        plan = json.loads((repo / 'evaluation/manifests/eval-v8-first-formal-plan.json').read_text(encoding='utf-8'))
        plan.update({'controller_candidate_gate_passed': True, 'formal_inputs_frozen': True, 'real_provider_authorization_received': True, 'formal_run_executed': False, 'provider_calls': 0, 'status': 'approved_for_formal_run'})
        with mock.patch.object(v8_runner.continuity_engine, 'PROMPT_VERSION', 'unexpected-prompt-version'), mock.patch.object(v8_runner, 'DeepSeekProvider', side_effect=AssertionError('provider_must_not_initialize')):
            with self.assertRaisesRegex(RuntimeError, 'v8_formal_prompt_version_mismatch'):
                v8_runner.assert_real_execution_preconditions(plan=plan, formal_validator=lambda **_: self.fail('formal_validator_must_not_run'))
        self.assertEqual(len(workspace_paths), 24)
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})

    def test_v8_post_run_cli_integrity_tamper_and_reexecution_guards(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        plan = json.loads((repo / 'evaluation/manifests/eval-v8-first-formal-plan.json').read_text(encoding='utf-8'))
        artifacts = [repo / value for value in plan['planned_output_paths'].values()]
        databases = sorted((repo / 'evaluation/fixture-workspaces/scc-web-demo-eval-v8-first-formal').glob('*/runtime/data/demo.sqlite3'))
        before = {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in [*artifacts, *databases]}
        environment = os.environ.copy(); environment.pop('PYTHONPATH', None)
        for key in ('CONTINUITY_PROVIDER', 'CONTINUITY_MODEL', 'CONTINUITY_BASE_URL', 'CONTINUITY_API_KEY'):
            environment.pop(key, None)
        for module, expected in (
            ('evaluation.validate_eval_set_v8_candidate', '"lifecycle": "post_run"'),
            ('evaluation.validate_eval_set_v8', '"lifecycle": "post_run"'),
            ('evaluation.validate_v8_first_formal_results', '"status": "gate_failed"'),
        ):
            completed = subprocess.run([sys.executable, '-m', module], cwd=repo, env=environment, capture_output=True, text=True)
            self.assertEqual(completed.returncode, 0, completed.stderr)
            self.assertIn(expected, completed.stdout)
        execute = subprocess.run([sys.executable, '-m', 'evaluation.execute_v8_first_formal', '--execute'], cwd=repo, env=environment, capture_output=True, text=True)
        self.assertNotEqual(execute.returncode, 0)
        self.assertIn('v8_first_formal_must_have_zero_prior_outputs', execute.stderr)
        with mock.patch('evaluation.validate_v8_first_formal_results.sha256_file', return_value='0' * 64):
            with self.assertRaisesRegex(ValueError, 'v8_post_artifact_hash_invalid'):
                validate_v8_first_formal_results()
        self.assertTrue(validate_v8_first_formal_results()['valid'])
        self.assertEqual(before, {path: hashlib.sha256(path.read_bytes()).hexdigest() for path in before})

    def test_v5_bad_case_duplicate_and_quota_mutations_fail_closed(self):
        duplicate = copy.deepcopy(load_v5_candidate())
        duplicate['cases'][1]['case_id'] = duplicate['cases'][0]['case_id']
        with self.assertRaisesRegex(ValueError, 'v5_candidate_duplicate_case_or_semantic_identifier'):
            validate_v5_candidate_case_set(duplicate)
        wrong_quota = copy.deepcopy(load_v5_candidate())
        wrong_quota['cases'][0]['expected_class'] = 'no_conflict'
        wrong_quota['cases'][0]['expected_category'] = None
        with self.assertRaisesRegex(ValueError, 'v5_candidate_global_quota_invalid'):
            validate_v5_candidate_case_set(wrong_quota)

    def test_v5_bad_case_category_evidence_and_lineage_mutations_fail_closed(self):
        wrong_category = copy.deepcopy(load_v5_candidate())
        wrong_category['cases'][0]['expected_category'] = 'unsupported_category'
        with self.assertRaisesRegex(ValueError, 'v5_candidate_conflict_category_invalid'):
            validate_v5_candidate_case_set(wrong_category)
        missing_evidence = copy.deepcopy(load_v5_candidate())
        missing_evidence['cases'][0]['expected_evidence'][0]['chapter_number'] = 999
        with self.assertRaisesRegex(ValueError, 'v5_candidate_expected_evidence_unresolvable'):
            validate_v5_candidate_case_set(missing_evidence)
        cross_corpus = copy.deepcopy(load_v5_candidate())
        cross_corpus['cases'][0]['source_lineage'][0]['corpus_key'] = 'reed_foundry'
        with self.assertRaisesRegex(ValueError, 'v5_candidate_cross_corpus_or_missing_source_lineage'):
            validate_v5_candidate_case_set(cross_corpus)

    def test_v5_bad_case_manifest_challenge_and_false_run_fields_fail_closed(self):
        repo = pathlib.Path(__file__).resolve().parents[2]
        manifest = json.loads((repo / 'evaluation/manifests/eval-set-v5-candidate-manifest.json').read_text(encoding='utf-8'))
        bad_hash = copy.deepcopy(manifest)
        bad_hash['case_set']['canonical_sha256'] = '0' * 64
        with self.assertRaisesRegex(ValueError, 'v5_candidate_manifest_hash_or_scope_invalid'):
            validate_v5_candidate_manifest(manifest=bad_hash)
        weak_challenges = copy.deepcopy(load_v5_candidate())
        for case in weak_challenges['cases']:
            if 'conflicting_sources' in case['challenge_tags']:
                case['challenge_tags'].remove('conflicting_sources')
        with self.assertRaisesRegex(ValueError, 'v5_candidate_challenge_coverage_invalid'):
            validate_v5_candidate_case_set(weak_challenges)
        false_case_run = copy.deepcopy(load_v5_candidate())
        false_case_run['formal_run_executed'] = True
        false_case_run['provider_calls'] = 1
        with self.assertRaisesRegex(ValueError, 'v5_candidate_formal_or_provider_field_false_report'):
            validate_v5_candidate_case_set(false_case_run)
        false_manifest_run = copy.deepcopy(manifest)
        false_manifest_run['provider_calls'] = 1
        with self.assertRaisesRegex(ValueError, 'v5_candidate_manifest_identity_or_boundary_invalid'):
            validate_v5_candidate_manifest(manifest=false_manifest_run)
        plan = json.loads((repo / 'evaluation/manifests/eval-v5-first-formal-plan.json').read_text(encoding='utf-8'))
        false_plan_run = copy.deepcopy(plan)
        false_plan_run['formal_run_executed'] = True
        false_plan_run['provider_calls'] = 1
        with self.assertRaisesRegex(ValueError, 'v5_formal_plan_false_report'):
            validate_v5_formal_plan(false_plan_run)

    def test_v5_bad_case_prior_text_identifier_and_fixture_reuse_fail_closed(self):
        prior_case = load_v4_candidate()['cases'][0]
        reused_text = copy.deepcopy(load_v5_candidate())
        reused_text['cases'][0]['target_draft'] = prior_case['target_draft']
        with self.assertRaisesRegex(ValueError, 'v5_candidate_prior_target_text_reuse'):
            validate_v5_candidate_case_set(reused_text)
        reused_identifier = copy.deepcopy(load_v5_candidate())
        reused_identifier['cases'][0]['case_id'] = prior_case['case_id']
        with self.assertRaisesRegex(ValueError, 'v5_candidate_prior_identifier_or_core_fact_reuse'):
            validate_v5_candidate_case_set(reused_identifier)
        corpora = {key: load_corpus(key, V5_CORPUS_PATHS) for key in V5_CORPUS_PATHS}
        corpora['ember_observatory']['chapters'][0]['body'] = load_corpus('mist_jetty', V4_CORPUS_PATHS)['chapters'][0]['body']
        with self.assertRaisesRegex(ValueError, 'v5_candidate_prior_evidence_text_reuse'):
            validate_v5_corpora(corpora)

    def test_v5_incremental_metrics_and_gate_are_backward_compatible(self):
        def row(expected_class, expected_category=None, mismatch=False):
            conflict = expected_class == 'conflict'
            return {
                'expected_class': expected_class, 'predicted_class': expected_class,
                'expected_category': expected_category, 'predicted_category': expected_category,
                'retrieval_hit_at_5': True, 'cited_evidence_expected_count': 2 if conflict else 0,
                'cited_evidence_count': 2 if conflict else 0, 'resolvable_evidence_count': 2 if conflict else 0,
                'schema_valid': True, 'latency_ms': 1, 'input_tokens': 1, 'output_tokens': 1, 'cost_cny': 0,
                'challenge_tags': ['category_mismatch_regression'] if mismatch else [],
                'requires_multiple_direct_evidence': conflict,
                'expected_evidence_count': 2 if conflict else 0,
                'cited_expected_evidence_unique_count': 2 if conflict else 0,
                'expected_evidence_full_set_cited': True if conflict else None,
            }
        rows = [row('conflict', category, True) for category in ('attribute', 'timeline', 'event_status')] + [row('no_conflict'), row('insufficient_evidence')]
        metrics = aggregate(rows)
        thresholds = json.loads((pathlib.Path(__file__).resolve().parents[2] / 'evaluation/manifests/eval-set-v5-candidate-manifest.json').read_text(encoding='utf-8'))['required_thresholds']
        passed, checks = gate(metrics, {'validity': 1}, thresholds)
        self.assertTrue(passed)
        self.assertTrue(all(checks.values()))
        self.assertEqual(metrics['designated_category_mismatch_regression'], {'correct': 3, 'total': 3})
        self.assertEqual((metrics['conflict_category_accuracy'], metrics['expected_evidence_recall'], metrics['multi_direct_evidence_full_set_recall']), (1.0, 1.0, 1.0))

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
        self.assertEqual((result['source_files'], result['temporary_databases'], result['unresolved']), (25, 25, 0))

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

    def test_terminal_failures_never_establish_quality_stability(self):
        rows = [
            {'predicted_class': 'no_conflict', 'category_severity': None, 'evidence_ids': [], 'explanation_sha256': 'same', 'terminal_status': 'failed'},
            {'predicted_class': 'no_conflict', 'category_severity': None, 'evidence_ids': [], 'explanation_sha256': 'same', 'terminal_status': 'failed'},
            {'predicted_class': 'no_conflict', 'category_severity': None, 'evidence_ids': [], 'explanation_sha256': 'same', 'terminal_status': 'failed'},
        ]
        result = stability(rows)
        self.assertEqual(result['terminal_failure_count'], 3)
        self.assertFalse(result['quality_stability_established'])
        self.assertFalse(any(result[key] for key in ('class_decision_stability', 'category_severity_stability', 'evidence_id_set_stability', 'exact_explanation_text_stability')))

    def test_v5_first_transport_failure_aborts_after_one_provider_run(self):
        class TransportFailureProvider:
            label = 'transport-failure-test-provider'
            model_label = 'transport-failure-test-model'
            available = True
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                raise ProviderFailure()

        repo = pathlib.Path(__file__).resolve().parents[2]
        provider = TransportFailureProvider()
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v5-abort-contract-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            config = build_run_config(
                'scc-web-demo-eval-v5-abort-contract',
                'evaluation/case_sets/eval-set-v5.json',
                'evaluation/manifests/eval-set-v5-manifest.json',
                'v5-abort-contract-output',
                str((temporary / 'checkpoint.json').relative_to(repo)).replace('\\', '/'),
            )
            outcome = execute_formal_run(
                config,
                runtime_mode=EVALUATION_FIXTURE_MODE,
                fixture_work_root_path=temporary / 'work',
                provider=provider,
                write_artifacts=False,
                run_stability=True,
                formal_run_kind='first_valid_formal',
                abort_after_first_transport_failure=True,
            )
        self.assertEqual(provider.calls, 1)
        self.assertEqual(outcome['report']['status'], 'aborted_valid_run_attempt')
        self.assertEqual(outcome['report']['abort_reason'], 'provider_error')
        self.assertEqual(len(outcome['report']['formal_case_results']), 1)
        self.assertEqual(outcome['stability']['rows'], [])
        self.assertEqual(outcome['report']['gate_checks'], {'quality_gate_evaluated': False})

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
                    first_run_id = connection.execute("SELECT r.id FROM v2_runs r JOIN v2_projects p ON p.id=r.project_id JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=? AND r.result_origin='provider'",(runner_account_name(case['case_id']),)).fetchone()
                resumed = FormalCheckpoint(checkpoint_path, 'fixture-case-set')
                with TestClient(app) as client:
                    result, state = run_case(resumed, client, case, ApiResponseScanner())
                with app.state.database.connection() as connection:
                    final_account_count = connection.execute('SELECT COUNT(*) FROM v2_users WHERE account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                    final_project_count = connection.execute('SELECT COUNT(*) FROM v2_projects p JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=?',(runner_account_name(case['case_id']),)).fetchone()[0]
                    final_revision = connection.execute('SELECT d.revision FROM v2_drafts d JOIN v2_projects p ON p.id=d.project_id JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=? AND p.seed_key=?',(runner_account_name(case['case_id']),case['seed_key'])).fetchone()[0]
                    final_runs = connection.execute("SELECT COUNT(*) FROM v2_runs r JOIN v2_projects p ON p.id=r.project_id JOIN v2_users u ON u.id=p.user_id WHERE u.account_name=? AND r.result_origin='provider'",(runner_account_name(case['case_id']),)).fetchone()[0]
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

    def test_v5_fixture_runner_accepts_only_frozen_formal_paths_without_writing_results(self):
        class EmptyIssueProvider:
            label = 'v5-fixture-runner-contract-provider'
            model_label = 'v5-fixture-runner-contract-model'
            available = True
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

        repo = pathlib.Path(__file__).resolve().parents[2]
        cases = load_v5_candidate()['cases']
        representatives = [next(case for case in cases if case['corpus_key'] == key) for key in V5_CORPUS_PATHS]
        with tempfile.TemporaryDirectory(dir=repo / 'evaluation' / 'results', prefix='v5-fixture-runner-contract-') as temporary_name:
            temporary = pathlib.Path(temporary_name)
            provider = EmptyIssueProvider()
            outcome = execute_formal_run(self._v5_fixture_config(temporary), runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=temporary / 'work', provider=provider, write_artifacts=False, run_stability=False, cases_override=representatives)
            self.assertEqual((len(outcome['report']['formal_case_results']), provider.calls), (4, 4))
            self.assertTrue(all(row['retrieval_hit_at_5'] for row in outcome['report']['formal_case_results']))
            self.assertFalse(any(temporary.glob('fixture-v5-contract-output-*')))

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
            def __init__(self): self.calls = 0
            def evaluate(self, request):
                self.calls += 1
                return ProviderResult({'issues': []}, input_tokens=1, output_tokens=1, latency_ms=1)

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
            v5_candidate = build_run_config('scc-web-demo-eval-v5-fixture-negative', 'evaluation/case_sets/eval-set-v5-candidate.json', 'evaluation/manifests/eval-set-v5-candidate-manifest.json', 'fixture-v5-negative-output', str((temporary / 'v5-candidate-checkpoint.json').relative_to(repo)).replace('\\', '/'))
            v5_work = temporary / 'v5-work'
            v5_provider = EmptyIssueProvider()
            with self.assertRaisesRegex(RuntimeError, 'evaluation_manifest_not_approved'):
                execute_formal_run(v5_candidate, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=v5_work, provider=v5_provider, write_artifacts=False, run_stability=False)
            self.assertFalse(v5_work.exists())
            self.assertEqual(v5_provider.calls, 0)
            approved = self._fixture_config(temporary)
            with self.assertRaisesRegex(RuntimeError, 'fixture_mode_requires_work_root_and_rejects_base_url'):
                execute_formal_run(approved, runtime_mode=EVALUATION_FIXTURE_MODE, base_url='http://127.0.0.1:8066', fixture_work_root_path=work, provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
            with self.assertRaisesRegex(RuntimeError, 'fixture_work_root_forbidden'):
                execute_formal_run(approved, runtime_mode=EVALUATION_FIXTURE_MODE, fixture_work_root_path=repo / 'runtime', provider=EmptyIssueProvider(), write_artifacts=False, run_stability=False)
