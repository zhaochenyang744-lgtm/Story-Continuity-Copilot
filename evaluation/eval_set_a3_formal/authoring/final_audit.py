"""Authoring-only cross-set and byte audits. Never emit source strings."""
from pathlib import Path
from difflib import SequenceMatcher
import hashlib
import json
import re
import runpy

ROOT=Path(__file__).resolve().parents[3]
FORMAL=ROOT/'evaluation/eval_set_a3_formal';SAFE=ROOT/'evaluation/eval_set_a3s_formal'
HAN=re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')


def main():
    helper=runpy.run_path(str(FORMAL/'authoring/build_metadata.py'),run_name='authoring_support')
    data=[json.loads((d/'tasks.json').read_text(encoding='utf-8')) for d in (FORMAL,SAFE)]
    work_names=[set(w['names']) for obj in data for w in obj['works']]
    all_names=[n for ns in work_names for n in ns]
    titles=[w['title'] for obj in data for w in obj['works']]
    reference=helper['reference'](all_names+titles)
    cross_names=sum(len(a&b) for i,a in enumerate(work_names) for b in work_names[:i])
    inputs=[[helper['norm'](t.get('input',t.get('request',''))) for t in obj['tasks']] for obj in data]
    cross_inputs=sum(SequenceMatcher(None,a,b,autojunk=False).ratio()>=.8 for a in inputs[0] for b in inputs[1])
    # Inspect every overlapping 80-Han window; quotes are shorter than this threshold.
    seen={};duplicate_windows=0;passage_pairs=set();source_chapters=0
    for di,(d,obj) in enumerate(zip((FORMAL,SAFE),data),1):
        for wi,w in enumerate(obj['works'],1):
            chs=helper['parse']((d/w['source_file']).read_text(encoding='utf-8'))
            for n,ch in chs.items():
                source_chapters+=1;body=''.join(HAN.findall(ch['body']));loc=(di,wi,n)
                for start in range(max(0,len(body)-79)):
                    g=body[start:start+80]
                    previous=seen.get(g)
                    if previous is not None:
                        duplicate_windows+=1;passage_pairs.add((previous,loc))
                    else:seen[g]=loc
    # Refresh only provenance snapshots; sources, task questions, and gold remain unchanged.
    for d,obj in zip((FORMAL,SAFE),data):
        ref=helper['reference']([n for w in obj['works'] for n in w['names']])
        (d/'authoring/novelty-reference.json').write_text(json.dumps(ref,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    byte_files=0;byte_errors=0
    for d in (FORMAL,SAFE):
        for p in d.rglob('*'):
            if p.is_file() and p.suffix in {'.md','.json','.py','.txt','.sha256'}:
                byte_files+=1;raw=p.read_bytes()
                if raw.startswith(b'\xef\xbb\xbf') or b'\r\n' in raw:byte_errors+=1
                raw.decode('utf-8')
    baseline=json.loads((FORMAL/'authoring/baseline.json').read_text(encoding='utf-8'))
    protected=['evaluation/assistant_a3/SPEC.md','evaluation/assistant_a3/thresholds.py']
    protected_errors=sum(hashlib.sha256((ROOT/p).read_bytes()).hexdigest()!=baseline['sha256'][p] for p in protected)
    result={'cross_work_names_overlap':cross_names,'new_names_and_titles_prior_overlap':reference['names_overlap'],
            'cross_set_input_similarity_conflicts':cross_inputs,'source_chapters':source_chapters,
            'repeated_80han_windows':duplicate_windows,'repeated_passage_pairs':len(passage_pairs),
            'byte_files':byte_files,'byte_errors':byte_errors,'protected_files':len(protected),'protected_hash_errors':protected_errors,
            'dev_branch_tasks_present':reference['dev_branch_tasks_present']}
    (FORMAL/'authoring/final-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    (SAFE/'authoring/final-audit.json').write_text(json.dumps(result,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,sort_keys=True))
    return int(any(result[k] for k in ('cross_work_names_overlap','new_names_and_titles_prior_overlap','cross_set_input_similarity_conflicts',
                                      'repeated_80han_windows','byte_errors','protected_hash_errors')))


if __name__=='__main__':raise SystemExit(main())
