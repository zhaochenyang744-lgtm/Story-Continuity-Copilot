import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult


def idem(value=None): return {"Idempotency-Key": value or str(uuid.uuid4())}


class NoProvider:
    label="no-provider"; model_label="no-provider"
    @property
    def available(self): return True
    def evaluate(self, _request): return ProviderResult({"issues": []})


class SourceChangeSetTests(unittest.TestCase):
    def setUp(self):
        root=pathlib.Path(tempfile.mkdtemp(prefix="scc-11j-"))
        self.app=create_app(AppPaths.from_project_root(root,protected_poc_root=root/"protected"),provider=NoProvider(),executor=lambda *_:None)
        self.client=TestClient(self.app)
        self.client.post("/api/auth/register",json={"account_name":"append-author","display_name":"Append","password":"safe-password-123"},headers=idem())
        preview=self.client.post("/api/imports/preview",files={"file":("base.md","# Base\n旧章节正文。".encode(),"text/markdown")},headers=idem()).json()["data"]
        committed=self.client.post(f"/api/imports/{preview['import_id']}/commit",json={"confirm":True,"title":"Append target","chapter_preview_ids":[x["preview_id"] for x in preview["detected"]["chapters"]]},headers=idem()).json()["data"]
        self.project=committed["project"]["id"]

    def preview(self, method, **extra):
        payload={"mode":"append","input_method":method,"base_source_revision":1}
        payload.update(extra)
        return self.client.post(f"/api/projects/{self.project}/source-change-sets/preview",json=payload,headers=idem())

    def business_state(self):
        with self.app.state.database.connection() as connection:
            return (connection.execute("SELECT COUNT(*) FROM v2_chapters WHERE project_id=?",(self.project,)).fetchone()[0],connection.execute("SELECT COUNT(*) FROM v2_source_spans WHERE project_id=?",(self.project,)).fetchone()[0],connection.execute("SELECT source_revision FROM v2_projects WHERE id=?",(self.project,)).fetchone()[0],connection.execute("SELECT COUNT(*) FROM v2_drafts WHERE project_id=?",(self.project,)).fetchone()[0])

    def test_preview_schema_and_file_audit_redacts_content_and_path(self):
        result=self.preview("file",filename=r"C:\secret\chapter.md",content="# New\n正文").json()["data"]["source_change_set"]
        self.assertEqual(set(result),{"id","project_id","base_source_revision","target_source_revision","mode","input_method","content_sha256","status","chapter_count","source_span_count","chapters","previewed_at","committed_at","failed_at","failure_code","expires_at","audit"})
        self.assertEqual((result["audit"]["file_basename"],result["committed_at"],result["failed_at"],result["failure_code"]),("chapter.md",None,None,None))
        self.assertNotIn("正文",str(result)); self.assertNotIn("C:\\secret",str(result))

    def test_preview_does_not_change_any_business_source_table(self):
        before=self.business_state(); self.assertEqual(self.preview("paste",content="# New\n正文").status_code,201); self.assertEqual(self.business_state(),before)

    def test_preview_idempotency_replay_and_conflict(self):
        key=str(uuid.uuid4()); first=self.client.post(f"/api/projects/{self.project}/source-change-sets/preview",json={"mode":"append","input_method":"paste","base_source_revision":1,"content":"# New\n正文"},headers=idem(key)); replay=self.client.post(f"/api/projects/{self.project}/source-change-sets/preview",json={"mode":"append","input_method":"paste","base_source_revision":1,"content":"# New\n正文"},headers=idem(key)); conflict=self.client.post(f"/api/projects/{self.project}/source-change-sets/preview",json={"mode":"append","input_method":"paste","base_source_revision":1,"content":"# Different\n正文"},headers=idem(key))
        self.assertEqual((first.status_code,replay.status_code,conflict.status_code),(201,201,409)); self.assertEqual(first.json()["data"],replay.json()["data"]); self.assertEqual(conflict.json()["error"]["code"],"idempotency_conflict")

    def test_file_format_expiry_and_base_conflicts_have_no_business_writes(self):
        before=self.business_state(); bad=self.preview("file",filename="bad.pdf",content="x"); self.assertEqual((bad.status_code,bad.json()["error"]["code"]),(415,"unsupported_format")); change=self.preview("paste",content="# New\n正文").json()["data"]["source_change_set"]
        with self.app.state.database.connection() as connection: connection.execute("UPDATE v2_source_change_sets SET expires_at=? WHERE id=?",("2000-01-01T00:00:00+00:00",change["id"]))
        expired=self.client.post(f"/api/projects/{self.project}/source-change-sets/{change['id']}/commit",json={"confirm":True,"content_sha256":change["content_sha256"]},headers=idem())
        self.assertEqual((expired.status_code,expired.json()["error"]["code"]),(409,"source_change_set_expired")); self.assertEqual(self.business_state(),before)

    def commit_preview(self, method, **extra):
        preview=self.preview(method,**extra).json()["data"]["source_change_set"]
        response=self.client.post(f"/api/projects/{self.project}/source-change-sets/{preview['id']}/commit",json={"confirm":True,"content_sha256":preview["content_sha256"]},headers=idem())
        self.assertEqual(response.status_code,200)
        return preview,response.json()["data"]

    def assert_append_revision_two(self, result):
        self.assertEqual(result["source_change_set"]["target_source_revision"],2)
        with self.app.state.database.connection() as connection:
            chapters=connection.execute("SELECT source_revision FROM v2_chapters WHERE project_id=? AND source_revision=2",(self.project,)).fetchall()
            spans=connection.execute("SELECT source_revision FROM v2_source_spans WHERE project_id=? AND source_revision=2",(self.project,)).fetchall()
        self.assertEqual(([row[0] for row in chapters],[row[0] for row in spans]),([2],[2]))
        revision=self.client.get(f"/api/projects/{self.project}/source-revisions/2/spans")
        self.assertEqual(revision.status_code,200)
        self.assertEqual((revision.json()["data"]["project_id"],revision.json()["data"]["source_revision"],len(revision.json()["data"]["source_spans"])),(self.project,2,1))

    def test_paste_commit_writes_only_structured_target_revision(self):
        _,result=self.commit_preview("paste",content="# Paste\n追加正文。")
        self.assert_append_revision_two(result)

    def test_file_commit_writes_only_structured_target_revision(self):
        _,result=self.commit_preview("file",filename="append.md",content="# File\n追加正文。")
        self.assert_append_revision_two(result)

    def test_draft_complete_commit_writes_only_structured_target_revision(self):
        draft=self.client.get(f"/api/projects/{self.project}").json()["data"]["current_draft"]
        self.client.patch(f"/api/projects/{self.project}/drafts/{draft['id']}",json={"base_revision":1,"body":"# Draft\n追加正文。"},headers=idem())
        _,result=self.commit_preview("draft_complete",draft_id=draft["id"])
        self.assert_append_revision_two(result)

    def test_commit_is_atomic_idempotent_and_keeps_existing_evidence_resolvable(self):
        preview=self.preview("paste",content="# 第二章\n新增章节。\n# 第三章\n再追加一章。").json()["data"]["source_change_set"]
        before=self.client.get(f"/api/projects/{self.project}/chapters?include=excerpt").json()["data"]["chapters"]
        key=str(uuid.uuid4()); payload={"confirm":True,"content_sha256":preview["content_sha256"]}
        first=self.client.post(f"/api/projects/{self.project}/source-change-sets/{preview['id']}/commit",json=payload,headers=idem(key)); replay=self.client.post(f"/api/projects/{self.project}/source-change-sets/{preview['id']}/commit",json=payload,headers=idem(key))
        self.assertEqual((first.status_code,replay.status_code),(200,200)); self.assertEqual(first.json()["data"],replay.json()["data"])
        project=self.client.get(f"/api/projects/{self.project}").json()["data"]
        chapters=self.client.get(f"/api/projects/{self.project}/chapters?include=excerpt").json()["data"]["chapters"]
        self.assertEqual((project["source_revision"],len(chapters),first.json()["data"]["next_draft"]["chapter_number"]),(2,3,4))
        self.assertEqual(chapters[0],before[0])
        spans=self.client.get(f"/api/projects/{self.project}/source-revisions/2/spans").json()["data"]["source_spans"]
        self.assertEqual(len(spans),2)
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_drafts WHERE project_id=? AND status='draft'",(self.project,)).fetchone()[0],1)

    def test_draft_snapshot_stale_and_new_key_replay_return_original_result(self):
        draft=self.client.get(f"/api/projects/{self.project}").json()["data"]["current_draft"]
        self.client.patch(f"/api/projects/{self.project}/drafts/{draft['id']}",json={"base_revision":1,"body":"# 完成\n原始正文"},headers=idem())
        preview=self.preview("draft_complete",draft_id=draft["id"]).json()["data"]["source_change_set"]
        self.client.patch(f"/api/projects/{self.project}/drafts/{draft['id']}",json={"base_revision":2,"body":"# 完成\n已变化正文"},headers=idem())
        stale=self.client.post(f"/api/projects/{self.project}/source-change-sets/{preview['id']}/commit",json={"confirm":True,"content_sha256":preview["content_sha256"]},headers=idem())
        self.assertEqual((stale.status_code,stale.json()["error"]["code"]),(409,"source_draft_stale"))
        self.assertEqual(self.client.get(f"/api/projects/{self.project}").json()["data"]["source_revision"],1)
        fresh=self.preview("paste",content="# 新章\n正文").json()["data"]["source_change_set"]
        first=self.client.post(f"/api/projects/{self.project}/source-change-sets/{fresh['id']}/commit",json={"confirm":True,"content_sha256":fresh["content_sha256"]},headers=idem())
        replay=self.client.post(f"/api/projects/{self.project}/source-change-sets/{fresh['id']}/commit",json={"confirm":True,"content_sha256":fresh["content_sha256"]},headers=idem())
        self.assertEqual((first.status_code,replay.status_code,first.json()["data"]["next_draft"]["id"]),(200,200,replay.json()["data"]["next_draft"]["id"]))

    def test_conflicts_bad_hash_and_cross_project_have_no_half_write(self):
        preview=self.preview("file",filename="append.md",content="# New\n正文").json()["data"]["source_change_set"]
        before=self.client.get(f"/api/projects/{self.project}").json()["data"]
        bad=self.client.post(f"/api/projects/{self.project}/source-change-sets/{preview['id']}/commit",json={"confirm":True,"content_sha256":"forged"},headers=idem())
        self.assertEqual((bad.status_code,bad.json()["error"]["code"]),(409,"source_hash_mismatch"))
        self.assertEqual(self.client.get(f"/api/projects/{self.project}").json()["data"]["chapter_count"],before["chapter_count"])
        stale=self.preview("paste",content="# stale\n正文",base_source_revision=2)
        self.assertEqual((stale.status_code,stale.json()["error"]["code"]),(409,"source_revision_conflict"))
        other_preview=self.client.post("/api/imports/preview",files={"file":("o.md",b"# O\nO","text/markdown")},headers=idem()).json()["data"]
        other=self.client.post(f"/api/imports/{other_preview['import_id']}/commit",json={"confirm":True,"title":"Other","chapter_preview_ids":[x["preview_id"] for x in other_preview["detected"]["chapters"]]},headers=idem()).json()["data"]["project"]["id"]
        cross=self.client.post(f"/api/projects/{other}/source-change-sets/{preview['id']}/commit",json={"confirm":True,"content_sha256":preview["content_sha256"]},headers=idem())
        self.assertEqual(cross.status_code,404)

    def test_cross_account_and_source_revision_reads_are_project_isolated(self):
        preview=self.preview("paste",content="# Hidden\n正文").json()["data"]["source_change_set"]
        other=TestClient(self.app)
        other.post("/api/auth/register",json={"account_name":"second-author","display_name":"Second","password":"safe-password-456"},headers=idem())
        self.assertEqual(other.get(f"/api/projects/{self.project}/source-revisions/1/spans").status_code,404)
        denied=other.post(f"/api/projects/{self.project}/source-change-sets/{preview['id']}/commit",json={"confirm":True,"content_sha256":preview["content_sha256"]},headers=idem())
        self.assertEqual(denied.status_code,404)
        self.assertEqual(self.business_state()[2],1)

    def test_restart_preserves_structured_lineage_and_historical_source_reference(self):
        with self.app.state.database.connection() as connection:
            baseline=connection.execute("SELECT id FROM v2_source_spans WHERE project_id=? AND source_revision=1",(self.project,)).fetchone()[0]
            connection.execute("INSERT INTO v2_memory_records VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",("historical-memory",self.project,1,"fact","旧章节","status","保留",baseline,"author_confirmed",None,None,None))
        _,result=self.commit_preview("paste",content="# New\n正文")
        with self.app.state.database.connection() as connection:
            before=connection.execute("SELECT id,source_revision FROM v2_source_spans WHERE project_id=? ORDER BY id",(self.project,)).fetchall()
        self.app.state.database.initialize()
        with self.app.state.database.connection() as connection:
            after=connection.execute("SELECT id,source_revision FROM v2_source_spans WHERE project_id=? ORDER BY id",(self.project,)).fetchall()
        self.assertEqual([tuple(row) for row in before],[tuple(row) for row in after])
        memory=self.client.get(f"/api/projects/{self.project}/memory").json()["data"]["records"]
        self.assertEqual(memory[0]["source"]["span_id"],baseline)
        self.assertEqual(result["source_change_set"]["target_source_revision"],2)


if __name__ == "__main__": unittest.main()
