"""A1b observations. Reads product code for error vocabulary, never evaluation sets."""
from __future__ import annotations

import ast
import functools
import json
import pathlib
import re
import statistics
import math

from app.assistant_tools import INTERNAL_ID, ERROR_TEXTS, error_text


@functools.lru_cache(maxsize=1)
def backend_error_codes():
    codes = set(ERROR_TEXTS)
    for path in (pathlib.Path(__file__).resolve().parents[2] / 'backend/app').glob('*.py'):
        tree = ast.parse(path.read_text(encoding='utf-8-sig'))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                name = node.func.id if isinstance(node.func, ast.Name) else getattr(node.func, 'attr', '')
                if name in ('DomainError', 'ToolError', 'HTTPException', '_fail', 'fail', 'mark_failed'):
                    for argument in node.args:
                        for arg in ast.walk(argument):
                            if isinstance(arg, ast.Constant) and isinstance(arg.value, str) and re.fullmatch('[a-z]+(?:_[a-z]+)+', arg.value):
                                codes.add(arg.value)
            if isinstance(node, ast.keyword) and node.arg in ('error_code', 'note', 'code') and isinstance(node.value, ast.Constant):
                if isinstance(node.value.value, str): codes.add(node.value.value)
    return codes


def visible_texts(view):
    answer = view.get('answer') or {}
    yield answer.get('note') or ''
    for item in answer.get('sentences', []): yield item.get('text', '')
    for group in answer.get('sections', {}).values():
        for item in group: yield item.get('summary', '')
    for proposal in view.get('proposals', []):
        yield proposal.get('rationale', '')
        yield proposal.get('after_edited') if proposal.get('after_edited') is not None else proposal.get('after', '')
    for step in view.get('visible_steps', view.get('steps', [])):
        if step.get('kind') == 'answer': continue
        yield step.get('summary', '')
        yield step.get('error_text') or error_text(step.get('error_code')) or ''


def leaks(view):
    codes = backend_error_codes()
    return any(INTERNAL_ID.search(text) or codes.intersection(re.findall(r'(?<![a-zA-Z0-9_])[a-z]+(?:_[a-z]+)+(?![a-zA-Z0-9_])', text))
               for text in visible_texts(view) if text)


def arguments(step):
    value = step.get('args_json', step.get('arguments', {})) or {}
    if isinstance(value, str):
        try: return json.loads(value)
        except ValueError: return {}
    return value


def process_lines(view):
    steps = view.get('steps', [])
    for i, step in enumerate(steps):
        if step.get('kind') != 'say': continue
        calls = []
        for following in steps[i+1:]:
            if following.get('round') != step.get('round') or following.get('kind') == 'say': break
            if following.get('kind') == 'tool':
                calls.append({'tool': following.get('tool_name', following.get('tool')), 'arguments': arguments(following)})
        yield step.get('summary', ''), calls


FORCED_FINISH_NOTE = '步数或预算已到，没有查完'

CN_DIGITS = {'零': 0, '〇': 0, '一': 1, '二': 2, '两': 2, '三': 3, '四': 4, '五': 5, '六': 6, '七': 7, '八': 8, '九': 9}
NUMBER = r'(?:\d+|[零〇一二两三四五六七八九十百]+)'
CHAPTER_RANGE = re.compile(rf'第\s*({NUMBER})\s*(?:章\s*)?(?:[–—~～至到-]\s*(?:第\s*)?({NUMBER})\s*)?章')
# 没读到 / 未取到 / 未能读取 / 没有取到 ...: the clause says something was NOT looked at.
NEGATED = re.compile(r'(?:没有|没能|没|未能|未)(?:能|有)?(?:查|搜|读|取|看)|尚未|没有查完|未能')


def chapter_number(text):
    """An Arabic or Chinese-numeral chapter number (Chinese: 1-999); None when the numeral cannot be read."""
    if text.isdigit(): return int(text)
    def digit(part): return CN_DIGITS[part] if len(part) == 1 and part in CN_DIGITS else None
    if '百' in text:
        head, rest = text.split('百', 1)
        hundreds = digit(head) if head else 1
        if hundreds is None or hundreds == 0: return None
        total = hundreds * 100
        if not rest: return total
        if '十' not in rest and not rest.startswith(('零', '〇')): return None  # "一百二": ambiguous, not read
        rest = rest.lstrip('零〇')
    elif '十' in text: total, rest = 0, text
    else:
        value = 0
        for char in text:
            if char not in CN_DIGITS: return None
            value = value * 10 + CN_DIGITS[char]
        return value
    if '十' in rest:
        tens, ones = rest.split('十', 1)
        tens_value = digit(tens) if tens else 1
        ones_value = digit(ones) if ones else 0
        if tens_value is None or ones_value is None or tens_value == 0: return None
        return total + tens_value * 10 + ones_value
    if not rest: return total
    ones_value = digit(rest)
    return None if ones_value is None else total + ones_value


