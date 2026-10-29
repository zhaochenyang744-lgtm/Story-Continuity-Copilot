"""Give independent reviewers only the task-authorized blind inputs."""
from pathlib import Path
import hashlib,json,random,sys
FORMAL=Path(__file__).resolve().parent.parent
SAFETY=FORMAL.parent/'eval_set_a2s5_formal'
NEW={'add_thread','edit_thread','abandon_thread'}
def load(p):return json.loads(p.read_text(encoding='utf-8'))
def save(p,d):p.write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
roots=(SAFETY,) if sys.argv[1:]==['safety'] else (FORMAL,SAFETY)
route_total=0;new_total=0
for root in roots:
    d=load(root/'tasks.json');rng=random.Random(20261025)
    if root==FORMAL:
        route=[{k:t[k] for k in ('id','input','context')} for t in d['tasks'] if t['suite']=='route']
        rng.shuffle(route);save(root/'authoring/route-blind-input.json',route)
        route_total+=len(route)
    ts=[t for t in d['tasks'] if any(a['kind'] in NEW for a in t.get('expected_actions',t.get('allowed_actions',[])))]
    payload={'tasks':[{'id':t['id'],'work':t['work'],'request':t['request']} for t in ts],
      'materials':{w['key']:{kind:load(root/path) for kind,path in w['materials'].items()} for w in d['works']}}
    rng.shuffle(payload['tasks']);save(root/'authoring/new-action-blind-input.json',payload)
    new_total+=len(payload['tasks'])
print(json.dumps({'route_inputs':route_total,'new_action_inputs':new_total}))
