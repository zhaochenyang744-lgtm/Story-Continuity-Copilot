from __future__ import annotations

import os
import pathlib
import sqlite3
import tempfile
import threading
import time
import unittest
import uuid
from dataclasses import replace
from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import COOKIE, create_app
from app.provider import ProviderResult
from app.stage13 import SmtpMailer, Stage13Settings
from tests.stage13_harness import validate_stage13_harness


class CaptureMailer:
    def __init__(self, fail: bool = False, delay: float = 0.0):
        self.fail = fail
        self.delay = delay
        self.messages: list[dict[str, str]] = []
        self.completed = threading.Event()

    def send(self, recipient: str, purpose: str, action_url: str) -> None:
        self.messages.append({"recipient": recipient, "purpose": purpose, "action_url": action_url})
        if self.delay:
            time.sleep(self.delay)
        self.completed.set()
        if self.fail:
            raise RuntimeError("capture_failure")

    def token(self, purpose: str) -> str:
        deadline = time.monotonic() + 3
        url = None
        while time.monotonic() < deadline:
            url = next((item["action_url"] for item in reversed(self.messages) if item["purpose"] == purpose), None)
            if url:
                break
            time.sleep(0.01)
        if not url:
            raise AssertionError(f"missing captured {purpose} message")
        return parse_qs(urlparse(url).fragment)["token"][0]


class CountingProvider:
    label = "stage13-injected-provider"
    model_label = "stage13-injected-model"
    available = True

    def __init__(self):
        self.calls = 0

    def evaluate(self, request):
        self.calls += 1
        return ProviderResult({"issues": []}, input_tokens=20, output_tokens=5, cost_cny=None, latency_ms=5)


def auth_headers() -> dict[str, str]:
    return {"Origin": "http://testserver"}


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4()), **auth_headers()}


