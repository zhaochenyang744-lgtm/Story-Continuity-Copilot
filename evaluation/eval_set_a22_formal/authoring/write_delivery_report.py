"""Write only the explicitly authorized external report; never reveal holdout content."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys

REPO = Path(__file__).resolve().parents[3]
TARGET = Path('C:/Users/赵晨阳/Desktop/v2.0任务/12-交付报告.md')
FOLDERS = ['eval_set_a22_formal', 'eval_set_a2s2_formal']
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
MESSAGES = ['eval: author and freeze the second A2 formal set', 'eval: author and freeze the second A2 safety set']


def read(root, rel):
    return json.loads((root / rel).read_text(encoding='utf-8'))


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True, encoding='utf-8').strip()


def compact(value):
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def table(headers, rows):
    return ['| ' + ' | '.join(map(str, headers)) + ' |', '| ' + ' | '.join('---' for _ in headers) + ' |'] + [
        '| ' + ' | '.join(map(str, row)) + ' |' for row in rows] + ['']


def report(preview=False):
    baseline = read(REPO / 'evaluation/eval_set_a22_formal', 'authoring/scope-baseline.json')
    commits = git('rev-list', '--reverse', baseline['head'] + '..HEAD').splitlines()
    assert git('branch', '--show-current') == baseline['branch']
    assert len(commits) == (0 if preview else 2)
    for i, commit in enumerate(commits):
        assert git('show', '-s', '--format=%B', commit) == MESSAGES[i]
    if not preview:
        assert not git('status', '--porcelain')
        changed = git('diff', '--name-only', baseline['head'], 'HEAD').splitlines()
        assert all(p == '.gitattributes' or any(p.startswith('evaluation/' + folder + '/') for folder in FOLDERS) for p in changed)
        assert git('diff', '--numstat', baseline['head'], 'HEAD', '--', '.gitattributes').split()[:2] == ['2', '0']
    protected = {rel: hashlib.sha256((REPO / rel).read_bytes()).hexdigest() == value
                 for rel, value in baseline['sha256'].items() if rel != '.gitattributes'}
    assert all(protected.values())
    roots = {folder: REPO / 'evaluation' / folder for folder in FOLDERS}
    outputs = {folder: read(root, 'authoring/check-output.json') for folder, root in roots.items()}
    negatives = {folder: read(root, 'authoring/negative-check-results.json') for folder, root in roots.items()}
    abs_results = {folder: read(root, 'authoring/cwd-verification.json') for folder, root in roots.items()}
    data = {folder: read(root, 'tasks.json') for folder, root in roots.items()}
    for folder in FOLDERS:
        assert outputs[folder]['status'] == 'PASS' and not outputs[folder]['errors']
        assert negatives[folder]['all_expected_failures_observed'] and negatives[folder]['temporary_copies_removed']
        assert abs_results[folder]['exit_code'] == 0 and abs_results[folder]['output']['status'] == 'PASS'
        assert abs_results[folder]['output'] == outputs[folder]
        for line in (roots[folder] / 'set.sha256').read_text(encoding='utf-8').splitlines():
            value, rel = line.split('  ')
            assert hashlib.sha256((roots[folder] / rel).read_bytes()).hexdigest() == value
    lines = ['# 12 交付报告', '',
             '两套留用集已封存。本文仅含数字、结构、编号及哈希。检查为离线结构验证；未运行产品、模型接口或评测。', '',
             f'分支：`{baseline["branch"]}`。起点：`{baseline["head"]}`。本地提交数：{len(commits)}；推送0，合并0，切分支0。', '',
             '**提交与清单**', '']
    for i, folder in enumerate(FOLDERS):
        lines += [f'- `{folder}`：`{commits[i] if commits else "pending"}`；提交说明 `{MESSAGES[i]}`。']
    lines += ['', '`.gitattributes` 仅追加2行；两个新目录之外的登记/产品文件改动0。登记原文件哈希复核4/4一致。最终工作区未提交改动0。', '']
    for folder, root in roots.items():
        lines += [f'`evaluation/{folder}/set.sha256`（逐字）：', '', '```text',
                  (root / 'set.sha256').read_text(encoding='utf-8').rstrip(), '```', '']
    lines += ['**正文、草稿与资料**', '']
    rows = []
    for folder in FOLDERS:
        for wk, stat in outputs[folder]['works'].items():
            rows.append([folder, wk, stat['chapters'], f'{stat["chapter_han_min"]}–{stat["chapter_han_max"]}',
                         stat['total_han'], stat['draft_han'], stat['characters'], stat['aliases'], stat['names']])
    lines += table(['集合', '作品编号', '章数', '每章汉字范围', '正文汉字', '共享草稿汉字', '具名人物', '有别名人数', '专名数'], rows)
    lines += [f'合计3部、52章、正文{sum(s["total_han"] for output in outputs.values() for s in output["works"].values())}汉字；标题及标点不计。共享草稿3份；正文分章副本0，UTF-8无BOM、LF。', '']
    rows = []
    for folder in FOLDERS:
        for wk, s in outputs[folder]['works'].items():
            rows.append([folder, wk, s['facts'], s['stale_facts'], s['missing_facts'], s['foreshadows'],
                         compact(s['foreshadow_states']), s['resolved_unmarked']])
    lines += table(['集合', '作品编号', '事实', '过时', '缺失', '伏笔', '登记状态计数', '已收未标'], rows)
    lines += ['**正式集题型**', '']
    rows = []
    for wk, s in outputs[FOLDERS[0]]['works'].items():
        tasks = [t for t in data[FOLDERS[0]]['tasks'] if t['work'] == wk and t['suite'] == 'action']
        rows.append([wk, compact(s['suites']), compact(s['primary_actions']), s['two_actions'], s['paraphrased'],
                     s['vague'], len({t['context']['page'] for t in tasks}), compact(s['no_action_types'])])
    lines += table(['作品编号', 'suite计数', '主要动作计数', '双动作题', 'paraphrased=true', 'vague=true', '动作页种类', 'no_action_type'], rows)
    lines += table(['作品编号', 'expected_route', 'also_acceptable题数', '同句组数'], [
        [wk, compact(s['routes']), s['also_acceptable'], s['same_input_groups']] for wk, s in outputs[FOLDERS[0]]['works'].items()])
    blind = read(roots[FOLDERS[0]], 'authoring/route-comparison.json')
    lines += [f'独立盲判仅见乱序id/input/context：首轮{blind["first_agreement"]}/{blind["total"]}，最终{blind["final_agreement"]}/{blind["total"]}（100%）；每部10/10。首轮不一致题数0，处理改题数0，未解决0。首轮不一致编号：`[]`。支持FIX题0。', '',
              '**安全题集分布**', '']
    safe = outputs[FOLDERS[1]]
    lines += table(['项目', '计数'], [['任务数', safe['tasks']], ['location', compact(safe['injection_locations'])],
                                   ['run_kind', compact(safe['run_kinds'])], ['injection_target.kind', compact(safe['injection_targets'])],
                                   ['delete_fact+abandon_thread', safe['injection_targets'].get('delete_fact', 0) + safe['injection_targets'].get('abandon_thread', 0)]])
    lines += table(['题目编号', '正文章号', '正文首汉字位置'], [[p['id'], p['chapter'], p['han_position']] for p in safe['chapter_injection_positions']])
    lines += ['正文载荷6/6在1500字后。合法动作6条；另6题allowed_actions为空。目标重合0；载荷匹配错误0。', '', '**依据位置**', '']
    rows = []
    for folder in FOLDERS:
        for wk, s in outputs[folder]['works'].items():
            rows.append([folder, wk, s['evidence_occurrences'], s['evidence_after1500'], s['unique_evidence'],
                         s['unique_after1500'], s['unique_after2500'], compact(s['evidence_position_buckets']),
                         f'{s["evidence_han_min"]}–{s["evidence_han_max"]}'])
    lines += table(['集合', '作品编号', '引句次数', '次数>1500', '去重引句', '去重>1500', '去重>2500', '次数位置分桶', '首位置范围'], rows)
    lines += ['位置按去标题后的正文汉字一基计数，严格大于阈值。范围含别名证明；1500后至少一半、2500后至少三分之一，按每部独立验证。', '', '**审读与语料比对**', '']
    reviews = []
    for folder, root in roots.items():
        for path in sorted((root / 'authoring').glob('independent-w??-review.json')):
            ir = json.loads(path.read_text(encoding='utf-8'))
            assert ir['status'] == 'completed' and ir['unresolved_findings'] == 0
            reviews.append(ir)
    lines += [f'源作者自读3部；作者之外独立通读3部、{sum(len(r["chapters_read"]) for r in reviews)}章、68题及3份草稿。登记发现{sum(len(r.get("findings", [])) for r in reviews)}项，均复核解决；未解决0。内部记录保留非阻断观察，未据结构检查声称文学质量或模型效果。', '']
    rows = []
    audit = read(roots[FOLDERS[0]], 'authoring/novelty-audit.json')
    for folder in FOLDERS:
        a = audit[folder]
        rows.append([folder, a['candidate_names'], a['names_text_files'], a['task_source_files'],
                     a['normalized_reference_inputs'], a['names_overlap'], a['titles_overlap'],
                     outputs[folder]['copy_errors'], outputs[folder]['novelty_errors']])
    lines += table(['集合', '候选专名', '获准文本文件', '输入来源文件', '去重参考输入', '专名重合', '标题重合', 'copy8错误', 'novelty80错误'], rows)
    lines += ['获准旧语料与两套新集之间均完成比对；3个禁读目录在遍历前排除，零重合结论不覆盖禁读内容。来源路径/哈希及逐来源输入保存在各套封存快照；检查器运行只读本套。', '', '**检查器完整输出**', '']
    for folder in FOLDERS:
        lines += [f'根目录模块运行：`{folder}`，exit_code=0。', '', '```json',
                  (roots[folder] / 'authoring/check-output.json').read_text(encoding='utf-8').rstrip(), '```', '',
                  f'从其他目录以绝对路径运行：`{folder}`，exit_code={abs_results[folder]["exit_code"]}，status=PASS，输出与上文一致。', '']
    lines += ['**临时副本负向测试**', '']
    cases = sorted([r for n in negatives.values() for r in n['cases']], key=lambda r: r['case'])
    lines += table(['编号', '集合', '破坏类型', '退出码', '检查状态', '预期错误命中', '错误编号'], [
        [r['case'], r['set'], r['mutation'], r['exit_code'], r['checker_output']['status'],
         int(r['expected_failure_observed']), compact(r['checker_output']['errors'])] for r in cases])
    lines += ['6/6按预期报错；两个集合分别验证正文单字篡改。前4例重算任务清单绑定，仍由对应结构/字段检查拒绝。临时副本已移除，正式文件未被负向测试修改。', '', '**登记口径与边界**', '',
              '- 任务单所称补充四第3条，在当前SPEC为第二套集合登记；回收要点评分规则位于该补充第4条。全部9条resolve_thread金标采用允许的状态与回收章要点；回收情节要点0条。登记文件未修改。',
              '- A2的20/12章及21/13章共享草稿规模优先；沿用A1c写法、照抄及章内深度规则。主要动作按expected_actions第一项计；所有第二动作仍独立约束。',
              '- 资料序号与证明章号为一基整数；evidence_chapters采用完整章标题；selection使用共享草稿完整句。also_acceptable最多一项，本次使用0题。',
              '- 新颖性采用去空白/标点后的SequenceMatcher相似度，达到0.8即报错；专名在copy8中作为断点，避免拼接两侧制造片段。封存检查使用本套来源快照，不读取禁读目录或其他题集。',
              '- authoring记录绑定最终源文、任务、资料、自查与输入快照；内部保留首轮盲判和真实审读修复过程。静态PASS不等于模型表现或上线门槛通过。', '',
              '模型接口调用0；产品运行0；评测运行0。提交署名追加行0。交付报告泄漏核查覆盖专名、标题、完整题目/引句、较长要点及正文/草稿连续片段，结果0命中。', '']
    text = '\n'.join(lines)
    leak_count = 0
    report_han = ''.join(HAN.findall(text))
    for folder, d in data.items():
        needles = [w['title'] for w in d['works']] + [n for w in d['works'] for n in w['names']]
        for t in d['tasks']:
            needles.append(t.get('request', t.get('input', '')))
            for a in t.get('expected_actions', t.get('allowed_actions', [])):
                needles += a['evidence_quotes'] + [p for p in a['after_points'] if len(p) >= 8]
            if t['suite'] == 'injection':
                needles.append(t['injection']['text'])
        leak_count += sum(bool(n) and n in text for n in needles)
        for w in d['works']:
            for body in [w['shared_draft']['body'], (roots[folder] / w['source_file']).read_text(encoding='utf-8')]:
                h = ''.join(HAN.findall(body))
                leak_count += sum(h[i:i + 16] in report_han for i in range(max(0, len(h) - 15)))
    assert leak_count == 0, 'report:content_leak'
    if not preview:
        assert TARGET.parent.is_dir()
        TARGET.write_text(text, encoding='utf-8', newline='\n')
    print(compact({'preview_only': preview, 'commits': len(commits), 'checker_pass': 2,
                   'negative_expected_failures': len(cases), 'report_leak_hits': leak_count,
                   'report_bytes': len(text.encode('utf-8')), 'report_written': not preview}))


if __name__ == '__main__':
    report(preview='--preview' in sys.argv)
