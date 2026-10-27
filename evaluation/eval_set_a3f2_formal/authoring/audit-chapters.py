"""Counts and duplicate/encoding audits of the three new canonical works only."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
MARK = re.compile(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$', re.M)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--save', action='store_true')
    args = parser.parse_args()
    results = {}
    for sid in ('eval_set_a3f2_formal', 'eval_set_a3s2_formal'):
        root = REPO / 'evaluation' / sid
        out = {}
        for p in sorted((root / 'works').glob('*.md')):
            raw = p.read_bytes()
            text = raw.decode('utf-8')
            marks = list(MARK.finditer(text))
            entries = []
            paragraphs = []
            for i, m in enumerate(marks):
                body = text[m.end():marks[i+1].start() if i+1 < len(marks) else len(text)]
                ps = [s.strip() for s in re.split(r'\n\s*\n', body) if s.strip()]
                paragraphs.extend(''.join(HAN.findall(s)) for s in ps if len(HAN.findall(s)) >= 80)
                entries.append({'chapter': int(m[1]), 'han': len(HAN.findall(body)), 'paragraphs': len(ps)})
            counts = Counter(paragraphs)
            out[p.stem] = {'sha256': hashlib.sha256(raw).hexdigest(), 'chapters': entries,
                           'total_han': sum(e['han'] for e in entries),
                           'duplicate_paragraphs': sum(n-1 for n in counts.values() if n > 1),
                           'bom': raw.startswith(b'\xef\xbb\xbf'), 'crlf': raw.count(b'\r\n'),
                           'replacement_characters': text.count('\ufffd')}
        results[sid] = out
        if args.save:
            (root / 'authoring/chapter-audit.json').write_text(json.dumps(out, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps(results, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
