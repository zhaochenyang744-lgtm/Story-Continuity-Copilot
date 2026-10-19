"""A1c metrics (real chapter length, v1.8.0). The bar is evaluation/assistant_a1c/thresholds.py, registered; this file
only computes the numbers it is applied to. Every rate pools all passes. Metric definitions follow
evaluation/assistant_a1c/SPEC.md and its addendum 2 (2026-10-16), items 2, 4, 5 and 7.
"""
from __future__ import annotations

import json
import statistics

from evaluation.assistant_a1c import thresholds
from . import supplemental
from .score import decide, ratio, verdicts

READ_WINDOW = 2000  # the product's per-read ceiling (backend/app/assistant_tools.py READ_DEFAULT_CHARS)


def is_a1c(name):
    return name.startswith('eval_set_a1c')


def answerable(row):
    """QA with an answer and follow-ups (a follow-up always has one)."""
    task = row['task']
    return task['suite'] == 'follow_up' or (task['suite'] == 'qa' and task.get('qa_type', 'answerable_single').startswith('answerable'))


def view_seconds(row, view):
    if 'elapsed_seconds' in view: return view['elapsed_seconds']
    return row.get('first_assistant_seconds', 0) if view is row.get('first_assistant') else row.get('assistant_seconds', 0)


def view_cost(row, view, only_view):
    usage = view.get('token_usage')
    if usage is None: return row.get('assistant_cost_cny', 0) if only_view else 0
    rates = row.get('assistant_rates') or [2, 8]
    return ((usage.get('input_tokens') or 0) * rates[0] + (usage.get('output_tokens') or 0) * rates[1]) / 1e6


def view_steps(view):
    return (view.get('usage') or {}).get('steps', 0)


def window(args, lengths):
    """(chapter, start, end) of one successful read_chapter: min(max_chars, 2000, length - from_char), at least 0."""
    number, start, limit = args.get('chapter_number'), args.get('from_char', 0), args.get('max_chars', READ_WINDOW)
    if any(isinstance(v, bool) or not isinstance(v, int) for v in (number, start, limit)): return None
    length = lengths.get(str(number), lengths.get(number))
    if not isinstance(length, int): return None
    got = max(0, min(limit, READ_WINDOW, length - start))
    return number, start, start + got


def characters_read(row, view):
    """Characters one assistant task read through successful read_chapter calls.

    read: every returned character, counted per call. unique: characters of a chapter counted once however many reads
    covered them. chapter_total: the stored length of every chapter that returned at least one character (a read that
    starts past the chapter's end returns nothing and does not make the chapter "read"). None when this record has no
    stored chapter lengths. Chapter lengths come from the product's own stored text (export snapshot), not the markdown.
    """
    lengths = row.get('chapter_lengths')
    if not lengths: return None
    spans, read = {}, 0
    for step in view.get('steps', []):
        if step.get('kind') != 'tool' or step.get('error_code'): continue
        if step.get('tool_name', step.get('tool')) != 'read_chapter': continue
        found = window(supplemental.arguments(step), lengths)
        if not found: continue
        number, start, end = found
        read += end - start
        if end > start: spans.setdefault(number, []).append((start, end))
    unique = 0
    for intervals in spans.values():
        top = -1
        for start, end in sorted(intervals):
            start = max(start, top)
            if end > start: unique += end - start
            top = max(top, end)
    total = sum(lengths.get(str(n), lengths.get(n)) for n in spans)
    return {'read': read, 'unique': unique, 'chapter_total': total, 'chapters': len(spans)}


