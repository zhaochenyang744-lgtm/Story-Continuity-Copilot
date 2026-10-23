"""Authoring-only, permitted-corpus scans; a sealed checker never calls this."""
import hashlib
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
NEW = {'eval_set_a22_formal', 'eval_set_a2s2_formal'}
EXCLUDED = {'eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring'}
TEXT_SUFFIXES = {'.md', '.json', '.jsonl', '.txt', '.py', '.sha256', '.yaml', '.yml', '.toml',
                 '.csv', '.tsv', '.rst', '.html', '.xml', '.ini'}


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm(v):
    return ''.join(c for c in v if c.isalnum()).lower()


def inputs(obj):
    if isinstance(obj, dict):
        for key, value in obj.items():
            if key in {'input', 'question', 'request'} and isinstance(value, str) and norm(value):
                yield norm(value)
            elif isinstance(value, (dict, list)):
                yield from inputs(value)
    elif isinstance(obj, list):
        for value in obj:
            yield from inputs(value)


def load(p):
    return json.loads(p.read_text(encoding='utf-8-sig'))


def main():
    ev = REPO / 'evaluation'
    old_tasks, old_texts = [], []
    for d in sorted(ev.iterdir()):
        # Filter each top-level directory before descending; never open a prohibited directory.
        if not d.is_dir() or d.name in EXCLUDED | NEW:
            continue
        old_tasks.extend(sorted(d.rglob('tasks.json')))
        if d.name.startswith('eval_set'):
            old_texts.extend(p for p in sorted(d.rglob('*')) if p.is_file() and p.suffix in TEXT_SUFFIXES)
    all_candidates, data_by = [], {}
    for folder in sorted(NEW):
        data_by[folder] = load(ev / folder / 'tasks.json')
        all_candidates.extend(n for w in data_by[folder]['works'] for n in w['names'])
    assert len(all_candidates) == len(set(all_candidates)), 'new_name_intersection'
    summary = {}
    for folder in sorted(NEW):
        root = ev / folder
        other = next(name for name in NEW if name != folder)
        task_paths = old_tasks + [ev / other / 'tasks.json']
        other_core = [ev / other / 'tasks.json'] + [p for sub in ['works', 'materials']
                                                        for p in (ev / other / sub).rglob('*') if p.is_file()]
        text_paths = sorted(set(old_texts + other_core))
        grouped = {p.relative_to(REPO).as_posix(): sorted(set(inputs(load(p)))) for p in task_paths}
        source_hashes = {p.relative_to(REPO).as_posix(): sha(p) for p in task_paths}
        names = [n for w in data_by[folder]['works'] for n in w['names']]
        titles = [w['title'] for w in data_by[folder]['works']]
        name_hits, title_hits = set(), set()
        for p in text_paths:
            text = p.read_text(encoding='utf-8-sig')
            name_hits.update(i for i, name in enumerate(names, 1) if name in text)
            title_hits.update(i for i, title in enumerate(titles, 1) if title in text)
        old = sorted({v for values in grouped.values() for v in values})
        text_hashes = {p.relative_to(REPO).as_posix(): sha(p) for p in text_paths}
        ref = {'normalized_inputs': old, 'normalized_inputs_by_source': grouped,
               'source_hashes': source_hashes, 'names_corpus_sha256': text_hashes,
               'excluded_directories': sorted(EXCLUDED), 'names_overlap': len(name_hits),
               'candidate_names_sha256': hashlib.sha256(json.dumps(sorted(names), ensure_ascii=False).encode('utf-8')).hexdigest(),
               'reference_counts': {'source_files': len(source_hashes), 'normalized_inputs': len(old),
                                    'names_text_files': len(text_hashes)}}
        (root / 'authoring/novelty-reference.json').write_text(json.dumps(ref, ensure_ascii=False, indent=2) + '\n',
                                                            encoding='utf-8', newline='\n')
        summary[folder] = {'task_source_files': len(task_paths), 'normalized_reference_inputs': len(old),
                           'names_text_files': len(text_paths), 'candidate_names': len(names),
                           'names_overlap': len(name_hits), 'titles_overlap': len(title_hits),
                           'overlap_name_indices': sorted(name_hits), 'overlap_title_indices': sorted(title_hits)}
    for folder in sorted(NEW):
        (ev / folder / 'authoring/novelty-audit.json').write_text(json.dumps(summary, sort_keys=True, indent=2) + '\n',
                                                               encoding='utf-8', newline='\n')
    print(json.dumps(summary, sort_keys=True))
    return 0 if all(v['names_overlap'] == v['titles_overlap'] == 0 for v in summary.values()) else 1


if __name__ == '__main__':
    raise SystemExit(main())