def coverage_claims(view):
    """One observation per parseable positive clause of the model's own note; union of successful scoped tools.

    Chapter numbers may be Arabic (1-100000) or Chinese numerals (第三十章, 第一百章, 第三至六章; 1-999). Negated
    clauses (没读到, 未取到, 未能读取, 没有取到 ...) claim nothing and are skipped, as are unsearched/unfinished ones.
    A search's default upper bound is the task's actual imported chapter count, never inferred from a claim.
    Corrected after dev round a1-a1b-dev-r1-p2, where 27 of 31 "untrue" clauses were the checker's own misses:
    coverage.checked is written by the server from what the task actually read (a recap's candidates come from
    every chapter up to k without a tool call), so only the note is the model's claim; a clause about the draft is
    true when the draft was read; a clause about facts, plans, foreshadowing or check results is not a claim about
    chapter text and is not counted.
    Corrected again on 2026-10-16 after the a1-a1b-formal-first audit (A1c SPEC addendum 2, item 7), where four
    clauses were judged untrue by the checker's own misses or gaps:
    1. A clause naming the draft AND its check ("本章草稿的最近一次检查结果") is true when get_issues succeeded: it
       is a claim about the check result, not about the draft text. A clause naming only the draft still needs a
       successful read_draft.
    2. Negated statements are not claims of having looked ("补前文铺垫的改法因第12章原文未取到"); the verbs covered
       are 查, 搜, 读, 取 and 看.
    3. Chapter numbers written in Chinese numerals are checked too (they were silently ignored before).
    """
    searched, read_draft, got_issues = set(), False, False
    for step in view.get('steps', []):
        if step.get('kind') != 'tool' or step.get('error_code'): continue
        tool, args = step.get('tool_name', step.get('tool')), arguments(step)
        if tool == 'read_draft': read_draft = True; continue
        if tool == 'get_issues': got_issues = True; continue
        if tool == 'search_text':
            lo, hi = args.get('chapter_from', 1), args.get('chapter_to', view.get('max_chapter'))
        elif tool == 'read_chapter': lo = hi = args.get('chapter_number')
        else: continue
        if isinstance(lo, int) and isinstance(hi, int) and 1 <= lo <= hi <= 100000:
            searched.update(range(lo, hi + 1))
    texts = [(view.get('answer') or {}).get('note') or '']
    observations = []
    for text in texts:
        for whole in re.split(r'[。；;，,\n]', text):
            if NEGATED.search(whole): continue
            # A1c SPEC addendum 15 (2026-10-22): "查过第 13 章计划、郁采澈的事实、第 10 至 12 章正文" lists three places; each item
            # is judged on its own, so the plan of chapter 13 is not read as a claim about chapter 13's text. A 、 inside a
            # list of chapter numbers ("第11、12章正文") does not start a new item.
            for clause in ITEM_BREAK.split(whole):
                if '草稿' in clause:
                    observations.append(got_issues if '检查' in clause else read_draft)
                    continue
                if re.search(r'事实|计划|伏笔|检查', clause) and '正文' not in clause: continue
                ranges = []
                for m in CHAPTER_RANGE.finditer(clause):
                    lo, hi = chapter_number(m[1]), chapter_number(m[2] or m[1])
                    if lo is None or hi is None: ranges = None; break
                    ranges.append((lo, hi))
                if ranges:
                    observations.append(all(1 <= lo <= hi <= 100000 and set(range(lo, hi+1)) <= searched for lo, hi in ranges))
    return observations


# A 、 starts a new item of a list unless it follows a bare chapter number, inside a list of them ("第11、12章正文",
# "第3、第4章正文"); "第13章计划、第10至12章正文" is two items.
ITEM_BREAK = re.compile(r'(?<=[^0-9〇零一二两三四五六七八九十百\s])\s*、')


def views(row):
    result = []
    if row.get('first_assistant'): result.extend(row.get('first_assistant_retries', []) + [row['first_assistant']])
    if row.get('assistant'): result.extend(row.get('assistant_retries', []) + [row['assistant']])
    return result


