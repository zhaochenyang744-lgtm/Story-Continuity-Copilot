"""Independent V3 provenance, persisted API input and exact V2 equivalence audit."""
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
BASE = HERE.parent
RUN = BASE / 'runs/offline-equivalence-20260926-01'
V2 = ROOT / 'evaluation/current_flash_v2'
V2_RUN = V2 / 'runs/flash-v2-20260926-01'
io_attempts = []
def deny(*args, **kwargs):
    io_attempts.append('blocked')
    raise AssertionError('No network, SMTP or Provider calls')
socket.socket.connect = deny
socket.socket.connect_ex = deny
socket.create_connection = deny
smtplib.SMTP = deny
smtplib.SMTP_SSL = deny
sys.path.insert(0, str(ROOT / 'backend'))
from app.engine import WritingAnalysisEngine
class NoProvider:
    evaluate = deny
engine = WritingAnalysisEngine(NoProvider())
def read(p):
    return json.loads(p.read_text(encoding='utf-8'))
def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()
def digest(obj):
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

start = read(RUN / 'start.json')
summary = read(RUN / 'summary.json')
v2_frozen = read(V2 / 'frozen-inputs.json')['source_hashes']
expected_hashes = {**v2_frozen, **start['source_hashes']}
for rel, h in expected_hashes.items():
    assert sha(ROOT / rel) == h
case_defs = {c['id']: c for c in read(V2 / 'cases.json')['g03']}
new_records = sorted((RUN / 'cases').glob('*.json'))
old_records = {p.name.split('-', 1)[1].removesuffix('.json'): p for p in (V2_RUN / 'cases').glob('*-g03-*.json')}
watched = [ROOT / rel for rel in expected_hashes] + new_records + list(old_records.values()) + [RUN / 'start.json', RUN / 'summary.json', RUN / 'workspace-manifest.json', V2_RUN / 'workspace-manifest.json']
before = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
db_before = {}
new_db = {}
for version, folder, expected_root in (
    ('v2', V2_RUN, ROOT / 'artifacts/current_flash_v2/flash-v2-20260926-01'),
    ('v3', RUN, ROOT / 'artifacts/current_flash_v3/offline-equivalence-20260926-01'),
):
    manifest = read(folder / 'workspace-manifest.json')
    assert pathlib.Path(manifest['root']).resolve() == expected_root.resolve()
    for entry in manifest['database_files']:
        p = (expected_root / entry['path']).resolve()
        assert p.is_relative_to(expected_root.resolve())
        assert p.stat().st_size == entry['bytes'] and sha(p) == entry['sha256']
        db_before[p.relative_to(ROOT).as_posix()] = entry['sha256']
        if version == 'v3':
            new_db[entry['path'].split('/')[0]] = p
assert len(new_db) == 4 and len(db_before) == 12
original_connect = sqlite3.connect
allowed = {p.as_uri() + '?mode=ro&immutable=1' for p in new_db.values()}
opened = []
def ro_connect(database_uri, *args, **kwargs):
    assert database_uri in allowed and kwargs.get('uri') is True
    opened.append(database_uri)
    return original_connect(database_uri, *args, **kwargs)
