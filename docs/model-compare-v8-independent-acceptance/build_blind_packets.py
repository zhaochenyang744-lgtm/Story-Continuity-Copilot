"""Create immutable review packets. Reviewers must not read the root mapping."""
from __future__ import annotations

import argparse
import copy
import pathlib
import secrets
import sys

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from evaluation.model_compare_v8.config import CONDITIONS, cases, read, request_for, sha, stamp, write_x
from evaluation.current_flash_v7.score import policy

HERE = pathlib.Path(__file__).resolve().parent


def serial(value):
    if isinstance(value, set):
        return sorted(value)
    if isinstance(value, dict):
        return {k: serial(v) for k, v in value.items()}
    if isinstance(value, list):
        return [serial(v) for v in value]
    return value


def answer(folder, ordinal):
    request_path = folder / 'requests' / f'{ordinal:02d}.json'
    parsed_path = folder / 'evaluations' / f'{ordinal:02d}.json'
    if not request_path.exists():
        return None
    parsed = read(parsed_path) if parsed_path.exists() else {}
    receipts = [read(p) for p in sorted((folder / 'attempts').glob('*-finish.json'))]
    # Transport retries are currently suppressed after unknown usage. Match
    # evaluation number rather than assuming attempt and evaluation are equal.
    own = [r for r in receipts if r.get('evaluation') == ordinal]
    receipt = own[-1] if own else {}
    return {'business_request': read(request_path)['business_request'],
            'visible_content': receipt.get('visible_content'),
            'parsed_business_json': parsed.get('parsed_business_json'),
            'finish_reason': parsed.get('finish_reason', receipt.get('finish_reason')),
            'output_availability': ('visible_and_parsed' if parsed.get('outcome') == 'parsed'
                                    else 'visible_unparsed' if receipt.get('visible_content') else 'no_visible_output')}


def build(run_id, start, end, stage):
    run = ROOT / 'evaluation/model_compare_v8/runs' / run_id
    output = HERE / 'blind-review' / run_id
    mapping_root = output / 'root-only-mapping'
    for case in cases():
        n = case['ordinal']
        if not start <= n <= end:
            continue
        paths = {c['id']: run / 'cases' / f'{n:02d}' / c['id'] for c in CONDITIONS}
        if not all((p / 'trial-finish.json').exists() for p in paths.values()):
            continue
        destination = output / stage / f'{n:02d}.json'
        if destination.exists():
            continue
        mapping_path = mapping_root / f'{n:02d}.json'
        if mapping_path.exists():
            mapping = read(mapping_path)
        else:
            if stage != 'first':
                raise RuntimeError('first_packet_required')
            order = list(paths)
            secrets.SystemRandom().shuffle(order)
            mapping = {'case_ordinal': n, 'created_at': stamp(),
                       'responses': [{'response_alias': 'answer-' + secrets.token_hex(3), 'condition_id': c}
                                     for c in order],
                       'trial_finish_hashes': {c: sha(p / 'trial-finish.json') for c, p in paths.items()}}
            write_x(mapping_path, mapping)
        request = request_for(case)
        packet = {'case_alias': f'case-{n:02d}', 'stage': stage,
                  'expected_policy_reference': case['case_id'],
                  'policy': serial(policy(case, request)), 'business_request': request,
                  'review_instruction': 'Read each response independently; conditions, scores and usage are hidden. Record visible reasoning, never infer hidden thinking.',
                  'responses': []}
        for row in mapping['responses']:
            folder = paths[row['condition_id']]
            result = {'response_alias': row['response_alias']}
            if stage == 'first':
                result['first'] = answer(folder, 1)
            else:
                result['repair'] = answer(folder, 2)
                final = read(folder / 'engine-final.json')
                result['final'] = {k: copy.deepcopy(final[k]) for k in
                                   ('status', 'error_code', 'issues', 'contract_normalization_count', 'contract_normalizations')
                                   if k in final}
            packet['responses'].append(result)
        write_x(destination, packet)
    return output / stage


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run_id')
    p.add_argument('--start', type=int, default=1)
    p.add_argument('--end', type=int, default=34)
    p.add_argument('--stage', choices=('first', 'followup'), default='first')
    args = p.parse_args()
    print(build(args.run_id, args.start, args.end, args.stage))
