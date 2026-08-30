from __future__ import annotations

import hashlib
import hmac
import ipaddress
import math
import os
import re
import secrets
import smtplib
import time
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from typing import Any, Iterator, Protocol
from urllib.parse import urlparse

from .database import DomainError


def _canonical_origin(value: str, *, https_only: bool = False) -> str:
    try:
        parsed = urlparse(value)
    except ValueError as error:
        raise RuntimeError("public_config_invalid") from error
    if (
        parsed.scheme not in ({"https"} if https_only else {"http", "https"})
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.path not in {"", "/"}
        or parsed.params
        or parsed.query
        or parsed.fragment
        or value != f"{parsed.scheme}://{parsed.netloc}"
    ):
        raise RuntimeError("public_config_invalid")
    return value


def _positive_int(value: str | None, default: int, *, minimum: int, maximum: int) -> int:
    try:
        parsed = default if value is None else int(value)
    except ValueError as error:
        raise RuntimeError("public_config_invalid") from error
    if not minimum <= parsed <= maximum:
        raise RuntimeError("public_config_invalid")
    return parsed


def _nonnegative_rate(value: str | None, *, required: bool) -> float | None:
    if value is None or value == "":
        if required:
            raise RuntimeError("budget_rates_required")
        return None
    try:
        parsed = float(value)
    except ValueError as error:
        raise RuntimeError("budget_rates_invalid") from error
    if parsed < 0 or parsed != parsed or parsed == float("inf"):
        raise RuntimeError("budget_rates_invalid")
    return parsed


