from __future__ import annotations

import pathlib
import os
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.text_content import visible_draft_text


def idem() -> dict[str, str]:
    return {"Idempotency-Key": str(uuid.uuid4())}


class CapturingProvider:
    label = "rich-editor-capture"
    model_label = "rich-editor-capture-v1"
    available = True

    def __init__(self) -> None:
        self.requests: list[dict] = []

    def evaluate(self, request: dict) -> ProviderResult:
        self.requests.append(request)
        return ProviderResult({"issues": []})


class RichEditorCompatibilityTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        os.environ.update({
            "PUBLIC_APP_MODE": "0",
            "PUBLIC_BASE_URL": "http://127.0.0.1:3080",
            "BACKEND_ORIGIN": "http://127.0.0.1:8080",
            "TRUSTED_HOSTS": "127.0.0.1:8080,testserver",
            "TRUSTED_ORIGINS": "http://127.0.0.1:3080,http://testserver",
        })

    def setUp(self) -> None:
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-v140-rich-editor-"))
        self.provider = CapturingProvider()
        self.app = create_app(
            AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
            provider=self.provider,
            executor=lambda function, *args: function(*args),
        )
        self.client = TestClient(self.app)
        registered = self.client.post(
            "/api/auth/register",
            json={"account_name": "rich-author", "display_name": "Rich", "password": "safe-password-123"},
            headers=idem(),
        )
        self.project_id = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.draft_id = self.client.get(f"/api/projects/{self.project_id}").json()["data"]["current_draft"]["id"]

    def patch(self, revision: int, body: str, body_format: str | None = None):
        payload = {"base_revision": revision, "body": body}
        if body_format is not None:
            payload["body_format"] = body_format
        return self.client.patch(
            f"/api/projects/{self.project_id}/drafts/{self.draft_id}",
            json=payload,
            headers=idem(),
        )

    def test_legacy_and_plain_saves_are_lossless_and_do_not_require_migration(self):
        initial = self.client.get(f"/api/projects/{self.project_id}/drafts/{self.draft_id}").json()["data"]
        self.assertEqual(initial["body_format"], "plain_text")
        body = "第一段 <潮门> 与 **字面星号** 以及 C:\\雾港\\钥匙。\n反斜杠 \\*保持字面\\*。\n\n\n第四段。普通输入Z"
        saved = self.patch(1, body, "plain_text")
        self.assertEqual((saved.status_code, saved.json()["data"]["body_format"]), (200, "plain_text"))
        reloaded = self.client.get(f"/api/projects/{self.project_id}/drafts/{self.draft_id}").json()["data"]
        self.assertEqual((reloaded["body"], reloaded["body_format"]), (body, "plain_text"))
        with self.app.state.database.connection() as connection:
            rows = connection.execute("SELECT revision,body_format FROM v2_draft_content_formats WHERE draft_id=?", (self.draft_id,)).fetchall()
        self.assertEqual([(row["revision"], row["body_format"]) for row in rows], [(2, "plain_text")])

    def test_markdown_is_stored_losslessly_but_analysis_and_source_span_use_visible_text(self):
        markdown = "> 引用段落。\n\n- 列表一\n- 列表二\n\n**粗体词**与*斜体词*，\\*字面星号\\*，C:\\雾港\\钥匙。"
        saved = self.patch(1, markdown, "markdown")
        self.assertEqual((saved.status_code, saved.json()["data"]["body_format"]), (200, "markdown"))
        checked = self.client.post(
            f"/api/projects/{self.project_id}/checks",
            json={"draft_id": self.draft_id, "draft_revision": 2},
            headers=idem(),
        )
        self.assertEqual(checked.status_code, 202)
        request = self.provider.requests[-1]
        visible = "引用段落。\n\n列表一\n列表二\n\n粗体词与斜体词，*字面星号*，C:\\雾港\\钥匙。"
        self.assertEqual(request["draft"]["body"], "引用段落。\n列表一\n列表二\n\n粗体词与斜体词，*字面星号*，C:\\雾港\\钥匙。")
        claim_text = "".join(item["text"] for item in request["claims"])
        self.assertNotIn("**", claim_text)
        self.assertNotIn("> ", claim_text)
        self.assertNotIn("- 列表", claim_text)

        project = self.client.get(f"/api/projects/{self.project_id}").json()["data"]
        preview = self.client.post(
            f"/api/projects/{self.project_id}/source-change-sets/preview",
            json={"mode": "append", "input_method": "draft_complete", "base_source_revision": project["source_revision"], "draft_id": self.draft_id},
            headers=idem(),
        ).json()["data"]["source_change_set"]
        committed = self.client.post(
            f"/api/projects/{self.project_id}/source-change-sets/{preview['id']}/commit",
            json={"confirm": True, "content_sha256": preview["content_sha256"]},
            headers=idem(),
        )
        self.assertEqual(committed.status_code, 200)
        with self.app.state.database.connection() as connection:
            chapter = connection.execute("SELECT body FROM v2_chapters WHERE project_id=? AND source_revision=?", (self.project_id, project["source_revision"] + 1)).fetchone()
            span = connection.execute("SELECT body FROM v2_source_spans WHERE project_id=? AND source_revision=?", (self.project_id, project["source_revision"] + 1)).fetchone()
        self.assertEqual(chapter["body"], markdown)
        self.assertEqual(span["body"], visible)

    def test_visible_projection_preserves_literals_and_removes_only_supported_markers(self):
        body = "&lt;潮门&gt; 与 **粗体**、*斜体*、\\*字面星号\\*、C:\\雾港\\钥匙。  \n> - 列表引用。"
        self.assertEqual(
            visible_draft_text(body, "markdown"),
            "<潮门> 与 粗体、斜体、*字面星号*、C:\\雾港\\钥匙。\n列表引用。",
        )
        self.assertEqual(visible_draft_text(body, "plain_text"), body)

    def test_visible_projection_removes_nested_list_quote_and_entity_markers(self):
        body = "- &gt; 夜航规则不可改变。\n> - **潮门**仍关闭。\n  - > *银钥匙*仍由林默保管。"
        self.assertEqual(
            visible_draft_text(body, "markdown"),
            "夜航规则不可改变。\n潮门仍关闭。\n银钥匙仍由林默保管。",
        )

    def test_visible_projection_removes_empty_nested_list_item_marker(self):
        body = "- \n  > **夜航规则不可改变。**\n\n"
        self.assertEqual(visible_draft_text(body, "markdown"), "夜航规则不可改变。\n")


if __name__ == "__main__":
    unittest.main()
