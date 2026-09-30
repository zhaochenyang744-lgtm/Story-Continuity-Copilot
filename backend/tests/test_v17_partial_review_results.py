"""A contract failure on one claim must not discard the rest of the chapter.

Production, 2026-09-30, release v22-0696e52: an 816-character chapter became 36 claims, one of
them came back as a possible_conflict citing its own span as insufficient twice, and the whole run
failed with conflict_evidence_insufficient after 240 s and 78,878 tokens, returning nothing. The
record is evaluation/results/prod-longform-chapter-failure-20260930.json. A multi-claim batch that
fails its contract twice is now retried one claim at a time, and only a claim that still fails is
set aside as undecided.
"""
from __future__ import annotations

import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.stage13 import Stage13Settings

from app.engine import ContinuityEngine
from app.provider import REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS, ProviderResult


def data(claim_count: int):
    evidence = "林默是港务局的年轻记录员，左手缺了一根小指。"
    bodies = [f"第{index}句，林默张开左手，五根手指都在。" for index in range(1, claim_count + 1)]
    return {"draft": {"id": "draft-v17", "revision": 1, "body": "".join(bodies)},
            "claims": [{"id": f"claim-v17-{index}", "text": body, "allowed_evidence": [
                {"id": "span-v17", "chapter_id": "chapter-v17", "body": evidence, "prompt_excerpt": evidence}]}
                for index, body in enumerate(bodies, 1)],
            "memory": []}


def issue(claim_id: str, sufficiency: str):
    """A possible_conflict is only contract-valid when its citation is marked sufficient."""
    return {"claim_span_id": claim_id, "status": "conflict", "nature": "possible_conflict",
            "category": "attribute", "severity": "medium", "explanation": "两处手部描述相互矛盾。",
            "reasoning": "来源说缺一根小指，草稿说五指完好；没有共同时间可以确定二者不能并存。",
            "temporal_basis": {"claim_anchor": None, "evidence_anchor": None, "relation": "unknown"},
            "evidence": [{"chapter_id": "chapter-v17", "span_id": "span-v17", "relation": "contradicts",
                          "sufficiency": sufficiency, "related_memory_ids": []}],
            "evidence_chain": [{"span_id": "span-v17", "role": "prior_state"}],
            "suggested_revision": None, "available_actions": ["keep_intentional"], "proposed_memory_change": None}


def verdict(claim_id: str):
    return {"claim_span_id": claim_id, "verdict": "reviewed_issue", "basis": "两处手部描述相互矛盾，时间关系未知。"}


class Poisoned:
    """Answers correctly for every claim except one, which always cites insufficient evidence."""

    available = True
    continuity_contract_version = "v6"
    label = model_label = "v17-offline"

    def __init__(self, bad_claim_id: str | None):
        self.bad, self.requests = bad_claim_id, []

    def evaluate(self, request):
        self.requests.append(request)
        ids = [claim["id"] for claim in request["claims"]]
        return ProviderResult({"claim_verdicts": [verdict(claim_id) for claim_id in ids],
                               "issues": [issue(claim_id, "insufficient" if claim_id == self.bad else "sufficient")
                                          for claim_id in ids]}, input_tokens=1, output_tokens=1)