@dataclass(frozen=True)
class Stage13Settings:
    public_app_mode: bool
    public_base_url: str
    backend_origin: str
    trusted_hosts: tuple[str, ...]
    trusted_origins: tuple[str, ...]
    cookie_secure: bool
    visitor_ttl_hours: int
    cleanup_interval_seconds: int
    visitor_workflows: int
    registered_workflows: int
    visitor_provider_attempts: int
    registered_provider_attempts: int
    visitor_budget_cny: float
    registered_budget_cny: float
    input_cny_per_million: float | None
    output_cny_per_million: float | None
    recovery_hash_secret: bytes
    reset_base_url: str | None
    smtp_host: str | None = None
    smtp_port: int | None = None
    smtp_tls: bool = True
    smtp_username: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None
    require_recovery_email: bool = False
    test_mode: bool = False

    @classmethod
    def from_env(cls) -> "Stage13Settings":
        raw_mode = os.environ.get("PUBLIC_APP_MODE")
        if raw_mode is None:
            raise RuntimeError("public_app_mode_required")
        if raw_mode not in {"0", "1"}:
            raise RuntimeError("public_app_mode_invalid")
        public = raw_mode == "1"
        public_base = os.environ.get("PUBLIC_BASE_URL")
        backend = os.environ.get("BACKEND_ORIGIN")
        trusted_hosts_value = os.environ.get("TRUSTED_HOSTS")
        trusted_origins_value = os.environ.get("TRUSTED_ORIGINS")
        if not public_base or not backend or not trusted_hosts_value or not trusted_origins_value:
            raise RuntimeError("public_config_required")
        _canonical_origin(public_base, https_only=public)
        _canonical_origin(backend)
        parsed_backend = urlparse(backend)
        parsed_public = urlparse(public_base)
        if public:
            try:
                backend_ip = ipaddress.ip_address(str(parsed_backend.hostname))
                backend_private = backend_ip.is_private or backend_ip.is_loopback
            except ValueError:
                hostname = str(parsed_backend.hostname).casefold()
                backend_private = "." not in hostname or hostname.endswith((".internal", ".local"))
            if not backend_private:
                raise RuntimeError("backend_origin_not_private")
        if not public and (
            parsed_public.hostname != "127.0.0.1"
            or parsed_backend.hostname != "127.0.0.1"
            or parsed_public.port is None
            or parsed_backend.port is None
        ):
            raise RuntimeError("local_origin_invalid")
        trusted_hosts = tuple(
            item.strip().casefold()
            for item in trusted_hosts_value.split(",")
            if item.strip()
        )
        trusted_origins = tuple(
            item.strip()
            for item in trusted_origins_value.split(",")
            if item.strip()
        )
        if (
            not trusted_hosts
            or not trusted_origins
            or len(trusted_hosts) != len(set(trusted_hosts))
            or len(trusted_origins) != len(set(trusted_origins))
            or any("*" in item for item in (*trusted_hosts, *trusted_origins))
            or (public and ("testserver" in trusted_hosts or "http://testserver" in trusted_origins))
        ):
            raise RuntimeError("trusted_boundary_invalid")
        for host in trusted_hosts:
            try:
                parsed_host = urlparse(f"http://{host}")
                valid_host = (
                    parsed_host.hostname is not None
                    and parsed_host.username is None
                    and parsed_host.password is None
                    and parsed_host.path == ""
                    and parsed_host.params == ""
                    and parsed_host.query == ""
                    and parsed_host.fragment == ""
                    and parsed_host.netloc.casefold() == host
                )
                _ = parsed_host.port
            except ValueError:
                valid_host = False
            if not valid_host:
                raise RuntimeError("trusted_boundary_invalid")
        for origin in trusted_origins:
            _canonical_origin(origin, https_only=public)
        input_rate = _nonnegative_rate(os.environ.get("CONTINUITY_INPUT_CNY_PER_MILLION"), required=public)
        output_rate = _nonnegative_rate(os.environ.get("CONTINUITY_OUTPUT_CNY_PER_MILLION"), required=public)
        secret = os.environ.get("RECOVERY_HASH_SECRET", "")
        reset_base = os.environ.get("PUBLIC_RESET_BASE_URL")
        smtp_port_value = os.environ.get("SMTP_PORT")
        if public:
            required = {
                "CONTINUITY_API_KEY": os.environ.get("CONTINUITY_API_KEY"),
                "CONTINUITY_BASE_URL": os.environ.get("CONTINUITY_BASE_URL"),
                "SMTP_HOST": os.environ.get("SMTP_HOST"),
                "SMTP_PORT": smtp_port_value,
                "SMTP_TLS": os.environ.get("SMTP_TLS"),
                "SMTP_USERNAME": os.environ.get("SMTP_USERNAME"),
                "SMTP_PASSWORD": os.environ.get("SMTP_PASSWORD"),
                "SMTP_FROM": os.environ.get("SMTP_FROM"),
                "PUBLIC_RESET_BASE_URL": reset_base,
                "RECOVERY_HASH_SECRET": secret,
            }
            if any(not value for value in required.values()):
                raise RuntimeError("public_secrets_required")
            if os.environ.get("CONTINUITY_PROVIDER") != "deepseek" or os.environ.get("CONTINUITY_MODEL") != "deepseek-v4-pro":
                raise RuntimeError("provider_config_invalid")
            provider_url = urlparse(str(required["CONTINUITY_BASE_URL"]))
            if provider_url.scheme != "https" or not provider_url.hostname or provider_url.username or provider_url.password:
                raise RuntimeError("provider_config_invalid")
            if len(secret.encode("utf-8")) < 32:
                raise RuntimeError("recovery_secret_invalid")
            _canonical_origin(str(reset_base), https_only=True)
            if reset_base != public_base:
                raise RuntimeError("reset_base_url_invalid")
            if os.environ.get("SMTP_TLS") != "1":
                raise RuntimeError("smtp_config_invalid")
            normalize_email(str(required["SMTP_FROM"]))
            if os.environ.get("WEB_CONCURRENCY") != "1" or os.environ.get("SINGLE_INSTANCE") != "1" or os.environ.get("SQLITE_PERSISTENT_VOLUME") != "1":
                raise RuntimeError("deployment_contract_invalid")
        if not secret:
            # Local-only deterministic isolation key. Public mode never reaches this branch.
            secret = "story-continuity-local-stage13-isolation"
        try:
            smtp_port = int(smtp_port_value) if smtp_port_value else None
        except ValueError as error:
            raise RuntimeError("smtp_config_invalid") from error
        if smtp_port is not None and not 1 <= smtp_port <= 65535:
            raise RuntimeError("smtp_config_invalid")
        visitor_budget = float(os.environ.get("VISITOR_BUDGET_CNY", "1.00"))
        registered_budget = float(os.environ.get("REGISTERED_BUDGET_CNY", "10.00"))
        if not all(math.isfinite(value) and value >= 0 for value in (visitor_budget, registered_budget)):
            raise RuntimeError("budget_limits_invalid")
        return cls(
            public_app_mode=public,
            public_base_url=public_base,
            backend_origin=backend,
            trusted_hosts=trusted_hosts,
            trusted_origins=trusted_origins,
            cookie_secure=public,
            visitor_ttl_hours=_positive_int(os.environ.get("VISITOR_TTL_HOURS"), 24, minimum=1, maximum=168),
            cleanup_interval_seconds=_positive_int(os.environ.get("VISITOR_CLEANUP_INTERVAL_SECONDS"), 900, minimum=60, maximum=900),
            visitor_workflows=_positive_int(os.environ.get("VISITOR_WORKFLOWS_24H"), 3, minimum=1, maximum=1000),
            registered_workflows=_positive_int(os.environ.get("REGISTERED_WORKFLOWS_24H"), 20, minimum=1, maximum=10000),
            visitor_provider_attempts=_positive_int(os.environ.get("VISITOR_PROVIDER_ATTEMPTS_24H"), 30, minimum=1, maximum=10000),
            registered_provider_attempts=_positive_int(os.environ.get("REGISTERED_PROVIDER_ATTEMPTS_24H"), 120, minimum=1, maximum=100000),
            visitor_budget_cny=visitor_budget,
            registered_budget_cny=registered_budget,
            input_cny_per_million=0.0 if input_rate is None and not public else input_rate,
            output_cny_per_million=0.0 if output_rate is None and not public else output_rate,
            recovery_hash_secret=secret.encode("utf-8"),
            reset_base_url=reset_base,
            smtp_host=os.environ.get("SMTP_HOST"),
            smtp_port=smtp_port,
            smtp_tls=os.environ.get("SMTP_TLS", "1") == "1",
            smtp_username=os.environ.get("SMTP_USERNAME"),
            smtp_password=os.environ.get("SMTP_PASSWORD"),
            smtp_from=os.environ.get("SMTP_FROM"),
            require_recovery_email=public,
        )

    @classmethod
    def for_test(cls, frontend_port: int = 3080, backend_port: int = 8080) -> "Stage13Settings":
        return cls(
            public_app_mode=False,
            public_base_url=f"http://127.0.0.1:{frontend_port}",
            backend_origin=f"http://127.0.0.1:{backend_port}",
            trusted_hosts=(f"127.0.0.1:{backend_port}", "testserver"),
            trusted_origins=(f"http://127.0.0.1:{frontend_port}", "http://testserver"),
            cookie_secure=False,
            visitor_ttl_hours=24,
            cleanup_interval_seconds=900,
            visitor_workflows=3,
            registered_workflows=20,
            visitor_provider_attempts=30,
            registered_provider_attempts=120,
            visitor_budget_cny=1.0,
            registered_budget_cny=10.0,
            input_cny_per_million=1.0,
            output_cny_per_million=2.0,
            recovery_hash_secret=b"stage13-test-only-recovery-hash-secret-32bytes",
            reset_base_url=f"http://127.0.0.1:{frontend_port}",
            require_recovery_email=True,
            test_mode=True,
        )

    def reservation_microunits(self) -> int:
        if self.input_cny_per_million is None or self.output_cny_per_million is None:
            raise DomainError("budget_rates_unavailable", 503, True)
        cny = 6000 * self.input_cny_per_million / 1_000_000 + 2000 * self.output_cny_per_million / 1_000_000
        return max(0, int(round(cny * 1_000_000)))


