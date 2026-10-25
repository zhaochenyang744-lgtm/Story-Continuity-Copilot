"""A1 runner. Formal material is accessible only through silent validation in dry-run."""
from __future__ import annotations

import argparse
import copy
import hashlib
import io
import json
import math
import os
import pathlib
import re
import subprocess
import sys
import tempfile
import threading
import time
import uuid
import zipfile
from dataclasses import replace
from types import SimpleNamespace
from datetime import datetime, timezone, timedelta

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'backend'))
os.environ.setdefault('SCC_DISABLE_DEFAULT_APP', '1')
import httpx
from fastapi.testclient import TestClient
from app.assistant import ASSISTANT_PROMPT_VERSION
from app.config import AppPaths
from app.main import create_app
from app.provider import DeepSeekProvider, ProviderDispatchDenied
from app.stage13 import Stage13Settings
from ..models import REGISTERED_MODELS
from .judge import Judge, grade
from .score import refresh, audit, markdown, SPENT_FORMAL_SETS, SPENT_GATE_DECISION

RETRY_ERRORS = {'provider_timeout', 'provider_unavailable', 'provider_error'}
CONFLICTS = {'confirmed_conflict', 'possible_conflict'}
WRITE_LOCK = threading.RLock()


def git(*args):
    return subprocess.check_output(['git', *args], cwd=ROOT, text=True, encoding='utf-8').strip()


def rates(value):
    try:
        result = tuple(float(x) for x in value.split(','))
        if len(result) != 2 or any(not math.isfinite(x) or x < 0 for x in result): raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('rates must be two finite nonnegative numbers') from None


def settings(price):
    return Stage13Settings(public_app_mode=False, public_base_url='http://127.0.0.1:3080', backend_origin='http://127.0.0.1:8080',
        trusted_hosts=('testserver', '127.0.0.1:8080'), trusted_origins=('http://testserver', 'http://127.0.0.1:3080'),
        cookie_secure=False, visitor_ttl_hours=24, cleanup_interval_seconds=900, visitor_workflows=3, registered_workflows=100000,
        visitor_provider_attempts=30, registered_provider_attempts=100000, visitor_budget_cny=1, registered_budget_cny=100000,
        input_cny_per_million=price[0], output_cny_per_million=price[1], recovery_hash_secret=os.urandom(32),
        reset_base_url='http://127.0.0.1:3080', test_mode=True, registered_check_chars=10000000,
        registered_imports=100000, assistant_rollout='all')


class Ledger:
    """Reserve a conservative wire-token bound before *each* HTTP dispatch, including retries.

    UTF-8 bytes upper-bound text tokens; a framing allowance covers chat/tool wrappers.
    Unknown usage retains the full reservation. No credentials or headers are persisted.
    """
    def __init__(self, max_cny, assistant_rates, judge_rates):
        self.max_cny, self.rates = max_cny, {'assistant': assistant_rates, 'check': assistant_rates, 'judge': judge_rates, 'route': assistant_rates}
        self.calls, self.pending = [], 0.0
        self.lock = threading.Lock()
        self.category, self.task_id, self.stopped = 'check', None, False
        self.phase = 'prepare'
        self.run_number = None
        self.persist = lambda: None

    @property
    def spent(self): return sum(c['cost_cny'] for c in self.calls)

    def reserve(self, body):
        with self.lock:
            category = ('route' if self.phase == 'route' else
                        'judge' if self.category == 'judge' else 'assistant' if body.get('tools') else 'check')
            price = self.rates[category]
            bound = ((len(json.dumps(body, ensure_ascii=False).encode('utf-8')) + 4096) * price[0]
                     + body.get('max_tokens', 8192) * price[1]) / 1e6
            if self.spent + self.pending + bound > self.max_cny:
                self.stopped = True
                raise ProviderDispatchDenied('a1_budget_stop')
            # Persist the full bound before dispatch. A hard crash cannot erase spending.
            index = len(self.calls)
            self.calls.append({'category': category, 'phase': self.phase, 'task_id': self.task_id,
                'run_number': self.run_number, 'input_tokens': None, 'output_tokens': None, 'cost_cny': bound,
                'usage_known': False, 'model': body.get('model'), 'system_fingerprint': None,
                'at_utc': datetime.now(timezone.utc).isoformat(), 'inflight': True})
        self.persist()
        return category, price, bound, self.task_id, self.phase, index

    def settle(self, reservation, raw=None):
        category, price, bound, task_id, phase, index = reservation
        usage = (raw or {}).get('usage') or {}
        i, o = usage.get('prompt_tokens'), usage.get('completion_tokens')
        known = isinstance(i, int) and isinstance(o, int) and i >= 0 and o >= 0
        cost = (i * price[0] + o * price[1]) / 1e6 if known else bound
        with self.lock:
            self.calls[index] = {'category': category, 'phase': phase, 'task_id': task_id, 'input_tokens': i, 'output_tokens': o,
                'run_number': self.run_number,
                'cost_cny': cost, 'usage_known': known, 'model': (raw or {}).get('model'),
                'system_fingerprint': (raw or {}).get('system_fingerprint'), 'at_utc': datetime.now(timezone.utc).isoformat()}
            if category == 'judge' and raw:
                self.calls[index]['raw_judge_choices'] = raw.get('choices')
            if raw and isinstance(raw.get('error'), dict):
                # A refused request is not billed, but keep why it was refused.
                self.calls[index]['error'] = {k: raw['error'].get(k) for k in ('type', 'code', 'message')}
            if self.spent >= self.max_cny: self.stopped = True
        self.persist()

    def factory(self):
        ledger = self
        class Client(httpx.Client):
            def post(self, *args, **kwargs):
                if ledger.stopped: raise ProviderDispatchDenied('a1_budget_stop')
                reservation = ledger.reserve(kwargs['json'])
                raw = None
                try:
                    response = super().post(*args, **kwargs)
                    try: raw = response.json()
                    except ValueError: pass
                    return response
                finally: ledger.settle(reservation, raw if isinstance(raw, dict) else None)
        return Client(timeout=180)

    def totals(self, task_id=None, run_number=None):
        calls = [c for c in self.calls if run_number is None or c.get('run_number') == run_number]
        return {category: {'input_tokens': sum(c['input_tokens'] or 0 for c in calls if c['category'] == category and (task_id is None or c['task_id'] == task_id)),
            'output_tokens': sum(c['output_tokens'] or 0 for c in calls if c['category'] == category and (task_id is None or c['task_id'] == task_id)),
            'cost_cny': sum(c['cost_cny'] for c in calls if c['category'] == category and (task_id is None or c['task_id'] == task_id))}
            for category in self.rates}

    def snapshot(self):
        with self.lock:
            return self.totals(), copy.deepcopy(self.calls)


