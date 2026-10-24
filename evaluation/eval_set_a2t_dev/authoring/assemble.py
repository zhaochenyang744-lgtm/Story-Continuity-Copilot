"""Copy immutable sources and assemble authored packages, positions and review."""
import json
import re
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
HAN=re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
def read(p): return json.loads(p.read_text(encoding='utf-8'))
def write(p,x): p.write_text(json.dumps(x,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
works=[]; tasks=[]; reviews={}; md=['# A2 新动作调试集统一自查\n','状态：authoring；完整盲判记录另存，最终绑定在 independent-review.json。\n']
for wk,source in [('w01','eval_set_a23_formal'),('w02','eval_set_a24_formal')]:
    p=read(ROOT/f'authoring/{wk}-package.json')
    (ROOT/'works').mkdir(exist_ok=True); (ROOT/'materials').mkdir(exist_ok=True)
    for src,dst in [(f'evaluation/{source}/works/w01.md',f'works/{wk}.md'),(f'evaluation/{source}/materials/w01-facts.json',f'materials/{wk}-facts.json')]:
        (ROOT/dst).write_bytes((REPO/src).read_bytes())
    works.append(p['work']); tasks.extend(p['tasks']); reviews[wk]=p['self_review']
    write(ROOT/f'materials/{wk}-foreshadows.json',p['foreshadows'])
    md.append((ROOT/f'authoring/{wk}-review.md').read_text(encoding='utf-8')+'\n')
    source_text=(ROOT/f'works/{wk}.md').read_text(encoding='utf-8')
    starts=list(re.finditer(r'^# 第(\d+)章 ([^\n\r]+)$',source_text,re.M))
    chapters={int(m[1]):(m[0][2:],source_text[m.end():starts[i+1].start() if i+1<len(starts) else len(source_text)]) for i,m in enumerate(starts)}
    def pos(ch,q):
        n=next(n for n,(title,body) in chapters.items() if title==ch) if isinstance(ch,str) else ch
        body=chapters[n][1]
        return len(HAN.findall(body[:body.index(q)]))+1
    md.append(f'## {wk} 逐题自查与依据位置\n')
    for t in p['tasks']:
        evidence=[]
        for a in t.get('expected_actions',t.get('allowed_actions',[])):
            for ch,q in zip(a['evidence_chapters'],a['evidence_quotes']): evidence.append(f'{ch}，章内第{pos(ch,q)}个汉字起：{q}')
        md.append(f"- `{t['id']}`：{t['why']}"+(' 依据：'+'；'.join(evidence) if evidence else ' 无正文依据条目：路由/只读/拒绝/作者直给文字或放弃按字段分别判断。'))
    md.append(f'\n## {wk} 自查引文位置\n')
    for field,entries in p['self_review'].items():
        if not isinstance(entries,list): continue
        for e in entries:
            if isinstance(e,dict) and 'quote' in e:
                ch=e.get('changed_chapter',e.get('planted_chapter',e.get('chapter')))
                md.append(f"- {field} {e.get('fact',e.get('foreshadow',e.get('about',e.get('subject',e.get('name','')))))}：第{ch}章，第{pos(ch,e['quote'])}个汉字起；{e['quote']}")
write(ROOT/'tasks.json',{'version':'a2-2','set_id':'a2t-dev','author':'evaluation authoring','works':works,'tasks':tasks})
write(ROOT/'authoring/self-review.json',{'works':reviews})
(ROOT/'authoring/self-review.md').write_text('\n'.join(md)+'\n',encoding='utf-8')
