"""Reproducible, standard-library-only offline authoring audits.

Run from any directory using the designated interpreter with -X utf8 -B:
  audit-tools.py corpus --names-source planned
  audit-tools.py corpus --names-source tasks
  audit-tools.py source

No prose is generated. Sealed prior corpora are compared in memory and produce
counts only; their text and normalized inputs are never written to a snapshot.
The prohibited concurrent set is skipped before any path probing or traversal.
"""
from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import sys
import unicodedata

SET_ROOT = Path(__file__).resolve().parents[1]
EVALUATION = SET_ROOT.parent
REPO = EVALUATION.parent
SEALED = ('eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring')
PROHIBITED = frozenset({'eval_set_a2n7_formal'})
EXCLUDED = list(SEALED) + ['eval_set_a2n7_formal']
PLANNED_NAMES = (
    '迟砚岫', '岫线', '屠予铮', '铮尾', '乔闻荻', '荻哨', '巴映铄', '岑沅枢',
    '宗茵璧', '许照砾', '彭纾鹭', '温缈策', '邹牧斓', '辙珀星', '斜晖环道',
    '折芒帆艇', '回衡舵芯',
)
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def sha256(raw):
    return hashlib.sha256(raw).hexdigest()


def normalize(text):
    return ''.join(c for c in text if not c.isspace() and not unicodedata.category(c).startswith('P'))


def write_json(relative, value):
    path = SET_ROOT / relative
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def prior_files():
    """Yield only md/json files under readable or machine-comparable prior sets."""
    for directory in sorted(EVALUATION.iterdir(), key=lambda p: p.name):
        # No exists/is_dir/resolve/rglob call is made for a prohibited name.
        if directory.name in PROHIBITED or directory.name == SET_ROOT.name:
            continue
        if not directory.name.startswith('eval_set_') or not directory.is_dir():
            continue
        if directory.is_symlink():
            raise ValueError('prior_directory_symlink')
        for path in sorted(directory.rglob('*')):
            if path.suffix.lower() not in {'.md', '.json'} or not path.is_file():
                continue
            if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
                raise ValueError('prior_file_path')
            yield directory.name, path


def input_strings(value):
    if isinstance(value, dict):
        for key, item in value.items():
            if key in {'input', 'question', 'request'} and isinstance(item, str):
                yield item
            elif isinstance(item, (dict, list)):
                yield from input_strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from input_strings(item)


def candidate_names(source):
    if source == 'planned':
        names = list(PLANNED_NAMES)
    else:
        tasks = json.loads((SET_ROOT / 'tasks.json').read_text(encoding='utf-8'))
        names = [name for work in tasks['works'] for name in work['names']]
    if not names or len(names) != len(set(names)) or not all(isinstance(n, str) and n for n in names):
        raise ValueError('candidate_names')
    return sorted(names)


