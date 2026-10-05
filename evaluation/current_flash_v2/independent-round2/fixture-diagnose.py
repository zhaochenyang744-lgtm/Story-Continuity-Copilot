"""Independent saved-fixture audit. Only manifest-listed G03 DBs opened read-only."""
import ast
import copy
import hashlib
import json
import pathlib
import smtplib
import socket
import sqlite3
import sys

sys.dont_write_bytecode = True
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
BASE = HERE.parent
RUN = BASE / 'runs/flash-v2-20260926-01'
attempts = []
def deny(*args, **kwargs):
    attempts.append('network_or_smtp')
    raise AssertionError('Network and SMTP forbidden')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
smtplib.SMTP = deny
smtplib.SMTP_SSL = deny
def read(path):
    return json.loads(path.read_text(encoding='utf-8'))
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()
def canonical(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

frozen = read(BASE / 'frozen-inputs.json')
cases = read(BASE / 'cases.json')
corpus = read(BASE / 'g03-corpus.json')
workspace = read(RUN / 'workspace-manifest.json')
case_files = sorted((RUN / 'cases').glob('*.json'))
watched = [ROOT / path for path in frozen['source_hashes']] + case_files + [BASE / 'frozen-inputs.json', RUN / 'start.json', RUN / 'workspace-manifest.json', RUN / 'summary.json']
before = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
assert all(before[p] == h for p, h in frozen['source_hashes'].items())
assert read(RUN / 'start.json')['frozen_manifest_sha256'] == sha(BASE / 'frozen-inputs.json')
expected_root = (ROOT / 'artifacts/current_flash_v2/flash-v2-20260926-01').resolve()
assert pathlib.Path(workspace['root']).resolve() == expected_root
db_files = {}
for entry in workspace['database_files']:
    path = (expected_root / entry['path']).resolve()
    assert path.is_relative_to(expected_root)
    assert path.is_file() and path.stat().st_size == entry['bytes'] and sha(path) == entry['sha256']
    db_files[entry['path'].split('/')[0]] = path
assert len(db_files) == 8
db_before = {k: sha(v) for k, v in db_files.items()}
original_connect = sqlite3.connect
allowed_uris = {p.as_uri() + '?mode=ro&immutable=1' for k, p in db_files.items() if k.startswith('g03-')}
opened = []
def guarded_connect(database_uri, *args, **kwargs):
    assert database_uri in allowed_uris and kwargs.get('uri') is True
    opened.append(database_uri)
    return original_connect(database_uri, *args, **kwargs)
sqlite3.connect = guarded_connect

# Load only two pure functions, not the runner's environment/provider setup.
tree = ast.parse((BASE / 'run.py').read_text(encoding='utf-8'))
namespace = {}
nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in {'assert_business_input', 'g03_body'}]
exec(compile(ast.Module(body=nodes, type_ignores=[]), 'isolated_runner_contract_functions', 'exec'), namespace)
assert_business_input = namespace['assert_business_input']
g03_body = namespace['g03_body']
case_defs = {c['id']: c for family in ('g02', 'g03') for c in cases[family]}
all_rows = []
g03_rows = []
memory_id = 'fixture-memory-flash_v2_target-1'
target_id = 'fixture-span-flash_v2_target-1'
other_id = 'fixture-span-flash_v2_target-2'
fact = '星钥始终由乔霁保管。'
for file in case_files:
    record = read(file)
    case = case_defs[record['case_id']]
    assert record['input_sha256'] == canonical(case)
    assert len(record['business_requests']) == len(record['model_outputs']) == 1
    captured = record['business_requests'][0]
    request = captured['business_request']
    assert captured['business_request_sha256'] == canonical(request)
    assert captured['output_schema_sha256'] == canonical(request['output_schema'])
    assert record['model_outputs'][0]['business_request_sha256'] == captured['business_request_sha256']
    all_rows.append({'case_id': record['case_id'], 'input_and_request_hashes_match': True})
    if record['family'] != 'g03':
        continue
    assert_business_input(case, request)
    spans = {s['id']: s for s in request['layers']['written']['source_spans']}
    memory = request['layers']['confirmed']['memory_records']
    assert len(memory) == 1 and memory[0] == {'id': memory_id, 'memory_type': 'dynamic_state', 'subject': '星钥', 'predicate': 'holder', 'value': fact, 'source_span_id': target_id}
    assert request['layers']['written']['draft']['excerpt'] == '' and request['layers']['written']['draft_claims'] == []
    assert len(spans) == 2 and spans[other_id]['body'] == case['other_body']
    full_body = g03_body(case)
    assert record['input']['target_source_body'] == full_body
    assert record['input']['other_source_body'] == case['other_body']
    meta = request['retrieval']['target_source']
    assert meta['original_chars'] == len(full_body)
    assert meta['excerpt_chars'] == len(spans[target_id]['body'])
    assert meta['excerpt_truncated'] == (len(full_body) > 500)
    assert meta['status'] == ('unlocated' if case['mode'] == 'absent' else 'selected')
    if case['mode'] in ('deep', 'other_chapter'):
        assert full_body.index(fact) == 1100 and fact in spans[target_id]['body'] and len(spans[target_id]['body']) == 502
        assert spans[target_id]['body'].strip('…') in full_body
    else:
        assert spans[target_id]['body'] == full_body
    if case['mode'] == 'absent':
        assert fact not in spans[target_id]['body'] and record['product']['analysis']['evidence_status'] == 'insufficient' and record['product']['analysis']['items'] == []
    else:
        assert record['product']['analysis']['evidence_status'] == 'supported'
    chapter_checks = []
    for output_kind, payload in [('first', record['model_outputs'][0]['business_json']), ('final', record['product']['analysis'])]:
        for item in payload['items']:
            if item['area'] == 'chapter':
                matched = [e['source_id'] for e in item['evidence'] if e['source_type'] == 'source_span' and e['source_id'] in spans and spans[e['source_id']]['chapter_id'] == item['target_id']]
                assert matched
                chapter_checks.append({'output': output_kind, 'chapter_id': item['target_id'], 'own_chapter_sources': matched})
    uri = db_files[case['id']].as_uri() + '?mode=ro&immutable=1'
    connection = sqlite3.connect(uri, uri=True)
    connection.row_factory = sqlite3.Row
    try:
        db_memory = [dict(r) for r in connection.execute('SELECT id,memory_type,subject,predicate,value,source_span_id FROM v2_memory_records')]
        assert db_memory == memory
        db_spans = [dict(r) for r in connection.execute('SELECT id,chapter_id,body,source_revision FROM v2_source_spans ORDER BY id')]
        db_chapters = [dict(r) for r in connection.execute('SELECT id,chapter_number,body,source_revision FROM v2_chapters ORDER BY chapter_number')]
        assert len(db_spans) == len(db_chapters) == 2
        db_span_by_id = {s['id']: s for s in db_spans}
        assert db_span_by_id[target_id]['body'] == full_body and db_span_by_id[other_id]['body'] == case['other_body']
        mismatches = [{'chapter_id': c['id'], 'chapter_body': c['body'], 'span_id': s['id'], 'span_chars': len(s['body']),
                       'span_body_in_chapter': s['body'] in c['body'], 'chapter_revision': c['source_revision'], 'span_revision': s['source_revision']}
                      for c in db_chapters for s in db_spans if s['chapter_id'] == c['id'] and s['body'] != c['body']]
    finally:
        connection.close()
    bad_type = copy.deepcopy(request)
    bad_type['layers']['confirmed']['memory_records'][0]['memory_type'] = 'not_a_memory_type'
    try:
        assert_business_input(case, bad_type)
        invalid_type_rejected = False
    except RuntimeError:
        invalid_type_rejected = True
    g03_rows.append({'case_id': case['id'], 'full_target_chars': len(full_body), 'target_fact_offset': full_body.find(fact),
                     'supplied_target_chars': len(spans[target_id]['body']), 'other_chapter_exactly_supplied': True,
                     'memory_complete_matches': True, 'first_and_final_chapter_bindings': chapter_checks,
                     'product_evidence_status': record['product']['analysis']['evidence_status'],
                     'db_chapter_source_mismatches': mismatches, 'preflight_rejects_invalid_memory_type': invalid_type_rejected})

after = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
db_after = {k: sha(v) for k, v in db_files.items()}
assert before == after and db_before == db_after and not attempts
report = {'scope': 'saved snapshots; only 4 manifest-allowlisted G03 SQLite files opened mode=ro immutable=1; no Provider',
          'all_record_hashes': all_rows, 'g03': g03_rows, 'source_and_run_hashes_before': before, 'source_and_run_hashes_after': after,
          'database_hashes_before': db_before, 'database_hashes_after': db_after, 'database_readonly_open_count': len(opened),
          'network_smtp_attempts': attempts}
with (HERE / 'fixture-results.json').open('x', encoding='utf-8') as stream:
    json.dump(report, stream, ensure_ascii=False, indent=2)
print(json.dumps({'records_verified': len(all_rows), 'g03': g03_rows, 'all_hashes_unchanged': True, 'readonly_db_count': len(opened)}, ensure_ascii=False))