class PartialReviewResultTests(unittest.TestCase):
    def test_one_bad_claim_no_longer_discards_the_other_claims(self):
        payload = data(4)
        provider = Poisoned("claim-v17-3")
        result = ContinuityEngine(provider).execute(payload)
        self.assertEqual(result["status"], "completed")
        self.assertEqual([row["claim_span_id"] for row in result["undecided_claims"]], ["claim-v17-3"])
        self.assertEqual(result["undecided_claims"][0]["error_code"], "conflict_evidence_insufficient")
        self.assertEqual([item["claim_span_id"] for item in result["issues"]],
                         ["claim-v17-1", "claim-v17-2", "claim-v17-4"])

    def test_a_clean_chapter_reports_no_undecided_claims(self):
        result = ContinuityEngine(Poisoned(None)).execute(data(4))
        self.assertEqual((result["status"], result["undecided_claim_count"]), ("completed", 0))
        self.assertEqual(len(result["issues"]), 4)

    def test_a_chapter_that_fails_on_every_claim_still_fails_closed(self):
        payload = data(3)
        provider = Poisoned(None)
        provider.evaluate = lambda request: ProviderResult(
            {"claim_verdicts": [verdict(claim["id"]) for claim in request["claims"]],
             "issues": [issue(claim["id"], "insufficient") for claim in request["claims"]]},
            input_tokens=1, output_tokens=1)
        result = ContinuityEngine(provider).execute(payload)
        self.assertEqual((result["status"], result["error_code"]), ("failed", "conflict_evidence_insufficient"))
        self.assertNotIn("issues", result)


class UndecidedClaimsReachTheAuthorTests(unittest.TestCase):
    """The engine may report an undecided claim, but the author only learns of it if it is stored
    and served. A silent partial result would be worse than the failure it replaced."""

    def test_an_undecided_claim_is_persisted_and_served_in_run_metrics(self):
        class OneBadClaim:
            """Cites the evidence the request actually offered; poisons only the second claim."""

            available = True
            continuity_contract_version = "v6"
            label = model_label = "v17-api"
            # Review is deployed with thinking high, whose repair allowance is 9,000; on the bare
            # 6,000 default a four-claim repair does not fit and never reaches the contract at all.
            continuity_repair_input_budget_units = REVIEW_THINKING_REPAIR_INPUT_BUDGET_UNITS

            def evaluate(self, request):
                issues, verdicts = [], []
                for index, claim in enumerate(request["claims"], 1):
                    span = (claim["allowed_evidence"] or [None])[0]
                    verdicts.append(verdict(claim["id"]))
                    if span is None:
                        continue
                    sufficiency = "insufficient" if index == 2 else "sufficient"
                    issues.append({**issue(claim["id"], sufficiency),
                                   "evidence": [{"chapter_id": span["chapter_id"], "span_id": span["id"],
                                                 "relation": "contradicts", "sufficiency": sufficiency,
                                                 "related_memory_ids": []}],
                                   "evidence_chain": [{"span_id": span["id"], "role": "prior_state"}]})
                for row in verdicts:
                    if not any(item["claim_span_id"] == row["claim_span_id"] for item in issues):
                        row["verdict"] = "no_issue"
                return ProviderResult({"claim_verdicts": verdicts, "issues": issues}, input_tokens=1, output_tokens=1)

        root = pathlib.Path(tempfile.mkdtemp(prefix="v17-api-"))
        app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
                         provider=OneBadClaim(), executor=lambda fn, *args: fn(*args), settings=Stage13Settings.for_test())
        client = TestClient(app)
        idem = lambda: {"Idempotency-Key": str(uuid.uuid4())}
        registered = client.post("/api/auth/register", headers=idem(), json={
            "account_name": "undecidedclaims", "display_name": "Undecided", "password": "valid-password-99",
            "recovery_email": "undecided@example.test"}).json()["data"]
        project_id = registered["onboarding"]["tutorial"]["project_id"]
        draft = client.get(f"/api/projects/{project_id}").json()["data"]["current_draft"]
        run_id = client.post(f"/api/projects/{project_id}/checks", headers=idem(),
                             json={"draft_id": draft["id"], "draft_revision": draft["revision"]}).json()["data"]["run_id"]
        view = client.get(f"/api/projects/{project_id}/checks/{run_id}?include=issues,metrics").json()["data"]
        self.assertEqual(view["status"], "completed")
        self.assertEqual(view["metrics"]["undecided_claim_count"], len(view["metrics"]["undecided_claims"]))
        for row in view["metrics"]["undecided_claims"]:
            self.assertEqual(sorted(row), ["claim_span_id", "error_code"])
        client.close()


if __name__ == "__main__":
    unittest.main()
