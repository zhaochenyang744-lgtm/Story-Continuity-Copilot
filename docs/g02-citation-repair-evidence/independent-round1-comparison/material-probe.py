"""Prehandoff snapshot audit. Reads named JSON/code only; no API, DB or Provider."""
from __future__ import annotations
import collections
import copy
import datetime
import hashlib
import json
import pathlib
import re
import socket
import sqlite3
import sys
import types

ROOT = pathlib.Path(__file__).resolve().parents[3]
HERE = pathlib.Path(__file__).resolve().parent
TARGET = ROOT / 'evaluation/current_contract_compare_v1'
sys.dont_write_bytecode = True
sys.path.insert(0, str(ROOT / 'backend'))

def forbidden(*args, **kwargs):
    raise RuntimeError('independent_review_no_network_or_database')

socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
sqlite3.connect = forbidden

named = ['build.py', 'preflight.py', 'cases.json', 'actual-inputs.json', 'score.py',
         'corpora/north_glass.json', 'corpora/harbor_signal.json',
         'corpora/orchard_restoration.json', 'corpora/basalt_observatory.json']
raw = {name: (TARGET / name).read_bytes() for name in named if (TARGET / name).exists()}
dependencies = {name: (ROOT / name).read_bytes() for name in
                ['backend/app/engine.py', 'backend/app/provider.py', 'backend/app/v2_database.py',
                 'evaluation/v2_fixture_loader.py']}
def digest(value):
    return hashlib.sha256(value).hexdigest()
encoding_notes = []
def decode(name):
    try:
        return raw[name].decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        encoding_notes.append({'path': name, 'utf8_error': str(exc), 'diagnostic_decoder_only': 'gbk'})
        return raw[name].decode('gbk')
cases = json.loads(decode('cases.json'))['cases']
corpora = {name.removeprefix('corpora/').removesuffix('.json'): json.loads(decode(name))
           for name in raw if name.startswith('corpora/')}
capture = json.loads(decode('actual-inputs.json')) if raw.get('actual-inputs.json') else None
score = types.ModuleType('independent_candidate_score_snapshot')
score.__file__ = str(TARGET / 'score.py')
exec(compile(decode('score.py'), score.__file__, 'exec'), score.__dict__)
from app.engine import ContinuityEngine
engine = ContinuityEngine(object())

