"""Developer diagnostic (not a gate): continuity review latency on *imported* projects.

The V10 gate loads Memory from fixtures. Real users import text and let Flash build Memory, which
can miss a fact that the draft contradicts. On such projects the v21 review thought at high and
medium effort until the 16,000-token cap (about 150 s). This runner imports each novel, accepts
every Memory candidate, then checks each draft through the real API and records per-dispatch
metadata (effort, finish reason, tokens, seconds) and the resulting issue natures.

Usage: python -m evaluation.imported_runaway_dev.run --label v21 [--repeats 1]
Output: evaluation/imported_runaway_dev/results/<label>.json (metadata only, no model text).
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import tempfile
import time
import uuid

ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ["SCC_DISABLE_DEFAULT_APP"] = "1"

from fastapi.testclient import TestClient  # noqa: E402

from app.config import AppPaths  # noqa: E402
from app.engine import PROMPT_VERSION  # noqa: E402
from app.main import create_app  # noqa: E402
from app.provider import DeepSeekProvider  # noqa: E402
from app.stage13 import Stage13Settings  # noqa: E402

HERE = pathlib.Path(__file__).resolve().parent
CASES = json.loads((HERE / "cases.json").read_text(encoding="utf-8"))


class Recording(DeepSeekProvider):
    def __init__(self):
        super().__init__()
        self.log: list[dict] = []

    def _send(self, body):
        prompt = json.loads(body["messages"][0]["content"])
        entry = {"review": "claim_verdicts" in json.dumps(prompt.get("output_schema", {})), "repair": bool(prompt.get("contract_repair")),
                 "effort": body.get("reasoning_effort") or ("none" if body["thinking"]["type"] == "disabled" else None)}
        started = time.perf_counter()
        try:
            result = super()._send(body)
            entry.update(outcome="parsed", finish=result.finish_reason, input=result.observed_response_input_tokens,
                         output=result.observed_response_output_tokens)
            return result
        except Exception as error:
            entry.update(outcome=type(error).__name__, finish=getattr(error, "finish_reason", None),
                         input=getattr(error, "observed_response_input_tokens", None), output=getattr(error, "observed_response_output_tokens", None))
            raise
        finally:
            entry["seconds"] = round(time.perf_counter() - started, 1)
            self.log.append(entry)


def data(response):
    if response.status_code >= 300:
        raise RuntimeError(f"{response.status_code} {response.text[:200]}")
    return response.json()["data"]


def run_novel(novel: dict, provider: Recording, only: set[str] | None = None) -> list[dict]:
    drafts = [case for case in novel["drafts"] if not only or case["id"] in only]
    if not drafts:
        return []
    root = pathlib.Path(tempfile.mkdtemp(prefix="scc-imported-dev-"))
    app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=provider,
                     executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
    client = TestClient(app)
    idem = lambda: {"Idempotency-Key": str(uuid.uuid4())}
    data(client.post("/api/auth/register", json={"account_name": f"dev{uuid.uuid4().hex[:8]}", "display_name": "Dev",
                                                  "password": "dev-local-password-123", "recovery_email": "dev@example.test"}, headers=idem()))
    preview = data(client.post("/api/imports/preview", files={"file": ("novel.md", novel["source"].encode(), "text/markdown")}, headers=idem()))
    project = data(client.post(f"/api/imports/{preview['import_id']}/commit", json={"confirm": True, "title": novel["id"],
                   "chapter_preview_ids": [row["preview_id"] for row in preview["detected"]["chapters"]]}, headers=idem()))["project"]["id"]
    init = data(client.post(f"/api/projects/{project}/memory/initializations", json={"source_revision": 1}, headers=idem()))["initialization"]
    for candidate in init.get("candidates") or []:
        client.post(f"/api/projects/{project}/memory/initializations/{init['id']}/candidates/{candidate['id']}/decision",
                    json={"decision": "accepted"}, headers=idem())
    client.post(f"/api/projects/{project}/memory/initializations/{init['id']}/commit", json={"confirm": True}, headers=idem())
    memory_count = len(init.get("candidates") or [])
    records = []
    for case in drafts:
        draft = data(client.get(f"/api/projects/{project}"))["current_draft"]
        patched = data(client.patch(f"/api/projects/{project}/drafts/{draft['id']}", json={"base_revision": draft["revision"], "body": case["body"]},
                                    headers=idem()))
        before = len(provider.log)
        started = time.perf_counter()
        run = data(client.post(f"/api/projects/{project}/checks", json={"draft_id": draft["id"], "draft_revision": patched["revision"]}, headers=idem()))
        view = data(client.get(f"/api/projects/{project}/checks/{run['run_id']}?include=issues,evidence,metrics"))
        dispatches = provider.log[before:]
        records.append({"novel": novel["id"], "case": case["id"], "expect": case["expect"], "memory_candidates": memory_count,
                        "seconds": round(time.perf_counter() - started, 1), "status": view["status"], "error_code": view.get("error_code"),
                        "natures": sorted(issue.get("nature") for issue in view.get("issues") or []),
                        "runaway_dispatches": sum(1 for d in dispatches if d.get("finish") == "length"),
                        "non_thinking_fallback": any(d.get("effort") == "none" for d in dispatches if d["review"]),
                        "tokens": sum((d.get("input") or 0) + (d.get("output") or 0) for d in dispatches), "dispatches": dispatches})
        print(json.dumps({k: v for k, v in records[-1].items() if k != "dispatches"}, ensure_ascii=False), flush=True)
    client.close()
    return records


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", required=True)
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--only", nargs="*", help="case ids to run (default: all)")
    args = parser.parse_args()
    only = set(args.only) if args.only else None
    os.environ["CONTINUITY_REVIEW_THINKING"] = "high"
    out = HERE / "results" / f"{args.label}.json"
    if out.exists():
        raise FileExistsError(out)
    provider = Recording()
    if not provider.available:
        raise RuntimeError("provider_unavailable")
    records = [record for _ in range(args.repeats) for novel in CASES["novels"] for record in run_novel(novel, provider, only)]
    summary = {"label": args.label, "prompt_version": PROMPT_VERSION, "model": provider.model, "checks": len(records),
               "completed": sum(r["status"] == "completed" for r in records),
               "checks_with_runaway": sum(r["runaway_dispatches"] > 0 for r in records),
               "non_thinking_fallbacks": sum(r["non_thinking_fallback"] for r in records),
               "median_seconds": sorted(r["seconds"] for r in records)[len(records) // 2],
               "max_seconds": max(r["seconds"] for r in records), "total_tokens": sum(r["tokens"] for r in records)}
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps({"summary": summary, "records": records}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == "__main__":
    main()
