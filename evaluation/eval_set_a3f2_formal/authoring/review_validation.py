"""Read-only validation of actual first/final independent records; no product imports."""
import hashlib
import json
from pathlib import Path
import re


def verify_review_records(root, data, gold, summary=None):
    root = Path(root).resolve()
    errors, required = [], set()
    full_coverage, final_votes, initial_threads = {}, {}, {}
    thread_total = first_agreement = final_agreement = 0
    work_stats = {}
    routes = {'long_task', 'change', 'ask', 'recap', 'check_passage', 'out_of_scope'}

    def need(ok, code):
        if not ok:
            errors.append('independent:' + code)
        return bool(ok)

    def digest(p):
        return hashlib.sha256(p.read_bytes()).hexdigest()

    def is_hash(value):
        return isinstance(value, str) and re.fullmatch(r'[0-9a-f]{64}', value) is not None

    def local(rel):
        if not isinstance(rel, str):
            return None
        p = (root / rel).resolve()
        return p if p.is_relative_to(root) and '..' not in Path(rel).parts else None

    def read(rel, label, expected=dict, raw=True):
        if raw and isinstance(rel, str):
            required.add(rel)
        p = local(rel)
        if not need(p is not None and p.is_file(), label + ':file'):
            return {} if expected is dict else []
        try:
            result = json.loads(p.read_text(encoding='utf-8'))
        except Exception:
            need(False, label + ':json')
            return {} if expected is dict else []
        if not need(isinstance(result, expected), label + ':type'):
            return {} if expected is dict else []
        return result

    def bodies(text):
        marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 [^\r\n]+$', text, re.M))
        return {int(m[1]): text[m.end():marks[i+1].start() if i+1 < len(marks) else len(text)]
                for i, m in enumerate(marks)}

    def source_hashes(value):
        out = set()
        if isinstance(value, dict):
            for k, v in value.items():
                if k == 'source_sha256' and is_hash(v):
                    out.add(v)
                elif isinstance(v, (dict, list)):
                    out.update(source_hashes(v))
        elif isinstance(value, list):
            for v in value:
                out.update(source_hashes(v))
        return out

    for work in data['works']:
        wk = work['key']
        source = local(work['source_file'])
        source_hash = digest(source)
        chs = bodies(source.read_text(encoding='utf-8'))
        total = len(chs)
        full_coverage[wk] = total
        threads_path = local(work['materials']['foreshadows'])
        threads = json.loads(threads_path.read_text(encoding='utf-8'))
        initial_threads[wk] = threads
        expected_indices = set(range(1, len(threads)+1))
        full = read(f'authoring/independent-full-reading-{wk}.json', wk + ':full')
        need(full.get('status') == 'completed' and full.get('work') == wk and
             full.get('chapter_coverage') == list(range(1, total+1)), wk + ':full:completion')
        need(full.get('source_sha256') == source_hash, wk + ':full:source_binding')
        need(full.get('unresolved_findings') == 0 and isinstance(full.get('findings'), list) and
             all(f.get('resolution_status') in {'closed', 'designed', 'not_conflict'} for f in full.get('findings', [])),
             wk + ':full:findings')
        support = full.get('supporting_input_sha256', {})
        need(isinstance(support, dict), wk + ':full:support_map')
        for rel, h in support.items() if isinstance(support, dict) else []:
            p = local(rel)
            need(p is not None and p.is_file() and digest(p) == h, wk + ':full:support_binding')
        notes = f'authoring/independent-continuity-notes-{wk}-stage1.json'
        if (root / notes).is_file():
            read(notes, wk + ':notes')
        first = read(f'authoring/independent-thread-{wk}.json', wk + ':thread:first')
        final_rel = f'authoring/independent-thread-{wk}-final.json'
        final = read(final_rel, wk + ':thread:final') if (root / final_rel).is_file() else first
        snap = read(f'authoring/blind-thread-input-{wk}.json', wk + ':thread:input')
        need(snap.get('first_record_sha256') == digest(root / f'authoring/independent-thread-{wk}.json')
             if (root / f'authoring/independent-thread-{wk}.json').is_file() else False,
             wk + ':thread:first_record_binding')
        original_text = snap.get('foreshadows_text', '')
        need(isinstance(original_text, str) and is_hash(snap.get('foreshadows_sha256')) and
             hashlib.sha256(original_text.encode('utf-8')).hexdigest() == snap.get('foreshadows_sha256'),
             wk + ':thread:input_hash')
        try:
            original_threads = json.loads(original_text)
        except Exception:
            original_threads = []
        need(isinstance(original_threads, list) and len(original_threads) == len(threads), wk + ':thread:input_count')
        old_titles = {t.get('title'): i for i, t in enumerate(original_threads, 1) if isinstance(t, dict)}
        need(len(old_titles) == len(threads), wk + ':thread:input_titles')
        need(is_hash(first.get('source_sha256')) and first.get('source_sha256') == snap.get('source_sha256') and
             first.get('source_sha256') in source_hashes(full), wk + ':thread:first_source_binding')
        need(first.get('foreshadows_sha256') == snap.get('foreshadows_sha256'), wk + ':thread:first_material_binding')
        need(final.get('source_sha256') == source_hash and final.get('foreshadows_sha256') == digest(threads_path),
             wk + ':thread:final_binding')

        def votes(record, phase):
            label = wk + ':thread:' + phase
            need(record.get('status') == 'completed' and record.get('work') == wk and
                 record.get('chapter_coverage') == list(range(1, total+1)), label + ':completion')
            values = record.get('decisions', [])
            need(isinstance(values, list), label + ':array')
            values = values if isinstance(values, list) else []
            result, seen = {}, []
            for j, value in enumerate(values, 1):
                if not need(isinstance(value, dict), f'{label}:{j}:type'):
                    continue
                index = value.get('foreshadow')
                if phase == 'first' and isinstance(index, str):
                    index = old_titles.get(index)
                need(type(index) is int and index in expected_indices and index not in seen, f'{label}:{j}:index')
                seen.append(index)
                state, chapter, quote = value.get('state'), value.get('chapter'), value.get('quote')
                need(state in {'resolved', 'abandoned', 'open'}, f'{label}:{j}:state')
                if state in {'resolved', 'abandoned'}:
                    need(type(chapter) is int and chapter in chs and isinstance(quote, str) and 10 <= len(quote) <= 60,
                         f'{label}:{j}:evidence_fields')
                    if phase == 'final' and isinstance(quote, str):
                        need(chs.get(chapter, '').count(quote) == 1, f'{label}:{j}:quote')
                if type(index) is int and index in expected_indices:
                    result[index] = value
            need(len(values) == len(expected_indices) and set(seen) == expected_indices and len(seen) == len(set(seen)),
                 label + ':coverage')
            return result

        first_map, final_map = votes(first, 'first'), votes(final, 'final')
        expected = {i: (('resolved', t.get('resolved_chapter')) if t['status'] == 'resolved' else
                        ('abandoned', None) if t['status'] == 'abandoned' else ('open', None))
                    for i, t in enumerate(threads, 1)}
        for field, state in [('resolved_unmarked', 'resolved'), ('abandoned_in_text', 'abandoned')]:
            for e in gold[wk][field]:
                expected[e['foreshadow']] = state, e['chapter']
        def agreement(mapping):
            return sum((v.get('state'), None if v.get('state') == 'open' else v.get('chapter')) == expected[i]
                       for i, v in mapping.items())
        before, after = agreement(first_map), agreement(final_map)
        need(after == len(threads), wk + ':thread:agreement')
        thread_total += len(threads)
        first_agreement += before
        final_agreement += after
        final_votes[wk] = final_map
        work_stats[wk] = {'total': len(threads), 'first_agreement': before, 'final_agreement': after}

    action_sets = action_agreement = 0
    for t in data['tasks']:
        wk = t['work']
        run = t.get('run_suite') or gold[wk].get('run_suites', {}).get(t['id']) or t['suite']
        if run != 'thread_audit':
            continue
        action_sets += 1
        bounds = t.get('plan_edit', {}).get('chapters') or t['scope'] or [1, full_coverage[wk]]
        independent = set()
        for index, vote in final_votes[wk].items():
            ch, state = vote.get('chapter'), vote.get('state')
            if initial_threads[wk][index-1]['status'] in {'planted', 'developing'} and type(ch) is int and bounds[0] <= ch <= bounds[1]:
                if state in {'resolved', 'abandoned'}:
                    independent.add(('resolve_thread' if state == 'resolved' else 'abandon_thread', index))
        field = 'allowed_actions' if t['suite'] == 'injection' else 'expected_actions'
        actual = {(a.get('kind'), a.get('target')) for a in t.get(field, [])}
        match = independent == actual
        action_agreement += int(match)
        need(match, t['id'] + ':thread:action_set')
    bt = {'total': thread_total, 'first_agreement': first_agreement, 'final_agreement': final_agreement,
          'unresolved': thread_total-final_agreement, 'action_sets': action_sets,
          'action_set_agreement': action_agreement, 'works': work_stats}
    br = None
    route_tasks = {t['id']: t for t in data['tasks'] if t['suite'] == 'route'}
    if route_tasks:
        first = read('authoring/independent-route.json', 'route:first')
        last_rel = 'authoring/independent-route-final.json'
        final = read(last_rel, 'route:final') if (root / last_rel).is_file() else first

        def route_votes(record, phase):
            label = 'route:' + phase
            rel = record.get('input_file', 'authoring/blind-route-inputs.json')
            view = read(rel, label + ':input', list)
            p = local(rel)
            need(p is not None and p.is_file() and record.get('input_sha256') == digest(p), label + ':input_binding')
            valid_view = all(isinstance(v, dict) and set(v) == {'id', 'input', 'context'} for v in view)
            vm = {v.get('id'): v for v in view if isinstance(v, dict)}
            need(valid_view and len(view) == len(route_tasks) and set(vm) == set(route_tasks), label + ':input_coverage')
            if phase == 'final':
                need(all(vm.get(i, {}).get('input') == t['input'] and vm.get(i, {}).get('context') == t['context'] for i, t in route_tasks.items()),
                     label + ':current_input')
            values = record.get('decisions', [])
            need(record.get('status') == 'completed' and isinstance(values, list), label + ':completion')
            values = values if isinstance(values, list) else []
            result = {}
            for j, value in enumerate(values, 1):
                if not need(isinstance(value, dict), f'{label}:{j}:type'):
                    continue
                tid = value.get('id')
                need(tid in route_tasks and tid not in result and value.get('route') in routes, f'{label}:{j}:vote')
                if tid in route_tasks:
                    result[tid] = value
            need(len(values) == len(route_tasks) and set(result) == set(route_tasks), label + ':coverage')
            return result

        first_map, final_map = route_votes(first, 'first'), route_votes(final, 'final')
        def route_agreement(mapping):
            return sum(v.get('route') in [route_tasks[i]['expected_route']] + route_tasks[i].get('also_acceptable', [])
                       for i, v in mapping.items())
        before, after = route_agreement(first_map), route_agreement(final_map)
        need(after == len(route_tasks), 'route:agreement')
        br = {'total': len(route_tasks), 'first_agreement': before, 'final_agreement': after, 'unresolved': len(route_tasks)-after}
    if summary is not None:
        need(summary.get('blind_threads') == bt, 'records:thread_summary')
        if br is not None:
            need(summary.get('blind_route') == br, 'records:route_summary')
        listed = summary.get('review_files_sha256', {})
        need(isinstance(listed, dict) and set(listed) == required, 'records:raw_coverage')
        for rel in required:
            p = local(rel)
            need(p is not None and p.is_file() and isinstance(listed, dict) and listed.get(rel) == digest(p), 'records:raw_hash')
    return {'errors': errors, 'blind_threads': bt, 'blind_route': br,
            'chapter_coverage': full_coverage, 'raw_files': sorted(required)}