sqlite3.connect = ro_connect
rows = []
fact = '星钥始终由乔霁保管。'
for file in new_records:
    rec = read(file)
    case = case_defs[rec['case_id']]
    baseline = read(old_records[case['id']])
    baseline_request = baseline['business_requests'][0]['business_request']
    request = rec['v3_business_request']
    # No field filtering or normalization: ordinary recursive Python equality.
    assert request == baseline_request
    expected_hash = baseline['business_requests'][0]['business_request_sha256']
    assert digest(request) == digest(baseline_request) == expected_hash == rec['v2_business_request_sha256'] == rec['v3_business_request_sha256']
    assert rec['exact_business_request_equal'] and rec['different_paths'] == [] and rec['external_http_dispatches'] == 0
    body = case['target_body'] if 'target_body' in case else case['target_prefix_repeat'] * case['repeat_count'] + case['target_fact'] + case['target_suffix_repeat'] * case['suffix_count']
    expected_bodies = {'fixture-chapter-flash_v2_target-1': body, 'fixture-chapter-flash_v2_target-2': case['other_body']}
    connection = sqlite3.connect(new_db[case['id']].as_uri() + '?mode=ro&immutable=1', uri=True)
    connection.row_factory = sqlite3.Row
    try:
        project = connection.execute('SELECT id,source_revision,current_memory_version FROM v2_projects').fetchall()
        assert len(project) == 1 and project[0]['source_revision'] == project[0]['current_memory_version'] == 1
        chapters = [dict(r) for r in connection.execute('SELECT id,chapter_number,body,summary,source_revision FROM v2_chapters ORDER BY chapter_number')]
        spans = [dict(r) for r in connection.execute('SELECT id,chapter_id,body,source_revision FROM v2_source_spans ORDER BY id')]
        outlines = [dict(r) for r in connection.execute('SELECT chapter_number,summary FROM v2_outline_nodes ORDER BY chapter_number')]
        assert len(chapters) == len(spans) == len(outlines) == 2
        for ch in chapters:
            span = next(s for s in spans if s['chapter_id'] == ch['id'])
            outline = next(o for o in outlines if o['chapter_number'] == ch['chapter_number'])
            assert ch['body'] == span['body'] == expected_bodies[ch['id']]
            assert ch['summary'] == outline['summary'] == ch['body'][:180]
            assert ch['source_revision'] == span['source_revision'] == 1
        memory = [dict(r) for r in connection.execute('SELECT id,version,memory_type,subject,predicate,value,source_span_id,review_status FROM v2_memory_records')]
        assert memory == [{'id': 'fixture-memory-flash_v2_target-1', 'version': 1, 'memory_type': 'dynamic_state', 'subject': '星钥', 'predicate': 'holder', 'value': fact, 'source_span_id': 'fixture-span-flash_v2_target-1', 'review_status': 'author_confirmed'}]
        persisted_inputs = [dict(r) for r in connection.execute('SELECT run_id,project_id,analysis_type,input_json FROM v2_analysis_inputs')]
        assert len(persisted_inputs) == 1 and persisted_inputs[0]['analysis_type'] == 'change_impact'
        persisted = json.loads(persisted_inputs[0]['input_json'])
        derived_request = engine._request(persisted)
        assert derived_request == request and digest(derived_request) == expected_hash
        run = dict(connection.execute('SELECT id,run_type,status,input_tokens,output_tokens FROM v2_runs WHERE id=?', (persisted_inputs[0]['run_id'],)).fetchone())
        assert run['id'] != baseline['product']['run_id'] and run['run_type'] == 'change_impact' and run['status'] == 'completed'
        assert run['input_tokens'] == run['output_tokens'] == 1
        assert connection.execute('SELECT COUNT(*) FROM v2_analysis_results WHERE run_id=?', (run['id'],)).fetchone()[0] == 1
    finally:
        connection.close()
    rows.append({'case_id': case['id'], 'full_request_equal_v2': True, 'request_sha256': expected_hash,
                 'request_reconstructed_from_persisted_product_api_input': True, 'parent_span_summary_revision_memory_consistent': True,
                 'target_body_chars': len(body), 'target_fact_position': body.find(fact), 'new_fake_run_id_differs_from_real_v2': True,
                 'fake_run_tokens': [1, 1], 'external_http': 0})
assert len(rows) == 4 and summary['all_exact_business_requests_equal'] and summary['external_http_dispatches'] == 0
after = {p.relative_to(ROOT).as_posix(): sha(p) for p in watched}
db_after = {p: sha(ROOT / p) for p in db_before}
assert before == after and db_before == db_after and not io_attempts
result = {'scope': 'four exact manifest-listed V3 DBs read-only; V2 DBs hashed only; no Provider or new product runs',
          'cases': rows, 'source_records_before': before, 'source_records_after': after,
          'database_hashes_before': db_before, 'database_hashes_after': db_after,
          'readonly_database_connections': len(opened), 'network_smtp_provider_attempts': io_attempts}
with (HERE / 'fixture-results.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps({'cases': rows, 'all_hashes_unchanged': True, 'readonly_database_connections': len(opened)}, ensure_ascii=False))
