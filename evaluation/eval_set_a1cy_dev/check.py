"""Development-set checker adapted from eval_set_a1cx_dev/check.py; reads this set only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parent
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
ROUTES = {'ask', 'fix_issue', 'recap', 'check_passage', 'out_of_scope'}
PAGES = {'writing', 'chapters', 'materials', 'plan', 'overview'}
SUGGEST_TYPES = {'thread_resolution', 'conflict_options', 'open_whereabouts', 'creative_direction'}


def chapters(text):
    starts = list(re.finditer(r'^# (.+)$', text, re.M))
    return {m[1].strip(): text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)]
            for i, m in enumerate(starts)}


def grams(value, names):
    normalized = ''.join(HAN.findall(value))
    for name in sorted(names, key=len, reverse=True):
        normalized = normalized.replace(''.join(HAN.findall(name)), '|')
    return {part[i:i+8] for part in normalized.split('|') for i in range(len(part)-7)}


def validate(root=ROOT):
    errors, copy_errors = [], []
    def require(ok, label):
        if not ok: errors.append(label)
    data = json.loads((root / 'tasks.json').read_text(encoding='utf-8'))
    require(data.get('set_id') == 'a1cy-dev', 'set_id')
    manifest = []
    for line in (root / 'set.sha256').read_text(encoding='utf-8').splitlines():
        digest, name = line.split('  ', 1)
        path = (root / name).resolve()
        require(path.is_relative_to(root.resolve()), 'manifest:path')
        if not path.is_relative_to(root.resolve()): continue
        require(path.is_file() and hashlib.sha256(path.read_bytes()).hexdigest() == digest, 'manifest:' + name)
        manifest.append(name)
    expected = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for p in (root / 'works').rglob('*') if p.is_file()])
    require(manifest == expected, 'manifest:coverage')
    works = {w['key']: w for w in data['works']}
    require(set(works) == {'w01', 'w02', 'w03'} and len(data['works']) == 3, 'works')
    texts = {k: chapters((root / w['source_file']).read_text(encoding='utf-8')) for k, w in works.items()}
    require({k: len(v) for k, v in texts.items()} == {'w01': 30, 'w02': 30, 'w03': 12}, 'chapters')
    tasks = data['tasks']
    ids = {t['id']: t for t in tasks}
    require(len(ids) == len(tasks) == 32, 'task_count_or_duplicate')
    positions_by_work = defaultdict(list)
    for t in tasks:
        tid, wk, suite = t['id'], t['work'], t['suite']
        require(tid.startswith('a1cyd-'), tid + ':prefix')
        require(wk in {'w01', 'w02'} and suite in {'route', 'suggest', 'qa', 'fix'}, tid + ':work_or_suite')
        if wk not in works: continue
        work, chs = works[wk], texts[wk]
        selection = t.get('selection')
        refs, quotes = t.get('evidence_chapters', []), t.get('evidence_quotes', [])
        if suite == 'route':
            context = t.get('context', {})
            require(isinstance(t.get('input'), str) and 4 <= len(t['input']) <= 60, tid + ':input')
            require(isinstance(t.get('why'), str) and bool(t['why'].strip()), tid + ':why')
            require(context.get('page') in PAGES, tid + ':page')
            require(set(context) <= {'page', 'selection', 'issue_from', 'chapter_number'}, tid + ':context_fields')
            selection = context.get('selection')
            if selection is not None or context.get('issue_from') is not None:
                require(context.get('page') == 'writing', tid + ':writing_context')
            if 'chapter_number' in context:
                require(type(context['chapter_number']) is int and 1 <= context['chapter_number'] <= 31, tid + ':chapter_number')
            route = t.get('expected_route')
            require(route in ROUTES, tid + ':route')
            acceptable = t.get('also_acceptable', [])
            require(isinstance(acceptable, list) and len(acceptable) <= 1
                    and all(v in ROUTES and v != route for v in acceptable), tid + ':also_acceptable')
            fix = ids.get(context.get('issue_from'))
            if 'issue_from' in context:
                require(bool(fix) and fix['suite'] == 'fix' and fix['work'] == wk, tid + ':issue_from')
            if route == 'fix_issue': require(bool(fix), tid + ':fix_requires_issue')
            if route == 'check_passage': require(bool(selection), tid + ':check_requires_selection')
            # Route questions may concern any chapter; check all of this work, never sealed siblings.
            reference = set().union(*(grams(body, work['names']) for body in chs.values()))
            if grams(t.get('input', ''), work['names']) & reference: copy_errors.append(tid + ':input')
        else:
            require(isinstance(refs, list) and bool(refs) if suite != 'suggest' or t.get('suggest_type') != 'creative_direction'
                    else refs == [], tid + ':references')
            require(all(c in chs for c in refs), tid + ':chapter_reference')
            if suite in {'qa', 'suggest'}:
                for field in ('answer_points', 'forbidden_claims', 'evidence_quotes'):
                    require(isinstance(t.get(field), list) and all(isinstance(x, str) and bool(x) for x in t[field]), tid + ':' + field)
                require(isinstance(t.get('question'), str) and bool(t['question']), tid + ':question')
                require(type(t.get('paraphrased')) is bool and type(t.get('deep')) is bool, tid + ':flags')
                require(len(refs) == len(quotes), tid + ':quote_alignment')
                positions = []
                for c, q in zip(refs, quotes):
                    body = chs.get(c, '')
                    require(10 <= len(q) <= 60 and body.count(q) == 1, tid + ':quote')
                    if q and body.count(q) == 1:
                        positions.append(len(HAN.findall(body[:body.index(q)])) + 1)
                require(t.get('deep') == any(p > 1500 for p in positions), tid + ':deep')
                if suite == 'suggest':
                    kind = t.get('suggest_type')
                    require(kind in SUGGEST_TYPES, tid + ':suggest_type')
                    if kind == 'creative_direction':
                        require(t['answer_points'] == refs == quotes == [] and bool(t['forbidden_claims']), tid + ':creative_fields')
                    else:
                        require(bool(t['answer_points']) and bool(refs), tid + ':grounded_fields')
                        positions_by_work[wk] += positions
                else:
                    require(t.get('qa_type') == 'answerable_single' and bool(t['answer_points']), tid + ':qa_fields')
            if suite == 'fix':
                require(bool(t.get('conflict_sentence')) and t['draft'].count(t['conflict_sentence']) == 1
                        and bool(t.get('fix_idea')), tid + ':fix')
            reference = set().union(*(grams(chs.get(c, ''), work['names']) for c in refs))
            for field in ('question', 'selection', 'draft'):
                if grams(t.get(field, ''), work['names']) & reference: copy_errors.append(tid + ':' + field)
            if suite in {'qa', 'suggest'} and grams(work['shared_draft']['body'], work['names']) & reference:
                copy_errors.append(tid + ':shared_draft')
        if selection is not None:
            require(isinstance(selection, str) and bool(selection) and selection in work['shared_draft']['body']
                    and bool(re.search(r'[。！？]', selection)), tid + ':selection')
    for wk in ('w01', 'w02'):
        own = [t for t in tasks if t['work'] == wk]
        require(Counter(t['suite'] for t in own) == {'qa': 1, 'fix': 1, 'route': 10, 'suggest': 4}, wk + ':suite_distribution')
        routes = [t for t in own if t['suite'] == 'route']
        require(Counter(t['expected_route'] for t in routes) == {'ask': 4, 'fix_issue': 2, 'recap': 1, 'check_passage': 2, 'out_of_scope': 1}, wk + ':route_distribution')
        require(sum(bool(t.get('also_acceptable')) for t in routes) <= 2, wk + ':acceptable_count')
        require(any(t['expected_route'] == 'ask' and '建议' in t['input'] for t in routes), wk + ':ask_suggestion')
        # The fourth ask is the ambiguous item; identifying ambiguity is a semantic self-review,
        # not a requirement to use a specific phrase or to supply the optional also_acceptable.
        groups = defaultdict(list)
        for t in routes: groups[t['input']].append(t)
        require(sum(len({t['expected_route'] for t in group}) >= 2 and
                    len({json.dumps(t['context'], sort_keys=True, ensure_ascii=False) for t in group}) >= 2
                    for group in groups.values()) >= 2, wk + ':same_input_groups')
        require(sum(not any(b in t['input'] for b in ('写前回顾', '帮我改这一处', '检查这段')) for t in routes) >= 5, wk + ':paraphrases')
        require(Counter(t['suggest_type'] for t in own if t['suite'] == 'suggest') == {k: 1 for k in SUGGEST_TYPES}, wk + ':suggest_distribution')
        positions = positions_by_work[wk]
        require(bool(positions) and sum(p > 1500 for p in positions) * 2 >= len(positions), wk + ':deep_evidence_half')
    errors.extend(copy_errors)
    return {'status': 'FAIL' if errors else 'PASS', 'tasks': len(tasks), 'works': len(works),
            'suites': dict(Counter(t['suite'] for t in tasks)), 'errors': errors, 'copy_errors': len(copy_errors),
            'scope': 'this_set_only', 'model_calls': 0, 'semantic_acceptance': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--staged-dev', action='store_true')
    parser.parse_args()
    result = validate()
    print(json.dumps(result, ensure_ascii=False))
    return bool(result['errors'])


if __name__ == '__main__':
    raise SystemExit(main())
