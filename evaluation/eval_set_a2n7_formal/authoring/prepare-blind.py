"""Build the content-only blind packet; keep the answer-label key separate."""
from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
from random import Random

ROOT = Path(__file__).resolve().parents[1]


def read_json(relative):
    return json.loads((ROOT / relative).read_text(encoding='utf-8'))


def dump(relative, value):
    (ROOT / relative).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n',
                                 encoding='utf-8', newline='\n')


def build():
    data = read_json('tasks.json')
    tasks = data['tasks']
    assert data['set_id'] == 'a2n7-formal' and len(tasks) == 20
    assert len({task['id'] for task in tasks}) == 20
    assert all(task['id'].startswith('a2n7-') and task['suite'] in {'action', 'no_action'} for task in tasks)
    assert len(data['works']) == 1 and data['works'][0]['key'] == 'w01'
    work = data['works'][0]
    assert work['source_file'] == 'works/w01.md'
    assert work['materials'] == {'facts': 'materials/w01-facts.json',
                                 'foreshadows': 'materials/w01-foreshadows.json'}
    rng = Random(20261028)
    shuffled = list(tasks)
    rng.shuffle(shuffled)
    key = {f'b{index:02d}': task['id'] for index, task in enumerate(shuffled, 1)}
    # The mapping itself is random; shuffling already labelled IDs would leak suites.
    labels = [task['suite'] for task in shuffled]
    assert sum(a != b for a, b in zip(labels, labels[1:])) >= 4
    packet_tasks = [{'id': f'b{index:02d}', 'request': task['request'],
                     'context': deepcopy(task['context'])}
                    for index, task in enumerate(shuffled, 1)]
    rng.shuffle(packet_tasks)
    packet = {'works': {'w01': {
        'source': (ROOT / 'works/w01.md').read_text(encoding='utf-8'),
        'facts': read_json('materials/w01-facts.json'),
        'foreshadows': read_json('materials/w01-foreshadows.json'),
        'shared_draft': deepcopy(work['shared_draft'])}}, 'tasks': packet_tasks}
    serialized = json.dumps(packet, ensure_ascii=False)
    assert not any(task['id'] in serialized for task in tasks)
    assert all(set(item) == {'id', 'request', 'context'} for item in packet_tasks)
    assert [key[item['id']] for item in packet_tasks] != [task['id'] for task in tasks]
    # Preserve the first independent judgement if this preparation is rerun.
    if (ROOT / 'authoring/blind-verdicts.json').exists():
        assert read_json('authoring/blind-packet.json') == packet
        assert read_json('authoring/blind-key.json') == key
    dump('authoring/blind-packet.json', packet)
    dump('authoring/blind-key.json', key)
    return {'status': 'PASS', 'works': 1, 'tasks': len(packet_tasks), 'opaque_ids': len(key),
            'gold_fields_in_packet': 0, 'key_label_transitions': sum(a != b for a, b in zip(labels, labels[1:]))}


def main():
    try:
        result = build()
    except Exception:
        result = {'status': 'FAIL', 'errors': ['blind_preparation:invalid_or_changed_source']}
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0 if result['status'] == 'PASS' else 1


if __name__ == '__main__':
    raise SystemExit(main())
