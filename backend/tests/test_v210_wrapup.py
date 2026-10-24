"""v2.1 wrap-up: a sample work takes no characters, the change ledger lists adopted proposals and pages by position, a task older than
the page's list can be read with its chain, and every error code the assistant returns has words on the page."""
from __future__ import annotations

import json
import pathlib
import re
import unittest

from app.assistant_store import AssistantStore
from app.database import DomainError

from tests.assistant_case import AssistantCase
from tests.scripted_chat import call, turn
from tests.test_assistant import cite
from tests.test_assistant_limits import read
from tests.test_assistant_v180 import FINAL, Task04Case

ROOT = pathlib.Path(__file__).resolve().parents[2]


class SampleWorkIsFreeTests(AssistantCase):
    """The demo and the tutorial's work: the day's counts and the server's budget still stand, the characters are not touched."""

    def reservations(self) -> int:
        return self.rows("SELECT COUNT(*) n FROM v2_usage_reservations WHERE workflow_kind='assistant_task'")[0]["n"]

    def test_a_task_on_the_sample_work_takes_no_characters_but_is_counted(self):
        self.start()
        self.register()
        task = self.run_ask(read(9), cite(9))
        self.assertEqual(task["status"], "completed", task)
        self.assertEqual(task["usage"]["chars_charged"], 0)
        self.assertEqual(self.usage()["check_chars_used"], 0)
        self.assertEqual(self.rows("SELECT chars_charged FROM assistant_tasks")[0]["chars_charged"], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_character_usage")[0]["n"], 0)
        self.assertEqual(self.reservations(), 1)

    def test_a_task_on_the_authors_own_work_still_takes_its_characters(self):
        self.start()
        self.register()
        self.own_work()
        task = self.run_ask(read(9), cite(9))
        self.assertEqual(task["usage"]["chars_charged"], 500)
        self.assertEqual(self.usage()["check_chars_used"], 500)

    def test_the_sample_work_stays_open_when_the_allowance_is_used_up(self):
        self.start(registered_check_chars=400)
        self.register()
        self.run_ask(read(9), cite(9))
        self.assertEqual(self.usage()["check_chars_remaining"], 400)
        self.own_work()
        self.provider.script(read(9), cite(9))
        error = self.ask(expect=429).json()["error"]
        self.assertEqual(error["code"], "character_quota_exceeded")

    def test_the_days_count_is_kept_on_the_sample_work(self):
        self.start(registered_workflows=2)
        self.register()
        for _ in range(2):
            self.run_ask(read(9), cite(9))
        self.provider.script(read(9), cite(9))
        self.assertEqual(self.ask(expect=429).json()["error"]["code"], "workflow_quota_exceeded")
        self.assertEqual(self.usage()["check_chars_used"], 0)

    def test_a_check_reserves_no_characters_on_the_sample_work(self):
        self.start(registered_check_chars=400)
        self.register()
        sample = self.project_id
        reserve = self.stage13.reserve_workflow
        reserve(self.user_id, sample, "chapter_check", "run-sample", characters=5000, character_kind="check")
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_character_usage")[0]["n"], 0)
        self.assertEqual(self.rows("SELECT COUNT(*) n FROM v2_usage_reservations WHERE run_id='run-sample'")[0]["n"], 1)
        self.own_work()
        with self.assertRaises(DomainError) as refused:
            reserve(self.user_id, sample, "chapter_check", "run-own", characters=5000, character_kind="check")
        self.assertEqual(refused.exception.code, "character_quota_exceeded")
        reserve(self.user_id, sample, "chapter_check", "run-own", characters=300, character_kind="check")
        self.assertEqual(self.usage()["check_chars_used"], 300)

    def test_the_point_check_allowance_is_free_there_too(self):
        self.start()
        self.register()
        task = self.run_ask(read(9), cite(9))
        reservation = self.rows("SELECT reservation_id FROM assistant_tasks")[0]["reservation_id"]
        self.stage13.spend_extra_characters(self.user_id, self.project_id, task["id"], reservation, 120)
        self.assertEqual(self.usage()["check_chars_used"], 0)
        self.own_work()
        self.stage13.spend_extra_characters(self.user_id, self.project_id, task["id"], reservation, 120)
        self.assertEqual(self.usage()["check_chars_used"], 120)

    def test_a_visitor_is_not_charged_as_before(self):
        self.start()
        self.visitor()
        task = self.run_ask(read(9), cite(9))
        self.assertEqual(task["usage"]["chars_charged"], 0)


class AdoptionLedgerTests(Task04Case):
    def finished(self, *extra_calls):
        task = self.fix(turn(*self.proposals_turn()["calls"], *extra_calls), FINAL)
        self.assertEqual(task["status"], "completed", task)
        return task

    def adopt_edit(self, task, proposal, after=None):
        body = self.rows("SELECT body FROM v2_drafts WHERE project_id=?", self.project_id)[0]["body"]
        revision = self.save(body.replace(proposal["before"], after or proposal["after"])) if proposal["before"] in body else \
            self.rows("SELECT revision FROM v2_drafts WHERE project_id=?", self.project_id)[0]["revision"]
        payload = {"draft_revision": revision, **({"after": after} if after else {})}
        response = self.action(task, proposal, "adopt", payload)
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def ledger(self, **query):
        params = "&".join(f"{name}={value}" for name, value in query.items())
        response = self.client.get(f"/api/projects/{self.project_id}/assistant/changes" + (f"?{params}" if params else ""))
        self.assertEqual(response.status_code, 200, response.text)
        return response.json()["data"]

    def test_an_adopted_proposal_is_listed_and_stays_when_the_adoption_is_undone(self):
        self.own_work()
        task = self.finished()
        proposal = task["proposals"][0]
        self.adopt_edit(task, proposal)
        entry = self.ledger()["changes"][0]
        self.assertEqual((entry["entry"], entry["kind"], entry["status"], entry["task_id"], entry["id"]), ("adoption", "edit_this", "adopted", task["id"], proposal["id"]))
        self.assertEqual((entry["before"], entry["after"], entry["edited_by_author"], entry["undone_at"]), (proposal["before"], proposal["after"], False, None))
        self.assertIsNotNone(entry["adopted_at"])
        undone = self.action(task, proposal, "undo").json()["data"]
        self.assertEqual(undone["status"], "proposed")
        self.assertIsNotNone(undone["undone_at"])
        again = self.ledger()["changes"]
        self.assertEqual([(item["id"], item["status"]) for item in again], [(proposal["id"], "undone")])
        self.assertEqual((again[0]["undone_at"], again[0]["adopted_at"]), (undone["undone_at"], None))
        # Adopting again empties the mark: the entry is adopted once more, with the time of the new adoption.
        self.adopt_edit(task, proposal)
        last = self.ledger()["changes"]
        self.assertEqual([(item["id"], item["status"], item["undone_at"]) for item in last], [(proposal["id"], "adopted", None)])
        self.assertEqual(self.rows("SELECT undone_at,undone_after FROM assistant_proposals WHERE id=?", proposal["id"]), [{"undone_at": None, "undone_after": None}])

    def test_the_authors_own_wording_is_what_the_entry_shows_even_after_the_undo(self):
        task = self.finished()
        proposal = task["proposals"][0]
        edited = "苏岑摸了摸空着的内袋，罗盘还锁在温岚的抽屉里。"
        self.adopt_edit(task, proposal, edited)
        entry = self.ledger()["changes"][0]
        self.assertEqual((entry["after"], entry["edited_by_author"]), (edited, True))
        self.action(task, proposal, "undo")
        entry = self.ledger()["changes"][0]
        self.assertEqual((entry["status"], entry["after"], entry["edited_by_author"]), ("undone", edited, True))

    def test_an_adopted_setup_is_listed_with_its_chapter(self):
        setup = call("propose_edit", kind="add_setup", chapter_number=9, after="她把罗盘交回苏岑。", rationale="补上交接。")
        task = self.finished(setup)
        proposal = next(item for item in task["proposals"] if item["kind"] == "add_setup")
        self.assertEqual(self.action(task, proposal, "adopt", {"after": "她把罗盘悄悄交回了苏岑。"}).status_code, 200)
        entry = self.ledger()["changes"][0]
        self.assertEqual((entry["kind"], entry["chapter_number"], entry["after"], entry["edited_by_author"]), ("add_setup", 9, "她把罗盘悄悄交回了苏岑。", True))
        self.action(task, proposal, "undo")
        entry = self.ledger()["changes"][0]
        self.assertEqual((entry["status"], entry["after"]), ("undone", "她把罗盘悄悄交回了苏岑。"))

    def test_a_proposal_that_was_never_adopted_is_not_listed_and_a_dismissed_one_after_an_undo_stays(self):
        task = self.finished()
        proposal = task["proposals"][0]
        self.assertEqual(self.ledger()["changes"], [])
        self.adopt_edit(task, proposal)
        self.action(task, proposal, "undo")
        self.assertEqual(self.action(task, proposal, "dismiss").status_code, 200)
        self.assertEqual([item["status"] for item in self.ledger()["changes"]], ["undone"])

    def test_an_older_database_gets_the_new_columns_when_it_starts(self):
        with self.db.connection() as c:
            c.execute("ALTER TABLE assistant_proposals DROP COLUMN undone_at")
            c.execute("ALTER TABLE assistant_proposals DROP COLUMN undone_after")
        AssistantStore(self.db).initialize()
        with self.db.connection() as c:
            columns = {row[1] for row in c.execute("PRAGMA table_info(assistant_proposals)")}
        self.assertLessEqual({"undone_at", "undone_after"}, columns)

    # -- pages -----------------------------------------------------------------------------------------------------
    def seed(self, task, stamps_changes, adoptions):
        """Changes (by their time) and the first proposals adopted (by their time) with the times given, so that ties are tested too."""
        with self.db.connection() as c:
            for index, stamp in enumerate(stamps_changes):
                c.execute("INSERT INTO assistant_changes(id,task_id,project_id,ordinal,kind,target_id,before_json,after_json,display_json,evidence_json,status,"
                          "edited_by_author,created_at,decided_at,applied_at,undone_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                          (f"achange-seed-{index}", task["id"], self.project_id, index + 1, "resolve_thread", f"thread-{index}", "{}", "{}",
                           json.dumps({"title": f"伏笔{index}", "before": "已埋下", "after": "已回收"}, ensure_ascii=False), "[]", "applied", 0,
                           stamp, stamp, stamp, None))
            for proposal, stamp in zip([item for item in task["proposals"] if item["kind"] != "intentional"], adoptions):
                c.execute("UPDATE assistant_proposals SET status='adopted',decided_at=? WHERE id=?", (stamp, proposal["id"]))

    def test_pages_follow_the_position_of_the_last_entry_and_lose_none_through_ties(self):
        task = self.finished(call("propose_edit", kind="add_setup", chapter_number=9, after="她把罗盘交回苏岑。", rationale="补上交接。"))
        t = [f"2026-10-0{n}T08:00:00.000000+00:00" for n in range(1, 6)]
        # three changes and two adoptions; the third change and the first adoption share their instant
        self.seed(task, [t[0], t[2], t[2]], [t[2], t[4]])
        everything = self.ledger(limit=50)
        self.assertIsNone(everything["next"])
        self.assertEqual(len(everything["changes"]), 5)
        ids = [(item["entry"], item["id"]) for item in everything["changes"]]
        walked, before = [], None
        for _ in range(10):
            page = self.ledger(limit=2, **({"before": before} if before else {}))
            walked += [(item["entry"], item["id"]) for item in page["changes"]]
            before = page["next"]
            if before is None:
                break
        self.assertEqual(walked, ids)
        self.assertEqual(len(set(walked)), 5)

    def test_an_undo_between_pages_repeats_nothing(self):
        task = self.finished(call("propose_edit", kind="add_setup", chapter_number=9, after="她把罗盘交回苏岑。", rationale="补上交接。"))
        t = [f"2026-10-0{n}T08:00:00.000000+00:00" for n in range(1, 7)]
        self.seed(task, [t[0], t[1], t[2], t[3]], [t[4], t[5]])
        first = self.ledger(limit=2)
        shown = [(item["entry"], item["id"]) for item in first["changes"]]
        self.assertEqual(len(shown), 2)
        self.assertIsNotNone(first["next"])
        # the entry just below the page is undone now: it moves to the top
        third = self.ledger(limit=3)["changes"][2]
        self.assertEqual(third["entry"], "change")
        with self.db.connection() as c:
            c.execute("UPDATE assistant_changes SET status='undone',undone_at=? WHERE id=?", ("2026-10-09T08:00:00.000000+00:00", third["id"]))
        rest = self.ledger(limit=50, before=first["next"])["changes"]
        later = [(item["entry"], item["id"]) for item in rest]
        self.assertFalse(set(later) & set(shown))
        self.assertEqual(len(later), 3)  # the undone one went to the top, above the cursor; the three older ones follow

    def test_a_bad_position_is_refused(self):
        response = self.client.get(f"/api/projects/{self.project_id}/assistant/changes?before=not-a-position")
        self.assertEqual((response.status_code, response.json()["error"]["code"]), (400, "invalid_request"))