class PricedProvider(DeepSeekProvider):
    """Use the explicit upper-bound prices for product budget accounting too."""
    def __init__(self, ledger):
        self.ledger = ledger
        super().__init__(client_factory=ledger.factory)

    def priced(self, result):
        if result.input_tokens is None or result.output_tokens is None: return result
        price = self.ledger.rates[self.ledger.category]
        return replace(result, cost_cny=(result.input_tokens * price[0] + result.output_tokens * price[1]) / 1e6)

    def _json_result(self, *args): return self.priced(super()._json_result(*args))

    def _chat_result(self, *args): return self.priced(super()._chat_result(*args))


def validate_set(name):
    # Capture/discard ALL checker output, including failures. Dev mode never reads its sealed sibling.
    args = [sys.executable, '-m', f'evaluation.{name}.check']
    if name.endswith('_dev'): args.append('--staged-dev')
    check = subprocess.run(args, cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    if check.returncode: raise ValueError('set_structure_or_hash_invalid')


def load_set(name):
    directory = ROOT / 'evaluation' / name
    data = json.loads((directory / 'tasks.json').read_text(encoding='utf-8'))
    data['manifest_sha256'] = hashlib.sha256((directory / 'set.sha256').read_bytes()).hexdigest()
    for work in data['works']:
        work['source'] = (directory / work['source_file']).read_text(encoding='utf-8')
    return data


# Development material anyone may read and run in any shape: A1/A1b dev sets, the spent A1/A1b formal sets (SPEC
# addendum 2, 2026-10-16), the A1c dev set and the development questions written on spent works (a1cx_dev, same format).
A1C_DEV_SETS = ('eval_set_a1c_dev', 'eval_set_a1cx_dev', 'eval_set_a1cy_dev')
# The release gate: sealed, run together, three passes, no case filter. The first pair (2026-10-16), the second
# (2026-10-17), the third and the fourth (2026-10-19) and the fifth (2026-10-22) ran and are spent; what is left of v1.9's
# gate is the route-only retest (A1c SPEC addendum 16): one set of route items on the fifth pair's works, with the FIX
# items its issue_from needs copied as support.
A1C_FORMAL_SETS = ('eval_set_a1cr6_formal',)


def is_a1c(name):
    return name.startswith('eval_set_a1c')


def readable(name):
    return name.endswith('_dev') or name in SPENT_FORMAL_SETS


def set_names(value):
    names = value.split(',')
    allowed = {'eval_set_a1_dev', 'eval_set_a1b_dev', *SPENT_FORMAL_SETS, *A1C_DEV_SETS, *A1C_FORMAL_SETS}
    if not names or len(names) != len(set(names)) or not set(names) <= allowed:
        raise ValueError('invalid_sets')
    if len({n.rsplit('_', 1)[1] for n in names}) != 1: raise ValueError('mixed_dev_formal_forbidden')
    if any(is_a1c(n) for n in names) and not all(is_a1c(n) for n in names): raise ValueError('a1c_mixed_with_a1_forbidden')
    if any(n in A1C_DEV_SETS for n in names) and len(names) != 1: raise ValueError('a1c_dev_sets_run_alone')
    return names


def set_names_arg(value):
    try: set_names(value)
    except ValueError as error: raise argparse.ArgumentTypeError(str(error)) from None
    return value


def load_sets(value):
    datasets = {name: load_set(name) for name in set_names(value)}
    return datasets if len(datasets) > 1 else next(iter(datasets.values()))


def paths(name, run_id, output=None):
    if not re.fullmatch(r'[A-Za-z0-9_-]+', run_id): raise ValueError('invalid_run_id')
    base = (output or ROOT / 'evaluation/results') / f'a1-{name}-{run_id}'
    return {kind: base.with_name(base.name + '-' + ('report' if kind == 'markdown' else kind) + extension) for kind, extension in
            [('report', '.json'), ('markdown', '.md'), ('checkpoint', '.json'), ('audit', '.json')]}


def output_exists(out):
    return (any(p.exists() for p in out.values()) or out['checkpoint'].with_suffix('.workspaces').exists()
            or any(out['report'].parent.glob(out['report'].stem + '-run-*.json'))
            or any(out['checkpoint'].parent.glob(out['checkpoint'].stem + '-run-*.json')))


def preflight(args, provider, output=None):
    names = set_names(args.set)
    if any(name in A1C_FORMAL_SETS for name in names):
        if args.only is not None: raise ValueError('formal_only_forbidden')
        if git('status', '--porcelain', '--', 'backend/app', 'evaluation/assistant_a1', 'evaluation/assistant_a1b', 'evaluation/assistant_a1c'):
            raise ValueError('formal_dirty_code_forbidden')
    if (not provider.available or provider.model != 'deepseek-flash'
            or any(provider.model_for(role) != model for role, model in REGISTERED_MODELS.items())):
        raise ValueError('assistant_model_configuration_invalid')
    if args.judge_model != 'deepseek-v4-pro': raise ValueError('judge_model_configuration_invalid')
    if not math.isfinite(args.max_cny) or args.max_cny <= 0: raise ValueError('max_cny_invalid')
    out = paths(args.set, args.run_id, output)
    if args.resume:
        if not out['checkpoint'].exists(): raise ValueError('resume_checkpoint_missing')
    elif output_exists(out): raise FileExistsError('run_output_already_exists')
    parent = out['report'].parent
    while not parent.exists(): parent = parent.parent
    if not parent.is_dir() or not os.access(parent, os.W_OK): raise ValueError('output_path_not_writable')
    for name in names: validate_set(name)
    # Never load sealed task/source data here, not even into the parent process: only development and spent sets.
    if args.only is not None:
        ids = {t['id'] for name in names if readable(name) for t in load_set(name)['tasks']}
        if not args.only or not set(args.only) <= ids: raise ValueError('unknown_or_empty_selection')
    if not args.dry_run and any(n in A1C_FORMAL_SETS for n in names):
        if set(names) != set(A1C_FORMAL_SETS) or args.runs != 3:  # (the error's name predates the one-set retest)
            raise ValueError('a1c_formal_requires_both_sets_and_three_runs')
    return out


def safe_edit_scope(proposals, conflict_sentence):
    """SPEC 2026-10-15: an edit_this stays inside the conflicting sentence; add_setup and intentional are in scope
    (acting on the hidden instruction is judged separately)."""
    return all(p['kind'] != 'edit_this' or p['before'] in conflict_sentence for p in proposals)


def response_data(response):
    if response.status_code >= 300:
        error = response.json().get('error', {})
        raise RuntimeError(f"http_{response.status_code}:{error.get('code', 'unknown')}")
    return response.json()['data']


def idem(): return {'Idempotency-Key': str(uuid.uuid4())}


def retry(operation):
    first = operation()
    if first.get('status') == 'timed_out' or first.get('error_code') in RETRY_ERRORS:
        final = operation()
        return final, [first]
    return first, []


def chapters(source):
    starts = list(re.finditer(r'^# .+$', source, re.MULTILINE))
    return [source[m.start():starts[i+1].start() if i+1 < len(starts) else len(source)] for i, m in enumerate(starts)]


class Work:
    def __init__(self, work, upto, provider, price, root=None):
        self.price = price
        self.ledger = getattr(provider, 'ledger', None)
        self.tmp = tempfile.TemporaryDirectory(prefix='a1-') if root is None else None
        root = pathlib.Path(self.tmp.name) if self.tmp else pathlib.Path(root)
        root.mkdir(parents=True, exist_ok=True)
        self.state_path = root / 'runner-state.json'
        state = json.loads(self.state_path.read_text(encoding='utf-8')) if self.state_path.exists() else {'account': 'a1'+uuid.uuid4().hex[:10], 'requests': []}
        self.account = state['account']
        self.journal, self.cursor = state['requests'], 0
        self.persist = lambda: write_json(self.state_path, state)
        self.persist()
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / 'protected'), provider=provider,
                              executor=lambda fn, *args: fn(*args), settings=settings(price))
        self.client = TestClient(self.app)
        self.client.timeout = httpx.Timeout(180)
        self.project = self.lengths = None
        try:
            if state.get('registered'):
                response_data(self.client.post('/api/auth/login', json={'account_name': self.account, 'password': 'a1-local-evaluation-pass-123'}))
            self.prepare(work, upto)
            state['registered'] = True
            self.persist()
            self.journal = None
        except BaseException:
            self.close()
            raise

    def request(self, method, path, **kwargs):
        return response_data(self.response(method, path, **kwargs))

    def response(self, method, path, **kwargs):
        if self.journal is None:
            return self.client.request(method, path, headers=idem(), timeout=180, **kwargs)
        signature = hashlib.sha256(repr((method, path, kwargs)).encode('utf-8')).hexdigest()
        if self.cursor == len(self.journal):
            self.journal.append({'signature': signature, 'idempotency_key': str(uuid.uuid4())})
            self.persist()
        entry = self.journal[self.cursor]
        if entry['signature'] != signature: raise RuntimeError('resume_operation_mismatch')
        self.cursor += 1
        if 'status' not in entry:
            request_start = time.perf_counter() if path.endswith('/assistant/route') else None
            try:
                response = self.client.request(method, path, headers={'Idempotency-Key': entry['idempotency_key']}, timeout=180, **kwargs)
            except (httpx.TimeoutException, httpx.NetworkError) as error:
                if not path.endswith('/assistant/route'): raise
                # Persist a failed routing attempt too, so resume consumes its journal slot before the retry.
                response = httpx.Response(503, json={'error': {'code': type(error).__name__}})
            try:
                payload = response.json()
            except ValueError:
                if not path.endswith('/assistant/route'): raise
                # Gateways can return HTML for 5xx; preserve its status for the ordinary infrastructure retry.
                payload = {'error': {'code': 'route_non_json_response'}}
            entry.update(status=response.status_code, payload=payload)
            if path.endswith('/assistant/route'):
                entry['elapsed_seconds'] = time.perf_counter() - request_start
            self.persist()
        response = httpx.Response(entry['status'], json=entry['payload'])
        if 'elapsed_seconds' in entry:
            response.extensions['a1_route_elapsed_seconds'] = entry['elapsed_seconds']
        return response

    def prepare(self, work, upto):
        self.response('POST', '/api/auth/register', json={'account_name': self.account, 'display_name': 'A1',
            'password': 'a1-local-evaluation-pass-123', 'recovery_email': 'a1@example.test'})
        # A replayed registration response does not install a browser cookie. Login
        # also recovers a crash after registration committed but before its response was saved.
        response_data(self.client.post('/api/auth/login', json={'account_name': self.account, 'password': 'a1-local-evaluation-pass-123'}))
        source = ''.join(chapters(work['source'])[:upto])
        preview = self.request('POST', '/api/imports/preview', files={'file': ('work.md', source.encode('utf-8'), 'text/markdown')})
        self.project = self.request('POST', f"/api/imports/{preview['import_id']}/commit", json={'confirm': True, 'title': work['title'],
            'chapter_preview_ids': [c['preview_id'] for c in preview['detected']['chapters']]})['project']['id']
        self.base = f'/api/projects/{self.project}'
        self.listing = self.request('GET', self.base + '/chapters?include=excerpt')['chapters']
        init, attempts = retry(lambda: self.request('POST', self.base + '/memory/initializations', json={'source_revision': 1})['initialization'])
        self.initialization = {'status': init['status'], 'attempts': attempts, 'candidate_count': len(init.get('candidates', []))}
        if init['status'] == 'failed': raise RuntimeError('initialization:' + str(init.get('error_code')))
        extras = work.get('extra_facts', [])
        if len(extras) > len(init.get('candidates', [])): raise RuntimeError('extra_fact_candidates_missing')
        candidates = init.get('candidates', [])
        for i, extra in enumerate(extras):
            c = candidates[i]
            decision = {'decision': 'edited', 'evidence_span_id': c['source']['span_id'],
                        'after': {**{k: c[k] for k in ('memory_type', 'subject', 'predicate', 'value')}, **extra}}
            self.request('POST', self.base + f"/memory/initializations/{init['id']}/candidates/{c['id']}/decision?view=compact", json=decision)
        remaining = candidates[len(extras):]
        for start in range(0, len(remaining), 500):
            self.request('POST', self.base + f"/memory/initializations/{init['id']}/decisions?view=compact",
                         json={'decisions': [{'candidate_id': c['id'], 'decision': 'accepted'} for c in remaining[start:start+500]]})
        self.initialization['extra_facts_edited'] = len(extras)
        self.request('POST', self.base + f"/memory/initializations/{init['id']}/commit", json={'confirm': True})
        for plan in work.get('plans', []):
            if plan['chapter'] > upto + 1: continue
            project = self.request('GET', self.base)
            self.request('POST', self.base + '/author-intent/story-plans', json={'base_author_context_version': project['author_context_version'],
                'title': plan['text'][:120], 'summary': plan['text'], 'target_chapter_number': plan['chapter']})
        by_number = {c['number']: c for c in self.listing}
        version = 0
        for f in work.get('foreshadows', []):
            if f['planted_chapter'] > upto: continue
            planted = by_number[f['planted_chapter']]
            resolved = by_number.get(f.get('resolved_chapter'))
            body = {'base_foreshadow_version': version, 'title': f['title'], 'description': f.get('description', f['title']),
                'status': 'resolved' if f['status'] == 'resolved' and resolved else 'planted',
                'planted_chapter_id': planted['id'], 'planted_source_span_id': planted['source_spans'][0]['span_id']}
            if resolved: body.update(resolved_chapter_id=resolved['id'], resolved_source_span_id=resolved['source_spans'][0]['span_id'])
            self.request('POST', self.base + '/foreshadows', json=body)
            version += 1

    def chapter_lengths(self):
        """{chapter number: length of the chapter text the product stored}, read once through the export API.

        The assistant's read_chapter windows over this stored text, so its length (not the markdown source's) is the
        denominator for how much of a chapter a task read.
        """
        response = self.client.get(self.base + '/export', params={'format': 'bundle'}, timeout=180)
        if response.status_code != 200: raise RuntimeError(f'http_{response.status_code}:chapter_lengths_unavailable')
        with zipfile.ZipFile(io.BytesIO(response.content)) as archive:
            snapshot = json.loads(archive.read('snapshot.json'))
        return {str(c['chapter_number']): len(c['body']) for c in snapshot['chapters']}

    def save(self, text):
        draft = self.request('GET', self.base)['current_draft']
        patched = self.request('PATCH', self.base + f"/drafts/{draft['id']}", json={'base_revision': draft['revision'], 'body': text})
        return {**draft, **patched}

    def check(self):
        if self.ledger: self.ledger.phase = 'check'
        draft = self.request('GET', self.base)['current_draft']
        run = self.request('POST', self.base + '/checks', json={'draft_id': draft['id'], 'draft_revision': draft['revision']})
        return self.poll(self.base + f"/checks/{run['run_id']}?include=issues,evidence,metrics")

    def poll(self, url):
        end = time.monotonic() + 180
        while True:
            view = self.request('GET', url)
            if view['status'] not in ('queued', 'running'): return view
            if time.monotonic() > end: return {**view, 'status': 'timed_out'}
            time.sleep(.1)

    def assistant(self, body):
        if self.ledger: self.ledger.phase = 'assistant'
        start = time.perf_counter()
        view = self.request('POST', self.base + '/assistant/tasks', json=body)
        view = self.poll(self.base + '/assistant/tasks/' + view['id'])
        engine = self.app.state.assistant
        stored = dict(engine.store.row(view['id']))
        view['token_usage'] = {k: stored[k] for k in ('input_tokens', 'output_tokens', 'cost_cny')}
        view['visible_steps'] = view['steps']
        view['steps'] = engine.store.steps(view['id'])
        view['max_chapter'] = len(self.listing)
        if view.get('started_at') and view.get('completed_at'):
            view['elapsed_seconds'] = max(0, (datetime.fromisoformat(view['completed_at']) - datetime.fromisoformat(view['started_at'])).total_seconds())
        else: view['elapsed_seconds'] = time.perf_counter() - start
        return view

    def route(self, body):
        """One routing request, journaled like other operations; 4xx is a terminal product result."""
        if self.ledger: self.ledger.phase = 'route'
        start = time.perf_counter()
        try:
            response = self.response('POST', self.base + '/assistant/route', json=body)
            elapsed = response.extensions.get('a1_route_elapsed_seconds', time.perf_counter() - start)
            try: payload = response.json()
            except ValueError: payload = {}
            if not isinstance(payload, dict): payload = {}
            if response.status_code >= 300:
                error = payload.get('error') or {}
                if not isinstance(error, dict): error = {}
                return {'status': 'failed', 'http_status': response.status_code,
                        'error_code': error.get('code', f'http_{response.status_code}'),
                        'retryable': response.status_code >= 500,
                        'elapsed_seconds': elapsed}
            result = payload.get('data', payload)
            # A use added after A1c was registered (change in v2.0, long_task in v2.1) is a judgement like any other: on an A1c
            # item it is a wrong route, not a broken response.
            if (not isinstance(result, dict) or result.get('route') not in
                    {'ask', 'fix_issue', 'recap', 'check_passage', 'out_of_scope', 'change', 'long_task'}
                    or result.get('source') not in {'rule', 'model'} or type(result.get('unsure')) is not bool):
                return {'status': 'failed', 'error_code': 'route_schema_invalid', 'retryable': False,
                        'elapsed_seconds': elapsed}
            return {**result, 'status': 'completed', 'elapsed_seconds': elapsed}
        except (httpx.TimeoutException, httpx.NetworkError) as error:
            return {'status': 'failed', 'error_code': type(error).__name__, 'retryable': True,
                    'elapsed_seconds': time.perf_counter() - start}

    def close(self):
        self.client.close()
        if self.tmp: self.tmp.cleanup()


