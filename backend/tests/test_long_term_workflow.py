"""Isolated author workflow tests; all Provider data is explicitly injected."""
import json
import pathlib
import sqlite3
import tempfile
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.database import DomainError
from app.engine import ContinuityEngine, MemoryDeltaEngine
from app.long_term_workflow import commit_revision, preview_revision, resolve_review, review_state, set_reuse
from app.main import create_app
from app.provider import ProviderResult
from app.v2_database import V2Database


def key():
    return str(uuid.uuid4())


PROVENANCE = {name: "injected-workflow-fixture" for name in ("provider_label", "model_label", "prompt_version", "schema_version", "retrieval_method_version")}
ENV = {"PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3217", "BACKEND_ORIGIN": "http://127.0.0.1:8217", "TRUSTED_HOSTS": "127.0.0.1:8217,testserver", "TRUSTED_ORIGINS": "http://127.0.0.1:3217,http://testserver", "SCC_DISABLE_DEFAULT_APP": "1"}


def import_complete_fixture(db, user):
    """Exercise the real import/initialization contract using explicit fixtures."""
    text = "# 第一章 雾港调查\n林默是港口调查员。林默在雾港。\n# 第二章 罗盘交接\n林默将罗盘交给温岚保管。"
    imported, _ = db.preview_import(user, "complete-manuscript.txt", text.encode("utf-8"), key())
    committed, _ = db.commit_import(user, imported["import_id"], {"confirm": True, "title": "完整导入验收作品", "chapter_preview_ids": [row["preview_id"] for row in imported["detected"]["chapters"]]}, key())
    project = committed["project"]["id"]
    source_input = db.memory_initialization_input(user, project, 1)
    source = source_input["sources"][0]
    candidates = [{"memory_type": "static_canon", "subject": "林默", "predicate": "identity", "value": "港口调查员", "chapter_id": source["chapter_id"], "source_span_id": source["id"]}, {"memory_type": "dynamic_state", "subject": "林默", "predicate": "status", "value": "在雾港", "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]
    db.complete_memory_initialization(user, project, source_input, {"candidates": candidates}, PROVENANCE, key())
    initialization = db.memory_initialization(user, project)
    for candidate in initialization["candidates"]:
        db.decide_memory_candidate(user, project, initialization["id"], candidate["id"], {"decision": "accepted"}, key())
    db.commit_memory_initialization(user, project, initialization["id"], {"confirm": True}, key())
    draft = committed["project"]["current_draft"]
    db.patch_draft(user, project, draft["id"], {"base_revision": 1, "body": "林默说自己从未到过雾港。"}, key())
    return project


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="scc-long-term-")
        root = pathlib.Path(self.temp.name)
        self.paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected")
        self.db = V2Database(self.paths)
        self.db.initialize()
        registered, _ = self.db.register({"account_name": "workflow-author", "display_name": "Author", "password": "safe-workflow-password"}, key())
        self.user = registered["user"]["id"]
        self.tutorial_project = registered["onboarding"]["tutorial"]["project_id"]
        self.project = import_complete_fixture(self.db, self.user)
        with self.db.connection() as c:
            self.draft = dict(c.execute("SELECT * FROM v2_drafts WHERE project_id=? AND status IN ('draft','saved')", (self.project,)).fetchone())
            memory = c.execute("SELECT m.*,s.chapter_id FROM v2_memory_records m JOIN v2_source_spans s ON s.id=m.source_span_id WHERE m.project_id=? LIMIT 1", (self.project,)).fetchone()
            self.chapter_id = memory["chapter_id"]
            self.span = dict(c.execute("SELECT * FROM v2_source_spans WHERE id=?", (memory["source_span_id"],)).fetchone())
            self.memory_id = memory["id"]

    def tearDown(self):
        self.temp.cleanup()

    def state(self):
        return review_state(self.db, self.user, self.project)

    def dump(self):
        with self.db.connection() as c:
            return "\n".join(c.iterdump())

    def canon_memory(self):
        memory = self.db.memory(self.user, self.project, None)
        return {**memory, "records": [{key: value for key, value in row.items() if key not in {"requires_source_review", "source_is_current"}} for row in memory["records"]]}

    def check(self, different_evidence=False):
        created, _, _ = self.db.create_run(self.user, self.project, {"draft_id": self.draft["id"], "draft_revision": self.draft["revision"]}, key(), PROVENANCE)
        run_id = created["run_id"]
        data = self.db.run_input(self.project, run_id)
        excerpt = self.span["body"]
        if different_evidence:
            excerpt = excerpt[:max(1, len(excerpt) // 2)]
        issue = {"claim_span_id": data["claims"][0]["id"], "status": "conflict", "category": "continuity", "severity": "high", "evidence_status": "sufficient", "explanation": "Injected issue for author workflow testing", "evidence": [{"chapter_id": self.span["chapter_id"], "span_id": self.span["id"], "excerpt": excerpt, "relation": "contradicts", "sufficiency": "sufficient", "related_memory_ids": [self.memory_id]}]}
        self.db.finish_run(self.project, run_id, {"status": "completed", "issues": [issue]})
        return self.db.run_view(self.user, self.project, run_id, {"issues", "evidence"})

    def decided(self, decision="keep_intentional"):
        run = self.check()
        issue_id = run["issues"][0]["id"]
        self.db.decide(self.user, self.project, issue_id, {"run_id": run["run_id"], "source_revision": run["source_revision"], "decision": decision, "note": "作者已核实叙述视角。"}, key())
        return run, issue_id

    def preview(self, body=None, **extra):
        state = self.state()
        chapter = next(row for row in state["chapters"] if row["id"] == self.chapter_id)
        payload = {"base_source_revision": state["source_revision"], "base_chapter_revision": chapter["source_revision"], "title": chapter["title"], "body": body or chapter["body"] + "\n作者修订后的补充情节。", "body_format": chapter["body_format"]}
        payload.update(extra)
        data, status = preview_revision(self.db, self.user, self.project, self.chapter_id, payload, key())
        self.assertEqual(status, 201)
        return data["revision_preview"]

    def commit(self, preview):
        data, status = commit_revision(self.db, self.user, self.project, preview["id"], {"confirm": True, "content_sha256": preview["content_sha256"]}, key())
        self.assertEqual(status, 200)
        return data

    def resolve(self, review, decision="retain"):
        payload = {"confirm": True, "base_revision": review["revision"], "base_memory_version": self.state()["memory_version"], "decision": decision, "note": "逐条核对修订后的章节。"}
        if decision == "retain":
            payload["evidence_span_id"] = review["new_source_span_id"]
        return resolve_review(self.db, self.user, self.project, review["id"], payload, key())[0]

    def assert_error_zero_writes(self, code, operation):
        before = self.dump()
        with self.assertRaises(DomainError) as error:
            operation()
        self.assertEqual(error.exception.code, code)
        self.assertEqual(self.dump(), before)

    def test_repeat_run_preserves_visible_evidence_and_does_not_write_canon(self):
        _, issue_id = self.decided()
        eligible = next(row for row in self.state()["reusable_decisions"] if row["issue_id"] == issue_id)
        self.assertEqual((eligible["revision"], eligible["is_current"]), (0, True))
        before_memory = self.db.memory(self.user, self.project, None)
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        second = self.check()
        issue = second["issues"][0]
        self.assertEqual(issue["reused_decision"]["source_issue_id"], issue_id)
        self.assertEqual((issue["status"], issue["raw_issue_status"], issue["decision"]["reused"]), ("decided", "open", True))
        self.assertEqual(len(issue["evidence"]), 1)
        self.assertEqual(self.db.memory(self.user, self.project, None), before_memory)
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_decisions WHERE run_id=?", (second["run_id"],)).fetchone()[0], 0)

    def test_disable_and_explicit_reenable_restore_review_state(self):
        _, issue_id = self.decided("false_positive")
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        second = self.check()
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": False, "base_policy_revision": 1}, key())
        view = self.db.run_view(self.user, self.project, second["run_id"], {"issues", "evidence"})
        self.assertEqual(view["issues"][0]["status"], "open")
        self.assertIsNone(view["issues"][0]["reused_decision"])
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 2}, key())
        self.assertIsNotNone(self.db.run_view(self.user, self.project, second["run_id"], {"issues"})["issues"][0]["reused_decision"])

    def test_new_evidence_never_reuses_previous_author_decision(self):
        _, issue_id = self.decided()
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        second = self.check(different_evidence=True)
        self.assertIsNone(second["issues"][0]["reused_decision"])
        self.assertEqual(second["issues"][0]["status"], "open")

    def test_draft_edit_invalidates_policy_even_when_text_is_restored(self):
        _, issue_id = self.decided()
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        self.db.patch_draft(self.user, self.project, self.draft["id"], {"base_revision": self.draft["revision"], "body": self.draft["body"] + "修改。"}, key())
        self.db.patch_draft(self.user, self.project, self.draft["id"], {"base_revision": self.draft["revision"] + 1, "body": self.draft["body"]}, key())
        policy = next(row for row in self.state()["reusable_decisions"] if row["issue_id"] == issue_id)
        self.assertFalse(policy["is_current"])
        self.assertEqual(policy["invalidation_reason"], "draft_revision_changed")
        self.assert_error_zero_writes("decision_reuse_stale", lambda: set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 1}, key()))

    def test_source_revision_and_memory_version_invalidate_reuse(self):
        _, issue_id = self.decided()
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        result = self.commit(self.preview())
        policy = next(row for row in self.state()["reusable_decisions"] if row["issue_id"] == issue_id)
        self.assertFalse(policy["is_current"])
        for review in result["source_revision_reviews"]:
            self.resolve(review)
        self.assertGreater(self.state()["memory_version"], 1)
        self.assertFalse(next(row for row in self.state()["reusable_decisions"] if row["issue_id"] == issue_id)["is_current"])

    def test_reuse_auth_idempotency_and_revision_conflicts(self):
        _, issue_id = self.decided()
        payload = {"enabled": True, "base_policy_revision": 0}
        idem_key = key()
        first = set_reuse(self.db, self.user, self.project, issue_id, payload, idem_key)
        self.assertEqual(set_reuse(self.db, self.user, self.project, issue_id, payload, idem_key), first)
        self.assert_error_zero_writes("idempotency_conflict", lambda: set_reuse(self.db, self.user, self.project, issue_id, {"enabled": False, "base_policy_revision": 1}, idem_key))
        self.assert_error_zero_writes("decision_reuse_revision_conflict", lambda: set_reuse(self.db, self.user, self.project, issue_id, payload, key()))
        self.assert_error_zero_writes("resource_not_found", lambda: set_reuse(self.db, "outsider", self.project, issue_id, payload, key()))

    def test_preview_is_non_destructive_and_commit_preserves_old_spans(self):
        with self.db.connection() as c:
            original_chapter = dict(c.execute("SELECT * FROM v2_chapters WHERE id=?", (self.chapter_id,)).fetchone())
            original_spans = [dict(row) for row in c.execute("SELECT * FROM v2_source_spans WHERE chapter_id=?", (self.chapter_id,)).fetchall()]
        original_memory = self.canon_memory()
        preview = self.preview()
        self.assertGreater(preview["impact"]["affected_memory_count"], 0)
        with self.db.connection() as c:
            self.assertEqual(dict(c.execute("SELECT * FROM v2_chapters WHERE id=?", (self.chapter_id,)).fetchone()), original_chapter)
        result = self.commit(preview)
        self.assertEqual(result["source_change_set"]["mode"], "revise")
        self.assertEqual(self.canon_memory(), original_memory)
        pending_records = [row for row in self.db.memory(self.user, self.project, None)["records"] if row["requires_source_review"]]
        self.assertEqual(len(pending_records), len(result["source_revision_reviews"]))
        self.assertTrue(all(not row["source_is_current"] and row["review_status"] == "author_confirmed" for row in pending_records))
        with self.db.connection() as c:
            for old in original_spans:
                self.assertEqual(dict(c.execute("SELECT * FROM v2_source_spans WHERE id=?", (old["id"],)).fetchone()), old)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_chapter_revision_history WHERE chapter_id=?", (self.chapter_id,)).fetchone()[0], 2)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_chapters WHERE id=?", (self.chapter_id,)).fetchone()[0], 1)
        chapter = next(row for row in self.db.chapters(self.user, self.project, True)["chapters"] if row["id"] == self.chapter_id)
        self.assertTrue(any(not row["is_current"] for row in chapter["source_spans"]))
        self.assertTrue(any(row["is_current"] for row in chapter["source_spans"]))

    def test_revision_pending_blocks_all_ai_and_old_run_is_stale(self):
        run = self.check()
        result = self.commit(self.preview())
        self.assertTrue(self.db.run_view(self.user, self.project, run["run_id"], {"issues", "evidence"})["is_stale"])
        self.assertEqual(self.db.memory_coverage(self.user, self.project)["blocking_reason"], "source_revision_review_required")
        self.assert_error_zero_writes("source_revision_review_required", lambda: self.db.create_analysis_run(self.user, self.project, {"analysis_type": "context_brief", "draft_id": self.draft["id"], "draft_revision": self.draft["revision"]}, key(), PROVENANCE))
        self.assert_error_zero_writes("source_revision_review_required", lambda: self.db.create_incremental_runs(self.user, self.project, {"source_revision": 2}, key(), PROVENANCE, PROVENANCE))
        self.assertTrue(result["source_revision_reviews"])

    def test_each_fact_requires_explicit_current_evidence_then_new_version(self):
        result = self.commit(self.preview())
        review = result["source_revision_reviews"][0]
        base = self.state()["memory_version"]
        payload = {"confirm": True, "base_revision": 1, "base_memory_version": base, "decision": "retain", "note": "作者确认。", "evidence_span_id": self.span["id"]}
        self.assert_error_zero_writes("source_review_current_evidence_required", lambda: resolve_review(self.db, self.user, self.project, review["id"], payload, key()))
        payload["evidence_span_id"] = review["new_source_span_id"]
        idem_key = key()
        resolved = resolve_review(self.db, self.user, self.project, review["id"], payload, idem_key)
        self.assertEqual(resolve_review(self.db, self.user, self.project, review["id"], payload, idem_key), resolved)
        self.assertEqual(resolved[0]["memory_version"], base + 1)
        old = next(row for row in self.db.memory(self.user, self.project, base)["records"] if row["id"] == review["memory"]["id"])
        self.assertIn(old["source"]["span_id"], review["old_source_span_ids"])
        current = next(row for row in self.db.memory(self.user, self.project, base + 1)["records"] if row["id"].startswith(review["memory"]["id"]))
        self.assertEqual(current["source"]["span_id"], review["new_source_span_id"])
        self.assert_error_zero_writes("source_review_revision_conflict", lambda: resolve_review(self.db, self.user, self.project, review["id"], payload, key()))

    def test_invalidate_keeps_history_and_recovery_delta_uses_current_sources(self):
        result = self.commit(self.preview())
        for review in result["source_revision_reviews"]:
            self.resolve(review, "invalidate")
        self.assertEqual(self.db.memory_coverage(self.user, self.project)["blocking_reason"], "delta_review_required")
        created, _, _ = self.db.create_incremental_runs(self.user, self.project, {"source_revision": 2}, key(), PROVENANCE, PROVENANCE)
        continuity, delta = self.db.incremental_inputs(self.project, created["batch_id"])
        self.assertTrue(delta["sources"])
        self.assertNotIn(self.span["id"], [row["id"] for row in delta["sources"]])
        self.assertNotIn(self.memory_id, [row["id"] for row in continuity["memory"]])

    def test_bad_hash_confirmation_expiry_cross_account_are_atomic(self):
        preview = self.preview()
        for code, user, payload in [("source_hash_mismatch", self.user, {"confirm": True, "content_sha256": "f" * 64}), ("confirmation_required", self.user, {"confirm": False, "content_sha256": preview["content_sha256"]}), ("resource_not_found", "outsider", {"confirm": True, "content_sha256": preview["content_sha256"]})]:
            self.assert_error_zero_writes(code, lambda: commit_revision(self.db, user, self.project, preview["id"], payload, key()))
        with self.db.connection() as c:
            c.execute("UPDATE v2_source_change_sets SET expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (preview["id"],))
        self.assert_error_zero_writes("source_change_set_expired", lambda: self.commit(preview))

    def test_parallel_previews_have_one_commit_and_conflicting_commit_zero_writes(self):
        first, second = self.preview(body="甲版本。"), self.preview(body="乙版本。")
        def attempt(preview):
            try:
                return self.commit(preview)["revision_preview"]["id"]
            except DomainError as error:
                return error.code
        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(attempt, (first, second)))
        self.assertEqual(outcomes.count("source_revision_conflict"), 1)
        self.assertEqual(self.state()["source_revision"], 2)
        failed = second if outcomes[0] == first["id"] else first
        self.assert_error_zero_writes("source_revision_conflict", lambda: self.commit(failed))

    def test_revision_commit_replay_and_generic_append_route_rejected(self):
        preview = self.preview()
        self.assert_error_zero_writes("source_revision_commit_route_required", lambda: self.db.commit_source_change_set(self.user, self.project, preview["id"], {"confirm": True, "content_sha256": preview["content_sha256"]}, key()))
        result = self.commit(preview)
        self.assertEqual(self.commit(preview), result)

    def test_migration_restart_preserves_workflow_and_integrity(self):
        _, issue_id = self.decided()
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        result = self.commit(self.preview(body="**修订章节**\n作者保存 Markdown。", body_format="markdown"))
        before = self.state()
        restarted = V2Database(self.paths)
        restarted.initialize()
        restarted.initialize()
        self.assertEqual(review_state(restarted, self.user, self.project), before)
        with restarted.connection() as c:
            self.assertEqual(c.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(c.execute("SELECT body FROM v2_source_spans WHERE id=?", (result["source_revision_reviews"][0]["new_source_span_id"],)).fetchone()[0], "修订章节\n作者保存 Markdown。")

    def test_failed_mid_commit_rolls_back_chapter_span_revision_and_audit(self):
        preview = self.preview()
        with self.db.connection() as c:
            c.execute("CREATE TRIGGER injected_revision_failure BEFORE UPDATE OF source_revision ON v2_projects BEGIN SELECT RAISE(ABORT,'injected revision failure'); END")
        before = self.dump()
        with self.assertRaises(sqlite3.IntegrityError):
            self.commit(preview)
        self.assertEqual(self.dump(), before)
        with self.db.connection() as c:
            c.execute("DROP TRIGGER injected_revision_failure")
        self.assertEqual(self.commit(preview)["source_change_set"]["target_source_revision"], 2)

    def test_all_old_facts_can_be_retired_and_new_canon_review_completed(self):
        # A small imported work may have all facts linked to its only chapter.
        with self.db.connection() as c:
            c.execute("UPDATE v2_memory_records SET source_span_id=? WHERE project_id=?", (self.span["id"], self.project))
        result = self.commit(self.preview(body="林默现在是港口调查员。"))
        for review in result["source_revision_reviews"]:
            self.resolve(review, "invalidate")
        created, _, _ = self.db.create_incremental_runs(self.user, self.project, {"source_revision": 2}, key(), PROVENANCE, PROVENANCE)
        continuity_input, delta_input = self.db.incremental_inputs(self.project, created["batch_id"])
        self.assertEqual(delta_input["memory"], [])

        class NewFactProvider:
            available = True
            label = "injected-new-fact"
            model_label = "injected-new-fact"
            def evaluate(self, request):
                if request.get("task") == "memory_delta":
                    source = request["sources"][0]
                    return ProviderResult({"candidates": [{"change_kind": "new_fact", "affected_memory_id": None, "memory_type": "static_canon", "subject": "林默", "predicate": "identity", "value": "港口调查员", "invalidation_reason": None, "chapter_id": source["chapter_id"], "source_span_id": source["id"]}]})
                return ProviderResult({"issues": []})

        continuity = ContinuityEngine(NewFactProvider()).execute(continuity_input)
        delta = MemoryDeltaEngine(NewFactProvider()).execute(delta_input)
        self.assertEqual((continuity["status"], delta["status"]), ("completed", "completed"), delta)
        self.db.finish_incremental_runs(self.project, created["batch_id"], continuity, delta)
        view = self.db.memory_delta(self.user, self.project)
        candidate = view["candidates"][0]
        self.db.decide_memory_delta_candidate(self.user, self.project, created["batch_id"], candidate["id"], {"decision": "accepted"}, key())
        self.db.commit_memory_delta(self.user, self.project, created["batch_id"], {"confirm": True}, key())
        self.assertEqual(self.db.memory_coverage(self.user, self.project)["status"], "ready_current")
        current = self.db.memory(self.user, self.project, None)
        self.assertTrue(any(row["subject"] == "林默" and row["source_is_current"] for row in current["records"]))

    def test_revision_then_import_reset_preserves_text_and_source_history(self):
        self.commit(self.preview())
        chapter_before = next(row for row in self.state()["chapters"] if row["id"] == self.chapter_id)
        self.db.reset(self.user, self.project, {"confirm": True, "reason": "fresh_start"}, key())
        with self.db.connection() as c:
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_source_revision_reviews WHERE project_id=?", (self.project,)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_chapter_revision_history WHERE chapter_id=?", (self.chapter_id,)).fetchone()[0], 2)
        self.assertEqual(next(row for row in self.state()["chapters"] if row["id"] == self.chapter_id), chapter_before)

    def test_fragment_only_legacy_chapter_is_visible_and_cannot_be_revised(self):
        state = review_state(self.db, self.user, self.tutorial_project)
        chapter = state["chapters"][0]
        self.assertEqual(chapter["body_origin"], "source_fragments")
        self.assertFalse(chapter["revision_editable"])
        self.assertIn("未保存完整章节正文", chapter["body_notice"])
        self.assertTrue(chapter["body"].strip())
        with self.db.connection() as c:
            original = c.execute("SELECT body FROM v2_chapters WHERE id=?", (chapter["id"],)).fetchone()[0]
            fragments = [row[0] for row in c.execute("SELECT body FROM v2_source_spans WHERE project_id=? AND chapter_id=? AND source_revision=? ORDER BY rowid", (self.tutorial_project, chapter["id"], chapter["source_revision"])).fetchall()]
        self.assertEqual(original, "")
        self.assertEqual(chapter["body"], "\n\n".join(fragments))
        payload = {"base_source_revision": 1, "base_chapter_revision": chapter["source_revision"], "title": chapter["title"], "body": chapter["body"] + "试图覆盖片段。", "body_format": "plain_text"}
        self.assert_error_zero_writes("chapter_full_text_unavailable", lambda: preview_revision(self.db, self.user, self.tutorial_project, chapter["id"], payload, key()))

    def test_preexisting_preview_cannot_commit_without_complete_original_body(self):
        preview = self.preview()
        with self.db.connection() as c:
            c.execute("UPDATE v2_chapters SET body='' WHERE id=?", (self.chapter_id,))
        self.assert_error_zero_writes("chapter_full_text_unavailable", lambda: self.commit(preview))

    def test_expired_visitor_cleanup_handles_workflow_foreign_keys(self):
        _, issue_id = self.decided()
        set_reuse(self.db, self.user, self.project, issue_id, {"enabled": True, "base_policy_revision": 0}, key())
        self.commit(self.preview())
        class NoProvider:
            available = False
            label = "not_called"
        with patch.dict("os.environ", ENV):
            app = create_app(self.paths, provider=NoProvider(), executor=lambda *_: None)
        with self.db.connection() as c:
            c.execute("UPDATE v2_users SET account_type='visitor',visitor_expires_at='2000-01-01T00:00:00+00:00' WHERE id=?", (self.user,))
        app.state.stage13.cleanup_expired_visitors()
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_users WHERE id=?", (self.user,)).fetchone()[0], 0)
            self.assertEqual(c.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_revision_requires_completed_current_context_review(self):
        imported, _ = self.db.preview_import(self.user, "unreviewed.md", "# 未审阅章节\n林默在雾港。".encode("utf-8"), key())
        committed, _ = self.db.commit_import(self.user, imported["import_id"], {"confirm": True, "title": "尚未确认的作品", "chapter_preview_ids": [row["preview_id"] for row in imported["detected"]["chapters"]]}, key())
        project = committed["project"]["id"]
        state = review_state(self.db, self.user, project)
        chapter = state["chapters"][0]
        payload = {"base_source_revision": 1, "base_chapter_revision": 1, "title": chapter["title"], "body": "林默已离开雾港。", "body_format": "plain_text"}
        self.assert_error_zero_writes("source_revision_context_review_required", lambda: preview_revision(self.db, self.user, project, chapter["id"], payload, key()))
        revised = self.commit(self.preview())
        for review in revised["source_revision_reviews"]:
            self.resolve(review)
        self.assert_error_zero_writes("source_revision_context_review_required", lambda: self.preview(body="下一次修订。"))


class WorkflowApiTests(unittest.TestCase):
    def test_registered_routes_auth_csrf_and_validation(self):
        class NoProvider:
            available = False
            label = "not_called"
        with tempfile.TemporaryDirectory(prefix="scc-long-term-api-") as temp, patch.dict("os.environ", ENV):
            root = pathlib.Path(temp)
            app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=NoProvider(), executor=lambda *_: None)
            client = TestClient(app)
            registered = client.post("/api/auth/register", json={"account_name": "workflow-api-author", "display_name": "API", "password": "safe-api-password"}, headers={"Idempotency-Key": key()})
            self.assertEqual(registered.status_code, 201)
            project = import_complete_fixture(app.state.database, registered.json()["data"]["user"]["id"])
            endpoint = f"/api/projects/{project}/long-term-review"
            state = client.get(endpoint)
            self.assertEqual(state.status_code, 200, state.text)
            chapter = state.json()["data"]["chapters"][0]
            route = f"/api/projects/{project}/chapters/{chapter['id']}/revisions/preview"
            payload = {"base_source_revision": 1, "base_chapter_revision": 1, "title": chapter["title"], "body": chapter["body"] + "更改。"}
            self.assertEqual(client.post(route, json=payload, headers={"Idempotency-Key": key(), "Origin": "https://evil.example"}).status_code, 403)
            self.assertEqual(client.post(route, json={**payload, "base_source_revision": True}, headers={"Idempotency-Key": key()}).status_code, 400)
            preview_response = client.post(route, json=payload, headers={"Idempotency-Key": key()})
            self.assertEqual(preview_response.status_code, 201)
            preview = preview_response.json()["data"]["revision_preview"]
            committed = client.post(f"/api/projects/{project}/chapter-revisions/{preview['id']}/commit", json={"confirm": True, "content_sha256": preview["content_sha256"]}, headers={"Idempotency-Key": key()})
            self.assertEqual(committed.status_code, 200, committed.text)
            draft = client.get(f"/api/projects/{project}").json()["data"]["current_draft"]
            check_payload = {"draft_id": draft["id"], "draft_revision": draft["revision"]}
            with app.state.database.connection() as c:
                before_runs = c.execute("SELECT COUNT(*) FROM v2_runs WHERE project_id=?", (project,)).fetchone()[0]
            blocked_check = client.post(f"/api/projects/{project}/checks", json=check_payload, headers={"Idempotency-Key": key()})
            self.assertEqual(blocked_check.status_code, 409, blocked_check.text)
            self.assertEqual(blocked_check.json()["error"]["code"], "source_revision_review_required")
            with app.state.database.connection() as c:
                self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_runs WHERE project_id=?", (project,)).fetchone()[0], before_runs)
            outsider = TestClient(app)
            self.assertEqual(outsider.get(endpoint).status_code, 401)
            outsider.post("/api/auth/register", json={"account_name": "workflow-outsider", "display_name": "Other", "password": "safe-api-password"}, headers={"Idempotency-Key": key()})
            self.assertEqual(outsider.get(endpoint).status_code, 404)
            self.assertEqual(outsider.post(route, json=payload, headers={"Idempotency-Key": key()}).status_code, 404)
            self.assertEqual(outsider.post(f"/api/projects/{project}/checks", json=check_payload, headers={"Idempotency-Key": key()}).status_code, 404)


if __name__ == "__main__":
    unittest.main()
