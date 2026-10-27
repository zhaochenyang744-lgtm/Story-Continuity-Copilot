"""Authoring-only offline corpus receipts; stdout never contains source text.

Ordinary, previously used corpora supply normalized input snapshots.  The three
reserve corpora are read only by this program and leave counts and hashes only.
The independently authored A3 sets are pruned before traversal or file access.
"""
from __future__ import annotations

import argparse
from difflib import SequenceMatcher
import hashlib
import json
import os
from pathlib import Path
import sys
import unicodedata


ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[1]
EVALUATION = REPO / 'evaluation'
SEALED = ['eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring']
BLOCKED = {'eval_set_a3f2_formal', 'eval_set_a3s2_formal', 'eval_set_a3s3_formal'}
PRUNED = BLOCKED | {ROOT.name, '__pycache__', '.git', 'node_modules'}
EXTENSIONS = {'.md', '.json'}
NORMALIZATION = 'remove_whitespace_and_unicode_punctuation_preserve_case'


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def norm(value: str) -> str:
    return ''.join(c for c in value if not c.isspace()
                   and not unicodedata.category(c).startswith('P'))


def inputs(obj) -> list[str]:
    result = []
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {'request', 'input', 'question'} and isinstance(value, str):
                cleaned = norm(value)
                if cleaned:
                    result.append(cleaned)
            elif isinstance(value, (list, dict)):
                result.extend(inputs(value))
    elif isinstance(obj, list):
        for value in obj:
            result.extend(inputs(value))
    return result


def write(path: Path, obj) -> None:
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n',
                    encoding='utf-8', newline='\n')


def linked(path: Path) -> bool:
    return path.is_symlink() or (hasattr(path, 'is_junction') and path.is_junction())


def corpus() -> tuple[dict, dict, dict]:
    ordinary, sealed, texts = {}, {}, {}
    for base, dirs, files in os.walk(EVALUATION, followlinks=False):
        # No stat, recursion or file read is performed on any blocked set.
        dirs[:] = sorted(name for name in dirs
                         if name not in PRUNED and not linked(Path(base) / name))
        folder = Path(base)
        parts = folder.relative_to(EVALUATION).parts
        if not parts or not parts[0].startswith('eval_set_'):
            continue
        for filename in sorted(files):
            path = folder / filename
            if path.suffix.lower() not in EXTENSIONS or linked(path):
                continue
            if not path.resolve().is_relative_to(EVALUATION.resolve()):
                raise ValueError('corpus_path')
            relative = path.relative_to(REPO).as_posix()
            raw = path.read_bytes()
            value = raw.decode('utf-8-sig')
            obj = None
            if path.suffix.lower() == '.json':
                # Parse escaped Unicode before exact name comparison as well.
                obj = json.loads(value)
                value = json.dumps(obj, ensure_ascii=False)
            group = sealed if parts[0] in SEALED else ordinary
            group[relative] = {
                'hash': hashlib.sha256(raw).hexdigest(),
                'inputs': inputs(obj) if filename == 'tasks.json' else [],
            }
            texts[relative] = value
    return ordinary, sealed, texts


def names_digest(names: list[str]) -> str:
    return hashlib.sha256(json.dumps(sorted(names), ensure_ascii=False)
                          .encode('utf-8')).hexdigest()


def names_from(data) -> list[str]:
    return sorted(name for work in data['works'] for name in work['names'])


def overlaps(names: list[str], sources: dict, texts: dict) -> list[int]:
    return [number for number, name in enumerate(names, 1)
            if any(name in texts[relative] for relative in sources)]


def novelty_count(new_inputs: list[str], old_inputs: list[str]) -> int:
    # The length bound skips only pairs that cannot reach the registered .80.
    return sum(any(new == old or (
        2 * min(len(new), len(old)) / max(1, len(new) + len(old)) >= .8
        and SequenceMatcher(None, new, old).ratio() >= .8)
        for old in old_inputs) for new in new_inputs)


