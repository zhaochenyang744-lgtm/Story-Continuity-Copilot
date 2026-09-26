from __future__ import annotations
import datetime, hashlib, json, pathlib, subprocess, sys
from unittest import mock
ROOT=pathlib.Path(__file__).resolve().parents[3]
HERE=pathlib.Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def write(n,x):
    with (HERE/n).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
old={x['path']:x['sha256'] for x in read('docs/g02-citation-repair-evidence/controller-baseline.json')['immutable_prior_files']}
v4=read('docs/g02-citation-repair-evidence/independent-round1-root/results-before.json')
v1=read('docs/g02-citation-repair-evidence/independent-round2-root/comparison-v1-preservation.json')['files']
v2=read('docs/g02-citation-repair-evidence/independent-round3-root/v2-preservation-final.json')['files']
protected={**old,**v4,**v1,**v2}
assert all((ROOT/p).is_file() and sha(ROOT/p)==h for p,h in protected.items())
m=read('evaluation/current_contract_compare_v3/frozen-inputs.json')
paths=[p for p in (ROOT/'evaluation/current_contract_compare_v3').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
paths += [ROOT/p for p in m['source_hashes']]
before={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
write('snapshot-before.json',before)
commands=[
('v1-freeze.txt',[sys.executable,'evaluation/current_contract_compare_v1/freeze.py','verify']),
('v2-freeze.txt',[sys.executable,'evaluation/current_contract_compare_v2/freeze.py','verify']),
('v3-freeze.txt',[sys.executable,'-m','evaluation.current_contract_compare_v3.freeze','verify']),
('v3-tests.txt',[sys.executable,'-m','pytest','evaluation/current_contract_compare_v3/test_v3.py','-q']),
]
checks=[]
for name,cmd in commands:
    p=subprocess.run(cmd,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    with (HERE/name).open('x',encoding='utf-8') as f:f.write(p.stdout+p.stderr)
    checks.append({'log':name,'returncode':p.returncode})
from evaluation.current_contract_compare_v3 import run,controls
guard=[]
for module,worker in ((run,'analyze'),(controls,'controls')):
    name=module.__name__.split('.')[-1]
    base=(HERE/f'guard-{name}').resolve()
    assert base.is_relative_to(HERE.resolve())
    base.mkdir(exist_ok=False)
    with mock.patch.object(run,'HERE',base):
        occupied=run.reserve_run_dir('occupied')
        with mock.patch.object(module,worker,side_effect=AssertionError('work_started_too_early')) as fn:
            try:module.execute('occupied')
            except FileExistsError:pass
            else:raise AssertionError('existing identity accepted')
            assert fn.call_count==0
        with mock.patch.object(module,worker,side_effect=RuntimeError('independent-intentional-first-failure')) as fn:
            try:module.execute('failure')
            except RuntimeError:pass
            else:raise AssertionError('missing failure')
            failure=base/'runs/failure/first-failure.json'
            assert json.loads(failure.read_text(encoding='utf-8'))['error_type']=='RuntimeError'
            original=sha(failure)
            try:module.execute('failure')
            except FileExistsError:pass
            else:raise AssertionError('reused failed identity')
            assert fn.call_count==1 and sha(failure)==original
        sentinel=base/'sentinel.json'
        run.write_x(sentinel,{'original':True})
        original=sha(sentinel)
        try:run.write_x(sentinel,{'original':False})
        except FileExistsError:pass
        else:raise AssertionError('existing file overwritten')
        assert sha(sentinel)==original
        guard.append({'entrypoint':name,'existing_identity_refused_before_work':True,'first_failure_retained':True,'retry_did_not_execute_worker':True,'create_only_file_preserved':True})
write('output-guard-results.json',{'controls':guard,'new_api_runs':0,'real_provider_calls':0})
changed=[p for p,h in before.items() if sha(ROOT/p)!=h]
historical_changed=[p for p,h in protected.items() if sha(ROOT/p)!=h]
out={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'old_preserved':len(old),'v4_preserved':len(v4),'comparison_v1_preserved':len(v1),'comparison_v2_preserved':len(v2),'snapshot_files':len(before),'checks':checks,'changed':changed,'historical_changed':historical_changed,'guard_entrypoints':2,'new_api_runs':0,'real_provider_calls':0,'manifest_sha256':sha(ROOT/'evaluation/current_contract_compare_v3/frozen-inputs.json')}
write('verification.json',out)
print(json.dumps(out,ensure_ascii=False))
assert all(x['returncode']==0 for x in checks) and not changed and not historical_changed

