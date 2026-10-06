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

    def timeline(self):
        response = self.client.get(f"/api/projects/{self.project_id}/chapter-timeline")
        self.assertEqual(response.status_code, 200, response.text)
        return {(row["chapter_number"], row["draft"]): row["status"] for row in response.json()["data"]["chapters"]}

    def test_the_timeline_lists_every_chapter_then_the_draft_with_check_status(self):
        before = self.timeline()
        self.assertEqual([key for key in before], [(n, False) for n in range(1, 11)] + [(11, True)])
        # The sample's preset review is not a check of the written chapters.
        self.assertEqual(set(before[(n, False)] for n in range(1, 11)), {"unchecked"})
        self.assertEqual(self.start([2, 9]).status_code, 202)
        after = self.timeline()
        self.assertEqual((after[(2, False)], after[(9, False)], after[(3, False)]), ("checked", "checked", "unchecked"))
        with self.app.state.database.connection() as c:
            # Revising chapter 1 later changes the basis of both checks.
            c.execute("INSERT INTO v2_chapter_revision_history VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (self.project_id, self.chapters[1], 2, "雾钟", "", "改过的正文。", "plain_text", "[]", "sourcechangeset-test", "9999-01-01T00:00:00+00:00"))
            # Revising chapter 9 itself leaves its new text unchecked.
            chapter9 = c.execute("SELECT * FROM v2_chapters WHERE id=?", (self.chapters[9],)).fetchone()
            c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,?,?,?)", ("span-test-ch9-r2", self.project_id, self.chapters[9], "chapter_revision", "改过的第九章。", chapter9["source_revision"] + 1))
            c.execute("UPDATE v2_chapters SET source_revision=? WHERE id=?", (chapter9["source_revision"] + 1, self.chapters[9]))
        revised = self.timeline()
        self.assertEqual((revised[(2, False)], revised[(9, False)]), ("basis_changed", "edited_unchecked"))

    def test_a_checked_draft_and_the_chapter_it_becomes_count_as_checked(self):
        draft = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]
        saved = self.client.patch(f"/api/projects/{self.project_id}/drafts/{draft['id']}", headers=self.idem(),
                                  json={"title": "第十一章", "body": "温岚把黄铜罗盘放进档案室的抽屉。", "base_revision": draft["revision"]}).json()["data"]
        self.assertEqual(self.timeline()[(11, True)], "unchecked")
        check = self.client.post(f"/api/projects/{self.project_id}/checks", headers=self.idem(), json={"draft_id": saved["id"], "draft_revision": saved["revision"]})
        self.assertEqual(check.status_code, 202, check.text)
        self.assertEqual(self.timeline()[(11, True)], "checked")
        # Completing the checked revision into chapter 11 carries the check over to the chapter.
        project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        preview = self.client.post(f"/api/projects/{self.project_id}/source-change-sets/preview", headers=self.idem(), json={
            "mode": "append", "input_method": "draft_complete", "base_source_revision": project["source_revision"], "draft_id": saved["id"]})
        self.assertEqual(preview.status_code, 201, preview.text)
        change = preview.json()["data"]["source_change_set"]
        committed = self.client.post(f"/api/projects/{self.project_id}/source-change-sets/{change['id']}/commit", headers=self.idem(),
                                     json={"confirm": True, "content_sha256": change["content_sha256"]})
        self.assertEqual(committed.status_code, 200, committed.text)
        after = self.timeline()
        self.assertEqual((after[(11, False)], after[(12, True)]), ("checked", "empty"))
        # Saving a new revision of a checked draft makes it edited since its check.
        next_draft = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]
        self.assertEqual(next_draft["chapter_number"], 12)

    def test_an_estimate_spends_nothing(self):
        response = self.client.post(f"/api/projects/{self.project_id}/chapter-checks/estimate", headers=self.idem(),
                                    json={"chapter_ids": [self.chapters[2], self.chapters[9]]})
        self.assertEqual(response.status_code, 200, response.text)
        data = response.json()["data"]
        self.assertEqual(data["characters"], written_chars(self.span_text[2]) + written_chars(self.span_text[9]))
        self.assertEqual(data["estimated_cny"], round(data["characters"] / 1000 * 0.085, 2))
        self.assertEqual(self.client.get("/api/account/usage").json()["data"]["check_chars_used"], 0)
        self.assertEqual(self.provider.requests, [])

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
        # They see a labelled sample instead: the open fog-bell mystery, against chapter 1's rule.
        runs = guest.get(f"/api/projects/{project_id}/chapter-checks").json()["data"]["runs"]
        sample = [run for run in runs if run["sample"]]
        self.assertEqual(len(sample), 1)
        report = sample[0]["report"]
        self.assertEqual([row["chapter_number"] for row in report["chapters"]], [9, 10])
        issue = report["chapters"][1]["issues"][0]
        self.assertEqual((issue["nature"], issue["category"], issue["evidence"][0]["chapter_number"]), ("possible_conflict", "world_rule", 1))


if __name__ == "__main__":
    unittest.main()


class ImportedTextIsEnoughContextTests(unittest.TestCase):
    """v1.6.0: an imported work can be checked before its fact base is built or reviewed."""

    def setUp(self):
        from tests.test_stage9_memory_initialization import Stage9MemoryInitializationTests
        self.stage9 = Stage9MemoryInitializationTests("test_import_initialize_decide_commit_v1_then_first_check")
        self.stage9.setUp()
        self.addCleanup(self.stage9.tearDown)

    def test_the_screened_pipeline_needs_only_written_text(self):
        db = self.stage9.app.state.database
        project_id = self.stage9.imported_project()
        user_id = self.stage9.client.get("/api/auth/session").json()["data"]["user"]["id"]
        draft = self.stage9.client.get(f"/api/projects/{project_id}").json()["data"]["current_draft"]
        saved = self.stage9.client.patch(f"/api/projects/{project_id}/drafts/{draft['id']}", headers={"Idempotency-Key": str(uuid.uuid4())},
                                         json={"title": "新章", "body": "林默推开港务局的门。", "base_revision": draft["revision"]}).json()["data"]
        coverage = self.stage9.client.get(f"/api/projects/{project_id}/memory/coverage").json()["data"]
        self.assertEqual(coverage["status"], "required")
        db.check_preflight(user_id, project_id, saved["id"], saved["revision"], screened=True)
        with self.assertRaises(Exception) as caught:
            db.check_preflight(user_id, project_id, saved["id"], saved["revision"], screened=False)
        self.assertEqual(getattr(caught.exception, "code", None), "insufficient_project_context")
        # A work with no written text at all still has nothing to check against.
        with db.connection() as c:
            c.execute("UPDATE v2_source_spans SET body='' WHERE project_id=?", (project_id,))
        with self.assertRaises(Exception) as empty:
            db.check_preflight(user_id, project_id, saved["id"], saved["revision"], screened=True)
        self.assertEqual(getattr(empty.exception, "code", None), "insufficient_project_context")
