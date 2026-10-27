"""Authoring counts for lead-authored text before independent review; not an acceptance checker."""
from pathlib import Path
from difflib import SequenceMatcher
import json
import runpy

HERE=Path(__file__).resolve().parent

def main():
    corpus_api=runpy.run_path(str(HERE/'corpus-audit.py'))
    ordinary,sealed,texts=corpus_api['corpus']()
    old=sorted({s for group in (ordinary,sealed) for item in group.values() for s in item['inputs']})
    roots=corpus_api['SETS']
    data={p:json.loads((p/'tasks.json').read_text(encoding='utf-8')) for p in roots if (p/'tasks.json').exists()}
    result=[]
    for root,d in data.items():
        api=runpy.run_path(str(root/'check.py'))
        refs={w['key']:set().union(*(api['grams'](c['body'],w['names'])
                        for c in api['chapter_map']((root/w['source_file']).read_text(encoding='utf-8')).values())) for w in d['works']}
        works={w['key']:w for w in d['works']}
        sibling=[corpus_api['norm'](t.get('request',t.get('input',''))) for p,x in data.items() if p!=root for t in x['tasks']]
        errors=[]
        for t in d['tasks']:
            fields=[('input' if t['suite']=='route' else 'request',t.get('input',t.get('request','')))]
            fields += [(f'point:{i}:{j}',s) for i,a in enumerate(t.get('expected_actions',t.get('allowed_actions',[])),1)
                       for j,s in enumerate(a['after_points'],1)]
            for field,s in fields:
                if api['grams'](s,works[t['work']]['names']) & refs[t['work']]:errors.append(t['id']+':'+field+':copy8')
            n=corpus_api['norm'](fields[0][1])
            if any(n==s or (2*min(len(n),len(s))/max(1,len(n)+len(s))>=.8 and SequenceMatcher(None,n,s).ratio()>=.8) for s in old+sibling):
                errors.append(t['id']+':novelty80')
        names=[n for w in d['works'] for n in w['names']]
        overlaps=sum(any(n in s for s in texts.values()) for n in names)
        out={'set':root.name,'tasks':len(d['tasks']),'text_errors':errors,'names_overlap':overlaps,
             'acceptance_check':False,'blocked_directories_accessed':0}
        (root/'authoring/text-precheck.json').write_text(json.dumps(out,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
        result.append(out)
    print(json.dumps(result,ensure_ascii=False))
    return 0 if result and all(not x['text_errors'] and not x['names_overlap'] for x in result) else 1

if __name__=='__main__':
    raise SystemExit(main())