class TaskChainTests(AssistantCase):
    def test_a_task_comes_with_the_questions_it_follows_and_those_that_follow_it(self):
        self.start()
        self.register()
        first = self.run_ask(read(9), cite(9))
        second = self.run_ask(read(9), cite(9), follow_up_of=first["id"])
        third = self.run_ask(read(9), cite(9), follow_up_of=second["id"])
        url = f"/api/projects/{self.project_id}/assistant/tasks/"
        plain = self.client.get(url + second["id"]).json()["data"]
        self.assertNotIn("chain", plain)
        chained = self.client.get(url + second["id"] + "?chain=1").json()["data"]
        self.assertEqual((chained["id"], [item["id"] for item in chained["chain"]]), (second["id"], [first["id"], third["id"]]))
        head = self.client.get(url + first["id"] + "?chain=1").json()["data"]
        self.assertEqual([item["id"] for item in head["chain"]], [second["id"], third["id"]])
        alone = self.run_ask(read(9), cite(9))
        self.assertEqual(self.client.get(url + alone["id"] + "?chain=1").json()["data"]["chain"], [])

    def test_a_task_the_author_cleared_is_not_found_and_does_not_come_in_a_chain(self):
        self.start()
        self.register()
        first = self.run_ask(read(9), cite(9))
        second = self.run_ask(read(9), cite(9), follow_up_of=first["id"])
        url = f"/api/projects/{self.project_id}/assistant/tasks/"
        with self.db.connection() as c:
            c.execute("UPDATE assistant_tasks SET hidden_at='2026-10-01T00:00:00+00:00' WHERE id=?", (first["id"],))
        self.assertEqual(self.client.get(url + first["id"] + "?chain=1").status_code, 404)
        self.assertEqual(self.client.get(url + second["id"] + "?chain=1").json()["data"]["chain"], [])

    def test_a_task_older_than_the_list_is_still_there(self):
        self.start()
        self.register()
        old = self.run_ask(read(9), cite(9))
        listed = self.client.get(f"/api/projects/{self.project_id}/assistant/tasks?limit=1").json()["data"]["tasks"]
        self.assertEqual(len(listed), 1)
        self.run_ask(read(9), cite(9))
        listed = self.client.get(f"/api/projects/{self.project_id}/assistant/tasks?limit=1").json()["data"]["tasks"]
        self.assertNotEqual(listed[0]["id"], old["id"])
        self.assertEqual(self.client.get(f"/api/projects/{self.project_id}/assistant/tasks/{old['id']}?chain=1").status_code, 200)


