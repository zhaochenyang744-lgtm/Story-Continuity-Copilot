"""Independent V8 selection/score reconstruction; no DB, HTTP or Provider calls."""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import smtplib
import socket
import sqlite3
import sys

sys.dont_write_bytecode = True
os.environ['SCC_DISABLE_DEFAULT_APP'] = '1'
HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[2]
RUN = ROOT / 'evaluation/current_flash_v1/runs/flash-v1-20260926-01'
attempts = []


def forbidden(*args, **kwargs):
    attempts.append('forbidden_io')
    raise AssertionError('Network, SMTP and database access forbidden')


socket.socket.connect = forbidden
socket.socket.connect_ex = forbidden
socket.create_connection = forbidden
smtplib.SMTP = forbidden
smtplib.SMTP_SSL = forbidden
sqlite3.connect = forbidden
sys.path.insert(0, str(ROOT / 'backend'))
from app.engine import ContinuityEngine, _claim_terms, _relevance_score


class NoProvider:
    def evaluate(self, request):
        raise AssertionError('Provider must not execute')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


frozen = read(ROOT / 'evaluation/current_flash_v1/frozen-inputs.json')
tracked = [ROOT / rel for rel in frozen['source_hashes']]
case_files = sorted((RUN / 'cases').glob('*.json'))
tracked += case_files + [RUN / 'summary.json', RUN / 'postrun-audit.json']
before = {p.relative_to(ROOT).as_posix(): sha(p) for p in tracked}
frozen_matches = {rel: before[rel] == digest for rel, digest in frozen['source_hashes'].items()}
assert all(frozen_matches.values())
case_source = read(ROOT / 'evaluation/case_sets/eval-set-v8.json')['cases']
by_id = {case['case_id']: case for case in case_source}
engine = ContinuityEngine(NoProvider())
rows = []


def target_prediction(payload, claim_id):
    if not isinstance(payload, dict) or not isinstance(payload.get('issues'), list):
        return None
    issues = [issue for issue in payload['issues'] if issue.get('claim_span_id') == claim_id]
    if any(i.get('nature') == 'confirmed_conflict' or i.get('status') == 'conflict' for i in issues):
        return 'conflict'
    if any(i.get('nature') == 'insufficient_evidence' or i.get('status') == 'insufficient_evidence' for i in issues):
        return 'insufficient_evidence'
    return 'no_conflict'


