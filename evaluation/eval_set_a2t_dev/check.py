"""Offline structural checks for the readable A2 thread-action development set.

Adapted from the fourth pair's checkers. Old requests are read only by the
novelty comparison and are never returned, cached, or printed. PASS is not a
product run or a claim about model quality or independent semantic acceptance.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
PAGES = {'writing', 'chapters', 'materials', 'plan', 'overview'}
NEW = {'add_thread', 'edit_thread', 'abandon_thread'}
KINDS = NEW | {'add_fact', 'change_fact', 'resolve_thread'}
THREAD_KINDS = {'resolve_thread', 'edit_thread', 'abandon_thread', 'delete_thread'}
ROUTES = {'ask', 'fix_issue', 'recap', 'check_passage', 'out_of_scope', 'change'}
MEMORIES = {'static_canon', 'dynamic_state', 'event_timeline', 'character_knowledge', 'open_thread'}
STATES = {'planned', 'planted', 'developing', 'resolved', 'abandoned'}
OPEN = {'planned', 'planted', 'developing'}
NO_ACTION = {'already_recorded', 'no_evidence', 'prose_edit', 'unsupported_kind'}
SOURCES = {'w01': 'eval_set_a23_formal', 'w02': 'eval_set_a24_formal'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(value):
    return ''.join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith('P'))


def grams(value, names):
    value = ''.join(HAN.findall(value))
    for name in sorted(names, key=len, reverse=True):
        clean = ''.join(HAN.findall(name))
        if clean:
            value = value.replace(clean, '|')
    return {s[i:i + 8] for s in value.split('|') for i in range(len(s) - 7)}


def chapter_map(text):
    starts = list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\n\r]+)$', text, re.M))
    return {int(m[1]): {'title': m[0][2:], 'body': text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)]}
            for i, m in enumerate(starts)}


def complete_selection(body, selection):
    if not isinstance(selection, str) or not selection:
        return False
    tail = selection.rstrip(' \t\r\n”’"\'')
    if not tail or tail[-1] not in '。！？':
        return False
    return any(not body[:m.start()].rstrip(' \t\r') or
               body[:m.start()].rstrip(' \t\r')[-1] in '。！？\n：:“‘"\''
               for m in re.finditer(re.escape(selection), body))


def repository(root):
    for parent in (root, *root.parents):
        if (parent / 'evaluation/assistant_a2/SPEC.md').is_file():
            return parent
    raise ValueError('repository_not_found')


class InvalidStructure(Exception):
    pass


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise InvalidStructure('duplicate_json_key')
        result[key] = value
    return result


def validate(root=ROOT):
    root = Path(root).resolve()
    repo = repository(root)
    errors = []
    stats = {'set_id': 'a2t-dev', 'works': {}, 'tasks': 0, 'copy_errors': 0, 'novelty_errors': 0}

    def need(ok, label):
        if not ok:
            errors.append(label)
        return bool(ok)

    def string(value, low=1, high=10**9):
        return isinstance(value, str) and low <= len(value) <= high and bool(value.strip())

    def index(value, items):
        return type(value) is int and 1 <= value <= len(items)

    def read(rel):
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('file')
        return path.read_text(encoding='utf-8')

    def jread(rel):
        return json.loads(read(rel), object_pairs_hook=unique_object)

    def external_json(path):
        return json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=unique_object)

    need(all(not p.is_symlink() and not (hasattr(p, 'is_junction') and p.is_junction())
             for p in root.rglob('*')), 'structure:symlink')
    for rel in ('README.md', 'tasks.json', 'set.sha256', 'check.py', 'authoring/self-review.md',
                'authoring/self-review.json', 'authoring/independent-review.json'):
        need((root / rel).is_file(), 'structure:' + rel)
    data, review = jread('tasks.json'), jread('authoring/self-review.json')
    need(isinstance(data, dict) and set(data) == {'version', 'set_id', 'author', 'works', 'tasks'}, 'top:fields')
    need(data.get('version') == 'a2-2' and data.get('set_id') == 'a2t-dev' and
         data.get('author') == 'evaluation authoring', 'top:metadata')
    works_list, tasks = data.get('works'), data.get('tasks')
    need(isinstance(works_list, list) and isinstance(tasks, list), 'top:arrays')
    works = {w.get('key'): w for w in works_list if isinstance(w, dict)}
    need(set(works) == set(SOURCES) and len(works_list) == 2, 'works:keys')
    need(isinstance(review.get('works'), dict) and set(review['works']) == set(SOURCES), 'review:works')
    expected_paths = sorted(['tasks.json'] + [f'works/{wk}.md' for wk in SOURCES] +
                            [f'materials/{wk}-{kind}.json' for wk in SOURCES for kind in ('facts', 'foreshadows')])
    actual_paths = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for folder in ('works', 'materials')
                                          for p in (root / folder).rglob('*') if p.is_file()])
    need(actual_paths == expected_paths, 'structure:data_paths')
    manifest_names = []
    for i, line in enumerate(read('set.sha256').splitlines(), 1):
        match = re.fullmatch(r'([0-9a-f]{64})  ([A-Za-z0-9_./-]+)', line)
        if not need(bool(match), f'manifest:{i}:format'):
            continue
        hash_value, rel = match.groups()
        path = (root / rel).resolve()
        safe = path.is_relative_to(root) and '..' not in Path(rel).parts and path.is_file()
        need(safe, f'manifest:{i}:path')
        if safe:
            need(digest(path) == hash_value, f'manifest:{i}:hash')
        manifest_names.append(rel)
    need(manifest_names == expected_paths, 'manifest:coverage_order')
    parsed, facts_by, threads_by, review_by, references = {}, {}, {}, {}, {}
    positions, unique_positions = defaultdict(list), defaultdict(dict)
    all_names = []

    def quote(wk, chapter, text, label):
        chs = parsed[wk]
        if isinstance(chapter, str):
            matches = [n for n, value in chs.items() if value['title'] == chapter]
            number = matches[0] if len(matches) == 1 else None
        else:
            number = chapter if type(chapter) is int else None
        body = chs.get(number, {}).get('body', '')
        valid = string(text, 10, 60) and text in body
        need(valid and number in chs, label + ':quote')
        if valid:
            pos = len(HAN.findall(body[:body.index(text)])) + 1
            positions[wk].append(pos)
            unique_positions[wk][(number, text)] = pos
            return number
        return None

    for wk, source_set in SOURCES.items():
        w, wr = works[wk], review['works'][wk]
        original = repo / 'evaluation' / source_set
        old_work = next(v for v in external_json(original / 'tasks.json')['works'] if v['key'] == 'w01')
        need(set(w) == {'key', 'title', 'language', 'source_file', 'purpose', 'kind', 'names', 'materials', 'shared_draft'}, wk + ':fields')
        need(w.get('language') == 'zh' and w.get('purpose') == 'general' and w.get('kind') == 'long', wk + ':metadata')
        need(all(w.get(k) == old_work[k] for k in ('title', 'names', 'shared_draft')), wk + ':source_metadata_equal')
        need(w.get('source_file') == f'works/{wk}.md' and w.get('materials') ==
             {'facts': f'materials/{wk}-facts.json', 'foreshadows': f'materials/{wk}-foreshadows.json'}, wk + ':paths')
        need((root / f'works/{wk}.md').read_bytes() == (original / 'works/w01.md').read_bytes(), wk + ':source_bytes_equal')
        need((root / f'materials/{wk}-facts.json').read_bytes() == (original / 'materials/w01-facts.json').read_bytes(), wk + ':facts_bytes_equal')
        old_review = external_json(original / 'authoring/self-review.json')['works']['w01']
        for field in ('stale_facts', 'missing_facts'):
            need(wr.get(field) == old_review[field], wk + ':source_review_equal:' + field)
        source = read(f'works/{wk}.md')
        chs = chapter_map(source)
        parsed[wk] = chs
        chapter_order = [int(n) for n in re.findall(r'^# 第([1-9][0-9]*)章 [^\n\r]+$', source, re.M)]
        need(chapter_order == list(range(1, 21)) and len(re.findall(r'^# ', source, re.M)) == 20 and
             bool(re.match(r'\s*# 第1章 ', source)), wk + ':chapters')
        lengths = {n: len(HAN.findall(value['body'])) for n, value in chs.items()}
        for n, count in lengths.items():
            need(2500 <= count <= 3500, f'{wk}:chapter:{n}:length')
        draft = w.get('shared_draft', {})
        need(isinstance(draft, dict) and set(draft) == {'chapter_title', 'body'} and
             bool(re.fullmatch(r'第21章 [^\n]+', draft.get('chapter_title', ''))) and
             isinstance(draft.get('body'), str) and 600 <= len(HAN.findall(draft['body'])) <= 1000, wk + ':draft')
        names = w.get('names', [])
        need(isinstance(names, list) and all(string(n) for n in names) and len(set(names)) == len(names), wk + ':names')
        need(all(n in source + draft.get('body', '') for n in names), wk + ':names_presence')
        all_names.extend(names)
        references[wk] = set().union(*(grams(ch['body'], names) for ch in chs.values()))
        fs, ts = jread(f'materials/{wk}-facts.json'), jread(f'materials/{wk}-foreshadows.json')
        facts_by[wk], threads_by[wk], review_by[wk] = fs, ts, wr
        need(isinstance(fs, list) and 25 <= len(fs) <= 40, wk + ':fact_count')
        need(isinstance(ts, list) and 8 <= len(ts) <= 14, wk + ':thread_count')
        for i, fact in enumerate(fs, 1):
            need(isinstance(fact, dict) and set(fact) == {'memory_type', 'subject', 'predicate', 'value', 'chapter'}, f'{wk}:fact:{i}:fields')
            need(fact.get('memory_type') in MEMORIES and string(fact.get('subject'), 1, 20) and
                 string(fact.get('predicate'), 1, 20) and string(fact.get('value'), 1, 60) and
                 type(fact.get('chapter')) is int and fact['chapter'] in chs, f'{wk}:fact:{i}:values')
        need(len({(f['subject'], f['predicate']) for f in fs}) == len(fs), wk + ':fact_keys')
        states = Counter(t.get('status') for t in ts)
        need(states['resolved'] >= 1 and states['planted'] + states['developing'] >= 2, wk + ':thread_states')
        for i, thread in enumerate(ts, 1):
            fields = {'title', 'description', 'status', 'planted_chapter'} | ({'resolved_chapter'} if thread.get('status') == 'resolved' else set())
            need(set(thread) == fields and string(thread.get('title'), 1, 30) and
                 string(thread.get('description'), 20, 200) and thread.get('status') in STATES and
                 type(thread.get('planted_chapter')) is int and thread['planted_chapter'] in chs, f'{wk}:thread:{i}:values')
            if thread.get('status') == 'resolved':
                need(type(thread.get('resolved_chapter')) is int and thread['planted_chapter'] <= thread['resolved_chapter'] <= 20,
                     f'{wk}:thread:{i}:resolution')
        need(len({t['title'] for t in ts}) == len(ts), wk + ':thread_titles')
        minima = {'stale_facts': 5, 'missing_facts': 6, 'resolved_unmarked': 2, 'open_threads': 3, 'stale_notes': 2, 'missing_threads': 3}
        for field, minimum in minima.items():
            entries = wr.get(field)
            need(isinstance(entries, list) and len(entries) >= minimum, f'{wk}:review:{field}:count')
            keys = []
            for i, entry in enumerate(entries, 1):
                label = f'{wk}:review:{field}:{i}'
                if field == 'open_threads':
                    need(set(entry) == {'foreshadow', 'abandonable'} and type(entry.get('abandonable')) is bool,
                         label + ':fields')
                    valid = index(entry.get('foreshadow'), ts)
                    need(valid and ts[entry['foreshadow'] - 1]['status'] in OPEN, label + ':state')
                    keys.append(entry.get('foreshadow'))
                    continue
                if field == 'stale_facts':
                    fields, chapter_key = {'fact', 'changed_chapter', 'quote'}, 'changed_chapter'
                elif field == 'missing_facts':
                    fields, chapter_key = {'subject', 'predicate', 'chapter', 'quote'}, 'chapter'
                elif field == 'missing_threads':
                    fields, chapter_key = {'about', 'planted_chapter', 'quote'}, 'planted_chapter'
                else:
                    fields, chapter_key = {'foreshadow', 'chapter', 'quote'}, 'chapter'
                need(isinstance(entry, dict) and set(entry) == fields, label + ':fields')
                need(type(entry.get(chapter_key)) is int and entry[chapter_key] in chs, label + ':chapter')
                quote(wk, entry.get(chapter_key), entry.get('quote'), label)
                if field == 'stale_facts':
                    valid = index(entry.get('fact'), fs)
                    need(valid, label + ':index')
                    if valid:
                        need(entry['changed_chapter'] > fs[entry['fact'] - 1]['chapter'], label + ':chronology')
                    keys.append(entry.get('fact'))
                elif field in {'resolved_unmarked', 'stale_notes'}:
                    valid = index(entry.get('foreshadow'), ts)
                    need(valid, label + ':index')
                    if valid:
                        thread = ts[entry['foreshadow'] - 1]
                        need(entry['chapter'] >= thread['planted_chapter'], label + ':chronology')
                        if field == 'resolved_unmarked':
                            need(thread['status'] in {'planted', 'developing'}, label + ':state')
                    keys.append(entry.get('foreshadow'))
                elif field == 'missing_facts':
                    need(string(entry.get('subject'), 1, 20) and string(entry.get('predicate'), 1, 20) and
                         (entry['subject'], entry['predicate']) not in {(f['subject'], f['predicate']) for f in fs}, label + ':missing')
                    keys.append((entry.get('subject'), entry.get('predicate')))
                else:
                    need(string(entry.get('about'), 1, 30) and entry.get('about') not in {t['title'] for t in ts}, label + ':missing')
                    keys.append((entry.get('about'), entry.get('planted_chapter')))
            need(len(set(keys)) == len(keys), f'{wk}:review:{field}:duplicates')
        resolved_ids = {e['foreshadow'] for e in wr['resolved_unmarked']}
        open_ids = {e['foreshadow'] for e in wr['open_threads']}
        need(not resolved_ids & open_ids, wk + ':review:resolved_open_overlap')
        need(sum(e['abandonable'] is True for e in wr['open_threads']) >= 2, wk + ':review:abandonable')
        # The legacy aliases/characters are preserved context, where supplied.
        for i, alias in enumerate(wr.get('aliases', []), 1):
            need(alias.get('name') in names and alias.get('alias') in names, f'{wk}:alias:{i}:names')
            quote(wk, alias.get('chapter'), alias.get('quote'), f'{wk}:alias:{i}')
        stats['works'][wk] = {'chapters': len(chs), 'chapter_han_min': min(lengths.values()), 'chapter_han_max': max(lengths.values()),
                              'total_han': sum(lengths.values()), 'draft_han': len(HAN.findall(draft['body'])),
                              'facts': len(fs), 'foreshadows': len(ts), 'foreshadow_states': dict(sorted(states.items())),
                              **{field: len(wr[field]) for field in minima},
                              'abandonable': sum(e['abandonable'] is True for e in wr['open_threads']),
                              'source_bytes_equal': (root / f'works/{wk}.md').read_bytes() == (original / 'works/w01.md').read_bytes(),
                              'facts_bytes_equal': (root / f'materials/{wk}-facts.json').read_bytes() == (original / 'materials/w01-facts.json').read_bytes()}
    need(len(all_names) == len(set(all_names)), 'works:names_overlap')

    ids = {}
    for i, task in enumerate(tasks, 1):
        tid = task.get('id')
        valid = isinstance(tid, str) and bool(re.fullmatch(r'a2t-[A-Za-z0-9][A-Za-z0-9_-]*', tid))
        need(valid and tid not in ids, f'task:{i}:id')
        if valid:
            ids[tid] = task
    need(len(tasks) == len(ids) == 36, 'tasks:count')
    stats['tasks'] = len(tasks)

    # Programmatic comparison includes sealed sets without exposing their text.
    # A negative-test clone nested in this new directory is excluded together
    # with the canonical set, so it is never compared against its own requests.
    old_inputs, corpus_files, unreadable = set(), 0, 0
    evaluation = repo / 'evaluation'
    canonical = evaluation / 'eval_set_a2t_dev'

    def collect_inputs(value):
        if isinstance(value, dict):
            for k, v in value.items():
                if k in {'input', 'question', 'request'} and isinstance(v, str):
                    old_inputs.add(normalized(v))
                else:
                    collect_inputs(v)
        elif isinstance(value, list):
            for v in value:
                collect_inputs(v)

    for path in evaluation.rglob('tasks.json'):
        resolved = path.resolve()
        if resolved.is_relative_to(canonical) or resolved.is_relative_to(root) or any(
                part.startswith(('_negative', '.negative', '_tmp')) for part in path.relative_to(evaluation).parts):
            continue
        try:
            collect_inputs(external_json(path))
            corpus_files += 1
        except (OSError, ValueError):
            unreadable += 1
    old_inputs.discard('')
    need(corpus_files > 0 and unreadable == 0 and bool(old_inputs), 'novelty:corpus')
    stats.update({'novelty_source_files': corpus_files, 'novelty_reference_inputs': len(old_inputs),
                  'novelty_unreadable_files': unreadable, 'source_metadata_reuse_exempt': 2})

    def copy_check(wk, value, label):
        if isinstance(value, str) and grams(value, works[wk]['names']) & references[wk]:
            errors.append(label + ':copy8')
            stats['copy_errors'] += 1

    def action(wk, entry, label, task_author_words=None):
        fs, ts, wr = facts_by[wk], threads_by[wk], review_by[wk]
        base = {'kind', 'target', 'after_points', 'evidence_chapters', 'evidence_quotes'}
        kind, target = entry.get('kind'), entry.get('target')
        fields = base | ({'author_words'} if kind == 'edit_thread' else set())
        need(isinstance(entry, dict) and set(entry) == fields, label + ':fields')
        need(kind in KINDS, label + ':kind')
        proof = None
        if kind == 'change_fact':
            proof = next((e for e in wr['stale_facts'] if e['fact'] == target), None)
            need(index(target, fs) and proof is not None, label + ':target')
        elif kind == 'resolve_thread':
            proof = next((e for e in wr['resolved_unmarked'] if e['foreshadow'] == target), None)
            need(index(target, ts) and proof is not None, label + ':target')
        elif kind == 'add_fact':
            if isinstance(target, dict):
                proof = next((e for e in wr['missing_facts'] if (e['subject'], e['predicate']) ==
                              (target.get('subject'), target.get('predicate'))), None)
            need(isinstance(target, dict) and set(target) == {'subject', 'predicate'} and proof is not None, label + ':target')
        elif kind == 'add_thread':
            if isinstance(target, dict):
                proof = next((e for e in wr['missing_threads'] if (e['about'], e['planted_chapter']) ==
                              (target.get('about'), target.get('planted_chapter'))), None)
            need(isinstance(target, dict) and set(target) == {'about', 'planted_chapter'} and
                 string(target.get('about'), 1, 30) and type(target.get('planted_chapter')) is int and proof is not None,
                 label + ':missing_thread_target')
        elif kind == 'edit_thread':
            author_words = entry.get('author_words')
            need(type(author_words) is bool and (task_author_words is None or author_words == task_author_words), label + ':author_words')
            proof = next((e for e in wr['stale_notes'] if e['foreshadow'] == target), None)
            need(index(target, ts) and (author_words is True or proof is not None), label + ':stale_note_target')
        elif kind == 'abandon_thread':
            proof = next((e for e in wr['open_threads'] if e['foreshadow'] == target and e['abandonable'] is True), None)
            need(index(target, ts) and proof is not None and ts[target - 1]['status'] in OPEN, label + ':open_thread_target')
        points = entry.get('after_points')
        need(isinstance(points, list) and 1 <= len(points) <= 3 and all(string(p, 1, 30) for p in points) and
             len(set(points)) == len(points), label + ':points')
        for i, point in enumerate(points, 1):
            copy_check(wk, point, f'{label}:point:{i}')
        cs, qs = entry.get('evidence_chapters'), entry.get('evidence_quotes')
        optional = kind == 'abandon_thread' or kind == 'edit_thread' and entry.get('author_words') is True
        need(isinstance(cs, list) and isinstance(qs, list) and len(cs) == len(qs) and
             (optional or len(cs) > 0) and all(isinstance(c, str) for c in cs), label + ':evidence')
        need(len(set(zip(cs, qs))) == len(cs), label + ':evidence_duplicates')
        evidence_numbers = [quote(wk, c, q, f'{label}:evidence:{i}') for i, (c, q) in enumerate(zip(cs, qs), 1)]
        if kind == 'abandon_thread':
            need(points == ['已放弃'] and cs == qs == [], label + ':abandon_program_point')
        if kind == 'resolve_thread':
            resolution = '收在第' + str(proof['chapter']) + '章' if proof else None
            need(points.count('已回收') == 1 and resolution is not None and points.count(resolution) == 1 and
                 sum(bool(re.fullmatch(r'收在第[1-9][0-9]*章', p)) for p in points) == 1, label + ':resolve_program_points')
        if kind == 'add_thread' and isinstance(target, dict):
            valid_numbers = [n for n in evidence_numbers if n is not None]
            need(bool(valid_numbers) and min(valid_numbers) == target.get('planted_chapter'), label + ':earliest_evidence_chapter')
            need(all(not re.fullmatch(r'埋在第[1-9][0-9]*章', p) or p == f"埋在第{target.get('planted_chapter')}章" for p in points), label + ':planted_program_point')
        return kind, json.dumps(target, ensure_ascii=False, sort_keys=True)

    injection_tasks = []
    for i, task in enumerate(tasks, 1):
        tid = task.get('id') if task.get('id') in ids else f'task:{i}'
        wk, suite = task.get('work'), task.get('suite')
        if not need(wk in SOURCES, tid + ':work'):
            continue
        need(suite in {'action', 'no_action', 'route', 'injection'}, tid + ':suite')
        base_fields = {'id', 'work', 'suite', 'context', 'why', 'input' if suite == 'route' else 'request'}
        extras = {'action': {'expected_actions', 'paraphrased', 'vague'},
                  'no_action': {'no_action_type', 'request_targets'},
                  'route': {'expected_route'} | ({'also_acceptable'} if 'also_acceptable' in task else set()),
                  'injection': {'run_kind', 'injection', 'injection_target', 'allowed_actions'}}
        entry_field = 'expected_actions' if suite == 'action' else 'allowed_actions'
        has_edit = any(e.get('kind') == 'edit_thread' for e in task.get(entry_field, []))
        optional_task_fields = {'author_words'} if has_edit and 'author_words' in task else set()
        if suite in extras:
            need(set(task) == base_fields | extras[suite] | optional_task_fields, tid + ':fields')
        need(string(task.get('why')), tid + ':why')
        context = task.get('context', {})
        need(isinstance(context, dict) and set(context) <= {'page', 'chapter_number', 'selection', 'issue_from'} and
             context.get('page') in PAGES, tid + ':context')
        if 'chapter_number' in context:
            need(type(context['chapter_number']) is int and 1 <= context['chapter_number'] <= 21, tid + ':chapter_number')
        if 'selection' in context:
            selection = context['selection']
            need(context['page'] == 'writing' and string(selection, 1, 80) and selection in works[wk]['shared_draft']['body'] and
                 complete_selection(works[wk]['shared_draft']['body'], selection), tid + ':selection')
        # This compact dev set does not author support FIX items.
        need('issue_from' not in context, tid + ':issue_from_unsupported')
        field = 'input' if suite == 'route' else 'request'
        low, high = (4, 60) if suite == 'route' else (6, 80)
        need(string(task.get(field), low, high), tid + ':input')
        if isinstance(task.get(field), str):
            copy_check(wk, task[field], tid + ':' + field)
            n = normalized(task[field])
            if any(n == old or (min(len(n), len(old)) * 2 / max(1, len(n) + len(old)) >= .8 and
                               SequenceMatcher(None, n, old).ratio() >= .8) for old in old_inputs):
                errors.append(tid + ':novelty80')
                stats['novelty_errors'] += 1
        if suite == 'action':
            entries = task.get('expected_actions', [])
            need(isinstance(entries, list) and 1 <= len(entries) <= 2, tid + ':actions')
            need(type(task.get('paraphrased')) is bool and type(task.get('vague')) is bool, tid + ':flags')
            keys = [action(wk, e, f'{tid}:action:{j}', task.get('author_words')) for j, e in enumerate(entries, 1)]
            need(len(set(keys)) == len(keys), tid + ':action_duplicates')
        elif suite == 'no_action':
            need(task.get('no_action_type') in NO_ACTION, tid + ':no_action_type')
            targets = task.get('request_targets', {})
            need(isinstance(targets, dict) and set(targets) == {'facts', 'foreshadows'} and
                 all(isinstance(targets.get(f), list) and len(set(targets[f])) == len(targets[f]) and
                     all(index(n, items) for n in targets[f]) for f, items in (('facts', facts_by[wk]), ('foreshadows', threads_by[wk]))), tid + ':request_targets')
            if task.get('no_action_type') == 'already_recorded':
                need(bool(targets.get('facts') or targets.get('foreshadows')), tid + ':already_recorded_target')
            if task.get('no_action_type') == 'unsupported_kind':
                need(bool(targets.get('foreshadows')), tid + ':delete_thread_target')
        elif suite == 'route':
            route = task.get('expected_route')
            need(route in ROUTES - {'fix_issue'}, tid + ':route')
            acceptable = task.get('also_acceptable', [])
            need(isinstance(acceptable, list) and len(acceptable) <= 1 and all(r in ROUTES and r != route for r in acceptable), tid + ':acceptable')
            if route == 'check_passage':
                need(bool(context.get('selection')), tid + ':check_selection')
        elif suite == 'injection':
            injection_tasks.append(task)
            need(task.get('run_kind') in {'change', 'ask', 'recap'}, tid + ':run_kind')
            entries = task.get('allowed_actions', [])
            need(isinstance(entries, list) and (len(entries) >= 1 if task.get('run_kind') == 'change' else entries == []), tid + ':allowed_count')
            keys = [action(wk, e, f'{tid}:allowed:{j}', task.get('author_words')) for j, e in enumerate(entries, 1)]
            need(len(set(keys)) == len(keys), tid + ':allowed_duplicates')
            target = task.get('injection_target', {})
            need(isinstance(target, dict) and set(target) == {'kind', 'target'} and target.get('kind') in NEW | {'delete_thread'}, tid + ':injection_target')
            kind, value = target.get('kind'), target.get('target')
            if kind in THREAD_KINDS:
                need(index(value, threads_by[wk]), tid + ':target_thread')
            elif kind == 'add_thread':
                need(isinstance(value, dict) and set(value) == {'about', 'planted_chapter'} and
                     string(value.get('about'), 1, 30) and type(value.get('planted_chapter')) is int and
                     value['planted_chapter'] in parsed[wk], tid + ':target_add_thread')
            for allowed in entries:
                ak, av = allowed['kind'], allowed['target']
                overlap = kind in THREAD_KINDS and ak in THREAD_KINDS and value == av
                if kind == ak == 'add_thread':
                    overlap = value.get('about') == av.get('about')
                need(not overlap, tid + ':target_object_overlap')
            injection = task.get('injection', {})
            need(isinstance(injection, dict) and set(injection) == {'text', 'location'} and string(injection.get('text')), tid + ':injection')
            location, carrier = injection.get('location', {}), ''
            where = location.get('kind')
            need(where in {'fact', 'foreshadow'} and set(location) == {'kind', 'index'}, tid + ':location')
            items = facts_by[wk] if where == 'fact' else threads_by[wk]
            if need(index(location.get('index'), items), tid + ':carrier_index'):
                carrier = items[location['index'] - 1]['value' if where == 'fact' else 'description']
            need(string(injection.get('text')) and injection['text'] in carrier, tid + ':injection_match')

    for wk in SOURCES:
        own = [t for t in tasks if t.get('work') == wk and t.get('suite') != 'injection']
        need(Counter(t['suite'] for t in own) == {'action': 9, 'no_action': 3, 'route': 4}, wk + ':suite_distribution')
        actions = [t for t in own if t['suite'] == 'action']
        primary = Counter(t['expected_actions'][0]['kind'] for t in actions if t.get('expected_actions'))
        need(primary == {'add_thread': 3, 'edit_thread': 3, 'abandon_thread': 3}, wk + ':primary_actions')
        multi = sum(len(t['expected_actions']) == 2 and any(e['kind'] in NEW for e in t['expected_actions']) and
                    any(e['kind'] in KINDS - NEW for e in t['expected_actions']) for t in actions)
        paraphrased = sum(t.get('paraphrased') is True for t in actions)
        vague = sum(t.get('vague') is True for t in actions)
        need(multi >= 1 and paraphrased >= 5 and vague >= 2, wk + ':action_distribution')
        pages = Counter(t['context']['page'] for t in actions)
        need(len(pages) >= 3, wk + ':action_pages')
        edits = [e for t in actions for e in t['expected_actions'] if e['kind'] == 'edit_thread']
        author_words = Counter(str(e.get('author_words')).lower() for e in edits)
        need(author_words['true'] >= 1 and author_words['false'] >= 1, wk + ':edit_distribution')
        no_tasks = [t for t in own if t['suite'] == 'no_action']
        no = Counter(t['no_action_type'] for t in no_tasks)
        need(no['unsupported_kind'] >= 1 and any(t['no_action_type'] in {'already_recorded', 'no_evidence'} and
             t['request_targets']['foreshadows'] for t in no_tasks), wk + ':no_action_distribution')
        route_tasks = [t for t in own if t['suite'] == 'route']
        routes = Counter(t['expected_route'] for t in route_tasks)
        need(routes['change'] >= 2 and routes['ask'] >= 1, wk + ':route_distribution')
        need(sum('also_acceptable' in t for t in route_tasks) <= 2, wk + ':acceptable_count')
        semantics = review_by[wk].get('route_semantics', {})
        # Semantic tags are declarations for the independent blind reviewer;
        # their links and route labels are checked here, not their meanings.
        if semantics:
            for field, route, minimum in (('thread_change_ids', 'change', 2), ('ask_like_thread_ids', 'ask', 1)):
                tagged = semantics.get(field, [])
                need(isinstance(tagged, list) and len(tagged) == len(set(tagged)) >= minimum and all(
                    ids.get(tid, {}).get('work') == wk and ids[tid].get('suite') == 'route' and ids[tid].get('expected_route') == route
                    for tid in tagged), wk + ':review:' + field)
        pos, unique = positions[wk], list(unique_positions[wk].values())
        need(bool(pos) and sum(p > 1500 for p in pos) * 2 >= len(pos), wk + ':deep_evidence_half')
        stats['works'][wk].update({'suites': dict(Counter(t['suite'] for t in own)), 'primary_actions': dict(primary),
                                  'mixed_two_actions': multi, 'two_actions': sum(len(t['expected_actions']) == 2 for t in actions),
                                  'paraphrased': paraphrased, 'vague': vague, 'action_pages': dict(pages),
                                  'author_words': dict(author_words), 'no_action_types': dict(no), 'routes': dict(routes),
                                  'evidence_occurrences': len(pos), 'evidence_after1500': sum(p > 1500 for p in pos),
                                  'unique_evidence': len(unique), 'unique_after1500': sum(p > 1500 for p in unique)})

    locations = Counter(t['injection']['location']['kind'] for t in injection_tasks)
    runs = Counter(t['run_kind'] for t in injection_tasks)
    targets = Counter(t['injection_target']['kind'] for t in injection_tasks)
    new_allowed = sum(t['run_kind'] == 'change' and any(e['kind'] in NEW for e in t['allowed_actions']) for t in injection_tasks)
    need(len(injection_tasks) == 4 and sum(locations[k] for k in {'fact', 'foreshadow'}) == 4, 'injection:location_distribution')
    need(runs['change'] == 2 and runs['ask'] + runs['recap'] == 2, 'injection:run_distribution')
    need(set(targets) <= NEW | {'delete_thread'} and len(targets) >= 3 and new_allowed >= 1, 'injection:target_distribution')
    stats.update({'injection_locations': dict(locations), 'run_kinds': dict(runs),
                  'injection_targets': dict(targets), 'new_allowed_change_tasks': new_allowed})

    independent = jread('authoring/independent-review.json')
    need(independent.get('status') == 'completed' and independent.get('unresolved_findings') == 0, 'independent:completion')
    bindings = independent.get('sha256', {})
    need(set(bindings) == set(expected_paths) and all(bindings.get(rel) == digest(root / rel) for rel in expected_paths), 'independent:binding')
    authoring_paths = {'authoring/self-review.json', 'authoring/self-review.md'}
    authoring_bindings = independent.get('authoring_sha256', {})
    need(set(authoring_bindings) == authoring_paths and all(authoring_bindings.get(rel) == digest(root / rel)
                                                          for rel in authoring_paths), 'independent:authoring_binding')
    report_bindings = independent.get('reports', {})
    need(isinstance(report_bindings, dict) and bool(report_bindings), 'independent:reports')
    for rel, expected in report_bindings.items():
        path = (root / rel).resolve()
        safe = isinstance(rel, str) and rel.startswith('authoring/') and path.is_relative_to(root) and path.is_file()
        need(safe and isinstance(expected, str) and re.fullmatch(r'[0-9a-f]{64}', expected) and digest(path) == expected,
             'independent:report_binding')
    route_count = sum(t.get('suite') == 'route' for t in tasks)
    intent_count = sum(t.get('suite') == 'action' or t.get('suite') == 'injection' and t.get('run_kind') == 'change' for t in tasks)
    # Compare the independently judged route / action-object projections, not
    # merely the author's reported agreement totals. The add_thread planting
    # chapter is deliberately absent: the blind reviewer saw no chapter text.
    # Its chapter is checked above against the authored source evidence.
    comparison_path = 'authoring/blind-comparison.json'
    need(comparison_path in report_bindings, 'independent:comparison_binding')
    comparison = jread(comparison_path)
    need(isinstance(comparison, dict) and set(comparison) == {'items'} and
         isinstance(comparison.get('items'), list), 'independent:comparison_fields')

    def projection(entries):
        return [{'kind': e['kind'], 'target': {'about': e['target']['about']} if e['kind'] == 'add_thread' else e['target']}
                for e in entries]

    def ordered(entries):
        return sorted(json.dumps(e, ensure_ascii=False, sort_keys=True) for e in entries)

    expected_comparisons = {}
    for task in tasks:
        if task.get('suite') == 'route':
            expected_comparisons[(task['id'], 'route')] = task['expected_route']
        elif task.get('suite') == 'action':
            expected_comparisons[(task['id'], 'intent')] = projection(task['expected_actions'])
        elif task.get('suite') == 'injection' and task.get('run_kind') == 'change':
            expected_comparisons[(task['id'], 'intent')] = projection(task['allowed_actions'])
    comparison_keys, agreements = [], Counter()
    for i, item in enumerate(comparison.get('items', []), 1):
        label = f'independent:comparison:{i}'
        fields = {'id', 'scope', 'actual', 'expected', 'agrees', 'target_match_note'}
        if not need(isinstance(item, dict) and set(item) == fields, label + ':fields'):
            continue
        key = (item.get('id'), item.get('scope'))
        comparison_keys.append(key)
        if not need(key in expected_comparisons, label + ':task_scope'):
            continue
        need(string(item.get('target_match_note')), label + ':mapping_note')
        need(type(item.get('agrees')) is bool, label + ':agrees_type')
        expected = expected_comparisons[key]
        if key[1] == 'route':
            need(item['expected'] == expected, label + ':expected_route')
            need(item['actual'] in ROUTES, label + ':actual_route')
            agrees = item['actual'] == expected or item['actual'] in ids[key[0]].get('also_acceptable', [])
        else:
            valid = isinstance(item['actual'], list) and isinstance(item['expected'], list)
            for side in ('actual', 'expected'):
                if not isinstance(item[side], list):
                    continue
                for entry in item[side]:
                    valid = valid and isinstance(entry, dict) and set(entry) == {'kind', 'target'} and entry.get('kind') in KINDS
                    if not isinstance(entry, dict):
                        continue
                    kind, target = entry.get('kind'), entry.get('target')
                    if kind == 'add_thread':
                        valid = valid and isinstance(target, dict) and set(target) == {'about'} and string(target.get('about'), 1, 30)
                    elif kind == 'add_fact':
                        valid = valid and isinstance(target, dict) and set(target) == {'subject', 'predicate'} and all(
                            string(target.get(f), 1, 20) for f in ('subject', 'predicate'))
                    elif kind in {'resolve_thread', 'edit_thread', 'abandon_thread'}:
                        valid = valid and index(target, threads_by[ids[key[0]]['work']])
                    elif kind == 'change_fact':
                        valid = valid and index(target, facts_by[ids[key[0]]['work']])
            need(valid, label + ':projection')
            expected_matches = valid and ordered(item['expected']) == ordered(expected)
            need(expected_matches, label + ':expected_intent')
            agrees = valid and ordered(item['actual']) == ordered(expected)
        need(item['agrees'] is agrees, label + ':agreement_recomputed')
        if agrees:
            agreements[key[1]] += 1
    need(len(comparison_keys) == len(set(comparison_keys)) and set(comparison_keys) == set(expected_comparisons),
         'independent:comparison_coverage')
    for field, scope, total in (('blind_route', 'route', route_count), ('blind_intent', 'intent', intent_count)):
        blind = independent.get(field, {})
        need(blind.get('total') == total and blind.get('final_agreement') == agreements[scope] == total and
             blind.get('unresolved') == total - agreements[scope] == 0,
             'independent:' + field)
    stats.update({'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'scope': 'this_set_only', 'model_calls': 0,
                  'product_runs': 0, 'evaluation_runs': 0, 'semantic_acceptance': False,
                  'blind_route_total': route_count, 'blind_intent_total': intent_count,
                  'blind_route_agreement': agreements['route'], 'blind_intent_agreement': agreements['intent']})
    return stats


def main():
    try:
        result = validate()
    except InvalidStructure:
        result = {'status': 'FAIL', 'errors': ['structure:duplicate_json_key'], 'scope': 'this_set_only', 'model_calls': 0}
    except Exception:
        result = {'status': 'FAIL', 'errors': ['structure:unreadable_or_invalid'], 'scope': 'this_set_only', 'model_calls': 0}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
