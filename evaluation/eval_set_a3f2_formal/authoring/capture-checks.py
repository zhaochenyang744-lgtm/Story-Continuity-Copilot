"""Capture required root-module and arbitrary-directory absolute-path checks."""
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import subprocess
import sys
import tempfile

REPO = Path(__file__).resolve().parents[3]
SETS = ['eval_set_a3f2_formal', 'eval_set_a3s2_formal']


def run(job):
    sid, mode = job
    root = REPO / 'evaluation' / sid
    bindings = json.loads((root/'authoring/independent-review.json').read_text(encoding='utf-8'))['sha256']
    before = {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings}
    command = [sys.executable, '-X', 'utf8', '-B']
    if mode == 'module':
        command += ['-m', 'evaluation.' + sid + '.check']
        cwd = REPO
    else:
        command += [str(root / 'check.py')]
        cwd = Path(tempfile.gettempdir()).resolve()
    result = subprocess.run(command, cwd=cwd, text=True, encoding='utf-8', capture_output=True)
    output = result.stdout.strip()
    parsed = json.loads(output)
    after = {p: hashlib.sha256((root/p).read_bytes()).hexdigest() for p in bindings}
    return sid, mode, {'exit_code': result.returncode, 'stdout': output, 'output': parsed,
                       'stderr_empty': not result.stderr.strip(), 'data_sha256': before,
                       'data_unchanged': before == after == bindings}


def main():
    jobs = [(s, m) for s in SETS for m in ('module', 'absolute')]
    with ThreadPoolExecutor(max_workers=4) as pool:
        values = list(pool.map(run, jobs))
    records = {s: {} for s in SETS}
    for sid, mode, result in values:
        records[sid][mode] = result
    failures = []
    for sid, record in records.items():
        for mode, result in record.items():
            if result['exit_code'] or result['output'].get('status') != 'PASS' or not result['stderr_empty'] or not result['data_unchanged']:
                failures.append(sid + ':' + mode)
        identical = record['module']['output'] == record['absolute']['output']
        if not identical:
            failures.append(sid + ':cwd_output_difference')
        record['outputs_identical'] = identical
        (REPO / 'evaluation' / sid / 'authoring/check-results.json').write_text(
            json.dumps(record, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'checks': len(values), 'passed': len(values)-sum(r['exit_code'] != 0 or r['output'].get('status') != 'PASS'
                                                                    for _, _, r in values),
                      'cwd_pairs_identical': sum(r['outputs_identical'] for r in records.values()),
                      'errors': failures}, ensure_ascii=False, sort_keys=True))
    return int(bool(failures))


if __name__ == '__main__':
    raise SystemExit(main())
