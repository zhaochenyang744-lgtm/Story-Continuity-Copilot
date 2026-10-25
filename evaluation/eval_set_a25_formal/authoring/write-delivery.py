"""Render a content-restricted numeric delivery after all checks and commits."""
from pathlib import Path
import hashlib,json,re,subprocess
FORMAL=Path(__file__).resolve().parent.parent
SAFETY=FORMAL.parent/'eval_set_a2s5_formal'
REPO=FORMAL.parents[1]
DEST=Path(r'C:\Users\赵晨阳\Desktop\v2.1任务\13-交付报告.md')
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def dump(d):return json.dumps(d,ensure_ascii=False,sort_keys=True)
checks=load(FORMAL/'authoring/checker-runs.json')
commits={root.name:subprocess.check_output(['git','log','-1','--format=%H',
    '--grep=^eval: author and freeze the fifth A2 '+kind+' set$'],cwd=REPO).decode().strip()
    for root,kind in ((FORMAL,'formal'),(SAFETY,'safety'))}
assert all(re.fullmatch(r'[0-9a-f]{40}',v) for v in commits.values())
parts=['# 13 交付报告','', '日期：2026-10-25。版本：a2-2。两套均封存；报告只含编号、数字、结构、哈希和固定规则口径。','',
 '## 1. 本地提交与冻结','']
for root in (FORMAL,SAFETY):
    parts += [f'### {root.name}', '',f'提交：`{commits[root.name]}`。',
      f'`set.sha256` 文件SHA-256：`{sha(root/"set.sha256")}`。','', '```text',
      (root/'set.sha256').read_text(encoding='utf-8').rstrip(),'```','']
parts += ['## 2. 正文、资料、题型与位置统计','']
for sn,entry in checks['root'].items():
    parts += [f'### {sn}','','```json',dump(entry['result']),'```','']
parts += ['两个检查器完整输出如上。两套从根目录及外部工作目录以绝对路径运行的结果：','',
 '```json',dump({k:{n:{'exit_code':v['exit_code'],'status':v['result']['status']} for n,v in group.items()}
   for k,group in checks.items()}),'```','']
parts += ['## 3. 独立复核','']
for root in (FORMAL,SAFETY):
    d=load(root/'authoring/independent-review.json')
    summary={k:d[k] for k in ('chapter_coverage','task_coverage','facts_coverage','foreshadow_coverage',
       'findings','closed_findings','unresolved_findings','new_action_blind','checker_review') if k in d}
    if 'blind_route' in d:summary['blind_route']=d['blind_route']
    parts += [f'`{root.name}`：','', '```json',dump(summary),'```','']
parts += ['## 4. 排重与负向测试','', '```json',dump(load(FORMAL/'authoring/corpus-audit.json')),'```','',
 '```json',dump(load(FORMAL/'authoring/negative-check-results.json')),'```','',
 '## 5. 登记与任务单口径','',
 '- 补充七覆盖旧文数量：action每部18，正式每部34，两部68；伏笔每部10–14，本次各10。安全12题。版本a2-2。',
 '- 标回收使用两个原样程序要点；加伏笔的章号要点亦使用原样格式；标放弃恰好一条程序要点。',
 '- 补充七允许edit_thread无依据；本任务对按正文修正的类型要求依据，采用较严格口径。直接给说明的类型以题级author_words=true标明。',
 '- 沿用第四套及A1c写法：依据出现次数至少一半在1500字后，去重依据至少三分之一在2500字后。完整标题不计入汉字数，位置按首汉字一基计。',
 '- A1c引用用于写法、别名、干扰和照抄规则；章数、草稿及材料设置采用A2任务单，不套用旧A1c的30章、第31章计划或有意正文矛盾数量。',
 '- 任务检查小节允许已收未标索引指向planned；补充七要求至少4条记录仍为planted/developing。检查器同时保留planned扩展并聚合要求至少4条指向planted/developing。本次数据满足；必需7项负向测试外另加第8项专测此约束。',
 '- 主要动作按数组首项计，次要动作同样校验。起始资料各题重新装载，不把不同题的变更视为连续发生。',
 '- 封存的五个禁读目录仅由程序进行专名和新颖性比对，输出计数及来源hash；检查器只读本套计数凭证和可读旧语料快照。未复制禁读语料原文。',
 '- 起始资料中的指定指令是注入载荷，其余事实与正文逐条对应。草稿不作已完成正文的改动依据。',
 '- 同句组的相同输入是规则要求；新颖性针对既有题集及两新套交叉比较。',
 '- 0次外部模型接口调用、0次产品运行、0次评测运行、0次推送、0次合并、0次切分支。检查器PASS是结构及离线约束结果。','']
text='\n'.join(parts)
# Never expose a source-derived string in the delivery report.
categories={'names':[],'titles':[],'requests':[],'why':[],'points':[],'quotes':[],'draft':[], 'injection':[], 'prose':[]}
for root in (FORMAL,SAFETY):
    d=load(root/'tasks.json')
    for w in d['works']:
        categories['names']+=w['names'];categories['titles'].append(w['title'])
        categories['draft']+=re.findall(r'[^\n。！？]+[。！？]',w['shared_draft']['body'])
        source=(root/w['source_file']).read_text(encoding='utf-8')
        categories['titles']+=re.findall(r'^# (.+)$',source,re.M)
        categories['prose'] += [s for s in re.findall(r'[^\n。！？]+[。！？]',source) if len(s)>=10]
    for t in d['tasks']:
        categories['requests'].append(t.get('request',t.get('input','')))
        categories['why'].append(t['why'])
        if 'injection' in t:categories['injection'].append(t['injection']['text'])
        for a in t.get('expected_actions',t.get('allowed_actions',[])):
            categories['points'] += [p for p in a['after_points'] if not re.fullmatch(r'已回收|已放弃|收在第\d+章|埋在第\d+章',p)]
            categories['quotes']+=a['evidence_quotes']
    for wr in load(root/'authoring/self-review.json')['works'].values():
        for k in ('aliases','stale_facts','missing_facts','resolved_unmarked','stale_notes','missing_threads'):
            categories['quotes'] += [e['quote'] for e in wr[k]]
counts={k:sum(bool(s) and s in text for s in set(v)) for k,v in categories.items()}
assert not any(counts.values()),counts
parts += ['## 6. 报告内容检查','', '```json',dump({'status':'PASS','leakage_counts':counts}),'```','']
DEST.write_text('\n'.join(parts),encoding='utf-8')
print(dump({'status':'PASS','report_written':1,'leakage_counts':counts,'bytes':DEST.stat().st_size}))
