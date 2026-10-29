"""Validate complete raw independent records before binding final data."""
import argparse
import hashlib
import json
from pathlib import Path
from review_validation import verify_review_records

REPO = Path(__file__).resolve().parents[3]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--set', required=True, choices=['eval_set_a3f2_formal', 'eval_set_a3s2_formal'])
    root = REPO / 'evaluation' / parser.parse_args().set
    data = load(root / 'tasks.json')
    gold = load(root / 'authoring/self-review.json')['works']
    proof = verify_review_records(root, data, gold)
    if proof['errors']:
        print(json.dumps({'status': 'FAIL', 'errors': proof['errors']}, ensure_ascii=False, sort_keys=True))
        return 1
    paths = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for d in ('works', 'materials')
                                    for p in (root/d).rglob('*') if p.is_file()])
    authoring = ['authoring/self-review.json', 'authoring/self-review.md', 'authoring/novelty-reference.json']
    result = {'status': 'completed', 'unresolved_findings': 0, 'chapter_coverage': proof['chapter_coverage'],
              'sha256': {p: sha(root/p) for p in paths}, 'authoring_sha256': {p: sha(root/p) for p in authoring},
              'review_files_sha256': {p: sha(root/p) for p in proof['raw_files']},
              'blind_threads': proof['blind_threads'], 'checker_sha256': sha(root/'check.py')}
    if proof['blind_route'] is not None:
        result['blind_route'] = proof['blind_route']
    (root/'authoring/independent-review.json').write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    (root/'set.sha256').write_text(''.join(sha(root/p)+'  '+p+'\n' for p in paths), encoding='utf-8', newline='\n')
    print(json.dumps({'status': 'PASS', 'data_files': len(paths), 'review_files': len(proof['raw_files']),
                      'blind_threads': proof['blind_threads'], 'blind_route': proof['blind_route']}, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
