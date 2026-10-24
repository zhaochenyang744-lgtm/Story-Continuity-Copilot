"""Run the two offline structure checkers from both required locations."""
from pathlib import Path
import json,subprocess,sys
HERE=Path(__file__).resolve().parent
REPO=HERE.parents[2]
SETS=('eval_set_a25_formal','eval_set_a2s5_formal')
out={'root':{},'absolute':{}}
for mode in out:
    for sn in SETS:
        script=REPO/'evaluation'/sn/'check.py'
        args=[sys.executable,'-X','utf8','-B']+(['-m','evaluation.'+sn+'.check'] if mode=='root' else [str(script)])
        result=subprocess.run(args,cwd=REPO if mode=='root' else REPO.parents[3],
          capture_output=True,text=True,encoding='utf-8')
        try:body=json.loads(result.stdout)
        except ValueError:body={'status':'FAIL','errors':['runner:invalid_json']}
        out[mode][sn]={'exit_code':result.returncode,'result':body}
        print(json.dumps({'mode':mode,'set':sn,'exit_code':result.returncode,'result':body},ensure_ascii=False))
(HERE/'checker-runs.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
sys.exit(0 if all(x['exit_code']==0 and x['result']['status']=='PASS' for group in out.values() for x in group.values()) else 1)
