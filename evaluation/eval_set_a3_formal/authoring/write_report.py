"""Write the authorized delivery report using only identifiers, counts, and hashes."""
from pathlib import Path
import hashlib
import json
import re
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[3]
DEST=Path(r'C:\Users\赵晨阳\Desktop\v2.1任务\06-交付报告.md')
FORMAL=ROOT/'evaluation/eval_set_a3_formal';SAFE=ROOT/'evaluation/eval_set_a3s_formal'


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def dumps(v):
    return json.dumps(v,ensure_ascii=False,sort_keys=True)


def main():
    commits=sys.argv[1:3]
    if len(commits)!=2 or not all(re.fullmatch('[0-9a-f]{40}',x) for x in commits):raise ValueError('commits')
    outputs=[]
    for d in (FORMAL,SAFE):
        p=subprocess.run([sys.executable,'-X','utf8','-B',str(d/'check.py')],cwd=ROOT,capture_output=True,text=True,encoding='utf-8')
        o=json.loads(p.stdout)
        if p.returncode or o['status']!='PASS':raise ValueError('check')
        outputs.append(o)
    lines=['# 06 交付报告','','2026-10-24（Australia/Sydney）。留用集内容封存；以下仅编号、数字、结构与哈希。','',
      '## 提交','',f'- `eval_set_a3_formal`：`{commits[0]}`。',f'- `eval_set_a3s_formal`：`{commits[1]}`。',
      '- 分支：`eval/a3-authoring`。本地提交2次；推送0、合并0、切分支0。','',
      '## 哈希清单','']
    for d in (FORMAL,SAFE):lines += ['`'+d.name+'/set.sha256`：','','```text',(d/'set.sha256').read_text(encoding='utf-8').strip(),'```','']
    lines+=['## 作品与资料计数','','|集合|作品编号|章数|每章汉字最少|最多|正文汉字总数|共享草稿汉字|',
            '|---|---|---:|---:|---:|---:|---:|']
    for d,o in zip((FORMAL,SAFE),outputs):
        for wk,w in o['works'].items():lines.append('|'+d.name+'|'+wk+'|'+'|'.join(str(w[k]) for k in ('chapters','chapter_han_min','chapter_han_max','total_han','draft_han'))+'|')
    lines+=['','|集合|作品编号|事实|伏笔|人物|别名|追踪对象|状态|矛盾|已收未标|仍开放|明确放弃|过时事实|缺失事实|干扰项|决定点|',
            '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for d,o in zip((FORMAL,SAFE),outputs):
        for wk,w in o['works'].items():lines.append('|'+d.name+'|'+wk+'|'+'|'.join(str(w[k]) for k in ('facts','foreshadows','characters','aliases','trace_objects','trace_states','contradictions','resolved_unmarked','still_open','abandoned_in_text','stale_facts','missing_facts','decoys','decision_points'))+'|')
    lines+=['','## 正式集分布','']
    for wk,w in outputs[0]['works'].items():
        lines += ['- '+wk+'：'+dumps({'suites':w['suites'],'scope_given':w['scope_given'],'scope_all':w['scope_all'],'expected_action_kinds':w['expected_action_kinds'],'routes':w['routes'],'same_input_groups':w['same_input_groups']})]
    lines+=['','## 安全集分布','',dumps({k:outputs[1][k] for k in ('injection_locations','run_suites','injection_targets','chapter_injection_positions')}),'',
            '## 考点句位置','']
    for d,o in zip((FORMAL,SAFE),outputs):
        for wk,w in o['works'].items():lines.append('- '+d.name+'/'+wk+'：'+dumps({k:w[k] for k in ('point_quotes','point_after1500','point_after2500','point_han_min','point_han_max','point_position_buckets')}))
    ind=load(FORMAL/'authoring/independent-review.json');blind=ind['blind_route']
    lines+=['','## 独立复判与静态审查','',dumps(blind),
            '- 正式集全文独立通读覆盖：'+dumps(ind['chapter_coverage'])+'；未关闭问题：'+str(ind['unresolved_findings'])+'。',
            '- 安全集全文独立通读覆盖：'+dumps(load(SAFE/'authoring/independent-review.json')['chapter_coverage'])+'；未关闭问题：'+str(load(SAFE/'authoring/independent-review.json')['unresolved_findings'])+'。','']
    for d,o in zip((FORMAL,SAFE),outputs):
        ref=load(d/'authoring/novelty-reference.json')
        lines.append('- '+d.name+'：'+dumps({'names_overlap':ref['names_overlap'],'reference_counts':ref['reference_counts'],'copy_errors':o['copy_errors'],'novelty_errors':o['novelty_errors'],'dev_branch_tasks_present':ref['dev_branch_tasks_present']}))
    cross=load(FORMAL/'authoring/final-audit.json')
    lines+=['- 两新套交叉审计：'+dumps(cross)+'。',
      '- 旧语料比对在遍历前排除3个禁读目录：`eval_set_a1_reserve`、`eval_set_a1b_reserve`、`eval_set_v13_authoring`；零重合不覆盖这些未读目录。','',
      '## 检查器完整输出','']
    for d,o in zip((FORMAL,SAFE),outputs):lines+=['`'+d.name+'`：','','```json',dumps(o),'```','']
    lines+=['根目录模块调用2/2 PASS；其他目录绝对路径调用2/2 PASS；见结构验证记录。','',
            '## 负向测试','', '前5项在临时副本破坏数据后同步重算哈希及绑定，确认语义结构检查本身拒绝；第6项保留原清单验证正文篡改。','',
            '```json',dumps(load(FORMAL/'authoring/negative-check-results.json')),'```','',
            '检查器审查后的补充回归：','','```json',dumps(load(FORMAL/'authoring/checker-regressions.json')),'```','',
            '## 登记歧义处理','',
            '1. 共享草稿按任务单600–1000汉字，覆盖引用旧规范的800–1200范围。',
            '2. 汉字只计U+3400–U+4DBF及U+4E00–U+9FFF；标题不计；引用首汉字一基，严格大于1500计后段，并沿A1c保留至少三分之一大于2500的要求。',
            '3. `evidence_chapters`沿A2使用完整章标题；资料、考点、目标及`scope`使用一基整数。',
            '4. 安全集追踪按任务单放宽至4–6状态；不套用30章正式作品的跨15章要求。',
            '5. 安全指令同时满足SPEC列举类别与thresholds的全部八种`injection_target.kind`，从严覆盖8种。',
            '6. `narrowed`运行类别存于封存自查的`run_suites`，题目不添加未登记运行字段；`expected_actions`独立完整，`allowed_actions`另查范围，不替代必需动作。',
            '7. `trace`请求只交报告，`allowed_actions`为空；正式集`ask`请求询问后只报告，`expected_actions`为空，符合SPEC允许为空的说明；安全`skip_asking`按预存作者回答列合法动作。',
            '8. `scope`非空的题按明确区间，`null`代表全书；`narrowed`的原始全书请求计入全书数，实际动作与依据只按`plan_edit`。',
            '9. `stale_facts.changed_chapter`记首次过时章；正式集另以authoring.fact_updates登记首次值和后续明确更新，每部5条、其中后续2条。同一fact按执行范围内最后明确值出1卡，绑定该次证据和after_points，不因首次章在范围外而漏算后续更新。',
            '10. 资料中载荷按明确要求作为误收旁注保留，非指令部分由正文支持；不同动作名指向同一资料也判注入目标重合。',
            '11. 新颖性去空白和Unicode标点，保留大小写；SequenceMatcher达到0.8即失败。封存检查器只读本套旧输入快照，来源哈希绑定；两新套另做交叉比对。',
            '12. 结构PASS与独立语义通读分别记录；模型接口调用0、产品运行0、评测运行0。','']
    lines += ['13. 题量、章数、起始资料、追踪矛盾及决定点按A3明确要求；不套用旧A1/A1c的计划、FIX或有意矛盾总数。位置分母按章号与原句去重，别名引文计入，纯初始事实支持不充当考点，注入位置另外计数。','']
    lines += ['14. 开发分支的指定路径通过git show核验；dev_branch_tasks_present只表示该分支树中是否已有此已提交文件，不推断其他worktree的未提交状态。未进入其他worktree。','']
    lines += ['15. 为隔离询问指标，正式集非ask的事实整理题不同时覆盖决定点两端；决定点由专门ask题覆盖。安全skip_asking题另有明确决定点和预存作者回答。此为成卷范围选择，不修改登记规则。','']
    text='\n'.join(lines)
    sensitive=[]
    for d in (FORMAL,SAFE):
        data=load(d/'tasks.json')
        for w in data['works']:sensitive += w['names']+[w['title']]
        def collect(v):
            if isinstance(v,dict):
                for k,x in v.items():
                    if k in {'request','input','quote','question','text'} and isinstance(x,str):sensitive.append(x)
                    elif k in {'after_points','evidence_quotes'} and isinstance(x,list):sensitive.extend(s for s in x if isinstance(s,str) and len(s)>=8)
                    else:collect(x)
            elif isinstance(v,list):
                for x in v:collect(x)
        collect(data);collect(load(d/'authoring/self-review.json'))
        for w in data['works']:
            body=(d/w['source_file']).read_text(encoding='utf-8')
            sensitive.extend(s for s in re.split(r'[\n。！？]',body) if len(s)>=20)
            sensitive.extend(s for s in re.split(r'[\n。！？]',w['shared_draft']['body']) if len(s)>=20)
    hits=sum(bool(s) and s in text for s in sensitive)
    if hits or re.search(r'Co-Authored-By|Generated.by|AI署名',text,re.I):raise ValueError('report leakage')
    DEST.write_text(text,encoding='utf-8')
    print(dumps({'report_written':1,'leakage_hits':hits,'checker_pass':2,'negative_detected':load(FORMAL/'authoring/negative-check-results.json')['detected']}))


if __name__=='__main__':main()
