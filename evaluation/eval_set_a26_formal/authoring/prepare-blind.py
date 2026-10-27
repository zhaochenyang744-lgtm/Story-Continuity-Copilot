"""Export only the authorized information for independent intent judgments."""
from pathlib import Path
import json
import random

FORMAL=Path(__file__).resolve().parent.parent
SAFETY=FORMAL.parent/'eval_set_a2s6_formal'
NEW={'add_thread','edit_thread','abandon_thread'}

def load(p):
    return json.loads(p.read_text(encoding='utf-8'))

def save(p,d):
    p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')

def main():
    counts={'route':0,'new_action':0}
    for root in (FORMAL,SAFETY):
        if not (root/'tasks.json').exists():
            continue
        d=load(root/'tasks.json')
        rng=random.Random(20261027)
        if root==FORMAL:
            route=[{k:t[k] for k in ('id','input','context')} for t in d['tasks'] if t['suite']=='route']
            rng.shuffle(route)
            save(root/'authoring/route-blind-input.json',route)
            if not (root/'authoring/route-blind-input.initial.json').exists():
                save(root/'authoring/route-blind-input.initial.json',route)
            counts['route']+=len(route)
        tasks=[{k:t[k] for k in ('id','work','request')} for t in d['tasks']
               if any(a['kind'] in NEW for a in t.get('expected_actions',t.get('allowed_actions',[])))]
        rng.shuffle(tasks)
        payload={'tasks':tasks,'materials':{w['key']:{kind:load(root/path) for kind,path in w['materials'].items()}
                                         for w in d['works']}}
        save(root/'authoring/new-action-blind-input.json',payload)
        if not (root/'authoring/new-action-blind-input.initial.json').exists():
            save(root/'authoring/new-action-blind-input.initial.json',payload)
        counts['new_action']+=len(tasks)
    print(json.dumps(counts))

if __name__=='__main__':
    main()
