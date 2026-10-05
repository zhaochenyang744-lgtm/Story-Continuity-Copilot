"""Restricted Stage 13 browser-test app. It is never imported by production startup."""

from __future__ import annotations

import hashlib
import os
from pathlib import Path
import threading
from urllib.parse import parse_qs, urlparse

from app.config import AppPaths

os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"
from app.main import create_app
from app.provider import ProviderInvalidJson, ProviderResult, ProviderTimeout
from app.stage13 import Stage13Settings
from tests.stage13_harness import validate_stage13_harness


class CaptureMailer:
    def __init__(self):
        self.messages: list[dict[str, str]] = []

    def send(self, recipient: str, purpose: str, action_url: str) -> None:
        self.messages.append({"recipient": recipient, "purpose": purpose, "action_url": action_url})


class Stage13Provider:
    label = "provider"
    model_label = "model"

    def __init__(self):
        self.calls = 0
        self.entered = threading.Event()
        self.release = threading.Event()
        self.failed_once: set[str] = set()

    @property
    def available(self):
        return True

    def evaluate(self, request):
        self.calls += 1
        if request.get("task") == "memory_initialization":
            source = request["sources"][0]
            return ProviderResult(
                {"candidates": [{"memory_type": "static_canon", "subject": "潮汐门", "predicate": "status", "value": "仅在清晨开启", "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]},
                input_tokens=40, output_tokens=20, cost_cny=None, latency_ms=10,
            )
        if request.get("task") == "memory_delta":
            source = request["sources"][0]
            return ProviderResult(
                {"candidates": [{"change_kind": "new_fact", "affected_memory_id": None, "memory_type": "open_thread", "subject": "潮汐门", "predicate": "status", "value": "等待作者确认", "invalidation_reason": None, "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]},
                input_tokens=40, output_tokens=20, cost_cny=None, latency_ms=10,
            )
        body = request["draft"]["body"]
        if "STAGE13_BLOCK" in body:
            self.release.clear()
            self.entered.set()
            if not self.release.wait(20):
                raise ProviderTimeout()
        if "STAGE13_TIMEOUT" in body:
            raise ProviderTimeout()
        if "STAGE13_FAILURE" in body:
            raise ProviderInvalidJson()
        if "STAGE13_FAIL_ONCE" in body and request["draft"]["id"] not in self.failed_once:
            self.failed_once.add(request["draft"]["id"])
            raise ProviderInvalidJson()
        return ProviderResult({"issues": []}, input_tokens=48, output_tokens=12, cost_cny=None, latency_ms=12)


harness = validate_stage13_harness()
test_root = Path(harness["test_root"])
if "story-continuity-web-demo" in str(test_root).casefold():
    raise RuntimeError("E2E_TEST_ROOT must not be inside the repository")
test_root.mkdir(parents=True, exist_ok=True)
paths = AppPaths.from_project_root(test_root, protected_poc_root=test_root / "protected-placeholder")
provider = Stage13Provider()
mailer = CaptureMailer()
settings = Stage13Settings.for_test(frontend_port=harness["frontend_port"], backend_port=harness["backend_port"])
app = create_app(paths=paths, provider=provider, settings=settings, mailer=mailer)


@app.get("/api/test/stage13/stats")
def stage13_stats():
    return {
        "provider_mode": "injected_stub",
        "provider_calls": provider.calls,
        "provider_http_calls": 0,
        "mailer_mode": "capture",
        "mailer_calls": len(mailer.messages),
        "smtp_external_calls": 0,
        "blocked": provider.entered.is_set() and not provider.release.is_set(),
    }


@app.get("/api/test/stage13/mail/{purpose}")
def stage13_mail(purpose: str):
    message = next((item for item in reversed(mailer.messages) if item["purpose"] == purpose), None)
    if not message:
        return {"available": False}
    token = parse_qs(urlparse(message["action_url"]).fragment)["token"][0]
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    with app.state.database.connection() as connection:
        active = connection.execute(
            "SELECT 1 FROM v2_recovery_tokens WHERE token_hash=? AND purpose=? AND used_at IS NULL AND revoked_at IS NULL",
            (token_hash, purpose),
        ).fetchone()
    if not active:
        return {"available": False}
    return {"available": True, "purpose": purpose, "token": token, "path": urlparse(message["action_url"]).path}


@app.post("/api/test/stage13/release")
def stage13_release():
    provider.release.set()
    return {"released": True}


@app.post("/api/test/stage13/expire/{user_id}")
def stage13_expire(user_id: str):
    with app.state.database.connection() as connection:
        changed = connection.execute("UPDATE v2_users SET visitor_expires_at='2000-01-01T00:00:00+00:00' WHERE id=? AND account_type='visitor'", (user_id,)).rowcount
    return {"changed": changed}


@app.post("/api/test/stage13/cleanup")
def stage13_cleanup():
    return app.state.stage13.cleanup_expired_visitors()


@app.get("/api/test/stage13/counts/{user_id}")
def stage13_counts(user_id: str):
    with app.state.database.connection() as connection:
        project_count = connection.execute("SELECT COUNT(*) FROM v2_projects WHERE user_id=?", (user_id,)).fetchone()[0]
        session_count = connection.execute("SELECT COUNT(*) FROM v2_sessions WHERE user_id=?", (user_id,)).fetchone()[0]
        usage_count = connection.execute("SELECT COUNT(*) FROM v2_usage_reservations WHERE user_id=?", (user_id,)).fetchone()[0]
    return {"projects": project_count, "sessions": session_count, "usage": usage_count}
