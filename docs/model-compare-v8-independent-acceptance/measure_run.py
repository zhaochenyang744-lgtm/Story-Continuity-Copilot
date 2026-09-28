"""Independent descriptive accounting from immutable V8 receipts, no API calls."""
import argparse
import collections
import datetime
import json
import pathlib
import statistics

ROOT = pathlib.Path(__file__).resolve().parents[2]
ARMS = ('flash-off', 'flash-high', 'pro-high')


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def distribution(values):
    if not values:
        return None
    values = sorted(values)
    return {'n': len(values), 'sum': sum(values), 'median': statistics.median(values),
            'p95_nearest_rank': values[max(0, (95 * len(values) + 99) // 100 - 1)], 'max': max(values)}


def measure(run_id):
    run = ROOT / 'evaluation/model_compare_v8/runs' / run_id
    result = {'run_id': run_id, 'finished': (run / 'summary.json').exists(), 'conditions': {}}
    for arm in ARMS:
        trials = [p.parent for p in sorted((run / 'cases').glob('*/' + arm + '/trial-finish.json'))]
        records = []
        receipts = []
        for folder in trials:
            own = [read(p) for p in sorted((folder / 'attempts').glob('*-finish.json'))]
            receipts.extend(own)
            scores = read(folder / 'scores.json')
            final = read(folder / 'engine-final.json')
            start, finish = read(folder / 'trial-start.json'), read(folder / 'trial-finish.json')
            evaluation_usage = collections.defaultdict(list)
            for r in own:
                evaluation_usage[r['evaluation']].append(r['usage'])
            compatible = {str(e): all(u['status'] == 'complete' for u in us) and sum(u['total_tokens'] or 0 for u in us) <= 8000
                          for e, us in evaluation_usage.items()}
            seconds = (datetime.datetime.fromisoformat(finish['finished_at']) - datetime.datetime.fromisoformat(start['started_at'])).total_seconds()
            records.append({'case': int(folder.parent.name), 'status': final['status'], 'error_code': final.get('error_code'),
                            'first_machine': (scores.get('first') or {}).get('machine_result'),
                            'first_errors': (scores.get('first') or {}).get('errors', []),
                            'final_machine': scores['final']['machine_result'], 'final_errors': scores['final']['errors'],
                            'evaluations': finish['evaluation_count'], 'posts': finish['post_count'],
                            'original_8000_compatibility_by_evaluation': compatible,
                            'case_seconds': seconds, 'normalizations': final.get('contract_normalization_count', 0)})
        complete = [r for r in receipts if r['usage']['status'] == 'complete']
        result['conditions'][arm] = {
            'condition_cases': len(trials), 'cases': records, 'posts': len(receipts),
            'first_machine_pass': [r['case'] for r in records if r['first_machine'] == 'pass'],
            'final_machine_pass': [r['case'] for r in records if r['final_machine'] == 'pass'],
            'repairs': sum(r['evaluations'] > 1 for r in records),
            'engine_statuses': dict(collections.Counter(r['status'] for r in records)),
            'finish_reasons': dict(collections.Counter(str(r['finish_reason']) for r in receipts)),
            'http_statuses': dict(collections.Counter(str(r['http_status']) for r in receipts)),
            'known_tokens': {key: sum(r['usage'][key] for r in complete) for key in ('prompt_tokens', 'completion_tokens', 'total_tokens')},
            'unknown_usage_receipts': len(receipts) - len(complete),
            'response_models': sorted({str(r['response_model']) for r in receipts}),
            'reasoning_detail_statuses': dict(collections.Counter(r['usage'].get('reasoning_tokens_status', 'not_exposed') for r in receipts)),
            'known_reasoning_tokens_subtotal': sum(r['usage']['reasoning_tokens'] for r in receipts if r['usage'].get('reasoning_tokens') is not None),
            'reasoning_subtotal_complete': bool(receipts) and all(r['usage'].get('reasoning_tokens') is not None for r in receipts),
            'reasoning_body_present_count': sum(bool(r.get('reasoning', {}).get('present')) for r in receipts),
            'first_request_latency_ms': distribution([r['latency_ms'] for r in receipts if r['evaluation'] == 1 and r['latency_ms'] is not None]),
            'all_request_latency_ms': distribution([r['latency_ms'] for r in receipts if r['latency_ms'] is not None]),
            'condition_case_seconds': distribution([r['case_seconds'] for r in records]),
        }
    if result['finished']:
        result['run_summary'] = read(run / 'summary.json')
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('run_id')
    p.add_argument('--output')
    args = p.parse_args()
    result = measure(args.run_id)
    if args.output:
        path = pathlib.Path(__file__).resolve().parent / args.output
        with path.open('x', encoding='utf-8') as f:
            json.dump(result, f, ensure_ascii=False, indent=2)
            f.write('\n')
    print(json.dumps({'finished': result['finished'], 'conditions': {a: {
        'cases': v['condition_cases'], 'posts': v['posts'], 'known_tokens': v['known_tokens']['total_tokens'],
        'first_machine_pass_count': len(v['first_machine_pass']), 'final_machine_pass_count': len(v['final_machine_pass'])}
        for a, v in result['conditions'].items()}}, ensure_ascii=False))