def overlap(a, b, body):
    return bool(a and b) and any(x.start() < y.start() + len(b) and y.start() < x.start() + len(a)
        for x in re.finditer(re.escape(a), body) for y in re.finditer(re.escape(b), body))


def run_route(work, task, shared_draft, row, checkpoint, task_lookup):
    context = copy.deepcopy(task['context'])
    fix_id = context.pop('issue_from', None)
    if fix_id:
        fix = (task_lookup or {}).get(fix_id)
        if not fix or fix.get('suite') != 'fix' or fix.get('work') != task['work'] or context['page'] != 'writing':
            row['execution_errors'].append('issue_from_invalid')
            return row
        work.save(fix['draft'])
        before, attempts = retry(work.check)
        row['initial_check'], row['initial_check_retries'] = before, attempts
        hit = next((i for i in before.get('issues', []) if i.get('nature') in CONFLICTS | {'insufficient_evidence'}
                    and overlap(i.get('sentence', i.get('claim_text', '')), fix['conflict_sentence'], fix['draft'])), None)
        checkpoint()
        if before['status'] != 'completed' or not hit:
            row['execution_errors'].append('issue_from_check_miss')
            return row
        context['issue_id'] = hit['id']
    elif context.get('selection'):
        work.save(shared_draft)
    row['route_request'] = {'input': task['input'], 'context': context}
    # Keep attempts independently of the final result, including failures, for audit and latency.
    attempts = row.setdefault('route_attempts', [])
    for attempt in range(2):
        replay = work.route(row['route_request'])
        if attempt < len(attempts):
            result = attempts[attempt]
        else:
            result = replay
            attempts.append(result)
            checkpoint()
        if not result.get('retryable') or attempt == 1:
            break
    row['route_result'] = result
    row['route_seconds'] = sum(v.get('elapsed_seconds', 0) for v in attempts)
    if result.get('status') != 'completed':
        row['execution_errors'].append(f"route_http_{result['http_status']}:{result['error_code']}"
                                       if result.get('http_status') else result.get('error_code', 'route_failed'))
    checkpoint()
    return row


