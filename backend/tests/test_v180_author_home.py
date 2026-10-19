"""The author's home page and settings (v1.8.0 08a): bio, password change, writing days, the home payload,
daily usage, exporting every work, and cleaning all of it up."""
from __future__ import annotations

import dataclasses
import io
import json
import pathlib
import sqlite3
import tempfile
import unittest
import uuid
import zipfile
from datetime import datetime, timedelta, timezone
from unittest import mock

from fastapi.testclient import TestClient

from app import author_home
from app.config import AppPaths
from app.main import create_app
from app.provider import ProviderResult
from app.stage13 import Stage13Settings
from app.text_content import written_chars
from app import v2_database

PASSWORD = "valid-password-99"
UTC = timezone.utc


def idem():
    return {"Idempotency-Key": str(uuid.uuid4())}


class Silent:
    label = model_label = "home-test-provider"
    available = True

    def evaluate(self, request):
        return ProviderResult({"issues": []}, input_tokens=1, output_tokens=1)


class HomeCase(unittest.TestCase):
    def setUp(self):
        self.root = pathlib.Path(tempfile.mkdtemp(prefix="v180-home-"))
        self.app = create_app(AppPaths.from_project_root(self.root, protected_poc_root=self.root / "protected"), provider=Silent(),
                              executor=lambda fn, *args: fn(*args), settings=dataclasses.replace(Stage13Settings.for_test()))
        self.db = self.app.state.database
        self.client = self.new_client()
        self.account = self.register(self.client, "home")

    def new_client(self):
        client = TestClient(self.app)
        self.addCleanup(client.close)
        return client

    def register(self, client, prefix):
        name = f"{prefix}{uuid.uuid4().hex[:8]}"
        data = client.post("/api/auth/register", headers=idem(), json={"account_name": name, "display_name": "作者", "password": PASSWORD,
                                                                          "recovery_email": f"{name}@example.test"})
        self.assertEqual(data.status_code, 201, data.text)
        body = data.json()["data"]
        return {"name": name, "id": body["user"]["id"], "sample": body["onboarding"]["tutorial"]["project_id"], "email": f"{name}@example.test"}

    def session(self, client=None):
        return (client or self.client).get("/api/auth/session").json()["data"]["user"]

    def new_work(self, title="夜航", client=None):
        client = client or self.client
        response = client.post("/api/projects", headers=idem(), json={"title": title, "genre": "悬疑", "summary": "港口的故事。"})
        self.assertEqual(response.status_code, 201, response.text)
        return response.json()["data"]["project"]["id"]

    def draft(self, project, client=None):
        return (client or self.client).get(f"/api/projects/{project}").json()["data"]["current_draft"]

    def save(self, project, text, client=None):
        client = client or self.client
        draft = self.draft(project, client)
        response = client.patch(f"/api/projects/{project}/drafts/{draft['id']}", headers=idem(), json={"base_revision": draft["revision"], "body": text, "title": draft.get("title") or "第1章"})
        self.assertEqual(response.status_code, 200, response.text)
        return draft["id"]

    def complete(self, project, client=None):
        client = client or self.client
        info = client.get(f"/api/projects/{project}").json()["data"]
        preview = client.post(f"/api/projects/{project}/source-change-sets/preview", headers=idem(), json={
            "mode": "append", "input_method": "draft_complete", "base_source_revision": info["source_revision"], "draft_id": info["current_draft"]["id"]})
        self.assertEqual(preview.status_code, 201, preview.text)
        change = preview.json()["data"]["source_change_set"]
        committed = client.post(f"/api/projects/{project}/source-change-sets/{change['id']}/commit", headers=idem(), json={"confirm": True, "content_sha256": change["content_sha256"]})
        self.assertEqual(committed.status_code, 200, committed.text)

    def days(self, user_id=None):
        with self.db.connection() as c:
            return [dict(row) for row in c.execute("SELECT * FROM v2_writing_days WHERE user_id=? ORDER BY day,project_id,chapter_number", (user_id or self.account["id"],))]

    def home(self, client=None):
        response = (client or self.client).get("/api/account/home")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def record(self, project_id, day, net, chapter=1, saves=True, user_id=None):
        """A write of `net` characters on the Beijing-time day `day` (noon), the way patch_draft records it."""
        stamp = (author_home.day_start(day) + timedelta(hours=12)).isoformat()
        with self.db.connection() as c:
            author_home.record_writing(c, {"id": project_id, "data_origin": "user_created"}, user_id or self.account["id"], chapter, net, stamp, draft_save=saves)


class MigrationTests(unittest.TestCase):
    def test_the_migration_is_repeatable_and_changes_no_existing_column(self):
        connection = sqlite3.connect(":memory:")
        connection.row_factory = sqlite3.Row
        connection.executescript(v2_database.SCHEMA)
        before = [tuple(row) for row in connection.execute("PRAGMA table_info(v2_users)")]
        author_home.migrate(connection)
        author_home.migrate(connection)
        after = [tuple(row) for row in connection.execute("PRAGMA table_info(v2_users)")]
        self.assertEqual(after[:len(before)], before, "every column that was there is as it was")
        self.assertEqual([row[1] for row in after[len(before):]], ["bio", "password_changed_at"])
        by_name = {row[1]: row for row in after}
        self.assertEqual((by_name["bio"][2], by_name["bio"][3], by_name["bio"][4]), ("TEXT", 1, "''"))
        self.assertEqual(by_name["password_changed_at"][3], 0)
        # An older release writes users by naming its columns; the new ones fall back to their defaults.
        connection.execute("INSERT INTO v2_users(id,account_name,display_name,password_hash,created_at) VALUES('u','old','旧','x','2026-01-01T00:00:00+00:00')")
        row = connection.execute("SELECT * FROM v2_users WHERE id='u'").fetchone()
        self.assertEqual((row["bio"], row["password_changed_at"]), ("", None))
        tables = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.assertIn("v2_writing_days", tables)

    def test_starting_the_app_twice_on_one_database_is_harmless(self):
        root = pathlib.Path(tempfile.mkdtemp(prefix="v180-home-mig-"))
        paths = AppPaths.from_project_root(root, protected_poc_root=root / "protected")
        first = create_app(paths, provider=Silent(), settings=Stage13Settings.for_test())
        with first.state.database.connection() as c:
            columns = [tuple(row) for row in c.execute("PRAGMA table_info(v2_users)")]
        second = create_app(paths, provider=Silent(), settings=Stage13Settings.for_test())
        with second.state.database.connection() as c:
            self.assertEqual([tuple(row) for row in c.execute("PRAGMA table_info(v2_users)")], columns)


