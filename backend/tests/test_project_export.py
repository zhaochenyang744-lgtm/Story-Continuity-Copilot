from __future__ import annotations

import hashlib
import io
import json
import os
import pathlib
import tempfile
import unittest
import uuid
import zipfile
from unittest.mock import patch

from fastapi.testclient import TestClient

os.environ.setdefault("SCC_DISABLE_DEFAULT_APP", "1")

from app.config import AppPaths
from app.database import DomainError
from app.main import COOKIE, create_app
from app.project_export import export_content, export_filename, project_snapshot, register_project_export_routes


def idem():
    return {"Idempotency-Key": str(uuid.uuid4())}


class NoNetworkProvider:
    label = "export-test-stub"
    model_label = "export-test-stub"
    available = True

    def evaluate(self, request):
        raise AssertionError("Export must never invoke a provider")


class ProjectExportTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {
            "PUBLIC_APP_MODE": "0", "PUBLIC_BASE_URL": "http://127.0.0.1:3080",
            "BACKEND_ORIGIN": "http://127.0.0.1:8080", "TRUSTED_HOSTS": "127.0.0.1:8080,testserver",
            "TRUSTED_ORIGINS": "http://127.0.0.1:3080,http://testserver",
        })
        self.env.start()
        self.temp = tempfile.TemporaryDirectory(prefix="scc-project-export-")
        root = pathlib.Path(self.temp.name)
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=NoNetworkProvider())
        self.db = self.app.state.database
        if not any(getattr(route, "path", None) == "/api/projects/{project_id}/export" for route in self.app.routes):
            register_project_export_routes(self.app, self.db, lambda request: self.db.session_user(request.cookies.get(COOKIE)))
        self.client = TestClient(self.app)
        response = self.client.post("/api/auth/register", headers=idem(), json={
            "account_name": "export-author", "display_name": "Export", "password": "private-export-password-123",
        })
        self.assertEqual(response.status_code, 201, response.text)
        data = response.json()["data"]
        self.user_id = data["user"]["id"]
        self.project_id = data["onboarding"]["tutorial"]["project_id"]
        self.url = f"/api/projects/{self.project_id}/export"
        self.draft_id = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]["id"]

    def tearDown(self):
        self.client.close()
        self.app.state.recovery_executor.shutdown(wait=True)
        self.temp.cleanup()
        self.env.stop()

    def bundle(self, include_draft=False):
        response = self.client.get(self.url, params={"format": "bundle", "include_draft": str(include_draft).lower()})
        self.assertEqual(response.status_code, 200, response.text if response.status_code != 200 else "")
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        return response, archive, json.loads(archive.read("snapshot.json"))

    def save_draft(self, body, body_format="plain_text"):
        response = self.client.patch(
            f"/api/projects/{self.project_id}/drafts/{self.draft_id}", headers=idem(),
            json={"base_revision": 1, "body": body, "body_format": body_format},
        )
        self.assertEqual(response.status_code, 200, response.text)

    def test_zip_manifest_hashes_scope_and_no_credentials(self):
        response, archive, snapshot = self.bundle()
        expected = {"README.txt", "manuscript.txt", "manuscript.md", "materials.md", "snapshot.json", "checksums.json"}
        self.assertEqual(set(archive.namelist()), expected)
        self.assertIsNone(archive.testzip())
        for name, checksum in json.loads(archive.read("checksums.json")).items():
            self.assertEqual(hashlib.sha256(archive.read(name)).hexdigest(), checksum)
        self.assertEqual(snapshot["drafts"], [])
        self.assertFalse(snapshot["scope"]["unsaved_browser_edits_included"])
        stored_digest = snapshot.pop("snapshot_sha256")
        snapshot.pop("exported_at")
        canonical = (json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
        self.assertEqual(stored_digest, hashlib.sha256(canonical).hexdigest())
        self.assertEqual(response.headers["X-Export-Snapshot-SHA256"], stored_digest)
        for name in archive.namelist():
            for secret in (b"private-export-password", b"password_hash", b"recovery_email", b"token_hash", b"scc_local_session", b"export-author"):
                self.assertNotIn(secret, archive.read(name))
            self.assertFalse(pathlib.PurePosixPath(name).is_absolute())
            self.assertNotIn("..", pathlib.PurePosixPath(name).parts)
        self.assertEqual(response.headers["Cache-Control"], "no-store, private")
        self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
        self.assertIn("attachment;", response.headers["Content-Disposition"])

    def test_every_format_requires_session_and_project_owner(self):
        anonymous = TestClient(self.app)
        try:
            for format in ("txt", "markdown", "bundle"):
                self.assertEqual(anonymous.get(self.url, params={"format": format}).status_code, 401)
            response = anonymous.post("/api/auth/register", headers=idem(), json={
                "account_name": "another-author", "display_name": "Other", "password": "another-safe-password-123",
            })
            self.assertEqual(response.status_code, 201)
            for format in ("txt", "markdown", "bundle"):
                self.assertEqual(anonymous.get(self.url, params={"format": format}).status_code, 404)
        finally:
            anonymous.close()

    def test_same_owner_projects_are_isolated(self):
        response = self.client.post("/api/projects", json={"title": "OTHER_PROJECT_TITLE"}, headers=idem())
        self.assertEqual(response.status_code, 201, response.text)
        other = response.json()["data"]["project"]["id"]
        with self.db.connection() as c:
            c.execute("UPDATE v2_drafts SET body='OTHER_PROJECT_PRIVATE_BODY' WHERE project_id=?", (other,))
        _, archive, _ = self.bundle(True)
        for name in archive.namelist():
            self.assertNotIn(b"OTHER_PROJECT_", archive.read(name))

    def test_full_text_order_empty_lines_and_unicode_are_preserved(self):
        first = "正文一𠮷🙂\n\n\n保留空行和 **字面星号**。\n"
        second = "正文二" * 75_000 + "\nEND_OF_LARGE_CHAPTER"
        with self.db.connection() as c:
            rows = c.execute("SELECT id FROM v2_chapters WHERE project_id=? ORDER BY chapter_number", (self.project_id,)).fetchall()
            self.assertGreaterEqual(len(rows), 2)
            c.execute("UPDATE v2_chapters SET body=? WHERE id=?", (first, rows[0]["id"]))
            c.execute("UPDATE v2_chapters SET body=? WHERE id=?", (second, rows[1]["id"]))
        _, archive, snapshot = self.bundle()
        text = archive.read("manuscript.txt").decode()
        self.assertIn(first, text)
        self.assertIn(second, text)
        self.assertLess(text.index(first), text.index(second))
        self.assertEqual(snapshot["chapters"][0]["body"], first)
        self.assertIn("\\*\\*字面星号\\*\\*", archive.read("manuscript.md").decode())
        self.assertEqual([ch["chapter_number"] for ch in snapshot["chapters"]], sorted(ch["chapter_number"] for ch in snapshot["chapters"]))
        self.assertEqual(snapshot["chapters"][0]["body_origin"], "chapter_body")
        self.assertTrue(snapshot["chapters"][0]["has_complete_body"])
        self.assertEqual(snapshot["chapters"][0]["source_fragments"], [])

    def test_fragment_only_chapters_keep_raw_body_and_order_with_explicit_incomplete_labels(self):
        with self.db.connection() as c:
            chapter = c.execute("SELECT * FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", (self.project_id,)).fetchone()
            self.assertEqual(chapter["body"], "")
            c.execute("UPDATE v2_source_spans SET source_revision=999 WHERE chapter_id=?", (chapter["id"],))
            for span_id, marker in [("z-export-first-fragment", "FIRST_FRAGMENT_ONLY"),
                                    ("a-export-second-fragment", "SECOND_FRAGMENT_ONLY")]:
                c.execute("INSERT INTO v2_source_spans VALUES(?,?,?,'片段',?,?)",
                          (span_id, self.project_id, chapter["id"], marker, chapter["source_revision"]))
        _, archive, snapshot = self.bundle()
        exported = snapshot["chapters"][0]
        self.assertEqual(exported["body"], "")
        self.assertEqual(exported["body_origin"], "source_fragments")
        self.assertFalse(exported["has_complete_body"])
        self.assertEqual([source["id"] for source in exported["source_fragments"]],
                         ["z-export-first-fragment", "a-export-second-fragment"])
        self.assertEqual(snapshot["completeness"]["status"], "partial_stored_chapters")
        self.assertFalse(snapshot["completeness"]["all_committed_chapter_bodies_present"])
        self.assertGreater(snapshot["completeness"]["fragment_only_chapters"], 0)
        for name in ("manuscript.txt", "manuscript.md"):
            text = archive.read(name).decode()
            self.assertIn("来源片段，非完整章节", text)
            self.assertIn("不能视为完整作品原稿", text)
            self.assertLess(text.index("FIRST"), text.index("SECOND"))
            self.assertEqual(text.count("FIRST"), 1)
        self.assertIn("不能视为完整作品原稿", archive.read("README.txt").decode())

    def test_missing_and_complete_body_statuses_are_distinct(self):
        with self.db.connection() as c:
            chapter = c.execute("SELECT * FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", (self.project_id,)).fetchone()
            c.execute("UPDATE v2_chapters SET source_revision=999 WHERE id=?", (chapter["id"],))
        _, archive, snapshot = self.bundle()
        self.assertEqual(snapshot["chapters"][0]["body_origin"], "unavailable")
        self.assertEqual(snapshot["completeness"]["missing_body_chapters"], 1)
        self.assertIn("完整正文缺失", archive.read("manuscript.txt").decode())
        with self.db.connection() as c:
            c.execute("UPDATE v2_chapters SET body='真正保存的正文\\n\\n保留段落' WHERE project_id=?", (self.project_id,))
        _, archive, snapshot = self.bundle()
        self.assertEqual(snapshot["completeness"]["status"], "complete_stored_chapters")
        self.assertTrue(snapshot["completeness"]["all_committed_chapter_bodies_present"])
        self.assertNotIn("不能视为完整作品原稿", archive.read("manuscript.txt").decode())
        self.assertTrue(all(chapter["body_origin"] == "chapter_body" for chapter in snapshot["chapters"]))

    def test_saved_draft_is_opt_in_and_marked_separately(self):
        marker = "DRAFT_ONLY_CURRENT_SAVED_BODY"
        self.save_draft(marker)
        self.assertNotIn(marker, self.client.get(self.url, params={"format": "txt"}).text)
        _, archive, snapshot = self.bundle(True)
        self.assertEqual(len(snapshot["drafts"]), 1)
        self.assertEqual(snapshot["drafts"][0]["body"], marker)
        self.assertIn("未入库草稿", archive.read("manuscript.txt").decode())
        self.assertEqual(archive.read("manuscript.txt").decode().count(marker), 1)

    def test_completed_rich_draft_is_not_duplicated_and_formats_are_preserved(self):
        body = "> 引用\n\n- 第一项\n- 第二项\n\n**粗体词**与*斜体词*。"
        self.save_draft(body, "markdown")
        revision = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["source_revision"]
        preview = self.client.post(f"/api/projects/{self.project_id}/source-change-sets/preview", headers=idem(), json={
            "mode": "append", "input_method": "draft_complete", "base_source_revision": revision, "draft_id": self.draft_id,
        })
        self.assertEqual(preview.status_code, 201, preview.text)
        change = preview.json()["data"]["source_change_set"]
        response = self.client.post(f"/api/projects/{self.project_id}/source-change-sets/{change['id']}/commit", headers=idem(), json={
            "confirm": True, "content_sha256": change["content_sha256"],
        })
        self.assertEqual(response.status_code, 200, response.text)
        _, archive, snapshot = self.bundle(True)
        self.assertEqual(snapshot["chapters"][-1]["body"], body)
        self.assertEqual(snapshot["chapters"][-1]["body_format"], "markdown")
        self.assertEqual(snapshot["drafts"], [])
        self.assertEqual(archive.read("manuscript.md").decode().count(body), 1)
        self.assertIn("粗体词与斜体词", archive.read("manuscript.txt").decode())
        self.assertNotIn("**粗体词**", archive.read("manuscript.txt").decode())

    def test_overlap_is_rejected_instead_of_silently_duplicating_body(self):
        with self.db.connection() as c:
            number = c.execute("SELECT MIN(chapter_number) FROM v2_chapters WHERE project_id=?", (self.project_id,)).fetchone()[0]
            c.execute("UPDATE v2_drafts SET chapter_number=?,body='overlap' WHERE id=?", (number, self.draft_id))
        self.assertEqual(self.client.get(self.url, params={"include_draft": "true"}).status_code, 409)
        self.assertEqual(self.client.get(self.url).status_code, 200)

    def test_path_inputs_invalid_format_and_invalid_boolean_are_rejected(self):
        for params in ({"filename": "../../secret.txt"}, {"path": "C:\\secret"}):
            self.assertEqual(self.client.get(self.url, params=params).status_code, 422)
        # The app's established RequestValidationError handler uses HTTP 400.
        for params in ({"format": "../txt"}, {"include_draft": "maybe"}):
            self.assertEqual(self.client.get(self.url, params=params).status_code, 400)
        for title in ("../../a\\b\r\nX-Injected: yes", "CON", "..", "", "a" * 500, "中文\u202efile"):
            filename = export_filename(title, "zip")
            self.assertNotRegex(filename, r'[/\\:\r\n\u202e]')
            self.assertLess(len(filename), 90)
            self.assertEqual(pathlib.PureWindowsPath(filename).name, filename)
        with self.assertRaises(DomainError):
            export_filename("title", "../zip")

    def test_export_read_does_not_migrate_legacy_materials_or_change_database(self):
        with self.db.connection() as c:
            c.execute("""INSERT INTO v2_author_story_plans VALUES(
                'export-legacy-plan',?,'旧规划','旧规划内容','目标',1,'planned',NULL,NULL,'2026-09-12','2026-09-12')""", (self.project_id,))
        with self.db.connection() as c:
            before = "\n".join(c.iterdump())
        _, archive, snapshot = self.bundle()
        self.assertTrue(any(item["title"] == "旧规划" for item in snapshot["author_materials"]))
        self.assertIn("旧规划内容", archive.read("materials.md").decode())
        with self.db.connection() as c:
            after = "\n".join(c.iterdump())
        self.assertEqual(before, after)

    def test_historical_source_is_not_a_current_fact_or_manuscript(self):
        with self.db.connection() as c:
            chapter = c.execute("SELECT * FROM v2_chapters WHERE project_id=? ORDER BY chapter_number LIMIT 1", (self.project_id,)).fetchone()
            old_span = c.execute("SELECT id FROM v2_source_spans WHERE chapter_id=? LIMIT 1", (chapter["id"],)).fetchone()["id"]
            c.execute("UPDATE v2_chapters SET body='CURRENT_REVISED_BODY',source_revision=2 WHERE id=?", (chapter["id"],))
            c.execute("INSERT INTO v2_source_spans VALUES('export-current-span',?,?,'revision','CURRENT_REVISED_BODY',2)", (self.project_id, chapter["id"]))
            version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0]
            c.execute("INSERT INTO v2_memory_records VALUES('export-stale-fact',?,?,'static_canon','人物','属性','OLD_FACT',?,'author_confirmed',NULL,NULL,NULL)", (self.project_id, version, old_span))
        _, archive, snapshot = self.bundle()
        self.assertNotIn(old_span, {item["id"] for item in snapshot["sources"]})
        self.assertIn("CURRENT_REVISED_BODY", archive.read("manuscript.txt").decode())
        self.assertNotIn("export-stale-fact", {item["id"] for item in snapshot["confirmed_facts"]})
        self.assertIn("export-stale-fact", {item["id"] for item in snapshot["facts_needing_review"]})

    def test_snapshot_remains_atomic_when_a_writer_commits_mid_export(self):
        with self.db.connection() as c:
            c.execute("PRAGMA journal_mode=WAL")
        original = self.db._project
        def change_after_first_read(c, user_id, project_id, writable=False):
            selected = original(c, user_id, project_id, writable)
            with self.db.connection() as writer:
                writer.execute("UPDATE v2_projects SET title='AFTER_SNAPSHOT' WHERE id=?", (project_id,))
                writer.execute("UPDATE v2_chapters SET body='AFTER_SNAPSHOT' WHERE project_id=?", (project_id,))
            return selected
        with patch.object(self.db, "_project", side_effect=change_after_first_read):
            snapshot = project_snapshot(self.db, self.user_id, self.project_id)
        self.assertNotEqual(snapshot["project"]["title"], "AFTER_SNAPSHOT")
        self.assertTrue(all(chapter["body"] != "AFTER_SNAPSHOT" for chapter in snapshot["chapters"]))
        content = export_content(snapshot, "txt")[0]
        self.assertNotIn(b"AFTER_SNAPSHOT", content)

    def test_archived_project_can_still_be_exported_and_oversize_is_explicit(self):
        with self.db.connection() as c:
            c.execute("UPDATE v2_projects SET status='archived' WHERE id=?", (self.project_id,))
        self.assertEqual(self.client.get(self.url).status_code, 200)
        snapshot = project_snapshot(self.db, self.user_id, self.project_id)
        with patch("app.project_export.MAX_EXPORT_BYTES", 10):
            with self.assertRaises(DomainError) as caught:
                export_content(snapshot, "bundle")
            self.assertEqual(caught.exception.code, "export_too_large")

    def test_revised_rich_format_and_inactive_facts_are_not_mislabeled(self):
        with self.db.connection() as c:
            chapter = c.execute("SELECT id FROM v2_chapters WHERE project_id=? LIMIT 1", (self.project_id,)).fetchone()
            c.execute("CREATE TABLE IF NOT EXISTS v2_chapter_content_formats(chapter_id TEXT NOT NULL,source_revision INTEGER NOT NULL,body_format TEXT NOT NULL,PRIMARY KEY(chapter_id,source_revision))")
            c.execute("INSERT OR REPLACE INTO v2_chapter_content_formats VALUES(?,2,'markdown')", (chapter["id"],))
            c.execute("UPDATE v2_chapters SET body='**修订后格式**',source_revision=2 WHERE id=?", (chapter["id"],))
            version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (self.project_id,)).fetchone()[0]
            c.execute("INSERT INTO v2_memory_records VALUES('export-inactive-fact',?,?,'static_canon','人物','属性','撤销属性',NULL,'author_confirmed',NULL,?,NULL)", (self.project_id, version, version - 1))
        _, archive, snapshot = self.bundle()
        current = next(item for item in snapshot["chapters"] if item["id"] == chapter["id"])
        self.assertEqual(current["body_format"], "markdown")
        self.assertIn("**修订后格式**", archive.read("manuscript.md").decode())
        self.assertNotIn("export-inactive-fact", {item["id"] for item in snapshot["confirmed_facts"]})
        self.assertIn("export-inactive-fact", {item["id"] for item in snapshot["inactive_facts"]})


if __name__ == "__main__":
    unittest.main()
