"""Final authorized-corpus name, title, input-similarity and frozen-byte audit."""
from difflib import SequenceMatcher
import hashlib
import json
from pathlib import Path
import unicodedata

REPO = Path(__file__).resolve().parents[3]
SETS = ['eval_set_a3f2_formal', 'eval_set_a3s2_formal']
BANNED = {'eval_set_a1_reserve', 'eval_set_a1b_reserve', 'eval_set_v13_authoring',
          'eval_set_a26_formal', 'eval_set_a2s6_formal'}


def load(p):
    return json.loads(p.read_text(encoding='utf-8'))


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def norm(s):
    return ''.join(c for c in s if not c.isspace() and not unicodedata.category(c).startswith('P'))


def main():
    errors, names, titles, queries, groups, hashes = [], [], [], [], set(), {}
    roots = {s: REPO/'evaluation'/s for s in SETS}
    refs = load(roots[SETS[0]]/'authoring/novelty-reference.json')
    copy_errors = 0
    for sid, root in roots.items():
        data = load(root/'tasks.json')
        review = load(root/'authoring/self-review.json')['works']
        ownref = load(root/'authoring/novelty-reference.json')
        for field in ('source_hashes', 'names_corpus_sha256', 'normalized_inputs'):
            if ownref[field] != refs[field]:
                errors.append('reference:inconsistent')
        for w in data['works']:
            names.extend(w['names'])
            titles.append(w['title'])
        for wr in review.values():
            groups.update(frozenset(x) for x in wr['same_input_groups'])
        for t in data['tasks']:
            queries.append((t['id'], norm(t['input'] if t['suite']=='route' else t['request'])))
        checks = load(root/'authoring/check-results.json')
        copy_errors += checks['module']['output']['copy_errors']
        for mode in ('module','absolute'):
            for rel, h in checks[mode]['data_sha256'].items():
                if digest(root/rel) != h:
                    errors.append(sid+':check_capture_stale')
        hashes[sid] = {'tasks_sha256':digest(root/'tasks.json'), 'manifest_sha256':digest(root/'set.sha256')}
    name_hits = title_hits = corpus_drift = 0
    for rel, expected in refs['names_corpus_sha256'].items():
        p = (REPO/rel).resolve()
        if not p.is_relative_to(REPO/'evaluation') or BANNED.intersection(p.parts) or any(x in p.parts for x in SETS):
            errors.append('corpus:unsafe_path')
            continue
        raw = p.read_bytes()
        corpus_drift += hashlib.sha256(raw).hexdigest() != expected
        text = raw.decode('utf-8-sig')
        name_hits += sum(n in text for n in names)
        title_hits += sum(t in text for t in titles)
    for rel, h in refs['source_hashes'].items():
        p = (REPO/rel).resolve()
        if not p.is_relative_to(REPO/'evaluation') or BANNED.intersection(p.parts):
            errors.append('inputs:unsafe_path')
            continue
        corpus_drift += digest(p) != h
    external_errors, internal_errors, max_external, max_internal = 0, 0, 0.0, 0.0
    bad_pairs = []
    for i, (tid, value) in enumerate(queries):
        for j, old in enumerate(refs['normalized_inputs'],1):
            ratio = SequenceMatcher(None,value,old,autojunk=False).ratio()
            max_external = max(max_external,ratio)
            if ratio >= .8:
                external_errors += 1
                bad_pairs.append({'id':tid,'old_index':j,'ratio':ratio})
        for oid, other in queries[:i]:
            if frozenset((tid,oid)) in groups:
                continue
            ratio = SequenceMatcher(None,value,other,autojunk=False).ratio()
            max_internal = max(max_internal,ratio)
            if ratio >= .8:
                internal_errors += 1
                bad_pairs.append({'id':tid,'other_id':oid,'ratio':ratio})
    if name_hits or title_hits or corpus_drift or external_errors or internal_errors or copy_errors or len(names)!=len(set(names)):
        errors.append('lexical:constraint')
    result = {'status':'FAIL' if errors else 'PASS', 'errors':errors, 'names':len(names), 'unique_names':len(set(names)),
              'titles':len(titles), 'names_overlap':name_hits, 'titles_overlap':title_hits, 'corpus_drift':corpus_drift,
              'old_source_files':len(refs['source_hashes']), 'old_text_files':len(refs['names_corpus_sha256']),
              'old_normalized_inputs':len(refs['normalized_inputs']), 'new_inputs':len(queries),
              'new_unique_normalized_inputs':len({v for _,v in queries}), 'allowed_same_input_groups':len(groups),
              'copy_errors':copy_errors, 'novelty_errors':external_errors, 'internal_novelty_errors':internal_errors,
              'max_external_similarity':max_external, 'max_internal_similarity_excluding_groups':max_internal,
              'bad_pairs':bad_pairs, 'bindings':hashes, 'excluded_directories':sorted(BANNED)}
    (roots[SETS[0]]/'authoring/lexical-audit.json').write_text(json.dumps(result,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps(result,ensure_ascii=False,sort_keys=True))
    return int(bool(errors))


if __name__=='__main__':
    raise SystemExit(main())
