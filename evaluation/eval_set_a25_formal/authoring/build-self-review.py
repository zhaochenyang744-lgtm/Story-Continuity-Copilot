"""Bind the lead's prewritten evidence inventory to completed canonical prose."""
from pathlib import Path
import json,re
ROOT=Path(__file__).resolve().parents[3]
H=re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')
INVENTORY={
('eval_set_a25_formal','w01'):{'title':'证词留白处','characters':['简迭微','段泊循','毕见岚','屈绍荻','符砚杭','宓书冽','封南缬','蒯令皎'],
 'aliases':['绛穗','苔隅','柚翎'],'extra':['芥衡市','折榆庭','南穗辩护所','衔序夹','岬纹笔','叠槭牌']},
('eval_set_a25_formal','w02'):{'title':'另一种句尾','characters':['慎珑序','嵇映璜','饶旻弈','邰颂微','覃蘅执','邴绍棠','禄青宓','冀照玄'],
 'aliases':['珀弦','筠赭','绯榫'],'extra':['蒲弧市','芰序互动','拾昼环','瑟页盘','釉棱麦','斛星笔']},
('eval_set_a2s5_formal','w01'):{'title':'表决以前','characters':['寇荞澈','郁弥岫','韦望稷','褚镜薰','钭星芫','仇栖砚','缑听澜','丘漫蕖'],
 'aliases':['泊蓼','榧尾','瓯星'],'extra':['苡霁市','斜萼实业','翡晷函','绒棱签','夕缟册']},
}
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
def chapters(source):
    ms=list(re.finditer(r'^# 第(\d+)章 [^\r\n]+',source,re.M))
    return {int(m[1]):{'title':m[0][2:],'body':source[m.end():ms[i+1].start() if i+1<len(ms) else len(source)]} for i,m in enumerate(ms)}

def make(root,w,inv):
    b=(root/'authoring'/f'bible-{w}.md').read_text(encoding='utf-8')
    source=(root/'works'/f'{w}.md').read_text(encoding='utf-8');chs=chapters(source)
    assert len(chs)==(12 if 'a2s5' in root.name else 20)
    wr={'characters':inv['characters'],'aliases':[], 'stale_facts':[], 'missing_facts':[],
      'resolved_unmarked':[],'open_threads':[{'foreshadow':n,'abandonable':n in (5,6)} for n in range(5,9)],
      'stale_notes':[],'missing_threads':[]}
    for n,c,q in re.findall(r'^S(\d+) 第(\d+)章：「([^」]+)」',b,re.M):
        wr['stale_facts'].append({'fact':int(n),'changed_chapter':int(c),'quote':q})
    for c,s,p,q in re.findall(r'^M\d+ 第(\d+)章 (.+?)/(.+?)：「([^」]+)」',b,re.M):
        wr['missing_facts'].append({'subject':s,'predicate':p,'chapter':int(c),'quote':q})
    for n,c,q in re.findall(r'^R(\d+) 第(\d+)章：「([^」]+)」',b,re.M):
        wr['resolved_unmarked'].append({'foreshadow':int(n),'chapter':int(c),'quote':q})
    first=wr['resolved_unmarked'][0]
    wr['stale_notes'].append(dict(foreshadow=1,chapter=first['chapter'],quote=first['quote']))
    n2=re.search(r'N2第(\d+)章：「([^」]+)」',b)
    wr['stale_notes'].append(dict(foreshadow=5,chapter=int(n2[1]),quote=n2[2]))
    for c,about,q in re.findall(r'^T\d+ 第(\d+)章 about=(.+?)(?:，原句)?：「([^」]+)」',b,re.M):
        wr['missing_threads'].append({'about':about,'planted_chapter':int(c),'quote':q})
    assert [len(wr[k]) for k in ('stale_facts','missing_facts','resolved_unmarked','stale_notes','missing_threads')]==[5,6,4,2,3]
    for name,alias in zip(inv['characters'],inv['aliases']):
        found=[]
        for n,ch in chs.items():
            for m in re.finditer(r'[^\n。！？]+[。！？]',ch['body']):
                s=m[0].strip(' “”“')
                if name in s and alias in s and 10<=len(s)<=60:found.append((n,s))
        assert found,(w,alias)
        n,s=found[0];wr['aliases'].append({'name':name,'alias':alias,'chapter':n,'quote':s})
    for field in ('stale_facts','missing_facts','resolved_unmarked','stale_notes','missing_threads','aliases'):
        for e in wr[field]:
            n=e.get('changed_chapter',e.get('planted_chapter',e.get('chapter')))
            assert e['quote'] in chs[n]['body'],(w,field,n)
            assert 10<=len(e['quote'])<=60,(w,field,n)
    return wr

if __name__=='__main__':
    for sn in ('eval_set_a25_formal','eval_set_a2s5_formal'):
        r=ROOT/'evaluation'/sn;d={'works':{}}
        for (s,w),inv in INVENTORY.items():
            if s==sn:d['works'][w]=make(r,w,inv)
        save(r/'authoring/self-review.json',d)
    print(json.dumps({'self_reviews':2}))
