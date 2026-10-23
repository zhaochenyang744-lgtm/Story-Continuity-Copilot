"""Serialize lead-authored records and audit positions; never generate prose."""
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def load(path):
    return json.loads(path.read_text(encoding='utf-8'))


def write(path, data):
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')


def parse(path):
    text = path.read_text(encoding='utf-8')
    starts = list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$', text, re.M))
    return {int(m[1]): {'title': m[0][2:], 'body': text[m.end():starts[i + 1].start() if i + 1 < len(starts) else len(text)]}
            for i, m in enumerate(starts)}


def action(root, wk, kind, number, points):
    bible = load(root / 'authoring' / f'{wk}-bible.json')
    field = {'add_fact': 'missing_facts', 'change_fact': 'stale_facts', 'resolve_thread': 'resolved_unmarked'}[kind]
    proof = bible[field][number - 1]
    n = proof.get('changed_chapter', proof.get('chapter'))
    chs = parse(root / 'works' / f'{wk}.md')
    q = proof['quote']
    assert chs[n]['body'].count(q) == 1, (wk, field, number)
    target = ({'subject': proof['subject'], 'predicate': proof['predicate']} if kind == 'add_fact' else
              proof['fact'] if kind == 'change_fact' else proof['foreshadow'])
    return {'kind': kind, 'target': target, 'after_points': points,
            'evidence_chapters': [chs[n]['title']], 'evidence_quotes': [q]}


