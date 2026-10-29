"""Run only the offline set checker, including four isolated corruption probes."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import uuid
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
def dump(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def load(p): return json.loads(p.read_text(encoding='utf-8'))
def run(args,cwd):
    p=subprocess.run([sys.executable,'-X','utf8','-B',*args],cwd=cwd,capture_output=True,text=True,encoding='utf-8')
    return {'command':[str(sys.executable),'-X','utf8','-B',*map(str,args)],'cwd':str(cwd),'exit_code':p.returncode,'stdout':p.stdout.strip(),'stderr':p.stderr.strip(),'result':json.loads(p.stdout)}
runs={
 'repository_module':run(['-m','evaluation.eval_set_a2t_dev.check'],REPO),
 'outside_absolute':run([str(ROOT/'check.py')],Path(tempfile.gettempdir())),
}
dump(ROOT/'authoring/checker-runs.json',runs)
assert all(r['exit_code']==0 and r['result']['status']=='PASS' and not r['stderr'] for r in runs.values())
source_files=[p for p in ROOT.rglob('*') if p.is_file() and not any(part.startswith('_negative') for part in p.relative_to(ROOT).parts)]
temp_root=(ROOT/'authoring'/('_negative-tmp-'+uuid.uuid4().hex)).resolve()
assert temp_root.is_relative_to((ROOT/'authoring').resolve()) and temp_root.parent==(ROOT/'authoring').resolve()
temp_root.mkdir()
results=[]
try:
    for name,expected in [
      ('delete_abandon_action','w01:primary_actions'),
      ('wrong_add_thread_target','missing_thread_target'),
      ('alter_stale_note_quote','w01:review:stale_notes:1:quote'),
      ('alter_source_one_han','w01:source_bytes_equal'),
    ]:
        clone=temp_root/name
        clone.mkdir()
        for source in source_files:
            dest=clone/source.relative_to(ROOT)
            dest.parent.mkdir(parents=True,exist_ok=True)
            shutil.copyfile(source,dest)
        if name=='delete_abandon_action':
            p=clone/'tasks.json'; d=load(p)
            n=next(i for i,t in enumerate(d['tasks']) if t['work']=='w01' and t['suite']=='action' and t['expected_actions'][0]['kind']=='abandon_thread')
            d['tasks'].pop(n); dump(p,d)
        elif name=='wrong_add_thread_target':
            p=clone/'tasks.json'; d=load(p)
            t=next(t for t in d['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']=='add_thread')
            t['expected_actions'][0]['target']['about']='故意不存在的缺线对象'; dump(p,d)
        elif name=='alter_stale_note_quote':
            p=clone/'authoring/self-review.json'; d=load(p)
            e=d['works']['w01']['stale_notes'][0]; e['quote']='错'+e['quote'][1:]; dump(p,d)
        else:
            p=clone/'works/w01.md'; b=p.read_bytes()
            assert '雨水'.encode() in b
            p.write_bytes(b.replace('雨水'.encode(),'风水'.encode(),1))
        r=run([str(clone/'check.py')],REPO)
        target_found=any(expected in e for e in r['result']['errors'])
        assert r['exit_code']!=0 and r['result']['status']=='FAIL' and target_found,(name,r)
        results.append({'name':name,'expected_error':expected,'expected_error_found':target_found,'exit_code':r['exit_code'],'status':r['result']['status'],'checker_output':r['result']})
finally:
    # Verify the resolved absolute boundary and reject every reparse point
    # before the sole recursive removal; never pass paths across shells.
    assert temp_root.parent==(ROOT/'authoring').resolve() and temp_root.name.startswith('_negative-tmp-')
    assert not temp_root.is_symlink() and not (hasattr(temp_root,'is_junction') and temp_root.is_junction())
    assert all(not p.is_symlink() and not (hasattr(p,'is_junction') and p.is_junction()) for p in temp_root.rglob('*'))
    shutil.rmtree(temp_root)
dump(ROOT/'authoring/negative-tests.json',{'tests':results,'total':4,'expected_failures':len(results),'temporary_copies_removed':not temp_root.exists()})
baseline=load(ROOT/'authoring/protected-baseline.json')
protected={p:hashlib.sha256((REPO/p).read_bytes()).hexdigest()==h for p,h in baseline['sha256'].items()}
assert all(protected.values())
dump(ROOT/'authoring/protected-postflight.json',{'protected_files':protected,'all_unchanged':all(protected.values()),'temporary_copies_remaining':len(list((ROOT/'authoring').glob('_negative-tmp-*')))})
print(json.dumps({'root':'PASS','outside_absolute':'PASS','negative_expected_failures':len(results),'temporary_copies_removed':not temp_root.exists(),'protected_unchanged':all(protected.values())},ensure_ascii=False))
