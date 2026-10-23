"""Offline bookkeeping, bindings, required mutation probes, and count-only results."""
from pathlib import Path
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

ROOT=Path(__file__).resolve().parents[3]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def save(p,v):
    p.write_text(json.dumps(v,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')


def bind(root):
    paths=sorted(['tasks.json']+[p.relative_to(root).as_posix() for d in ('works','materials') for p in (root/d).rglob('*') if p.is_file()])
    (root/'set.sha256').write_text(''.join(sha(root/p)+'  '+p+'\n' for p in paths),encoding='utf-8')
    p=root/'authoring/independent-review.json'
    obj=json.loads(p.read_text(encoding='utf-8'))
    obj['sha256']={n:sha(root/n) for n in paths}
    obj['authoring_sha256']={n:sha(root/n) for n in ('authoring/self-review.json','authoring/self-review.md','authoring/novelty-reference.json')}
    save(p,obj)


def run_check(root,cwd=None):
    p=subprocess.run([sys.executable,'-X','utf8','-B',str(root/'check.py')],cwd=cwd or root,capture_output=True,text=True,encoding='utf-8')
    try:obj=json.loads(p.stdout)
    except Exception:obj={'status':'FAIL','errors':['probe:invalid_output']}
    return p.returncode,obj


def negative():
    formal=ROOT/'evaluation/eval_set_a3_formal';safe=ROOT/'evaluation/eval_set_a3s_formal'
    cases=[(1,formal,'trace_count'),(2,formal,'quote'),(3,formal,'tidy_complete'),
           (4,safe,'injection_quote'),(5,safe,'injection_collision'),(6,formal,'source_hash')]
    results=[]
    for number,source,kind in cases:
        with tempfile.TemporaryDirectory(prefix='a3-authoring-negative-') as td:
            temp=Path(td).resolve(); target=temp/'set'
            if not temp.name.startswith('a3-authoring-negative-'):
                raise ValueError('temporary boundary')
            shutil.copytree(source,target)
            data=json.loads((target/'tasks.json').read_text(encoding='utf-8'))
            if kind=='trace_count':
                n=next(i for i,t in enumerate(data['tasks']) if t['suite']=='trace');del data['tasks'][n]
                save(target/'tasks.json',data);bind(target)
            elif kind=='quote':
                p=target/'authoring/self-review.json';obj=json.loads(p.read_text(encoding='utf-8'))
                e=obj['works']['w01']['trace_objects'][0]['states'][0];q=e['quote'];e['quote']=('乙' if q[0]!='乙' else '丙')+q[1:]
                save(p,obj);bind(target)
            elif kind=='tidy_complete':
                t=next(t for t in data['tasks'] if t['suite']=='tidy' and t['expected_actions']);del t['expected_actions'][0]
                save(target/'tasks.json',data);bind(target)
            elif kind=='injection_quote':
                t=data['tasks'][0];q=t['injection']['text'];t['injection']['text']=('乙' if q[0]!='乙' else '丙')+q[1:]
                save(target/'tasks.json',data);bind(target)
            elif kind=='injection_collision':
                t=next(t for t in data['tasks'] if t['allowed_actions']);a=t['allowed_actions'][0]
                t['injection_target']={'kind':a['kind'],'target':a['target']};save(target/'tasks.json',data);bind(target)
            else:
                p=target/'works/w01.md';s=p.read_text(encoding='utf-8');start=s.index('\n')+1
                n=next(i for i in range(start,len(s)) if '\u4e00'<=s[i]<='\u9fff');s=s[:n]+('雨' if s[n]!='雨' else '风')+s[n+1:]
                p.write_text(s,encoding='utf-8')
            code,result=run_check(target,temp)
            es=result.get('errors',[])
            wanted={'trace_count':lambda x:':suite_distribution' in x or x=='tasks:count',
                    'quote':lambda x:':trace:1:state:1:quote' in x,
                    'tidy_complete':lambda x:':actions_complete' in x,
                    'injection_quote':lambda x:':injection_quote' in x,
                    'injection_collision':lambda x:':injection_collision' in x,
                    'source_hash':lambda x:x.startswith('manifest:') and x.endswith(':hash')}[kind]
            detected=code!=0 and result.get('status')=='FAIL' and any(wanted(e) for e in es)
            results.append({'number':number,'exit_code':code,'detected':detected,'error_count':len(es),'errors':es,
                            'metadata_hashes_refreshed':kind!='source_hash'})
    payload={'total':len(results),'detected':sum(r['detected'] for r in results),'results':results}
    save(formal/'authoring/negative-check-results.json',payload)
    save(safe/'authoring/negative-check-results.json',{'total':2,'detected':sum(r['detected'] for r in results if r['number'] in (4,5)),
         'results':[r for r in results if r['number'] in (4,5)]})
    return payload


def regressions():
    """Focused mutation probes for independent review findings and later-state completeness."""
    formal=ROOT/'evaluation/eval_set_a3_formal';safe=ROOT/'evaluation/eval_set_a3s_formal'
    results=[]
    for number,source in ((1,formal),(2,safe),(3,safe),(4,formal),(5,formal)):
        with tempfile.TemporaryDirectory(prefix='a3-authoring-regression-') as td:
            temp=Path(td).resolve()
            if not temp.name.startswith('a3-authoring-regression-'):raise ValueError('temporary boundary')
            target=temp/'set';shutil.copytree(source,target)
            data=json.loads((target/'tasks.json').read_text(encoding='utf-8'))
            if number==1:
                t=next(t for t in data['tasks'] if t['suite']=='narrowed' and t['expected_actions'])
                t['allowed_actions'].append(t['expected_actions'].pop())
                save(target/'tasks.json',data)
                wanted=':actions_complete'
            elif number==2:
                p=target/'authoring/self-review.json';obj=json.loads(p.read_text(encoding='utf-8'))
                obj['works']['w01']['decision_answers']['1']['chosen']='a'
                save(p,obj);wanted=':decision_selected_evidence'
            elif number==3:
                t=next(t for t in data['tasks'] if t['injection_target']['kind']=='skip_asking')
                a=next(a for a in t['allowed_actions'] if a['kind']=='change_fact')
                t['injection_target']={'kind':'out_of_plan','target':a['target']}
                save(target/'tasks.json',data);wanted=':injection_object_collision'
            elif number==4:
                t=next(t for t in data['tasks'] if t['id']=='a3f-w01-tidy-02')
                a=next(a for a in t['expected_actions'] if a['kind']=='change_fact' and a['target']==1)
                review=json.loads((target/'authoring/self-review.json').read_text(encoding='utf-8'))
                e=next(e for e in review['works']['w01']['fact_updates'] if e['fact']==1 and e['changed_chapter']==19)
                import re
                source=(target/'works/w01.md').read_text(encoding='utf-8')
                title=re.search(r'^# (第19章 [^\n]+)$',source,re.M)[1]
                a.update(after_points=e['after_points'],evidence_chapters=[title],evidence_quotes=[e['quote']])
                save(target/'tasks.json',data);wanted=':latest_update_evidence'
            else:
                t=next(t for t in data['tasks'] if t['id']=='a3f-w01-tidy-02')
                t['expected_actions']=[a for a in t['expected_actions'] if not(a['kind']=='change_fact' and a['target']==1)]
                save(target/'tasks.json',data);wanted=':actions_complete'
            bind(target)
            code,result=run_check(target,temp);es=result.get('errors',[])
            results.append({'number':number,'exit_code':code,'detected':code!=0 and result.get('status')=='FAIL' and any(wanted in e for e in es),
                            'error_count':len(es),'errors':es})
    obj={'total':5,'detected':sum(r['detected'] for r in results),'results':results}
    save(formal/'authoring/checker-regressions.json',obj)
    return obj


if __name__=='__main__':
    command=sys.argv[1]
    if command=='bind':
        for name in ('eval_set_a3_formal','eval_set_a3s_formal'):bind(ROOT/'evaluation'/name)
        print(json.dumps({'bound_sets':2}))
    elif command=='negative':
        result=negative();print(json.dumps(result,sort_keys=True));raise SystemExit(int(result['detected']!=6))
    elif command=='regressions':
        result=regressions();print(json.dumps(result,sort_keys=True));raise SystemExit(int(result['detected']!=5))
