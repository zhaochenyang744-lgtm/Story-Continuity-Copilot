"""Run only the two offline structure checkers, in both supported forms."""
from pathlib import Path
import json
import subprocess
import sys

REPO=Path(__file__).resolve().parents[3]

def main():
    summary=[]
    for name in ('eval_set_a26_formal','eval_set_a2s6_formal'):
        root=REPO/'evaluation'/name
        runs={}
        for mode,cwd,args in (
            ('root',REPO,['-m',f'evaluation.{name}.check']),
            ('absolute',root/'authoring',[str(root/'check.py')])):
            p=subprocess.run([sys.executable,'-X','utf8','-B']+args,cwd=cwd,capture_output=True,text=True,encoding='utf-8')
            d=json.loads(p.stdout)
            assert len(p.stdout.strip().splitlines())==1 and not p.stderr.strip(), 'checker_output_shape'
            runs[mode]=d
            summary.append({'set':name,'mode':mode,'exit_code':p.returncode,'status':d['status'],'errors':d.get('errors',[])})
        assert runs['root']==runs['absolute'], 'checker_mode_disagreement'
        (root/'authoring/checker-runs.json').write_text(json.dumps(runs,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(summary,ensure_ascii=False))
    return 0 if all(x['exit_code']==0 and x['status']=='PASS' for x in summary) else 1

if __name__=='__main__':
    raise SystemExit(main())