def calculate(rows, expected, runs):
    """-> (metrics: the 18 gated values, extra: reported, not gated). Decides every row first, as A1's calculate does."""
    for row in rows:
        row['audit_wrong'] = False
        decide(row)
    qa = [r for r in rows if r['task']['suite'] == 'qa']
    recap = [r for r in rows if r['task']['suite'] == 'recap']
    fix = [r for r in rows if r['task']['suite'] == 'fix']
    follow = [r for r in rows if r['task']['suite'] == 'follow_up']
    # Same unit as A1b: every assistant task, a follow-up's first question and the follow-up each once (an
    # infrastructure-retried attempt is its own entry, as in A1b's views()).
    tasks = [(r, v) for r in rows for v in supplemental.views(r)]
    correct = {(r.get('set'), r['task']['id'], r.get('run_number')): bool(r['correct']) for r in rows}

    def qacc(kind): return ratio([r['correct'] for r in qa if r['task'].get('qa_type', 'answerable_single').startswith(kind)])
    def repeated(items):
        if runs != 3: return None
        return ratio([all(correct.get((t['set'], t['id'], n), False) for n in (1, 2, 3)) for t in items])
    def judgments(name): return [j for r in rows for j in r.get('judgments', []) if j.get('question') == name]

    citations = [j.get('verdict') == 'supported' for r in rows if r['task']['suite'] in ('qa', 'follow_up', 'recap')
                 for j in r.get('judgments', []) if j.get('question') == 'citation_support']
    per_view = {}
    for row in rows:
        for view in supplemental.views(row): per_view[id(view)] = len(supplemental.views(row)) == 1
    budget = [view_steps(v) <= 8 and view_cost(r, v, per_view[id(v)]) <= .3 for r, v in tasks]
    seconds = [view_seconds(r, v) for r, v in tasks]
    metrics = {
        'qa_answerable_accuracy': qacc('answerable'),
        'deep_answerable_accuracy': ratio([r['correct'] for r in rows if answerable(r) and r['task'].get('deep') is True]),
        'qa_not_in_text_accuracy': qacc('not_in_text'),
        'qa_conflicting_accuracy': qacc('conflicting'),
        'follow_up_accuracy': ratio([r['correct'] for r in follow]),
        'citation_support_rate': ratio(citations),
        'recap_must_mention_recall': ratio([verdicts(r).get(f'must_mention:{i}') == 'yes' for r in recap for i in range(len(r['task']['must_mention']))]),
        'recap_must_not_hits': sum(verdicts(r).get(f'must_not:{i}') == 'yes' for r in recap for i in range(len(r['task']['must_not']))) if recap else None,
        'fix_success_rate': ratio([r['correct'] for r in fix]),
        'pass3_rate': repeated(expected),
        'budget_compliance_rate': ratio(budget),
        'latency_p90_seconds': supplemental.distribution(seconds)['p90'] if seconds else None,
        'forced_finish_rate': ratio([supplemental.FORCED_FINISH_NOTE in ((v.get('coverage') or {}).get('not_checked') or []) for _, v in tasks]),
        'internal_leak_rate': ratio([supplemental.leaks(v) for _, v in tasks]),
        'safe_all_runs': repeated([t for t in expected if t['suite'] == 'safe']),
        'process_matches_action': ratio([j.get('verdict') == 'yes' for j in judgments('process_matches_action')]),
        'process_or_note_asserts_story': ratio([j.get('verdict') != 'no' for j in judgments('process_or_note_asserts_story')]),
        'coverage_claims_true_rate': ratio([value for _, v in tasks for value in supplemental.coverage_claims(v)]),
    }
    reads = [x for x in (characters_read(r, v) for r, v in tasks) if x is not None]
    with_chapters = [x for x in reads if x['chapters']]
    extra = {
        'pooled_accuracy': ratio([r['correct'] for r in rows]),
        'first_pass_validation_rate': ratio([v.get('status') == 'completed' and not any(s.get('kind') == 'repair' or s.get('error_code') == 'citation_validation_failed'
                                                                                         for s in v.get('steps', [])) for _, v in tasks]),
        'cost_cny_distribution': supplemental.distribution([view_cost(r, v, per_view[id(v)]) for r, v in tasks]),
        'steps_distribution': supplemental.distribution([view_steps(v) for _, v in tasks]),
        'characters_read_distribution': {
            'tasks_with_chapter_lengths': len(reads),
            'read': supplemental.distribution([x['read'] for x in reads]),
            'unique': supplemental.distribution([x['unique'] for x in reads]),
            'unique_ratio': supplemental.distribution([x['unique'] / x['chapter_total'] for x in with_chapters]),
            'unique_ratio_pooled': sum(x['unique'] for x in with_chapters) / sum(x['chapter_total'] for x in with_chapters) if with_chapters else None,
        },
        'coverage_claim_count': sum(len(supplemental.coverage_claims(v)) for _, v in tasks), 'assistant_task_count': len(tasks),
    }
    extra['pooled_minus_pass3'] = extra['pooled_accuracy'] - metrics['pass3_rate'] if metrics['pass3_rate'] is not None and rows else None
    return metrics, extra


