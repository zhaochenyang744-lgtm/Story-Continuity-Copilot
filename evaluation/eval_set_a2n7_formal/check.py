"""Offline, content-free A2 supplementary validation, derived from a26/check.py.

The validator checks frozen structure and review provenance, not semantic acceptance.
It reads only this set and never imports product code or an evaluation runner.
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
KINDS = {'add_fact', 'change_fact', 'resolve_thread', 'add_thread', 'edit_thread', 'abandon_thread'}
NEW_KINDS = {'add_thread', 'edit_thread', 'abandon_thread'}
THREAD_KINDS = {'resolve_thread', 'edit_thread', 'abandon_thread'}
EXCLUDED = ['eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring']
BLOCKED = {'eval_set_a3f2_formal', 'eval_set_a3s2_formal', 'eval_set_a3s3_formal'}
MEMORIES = {'static_canon', 'dynamic_state', 'event_timeline', 'character_knowledge', 'open_thread'}
STATES = {'planned', 'planted', 'developing', 'resolved', 'abandoned'}
NO_ACTION = {'already_recorded': 4, 'no_evidence': 4, 'prose_edit': 2, 'unsupported_kind': 2}
BLIND_FILES = {'authoring/blind-packet.json', 'authoring/blind-key.json',
               'authoring/blind-verdicts.json', 'authoring/blind-comparison.json'}


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalized(value):
    # The task removes whitespace and punctuation only: case is retained.
    return ''.join(c for c in value if not c.isspace() and not unicodedata.category(c).startswith('P'))


def counter_output(counter, allowed):
    """Never echo an invalid enum value, including on failed validation."""
    result = {key: counter[key] for key in sorted(allowed) if counter[key]}
    invalid = sum(count for key, count in counter.items() if key not in allowed)
    if invalid:
        result['invalid'] = invalid
    return result


def complete_selection(body, selection):
    if not isinstance(selection, str) or not selection:
        return False
    tail = selection.rstrip(' \t\r\n”’\"\'')
    if not tail or tail[-1] not in '。！？':
        return False
    for match in re.finditer(re.escape(selection), body):
        before = body[:match.start()].rstrip(' \t\r')
        if not before or before[-1] in '。！？\n：:“‘\"\'':
            return True
    return False


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
    root = root.resolve()
    errors = []
    stats = {'works': {}, 'tasks': 0, 'copy_errors': 0, 'novelty_errors': 0}

    def need(ok, label):
        if not ok:
            errors.append(label)
        return bool(ok)

    def read(rel):
        path = (root / rel).resolve()
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('file')
        return path.read_text(encoding='utf-8')

    def jread(rel):
        return json.loads(read(rel), object_pairs_hook=unique_object)

    def string(value, low=1, high=10**9):
        return isinstance(value, str) and low <= len(value) <= high and bool(value.strip())

    def index(value, items):
        return type(value) is int and 1 <= value <= len(items)

    need(all(not p.is_symlink() and not (hasattr(p, 'is_junction') and p.is_junction())
             for p in root.rglob('*')), 'structure:symlink')
    for path in root.rglob('*'):
        if path.is_file() and not path.is_symlink() and path.suffix in {'.py', '.json', '.md', '.txt', '.sha256'}:
            raw = path.read_bytes()
            need(not raw.startswith(b'\xef\xbb\xbf') and b'\r' not in raw, 'structure:utf8_lf')
            raw.decode('utf-8')
    for rel in ('README.md', 'tasks.json', 'set.sha256', 'check.py', 'authoring/self-review.md',
                'authoring/self-review.json', 'authoring/novelty-reference.json', 'authoring/sealed-comparison.json', 'authoring/independent-review.json',
                *sorted(BLIND_FILES)):
        need((root / rel).is_file(), 'structure:' + rel)
    data, review = jread('tasks.json'), jread('authoring/self-review.json')
    need(isinstance(data, dict) and set(data) == {'version', 'set_id', 'author', 'works', 'tasks'}, 'top:fields')
    need(data.get('version') == 'a2-2', 'top:version')
    need(data.get('set_id') == 'a2n7-formal', 'top:set_id')
    need(data.get('author') == 'evaluation authoring', 'top:author')
    expected_keys = {'w01'}
    total_chapters = 12
    works_list, tasks = data.get('works'), data.get('tasks')
    need(isinstance(works_list, list) and isinstance(tasks, list), 'top:arrays')
    works = {w.get('key'): w for w in works_list if isinstance(w, dict)}
    need(set(works) == expected_keys and len(works_list) == len(expected_keys), 'works:keys')
    need(isinstance(review.get('works'), dict) and set(review['works']) == expected_keys, 'review:works')
    expected_paths = sorted(['tasks.json'] + [f'works/{wk}.md' for wk in expected_keys] +
                            [f'materials/{wk}-{kind}.json' for wk in expected_keys for kind in ('facts', 'foreshadows')])
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
    positions = defaultdict(list)
    unique_positions = defaultdict(dict)
    all_names = []

    def quote(wk, chapter, text, label, count=True):
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
            need(body.count(text) == 1, label + ':quote_unique')
            pos = len(HAN.findall(body[:body.index(text)])) + 1
            if count:
                positions[wk].append(pos)
                unique_positions[wk][(number, text)] = pos
            return pos
        return None

    for wk in sorted(expected_keys):
        w, wr = works[wk], review['works'][wk]
        lab = wk
        need(set(w) == {'key', 'title', 'language', 'source_file', 'purpose', 'kind', 'names', 'materials', 'shared_draft'}, lab + ':fields')
        need(string(w.get('title')) and w.get('language') == 'zh' and w.get('purpose') == 'general' and w.get('kind') == 'long', lab + ':metadata')
        need(w.get('source_file') == f'works/{wk}.md' and w.get('materials') ==
             {'facts': f'materials/{wk}-facts.json', 'foreshadows': f'materials/{wk}-foreshadows.json'}, lab + ':paths')
        source = read(f'works/{wk}.md')
        chs = chapter_map(source)
        parsed[wk] = chs
        chapter_order = [int(n) for n in re.findall(r'^# 第([1-9][0-9]*)章 [^\n\r]+$', source, re.M)]
        need(chapter_order == list(range(1, total_chapters + 1)) and
             len(re.findall(r'^# ', source, re.M)) == total_chapters, lab + ':chapters')
        need(bool(re.match(r'\s*# 第1章 ', source)), lab + ':chapter_start')
        lengths = {n: len(HAN.findall(value['body'])) for n, value in chs.items()}
        for n, count in lengths.items():
            need(2500 <= count <= 3500, f'{lab}:chapter:{n}:length')
        draft = w.get('shared_draft', {})
        need(isinstance(draft, dict) and set(draft) == {'chapter_title', 'body'} and
             bool(re.fullmatch(r'第' + str(total_chapters + 1) + r'章 [^\n]+', draft.get('chapter_title', ''))) and
             isinstance(draft.get('body'), str) and 600 <= len(HAN.findall(draft['body'])) <= 1000, lab + ':draft')
        names = w.get('names', [])
        need(isinstance(names, list) and all(string(n) for n in names) and len(set(names)) == len(names), lab + ':names')
        need(all(n in source + draft.get('body', '') for n in names), lab + ':names_presence')
        all_names.extend(names)
        references[wk] = set().union(*(grams(ch['body'], names) for ch in chs.values()))
        fs, ts = jread(f'materials/{wk}-facts.json'), jread(f'materials/{wk}-foreshadows.json')
        facts_by[wk], threads_by[wk], review_by[wk] = fs, ts, wr
        need(isinstance(fs, list) and 25 <= len(fs) <= 40, lab + ':fact_count')
        need(isinstance(ts, list) and 10 <= len(ts) <= 14, lab + ':thread_count')
        for i, fact in enumerate(fs, 1):
            need(isinstance(fact, dict) and set(fact) == {'memory_type', 'subject', 'predicate', 'value', 'chapter'}, f'{lab}:fact:{i}:fields')
            need(fact.get('memory_type') in MEMORIES and string(fact.get('subject'), 1, 20) and
                 string(fact.get('predicate'), 1, 20) and string(fact.get('value'), 1, 60) and
                 type(fact.get('chapter')) is int and fact['chapter'] in chs, f'{lab}:fact:{i}:values')
        need(len({(f['subject'], f['predicate']) for f in fs}) == len(fs), lab + ':fact_keys')
        states = Counter(t.get('status') for t in ts)
        need(states['resolved'] >= 1 and states['planted'] + states['developing'] >= 4, lab + ':thread_states')
        for i, thread in enumerate(ts, 1):
            fields = {'title', 'description', 'status', 'planted_chapter'} | ({'resolved_chapter'} if thread.get('status') == 'resolved' else set())
            need(set(thread) == fields and string(thread.get('title'), 1, 30) and
                 string(thread.get('description'), 20, 200) and thread.get('status') in STATES and
                 type(thread.get('planted_chapter')) is int and thread['planted_chapter'] in chs, f'{lab}:thread:{i}:values')
            if thread.get('status') == 'resolved':
                need(type(thread.get('resolved_chapter')) is int and thread['planted_chapter'] <= thread['resolved_chapter'] <= total_chapters,
                     f'{lab}:thread:{i}:resolution')
        need(len({t['title'] for t in ts}) == len(ts), lab + ':thread_titles')
        for field, minimum in (('stale_facts', 5), ('missing_facts', 6), ('resolved_unmarked', 4)):
            entries = wr.get(field)
            need(isinstance(entries, list) and len(entries) >= minimum, f'{lab}:review:{field}:count')
            for i, entry in enumerate(entries, 1):
                label = f'{lab}:review:{field}:{i}'
                fields = {'fact', 'changed_chapter', 'quote'} if field == 'stale_facts' else (
                    {'subject', 'predicate', 'chapter', 'quote'} if field == 'missing_facts' else
                    {'foreshadow', 'chapter', 'quote'})
                need(isinstance(entry, dict) and set(entry) == fields, label + ':fields')
                chapter_key = 'changed_chapter' if field == 'stale_facts' else 'chapter'
                need(type(entry.get(chapter_key)) is int and entry[chapter_key] in chs, label + ':chapter')
                quote(wk, entry.get(chapter_key), entry.get('quote'), label)
                if field == 'stale_facts':
                    valid = index(entry.get('fact'), fs)
                    need(valid, label + ':index')
                    if valid:
                        need(type(entry.get('changed_chapter')) is int and entry['changed_chapter'] > fs[entry['fact'] - 1]['chapter'], label + ':chronology')
                elif field == 'resolved_unmarked':
                    valid = index(entry.get('foreshadow'), ts)
                    need(valid, label + ':index')
                    if valid:
                        thread = ts[entry['foreshadow'] - 1]
                        need(thread['status'] in {'planned', 'planted', 'developing'} and type(entry.get('chapter')) is int and
                             entry['chapter'] >= thread['planted_chapter'], label + ':state')
                else:
                    need(string(entry.get('subject'), 1, 20) and string(entry.get('predicate'), 1, 20) and
                         (entry['subject'], entry['predicate']) not in {(f['subject'], f['predicate']) for f in fs}, label + ':missing')
            keyfield = 'fact' if field == 'stale_facts' else 'foreshadow' if field == 'resolved_unmarked' else None
            keys = [e.get(keyfield) if keyfield else (e.get('subject'), e.get('predicate')) for e in entries]
            need(len(set(keys)) == len(keys), f'{lab}:review:{field}:duplicates')
        resolved_ids = {e['foreshadow'] for e in wr['resolved_unmarked']}
        need(sum(index(n, ts) and ts[n - 1]['status'] in {'planted', 'developing'}
                 for n in resolved_ids) >= 4, lab + ':review:resolved_unmarked:registered_states')
        open_entries = wr.get('open_threads', [])
        need(isinstance(open_entries, list) and len(open_entries) >= 4, lab + ':review:open_threads:count')
        open_ids = []
        for i, entry in enumerate(open_entries, 1):
            label = f'{lab}:review:open_threads:{i}'
            good = isinstance(entry, dict) and set(entry) == {'foreshadow', 'abandonable'} and index(entry.get('foreshadow'), ts)
            need(good and type(entry.get('abandonable')) is bool, label + ':fields')
            if good:
                number = entry['foreshadow']
                open_ids.append(number)
                need(ts[number - 1]['status'] in {'planned', 'planted', 'developing'}, label + ':state')
        need(len(open_ids) == len(set(open_ids)) and not resolved_ids.intersection(open_ids), lab + ':review:open_threads:disjoint')
        need(sum(e.get('abandonable') is True for e in open_entries) >= 2, lab + ':review:abandonable:count')
        need(sum(t['status'] in {'planned', 'planted', 'developing'} and i not in resolved_ids for i, t in enumerate(ts, 1)) >= 4, lab + ':unresolved_threads')
        for field, minimum in (('stale_notes', 2), ('missing_threads', 3)):
            entries = wr.get(field, [])
            need(isinstance(entries, list) and len(entries) >= minimum, f'{lab}:review:{field}:count')
            entry_keys = []
            for i, entry in enumerate(entries, 1):
                label = f'{lab}:review:{field}:{i}'
                fields = {'foreshadow', 'chapter', 'quote'} if field == 'stale_notes' else {'about', 'planted_chapter', 'quote'}
                need(isinstance(entry, dict) and set(entry) == fields, label + ':fields')
                chapter_key = 'chapter' if field == 'stale_notes' else 'planted_chapter'
                number = entry.get(chapter_key)
                need(type(number) is int and number in chs, label + ':chapter')
                quote(wk, number, entry.get('quote'), label)
                if field == 'stale_notes':
                    valid = index(entry.get('foreshadow'), ts)
                    need(valid, label + ':index')
                    if valid:
                        need(number >= ts[entry['foreshadow'] - 1]['planted_chapter'], label + ':chronology')
                    entry_keys.append(entry.get('foreshadow'))
                else:
                    need(string(entry.get('about'), 1, 30), label + ':about')
                    entry_keys.append((entry.get('about'), number))
            need(len(entry_keys) == len(set(entry_keys)), f'{lab}:review:{field}:duplicates')
        aliases = wr.get('aliases', [])
        characters = wr.get('characters', [])
        need(isinstance(characters, list) and all(string(n) for n in characters) and
             len(characters) == len(set(characters)) >= 8 and all(n in names for n in characters), lab + ':characters')
        need(isinstance(aliases, list) and len({a.get('name') for a in aliases}) >= 4, lab + ':aliases')
        for i, alias in enumerate(aliases, 1):
            need(isinstance(alias, dict) and set(alias) == {'name', 'alias', 'chapter', 'quote'} and
                 type(alias.get('chapter')) is int and alias['chapter'] in chs, f'{lab}:alias:{i}:fields')
            need(alias.get('name') in characters and alias.get('alias') in names and alias.get('alias') != alias.get('name'), f'{lab}:alias:{i}:names')
            quote(wk, alias.get('chapter'), alias.get('quote'), f'{lab}:alias:{i}')
            need(alias.get('name') in alias.get('quote', '') and alias.get('alias') in alias.get('quote', ''),
                 f'{lab}:alias:{i}:quote_identity')
            need(any(f.get('subject') == alias.get('name') and alias.get('alias') in f.get('value', '')
                     for f in fs), f'{lab}:alias:{i}:fact_identity')
        need(len({(a['name'], a['alias']) for a in aliases}) == len(aliases), lab + ':alias_duplicates')
        stats['works'][wk] = {'chapters': len(chs), 'chapter_han_min': min(lengths.values()), 'chapter_han_max': max(lengths.values()),
                              'total_han': sum(lengths.values()), 'draft_han': len(HAN.findall(draft['body'])), 'names': len(names),
                              'characters': len(characters), 'aliases': len(aliases), 'facts': len(fs), 'stale_facts': len(wr['stale_facts']),
                              'missing_facts': len(wr['missing_facts']), 'foreshadows': len(ts), 'foreshadow_states': counter_output(states, STATES),
                              'resolved_unmarked': len(wr['resolved_unmarked']), 'open_threads': len(open_entries),
                              'abandonable': sum(e.get('abandonable') is True for e in open_entries),
                              'stale_notes': len(wr['stale_notes']), 'missing_threads': len(wr['missing_threads'])}
    need(len(all_names) == len(set(all_names)), 'works:names_overlap')
    ids = {}
    prefix = 'a2n7-'
    for i, task in enumerate(tasks, 1):
        tid = task.get('id')
        valid = isinstance(tid, str) and bool(re.fullmatch(prefix + r'[A-Za-z0-9][A-Za-z0-9_-]*', tid))
        need(valid, f'task:{i}:id')
        need(tid not in ids, f'task:{i}:duplicate')
        if valid:
            ids[tid] = task
    expected_count = 20
    need(len(tasks) == len(ids) == expected_count, 'tasks:count')
    stats['tasks'] = len(tasks)
    ref = jread('authoring/novelty-reference.json')
    old_inputs = ref.get('normalized_inputs', [])
    need(isinstance(old_inputs, list) and bool(old_inputs) and all(string(s) and s == normalized(s) for s in old_inputs), 'novelty:reference')
    need(ref.get('excluded_directories') == EXCLUDED, 'novelty:exclusions')
    need(ref.get('normalization') == 'remove_whitespace_and_unicode_punctuation_preserve_case', 'novelty:normalization')
    need(isinstance(ref.get('source_hashes'), dict) and bool(ref['source_hashes']), 'novelty:provenance')
    source_hashes = ref.get('source_hashes', {})
    text_hashes = ref.get('names_corpus_sha256', {})
    need(isinstance(text_hashes, dict) and bool(text_hashes) and all(
        isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) for value in list(source_hashes.values()) + list(text_hashes.values())),
        'novelty:source_hash_format')
    grouped_inputs = ref.get('normalized_inputs_by_source', {})
    need(isinstance(grouped_inputs, dict) and set(grouped_inputs) == set(source_hashes) and all(
        isinstance(values, list) and values == sorted(set(values)) and all(string(v) and v == normalized(v) for v in values)
        for values in grouped_inputs.values()) and sorted({v for values in grouped_inputs.values() for v in values}) == old_inputs,
        'novelty:input_source_binding')
    need(ref.get('reference_counts') == {'source_files': len(source_hashes), 'normalized_inputs': len(old_inputs),
                                        'names_text_files': len(text_hashes)}, 'novelty:reference_counts')
    need(old_inputs == sorted(set(old_inputs)), 'novelty:reference_duplicates')
    need(all(isinstance(path, str) and not any(part in set(EXCLUDED) for part in Path(path).parts) for path in list(source_hashes) + list(text_hashes)),
         'novelty:excluded_source')
    need(all(not any(part in BLOCKED for part in Path(path).parts)
             for path in list(source_hashes) + list(text_hashes)), 'novelty:forbidden_source')
    stats['novelty_reference_inputs'] = len(old_inputs)
    sealed = jread('authoring/sealed-comparison.json')
    need(isinstance(sealed, dict) and sealed.get('status') == 'PASS' and
         sealed.get('names_overlap') == 0 and sealed.get('novelty_errors') == 0 and
         sealed.get('excluded_directories') == EXCLUDED, 'sealed:status')
    sealed_bindings = sealed.get('candidate_sha256', {})
    need(isinstance(sealed_bindings, dict) and set(sealed_bindings) == set(expected_paths) and
         all(sealed_bindings.get(rel) == digest(root / rel) for rel in expected_paths), 'sealed:candidate_binding')
    sealed_sources = sealed.get('source_hashes', {})
    need(isinstance(sealed_sources, dict) and all(not any(part in BLOCKED for part in Path(rel).parts)
         for rel in sealed_sources), 'sealed:forbidden_source')
    need(isinstance(sealed_sources, dict) and bool(sealed_sources) and all(
        isinstance(rel, str) and not Path(rel).is_absolute() and '..' not in Path(rel).parts and
        any(part in EXCLUDED for part in Path(rel).parts) and isinstance(value, str) and
        re.fullmatch(r'[0-9a-f]{64}', value) for rel, value in sealed_sources.items()), 'sealed:source_provenance')
    sealed_counts = sealed.get('reference_counts', {})
    need(isinstance(sealed_counts, dict) and set(sealed_counts) == {'source_files', 'normalized_inputs', 'names_text_files'} and
         all(type(n) is int and n >= 0 for n in sealed_counts.values()) and
         sealed_counts.get('names_text_files') == len(sealed_sources) and
         sealed_counts.get('source_files') == sum(Path(rel).name == 'tasks.json' for rel in sealed_sources), 'sealed:counts')
    stats['sealed_reference_counts'] = {key: sealed_counts.get(key) if type(sealed_counts.get(key)) is int else 0
                                         for key in ('source_files', 'normalized_inputs', 'names_text_files')}

    def copy_check(wk, value, label):
        if grams(value, works[wk]['names']) & references[wk]:
            errors.append(label + ':copy8')
            stats['copy_errors'] += 1

    def action(wk, entry, label, author_words=False):
        fs, ts, wr = facts_by[wk], threads_by[wk], review_by[wk]
        need(isinstance(entry, dict) and set(entry) == {'kind', 'target', 'after_points', 'evidence_chapters', 'evidence_quotes'}, label + ':fields')
        kind, target = entry.get('kind'), entry.get('target')
        need(kind in KINDS, label + ':kind')
        if kind == 'change_fact':
            need(index(target, fs) and target in {e['fact'] for e in wr['stale_facts']}, label + ':target')
        elif kind == 'resolve_thread':
            need(index(target, ts) and target in {e['foreshadow'] for e in wr['resolved_unmarked']}, label + ':target')
        elif kind == 'add_fact':
            need(isinstance(target, dict) and set(target) == {'subject', 'predicate'} and
                 (target.get('subject'), target.get('predicate')) in {(e['subject'], e['predicate']) for e in wr['missing_facts']}, label + ':target')
        elif kind == 'add_thread':
            need(isinstance(target, dict) and set(target) == {'about', 'planted_chapter'} and
                 string(target.get('about'), 1, 30) and type(target.get('planted_chapter')) is int and
                 (target.get('about'), target.get('planted_chapter')) in
                 {(e['about'], e['planted_chapter']) for e in wr['missing_threads']}, label + ':target')
        elif kind == 'edit_thread':
            need(index(target, ts) and (author_words or target in {e['foreshadow'] for e in wr['stale_notes']}), label + ':target')
        elif kind == 'abandon_thread':
            need(index(target, ts) and target in {e['foreshadow'] for e in wr['open_threads'] if e['abandonable']}, label + ':target')
        points = entry.get('after_points')
        need(isinstance(points, list) and 1 <= len(points) <= 3 and all(string(p, 1, 30) for p in points) and
             len(set(points)) == len(points), label + ':points')
        for i, point in enumerate(points, 1):
            copy_check(wk, point, f'{label}:point:{i}')
        cs, qs = entry.get('evidence_chapters'), entry.get('evidence_quotes')
        may_be_empty = kind == 'abandon_thread' or kind == 'edit_thread' and author_words
        need(isinstance(cs, list) and isinstance(qs, list) and len(cs) == len(qs) and
             (bool(cs) or may_be_empty) and
             all(isinstance(c, str) for c in cs), label + ':evidence')
        need(len(set(zip(cs, qs))) == len(cs), label + ':evidence_duplicates')
        for i, (chapter, q) in enumerate(zip(cs, qs), 1):
            quote(wk, chapter, q, f'{label}:evidence:{i}')
        proof = None
        if kind == 'change_fact':
            proof = next((e for e in wr['stale_facts'] if e['fact'] == target), None)
        elif kind == 'resolve_thread':
            proof = next((e for e in wr['resolved_unmarked'] if e['foreshadow'] == target), None)
        elif kind == 'add_fact' and isinstance(target, dict):
            proof = next((e for e in wr['missing_facts'] if (e['subject'], e['predicate']) ==
                          (target.get('subject'), target.get('predicate'))), None)
        elif kind == 'add_thread' and isinstance(target, dict):
            proof = next((e for e in wr['missing_threads'] if (e['about'], e['planted_chapter']) ==
                          (target.get('about'), target.get('planted_chapter'))), None)
        elif kind == 'edit_thread' and not author_words:
            proof = next((e for e in wr['stale_notes'] if e['foreshadow'] == target), None)
        if proof is not None and kind != 'abandon_thread':
            chapter_key = 'changed_chapter' if kind == 'change_fact' else 'planted_chapter' if kind == 'add_thread' else 'chapter'
            number = proof.get(chapter_key)
            need(number in parsed[wk] and parsed[wk][number]['title'] in cs, label + ':proof_chapter')
        if kind == 'resolve_thread':
            # Task 32 and SPEC addenda 4/5 require these exact program points.
            resolution = '收在第' + str(proof['chapter']) + '章' if proof else None
            need(isinstance(points, list) and len(points) in {2, 3} and
                 points.count('已回收') == 1 and resolution is not None and points.count(resolution) == 1 and
                 sum(bool(re.fullmatch(r'收在第[1-9][0-9]*章', p)) for p in points if isinstance(p, str)) == 1,
                 label + ':resolve_program_points')
        elif kind == 'abandon_thread':
            need(points == ['已放弃'], label + ':abandon_program_points')
        elif kind == 'add_thread' and isinstance(target, dict):
            planted_points = [p for p in points if isinstance(p, str) and re.fullmatch(r'埋在第[1-9][0-9]*章', p)]
            need(not planted_points or planted_points == ['埋在第' + str(target.get('planted_chapter')) + '章'], label + ':planted_program_points')
        return (kind, json.dumps(target, ensure_ascii=False, sort_keys=True))

    def alias_use(task, wk, label):
        use = task.get('alias_use')
        fs, wr = facts_by[wk], review_by[wk]
        good = (isinstance(use, dict) and set(use) == {'name', 'alias', 'fact'} and
                string(use.get('name')) and string(use.get('alias')) and index(use.get('fact'), fs))
        need(good, label + ':alias_use_fields')
        if not good:
            return False
        name, alias = use['name'], use['alias']
        identity = fs[use['fact'] - 1]
        good = ((name, alias) in {(a['name'], a['alias']) for a in wr['aliases']} and
                identity['subject'] == name and alias in identity['value'] and
                alias in task.get('request', '') and name not in task.get('request', ''))
        need(good, label + ':alias_identity')
        if task.get('suite') == 'action':
            entries = task.get('expected_actions', [])
            target = entries[0].get('target') if len(entries) == 1 else None
            target_ok = (len(entries) == 1 and entries[0].get('kind') == 'change_fact' and
                         index(target, fs) and fs[target - 1]['subject'] == name)
        else:
            targets = task.get('request_targets', {}).get('facts', [])
            target_ok = (task.get('no_action_type') == 'already_recorded' and bool(targets) and
                         all(index(n, fs) and fs[n - 1]['subject'] == name for n in targets))
        need(target_ok, label + ':alias_target_subject')
        return good and target_ok

    for i, task in enumerate(tasks, 1):
        tid = task.get('id') if task.get('id') in ids else f'task:{i}'
        wk, suite = task.get('work'), task.get('suite')
        if not need(wk in expected_keys, tid + ':work'):
            continue
        need(suite in {'action', 'no_action'}, tid + ':suite')
        base_fields = {'id', 'work', 'suite', 'context', 'why', 'request'}
        extra = {'expected_actions', 'paraphrased', 'vague'} if suite == 'action' else {'no_action_type', 'request_targets'}
        if 'alias_use' in task:
            extra.add('alias_use')
        if suite == 'action' and any(e.get('kind') == 'edit_thread' for e in task.get('expected_actions', []) if isinstance(e, dict)):
            extra.add('author_words')
        if suite == 'no_action' and 'premise_contradicted' in task:
            extra.add('premise_contradicted')
            need(type(task['premise_contradicted']) is bool and task.get('no_action_type') == 'no_evidence', tid + ':premise_flag')
            if task['premise_contradicted'] is True:
                extra.add('premise_evidence')
        need(set(task) == base_fields | extra, tid + ':fields')
        need(string(task.get('why')), tid + ':why')
        context = task.get('context', {})
        need(isinstance(context, dict) and set(context) <= {'page', 'chapter_number', 'selection'} and
             context.get('page') in PAGES, tid + ':context')
        if 'chapter_number' in context:
            need(type(context['chapter_number']) is int and 1 <= context['chapter_number'] <= total_chapters + 1, tid + ':chapter_number')
        if 'selection' in context:
            selection = context['selection']
            need(context['page'] == 'writing' and string(selection, 1, 80) and selection in works[wk]['shared_draft']['body'] and
                 complete_selection(works[wk]['shared_draft']['body'], selection), tid + ':selection')
        need(string(task.get('request'), 6, 80) and 'input' not in task, tid + ':input')
        if isinstance(task.get('request'), str):
            copy_check(wk, task['request'], tid + ':request')
            n = normalized(task['request'])
            match = any(n == old or (min(len(n), len(old)) * 2 / max(1, len(n) + len(old)) >= .8 and
                                    SequenceMatcher(None, n, old).ratio() >= .8) for old in old_inputs)
            if match:
                errors.append(tid + ':novelty80')
                stats['novelty_errors'] += 1
            need(not re.search(r'如果|假如|假使|倘若|要是|若是', task['request']), tid + ':conditional_request')
        if suite == 'action':
            entries = task.get('expected_actions', [])
            need(isinstance(entries, list) and len(entries) == 1, tid + ':actions')
            need(type(task.get('paraphrased')) is bool and type(task.get('vague')) is bool, tid + ':flags')
            if any(e.get('kind') == 'edit_thread' for e in entries):
                need(type(task.get('author_words')) is bool, tid + ':author_words')
            for j, entry in enumerate(entries, 1):
                action(wk, entry, f'{tid}:action:{j}', task.get('author_words') is True)
            if any(e.get('kind') == 'change_fact' for e in entries):
                alias_use(task, wk, tid)
            elif 'alias_use' in task:
                need(False, tid + ':alias_use_scope')
            if any(e.get('kind') == 'abandon_thread' for e in entries):
                need(bool(re.search(r'不.{0,12}(?:写|追|展开)|放弃|作罢|停写|别.{0,12}(?:写|追)|舍弃', task.get('request', ''))) and
                     not re.search(r'[？?]|是否|是不是|要不要|能不能|可不可以', task.get('request', '')), tid + ':abandon_author_intent')
        elif suite == 'no_action':
            need(task.get('no_action_type') in NO_ACTION, tid + ':no_action_type')
            targets = task.get('request_targets', {})
            need(isinstance(targets, dict) and set(targets) == {'facts', 'foreshadows'} and
                 all(isinstance(targets.get(f), list) and len(set(targets[f])) == len(targets[f]) and
                     all(index(n, items) for n in targets[f]) for f, items in (('facts', facts_by[wk]), ('foreshadows', threads_by[wk]))), tid + ':request_targets')
            if task.get('no_action_type') == 'already_recorded':
                need(bool(targets.get('facts') or targets.get('foreshadows')), tid + ':already_recorded_target')
            if 'alias_use' in task:
                alias_use(task, wk, tid)
            if task.get('no_action_type') == 'unsupported_kind':
                need(bool(re.search(r'删|移除|去掉|抹掉|清掉|撤掉', task.get('request', ''))) and
                     len(targets.get('facts', [])) + len(targets.get('foreshadows', [])) == 1, tid + ':unsupported_deletion')
            if task.get('premise_contradicted') is True:
                proof = task.get('premise_evidence', {})
                need(isinstance(proof, dict) and set(proof) == {'chapter', 'quote'} and
                     type(proof.get('chapter')) is int, tid + ':premise_evidence_fields')
                quote(wk, proof.get('chapter'), proof.get('quote'), tid + ':premise_evidence')
                need(string(proof.get('quote')) and proof.get('quote') in task.get('why', ''), tid + ':premise_why_quote')
    for wk in sorted(expected_keys):
        own = [t for t in tasks if t.get('work') == wk]
        s = stats['works'][wk]
        need(Counter(t.get('suite') for t in own) == {'action': 8, 'no_action': 12}, wk + ':suite_distribution')
        actions = [t for t in own if t.get('suite') == 'action']
        primary = Counter(t['expected_actions'][0]['kind'] for t in actions if t.get('expected_actions'))
        need(primary == {'add_fact': 2, 'change_fact': 2, 'resolve_thread': 2, 'edit_thread': 1, 'abandon_thread': 1}, wk + ':primary_actions')
        multi = sum(len(t.get('expected_actions', [])) != 1 for t in actions)
        paraphrased = sum(t.get('paraphrased') is True for t in actions)
        vague = sum(t.get('vague') is True for t in actions)
        need(multi == 0 and paraphrased >= 4 and vague >= 1, wk + ':action_distribution')
        vague_new = sum(t.get('vague') is True and any(e.get('kind') in NEW_KINDS for e in t.get('expected_actions', [])) for t in actions)
        need(vague_new >= 1, wk + ':new_action_vague')
        edits = [t for t in actions if t.get('expected_actions') and t['expected_actions'][0].get('kind') == 'edit_thread']
        edit_modes = Counter('author_words' if t.get('author_words') is True else 'from_text' for t in edits)
        need(len(edits) == 1, wk + ':edit_modes')
        need(len({t.get('context', {}).get('page') for t in actions}) >= 3, wk + ':action_pages')
        no_tasks = [t for t in own if t.get('suite') == 'no_action']
        no = Counter(t.get('no_action_type') for t in no_tasks)
        need(no == NO_ACTION, wk + ':no_action_distribution')
        thread_no = Counter(t.get('no_action_type') for t in no_tasks if t.get('request_targets', {}).get('foreshadows'))
        need(thread_no['already_recorded'] >= 1 and thread_no['no_evidence'] >= 1 and
             thread_no['unsupported_kind'] >= 1, wk + ':no_action_thread_distribution')
        already_alias = sum(t.get('no_action_type') == 'already_recorded' and 'alias_use' in t for t in no_tasks)
        change_alias = sum(t.get('expected_actions') and t['expected_actions'][0].get('kind') == 'change_fact' and
                           'alias_use' in t for t in actions)
        contradicted = sum(t.get('no_action_type') == 'no_evidence' and t.get('premise_contradicted') is True for t in no_tasks)
        need(already_alias >= 2 and change_alias == 2, wk + ':alias_task_distribution')
        need(contradicted >= 2, wk + ':premise_contradicted_distribution')
        s.update({'suites': counter_output(Counter(t.get('suite') for t in own), {'action', 'no_action'}),
                  'primary_actions': counter_output(primary, KINDS), 'multiple_or_missing_actions': multi,
                  'paraphrased': paraphrased, 'vague': vague, 'vague_new_actions': vague_new,
                  'edit_thread_modes': counter_output(edit_modes, {'author_words', 'from_text'}),
                  'no_action_types': counter_output(no, set(NO_ACTION)), 'no_action_thread_types': counter_output(thread_no, set(NO_ACTION)),
                  'already_recorded_alias': already_alias, 'change_fact_alias': change_alias, 'premise_contradicted': contradicted})
        pos, unique = positions[wk], list(unique_positions[wk].values())
        need(bool(pos) and sum(p > 1500 for p in pos) * 2 >= len(pos), wk + ':deep_evidence_half')
        need(bool(unique) and sum(p > 2500 for p in unique) * 3 >= len(unique), wk + ':deep_evidence_third_after2500')
        s.update({'evidence_occurrences': len(pos), 'evidence_after1500': sum(p > 1500 for p in pos),
                  'unique_evidence': len(unique), 'unique_after1500': sum(p > 1500 for p in unique),
                  'unique_after2500': sum(p > 2500 for p in unique),
                  'evidence_han_min': min(pos) if pos else 0, 'evidence_han_max': max(pos) if pos else 0,
                  'evidence_position_buckets': {'1_1500': sum(p <= 1500 for p in pos),
                                                '1501_2500': sum(1500 < p <= 2500 for p in pos),
                                                '2501_plus': sum(p > 2500 for p in pos)}})
    independent = jread('authoring/independent-review.json')
    need(independent.get('status') == 'completed' and independent.get('unresolved_findings') == 0 and
         independent.get('chapter_coverage') == {wk: total_chapters for wk in sorted(expected_keys)}, 'independent:completion')
    bindings = independent.get('sha256', {})
    need(set(bindings) == set(expected_paths) and all(bindings.get(rel) == digest(root / rel) for rel in expected_paths), 'independent:binding')
    authoring_paths = {'authoring/self-review.json', 'authoring/self-review.md', 'authoring/novelty-reference.json',
                       'authoring/sealed-comparison.json'}
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
    source_reports = independent.get('source_reports', {})
    need(isinstance(source_reports, dict) and set(source_reports) == expected_keys, 'independent:source_reports')
    for wk in sorted(expected_keys):
        rel = source_reports.get(wk)
        safe = isinstance(rel, str) and rel.startswith('authoring/') and rel in report_bindings
        need(safe, f'independent:{wk}:source_report_path')
        if not safe:
            continue
        report = jread(rel)
        need(isinstance(report, dict) and report.get('work') == wk and report.get('status') == 'completed' and
             report.get('unresolved_findings') == 0 and report.get('independent_of_creation_and_gold_authoring') is True and
             report.get('chapters_read') == list(range(1, total_chapters + 1)) and report.get('shared_draft_read') is True,
             f'independent:{wk}:source_report_coverage')
        need(report.get('source_sha256') == digest(root / f'works/{wk}.md'), f'independent:{wk}:source_report_source')
        need(report.get('draft_body_sha256') == hashlib.sha256(works[wk]['shared_draft']['body'].encode('utf-8')).hexdigest(),
             f'independent:{wk}:source_report_draft')
        need(report.get('tasks_sha256') == digest(root / 'tasks.json') and
             isinstance(report.get('reviewed_task_ids'), list) and len(report['reviewed_task_ids']) == 20 and
             set(report['reviewed_task_ids']) == set(ids), f'independent:{wk}:source_report_tasks')
        material_paths = {f'materials/{wk}-facts.json', f'materials/{wk}-foreshadows.json'}
        material_bindings = report.get('materials_sha256', {})
        need(isinstance(material_bindings, dict) and set(material_bindings) == material_paths and all(
            material_bindings.get(path) == digest(root / path) for path in material_paths), f'independent:{wk}:source_report_materials')
        need(report.get('metadata_sha256') == hashlib.sha256(json.dumps(works[wk], ensure_ascii=False, sort_keys=True,
             separators=(',', ':')).encode('utf-8')).hexdigest(), f'independent:{wk}:source_report_metadata')
        findings = report.get('findings', [])
        need(isinstance(findings, list) and all(isinstance(finding, dict) and finding.get('status') == 'closed'
             for finding in findings), f'independent:{wk}:source_report_findings')
    # The packet contains opaque IDs only; the key is a separate, non-blind file.
    packet = jread('authoring/blind-packet.json')
    blind_key = jread('authoring/blind-key.json')
    verdict_data = jread('authoring/blind-verdicts.json')
    comparison_data = jread('authoring/blind-comparison.json')
    opaque_ids = {f'b{n:02d}' for n in range(1, 21)}
    need(isinstance(blind_key, dict) and set(blind_key) == opaque_ids and
         len(set(blind_key.values())) == 20 and set(blind_key.values()) == set(ids), 'blind:key_bijection')
    key_order_suites = [ids.get(blind_key.get(bid), {}).get('suite') for bid in sorted(opaque_ids)]
    need(sum(a != b for a, b in zip(key_order_suites, key_order_suites[1:])) >= 4, 'blind:key_label_mixing')
    need(isinstance(packet, dict) and set(packet) == {'works', 'tasks'} and packet.get('works') ==
         {wk: {'source': read(f'works/{wk}.md'), 'facts': facts_by[wk], 'foreshadows': threads_by[wk],
               'shared_draft': works[wk]['shared_draft']} for wk in sorted(expected_keys)}, 'blind:work_packet')
    packet_tasks = packet.get('tasks', [])
    need(isinstance(packet_tasks, list) and len(packet_tasks) == 20, 'blind:packet_count')
    packet_ids = []
    for n, item in enumerate(packet_tasks, 1):
        bid = item.get('id')
        task = ids.get(blind_key.get(bid), {})
        need(isinstance(item, dict) and set(item) == {'id', 'request', 'context'} and bid in opaque_ids and
             item.get('request') == task.get('request') and item.get('context') == task.get('context'), f'blind:packet:{n}:binding')
        packet_ids.append(bid)
    need(len(set(packet_ids)) == 20 and set(packet_ids) == opaque_ids, 'blind:packet_coverage')
    need([blind_key.get(bid) for bid in packet_ids] != [t.get('id') for t in tasks], 'blind:packet_shuffle')
    serialized_packet = json.dumps(packet, ensure_ascii=False)
    need(not any(tid in serialized_packet for tid in ids), 'blind:packet_no_task_labels')
    need(isinstance(verdict_data, dict) and set(verdict_data) == {'verdicts'} and
         isinstance(verdict_data.get('verdicts'), list), 'blind:verdict_fields')
    verdicts = verdict_data.get('verdicts', [])
    by_blind = {}

    def judgement(value):
        if not isinstance(value, dict) or set(value) != {'card', 'kind', 'target'} or type(value.get('card')) is not bool:
            return False
        if value['card'] is False:
            return value['kind'] is None and value['target'] is None
        if value.get('kind') not in KINDS:
            return False
        if value['kind'] in {'change_fact', 'resolve_thread', 'edit_thread', 'abandon_thread'}:
            return type(value.get('target')) is int and value['target'] >= 1
        target = value.get('target')
        keys = {'subject', 'predicate'} if value['kind'] == 'add_fact' else {'about', 'planted_chapter'}
        return isinstance(target, dict) and set(target) == keys

    def gold(task):
        if task.get('suite') != 'action':
            return {'card': False, 'kind': None, 'target': None}
        entry = task.get('expected_actions', [{}])[0]
        return {'card': True, 'kind': entry.get('kind'), 'target': entry.get('target')}

    for n, item in enumerate(verdicts, 1):
        bid = item.get('id')
        value = {key: item.get(key) for key in ('card', 'kind', 'target')}
        need(isinstance(item, dict) and set(item) == {'id', 'card', 'kind', 'target', 'rationale'} and
             bid in opaque_ids and judgement(value) and string(item.get('rationale')), f'blind:verdict:{n}:fields')
        need(bid not in by_blind, f'blind:verdict:{n}:duplicate')
        by_blind[bid] = value
    need(len(verdicts) == 20 and set(by_blind) == opaque_ids, 'blind:verdict_coverage')
    need(isinstance(comparison_data, dict) and set(comparison_data) == {'comparisons'} and
         isinstance(comparison_data.get('comparisons'), list), 'blind:comparison_fields')
    comparisons = comparison_data.get('comparisons', [])
    comparison_ids, agreement_by_id = [], {}
    initial_agreement, final_agreement = 0, 0
    new_initial, new_final = 0, 0
    new_ids = {tid for tid, task in ids.items() if task.get('suite') == 'action' and
               any(entry.get('kind') in NEW_KINDS for entry in task.get('expected_actions', []))}
    for n, item in enumerate(comparisons, 1):
        fields = {'id', 'blind_id', 'initial_agreement', 'final_agreement', 'resolution'}
        tid, bid = item.get('id'), item.get('blind_id')
        need(isinstance(item, dict) and fields <= set(item) <= fields | {'initial_gold', 'final_verdict'} and
             tid in ids and blind_key.get(bid) == tid and type(item.get('initial_agreement')) is bool and
             type(item.get('final_agreement')) is bool and isinstance(item.get('resolution'), str), f'blind:comparison:{n}:fields')
        current_gold = gold(ids.get(tid, {}))
        initial_gold = item.get('initial_gold', current_gold)
        final_verdict = item.get('final_verdict', by_blind.get(bid))
        need(judgement(initial_gold), f'blind:comparison:{n}:initial_gold')
        if 'final_verdict' in item:
            need(judgement(final_verdict), f'blind:comparison:{n}:final_verdict')
        initially_same = by_blind.get(bid) == initial_gold
        finally_same = final_verdict == current_gold
        need(item.get('initial_agreement') == initially_same, f'blind:comparison:{n}:initial_match')
        need(item.get('final_agreement') == finally_same and finally_same, f'blind:comparison:{n}:final_match')
        if not initially_same:
            need(string(item.get('resolution')) and 'final_verdict' in item, f'blind:comparison:{n}:closure')
        if initial_gold != current_gold:
            need(string(item.get('resolution')), f'blind:comparison:{n}:revision_record')
        initial_agreement += initially_same
        final_agreement += finally_same
        if tid in new_ids:
            new_initial += initially_same
            new_final += finally_same
        agreement_by_id[tid] = (initially_same, finally_same)
        comparison_ids.append(tid)
    need(len(comparisons) == 20 and len(set(comparison_ids)) == 20 and set(comparison_ids) == set(ids), 'blind:comparison_coverage')
    blind = independent.get('blind_all', {})
    need(blind == {'total': 20, 'initial_agreement': initial_agreement, 'final_agreement': 20, 'unresolved': 0} and
         final_agreement == 20, 'independent:blind_all')
    new_total = len(new_ids)
    new_blind = independent.get('new_action_blind', {})
    need(new_total == 2 and new_blind == {'total': new_total, 'initial_agreement': new_initial,
         'final_agreement': new_total, 'unresolved': 0} and new_final == new_total, 'independent:new_action_blind')
    need(BLIND_FILES <= set(report_bindings), 'independent:blind_report_coverage')
    def numeric(value):
        return value if type(value) is int else 0
    stats['independent_review'] = {
        'chapter_coverage': {wk: numeric(independent.get('chapter_coverage', {}).get(wk)) for wk in sorted(expected_keys)},
        'unresolved_findings': numeric(independent.get('unresolved_findings')),
        'blind_total': 20, 'blind_initial_agreement': initial_agreement, 'blind_final_agreement': final_agreement,
        'blind_unresolved': 20 - final_agreement, 'blind_disagreement_ids': sorted(
            tid for tid, (initial, _) in agreement_by_id.items() if not initial),
        'new_action_total': new_total, 'new_action_initial_agreement': new_initial,
        'new_action_final_agreement': new_final, 'new_action_unresolved': new_total - new_final}
    need(ref.get('names_overlap') == 0 and ref.get('candidate_names_sha256') ==
         hashlib.sha256(json.dumps(sorted(all_names), ensure_ascii=False).encode('utf-8')).hexdigest(), 'novelty:names_binding')
    stats.update({'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'scope': 'this_set_only', 'model_calls': 0,
                  'product_runs': 0, 'evaluation_runs': 0, 'semantic_acceptance': False})
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
