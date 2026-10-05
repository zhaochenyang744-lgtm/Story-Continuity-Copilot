from __future__ import annotations
import datetime, hashlib, json, pathlib, subprocess, sys
ROOT=pathlib.Path(__file__).resolve().parents[3]
HERE=pathlib.Path(__file__).resolve().parent
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p):return json.loads((ROOT/p).read_text(encoding='utf-8'))
def write(n,x):
    with (HERE/n).open('x',encoding='utf-8') as f:json.dump(x,f,ensure_ascii=False,indent=2)
old={x['path']:x['sha256'] for x in read('docs/g02-citation-repair-evidence/controller-baseline.json')['immutable_prior_files']}
v4=read('docs/g02-citation-repair-evidence/independent-round1-root/results-before.json')
v1=read('docs/g02-citation-repair-evidence/independent-round2-root/comparison-v1-preservation.json')['files']
manifest=read('evaluation/current_contract_compare_v2/frozen-inputs.json')
protected={**old,**v4,**v1}
mismatches=[p for p,h in protected.items() if not (ROOT/p).is_file() or sha(ROOT/p)!=h]
assert not mismatches,mismatches
paths=[p for p in (ROOT/'evaluation/current_contract_compare_v2').rglob('*') if p.is_file() and '__pycache__' not in p.parts and p.suffix!='.pyc']
paths += [ROOT/p for p in manifest['source_hashes']]
before={p.relative_to(ROOT).as_posix():sha(p) for p in paths}
write('snapshot-before.json',before)
commands=[
('v1-freeze.txt',[sys.executable,'evaluation/current_contract_compare_v1/freeze.py','verify']),
('v2-freeze.txt',[sys.executable,'evaluation/current_contract_compare_v2/freeze.py','verify']),
('v2-offline-tests.txt',[sys.executable,'-m','pytest','evaluation/current_contract_compare_v2/test_offline.py','-q']),
]
checks=[]
for name,command in commands:
    p=subprocess.run(command,cwd=ROOT,capture_output=True,text=True,encoding='utf-8',errors='replace')
    with (HERE/name).open('x',encoding='utf-8') as f:f.write(p.stdout+p.stderr)
    checks.append({'log':name,'returncode':p.returncode})
after={p:sha(ROOT/p) for p in before}
drift=[p for p in before if before[p]!=after[p]]
old_changed=[p for p,h in protected.items() if sha(ROOT/p)!=h]
out={'timestamp':datetime.datetime.now(datetime.timezone.utc).isoformat(),'old_preserved_count':len(old),'v4_preserved_count':len(v4),'v1_preserved_count':len(v1),'checked_files':len(before),'changes':drift,'old_changed':old_changed,'checks':checks,'real_provider_calls':0,'v2_manifest_sha256':sha(ROOT/'evaluation/current_contract_compare_v2/frozen-inputs.json')}
write('verification.json',out)
print(json.dumps(out,ensure_ascii=False))
assert not drift and not old_changed and all(x['returncode']==0 for x in checks)

