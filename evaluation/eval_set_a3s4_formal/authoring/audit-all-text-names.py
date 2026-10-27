"""Exact candidate comparison against every UTF-8-decodable old set file; counts only."""
from pathlib import Path
import hashlib
import json

ROOT=Path(__file__).resolve().parents[1]
data=json.loads((ROOT/'tasks.json').read_text(encoding='utf-8'))
names=sorted({n for w in data['works'] for n in w['names']+[w['title']]})
excluded={'eval_set_a1_reserve','eval_set_a1b_reserve','eval_set_v13_authoring','eval_set_a26_formal','eval_set_a2s6_formal','eval_set_a2n7_formal'}
result={k:dict(files=0,bytes=0,matched_names=0,matched_files=0,occurrences=0,undecodable_files=0) for k in ['readable','sealed_program_only']}
matched={k:set() for k in result};corpus={k:hashlib.sha256() for k in result}
for directory in sorted(ROOT.parent.glob('eval_set_*')):
    if not directory.is_dir() or directory==ROOT:continue
    kind='sealed_program_only' if directory.name in excluded else 'readable'
    for p in sorted(directory.rglob('*')):
        if not p.is_file():continue
        raw=p.read_bytes()
        try:text=raw.decode('utf-8-sig')
        except UnicodeDecodeError:
            result[kind]['undecodable_files']+=1;continue
        result[kind]['files']+=1;result[kind]['bytes']+=len(raw)
        occurrences=sum(text.count(n) for n in names)
        result[kind]['matched_files']+=int(occurrences>0)
        result[kind]['occurrences']+=occurrences
        matched[kind].update(n for n in names if n in text)
        rel=p.relative_to(ROOT.parent).as_posix()
        corpus[kind].update((rel+'\0'+hashlib.sha256(raw).hexdigest()+'\n').encode('utf-8'))
for kind in result:
    result[kind]['matched_names']=len(matched[kind]);result[kind]['corpus_sha256']=corpus[kind].hexdigest()
out=dict(status='PASS' if not any(v['matched_names'] for v in result.values()) else 'FAIL',candidate_names=len(names),candidate_names_sha256=hashlib.sha256(json.dumps(names,ensure_ascii=False).encode()).hexdigest(),plaintext_outputs=0,**result)
(ROOT/'authoring/names-all-text-audit.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
print(json.dumps(out,ensure_ascii=False))
raise SystemExit(out['status']!='PASS')