def corpus_audit(names_source):
    names = candidate_names(names_source)
    candidate_hash = sha256(json.dumps(names, ensure_ascii=False).encode('utf-8'))
    source_hashes, text_hashes, by_source = {}, {}, {}
    readable_counts, sealed_counts = {}, {}
    readable_matching_names, sealed_matching_names = set(), set()
    readable_occurrences = readable_matching_files = 0
    for directory, path in prior_files():
        raw = path.read_bytes()
        text = raw.decode('utf-8-sig')
        counts = Counter({n: text.count(n) for n in names})
        hits = {n for n, count in counts.items() if count}
        if directory in SEALED:
            record = sealed_counts.setdefault(directory, {'text_files': 0, 'matching_files': 0, 'occurrences': 0})
            record['text_files'] += 1
            record['matching_files'] += int(bool(hits))
            record['occurrences'] += sum(counts.values())
            sealed_matching_names.update(hits)
            continue
        relative = path.relative_to(REPO).as_posix()
        text_hashes[relative] = sha256(raw)
        readable_counts[directory] = readable_counts.get(directory, 0) + 1
        readable_matching_files += int(bool(hits))
        readable_occurrences += sum(counts.values())
        readable_matching_names.update(hits)
        if path.name == 'tasks.json':
            data = json.loads(text)
            by_source[relative] = sorted({normalize(item) for item in input_strings(data) if normalize(item)})
            source_hashes[relative] = sha256(raw)
    old = sorted({item for items in by_source.values() for item in items})
    reference = {
        'excluded_directories': EXCLUDED,
        'normalized_inputs': old,
        'normalized_inputs_by_source': by_source,
        'source_hashes': source_hashes,
        'names_corpus_sha256': text_hashes,
        'candidate_names_sha256': candidate_hash,
        'names_overlap': len(readable_matching_names),
        'reference_counts': {
            'source_files': len(source_hashes), 'normalized_inputs': len(old),
            'names_text_files': len(text_hashes),
        },
    }
    audit = {
        'status': 'PASS' if not readable_matching_names and not sealed_matching_names else 'FAIL',
        'candidate_names': len(names), 'candidate_names_sha256': candidate_hash,
        'names_source': names_source,
        'readable': {
            'directories': len(readable_counts), 'text_files': len(text_hashes),
            'files_by_directory': readable_counts,
            'matching_names': len(readable_matching_names), 'matching_files': readable_matching_files,
            'occurrences': readable_occurrences, 'task_source_files': len(source_hashes),
            'normalized_inputs': len(old),
        },
        'sealed': {
            'directories_scoped': len(SEALED), 'directories': len(sealed_counts),
            'files_by_directory': {name: sealed_counts.get(name, {'text_files': 0, 'matching_files': 0, 'occurrences': 0})
                                  for name in SEALED},
            'matching_names': len(sealed_matching_names),
            'text_files': sum(c['text_files'] for c in sealed_counts.values()),
            'matching_files': sum(c['matching_files'] for c in sealed_counts.values()),
            'occurrences': sum(c['occurrences'] for c in sealed_counts.values()),
            'content_output': 0,
        },
        'excluded_directories': EXCLUDED,
        'prohibited_files_read': 0,
    }
    write_json('authoring/novelty-reference.json', reference)
    write_json('authoring/prior-corpus-audit.json', audit)
    return audit


def source_audit():
    result = {'status': 'PASS', 'works': {}, 'utf8_bom_files': 0, 'cr_files': 0}
    for path in SET_ROOT.rglob('*'):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        result['utf8_bom_files'] += int(raw.startswith(b'\xef\xbb\xbf'))
        result['cr_files'] += int(b'\r' in raw)
    for path in sorted((SET_ROOT / 'works').glob('*.md')):
        text = path.read_text(encoding='utf-8')
        marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 [^\r\n]+$', text, re.M))
        lengths, repeated = [], Counter()
        for i, mark in enumerate(marks):
            body = text[mark.end():marks[i+1].start() if i+1 < len(marks) else len(text)]
            lengths.append(len(HAN.findall(body)))
            repeated.update(s.strip() for s in re.split(r'[。！？]', body) if len(HAN.findall(s)) >= 15)
        result['works'][path.stem] = {
            'chapters': len(marks), 'chapter_han': lengths, 'total_han': sum(lengths),
            'repeated_sentences': sum(v - 1 for v in repeated.values() if v > 1),
            'sha256': sha256(path.read_bytes()),
        }
    if result['utf8_bom_files'] or result['cr_files']:
        result['status'] = 'FAIL'
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    corpus = commands.add_parser('corpus')
    corpus.add_argument('--names-source', choices=('planned', 'tasks'), required=True)
    commands.add_parser('source')
    args = parser.parse_args()
    try:
        result = corpus_audit(args.names_source) if args.command == 'corpus' else source_audit()
    except Exception:
        result = {'status': 'FAIL', 'errors': ['audit:unreadable_or_invalid']}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    sys.exit(main())
