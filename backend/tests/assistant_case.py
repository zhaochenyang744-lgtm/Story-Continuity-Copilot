"""Shared setup for the assistant tests: an app with a scripted chat model, a registered author and a visitor."""
from __future__ import annotations

import dataclasses
import json
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app
from app.stage13 import Stage13Settings

from tests.scripted_chat import ScriptedChatProvider


class AssistantCase(unittest.TestCase):
    provider: ScriptedChatProvider
    project_id: str

    def start(self, provider=None, **overrides) -> None:
        root = pathlib.Path(tempfile.mkdtemp(prefix="v180-assistant-"))
        self.settings = dataclasses.replace(Stage13Settings.for_test(), **overrides)
        self.provider = provider if provider is not None else ScriptedChatProvider()
        self.app = create_app(AppPaths.from_project_root(root, protected_poc_root=root / "protected"), provider=self.provider,
                              executor=lambda fn, *args: fn(*args), settings=self.settings)
        self.db = self.app.state.database
        self.stage13 = self.app.state.stage13
        self.engine = self.app.state.assistant
        self.client = TestClient(self.app)
        self.addCleanup(self.client.close)

    @staticmethod
    def idem() -> dict[str, str]:
        return {"Idempotency-Key": str(uuid.uuid4())}

    def register(self) -> str:
        data = self.client.post("/api/auth/register", headers=self.idem(), json={
            "account_name": f"asst{uuid.uuid4().hex[:8]}", "display_name": "Assistant", "password": "valid-password-99",
            "recovery_email": f"{uuid.uuid4().hex[:8]}@example.test"}).json()["data"]
        self.user_id = data["user"]["id"]
        self.project_id = data["onboarding"]["tutorial"]["project_id"]
        return self.project_id

    def visitor(self) -> str:
        data = self.client.post("/api/auth/visitor").json()["data"]
        self.user_id = data["user"]["id"]
        projects = self.client.get("/api/projects").json()["data"]["projects"]
        self.project_id = next(item["id"] for item in projects if item["data_origin"] == "demo_seed")
        return self.project_id

    def ask(self, question: str = "苏岑知道罗盘被调包了吗？", page: str = "writing", expect: int | None = 202, project_id: str | None = None,
            headers: dict | None = None, **extra):
        context = {"page": page, **{name: extra.pop(name) for name in ("chapter_number", "selection", "character_id") if name in extra}}
        response = self.client.post(f"/api/projects/{project_id or self.project_id}/assistant/tasks", headers=headers or self.idem(),
                                    json={"kind": "ask", "question": question, "context": context, **extra})
        if expect is not None:
            self.assertEqual(response.status_code, expect, response.text)
        return response

    def task(self, task_id: str, project_id: str | None = None) -> dict:
        response = self.client.get(f"/api/projects/{project_id or self.project_id}/assistant/tasks/{task_id}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def run_ask(self, *turns, **kwargs) -> dict:
        """Script the model, ask, and return the finished task (the test executor runs the task inside the request)."""
        self.provider.script(*turns)
        response = self.ask(**kwargs)
        return self.task(response.json()["data"]["id"], kwargs.get("project_id"))

    def usage(self) -> dict:
        return self.client.get("/api/account/usage").json()["data"]

    def rows(self, sql: str, *params):
        with self.db.connection() as c:
            return [dict(row) for row in c.execute(sql, params).fetchall()]

    def all_messages(self) -> str:
        return json.dumps([call["messages"] for call in self.provider.calls], ensure_ascii=False)
