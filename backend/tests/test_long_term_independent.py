"""Independent behavioral acceptance; all fixtures use disposable SQLite only."""
import json
import os
import unittest
from concurrent.futures import ThreadPoolExecutor

os.environ.setdefault("SCC_DISABLE_DEFAULT_APP", "1")

from app.database import DomainError
from app.long_term_workflow import resolve_review, set_reuse
from tests import test_long_term_workflow as fixtures


class IndependentLongTermTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.WorkflowTests()
        self.fixture.setUp()
        self.f = self.fixture

    def tearDown(self):
        self.fixture.tearDown()

    def expect_rejected_without_writes(self, operation, allowed_codes):
        before = self.f.dump()
        with self.assertRaises(DomainError) as caught:
            operation()
        self.assertIn(caught.exception.code, allowed_codes)
        self.assertEqual(self.f.dump(), before)

    def canon_change(self):
        f = self.f
        run = f.check()
        issue = run["issues"][0]
        with f.db.connection() as c:
            c.execute("UPDATE v2_issues SET proposed_change_json=? WHERE id=?", (json.dumps({
                "operation": "add", "memory_type": "static_canon", "subject": "独立验收人物",
                "predicate": "身份", "value": "旧来源提议的新事实",
            }, ensure_ascii=False), issue["id"]))
        f.db.decide(f.user, f.project, issue["id"], {
            "run_id": run["run_id"], "source_revision": run["source_revision"], "decision": "keep_intentional", "note": "独立验收决定。",
        }, fixtures.key())
        return f.db.create_changeset(f.user, f.project, {
            "run_id": run["run_id"], "source_run_revision": run["source_revision"], "resolved_revision": f.draft["revision"],
        }, fixtures.key())[0]["change_set"]

    def test_reuse_updates_all_pending_counts_and_disable_restores_them(self):
        f = self.f
        # Make the isolated tutorial visible to the regular home/project APIs.
        with f.db.connection() as c:
            c.execute("UPDATE v2_projects SET data_origin='user_created' WHERE id=?", (f.project,))
        _, issue_id = f.decided()
        baseline = f.db.project(f.user, f.project)["open_issue_count"]
        set_reuse(f.db, f.user, f.project, issue_id, {"enabled": True, "base_policy_revision": 0}, fixtures.key())
        second = f.check()
        self.assertIsNotNone(second["issues"][0]["reused_decision"])
        project = f.db.project(f.user, f.project)
        listed = next(item for item in f.db.list_projects(f.user, None, None, None, None)["projects"] if item["id"] == f.project)
        home = next(item for item in f.db.home(f.user)["pending_continuity"] if item["project_id"] == f.project)
        self.assertEqual((project["open_issue_count"], listed["open_issue_count"], home["open_count"]), (baseline,) * 3)
        set_reuse(f.db, f.user, f.project, issue_id, {"enabled": False, "base_policy_revision": 1}, fixtures.key())
        self.assertEqual(f.db.project(f.user, f.project)["open_issue_count"], baseline + 1)

    def test_old_prepared_canon_commit_is_blocked_while_revision_reviews_pending(self):
        f = self.f
        change = self.canon_change()
        revision = f.commit(f.preview())
        self.assertTrue(revision["source_revision_reviews"])
        self.expect_rejected_without_writes(lambda: f.db.commit_changeset(f.user, f.project, change["id"], {
            "confirm": True, "accepted_item_ids": [item["id"] for item in change["items"]], "rejected_item_ids": [],
        }, fixtures.key()), {"source_revision_review_required", "run_basis_changed", "lineage_invalid_requires_recheck"})

    def test_old_run_cannot_receive_decisions_after_revision_fact_reviews_finish(self):
        f = self.f
        run = f.check()
        revision = f.commit(f.preview())
        for review in revision["source_revision_reviews"]:
            f.resolve(review, "retain")
        self.assertTrue(f.db.run_view(f.user, f.project, run["run_id"], {"issues", "evidence"})["is_stale"])
        self.expect_rejected_without_writes(lambda: f.db.decide(f.user, f.project, run["issues"][0]["id"], {
            "run_id": run["run_id"], "source_revision": run["source_revision"], "decision": "false_positive", "note": "不能把过时审阅作为当前决定。",
        }, fixtures.key()), {"run_basis_changed", "lineage_invalid_requires_recheck"})

    def test_new_canon_proposal_from_old_run_is_rejected_after_source_change(self):
        f = self.f
        run, _ = f.decided()
        with f.db.connection() as c:
            c.execute("UPDATE v2_issues SET proposed_change_json=? WHERE id=?", (json.dumps({
                "operation": "add", "memory_type": "static_canon", "subject": "人物", "predicate": "身份", "value": "旧提议",
            }), run["issues"][0]["id"]))
        revision = f.commit(f.preview())
        for review in revision["source_revision_reviews"]:
            f.resolve(review, "invalidate")
        self.expect_rejected_without_writes(lambda: f.db.create_changeset(f.user, f.project, {
            "run_id": run["run_id"], "source_run_revision": run["source_revision"], "resolved_revision": f.draft["revision"],
        }, fixtures.key()), {"run_basis_changed", "lineage_invalid_requires_recheck"})

    def test_foreign_project_review_ids_do_not_cross_same_account_boundaries(self):
        f = self.f
        review = f.commit(f.preview())["source_revision_reviews"][0]
        other = f.db.create_project(f.user, {"title": "独立隔离作品"}, fixtures.key())[0]["project"]["id"]
        self.expect_rejected_without_writes(lambda: resolve_review(f.db, f.user, other, review["id"], {
            "confirm": True, "base_revision": review["revision"], "base_memory_version": 1, "decision": "invalidate", "note": "跨作品请求",
        }, fixtures.key()), {"resource_not_found"})

    def test_competing_retain_and_invalidate_have_one_durable_decision(self):
        f = self.f
        review = f.commit(f.preview())["source_revision_reviews"][0]
        version = f.state()["memory_version"]
        def apply(decision):
            try:
                return resolve_review(f.db, f.user, f.project, review["id"], {
                    "confirm": True, "base_revision": review["revision"], "base_memory_version": version,
                    "decision": decision, "note": "并发复核决定", "evidence_span_id": review["new_source_span_id"],
                }, fixtures.key())[0]
            except DomainError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as executor:
            outcomes = list(executor.map(apply, ("retain", "invalidate")))
        self.assertEqual(outcomes.count("source_review_revision_conflict"), 1)
        self.assertEqual(f.state()["memory_version"], version + 1)
        with f.db.connection() as c:
            self.assertEqual(c.execute("SELECT revision FROM v2_source_revision_reviews WHERE id=?", (review["id"],)).fetchone()[0], 2)
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_changed_author_context_never_reuses_prior_decision(self):
        f = self.f
        _, issue_id = f.decided()
        set_reuse(f.db, f.user, f.project, issue_id, {"enabled": True, "base_policy_revision": 0}, fixtures.key())
        with f.db.connection() as c:
            c.execute("UPDATE v2_projects SET author_context_version=author_context_version+1 WHERE id=?", (f.project,))
        policy = next(item for item in f.state()["reusable_decisions"] if item["issue_id"] == issue_id)
        self.assertFalse(policy["is_current"])
        self.expect_rejected_without_writes(lambda: set_reuse(f.db, f.user, f.project, issue_id, {
            "enabled": True, "base_policy_revision": 1,
        }, fixtures.key()), {"decision_reuse_stale"})

    def test_pending_state_is_not_disclosed_to_other_accounts(self):
        f = self.f
        self.assertTrue(f.commit(f.preview())["source_revision_reviews"])
        self.expect_rejected_without_writes(lambda: f.db.create_author_comparison_analysis(
            "another-account", f.project, "any-comparison-id", {"base_decision_revision": 0},
            fixtures.key(), fixtures.PROVENANCE,
        ), {"resource_not_found"})

    def test_queued_analysis_cannot_send_old_sources_after_revision_review(self):
        f = self.f
        created, _, _ = f.db.create_analysis_run(f.user, f.project, {
            "analysis_type": "context_brief", "draft_id": f.draft["id"], "draft_revision": f.draft["revision"],
        }, fixtures.key(), fixtures.PROVENANCE)
        revision = f.commit(f.preview())
        for review in revision["source_revision_reviews"]:
            f.resolve(review, "retain")
        self.expect_rejected_without_writes(lambda: f.db.analysis_run_input(f.project, created["run_id"]),
                                            {"run_basis_changed", "source_revision_review_required"})

    def test_different_proposed_fact_is_not_hidden_by_previous_reuse(self):
        f = self.f
        _, issue_id = f.decided("false_positive")
        set_reuse(f.db, f.user, f.project, issue_id, {"enabled": True, "base_policy_revision": 0}, fixtures.key())
        run = f.check()
        with f.db.connection() as c:
            # A second provider issue cites the same passage but proposes a
            # different fact/correction. This requires a fresh author decision.
            c.execute("UPDATE v2_issues SET proposed_change_json=? WHERE id=?", (json.dumps({
                "operation": "add", "memory_type": "static_canon", "subject": "另一人物",
                "predicate": "知情边界", "value": "不应由前次作者决定自动跳过的另一事实",
            }, ensure_ascii=False), run["issues"][0]["id"]))
        issue = f.db.run_view(f.user, f.project, run["run_id"], {"issues", "evidence"})["issues"][0]
        self.assertIsNone(issue["reused_decision"])
        self.assertEqual(issue["status"], "open")


if __name__ == "__main__":
    unittest.main()
