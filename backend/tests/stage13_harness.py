from __future__ import annotations

import os
from pathlib import Path
import tempfile
from typing import Mapping


PROFILES = {
    "impl": {
        "frontend_origin": "http://127.0.0.1:3080",
        "backend_origin": "http://127.0.0.1:8080",
        "dist_dir": ".next-stage13-impl",
        "temp_prefix": "story-stage13-impl-",
        "account_prefix": "stage13impl",
        "frontend_port": 3080,
        "backend_port": 8080,
    },
    "pm3": {
        "frontend_origin": "http://127.0.0.1:3081",
        "backend_origin": "http://127.0.0.1:8081",
        "dist_dir": ".next-stage13-pm3",
        "temp_prefix": "story-stage13-pm3-",
        "account_prefix": "stage13pm3",
        "frontend_port": 3081,
        "backend_port": 8081,
    },
    "v4impl": {
        "frontend_origin": "http://127.0.0.1:3084",
        "backend_origin": "http://127.0.0.1:8084",
        "dist_dir": ".next-stage13-v4-impl",
        "temp_prefix": "story-stage13-v4-impl-",
        "account_prefix": "stage13v4impl",
        "frontend_port": 3084,
        "backend_port": 8084,
    },
    "v4pm3": {
        "frontend_origin": "http://127.0.0.1:3085",
        "backend_origin": "http://127.0.0.1:8085",
        "dist_dir": ".next-stage13-v4-pm3",
        "temp_prefix": "story-stage13-v4-pm3-",
        "account_prefix": "stage13v4pm3",
        "frontend_port": 3085,
        "backend_port": 8085,
    },
    "v110impl": {
        "frontend_origin": "http://127.0.0.1:3190",
        "backend_origin": "http://127.0.0.1:8190",
        "dist_dir": ".next-v110-impl",
        "temp_prefix": "story-v110-impl-",
        "account_prefix": "v110impl",
        "frontend_port": 3190,
        "backend_port": 8190,
    },
}


def _isolated_path(value: str | None, profile: dict, name: str, root: Path | None = None) -> Path:
    if not value:
        raise RuntimeError(f"{name.lower()}_required")
    resolved = Path(value).resolve()
    system_temp = Path(tempfile.gettempdir()).resolve()
    if system_temp not in resolved.parents or not any(part.startswith(profile["temp_prefix"]) for part in resolved.parts):
        raise RuntimeError(f"{name.lower()}_profile_mismatch")
    if root is not None and resolved != root and root not in resolved.parents:
        raise RuntimeError(f"{name.lower()}_outside_test_root")
    return resolved


def validate_stage13_harness(env: Mapping[str, str] | None = None) -> dict:
    source = os.environ if env is None else env
    profile_name = source.get("STAGE13_HARNESS_PROFILE")
    profile = PROFILES.get(profile_name)
    if profile is None:
        raise RuntimeError("stage13_harness_profile_invalid")
    exact = {
        "E2E_BASE_URL": profile["frontend_origin"],
        "E2E_BACKEND_ORIGIN": profile["backend_origin"],
        "BACKEND_ORIGIN": profile["backend_origin"],
        "PUBLIC_APP_MODE": "0",
        "PUBLIC_BASE_URL": profile["frontend_origin"],
        "NEXT_DIST_DIR": profile["dist_dir"],
    }
    for name, expected in exact.items():
        if source.get(name) != expected:
            raise RuntimeError(f"{name.lower()}_profile_mismatch")
    account_prefix = source.get("E2E_ACCOUNT_PREFIX", "")
    if not account_prefix.startswith(profile["account_prefix"]):
        raise RuntimeError("e2e_account_prefix_profile_mismatch")
    test_root = _isolated_path(source.get("E2E_TEST_ROOT"), profile, "E2E_TEST_ROOT")
    output_dir = _isolated_path(source.get("E2E_OUTPUT_DIR"), profile, "E2E_OUTPUT_DIR", test_root)
    return {"profile_name": profile_name, "test_root": test_root, "output_dir": output_dir, "account_prefix": account_prefix, **profile}
