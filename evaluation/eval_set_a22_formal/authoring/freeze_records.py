"""Bind completed independent reviews and run only the offline set checker."""
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def write(p, data):
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def bind(folder):
    root = REPO / 'evaluation' / folder
    safety = folder == 'eval_set_a2s2_formal'
    keys, size = (['w01'], 12) if safety else (['w01', 'w02'], 20)
    data_paths = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for sub in ['works', 'materials']
                                       for p in (root / sub).rglob('*') if p.is_file()])
    bindings = {rel: sha(root / rel) for rel in data_paths}
    authoring_paths = ['authoring/self-review.json', 'authoring/self-review.md', 'authoring/novelty-reference.json']
    record_paths, finding_count = [], 0
    for wk in keys:
        rel = f'authoring/independent-{wk}-review.json'
        r = load(root / rel)
        assert r['status'] == 'completed' and r['unresolved_findings'] == 0
        assert r['chapters_read'] == list(range(1, size + 1))
        assert r['source_sha256'] == bindings[f'works/{wk}.md']
        assert r['tasks_sha256'] == bindings['tasks.json']
        assert r['materials_sha256'] == {f'materials/{wk}-{k}.json': bindings[f'materials/{wk}-{k}.json']
                                        for k in ['facts', 'foreshadows']}
        finding_count += len(r.get('findings', []))
        record_paths.append(rel)
    result = {'status': 'completed', 'unresolved_findings': 0,
              'chapter_coverage': {wk: size for wk in keys}, 'findings_recorded': finding_count,
              'independent_records': {rel: sha(root / rel) for rel in record_paths}, 'sha256': bindings,
              'authoring_sha256': {rel: sha(root / rel) for rel in authoring_paths}}
    if not safety:
        blind = load(root / 'authoring/route-comparison.json')
        assert blind['total'] == 20 and blind['final_agreement'] == 20 and blind['unresolved'] == 0
        assert blind['predictions_sha256'] == sha(root / 'authoring/blind-route-predictions.json')
        assert blind['blind_input_sha256'] == sha(root / 'authoring/route-blind-input.json')
        result['blind_route'] = blind
    write(root / 'authoring/independent-review.json', result)
    (root / 'set.sha256').write_text(''.join(f'{value}  {rel}\n' for rel, value in bindings.items()),
                                    encoding='utf-8', newline='\n')
    return root


def check(root):
    run = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-m', f'evaluation.{root.name}.check'],
                         cwd=REPO, capture_output=True, text=True, encoding='utf-8')
    output = json.loads(run.stdout)
    history = {'at_utc': datetime.now(timezone.utc).isoformat(), 'mode': 'root_module',
               'exit_code': run.returncode, 'stderr_empty': not run.stderr.strip(), 'output': output}
    with (root / 'authoring/check-history.jsonl').open('a', encoding='utf-8', newline='\n') as f:
        f.write(json.dumps(history, ensure_ascii=False, sort_keys=True) + '\n')
    (root / 'authoring/check-output.json').write_text(run.stdout, encoding='utf-8', newline='\n')
    print(run.stdout, end='')
    assert not run.stderr.strip()
    return run.returncode


if __name__ == '__main__':
    raise SystemExit(check(bind(sys.argv[1])))
