"""Render authored per-case rationales and mechanically audited quote positions."""
from pathlib import Path
import json
import re

ROOT = Path(__file__).resolve().parents[1]
data = json.loads((ROOT / 'tasks.json').read_text(encoding='utf-8'))
review = json.loads((ROOT / 'authoring/self-review.json').read_text(encoding='utf-8'))
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
lines = ['# 正式集主控逐题自查', '',
    '主控先写设定与起始资料草案，正文作者按四章交接逐章手写，主控接收后登记实际变化与下一批约束。'
    '题目、理由及语义要点由主控逐题写定，程序只序列化既定文字并检查结构、重复、位置和哈希。', '',
    '每题重置起始资料。主要动作按expected_actions第一项计；二动作题要求两项分别有依据。'
    '章内位置是去标题后首汉字一基位置；引用按出现次数统计，并另列唯一引文。'
    '专名在八汉字照抄比较中作为断点，不能删后拼接；新颖性只去空白和Unicode标点，保留大小写。', '',
    '五条过时事实仍保留旧值；六条正文缺项不提前塞进资料；四条已收未标仍保留旧状态；另三条真正未解。'
    '职业、具体职责、实际保管、存放位置和身份鉴别分别核对。共享草稿不是已完成正文证据。', '']

for work in data['works']:
    wk = work['key']
    source = (ROOT / work['source_file']).read_text(encoding='utf-8')
    starts = list(re.finditer(r'^# 第([0-9]+)章 ([^\r\n]+)$', source, re.M))
    chapters = {m[0][2:]: source[m.end():starts[i+1].start() if i+1 < len(starts) else len(source)]
                for i, m in enumerate(starts)}
    bynumber = {int(m[1]): m[0][2:] for m in starts}
    lines += ['## ' + wk, '', '| id | 逐题理由 | 依据定位 |', '| --- | --- | --- |']
    for task in [t for t in data['tasks'] if t['work'] == wk]:
        loc = []
        for entry in task.get('expected_actions', []):
            for chapter, quote in zip(entry['evidence_chapters'], entry['evidence_quotes']):
                body = chapters[chapter]
                assert body.count(quote) == 1
                pos = len(HAN.findall(body[:body.index(quote)])) + 1
                loc.append(chapter + ' / ' + str(pos))
        if task['suite'] == 'no_action':
            category = task['no_action_type']
            if category == 'already_recorded':
                loc += ['已有F' + ','.join(map(str, task['request_targets']['facts']))]
            elif category == 'no_evidence':
                loc += ['全20章未交代' if task['id'].endswith('03') else '固定正文与请求相反；F' + ','.join(map(str, task['request_targets']['facts']))]
            elif category == 'prose_edit':
                loc += ['正文编辑，不出资料卡']
            else:
                loc += ['不支持的动作；不改成相近动作']
        if task['suite'] == 'route':
            loc += ['input/context；expected_route=' + task['expected_route']]
            if 'selection' in task['context']:
                selection = task['context']['selection']
                assert selection in work['shared_draft']['body']
                loc += ['草稿完整选句 / ' + str(len(selection)) + '字符']
        lines.append('| ' + task['id'] + ' | ' + task['why'] + ' | ' + '；'.join(loc) + ' |')
    lines += ['', '本部自查引文位置（包含别名，用于复核统计分母）：', '', '| 项目 | 章 | 首汉字位置 |', '| --- | ---: | ---: |']
    wr = review['works'][wk]
    for field in ('stale_facts', 'missing_facts', 'resolved_unmarked', 'aliases'):
        for i, row in enumerate(wr[field], 1):
            number = row.get('changed_chapter', row.get('chapter'))
            body = chapters[bynumber[number]]
            assert body.count(row['quote']) == 1
            pos = len(HAN.findall(body[:body.index(row['quote'])])) + 1
            lines.append(f'| {field}:{i} | {number} | {pos} |')
    lines += ['']

blind = json.loads((ROOT / 'authoring/blind-route-audit.json').read_text(encoding='utf-8'))
lines += ['## 独立路由复判', '',
    '未参与出题的复判者只读打乱顺序的id/input/context，两部各10条，完整20条预测先分别绑定盲文件SHA256，之后才开放正式作品与金标。', '',
    f"首次一致{blind['initial_agreement']}/{blind['total']}；最终一致{blind['final_agreement']}/{blind['total']}；分歧{len(blind['disagreements'])}；未决{blind['unresolved']}；盲判后金标修改{blind['gold_changes_after_blind']}。",
    '本次没有不一致题目。两组同句分别为w01的07/09和w02的07/09；无选区的overview按默认问答，带草稿完整选句的writing按片段检查。不是用also_acceptable掩盖分歧。', '',
    '## 语义复核与冻结', '',
    '每部由未参与本部正文或草稿写作的另一名审读者全文通读；独立报告记录真实覆盖、发现与回查。'
    '最终由independent-review.json绑定源数据、自查与旧题快照；语义修改后重新审读受影响部分、定位、绑定、manifest、完整checker及相关负例。'
    '结构PASS只表示静态作者约束检查通过，不表示模型质量或正式评测过关。', '']
(ROOT / 'authoring/self-review.md').write_text('\n'.join(lines), encoding='utf-8', newline='\n')
print(json.dumps({'reviewed_cases': len(data['tasks']), 'blind_agreement': blind['final_agreement']}))
