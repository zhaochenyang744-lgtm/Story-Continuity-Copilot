import json
import pathlib
import tempfile
import unittest
import uuid

from fastapi.testclient import TestClient

from app.config import AppPaths
from app.main import create_app


def idem(value: str | None = None) -> dict[str, str]:
    return {"Idempotency-Key": value or str(uuid.uuid4())}


class ForbiddenDuringPresetProvider:
    available = True
    label = "must-not-run-for-preset"

    def __init__(self):
        self.calls = 0

    def evaluate(self, _request):
        self.calls += 1
        raise AssertionError("preset review must not call a Provider")


class Stage8PresetReviewTests(unittest.TestCase):
    def setUp(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="scc-stage8-"))
        self.provider = ForbiddenDuringPresetProvider()
        self.app = create_app(
            AppPaths.from_project_root(root, protected_poc_root=root / "protected"),
            provider=self.provider,
            executor=lambda fn, *args: fn(*args),
        )
        self.client = TestClient(self.app)
        registered = self.client.post(
            "/api/auth/register",
            json={"account_name": "stage8author", "display_name": "Stage 8", "password": "safe-password-88"},
            headers=idem(),
        )
        self.assertEqual(registered.status_code, 201)
        self.grey = registered.json()["data"]["onboarding"]["tutorial"]["project_id"]
        self.other = self.client.post("/api/projects", json={"title": "Stage 8 Other"}, headers=idem()).json()["data"]["project"]["id"]

    def preset_view(self):
        project = self.client.get(f"/api/projects/{self.grey}").json()["data"]
        return self.client.get(
            f"/api/projects/{self.grey}/checks/{project['latest_run']['run_id']}?include=issues,evidence,metrics"
        )

    def decide_and_create_changeset(self):
        run = self.preset_view().json()["data"]
        for issue in run["issues"]:
            decision = "false_positive" if "表面冲突" in issue["claim_text"] else "keep_intentional"
            response = self.client.post(
                f"/api/projects/{self.grey}/issues/{issue['id']}/decision",
                json={"run_id": run["run_id"], "source_revision": run["source_revision"], "decision": decision, "note": "作者审阅"},
                headers=idem(),
            )
            self.assertEqual(response.status_code, 200)
        created = self.client.post(
            f"/api/projects/{self.grey}/memory/change-sets",
            json={"run_id": run["run_id"], "source_run_revision": 1, "resolved_revision": 1},
            headers=idem(),
        )
        self.assertEqual(created.status_code, 201)
        return run, created.json()["data"]["change_set"]

    def database_dump(self):
        with self.app.state.database.connection() as connection:
            return "\n".join(connection.iterdump())

    def test_isolated_tutorial_has_scoped_completed_review_without_provider(self):
        response = self.preset_view()
        self.assertEqual(response.status_code, 200)
        run = response.json()["data"]
        self.assertEqual((run["status"], run["result_origin"], run["source_revision"], run["current_revision"]), ("completed", "demo_preset", 1, 1))
        self.assertIn("未调用 Provider", run["result_origin_label"])
        self.assertEqual(len(run["issues"]), 4)
        self.assertEqual(self.provider.calls, 0)
        for issue in run["issues"]:
            self.assertTrue(issue["claim_text"])
            self.assertEqual(len(issue["evidence"]), 1)
            evidence = issue["evidence"][0]
            self.assertEqual(evidence["source_revision"], 1)
            self.assertGreaterEqual(evidence["chapter_number"], 1)
            self.assertTrue(evidence["chapter_title"])
            self.assertTrue(evidence["excerpt_context"])
            self.assertTrue(evidence["source_path"].startswith(f"/projects/{self.grey}/sources#span-"))
        self.assertEqual(self.client.get(f"/api/projects/{self.other}/checks/{run['run_id']}?include=issues,evidence").status_code, 404)
        outsider = TestClient(self.app)
        outsider.post("/api/auth/register", json={"account_name":"stage8other","display_name":"Other","password":"safe-password-89"}, headers=idem())
        self.assertEqual(outsider.get(f"/api/projects/{self.grey}/checks/{run['run_id']}?include=issues,evidence").status_code, 404)

    def test_evidence_source_revision_and_project_lineage_fail_closed(self):
        run = self.preset_view().json()["data"]
        evidence_id = run["issues"][0]["evidence"][0]["id"]
        with self.app.state.database.connection() as connection:
            original = dict(connection.execute("SELECT * FROM v2_evidence WHERE id=?", (evidence_id,)).fetchone())
        for sql, values in (
            ("UPDATE v2_evidence SET source_revision=2 WHERE id=?", (evidence_id,)),
            ("UPDATE v2_evidence SET project_id=? WHERE id=?", (self.other, evidence_id)),
            ("UPDATE v2_evidence SET span_id='missing-source' WHERE id=?", (evidence_id,)),
        ):
            with self.subTest(sql=sql):
                with self.app.state.database.connection() as connection:
                    connection.execute(sql, values)
                failed = self.client.get(f"/api/projects/{self.grey}/checks/{run['run_id']}?include=issues,evidence")
                self.assertEqual((failed.status_code, failed.json()["error"]["code"]), (422, "evidence_unresolvable"))
                with self.app.state.database.connection() as connection:
                    connection.execute(
                        "UPDATE v2_evidence SET project_id=?,span_id=?,source_revision=? WHERE id=?",
                        (original["project_id"], original["span_id"], original["source_revision"], evidence_id),
                    )

    def test_three_candidate_actions_commit_once_and_keep_canon_author_controlled(self):
        _, change_set = self.decide_and_create_changeset()
        self.assertEqual(len(change_set["items"]), 3)
        self.assertEqual(self.client.get(f"/api/projects/{self.grey}").json()["data"]["current_memory_version"], 4)
        by_subject = {item["after"]["subject"]: item for item in change_set["items"]}
        accepted = by_subject["黄铜罗盘临时离手"]
        rejected = by_subject["黄铜罗盘"]
        edited = by_subject["苏岑"]
        payload = {
            "confirm": True,
            "accepted_item_ids": [accepted["id"], edited["id"]],
            "rejected_item_ids": [rejected["id"]],
            "edited_items": [{
                "item_id": edited["id"], "memory_type": "event_timeline", "subject": "苏岑",
                "predicate": "next_action", "value": "先核对异常雾钟，再追查白色渡船",
            }],
            "note": "分别接受、拒绝和编辑",
        }
        commit_key = str(uuid.uuid4())
        first = self.client.post(f"/api/projects/{self.grey}/memory/change-sets/{change_set['id']}/commit", json=payload, headers=idem(commit_key))
        replay = self.client.post(f"/api/projects/{self.grey}/memory/change-sets/{change_set['id']}/commit", json=payload, headers=idem(commit_key))
        self.assertEqual((first.status_code, replay.status_code), (200, 200))
        self.assertEqual(first.json()["data"], replay.json()["data"])
        result = first.json()["data"]
        self.assertEqual((result["memory_version"]["previous"], result["memory_version"]["current"]), (4, 5))
        self.assertEqual(result["edited_item_ids"], [edited["id"]])
        memory = self.client.get(f"/api/projects/{self.grey}/memory?version=5").json()["data"]["records"]
        self.assertTrue(any(row["subject"] == "黄铜罗盘临时离手" and row["review_status"] == "author_confirmed" for row in memory))
        self.assertTrue(any(row["value"] == "先核对异常雾钟，再追查白色渡船" and row["review_status"] == "author_confirmed" for row in memory))
        self.assertFalse(any(row["value"] == "由温岚放在潮汐档案室桌上" for row in memory))
        with self.app.state.database.connection() as connection:
            states = dict(connection.execute("SELECT id,review_status FROM v2_change_set_items WHERE change_set_id=?", (change_set["id"],)))
            committed_edit = json.loads(connection.execute("SELECT committed_after_json FROM v2_change_set_items WHERE id=?", (edited["id"],)).fetchone()[0])
        self.assertEqual((states[accepted["id"]], states[rejected["id"]], states[edited["id"]]), ("accepted", "rejected", "edited"))
        self.assertEqual(committed_edit["value"], "先核对异常雾钟，再追查白色渡船")

    def test_invalid_edit_and_stale_lineage_have_no_partial_side_effects(self):
        run, change_set = self.decide_and_create_changeset()
        items = change_set["items"]
        invalid_payload = {
            "confirm": True,
            "accepted_item_ids": [items[0]["id"]],
            "rejected_item_ids": [item["id"] for item in items[1:]],
            "edited_items": [{"item_id":items[0]["id"],"memory_type":"open_thread","subject":"","predicate":"status","value":"x"}],
        }
        before = self.database_dump()
        invalid = self.client.post(f"/api/projects/{self.grey}/memory/change-sets/{change_set['id']}/commit", json=invalid_payload, headers=idem())
        self.assertEqual((invalid.status_code, invalid.json()["error"]["code"]), (422, "invalid_item_edit"))
        self.assertEqual(self.database_dump(), before)
        project = self.client.get(f"/api/projects/{self.grey}").json()["data"]
        draft = self.client.get(f"/api/projects/{self.grey}/drafts/{project['current_draft']['id']}").json()["data"]
        self.client.patch(f"/api/projects/{self.grey}/drafts/{draft['id']}", json={"base_revision":1,"body":draft["body"]+"\n普通编辑。"}, headers=idem())
        stale_before = self.database_dump()
        valid_selection = {"confirm":True,"accepted_item_ids":[items[0]["id"]],"rejected_item_ids":[item["id"] for item in items[1:]],"edited_items":[]}
        stale = self.client.post(f"/api/projects/{self.grey}/memory/change-sets/{change_set['id']}/commit", json=valid_selection, headers=idem())
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "lineage_invalid_requires_recheck"))
        self.assertEqual(self.database_dump(), stale_before)

    def test_reset_restores_same_preset_and_preserves_other_projects(self):
        initial = self.preset_view().json()["data"]
        _, change_set = self.decide_and_create_changeset()
        items = change_set["items"]
        self.client.post(
            f"/api/projects/{self.grey}/memory/change-sets/{change_set['id']}/commit",
            json={"confirm":True,"accepted_item_ids":[items[0]["id"]],"rejected_item_ids":[item["id"] for item in items[1:]],"edited_items":[]},
            headers=idem(),
        )
        before_other = self.client.get(f"/api/projects/{self.other}").json()["data"]
        reset_key = str(uuid.uuid4())
        first = self.client.post(f"/api/projects/{self.grey}/reset", json={"confirm":True,"reason":"demo_recovery"}, headers=idem(reset_key))
        replay = self.client.post(f"/api/projects/{self.grey}/reset", json={"confirm":True,"reason":"demo_recovery"}, headers=idem(reset_key))
        self.assertEqual(first.json()["data"], replay.json()["data"])
        restored = self.preset_view().json()["data"]
        self.assertEqual(restored["run_id"], initial["run_id"])
        self.assertEqual((len(restored["issues"]), restored["result_origin"], restored["current_revision"]), (4, "demo_preset", 1))
        self.assertEqual(self.client.get(f"/api/projects/{self.grey}").json()["data"]["current_memory_version"], 4)
        after_other = self.client.get(f"/api/projects/{self.other}").json()["data"]
        self.assertEqual(before_other, after_other)
        with self.app.state.database.connection() as connection:
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_decisions WHERE project_id=?", (self.grey,)).fetchone()[0], 0)
            self.assertEqual(connection.execute("SELECT COUNT(*) FROM v2_change_sets WHERE project_id=?", (self.grey,)).fetchone()[0], 0)
        self.assertEqual(self.provider.calls, 0)


if __name__ == "__main__":
    unittest.main()