class ErrorWordsTests(unittest.TestCase):
    """Every error code the assistant's routes can return has words on the page. A code added to the backend without them fails here."""

    FILES = ("frontend/app/client/project/assistant-parts.tsx", "frontend/app/client/project/assistant-change.tsx", "frontend/app/client/project/assistant-fix.tsx")

    @staticmethod
    def codes() -> set[str]:
        found: set[str] = set()
        for path in sorted((ROOT / "backend" / "app").glob("assistant*.py")):
            text = path.read_text(encoding="utf-8")
            found |= set(re.findall(r'DomainError\(\s*"([a-z_0-9]+)"', text))
            found |= set(re.findall(r'HTTPException\(\s*\d+,\s*"([a-z_0-9]+)"', text))
        return found

    @staticmethod
    def worded() -> set[str]:
        words: set[str] = set()
        api = (ROOT / "frontend/app/api.ts").read_text(encoding="utf-8")
        words |= {code for code, text in re.findall(r'^\s+([a-z_0-9]+):\s*"([^"]+)"', api, re.M) if re.search(r"[一-鿿]", text)}
        for name in ErrorWordsTests.FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            # A `case "code":` of a switch answers with words when what follows it, up to the next case, has some (a case that falls
            # through to the next one shares its words), or names a constant that holds them.
            pieces = re.split(r'(?m)^\s*case "([a-z_0-9]+)":', text)
            waiting: list[str] = []
            for code, body in zip(pieces[1::2], pieces[2::2]):
                waiting.append(code)
                body = body.split("default:")[0]
                if not body.strip():
                    continue
                if re.search(r"[一-鿿]|\$\{[A-Z][A-Z_]{3,}\}", body):
                    words |= set(waiting)
                waiting = []
        return words

    def test_every_code_has_words(self):
        missing = sorted(self.codes() - self.worded())
        self.assertEqual(missing, [], f"no words for these error codes on the page: {missing}")

    def test_the_words_have_no_english_code_in_them(self):
        for name in self.FILES:
            text = (ROOT / name).read_text(encoding="utf-8")
            for words in re.findall(r'case "[a-z_0-9]+":\s*return\s*(?:\{\s*text:\s*)?[`"]([^`"]*)', text):
                self.assertIsNone(re.search(r"\b[a-z]+_[a-z_]+\b", words), words)


if __name__ == "__main__":
    unittest.main()