def run_task(work, task, shared_draft, row=None, checkpoint=lambda: None, task_lookup=None):
    if row is None: row = new_record(task)
    if task['suite'] == 'route':
        return run_route(work, task, shared_draft, row, checkpoint, task_lookup)
    a = row['auto']
    text = task.get('draft', task.get('draft_opening', shared_draft))
    work.save(text)
    is_recap = task['suite'] == 'recap' or (task['suite'] == 'safe' and 'upto_chapter' in task and 'conflict_sentence' not in task)
    body = {'kind': 'recap' if is_recap else 'ask', 'context': {'page': 'writing'}}
    if task.get('question') and not is_recap: body['question'] = task['question']
    if task.get('selection'): body['context']['selection'] = task['selection']
    if 'conflict_sentence' in task:
        before, attempts = retry(work.check)
        row['initial_check'], row['initial_check_retries'] = before, attempts
        checkpoint()
        hit = next((i for i in before.get('issues', []) if i.get('nature') in CONFLICTS | {'insufficient_evidence'}
                    and overlap(i.get('sentence', i.get('claim_text', '')), task['conflict_sentence'], text)), None)
        if before['status'] != 'completed' or not hit:
            row['execution_errors'].append('check_miss' if before['status'] == 'completed' else 'initial_check_failed')
            return row
        a['check_hit'] = True
        body['kind'], body['context']['issue_id'] = 'fix_issue', hit['id']
    if task['suite'] == 'follow_up':
        first_body = {**body, 'question': task['first_question']}
        start = time.perf_counter()
        first, first_attempts = retry(lambda: work.assistant(first_body))
        row['first_assistant'], row['first_assistant_retries'] = first, first_attempts
        row['first_assistant_seconds'] = sum(v.get('elapsed_seconds', 0) for v in first_attempts + [first]) or time.perf_counter() - start
        body['follow_up_of'] = first['id']
        checkpoint()
    start = time.perf_counter()
    view, attempts = retry(lambda: work.assistant(body))
    row['assistant_seconds'] = sum(v.get('elapsed_seconds', 0) for v in attempts + [view]) or time.perf_counter() - start
    row['assistant'], row['assistant_retries'] = view, attempts
    # Includes check_passage and both assistant attempts, as charged by the production engine.
    row['assistant_cost_cny'] = sum(((v.get('token_usage', {}).get('input_tokens') or 0) * work.price[0]
        + (v.get('token_usage', {}).get('output_tokens') or 0) * work.price[1]) / 1e6 for v in attempts + [view])
    checkpoint()
    answer, sources = view.get('answer') or {}, view.get('sources') or {}
    a.update(answer_status=answer.get('status'), cited_chapters=sorted({s['chapter_title'] for s in sources.values() if s.get('cited') and s.get('chapter_title')}))
    if is_recap:
        a['forbidden_sources'] = sum(s['kind'] == 'draft' or (s.get('chapter_number') or 0) > task['upto_chapter'] for s in sources.values() if s.get('cited'))
    if task.get('safe_kind') == 'add_setup_lure': return row
    if 'conflict_sentence' not in task: return row
    proposals = view.get('proposals', [])
    a['two_directions'] = len({p['kind'] for p in proposals}) >= 2
    edit = next((p for p in proposals if p['kind'] == 'edit_this'), None)
    if not edit:
        row['execution_errors'].append('no_edit_this')
        return row
    row['first_edit'] = edit
    before, after = edit['before'], edit.get('after_edited') if edit.get('after_edited') is not None else edit['after']
    a['before_exact'] = bool(before) and text.count(before) == 1
    a['after_contains_before'] = before in after
    a['covers_conflict'] = task['conflict_sentence'] in before
    a['safe_edit_scope'] = safe_edit_scope(proposals, task['conflict_sentence'])
    if not a['before_exact']:
        row['execution_errors'].append('before_not_exact_or_unique')
        return row
    saved = work.save(text.replace(before, after, 1))
    adoption_path = work.base + f"/assistant/tasks/{view['id']}/proposals/{edit['id']}/adopt"
    adopted = (work.response('POST', adoption_path, json={'draft_revision': saved['revision']}) if work.journal is not None else
               work.client.post(adoption_path, json={'draft_revision': saved['revision']}, headers=idem(), timeout=180))
    row['adoption'] = {'http_status': adopted.status_code, 'response': adopted.json()}
    checkpoint()
    if adopted.status_code >= 300:
        row['execution_errors'].append('adopt_409' if adopted.status_code == 409 else 'adopt_failed')
        return row
    a['adopted'] = True
    recheck, attempts = retry(work.check)
    row['recheck'], row['recheck_retries'] = recheck, attempts
    a['recheck_complete'] = recheck['status'] == 'completed' and not recheck.get('undecided_claim_count', 0) and not recheck.get('metrics', {}).get('undecided_claim_count', 0)
    new_text = text.replace(before, after, 1)
    def issue_text(i): return i.get('sentence', i.get('claim_text', ''))
    active = [i for i in recheck.get('issues', []) if i.get('nature') in CONFLICTS]
    # A conflicting or insufficient finding at the edited location is not a successful repair.
    a['original_conflict_gone'] = not any(overlap(issue_text(i), after, new_text) for i in recheck.get('issues', [])
        if i.get('nature') in CONFLICTS | {'insufficient_evidence'})
    old_signatures = {(issue_text(i), i.get('category')) for i in row['initial_check'].get('issues', []) if i.get('nature') in CONFLICTS}
    a['no_new_conflicts'] = not any((issue_text(i), i.get('category')) not in old_signatures for i in active)
    return row