def refresh(report):
    rows = report['records']
    report['metrics'], report['reported_not_gated'] = calculate(rows, report['expected_cases'], report['runs'])
    report['by_set'] = {name: {'tasks': sum(r['set'] == name for r in rows), 'correct': sum(r['set'] == name and r['correct'] for r in rows)}
                        for name in report['sets']}
    result = thresholds.evaluate(report['metrics'])
    report['threshold_result'] = result
    report['gate_decision'] = result['status'] if report['complete'] else 'incomplete_not_a_gate'
    if report.get('selection'): report['gate_decision'] = 'filtered_not_a_gate'
    per_pass = []
    for number in range(1, report['runs'] + 1):
        values, _ = calculate([r for r in rows if r['run_number'] == number], report['expected_cases'], 1)
        values['safe_all_runs'] = ratio([r['correct'] for r in rows if r['run_number'] == number and r['task']['suite'] == 'safe'])
        per_pass.append({'run_number': number, **values})
    spread = {}
    for key, _, _ in thresholds._CHECKS:
        values = [p[key] for p in per_pass]
        spread[key] = max(values) - min(values) if all(v is not None for v in values) else None
    report['reported_not_gated'].update(per_pass_values=per_pass, per_pass_spread=spread)
    return report


def markdown(report):
    result = report['threshold_result']
    lines = ['# A1c evaluation (real chapter length)', '',
             f"Sets: {', '.join(report['sets'])}; passes: {report['runs']}; complete: {report['complete']}; status: {report['gate_decision']}", '']
    if any(name.endswith('_dev') for name in report['sets']):
        lines += ['Development run: the bar is applied only to tell tuning when to stop; it is not the release gate.', '']
    lines += ['| Check | Value | Bar | Pass |', '|---|---:|---:|---|']
    for key, bar, op in thresholds._CHECKS:
        value = report['metrics'][key]
        lines.append(f"| {key} | {'n/a' if value is None else round(value, 4)} | {'>=' if op == 'min' else '<='} {round(thresholds.THRESHOLDS[bar], 4)} | "
                     f"{'n/a' if result['checks'][key] is None else result['checks'][key]} |")
    lines += ['', '## Failed tasks', '']
    lines += [f"- run {r['run_number']} / {r['set']} / {r['task']['id']}: {', '.join(r['failure_reasons'])}" for r in report['records'] if not r['correct']]
    lines += ['', '## Reported, not gated', '', '```json', json.dumps(report['reported_not_gated'], ensure_ascii=False, indent=2), '```']
    if report.get('usage'):
        lines += ['', '## Usage (upper-bound rates)', '', '| Category | Input tokens | Output tokens | CNY |', '|---|---:|---:|---:|']
        for category, usage in report['usage'].items():
            lines.append(f"| {category} | {usage['input_tokens']} | {usage['output_tokens']} | {usage['cost_cny']:.6f} |")
        lines += ['', f"Time-band estimate, excluding cache discounts: {report.get('time_band_estimated_cny')}"]
    if report.get('overrides'):
        lines += ['', '## Overrides and gate flips (user decision required)', '', '```json',
                  json.dumps({k: report[k] for k in ('overrides', 'flipped_checks', 'requires_user_decision')}, ensure_ascii=False, indent=2), '```']
    return '\n'.join(lines) + '\n'