class BioTests(HomeCase):
    def patch(self, **fields):
        user = self.session()
        body = {"base_profile_revision": user["profile_revision"], "display_name": user["display_name"], "avatar_preset": user["avatar_preset"], **fields}
        return self.client.patch("/api/auth/profile", headers=idem(), json=body)

    def test_a_new_account_has_an_empty_bio_a_join_time_and_no_password_change(self):
        user = self.session()
        self.assertEqual((user["bio"], user["password_changed_at"]), ("", None))
        self.assertTrue(user["created_at"].startswith("20"))

    def test_bio_accepts_empty_sixty_characters_and_refuses_sixty_one(self):
        self.assertEqual(self.patch(bio="").status_code, 200)
        self.assertEqual(self.session()["bio"], "")
        sixty = "写" * 60
        saved = self.patch(bio=sixty)
        self.assertEqual(saved.status_code, 200, saved.text)
        self.assertEqual(saved.json()["data"]["user"]["bio"], sixty)
        revision = self.session()["profile_revision"]
        refused = self.patch(bio="写" * 61)
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (400, "invalid_request"))
        self.assertEqual((self.session()["bio"], self.session()["profile_revision"]), (sixty, revision))

    def test_bio_is_one_line_trimmed_and_left_alone_when_not_sent(self):
        self.assertEqual(self.patch(bio="  写近未来的\n港口。 ").json()["data"]["user"]["bio"], "写近未来的 港口。")
        user = self.session()
        # An older client that does not know the field changes the name and leaves the bio.
        renamed = self.client.patch("/api/auth/profile", headers=idem(), json={"base_profile_revision": user["profile_revision"], "display_name": "新名字", "avatar_preset": user["avatar_preset"]})
        self.assertEqual(renamed.status_code, 200, renamed.text)
        self.assertEqual((self.session()["display_name"], self.session()["bio"]), ("新名字", "写近未来的 港口。"))

    def test_a_stale_revision_is_still_a_conflict(self):
        user = self.session()
        self.assertEqual(self.patch(bio="一").status_code, 200)
        stale = self.client.patch("/api/auth/profile", headers=idem(), json={"base_profile_revision": user["profile_revision"], "display_name": "x", "avatar_preset": user["avatar_preset"], "bio": "二"})
        self.assertEqual((stale.status_code, stale.json()["error"]["code"]), (409, "profile_revision_conflict"))

    def test_a_visitor_cannot_edit_it(self):
        visitor = self.new_client()
        user = visitor.post("/api/auth/visitor", headers=idem()).json()["data"]["user"]
        self.assertEqual(user["bio"], "")
        refused = visitor.patch("/api/auth/profile", headers=idem(), json={"base_profile_revision": 1, "display_name": "访客", "avatar_preset": "continuity_violet", "bio": "我"})
        self.assertEqual(refused.status_code, 403)


class PasswordTests(HomeCase):
    def change(self, current=PASSWORD, new="another-password-1", client=None):
        return (client or self.client).post("/api/auth/password", json={"current_password": current, "new_password": new})

    def second_session(self):
        with self.db.connection() as c:
            token, _ = self.db._new_session(c, self.account["id"])
        other = self.new_client()
        other.cookies.set("scc_local_session", token)
        self.assertEqual(other.get("/api/auth/session").status_code, 200)
        return other

    def test_a_wrong_current_password_is_a_400_not_a_lost_session(self):
        wrong = self.change(current="not-the-password")
        self.assertEqual((wrong.status_code, wrong.json()["error"]["code"]), (400, "current_password_incorrect"))
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200)
        self.assertIsNone(self.session()["password_changed_at"])

    def test_the_new_password_follows_the_rule_of_the_reset(self):
        for weak in ("short", "aaaaaaaaaaaa", "123456789"):
            refused = self.change(new=weak)
            self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (422, "password_policy_failed"), weak)
        self.assertIsNone(self.session()["password_changed_at"])

    def test_wrong_guesses_are_limited_per_user_five_in_fifteen_minutes(self):
        for _ in range(5):
            self.assertEqual(self.change(current="wrong-wrong-wrong").status_code, 400)
        limited = self.change()
        self.assertEqual((limited.status_code, limited.json()["error"]["code"], limited.json()["error"]["retryable"]), (429, "password_change_rate_limited", True))
        # Another account is not held back by it.
        other_client = self.new_client()
        self.register(other_client, "rate")
        self.assertEqual(self.change(client=other_client).status_code, 200)
        # Attempts older than the window no longer count.
        with self.db.connection() as c:
            c.execute("UPDATE v2_login_attempts SET attempted_at=? WHERE account_name=?", ((datetime.now(UTC) - timedelta(minutes=16)).isoformat(), f"password:{self.account['id']}"))
        self.assertEqual(self.change().status_code, 200)

    def test_success_keeps_this_session_ends_the_others_and_voids_reset_links(self):
        other = self.second_session()
        raw, _ = self.app.state.stage13._issue_token(self.account["id"], "password_reset", self.app.state.stage13.email_hash(self.account["email"]), 30)
        done = self.change()
        self.assertEqual(done.status_code, 200, done.text)
        self.assertTrue(done.json()["data"]["changed"])
        self.assertEqual(self.client.get("/api/auth/session").status_code, 200, "the session that changed it stays signed in")
        gone = other.get("/api/auth/session")
        self.assertEqual((gone.status_code, gone.json()["error"]["code"]), (401, "authentication_required"))
        reset = self.new_client().post("/api/auth/password-reset/confirm", headers=idem(), json={"token": raw, "password": "reset-password-777"})
        self.assertEqual((reset.status_code, reset.json()["error"]["code"]), (400, "recovery_token_invalid"))
        stamp = self.session()["password_changed_at"]
        self.assertIsNotNone(stamp)
        self.assertEqual(author_home.local_day(stamp), author_home.local_day(datetime.now(UTC)))
        self.assertEqual(self.new_client().post("/api/auth/login", headers=idem(), json={"account_name": self.account["name"], "password": "another-password-1"}).status_code, 200)

    def test_the_old_password_no_longer_signs_in(self):
        self.assertEqual(self.change().status_code, 200)
        old = self.new_client().post("/api/auth/login", headers=idem(), json={"account_name": self.account["name"], "password": PASSWORD})
        self.assertEqual(old.status_code, 401)

    def test_a_password_reset_is_dated_too(self):
        stage13 = self.app.state.stage13
        raw, _ = stage13._issue_token(self.account["id"], "password_reset", stage13.email_hash(self.account["email"]), 30)
        self.assertEqual(self.new_client().post("/api/auth/password-reset/confirm", headers=idem(), json={"token": raw, "password": "reset-password-777"}).status_code, 200)
        with self.db.connection() as c:
            self.assertIsNotNone(c.execute("SELECT password_changed_at FROM v2_users WHERE id=?", (self.account["id"],)).fetchone()[0])

    def test_a_visitor_gets_a_403(self):
        visitor = self.new_client()
        visitor.post("/api/auth/visitor", headers=idem())
        refused = self.change(client=visitor)
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (403, "password_change_not_allowed"))

    def test_it_needs_a_session_and_a_trusted_origin(self):
        self.assertEqual(self.change(client=self.new_client()).status_code, 401)
        crossed = self.client.post("/api/auth/password", headers={"Origin": "https://evil.example"}, json={"current_password": PASSWORD, "new_password": "another-password-1"})
        self.assertEqual(crossed.status_code, 403)


