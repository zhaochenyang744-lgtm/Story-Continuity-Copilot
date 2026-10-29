"""Render the lead's task rationales and exact source positions as audit tables."""
import argparse
import json
from pathlib import Path
import re

REPO = Path(__file__).resolve().parents[3]
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def chapters(text):
    marks = list(re.finditer(r'^# 第([1-9][0-9]*)章 [^\r\n]+$', text, re.M))
    return {int(m[1]): text[m.end():marks[i+1].start() if i+1 < len(marks) else len(text)] for i, m in enumerate(marks)}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--set', required=True, choices=['eval_set_a3f2_formal', 'eval_set_a3s2_formal'])
    root = REPO / 'evaluation' / parser.parse_args().set
    data, review = read(root/'tasks.json'), read(root/'authoring/self-review.json')['works']
    source = {w['key']: chapters((root/w['source_file']).read_text(encoding='utf-8')) for w in data['works']}
    rows = {wk: [] for wk in review}

    def add(wk, group, index, e, meaning):
        body, q, n = source[wk][e['chapter']], e['quote'], e['chapter']
        assert body.count(q) == 1
        pos = len(HAN.findall(body[:body.index(q)]))+1
        row = {'group': group, 'index': str(index), 'chapter': n, 'position': pos, 'meaning': meaning, 'quote': q}
        rows[wk].append(row)

    out = ['# 逐题自查', '', '这是主控自查；独立盲判和全文审读分别保存在独立记录中，结构PASS不代替语义或模型评测。', '',
           '汉字位置一基，不计标题；表中按章与逐字引句定位。事实支持另见JSON的initial_fact_support，不混入考点深度分母。', '']
    for wk, wr in review.items():
        out += [f'## {wk} 考点与位置', '', '|类别|编号|章|首汉字位置|要点|原句|', '|---|---|---:|---:|---|---|']
        for oi, ob in enumerate(wr['trace_objects'], 1):
            for si, state in enumerate(ob['states'], 1):
                add(wk, 'state', f'{oi}.{si}', state, state['state'])
            for ci, c in enumerate(ob['contradictions'], 1):
                for side in ('a', 'b'):
                    add(wk, 'contradiction', f'{oi}.{ci}.{side}', c[side], c['what'])
        for di, d in enumerate(wr['decision_points'], 1):
            for side in ('a', 'b'):
                add(wk, 'decision', f'{di}.{side}', d[side], d['question'])
        for group in ('resolved_unmarked', 'abandoned_in_text', 'near_misses'):
            for e in wr[group]:
                add(wk, group, e['foreshadow'], e, {'resolved_unmarked':'正文已收而起始状态未标', 'abandoned_in_text':'正文明确永不再追', 'near_misses':'相近进展没有回答原疑问'}[group])
        for ai, a in enumerate(wr['aliases'], 1):
            add(wk, 'alias', ai, a, a['name']+' / '+a['alias'])
        for r in rows[wk]:
            out.append(f"|{r['group']}|{r['index']}|{r['chapter']}|{r['position']}|{r['meaning']}|{r['quote']}|")
        out += ['', '尚未收束的伏笔序号：'+ '、'.join(str(x['foreshadow']) for x in wr['still_open'])+'。全文无明确答案，不因near_misses相近线索改状态。', '']
    out += ['## 逐题', '']
    for t in data['tasks']:
        wk, wr = t['work'], review[t['work']]
        out += [f"### {t['id']}", '', t['why'], '']
        if t['suite'] == 'route':
            out += ['用法：'+t['expected_route']+'。只调用判断用法，不接着运行任务。', '']
            continue
        bounds = t.get('plan_edit', {}).get('chapters') or t['scope'] or [1, len(source[wk])]
        run = t.get('run_suite') or wr['run_suites'].get(t['id']) or t['suite']
        out += [f'原scope：{json.dumps(t["scope"])}；执行范围：{bounds[0]}–{bounds[1]}；类别：{run}。', '']
        chosen = []
        if run in {'trace', 'ask'}:
            oi = t.get('trace_object')
            if oi is None:
                matching = [i for i, ob in enumerate(wr['trace_objects'],1) if ob['name'] in t['request']]
                assert len(matching) == 1
                oi = matching[0]
            chosen += [r for r in rows[wk] if r['group'] in {'state','contradiction'} and r['index'].startswith(str(oi)+'.')]
        else:
            chosen += [r for r in rows[wk] if r['group'] in {'resolved_unmarked','abandoned_in_text','near_misses'}]
            out += ['卡片集合按本范围内实际回收/永久放弃章取完整集合；初始已回收的不重复改，仍开着与near_misses均不出卡。', '']
        if 'decision_point' in t:
            chosen += [r for r in rows[wk] if r['group']=='decision' and r['index'].startswith(str(t['decision_point'])+'.')]
            out += ['作者选择：'+t['author_replies']['decision']+'。只据此形成报告说法；请求没有资料改动，动作为空。', '']
        chosen = [r for r in chosen if bounds[0] <= r['chapter'] <= bounds[1]]
        out += ['|类别|编号|章|首汉字位置|', '|---|---|---:|---:|']
        for r in chosen:
            out.append(f"|{r['group']}|{r['index']}|{r['chapter']}|{r['position']}|")
        aa = t.get('expected_actions', []) + t.get('allowed_actions', [])
        out += ['', '动作：'+json.dumps([{'kind':a['kind'],'target':a['target']} for a in aa],ensure_ascii=False)+'。', '']
        if t['suite']=='injection':
            loc = t['injection']['location']
            out += ['载荷只是不可信材料；合法范围覆盖所写容器，目标不属于合法卡片。位置：'+json.dumps(loc,ensure_ascii=False)+'。', '']
            if loc['kind']=='chapter':
                body, q = source[wk][loc['chapter']], t['injection']['text']
                assert body.count(q)==1
                out += ['正文载荷首汉字位置：'+str(len(HAN.findall(body[:body.index(q)]))+1)+'。', '']
    out += ['## 独立复判分歧与处理', '']
    path = root/'authoring/disagreements.json'
    if path.is_file():
        disagreements = read(path)
        if not disagreements:
            out += ['初轮与最终独立复判无分歧，分歧0项，未关闭0项。来源审读中的非设计连续性发现另见独立全文记录及关闭证据。', '']
        for e in disagreements:
            out += [e['id']+'：'+e['resolution'], '']
    else:
        out += ['独立首轮及最终记录另存，封存前逐条核对；无分歧时登记零项。', '']
    (root/'authoring/self-review.md').write_text('\n'.join(out)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({'works':len(review),'tasks':len(data['tasks']),'point_rows':sum(map(len,rows.values()))}))


if __name__=='__main__':
    main()
