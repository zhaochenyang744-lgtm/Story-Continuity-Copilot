"""Write the explicitly requested numeric/structural sealed-set delivery report."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[3]
DESTINATION = Path(r'C:\Users\赵晨阳\Desktop\v2.0任务\19-交付报告.md')
SETS = ['eval_set_a24_formal', 'eval_set_a2s4_formal']


def read_json(path):
    return json.loads(path.read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True, encoding='utf-8').strip()


def inline(value):
    return '`' + json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')) + '`'


def main():
    assert git('branch', '--show-current') == 'eval/a2-4-authoring'
    assert not git('status', '--porcelain'), 'worktree_not_clean'
    subjects = ['eval: author and freeze the fourth A2 formal set', 'eval: author and freeze the fourth A2 safety set']
    commits = dict(line.split('\t', 1)[::-1] for line in git('log', '-2', '--format=%H%x09%s').splitlines())
    assert set(commits) == set(subjects)
    for subject in subjects:
        assert git('show', '-s', '--format=%B', commits[subject]) == subject
    assert git('rev-list', '--count', 'eae8805999c3f154b7cca86eb7629f727dc0cbf3..HEAD') == '2'
    bases = {folder: REPO / 'evaluation' / folder for folder in SETS}
    runs = {folder: read_json(base / 'authoring/checker-runs.json') for folder, base in bases.items()}
    stats = {folder: json.loads(run['root']['stdout']) for folder, run in runs.items()}
    assert all(s['status'] == 'PASS' and not s['errors'] for s in stats.values())
    assert all(r['root']['exit_code'] == 0 and r['absolute']['exit_code'] == 0 and
               json.loads(r['root']['stdout']) == json.loads(r['absolute']['stdout']) for r in runs.values())
    tasks = {folder: read_json(base / 'tasks.json') for folder, base in bases.items()}
    corpus = read_json(bases[SETS[0]] / 'authoring/corpus-audit.json')
    blind = read_json(bases[SETS[0]] / 'authoring/blind-route-comparison.json')
    names = read_json(bases[SETS[0]] / 'authoring/proper-name-audit.json')
    negative = read_json(bases[SETS[0]] / 'authoring/negative-tests.json')
    prose = read_json(bases[SETS[0]] / 'authoring/prose-audit.json')
    lines = ['# 19 交付报告', '', '日期：2026-10-24。分支：`eval/a2-4-authoring`。本地提交2次。', '',
             '## 提交与清单', '']
    for folder, subject in zip(SETS, subjects):
        lines += [f'- `{folder}`：`{commits[subject]}`。']
    for folder, base in bases.items():
        lines += ['', f'### {folder}/set.sha256', '', '```text', (base / 'set.sha256').read_text(encoding='utf-8').rstrip(), '```']
    lines += ['', '## 正文与起始资料', '',
              '|集合|作品编号|章数|章内汉字最小–最大|全书汉字|草稿汉字|人物|别名|专名|',
              '|---|---|---:|---:|---:|---:|---:|---:|---:|']
    for folder, result in stats.items():
        for wk, s in result['works'].items():
            lines += [f"|{folder}|{wk}|{s['chapters']}|{s['chapter_han_min']}–{s['chapter_han_max']}|{s['total_han']}|{s['draft_han']}|{s['characters']}|{s['aliases']}|{s['names']}|"]
    lines += ['', '|集合|作品编号|事实|过时|缺失|伏笔|已收未标|伏笔状态数量|', '|---|---|---:|---:|---:|---:|---:|---|']
    for folder, result in stats.items():
        for wk, s in result['works'].items():
            lines += [f"|{folder}|{wk}|{s['facts']}|{s['stale_facts']}|{s['missing_facts']}|{s['foreshadows']}|{s['resolved_unmarked']}|{inline(s['foreshadow_states'])}|"]
    lines += ['', '## 正式集分布', '']
    for wk, s in stats[SETS[0]]['works'].items():
        own = [t for t in tasks[SETS[0]]['tasks'] if t['work'] == wk]
        actions = [t for t in own if t['suite'] == 'action']
        lines += [f'### {wk}', '',
                  f"- suite：{inline(s['suites'])}。主要动作：{inline(s['primary_actions'])}。",
                  '- 全部动作条目：' + inline(dict(Counter(a['kind'] for t in actions for a in t['expected_actions']))) + '。',
                  f"- 双动作题{s['two_actions']}；paraphrased={s['paraphrased']}；vague={s['vague']}。",
                  '- action页面分布：' + inline(dict(Counter(t['context']['page'] for t in actions))) + '。',
                  f"- no_action_type：{inline(s['no_action_types'])}。",
                  f"- expected_route：{inline(s['routes'])}；also_acceptable={s['also_acceptable']}；同句组={s['same_input_groups']}。"]
    safety = stats[SETS[1]]
    lines += ['', '## 安全集分布', '', f"- 位置：{inline(safety['injection_locations'])}。",
              f"- run_kind：{inline(safety['run_kinds'])}。", f"- injection_target：{inline(safety['injection_targets'])}。",
              '- allowed_actions：' + inline(dict(Counter(a['kind'] for t in tasks[SETS[1]]['tasks'] for a in t['allowed_actions']))) + '。',
              '- 正文指令位置：' + inline(safety['chapter_injection_positions']) + '。',
              '- 正文指令在1500字后6/6、2500字后6/6；逐容器唯一出现6/6。',
              '', '## 依据位置', '', '|集合|作品编号|引用次数|1500后|去重依据|去重1500后|去重2500后|首字位置范围|分桶|',
              '|---|---|---:|---:|---:|---:|---:|---:|---|']
    for folder, result in stats.items():
        for wk, s in result['works'].items():
            lines += [f"|{folder}|{wk}|{s['evidence_occurrences']}|{s['evidence_after1500']}|{s['unique_evidence']}|{s['unique_after1500']}|{s['unique_after2500']}|{s['evidence_han_min']}–{s['evidence_han_max']}|{inline(s['evidence_position_buckets'])}|"]
    lines += ['', '## 独立复核与语料审计', '',
              f"- route初判：{blind['initial_agreement']}/{blind['total']}，一致率{blind['initial_agreement']/blind['total']:.0%}；不一致{blind['initial_disagreements']}。",
              f"- 更名后route复判：{blind['final_agreement']}/{blind['total']}，一致率{blind['final_agreement']/blind['total']:.0%}；不一致{len(blind['final_disagreement_ids'])}，未解决{blind['unresolved']}。",
              '- route不一致编号：' + inline(blind['final_disagreement_ids']) + '；意图与金标修订数0。']
    for folder, base in bases.items():
        record = read_json(base / 'authoring/independent-review.json')
        lines += [f"- {folder}独立全文覆盖：{inline(record['chapter_coverage'])}；题目覆盖{record['task_coverage']}；发现{record['findings']}；关闭{record['closed_findings']}；未解决{record['unresolved_findings']}。"]
    lines += [f"- 专名完整名初审重合{names['prior_complete_name_overlap']}；扩展简称初审重合{names['initial_short_name_overlap']}；统一更名{names['proper_names_revised']}项；新增简称登记{names['short_names_added']}项。"]
    for folder in SETS:
        c = corpus[folder]
        lines += [f"- {folder}最终专名重合{c['names_overlap']}；旧文本{c['corpus_files']}文件；旧任务{c['source_files']}文件，归一化输入{c['reference_inputs']}条；照抄错误{stats[folder]['copy_errors']}，旧题新颖性错误{stats[folder]['novelty_errors']}。"]
    lines += ['- 两新套输入相似度≥0.8的非同句组配对：' + str(len(corpus['new_cross_input_overlaps'])) + '；跨作品专名重复：' + str(corpus['new_names_duplicates']) + '。',
              '- 跨作品完整段落重复组（至少30汉字）：' + str(prose['cross_work_repeated_complete_paragraph_groups']) + '。',
              '- 比对范围在遍历前排除 `eval_set_a1_reserve`、`eval_set_a1b_reserve`、`eval_set_v13_authoring`；0重合结论不涵盖这3个禁读目录。',
              '', '## 检查器完整输出', '']
    for folder, run in runs.items():
        lines += [f'### {folder}', '', '```json', run['root']['stdout'].rstrip(), '```', '',
                  f"根目录退出码{run['root']['exit_code']}；其他目录绝对路径退出码{run['absolute']['exit_code']}；两次完整JSON相同。"]
    lines += ['', '## 临时副本负向测试', '', f"总数{negative['total']}；预期检出{negative['passed']}；临时副本清理={str(negative['temporary_copies_removed']).lower()}。", '']
    for case in negative['cases']:
        lines += [f"- `{case['id']}`：基线{case['temporary_baseline_status']}；破坏后{case['status']}；退出码{case['exit_code']}；目标错误检出={str(case['detected_expected_error']).lower()}；错误{inline(case['errors'])}。"]
    baseline = read_json(bases[SETS[0]] / 'authoring/protected-baseline.json')
    assert all(hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == expected for rel, expected in baseline['sha256'].items())
    changed = git('diff', '--name-only', baseline['head'], 'HEAD').splitlines()
    assert all(path == '.gitattributes' or path.startswith(tuple('evaluation/' + folder + '/' for folder in SETS)) for path in changed)
    lines += ['', '## 范围与规则口径', '',
              f'- 受保护登记文件{len(baseline["sha256"])}个，哈希全部保持；本地新增提交2个；工作区未提交文件0个。',
              '- 变更范围：2个新目录与 `.gitattributes`；模型接口0、产品运行0、评测运行0。',
              '- A2规模优先：20/20/12章，共享草稿为21/21/13章；不套用旧A1c的30章、正文有意矛盾或第31章计划。',
              '- 汉字计U+3400–U+4DBF、U+4E00–U+9FFF，不含标题与标点。章内位置取首汉字一基；严格大于1500计后段，另从严检查至少1/3去重依据大于2500。',
              '- evidence_chapters使用完整章标题；材料和self-review使用整数章号、一基数组位置。',
              '- resolve_thread采用任务单规定的2条精确程序点；额外语义点0。',
              '- 同句组保持input逐字相同、context不同、expected_route不同；本套不使用fix_issue或支持FIX，also_acceptable为0。',
              '- 安全资料中的指定载荷按误收备注处理；其余资料仍需正文支持。注入对象与合法对象按动作和对象双重隔离。',
              '- 结构PASS与独立语义审读分开记录；checker中的semantic_acceptance=false表示检查器本身不作语义或模型质量判定。',
              '- 交付后封存；正式运行前按登记边界只运行本套结构检查器。', '']
    report = '\n'.join(lines)
    forbidden = []
    for folder, data in tasks.items():
        for work in data['works']:
            forbidden += [(folder, 'name', value) for value in work['names']]
            forbidden += [(folder, 'title', work['title'])]
            forbidden += [(folder, 'draft', p) for p in work['shared_draft']['body'].split('\n\n') if len(p) >= 15]
        for task in data['tasks']:
            forbidden += [(task['id'], key, task[key]) for key in ['input', 'request', 'why'] if key in task]
            if 'injection' in task:
                forbidden += [(task['id'], 'injection', task['injection']['text'])]
            for action in task.get('expected_actions', task.get('allowed_actions', [])):
                forbidden += [(task['id'], 'point', p) for p in action['after_points']]
                forbidden += [(task['id'], 'evidence', q) for q in action['evidence_quotes']]
    hits = [{'id': tag, 'field': field} for tag, field, value in forbidden if value and value in report]
    assert not hits, json.dumps({'report_leak_hits': hits})
    report += f'报告封存内容精确字符串检查：候选{len(forbidden)}项，命中0。\n'
    DESTINATION.write_text(report, encoding='utf-8', newline='\n')
    print(json.dumps({'report': str(DESTINATION), 'bytes': DESTINATION.stat().st_size, 'leak_candidates': len(forbidden),
                      'leak_hits': 0, 'commits': [commits[s] for s in subjects]}, ensure_ascii=False))


if __name__ == '__main__':
    main()
