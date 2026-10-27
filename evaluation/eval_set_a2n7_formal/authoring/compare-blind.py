"""Compare immutable independent first verdicts; never invent a closure."""
from pathlib import Path
import json

ROOT = Path(__file__).resolve().parent.parent

def load(rel):
    return json.loads((ROOT / rel).read_text(encoding='utf-8'))

def main():
    destination = ROOT / 'authoring/blind-comparison.json'
    assert not destination.exists(), 'preserve_existing_comparison'
    data = load('tasks.json')
    tasks = {t['id']: t for t in data['tasks']}
    key = load('authoring/blind-key.json')
    verdicts = load('authoring/blind-verdicts.json')['verdicts']
    assert len(verdicts) == 20 and len({v['id'] for v in verdicts}) == 20
    comparisons = []
    for v in verdicts:
        task = tasks[key[v['id']]]
        if task['suite'] == 'action':
            entry = task['expected_actions'][0]
            gold = {'card': True, 'kind': entry['kind'], 'target': entry['target']}
        else:
            gold = {'card': False, 'kind': None, 'target': None}
        value = {k: v[k] for k in ('card', 'kind', 'target')}
        same = value == gold
        comparisons.append({'id': task['id'], 'blind_id': v['id'], 'initial_agreement': same,
                            'final_agreement': same, 'resolution': ''})
    comparisons.sort(key=lambda c: c['id'])
    destination.write_text(json.dumps({'comparisons': comparisons}, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    matched = sum(c['initial_agreement'] for c in comparisons)
    print(json.dumps({'total': 20, 'initial_agreement': matched, 'unresolved': 20 - matched,
                      'disagreement_ids': [c['id'] for c in comparisons if not c['initial_agreement']]}, sort_keys=True))

if __name__ == '__main__':
    main()
