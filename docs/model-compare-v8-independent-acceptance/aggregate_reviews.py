"""Join locked manual reviews only after complete coverage; preserve adjudications."""
import collections
import copy
import hashlib
import json
import pathlib
import sys

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'backend')]
from evaluation.model_compare_v8.config import cases, request_for
from evaluation.current_flash_v7.score import policy

RUN_ID = 'model-compare-v8-20260927-01'
PACKETS = HERE / 'blind-review' / RUN_ID
RUN = ROOT / 'evaluation/model_compare_v8/runs' / RUN_ID
ARMS = ('flash-off', 'flash-high', 'pro-high')


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def sha(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def aggregate():
    reviews, provenance, adjustments = {}, {}, []
    for folder in sorted(HERE.glob('semantic-review-*')):
        for p in sorted(folder.glob('*.json')):
            doc = read(p)
            if p.name.startswith('adjudication-'):
                adjustments.append((p, doc))
                continue
            for record in doc.get('records', []) + doc.get('repair_records', []):
                if record.get('stage') not in ('first', 'repair', 'final'):
                    continue
                key = (int(record['case_alias'].split('-')[-1]), record['response_alias'], record['stage'])
                if key in reviews:
                    if reviews[key] != record:
                        raise RuntimeError('duplicate_conflicting_review:' + repr(key))
                    continue
                if record.get('locked_before_condition_reveal') is not True:
                    raise RuntimeError('review_not_locked:' + repr(key))
                reviews[key] = copy.deepcopy(record)
                provenance[key] = {'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)}
    expected = set()
    for n in range(1, 35):
        first = read(PACKETS / 'first' / f'{n:02}.json')
        for row in first['responses']:
            expected |= {(n, row['response_alias'], 'first'), (n, row['response_alias'], 'final')}
        followup_path = PACKETS / 'followup' / f'{n:02}.json'
        if followup_path.exists():
            for row in read(followup_path)['responses']:
                if row['repair'] is not None:
                    expected.add((n, row['response_alias'], 'repair'))
    missing = sorted(expected - set(reviews))
    if missing:
        return {'complete': False, 'locked_records': len(reviews), 'missing': missing}
    if set(reviews) != expected:
        raise RuntimeError('unexpected_review_records')
    for p, doc in adjustments:
        key = (int(doc['case_alias'].split('-')[-1]), doc['response_alias'], doc['stage'])
        assert reviews[key]['ratings'] == doc['original_ratings']
        reviews[key]['ratings'] = doc['revised_ratings']
        provenance[key]['adjudication'] = {'path': p.relative_to(ROOT).as_posix(), 'sha256': sha(p)}
    # No condition mapping is opened until every first/repair/final is locked.
    mappings = {n: {r['response_alias']: r['condition_id'] for r in
                   read(PACKETS / 'root-only-mapping' / f'{n:02}.json')['responses']} for n in range(1, 35)}
    groups = {}
    for case in cases():
        allowed = policy(case, request_for(case))['allowed_outcomes']
        groups[case['ordinal']] = ('confirmed_conflict' if 'confirmed_conflict' in allowed else
                                   'insufficient_evidence' if 'insufficient_evidence' in allowed else 'no_conflict')
    rows, differences = [], []
    for key, review in sorted(reviews.items()):
        n, alias, stage = key
        arm = mappings[n][alias]
        scores = read(RUN / 'cases' / f'{n:02}' / arm / 'scores.json')
        machine = scores['repair'][0] if stage == 'repair' else scores[stage]
        manual_pass = review['ratings']['strict_composite'] == 'pass'
        machine_pass = machine['machine_result'] == 'pass'
        row = {'case': n, 'response_alias': alias, 'condition': arm, 'stage': stage, 'group': groups[n],
               'ratings': review['ratings'], 'observed_decision': review.get('observed_decision'),
               'actual_issue_count': review.get('actual_issue_count'), 'manual_strict': manual_pass,
               'machine_result': machine['machine_result'], 'machine_errors': machine['errors'],
               'accepted_strict': manual_pass and machine_pass, 'review': provenance[key]}
        rows.append(row)
        if manual_pass != machine_pass:
            differences.append(row)
    totals = {}
    for arm in ARMS:
        totals[arm] = {}
        for stage in ('first', 'repair', 'final'):
            own = [r for r in rows if r['condition'] == arm and r['stage'] == stage]
            totals[arm][stage] = {
                'n': len(own), 'accepted_strict': sum(r['accepted_strict'] for r in own),
                'strict_pass_cases': [r['case'] for r in own if r['accepted_strict']],
                'dimensions': {dim: dict(collections.Counter(r['ratings'][dim] for r in own)) for dim in
                               ('F', 'C', 'E_roles', 'E_set', 'E_binding', 'S', 'D', 'T')},
                'groups': {group: {'n': sum(r['group'] == group for r in own),
                                   'strict_pass': sum(r['accepted_strict'] and r['group'] == group for r in own)}
                           for group in ('no_conflict', 'confirmed_conflict', 'insufficient_evidence')},
                'expected_issue_cases': sum(r['group'] != 'no_conflict' for r in own),
                'actual_issue_delivery_in_expected_cases': sum(r['group'] != 'no_conflict' and
                       isinstance(r['actual_issue_count'], int) and r['actual_issue_count'] > 0 for r in own),
            }
    pairs = {}
    for stage in ('first', 'final'):
        pairs[stage] = {}
        for left, right in (('flash-high', 'flash-off'), ('pro-high', 'flash-high'), ('pro-high', 'flash-off')):
            l = set(totals[left][stage]['strict_pass_cases']); r = set(totals[right][stage]['strict_pass_cases'])
            pairs[stage][left + '_vs_' + right] = {'left_only_pass': sorted(l-r), 'right_only_pass': sorted(r-l),
                                                  'both_pass': len(l&r), 'both_fail': 34-len(l|r)}
    return {'complete': True, 'run_id': RUN_ID, 'review_records': len(rows), 'conditions': totals,
            'pairwise_strict': pairs, 'manual_machine_strict_differences': differences, 'rows': rows,
            'criteria_sha256': sha(HERE / 'SEMANTIC-CRITERIA.json'),
            'method': 'All required manual records locked before opening mappings. Apply explicit preserved adjudications. Strict requires both manual semantic/contract pass and unchanged machine policy pass.'}


if __name__ == '__main__':
    result = aggregate()
    if len(sys.argv) > 1:
        if not result['complete']:
            raise RuntimeError('cannot_persist_incomplete_acceptance')
        with (HERE / sys.argv[1]).open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write('\n')
    print(json.dumps(result if not result['complete'] else {
        'complete': True, 'records': result['review_records'],
        'totals': {a: {s: {'n': d['n'], 'strict': d['accepted_strict'], 'F': d['dimensions']['F']}
                      for s, d in v.items()} for a, v in result['conditions'].items()},
        'strict_differences': result['manual_machine_strict_differences']}, ensure_ascii=False))
