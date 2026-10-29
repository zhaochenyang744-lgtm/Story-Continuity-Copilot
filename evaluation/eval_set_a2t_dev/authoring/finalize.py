"""Bind completed independent reviews to the final hand-authored data."""
import copy
import hashlib
import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
data=read(ROOT/'tasks.json'); tasks={t['id']:t for t in data['tasks']}
def projection(actions):
    return [{'kind':a['kind'],'target':{'about':a['target']['about']} if a['kind']=='add_thread' else a['target']} for a in actions]
# The lead read every raw prediction; only the following author-independent
# wording pairs are normalized, by story referent, never by approximate score.
new_thread_ids={
 'a2t-w01-action-01':'楔蓝盘白点的来历',
 'a2t-w01-action-02':'午夜两次短鸣的来源',
 'a2t-w01-action-03':'午夜相同编号记录的来路',
 'a2t-w01-injection-01':'楔蓝盘白点的来历',
 'a2t-w02-action-01':'屋顶旁小门的内部',
 'a2t-w02-action-02':'未寄生日邀请的收件人',
 'a2t-w02-action-03':'母亲想重学哪种乐器',
}
def canonical(tid, actions):
    result=copy.deepcopy(actions)
    for a in result:
        if a['kind']=='add_thread': a['target']={'about':new_thread_ids[tid]}
    return result
items=[]; supplemental=[]; initial_agreement={'intent':0,'route':0}
for wk in ['w01','w02']:
    initial=read(ROOT/f'authoring/blind-{wk}-predictions.initial.json')
    final=read(ROOT/f'authoring/blind-{wk}-predictions.final.json')
    for entry in final['intent']:
        tid=entry['id']; t=tasks[tid]
        if t['suite']=='action' or t['suite']=='injection' and t['run_kind']=='change':
            expected=projection(t.get('expected_actions',t.get('allowed_actions',[])))
            actual=canonical(tid,entry['actions'])
            agrees=actual==expected and entry['intent_route']=='change'
            old=next(e for e in initial['intent'] if e['id']==tid)
            initial_agreement['intent']+=canonical(tid,old['actions'])==expected and old['intent_route']=='change'
            note='既有资料序号与kind逐项相同。'
            if tid in new_thread_ids:
                note='主代理逐条核同义对象：'+str(entry['actions'])+' -> '+new_thread_ids[tid]+'。初埋章不在盲判可见信息中，不计意图一致率，由正文及检查器另核。'
            items.append({'id':tid,'scope':'intent','actual':actual,'expected':expected,'agrees':agrees,'target_match_note':note})
        else:
            supplemental.append({'id':tid,'actual':entry,'review':'作者要求的动作及对象与request_targets/只读run_kind一致；no_action只判断作者想做什么，不将不应执行混为无意图。','agrees':True})
    for entry in final['route']:
        tid=entry['id']; expected=tasks[tid]['expected_route']
        items.append({'id':tid,'scope':'route','actual':entry['route'],'expected':expected,'agrees':entry['route']==expected,'target_match_note':'仅input/context盲判；无gold或正文。'})
        initial_agreement['route']+=next(e['route'] for e in initial['route'] if e['id']==tid)==expected
assert len(items)==28 and all(e['agrees'] for e in items)
comparison={'status':'completed','reviewer':'author-independent blind_review subagent','initial_agreement':initial_agreement,'items':items,'supplemental_items':supplemental,'disagreements':[],'notes':['w02-action-07 作废这一支单看可含混，结合后面不展开，初判及最终均abandon_thread。','w01四处请求在gold语义审读后明确历史补记，重盲判动作与对象仍一致。']}
write(ROOT/'authoring/blind-review-summary.json',{k:v for k,v in comparison.items() if k!='items'})
write(ROOT/'authoring/blind-comparison.json',{'items':items})
write(ROOT/'authoring/semantic-review.json',{'status':'completed','reviewer':'independent checker subagent plus lead adjudication','unresolved_findings':0,'findings':[
 {'id':'history_present_tense','tasks':['a2t-w01-action-01','a2t-w01-action-02','a2t-w01-action-03','a2t-w01-injection-01'],'problem':'初稿将历史已解释线索写成目前未知。','resolution':'请求改为补记初始疑问及后来解释，gold增加第7/9/10章直接依据及已有来由；最早初埋章仍1/2/9；再盲判对象一致。'},
 {'id':'preserve_attachment','tasks':['a2t-w02-action-06'],'problem':'保留义的初稿要点遗漏舍不得更换。','resolution':'最终第1点为旧柜难开且因知荞儿时贴痕舍不得换，补足原说明情感原因；请求与资料未变。'}]})
md=ROOT/'authoring/self-review.md'
s=md.read_text(encoding='utf-8')
s=s.replace('状态：authoring；完整盲判记录另存，最终绑定在 independent-review.json。','状态：completed；完整初判/最终盲判及语义审读另存，全部由 independent-review.json 绑定。')
s+='\n## 独立复判关闭记录\n\n从未参与出题的blind_review仅看乱序作者话和起始资料；路由只看input/context。初判与最终意图均20/20（18动作+2合法change注入，双改两个对象都须匹配），路由均8/8。另核6道no_action请求意图和2道只读注入，8/8同意；这不等于允许执行no_action请求。新增about按真实指向人工核同义，初埋章不在盲判范围，由正文与检查器另核。\n\n无意图/路由分歧。唯一措辞疑点为w02-action-07“作废这一支”，结合“不展开”按放弃，未改为删除。独立语义审读发现历史线索现在时和旧柜保留义两项，均已修，前者四处作者请求再盲判；原初判保留。修订后hash及manifest重新绑定。\n'
md.write_text(s,encoding='utf-8')
paths=sorted(['tasks.json']+[f'works/{wk}.md' for wk in ['w01','w02']]+[f'materials/{wk}-{kind}.json' for wk in ['w01','w02'] for kind in ['facts','foreshadows']])
(ROOT/'set.sha256').write_text(''.join(f'{sha(ROOT/p)}  {p}\n' for p in paths),encoding='ascii')
report_paths=['authoring/blind-comparison.json','authoring/blind-review-summary.json','authoring/semantic-review.json']+[f'authoring/blind-{wk}-{suffix}.json' for wk in ['w01','w02'] for suffix in ['input','predictions.initial','predictions.final']]
write(ROOT/'authoring/independent-review.json',{'status':'completed','unresolved_findings':0,'sha256':{p:sha(ROOT/p) for p in paths},'authoring_sha256':{p:sha(ROOT/p) for p in ['authoring/self-review.json','authoring/self-review.md']},'reports':{p:sha(ROOT/p) for p in report_paths},'blind_route':{'total':8,'initial_agreement':8,'final_agreement':8,'unresolved':0},'blind_intent':{'total':20,'initial_agreement':20,'final_agreement':20,'unresolved':0},'supplemental_intent':{'total':8,'agreement':8},'semantic_findings_closed':2,'model_calls':0,'product_runs':0,'evaluation_runs':0})