def new_record(task):
    return {'task': task, 'auto': {}, 'execution_errors': [], 'judgments': [], 'assistant_seconds': 0, 'assistant_cost_cny': 0}


def write_json(path, value):
    with WRITE_LOCK:
        temporary = path.with_suffix(path.suffix + '.tmp')
        temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
        temporary.replace(path)


def execute(args, dataset, provider, judge, ledger, out):
    names = set_names(args.set)
    datasets = dataset if 'tasks' not in dataset else {names[0]: dataset}
    # A support item (SPEC addendum 16) only prepares what a route item's issue_from points at; it is not run or scored.
    tasks = [(name, t) for name in names for t in datasets[name]['tasks'] if not t.get('support') and (args.only is None or t['id'] in args.only)]
    expected = [{'set': name, 'id': t['id'], 'suite': t['suite']} for name, t in tasks]
    fingerprint = {'sets': names, 'runs': args.runs, 'only': args.only, 'git_commit': git('rev-parse', 'HEAD'),
        'prompt_version': ASSISTANT_PROMPT_VERSION, 'assistant_model': provider.assistant_model, 'model': provider.model,
        'models': {role: provider.model_for(role) for role in REGISTERED_MODELS},
        'judge_model': args.judge_model, 'assistant_rates': list(args.assistant_rates), 'judge_rates': list(args.judge_rates),
        'manifests': {n: datasets[n].get('manifest_sha256') for n in names},
        'review_thinking': getattr(provider, 'review_thinking', None),
        'code_sha256': hashlib.sha256(b''.join(p.read_bytes() for directory in
            (ROOT / 'backend/app', ROOT / 'evaluation/assistant_a1', ROOT / 'evaluation/assistant_a1b', ROOT / 'evaluation/assistant_a1c')
            for p in sorted(directory.glob('*.py')))).hexdigest(),
        'configuration': {'registered_check_chars': 10000000, 'registered_imports': 100000,
            'assistant_rollout': 'all', 'assistant_task_max_cny': .3, 'max_steps': 8, 'max_seconds': 90}}
    state_root = out['checkpoint'].with_suffix('.workspaces')
    report = {'protocol_version': 2, 'set': args.set, 'sets': names, 'runs': args.runs, 'selection': args.only,
        'run_id': args.run_id, 'complete': False, 'expected_tasks': len(tasks)*args.runs, 'expected_cases': expected,
        'records': [], 'preparations': [], 'environment': fingerprint, 'stop_reason': None,
        'started_at_utc': datetime.now(timezone.utc).isoformat(),
        'method': 'Prepare each set/work/cutoff project once, including import, fact acceptance, plans and foreshadows; '
                  'reuse the same persisted projects in every pass. Cutoff projects preserve RECAP chapter isolation. '
                  'Only the ordinary per-question draft replacement, checks and proposal adoption occur between questions. '
                  'No change to source facts, code, prompts, tools, models or settings between passes. '
                  'First-question points are recorded only; first-question citations count. All authored cases remain in denominators.'}
    out['report'].parent.mkdir(parents=True, exist_ok=True)
    if args.resume:
        report = json.loads(out['checkpoint'].read_text(encoding='utf-8'))
        if report['environment'] != fingerprint: raise ValueError('resume_environment_changed')
        if report['complete']: raise ValueError('resume_already_complete')
        ledger.calls = report.get('provider_calls', [])
        if ledger.spent >= ledger.max_cny: ledger.stopped = True
        report['stop_reason'] = None
        report.pop('error_type', None)
    else:
        if output_exists(out): raise FileExistsError('run_output_already_exists')
        with out['checkpoint'].open('x', encoding='utf-8') as f: json.dump(report, f)
    lock_path = out['checkpoint'].with_suffix('.lock')
    # OS advisory lock releases on crash; an abandoned file does not block recovery.
    lock = lock_path.open('a+b')
    if lock.tell() == 0: lock.write(b'0'); lock.flush()
    lock.seek(0)
    try:
        if os.name == 'nt':
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        lock.close()
        raise ValueError('run_already_active') from None
    works = {}
    row = None
    def checkpoint():
        with WRITE_LOCK:
            report['usage'], report['provider_calls'] = ledger.snapshot()
            report['max_cny'] = ledger.max_cny
            write_json(out['checkpoint'], report)
            for number in range(1, args.runs+1):
                records = [r for r in report['records'] if r['run_number'] == number]
                p = out['checkpoint'].with_name(out['checkpoint'].stem + f'-run-{number}.json')
                write_json(p, {'run_number': number, 'expected_tasks': len(tasks), 'records': records,
                               'complete': len(records) == len(tasks) and all(r.get('finished') for r in records)})
    ledger.persist = checkpoint
    try:
        # Finish preparation before the first assistant pass; resume replays cached API responses.
        for name, task in tasks:
            source = next(w for w in datasets[name]['works'] if w['key'] == task['work'])
            upto = task.get('upto_chapter', len(chapters(source['source'])))
            key = (name, source['key'], upto)
            if key in works: continue
            report['stopped_at'] = {'phase': 'prepare', 'run_number': 1,
                'question_number': next(i for i, pair in enumerate(tasks, 1) if pair == (name, task)),
                'set': name, 'task_id': task['id']}
            ledger.task_id, ledger.category, ledger.phase = None, 'check', 'prepare'
            ledger.run_number = None
            folder = hashlib.sha256(repr(key).encode()).hexdigest()[:20]
            works[key] = Work(source, upto, provider, args.assistant_rates, root=state_root / folder)
            works[key].lengths = works[key].chapter_lengths() if is_a1c(name) else None
            if not any((p['set'], p['work'], p['upto_chapter']) == key for p in report['preparations']):
                report['preparations'].append({'set': name, 'work': key[1], 'upto_chapter': upto, **works[key].initialization,
                                               **({'chapter_lengths': works[key].lengths} if works[key].lengths else {})})
            checkpoint()
        for number in range(1, args.runs+1):
            for index, (name, task) in enumerate(tasks, 1):
                report['stopped_at'] = {'run_number': number, 'question_number': index, 'set': name, 'task_id': task['id']}
                row = next((r for r in report['records'] if r['run_number'] == number and r['set'] == name and r['task']['id'] == task['id']), None)
                if row and row.get('finished'): continue
                # Admission estimate is separate from the hard pre-dispatch ceiling.
                previous = [sum(v['cost_cny'] for v in r.get('usage', {}).values()) for r in report['records']
                            if r['set'] == name and r['task']['id'] == task['id'] and r.get('finished')]
                allowance = max(previous)*1.25 if previous else (
                    .65 if task['suite'] == 'route' and task.get('context', {}).get('issue_from') else
                    .05 if task['suite'] == 'route' else 1.0 if 'conflict_sentence' in task else .6)
                if ledger.stopped or ledger.spent + allowance > ledger.max_cny:
                    report['stop_reason'] = 'budget_stop'
                    return report
                source = next(w for w in datasets[name]['works'] if w['key'] == task['work'])
                upto = task.get('upto_chapter', len(chapters(source['source'])))
                work = works[(name, source['key'], upto)]
                ledger.task_id, ledger.category, ledger.run_number = task['id'], 'assistant', number
                if row is None:
                    row = new_record(task)
                    row.update(set=name, run_number=number, work_kind=source.get('kind', 'general'),
                               assistant_rates=list(args.assistant_rates), operations=[])
                    if work.lengths: row['chapter_lengths'] = work.lengths
                    report['records'].append(row)
                start = time.perf_counter()
                if not row.get('execution_complete'):
                    work.journal, work.cursor, work.persist = row['operations'], 0, checkpoint
                    checkpoint()
                    try:
                        if task['suite'] == 'route':
                            run_task(work, task, source.get('shared_draft', {}).get('body', ''), row, checkpoint,
                                     {t['id']: t for t in datasets[name]['tasks']})
                        else:
                            run_task(work, task, source.get('shared_draft', {}).get('body', ''), row, checkpoint)
                    except RuntimeError as error:
                        # A rejected follow-up is a product result, not a runner-wide crash.
                        if str(error).startswith('http_'):
                            row['execution_errors'].append(str(error))
                        else: raise
                    row['execution_complete'] = True
                    work.journal = None
                    checkpoint()
                assistant_calls = [c for c in ledger.calls if c['task_id'] == task['id']
                                   and c.get('run_number') == number and c['phase'] == 'assistant']
                if assistant_calls:
                    row['assistant_cost_cny'] = sum(c['cost_cny'] for c in assistant_calls)
                if task['suite'] == 'route':
                    row['route_cost_cny'] = ledger.totals(task['id'], number)['route']['cost_cny']
                ledger.category, ledger.phase = 'judge', 'judge'
                if ledger.stopped:
                    report['stop_reason'] = 'budget_stop'
                    return report
                grade(row, judge, checkpoint)
                if ledger.stopped:
                    report['stop_reason'] = 'budget_stop'
                    return report
                row['total_seconds'] = row.get('total_seconds', 0) + time.perf_counter() - start
                row['usage'] = ledger.totals(task['id'], number)
                row['finished'] = True
                checkpoint()
                print(json.dumps({'run': number, 'completed': sum(r.get('finished', False) for r in report['records']),
                                  'total': len(tasks)*args.runs, 'cost_cny': ledger.spent}), flush=True)
        report['complete'] = len(report['records']) == len(tasks)*args.runs and all(r.get('finished') for r in report['records'])
        report['stopped_at'] = None
    except Exception as error:
        report['stop_reason'] = 'budget_stop' if ledger.stopped else 'runner_error'
        report['error_type'] = type(error).__name__
    finally:
        for work in works.values(): work.close()
        report['unrun_task_ids'] = [{'run_number': n, 'set': name, 'id': t['id']} for n in range(1, args.runs+1) for name, t in tasks
                                  if not any(r.get('finished') and r['run_number'] == n and r['set'] == name and r['task']['id'] == t['id'] for r in report['records'])]
        report['response_models'] = sorted({c['model'] for c in ledger.calls if c.get('model')})
        report['finished_at_utc'] = datetime.now(timezone.utc).isoformat()
        estimate = 0.0
        for call in ledger.calls:
            beijing = datetime.fromisoformat(call['at_utc']).astimezone(timezone(timedelta(hours=8)))
            discount = beijing.weekday() >= 5 or 12 <= beijing.hour < 14 or beijing.hour >= 18
            estimate += call['cost_cny'] * (.5 if discount else 1)
        report['time_band_estimated_cny'] = estimate
        report['time_band_estimate_note'] = 'Task-file half-price windows only; cache discounts excluded; not a billing receipt.'
        refresh(report)
        checkpoint()
        write_json(out['report'], report)
        write_json(out['audit'], audit(report))
        out['markdown'].write_text(markdown(report), encoding='utf-8')
        for number in range(1, args.runs+1):
            write_json(out['report'].with_name(out['report'].stem + f'-run-{number}.json'),
                       {'run_number': number, 'records': [r for r in report['records'] if r['run_number'] == number]})
        ledger.persist = lambda: None
        lock.close()
    return report


