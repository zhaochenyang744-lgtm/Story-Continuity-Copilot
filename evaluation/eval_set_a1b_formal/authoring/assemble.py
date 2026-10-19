"""Serialize primary-authored records; never generates or edits fiction or golds.

Run only after all 120 source chapters exist. Numeric authoring references are
mapped to exact source headings. Copies and verbatim review quotes are audited.
"""
from copy import deepcopy
import hashlib
import importlib.util
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
A = ROOT / 'authoring'

def read(name):
    return json.loads((A / name).read_text(encoding='utf-8'))

def write(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n', encoding='utf-8', newline='\n')

spec = importlib.util.spec_from_file_location('local_checker', ROOT / 'check.py')
c = importlib.util.module_from_spec(spec)
spec.loader.exec_module(c)
bible = read('story-bible.json')
safety = read('safety-authoring.json')
shared = read('shared-drafts.json')
quotes = read('quote-selections.json')['quotes']
sources, titles, bodies = {}, {}, {}
for w in bible['works']:
    key = w['key']
    source = (ROOT / 'works' / (key + '.md')).read_text(encoding='utf-8')
    hits = list(re.finditer(r'^# (.+)$', source, re.M))
    assert len(hits) == w['chapters'], key + ':incomplete_source'
    titles[key] = {i+1:h.group(1) for i,h in enumerate(hits)}
    bodies[key] = {h.group(1):source[h.end():hits[i+1].start() if i+1<len(hits) else len(source)].strip() for i,h in enumerate(hits)}
    assert all(c.chapter_number(t)==n for n,t in titles[key].items())
    sources[key] = {'source':source, 'chapters':bodies[key], 'numbers':{t:n for n,t in titles[key].items()}}

def map_refs(key, refs):
    return [titles[key][x] if isinstance(x,int) else x for x in refs]

works, work_reviews = [], []
for w in bible['works']:
    key = w['key']
    if key == 's2':
        works.append(deepcopy(safety['work']))
        work_reviews.append(deepcopy(safety['work_review']))
        continue
    names = [x for ch in w['characters'] for x in [ch['name']] + ch['aliases']]
    names += w['places'] + [o['object'] for o in w['objects']]
    names += [f['subject'] for f in w['intentional_conflicts']]
    if key == 'l2':
        names.append('红脉标本')
    names = list(dict.fromkeys(names))
    assert all(n in sources[key]['source'] for n in names), key + ':name_absent'
    works.append({'key':key, 'title':w['title'], 'language':'zh', 'source_file':'works/'+key+'.md', 'purpose':'general', 'kind':w['kind'], 'names':names,
        'plans':deepcopy(w['plans']),
        'foreshadows':[{k:v for k,v in t.items() if k in {'title','planted_chapter','status','resolved_chapter'}} for t in w['threads']],
        'shared_draft':deepcopy(shared[key])})
    work_reviews.append({'key':key, 'characters':deepcopy(w['characters']),
        'initial_objects':[{k:v for k,v in o.items() if k!='transfers'} for o in w['objects']],
        'transfers':[dict(object=o['object'], **x) for o in w['objects'] for x in o['transfers']],
        'states':deepcopy(w['states']), 'threads':deepcopy(w['threads']),
        'intentional_conflicts':[dict(subject=f['subject'], chapters=f['chapters'], quotes=f['facts'], preserve=True, rationale=f['constraint']) for f in w['intentional_conflicts']]})

tasks, reviews = [], []
for filename in ['long-questions.json','fix-recap-questions.json','follow-questions.json']:
    fragment = read(filename)
    by_id = {r['id']:r for r in fragment['review_notes']}
    for original in fragment['tasks']:
        t = deepcopy(original)
        tid,key = t['id'],t['work']
        r = deepcopy(by_id[tid])
        if 'first_evidence_chapters' in t:
            r['first_evidence_chapters'] = map_refs(key,t.pop('first_evidence_chapters'))
        if 'evidence_chapters' in t:
            t['evidence_chapters'] = map_refs(key,t['evidence_chapters'])
        for m in t.get('must_mention',[]):
            m['evidence_chapters'] = map_refs(key,m['evidence_chapters'])
        r['evidence_quotes'] = [{'chapter':titles[key][n], 'text':text} for n,text in quotes[tid]]
        for q in r['evidence_quotes']:
            assert q['text'] in bodies[key][q['chapter']], tid + ':quote_mismatch'
        refs = t.get('evidence_chapters',[]) + r.get('first_evidence_chapters',[]) + [ref for m in t.get('must_mention',[]) for ref in m['evidence_chapters']]
        nums = [sources[key]['numbers'][ref] for ref in refs]
        if key == 'l2':
            r['chapter_gap'] = (min(101-n for n in nums) if t['suite']=='fix' else max(nums)-min(nums)) if nums else 0
        tasks.append(t)
        reviews.append(r)
tasks += deepcopy(safety['tasks'])
reviews += deepcopy(safety['reviews'])
order = {'qa':0,'recap':1,'fix':2,'follow_up':3,'safe':4}
tasks.sort(key=lambda t:(order[t['suite']],t['id']))
review_map = {r['id']:r for r in reviews}
reviews = [review_map[t['id']] for t in tasks]
assert len(tasks)==47
c.WORKS = {w['key']:w for w in works}
c.SOURCES = sources
c.FIRST_REFS = {r['id']:r.get('first_evidence_chapters',[]) for r in reviews}
for t,r in zip(tasks,reviews):
    refs = t.get('evidence_chapters',[]) + r.get('first_evidence_chapters',[]) + [ref for m in t.get('must_mention',[]) for ref in m['evidence_chapters']]
    c.check_copy(t,refs)
assert not c.ERRORS, ','.join(c.ERRORS)
for r in reviews:
    r['copy_check'] = 'pass'

independent_records = [read(name) for name in ['independent-l2-review.json','independent-n-review.json','independent-s2-review.json'] if (A/name).exists()]
covered = {key:n for r in independent_records if r.get('status')=='completed' for key,n in r['reviewed_chapter_counts'].items()}
completed = covered == {'l2':100,'n':12,'s2':8} and all(r.get('unresolved_unintentional_conflicts')==0 and r.get('unresolved_gold_ambiguities')==0 for r in independent_records)
independent = {'reviewer_not_author':True, 'status':'completed' if completed else 'pending',
    'reviewed_chapter_counts':covered,
    'unresolved_unintentional_conflicts':sum(r.get('unresolved_unintentional_conflicts',0) for r in independent_records),
    'unresolved_gold_ambiguities':sum(r.get('unresolved_gold_ambiguities',0) for r in independent_records),
    'findings':[f for r in independent_records for f in r.get('findings',[])],
    'intentional_conflicts_preserved':[dict(work=next(iter(r['reviewed_chapter_counts'])),**f) for r in independent_records for f in r.get('intentional_conflicts',[])],
    'records':independent_records}
if (A/'independent-assembly-review.json').exists():
    independent['final_assembly_review'] = read('independent-assembly-review.json')
data = {'version':'a1b-1','set_id':'a1b-formal','author':'任务07a出题','works':works,'tasks':tasks}
review = {'set_id':'a1b-formal','works':work_reviews,'tasks':reviews,'independent_review':independent,
    'authoring':{'bible_before_prose':True,'primary_authored_all_questions_and_golds':True,'chapter_prose_method':'逐章独立原创；程序仅保存已写定文本、机械映射引用与审计。', 'accepted_handoffs':deepcopy(bible['accepted_handoffs']), 'model_calls':0, 'product_runs':0},
    'mechanical_copy_audit':{'status':'PASS','errors':0,'tasks':47,'includes_first_questions_and_shared_drafts':True},
    'semantic_boundary':'结构检查结果与独立语义复核分别记录；没有模型或产品评测结论。'}
write(ROOT/'tasks.json',data)
write(A/'self-review.json',review)
paths = sorted([ROOT/'tasks.json']+[p for p in (ROOT/'works').rglob('*') if p.is_file()],key=lambda p:p.relative_to(ROOT).as_posix())
(ROOT/'set.sha256').write_text(''.join(hashlib.sha256(p.read_bytes()).hexdigest()+'  '+p.relative_to(ROOT).as_posix()+'\n' for p in paths),encoding='utf-8',newline='\n')
print(json.dumps({'assembled_tasks':len(tasks),'copy_errors':c.COPY_ERRORS,'independent_review':independent['status']},sort_keys=True))
