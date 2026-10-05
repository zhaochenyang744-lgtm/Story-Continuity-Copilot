"""Bounded offline supplement: bind a chapter impact to that chapter's source."""
from __future__ import annotations
import os
os.environ['SCC_DISABLE_DEFAULT_APP'] = '1'
os.environ['PYTHONDONTWRITEBYTECODE'] = '1'
import sys, pathlib, json, copy, hashlib, socket, smtplib
sys.dont_write_bytecode = True
ROOT = pathlib.Path(__file__).resolve().parents[3]
OUT = pathlib.Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))
network_attempts = []
def deny_network(*args, **kwargs):
    network_attempts.append('blocked')
    raise AssertionError('network forbidden for independent validation probe')
socket.create_connection = deny_network
socket.socket.connect = deny_network
smtplib.SMTP = deny_network
from app.engine import WritingAnalysisEngine

class NoProvider:
    def evaluate(self, request):
        raise AssertionError('Provider must not be called')

engine = WritingAnalysisEngine(NoProvider())
base = {
    'task': 'change_impact',
    'bindings': {'project_id': 'synthetic-project'},
    'proposal': {'target_type': 'memory', 'target_id': 'memory-B', 'proposed_change': '改为由沈砚保管星钥。'},
    'retrieval': {'target_source': {'memory_id': 'memory-B', 'source_span_id': 'span-B', 'status': 'selected', 'source_revision': 1}},
    'layers': {
        'planned': {'story_plans': [], 'character_plans': [], 'world_plans': []},
        'confirmed': {'memory_records': [{'id': 'memory-B', 'subject': '星钥', 'predicate': '保管者', 'value': '乔霁', 'source_span_id': 'span-B'}]},
        'written': {'source_spans': [
            {'id': 'span-A', 'chapter_id': 'chapter-A', 'chapter_number': 1, 'label': '码头天气', 'body': '码头今天晴朗，渔夫只讨论天气。', 'source_revision': 1},
            {'id': 'span-B', 'chapter_id': 'chapter-B', 'chapter_number': 2, 'label': '星钥保管者', 'body': '星钥始终由乔霁保管。', 'source_revision': 1},
        ], 'draft_claims': []},
        'identity': {'characters': [], 'aliases': []},
        'reference': {'chapters': [
            {'id': 'chapter-A', 'chapter_number': 1, 'title': '码头'},
            {'id': 'chapter-B', 'chapter_number': 2, 'title': '保管'},
        ], 'world_entries': []},
    },
}

def payload(target, source_type, source_id):
    return {'summary': '原文章节需要修订。', 'items': [{
        'area': 'chapter', 'target_id': target,
        'impact': '该章明确写了乔霁持有星钥，必须更换为沈砚。',
        'evidence': [{'source_type': source_type, 'source_id': source_id}],
    }]}

cases = []
for name, remove_A, target, kind, source, expected in [
    ('chapter_A_only_cites_B_even_when_A_available', False, 'chapter-A', 'source_span', 'span-B', 'insufficient'),
    ('chapter_A_only_cites_B_when_A_not_retrieved', True, 'chapter-A', 'source_span', 'span-B', 'insufficient'),
    ('matching_chapter_B_source_positive_control', False, 'chapter-B', 'source_span', 'span-B', 'supported'),
    ('memory_only_negative_control', False, 'chapter-A', 'memory_record', 'memory-B', 'insufficient'),
]:
    data = copy.deepcopy(base)
    if remove_A:
        data['layers']['written']['source_spans'] = [s for s in data['layers']['written']['source_spans'] if s['chapter_id'] != 'chapter-A']
    provider_payload = payload(target, kind, source)
    result = engine.validate(provider_payload, data)
    cases.append({'name': name, 'expected_evidence_status': expected, 'passed': result['evidence_status'] == expected, 'input': data, 'provider_payload': provider_payload, 'actual': result})

report = {
    'scope': 'Direct validation only; synthetic content; no HTTP, database, Provider or SMTP calls.',
    'engine_sha256': hashlib.sha256((ROOT / 'backend/app/engine.py').read_bytes()).hexdigest(),
    'network_attempts': len(network_attempts),
    'results': cases,
}
target = OUT / 'chapter-evidence-results.json'
with target.open('x', encoding='utf-8') as handle:
    json.dump(report, handle, ensure_ascii=False, indent=2)
print(json.dumps({'cases': len(cases), 'passed': sum(c['passed'] for c in cases), 'network_attempts': len(network_attempts), 'result_file': str(target)}, ensure_ascii=False))