class Stage13PublicAppTests(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-unit-"))
        self.paths = AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected")
        self.mailer = CaptureMailer()
        self.provider = CountingProvider()
        self.settings = Stage13Settings.for_test()
        self.app = create_app(self.paths, provider=self.provider, executor=lambda fn, *args: fn(*args), settings=self.settings, mailer=self.mailer)
        self.client = TestClient(self.app)

    def register(self, account: str = "stage13implregistered", email: str = "writer@example.test", password: str = "valid-password-13"):
        return self.client.post(
            "/api/auth/register",
            headers=idem(),
            json={"account_name": account, "display_name": "Stage 13", "password": password, "recovery_email": email},
        )

    def visitor(self, client: TestClient | None = None):
        return (client or self.client).post("/api/auth/visitor", headers=auth_headers())

    @staticmethod
    def public_env() -> dict[str, str]:
        return {
            "PUBLIC_APP_MODE": "1", "PUBLIC_BASE_URL": "https://story.example", "BACKEND_ORIGIN": "http://127.0.0.1:8080",
            "TRUSTED_HOSTS": "127.0.0.1:8080", "TRUSTED_ORIGINS": "https://story.example",
            "CONTINUITY_PROVIDER": "deepseek", "CONTINUITY_MODEL": "deepseek-v4-pro", "CONTINUITY_API_KEY": "server-only-key",
            "CONTINUITY_BASE_URL": "https://api.example.test/chat/completions", "CONTINUITY_INPUT_CNY_PER_MILLION": "1",
            "CONTINUITY_OUTPUT_CNY_PER_MILLION": "2", "SMTP_HOST": "smtp.example.test", "SMTP_PORT": "587", "SMTP_TLS": "1",
            "SMTP_USERNAME": "server-user", "SMTP_PASSWORD": "server-password", "SMTP_FROM": "security@example.test",
            "PUBLIC_RESET_BASE_URL": "https://story.example", "RECOVERY_HASH_SECRET": "x" * 40,
            "WEB_CONCURRENCY": "1", "SINGLE_INSTANCE": "1", "SQLITE_PERSISTENT_VOLUME": "1",
        }

    def test_public_config_cookie_headers_readiness_and_secret_fail_closed(self):
        for value, code in ((None, "public_app_mode_required"), ("", "public_app_mode_invalid"), ("yes", "public_app_mode_invalid")):
            env = {} if value is None else {"PUBLIC_APP_MODE": value}
            with patch.dict(os.environ, env, clear=True), self.assertRaisesRegex(RuntimeError, code):
                Stage13Settings.from_env()
        public_env = self.public_env()
        for missing in ("PUBLIC_BASE_URL", "BACKEND_ORIGIN", "TRUSTED_HOSTS", "TRUSTED_ORIGINS", "WEB_CONCURRENCY", "SINGLE_INSTANCE", "SQLITE_PERSISTENT_VOLUME"):
            invalid = {name: value for name, value in public_env.items() if name != missing}
            with patch.dict(os.environ, invalid, clear=True), self.assertRaises(RuntimeError, msg=missing):
                Stage13Settings.from_env()
        for name, value in (("TRUSTED_HOSTS", "127.0.0.1:8080,testserver"), ("TRUSTED_ORIGINS", "https://story.example,http://testserver"), ("SMTP_TLS", "0")):
            invalid = {**public_env, name: value}
            with patch.dict(os.environ, invalid, clear=True), self.assertRaises(RuntimeError, msg=name):
                Stage13Settings.from_env()
        local_env = {
            "PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3080", "BACKEND_ORIGIN": "http://127.0.0.1:8080",
            "TRUSTED_HOSTS": "127.0.0.1:8080", "TRUSTED_ORIGINS": "http://127.0.0.1:3080",
        }
        with patch.dict(os.environ, local_env, clear=True):
            self.assertFalse(Stage13Settings.from_env().public_app_mode)
        for missing in ("PUBLIC_BASE_URL", "BACKEND_ORIGIN", "TRUSTED_HOSTS", "TRUSTED_ORIGINS"):
            invalid = {name: value for name, value in local_env.items() if name != missing}
            with patch.dict(os.environ, invalid, clear=True), self.assertRaisesRegex(RuntimeError, "public_config_required"):
                Stage13Settings.from_env()
        with self.assertRaisesRegex(RuntimeError, "smtp_starttls_required"):
            SmtpMailer(replace(self.settings, smtp_host="smtp.example.test", smtp_port=587, smtp_username="user", smtp_password="password", smtp_from="security@example.test", smtp_tls=False))
        with patch.dict(os.environ, public_env, clear=True):
            configured = Stage13Settings.from_env()
        self.assertTrue(configured.public_app_mode)
        self.assertTrue(configured.cookie_secure)
        response = self.visitor()
        self.assertEqual(response.status_code, 201)
        cookie = response.headers["set-cookie"]
        self.assertIn("HttpOnly", cookie)
        self.assertIn("SameSite=lax", cookie)
        self.assertNotIn("scc_local_session", response.text)
        self.assertEqual(response.headers["x-content-type-options"], "nosniff")
        self.assertEqual(response.headers["referrer-policy"], "no-referrer")
        self.assertIn("default-src 'none'", response.headers["content-security-policy"])
        ready = self.client.get("/readiness")
        self.assertEqual(set(ready.json()), {"status", "capabilities", "security_error_code"})
        self.assertNotIn(str(self.paths.database_path), ready.text)
        public_root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-public-"))
        public_settings = replace(
            self.settings, public_app_mode=True, public_base_url="https://testserver", trusted_hosts=("testserver",),
            trusted_origins=("https://testserver",), cookie_secure=True,
        )
        public_app = create_app(AppPaths.from_project_root(public_root, protected_poc_root=public_root / "protected"), provider=CountingProvider(), settings=public_settings, mailer=CaptureMailer())
        public_client = TestClient(public_app, base_url="https://testserver")
        self.assertEqual(public_client.post("/api/auth/visitor").json()["error"]["code"], "cross_site_request_rejected")
        public_response = public_client.post("/api/auth/visitor", headers={"Origin": "https://testserver"})
        self.assertIn("Secure", public_response.headers["set-cookie"])
        self.assertIn("max-age=63072000", public_response.headers["strict-transport-security"])

    def test_impl_and_pm3_harness_profiles_are_exact_and_cross_values_fail_closed(self):
        for profile, frontend_port, backend_port, marker, account, dist in (
            ("impl", 3080, 8080, "story-stage13-impl-", "stage13implunit", ".next-stage13-impl"),
            ("pm3", 3081, 8081, "story-stage13-pm3-", "stage13pm3unit", ".next-stage13-pm3"),
            ("v4impl", 3084, 8084, "story-stage13-v4-impl-", "stage13v4implunit", ".next-stage13-v4-impl"),
            ("v4pm3", 3085, 8085, "story-stage13-v4-pm3-", "stage13v4pm3unit", ".next-stage13-v4-pm3"),
        ):
            root = pathlib.Path(tempfile.gettempdir()) / f"{marker}unit-profile"
            env = {
                "STAGE13_HARNESS_PROFILE": profile, "E2E_BASE_URL": f"http://127.0.0.1:{frontend_port}",
                "E2E_BACKEND_ORIGIN": f"http://127.0.0.1:{backend_port}", "BACKEND_ORIGIN": f"http://127.0.0.1:{backend_port}",
                "PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": f"http://127.0.0.1:{frontend_port}", "NEXT_DIST_DIR": dist,
                "E2E_ACCOUNT_PREFIX": account, "E2E_TEST_ROOT": str(root), "E2E_OUTPUT_DIR": str(root / "playwright"),
            }
            self.assertEqual(validate_stage13_harness(env)["backend_port"], backend_port)
            for name, value in (("E2E_BASE_URL", "http://127.0.0.1:3999"), ("NEXT_DIST_DIR", ".next-other"), ("E2E_ACCOUNT_PREFIX", "stage13wrong")):
                with self.assertRaises(RuntimeError, msg=f"{profile}:{name}"):
                    validate_stage13_harness({**env, name: value})

    def test_visitor_identity_isolation_text_limits_expiry_and_atomic_cleanup(self):
        first = self.visitor()
        self.assertEqual(first.status_code, 201)
        first_user = first.json()["data"]["user"]
        self.assertEqual(first_user["account_type"], "visitor")
        self.assertEqual(len(first.json()["data"]["seeded_projects"]), 3)
        replay = self.visitor()
        self.assertEqual(replay.json()["data"]["user"]["id"], first_user["id"])
        other_client = TestClient(self.app)
        other = self.visitor(other_client)
        self.assertNotEqual(other.json()["data"]["user"]["id"], first_user["id"])
        foreign_project = other.json()["data"]["seeded_projects"][0]["id"]
        self.assertEqual(self.client.get(f"/api/projects/{foreign_project}").status_code, 404)
        too_large = ("界" * 50_001).encode("utf-8")
        rejected = self.client.post("/api/imports/preview", headers=idem(), files={"file": ("large.md", too_large, "text/markdown")})
        self.assertEqual((rejected.status_code, rejected.json()["error"]["code"]), (413, "import_too_large"))
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_import_drafts WHERE user_id=?", (first_user["id"],)).fetchone()[0], 0)
            c.execute("UPDATE v2_users SET visitor_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (first_user["id"],))
        self.assertEqual(self.client.get("/api/home").status_code, 401)
        preserved_before = other_client.get("/api/projects").json()["data"]["projects"]
        cleaned = self.app.state.stage13.cleanup_expired_visitors()
        self.assertEqual(cleaned["visitor_count"], 1)
        self.assertNotIn(first_user["id"], str(cleaned))
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_users WHERE id=?", (first_user["id"],)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_projects WHERE user_id=?", (first_user["id"],)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_usage_reservations WHERE user_id=?", (first_user["id"],)).fetchone()[0], 0)
        self.assertEqual(other_client.get("/api/projects").json()["data"]["projects"], preserved_before)

    def test_recovery_verify_enumeration_reset_replay_concurrency_and_session_revocation(self):
        registered = self.register()
        self.assertEqual(registered.status_code, 201)
        payload_text = registered.text
        self.assertNotIn("writer@example.test", payload_text)
        verify_token = self.mailer.token("verify_email")
        database_bytes = self.paths.database_path.read_bytes()
        self.assertNotIn(verify_token.encode(), database_bytes)
        self.assertNotIn(b"writer@example.test", database_bytes)
        with self.app.state.database.connection() as c:
            verify_expiry = c.execute("SELECT expires_at FROM v2_recovery_tokens WHERE purpose='verify_email' ORDER BY created_at DESC LIMIT 1").fetchone()[0]
        self.assertLessEqual((datetime.fromisoformat(verify_expiry) - datetime.now(timezone.utc)).total_seconds(), 30 * 60)
        purpose_drift = TestClient(self.app).post("/api/auth/password-reset/confirm", headers=auth_headers(), json={"token": verify_token, "password": "new-valid-password-13"})
        self.assertEqual((purpose_drift.status_code, purpose_drift.json()["error"]["code"]), (400, "recovery_token_invalid"))
        verified = self.client.post("/api/auth/recovery-email/verify", headers=auth_headers(), json={"token": verify_token})
        self.assertEqual(verified.status_code, 200)
        old_cookie = self.client.cookies.get(COOKIE)
        unknown = TestClient(self.app).post("/api/auth/password-reset/request", headers=auth_headers(), json={"recovery_email": "missing@example.test"})
        known = TestClient(self.app).post("/api/auth/password-reset/request", headers=auth_headers(), json={"recovery_email": "writer@example.test"})
        self.assertEqual((unknown.status_code, unknown.json()["data"]), (202, {"accepted": True}))
        self.assertEqual((known.status_code, known.json()["data"]), (202, {"accepted": True}))
        reset_token = self.mailer.token("password_reset")
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with self.app.state.database.connection() as c:
                reset_row = c.execute("SELECT expires_at,revoked_at FROM v2_recovery_tokens WHERE purpose='password_reset' ORDER BY created_at DESC LIMIT 1").fetchone()
            if reset_row and reset_row["revoked_at"] is None:
                break
            time.sleep(0.01)
        self.assertIsNotNone(reset_row)
        self.assertIsNone(reset_row["revoked_at"])
        reset_expiry = reset_row["expires_at"]
        self.assertLessEqual((datetime.fromisoformat(reset_expiry) - datetime.now(timezone.utc)).total_seconds(), 15 * 60)
        barrier = threading.Barrier(2)
        results: list[int] = []

        def confirm():
            client = TestClient(self.app)
            barrier.wait()
            response = client.post("/api/auth/password-reset/confirm", headers=auth_headers(), json={"token": reset_token, "password": "new-valid-password-13"})
            results.append(response.status_code)

        threads = [threading.Thread(target=confirm) for _ in range(2)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(sorted(results), [200, 400])
        old_session = TestClient(self.app)
        old_session.cookies.set(COOKIE, old_cookie)
        self.assertEqual(old_session.get("/api/home").status_code, 401)
        self.assertEqual(TestClient(self.app).post("/api/auth/login", headers=auth_headers(), json={"account_name": "stage13implregistered", "password": "valid-password-13"}).status_code, 401)
        self.assertEqual(TestClient(self.app).post("/api/auth/login", headers=auth_headers(), json={"account_name": "stage13implregistered", "password": "new-valid-password-13"}).status_code, 200)
        replay = TestClient(self.app).post("/api/auth/password-reset/confirm", headers=auth_headers(), json={"token": reset_token, "password": "another-valid-password-13"})
        self.assertEqual((replay.status_code, replay.json()["error"]["code"]), (400, "recovery_token_invalid"))

    def test_registration_idempotency_replay_does_not_resend_or_issue_another_token(self):
        replay_key = str(uuid.uuid4())
        payload = {"account_name": "stage13implidem", "display_name": "Idempotent Author", "password": "valid-password-13", "recovery_email": "idem@example.test"}
        first = self.client.post("/api/auth/register", headers={**auth_headers(), "Idempotency-Key": replay_key}, json=payload)
        self.assertEqual(first.status_code, 201)
        first_data = first.json()["data"]
        message_count = len(self.mailer.messages)
        with self.app.state.database.connection() as c:
            token_count = c.execute("SELECT COUNT(*) FROM v2_recovery_tokens WHERE user_id=? AND purpose='verify_email'", (first_data["user"]["id"],)).fetchone()[0]
        replay = self.client.post("/api/auth/register", headers={**auth_headers(), "Idempotency-Key": replay_key}, json=payload)
        self.assertEqual(replay.status_code, 201)
        replay_data = replay.json()["data"]
        for field in ("user", "seeded_projects", "recovery_email_delivery"):
            self.assertEqual(replay_data[field], first_data[field])
        self.assertEqual(len(self.mailer.messages), message_count)
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_recovery_tokens WHERE user_id=? AND purpose='verify_email'", (first_data["user"]["id"],)).fetchone()[0], token_count)

    def test_reset_request_smtp_failure_is_enumeration_safe_time_bounded_and_leaves_no_usable_token(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-resetfail-"))
        good_mailer = CaptureMailer()
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=CountingProvider(), settings=self.settings, mailer=good_mailer)
        client = TestClient(app)
        for account, email in (("stage13implunverified", "unverified@example.test"), ("stage13implverified", "verified@example.test")):
            response = client.post(
                "/api/auth/register", headers={**auth_headers(), "Idempotency-Key": str(uuid.uuid4())},
                json={"account_name": account, "display_name": account, "password": "valid-password-13", "recovery_email": email},
            )
            self.assertEqual(response.status_code, 201)
        verify_token = good_mailer.token("verify_email")
        self.assertEqual(client.post("/api/auth/recovery-email/verify", headers=auth_headers(), json={"token": verify_token}).status_code, 200)
        failing_mailer = CaptureMailer(fail=True, delay=0.25)
        app.state.stage13.mailer = failing_mailer
        responses = []
        durations = []
        for email in ("unknown-reset@example.test", "unverified@example.test", "verified@example.test"):
            started = time.monotonic()
            response = client.post("/api/auth/password-reset/request", headers=auth_headers(), json={"recovery_email": email})
            durations.append(time.monotonic() - started)
            responses.append(response)
        self.assertEqual([(response.status_code, response.json()["data"]) for response in responses], [(202, {"accepted": True})] * 3)
        self.assertLess(max(durations) - min(durations), 0.12)
        self.assertLess(max(durations), 0.20)
        raw_token = failing_mailer.token("password_reset")
        self.assertTrue(failing_mailer.completed.wait(2))
        deadline = time.monotonic() + 2
        while time.monotonic() < deadline:
            with app.state.database.connection() as c:
                usable = c.execute("SELECT COUNT(*) FROM v2_recovery_tokens WHERE purpose='password_reset' AND used_at IS NULL AND revoked_at IS NULL").fetchone()[0]
            if usable == 0:
                break
            time.sleep(0.01)
        self.assertEqual(usable, 0)
        rejected = client.post("/api/auth/password-reset/confirm", headers=auth_headers(), json={"token": raw_token, "password": "new-valid-password-13"})
        self.assertEqual((rejected.status_code, rejected.json()["error"]["code"]), (400, "recovery_token_invalid"))

    def test_mail_failure_revokes_token_and_resend_rate_limit_is_stable(self):
        failing_root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-mailfail-"))
        failing_app = create_app(
            AppPaths.from_project_root(failing_root, protected_poc_root=failing_root / "protected"),
            provider=CountingProvider(), executor=lambda fn, *args: fn(*args), settings=self.settings, mailer=CaptureMailer(fail=True),
        )
        failing = TestClient(failing_app)
        response = failing.post("/api/auth/register", headers=idem(), json={"account_name": "stage13implmailfail", "display_name": "Mail Fail", "password": "valid-password-13", "recovery_email": "mailfail@example.test"})
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()["data"]["recovery_email_delivery"], "failed")
        with failing_app.state.database.connection() as c:
            usable = c.execute("SELECT COUNT(*) FROM v2_recovery_tokens WHERE used_at IS NULL AND revoked_at IS NULL").fetchone()[0]
        self.assertEqual(usable, 0)
        self.assertEqual(self.register("stage13implrate", "rate@example.test").status_code, 201)
        limited = self.client.post("/api/auth/recovery-email/resend", headers=auth_headers(), json={"recovery_email": "rate@example.test"})
        self.assertEqual((limited.status_code, limited.json()["error"]["code"]), (429, "recovery_rate_limited"))

    def test_usage_workflow_provider_attempt_budget_and_concurrency_guards(self):
        created = self.visitor().json()["data"]
        project_id = created["seeded_projects"][0]["id"]
        project = self.client.get(f"/api/projects/{project_id}").json()["data"]
        draft = self.client.get(f"/api/projects/{project_id}/drafts/{project['current_draft']['id']}").json()["data"]
        before_calls = self.provider.calls
        for _ in range(3):
            response = self.client.post(
                f"/api/projects/{project_id}/checks", headers=idem(),
                json={"draft_id": draft["id"], "draft_revision": draft["revision"]},
            )
            self.assertEqual(response.status_code, 202)
        with self.app.state.database.connection() as c:
            issues_before = c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=?", (project_id,)).fetchone()[0]
        fourth = self.client.post(
            f"/api/projects/{project_id}/checks", headers=idem(),
            json={"draft_id": draft["id"], "draft_revision": draft["revision"]},
        )
        self.assertEqual((fourth.status_code, fourth.json()["error"]["code"]), (429, "workflow_quota_exceeded"))
        self.assertEqual(self.provider.calls - before_calls, 3)
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_issues WHERE project_id=?", (project_id,)).fetchone()[0], issues_before)
            failed = c.execute("SELECT status,error_code FROM v2_runs WHERE project_id=? ORDER BY created_at DESC LIMIT 1", (project_id,)).fetchone()
        self.assertEqual(tuple(failed), ("failed", "workflow_quota_exceeded"))

        concurrency_root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-concurrency-"))
        concurrency_settings = replace(self.settings, visitor_workflows=3)
        concurrency_app = create_app(AppPaths.from_project_root(concurrency_root, protected_poc_root=concurrency_root / "protected"), provider=CountingProvider(), settings=concurrency_settings, mailer=CaptureMailer())
        visitor = TestClient(concurrency_app).post("/api/auth/visitor", headers=auth_headers()).json()["data"]["user"]
        successes: list[str] = []
        failures: list[str] = []
        barrier = threading.Barrier(4)

        def reserve():
            barrier.wait()
            try:
                successes.append(concurrency_app.state.stage13.reserve_workflow(visitor["id"], None, "concurrent"))
            except Exception as error:
                failures.append(getattr(error, "code", type(error).__name__))

        workers = [threading.Thread(target=reserve) for _ in range(4)]
        for worker in workers:
            worker.start()
        for worker in workers:
            worker.join()
        self.assertEqual((len(successes), failures), (3, ["workflow_quota_exceeded"]))

    def test_provider_attempt_budget_registered_text_and_draft_limits_fail_before_partial_writes(self):
        attempt_root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-attempt-"))
        attempt_provider = CountingProvider()
        attempt_settings = replace(self.settings, visitor_workflows=5, visitor_provider_attempts=2)
        attempt_app = create_app(AppPaths.from_project_root(attempt_root, protected_poc_root=attempt_root / "protected"), provider=attempt_provider, executor=lambda fn, *args: fn(*args), settings=attempt_settings, mailer=CaptureMailer())
        attempt_client = TestClient(attempt_app)
        visitor_data = attempt_client.post("/api/auth/visitor", headers=auth_headers()).json()["data"]
        project_id = visitor_data["seeded_projects"][0]["id"]
        project = attempt_client.get(f"/api/projects/{project_id}").json()["data"]
        draft = attempt_client.get(f"/api/projects/{project_id}/drafts/{project['current_draft']['id']}").json()["data"]
        run_ids = []
        for _ in range(3):
            response = attempt_client.post(f"/api/projects/{project_id}/checks", headers=idem(), json={"draft_id": draft["id"], "draft_revision": draft["revision"]})
            self.assertEqual(response.status_code, 202)
            run_ids.append(response.json()["data"]["run_id"])
        third = attempt_client.get(f"/api/projects/{project_id}/checks/{run_ids[-1]}").json()["data"]
        self.assertEqual((third["status"], third["error_code"], attempt_provider.calls), ("failed", "provider_attempt_quota_exceeded", 2))

        budget_root = pathlib.Path(tempfile.mkdtemp(prefix="story-stage13-impl-budget-"))
        budget_provider = CountingProvider()
        budget_settings = replace(self.settings, visitor_workflows=5, visitor_budget_cny=0.019)
        budget_app = create_app(AppPaths.from_project_root(budget_root, protected_poc_root=budget_root / "protected"), provider=budget_provider, executor=lambda fn, *args: fn(*args), settings=budget_settings, mailer=CaptureMailer())
        budget_client = TestClient(budget_app)
        budget_visitor = budget_client.post("/api/auth/visitor", headers=auth_headers()).json()["data"]
        budget_project = budget_visitor["seeded_projects"][0]["id"]
        budget_draft = budget_client.get(f"/api/projects/{budget_project}").json()["data"]["current_draft"]
        first = budget_client.post(f"/api/projects/{budget_project}/checks", headers=idem(), json={"draft_id": budget_draft["id"], "draft_revision": budget_draft["revision"]})
        self.assertEqual(first.status_code, 202)
        second = budget_client.post(f"/api/projects/{budget_project}/checks", headers=idem(), json={"draft_id": budget_draft["id"], "draft_revision": budget_draft["revision"]})
        self.assertEqual((second.status_code, second.json()["error"]["code"], budget_provider.calls), (429, "server_budget_exceeded", 1))

        registered = self.register("stage13impllimits", "limits@example.test")
        self.assertEqual(registered.status_code, 201)
        oversized = ("文" * 350_001).encode("utf-8")
        rejected = self.client.post("/api/imports/preview", headers=idem(), files={"file": ("registered.md", oversized, "text/markdown")})
        self.assertEqual((rejected.status_code, rejected.json()["error"]["code"]), (413, "import_too_large"))
        own_project = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        own = self.client.get(f"/api/projects/{own_project}").json()["data"]
        rejected_draft = self.client.patch(
            f"/api/projects/{own_project}/drafts/{own['current_draft']['id']}", headers=idem(),
            json={"base_revision": own["current_draft"]["revision"], "body": "章" * 30_001},
        )
        self.assertEqual((rejected_draft.status_code, rejected_draft.json()["error"]["code"]), (413, "draft_too_large"))
        with self.app.state.database.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_import_drafts WHERE user_id=?", (registered.json()["data"]["user"]["id"],)).fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
