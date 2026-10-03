"""Cost and time metering for real-model long-form runs: usage split, replay cache, budget cap.

Everything hangs off DeepSeekProvider's `client_factory`, so the product code is unchanged and
every HTTP dispatch is seen exactly once, including length step-downs, contract repairs and
infrastructure retries.

Usage split per dispatch: input tokens that missed / hit the provider's prefix cache, reasoning
(thinking) tokens, visible output tokens. Purpose per dispatch: review, contract_repair,
length_retry (a dispatch that ran out of output and was thrown away), the other task names
(memory_initialization, memory_delta, ...), and unknown_usage (timed out or failed in flight;
charged at its worst-case reserve, because unknown is not zero).

Replay cache (development only): a response is stored under a key computed from the request
body with every UUID replaced by its order of first appearance, because each import mints new
ids. On replay the ids are mapped back. Reasoning text is never stored. A formal run must use
mode "off": the runner refuses anything else.

Budget cap: before each dispatch the meter reserves that dispatch's worst case (prompt length as
tokens plus max_tokens of output). If spent + in-flight reserves + this reserve would pass the cap,
the dispatch is refused with BudgetExceeded and the meter records why; the runner then stops.
"""
from __future__ import annotations

import hashlib
import json
import os
import pathlib
import re
import sys
import threading
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import asdict, dataclass

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT / "backend") not in sys.path:
    sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("SCC_DISABLE_DEFAULT_APP", "1")

import httpx  # noqa: E402

from app.provider import DeepSeekProvider, ProviderDispatchDenied, _dispatch_timeout  # noqa: E402

REPLAY_MODES = ("off", "record", "replay", "replay_or_record")
DEFAULT_CACHE_DIR = ROOT / "evaluation" / ".cache" / "longform-replay"
UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")
PLACEHOLDER = re.compile(r"⟦U(\d+)⟧")
DEFAULT_MAX_OUTPUT = 16000
# Tests swap in an httpx.MockTransport here; None means the real network.
TRANSPORT: httpx.BaseTransport | None = None

_call_kind: ContextVar[str] = ContextVar("longform_call_kind", default="unknown")


@dataclass(frozen=True)
class Prices:
    """CNY per million tokens."""
    input_miss: float
    input_hit: float
    output: float

    def cost(self, miss: int, hit: int, output: int) -> float:
        return (miss * self.input_miss + hit * self.input_hit + output * self.output) / 1_000_000


# The deployment's rates (deploy.env: CONTINUITY_INPUT/OUTPUT_CNY_PER_MILLION = 2.0 / 8.0). The
# product meter has no cache-hit rate, so the gate prices a cache hit like any other input token;
# a discounted estimate is reported beside it, never instead of it.
PRODUCTION_PRICES = Prices(input_miss=2.0, input_hit=2.0, output=8.0)


class BudgetExceeded(ProviderDispatchDenied):
    """The run's budget cap refused a dispatch before it was sent."""


class ReplayMiss(ProviderDispatchDenied):
    """Replay-only mode met a request that was never recorded."""


def call_kind(request: dict) -> str:
    if request.get("task"):
        return str(request["task"])
    return "review_repair" if "contract_repair" in request else "review"


class MeteredProvider(DeepSeekProvider):
    """DeepSeekProvider that tags each dispatch with the purpose of the request that caused it."""

    def evaluate(self, request):
        token = _call_kind.set(call_kind(request))
        try:
            return super().evaluate(request)
        finally:
            _call_kind.reset(token)


def _id_lists_as_sets(value):
    """Sort lists made only of id strings. The product breaks ranking ties by random ids, so the
    same request can list the same ids in a different order from one import to the next."""
    if isinstance(value, dict):
        return {key: _id_lists_as_sets(item) for key, item in value.items()}
    if isinstance(value, list):
        items = [_id_lists_as_sets(item) for item in value]
        if items and all(isinstance(item, str) and PLACEHOLDER.search(item) for item in items):
            return sorted(items)
        return items
    return value


