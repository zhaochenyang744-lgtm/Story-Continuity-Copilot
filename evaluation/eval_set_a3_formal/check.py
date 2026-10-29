"""Standard-library-only, sealed A3 validation. Read only this set; never echo prose."""
from __future__ import annotations
from collections import Counter
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import re
import unicodedata

ROOT = Path(__file__).resolve().parent
SAFETY = False
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
PAGES = {'writing', 'chapters', 'materials', 'plan', 'overview'}
MEMORIES = {'static_canon', 'dynamic_state', 'event_timeline', 'character_knowledge', 'open_thread'}
THREAD_STATES = {'planned', 'planted', 'developing', 'resolved', 'abandoned'}
KINDS = {'add_fact', 'change_fact', 'resolve_thread', 'abandon_thread'}
INJECTION_KINDS = KINDS | {'delete_fact', 'resolve_all', 'skip_asking', 'out_of_plan'}
ROUTES = {'long_task', 'change', 'ask', 'recap', 'check_passage', 'out_of_scope'}
SUITES = {'trace', 'thread_audit', 'tidy', 'ask', 'narrowed', 'route'}
EXCLUDED = ['eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring']


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(s):
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))


def grams(s, names):
    s = ''.join(HAN.findall(s))
    for n in sorted(names, key=len, reverse=True):
        s = s.replace(''.join(HAN.findall(n)), '|')
    return {p[i:i + 8] for p in s.split('|') for i in range(len(p) - 7)}


def chapters(s):
    marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$', s, re.M))
    return {int(m[1]): {'title': m[0][2:], 'body': s[m.end():marks[i + 1].start() if i + 1 < len(marks) else len(s)]}
            for i, m in enumerate(marks)}


def action_key(a):
    return (a.get('kind'), json.dumps(a.get('target'), ensure_ascii=False, sort_keys=True))


def counted(values, permitted):
    c = Counter(values)
    out = {k: c[k] for k in sorted(permitted) if c[k]}
    invalid = sum(v for k, v in c.items() if k not in permitted)
    if invalid:
        out['invalid'] = invalid
    return out


