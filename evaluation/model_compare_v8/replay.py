"""Offline parity check against all 34 archived V7 response chains; no Provider/DB."""
from __future__ import annotations

import argparse
import copy

from app.provider import ProviderResult
from evaluation.model_compare_v8.config import *
from evaluation.model_compare_v8.harness import FrozenInputEngine, experimental_budget
from evaluation.model_compare_v8.score import engine_final_score

V7_LIVE = ROOT / "evaluation/current_flash_v7/runs/flash-v7-20260927-01/cases"


def replay_all():
    results, hashes = [], {}
    def capture(path):
        hashes[path.relative_to(ROOT).as_posix()] = sha(path)
        return read(path)
    for case in cases():
        folder = V7_LIVE / f"{case['ordinal']:02d}"
        chain = [capture(path) for path in sorted((folder / "evaluations").glob("*.json"))]
        requests = [capture(path)["business_request"] for path in sorted((folder / "requests").glob("*.json"))]
        attempts = [capture(path) for path in sorted((folder / "attempts").glob("*-finish.json"))]
        archived = capture(folder / "scores.json")["final"]
        class ReplayProvider:
            available = True
            continuity_contract_version = "v6"
            calls = 0
            def evaluate(self, request):
                index = self.calls
                if request != requests[index]:
                    raise AssertionError("replay_request_chain_changed")
                self.calls += 1
                usage = attempts[index]["usage"]["values"]
                return ProviderResult(copy.deepcopy(chain[index]["parsed_business_json"]),
                    usage["prompt_tokens"], usage["completion_tokens"], None, attempts[index]["latency_ms"],
                    attempts[index]["finish_reason"], usage["prompt_tokens"], usage["completion_tokens"], None)
        provider = ReplayProvider()
        with experimental_budget():
            final = FrozenInputEngine(provider).execute(copy.deepcopy(requests[0]))
        score = engine_final_score(case, final, requests[0], chain[-1]["parsed_business_json"], attempts[-1]["finish_reason"])
        equivalent = score["machine_result"] == archived["machine_result"] and set(score["errors"]) == set(archived["errors"])
        results.append({"ordinal": case["ordinal"], "case_id": case["case_id"], "evaluations": provider.calls,
            "captured_evaluations": len(chain), "request_chain_equal": provider.calls == len(chain),
            "archived_machine_result": archived["machine_result"], "adapter_machine_result": score["machine_result"],
            "archived_errors": archived["errors"], "adapter_errors": score["errors"], "equivalent": equivalent})
    stable = all(sha(ROOT / path) == expected for path, expected in hashes.items())
    return {"mode": "offline_v7_replay_only", "provider_calls": 0, "database_connections": 0,
        "cases": results, "equivalent_cases": sum(r["equivalent"] for r in results),
        "archived_final_pass": sum(r["archived_machine_result"] == "pass" for r in results),
        "adapter_final_pass": sum(r["adapter_machine_result"] == "pass" for r in results),
        "read_hashes": hashes, "read_hashes_stable": stable,
        "not_a_new_model_score": True, "excluded_layer": "API/DB persistence only"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", default="offline-replay-01.json")
    args = parser.parse_args()
    if pathlib.Path(args.output).name != args.output:
        raise ValueError("output_must_be_new_filename_in_v8")
    result = replay_all()
    write_x(HERE / args.output, result)
    print({k: result[k] for k in ("equivalent_cases", "archived_final_pass", "adapter_final_pass", "read_hashes_stable")})
    if result["equivalent_cases"] != 34 or result["adapter_final_pass"] != 19 or not result["read_hashes_stable"]:
        raise SystemExit(1)