def candidate_paths() -> list[str]:
    paths = ['tasks.json']
    for name in ('works', 'materials'):
        folder = ROOT / name
        if not folder.is_dir() or linked(folder):
            raise ValueError('candidate_folder')
        for base, dirs, files in os.walk(folder, followlinks=False):
            if any(linked(Path(base) / child) for child in dirs):
                raise ValueError('candidate_link')
            for filename in files:
                path = Path(base) / filename
                if linked(path) or not path.resolve().is_relative_to(ROOT):
                    raise ValueError('candidate_path')
                paths.append(path.relative_to(ROOT).as_posix())
    return sorted(paths)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preflight', action='store_true')
    parser.add_argument('--names-file', type=Path,
                        help='optional candidate-only JSON array of names')
    parser.add_argument('--names-json',
                        help='optional candidate-only JSON array of names')
    args = parser.parse_args(argv)
    if args.names_file is not None and args.names_json is not None:
        raise ValueError('candidate_names_arguments')
    data = None
    if args.names_file is not None:
        path = args.names_file.resolve()
        if not path.is_relative_to(ROOT) or linked(path):
            raise ValueError('candidate_names_path')
        names = json.loads(path.read_text(encoding='utf-8-sig'))
    elif args.names_json is not None:
        names = json.loads(args.names_json)
    else:
        data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
        names = names_from(data)
    if not isinstance(names, list) or not names or not all(
            isinstance(name, str) and name.strip() for name in names):
        raise ValueError('candidate_names')
    names = sorted(names)
    ordinary, sealed, texts = corpus()
    ordinary_overlap = overlaps(names, ordinary, texts)
    sealed_overlap = overlaps(names, sealed, texts)
    if args.preflight:
        out = {'status': 'FAIL' if ordinary_overlap or sealed_overlap else 'PASS',
               'names': len(names),
               'names_overlap': len(set(ordinary_overlap) | set(sealed_overlap)),
               'name_indices': sorted(set(ordinary_overlap) | set(sealed_overlap)),
               'ordinary_overlap': len(ordinary_overlap),
               'sealed_overlap': len(sealed_overlap),
               'names_text_files': len(texts),
               'candidate_names_sha256': names_digest(names),
               'blocked_directories_accessed': 0}
        write(ROOT / 'authoring/name-preflight.json', out)
        print(json.dumps(out, ensure_ascii=True))
        return 1 if ordinary_overlap or sealed_overlap else 0
    if data is None:
        data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
    if names != names_from(data):
        raise ValueError('candidate_names_binding')
    new_inputs = inputs(data['tasks'])
    grouped = {relative: sorted(set(item['inputs']))
               for relative, item in ordinary.items()
               if Path(relative).name == 'tasks.json'}
    source_hashes = {relative: ordinary[relative]['hash'] for relative in grouped}
    old_inputs = sorted({value for values in grouped.values() for value in values})
    ordinary_novelty = novelty_count(new_inputs, old_inputs)
    reference = {
        'normalization': NORMALIZATION,
        'excluded_directories': SEALED,
        'source_hashes': source_hashes,
        'normalized_inputs_by_source': grouped,
        'normalized_inputs': old_inputs,
        'names_corpus_sha256': {relative: item['hash']
                                for relative, item in ordinary.items()},
        'reference_counts': {'source_files': len(source_hashes),
                             'normalized_inputs': len(old_inputs),
                             'names_text_files': len(ordinary)},
        'names_overlap': len(ordinary_overlap),
        'candidate_names_sha256': names_digest(names),
    }
    sealed_inputs = sorted({value for item in sealed.values() for value in item['inputs']})
    sealed_novelty = novelty_count(new_inputs, sealed_inputs)
    receipt = {
        'status': 'FAIL' if sealed_overlap or sealed_novelty else 'PASS',
        'candidate_sha256': {relative: sha(ROOT / relative)
                             for relative in candidate_paths()},
        'names_overlap': len(sealed_overlap),
        'novelty_errors': sealed_novelty,
        'source_hashes': {relative: item['hash'] for relative, item in sealed.items()},
        'excluded_directories': SEALED,
        'reference_counts': {'source_files': sum(Path(relative).name == 'tasks.json'
                                                for relative in sealed),
                             'normalized_inputs': len(sealed_inputs),
                             'names_text_files': len(sealed)},
    }
    write(ROOT / 'authoring/novelty-reference.json', reference)
    write(ROOT / 'authoring/sealed-comparison.json', receipt)
    failed = bool(ordinary_overlap or sealed_overlap or ordinary_novelty or sealed_novelty)
    out = {'status': 'FAIL' if failed else 'PASS', 'sets': 1,
           'names': len(names), 'names_overlap': len(set(ordinary_overlap) | set(sealed_overlap)),
           'ordinary_names_overlap': len(ordinary_overlap),
           'sealed_names_overlap': len(sealed_overlap),
           'novelty_errors': ordinary_novelty,
           'sealed_novelty_errors': sealed_novelty,
           'reference_inputs': len(old_inputs),
           'sealed_reference_inputs': len(sealed_inputs),
           'names_text_files': len(texts), 'candidate_files': len(receipt['candidate_sha256']),
           'blocked_directories_accessed': 0, 'model_calls': 0}
    print(json.dumps(out, ensure_ascii=True))
    return 1 if failed else 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (OSError, UnicodeError, ValueError, TypeError, KeyError):
        # Exception messages may contain source snippets or names; do not echo.
        print(json.dumps({'status': 'FAIL', 'errors': ['audit:structure_or_io'],
                          'blocked_directories_accessed': 0}))
        raise SystemExit(2)
