"""Create a sealed-set report containing only structure, counts and hashes."""
from pathlib import Path
import hashlib
import json
import re
import subprocess

REPO=Path(__file__).resolve().parents[3]
ROOTS=[REPO/'evaluation'/n for n in ('eval_set_a26_formal','eval_set_a2s6_formal')]
DEST=Path(r'C:\Users\赵晨阳\Desktop\v2.1任务\32-交付报告.md')

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    history=subprocess.check_output(['git','log','-2','--format=%H%x09%s'],cwd=REPO,text=True,encoding='utf-8').splitlines()
    commits=[line.split('\t',1) for line in history]
    assert commits[0][1]=='eval: author and freeze the sixth A2 safety set'
    assert commits[1][1]=='eval: author and freeze the sixth A2 formal set'
    branch=subprocess.check_output(['git','branch','--show-current'],cwd=REPO,text=True,encoding='utf-8').strip()
    assert branch=='eval/a2-6-authoring'
    lines=['# 32 交付报告','', '日期：2026-10-27。分支：`eval/a2-6-authoring`。', '',
           f'- 正式集提交：`{commits[1][0]}`。',f'- 安全集提交：`{commits[0][0]}`。',
           '- 本地提交2；推送0；合并0；切分支0；模型接口0；产品运行0；评测运行0。','']
    for root in ROOTS:
        run=load(root/'authoring/checker-runs.json')
        assert run['root']['status']=='PASS' and run['absolute']['status']=='PASS'
        assert run['root']==run['absolute']
        independent=load(root/'authoring/independent-review.json')
        assert independent['status']=='completed' and independent['unresolved_findings']==0
        lines += [f'## {root.name}','', '### 封存清单','', '```text', (root/'set.sha256').read_text(encoding='utf-8').rstrip(), '```','',
                  f'清单自身 SHA-256：`{sha(root/"set.sha256")}`。','', '### 数量与分布','']
        stats=run['root']
        for wk,s in stats['works'].items():
            lines += [f'#### {wk}','', '```json',json.dumps(s,ensure_ascii=False,sort_keys=True,indent=2),'```','']
            if 'no_action_thread_types' in s:
                zero_filled={key:s['no_action_thread_types'].get(key,0) for key in ('already_recorded','no_evidence','prose_edit','unsupported_kind')}
                lines += ['关于伏笔的no_action数量（按request_targets.foreshadows非空计）：','',
                          '```json',json.dumps(zero_filled,ensure_ascii=False,sort_keys=True),'```','']
        if 'chapter_injection_positions' in stats:
            injection={k:stats[k] for k in ('injection_locations','run_kinds','injection_targets','change_tasks_with_new_actions','chapter_injection_positions')}
            lines += ['```json',json.dumps(injection,ensure_ascii=False,sort_keys=True,indent=2),'```','']
        for field in ('blind_route','new_action_blind'):
            if field in independent:
                b=independent[field]
                lines += [f'复判 `{field}`：不一致{len(b.get("disagreement_ids",[]))}；已处理关闭{len(b.get("closed_ids",[]))}；未闭{b["unresolved"]}。','',
                          '```json',json.dumps(b,ensure_ascii=False,sort_keys=True,indent=2),'```','']
        ref=load(root/'authoring/novelty-reference.json')
        seal=load(root/'authoring/sealed-comparison.json')
        lines += [f'新专名重合：{ref["names_overlap"]+seal["names_overlap"]}；照抄错误：{stats["copy_errors"]}；新颖性错误：{stats["novelty_errors"]+seal["novelty_errors"]}。','',
                  '### 检查器完整输出','', '根目录模块运行与非根目录绝对路径运行输出相同，退出码均0。','',
                  '```json',json.dumps(stats,ensure_ascii=False,sort_keys=True),'```','']
    negative=load(ROOTS[0]/'authoring/negative-check-results.json')
    assert negative['status']=='PASS' and negative['temporary_copies_remaining']==0
    lines += ['## 负向测试','', '```json',json.dumps(negative,ensure_ascii=False,sort_keys=True,indent=2),'```','',
              '## 规则差异与处理','',
              '1. 任务单先读第5项把新目录称作第五套。依据补充九及同项检查器迁移说明，参考a25/a2s5，产出a26/a2s6。',
              '2. SPEC正文旧规模为12动作、8–12伏笔；采用补充七及任务单的18动作、10–14伏笔。',
              '3. 任务单提到封存A3的程序比对，同时明确禁止寻找新A3两目录。按明确禁找要求在遍历前排除；零重合不覆盖这两目录。旧A3正式和安全集按任务单明确可读范围纳入；第五套A2按补充九作为已用参考。三个旧封存目录仅程序比对并输出计数。',
              '4. 1500后至少一半是最低要求；保留所引A1c第2节及第五套检查器的去重依据2500后至少三分之一。A1c其他旧规模不移入：采用20/12章、600–1000汉字草稿。',
              '5. 按正文改edit_thread须有依据；仅作者直接给话的edit_thread和abandon_thread允许空依据。author_words在正式动作题级；安全合法edit样例只采用按正文模式。resolve_thread按补充四/五的程序要点格式；补充八和补充十涉及撤销或打分展示，不另改本次题量。',
              '6. 主要动作按expected_actions首项统计；多改动分别对应两件事；别名对应同时见于正文和起始事实。route采用A2六类及每部至少1组同句，不搬A1c的旧分布与2组要求。',
              '7. 新动作盲判比较作者意图和对象；未给出正文的复判者不猜埋线章。章号与原句另由全文审读和检查器核对。未改输入时，初判原样作为最终结论保留，不将它说成第二次新盲判。',
              '', '## 验证边界','',
              '独立全文审读、自查与静态结构验证已完成；checker的semantic_acceptance为false，仅表示自动检查不作语义验收或模型效果保证。正式评测未运行。','']
    text='\n'.join(lines)
    private=[]
    for root in ROOTS:
        d=load(root/'tasks.json')
        for w in d['works']:
            private.extend(w['names']+[w['title']])
            private.extend(s.strip() for s in re.split(r'[\n]',w['shared_draft']['body']) if len(s.strip())>=8)
        for t in d['tasks']:
            private.extend(t[k] for k in ('request','input','why') if isinstance(t.get(k),str))
            if t.get('context',{}).get('selection'): private.append(t['context']['selection'])
            for a in t.get('expected_actions',t.get('allowed_actions',[])):
                private.extend(a['after_points']+a['evidence_quotes'])
    hits=sum(bool(s) and s in text for s in private)
    assert hits==0, 'report_content_leak'
    assert not re.search(r'Co-Authored-By|Generated by|AI署名',text,re.I)
    DEST.write_text(text,encoding='utf-8',newline='\n')
    print(json.dumps({'report_sha256':sha(DEST),'leak_hits':hits,'commits':2},ensure_ascii=False))

if __name__=='__main__':
    main()
