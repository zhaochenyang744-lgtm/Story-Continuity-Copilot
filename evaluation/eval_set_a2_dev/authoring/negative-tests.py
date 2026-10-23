"""Offline mutation tests on disposable copies; never edits the delivered corpus."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def manifest(root: Path) -> None:
    files = [root / 'tasks.json']
    for dirname in ('works', 'materials'):
        files.extend(p for p in (root / dirname).rglob('*') if p.is_file())
    files.sort(key=lambda p: p.relative_to(root).as_posix())
    (root / 'set.sha256').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.relative_to(root).as_posix() + '\n'
        for p in files), encoding='utf-8', newline='\n')


def main() -> int:
    records = []
    cases = ('delete_change_task', 'alter_evidence_character', 'target_nonstale_fact', 'alter_source_character')
    with tempfile.TemporaryDirectory(prefix='a2-dev-negative-') as temp:
        temp_root = Path(temp).resolve()
        for case in cases:
            root = temp_root / case
            shutil.copytree(ROOT, root)
            data = json.loads((root / 'tasks.json').read_text(encoding='utf-8'))
            actions = [t for t in data['tasks'] if t['suite'] == 'action']
            if case == 'delete_change_task':
                victim = next(t for t in actions if t['expected_actions'][0]['kind'] == 'change_fact')
                data['tasks'].remove(victim)
            elif case == 'alter_evidence_character':
                action = actions[0]['expected_actions'][0]
                quote = action['evidence_quotes'][0]
                action['evidence_quotes'][0] = ('龘' if quote[0] != '龘' else '靐') + quote[1:]
            elif case == 'target_nonstale_fact':
                review = json.loads((root / 'authoring/self-review.json').read_text(encoding='utf-8'))
                stale = {item['fact'] for item in review['stale_facts']}
                facts = json.loads((root / 'materials/w01-facts.json').read_text(encoding='utf-8'))
                target = next(n for n in range(1, len(facts) + 1) if n not in stale)
                victim = next(t for t in actions if t['expected_actions'][0]['kind'] == 'change_fact')
                victim['expected_actions'][0]['target'] = target
            else:
                source = root / 'works/w01.md'
                text = source.read_text(encoding='utf-8')
                offset = text.index('\n') + 1
                while offset < len(text) and text[offset].isspace():
                    offset += 1
                text = text[:offset] + ('龘' if text[offset] != '龘' else '靐') + text[offset + 1:]
                source.write_text(text, encoding='utf-8', newline='\n')
            if case != 'alter_source_character':
                (root / 'tasks.json').write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n',
                                               encoding='utf-8', newline='\n')
                manifest(root)
            # Import the original checker so novelty still uses the original worktree.
            # The checker receives only the disposable set directory for validation.
            code = (
                'import importlib.util,json,pathlib,sys; '
                'spec=importlib.util.spec_from_file_location("a2_check",sys.argv[1]); '
                'module=importlib.util.module_from_spec(spec); spec.loader.exec_module(module); '
                'result=module.validate(pathlib.Path(sys.argv[2])); '
                'print(json.dumps(result,ensure_ascii=False)); '
                'sys.exit(1 if result["status"]=="FAIL" else 0)'
            )
            proc = subprocess.run([sys.executable, '-X', 'utf8', '-B', '-c', code,
                                   str(ROOT / 'check.py'), str(root)], cwd=temp_root,
                                  text=True, capture_output=True, encoding='utf-8', check=False)
            try:
                result = json.loads(proc.stdout)
            except json.JSONDecodeError:
                result = {'status': 'INVALID_OUTPUT', 'errors': [proc.stderr.strip()]}
            errors = result.get('errors', [])
            # The first three mutations have valid new hashes: failures must be structural.
            detected = proc.returncode != 0 and result.get('status') == 'FAIL' and bool(errors)
            if case != 'alter_source_character':
                detected = detected and any('manifest' not in error for error in errors)
                detected = detected and not any('manifest' in error for error in errors)
            else:
                detected = detected and any('manifest' in error for error in errors)
            records.append({'case': case, 'manifest_rebuilt': case != 'alter_source_character',
                            'returncode': proc.returncode, 'detected': detected,
                            'checker_output': result})
    output = {'status': 'PASS' if all(item['detected'] for item in records) else 'FAIL',
              'cases': records, 'temporary_copies_removed': True}
    (ROOT / 'authoring/negative-test-results.json').write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    print(json.dumps(output, ensure_ascii=False))
    return 0 if output['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
