"""Standalone, standard-library maintenance. Never starts the application or a Provider.

Only the SQLite online backup API and read-only metadata queries touch the source.
All restored copies, manifests, alerts and usage snapshots live outside its directory.
"""
from __future__ import annotations

import argparse
from contextlib import closing, contextmanager
from datetime import datetime, timedelta, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import tempfile
import time
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
import uuid


class OperationsError(RuntimeError):
    pass


def now() -> datetime:
    return datetime.now(timezone.utc)


def stamp() -> str:
    return now().isoformat()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, temporary = tempfile.mkstemp(prefix=".ops-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(value, handle, ensure_ascii=True, sort_keys=True, allow_nan=False)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, 0o600)
        os.replace(temporary, path)
    finally:
        if Path(temporary).exists():
            Path(temporary).unlink()


def load_config(path: Path) -> dict:
    config = json.loads(path.read_text(encoding="utf-8-sig"))
    if config.get("local_test_mirror") and config.get("offsite_ssh"):
        raise OperationsError("ambiguous_replica_targets")
    for key in ("database", "backup_dir", "state_dir", "drill_dir"):
        candidate = Path(config[key]).expanduser()
        if not candidate.is_absolute():
            raise OperationsError("absolute_paths_required")
        if candidate.is_symlink():
            raise OperationsError("symlink_target_rejected")
        config[key] = candidate.resolve()
    database = config["database"]
    if not database.is_file():
        raise OperationsError("database_missing")
    protected = {"evaluation", "held-out", "heldout", "golden", "story-continuity-poc"}
    for key in ("database", "backup_dir", "state_dir", "drill_dir"):
        if protected.intersection(part.casefold() for part in config[key].parts):
            raise OperationsError("protected_path_rejected")
    outputs = [config[key] for key in ("backup_dir", "state_dir", "drill_dir")]
    for target in outputs:
        if target == database.parent or target.is_relative_to(database.parent) or database.is_relative_to(target):
            raise OperationsError("output_overlaps_source")
    for index, target in enumerate(outputs):
        if any(target == other or target.is_relative_to(other) or other.is_relative_to(target)
               for other in outputs[index + 1:]):
            raise OperationsError("output_directories_overlap")
        target.mkdir(parents=True, exist_ok=True, mode=0o700)
    for key, default in (("backup_max_age_hours", 30), ("drill_max_age_days", 9),
                         ("failure_window_hours", 24), ("stuck_run_minutes", 30),
                         ("retention_days", 30), ("minimum_backups", 7)):
        value = config.get(key, default)
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value <= 0:
            raise OperationsError("invalid_threshold")
        config[key] = value
    return config


@contextmanager
def readonly(path: Path):
    connection = sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only=ON")
    try:
        yield connection
    finally:
        connection.close()


def inspect_database(path: Path) -> dict:
    with readonly(path) as connection:
        if [row[0] for row in connection.execute("PRAGMA integrity_check")] != ["ok"]:
            raise OperationsError("integrity_failed")
        if connection.execute("PRAGMA foreign_key_check").fetchone():
            raise OperationsError("foreign_key_failed")
        names = [row[0] for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name")]
        if "schema_migrations" not in names or "v2_runs" not in names:
            raise OperationsError("application_schema_missing")
        # Hash table/count metadata. Never emit business rows or user-defined table names.
        counts = [(name, connection.execute('SELECT COUNT(*) FROM "' + name.replace('"', '""') + '"').fetchone()[0])
                  for name in names]
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
    return {"integrity": "ok", "foreign_key_violations": 0, "schema_version": version,
            "table_count": len(names), "row_count_digest": hashlib.sha256(json.dumps(counts).encode()).hexdigest()}


def latest_manifest(config: dict) -> dict | None:
    records = sorted(config["backup_dir"].glob("ops-backup-*.json"), reverse=True)
    if not records:
        return None
    item = json.loads(records[0].read_text(encoding="utf-8"))
    name = item.get("backup_name", "")
    if not re.fullmatch(r"ops-backup-[0-9TZ-]+-[0-9a-f]{8}\.sqlite3", name):
        raise OperationsError("backup_manifest_invalid")
    return item


def replicate(config: dict, source: Path, expected: str) -> dict:
    mirror = config.get("local_test_mirror")
    if mirror:
        target_dir = Path(mirror).expanduser().resolve()
        if not Path(mirror).is_absolute() or any(target_dir == config[key] or target_dir.is_relative_to(config[key]) or config[key].is_relative_to(target_dir)
                                               for key in ("backup_dir", "state_dir", "drill_dir")) or target_dir == config["database"].parent or target_dir.is_relative_to(config["database"].parent):
            raise OperationsError("test_mirror_overlap")
        target_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        target = target_dir / source.name
        with target.open("xb") as output, source.open("rb") as input_file:
            shutil.copyfileobj(input_file, output)
        os.chmod(target, 0o600)
        if sha256(target) != expected:
            raise OperationsError("test_mirror_hash_mismatch")
        return {"status": "local_test_verified", "is_off_instance": False, "sha256": expected,
                "bytes": target.stat().st_size, "verified_at": stamp()}
    remote = config.get("offsite_ssh")
    if not remote:
        return {"status": "missing", "reason": "offsite_target_unconfigured"}
    host, directory = remote.get("target", ""), remote.get("directory", "")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+@[A-Za-z0-9][A-Za-z0-9.-]*", host) or host.split("@")[-1] in {"localhost", "127.0.0.1"}:
        raise OperationsError("offsite_target_invalid")
    if not re.fullmatch(r"/[A-Za-z0-9_./-]+", directory) or ".." in directory.split("/"):
        raise OperationsError("offsite_directory_invalid")
    identity = Path(remote.get("identity_file", ""))
    if not identity.is_absolute() or not identity.is_file():
        raise OperationsError("offsite_identity_missing")
    options = ["-oBatchMode=yes", "-oStrictHostKeyChecking=yes", "-oConnectTimeout=15", "-i", str(identity)]
    staging = directory.rstrip("/") + "/." + source.name + ".partial"
    destination = directory.rstrip("/") + "/" + source.name
    # No remote shell interpolation from business data; target/path are strictly constrained.
    transferred = subprocess.run(["scp", "-q", *options, str(source), host + ":" + staging],
                                 capture_output=True, timeout=300, check=False)
    if transferred.returncode:
        raise OperationsError("offsite_transfer_failed")
    script = ("import hashlib,json,os,pathlib; p=pathlib.Path(" + repr(staging) + "); "
              "h=hashlib.sha256(p.read_bytes()).hexdigest(); "
              "assert h==" + repr(expected) + "; "
              "d=pathlib.Path(" + repr(destination) + "); assert not d.exists(); "
              "os.chmod(p,0o600); os.replace(p,d); "
              "m=hashlib.sha256(pathlib.Path('/etc/machine-id').read_bytes()).hexdigest(); "
              "print(json.dumps({'sha256':h,'bytes':d.stat().st_size,'machine_hash':m}))")
    import shlex
    verified = subprocess.run(["ssh", *options, host, "python3 -c " + shlex.quote(script)],
                              capture_output=True, text=True, timeout=300, check=False)
    if verified.returncode:
        raise OperationsError("offsite_verification_failed")
    receipt = json.loads(verified.stdout)
    if receipt.get("sha256") != expected or receipt.get("bytes") != source.stat().st_size:
        raise OperationsError("offsite_verification_failed")
    if not Path("/etc/machine-id").is_file() or receipt.get("machine_hash") == sha256(Path("/etc/machine-id")):
        raise OperationsError("offsite_independence_unverified")
    return {"status": "verified", "is_off_instance": True, "verified_at": stamp(),
            "sha256": receipt["sha256"], "bytes": receipt["bytes"]}


def backup(config: dict) -> dict:
    token = now().strftime("%Y%m%dT%H%M%S%fZ") + "-" + uuid.uuid4().hex[:8]
    destination = config["backup_dir"] / ("ops-backup-" + token + ".sqlite3")
    temporary = destination.with_suffix(".partial")
    started = time.monotonic()
    try:
        with readonly(config["database"]) as source:
            with closing(sqlite3.connect(temporary)) as target, target:
                def progress(status, remaining, total):
                    if time.monotonic() - started > 300:
                        raise OperationsError("backup_timeout")
                source.backup(target, pages=256, progress=progress, sleep=0.05)
        summary = inspect_database(temporary)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
        manifest = {"operation": "backup", "created_at": stamp(), "backup_name": destination.name,
                    "sha256": sha256(destination), "bytes": destination.stat().st_size, **summary,
                    "offsite": {"status": "pending"}}
        write_json(destination.with_suffix(".json"), manifest)
        try:
            manifest["offsite"] = replicate(config, destination, manifest["sha256"])
        except (OperationsError, OSError, subprocess.SubprocessError, ValueError):
            manifest["offsite"] = {"status": "failed", "reason": "offsite_copy_failed"}
        write_json(destination.with_suffix(".json"), manifest)
        write_json(config["state_dir"] / "retention-latest.json", retention(config))
        return manifest
    finally:
        if temporary.exists():
            temporary.unlink()


def drill(config: dict) -> dict:
    item = latest_manifest(config)
    if not item:
        raise OperationsError("backup_missing")
    source = config["backup_dir"] / item["backup_name"]
    if source.is_symlink() or sha256(source) != item["sha256"]:
        raise OperationsError("backup_hash_mismatch")
    before = inspect_database(source)
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ops-drill-", dir=config["drill_dir"]) as directory:
        target = Path(directory) / "restored.sqlite3"
        shutil.copyfile(source, target)
        if sha256(target) != item["sha256"]:
            raise OperationsError("restore_copy_hash_mismatch")
        restored = inspect_database(target)
        if restored != before:
            raise OperationsError("restore_metadata_mismatch")
        # A committed write/read/delete exercises a usable recovered SQLite database.
        with closing(sqlite3.connect(target)) as connection, connection:
            connection.execute("CREATE TABLE ops_recovery_probe(value INTEGER NOT NULL)")
            connection.execute("INSERT INTO ops_recovery_probe VALUES(1)")
            connection.commit()
        with closing(sqlite3.connect(target)) as connection, connection:
            if connection.execute("SELECT value FROM ops_recovery_probe").fetchone() != (1,):
                raise OperationsError("restore_write_probe_failed")
            connection.execute("DROP TABLE ops_recovery_probe")
            connection.commit()
        if inspect_database(target) != before or sha256(source) != item["sha256"]:
            raise OperationsError("restore_postcheck_failed")
    result = {"operation": "drill", "status": "passed", "completed_at": stamp(),
              "backup_name": item["backup_name"], "backup_sha256": item["sha256"],
              "duration_ms": round((time.monotonic() - started) * 1000),
              "source_unchanged": True, "committed_write_probe": "passed", **before}
    write_json(config["state_dir"] / "last-drill.json", result)
    return result


def usage(config: dict) -> dict:
    cutoff = (now() - timedelta(hours=config["failure_window_hours"])).isoformat()
    with readonly(config["database"]) as connection:
        names = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        runs = connection.execute(
            "SELECT status,input_tokens,output_tokens,cost_cny,created_at,completed_at,started_at "
            "FROM v2_runs WHERE result_origin='provider' AND (julianday(created_at)>=julianday(?) OR julianday(completed_at)>=julianday(?))", (cutoff, cutoff)).fetchall()
        active_runs = connection.execute("SELECT started_at,created_at FROM v2_runs WHERE result_origin='provider' AND status IN ('queued','running')").fetchall()
        attempts = connection.execute("SELECT COUNT(*) FROM v2_provider_attempts WHERE julianday(created_at)>=julianday(?)", (cutoff,)).fetchone()[0] if "v2_provider_attempts" in names else None
        reservations = connection.execute("SELECT COUNT(*), SUM(reserved_microunits) FROM v2_usage_reservations WHERE julianday(created_at)>=julianday(?)", (cutoff,)).fetchone() if "v2_usage_reservations" in names else None
    fields = {}
    for field in ("input_tokens", "output_tokens", "cost_cny"):
        observed = [row[field] for row in runs if isinstance(row[field], (int, float)) and math.isfinite(row[field]) and row[field] >= 0]
        missing = len(runs) - len(observed)
        fields[field] = {"status": "unknown" if missing else "available", "unknown_run_count": missing,
                         "known_run_count": len(observed), "known_run_sum": sum(observed) if observed else (0 if not runs else None),
                         "all_run_sum": None if missing else sum(observed)}
    status_counts = {status: sum(row["status"] == status for row in runs)
                     for status in ("queued", "running", "completed", "failed", "timed_out", "cancelled", "budget_paused")}
    stuck_cutoff = now() - timedelta(minutes=config["stuck_run_minutes"])
    stuck = 0
    for row in active_runs:
        value = row["started_at"] or row["created_at"]
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            stuck += parsed.replace(tzinfo=parsed.tzinfo or timezone.utc) < stuck_cutoff
        except (ValueError, AttributeError):
            stuck += 1
    return {"operation": "usage", "observed_at": stamp(), "window_start": cutoff,
            "provider_run_count": len(runs), "run_status_counts": status_counts, "stuck_run_count": stuck,
            "provider_attempt_count": attempts, "provider_attempt_status": "unknown" if attempts is None else "available",
            "workflow_reservation_count": reservations[0] if reservations else None,
            "reserved_budget_cny": reservations[1] / 1_000_000 if reservations and reservations[1] is not None else (0 if reservations else None),
            "run_observed_metrics": fields, "billed_cost_cny": None, "billed_cost_status": "unknown",
            "scope": "rolling_snapshot_of_retained_rows;not_additive;run_metrics_may_share_failed_batch_totals;reservations_are_not_spend;initialization_and_cleaned_visitors_may_be_unrepresented"}


def probe(origin: str, route: str) -> dict:
    parsed = urlsplit(origin)
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise OperationsError("health_origin_invalid")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and parsed.hostname in {"127.0.0.1", "localhost", "::1"}):
        raise OperationsError("health_origin_invalid")
    try:
        with urlopen(Request(origin.rstrip("/") + route, headers={"Accept": "application/json"}), timeout=10) as response:
            payload = json.loads(response.read(65537))
            expected = "ok" if route == "/health" else "ready"
            return {"ok": response.status == 200 and payload.get("status") == expected, "http_status": response.status}
    except Exception:
        return {"ok": False, "error_code": "endpoint_unavailable"}


def age_hours(value: str) -> float:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise OperationsError("timestamp_timezone_missing")
    return max(0, (now() - parsed).total_seconds() / 3600)


def monitor(config: dict) -> dict:
    alerts = []
    checks = {route[1:]: probe(config["health_origin"], route) for route in ("/health", "/readiness")}
    for name, result in checks.items():
        if not result["ok"]:
            alerts.append(name + "_unavailable")
    try:
        item = latest_manifest(config)
        if not item:
            alerts += ["backup_missing", "offsite_copy_missing"]
        else:
            source = config["backup_dir"] / item["backup_name"]
            if source.is_symlink() or sha256(source) != item["sha256"]:
                alerts.append("backup_integrity_failed")
            if age_hours(item["created_at"]) > config["backup_max_age_hours"]:
                alerts.append("backup_stale")
            if item.get("offsite", {}).get("status") != "verified":
                alerts.append("offsite_copy_missing")
    except (OSError, ValueError, KeyError, OperationsError):
        alerts.append("backup_integrity_failed")
    try:
        last_drill = json.loads((config["state_dir"] / "last-drill.json").read_text())
        if last_drill.get("status") != "passed" or age_hours(last_drill["completed_at"]) > config["drill_max_age_days"] * 24:
            alerts.append("restore_drill_stale")
    except (OSError, ValueError, KeyError, OperationsError):
        alerts.append("restore_drill_missing")
    for command in ("backup", "drill"):
        failure_path = config["state_dir"] / ("last-" + command + "-failure.json")
        if failure_path.exists():
            try:
                failure = json.loads(failure_path.read_text())
                success = json.loads((config["state_dir"] / ("last-" + command + ".json")).read_text())
                success_time = success.get("created_at") or success.get("completed_at")
                if not success_time or age_hours(failure["observed_at"]) < age_hours(success_time):
                    alerts.append(command + "_job_failed")
            except (OSError, ValueError, KeyError, OperationsError):
                alerts.append(command + "_job_failed")
    try:
        ledger = usage(config)
        write_json(config["state_dir"] / "usage-latest.json", ledger)
        # One snapshot per hour: repeat probes do not create an apparently additive billing ledger.
        write_json(config["state_dir"] / "usage" / (now().strftime("%Y%m%dT%H") + ".json"), ledger)
        if any(ledger["run_status_counts"][status] for status in ("failed", "timed_out", "budget_paused")):
            alerts.append("failed_runs_in_window")
        if ledger["stuck_run_count"]:
            alerts.append("stuck_runs")
    except sqlite3.Error:
        alerts.append("usage_query_failed")
    result = {"operation": "monitor", "observed_at": stamp(), "ok": not alerts, "checks": checks,
              "alerts": sorted(set(alerts)), "notification_channel": "local_json_and_systemd_journal"}
    previous_path = config["state_dir"] / "monitor-latest.json"
    try:
        previous = json.loads(previous_path.read_text())
    except (OSError, ValueError):
        previous = {}
    if previous.get("alerts") != result["alerts"]:
        write_json(config["state_dir"] / "alerts" / (now().strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8] + ".json"), result)
    write_json(previous_path, result)
    return result


