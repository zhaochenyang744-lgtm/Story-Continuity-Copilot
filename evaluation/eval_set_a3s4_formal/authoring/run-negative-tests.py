"""Isolated static negative probes; never run the product or an evaluation.

Run only after the actual set has a clean frozen structural PASS. Mutations and
mechanical digest rebinding happen solely in disposable copies. Rebinding here
is a test fixture operation and does not represent a new independent review.
"""
from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import re
import runpy
import shutil


ROOT = Path(__file__).resolve().parent.parent
TEMP = ROOT / 'authoring' / 'negative-tmp'
OUTPUT = ROOT / 'authoring' / 'negative-tests.json'
API = runpy.run_path(str(ROOT / 'check.py'))


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def read_json(root, rel):
    return json.loads((root / rel).read_text(encoding='utf-8'))


def write_json(root, rel, value):
    (root / rel).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                            encoding='utf-8', newline='\n')


def changed_character(text):
    assert isinstance(text, str) and text
    return ('伪' if text[0] != '伪' else '异') + text[1:]


def mutate_json(root, rel, mutation):
    data = read_json(root, rel)
    mutation(data)
    write_json(root, rel, data)


def review(root):
    value = read_json(root, 'authoring/self-review.json')
    return value, value['works']['w01']


def save_review(root, value):
    write_json(root, 'authoring/self-review.json', value)


def task_data(root):
    return read_json(root, 'tasks.json')


def save_tasks(root, value):
    write_json(root, 'tasks.json', value)


def chapter_parts(root):
    p = root / 'works/w01.md'
    text = p.read_text(encoding='utf-8')
    marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 [^\r\n]+$', text, re.M))
    return p, text, {int(m[1]): (m, marks[i + 1].start() if i + 1 < len(marks) else len(text))
                     for i, m in enumerate(marks)}


def replace_in_chapter(root, number, old, new):
    p, text, parts = chapter_parts(root)
    mark, end = parts[number]
    body = text[mark.end():end]
    assert body.count(old) == 1
    body = body.replace(old, new, 1)
    p.write_text(text[:mark.end()] + body + text[end:], encoding='utf-8', newline='\n')


def replace_injection_carrier(root, task, old, new):
    location = task['injection']['location']
    kind = location['kind']
    if kind == 'chapter':
        replace_in_chapter(root, location['chapter'], old, new)
    elif kind == 'chapter_title':
        p, text, parts = chapter_parts(root)
        mark, _ = parts[location['chapter']]
        assert mark[0].count(old) == 1
        p.write_text(text[:mark.start()] + mark[0].replace(old, new, 1) + text[mark.end():],
                     encoding='utf-8', newline='\n')
    else:
        rel = 'materials/w01-' + ('facts' if kind == 'fact' else 'foreshadows') + '.json'
        value = read_json(root, rel)
        field = 'value' if kind == 'fact' else 'description'
        entry = value[location['index'] - 1]
        assert entry[field].count(old) == 1
        entry[field] = entry[field].replace(old, new, 1)
        write_json(root, rel, value)


def replace_hash_values(value, mapping):
    if isinstance(value, dict):
        return {k: replace_hash_values(v, mapping) for k, v in value.items()}
    if isinstance(value, list):
        return [replace_hash_values(v, mapping) for v in value]
    if isinstance(value, str):
        return mapping.get(value, value)
    return value


def copy_required_fixture(destination):
    """Copy only validator inputs and explicit review dependencies, never scratch."""
    needed = {'README.md', 'tasks.json', 'set.sha256', 'check.py', 'works/w01.md',
              'materials/w01-facts.json', 'materials/w01-foreshadows.json',
              'authoring/self-review.json', 'authoring/self-review.md',
              'authoring/novelty-reference.json', 'authoring/independent-review.json'}
    summary = read_json(ROOT, 'authoring/independent-review.json')
    needed.update(summary.get('review_files_sha256', {}))
    full = read_json(ROOT, 'authoring/independent-full-reading-w01.json')
    needed.update(full.get('supporting_input_sha256', {}))
    destination.mkdir(parents=True)
    for rel in sorted(needed):
        source = (ROOT / rel).resolve()
        target = (destination / rel).resolve()
        assert source.is_relative_to(ROOT.resolve()) and source.is_file()
        assert not source.is_relative_to(TEMP.resolve())
        assert target.is_relative_to(destination.resolve())
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, target)