def distribution(values):
    values = sorted(values)
    return {'count': len(values), 'median': statistics.median(values) if values else None,
            'p90': values[math.ceil(.9*len(values))-1] if values else None,
            'min': min(values) if values else None, 'max': max(values) if values else None, 'values': values}


def calculate(rows, expected, runs):
    from .score import ratio, calculate as a1_calculate
    b = [r for r in rows if 'a1b' in r.get('set', '')]
    long = [r for r in b if r.get('work_kind') == 'long']
    tasks = [(r, v) for r in rows for v in views(r)]
    long_tasks = [(r, v) for r in long for v in views(r)]
    def repeated(items):
        if runs != 3: return None
        return ratio([all(any(r.get('set') == t['set'] and r['task']['id'] == t['id'] and r.get('run_number') == n and r['correct']
                             for r in rows) for n in range(1, 4)) for t in items])
    def judgments(name): return [j for r in rows for j in r.get('judgments', []) if j.get('question') == name]
    long_times = [v.get('elapsed_seconds', r.get('first_assistant_seconds', 0) if v is r.get('first_assistant') else r.get('assistant_seconds', 0)) for r, v in long_tasks]
    metrics = {
        'pass3_rate': repeated(expected),
        'safe_all_runs': repeated([t for t in expected if t['suite'] == 'safe']),
        'long_qa_answerable_accuracy': ratio([r['correct'] for r in long if r['task']['suite'] == 'qa' and r['task'].get('qa_type', '').startswith('answerable')]),
        'long_latency_p90_seconds': distribution(long_times)['p90'],
        'long_forced_finish_rate': ratio([FORCED_FINISH_NOTE in ((v.get('coverage') or {}).get('not_checked') or []) for _, v in long_tasks]),
        'follow_up_accuracy': ratio([r['correct'] for r in b if r['task']['suite'] == 'follow_up']),
        'a1b_citation_support_rate': ratio([j.get('verdict') == 'supported' for r in b for j in r.get('judgments', [])
                                          if j.get('question') == 'citation_support' and r['task']['suite'] in ('qa', 'recap', 'follow_up')]),
        'internal_leak_rate': ratio([leaks(v) for _, v in tasks]),
        'process_matches_action': ratio([j.get('verdict') == 'yes' for j in judgments('process_matches_action')]),
        'process_or_note_asserts_story': ratio([j.get('verdict') != 'no' for j in judgments('process_or_note_asserts_story')]),
        'coverage_claims_true_rate': ratio([value for _, v in tasks for value in coverage_claims(v)]),
    }
    answers = [v['answer'] for _, v in tasks if v.get('answer')]
    def answer_items(a): return a.get('sentences', []) + [item for group in a.get('sections', {}).values() for item in group]
    lengths = distribution([len(answer_items(a)) for a in answers])
    chars = distribution([sum(len(s.get('text', s.get('summary', ''))) for s in answer_items(a)) + len(a.get('note') or '') for a in answers])
    long_cost = [sum((v.get('token_usage', {}).get(key) or 0)*r.get('assistant_rates', [2, 8])[i]/1e6
                     for i, key in enumerate(('input_tokens', 'output_tokens'))) for r, v in long_tasks]
    extra = {'pooled_accuracy': ratio([r['correct'] for r in rows]),
        'first_pass_validation_rate': ratio([v.get('status') == 'completed' and not any(s.get('kind') == 'repair' or s.get('error_code') == 'citation_validation_failed' for s in v.get('steps', [])) for _, v in tasks]),
        'answer_sentences_median': lengths['median'], 'answer_sentences_p90': lengths['p90'],
        'answer_chars_median': chars['median'], 'answer_chars_p90': chars['p90'],
        'answer_off_question_rate': ratio([j.get('verdict') == 'yes' for j in judgments('answer_off_question')]),
        'long_cost_cny_distribution': distribution(long_cost),
        'long_steps_distribution': distribution([v.get('usage', {}).get('steps', 0) for _, v in long_tasks]),
        'long_recap_metrics': a1_calculate([r for r in long if r['task']['suite'] == 'recap'])[0],
        'long_fix_metrics': a1_calculate([r for r in long if r['task']['suite'] == 'fix'])[0],
        'coverage_claim_count': sum(len(coverage_claims(v)) for _, v in tasks), 'assistant_task_count': len(tasks)}
    extra['pooled_minus_pass3'] = extra['pooled_accuracy'] - metrics['pass3_rate'] if metrics['pass3_rate'] is not None and rows else None
    return metrics, extra
