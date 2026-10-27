"""Write the authorized desktop report from a content-free projection only."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1];REPO=ROOT.parents[1]
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def git(*args):return subprocess.check_output(['git',*args],cwd=REPO).decode('utf-8').strip()
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
check=read('authoring/check-output.json');negative=read('authoring/negative-tests.json')
data=read('tasks.json');position=read('authoring/position-audit.json');names=read('authoring/names-audit.json')
protect=read('authoring/protected-final.json');novel=read('authoring/task-novelty-audit.json')
assert check['status']=='PASS' and not check['errors']
assert negative['status']=='PASS' and negative['failed']==0 and negative['temporary_copies_remaining']==0
assert protect['changed_count']==0
assert not novel['copy_pending_source_completion'] and novel['external_failure_count']==novel['internal_failure_count']==0
assert novel['source_sha256']==sha(ROOT/'works/w01.md') and novel['tasks_sha256']==sha(ROOT/'tasks.json')
assert names['story_bible_sha256']==sha(ROOT/'authoring/story-bible.md')
commit=git('rev-parse','HEAD');branch=git('branch','--show-current')
message=git('show','-s','--format=%B','HEAD')
assert branch=='eval/a3-4-authoring'
preflight='--preflight' in sys.argv
expected_message='eval: author and freeze the second A3 supplementary safety set'
if preflight:message=expected_message
else:
    assert message==expected_message
    assert git('rev-list','--count',read('authoring/protected-baseline.json')['head']+'..HEAD')=='1'
manifest=(ROOT/'set.sha256').read_text(encoding='ascii').strip()
lines=['# 36 交付报告','','|结构项|数值|','|---|---|',f'|分支|`{branch}`|',f'|提交|`{commit}`|','|新增提交|1|',f'|提交说明|`{message}`|','|推送/合并/切分支/进入其他worktree|0 / 0 / 0 / 0|','|模型调用/产品运行/评测运行|0 / 0 / 0|','|正式集/整理资料题/route题|0 / 0 / 0|',f"|受保护文件/变化|{protect['protected_files']} / {protect['changed_count']}|",'','## 封存','','```text',manifest,'```',f"\n`set.sha256` SHA-256：`{sha(ROOT/'set.sha256')}`",'','## 数量与分布','','```json',json.dumps(dict(chapters=position['chapter_han'],total_han=position['total_han'],shared_draft_han=position['draft_han'],facts=len(read('materials/w01-facts.json')),foreshadows=len(read('materials/w01-foreshadows.json')),repeated_paragraph_groups=position['repeated_paragraph_groups'],encoding_errors=len(position['encoding_errors'])),ensure_ascii=False,indent=2),'```','','## 专名、照抄和新颖性','','```json',json.dumps(dict(names_audit={k:v for k,v in names.items() if k in {'status','candidate_names','tasks_candidate_names','tasks_candidate_names_sha256'}},readable={k:v for k,v in names['readable'].items() if k!='file_sha256'},sealed_program_only={k:v for k,v in names.get('sealed_program_only',names.get('sealed',{})).items() if k!='file_sha256'},task_novelty=novel),ensure_ascii=False,indent=2),'```','','旧语料结构：48目录，41份README；107份作品文件、97种独立开头、194章；7目录无README。6目录排除明文读取，只作程序计数。','','## 检查器完整输出','','```json',json.dumps(check,ensure_ascii=False,sort_keys=True),'```','','## 负向测试','','```json',json.dumps(negative,ensure_ascii=False,indent=2),'```','','## 依据、歧义和边界','','|项|采用结构|','|---|---|','|优先级|SPEC补充六 → 补充五 → 36 → 35/33安全部分|','|补测规模|1 × 12章；10题；2决定点；数字型≥1|','|单端范围|3题；6–12、1–9、7–12；3诱饵登记|','|结尾补全|已完成正文止点12；共享开头13不扩展scope|','|考点深度|≥1/2在1500后；保留前套≥1/3在2500后|','|旧任务禁读|继承3目录；另3封存目录；6目录只计数|','|动作范围|按结局证据章计算；范围外诱饵不进入allowed_actions|','|数字决定点|同一原定数值，两侧相隔≥3章且均在500字后|','|独立复判|初判仅正文与起始伏笔；对照后保留首判记录|','|检查结论|结构及离线检查；模型/产品/正式评测结论0|','|登记修改|0|','']
sealed=read('authoring/sealed-input-novelty-counts.json')
assert sealed['status']=='PASS' and sealed['failure_count']==0 and sealed['plaintext_outputs']==0
assert sealed['tasks_sha256']==sha(ROOT/'tasks.json')
lines += ['','## 封存输入程序比对','','```json',json.dumps({k:v for k,v in sealed.items() if k not in {'directories','tasks_sha256'}},ensure_ascii=False,indent=2),'```','']
all_text=read('authoring/names-all-text-audit.json')
assert all_text['status']=='PASS' and all_text['plaintext_outputs']==0
lures=read('authoring/self-review.json')['works']['w01']['out_of_scope_lures']
lines += ['','## 全部文本与诱饵去重','','```json',json.dumps(dict(names_all_utf8_text=all_text,lure_registrations=len(lures),distinct_lure_points=len({(x['chapter'],x['quote']) for x in lures})),ensure_ascii=False,indent=2),'```','']
independent=read('authoring/independent-review.json');bt=independent['blind_threads']
lines += ['','## 依据位置与独立复核','','```json',json.dumps(dict(point_positions=position['points'],chapter_coverage=independent['chapter_coverage'],unresolved_findings=independent['unresolved_findings'],thread_first_agreement_rate=bt['first_agreement']/bt['total'],thread_final_agreement_rate=bt['final_agreement']/bt['total'],action_set_agreement_rate=bt['action_set_agreement']/bt['action_sets'],route_tasks=0,strict_narrative_meta_matches=position['strict_narrative_meta_matches']),ensure_ascii=False,indent=2),'```','']
full=read('authoring/independent-full-reading-w01.json');gold=read('authoring/independent-gold-audit.json')
entrypoints=read('authoring/check-entrypoints.json')
assert gold['status']=='PASS' and entrypoints['passed']==2 and entrypoints['identical_results']
lines += ['','## 复核闭环与检查入口','','```json',json.dumps(dict(findings=[dict(id=f['id'],resolution_status=f['resolution_status']) for f in full['findings']],gold_counts={k:v for k,v in gold.get('counts',{}).items() if type(v) in {int,float,bool}},entrypoints=entrypoints),ensure_ascii=False,indent=2),'```','']
report='\n'.join(lines)
# Exact source-sensitive strings must never appear in the report.
for w in data['works']:
    for secret in w['names']+[w['title']]:assert secret not in report
for t in data['tasks']:
    for secret in [t['request'],t['injection']['text']]:assert secret not in report
    for a in t['allowed_actions']:
        for q in a['evidence_quotes']:assert q not in report
target=Path(r'C:\Users\赵晨阳\Desktop\v2.1任务\36-交付报告.md')
if preflight:
    print(json.dumps(dict(status='PASS',report_bytes=len(report.encode('utf-8')),source_leakage_matches=0,write_operations=0),ensure_ascii=False))
else:
    target.write_text(report,encoding='utf-8',newline='\n')
    print(json.dumps(dict(report=str(target),report_sha256=sha(target),source_leakage_matches=0,commit=commit),ensure_ascii=False))