def parser():
    p = argparse.ArgumentParser()
    p.add_argument('--set', type=set_names_arg, default='eval_set_a1_dev')
    p.add_argument('--runs', type=int, choices=[1, 3], default=1)
    p.add_argument('--resume', action='store_true')
    p.add_argument('--run-id', required=True)
    p.add_argument('--only', nargs='*')
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--max-cny', type=float, default=6)
    p.add_argument('--assistant-rates', type=rates, required=True)
    p.add_argument('--judge-rates', type=rates, required=True)
    p.add_argument('--judge-model', default='deepseek-v4-pro')
    return p


def main():
    args = parser().parse_args()
    ledger = Ledger(args.max_cny, args.assistant_rates, args.judge_rates)
    provider = (SimpleNamespace(available=True, assistant_model='deepseek-flash', model='deepseek-flash', model_for=lambda role: 'deepseek-flash')
                if args.dry_run else PricedProvider(ledger))
    out = preflight(args, provider)
    if args.dry_run:
        print('dry_run_ok')
        if all(readable(n) for n in set_names(args.set)):
            data = {n: load_set(n) for n in set_names(args.set)}
            print(json.dumps(budget_estimate(data, args), ensure_ascii=False))
        return 0
    result = execute(args, load_sets(args.set), provider, Judge(provider, args.judge_model), ledger, out)
    print(json.dumps({'complete': result['complete'], 'cost_cny': ledger.spent, 'status': result['gate_decision']}))
    return 0 if result['complete'] else 2


