"""Required mutation tests in checked temporary copies; originals are never changed."""
from pathlib import Path
import hashlib,json,shutil,subprocess,sys,tempfile
HERE=Path(__file__).resolve().parent
FORMAL=HERE.parent
SAFETY=FORMAL.parent/'eval_set_a2s5_formal'

def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def rebind(root):
    data=sorted([root/'tasks.json']+[p for k in ('works','materials') for p in (root/k).glob('*') if p.is_file()])
    hashes={p.relative_to(root).as_posix():digest(p) for p in data}
    (root/'set.sha256').write_text(''.join(f'{h}  {p}\n' for p,h in hashes.items()),encoding='utf-8')
    s=load(root/'authoring/sealed-comparison.json');s['candidate_sha256']=hashes;save(root/'authoring/sealed-comparison.json',s)
    r=load(root/'authoring/independent-review.json');r['sha256']=hashes
    r['authoring_sha256']['authoring/sealed-comparison.json']=digest(root/'authoring/sealed-comparison.json')
    save(root/'authoring/independent-review.json',r)

def change(d,number):
    if number in (1,2):
        kind='change_fact' if number==1 else 'abandon_thread'
        hit=next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']==kind)
        d['tasks'].remove(hit)
    elif number==3:
        t=next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['evidence_quotes'])
        q=t['expected_actions'][0]['evidence_quotes'][0]
        t['expected_actions'][0]['evidence_quotes'][0]='龘'+q[1:]
    elif number==4:
        t=next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']=='add_thread')
        t['expected_actions'][0]['target']['about']='不存在的测试目标'
    elif number==5:
        t=d['tasks'][0];t['injection']['text']='龘'+t['injection']['text'][1:]
    elif number==6:
        t=next(t for t in d['tasks'] if t['run_kind']=='change' and t['injection_target']['kind']=='abandon_thread')
        t['allowed_actions']=[{'kind':'abandon_thread','target':t['injection_target']['target'],
          'after_points':['已放弃'],'evidence_chapters':[],'evidence_quotes':[]}]

results=[]
for number in range(1,9):
    origin=FORMAL if number in (1,2,3,4,7,8) else SAFETY
    temp=Path(tempfile.mkdtemp(prefix='_negative-tmp-',dir=HERE)).resolve()
    assert temp.parent==HERE.resolve() and temp.name.startswith('_negative-tmp-')
    try:
        for f in origin.iterdir():
            if f.is_file():shutil.copy2(f,temp/f.name)
        for folder in ('works','materials'):
            shutil.copytree(origin/folder,temp/folder)
        (temp/'authoring').mkdir()
        for f in (origin/'authoring').iterdir():
            if f.is_file():shutil.copy2(f,temp/'authoring'/f.name)
        if number==7:
            p=temp/'works/w01.md';s=p.read_text(encoding='utf-8');mark=s.index('\n\n')+2
            p.write_text(s[:mark]+'龘'+s[mark+1:],encoding='utf-8')
        elif number==8:
            p=temp/'materials/w01-foreshadows.json';threads=load(p)
            for i in range(4):threads[i]['status']='planned'
            threads[7]['status']='planted'
            save(p,threads);rebind(temp)
        else:
            d=load(temp/'tasks.json');change(d,number);save(temp/'tasks.json',d);rebind(temp)
        run=subprocess.run([sys.executable,'-X','utf8','-B',str(temp/'check.py')],cwd=HERE,
          capture_output=True,text=True,encoding='utf-8')
        result=json.loads(run.stdout);errors=result.get('errors',[])
        intended={1:lambda e:e=='tasks:count' or e.endswith(':primary_actions'),
          2:lambda e:e=='tasks:count' or e.endswith(':primary_actions'),
          3:lambda e:':evidence:' in e and e.endswith(':quote'),
          4:lambda e:':action:' in e and e.endswith(':target'),
          5:lambda e:e.endswith(':injection_match'),
          6:lambda e:e.endswith(':target_object_overlap') or e.endswith(':target_allowed_overlap'),
          7:lambda e:e.startswith('manifest:') and e.endswith(':hash'),
          8:lambda e:e.endswith(':review:resolved_unmarked:registered_states')}[number]
        ok=run.returncode!=0 and result['status']=='FAIL' and any(intended(e) for e in errors)
        results.append({'case':number,'exit_code':run.returncode,'status':result['status'],
          'intended_detected':ok,'error_count':len(errors),'errors':errors})
    finally:
        assert temp.parent==HERE.resolve() and temp.name.startswith('_negative-tmp-')
        shutil.rmtree(temp)
summary={'status':'PASS' if all(r['intended_detected'] for r in results) else 'FAIL',
 'total':len(results),'detected':sum(r['intended_detected'] for r in results),'temporary_copies_remaining':
 len(list(HERE.glob('_negative-tmp-*'))),'results':results}
save(HERE/'negative-check-results.json',summary)
save(SAFETY/'authoring/negative-check-results.json',summary)
print(json.dumps(summary,ensure_ascii=False));sys.exit(0 if summary['status']=='PASS' else 1)