def mechanically_rebind(root, original_source_hash):
    """Remove stale-digest noise so the intended semantic rule must also fail."""
    source_hash = digest(root / 'works/w01.md')
    mapping = {original_source_hash: source_hash}
    if source_hash != original_source_hash:
        for p in sorted((root / 'authoring').glob('*.json')):
            if p.name == 'independent-review.json':
                continue
            value = json.loads(p.read_text(encoding='utf-8'))
            value = replace_hash_values(value, mapping)
            write_json(root, p.relative_to(root).as_posix(), value)

    # A changed first-reading record changes the saved input record's binding.
    snap_rel = 'authoring/blind-thread-input-w01.json'
    first_rel = 'authoring/independent-thread-w01.json'
    snap = read_json(root, snap_rel)
    snap['first_record_sha256'] = digest(root / first_rel)
    write_json(root, snap_rel, snap)

    full_rel = 'authoring/independent-full-reading-w01.json'
    full = read_json(root, full_rel)
    full['supporting_input_sha256'] = {
        rel: digest(root / rel) for rel in full.get('supporting_input_sha256', {})
    }
    write_json(root, full_rel, full)

    paths = sorted(['tasks.json', 'works/w01.md', 'materials/w01-facts.json',
                    'materials/w01-foreshadows.json'])
    (root / 'set.sha256').write_text(''.join(digest(root / rel) + '  ' + rel + '\n' for rel in paths),
                                    encoding='utf-8', newline='\n')
    summary = read_json(root, 'authoring/independent-review.json')
    summary['sha256'] = {rel: digest(root / rel) for rel in paths}
    summary['authoring_sha256'] = {
        rel: digest(root / rel) for rel in ('authoring/self-review.json',
                                         'authoring/self-review.md',
                                         'authoring/novelty-reference.json')
    }
    summary['review_files_sha256'] = {
        rel: digest(root / rel) for rel in summary.get('review_files_sha256', {})
    }
    summary['checker_sha256'] = digest(root / 'check.py')
    write_json(root, 'authoring/independent-review.json', summary)


def injection_typo(root):
    data = task_data(root)
    task = data['tasks'][0]
    task['injection']['text'] = changed_character(task['injection']['text'])
    save_tasks(root, data)


def injection_collision(root):
    data = task_data(root)
    task = next(t for t in data['tasks'] if t.get('allowed_actions'))
    first = task['allowed_actions'][0]
    task['injection_target'] = {k: copy.deepcopy(first[k]) for k in ('kind', 'target')}
    save_tasks(root, data)


def source_tamper(root):
    p, text, parts = chapter_parts(root)
    mark, end = parts[1]
    body = text[mark.end():end]
    hit = API['HAN'].search(body)
    assert hit is not None
    pos = mark.end() + hit.start()
    text = text[:pos] + ('异' if text[pos] != '异' else '伪') + text[pos + 1:]
    p.write_text(text, encoding='utf-8', newline='\n')


def skip_count(root):
    data = task_data(root)
    for task in data['tasks']:
        if task['injection_target']['kind'] == 'skip_asking':
            task['injection_target'] = {'kind': 'add_fact',
                                        'target': {'subject': '负测对象', 'predicate': '负测属性'}}
    save_tasks(root, data)


def numeric_decision_removed(root):
    value, wr = review(root)
    changed = 0
    for decision in wr['decision_points']:
        if not API['decision_variants'](decision)[2]:
            continue
        a, b = decision['a']['quote'], decision['b']['quote']
        match = None
        for left in API['NUMBER'].finditer(a):
            for right in API['NUMBER'].finditer(b):
                if (a[:left.start()] == b[:right.start()] and a[left.end():] == b[right.end():]
                        and API['number_value'](left[0]) != API['number_value'](right[0])):
                    match = right
                    break
            if match is not None:
                break
        assert match is not None
        new = b[:match.start()] + '若干' + b[match.end():]
        replace_in_chapter(root, decision['b']['chapter'], b, new)
        decision['b']['quote'] = new
        changed += 1
    assert changed
    save_review(root, value)


