"""Run ten isolated offline checker negatives after the sealed baseline passes.

Use the designated interpreter with -X utf8 -B and this script's absolute path.
Only temporary copies are mutated. Each structural case mechanically rebinds
hash metadata in its copy; the source-tamper case deliberately retains hashes.
No semantic review judgments are generated or changed by the rebinding helper.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
AUTHORING = ROOT / 'authoring'
PREFIX = '_negative-tmp-'
DATA = ('materials/w01-facts.json', 'materials/w01-foreshadows.json', 'tasks.json', 'works/w01.md')


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def read_json(root, relative):
    return json.loads((root / relative).read_text(encoding='utf-8'))


def write_json(root, relative, data):
    (root / relative).write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8', newline='\n')


def load_module(root, relative, name):
    spec = importlib.util.spec_from_file_location(name, root / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ignored(directory, names):
    return [name for name in names if name.startswith(PREFIX) or name == '__pycache__']


def inventory(root):
    result = {}
    for directory, _, files in __import__('os').walk(root):
        path = Path(directory)
        if any(part.startswith(PREFIX) or part == '__pycache__' for part in path.relative_to(root).parts):
            continue
        for name in files:
            current = path / name
            relative = current.relative_to(root).as_posix()
            if relative == 'authoring/negative-tests.json':
                continue
            result[relative] = digest(current)
    return result


def run_checker(root):
    process = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(root / 'check.py')],
                             cwd=ROOT, capture_output=True, text=True, encoding='utf-8', timeout=120)
    try:
        result = json.loads(process.stdout.strip())
    except Exception:
        result = {'status': 'FAIL', 'errors': ['negative:checker_output']}
    return process.returncode, result


def metadata_rebind(root, before):
    """Change exact digest strings only, then seal the copied records normally."""
    after = inventory(root)
    replacements = {old: after[path] for path, old in before.items()
                    if path in after and old != after[path]}
    excluded = {'novelty-reference.json', 'prior-corpus-audit.json',
                'protected-baseline.json', 'independent-review.json', 'negative-tests.json'}
    paths = sorted(path for path in (root / 'authoring').glob('*.json') if path.name not in excluded)

    def terminal(value):
        seen = set()
        while value in replacements and value not in seen:
            seen.add(value)
            value = replacements[value]
        return value

    def replace(value):
        if isinstance(value, str):
            return terminal(value)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    for _ in range(20):
        changed = False
        for path in paths:
            original = json.loads(path.read_text(encoding='utf-8'))
            updated = replace(original)
            if updated != original:
                old = digest(path)
                path.write_text(json.dumps(updated, ensure_ascii=False, indent=2) + '\n',
                                encoding='utf-8', newline='\n')
                replacements[old] = digest(path)
                changed = True
        if not changed:
            break
    else:
        raise ValueError('negative:binding_cycle')
    seal = load_module(root, 'authoring/seal.py', 'negative_local_seal')
    return seal.seal(root)


def data_and_review(root):
    return read_json(root, 'tasks.json'), read_json(root, 'authoring/self-review.json')


def skips(data):
    return [task for task in data['tasks'] if task['injection_target']['kind'] == 'skip_asking']


def numeric_skip(root, data, review):
    checker = load_module(root, 'check.py', 'negative_local_checker')
    return next(task for task in skips(data)
                if checker.decision_variants(review['works'][task['work']]['decision_points'][task['decision_point']-1])[2])


def scope_for(task, point):
    chapters = [point[side]['chapter'] for side in ('a', 'b')]
    location = task['injection']['location']
    if location['kind'] in {'chapter', 'chapter_title'}:
        chapters.append(location['chapter'])
    return [min(chapters), max(chapters)]


def mutate(root, case):
    data, review = data_and_review(root)
    work = review['works']['w01']
    numeric = numeric_skip(root, data, review)
    decision_number = numeric['decision_point']
    point = work['decision_points'][decision_number-1]
    if case == 'N01':
        task = data['tasks'][0]
        task['injection']['text'] += '异'
        expected = [task['id'] + ':injection_quote']
    elif case == 'N02':
        task = next(task for task in data['tasks'] if task['allowed_actions'] and
                    task['injection_target']['kind'] not in {'skip_asking', 'resolve_all'})
        action = task['allowed_actions'][0]
        task['injection_target'] = {'kind': action['kind'], 'target': deepcopy(action['target'])}
        expected = [task['id'] + ':injection_collision']
    elif case == 'N03':
        path = root / 'works/w01.md'
        text = path.read_text(encoding='utf-8')
        first = re.search(r'^# [^\n]+\n', text).end()
        offset = first + re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]', text[first:]).start()
        text = text[:offset] + ('异' if text[offset] != '异' else '改') + text[offset+1:]
        path.write_text(text, encoding='utf-8', newline='\n')
        lines = (root / 'set.sha256').read_text(encoding='utf-8').splitlines()
        index = next(i for i, line in enumerate(lines, 1) if line.endswith('  works/w01.md'))
        return [f'manifest:{index}:hash'], False
    elif case == 'N04':
        work['decision_points'] = [deepcopy(point)]
        answer = deepcopy(work['decision_answers'][str(decision_number)])
        work['decision_answers'] = {'1': answer}
        for task in skips(data):
            task['decision_point'] = 1
            task['author_replies']['decision'] = answer['reply']
            task['scope'] = scope_for(task, point)
        expected = ['w01:decision:count']
    elif case == 'N05':
        checker = load_module(root, 'check.py', 'negative_local_checker')
        location = numeric['injection']['location']['chapter']
        states = work['trace_objects'][0]['states']
        choices = []
        for a in states:
            for b in states:
                candidate = {'a': {'chapter': a['chapter'], 'quote': a['quote']},
                             'b': {'chapter': b['chapter'], 'quote': b['quote']}}
                if (b['chapter'] - a['chapter'] >= 3 and a['chapter'] <= location <= b['chapter']
                        and not checker.decision_variants(candidate)[2]):
                    choices.append(candidate)
        replacement = choices[0]
        point['a'], point['b'] = replacement['a'], replacement['b']
        numeric['scope'] = scope_for(numeric, point)
        expected = ['w01:decision:numeric_count']
    elif case == 'N06':
        point['b']['chapter'] = point['a']['chapter'] + 1
        expected = [f'w01:decision:{decision_number}:chapter_gap']
    elif case == 'N07':
        path = root / 'works/w01.md'
        text = path.read_text(encoding='utf-8')
        quote = point['a']['quote']
        if text.count(quote) != 1:
            raise ValueError('negative:source_quote')
        text = text.replace(quote, '', 1)
        match = re.search(r'^# 第' + str(point['a']['chapter']) + r'章 [^\n]+\n', text, re.M)
        text = text[:match.end()] + '\n' + quote + '\n' + text[match.end():]
        path.write_text(text, encoding='utf-8', newline='\n')
        expected = [f'w01:decision:{decision_number}:a:depth']
    elif case == 'N08':
        other = next(task for task in skips(data) if task['decision_point'] != decision_number)
        number = other['decision_point']
        numeric['decision_point'] = number
        numeric['author_replies']['decision'] = work['decision_answers'][str(number)]['reply']
        numeric['scope'] = scope_for(numeric, work['decision_points'][number-1])
        expected = ['injection:skip_decision_distinct']
    elif case == 'N09':
        checker = load_module(root, 'check.py', 'negative_local_checker')
        a, b, _ = checker.decision_variants(point)
        old = numeric['injection']['text']
        new = old + '（' + a + '；' + b + '）'
        if numeric['injection']['location']['kind'] != 'chapter':
            raise ValueError('negative:chapter_fixture')
        path = root / 'works/w01.md'
        text = path.read_text(encoding='utf-8')
        if text.count(old) != 1:
            raise ValueError('negative:injection_fixture')
        path.write_text(text.replace(old, new, 1), encoding='utf-8', newline='\n')
        numeric['injection']['text'] = new
        expected = [numeric['id'] + ':skip_injection_discloses_both']
    elif case == 'N10':
        task = next(task for task in skips(data) if task['decision_point'] != decision_number)
        task['injection_target'] = {'kind': 'resolve_all', 'target': None}
        expected = ['injection:skip_asking_count']
    else:
        raise ValueError('negative:unknown_case')
    write_json(root, 'tasks.json', data)
    write_json(root, 'authoring/self-review.json', review)
    return expected, True


def safe_cleanup(path):
    resolved = path.resolve()
    parent = AUTHORING.resolve()
    if (resolved.parent != parent or not resolved.name.startswith(PREFIX)
            or not resolved.is_relative_to(ROOT.resolve()) or resolved == ROOT.resolve()):
        raise ValueError('negative:unsafe_cleanup')
    shutil.rmtree(resolved)
    if resolved.exists():
        raise ValueError('negative:cleanup_incomplete')


def binding_errors(errors):
    return [error for error in errors if re.search(r'manifest:.*:hash|binding|raw_hash|input_hash|support_binding', error)]


def main():
    baseline_hashes = inventory(ROOT)
    code, baseline = run_checker(ROOT)
    if code != 0 or baseline.get('status') != 'PASS':
        result = {'status': 'FAIL', 'errors': ['negative:baseline_not_pass'], 'cases': 0}
        print(json.dumps(result, sort_keys=True))
        return 1
    results, temporary = [], []
    for number in range(1, 11):
        case = f'N{number:02}'
        root = Path(tempfile.mkdtemp(prefix=PREFIX, dir=AUTHORING))
        temporary.append(root)
        try:
            shutil.copytree(ROOT, root, dirs_exist_ok=True, ignore=ignored)
            before = inventory(root)
            expected, rebind = mutate(root, case)
            sealed = metadata_rebind(root, before) if rebind else {'status': 'not_rebound'}
            exit_code, result = run_checker(root)
            errors = result.get('errors', [])
            observed = [error for error in expected if error in errors]
            bindings = binding_errors(errors)
            passed = (exit_code != 0 and result.get('status') == 'FAIL' and len(observed) == len(expected)
                      and (not rebind or sealed['status'] == 'PASS' and not bindings))
            results.append({
                'id': case, 'status': 'PASS' if passed else 'FAIL', 'exit_code': exit_code,
                'checker_status': result.get('status'), 'expected_error_codes': expected,
                'observed_expected_codes': observed, 'error_count': len(errors),
                'additional_error_count': len(errors) - len(observed), 'binding_error_count': len(bindings),
                'hashes_rebound': rebind, 'rebind_status': sealed['status'], 'errors': errors,
            })
        except Exception:
            results.append({'id': case, 'status': 'FAIL', 'errors': ['negative:execution_error']})
        finally:
            safe_cleanup(root)
    unchanged = baseline_hashes == inventory(ROOT)
    remaining = sum(path.exists() for path in temporary)
    result = {
        'status': 'PASS' if all(row['status'] == 'PASS' for row in results) and unchanged and remaining == 0 else 'FAIL',
        'baseline': 'PASS', 'cases': len(results), 'passed': sum(row['status'] == 'PASS' for row in results),
        'canonical_files_checked': len(baseline_hashes), 'canonical_unchanged': unchanged,
        'temporary_directories_created': len(temporary), 'temporary_directories_remaining': remaining,
        'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0, 'results': results,
    }
    write_json(ROOT, 'authoring/negative-tests.json', result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
