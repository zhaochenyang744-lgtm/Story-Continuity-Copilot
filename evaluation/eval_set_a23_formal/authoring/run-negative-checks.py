"""Five requested corruptions, isolated in disposable in-scope copies; no model calls."""
from pathlib import Path
import copy
import hashlib
import json
import re
import shutil
import subprocess
import sys

FORMAL = Path(__file__).resolve().parents[1]
SAFETY = FORMAL.parent / 'eval_set_a2s3_formal'
safety_only = '--safety-only' in sys.argv
source = SAFETY if safety_only else FORMAL
temporary = source / 'authoring' / ('_negative-tmp-safety' if safety_only else '_negative-tmp-formal')
assert not temporary.exists()
temporary.mkdir()
required = ['README.md', 'check.py', 'set.sha256', 'tasks.json',
            'authoring/self-review.md', 'authoring/self-review.json',
            'authoring/novelty-reference.json', 'authoring/independent-review.json']
required += [p.relative_to(source).as_posix() for f in ('works', 'materials') for p in (source/f).iterdir() if p.is_file()]
digest = lambda p: hashlib.sha256(p.read_bytes()).hexdigest()
def write(path, obj):
    path.write_text(json.dumps(obj, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')

def corrupt_character(text):
    match = re.search(r'[\u3400-\u4dbf\u4e00-\u9fff]', text)
    assert match and match[0] != '龘'
    return text[:match.start()] + '龘' + text[match.end():]

cases = [('N03', 'injection_character'), ('N04', 'target_allowed_overlap'), ('N05', 'source_character')] if safety_only else [
    ('N01', 'remove_primary_change'), ('N02', 'evidence_character')]
results = []
for label, mutation in cases:
    dest = temporary / label
    dest.mkdir()
    for rel in required:
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source / rel, target)
    tasks = json.loads((dest/'tasks.json').read_text(encoding='utf-8'))
    if mutation == 'remove_primary_change':
        victim = next(t for t in tasks['tasks'] if t['suite']=='action' and t['expected_actions'][0]['kind']=='change_fact')
        tasks['tasks'].remove(victim)
    elif mutation == 'evidence_character':
        victim = next(t for t in tasks['tasks'] if t['suite']=='action')
        q = victim['expected_actions'][0]['evidence_quotes'][0]
        victim['expected_actions'][0]['evidence_quotes'][0] = corrupt_character(q)
    elif mutation == 'injection_character':
        tasks['tasks'][0]['injection']['text'] = corrupt_character(tasks['tasks'][0]['injection']['text'])
    elif mutation == 'target_allowed_overlap':
        victim = next(t for t in tasks['tasks'] if t['run_kind']=='change' and t['allowed_actions'])
        allowed = victim['allowed_actions'][0]
        victim['injection_target'] = copy.deepcopy({'kind':allowed['kind'], 'target':allowed['target']})
    elif mutation == 'source_character':
        p = dest/'works/w01.md'
        text = p.read_text(encoding='utf-8')
        header_end = text.index('\n')
        p.write_text(text[:header_end+1]+corrupt_character(text[header_end+1:]), encoding='utf-8', newline='\n')
    if mutation != 'source_character':
        write(dest/'tasks.json', tasks)
        # Refresh only temporary integrity bindings to isolate the targeted semantic/structure check.
        independent = json.loads((dest/'authoring/independent-review.json').read_text(encoding='utf-8'))
        independent['sha256']['tasks.json'] = digest(dest/'tasks.json')
        write(dest/'authoring/independent-review.json', independent)
        paths = sorted(independent['sha256'])
        (dest/'set.sha256').write_text(''.join(f'{digest(dest/p)}  {p}\n' for p in paths), encoding='utf-8', newline='\n')
    run = subprocess.run([sys.executable, '-X', 'utf8', '-B', str(dest/'check.py')], cwd=dest, capture_output=True, text=True, encoding='utf-8')
    assert not run.stderr.strip()
    lines = run.stdout.strip().splitlines()
    assert len(lines)==1
    output = json.loads(lines[0])
    expected = {'N01': lambda es: 'w01:primary_actions' in es and 'tasks:count' in es,
                'N02': lambda es: any(e.endswith(':evidence:1:quote') for e in es),
                'N03': lambda es: any(e.endswith(':injection_match') for e in es),
                'N04': lambda es: any(e.endswith(':target_allowed_overlap') for e in es),
                'N05': lambda es: any(e.startswith('manifest:') and e.endswith(':hash') for e in es) and 'independent:binding' in es}[label]
    caught = run.returncode != 0 and output.get('status')=='FAIL' and expected(output.get('errors', []))
    if mutation != 'source_character':
        assert not any(e.startswith('manifest:') or e=='independent:binding' for e in output['errors'])
    results.append({'id':label, 'mutation':mutation, 'caught':caught, 'exit_code':run.returncode,
                    'status':output.get('status'), 'errors':output.get('errors'), 'checker_output':output,
                    'temporary_integrity_refreshed': mutation!='source_character'})
    assert caught
write(source/'authoring/negative-check-results.json', {'tests':results, 'passed':len(results), 'failed':0,
    'temporary_copy_count':len(results), 'temporary_cleanup_required':True, 'model_calls':0,'product_runs':0,'evaluation_runs':0})
print(json.dumps({'tests':[{'id':v['id'],'caught':v['caught'],'exit_code':v['exit_code'],'errors':v['errors']} for v in results],
                  'temporary_root':str(temporary.resolve())}, ensure_ascii=False))
