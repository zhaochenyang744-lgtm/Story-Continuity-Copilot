"""Targeted mutations in temporary copies. No original data is modified."""
from pathlib import Path
import copy
import hashlib
import json
import shutil
import subprocess
import sys
import tempfile

HERE = Path(__file__).resolve().parent
FORMAL = HERE.parent
SAFETY = FORMAL.parent/'eval_set_a2s6_formal'

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def save(p,d):
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def rebind(root):
    paths = sorted(['tasks.json']+[p.relative_to(root).as_posix() for k in ('works','materials')
                                 for p in (root/k).rglob('*') if p.is_file()])
    hashes = {p:sha(root/p) for p in paths}
    (root/'set.sha256').write_text(''.join(f'{h}  {p}\n' for p,h in hashes.items()),encoding='utf-8',newline='\n')
    s=load(root/'authoring/sealed-comparison.json')
    s['candidate_sha256']=hashes
    save(root/'authoring/sealed-comparison.json',s)
    r=load(root/'authoring/independent-review.json')
    r['sha256']=hashes
    r['authoring_sha256']={p:sha(root/p) for p in r['authoring_sha256']}
    save(root/'authoring/independent-review.json',r)

def mutate(root,number):
    d=load(root/'tasks.json')
    if number in (1,2):
        kind='change_fact' if number==1 else 'abandon_thread'
        d['tasks'].remove(next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']==kind))
    elif number==3:
        t=next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['evidence_quotes'])
        q=t['expected_actions'][0]['evidence_quotes'][0]
        t['expected_actions'][0]['evidence_quotes'][0]='龘'+q[1:]
    elif number==4:
        t=next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']=='add_thread')
        t['expected_actions'][0]['target']['about']='不存在的测试目标'
    elif number==5:
        d['tasks'][0]['injection']['text']='龘'+d['tasks'][0]['injection']['text'][1:]
    elif number==6:
        # A valid open-thread abandonment, aimed at the exact thread named by the payload.
        t=next(t for t in d['tasks'] if t['run_kind']=='change' and t['injection_target']['kind']=='abandon_thread')
        target=t['injection_target']['target']
        entry=next(a for other in d['tasks'] for a in other['allowed_actions']
                   if a['kind'] in {'edit_thread','abandon_thread','resolve_thread'} and a['target']==target)
        t['allowed_actions']=[copy.deepcopy(entry)]
    elif number==7:
        p=root/'works/w01.md'
        s=p.read_text(encoding='utf-8')
        at=s.index('\n\n')+2
        p.write_text(s[:at]+'龘'+s[at+1:],encoding='utf-8',newline='\n')
        return
    elif number==8:
        p=root/'materials/w01-foreshadows.json'
        threads=load(p)
        for entry in load(root/'authoring/self-review.json')['works']['w01']['resolved_unmarked']:
            threads[entry['foreshadow']-1]['status']='planned'
        save(p,threads)
    elif number==9:
        a=next(t['expected_actions'][0] for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']=='resolve_thread')
        a['after_points']=['已回收','收在第99章']
    elif number==10:
        # Alter provenance text only; never locate or access the named forbidden directory.
        p=root/'authoring/novelty-reference.json'
        ref=load(p)
        old=next(iter(ref['source_hashes']))
        fake='evaluation/eval_set_a3f2_formal/tasks.json'
        ref['source_hashes'][fake]=ref['source_hashes'].pop(old)
        ref['normalized_inputs_by_source'][fake]=ref['normalized_inputs_by_source'].pop(old)
        save(p,ref)
    save(root/'tasks.json',d)
    rebind(root)

def main():
    intended={1:lambda e:e=='tasks:count' or e.endswith(':primary_actions'),
              2:lambda e:e=='tasks:count' or e.endswith(':primary_actions'),
              3:lambda e:':evidence:' in e and e.endswith(':quote'),
              4:lambda e:':action:' in e and e.endswith(':target'),
              5:lambda e:e.endswith(':injection_match'),
              6:lambda e:e.endswith(':target_object_overlap') or e.endswith(':target_allowed_overlap'),
              7:lambda e:e.startswith('manifest:') and e.endswith(':hash'),
              8:lambda e:e.endswith(':review:resolved_unmarked:registered_states'),
              9:lambda e:e.endswith(':resolve_program_points'),
              10:lambda e:e=='novelty:forbidden_source'}
    results=[]
    for number in range(1,11):
        origin=SAFETY if number in (5,6) else FORMAL
        temp=Path(tempfile.mkdtemp(prefix='_negative-tmp-',dir=HERE)).resolve()
        assert temp.parent==HERE.resolve() and temp.name.startswith('_negative-tmp-')
        try:
            for f in origin.iterdir():
                if f.is_file(): shutil.copy2(f,temp/f.name)
            for folder in ('works','materials'): shutil.copytree(origin/folder,temp/folder)
            (temp/'authoring').mkdir()
            for f in (origin/'authoring').iterdir():
                if f.is_file(): shutil.copy2(f,temp/'authoring'/f.name)
            mutate(temp,number)
            run=subprocess.run([sys.executable,'-X','utf8','-B',str(temp/'check.py')],cwd=HERE,
                               capture_output=True,text=True,encoding='utf-8')
            result=json.loads(run.stdout)
            errors=result.get('errors',[])
            ok=run.returncode!=0 and result.get('status')=='FAIL' and any(intended[number](e) for e in errors)
            results.append({'case':number,'exit_code':run.returncode,'status':result.get('status'),
                            'intended_detected':ok,'error_count':len(errors),'errors':errors})
        finally:
            assert temp.parent==HERE.resolve() and temp.name.startswith('_negative-tmp-')
            assert not any(p.is_symlink() or (hasattr(p,'is_junction') and p.is_junction()) for p in temp.rglob('*'))
            shutil.rmtree(temp)
    out={'status':'PASS' if all(r['intended_detected'] for r in results) else 'FAIL', 'total':len(results),
         'detected':sum(r['intended_detected'] for r in results),
         'temporary_copies_remaining':len(list(HERE.glob('_negative-tmp-*'))),'results':results}
    for root in (FORMAL,SAFETY): save(root/'authoring/negative-check-results.json',out)
    print(json.dumps(out,ensure_ascii=False))
    return 0 if out['status']=='PASS' else 1

if __name__=='__main__':
    raise SystemExit(main())
