"""Offline authoring audits. No generation of narrative or calls to any service."""
from pathlib import Path
from difflib import SequenceMatcher
from collections import Counter
import hashlib, json, re, subprocess, sys, unicodedata

REPO = Path(__file__).resolve().parents[3]
EVAL = REPO / 'evaluation'
FORMAL = EVAL / 'eval_set_a25_formal'
SAFETY = EVAL / 'eval_set_a2s5_formal'
NEW = {FORMAL.name, SAFETY.name}
SEALED = sorted({'eval_set_a3_formal', 'eval_set_a3s_formal', 'eval_set_a1_reserve',
                 'eval_set_a1b_reserve', 'eval_set_v13_authoring'})
HAN = re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')

def sha(p): return hashlib.sha256(p.read_bytes()).hexdigest()
def read(p): return json.loads(p.read_text(encoding='utf-8-sig'))
def write(p, data): p.write_text(json.dumps(data, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
def norm(s): return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))
def inputs(data):
    found=set()
    def visit(value):
        if isinstance(value,dict):
            for k,v in value.items():
                if k in ('input','question','request') and isinstance(v,str) and norm(v):found.add(norm(v))
                else:visit(v)
        elif isinstance(value,list):
            for v in value:visit(v)
    visit(data)
    return sorted(found)
def data_paths(root):
    return sorted([root/'tasks.json']+[p for folder in ('works','materials')
        for p in (root/folder).rglob('*') if p.is_file()])
def data_hashes(root): return {p.relative_to(root).as_posix():sha(p) for p in data_paths(root)}

def baseline():
    paths=subprocess.check_output(['git','ls-files','-z'],cwd=REPO).decode('utf-8').split('\0')
    record={p:sha(REPO/p) for p in paths if p and p!='.gitattributes'}
    write(FORMAL/'authoring/protected-baseline.json', {'head':subprocess.check_output(
        ['git','rev-parse','HEAD'],cwd=REPO).decode().strip(),'tracked_sha256':record})
    print(json.dumps({'protected_files':len(record)}))

def references():
    candidates=[]
    for root in (FORMAL,SAFETY):
        d=read(root/'tasks.json'); names=[n for w in d['works'] for n in w['names']]
        candidates.append((root,d,names,inputs(d)))
    open_hashes={}; open_grouped={}; open_text_hashes={}; sealed_hashes={}; sealed_input_count=0
    name_count=[0,0]; sealed_names=[0,0]; novel=[0,0]; sealed_novel=[0,0]
    for folder in sorted(EVAL.glob('eval_set*')):
        if not folder.is_dir() or folder.name in NEW: continue
        sealed=folder.name in SEALED
        tp=folder/'tasks.json'
        if tp.is_file():
            old=inputs(read(tp))
            if sealed: sealed_input_count+=len(old)
            else:
                rel=tp.relative_to(REPO).as_posix();open_hashes[rel]=sha(tp);open_grouped[rel]=old
            for i,(_,_,_,new_inputs) in enumerate(candidates):
                hits=sum(any(a==b or (2*min(len(a),len(b))/max(1,len(a)+len(b))>=.8 and
                    SequenceMatcher(None,a,b).ratio()>=.8) for b in old) for a in new_inputs)
                (sealed_novel if sealed else novel)[i]+=hits
        for p in sorted(folder.rglob('*')):
            if not p.is_file() or p.suffix.lower() not in {'.md','.json','.jsonl','.txt','.csv','.yaml','.yml'}:continue
            try: text=p.read_text(encoding='utf-8-sig')
            except (UnicodeError,OSError):continue
            rel=p.relative_to(REPO).as_posix()
            (sealed_hashes if sealed else open_text_hashes)[rel]=sha(p)
            for i,(_,_,names,_) in enumerate(candidates):
                (sealed_names if sealed else name_count)[i]+=sum(n in text for n in names)
    snapshot={'normalization':'remove_whitespace_and_unicode_punctuation_preserve_case',
      'excluded_directories':SEALED,'source_hashes':open_hashes,'normalized_inputs_by_source':open_grouped,
      'normalized_inputs':sorted({v for vals in open_grouped.values() for v in vals}),
      'names_corpus_sha256':open_text_hashes}
    snapshot['reference_counts']={'source_files':len(open_hashes),'normalized_inputs':len(snapshot['normalized_inputs']),
      'names_text_files':len(open_text_hashes)}
    for i,(root,_,_,_) in enumerate(candidates):
        local_snapshot=dict(snapshot)
        local_snapshot['names_overlap']=name_count[i]
        local_snapshot['candidate_names_sha256']=hashlib.sha256(json.dumps(
            sorted(candidates[i][2]),ensure_ascii=False).encode('utf-8')).hexdigest()
        write(root/'authoring/novelty-reference.json',local_snapshot)
        sealed={'status':'PASS' if sealed_names[i]==sealed_novel[i]==0 else 'FAIL',
          'candidate_sha256':data_hashes(root),'names_overlap':sealed_names[i],'novelty_errors':sealed_novel[i],
          'source_hashes':sealed_hashes,'excluded_directories':SEALED,'reference_counts':{
          'source_files':sum(Path(p).name=='tasks.json' for p in sealed_hashes),
          'normalized_inputs':sealed_input_count,'names_text_files':len(sealed_hashes)}}
        write(root/'authoring/sealed-comparison.json',sealed)
    cross=sum(SequenceMatcher(None,a,b).ratio()>=.8 for a in candidates[0][3] for b in candidates[1][3])
    result={'open_names_overlap':name_count,'sealed_names_overlap':sealed_names,'open_novelty_errors':novel,
      'sealed_novelty_errors':sealed_novel,'cross_set_novelty_errors':cross,
      'open_reference_counts':snapshot['reference_counts'],'sealed_reference_counts':sealed['reference_counts']}
    write(FORMAL/'authoring/corpus-audit.json',result);print(json.dumps(result))

def manifests():
    for root in (FORMAL,SAFETY):
        (root/'set.sha256').write_text(''.join(f'{h}  {p}\n' for p,h in data_hashes(root).items()),encoding='utf-8')
    print(json.dumps({'manifests':2}))

def bind():
    for root in (FORMAL,SAFETY):
        p=root/'authoring/independent-review.json';d=read(p)
        d['sha256']=data_hashes(root)
        d['authoring_sha256']={f'authoring/{n}':sha(root/'authoring'/n) for n in (
           'self-review.json','self-review.md','novelty-reference.json','sealed-comparison.json')}
        d['reports']={p.relative_to(root).as_posix():sha(p) for p in sorted((root/'authoring').glob('*review*.md'))
           if p.name!='self-review.md'}
        for p in sorted((root/'authoring').glob('*blind*.json')):d['reports'][p.relative_to(root).as_posix()]=sha(p)
        write(root/'authoring/independent-review.json',d)
    print(json.dumps({'bindings':2}))

def integrity():
    baseline=read(FORMAL/'authoring/protected-baseline.json')['tracked_sha256']
    changes=sum(not (REPO/p).is_file() or sha(REPO/p)!=h for p,h in baseline.items())
    print(json.dumps({'protected_files':len(baseline),'changed':changes}))
    return changes

if __name__=='__main__':
    commands={'baseline':baseline,'references':references,'manifests':manifests,'bind':bind,'integrity':integrity}
    result=commands[sys.argv[1]]();sys.exit(1 if result else 0)
