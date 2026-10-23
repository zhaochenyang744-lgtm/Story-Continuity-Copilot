"""Authoring-only counts and positions. Does not author or alter prose."""
from collections import Counter
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def chapters(text):
    marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$', text, re.M))
    return {int(m[1]): {'title': m[0][2:], 'body': text[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(text)]}
            for i, m in enumerate(marks)}


def main():
    report = {}
    for folder, keys in [('eval_set_a22_formal', ['w01', 'w02']), ('eval_set_a2s2_formal', ['w01'])]:
        report[folder] = {}
        for wk in keys:
            root = REPO / 'evaluation' / folder
            source = root / 'works' / f'{wk}.md'
            if not source.is_file():
                report[folder][wk] = {'chapters': 0}
                continue
            text = source.read_text(encoding='utf-8')
            chs = chapters(text)
            bible = json.loads((root / 'authoring' / f'{wk}-bible.json').read_text(encoding='utf-8'))
            lengths = {n: len(HAN.findall(ch['body'])) for n, ch in chs.items()}
            positions, missing = [], []
            for field in ['aliases', 'stale_facts', 'missing_facts', 'resolved_unmarked', 'chapter_injections']:
                for i, entry in enumerate(bible.get(field, []), 1):
                    n = entry.get('changed_chapter', entry.get('chapter'))
                    if n not in chs:
                        continue
                    q = entry.get('quote', entry.get('text'))
                    body = chs[n]['body']
                    count = body.count(q)
                    item = {'group': field, 'index': i, 'chapter': n, 'occurrences': count}
                    if count == 1:
                        item['han_position'] = len(HAN.findall(body[:body.index(q)])) + 1
                    else:
                        missing.append({'group': field, 'index': i, 'chapter': n, 'occurrences': count})
                    positions.append(item)
            paras = [re.sub(r'\s+', '', p) for p in text.split('\n\n') if len(HAN.findall(p)) >= 30 and not p.startswith('# ')]
            repeated = sum(c - 1 for c in Counter(paras).values() if c > 1)
            report[folder][wk] = {'chapters': len(chs), 'chapter_han': lengths, 'total_han': sum(lengths.values()),
                                   'positions': positions, 'missing': missing, 'repeated_paragraphs': repeated}
    print(json.dumps(report, ensure_ascii=False, sort_keys=True))


if __name__ == '__main__':
    main()
