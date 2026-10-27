"""Bind existing, completed review decisions and freeze the exact data bytes."""
from pathlib import Path
import hashlib
import json

REPO=Path(__file__).resolve().parents[3]

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def main():
    out=[]
    for name in ('eval_set_a26_formal','eval_set_a2s6_formal'):
        root=REPO/'evaluation'/name
        review=load(root/'authoring/independent-review.json')
        assert review['status']=='completed' and review['unresolved_findings']==0
        data=load(root/'tasks.json')
        assert set(review['source_reports'])=={w['key'] for w in data['works']}
        for w in data['works']:
            report=load(root/review['source_reports'][w['key']])
            count=12 if name=='eval_set_a2s6_formal' else 20
            assert report['status']=='completed' and report['unresolved_findings']==0
            assert report['chapters_read']==list(range(1,count+1))
            assert report['source_sha256']==sha(root/w['source_file'])
            body=w['shared_draft']['body']
            assert report['draft_body_sha256']==hashlib.sha256(body.encode('utf-8')).hexdigest()
            assert report['tasks_sha256']==sha(root/'tasks.json')
            assert report['materials_sha256']=={p:sha(root/p) for p in w['materials'].values()}
        paths=sorted(['tasks.json']+[p.relative_to(root).as_posix() for folder in ('works','materials')
                                  for p in (root/folder).rglob('*') if p.is_file()])
        hashes={rel:sha(root/rel) for rel in paths}
        receipt=load(root/'authoring/sealed-comparison.json')
        assert receipt['status']=='PASS' and receipt['candidate_sha256']==hashes
        assert receipt['names_overlap']==0 and receipt['novelty_errors']==0
        review['sha256']=hashes
        review['authoring_sha256']={rel:sha(root/rel) for rel in (
            'authoring/self-review.json','authoring/self-review.md','authoring/novelty-reference.json','authoring/sealed-comparison.json')}
        # The lead supplies the actual reviewed report paths; no completed decision is invented here.
        assert review['reports']
        review['reports']={rel:sha(root/rel) for rel in review['reports']}
        (root/'authoring/independent-review.json').write_text(json.dumps(review,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        (root/'set.sha256').write_text(''.join(f'{h}  {rel}\n' for rel,h in hashes.items()),encoding='utf-8',newline='\n')
        out.append({'set':name,'data_files':len(hashes),'manifest_sha256':sha(root/'set.sha256')})
    print(json.dumps(out))

if __name__=='__main__':
    main()
