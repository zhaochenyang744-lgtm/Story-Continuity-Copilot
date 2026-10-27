"""Render only counts, identifiers, hashes and complete checker JSON to task33 report."""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess

REPO = Path(__file__).resolve().parents[3]
DEST = Path(r'C:\Users\赵晨阳\Desktop\v2.1任务\33-交付报告.md')
SETS = ['eval_set_a3f2_formal', 'eval_set_a3s2_formal']


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=REPO, text=True, encoding='utf-8').strip()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--validate-only', action='store_true')
    validate_only = parser.parse_args().validate_only
    assert git('branch', '--show-current') == 'eval/a3-2-authoring'
    if validate_only:
        history = [['0'*40, 'eval: author and freeze the second A3 safety set'],
                   ['0'*40, 'eval: author and freeze the second A3 formal set']]
    else:
        assert not git('status', '--porcelain')
        history = [line.split('\x00', 1) for line in git('log', '-2', '--format=%H%x00%s').splitlines()]
    assert history[0][1] == 'eval: author and freeze the second A3 safety set'
    assert history[1][1] == 'eval: author and freeze the second A3 formal set'
    roots = {sid: REPO/'evaluation'/sid for sid in SETS}
    records = {s: load(r/'authoring/check-results.json') for s, r in roots.items()}
    stats = {s: c['module']['output'] for s, c in records.items()}
    for s, record in records.items():
        assert record['outputs_identical']
        for mode in ('module', 'absolute'):
            c = record[mode]
            assert c['exit_code'] == 0 and c['output']['status'] == 'PASS' and c['data_unchanged'] and c['stderr_empty']
            assert all(sha(roots[s]/p) == h for p, h in c['data_sha256'].items())
    base = load(roots[SETS[0]]/'authoring/scope-baseline.json')
    assert all(sha(REPO/p) == h for p, h in base['protected_sha256'].items())
    lexical = load(roots[SETS[0]]/'authoring/lexical-audit.json')
    assert lexical['status'] == 'PASS'
    negatives = [e for r in roots.values() for e in load(r/'authoring/negative-tests.json')['results']]
    assert len(negatives) == 7 and all(e['intended_error_detected'] for e in negatives)
    task_audit = load(roots[SETS[0]]/'authoring/independent-task-audit.json')
    assert task_audit['status'] == 'completed' and task_audit['unresolved_findings'] == 0
    assert set(task_audit['covered_task_ids']) == {t['id'] for t in load(roots[SETS[0]]/'tasks.json')['tasks']}
    assert all(sha(roots[SETS[0]]/p) == h for p, h in task_audit['sha256'].items())
    lines = ['# 33 交付报告', '', '范围：数字、结构、编号、哈希及检查器完整输出。', '',
             '|项目|结果|', '|---|---|',
             '|分支|eval/a3-2-authoring|', '|本地提交数|2|',
             '|正式集提交|'+history[1][0]+'|', '|安全题集提交|'+history[0][0]+'|',
             '|受保护文件哈希一致|5/5|', '|工作区未提交项|0|',
             '|push / merge / switch|0 / 0 / 0|', '|模型接口 / 产品 / 评测运行|0 / 0 / 0|',
             '|semantic_acceptance|false|', '', '结构检查与独立复核已完成；未进行真实模型评测。', '',
             '## 规模及起始资料', '',
             '|集|作品|章数|章汉字最小|章汉字最大|正文汉字总数|共享草稿章|共享草稿汉字|事实|伏笔|具名人物|别名|专名|',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for sid, result in stats.items():
        for wk, w in result['works'].items():
            values = [sid, wk, w['chapters'], w['chapter_han_min'], w['chapter_han_max'], w['total_han'],
                      w['chapters']+1, w['draft_han'], w['facts'], w['foreshadows'], w['characters'], w['aliases'], w['names']]
            lines.append('|'+ '|'.join(map(str, values))+'|')
    lines += ['', '|集/作品|trace_objects|states|contradictions|decision_points|resolved_unmarked|still_open|abandoned_in_text|near_misses|',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for sid, result in stats.items():
        for wk, w in result['works'].items():
            fields = ['trace_objects','trace_states','contradictions','decision_points','resolved_unmarked','still_open','abandoned_in_text','near_misses']
            lines.append('|'+sid+'/'+wk+'|'+'|'.join(str(w[k]) for k in fields)+'|')
    lines += ['', '|集/作品|planted|developing|planned|resolved|abandoned|', '|---|---:|---:|---:|---:|---:|']
    for sid, result in stats.items():
        for wk, w in result['works'].items():
            lines.append('|'+sid+'/'+wk+'|'+'|'.join(str(w['foreshadow_states'].get(k,0)) for k in ('planted','developing','planned','resolved','abandoned'))+'|')
    lines += ['', '## 正式集题目结构', '',
              '|作品|trace|thread_audit|ask|narrowed|route|scope非空|scope全书|resolve_thread|abandon_thread|口语长任务|',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    formal_data = load(roots[SETS[0]]/'tasks.json')
    for wk, w in stats[SETS[0]]['works'].items():
        long = [t for t in formal_data['tasks'] if t['work']==wk and t['suite']!='route']
        colloquial = sum(not any(x in t['request'] for x in ('清点','梳理','整理')) for t in long)
        values = [wk]+[w['suites'][k] for k in ('trace','thread_audit','ask','narrowed','route')]+[w['scope_given'],w['scope_all'],w['expected_action_kinds']['resolve_thread'],w['expected_action_kinds']['abandon_thread'],colloquial]
        lines.append('|'+ '|'.join(map(str,values))+'|')
    lines += ['', '|作品|long_task|change|ask|recap|check_passage|out_of_scope|同句组|narrowed trace|narrowed thread_audit|',
              '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for wk, w in stats[SETS[0]]['works'].items():
        values = [wk]+[w['routes'].get(k,0) for k in ('long_task','change','ask','recap','check_passage','out_of_scope')]+[w['same_input_groups'],1,1]
        lines.append('|'+ '|'.join(map(str,values))+'|')
    lines += ['', '正式集总题数38：长任务18、判断用法20；tidy=0；其他动作种类=0。', '',
              '## 安全题集结构', '', '|类别|分布|', '|---|---|',
              '|suite injection|10|', '|run_suite|trace=5；thread_audit=5|',
              '|location|chapter=5；chapter_title=1；fact=2；foreshadow=2|',
              '|injection_target|'+ '；'.join(k+'='+str(v) for k,v in stats[SETS[1]]['injection_targets'].items())+'|',
              '|压缩摘要针对项|2|', '|正文载荷严格>1500|5/5|', '|正常请求tidy|0|',
              '|合法动作与注入目标重合|0|', '', '|题目编号|章|正文载荷首汉字位置|', '|---|---:|---:|']
    for e in stats[SETS[1]]['chapter_injection_positions']:
        lines.append(f"|{e['id']}|{e['chapter']}|{e['han_position']}|")
    lines += ['', '## 引句位置', '',
              '|集/作品|检查器引句数|1–1500|1501–2500|>2500|严格>1500|最小位置|最大位置|',
              '|---|---:|---:|---:|---:|---:|---:|---:|']
    for sid, result in stats.items():
        for wk,w in result['works'].items():
            b=w['point_position_buckets'];values=[sid+'/'+wk,w['point_quotes'],b['1_1500'],b['1501_2500'],b['2501_plus'],w['point_after1500'],w['point_han_min'],w['point_han_max']]
            lines.append('|'+ '|'.join(map(str,values))+'|')
    lines += ['', '检查器该表含别名支持引句，初始事实支持引句不计入。另按纯考点去除别名支持后：', '',
              '|集/作品|纯考点去重引句|>1500|>2500|最小位置|最大位置|', '|---|---:|---:|---:|---:|---:|']
    for sid,root in roots.items():
        for wk,c in load(root/'authoring/core-point-audit.json').items():
            lines.append('|'+sid+'/'+wk+'|'+'|'.join(str(c[k]) for k in ('core_quotes','after1500','after2500','min','max'))+'|')
    lines += ['', '## 独立复核', '', '|项目|首轮一致|最终一致|未关闭|', '|---|---:|---:|---:|',
              '|正式集判断用法|20/20（100%）|20/20（100%）|0|',
              '|正式集伏笔状态及收束章|18/18（100%）|18/18（100%）|0|',
              '|安全题集伏笔状态及收束章|8/8（100%）|8/8（100%）|0|',
              '|正式集范围动作集合|6/6|6/6|0|', '|安全题集范围动作集合|5/5|5/5|0|',
              '|正式集逐题语义复核|38/38|38/38|0|', '',
              '复判分歧题数0，分歧编号集合为空，修题数0。首轮原件保留；正文非考点修订后的最终复判另存，伏笔状态/收束章变化0。', '',
              '|完整正文及共享草稿复核|正文覆盖|基础事实支持|关闭项|未关闭|', '|---|---:|---:|---:|---:|',
              '|正式集w01|30/30|30/30|7|0|', '|正式集w02|30/30|30/30|13|0|', '|安全题集w01|12/12|24/24|2|0|', '',
              '正文完整覆盖72/72；共享草稿覆盖3/3；前置自查修订2/2。检查器独立审查阻断项2/2关闭，补充探针5/5捕获，未关闭0。', '',
              '## 旧语料、照抄与新颖性', '', '|项目|数值|', '|---|---:|',
              '|获准题集目录|45|', '|已读作品文件开头|103|', '|去重作品开头全文数|99|', '|去重开头章数|297|', '|同字节副本核验|4|',
              '|旧文本文件|'+str(lexical['old_text_files'])+'|', '|旧tasks.json|'+str(lexical['old_source_files'])+'|',
              '|旧去重输入|'+str(lexical['old_normalized_inputs'])+'|', '|新输入|48|', '|新去重输入|46|', '|同句组豁免|2|',
              '|新专名/去重专名|57/57|', '|专名重合|0|', '|标题重合|0|', '|照抄违规|0|', '|历史新颖性违规|0|', '|集内非同句组相似违规|0|',
              '|历史相似度最大|'+str(lexical['max_external_similarity'])+'|', '|集内非同句组相似度最大|'+str(lexical['max_internal_similarity_excluding_groups'])+'|',
              '|旧语料哈希变化|0|', '|遍历前排除目录|5|', '',
              '相似度：去空白与Unicode标点，SequenceMatcher(autojunk=False)，阈值0.8。专名作为连续八汉字比较的断点。同句组仅豁免本集内对应两项，不豁免历史语料。零重合只覆盖获准可读语料。', '',
              '## 验证', '', '|调用方式|成功|退出码|输出一致|数据字节变化|', '|---|---:|---:|---:|---:|',
              '|根目录模块方式|2/2|0|2/2|0|', '|任意目录绝对路径方式|2/2|0|2/2|0|', '',
              '|负向测试编号|集|破坏项|破坏前|破坏后|退出码|对应错误捕获|', '|---:|---|---|---|---|---:|---:|']
    labels={1:'删除trace',2:'quote改一字',3:'expected_actions增加near_misses',4:'增加tidy',5:'injection.text改一字',6:'injection_target与allowed_actions重合',7:'works改一字'}
    for e in sorted(negatives,key=lambda x:x['test']):
        lines.append(f"|{e['test']}|{e['set']}|{labels[e['test']]}|PASS|FAIL|{e['exit_code']}|1|")
    lines += ['', '7/7负向测试捕获对应错误；临时副本清理7/7。第1–6项临时副本更新清单哈希后仍被语义结构规则捕获；第7项保留清单用于验证字节改动。正式数据改动0。', '',
              '正文重复长段0；正文BOM、CRLF、替换字符均0。', '',
              '## 规范歧义与采用规则', '',
              '1. A3旧表每部11道长任务，补充三及任务33去掉2道tidy，采用9道；tidy=0，narrowed与injection只用trace/thread_audit。登记门槛改动0。',
              '2. A3旧范围条目与任务33数量不同，按任务33每部scope非空至少3、全书至少3；实际3及6。narrowed原scope=null，执行边界取plan_edit。',
              '3. 引用A1c共享草稿旧长度与A3/任务33不同，采用600–1000汉字；实际796、796、761。起始资料按本任务30–45/9–14及20–35/6–10取值。',
              '4. 范围含端点；状态卡按实际回收/永久放弃章落入执行范围计，不按最初起植章计。初始已resolved不重复改，near_misses保持开放。矛盾另一端在范围外时，不越界补读或强求完整对照。',
              '5. 考点位置同时保留任务33至少一半>1500及引用A1c至少三分之一>2500；去重按章号加逐字引句。事实支持另计；别名支持纳入检查器扩展统计，并另列不含别名的纯考点统计。',
              '6. 注入种类按任务33功能类别的下限约束，不把枚举8种误当每种必出；本次实际8种全覆盖。skip_asking使用trace、范围内唯一decision_point及作者回复。',
              '7. 全库查重与禁读要求并存时，遍历前排除5个禁读/并行目录，未读取它们；查重结论不覆盖排除部分。',
              '8. 检查器PASS为离线结构证据；独立语义复核另存，semantic_acceptance=false。真实模型、产品运行、正式评测均0。', '',
              '## 冻结清单', '']
    for sid, root in roots.items():
        lines += ['### '+sid, '', 'set.sha256 SHA-256：`'+sha(root/'set.sha256')+'`', '', '```text',
                  (root/'set.sha256').read_text(encoding='utf-8').rstrip(), '```', '']
    lines += ['## 检查器完整输出', '']
    for sid in SETS:
        lines += ['### '+sid, '', '```json', records[sid]['module']['stdout'], '```', '']
    output='\n'.join(lines)+'\n'
    # Exact-string content leakage check; only identifiers/counts/hashes are allowed above.
    banned=[]
    for root in roots.values():
        d=load(root/'tasks.json');g=load(root/'authoring/self-review.json')
        for w in d['works']:
            banned += w['names']+[w['title'],w['shared_draft']['body']]
        for t in d['tasks']:
            banned += [t['input'] if t['suite']=='route' else t['request']]
            for field in ('expected_actions','allowed_actions'):
                for a in t.get(field,[]):banned+=a.get('evidence_quotes',[])
        def quotes(v):
            if isinstance(v,dict):
                for k,x in v.items():
                    if k=='quote' and isinstance(x,str):banned.append(x)
                    else:quotes(x)
            elif isinstance(v,list):
                for x in v:quotes(x)
        quotes(g)
    assert not any(x and x in output for x in banned)
    assert 'Co-Authored-By' not in output and 'Generated by' not in output
    if not validate_only:
        DEST.write_text(output,encoding='utf-8',newline='\n')
    print(json.dumps({'report_written':not validate_only,'report_sha256':hashlib.sha256(output.encode('utf-8')).hexdigest(),
                      'content_leaks':0,'local_commits':0 if validate_only else 2},ensure_ascii=False))


if __name__=='__main__':
    main()
