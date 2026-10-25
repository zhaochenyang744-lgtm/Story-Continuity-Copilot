"""Strip gold and evidence before the author-independent review."""
import json
from pathlib import Path
import random
ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parents[1]
for wk,source in [('w01','eval_set_a23_formal'),('w02','eval_set_a24_formal')]:
    p=ROOT/f'authoring/{wk}-package.json'
    if not p.exists(): continue
    data=json.loads(p.read_text(encoding='utf-8'))
    tasks=data['tasks']
    packet={'work':wk,'facts':json.loads((REPO/f'evaluation/{source}/materials/w01-facts.json').read_text(encoding='utf-8')),'foreshadows':data['foreshadows'],'intent':[{'id':t['id'],'request':t['request'],'context':t['context']} for t in tasks if t['suite']!='route'],'route':[{'id':t['id'],'input':t['input'],'context':t['context']} for t in tasks if t['suite']=='route']}
    random.Random(20261025).shuffle(packet['intent'])
    random.Random(20261025).shuffle(packet['route'])
    (ROOT/f'authoring/blind-{wk}-input.json').write_text(json.dumps(packet,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