class WritingDayTests(HomeCase):
    def test_a_draft_save_records_the_net_characters_of_that_day(self):
        project = self.new_work()
        self.save(project, "春" * 100)
        self.save(project, "春" * 160)
        rows = self.days()
        self.assertEqual([(row["chapter_number"], row["net_chars"], row["saves"]) for row in rows], [(1, 160, 2)], "one chapter on one day is one row")
        self.assertEqual(rows[0]["day"], author_home.local_day(datetime.now(UTC)))
        self.save(project, "春" * 110)
        self.assertEqual(self.days()[0]["net_chars"], 110, "cut text takes characters off the day")

    def test_the_count_is_the_works_own_character_count(self):
        project = self.new_work()
        self.save(project, "  春 天\n\n来了。 " * 10)
        listed = next(row for row in self.client.get("/api/projects").json()["data"]["projects"] if row["id"] == project)
        self.assertEqual(self.days()[0]["net_chars"], listed["word_count"])
        self.assertGreater(listed["word_count"], 0)

    def test_cutting_more_than_the_day_wrote_shows_as_zero(self):
        project = self.new_work()
        today = author_home.local_day(datetime.now(UTC))
        yesterday = (datetime.fromisoformat(today) - timedelta(days=1)).date().isoformat()
        self.record(project, yesterday, 300)
        self.record(project, today, -120, saves=False)
        stored = {row["day"]: row["net_chars"] for row in self.days()}
        self.assertEqual((stored[yesterday], stored[today]), (300, -120))
        calendar = self.home()["calendar"]
        self.assertEqual((calendar["chars"][-2], calendar["chars"][-1]), (300, 0))
        self.assertEqual(self.home()["year"]["chars"], 300)

    def test_completing_a_draft_does_not_count_it_twice(self):
        project = self.new_work()
        text = "夜里的港口很安静。" * 20
        self.save(project, text)
        self.complete(project)
        total = sum(row["net_chars"] for row in self.days())
        self.assertEqual(total, written_chars(text), "the draft was written once")
        listed = next(row for row in self.client.get("/api/projects").json()["data"]["projects"] if row["id"] == project)
        self.assertEqual((listed["chapter_count"], listed["word_count"]), (1, written_chars(text)))
        self.assertEqual(self.home()["year"]["chars"], written_chars(text))

    def test_writing_a_second_chapter_adds_to_the_same_day(self):
        project = self.new_work()
        self.save(project, "一" * 50)
        self.complete(project)
        self.save(project, "二" * 70)
        by_chapter = {row["chapter_number"]: row["net_chars"] for row in self.days()}
        self.assertEqual(by_chapter, {1: 50, 2: 70})
        self.assertEqual(self.home()["totals"]["chars"], 120)

    def test_pasted_chapters_the_sample_and_a_visitors_sample_are_not_recorded(self):
        project = self.new_work()
        info = self.client.get(f"/api/projects/{project}").json()["data"]
        preview = self.client.post(f"/api/projects/{project}/source-change-sets/preview", headers=idem(), json={
            "mode": "append", "input_method": "paste", "base_source_revision": info["source_revision"], "content": "# 第一章\n" + "粘贴的正文。" * 30}).json()["data"]["source_change_set"]
        self.assertEqual(self.client.post(f"/api/projects/{project}/source-change-sets/{preview['id']}/commit", headers=idem(), json={"confirm": True, "content_sha256": preview["content_sha256"]}).status_code, 200)
        self.assertEqual(self.days(), [])
        sample = self.draft(self.account["sample"])
        self.assertEqual(self.client.patch(f"/api/projects/{self.account['sample']}/drafts/{sample['id']}", headers=idem(), json={"base_revision": sample["revision"], "body": "示例里改一改。" * 20}).status_code, 200)
        self.assertEqual(self.days(), [])
        visitor = self.new_client()
        user = visitor.post("/api/auth/visitor", headers=idem()).json()["data"]["user"]
        demo = next(row for row in visitor.get("/api/projects").json()["data"]["projects"] if row["data_origin"] == "demo_seed")
        draft = self.draft(demo["id"], visitor)
        self.assertEqual(visitor.patch(f"/api/projects/{demo['id']}/drafts/{draft['id']}", headers=idem(), json={"base_revision": draft["revision"], "body": "访客改一改。" * 20}).status_code, 200)
        self.assertEqual(self.days(user["id"]), [])

    def test_an_imported_work_is_written_in_like_any_other(self):
        preview = self.client.post("/api/imports/preview", headers=idem(), files={"file": ("base.md", "# 第一章\n旧章节正文。".encode(), "text/markdown")}).json()["data"]
        committed = self.client.post(f"/api/imports/{preview['import_id']}/commit", headers=idem(), json={"confirm": True, "title": "旧稿", "chapter_preview_ids": [x["preview_id"] for x in preview["detected"]["chapters"]]}).json()["data"]
        project = committed["project"]["id"]
        self.assertEqual(self.days(), [], "importing is not writing and the past is not back-filled")
        self.save(project, "续写的新章。" * 10)
        self.assertEqual(len(self.days()), 1)

    def test_a_chapter_revision_is_recorded_on_its_chapter(self):
        project = self.new_work()
        self.save(project, "第一版的正文。" * 10)
        self.complete(project)
        before = sum(row["net_chars"] for row in self.days())
        snapshot = self.client.get(f"/api/projects/{project}/long-term-review").json()["data"]
        chapter = snapshot["chapters"][0]
        ready = {"status": "ready_current", "blocking_reason": None, "counts": {"confirmed_core": 0}}
        patcher = mock.patch.object(v2_database.V2Database, "_memory_coverage", return_value=ready)
        patcher.start()
        self.addCleanup(patcher.stop)
        preview = self.client.post(f"/api/projects/{project}/chapters/{chapter['id']}/revisions/preview", headers=idem(), json={
            "base_source_revision": snapshot["source_revision"], "base_chapter_revision": chapter["source_revision"], "title": chapter["title"], "body": chapter["body"] + "补写的一句话。"})
        self.assertEqual(preview.status_code, 201, preview.text)
        change = preview.json()["data"]["revision_preview"]
        committed = self.client.post(f"/api/projects/{project}/chapter-revisions/{change['id']}/commit", headers=idem(), json={"confirm": True, "content_sha256": change["content_sha256"]})
        self.assertEqual(committed.status_code, 200, committed.text)
        self.assertEqual(sum(row["net_chars"] for row in self.days()), before + written_chars("补写的一句话。"))
        self.assertEqual(sum(row["saves"] for row in self.days()), 1, "a revision is not a draft save")

    def test_the_day_turns_over_at_midnight_in_beijing(self):
        self.assertEqual(author_home.local_day("2026-10-17T15:59:59+00:00"), "2026-10-17")
        self.assertEqual(author_home.local_day("2026-10-17T16:00:00+00:00"), "2026-10-18")
        self.assertEqual(author_home.local_day("2026-10-17T16:01:00+00:00"), "2026-10-18")
        self.assertEqual(author_home.local_day("2026-10-17T16:01:00Z"), "2026-10-18")
        with self.db.connection() as c:
            for stamp in ("2026-10-17T15:59:00+00:00", "2026-10-17T16:01:00+00:00"):
                author_home.record_writing(c, {"id": "p", "data_origin": "user_created"}, self.account["id"], 1, 10, stamp, draft_save=True)
        self.assertEqual([(row["day"], row["net_chars"]) for row in self.days()], [("2026-10-17", 10), ("2026-10-18", 10)])
        self.assertEqual(author_home.DAY_UTC_OFFSET_HOURS, 8)