def retention(config: dict) -> dict:
    manifests = sorted(config["backup_dir"].glob("ops-backup-*.json"), reverse=True)
    candidates = []
    for index, path in enumerate(manifests):
        record = json.loads(path.read_text())
        if index >= config["minimum_backups"] and age_hours(record["created_at"]) > config["retention_days"] * 24:
            candidates.append(record["backup_name"])
    return {"operation": "retention", "mode": "report_only", "automatic_deletion": False,
            "minimum_backups": config["minimum_backups"], "retention_days": config["retention_days"],
            "candidate_count": len(candidates), "candidates": candidates, "deleted_count": 0}


@contextmanager
def lock(config: dict):
    # OS lock is released on process death; avoids stale lock directories after a reboot.
    path = config["state_dir"] / ".operations.lock"
    with path.open("a+b") as handle:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            if not handle.read(1):
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                raise OperationsError("operation_already_running") from None
        else:
            import fcntl
            try:
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                raise OperationsError("operation_already_running") from None
        yield


def main() -> int:
    parser = argparse.ArgumentParser(description="Local maintenance; stdout contains only sanitized operational metadata")
    parser.add_argument("--config", type=Path, required=True)
    parser.add_argument("command", choices=("backup", "drill", "monitor", "usage", "retention"))
    args = parser.parse_args()
    config = None
    try:
        config = load_config(args.config)
        with lock(config):
            result = globals()[args.command](config)
            write_json(config["state_dir"] / ("last-" + args.command + ".json"), result)
        healthy = result.get("ok", True) and not (args.command == "backup" and result["offsite"]["status"] != "verified")
        print(json.dumps({"ok": healthy, "result": result}, sort_keys=True, allow_nan=False))
        return 0 if healthy else 2
    except Exception as error:
        code = str(error) if isinstance(error, OperationsError) else "operation_failed"
        result = {"ok": False, "operation": args.command, "error_code": code, "observed_at": stamp()}
        if config:
            write_json(config["state_dir"] / ("last-" + args.command + "-failure.json"), result)
        print(json.dumps(result))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
