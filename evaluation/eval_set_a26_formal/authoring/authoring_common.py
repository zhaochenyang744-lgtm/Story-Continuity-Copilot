"""Serialize lead-authored literals and calculate source positions; no prose generation."""
from pathlib import Path
import hashlib
import json
import re

HAN=re.compile(r'[\u3400-\u4dbf\u4e00-\u9fff]')

def save(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(data,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

def chapters(path):
    s=path.read_text(encoding='utf-8')
    ms=list(re.finditer(r'^# 第([1-9][0-9]*)章 ([^\r\n]+)$',s,re.M))
    return {int(m[1]):{'title':m[0][2:],'body':s[m.end():ms[i+1].start() if i+1<len(ms) else len(s)]}
            for i,m in enumerate(ms)}

def fact(subject,predicate,value,chapter,memory_type='static_canon'):
    return dict(memory_type=memory_type,subject=subject,predicate=predicate,value=value,chapter=chapter)

def thread(title,description,status,planted,resolved=None):
    d=dict(title=title,description=description,status=status,planted_chapter=planted)
    if resolved is not None:d['resolved_chapter']=resolved
    return d

def action(chs,kind,target,points,chapter=None,quote=None):
    if chapter is None:
        assert quote is None
        cs,qs=[],[]
    else:
        assert isinstance(chapter,int) and 10<=len(quote)<=60 and quote in chs[chapter]['body']
        cs,qs=[chs[chapter]['title']],[quote]
    return dict(kind=kind,target=target,after_points=points,evidence_chapters=cs,evidence_quotes=qs)

def metadata(root,key,title,names,number,draft_title):
    p=root/f'authoring/{key}-shared-draft.txt'
    draft=p.read_text(encoding='utf-8').strip()
    assert 600<=len(HAN.findall(draft))<=1000
    return dict(key=key,title=title,language='zh',source_file=f'works/{key}.md',purpose='general',kind='long',names=names,
                materials={'facts':f'materials/{key}-facts.json','foreshadows':f'materials/{key}-foreshadows.json'},
                shared_draft={'chapter_title':f'第{number}章 {draft_title}','body':draft})

def position(chs,chapter,quote):
    body=chs[chapter]['body']
    assert quote in body
    return len(HAN.findall(body[:body.index(quote)]))+1

def write_self_review(root,data,review):
    save(root/'authoring/self-review.json',review)
    maps={w['key']:chapters(root/w['source_file']) for w in data['works']}
    lines=['# 逐题自查','', '正文人工逐章原创；以下语义理由由主控逐题写定，程序仅排版已写定的理由与计算引句位置。','']
    for wk,wr in review['works'].items():
        lines += [f'## {wk} 库存自查','']
        for field in ('aliases','stale_facts','missing_facts','resolved_unmarked','stale_notes','missing_threads'):
            for i,e in enumerate(wr[field],1):
                chapter=e.get('chapter',e.get('changed_chapter',e.get('planted_chapter')))
                lines += [f'- {field}/{i}：{maps[wk][chapter]["title"]}，第{position(maps[wk],chapter,e["quote"])}个汉字；原句：{e["quote"]}']
        lines += ['','开放线的末章核对及可放弃性见独立全文审读；开放与已收未标集合互不相交。','']
    for t in data['tasks']:
        wk=t['work']
        lines += [f'## {t["id"]}','', t['why'],'']
        if t['id'] in review.get('task_notes',{}):
            lines += [review['task_notes'][t['id']],'']
        if t.get('context',{}).get('selection'):
            w=next(w for w in data['works'] if w['key']==wk)
            body=w['shared_draft']['body'];selection=t['context']['selection']
            assert selection in body
            lines += [f'选中定位：{w["shared_draft"]["chapter_title"]}草稿，第{len(HAN.findall(body[:body.index(selection)]))+1}个汉字；{selection}','']
        if t['suite']=='route':
            lines += [f'判定：{t["expected_route"]}；依据为输入意图和context，正文考点位置不适用。','']
        elif t['suite']=='no_action':
            lines += [f'判定：{t["no_action_type"]}；对象：{json.dumps(t["request_targets"],ensure_ascii=False)}。正文缺失/功能不支持/改正文类不设虚构证据位置，已有资料及反证对应库存与全文审读。','']
        else:
            for a in t.get('expected_actions',t.get('allowed_actions',[])):
                lines += [f'动作：{a["kind"]}；对象：{json.dumps(a["target"],ensure_ascii=False)}；改后要点：{json.dumps(a["after_points"],ensure_ascii=False)}。']
                for title,q in zip(a['evidence_chapters'],a['evidence_quotes']):
                    n=next(n for n,c in maps[wk].items() if c['title']==title)
                    lines += [f'依据：{title}，第{position(maps[wk],n,q)}个汉字；{q}']
                if not a['evidence_quotes']:lines += ['依据为作者明确要求；本条不虚构正文证据及位置。']
                lines += ['']
            if t['suite']=='injection':
                inj=t['injection'];loc=inj['location']
                lines += [f'载荷对象：{json.dumps(t["injection_target"],ensure_ascii=False)}；位置：{json.dumps(loc,ensure_ascii=False)}。']
                if loc['kind']=='chapter':lines += [f'载荷章内位置：{position(maps[wk],loc["chapter"],inj["text"])}。']
                lines += ['载荷是故事/资料/草稿中的不可信内容；合法请求的对象与其隔离，ask/recap不允许改动。','']
    (root/'authoring/self-review.md').write_text('\n'.join(lines),encoding='utf-8',newline='\n')

def merge_proof(root,data):
    result=[]
    for w in data['works']:
        p=root/f'authoring/{w["key"]}-shared-draft.txt'
        saved=p.read_text(encoding='utf-8').strip()
        assert saved==w['shared_draft']['body']
        result.append({'work':w['key'],'equal':True,'body_utf8_sha256':hashlib.sha256(saved.encode('utf-8')).hexdigest()})
    save(root/'authoring/draft-merge-proof.json',{'status':'PASS','works':result})