class StreakTests(HomeCase):
    NOW = datetime(2026, 10, 18, 2, 0, tzinfo=UTC)  # 10:00 on 18 October in Beijing

    def streak(self):
        with mock.patch.object(author_home, "_now", return_value=self.NOW):
            totals = self.home()["totals"]
        return totals["streak_days"], totals["streak_includes_today"]

    def test_nothing_written_is_zero(self):
        self.assertEqual(self.streak(), (0, False))

    def test_written_today_counts_today(self):
        for day in ("2026-10-16", "2026-10-17", "2026-10-18"):
            self.record("p", day, 100)
        self.assertEqual(self.streak(), (3, True))

    def test_not_yet_written_today_the_run_up_to_yesterday_stands(self):
        for day in ("2026-10-15", "2026-10-16", "2026-10-17"):
            self.record("p", day, 100)
        self.assertEqual(self.streak(), (3, False))

    def test_a_missed_day_ends_the_run(self):
        for day in ("2026-10-10", "2026-10-11", "2026-10-12", "2026-10-16", "2026-10-17"):
            self.record("p", day, 100)
        self.assertEqual(self.streak(), (2, False))
        self.record("p", "2026-10-14", 100)
        self.assertEqual(self.streak(), (2, False))
        self.record("p", "2026-10-13", 100)
        self.record("p", "2026-10-15", 100)
        self.assertEqual(self.streak(), (8, False))

    def test_a_day_of_only_cuts_is_not_a_writing_day(self):
        self.record("p", "2026-10-17", 100)
        self.record("p", "2026-10-16", 100)
        self.record("p", "2026-10-18", -40, saves=False)
        self.assertEqual(self.streak(), (2, False))

    def test_days_with_nothing_but_the_day_before_yesterday_are_zero(self):
        self.record("p", "2026-10-16", 100)
        self.assertEqual(self.streak(), (0, False))

    def test_the_year_figures_and_the_five_shades(self):
        for index, (day, net) in enumerate([("2026-10-10", 100), ("2026-10-11", 400), ("2026-10-12", 900), ("2026-10-13", 2000), ("2026-10-14", 8000), ("2026-10-16", 50)]):
            self.record("p", day, net)
        with mock.patch.object(author_home, "_now", return_value=self.NOW):
            home = self.home()
        calendar = home["calendar"]
        self.assertEqual((calendar["start"], calendar["end"], len(calendar["chars"]), len(calendar["levels"])), ("2025-10-19", "2026-10-18", 365, 365))
        by_day = {author_home._shift(calendar["start"], i): (calendar["chars"][i], calendar["levels"][i]) for i in range(365)}
        self.assertEqual(by_day["2026-10-17"], (0, 0))
        levels = [by_day[day][1] for day in ("2026-10-16", "2026-10-10", "2026-10-11", "2026-10-12", "2026-10-13", "2026-10-14")]
        self.assertEqual(levels, sorted(levels), "more writing is never lighter")
        self.assertEqual((levels[0], levels[-1]), (1, 4))
        self.assertEqual(set(levels), {1, 2, 3, 4})
        self.assertEqual(home["year"], {"chars": 11450, "writing_days": 6, "best_day": {"day": "2026-10-14", "chars": 8000}, "longest_streak": 5, "checked_chapters": 0})

    def test_a_single_writing_day_is_not_the_palest(self):
        self.record("p", "2026-10-17", 500)
        with mock.patch.object(author_home, "_now", return_value=self.NOW):
            levels = [level for level in self.home()["calendar"]["levels"] if level]
        self.assertEqual(levels, [3])

    def test_the_calendar_is_the_window_of_365_days_ending_today(self):
        self.record("p", "2025-10-18", 700)  # one day before the window
        self.record("p", "2025-10-19", 300)
        with mock.patch.object(author_home, "_now", return_value=self.NOW):
            home = self.home()
        self.assertEqual((home["calendar"]["chars"][0], home["year"]["chars"], home["year"]["writing_days"]), (300, 300, 1))


