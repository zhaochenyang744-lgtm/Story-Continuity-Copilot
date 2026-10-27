"""Bind completed review records and data bytes; never creates semantic judgments."""
from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def seal(root=ROOT):
    root = Path(root).resolve()
    spec = importlib.util.spec_from_file_location('a3s3_local_contract', root / 'check.py')
    checker = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(checker)
    data = json.loads((root / 'tasks.json').read_text(encoding='utf-8'))
    review = json.loads((root / 'authoring/self-review.json').read_text(encoding='utf-8'))
    proof = checker.verify_review_records(root, data, review['works'])
    if proof['errors']:
        return {'status': 'FAIL', 'errors': proof['errors']}
    paths = sorted(['tasks.json', 'works/w01.md', 'materials/w01-facts.json', 'materials/w01-foreshadows.json'])
    authoring = ['authoring/self-review.json', 'authoring/self-review.md', 'authoring/novelty-reference.json']
    summary = {
        'status': 'completed',
        'unresolved_findings': 0,
        'chapter_coverage': proof['chapter_coverage'],
        'sha256': {p: digest(root / p) for p in paths},
        'authoring_sha256': {p: digest(root / p) for p in authoring},
        'review_files_sha256': {p: digest(root / p) for p in proof['raw_files']},
        'blind_threads': proof['blind_threads'],
        'checker_sha256': digest(root / 'check.py'),
    }
    (root / 'authoring/independent-review.json').write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')
    (root / 'set.sha256').write_text(''.join(f'{digest(root / p)}  {p}\n' for p in paths),
                                      encoding='utf-8', newline='\n')
    return {'status': 'PASS', 'data_files': len(paths), 'review_files': len(proof['raw_files']),
            'blind_threads': proof['blind_threads']}


if __name__ == '__main__':
    result = seal()
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    raise SystemExit(result['status'] != 'PASS')