class MailerPort(Protocol):
    def send(self, recipient: str, purpose: str, action_url: str) -> None: ...


class UnavailableMailer:
    def send(self, recipient: str, purpose: str, action_url: str) -> None:
        raise RuntimeError("mailer_unavailable")


class SmtpMailer:
    def __init__(self, settings: Stage13Settings):
        if not all((settings.smtp_host, settings.smtp_port, settings.smtp_username, settings.smtp_password, settings.smtp_from)):
            raise RuntimeError("smtp_config_required")
        if not settings.smtp_tls:
            raise RuntimeError("smtp_starttls_required")
        self.settings = settings

    def send(self, recipient: str, purpose: str, action_url: str) -> None:
        message = EmailMessage()
        message["From"] = self.settings.smtp_from
        message["To"] = recipient
        message["Subject"] = "Story Continuity 账户安全"
        label = "验证恢复邮箱" if purpose == "verify_email" else "重置密码"
        message.set_content(f"{label}：{action_url}\n如果不是你发起的请求，请忽略此邮件。")
        with smtplib.SMTP(str(self.settings.smtp_host), int(self.settings.smtp_port), timeout=15) as client:
            if self.settings.smtp_tls:
                client.starttls()
            client.login(str(self.settings.smtp_username), str(self.settings.smtp_password))
            client.send_message(message)


def normalize_email(value: str) -> str:
    candidate = value.strip().casefold()
    if len(candidate) > 254 or candidate.count("@") != 1:
        raise DomainError("recovery_email_invalid", 422)
    local, domain = candidate.rsplit("@", 1)
    try:
        ascii_domain = domain.encode("idna").decode("ascii")
    except UnicodeError as error:
        raise DomainError("recovery_email_invalid", 422) from error
    if (
        not local
        or len(local) > 64
        or not re.fullmatch(r"[a-z0-9.!#$%&'*+/=?^_`{|}~-]+", local)
        or not re.fullmatch(r"[a-z0-9](?:[a-z0-9.-]{0,251}[a-z0-9])?", ascii_domain)
        or ".." in local
        or ".." in ascii_domain
        or "." not in ascii_domain
    ):
        raise DomainError("recovery_email_invalid", 422)
    return f"{local}@{ascii_domain}"


def masked_email(normalized: str) -> str:
    local, domain = normalized.split("@", 1)
    parts = domain.split(".")
    host = parts[0]
    suffix = ".".join(parts[1:])
    return f"{local[0]}***@{host[0]}***.{suffix}"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(kind: str) -> str:
    import uuid

    return f"{kind}-{uuid.uuid4()}"