class HomePayloadTests(HomeCase):
    def test_the_figures_leave_the_sample_out_and_count_like_the_works_list(self):
        first, second = self.new_work("一号"), self.new_work("二号")
        self.save(first, "字" * 120)
        self.complete(first)
        self.save(first, "字" * 30)
        self.save(second, "字" * 40)
        home = self.home()
        self.assertEqual(home["totals"], {"works": 2, "chapters": 1, "chars": 190, "streak_days": 1, "streak_includes_today": True})
        listed = {row["id"]: row for row in self.client.get("/api/projects").json()["data"]["projects"]}
        for work in home["works"]:
            self.assertEqual((work["chapter_count"], work["word_count"], work["continuity_status"], work["open_issue_count"]),
                             (listed[work["id"]]["chapter_count"], listed[work["id"]]["word_count"], listed[work["id"]]["continuity_status"], listed[work["id"]]["open_issue_count"]))
        self.assertNotIn(self.account["sample"], {work["id"] for work in home["works"]})
        self.assertEqual(home["profile"]["account_type"], "registered")

    def test_every_work_is_listed_archived_ones_too_but_no_plan_length_is_invented(self):
        projects = [self.new_work(f"作品{index}") for index in range(8)]
        archived = projects[0]
        info = self.client.get(f"/api/projects/{archived}").json()["data"]
        self.assertEqual(self.client.patch(f"/api/projects/{archived}", headers=idem(), json={"base_metadata_revision": info["metadata_revision"], "status": "archived", "confirm_archive": True}).status_code, 200)
        works = self.home()["works"]
        self.assertEqual(len(works), 8)
        self.assertEqual(next(work for work in works if work["id"] == archived)["status"], "archived")
        self.assertTrue(all("planned_chapters" not in work for work in works))

    def test_the_work_being_written_is_the_one_whose_draft_was_saved_last(self):
        self.assertIsNone(self.home()["current"])
        first, second = self.new_work("甲"), self.new_work("乙")
        self.assertIsNone(self.home()["current"], "an empty draft is not being written")
        self.save(first, "甲的草稿。" * 10)
        self.save(second, "乙的草稿。" * 20)
        current = self.home()["current"]
        self.assertEqual((current["project_id"], current["chapter_number"], current["chars"], current["check_state"]), (second, 1, written_chars("乙的草稿。" * 20), "unchecked"))
        self.save(first, "甲的草稿。" * 11)
        self.assertEqual(self.home()["current"]["project_id"], first)
        info = self.client.get(f"/api/projects/{first}").json()["data"]
        self.client.patch(f"/api/projects/{first}", headers=idem(), json={"base_metadata_revision": info["metadata_revision"], "status": "archived", "confirm_archive": True})
        self.assertEqual(self.home()["current"]["project_id"], second, "an archived work is read-only")

    def test_the_check_state_of_the_current_chapter(self):
        project = self.new_work()
        draft_id = self.save(project, "要检查的草稿。" * 10)
        revision = self.draft(project)["revision"]
        with self.db.connection() as c:
            c.execute("INSERT INTO v2_runs(id,project_id,draft_id,source_revision,status,stage,provider_label,created_at,completed_at) VALUES('run-x',?,?,?,'completed','completed','p','2026-10-01T00:00:00+00:00','2026-10-01T00:01:00+00:00')", (project, draft_id, revision))
        self.assertEqual(self.home()["current"]["check_state"], "checked")
        self.save(project, "要检查的草稿。" * 11)
        self.assertEqual(self.home()["current"]["check_state"], "edited")

    def test_a_visitor_has_a_home_with_the_expiry_and_no_sample_work(self):
        visitor = self.new_client()
        visitor.post("/api/auth/visitor", headers=idem())
        home = self.home(visitor)
        self.assertEqual((home["profile"]["account_type"], home["profile"]["bio"], home["totals"]["works"], home["works"]), ("visitor", "", 0, []))
        self.assertIsNotNone(home["profile"]["visitor_expires_at"])

    def test_it_needs_a_session(self):
        self.assertEqual(self.new_client().get("/api/account/home").status_code, 401)

    def test_it_is_read_in_one_pass_not_once_per_work(self):
        for index in range(6):
            project = self.new_work(f"作品{index}")
            self.save(project, "写。" * 10)
        statements = []
        original = sqlite3.Connection

        class Counting(original):
            def execute(self, sql, *args):
                statements.append(sql)
                return super().execute(sql, *args)

        with mock.patch.object(sqlite3, "connect", lambda *a, **k: original(*a, **{**k, "factory": Counting})):
            self.home()
        small = len(statements)
        statements.clear()
        for index in range(6, 14):
            project = self.new_work(f"作品{index}")
            self.save(project, "写。" * 10)
        with mock.patch.object(sqlite3, "connect", lambda *a, **k: original(*a, **{**k, "factory": Counting})):
            self.home()
        # Each work costs the issue count, nothing per chapter, run or event.
        self.assertLessEqual(len(statements) - small, 8 * 3)


