"""Twelve isolated mutations; every case must hit its own structural check."""
from __future__ import annotations

from copy import deepcopy
import importlib.util
import json
from pathlib import Path
import re
import shutil
import uuid

ROOT = Path(__file__).resolve().parents[1]
TEMP_PARENT = ROOT.parent.resolve()
TEMP_PREFIX = '.a2n7-negative-'


def load(relative, root):
    return json.loads((root / relative).read_text(encoding='utf-8'))


def save(relative, value, root):
    (root / relative).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8', newline='\n')


def modify_tasks(root, predicate, change):
    data = load('tasks.json', root)
    task = next(task for task in data['tasks'] if predicate(task))
    change(task)
    save('tasks.json', data, root)


def primary(task, kind):
    return task.get('suite') == 'action' and task.get('expected_actions', [{}])[0].get('kind') == kind


def remove_action(root, kind):
    data = load('tasks.json', root)
    task = next(task for task in data['tasks'] if primary(task, kind))
    data['tasks'].remove(task)
    save('tasks.json', data, root)


def different_quote(value):
    assert isinstance(value, str) and value
    return value[:-1] + ('靐' if value[-1] == '龘' else '龘')


def evidence_mutation(root):
    def change(task):
        entry = task['expected_actions'][0]
        entry['evidence_quotes'][0] = different_quote(entry['evidence_quotes'][0])
    modify_tasks(root, lambda task: task.get('suite') == 'action' and
                 bool(task['expected_actions'][0]['evidence_quotes']), change)


def alias_mutation(root):
    modify_tasks(root, lambda task: primary(task, 'change_fact'),
                 lambda task: task['alias_use'].__setitem__('fact', 0))


def premise_quote_mutation(root):
    modify_tasks(root, lambda task: task.get('premise_contradicted') is True,
                 lambda task: task['premise_evidence'].__setitem__('quote',
                     different_quote(task['premise_evidence']['quote'])))


def premise_why_mutation(root):
    modify_tasks(root, lambda task: task.get('premise_contradicted') is True,
                 lambda task: task.__setitem__('why', '结构负例，移除了要求逐字引用的依据。'))


def recorded_target_mutation(root):
    count = len(load('materials/w01-facts.json', root))
    modify_tasks(root, lambda task: task.get('no_action_type') == 'already_recorded',
                 lambda task: task.__setitem__('request_targets', {'facts': [count + 1], 'foreshadows': []}))


def double_action_mutation(root):
    modify_tasks(root, lambda task: task.get('suite') == 'action',
                 lambda task: task['expected_actions'].append(deepcopy(task['expected_actions'][0])))


def source_mutation(root):
    path = root / 'works/w01.md'
    source = path.read_text(encoding='utf-8')
    positions = list(re.finditer(r'[\u3400-\u4dbf\u4e00-\u9fff]', source))
    assert positions
    position = positions[-1].start()
    replacement = '靐' if source[position] == '龘' else '龘'
    path.write_text(source[:position] + replacement + source[position + 1:], encoding='utf-8', newline='\n')


def manifest_mutation(root):
    path = root / 'set.sha256'
    lines = path.read_text(encoding='utf-8').splitlines()
    assert lines
    path.write_text('\n'.join(lines[1:]) + '\n', encoding='utf-8', newline='\n')


def blind_verdict_mutation(root):
    data = load('authoring/blind-verdicts.json', root)
    data['verdicts'][0]['card'] = not data['verdicts'][0]['card']
    save('authoring/blind-verdicts.json', data, root)


def alias_fact_mutation(root):
    review = load('authoring/self-review.json', root)['works']['w01']
    alias = review['aliases'][0]
    facts = load('materials/w01-facts.json', root)
    changed = 0
    for fact in facts:
        if fact['subject'] == alias['name'] and alias['alias'] in fact['value']:
            fact['value'] = '未登记该别名的对应关系'
            changed += 1
    assert changed
    save('materials/w01-facts.json', facts, root)


