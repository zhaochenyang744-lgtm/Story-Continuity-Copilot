"""Read-only authoring counts, old-corpus proper-name audit and review bindings."""
from __future__ import annotations

from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
EVALUATION = ROOT.parent
EXCLUDED = {'eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring',
            'eval_set_a2_formal', 'eval_set_a2s_formal', ROOT.name}
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def is_reparse(path: Path) -> bool:
    return path.is_symlink() or bool(getattr(path.lstat(), 'st_file_attributes', 0) & 0x400)


def main() -> None:
    data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
    work = data['works'][0]
    names = work['names']
    overlaps, scanned, sets = [], 0, []
    for folder in sorted(EVALUATION.iterdir()):
        if folder.name in EXCLUDED or not folder.name.startswith('eval_set') or not folder.is_dir() or is_reparse(folder):
            continue
        sets.append(folder.name)
        for parent, directories, files in os.walk(folder, followlinks=False):
            directories[:] = sorted(name for name in directories
                                    if not is_reparse(Path(parent) / name) and name not in EXCLUDED)
            for filename in sorted(files):
                path = Path(parent) / filename
                if path.suffix.lower() not in {'.md', '.json', '.txt'} or is_reparse(path):
                    continue
                body = path.read_text(encoding='utf-8-sig')
                scanned += 1
                hits = [name for name in names if name in body]
                if hits:
                    overlaps.append({'path': path.relative_to(EVALUATION).as_posix(), 'names': hits})
    source = (ROOT / work['source_file']).read_text(encoding='utf-8')
    matches = list(re.finditer(r'^# (第(\d+)章 .+)$', source, re.M))
    bodies = {int(m[2]): source[m.end():matches[i + 1].start() if i + 1 < len(matches) else len(source)]
              for i, m in enumerate(matches)}
    lengths = {str(n): len(HAN.findall(body)) for n, body in bodies.items()}
    paragraphs = []
    sentences = []
    for n, body in bodies.items():
        paragraphs.extend((''.join(HAN.findall(paragraph)), n) for paragraph in body.split('\n\n')
                          if len(HAN.findall(paragraph)) >= 40)
        sentences.extend((''.join(HAN.findall(sentence)), n) for sentence in re.split(r'[。！？]', body)
                         if len(HAN.findall(sentence)) >= 40)
    repeated_paragraphs = [p for p, count in Counter(p for p, n in paragraphs).items() if count > 1]
    repeated_sentences = [p for p, count in Counter(p for p, n in sentences).items() if count > 1]
    file_properties = []
    for parent, directories, files in os.walk(ROOT, followlinks=False):
        directories[:] = sorted(name for name in directories if name != '__pycache__')
        for filename in sorted(files):
            path = Path(parent) / filename
            raw = path.read_bytes()
            file_properties.append({'path': path.relative_to(ROOT).as_posix(),
                                    'utf8': _is_utf8(raw), 'bom': raw.startswith(b'\xef\xbb\xbf'),
                                    'crlf': b'\r\n' in raw})
    output = {
        'chapter_han_counts': lengths, 'source_han_total': sum(lengths.values()),
        'chapter_han_min': min(lengths.values()), 'chapter_han_max': max(lengths.values()),
        'shared_draft_han': len(HAN.findall(work['shared_draft']['body'])),
        'proper_name_audit': {'names': len(names), 'existing_sets': sets, 'text_files': scanned,
                              'overlap_files': overlaps, 'overlap_name_count': len({name for hit in overlaps for name in hit['names']}),
                              'excluded_before_traversal': sorted(EXCLUDED)},
        'duplicate_paragraphs_at_least_40_han': len(repeated_paragraphs),
        'duplicate_sentences_at_least_40_han': len(repeated_sentences),
        'bindings': {name: digest(ROOT / name) for name in ('works/w01.md', 'tasks.json',
                                                           'materials/w01-facts.json', 'materials/w01-foreshadows.json')},
        'encoding_issues': [item for item in file_properties if not item['utf8'] or item['bom'] or item['crlf']],
    }
    (ROOT / 'authoring/audit-results.json').write_text(json.dumps(output, ensure_ascii=False, indent=2) + '\n',
                                                     encoding='utf-8', newline='\n')
    print(json.dumps(output, ensure_ascii=False))


def _is_utf8(raw: bytes) -> bool:
    try:
        raw.decode('utf-8')
        return True
    except UnicodeDecodeError:
        return False


if __name__ == '__main__':
    main()
