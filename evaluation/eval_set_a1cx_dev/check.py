"""Structural checker for eval_set_a1cx_dev (development questions on spent long-text works; not held out).

Checks the manifest, the task fields the runner reads, and that every evidence quote occurs exactly once in its
chapter with `deep` matching its position (any quote past Han character 1,500). Runs from any directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import pathlib
import re
import sys

ROOT = pathlib.Path(__file__).resolve().parent
SUITES = {'qa', 'recap', 'fix', 'follow_up'}
QA_TYPES = {'answerable_single', 'answerable_multi', 'not_in_text', 'conflicting'}


def fail(label):
    print('FAIL', label)
    sys.exit(1)


def chapters(text):
    starts = list(re.finditer(r'^# (.+)$', text, re.M))
    return {m[1].strip(): text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)] for i, m in enumerate(starts)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged-dev', action='store_true', help='Accepted for runner compatibility; this set is dev only.')
    parser.parse_args()
    lines = (ROOT / 'set.sha256').read_text(encoding='utf-8').splitlines()
    listed = []
    for line in lines:
        digest, name = line.split('  ', 1)
        path = ROOT / name
        if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != digest: fail('manifest:' + name)
        listed.append(name)
    expected = sorted(['tasks.json'] + ['works/' + p.name for p in (ROOT / 'works').glob('*.md')])
    if listed != expected: fail('manifest:coverage')
    data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
    if data.get('set_id') != 'a1cx-dev': fail('set_id')
    works = {w['key']: w for w in data['works']}
    texts = {k: chapters((ROOT / w['source_file']).read_text(encoding='utf-8')) for k, w in works.items()}
    ids = set()
    for t in data['tasks']:
        if t['id'] in ids: fail('duplicate:' + t['id'])
        ids.add(t['id'])
        if t['work'] not in works or t['suite'] not in SUITES: fail('work_or_suite:' + t['id'])
        chs = texts[t['work']]
        if t['suite'] in ('qa', 'follow_up'):
            if t['suite'] == 'qa' and t.get('qa_type') not in QA_TYPES: fail('qa_type:' + t['id'])
            if not t.get('question'): fail('question:' + t['id'])
            if t['suite'] == 'follow_up' and not (t.get('first_question') and t.get('first_answer_points')): fail('follow:' + t['id'])
            quotes, refs = t.get('evidence_quotes', []), t.get('evidence_chapters', [])
            if len(quotes) != len(refs): fail('quotes_vs_chapters:' + t['id'])
            positions = []
            for chapter, quote in zip(refs, quotes):
                body = chs.get(chapter)
                if body is None or body.count(quote) != 1: fail('quote:' + t['id'])
                positions.append(len(re.findall(r'[\u4e00-\u9fff]', body[:body.find(quote)])))
            answerable = t['suite'] == 'follow_up' or t.get('qa_type', '').startswith('answerable')
            if answerable and t.get('deep') != any(p > 1500 for p in positions): fail('deep:' + t['id'])
            if t.get('selection') and t['selection'] not in works[t['work']]['shared_draft']['body']: fail('selection:' + t['id'])
        if t['suite'] == 'recap':
            if not 1 <= t['upto_chapter'] <= len(chs): fail('upto:' + t['id'])
            for m in t['must_mention']:
                if any(c not in chs for c in m['evidence_chapters']): fail('recap_ref:' + t['id'])
        if t['suite'] == 'fix':
            if t['conflict_sentence'] not in t['draft'] or any(c not in chs for c in t['evidence_chapters']): fail('fix:' + t['id'])
    print('OK', len(data['tasks']), 'tasks')


if __name__ == '__main__':
    main()
