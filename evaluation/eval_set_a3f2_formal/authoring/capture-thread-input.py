"""Capture exact first-round material bytes and seal the actual first vote file."""
import argparse
import hashlib
import json
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--work', required=True, choices=['w01','w02'])
    parser.add_argument('--finalize', action='store_true')
    args = parser.parse_args()
    wk = args.work
    source, material = ROOT/f'works/{wk}.md', ROOT/f'materials/{wk}-foreshadows.json'
    target = ROOT/f'authoring/blind-thread-input-{wk}.json'
    if not args.finalize:
        assert len(re.findall(r'^# 第[1-9][0-9]*章 ', source.read_text(encoding='utf-8'), re.M)) == 30
        value = {'source_sha256':sha(source), 'foreshadows_sha256':sha(material),
                 'foreshadows_text':material.read_text(encoding='utf-8'), 'capture':'before_independent_first_round'}
        if target.is_file():
            existing = json.loads(target.read_text(encoding='utf-8'))
            assert all(existing.get(k)==v for k,v in value.items())
            print(json.dumps({'work':wk,'capture_already_exists':True}))
            return
    else:
        value = json.loads(target.read_text(encoding='utf-8'))
        vote_path = ROOT/f'authoring/independent-thread-{wk}.json'
        vote = json.loads(vote_path.read_text(encoding='utf-8'))
        assert vote['status']=='completed' and vote['work']==wk and vote['chapter_coverage']==list(range(1,31))
        assert vote['source_sha256']==value['source_sha256'] and vote['foreshadows_sha256']==value['foreshadows_sha256']
        if 'first_record_sha256' in value:
            assert value['first_record_sha256']==sha(vote_path)
        value['first_record_sha256']=sha(vote_path)
    target.write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n',encoding='utf-8',newline='\n')
    print(json.dumps({'work':wk,'first_round_sealed':args.finalize,'material_items':len(json.loads(value['foreshadows_text']))}))


if __name__=='__main__':
    main()