def validate(root=ROOT):
    root = Path(root).resolve()
    errors, stats = [], {'works': {}, 'copy_errors': 0, 'novelty_errors': 0}
    parsed, facts, threads, reviews, positions, refs = {}, {}, {}, {}, {}, {}
    total, keys = (12, {'w01'}) if SAFETY else (30, {'w01', 'w02'})

    def need(ok, code):
        if not ok:
            errors.append(code)
        return bool(ok)

    def string(s, low=1, high=1000000):
        return isinstance(s, str) and low <= len(s) <= high and bool(s.strip())

    def index(i, seq):
        return type(i) is int and 1 <= i <= len(seq)

    def read(rel):
        p = (root / rel).resolve()
        if not p.is_relative_to(root) or not p.is_file():
            raise ValueError('invalid file')
        return p.read_text(encoding='utf-8')

    def jread(rel):
        return json.loads(read(rel))

    def quote(wk, ch, q, label, count=True):
        if isinstance(ch, str):
            found = [n for n, v in parsed[wk].items() if v['title'] == ch]
            ch = found[0] if len(found) == 1 else None
        body = parsed[wk].get(ch, {}).get('body', '') if type(ch) is int else ''
        if need(string(q, 10, 60) and body.count(q) == 1, label + ':quote'):
            pos = len(HAN.findall(body[:body.index(q)])) + 1
            if count:
                positions[wk][(ch, q)] = pos
            return ch, pos
        return None, 0

    def copy_check(wk, s, label):
        if isinstance(s, str) and grams(s, works[wk]['names']) & refs[wk]:
            errors.append(label + ':copy8')
            stats['copy_errors'] += 1

    required = ['README.md', 'tasks.json', 'set.sha256', 'check.py', 'authoring/self-review.md',
                'authoring/self-review.json', 'authoring/novelty-reference.json', 'authoring/independent-review.json']
    for i, p in enumerate(required, 1):
        need((root / p).is_file(), f'structure:{i}:file')
    need(all(not p.is_symlink() for p in root.rglob('*')), 'structure:symlink')
    data, review = jread('tasks.json'), jread('authoring/self-review.json')
    need(set(data) == {'version', 'set_id', 'author', 'works', 'tasks'}, 'top:fields')
    need(data.get('version') == 'a3-1' and data.get('set_id') == ('a3s-formal' if SAFETY else 'a3-formal')
         and data.get('author') == 'evaluation authoring', 'top:values')
    works = {w.get('key'): w for w in data['works']}
    need(set(works) == keys and len(data['works']) == len(keys), 'works:keys')
    need(set(review.get('works', {})) == keys, 'review:works')
    paths = sorted(['tasks.json'] + [f'works/{k}.md' for k in keys] +
                   [f'materials/{k}-{t}.json' for k in keys for t in ('facts', 'foreshadows')])
    actual = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for d in ('works', 'materials')
                                    for p in (root / d).rglob('*') if p.is_file()])
    need(actual == paths, 'structure:data_paths')
    manifest = []
    for i, line in enumerate(read('set.sha256').splitlines(), 1):
        m = re.fullmatch(r'([0-9a-f]{64})  ([a-zA-Z0-9_./-]+)', line)
        if not need(bool(m), f'manifest:{i}:format'):
            continue
        h, p = m.groups()
        resolved = (root / p).resolve()
        safe = resolved.is_relative_to(root) and '..' not in Path(p).parts and resolved.is_file()
        need(safe, f'manifest:{i}:path')
        if safe:
            need(digest(resolved) == h, f'manifest:{i}:hash')
        manifest.append(p)
    need(manifest == paths, 'manifest:coverage')
    all_names = []
    for wk in sorted(keys):
        w, wr = works[wk], review['works'][wk]
        need(set(w) == {'key', 'title', 'language', 'source_file', 'purpose', 'kind', 'names', 'materials', 'shared_draft'}, wk + ':fields')
        need(string(w.get('title')) and w.get('language') == 'zh' and w.get('purpose') == 'general' and w.get('kind') == 'long', wk + ':values')
        need(w.get('source_file') == f'works/{wk}.md' and w.get('materials') ==
             {'facts': f'materials/{wk}-facts.json', 'foreshadows': f'materials/{wk}-foreshadows.json'}, wk + ':paths')
        source = read(f'works/{wk}.md')
        chs = parsed[wk] = chapters(source)
        positions[wk] = {}
        need(list(chs) == list(range(1, total + 1)) and len(re.findall(r'^# ', source, re.M)) == total, wk + ':chapters')
        need(len({c['title'] for c in chs.values()}) == total, wk + ':titles')
        lengths = [len(HAN.findall(c['body'])) for c in chs.values()]
        for n, c in chs.items():
            need(2500 <= len(HAN.findall(c['body'])) <= 3500, f'{wk}:chapter:{n}:length')
        draft = w.get('shared_draft', {})
        need(set(draft) == {'chapter_title', 'body'} and
             bool(re.fullmatch(r'第' + str(total + 1) + r'章 [^\n]+', draft.get('chapter_title', ''))) and
             600 <= len(HAN.findall(draft.get('body', ''))) <= 1000, wk + ':draft')
        names = w.get('names', [])
        need(isinstance(names, list) and len(set(names)) == len(names) and all(string(n, 2, 30) for n in names), wk + ':names')
        need(all(n in source + draft.get('body', '') for n in names), wk + ':name_presence')
        all_names.extend(names)
        refs[wk] = set().union(*(grams(c['body'], names) for c in chs.values()))
        fs, ts = facts[wk], threads[wk] = jread(f'materials/{wk}-facts.json'), jread(f'materials/{wk}-foreshadows.json')
        reviews[wk] = wr
        need((20 if SAFETY else 30) <= len(fs) <= (35 if SAFETY else 45), wk + ':facts:count')
        need((6 if SAFETY else 9) <= len(ts) <= (10 if SAFETY else 14), wk + ':threads:count')
        for i, f in enumerate(fs, 1):
            need(set(f) == {'memory_type', 'subject', 'predicate', 'value', 'chapter'} and f.get('memory_type') in MEMORIES
                 and all(string(f.get(k), 1, 600) for k in ('subject', 'predicate', 'value'))
                 and type(f.get('chapter')) is int and f['chapter'] in chs, f'{wk}:fact:{i}:values')
        need(len({(f['subject'], f['predicate']) for f in fs}) == len(fs), wk + ':facts:duplicates')
        initial_support = wr.get('initial_fact_support', [])
        need(len(initial_support) == len(fs) and {e.get('fact') for e in initial_support} == set(range(1, len(fs) + 1)),
             wk + ':facts:support_coverage')
        for i, e in enumerate(initial_support, 1):
            need(set(e) == {'fact', 'chapter', 'quote'} and index(e.get('fact'), fs), f'{wk}:fact_support:{i}:fields')
            if index(e.get('fact'), fs):
                need(e.get('chapter') == fs[e['fact'] - 1]['chapter'], f'{wk}:fact_support:{i}:chapter')
            quote(wk, e.get('chapter'), e.get('quote'), f'{wk}:fact_support:{i}', count=False)
        for i, t in enumerate(ts, 1):
            need({'title', 'description', 'status', 'planted_chapter'} <= set(t) <=
                 {'title', 'description', 'status', 'planted_chapter', 'resolved_chapter'} and t.get('status') in THREAD_STATES
                 and string(t.get('title'), 1, 60) and string(t.get('description'), 1, 600)
                 and type(t.get('planted_chapter')) is int and t['planted_chapter'] in chs, f'{wk}:thread:{i}:values')
            if 'resolved_chapter' in t:
                need(type(t['resolved_chapter']) is int and t['planted_chapter'] <= t['resolved_chapter'] <= total
                     and t['status'] == 'resolved', f'{wk}:thread:{i}:resolved')
            if t['status'] == 'resolved':
                need('resolved_chapter' in t, f'{wk}:thread:{i}:resolved_required')
        chars, aliases = wr.get('characters', []), wr.get('aliases', [])
        need(len(set(chars)) >= 10 and all(n in names and n in source for n in chars), wk + ':characters')
        need(len({a.get('name') for a in aliases}) >= 3, wk + ':aliases')
        for i, a in enumerate(aliases, 1):
            need(set(a) == {'name', 'alias', 'chapter', 'quote'} and a.get('name') in chars and
                 a.get('alias') in names and a['alias'] != a['name'], f'{wk}:alias:{i}:fields')
            quote(wk, a.get('chapter'), a.get('quote'), f'{wk}:alias:{i}')
        core = {'trace_objects', 'resolved_unmarked', 'still_open', 'abandoned_in_text', 'stale_facts',
                'missing_facts', 'decoys', 'decision_points', 'same_input_groups'}
        need(core <= set(wr), wk + ':review:fields')
        tr = wr.get('trace_objects', [])
        need(len(tr) == (1 if SAFETY else 3), wk + ':trace:count')
        contradiction_quotes = set()
        for i, ob in enumerate(tr, 1):
            lab = f'{wk}:trace:{i}'
            need(set(ob) == {'name', 'states', 'contradictions'} and ob.get('name') in names, lab + ':fields')
            ss, cc = ob.get('states', []), ob.get('contradictions', [])
            need((4 if SAFETY else 5) <= len(ss) <= (6 if SAFETY else 9), lab + ':states')
            ns = [s.get('chapter') for s in ss]
            need(all(type(n) is int and n in chs for n in ns) and ns == sorted(set(ns)), lab + ':chronology')
            need(SAFETY or (max(ns) - min(ns) >= 15), lab + ':span')
            need(0 <= len(cc) <= 2 if SAFETY else 1 <= len(cc) <= 2, lab + ':contradictions')
            for j, s in enumerate(ss, 1):
                need(set(s) == {'chapter', 'state', 'quote'} and string(s.get('state'), 1, 30), f'{lab}:state:{j}:fields')
                need(ob['name'] in s.get('quote', ''), f'{lab}:state:{j}:object')
                quote(wk, s.get('chapter'), s.get('quote'), f'{lab}:state:{j}')
            for j, c in enumerate(cc, 1):
                need(set(c) == {'a', 'b', 'what'} and string(c.get('what'), 1, 40), f'{lab}:contradiction:{j}:fields')
                for side in ('a', 'b'):
                    e = c.get(side, {})
                    need(set(e) == {'chapter', 'quote'}, f'{lab}:contradiction:{j}:{side}:fields')
                    quote(wk, e.get('chapter'), e.get('quote'), f'{lab}:contradiction:{j}:{side}')
                    contradiction_quotes.add((e.get('chapter'), e.get('quote')))
                need(c['a']['chapter'] < c['b']['chapter'] and c['a']['quote'] != c['b']['quote'], f'{lab}:contradiction:{j}:distinct')
        minima = {'resolved_unmarked': 2 if SAFETY else 3, 'still_open': 0 if SAFETY else 4,
                  'abandoned_in_text': 0 if SAFETY else 1, 'stale_facts': 2 if SAFETY else 3,
                  'missing_facts': 3 if SAFETY else 6, 'decoys': 0 if SAFETY else 3}
        thread_groups = []
        for field, minimum in minima.items():
            entries = wr.get(field, [])
            need(isinstance(entries, list) and len(entries) >= minimum, f'{wk}:{field}:count')
            if field == 'abandoned_in_text' and not SAFETY:
                need(len(entries) == 1, wk + ':abandoned_in_text:exact')
            identities = []
            for i, e in enumerate(entries, 1):
                lab = f'{wk}:{field}:{i}'
                if field in {'resolved_unmarked', 'abandoned_in_text', 'still_open'}:
                    expected = {'foreshadow'} | (set() if field == 'still_open' else {'chapter', 'quote'})
                    need(set(e) == expected and index(e.get('foreshadow'), ts), lab + ':fields')
                    identities.append(e.get('foreshadow'))
                    if index(e.get('foreshadow'), ts):
                        t = ts[e['foreshadow'] - 1]
                        need(t['status'] in {'planted', 'developing'}, lab + ':state')
                        if field != 'still_open':
                            need(type(e.get('chapter')) is int and t['planted_chapter'] <= e['chapter'] <= total, lab + ':chronology')
                elif field in {'stale_facts', 'decoys'}:
                    expected = {'fact', 'quote', 'changed_chapter' if field == 'stale_facts' else 'chapter'}
                    need(set(e) == expected and index(e.get('fact'), fs), lab + ':fields')
                    identities.append(e.get('fact'))
                    if field == 'stale_facts' and index(e.get('fact'), fs):
                        need(type(e.get('changed_chapter')) is int and e['changed_chapter'] > fs[e['fact'] - 1]['chapter'], lab + ':chronology')
                else:
                    need(set(e) == {'subject', 'predicate', 'chapter', 'quote'} and string(e.get('subject')) and string(e.get('predicate')),
                         lab + ':fields')
                    ident = (e.get('subject'), e.get('predicate'))
                    identities.append(ident)
                    need(ident not in {(f['subject'], f['predicate']) for f in fs}, lab + ':missing')
                if field != 'still_open':
                    quote(wk, e.get('changed_chapter', e.get('chapter')), e.get('quote'), lab)
            need(len(set(identities)) == len(identities), f'{wk}:{field}:duplicates')
            if field in {'resolved_unmarked', 'abandoned_in_text', 'still_open'}:
                thread_groups.append(set(identities))
        if not SAFETY:
            updates = wr.get('fact_updates', [])
            stale = {e['fact']: e for e in wr['stale_facts']}
            need(isinstance(updates, list) and len(updates) >= len(stale), wk + ':fact_updates:count')
            pairs = []
            for i, e in enumerate(updates, 1):
                lab = f'{wk}:fact_update:{i}'
                need(set(e) == {'fact', 'changed_chapter', 'quote', 'after_points'} and e.get('fact') in stale,
                     lab + ':fields')
                fact, ch = e['fact'], e['changed_chapter']
                need(type(ch) is int and stale[fact]['changed_chapter'] <= ch <= total, lab + ':chronology')
                pairs.append((fact, ch))
                quote(wk, ch, e['quote'], lab)
                ps = e.get('after_points')
                need(isinstance(ps, list) and 1 <= len(ps) <= 3 and all(string(x, 1, 60) for x in ps), lab + ':points')
                for j, point in enumerate(ps, 1):
                    copy_check(wk, point, f'{lab}:point:{j}')
            need(pairs == sorted(set(pairs)), wk + ':fact_updates:order')
            for fact, first in stale.items():
                es = [e for e in updates if e['fact'] == fact]
                need(bool(es) and es[0]['changed_chapter'] == first['changed_chapter'] and es[0]['quote'] == first['quote'],
                     f'{wk}:fact_updates:{fact}:first')
        need(sum(len(g) for g in thread_groups) == len(set().union(*thread_groups)), wk + ':threads:partition')
        need(not ({e['fact'] for e in wr['decoys']} & {e['fact'] for e in wr['stale_facts']}), wk + ':decoys:stale_overlap')
        ds = wr.get('decision_points', [])
        need(len(ds) == (1 if SAFETY else 2), wk + ':decision:count')
        decisions_seen = set()
        for i, d in enumerate(ds, 1):
            need(set(d) == {'a', 'b', 'question'} and string(d.get('question'), 1, 40), f'{wk}:decision:{i}:fields')
            for side in ('a', 'b'):
                e = d.get(side, {})
                need(set(e) == {'chapter', 'quote'}, f'{wk}:decision:{i}:{side}:fields')
                quote(wk, e.get('chapter'), e.get('quote'), f'{wk}:decision:{i}:{side}')
                key = (e.get('chapter'), e.get('quote'))
                need(key not in contradiction_quotes and key not in decisions_seen, f'{wk}:decision:{i}:{side}:overlap')
                decisions_seen.add(key)
            need(d['a']['chapter'] < d['b']['chapter'] and d['a']['quote'] != d['b']['quote'], f'{wk}:decision:{i}:distinct')
        stats['works'][wk] = {'chapters': len(chs), 'chapter_han_min': min(lengths), 'chapter_han_max': max(lengths),
                              'total_han': sum(lengths), 'draft_han': len(HAN.findall(draft['body'])), 'characters': len(chars),
                              'aliases': len(aliases), 'names': len(names), 'facts': len(fs), 'foreshadows': len(ts),
                              'foreshadow_states': counted([t['status'] for t in ts], THREAD_STATES),
                              'trace_objects': len(tr), 'trace_states': sum(len(o['states']) for o in tr),
                              'contradictions': sum(len(o['contradictions']) for o in tr), 'decision_points': len(ds),
                              'fact_updates': len(wr.get('fact_updates', [])),
                              **{k: len(wr[k]) for k in minima}}
    need(len(all_names) == len(set(all_names)), 'names:works_overlap')
    novelty = jread('authoring/novelty-reference.json')
    old = novelty.get('normalized_inputs', [])
    need(isinstance(old, list) and bool(old) and all(string(s) and s == normalize(s) for s in old), 'novelty:reference')
    need(novelty.get('excluded_directories') == EXCLUDED and novelty.get('names_overlap') == 0, 'novelty:scope')
    need(novelty.get('candidate_names_sha256') == hashlib.sha256(json.dumps(sorted(all_names), ensure_ascii=False).encode()).hexdigest(), 'novelty:names_binding')
    sources, hashes = novelty.get('source_hashes', {}), novelty.get('names_corpus_sha256', {})
    grouped = novelty.get('normalized_inputs_by_source', {})
    need(bool(sources) and bool(hashes) and all(re.fullmatch('[0-9a-f]{64}', h) for h in list(sources.values()) + list(hashes.values())), 'novelty:hashes')
    need(set(grouped) == set(sources) and all(isinstance(vs, list) and vs == sorted(set(vs)) for vs in grouped.values())
         and sorted({s for vs in grouped.values() for s in vs}) == old, 'novelty:provenance')
    need(novelty.get('reference_counts') == {'source_files': len(sources), 'normalized_inputs': len(old), 'names_text_files': len(hashes)},
         'novelty:reference_counts')
    need(all(not any(banned in p.split('/') for banned in EXCLUDED) for p in list(sources) + list(hashes)), 'novelty:excluded_paths')
    stats['novelty_reference_inputs'] = len(old)
    tasks = data.get('tasks', [])
    need(isinstance(tasks, list) and len(tasks) == (10 if SAFETY else 42), 'tasks:count')
    ids = {}
    prefix = 'a3s-' if SAFETY else 'a3f-'
    for i, t in enumerate(tasks, 1):
        tid = t.get('id')
        valid = isinstance(tid, str) and bool(re.fullmatch(prefix + r'w0[12]-(?:trace|thread-audit|tidy|ask|narrowed|route|injection)-[0-9]{2}', tid))
        need(valid and tid not in ids, f'task:{i}:id')
        if valid:
            ids[tid] = t

    def in_scope(ch, bounds):
        return type(ch) is int and bounds[0] <= ch <= bounds[1]

    def registered(wk, kind):
        wr = reviews[wk]
        field = {'add_fact': 'missing_facts', 'change_fact': 'stale_facts', 'resolve_thread': 'resolved_unmarked', 'abandon_thread': 'abandoned_in_text'}[kind]
        found = []
        for e in (wr.get('fact_updates', wr[field]) if kind == 'change_fact' else wr[field]):
            target = {'subject': e['subject'], 'predicate': e['predicate']} if kind == 'add_fact' else e['fact' if kind == 'change_fact' else 'foreshadow']
            found.append((action_key({'kind': kind, 'target': target}), e.get('changed_chapter', e.get('chapter')), e['quote']))
        return found

    def required_actions(wk, run, bounds):
        kinds = {'thread_audit': ['resolve_thread', 'abandon_thread'], 'tidy': ['add_fact', 'change_fact'], 'trace': []}[run]
        return {k for kind in kinds for k, n, q in registered(wk, kind) if in_scope(n, bounds)}

    def action(wk, a, bounds, label, decision=None):
        need(set(a) == {'kind', 'target', 'after_points', 'evidence_chapters', 'evidence_quotes'}, label + ':fields')
        kind, target = a.get('kind'), a.get('target')
        need(kind in KINDS, label + ':kind')
        if kind == 'add_fact':
            need(isinstance(target, dict) and set(target) == {'subject', 'predicate'} and all(string(target.get(k)) for k in ('subject', 'predicate')), label + ':target')
        elif kind == 'change_fact':
            need(index(target, facts[wk]), label + ':target')
        else:
            need(index(target, threads[wk]), label + ':target')
        points, cs, qs = a.get('after_points'), a.get('evidence_chapters'), a.get('evidence_quotes')
        need(isinstance(points, list) and 1 <= len(points) <= 3 and all(string(p, 1, 60) for p in points), label + ':points')
        for i, p in enumerate(points, 1):
            copy_check(wk, p, f'{label}:point:{i}')
        need(isinstance(cs, list) and isinstance(qs, list) and len(cs) == len(qs) > 0 and all(isinstance(c, str) for c in cs), label + ':evidence')
        evidence = set()
        for i, (c, q) in enumerate(zip(cs, qs), 1):
            n, p = quote(wk, c, q, f'{label}:evidence:{i}')
            need(in_scope(n, bounds), f'{label}:evidence:{i}:scope')
            evidence.add((n, q))
        key = action_key(a)
        proof = [(n, q) for k, n, q in registered(wk, kind) if k == key] if kind in KINDS else []
        if decision:
            need(a in decision['actions'], label + ':decision_binding')
            selected = decision['point'][decision['chosen']]
            need((selected['chapter'], selected['quote']) in evidence, label + ':decision_selected_evidence')
        else:
            need(bool(proof) and any((n, q) in evidence and in_scope(n, bounds) for n, q in proof), label + ':point_binding')
            if kind == 'change_fact' and 'fact_updates' in reviews[wk]:
                eligible = [e for e in reviews[wk]['fact_updates'] if e['fact'] == target and in_scope(e['changed_chapter'], bounds)]
                latest = max(eligible, key=lambda e: e['changed_chapter']) if eligible else None
                need(latest is not None and (latest['changed_chapter'], latest['quote']) in evidence,
                     label + ':latest_update_evidence')
                need(latest is not None and points == latest['after_points'], label + ':latest_update_points')
        return key

    inputs, injection_positions = [], []
    for i, t in enumerate(tasks, 1):
        tid = t.get('id') if t.get('id') in ids else f'task:{i}'
        wk, suite = t.get('work'), t.get('suite')
        if not need(wk in keys, tid + ':work'):
            continue
        need(tid.startswith(prefix + wk + '-'), tid + ':id_work')
        need(suite in ({'injection'} if SAFETY else SUITES), tid + ':suite')
        need(string(t.get('why')), tid + ':why')
        ctx = t.get('context', {})
        need(isinstance(ctx, dict) and set(ctx) <= {'page', 'chapter_number', 'selection'} and ctx.get('page') in PAGES, tid + ':context')
        if 'chapter_number' in ctx:
            need(type(ctx['chapter_number']) is int and 1 <= ctx['chapter_number'] <= total + 1, tid + ':context_chapter')
        if 'selection' in ctx:
            sel = ctx['selection']; body = works[wk]['shared_draft']['body']
            need(ctx.get('page') == 'writing' and string(sel, 1, 80) and body.count(sel) == 1 and sel.rstrip('”’').endswith(('。', '！', '？')), tid + ':selection')
        field = 'input' if suite == 'route' else 'request'
        s = t.get(field)
        need(string(s, 4 if suite == 'route' else 8, 60 if suite == 'route' else 100), tid + ':input')
        copy_check(wk, s, tid + ':input')
        if isinstance(s, str):
            val = normalize(s)
            novel = all(val != p and SequenceMatcher(None, val, p, autojunk=False).ratio() < .8 for p in old)
            need(novel, tid + ':novelty')
            stats['novelty_errors'] += int(not novel)
            inputs.append((tid, val))
        base = {'id', 'suite', 'work', field, 'context', 'why'}
        if suite == 'route':
            need(base | {'expected_route'} <= set(t) <= base | {'expected_route', 'also_acceptable'}, tid + ':fields')
            need(t.get('expected_route') in ROUTES, tid + ':route')
            if t.get('expected_route') == 'check_passage':
                need(bool(ctx.get('selection')), tid + ':check_selection')
            if 'also_acceptable' in t:
                alt = t['also_acceptable']
                need(isinstance(alt, list) and len(alt) == 1 and alt[0] in ROUTES and alt[0] != t['expected_route'], tid + ':acceptable')
            continue
        need('scope' in t and 'author_replies' in t, tid + ':long_fields')
        scope = t.get('scope')
        bounds = [1, total] if scope is None else scope
        need(isinstance(bounds, list) and len(bounds) == 2 and all(type(n) is int for n in bounds) and 1 <= bounds[0] <= bounds[1] <= total, tid + ':scope')
        replies = t.get('author_replies', {})
        need(isinstance(replies, dict) and set(replies) <= {'decision'} and all(string(v, 1, 40) for v in replies.values()), tid + ':replies')
        extras = {'scope', 'author_replies'}
        run = suite
        if suite == 'narrowed':
            pe = t.get('plan_edit', {})
            need(scope is None and set(pe) == {'chapters'}, tid + ':plan_edit')
            bounds = pe.get('chapters')
            need(isinstance(bounds, list) and len(bounds) == 2 and all(type(n) is int for n in bounds) and
                 1 <= bounds[0] <= bounds[1] <= total and bounds != [1, total], tid + ':narrow_scope')
            run = reviews[wk].get('run_suites', {}).get(tid)
            need(run in {'trace', 'thread_audit', 'tidy'}, tid + ':run_suite')
            extras |= {'plan_edit', 'expected_actions', 'allowed_actions'}
        elif suite == 'trace':
            extras |= {'trace_object', 'allowed_actions'}
            need(index(t.get('trace_object'), reviews[wk]['trace_objects']), tid + ':trace_object')
        elif suite == 'injection':
            extras |= {'run_suite', 'injection', 'injection_target', 'allowed_actions'}
            run = t.get('run_suite')
            need(run in {'trace', 'thread_audit', 'tidy'}, tid + ':run_suite')
        else:
            extras |= {'expected_actions'}
        decision = t.get('decision_point')
        if suite == 'ask' or decision is not None:
            extras |= {'decision_point'}
            need(index(decision, reviews[wk]['decision_points']) and string(replies.get('decision'), 1, 40), tid + ':decision')
            if index(decision, reviews[wk]['decision_points']):
                dp = reviews[wk]['decision_points'][decision - 1]
                need(all(in_scope(dp[k]['chapter'], bounds) for k in ('a', 'b')), tid + ':decision_scope')
                need(sum(all(in_scope(d[k]['chapter'], bounds) for k in ('a', 'b')) for d in reviews[wk]['decision_points']) == 1,
                     tid + ':decision_exactly_one')
                record = reviews[wk].get('decision_answers', {}).get(str(decision), {})
                need(replies.get('decision') == record.get('reply') and record.get('chosen') in {'a', 'b'}, tid + ':decision_answer')
        need(set(t) == base | extras, tid + ':fields')
        actual_keys = []
        for field_a in ('expected_actions', 'allowed_actions'):
            if field_a not in t:
                continue
            aa = t[field_a]
            need(isinstance(aa, list), tid + ':' + field_a + ':array')
            for j, a in enumerate(aa, 1):
                decision_aa = None
                if decision is not None:
                    record = reviews[wk].get('decision_answers', {}).get(str(decision), {})
                    if a in record.get('actions', []):
                        decision_aa = {**record, 'point': reviews[wk]['decision_points'][decision - 1]}
                actual_keys.append(action(wk, a, bounds, f'{tid}:{field_a}:{j}', decision_aa))
        need(len(actual_keys) == len(set(actual_keys)), tid + ':actions_duplicate')
        if run in {'thread_audit', 'tidy'}:
            expected = required_actions(wk, run, bounds)
            if decision is not None:
                expected |= {action_key(a) for a in reviews[wk]['decision_answers'][str(decision)]['actions']}
            required_field = 'allowed_actions' if suite == 'injection' else 'expected_actions'
            actual_required = [action_key(a) for a in t.get(required_field, [])]
            need(len(actual_required) == len(set(actual_required)) and set(actual_required) == expected, tid + ':actions_complete')
        if suite == 'ask':
            need(t.get('expected_actions') == reviews[wk]['decision_answers'][str(decision)]['actions'], tid + ':ask_actions')
        if suite == 'injection':
            inj, target = t.get('injection', {}), t.get('injection_target', {})
            loc, text = inj.get('location', {}), inj.get('text')
            need(set(inj) == {'text', 'location'} and string(text) and set(target) == {'kind', 'target'}, tid + ':injection_fields')
            lk = loc.get('kind')
            need(lk in {'chapter', 'chapter_title', 'fact', 'foreshadow'}, tid + ':location_kind')
            container = ''
            if lk in {'chapter', 'chapter_title'}:
                n = loc.get('chapter')
                need(set(loc) == {'kind', 'chapter'} and type(n) is int and n in parsed[wk] and in_scope(n, bounds), tid + ':location')
                c = parsed[wk].get(n, {})
                container = c.get('body' if lk == 'chapter' else 'title', '')
                if lk == 'chapter' and isinstance(text, str) and text in container:
                    injection_positions.append({'id': tid, 'chapter': n, 'han_position': len(HAN.findall(container[:container.index(text)])) + 1})
            elif lk in {'fact', 'foreshadow'}:
                seq = facts[wk] if lk == 'fact' else threads[wk]
                n = loc.get('index')
                need(set(loc) == {'kind', 'index'} and index(n, seq), tid + ':location')
                if index(n, seq):
                    entry = seq[n - 1]
                    container = entry['value' if lk == 'fact' else 'description']
                    need(in_scope(entry['chapter' if lk == 'fact' else 'planted_chapter'], bounds), tid + ':location_scope')
            need(isinstance(text, str) and container.count(text) == 1, tid + ':injection_quote')
            kind, obj = target.get('kind'), target.get('target')
            need(kind in INJECTION_KINDS, tid + ':target_kind')
            if kind in {'resolve_all', 'skip_asking'}:
                need(obj is None, tid + ':target_null')
            elif kind in {'change_fact', 'delete_fact'}:
                need(index(obj, facts[wk]), tid + ':target_index')
            elif kind in {'resolve_thread', 'abandon_thread'}:
                need(index(obj, threads[wk]), tid + ':target_index')
            elif kind == 'add_fact':
                need(isinstance(obj, dict) and set(obj) == {'subject', 'predicate'} and all(string(obj.get(k)) for k in obj), tid + ':target_object')
            elif kind == 'out_of_plan':
                if isinstance(obj, list):
                    need(len(obj) == 2 and all(type(n) is int for n in obj) and 1 <= obj[0] <= obj[1] <= total
                         and (obj[1] < bounds[0] or obj[0] > bounds[1]), tid + ':target_outside')
                else:
                    valid_index = index(obj, facts[wk])
                    relevant_change = any(e['fact'] == obj and in_scope(e['changed_chapter'], bounds) for e in reviews[wk]['stale_facts'])
                    need(valid_index and not in_scope(facts[wk][obj - 1]['chapter'], bounds) and not relevant_change,
                         tid + ':target_outside')
            need(not any(action_key(a) == action_key(target) for a in t['allowed_actions']), tid + ':injection_collision')
            for a in t['allowed_actions']:
                same_fact = (kind in {'delete_fact', 'change_fact'} or kind == 'out_of_plan' and type(obj) is int) and a['kind'] == 'change_fact' and a['target'] == obj
                same_thread = kind in {'resolve_thread', 'abandon_thread'} and a['kind'] in {'resolve_thread', 'abandon_thread'} and a['target'] == obj
                need(not same_fact and not same_thread, tid + ':injection_object_collision')
            need(kind != 'skip_asking' or decision is not None, tid + ':skip_decision')
    same_groups = {frozenset(g) for wr in reviews.values() for g in wr.get('same_input_groups', [])}
    for i, (tid, val) in enumerate(inputs):
        for oid, other in inputs[:i]:
            if frozenset((tid, oid)) in same_groups:
                continue
            ok = val != other and SequenceMatcher(None, val, other, autojunk=False).ratio() < .8
            need(ok, tid + ':internal_novelty')
            stats['novelty_errors'] += int(not ok)
    for wk in sorted(keys):
        own = [t for t in tasks if t.get('work') == wk]
        wr, st = reviews[wk], stats['works'][wk]
        if not SAFETY:
            dist = Counter(t.get('suite') for t in own)
            need(dist == {'trace': 3, 'thread_audit': 2, 'tidy': 2, 'ask': 2, 'narrowed': 2, 'route': 10}, wk + ':suite_distribution')
            long = [t for t in own if t['suite'] != 'route']
            route = [t for t in own if t['suite'] == 'route']
            rd = Counter(t.get('expected_route') for t in route)
            need(rd['long_task'] == 4 and rd['change'] == 2 and rd['ask'] == 2 and sum(rd[k] for k in {'recap', 'check_passage', 'out_of_scope'}) == 2,
                 wk + ':route_distribution')
            need(sum(t.get('scope') is not None for t in long) >= 4 and sum(t.get('scope') is None for t in long) >= 3, wk + ':scope_distribution')
            need(sum(not any(s in t['request'] for s in ('清点', '梳理', '整理')) for t in long) * 2 >= len(long), wk + ':colloquial')
            need(sum(t['expected_route'] == 'long_task' and not any(s in t['input'] for s in ('清点', '梳理', '整理')) for t in route) >= 2,
                 wk + ':route_colloquial')
            need(len([t for t in route if 'also_acceptable' in t]) <= 2, wk + ':acceptable_count')
            need({t.get('trace_object') for t in own if t['suite'] == 'trace'} == {1, 2, 3}, wk + ':trace_coverage')
            groups = wr.get('same_input_groups', [])
            need(len(groups) >= 1, wk + ':same_input_count')
            for i, g in enumerate(groups, 1):
                pair = [ids.get(x, {}) for x in g]
                need(len(g) == 2 and len(set(g)) == 2 and all(t.get('suite') == 'route' and t.get('work') == wk for t in pair)
                     and len({t.get('input') for t in pair}) == 1 and len({t.get('expected_route') for t in pair}) == 2
                     and len({json.dumps(t.get('context'), sort_keys=True) for t in pair}) == 2, f'{wk}:same_input:{i}')
            st.update({'suites': counted([t['suite'] for t in own], SUITES), 'scope_given': sum(t['scope'] is not None for t in long),
                       'scope_all': sum(t['scope'] is None for t in long), 'routes': counted([t['expected_route'] for t in route], ROUTES),
                       'same_input_groups': len(groups), 'expected_action_kinds': counted([a['kind'] for t in own for a in t.get('expected_actions', [])], KINDS)})
        ps = list(positions[wk].values())
        need(bool(ps) and sum(p > 1500 for p in ps) * 2 >= len(ps), wk + ':points_after1500')
        need(bool(ps) and sum(p > 2500 for p in ps) * 3 >= len(ps), wk + ':points_after2500')
        st.update({'point_quotes': len(ps), 'point_after1500': sum(p > 1500 for p in ps), 'point_after2500': sum(p > 2500 for p in ps),
                   'point_han_min': min(ps) if ps else 0, 'point_han_max': max(ps) if ps else 0,
                   'point_position_buckets': {'1_1500': sum(p <= 1500 for p in ps), '1501_2500': sum(1500 < p <= 2500 for p in ps), '2501_plus': sum(p > 2500 for p in ps)}})
    if SAFETY:
        locs = Counter(t['injection']['location']['kind'] for t in tasks)
        kinds = Counter(t['injection_target']['kind'] for t in tasks)
        need(locs['chapter'] >= 5 and locs['fact'] + locs['foreshadow'] >= 3 and locs['chapter_title'] >= 1, 'injection:locations')
        need(all(kinds[k] >= 1 for k in INJECTION_KINDS), 'injection:all_kinds')
        need(sum(('摘要' in t['injection']['text'] or '压缩' in t['injection']['text']) for t in tasks) >= 2, 'injection:compaction')
        need(len(injection_positions) == locs['chapter'] and sum(p['han_position'] > 1500 for p in injection_positions) * 2 >= locs['chapter'], 'injection:depth')
        stats.update({'injection_locations': counted([t['injection']['location']['kind'] for t in tasks], {'chapter', 'chapter_title', 'fact', 'foreshadow'}),
                      'run_suites': counted([t['run_suite'] for t in tasks], {'trace', 'thread_audit', 'tidy'}),
                      'injection_targets': counted([t['injection_target']['kind'] for t in tasks], INJECTION_KINDS),
                      'chapter_injection_positions': injection_positions})
    independent = jread('authoring/independent-review.json')
    need(independent.get('status') == 'completed' and independent.get('unresolved_findings') == 0 and
         independent.get('chapter_coverage') == {wk: total for wk in sorted(keys)}, 'independent:completion')
    bindings = independent.get('sha256', {})
    need(set(bindings) == set(paths) and all(bindings.get(p) == digest(root / p) for p in paths), 'independent:data_binding')
    bound = {'authoring/self-review.json', 'authoring/self-review.md', 'authoring/novelty-reference.json'}
    ab = independent.get('authoring_sha256', {})
    need(set(ab) == bound and all(ab.get(p) == digest(root / p) for p in bound), 'independent:authoring_binding')
    if not SAFETY:
        blind = independent.get('blind_route', {})
        need(blind.get('total') == 20 and blind.get('final_agreement') == 20 and blind.get('unresolved') == 0, 'independent:route')
    stats.update({'tasks': len(tasks), 'status': 'FAIL' if errors else 'PASS', 'errors': errors, 'scope': 'this_set_only',
                  'model_calls': 0, 'product_runs': 0, 'evaluation_runs': 0, 'semantic_acceptance': False})
    return stats


def main():
    try:
        result = validate()
    except Exception:
        result = {'status': 'FAIL', 'errors': ['structure:unreadable_or_invalid'], 'scope': 'this_set_only', 'model_calls': 0}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return int(result['status'] != 'PASS')


if __name__ == '__main__':
    raise SystemExit(main())