STAGE13_SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_recovery_tokens(
  id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),purpose TEXT NOT NULL,
  token_hash TEXT NOT NULL UNIQUE,email_hash TEXT NOT NULL,expires_at TEXT NOT NULL,
  used_at TEXT,revoked_at TEXT,created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS v2_recovery_tokens_by_user ON v2_recovery_tokens(user_id,purpose,created_at);
CREATE TABLE IF NOT EXISTS v2_recovery_rate_limits(
  id TEXT PRIMARY KEY,action TEXT NOT NULL,subject_hash TEXT NOT NULL,ip_hash TEXT NOT NULL,attempted_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS v2_recovery_rate_window ON v2_recovery_rate_limits(action,subject_hash,ip_hash,attempted_at);
CREATE TABLE IF NOT EXISTS v2_usage_reservations(
  id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),project_id TEXT,
  run_id TEXT,workflow_kind TEXT NOT NULL,reserved_microunits INTEGER NOT NULL,created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS v2_usage_by_user ON v2_usage_reservations(user_id,created_at);
CREATE TABLE IF NOT EXISTS v2_provider_attempts(
  id TEXT PRIMARY KEY,user_id TEXT NOT NULL REFERENCES v2_users(id),reservation_id TEXT NOT NULL REFERENCES v2_usage_reservations(id),created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS v2_provider_attempts_by_user ON v2_provider_attempts(user_id,created_at);
CREATE TABLE IF NOT EXISTS v2_visitor_cleanup_audits(
  id TEXT PRIMARY KEY,cleaned_at TEXT NOT NULL,visitor_count INTEGER NOT NULL,visitor_hashes_json TEXT NOT NULL
);
"""

PENDING_DELIVERY = "delivery_pending"


class Stage13Service:
    def __init__(self, database: Any, settings: Stage13Settings, mailer: MailerPort):
        self.database = database
        self.settings = settings
        self.mailer = mailer
        self.initialize()

    def initialize(self) -> None:
        with self.database.connection() as c:
            user_columns = {row["name"] for row in c.execute("PRAGMA table_info(v2_users)")}
            additions = {
                "account_type": "TEXT NOT NULL DEFAULT 'registered'",
                "visitor_expires_at": "TEXT",
                "recovery_email_hash": "TEXT",
                "recovery_email_masked": "TEXT",
                "recovery_email_verified_at": "TEXT",
            }
            for name, definition in additions.items():
                if name not in user_columns:
                    c.execute(f"ALTER TABLE v2_users ADD COLUMN {name} {definition}")
            c.executescript(STAGE13_SCHEMA)
            c.execute(
                "CREATE UNIQUE INDEX IF NOT EXISTS v2_users_recovery_email_unique "
                "ON v2_users(recovery_email_hash) WHERE recovery_email_hash IS NOT NULL"
            )
            c.execute("INSERT OR IGNORE INTO schema_migrations VALUES(13,?)", (_now(),))

    def _digest(self, namespace: str, value: str) -> str:
        return hmac.new(self.settings.recovery_hash_secret, f"{namespace}:{value}".encode("utf-8"), hashlib.sha256).hexdigest()

    def email_hash(self, email: str) -> str:
        return self._digest("email", normalize_email(email))

    def ip_hash(self, ip: str) -> str:
        return self._digest("ip", ip)

    def account(self, user_id: str) -> dict[str, Any]:
        with self.database.connection() as c:
            row = c.execute(
                "SELECT id,account_name,display_name,account_type,visitor_expires_at,recovery_email_hash,recovery_email_masked,recovery_email_verified_at "
                "FROM v2_users WHERE id=?",
                (user_id,),
            ).fetchone()
            if not row:
                raise DomainError("authentication_required", 401)
            return dict(row)

    def safe_user(self, user_id: str) -> dict[str, Any]:
        row = self.account(user_id)
        return {
            "id": row["id"],
            "account_name": row["account_name"],
            "display_name": row["display_name"],
            "account_type": row["account_type"],
            "visitor_expires_at": row["visitor_expires_at"],
            "recovery_email": {
                "configured": bool(row["recovery_email_hash"]),
                "verified": bool(row["recovery_email_verified_at"]),
                "masked": row["recovery_email_masked"],
            },
        }

    def create_visitor(self, existing_token: str | None) -> dict[str, Any]:
        if existing_token:
            try:
                active = self.database.session_user(existing_token)
                profile = self.account(active["id"])
                if profile["account_type"] == "visitor":
                    return {"user": self.safe_user(active["id"]), "session": {"expires_at": active["expires_at"]}}
            except DomainError:
                pass
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            user_id = _new_id("visitor")
            account_name = f"visitor-{secrets.token_hex(16)}"
            display_name = "访客"
            password_hash = hashlib.sha256(secrets.token_bytes(32)).hexdigest()
            stamp = _now()
            expires = (datetime.now(timezone.utc) + timedelta(hours=self.settings.visitor_ttl_hours)).isoformat()
            c.execute(
                "INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at,account_type,visitor_expires_at) VALUES(?,?,?,?,?,'visitor',?)",
                (user_id, account_name, display_name, password_hash, stamp, expires),
            )
            seeded = []
            for seed_key, title, genre, summary in (
                ("grey_harbor", "灰港回声", "悬疑", "潮图修复师追查被改写的航线记录。"),
                ("paper_moon", "纸月档案", "奇幻", "档案修复员追查消失的纸月。"),
                ("zero_garden", "零点花园", "科幻", "夜班园丁记录零点开放的花。"),
            ):
                project_id = self.database._create_project(c, user_id, title, genre, summary, "demo_seed", seed_key)
                seeded.append({"id": project_id, "seed_key": seed_key, "title": title})
            raw = secrets.token_urlsafe(48)
            c.execute(
                "INSERT INTO v2_sessions VALUES(?,?,?,?,?,?)",
                (_new_id("session"), user_id, hashlib.sha256(raw.encode()).hexdigest(), expires, None, stamp),
            )
            return {
                "user": {
                    "id": user_id,
                    "account_name": account_name,
                    "display_name": display_name,
                    "account_type": "visitor",
                    "visitor_expires_at": expires,
                    "recovery_email": {"configured": False, "verified": False, "masked": None},
                },
                "session": {"expires_at": expires, "_token": raw},
                "seeded_projects": seeded,
            }

    def _rate(self, c: Any, action: str, subject_hash: str, ip_hash: str, maximum: int, minimum_seconds: int = 60) -> None:
        now = datetime.now(timezone.utc)
        cutoff = (now - timedelta(hours=1)).isoformat()
        rows = c.execute(
            "SELECT attempted_at FROM v2_recovery_rate_limits WHERE action=? AND subject_hash=? AND ip_hash=? AND attempted_at>? ORDER BY attempted_at DESC",
            (action, subject_hash, ip_hash, cutoff),
        ).fetchall()
        if len(rows) >= maximum:
            raise DomainError("recovery_rate_limited", 429, True)
        if rows and (now - datetime.fromisoformat(rows[0]["attempted_at"])).total_seconds() < minimum_seconds:
            raise DomainError("recovery_rate_limited", 429, True)
        c.execute(
            "INSERT INTO v2_recovery_rate_limits VALUES(?,?,?,?,?)",
            (_new_id("rate"), action, subject_hash, ip_hash, now.isoformat()),
        )

    def _issue_token(self, user_id: str, purpose: str, email_hash: str, minutes: int, *, delivery_pending: bool = False) -> tuple[str, str]:
        raw = secrets.token_urlsafe(48)
        token_hash = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        expires = (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()
        stamp = _now()
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute(
                "UPDATE v2_recovery_tokens SET revoked_at=? WHERE user_id=? AND purpose=? AND used_at IS NULL AND revoked_at IS NULL",
                (stamp, user_id, purpose),
            )
            c.execute(
                "INSERT INTO v2_recovery_tokens VALUES(?,?,?,?,?,?,?,?,?)",
                (_new_id("recovery"), user_id, purpose, token_hash, email_hash, expires, None, PENDING_DELIVERY if delivery_pending else None, stamp),
            )
        return raw, token_hash

    def _revoke_token_hash(self, token_hash: str) -> None:
        with self.database.connection() as c:
            c.execute("UPDATE v2_recovery_tokens SET revoked_at=? WHERE token_hash=? AND used_at IS NULL", (_now(), token_hash))

    def _activate_delivered_token(self, token_hash: str) -> bool:
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            token = c.execute(
                "SELECT id,user_id,purpose,created_at FROM v2_recovery_tokens WHERE token_hash=? AND used_at IS NULL AND revoked_at=?",
                (token_hash, PENDING_DELIVERY),
            ).fetchone()
            if not token:
                return False
            newer = c.execute(
                "SELECT 1 FROM v2_recovery_tokens WHERE user_id=? AND purpose=? AND (created_at>? OR (created_at=? AND id>?)) LIMIT 1",
                (token["user_id"], token["purpose"], token["created_at"], token["created_at"], token["id"]),
            ).fetchone()
            if newer:
                c.execute("UPDATE v2_recovery_tokens SET revoked_at=? WHERE id=?", (_now(), token["id"]))
                return False
            return c.execute(
                "UPDATE v2_recovery_tokens SET revoked_at=NULL WHERE id=? AND revoked_at=?",
                (token["id"], PENDING_DELIVERY),
            ).rowcount == 1

    def _action_url(self, purpose: str, raw: str) -> str:
        if not self.settings.reset_base_url:
            raise RuntimeError("reset_base_url_unavailable")
        path = "verify-email" if purpose == "verify_email" else "password-reset/confirm"
        return f"{self.settings.reset_base_url}/{path}#token={raw}"

    def bind_recovery_email(self, user_id: str, email: str, ip: str) -> dict[str, Any]:
        normalized = normalize_email(email)
        email_hash = self.email_hash(normalized)
        ip_hash = self.ip_hash(ip)
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            actor = c.execute("SELECT account_type FROM v2_users WHERE id=?", (user_id,)).fetchone()
            if not actor or actor["account_type"] != "registered":
                raise DomainError("recovery_email_not_available", 403)
            self._rate(c, "verify_send", email_hash, ip_hash, 3)
            if c.execute("SELECT 1 FROM v2_users WHERE recovery_email_hash=? AND id!=?", (email_hash, user_id)).fetchone():
                raise DomainError("recovery_email_unavailable", 409)
            c.execute(
                "UPDATE v2_users SET recovery_email_hash=?,recovery_email_masked=?,recovery_email_verified_at=NULL WHERE id=?",
                (email_hash, masked_email(normalized), user_id),
            )
        raw, token_hash = self._issue_token(user_id, "verify_email", email_hash, 30)
        try:
            self.mailer.send(normalized, "verify_email", self._action_url("verify_email", raw))
        except Exception as error:
            self._revoke_token_hash(token_hash)
            raise DomainError("recovery_delivery_failed", 503, True) from error
        return self.safe_user(user_id)["recovery_email"]

    def resend_verification(self, user_id: str, email: str, ip: str) -> dict[str, Any]:
        normalized = normalize_email(email)
        email_hash = self.email_hash(normalized)
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            row = c.execute("SELECT recovery_email_hash,recovery_email_verified_at FROM v2_users WHERE id=? AND account_type='registered'", (user_id,)).fetchone()
            if not row or row["recovery_email_hash"] != email_hash:
                raise DomainError("recovery_email_mismatch", 400)
            if row["recovery_email_verified_at"]:
                return {"configured": True, "verified": True}
            self._rate(c, "verify_send", email_hash, self.ip_hash(ip), 3)
        raw, token_hash = self._issue_token(user_id, "verify_email", email_hash, 30)
        try:
            self.mailer.send(normalized, "verify_email", self._action_url("verify_email", raw))
        except Exception as error:
            self._revoke_token_hash(token_hash)
            raise DomainError("recovery_delivery_failed", 503, True) from error
        return {"configured": True, "verified": False}

    def verify_email(self, raw_token: str, ip: str) -> dict[str, Any]:
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            self._rate(c, "verify_confirm", token_hash, self.ip_hash(ip), 5, minimum_seconds=0)
            token = c.execute(
                "SELECT * FROM v2_recovery_tokens WHERE token_hash=? AND purpose='verify_email' AND used_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                (token_hash, _now()),
            ).fetchone()
            if not token:
                raise DomainError("recovery_token_invalid", 400)
            changed = c.execute(
                "UPDATE v2_users SET recovery_email_verified_at=? WHERE id=? AND recovery_email_hash=?",
                (_now(), token["user_id"], token["email_hash"]),
            ).rowcount
            if changed != 1:
                raise DomainError("recovery_token_invalid", 400)
            c.execute("UPDATE v2_recovery_tokens SET used_at=? WHERE id=? AND used_at IS NULL", (_now(), token["id"]))
            return {"verified": True}

    def _deliver_password_reset(self, normalized: str, raw: str, token_hash: str) -> None:
        try:
            self.mailer.send(normalized, "password_reset", self._action_url("password_reset", raw))
        except Exception:
            self._revoke_token_hash(token_hash)
            return
        self._activate_delivered_token(token_hash)

    def request_password_reset(self, email: str, ip: str, submit: Any) -> None:
        started = time.monotonic()
        normalized = normalize_email(email)
        email_hash = self.email_hash(normalized)
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            self._rate(c, "reset_request", email_hash, self.ip_hash(ip), 3)
            user = c.execute(
                "SELECT id FROM v2_users WHERE account_type='registered' AND recovery_email_hash=? AND recovery_email_verified_at IS NOT NULL",
                (email_hash,),
            ).fetchone()
        if user:
            raw, token_hash = self._issue_token(user["id"], "password_reset", email_hash, 15, delivery_pending=True)
            try:
                submit(self._deliver_password_reset, normalized, raw, token_hash)
            except Exception:
                self._revoke_token_hash(token_hash)
        remaining = 0.075 - (time.monotonic() - started)
        if remaining > 0:
            time.sleep(remaining)

    def confirm_password_reset(self, raw_token: str, password: str, ip: str) -> dict[str, Any]:
        from .v2_database import _password

        if len(password) < 10 or len(set(password)) < 2:
            raise DomainError("password_policy_failed", 422)
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        ip_hash = self.ip_hash(ip)
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            self._rate(c, "reset_confirm", token_hash, ip_hash, 5, minimum_seconds=0)
            token = c.execute(
                "SELECT * FROM v2_recovery_tokens WHERE token_hash=? AND purpose='password_reset' AND used_at IS NULL AND revoked_at IS NULL AND expires_at>?",
                (token_hash, _now()),
            ).fetchone()
            if not token:
                raise DomainError("recovery_token_invalid", 400)
            stamp = _now()
            if c.execute("UPDATE v2_recovery_tokens SET used_at=? WHERE id=? AND used_at IS NULL AND revoked_at IS NULL", (stamp, token["id"])).rowcount != 1:
                raise DomainError("recovery_token_invalid", 400)
            c.execute("UPDATE v2_users SET password_hash=? WHERE id=?", (_password(password), token["user_id"]))
            c.execute("UPDATE v2_sessions SET revoked_at=? WHERE user_id=? AND revoked_at IS NULL", (stamp, token["user_id"]))
            c.execute(
                "UPDATE v2_recovery_tokens SET revoked_at=? WHERE user_id=? AND purpose='password_reset' AND used_at IS NULL AND revoked_at IS NULL",
                (stamp, token["user_id"]),
            )
            return {"reset": True, "session_revoked": True}

    def reserve_workflow(self, user_id: str, project_id: str | None, workflow_kind: str, run_id: str | None = None) -> str:
        reservation = self.settings.reservation_microunits()
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            actor = c.execute("SELECT account_type,visitor_expires_at FROM v2_users WHERE id=?", (user_id,)).fetchone()
            if not actor:
                raise DomainError("authentication_required", 401)
            if actor["account_type"] == "visitor" and (not actor["visitor_expires_at"] or actor["visitor_expires_at"] <= _now()):
                raise DomainError("visitor_expired", 401)
            visitor = actor["account_type"] == "visitor"
            workflow_limit = self.settings.visitor_workflows if visitor else self.settings.registered_workflows
            budget_limit = self.settings.visitor_budget_cny if visitor else self.settings.registered_budget_cny
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            count, used = c.execute(
                "SELECT COUNT(*),COALESCE(SUM(reserved_microunits),0) FROM v2_usage_reservations WHERE user_id=? AND created_at>?",
                (user_id, cutoff),
            ).fetchone()
            if count >= workflow_limit:
                raise DomainError("workflow_quota_exceeded", 429, True)
            if used + reservation > int(round(budget_limit * 1_000_000)):
                raise DomainError("server_budget_exceeded", 429, True)
            reservation_id = _new_id("usage")
            c.execute(
                "INSERT INTO v2_usage_reservations VALUES(?,?,?,?,?,?,?)",
                (reservation_id, user_id, project_id, run_id, workflow_kind, reservation, _now()),
            )
            return reservation_id

    def reserve_provider_attempt(self, user_id: str, reservation_id: str) -> None:
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            actor = c.execute("SELECT account_type FROM v2_users WHERE id=?", (user_id,)).fetchone()
            reservation = c.execute("SELECT 1 FROM v2_usage_reservations WHERE id=? AND user_id=?", (reservation_id, user_id)).fetchone()
            if not actor or not reservation:
                raise DomainError("usage_context_invalid", 503, True)
            limit = self.settings.visitor_provider_attempts if actor["account_type"] == "visitor" else self.settings.registered_provider_attempts
            cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
            count = c.execute("SELECT COUNT(*) FROM v2_provider_attempts WHERE user_id=? AND created_at>?", (user_id, cutoff)).fetchone()[0]
            if count >= limit:
                raise DomainError("provider_attempt_quota_exceeded", 429, True)
            c.execute("INSERT INTO v2_provider_attempts VALUES(?,?,?,?)", (_new_id("attempt"), user_id, reservation_id, _now()))

    def text_limits(self, user_id: str) -> dict[str, int]:
        visitor = self.account(user_id)["account_type"] == "visitor"
        return {
            "import_chars": 50_000 if visitor else 350_000,
            "import_bytes": 1 * 1024 * 1024 if visitor else 5 * 1024 * 1024,
            "draft_chars": 30_000,
        }

    def cleanup_expired_visitors(self) -> dict[str, Any]:
        with self.database.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            visitors = c.execute("SELECT id FROM v2_users WHERE account_type='visitor' AND visitor_expires_at<=?", (_now(),)).fetchall()
            hashes = [self._digest("cleanup", row["id"]) for row in visitors]
            for visitor in visitors:
                user_id = visitor["id"]
                projects = [row[0] for row in c.execute("SELECT id FROM v2_projects WHERE user_id=?", (user_id,)).fetchall()]
                for project_id in projects:
                    run_ids = [row[0] for row in c.execute("SELECT id FROM v2_runs WHERE project_id=?", (project_id,)).fetchall()]
                    change_ids = [row[0] for row in c.execute("SELECT id FROM v2_change_sets WHERE project_id=?", (project_id,)).fetchall()]
                    init_ids = [row[0] for row in c.execute("SELECT id FROM v2_memory_initializations WHERE project_id=?", (project_id,)).fetchall()]
                    batch_ids = [row[0] for row in c.execute("SELECT id FROM v2_memory_delta_batches WHERE project_id=?", (project_id,)).fetchall()]
                    source_change_ids = [row[0] for row in c.execute("SELECT id FROM v2_source_change_sets WHERE project_id=?", (project_id,)).fetchall()]
                    for run_id in run_ids:
                        c.execute("DELETE FROM v2_retrieval_traces WHERE run_id=?", (run_id,))
                        c.execute("DELETE FROM v2_run_claims WHERE run_id=?", (run_id,))
                        c.execute("DELETE FROM v2_run_events WHERE run_id=?", (run_id,))
                        c.execute("DELETE FROM v2_run_stages WHERE run_id=?", (run_id,))
                    for change_id in change_ids:
                        c.execute("DELETE FROM v2_change_set_items WHERE change_set_id=?", (change_id,))
                    for init_id in init_ids:
                        c.execute("DELETE FROM v2_memory_candidate_decisions WHERE initialization_id=?", (init_id,))
                        c.execute("DELETE FROM v2_memory_candidates WHERE initialization_id=?", (init_id,))
                    for batch_id in batch_ids:
                        c.execute("DELETE FROM v2_memory_delta_decisions WHERE batch_id=?", (batch_id,))
                        c.execute("DELETE FROM v2_memory_delta_candidates WHERE batch_id=?", (batch_id,))
                    for source_change_id in source_change_ids:
                        c.execute("DELETE FROM v2_source_change_set_audits WHERE change_set_id=?", (source_change_id,))
                    draft_ids = [row[0] for row in c.execute("SELECT id FROM v2_drafts WHERE project_id=?", (project_id,)).fetchall()]
                    for draft_id in draft_ids:
                        c.execute("DELETE FROM v2_draft_revisions WHERE draft_id=?", (draft_id,))
                    for table in (
                        "v2_evidence", "v2_decisions", "v2_issues", "v2_commit_audits", "v2_change_set_items",
                        "v2_change_sets", "v2_reset_audits", "v2_source_coverage_audits", "v2_memory_delta_decisions",
                        "v2_memory_delta_candidates", "v2_memory_delta_batches", "v2_source_change_set_audits",
                        "v2_source_change_sets", "v2_memory_candidate_decisions", "v2_memory_candidates",
                        "v2_memory_initializations", "v2_runs", "v2_drafts", "v2_memory_records",
                        "v2_memory_versions", "v2_source_spans", "v2_chapters", "v2_world_entries", "v2_characters",
                        "v2_outline_nodes",
                    ):
                        c.execute(f"DELETE FROM {table} WHERE project_id=?", (project_id,))
                    c.execute("DELETE FROM v2_projects WHERE id=?", (project_id,))
                reservation_ids = [row[0] for row in c.execute("SELECT id FROM v2_usage_reservations WHERE user_id=?", (user_id,)).fetchall()]
                for reservation_id in reservation_ids:
                    c.execute("DELETE FROM v2_provider_attempts WHERE reservation_id=?", (reservation_id,))
                c.execute("DELETE FROM v2_usage_reservations WHERE user_id=?", (user_id,))
                c.execute("DELETE FROM v2_recovery_tokens WHERE user_id=?", (user_id,))
                c.execute("DELETE FROM v2_import_drafts WHERE user_id=?", (user_id,))
                c.execute("DELETE FROM v2_sessions WHERE user_id=?", (user_id,))
                c.execute("DELETE FROM v2_idempotency WHERE scope=? OR scope LIKE ?", (user_id, f"%{user_id}%"))
                c.execute("DELETE FROM v2_users WHERE id=?", (user_id,))
            if visitors:
                import json

                c.execute(
                    "INSERT INTO v2_visitor_cleanup_audits VALUES(?,?,?,?)",
                    (_new_id("cleanup"), _now(), len(visitors), json.dumps(hashes)),
                )
            return {"visitor_count": len(visitors), "visitor_hashes": hashes}


@dataclass(frozen=True)
class UsageContext:
    user_id: str
    reservation_id: str


_usage_context: ContextVar[UsageContext | None] = ContextVar("stage13_usage_context", default=None)


@contextmanager
def provider_usage(user_id: str, reservation_id: str) -> Iterator[None]:
    token = _usage_context.set(UsageContext(user_id, reservation_id))
    try:
        yield
    finally:
        _usage_context.reset(token)


class UsageGuardProvider:
    def __init__(self, provider: Any, service: Stage13Service):
        self._provider = provider
        self._service = service

    def __getattr__(self, name: str) -> Any:
        return getattr(self._provider, name)

    @property
    def available(self) -> bool:
        return bool(self._provider.available)

    @property
    def label(self) -> str:
        return self._provider.label

    def evaluate(self, request: dict[str, Any]) -> Any:
        context = _usage_context.get()
        if context is None:
            raise ValueError("usage_context_required")
        try:
            self._service.reserve_provider_attempt(context.user_id, context.reservation_id)
        except DomainError as error:
            raise ValueError(error.code) from error
        return self._provider.evaluate(request)