class ActivityTests(HomeCase):
    def feed(self):
        return self.home()["activity"]

    def test_a_new_work_a_saved_draft_and_a_finished_chapter(self):
        project = self.new_work("夜航")
        self.save(project, "草稿的内容很机密。" * 5)
        self.save(project, "草稿的内容很机密。" * 8)
        events = self.feed()
        self.assertEqual([item["kind"] for item in events], ["draft_saved", "project_created"])
        saved = events[0]
        self.assertEqual((saved["project_title"], saved["chapter_number"], saved["net_chars"]), ("夜航", 1, written_chars("草稿的内容很机密。" * 8)))
        self.assertEqual(events[1]["origin"], "user_created")
        self.complete(project)
        events = self.feed()
        self.assertEqual(events[0]["kind"], "chapter_finished")
        self.assertEqual(events[0]["chapter_numbers"], [1])
        self.assertEqual(sum(item["kind"] == "draft_saved" for item in events), 1, "saves of one chapter on one day are one entry")

    def test_no_text_of_the_work_ever_reaches_the_feed(self):
        project = self.new_work("夜航")
        self.save(project, "绝密正文SECRET-BODY。" * 5)
        self.complete(project)
        self.add_adopted(project, "SECRET-BEFORE", "SECRET-AFTER", 1)
        payload = json.dumps(self.home()["activity"], ensure_ascii=False)
        for text in ("SECRET", "绝密正文"):
            self.assertNotIn(text, payload)
        keys = {key for item in self.feed() for key in item}
        self.assertTrue(keys <= {"kind", "at", "day", "project_id", "project_title", "chapter_number", "chapter_numbers", "chapter_title", "net_chars", "issue_count", "origin"}, keys)

    def add_adopted(self, project, before, after, chapter, decided="2026-10-12T04:00:00+00:00", status="adopted"):
        task = f"atask-{uuid.uuid4()}"
        with self.db.connection() as c:
            c.execute("INSERT INTO assistant_tasks(id,project_id,user_id,kind,status,input_json,source_revision,memory_version,author_context_version,scope_json,prompt_version,model_label,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (task, project, self.account["id"], "fix_issue", "completed", "{}", 1, 1, 0, "{}", "p", "m", decided))
            c.execute("INSERT INTO assistant_proposals(id,task_id,ordinal,kind,target,chapter_number,before,after,rationale,status,decided_at,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                      (f"prop-{uuid.uuid4()}", task, 1, "edit_this", "t", chapter, before, after, "r", status, decided if status == "adopted" else None, decided))

    def test_adopted_proposals_are_listed_and_the_undone_or_dismissed_are_not(self):
        project = self.new_work()
        self.add_adopted(project, "a", "b", 3)
        self.add_adopted(project, "a", "b", 4, status="proposed")
        self.add_adopted(project, "a", "b", 5, status="dismissed")
        adopted = [item for item in self.feed() if item["kind"] == "assistant_adopted"]
        self.assertEqual([(item["chapter_number"], item["at"], item["day"]) for item in adopted], [(3, "2026-10-12T04:00:00+00:00", "2026-10-12")])

    def add_run(self, project, run_type="continuity", completed="2026-10-13T04:00:00+00:00", issues=0, report=None, draft_id=None, **columns):
        run = f"run-{uuid.uuid4()}"
        with self.db.connection() as c:
            draft_id = draft_id or c.execute("SELECT id FROM v2_drafts WHERE project_id=?", (project,)).fetchone()[0]
            fields = {"id": run, "project_id": project, "draft_id": draft_id, "source_revision": 1, "status": "completed", "stage": "completed", "provider_label": "p",
                      "created_at": completed, "completed_at": completed, "run_type": run_type, **columns}
            c.execute(f"INSERT INTO v2_runs({','.join(fields)}) VALUES({','.join('?' * len(fields))})", list(fields.values()))
            for index in range(issues):
                c.execute("INSERT INTO v2_issues(id,project_id,run_id,claim_span_id,status,category,severity,evidence_status,explanation) VALUES(?,?,?,?,?,?,?,?,?)",
                          (f"issue-{uuid.uuid4()}", project, run, f"claim-{index}", "open", "attribute", "high", "sufficient", "SECRET-EXPLANATION"))
            if report is not None:
                c.execute("INSERT INTO v2_analysis_results VALUES(?,?,?,?,?)", (run, project, run_type, json.dumps(report, ensure_ascii=False), completed))
        return run

    def test_a_draft_check_a_chapter_check_and_what_does_not_count(self):
        project = self.new_work("检查")
        self.save(project, "待检查的草稿。" * 5)
        self.add_run(project, issues=2)
        self.add_run(project, "chapter_check", "2026-10-14T04:00:00+00:00", report={"chapters": [{"chapter_number": 2, "issues": []}, {"chapter_number": 5, "issues": [{}]}], "issue_count": 1})
        self.add_run(project, status="failed", completed="2026-10-15T04:00:00+00:00")
        self.add_run(project, completed="2026-10-16T04:00:00+00:00", result_origin="demo_preset")
        self.add_run(project, completed="2026-10-17T04:00:00+00:00", incremental_batch_id="batch")
        self.add_run(project, "memory_delta", "2026-10-18T04:00:00+00:00")
        checks = [item for item in self.feed() if item["kind"] == "checked"]
        self.assertEqual([(item["at"][:10], item["chapter_numbers"], item["issue_count"]) for item in checks], [("2026-10-14", [2, 5], 1), ("2026-10-13", [1], 2)])
        self.assertNotIn("SECRET", json.dumps(self.home()["activity"]))
        self.assertEqual(self.home()["year"]["checked_chapters"], 3, "chapter 1 by the draft check, chapters 2 and 5 by the chapter check")

    def test_checked_chapters_of_the_year_are_distinct_chapters_of_this_authors_works(self):
        project = self.new_work("检查")
        self.save(project, "待检查的草稿。" * 5)
        recent = (datetime.now(UTC) - timedelta(days=3)).isoformat()
        self.add_run(project, completed=recent)
        self.add_run(project, completed=recent)
        self.add_run(project, "chapter_check", recent, report={"chapters": [{"chapter_number": 1, "issues": []}, {"chapter_number": 2, "issues": []}], "issue_count": 0})
        self.assertEqual(self.home()["year"]["checked_chapters"], 2)

    def test_the_sample_work_and_other_authors_never_appear(self):
        sample = self.account["sample"]
        self.add_run(sample, issues=1)
        self.add_adopted(sample, "a", "b", 2)
        other = self.new_client()
        self.register(other, "other")
        stranger = self.new_work("别人的", other)
        self.save(stranger, "别人的字。" * 5, other)
        self.assertEqual(self.feed(), [])
        self.assertEqual(self.home()["totals"]["works"], 0)

    def test_at_most_twenty_newest_first(self):
        project = self.new_work()
        base = datetime(2026, 9, 1, tzinfo=UTC)
        with self.db.connection() as c:
            for number in range(1, 26):
                author_home.record_writing(c, {"id": project, "data_origin": "user_created"}, self.account["id"], number, number, (base + timedelta(days=number)).isoformat(), draft_save=True)
        events = self.feed()
        self.assertEqual(len(events), 20)
        self.assertEqual([item["kind"] for item in events[:2]], ["project_created", "draft_saved"])
        self.assertEqual([item["chapter_number"] for item in events[1:]], list(range(25, 6, -1)))
        self.assertEqual(events[1]["day"], "2026-09-26")

    def test_chapter_names_come_from_the_chapter_table(self):
        project = self.new_work()
        self.save(project, "正文。" * 10)
        self.complete(project)
        with self.db.connection() as c:
            c.execute("UPDATE v2_chapters SET title=? WHERE project_id=? AND chapter_number=1", ("桌上的留白", project))
        self.assertEqual({item["chapter_title"] for item in self.feed() if item["chapter_number"] == 1}, {"桌上的留白"})


class DailyUsageTests(HomeCase):
    def spend(self, kind, chars, at, run="r"):
        stage13 = self.app.state.stage13
        reservation = stage13.reserve_workflow(self.account["id"], None, kind, f"{run}-{uuid.uuid4()}", characters=chars, character_kind="check")
        with self.db.connection() as c:
            c.execute("UPDATE v2_character_usage SET created_at=? WHERE id=?", (at.isoformat(), f"chars-{reservation}"))
            c.execute("UPDATE v2_usage_reservations SET created_at=? WHERE id=?", (at.isoformat(), reservation))
        return reservation

    def usage(self, days=7):
        response = self.client.get(f"/api/account/usage/daily?days={days}")
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_checks_and_the_assistant_are_told_apart_per_day(self):
        now = datetime.now(UTC)
        self.spend("continuity", 1200, now - timedelta(minutes=5))
        self.spend("chapter_check", 800, now - timedelta(minutes=4))
        self.spend("assistant_task", 500, now - timedelta(minutes=3))
        self.spend("assistant_recheck", 60, now - timedelta(minutes=2))
        self.spend("continuity", 300, now - timedelta(days=2))
        self.spend("assistant_task", 500, now - timedelta(days=3))
        data = self.usage()
        self.assertEqual(len(data["days"]), 7)
        self.assertEqual(data["days"][-1]["day"], data["today"])
        by_day = {row["day"]: row for row in data["days"]}
        today = by_day[data["today"]]
        if author_home.local_day(now - timedelta(minutes=5)) == data["today"] == author_home.local_day(now - timedelta(minutes=2)):
            self.assertEqual((today["check_chars"], today["assistant_chars"]), (2000, 560))
        total = lambda key: sum(row[key] for row in data["days"])
        self.assertEqual((total("check_chars"), total("assistant_chars")), (2300, 1060))
        self.assertEqual(by_day[author_home.local_day(now - timedelta(days=3))]["assistant_chars"], 500)

    def test_an_assistant_task_in_the_real_flow_lands_in_the_assistant_column(self):
        project = self.new_work()
        stage13 = self.app.state.stage13
        stage13.reserve_workflow(self.account["id"], project, "assistant_task", "atask-1", characters=500, character_kind="check")
        stage13.reserve_workflow(self.account["id"], project, "continuity", "run-1", characters=700, character_kind="check")
        data = self.usage()
        self.assertEqual((sum(r["check_chars"] for r in data["days"]), sum(r["assistant_chars"] for r in data["days"])), (700, 500))
        self.assertEqual(self.client.get("/api/account/usage").json()["data"]["check_chars_used"], 1200)

    def test_days_are_one_to_thirty_one(self):
        self.assertEqual(len(self.usage(1)["days"]), 1)
        self.assertEqual(len(self.usage(31)["days"]), 31)
        for bad in (0, 32, -1):
            self.assertEqual(self.client.get(f"/api/account/usage/daily?days={bad}").status_code, 400, bad)
        self.assertEqual(self.client.get("/api/account/usage/daily?days=x").status_code, 400)
        self.assertEqual(len(self.client.get("/api/account/usage/daily").json()["data"]["days"]), 7)

    def test_the_oldest_charge_in_the_window_says_when_room_comes_back(self):
        self.assertIsNone(self.usage()["oldest_charge"])
        now = datetime.now(UTC)
        self.spend("continuity", 900, now - timedelta(hours=30))
        self.assertIsNone(self.usage()["oldest_charge"], "a charge older than 24 hours is already back")
        early = now - timedelta(hours=20)
        self.spend("continuity", 400, early)
        self.spend("continuity", 100, now - timedelta(hours=1))
        oldest = self.usage()["oldest_charge"]
        self.assertEqual(oldest["chars"], 400)
        self.assertAlmostEqual(datetime.fromisoformat(oldest["recovers_at"]).timestamp(), (early + timedelta(hours=24)).timestamp(), delta=1)

    def test_the_days_are_beijing_days(self):
        fixed = datetime(2026, 10, 18, 2, 0, tzinfo=UTC)
        with mock.patch.object(author_home, "_now", return_value=fixed):
            with self.db.connection() as c:
                for stamp, chars in (("2026-10-17T15:59:00+00:00", 10), ("2026-10-17T16:01:00+00:00", 20)):
                    c.execute("INSERT INTO v2_character_usage VALUES(?,?,?,?,?,?,?)", (f"chars-{uuid.uuid4()}", self.account["id"], None, None, "check", chars, stamp))
            data = self.usage(2)
        self.assertEqual([(row["day"], row["check_chars"]) for row in data["days"]], [("2026-10-17", 10), ("2026-10-18", 20)])

    def test_imports_are_not_check_characters_and_other_authors_do_not_show(self):
        now = datetime.now(UTC)
        with self.db.connection() as c:
            c.execute("INSERT INTO v2_character_usage VALUES(?,?,?,?,?,?,?)", ("chars-import", self.account["id"], None, None, "import", 9000, now.isoformat()))
        other = self.new_client()
        mine = self.register(other, "usage")
        self.app.state.stage13.reserve_workflow(mine["id"], None, "continuity", "r", characters=1234, character_kind="check")
        self.assertEqual(sum(row["check_chars"] for row in self.usage()["days"]), 0)

    def test_it_needs_a_session(self):
        self.assertEqual(self.new_client().get("/api/account/usage/daily").status_code, 401)


class ExportAllTests(HomeCase):
    def export(self, client=None):
        return (client or self.client).get("/api/account/export")

    def test_every_work_with_its_draft_in_one_zip_and_no_sample(self):
        first, second = self.new_work("夜航"), self.new_work("纸灯")
        self.save(first, "已入库的章节。" * 5)
        self.complete(first)
        self.save(first, "还没入库的草稿EXPORTED-DRAFT。")
        self.save(second, "第二部的草稿。")
        info = self.client.get(f"/api/projects/{second}").json()["data"]
        self.client.patch(f"/api/projects/{second}", headers=idem(), json={"base_metadata_revision": info["metadata_revision"], "status": "archived", "confirm_archive": True})
        response = self.export()
        self.assertEqual(response.status_code, 200, response.text[:200])
        self.assertEqual(response.headers["content-type"], "application/zip")
        self.assertRegex(response.headers["content-disposition"], r"filename\*=UTF-8''story-continuity-%E5%85%A8%E9%83%A8%E4%BD%9C%E5%93%81-\d{8}\.zip")
        self.assertIn(author_home.local_day(datetime.now(UTC)).replace("-", ""), response.headers["content-disposition"])
        archive = zipfile.ZipFile(io.BytesIO(response.content))
        names = archive.namelist()
        index = json.loads(archive.read("index.json"))
        self.assertEqual([item["title"] for item in index["works"]], ["夜航", "纸灯"])
        for item in index["works"]:
            for name in ("manuscript.txt", "manuscript.md", "materials.md", "snapshot.json", "README.txt", "checksums.json"):
                self.assertIn(f"{item['folder']}/{name}", names)
        self.assertIn("README.txt", names)
        first_snapshot = json.loads(archive.read(f"{index['works'][0]['folder']}/snapshot.json"))
        self.assertEqual(first_snapshot["scope"]["draft"], "current_saved_nonempty_draft")
        self.assertIn("EXPORTED-DRAFT", first_snapshot["drafts"][0]["body"])
        self.assertIn("EXPORTED-DRAFT", archive.read(f"{index['works'][0]['folder']}/manuscript.txt").decode())
        second_snapshot = json.loads(archive.read(f"{index['works'][1]['folder']}/snapshot.json"))
        self.assertEqual(second_snapshot["project"]["status"], "archived")
        everything = b"".join(archive.read(name) for name in names)
        self.assertNotIn("灰港".encode(), everything, "the sample work is not in it")
        self.assertEqual(len(index["works"]), 2)

    def test_the_files_are_the_single_work_bundle(self):
        project = self.new_work("夜航")
        self.save(project, "草稿。" * 5)
        single = zipfile.ZipFile(io.BytesIO(self.client.get(f"/api/projects/{project}/export?format=bundle&include_draft=true").content))
        whole = zipfile.ZipFile(io.BytesIO(self.export().content))
        folder = next(name.split("/")[0] for name in whole.namelist() if name.endswith("manuscript.txt"))
        self.assertEqual(sorted(name.split("/", 1)[1] for name in whole.namelist() if name.startswith(folder + "/")), sorted(single.namelist()))
        self.assertEqual(whole.read(f"{folder}/manuscript.txt"), single.read("manuscript.txt"))

    def test_an_account_with_no_works_still_gets_a_zip(self):
        archive = zipfile.ZipFile(io.BytesIO(self.export().content))
        self.assertEqual(json.loads(archive.read("index.json"))["works"], [])

    def test_a_visitor_gets_a_403(self):
        visitor = self.new_client()
        visitor.post("/api/auth/visitor", headers=idem())
        refused = self.export(visitor)
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (403, "export_not_allowed"))

    def test_it_needs_a_session(self):
        self.assertEqual(self.export(self.new_client()).status_code, 401)

    def test_three_in_ten_minutes(self):
        for _ in range(3):
            self.assertEqual(self.export().status_code, 200)
        limited = self.export()
        self.assertEqual((limited.status_code, limited.json()["error"]["code"]), (429, "export_rate_limited"))
        with self.db.connection() as c:
            c.execute("UPDATE v2_login_attempts SET attempted_at=? WHERE account_name=?", ((datetime.now(UTC) - timedelta(minutes=11)).isoformat(), f"export:{self.account['id']}"))
        self.assertEqual(self.export().status_code, 200)

    def test_too_large_is_refused(self):
        project = self.new_work("夜航")
        self.save(project, "草稿。" * 5)
        with mock.patch("app.project_export.MAX_EXPORT_BYTES", 100):
            refused = self.export()
        self.assertEqual((refused.status_code, refused.json()["error"]["code"]), (413, "export_too_large"))

    def test_only_this_authors_works(self):
        other = self.new_client()
        self.register(other, "else")
        self.new_work("别人的书", other)
        mine = self.new_work("我的书")
        index = json.loads(zipfile.ZipFile(io.BytesIO(self.export().content)).read("index.json"))
        self.assertEqual([item["title"] for item in index["works"]], ["我的书"])
        self.assertTrue(mine)


class CleanupTests(HomeCase):
    def test_deleting_a_work_removes_its_writing_days_and_only_those(self):
        keep, drop = self.new_work("留下"), self.new_work("删掉")
        self.save(keep, "留。" * 10)
        self.save(drop, "删。" * 10)
        self.assertEqual({row["project_id"] for row in self.days()}, {keep, drop})
        with self.db.connection() as c:
            self.db.purge_project(c, drop)
        self.assertEqual({row["project_id"] for row in self.days()}, {keep})

    def test_an_expired_visitor_leaves_nothing_behind(self):
        visitor = self.new_client()
        user = visitor.post("/api/auth/visitor", headers=idem()).json()["data"]["user"]
        project = self.new_work("访客的书", visitor)
        self.save(project, "访客写的。" * 10, visitor)
        self.assertEqual(len(self.days(user["id"])), 1)
        with self.db.connection() as c:
            c.execute("INSERT INTO v2_login_attempts VALUES(?,?)", (f"export:{user['id']}", datetime.now(UTC).isoformat()))
            c.execute("INSERT INTO v2_login_attempts VALUES(?,?)", (f"password:{user['id']}", datetime.now(UTC).isoformat()))
            c.execute("UPDATE v2_users SET visitor_expires_at=? WHERE id=?", ((datetime.now(UTC) - timedelta(hours=1)).isoformat(), user["id"]))
        self.assertEqual(self.app.state.stage13.cleanup_expired_visitors()["visitor_count"], 1)
        self.assertEqual(self.days(user["id"]), [])
        with self.db.connection() as c:
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_writing_days WHERE project_id=?", (project,)).fetchone()[0], 0)
            self.assertEqual(c.execute("SELECT COUNT(*) FROM v2_login_attempts WHERE account_name LIKE ?", (f"%:{user['id']}",)).fetchone()[0], 0)
            self.assertIsNone(c.execute("SELECT 1 FROM v2_users WHERE id=?", (user["id"],)).fetchone())
        self.assertEqual(len(self.home()["works"]), 0, "a registered author's own data is untouched")


if __name__ == "__main__":
    unittest.main()
