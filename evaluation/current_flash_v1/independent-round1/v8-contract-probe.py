"""Pure validation counterfactuals; fixture files remain immutable."""
import copy
import hashlib
import json
import os
import pathlib
import smtplib
import socket
import sqlite3
import sys

sys.dont_write_bytecode = True
os.environ['SCC_DISABLE_DEFAULT_APP'] = '1'
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
io_attempts = []
def deny(*args, **kwargs):
    io_attempts.append('blocked')
    raise AssertionError('No network, SMTP, database or Provider permitted')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
smtplib.SMTP = deny
smtplib.SMTP_SSL = deny
sqlite3.connect = deny
sys.path.insert(0, str(ROOT / 'backend'))
from app.engine import ContinuityEngine
class NoProvider:
    evaluate = deny
engine = ContinuityEngine(NoProvider())
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
cases = read(ROOT / 'evaluation/case_sets/eval-set-v8.json')['cases']
frozen = read(ROOT / 'evaluation/current_flash_v1/frozen-inputs.json')['source_hashes']
before = {path: sha(ROOT / path) for path in frozen}
assert before == frozen
results = []
for case_id in ('v8-dusk-viaduct-conflict-relationship', 'v8-sable-tideglass-conflict-world_rule'):
    case = next(c for c in cases if c['case_id'] == case_id)
    key = case['corpus_key']
    corpus = read(ROOT / f"evaluation/fixtures/eval-v8-{key.replace('_', '-')}.json")
    spans = [{'id': f'fixture-span-{key}-{c["chapter_number"]}', 'chapter_id': f'fixture-chapter-{key}-{c["chapter_number"]}',
              'body': c['body'], 'prompt_excerpt': c['body']} for c in corpus['chapters'] if c['chapter_number'] in {e['chapter_number'] for e in case['expected_evidence']}]
    memory = [{**{k: m[k] for k in ('memory_type', 'subject', 'predicate', 'value')},
               'id': f'fixture-memory-{key}-{i}', 'source_span_id': f'fixture-span-{key}-{m["source"]["chapter_number"]}'}
              for i, m in enumerate(corpus['memory'], 1)]
    rule_memory = next(m for m in memory if m['source_span_id'] == spans[0]['id'])
    data = {'draft': {'id': 'synthetic-draft', 'revision': 1, 'body': case['target_draft']},
            'claims': [{'id': 'claim-1', 'text': case['target_draft'], 'allowed_evidence': spans}], 'memory': memory}
    issue = {'claim_span_id': 'claim-1', 'status': 'conflict', 'nature': 'confirmed_conflict',
             'category': case['expected_category'], 'severity': 'high',
             'explanation': 'The frozen draft contradicts the combined rule and recorded observation.',
             'reasoning': 'Both frozen direct evidence spans are supplied in full for this validation-only probe.',
             'temporal_basis': {'claim_anchor': None, 'evidence_anchor': None, 'relation': 'timeless_rule'},
             'evidence': [{'chapter_id': s['chapter_id'], 'span_id': s['id'], 'relation': 'contradicts',
                           'sufficiency': 'sufficient', 'related_memory_ids': [rule_memory['id']] if index == 0 else []}
                          for index, s in enumerate(spans)],
             'evidence_chain': [{'span_id': s['id'], 'role': 'prior_state'} for s in spans],
             'suggested_revision': None, 'available_actions': [], 'proposed_memory_change': None}
    variants = []
    for mode in ('full_evidence_original_memory', 'full_evidence_predicate_only_counterfactual', 'full_evidence_possible_conflict_control'):
        bound = copy.deepcopy(data)
        payload = {'issues': [copy.deepcopy(issue)]}
        if mode == 'full_evidence_predicate_only_counterfactual':
            next(m for m in bound['memory'] if m['id'] == rule_memory['id'])['predicate'] = 'rule'
        if mode == 'full_evidence_possible_conflict_control':
            payload['issues'][0]['nature'] = 'possible_conflict'
            payload['issues'][0]['temporal_basis']['relation'] = 'unknown'
        try:
            output = engine.validate(payload, bound)
            verdict = {'accepted': True, 'status': output[0]['status'], 'nature': output[0]['nature']}
        except ValueError as error:
            verdict = {'accepted': False, 'error_type': type(error).__name__, 'error': str(error)}
        variants.append({'mode': mode, 'verdict': verdict})
    assert variants[0]['verdict'].get('error') == 'timeless_rule_unproven'
    assert variants[1]['verdict']['accepted']
    assert variants[2]['verdict']['accepted']
    results.append({'case_id': case_id, 'full_evidence_ids': [s['id'] for s in spans],
                    'original_memory_type_predicates': [[m['memory_type'], m['predicate']] for m in memory], 'variants': variants})
after = {path: sha(ROOT / path) for path in frozen}
assert before == after
assert not io_attempts
report = {'scope': 'synthetic payloads passed to validate only; no Provider execution or story-fixture edit',
          'warning': 'Predicate-only mutation is a mechanical counterfactual, not a semantically valid revised corpus or measured model outcome. possible_conflict can pass the legacy status=conflict score without confirmed_conflict.',
          'results': results, 'hashes_before': before, 'hashes_after': after, 'forbidden_io_attempts': io_attempts}
with (HERE / 'v8-contract-results.json').open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps({'results': results, 'all_hashes_unchanged': True, 'io_attempts': 0}, ensure_ascii=False))
