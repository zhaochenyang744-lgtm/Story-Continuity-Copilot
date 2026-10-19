"""Offline count/repetition/position/hash audits; never generates narrative.

Old-corpus novelty scanning explicitly excludes both protected reserve sets.
Ordinary operation reads only this new set. Use --novelty for the allowed
corpus comparison, with numeric/structural output and no matched prose.
"""
from pathlib import Path
from collections import Counter
import argparse
import hashlib
import json
import os
import re

ROOT = Path(__file__).resolve().parents[1]
HAN = re.compile(r"[\u3400-\u4dbf\u4e00-\u9fff]")


def han(value):
    return ''.join(HAN.findall(value))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--novelty', action='store_true')
    args = parser.parse_args()
    output = {'scope': 'this_set_only', 'works': []}
    all_paragraphs = Counter()
    for path in sorted((ROOT / 'works').glob('*.md')):
        raw = path.read_bytes()
        source = raw.decode('utf-8')
        headings = list(re.finditer(r'^# (.+)$', source, re.M))
        counts = []
        repeated = Counter()
        for i, hit in enumerate(headings):
            body = source[hit.end():headings[i + 1].start() if i + 1 < len(headings) else len(source)].strip()
            counts.append(len(han(body)))
            for paragraph in re.split(r'\n\s*\n', body):
                normalized = han(paragraph)
                if len(normalized) >= 40:
                    repeated[normalized] += 1
                    all_paragraphs[normalized] += 1
        output['works'].append({'key': path.stem, 'chapters': len(headings),
            'chapter_han_counts': counts, 'han_min': min(counts, default=0),
            'han_max': max(counts, default=0), 'total_han': sum(counts),
            'duplicate_paragraphs_40han': sum(v - 1 for v in repeated.values() if v > 1),
            'utf8_no_bom_lf': not raw.startswith(b'\xef\xbb\xbf') and b'\r' not in raw,
            'sha256': hashlib.sha256(raw).hexdigest()})
    output['duplicate_paragraphs_all_works_40han'] = sum(v - 1 for v in all_paragraphs.values() if v > 1)
    if args.novelty:
        data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
        names = {n for w in data['works'] for n in w['names']} | {w['title'] for w in data['works']}
        excluded = {'eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_a1c2_formal', 'eval_set_a1cs2_formal'}
        paths = []
        for current, directories, files in os.walk(ROOT.parent, followlinks=False):
            directories[:] = sorted(d for d in directories if d not in excluded and not (Path(current) / d).is_symlink() and not (hasattr(Path(current) / d, 'is_junction') and (Path(current) / d).is_junction()))
            for name in sorted(files):
                path = Path(current) / name
                if path.suffix in {'.md', '.json', '.txt', '.jsonl', '.csv', '.yaml', '.yml', '.toml'} and not path.is_symlink():
                    paths.append(path)
        hit_names = set()
        pairs = 0
        for path in paths:
            source = path.read_text(encoding='utf-8-sig')
            matched = {n for n in names if n in source}
            hit_names |= matched
            pairs += len(matched)
        output['novelty'] = {'scanned_files': len(paths), 'corpus': 'all_permitted_evaluation_text_files', 'new_names_and_titles': len(names),
            'overlapping_names': len(hit_names), 'name_file_matches': pairs,
            'protected_reserve_directories_excluded': 2, 'claim_covers_unread_reserves': False}
        output['scope'] = 'this_set_and_permitted_prior_corpora'
    print(json.dumps(output, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