def safe_cleanup(path):
    target = path.resolve()
    assert target == path and target.parent == TEMP_PARENT
    assert target != ROOT.resolve() and target.is_relative_to(TEMP_PARENT)
    assert target.name.startswith(TEMP_PREFIX) and re.fullmatch(r'\.a2n7-negative-[0-9a-f]{32}', target.name)
    assert target.is_dir()
    for item in [target, *target.rglob('*')]:
        info = item.lstat()
        assert not item.is_symlink() and not (getattr(info, 'st_file_attributes', 0) & 0x400)
        assert item.resolve().is_relative_to(target)
    shutil.rmtree(target)
    assert not target.exists()


def run():
    spec = importlib.util.spec_from_file_location('a2n7_negative_checker', ROOT / 'check.py')
    assert spec is not None and spec.loader is not None
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    baseline = checker.validate(ROOT)
    assert baseline.get('status') == 'PASS', 'baseline_not_pass'
    cases = [
        ('N01', lambda root: remove_action(root, 'change_fact'), r'^w01:primary_actions$'),
        ('N02', lambda root: remove_action(root, 'abandon_thread'), r'^w01:primary_actions$'),
        ('N03', evidence_mutation, r'^a2n7-.*:action:1:evidence:1:quote$'),
        ('N04', alias_mutation, r'^a2n7-.*:alias_use_fields$'),
        ('N05', premise_quote_mutation, r'^a2n7-.*:premise_evidence:quote$'),
        ('N06', premise_why_mutation, r'^a2n7-.*:premise_why_quote$'),
        ('N07', recorded_target_mutation, r'^a2n7-.*:request_targets$'),
        ('N08', double_action_mutation, r'^a2n7-.*:actions$'),
        ('N09', source_mutation, r'^blind:work_packet$'),
        ('N10', manifest_mutation, r'^manifest:coverage_order$'),
        ('N11', blind_verdict_mutation, r'^blind:verdict:1:fields$'),
        ('N12', alias_fact_mutation, r'^w01:alias:[0-9]+:fact_identity$'),
    ]
    results = []
    for case_id, mutate, expected_pattern in cases:
        temporary = (TEMP_PARENT / (TEMP_PREFIX + uuid.uuid4().hex)).resolve()
        assert temporary.parent == TEMP_PARENT and temporary != ROOT.resolve() and not temporary.exists()
        result = {'id': case_id, 'status': 'FAIL', 'validator_status': 'ERROR', 'validator_exit': 1,
                  'expected_error_hits': 0, 'matched_errors': [], 'cleanup': False}
        try:
            shutil.copytree(ROOT, temporary)
            mutate(temporary)
            validation = checker.validate(temporary)
            errors = validation.get('errors', [])
            matched = [error for error in errors if isinstance(error, str) and re.fullmatch(expected_pattern, error)]
            result.update({'validator_status': validation.get('status'),
                           'validator_exit': 1 if validation.get('status') == 'FAIL' else 0,
                           'expected_error_hits': len(matched), 'matched_errors': matched,
                           'error_count': len(errors)})
            if validation.get('status') == 'FAIL' and matched:
                result['status'] = 'PASS'
        except Exception:
            result['errors'] = ['negative:mutation_or_validator_exception']
        finally:
            if temporary.exists():
                try:
                    safe_cleanup(temporary)
                    result['cleanup'] = True
                except Exception:
                    result['status'] = 'FAIL'
                    result['errors'] = ['negative:cleanup_verification_failed']
            else:
                result['cleanup'] = True
        results.append(result)
    passed = sum(result['status'] == 'PASS' for result in results)
    report = {'status': 'PASS' if passed == len(cases) else 'FAIL', 'baseline_status': 'PASS',
              'invocation': 'validate(temporary_copy)', 'total': len(cases), 'passed': passed,
              'failed': len(cases) - passed, 'temporary_directories_remaining': sum(not result['cleanup'] for result in results),
              'cases': results, 'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0}
    save('authoring/negative-tests.json', report, ROOT)
    return report


def main():
    try:
        result = run()
    except Exception:
        result = {'status': 'FAIL', 'errors': ['negative:baseline_or_harness_failure'],
                  'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
