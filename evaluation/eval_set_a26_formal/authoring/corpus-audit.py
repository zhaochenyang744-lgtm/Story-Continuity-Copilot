"""Offline source provenance, names and input novelty; never emits source text."""
from pathlib import Path
from difflib import SequenceMatcher
import hashlib
import json
import os
import sys
import unicodedata

REPO = Path(__file__).resolve().parents[3]
SETS = [REPO / 'evaluation' / n for n in ('eval_set_a26_formal', 'eval_set_a2s6_formal')]
BLOCKED = {'eval_set_a3f2_formal', 'eval_set_a3s2_formal'}
SEALED = ['eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring']
NEW = {p.name for p in SETS}
EXT = {'.md', '.json', '.jsonl', '.txt', '.py'}
PLANNED = [
    ['黎见棠','许泊垣','周砚荞','宁晏菱','贺以蘅','任澄蓁','姜序弥','樊予蔚','荻瓣','榛屿','柑芽','澜苒市','莳页册','萼弧坠','卷云杯'],
    ['柴予萱','陆照苒','柴照棠','杨映荃','陆问杉','方若荻','柴闻序','陆筱砚','蓼芽','黛团','杉栖','筠洄市','禾角册','瓷棉熊','雾纹包','予萱','照苒'],
    ['夏聆榆','蒋未苒','陆惟荃','肖寄绫','陶令樾','尹棠叙','欧祈蔓','孟知嵩','蓬铃','麦隅','桐芒','涟芷市','苇穹泳馆','岚格袋','汀叶夹','涡纹绳']
]

def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()

def norm(s):
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))

def inputs(obj):
    out = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in {'input', 'question', 'request'} and isinstance(v, str) and v.strip():
                out.append(norm(v))
            elif isinstance(v, (dict, list)):
                out.extend(inputs(v))
    elif isinstance(obj, list):
        for v in obj:
            out.extend(inputs(v))
    return out

def write(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

def corpus():
    ordinary, sealed, texts = {}, {}, {}
    for base, dirs, files in os.walk(REPO / 'evaluation'):
        # Prune absolutely forbidden names before any child traversal or file access.
        dirs[:] = sorted(d for d in dirs if d not in BLOCKED | NEW | {'__pycache__', '.git', 'node_modules'})
        path = Path(base)
        if not any(p.startswith('eval_set_') for p in path.relative_to(REPO / 'evaluation').parts):
            continue
        for name in sorted(files):
            p = path / name
            if p.suffix not in EXT:
                continue
            rel = p.relative_to(REPO).as_posix()
            try:
                s = p.read_text(encoding='utf-8-sig')
            except UnicodeError:
                continue
            obj = None
            if p.suffix == '.json':
                try:
                    obj = json.loads(s)
                    s = json.dumps(obj, ensure_ascii=False)
                except (ValueError, TypeError):
                    pass
            group = sealed if any(part in SEALED for part in p.parts) else ordinary
            group[rel] = {'hash': sha(p), 'inputs': inputs(obj) if name == 'tasks.json' else []}
            texts[rel] = s
    return ordinary, sealed, texts

def main():
    ordinary, sealed, texts = corpus()
    if '--preflight' in sys.argv:
        names = sum(PLANNED, [])
        collisions = [i for i, n in enumerate(names, 1) if any(n in s for s in texts.values())]
        out = {'names': len(names), 'overlap': len(collisions), 'name_indices': collisions,
               'text_files': len(texts), 'blocked_directories_accessed': 0}
        write(SETS[0] / 'authoring/name-preflight.json', out)
        print(json.dumps(out))
        return
    data = [json.loads((p / 'tasks.json').read_text(encoding='utf-8')) for p in SETS]
    all_inputs = [inputs(d['tasks']) for d in data]
    for i, (root, d) in enumerate(zip(SETS, data)):
        names = sorted(n for w in d['works'] for n in w['names'])
        sibling_files = [SETS[1-i]/'tasks.json'] + [p for folder in ('works','materials')
                                                   for p in (SETS[1-i]/folder).rglob('*') if p.is_file()]
        sibling_text = '\n'.join(p.read_text(encoding='utf-8') for p in sibling_files)
        name_count = sum(any(n in texts[rel] for rel in ordinary) or n in sibling_text for n in names)
        sealed_names = sum(any(n in texts[rel] for rel in sealed) for n in names)
        grouped = {rel: sorted(set(item['inputs'])) for rel, item in ordinary.items() if Path(rel).name == 'tasks.json'}
        # A sibling candidate is authorized, fresh, and must also differ.
        sibling_rel = (SETS[1-i] / 'tasks.json').relative_to(REPO).as_posix()
        grouped[sibling_rel] = sorted(set(all_inputs[1-i]))
        source_hashes = {rel: item['hash'] for rel, item in ordinary.items() if Path(rel).name == 'tasks.json'}
        source_hashes[sibling_rel] = sha(SETS[1-i] / 'tasks.json')
        old = sorted({s for arr in grouped.values() for s in arr})
        text_hashes = {rel:item['hash'] for rel,item in ordinary.items()}
        text_hashes.update({p.relative_to(REPO).as_posix():sha(p) for p in sibling_files})
        reference = {'normalization': 'remove_whitespace_and_unicode_punctuation_preserve_case',
                     'excluded_directories': SEALED, 'source_hashes': source_hashes,
                     'normalized_inputs_by_source': grouped, 'normalized_inputs': old,
                     'names_corpus_sha256': text_hashes,
                     'reference_counts': {'source_files': len(source_hashes), 'normalized_inputs': len(old), 'names_text_files': len(text_hashes)},
                     'names_overlap': name_count,
                     'candidate_names_sha256': hashlib.sha256(json.dumps(names, ensure_ascii=False).encode('utf-8')).hexdigest()}
        seal_inputs = sorted({s for v in sealed.values() for s in v['inputs']})
        novelty = sum(any(n == s or (2*min(len(n),len(s))/max(1,len(n)+len(s)) >= .8 and SequenceMatcher(None,n,s).ratio() >= .8)
                          for s in seal_inputs) for n in all_inputs[i])
        paths = sorted(['tasks.json'] + [p.relative_to(root).as_posix() for folder in ('works','materials')
                                       for p in (root/folder).rglob('*') if p.is_file()])
        receipt = {'status': 'PASS' if not sealed_names and not novelty else 'FAIL',
                   'candidate_sha256': {rel: sha(root/rel) for rel in paths},
                   'names_overlap': sealed_names, 'novelty_errors': novelty,
                   'source_hashes': {rel:v['hash'] for rel,v in sealed.items()}, 'excluded_directories': SEALED,
                   'reference_counts': {'source_files': sum(Path(rel).name=='tasks.json' for rel in sealed),
                                        'normalized_inputs': len(seal_inputs), 'names_text_files': len(sealed)}}
        write(root/'authoring/novelty-reference.json', reference)
        write(root/'authoring/sealed-comparison.json', receipt)
        print(json.dumps({'set': i+1, 'names_overlap':name_count+sealed_names,'sealed_novelty_errors':novelty,
                          'reference_inputs':len(old), 'blocked_directories_accessed':0}))

if __name__ == '__main__':
    main()