rows = []
for case in cases:
    corpus = corpora[case['corpus_key']]
    chapters = {(x['chapter_number'], x['source_label']): x for x in corpus['chapters']}
    required = [chapters[(x['chapter_number'], x['source_label'])] for x in case['expected_evidence']]
    problems = []
    for declared, chapter in zip(case['expected_evidence'], required):
        if digest(chapter['body'].encode('utf-8')) != declared['body_sha256']:
            problems.append('required_body_hash_mismatch')
    captured = next((x for x in (capture or {}).get('rows', []) if x['case_id'] == case['case_id']), None)
    if captured:
        req = captured['business_request']
        if req['draft']['body'] != case['target_draft'] or req['claims'][0]['text'] != case['target_draft']:
            problems.append('capture_draft_claim_mismatch')
        spans = {x['id']: x for x in req['claims'][0]['allowed_evidence']}
        for chapter in required:
            sid = f"fixture-span-{case['corpus_key']}-{chapter['chapter_number']}"
            actual = spans.get(sid)
            if actual is None:
                problems.append('required_span_missing')
            elif actual['body'] != chapter['body'] or actual.get('prompt_excerpt', actual['body']) != chapter['body']:
                problems.append('required_body_excerpt_mismatch')
        for memory in req['memory']:
            ordinal = int(memory['id'].rsplit('-', 1)[1])
            expected = corpus['memory'][ordinal - 1]
            if any(memory.get(k) != expected[k] for k in ('memory_type','subject','predicate','value')):
                problems.append('captured_memory_field_mismatch')
        data = req
    else:
        data = None
        problems.append('capture_pending')
    row = {'case_id': case['case_id'], 'input_problems': problems}
    if data and case['expected_class'] == 'conflict':
        spans = {x['id']: x for x in data['claims'][0]['allowed_evidence']}
        evidence = []
        for chapter in required:
            sid = f"fixture-span-{case['corpus_key']}-{chapter['chapter_number']}"
            evidence.append({'span_id': sid, 'chapter_id': spans[sid]['chapter_id'],
                             'relation': 'contradicts', 'sufficiency': 'sufficient',
                             'related_memory_ids': [x['id'] for x in data['memory'] if x['source_span_id'] == sid]})
        clock = re.search(r'\d+点', data['claims'][0]['text'])
        temporal = {'relation': 'timeless_rule', 'claim_anchor': None, 'evidence_anchor': None}
        if case['temporal_policy'] == 'same_explicit_time':
            temporal = {'relation': 'explicit_overlap', 'claim_anchor': clock.group() if clock else None,
                        'evidence_anchor': clock.group() if clock else None}
        issue = {'claim_span_id': data['claims'][0]['id'], 'status': 'conflict',
                 'nature': 'confirmed_conflict', 'category': case['expected_category'], 'severity': 'high',
                 'explanation': 'The bound claim conflicts with the required supplied facts.',
                 'reasoning': case['label_reason'], 'temporal_basis': temporal,
                 'evidence': evidence, 'evidence_chain': [{'span_id': x['span_id'], 'role': 'prior_state'} for x in evidence],
                 'suggested_revision': None, 'available_actions': [], 'proposed_memory_change': None}
        try:
            validated = engine.validate({'issues': [issue]}, data)
            row['minimal_validator'] = 'accepted'
            row['engine_output_has_temporal_basis'] = 'temporal_basis' in validated[0]
            row['engine_output_score'] = score.score_one(case, {'status': 'completed', 'issues': validated})
            api_projection = copy.deepcopy(validated)
            api_projection[0]['classification'] = api_projection[0]['status']
            api_projection[0]['status'] = 'open'
            row['api_status_projection_score'] = score.score_one(case, {'status': 'completed', 'issues': api_projection})
        except ValueError as exc:
            row['minimal_validator'] = str(exc)
        possible = copy.deepcopy(issue)
        possible['nature'] = 'possible_conflict'
        row['possible_control'] = score.score_one(case, {'status':'completed','issues':[possible]})
    rows.append(row)

failed_empty = next(x for x in cases if x['expected_class'] == 'no_conflict')
result = {
    'scope':'PREHANDOFF snapshot, not model results or final acceptance',
    'captured_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),
    'provider_calls':0, 'http_calls':0, 'database_connections':0,
    'hashes':{name:digest(value) for name,value in raw.items()},
    'dependency_hashes':{name:digest(value) for name,value in dependencies.items()},
    'encoding_notes':encoding_notes,
    'case_count':len(cases), 'class_counts':dict(collections.Counter(x['expected_class'] for x in cases)),
    'triplet_count':len({(x['corpus_key'],x['axis_index']) for x in cases}), 'corpus_count':len(corpora),
    'multi_evidence_conflict_count':sum(x['expected_class']=='conflict' and len(x['expected_evidence'])>1 for x in cases),
    'multi_evidence_insufficient_count':sum(x['expected_class']=='insufficient_evidence' and len(x['expected_evidence'])>1 for x in cases),
    'failed_empty_control':score.score_one(failed_empty, {'status':'failed','issues':[]}),
    'rows':rows,
    'files_changed_during_probe':[name for name,value in raw.items() if (TARGET/name).read_bytes()!=value],
    'dependencies_changed_during_probe':[name for name,value in dependencies.items() if (ROOT/name).read_bytes()!=value],
}
destination = HERE / 'material-probe-results.json'
with destination.open('x', encoding='utf-8') as handle:
    json.dump(result, handle, ensure_ascii=False, indent=2)
print(json.dumps({'result':str(destination), 'case_count':len(cases),
                  'input_problem_cases':sum(bool(x['input_problems']) for x in rows),
                  'validator_results':{x['case_id']:x['minimal_validator'] for x in rows if 'minimal_validator' in x},
                  'encoding_notes':encoding_notes, 'changed':result['files_changed_during_probe']},ensure_ascii=True))
