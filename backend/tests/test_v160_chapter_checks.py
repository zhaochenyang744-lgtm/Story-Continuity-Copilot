"""Checking chosen written chapters (v1.6.0): up to eight at once, each against earlier chapters only,
reported per chapter, spending the author's daily check characters; not open to visitors."""
from __future__ import annotations

import dataclasses
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings
from app.text_content import written_chars

from tests.test_lf_screened_review import issue


class CompassReviewer:
    """Flags every sentence about the compass and reports it against the first passage it may cite."""
    available = True
    continuity_contract_version = "v6"
    label = model_label = "chapter-check-fake"

    def __init__(self):
        self.requests = []

    def evaluate(self, request):
        self.requests.append(request)
        if request.get("task") == "continuity_screen":
            return ProviderResult({"flags": [{"id": s["id"], "kind": "conflict", "facts": []} for s in request["sentences"] if "罗盘" in s["text"]]}, input_tokens=1, output_tokens=1)
        if request.get("task") == "continuity_triage":
            return ProviderResult({"scores": [{"id": s["id"], "score": 0} for s in request["sentences"]]}, input_tokens=1, output_tokens=1)
        issues, verdicts = [], []
        for claim in request["claims"]:
            found = "罗盘" in claim["text"] and claim["allowed_evidence"]
            if found:
                issues.append(issue(claim, claim["allowed_evidence"][0]))
            verdicts.append({"claim_span_id": claim["id"], "verdict": "reviewed_issue" if found else "no_issue", "basis": "依据早前段落判断。"})
        return ProviderResult({"issues": issues, "claim_verdicts": verdicts}, input_tokens=10, output_tokens=5)


class ChapterCheckTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="v160-chapter-check-"))
        self.provider = CompassReviewer()
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=self.provider,
                              executor=lambda fn, *args: fn(*args), settings=dataclasses.replace(Stage13Settings.for_test()))
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)
        registered = self.client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": f"cc{uuid.uuid4().hex[:8]}", "display_name": "CC", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        self.project_id = registered["onboarding"]["tutorial"]["project_id"]
        with self.app.state.database.connection() as c:
            self.chapters = {row["chapter_number"]: row["id"] for row in c.execute("SELECT id,chapter_number FROM v2_chapters WHERE project_id=?", (self.project_id,))}
            self.span_text = {row["chapter_number"]: row["body"] for row in c.execute(
                "SELECT s.body,ch.chapter_number FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE s.project_id=?", (self.project_id,))}

    @staticmethod
    def idem():
        return {"Idempotency-Key": str(uuid.uuid4())}

    def start(self, numbers):
        return self.client.post(f"/api/projects/{self.project_id}/chapter-checks", headers=self.idem(),
                                json={"chapter_ids": [self.chapters[number] for number in numbers]})

    def test_chosen_chapters_are_checked_and_reported_per_chapter(self):
        response = self.start([2, 9])
        self.assertEqual(response.status_code, 202, response.text)
        runs = self.client.get(f"/api/projects/{self.project_id}/chapter-checks").json()["data"]["runs"]
        self.assertEqual(runs[0]["status"], "completed", runs[0])
        report = runs[0]["report"]
        self.assertEqual([row["chapter_number"] for row in report["chapters"]], [2, 9])
        chapter9 = report["chapters"][1]
        self.assertEqual(len(chapter9["issues"]), 1)
        self.assertIn("罗盘", chapter9["issues"][0]["sentence"])
        # Chapter 9's evidence comes from an earlier chapter only; chapter 2 has nothing earlier about the compass.
        self.assertTrue(all(item["chapter_number"] < 9 for item in chapter9["issues"][0]["evidence"]))
        self.assertTrue(all(item["chapter_number"] < 2 for row in report["chapters"][0]["issues"] for item in row["evidence"]))
        self.assertEqual(report["issue_count"], sum(len(row["issues"]) for row in report["chapters"]))

    def test_a_check_spends_the_chosen_chapters_characters(self):
        self.assertEqual(self.start([2, 9]).status_code, 202)
        usage = self.client.get("/api/account/usage").json()["data"]
        self.assertEqual(usage["check_chars_used"], written_chars(self.span_text[2]) + written_chars(self.span_text[9]))

    def test_at_most_eight_chapters(self):
        response = self.start(list(range(1, 10)))
        self.assertEqual(response.status_code, 400, response.text)  # request validation answers 400 invalid_request
        self.assertEqual(self.provider.requests, [])

    def test_a_chapter_of_another_project_is_refused(self):
        response = self.client.post(f"/api/projects/{self.project_id}/chapter-checks", headers=self.idem(), json={"chapter_ids": ["ch-not-here"]})
        self.assertEqual(response.status_code, 422, response.text)
        self.assertEqual(response.json()["error"]["code"], "chapter_selection_invalid")

    def test_visitors_cannot_run_it(self):
        guest = TestClient(self.app)
        self.addCleanup(guest.close)
        self.assertEqual(guest.post("/api/auth/visitor", headers=self.idem()).status_code, 201)
        with self.app.state.database.connection() as c:
            visitor_id = c.execute("SELECT id FROM v2_users WHERE account_type='visitor'").fetchone()["id"]
            project_id = c.execute("SELECT id FROM v2_projects WHERE user_id=? AND seed_key='grey_harbor'", (visitor_id,)).fetchone()["id"]
            chapter_id = c.execute("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", (project_id,)).fetchone()["id"]
        response = guest.post(f"/api/projects/{project_id}/chapter-checks", headers=self.idem(), json={"chapter_ids": [chapter_id]})
        self.assertEqual(response.status_code, 403, response.text)
        self.assertEqual(response.json()["error"]["code"], "visitor_chapter_check_unavailable")


if __name__ == "__main__":
    unittest.main()