def assemble(folder):
    root = REPO / 'evaluation' / folder
    safety = folder == 'eval_set_a2s2_formal'
    authored = load(root / 'authoring' / 'lead-authored.json')
    works, reviews = [], {}
    for wk in (['w01'] if safety else ['w01', 'w02']):
        bible = load(root / 'authoring' / f'{wk}-bible.json')
        work = {k: deepcopy(bible[k]) for k in ['key', 'title', 'names']}
        work.update({'language': 'zh', 'source_file': f'works/{wk}.md', 'purpose': 'general', 'kind': 'long',
                     'materials': {'facts': f'materials/{wk}-facts.json', 'foreshadows': f'materials/{wk}-foreshadows.json'},
                     'shared_draft': authored['drafts'][wk]})
        works.append(work)
        wr = {k: deepcopy(bible[k]) for k in ['characters', 'aliases', 'stale_facts', 'missing_facts', 'resolved_unmarked']}
        if not safety:
            wr.update(authored['work_review'][wk])
        reviews[wk] = wr
    tasks = deepcopy(authored['tasks'])
    for t in tasks:
        field = 'allowed_actions' if safety else 'expected_actions'
        if field in t:
            t[field] = [action(root, t['work'], *entry) for entry in t[field]]
    data = {'version': 'a2-1', 'set_id': 'a2s2-formal' if safety else 'a22-formal',
            'author': 'evaluation authoring', 'works': works, 'tasks': tasks}
    write(root / 'tasks.json', data)
    task_reviews, lines = {}, ['# 逐题自查', '',
        '本记录包含封存内容。依据位置为去掉标题后的正文汉字一基位置。语义自查、独立审读和结构检查分别完成；本文不报告模型效果。', '',
        '## 起始资料与设计变化', '']
    for wk, wr in reviews.items():
        chs = parse(root / 'works' / f'{wk}.md')
        lines += [f'### {wk}', '']
        for field in ['stale_facts', 'missing_facts', 'resolved_unmarked', 'aliases']:
            for i, item in enumerate(wr[field], 1):
                n = item.get('changed_chapter', item.get('chapter'))
                q = item['quote']
                assert chs[n]['body'].count(q) == 1, (wk, field, i)
                pos = len(HAN.findall(chs[n]['body'][:chs[n]['body'].index(q)])) + 1
                lines += [f'- {field}/{i}：{chs[n]["title"]}，第{pos}个汉字起。原句：{q}']
        lines.append('')
    lines += ['## 题目', '']
    for t in tasks:
        wk, tid = t['work'], t['id']
        chs = parse(root / 'works' / f'{wk}.md')
        lines += [f'### {tid}', '', t['why'], '']
        entries = t.get('expected_actions', t.get('allowed_actions', []))
        evidence = []
        for i, e in enumerate(entries, 1):
            lines += [f'- 动作{i}：{e["kind"]}；目标：{json.dumps(e["target"], ensure_ascii=False)}；要点：' + '；'.join(e['after_points']) + '。']
            for title, q in zip(e['evidence_chapters'], e['evidence_quotes']):
                n = next(n for n, ch in chs.items() if ch['title'] == title)
                body = chs[n]['body']
                pos = len(HAN.findall(body[:body.index(q)])) + 1
                evidence.append({'chapter': n, 'han_position': pos})
                lines += [f'- 依据：{title}，第{pos}个汉字起；原句：{q}']
        if t['suite'] == 'route':
            lines += [f'- 主期望：{t["expected_route"]}；情境：{t["context"]["page"]}。独立复判另存首轮记录。',
                      '- 用法判断的依据是输入与界面情况，不以正文考点句为答案；章内依据位置不适用。']
        if t['suite'] == 'no_action':
            lines += [f'- 不出卡片，类型：{t["no_action_type"]}。指向：{json.dumps(t["request_targets"], ensure_ascii=False)}。']
            supplement = authored.get('no_action_review', {}).get(tid)
            if supplement:
                lines += ['- 语义核对：' + supplement]
            for proof in authored.get('no_action_evidence', {}).get(tid, []):
                n, q = proof['chapter'], proof['quote']
                body = chs[n]['body']
                assert body.count(q) == 1, tid
                pos = len(HAN.findall(body[:body.index(q)])) + 1
                evidence.append({'chapter': n, 'han_position': pos})
                lines += [f'- 对照正文：{chs[n]["title"]}，第{pos}个汉字起；原句：{q}']
            if t['no_action_type'] == 'prose_edit':
                body = next(w for w in works if w['key'] == wk)['shared_draft']['body']
                selected = t['context']['selection']
                pos = len(HAN.findall(body[:body.index(selected)])) + 1
                lines += [f'- 所选草稿句从草稿第{pos}个汉字开始；它不构成资料改动依据。']
            if t['no_action_type'] == 'no_evidence' and not authored.get('no_action_evidence', {}).get(tid):
                lines += ['- 全书未交代所要填写的信息，不存在可引用的答案句；通过全书阅读核对，不伪造位置。']
            if t['no_action_type'] == 'unsupported_kind':
                lines += ['- 判断依据是登记的三种支持动作；该请求的动作在范围外，章内考点句位置不适用。']
        if t['suite'] == 'action':
            lines += [f'- paraphrased={str(t["paraphrased"]).lower()}，vague={str(t["vague"]).lower()}。']
        if t['suite'] == 'injection':
            inj = t['injection']
            lines += [f'- 不可信指令位于：{json.dumps(inj["location"], ensure_ascii=False)}；目标：{json.dumps(t["injection_target"], ensure_ascii=False)}。']
            if inj['location']['kind'] == 'chapter':
                n = inj['location']['chapter']
                body = chs[n]['body']
                pos = len(HAN.findall(body[:body.index(inj['text'])])) + 1
                lines += [f'- 正文载荷从第{pos}个汉字开始；逐字匹配。']
            lines += ['- 请求要求的事项及载荷来源关联：' + authored['injection_review'][tid]]
        task_reviews[tid] = {'why': t['why'], 'evidence_positions': evidence}
        lines.append('')
    lines += ['## 登记歧义处理', '',
        'A2重新规定章数、草稿规模和题型，以A2及任务单为准；A1c写法、章内深处及照抄要求继续执行。任务单提到补充四第3条，该条登记第二套；实际要点评分口径位于同补充第4条，本集按明确写出的状态、回收章和依据直读要求处理，不修改登记文件。', '',
        '新颖性和专名比对按读取禁令排除三个目录；报告中的零重合只覆盖获准语料。资料中的指令备注属于安全集明确要求的测试载荷，不作事实真值。', '']
    if not safety and (root / 'authoring/route-comparison.json').is_file():
        blind = load(root / 'authoring/route-comparison.json')
        lines += ['## 独立用法复判', '',
                  f'只读随机化id/input/context，共{blind["total"]}题。首轮一致{blind["first_agreement"]}题，最终一致{blind["final_agreement"]}题，未解决{blind["unresolved"]}题。',
                  '首轮不一致编号：' + (', '.join(blind['first_disagreements']) or '无') + '。',
                  '原始盲判、输入及比较记录均保留；本次没有以金标提示审读者，也没有因盲判改题。', '']
    if safety and (root / 'authoring/writer-task-review.json').is_file():
        writer_review = load(root / 'authoring/writer-task-review.json')
        lines += ['## 源文作者核对主控题目', '',
                  f'逐题核对{writer_review["task_count"]}题，发现{len(writer_review["findings"])}项，未解决{writer_review["unresolved_findings"]}项。这项核对不替代独立通读。', '']
        for finding in writer_review['findings']:
            lines += [f'- {finding["id"]} / {finding["task_id"]}：{finding["detail"]} 处理：{finding["resolution"]}']
        lines.append('')
    independent_paths = sorted((root / 'authoring').glob('independent-w??-review.json'))
    if independent_paths:
        lines += ['## 作者之外的完整审读', '',
                  '各作品由未参与该作品写作的审读者逐章通读，并逐题复核。以下发现来自真实审读记录；根级独立审读记录另绑定最终源文、题目、资料和本自查的哈希。', '']
        for path in independent_paths:
            ir = load(path)
            lines += [f'- {path.name}：完整读章{len(ir["chapters_read"])}，状态{ir["status"]}，未解决{ir["unresolved_findings"]}。']
            for finding in ir.get('findings', []):
                lines += [f'  - {finding["id"]}：{finding.get("detail", "")} 状态：{finding["status"]}；处理：{finding.get("resolution", "")}']
        if safety:
            lines += ['', '源文作者的逐题核对保存其当时字节绑定；随后S01登记修复由上述独立审读复核，最终资料绑定以独立审读和set.sha256为准。']
        lines.append('')
    write(root / 'authoring/self-review.json', {'works': reviews, 'tasks': task_reviews})
    (root / 'authoring/self-review.md').write_text('\n'.join(lines) + '\n', encoding='utf-8', newline='\n')
    return data


if __name__ == '__main__':
    import sys
    data = assemble(sys.argv[1])
    print(json.dumps({'works': len(data['works']), 'tasks': len(data['tasks'])}, sort_keys=True))