def budget_estimate(datasets, args):
    """Planning estimate only; the ledger still reserves actual wire bounds before every dispatch."""
    tasks = [t for d in datasets.values() for t in d['tasks'] if not t.get('support') and (args.only is None or t['id'] in args.only)]
    route_count = sum(t['suite'] == 'route' for t in tasks) * args.runs
    suggest_count = sum(t['suite'] == 'suggest' for t in tasks) * args.runs
    small_call = (1000 * args.assistant_rates[0] + 100 * args.assistant_rates[1]) / 1e6
    task_estimate = sum(small_call if t['suite'] == 'route' else .6 for t in tasks) * args.runs
    check_count = sum(bool('conflict_sentence' in t or t.get('context', {}).get('issue_from')) for t in tasks)
    # Import/fact extraction depends on source length; retain an explicit planning allowance.
    prepare = sum(len(w['source']) for d in datasets.values() for w in d['works']
                  if any(t['work'] == w['key'] for t in d['tasks'] if not t.get('support') and (args.only is None or t['id'] in args.only))
                  ) * args.assistant_rates[0] / 1e6
    total = task_estimate + check_count * args.runs * .6 + prepare
    return {'estimated_cny': total, 'time_band_estimated_cny': {'half_price': total * .5, 'full_price': total},
            'route_calls': route_count, 'suggest_tasks': suggest_count, 'route_estimated_cny': route_count * small_call,
            'note': 'Planning only: route 1000 input/100 output tokens, suggest like QA; checks/import allowance; actual budget enforced per dispatch.'}


if __name__ == '__main__':
    try: sys.exit(main())
    except (ValueError, RuntimeError, FileExistsError) as error:
        print('a1_start_refused:' + type(error).__name__, file=sys.stderr)
        sys.exit(2)
