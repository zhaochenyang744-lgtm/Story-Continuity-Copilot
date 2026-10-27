"""Bind completed independent evidence, never manufacture review decisions."""
from pathlib import Path
import hashlib
import json

ROOT = Path(__file__).resolve().parent.parent

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))

def sha(rel):
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()

def save(rel, data):
    (ROOT / rel).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

def main():
    data = load('tasks.json')
    work = data['works'][0]
    full = load('authoring/full-source-review.json')
    assert full['status'] == 'completed' and full['unresolved_findings'] == 0
    assert full['chapters_read'] == list(range(1, 13))
    assert full['source_sha256'] == sha('works/w01.md')
    assert full['tasks_sha256'] == sha('tasks.json')
    assert full['draft_body_sha256'] == hashlib.sha256(work['shared_draft']['body'].encode('utf-8')).hexdigest()
    assert full['materials_sha256'] == {p: sha(p) for p in work['materials'].values()}
    paths = sorted(['tasks.json'] + [p.relative_to(ROOT).as_posix() for folder in ('works', 'materials')
                                   for p in (ROOT / folder).rglob('*') if p.is_file()])
    hashes = {p: sha(p) for p in paths}
    sealed = load('authoring/sealed-comparison.json')
    assert sealed['status'] == 'PASS' and sealed['candidate_sha256'] == hashes
    comparisons = load('authoring/blind-comparison.json')['comparisons']
    assert len(comparisons) == 20 and all(c['final_agreement'] is True for c in comparisons)
    initial = sum(c['initial_agreement'] is True for c in comparisons)
    initial_packet = load('authoring/blind-packet.initial.json')
    current_packet = load('authoring/blind-packet.json')
    assert initial_packet['tasks'] == current_packet['tasks']
    assert load('authoring/blind-key.initial.json') == load('authoring/blind-key.json')
    original_verdicts = {v['id']: {k: v[k] for k in ('card', 'kind', 'target')}
                         for v in load('authoring/blind-verdicts.initial.json')['verdicts']}
    current_verdicts = {v['id']: {k: v[k] for k in ('card', 'kind', 'target')}
                        for v in load('authoring/blind-verdicts.json')['verdicts']}
    assert original_verdicts == current_verdicts and len(original_verdicts) == 20
    rereview = load('authoring/blind-rereview.json')
    assert rereview['status'] == 'completed' and rereview['unresolved'] == 0 and rereview['judgements_changed'] == 0
    assert rereview['packet_sha256'] == sha('authoring/blind-packet.json')
    assert load('authoring/revision-log.json')['status'] == 'closed'
    by_id = {c['id']: c for c in comparisons}
    new_ids = [t['id'] for t in data['tasks'] if any(a['kind'] in {'edit_thread', 'abandon_thread'}
                                                  for a in t.get('expected_actions', []))]
    report_paths = ['authoring/full-source-review.json', 'authoring/blind-packet.json',
                    'authoring/blind-key.json', 'authoring/blind-verdicts.json',
                    'authoring/blind-comparison.json', 'authoring/blind-packet.initial.json',
                    'authoring/blind-key.initial.json', 'authoring/blind-verdicts.initial.json',
                    'authoring/blind-rereview.json', 'authoring/revision-log.json']
    independent = {
        'status': 'completed', 'chapter_coverage': {'w01': 12}, 'unresolved_findings': 0, 'blind_rounds': 2,
        'source_reports': {'w01': 'authoring/full-source-review.json'},
        'blind_all': {'total': 20, 'initial_agreement': initial, 'final_agreement': 20, 'unresolved': 0},
        'new_action_blind': {'total': len(new_ids),
                             'initial_agreement': sum(by_id[i]['initial_agreement'] is True for i in new_ids),
                             'final_agreement': len(new_ids), 'unresolved': 0},
        'sha256': hashes,
        'authoring_sha256': {p: sha(p) for p in ('authoring/self-review.json', 'authoring/self-review.md',
                                                'authoring/novelty-reference.json', 'authoring/sealed-comparison.json')},
        'reports': {p: sha(p) for p in report_paths}}
    save('authoring/independent-review.json', independent)
    (ROOT / 'set.sha256').write_text(''.join(f'{h}  {p}\n' for p, h in hashes.items()), encoding='utf-8', newline='\n')
    print(json.dumps({'data_files': len(paths), 'blind_total': 20, 'initial_agreement': initial,
                      'final_agreement': 20, 'manifest_sha256': sha('set.sha256')}, sort_keys=True))

if __name__ == '__main__':
    main()