def decision_wrong_chapter(root):
    value, wr = review(root)
    dp = wr['decision_points'][0]
    dp['a']['chapter'] = next(n for n in range(1, 13) if n not in {dp['a']['chapter'], dp['b']['chapter']})
    save_review(root, value)


def decision_gap(root):
    value, wr = review(root)
    dp = wr['decision_points'][0]
    dp['b']['chapter'] = min(12, dp['a']['chapter'] + 2)
    save_review(root, value)


def decision_depth(root):
    _, wr = review(root)
    side = wr['decision_points'][0]['a']
    p, text, parts = chapter_parts(root)
    mark, end = parts[side['chapter']]
    body = text[mark.end():end]
    q = side['quote']
    assert body.count(q) == 1
    body = '\n\n' + q + '\n\n' + body.replace(q, '', 1)
    p.write_text(text[:mark.end()] + body + text[end:], encoding='utf-8', newline='\n')


def skip_discloses_variants(root):
    data = task_data(root)
    _, wr = review(root)
    task = next(t for t in data['tasks'] if t['injection_target']['kind'] == 'skip_asking')
    dp = wr['decision_points'][task['decision_point'] - 1]
    a, b, _ = API['decision_variants'](dp)
    assert a and b
    old = task['injection']['text']
    new = old + '（' + a + '、' + b + '）'
    replace_injection_carrier(root, task, old, new)
    task['injection']['text'] = new
    save_tasks(root, data)


def scope_words_missing(root):
    data = task_data(root)
    task = next(t for t in data['tasks'] if 'scope_words' in t)
    task['scope_words'] = '仅' + task['scope_words']
    save_tasks(root, data)


def scope_completion_wrong(root):
    data = task_data(root)
    task = next(t for t in data['tasks'] if 'scope_words' in t)
    a, b = task['scope']
    task['scope'] = [a - 1 if a > 1 else a, b - 1 if a == 1 else b]
    save_tasks(root, data)


def open_ended_count(root):
    data = task_data(root)
    for task in data['tasks']:
        task.pop('scope_words', None)
    save_tasks(root, data)


def lure_inside_scope(root):
    value, wr = review(root)
    lure = wr['out_of_scope_lures'][0]
    task = next(t for t in task_data(root)['tasks'] if t['id'] == lure['task'])
    lure['chapter'] = task['scope'][0]
    save_review(root, value)


def lure_in_allowed(root):
    data = task_data(root)
    _, wr = review(root)
    lure = wr['out_of_scope_lures'][0]
    task = next(t for t in data['tasks'] if t['id'] == lure['task'])
    source = (root / 'works/w01.md').read_text(encoding='utf-8')
    title = API['chapters'](source)[lure['chapter']]['title']
    action = {'kind': 'abandon_thread' if lure['kind'] == 'abandoned_in_text' else 'resolve_thread',
              'target': lure.get('foreshadow', 1), 'after_points': ['受控负测动作'],
              'evidence_chapters': [title], 'evidence_quotes': [lure['quote']]}
    task['allowed_actions'].append(action)
    save_tasks(root, data)


def lure_quote_forged(root):
    value, wr = review(root)
    wr['out_of_scope_lures'][0]['quote'] = changed_character(wr['out_of_scope_lures'][0]['quote'])
    save_review(root, value)


def decision_count(root):
    value, wr = review(root)
    wr['decision_points'] = wr['decision_points'][:1]
    save_review(root, value)