def canonical_body(body: dict) -> tuple[str, list[str]]:
    """The body as canonical JSON with UUIDs replaced by their order of first appearance.

    Prompts are JSON inside the message content; id-only lists inside them compare as sets.
    """
    text = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    order: list[str] = []

    def swap(match):
        value = match.group()
        if value not in order:
            order.append(value)
        return f"⟦U{order.index(value)}⟧"

    canon = json.loads(UUID.sub(swap, text))
    for message in canon.get("messages") or []:
        if isinstance(message, dict) and isinstance(message.get("content"), str):
            try:
                message["content"] = json.dumps(_id_lists_as_sets(json.loads(message["content"])),
                                                ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            except ValueError:
                pass
    return json.dumps(canon, ensure_ascii=False, sort_keys=True, separators=(",", ":")), order


def request_key(body: dict) -> tuple[str, list[str]]:
    text, order = canonical_body(body)
    return hashlib.sha256(text.encode("utf-8")).hexdigest(), order


def _to_placeholders(text: str, order: list[str]) -> str:
    return UUID.sub(lambda m: f"⟦U{order.index(m.group())}⟧" if m.group() in order else m.group(), text)


def _from_placeholders(text: str, order: list[str]) -> str:
    return PLACEHOLDER.sub(lambda m: order[int(m.group(1))] if int(m.group(1)) < len(order) else m.group(), text)


def usage_split(usage: dict | None) -> dict | None:
    """Token split from a DeepSeek usage block; None when the block is missing or malformed."""
    if not isinstance(usage, dict):
        return None
    prompt, completion = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if not isinstance(prompt, int) or not isinstance(completion, int):
        return None
    hit = usage.get("prompt_cache_hit_tokens")
    hit = hit if isinstance(hit, int) and 0 <= hit <= prompt else 0
    details = usage.get("completion_tokens_details") or {}
    reasoning = details.get("reasoning_tokens") if isinstance(details, dict) else None
    reasoning = reasoning if isinstance(reasoning, int) and 0 <= reasoning <= completion else 0
    return {"input_miss": prompt - hit, "input_hit": hit, "reasoning": reasoning, "visible_output": completion - reasoning}


class Meter:
    def __init__(self, prices: Prices = PRODUCTION_PRICES, budget_cny: float | None = None,
                 replay: str = "off", cache_dir: pathlib.Path | None = None,
                 discount_prices: Prices | None = None):
        if replay not in REPLAY_MODES:
            raise ValueError(f"replay must be one of {REPLAY_MODES}")
        self.prices = prices
        self.discount_prices = discount_prices
        self.budget_cny = budget_cny
        self.replay = replay
        self.cache_dir = pathlib.Path(cache_dir or DEFAULT_CACHE_DIR)
        self.records: list[dict] = []
        self.stop_reason: str | None = None
        self.fingerprints: list[str] = []
        self._lock = threading.Lock()
        self._in_flight = 0.0
        self._phase = "setup"
        self._target: str | None = None

    # -- scope -----------------------------------------------------------------------------
    @contextmanager
    def scope(self, phase: str, target: str | None = None):
        """Attribute dispatches to a phase ("setup" or "check") and a target until the block ends."""
        previous = self._phase, self._target
        self._phase, self._target = phase, target
        try:
            yield
        finally:
            self._phase, self._target = previous

    # -- money -----------------------------------------------------------------------------
    @property
    def spent_cny(self) -> float:
        return sum(r["cost_cny"] if r["usage_known"] else r["reserve_cny"] for r in self.records if not r["replayed"])

    def _reserve(self, body: dict) -> float:
        prompt_chars = sum(len(m.get("content") or "") for m in body.get("messages") or [] if isinstance(m, dict))
        max_output = body.get("max_tokens") or DEFAULT_MAX_OUTPUT
        return self.prices.cost(prompt_chars, 0, max_output)

    def _admit(self, reserve: float) -> None:
        with self._lock:
            if self.stop_reason:
                raise BudgetExceeded(self.stop_reason)
            if self.budget_cny is not None and self.spent_cny + self._in_flight + reserve > self.budget_cny:
                self.stop_reason = "budget_cap"
                raise BudgetExceeded("budget_cap")
            self._in_flight += reserve

    def _release(self, reserve: float) -> None:
        with self._lock:
            self._in_flight -= reserve

    # -- records ---------------------------------------------------------------------------
    def _record(self, *, body: dict, raw: dict | None, status: int | None, latency_ms: int | None,
                replayed: bool, reserve: float, error: str | None = None) -> dict:
        choice = ((raw or {}).get("choices") or [{}])[0] if isinstance(raw, dict) else {}
        split = usage_split((raw or {}).get("usage")) if isinstance(raw, dict) else None
        finish = choice.get("finish_reason") if isinstance(choice, dict) else None
        kind = _call_kind.get()
        known = split is not None
        purpose = ("unknown_usage" if not known else "length_retry" if finish == "length" else
                   "contract_repair" if kind == "review_repair" else kind)
        cost = self.prices.cost(split["input_miss"], split["input_hit"], split["reasoning"] + split["visible_output"]) if known else None
        record = {
            "phase": self._phase, "target": self._target, "kind": kind, "purpose": purpose,
            "effort": body.get("reasoning_effort") or ("disabled" if (body.get("thinking") or {}).get("type") == "disabled" else None),
            "http_status": status, "finish_reason": finish, "latency_ms": latency_ms,
            "replayed": replayed, "usage_known": known, "error": error,
            "tokens": split, "cost_cny": cost, "reserve_cny": reserve,
            "discount_cost_cny": (self.discount_prices.cost(split["input_miss"], split["input_hit"],
                                                            split["reasoning"] + split["visible_output"])
                                  if known and self.discount_prices else None),
        }
        fingerprint = (raw or {}).get("system_fingerprint") if isinstance(raw, dict) else None
        with self._lock:
            self.records.append(record)
            if fingerprint and fingerprint not in self.fingerprints:
                self.fingerprints.append(fingerprint)
        return record

    # -- cache -----------------------------------------------------------------------------
    def _cache_path(self, key: str) -> pathlib.Path:
        return self.cache_dir / key[:2] / f"{key}.json"

    def _load(self, key: str, order: list[str]) -> dict | None:
        path = self._cache_path(key)
        if not path.exists():
            return None
        stored = json.loads(path.read_text(encoding="utf-8"))
        return json.loads(_from_placeholders(json.dumps(stored["response"], ensure_ascii=False), order))

    def _store(self, key: str, order: list[str], raw: dict, latency_ms: int) -> None:
        clean = json.loads(json.dumps(raw, ensure_ascii=False))
        for choice in clean.get("choices") or []:
            if isinstance(choice, dict) and isinstance(choice.get("message"), dict):
                choice["message"].pop("reasoning_content", None)
        path = self._cache_path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        text = json.dumps({"recorded_latency_ms": latency_ms,
                           "response": json.loads(_to_placeholders(json.dumps(clean, ensure_ascii=False), order))},
                          ensure_ascii=False)
        path.write_text(text, encoding="utf-8")

    # -- transport -------------------------------------------------------------------------
    def client_factory(self):
        """Pass as DeepSeekProvider(client_factory=meter.client_factory)."""
        meter = self

        class MeteredClient(httpx.Client):
            def post(self, url, *args, json=None, **kwargs):  # noqa: A002 - httpx's own keyword
                body = json or {}
                key, order = request_key(body)
                reserve = meter._reserve(body)
                if meter.replay in ("replay", "replay_or_record"):
                    cached = meter._load(key, order)
                    if cached is not None:
                        meter._record(body=body, raw=cached, status=200, latency_ms=0, replayed=True, reserve=reserve)
                        return httpx.Response(200, json=cached, request=httpx.Request("POST", url))
                    if meter.replay == "replay":
                        meter.stop_reason = meter.stop_reason or "replay_miss"
                        raise ReplayMiss("replay_miss")
                meter._admit(reserve)
                started = time.perf_counter()
                try:
                    response = super().post(url, *args, json=json, **kwargs)
                except Exception as error:
                    meter._record(body=body, raw=None, status=None, latency_ms=int((time.perf_counter() - started) * 1000),
                                  replayed=False, reserve=reserve, error=type(error).__name__)
                    raise
                finally:
                    meter._release(reserve)
                latency = int((time.perf_counter() - started) * 1000)
                try:
                    raw = response.json()
                except ValueError:
                    raw = None
                meter._record(body=body, raw=raw if isinstance(raw, dict) else None, status=response.status_code,
                              latency_ms=latency, replayed=False, reserve=reserve,
                              error=None if response.status_code < 300 else f"http_{response.status_code}")
                if meter.replay in ("record", "replay_or_record") and response.status_code == 200 and isinstance(raw, dict):
                    meter._store(key, order, raw, latency)
                return response

        return MeteredClient(timeout=httpx.Timeout(_dispatch_timeout.get() or DeepSeekProvider.timeout_seconds), transport=TRANSPORT)

    # -- summaries -------------------------------------------------------------------------
    def summary(self, phase: str | None = None, target: str | None = None) -> dict:
        rows = [r for r in self.records if (phase is None or r["phase"] == phase) and (target is None or r["target"] == target)]
        live = [r for r in rows if not r["replayed"]]
        known = [r for r in rows if r["usage_known"]]
        tokens = {field: sum(r["tokens"][field] for r in known) for field in ("input_miss", "input_hit", "reasoning", "visible_output")}
        p = self.prices
        purposes: dict[str, dict] = {}
        for r in rows:
            entry = purposes.setdefault(r["purpose"], {"dispatches": 0, "cost_cny": 0.0})
            entry["dispatches"] += 1
            entry["cost_cny"] += r["cost_cny"] if r["usage_known"] else r["reserve_cny"]
        unknown_reserve = sum(r["reserve_cny"] for r in rows if not r["usage_known"])
        return {
            "dispatches": len(rows), "replayed_dispatches": len(rows) - len(live),
            "unknown_usage_dispatches": sum(1 for r in rows if not r["usage_known"]),
            "tokens": tokens,
            "cost_cny": {
                "input_miss": tokens["input_miss"] * p.input_miss / 1e6,
                "input_hit": tokens["input_hit"] * p.input_hit / 1e6,
                "reasoning": tokens["reasoning"] * p.output / 1e6,
                "visible_output": tokens["visible_output"] * p.output / 1e6,
                "unknown_usage_reserve": unknown_reserve,
                "total": sum(r["cost_cny"] for r in known) + unknown_reserve,
            },
            "discount_estimate_cny": (sum(r["discount_cost_cny"] for r in known) + unknown_reserve) if self.discount_prices else None,
            "by_purpose": purposes,
            "cache_hit_share": tokens["input_hit"] / (tokens["input_hit"] + tokens["input_miss"]) if known and tokens["input_hit"] + tokens["input_miss"] else None,
            "efforts": {effort: sum(1 for r in rows if r["effort"] == effort) for effort in {r["effort"] for r in rows}},
        }

    def describe(self) -> dict:
        return {"prices_cny_per_million": asdict(self.prices),
                "discount_prices_cny_per_million": asdict(self.discount_prices) if self.discount_prices else None,
                "budget_cny": self.budget_cny, "replay": self.replay, "stop_reason": self.stop_reason,
                "spent_cny": self.spent_cny, "system_fingerprints": self.fingerprints}
