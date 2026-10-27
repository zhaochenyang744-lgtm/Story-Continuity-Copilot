"""Fault injection on disposable copies only; JSON output contains no content."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[3]
SETS = {'f': REPO / 'evaluation/eval_set_a3f2_formal', 's': REPO / 'evaluation/eval_set_a3s2_formal'}


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def save(p, value):
    p.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def run(root):
    p = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(root / 'check.py')], cwd=tempfile.gettempdir(),
                       text=True, encoding='utf-8', capture_output=True)
    try:
        result = json.loads(p.stdout)
    except Exception:
        result = {'status': 'FAIL', 'errors': ['negative:invalid_output']}
    return p.returncode, result


def refresh_temp_manifest(root):
    # Leave independent bindings intact: tests must also detect broken freeze binding.
    rels = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for d in ('works', 'materials')
                                   for p in (root / d).rglob('*') if p.is_file()])
    (root / 'set.sha256').write_text(''.join(hashlib.sha256((root / p).read_bytes()).hexdigest() + '  ' + p + '\n' for p in rels), encoding='utf-8')


def mutate(root, number):
    data = load(root / 'tasks.json')
    review = load(root / 'authoring/self-review.json')
    if number == 1:
        data['tasks'].remove(next(t for t in data['tasks'] if t['suite'] == 'trace'))
        save(root / 'tasks.json', data)
        return ':suite_distribution'
    if number == 2:
        item = review['works']['w01']['trace_objects'][0]['states'][0]
        item['quote'] = '错' + item['quote'][1:]
        save(root / 'authoring/self-review.json', review)
        return ':quote'
    if number == 3:
        task = next(t for t in data['tasks'] if t['suite'] == 'thread_audit' and t['scope'] is None)
        near = review['works'][task['work']]['near_misses'][0]
        action = deepcopy(task['expected_actions'][0])
        action['target'] = near['foreshadow']
        task['expected_actions'].append(action)
        save(root / 'tasks.json', data)
        return ':near_miss_action'
    if number == 4:
        task = deepcopy(next(t for t in data['tasks'] if t['suite'] == 'thread_audit'))
        task.update(id='a3f2-w01-tidy-01', suite='tidy')
        data['tasks'].append(task)
        save(root / 'tasks.json', data)
        return ':suite'
    if number == 5:
        item = data['tasks'][0]['injection']
        item['text'] = '错' + item['text'][1:]
        save(root / 'tasks.json', data)
        return ':injection_quote'
    if number == 6:
        task = next(t for t in data['tasks'] if t['allowed_actions'])
        a = task['allowed_actions'][0]
        task['injection_target'] = {'kind': a['kind'], 'target': deepcopy(a['target'])}
        save(root / 'tasks.json', data)
        return ':injection_collision'
    if number == 7:
        p = root / 'works/w01.md'
        s = p.read_text(encoding='utf-8')
        idx = next(i for i, c in enumerate(s) if '\u4e00' <= c <= '\u9fff' and i > s.index('\n'))
        p.write_text(s[:idx] + ('乙' if s[idx] != '乙' else '甲') + s[idx+1:], encoding='utf-8', newline='\n')
        return ':hash'
    raise ValueError('invalid test')


def main():
    temp_parent = Path(tempfile.gettempdir()).resolve()
    temp = Path(tempfile.mkdtemp(prefix='task33-a3-negative-', dir=temp_parent)).resolve()
    results = []
    try:
        for number, sid in [(1, 'f'), (2, 'f'), (3, 'f'), (4, 'f'), (5, 's'), (6, 's'), (7, 'f')]:
            root = temp / str(number)
            shutil.copytree(SETS[sid], root)
            returncode, baseline = run(root)
            if returncode or baseline.get('status') != 'PASS':
                raise RuntimeError('negative baseline did not pass')
            intended = mutate(root, number)
            if number != 7:
                refresh_temp_manifest(root)
            returncode, output = run(root)
            caught = returncode != 0 and output.get('status') == 'FAIL' and any(intended in e for e in output.get('errors', []))
            results.append({'test': number, 'set': sid, 'baseline_status': baseline['status'], 'exit_code': returncode,
                            'status': output.get('status'), 'intended_error_detected': caught, 'errors': output.get('errors', [])})
    finally:
        if not temp.is_relative_to(temp_parent) or not temp.name.startswith('task33-a3-negative-'):
            raise RuntimeError('unsafe temporary cleanup target')
        shutil.rmtree(temp)
    output = {'tests': len(results), 'detected': sum(r['intended_error_detected'] for r in results),
              'temporary_copies_removed': True, 'results': results}
    for sid in SETS:
        own = {**output, 'results': [r for r in results if r['set'] == sid]}
        own['tests'] = len(own['results'])
        own['detected'] = sum(r['intended_error_detected'] for r in own['results'])
        save(SETS[sid] / 'authoring/negative-tests.json', own)
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))
    return int(output['detected'] != output['tests'])


if __name__ == '__main__':
    raise SystemExit(main())