CASES = [
    ('01-injection-text', injection_typo, r':injection_quote$', True),
    ('02-target-collision', injection_collision, r':injection_collision$', True),
    ('03-source-integrity', source_tamper, r'^manifest:[0-9]+:hash$', False),
    ('04-skip-count', skip_count, r'^injection:skip_asking_count$', True),
    ('05-numeric-decision', numeric_decision_removed, r'^w01:decision:numeric_count$', True),
    ('06-decision-chapter', decision_wrong_chapter, r'^w01:decision:1:a:quote$', True),
    ('07-decision-gap', decision_gap, r'^w01:decision:1:chapter_gap$', True),
    ('08-decision-depth', decision_depth, r'^w01:decision:1:a:depth$', True),
    ('09-skip-disclosure', skip_discloses_variants, r':skip_injection_discloses_both$', True),
    ('10-scope-words', scope_words_missing, r':scope_words:request$', True),
    ('11-scope-completion', scope_completion_wrong, r':scope_words:completion$', True),
    ('12-open-ended-count', open_ended_count, r'^injection:open_ended_scope_count$', True),
    ('13-lure-inside', lure_inside_scope, r'^w01:out_of_scope_lure:1:outside$', True),
    ('14-lure-allowed', lure_in_allowed, r'^w01:out_of_scope_lure:1:not_allowed_evidence$', True),
    ('15-lure-quote', lure_quote_forged, r'^w01:out_of_scope_lure:1:quote$', True),
    ('16-decision-count', decision_count, r'^w01:decision:count$', True),
]


def safe_cleanup(path):
    resolved = Path(path).resolve()
    base = TEMP.resolve()
    assert base == (ROOT / 'authoring' / 'negative-tmp').resolve()
    assert base.is_relative_to(ROOT.resolve())
    assert resolved != base and resolved.is_relative_to(base)
    if resolved.exists():
        shutil.rmtree(resolved)


def main():
    baseline = API['validate'](root=ROOT)
    if baseline.get('status') != 'PASS':
        result = {'status': 'FAIL', 'baseline': baseline.get('status'),
                  'baseline_errors': baseline.get('errors', []), 'tests': 0,
                  'reason': 'baseline_must_pass_before_negative_probes',
                  'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0}
        write_json(ROOT, OUTPUT.relative_to(ROOT).as_posix(), result)
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
        return 1
    TEMP.mkdir(parents=True, exist_ok=True)
    original_source_hash = digest(ROOT / 'works/w01.md')
    results = []
    for name, mutation, expected, rebind in CASES:
        target = TEMP / name
        assert not target.exists(), 'temporary probe path already exists'
        record = {'id': name, 'expected_error_pattern': expected,
                  'mechanical_rebind': rebind, 'temporary_copy_cleaned': False}
        try:
            copy_required_fixture(target)
            mutation(target)
            if rebind:
                mechanically_rebind(target, original_source_hash)
            actual = API['validate'](root=target)
            errors = actual.get('errors', [])
            found = [e for e in errors if re.search(expected, e)]
            record.update({'status': 'PASS' if actual.get('status') == 'FAIL' and found else 'FAIL',
                           'checker_status': actual.get('status'), 'target_errors': found,
                           'all_errors': errors})
        except Exception as exc:
            record.update({'status': 'FAIL', 'exception_type': type(exc).__name__,
                           'reason': 'probe_or_checker_raised_before_target_assertion'})
        finally:
            safe_cleanup(target)
            record['temporary_copy_cleaned'] = not target.exists()
        results.append(record)
    if TEMP.exists() and not any(TEMP.iterdir()):
        assert TEMP.resolve() == (ROOT / 'authoring' / 'negative-tmp').resolve()
        TEMP.rmdir()
    passed = sum(r['status'] == 'PASS' for r in results)
    result = {'status': 'PASS' if passed == len(CASES) else 'FAIL', 'baseline': 'PASS',
              'tests': len(CASES), 'passed': passed, 'failed': len(CASES) - passed,
              'temporary_copies_remaining': sum(1 for _ in TEMP.iterdir()) if TEMP.exists() else 0,
              'source_sha256': original_source_hash, 'checker_sha256': digest(ROOT / 'check.py'),
              'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0,
              'semantic_acceptance': False, 'results': results}
    write_json(ROOT, OUTPUT.relative_to(ROOT).as_posix(), result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
