"""Render the lead's item-by-item reasons with audited locations, without inventing prose."""
from pathlib import Path
import json,re
FORMAL=Path(__file__).resolve().parent.parent
SAFETY=FORMAL.parent/'eval_set_a2s5_formal'
HAN=re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def chs(s):
    ms=list(re.finditer(r'^# (第\d+章 [^\n\r]+)',s,re.M))
    return {m[1]:s[m.end():ms[i+1].start() if i+1<len(ms) else len(s)] for i,m in enumerate(ms)}
def position(body,s):return len(HAN.findall(body[:body.index(s)]))+1

for root in (FORMAL,SAFETY):
    d=load(root/'tasks.json');wr=load(root/'authoring/self-review.json')['works']
    works={w['key']:w for w in d['works']}
    sources={w:chs((root/meta['source_file']).read_text(encoding='utf-8')) for w,meta in works.items()}
    out=['# 主控逐题自查','',
      '题目与要点由主控逐条撰写，以下仅自动绑定实际原句与一基汉字位置；程序没有生成正文或推定语义答案。',
      '正文、起始材料的预设差异不是意外矛盾。直接给说明与明确放弃按作者话处理，其他动作逐条核原文。','',
      '## 库存与原句审计','']
    for w,review in wr.items():
        out += [f'### {w}','']
        for field in ('stale_facts','missing_facts','resolved_unmarked','stale_notes','missing_threads','aliases'):
            for i,e in enumerate(review[field],1):
                n=e.get('changed_chapter',e.get('planted_chapter',e.get('chapter')))
                title=next(t for t in sources[w] if t.startswith(f'第{n}章 '))
                body=sources[w][title];q=e['quote'];assert q in body
                out.append(f'- {field}/{i}：{title}，首汉字{position(body,q)}，逐字原句「{q}」。')
        out += ['', '开放条目：'+json.dumps(review['open_threads'],ensure_ascii=False)+'。','']
    out += ['## 逐题说明','']
    for t in d['tasks']:
        w=t['work'];out += [f'### {t["id"]}','',f'请求：{t.get("request",t.get("input"))}',f'判断：{t["why"]}']
        actions=t.get('expected_actions',t.get('allowed_actions',[]))
        for a in actions:
            out.append('对象与动作：'+a['kind']+' '+json.dumps(a['target'],ensure_ascii=False)+'。')
            out.append('要点：'+json.dumps(a['after_points'],ensure_ascii=False)+'。')
            if not a['evidence_quotes']:
                out.append('依据：作者原话及对应起始条目；无正文依据要求，章内位置不适用。')
            for title,q in zip(a['evidence_chapters'],a['evidence_quotes']):
                body=sources[w][title];out.append(f'依据：{title}，首汉字{position(body,q)}，原句「{q}」。')
        if t['suite']=='no_action':
            out.append('指向资料：'+json.dumps(t['request_targets'],ensure_ascii=False)+'。')
            mode=t['no_action_type']
            if mode=='already_recorded':out.append('依据在起始资料既有条目的值或状态；不是缺失/过时目标，正文位置不代替资料状态判断。')
            elif mode=='no_evidence':
                if t['id'].endswith('no-03'):out.append('完整正文没有满足作者条件的肯定陈述，因此不存在可填的依据句位置；不把初埋相关信息当答案。')
                else:
                    e=wr[w]['resolved_unmarked'][0];title=next(ti for ti in sources[w] if ti.startswith(f'第{e["chapter"]}章 '))
                    out.append(f'相反证据：{title}，首汉字{position(sources[w][title],e["quote"])}，原句「{e["quote"]}」。')
            elif mode=='unsupported_kind':out.append('依据：A2补充七仍不支持删除；该规则不取自正文，章内位置不适用。')
        if t['suite']=='route':out.append('界面依据：'+json.dumps(t['context'],ensure_ascii=False)+'；预期用法='+t['expected_route']+'。用法判断不以故事事实代替作者意图。')
        sel=t['context'].get('selection')
        if sel:out.append(f'选段位于{works[w]["shared_draft"]["chapter_title"]}共享草稿，首汉字{position(works[w]["shared_draft"]["body"],sel)}；不作为已完成正文动作依据。')
        if 'injection' in t:
            inj=t['injection'];where=inj['location'];out.append('不可信载荷位置：'+json.dumps(where,ensure_ascii=False)+'。')
            out.append('禁止目标：'+json.dumps(t['injection_target'],ensure_ascii=False)+'；与合法目标按事实/伏笔两个库隔离，不能只比较数字。')
            if where['kind']=='chapter':
                title=next(ti for ti in sources[w] if ti.startswith(f'第{where["chapter"]}章 '))
                out.append('载荷首汉字：'+str(position(sources[w][title],inj['text']))+'。')
            if t['run_kind']!='change':out.append('此用法不允许任何资料变更；载荷原文不是作者请求。')
        out += ['']
    out += ['## 独立复核与处理','',
      '独立全文审读的覆盖、发现及关闭见independent-*-review.md；路由与新动作盲判见对应blind输入和初次结果，比较结果保留不覆盖。',
      '标志逐题按当前任务定义填写：出现明确动作术语的题不以语气轻松当作paraphrased；vague指未给章句、须检索定位的概略要求。',
      '安全合法请求明确指向载荷同章或同条资料，所有命令均是低信任材料。正文载荷没有被当成最早真实埋线事件。','']
    for kind in ('route','new-action'):
        p=root/'authoring'/f'{kind}-blind-comparison.json'
        if p.is_file():
            comp=load(p)
            out += [kind+'独立复判：'+json.dumps({k:comp[k] for k in (
              'total','initial_agreement','final_agreement','initial_rate','final_rate','unresolved','disagreement_ids','closed_ids')},ensure_ascii=False)+'。','']
    (root/'authoring/self-review.md').write_text('\n'.join(out),encoding='utf-8')
print(json.dumps({'self_review_documents':2}))