for path in case_files:
    record = read(path)
    if record['family'] != 'v8':
        continue
    case = by_id[record['case_id']]
    corpus = read(ROOT / f"evaluation/fixtures/eval-v8-{case['corpus_key'].replace('_', '-')}.json")
    spans = {f"fixture-span-{case['corpus_key']}-{c['chapter_number']}": {
        'id': f"fixture-span-{case['corpus_key']}-{c['chapter_number']}",
        'chapter_id': f"fixture-chapter-{case['corpus_key']}-{c['chapter_number']}",
        'body': c['body'], 'label': c['source_label']
    } for c in corpus['chapters']}
    memory = [{
        'id': f"fixture-memory-{case['corpus_key']}-{index}",
        **{k: m[k] for k in ('memory_type', 'subject', 'predicate', 'value')},
        'source_span_id': f"fixture-span-{case['corpus_key']}-{m['source']['chapter_number']}"
    } for index, m in enumerate(corpus['memory'], 1)]
    observed = record['model_outputs'][0]['input_refs']['claims']
    assert len(observed) == 1
    claim = observed[0]
    assert claim['text'] == case['target_draft']
    expected_ids = {f"fixture-span-{case['corpus_key']}-{e['chapter_number']}" for e in case['expected_evidence']}
    assert all(spans[f"fixture-span-{case['corpus_key']}-{e['chapter_number']}"]['label'] == e['source_label'] for e in case['expected_evidence'])
    terms = _claim_terms(claim['text'])
    db_ranked = []
    for span in spans.values():
        score = sum(term in span['body'] for term in terms)
        score += sum(2 for m in memory if m['source_span_id'] == span['id'] and any(term in (m['subject'] + m['value']) for term in terms))
        if score:
            db_ranked.append((score, span))
    reconstructed_top5 = [pair[1]['id'] for pair in sorted(db_ranked, key=lambda pair: (-pair[0], pair[1]['id']))[:5]]
    saved_top5 = record['product']['metrics']['retrieval'][0]['returned_span_ids']
    assert reconstructed_top5 == saved_top5
    selected = engine._selected_evidence({'id': claim['id'], 'text': claim['text'], 'allowed_evidence': [spans[s] for s in saved_top5]}, memory)
    actual_ids = [s['id'] for s in claim['allowed_evidence']]
    assert [s['id'] for s in selected] == actual_ids
    assert all(s['body'] == spans[s['id']]['body'] and s['prompt_excerpt'] == spans[s['id']]['body'] for s in claim['allowed_evidence'])
    assert selected == claim['allowed_evidence']
    scores = []
    for sid in saved_top5:
        related = [m for m in memory if m['source_span_id'] == sid]
        memory_text = ' '.join(str(m.get(key, '')) for m in related for key in ('subject', 'predicate', 'value'))
        lexical = min(20, _relevance_score(terms, spans[sid]['body']))
        memory_score = 10 * _relevance_score(terms, memory_text)
        scores.append({'span_id': sid, 'expected': sid in expected_ids, 'selected': sid in actual_ids,
                       'body_score': lexical, 'memory_score': memory_score, 'total': lexical + memory_score})
    first = target_prediction(record['model_outputs'][0]['business_json'], claim['id'])
    product_issues = [i for i in record['product']['issues'] if i['claim_span_id'] == claim['id']]
    final = ('conflict' if any(i['classification'] == 'conflict' for i in product_issues) else
             'insufficient_evidence' if any(i['classification'] == 'insufficient_evidence' for i in product_issues) else 'no_conflict')
    assert final == record['score_row']['predicted_class']
    rows.append({'case_id': case['case_id'], 'expected': case['expected_class'], 'first': first, 'final': final,
                 'first_correct': first == case['expected_class'], 'final_correct': final == case['expected_class'],
                 'claim_text_equals_frozen_target': True, 'source_bodies_and_excerpts_equal_fixture': True,
                 'expected_evidence_ids': sorted(expected_ids), 'db_top5': saved_top5, 'selected': actual_ids,
                 'expected_all_in_top5': expected_ids <= set(saved_top5), 'expected_all_selected': expected_ids <= set(actual_ids),
                 'selection_exact_reproduction': True, 'selection_scores': scores,
                 'first_output': record['model_outputs'][0]['business_json'], 'model_response_count': len(record['model_outputs'])})

assert len(rows) == 24
groups = {}
for label in ('conflict', 'no_conflict', 'insufficient_evidence'):
    group = [r for r in rows if r['expected'] == label]
    groups[label] = {'cases': len(group), 'first_correct': sum(r['first_correct'] for r in group),
                     'final_correct': sum(r['final_correct'] for r in group),
                     'expected_all_in_top5': sum(r['expected_all_in_top5'] for r in group),
                     'expected_all_selected': sum(r['expected_all_selected'] for r in group)}
after = {p.relative_to(ROOT).as_posix(): sha(p) for p in tracked}
assert before == after
assert not attempts
result = {'scope': 'read saved JSON and source assets; execute only pure selection method; no DB, network or provider',
          'groups': groups, 'rows': rows, 'frozen_source_hash_matches': frozen_matches,
          'all_input_and_implementation_hashes_unchanged': True, 'hashes_before': before, 'hashes_after': after,
          'forbidden_io_attempts': attempts}
with (HERE / 'v8-diagnostic-results.json').open('x', encoding='utf-8') as stream:
    json.dump(result, stream, ensure_ascii=False, indent=2)
print(json.dumps({'groups': groups, 'rows': len(rows), 'all_hashes_unchanged': True, 'io_attempts': 0}, ensure_ascii=False))
