"""Content-free, focused pre-freeze copy and question novelty audit."""
from difflib import SequenceMatcher
import json
from pathlib import Path
import runpy

REPO = Path(__file__).resolve().parents[3]
results = {}
for folder in ['eval_set_a22_formal', 'eval_set_a2s2_formal']:
    root = REPO / 'evaluation' / folder
    functions = runpy.run_path(str(root / 'check.py'))
    grams, normalized = functions['grams'], functions['normalized']
    data = json.loads((root / 'tasks.json').read_text(encoding='utf-8'))
    reference = json.loads((root / 'authoring/novelty-reference.json').read_text(encoding='utf-8'))['normalized_inputs']
    works = {w['key']: w for w in data['works']}
    corpus = {k: grams((root / w['source_file']).read_text(encoding='utf-8'), w['names']) for k, w in works.items()}
    errors = []
    for task in data['tasks']:
        tid, wk = task['id'], task['work']
        value = task.get('input', task.get('request', ''))
        if grams(value, works[wk]['names']) & corpus[wk]:
            errors.append(tid + ':copy8')
        n = normalized(value)
        if any(SequenceMatcher(None, n, old).ratio() >= .8 for old in reference):
            errors.append(tid + ':novelty80')
        for i, action in enumerate(task.get('expected_actions', task.get('allowed_actions', [])), 1):
            for j, point in enumerate(action['after_points'], 1):
                if grams(point, works[wk]['names']) & corpus[wk]:
                    errors.append(f'{tid}:action:{i}:point:{j}:copy8')
    results[folder] = {'tasks': len(data['tasks']), 'errors': errors, 'error_count': len(errors)}
print(json.dumps(results, sort_keys=True))
raise SystemExit(int(any(r['errors'] for r in results.values())))
