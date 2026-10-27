"""Offline counts, locations, integrity and review binding. No prose generation."""
from pathlib import Path
from collections import Counter
import hashlib
import importlib.util
import json
import re
import sys

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
HAN=re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def read(rel):return json.loads((ROOT/rel).read_text(encoding='utf-8'))
def save(rel,value):(ROOT/rel).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
spec=importlib.util.spec_from_file_location('a3s4_checker',ROOT/'check.py')
checker=importlib.util.module_from_spec(spec);spec.loader.exec_module(checker)
data=read('tasks.json');review=read('authoring/self-review.json')
source=(ROOT/'works/w01.md').read_text(encoding='utf-8')
chs=checker.chapters(source)

if '--positions' in sys.argv:
    points=[]
    def collect(v,path):
        if isinstance(v,dict):
            if 'chapter' in v and 'quote' in v:
                body=chs.get(v['chapter'],{}).get('body','');q=v['quote']
                points.append(dict(path=path,chapter=v['chapter'],matches=body.count(q),han_position=len(HAN.findall(body[:body.index(q)]))+1 if q in body else 0))
            for k,x in v.items():collect(x,path+'.'+k)
        elif isinstance(v,list):
            for i,x in enumerate(v,1):collect(x,path+'.'+str(i))
    collect(review,'review')
    injections=[]
    for t in data['tasks']:
        loc=t['injection']['location'];n=loc.get('chapter')
        if loc['kind']=='chapter':
            body=chs[n]['body'];q=t['injection']['text']
            injections.append(dict(id=t['id'],chapter=n,matches=body.count(q),han_position=len(HAN.findall(body[:body.index(q)]))+1 if q in body else 0))
    paras=[p.strip() for p in source.split('\n\n') if len(HAN.findall(p))>=30 and not p.lstrip().startswith('#')]
    dup=[n for p,n in Counter(paras).items() if n>1]
    encoding_bad=[]
    for p in ROOT.rglob('*'):
        if p.is_file() and 'negative-tmp' not in p.parts:
            raw=p.read_bytes()
            if raw.startswith(b'\xef\xbb\xbf') or b'\r' in raw:encoding_bad.append(p.relative_to(ROOT).as_posix())
    narrative='\n'.join(c['body'] for c in chs.values())
    meta_count=len(re.findall(r'第[0-9一二三四五六七八九十百]+章|金标|标准答案|追踪对象|评测考点',narrative))
    result=dict(chapter_han={str(n):len(HAN.findall(c['body'])) for n,c in chs.items()},total_han=sum(len(HAN.findall(c['body'])) for c in chs.values()),draft_han=len(HAN.findall(data['works'][0]['shared_draft']['body'])),points=points,chapter_injections=injections,repeated_paragraph_groups=len(dup),repeated_paragraph_extras=sum(n-1 for n in dup),strict_narrative_meta_matches=meta_count,encoding_errors=encoding_bad)
    save('authoring/position-audit.json',result)
    target=ROOT/'authoring/self-review.md';text=target.read_text(encoding='utf-8').split('\n<!-- numeric-audit -->')[0]
    lines=['','<!-- numeric-audit -->','','### 原句位置数值表','','|结构路径|章|精确出现次数|章内汉字位|','|---|---:|---:|---:|']
    lines += [f"|{p['path']}|{p['chapter']}|{p['matches']}|{p['han_position']}|" for p in points]
    lines += ['','### 正文注入位置','','|题目编号|章|精确出现次数|章内汉字位|','|---|---:|---:|---:|']
    lines += [f"|{p['id']}|{p['chapter']}|{p['matches']}|{p['han_position']}|" for p in injections]
    target.write_text(text+'\n'.join(lines)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({k:v for k,v in result.items() if k not in {'points','chapter_injections'}},ensure_ascii=False))

if '--bind' in sys.argv:
    paths=sorted(['tasks.json','works/w01.md','materials/w01-facts.json','materials/w01-foreshadows.json'])
    # Four data files: one work, two material arrays, one tasks file.
    first='authoring/independent-thread-w01.json'
    thread_text=(ROOT/'materials/w01-foreshadows.json').read_text(encoding='utf-8')
    first_record=read(first)
    assert first_record['foreshadows_sha256']==digest(ROOT/'materials/w01-foreshadows.json'), 'original blind material view must be preserved'
    blind_view=dict(source_sha256=first_record['source_sha256'],foreshadows_text=thread_text,foreshadows_sha256=first_record['foreshadows_sha256'],first_record_sha256=digest(ROOT/first))
    if (ROOT/'authoring/blind-thread-input-w01.json').exists():
        assert read('authoring/blind-thread-input-w01.json')==blind_view, 'first blind record and view must remain unchanged'
    else:save('authoring/blind-thread-input-w01.json',blind_view)
    proof=checker.verify_review_records(ROOT,data,review['works'])
    if proof['errors']:
        print(json.dumps(dict(status='FAIL',errors=proof['errors'])));raise SystemExit(1)
    bound=['authoring/self-review.json','authoring/self-review.md','authoring/novelty-reference.json']
    summary=dict(status='completed',unresolved_findings=0,chapter_coverage=proof['chapter_coverage'],sha256={p:digest(ROOT/p) for p in paths},authoring_sha256={p:digest(ROOT/p) for p in bound},review_files_sha256={p:digest(ROOT/p) for p in proof['raw_files']},blind_threads=proof['blind_threads'],checker_sha256=digest(ROOT/'check.py'))
    save('authoring/independent-review.json',summary)
    (ROOT/'set.sha256').write_text(''.join(digest(ROOT/p)+'  '+p+'\n' for p in paths),encoding='ascii',newline='\n')
    print(json.dumps(dict(status='BOUND',data_files=len(paths),raw_review_files=len(proof['raw_files']))))

if '--protected' in sys.argv:
    baseline=read('authoring/protected-baseline.json')['protected']
    changed=[p for p,h in baseline.items() if not (REPO/p).is_file() or digest(REPO/p)!=h]
    result=dict(protected_files=len(baseline),changed_count=len(changed),changed_paths=changed)
    save('authoring/protected-final.json',result)
    print(json.dumps(result,ensure_ascii=False))
