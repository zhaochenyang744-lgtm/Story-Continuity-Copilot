"""The author's decisions (v2.2): what the author said should hold from now on, kept so that checks, answers and long tasks
follow it (Desktop/v2.2任务/06-记忆设计.md).

A decision is a record of its own beside facts and threads: what was decided, in one sentence; whom and which chapters it
covers; where it came from, in the author's own words. It is written only by a card the author confirms (`add_decision`,
an action of `assistant_actions`, so the card, its confirm, its undo and the ledger are the changes' own): the program puts
the item on a task's card when the author's words say a decision (the recognition call, a check decision's note, an answer
to a long task's question); the model never proposes one. On the materials page the author edits or deletes a decision
directly, as a fact.

Which decisions a task is given is the program's choice, never the model's: those whose names stand in the task's words or
whose chapters it covers, at most `RELEVANT_MAX`, the newest first. With none of them, nothing changes.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from typing import Any, Callable

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field

from .assistant_store import utcnow
from .database import DomainError

SCHEMA = """
CREATE TABLE IF NOT EXISTS v2_author_decisions(
  id TEXT PRIMARY KEY, project_id TEXT NOT NULL REFERENCES v2_projects(id),
  kind TEXT NOT NULL, statement TEXT NOT NULL, subjects_json TEXT NOT NULL, chapters_json TEXT,
  foreshadow_id TEXT, prefer_chapter INTEGER,
  quote TEXT NOT NULL, source TEXT NOT NULL, source_ref TEXT, basis_chapter INTEGER,
  replaces_id TEXT, status TEXT NOT NULL, revision INTEGER NOT NULL,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL, archived_at TEXT);
CREATE INDEX IF NOT EXISTS v2_author_decisions_by_project ON v2_author_decisions(project_id,archived_at,status);
"""

KINDS = {"intentional": "有意为之", "prefer": "以哪处为准", "no_reminder": "不用提醒", "keep_open": "先别收", "style": "写作偏好"}
SOURCES = {"box": "助手输入框", "check_note": "章节检查", "long_choice": "长任务提问", "undo": "撤销时记下"}
ACTIVE, SUPERSEDED, STALE = "active", "superseded", "stale"
DECISION_MAX = 200  # per work (v2.2 plan 6.4)
RELEVANT_MAX = 5  # given to one task
STATEMENT_MAX = 80
SUBJECTS_MAX = 6
QUOTE_MAX = 200
# What an item compares to tell whether the decision still holds what it expects.
FIELDS = ("kind", "statement", "subjects", "chapters", "foreshadow_id", "prefer_chapter", "status")


def _values(row: Any) -> dict[str, Any]:
    return {"kind": row["kind"], "statement": row["statement"], "subjects": json.loads(row["subjects_json"]),
            "chapters": json.loads(row["chapters_json"]) if row["chapters_json"] else None, "foreshadow_id": row["foreshadow_id"],
            "prefer_chapter": row["prefer_chapter"], "status": row["status"]}


def read(c: sqlite3.Connection, db: Any, project_id: str, target_id: str) -> dict[str, Any] | None:
    """A decision as it stands; None before its card is confirmed and after an undo or a delete."""
    row = c.execute("SELECT * FROM v2_author_decisions WHERE id=? AND project_id=? AND archived_at IS NULL", (target_id, project_id)).fetchone()
    return {**_values(row), "value": row["statement"]} if row else None


def _active_count(c: sqlite3.Connection, project_id: str) -> int:
    return c.execute("SELECT COUNT(*) FROM v2_author_decisions WHERE project_id=? AND archived_at IS NULL", (project_id,)).fetchone()[0]


def write(c: sqlite3.Connection, db: Any, project_id: str, target_id: str, values: dict[str, Any] | None, user_id: str, stamp: str) -> None:
    """Write the decision a confirmed item holds (the one it replaces is marked superseded); with None, take it away again (an
    undo: the one it replaced is active again)."""
    row = c.execute("SELECT * FROM v2_author_decisions WHERE id=? AND project_id=?", (target_id, project_id)).fetchone()
    if values is None:
        if row is None or row["archived_at"]:
            return
        c.execute("UPDATE v2_author_decisions SET archived_at=?,updated_at=?,revision=revision+1 WHERE id=?", (stamp, stamp, target_id))
        if row["replaces_id"]:
            c.execute("UPDATE v2_author_decisions SET status=?,updated_at=?,revision=revision+1 WHERE id=? AND project_id=? AND status=?",
                      (ACTIVE, stamp, row["replaces_id"], project_id, SUPERSEDED))
        return
    if (row is None or row["archived_at"]) and _active_count(c, project_id) >= DECISION_MAX:
        raise DomainError("decision_limit_reached", 409)
    statement = str(values.get("value") or values["statement"])
    fields = (values["kind"], statement, json.dumps(values.get("subjects") or [], ensure_ascii=False),
              json.dumps(values["chapters"]) if values.get("chapters") else None, values.get("foreshadow_id"), values.get("prefer_chapter"))
    if row is None:
        c.execute("INSERT INTO v2_author_decisions(id,project_id,kind,statement,subjects_json,chapters_json,foreshadow_id,prefer_chapter,quote,source,"
                  "source_ref,basis_chapter,replaces_id,status,revision,created_at,updated_at,archived_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,NULL)",
                  (target_id, project_id, *fields, values.get("quote") or "", values.get("source") or "box", values.get("source_ref"),
                   values.get("basis_chapter"), values.get("replaces_id"), ACTIVE, 1, stamp, stamp))
    else:  # a redo after an undo
        c.execute("UPDATE v2_author_decisions SET kind=?,statement=?,subjects_json=?,chapters_json=?,foreshadow_id=?,prefer_chapter=?,status=?,"
                  "archived_at=NULL,updated_at=?,revision=revision+1 WHERE id=?", (*fields, ACTIVE, stamp, target_id))
    if values.get("replaces_id"):
        c.execute("UPDATE v2_author_decisions SET status=?,updated_at=?,revision=revision+1 WHERE id=? AND project_id=? AND archived_at IS NULL",
                  (SUPERSEDED, stamp, values["replaces_id"], project_id))


def clash(c: sqlite3.Connection, db: Any, project_id: str, target_id: str, values: dict[str, Any]) -> bool:
    """Whether the decision can no longer be written: the work holds as many decisions as it may."""
    row = c.execute("SELECT archived_at FROM v2_author_decisions WHERE id=? AND project_id=?", (target_id, project_id)).fetchone()
    return (row is None or row["archived_at"] is not None) and _active_count(c, project_id) >= DECISION_MAX


def scope_label(values: dict[str, Any], chapter_of: Callable[[str | None], int | None] = lambda _: None) -> str:
    """Whom and where a decision covers, in the author's terms: "管：宓蘅隼；第 3–9 章"."""
    parts = []
    if values.get("subjects"):
        parts.append("、".join(values["subjects"]))
    chapters = values.get("chapters")
    parts.append(f"第 {chapters[0]}–{chapters[1]} 章" if chapters and chapters[0] != chapters[1] else f"第 {chapters[0]} 章" if chapters else "全书")
    if values.get("kind") == "prefer" and values.get("prefer_chapter"):
        parts.append(f"以第 {values['prefer_chapter']} 章为准")
    return "管：" + "；".join(parts)


def card_item(c: sqlite3.Connection, task_id: str, project_id: str, record: dict[str, Any], replaces: Any | None = None) -> str:
    """Put a decision on a task's card, waiting for the author: `record` holds kind, statement, subjects, chapters,
    foreshadow_id, prefer_chapter, quote, source, source_ref and basis_chapter. Returns the item's id."""
    ordinal = c.execute("SELECT COALESCE(MAX(ordinal),0)+1 FROM assistant_changes WHERE task_id=?", (task_id,)).fetchone()[0]
    target = f"decision-{uuid.uuid4()}"
    after = {**{key: record.get(key) for key in ("kind", "statement", "subjects", "chapters", "foreshadow_id", "prefer_chapter",
                                                 "quote", "source", "source_ref", "basis_chapter")},
             "status": ACTIVE, "value": record["statement"], "replaces_id": replaces["id"] if replaces is not None else None}
    display = {"title": f"记下决定·{KINDS[record['kind']]}", "before": "资料里没有",
               "after": f"{record['statement']}（{scope_label(after)}）", "quote": record.get("quote"),
               **({"replaces": replaces["statement"]} if replaces is not None else {})}
    item_id = f"achange-{uuid.uuid4()}"
    c.execute("INSERT INTO assistant_changes(id,task_id,project_id,ordinal,kind,target_id,before_json,after_json,display_json,evidence_json,status,created_at) "
              "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (item_id, task_id, project_id, ordinal, "add_decision", target, "null",
                                                 json.dumps(after, ensure_ascii=False), json.dumps(display, ensure_ascii=False), "[]", "proposed", utcnow()))
    return item_id


def view(row: Any) -> dict[str, Any]:
    values = _values(row)
    return {"id": row["id"], **values, "kind_label": KINDS.get(row["kind"], row["kind"]), "scope": scope_label(values),
            "quote": row["quote"], "source": row["source"], "source_label": SOURCES.get(row["source"], row["source"]),
            "source_ref": row["source_ref"], "basis_chapter": row["basis_chapter"], "replaces_id": row["replaces_id"],
            "revision": row["revision"], "created_at": row["created_at"], "updated_at": row["updated_at"]}


def listing(c: sqlite3.Connection, project_id: str) -> list[dict[str, Any]]:
    """The work's decisions: those that may be out of date first, then the active, then the superseded; newest first."""
    order = {STALE: 0, ACTIVE: 1, SUPERSEDED: 2}
    rows = c.execute("SELECT * FROM v2_author_decisions WHERE project_id=? AND archived_at IS NULL ORDER BY created_at DESC,id", (project_id,)).fetchall()
    return [view(row) for row in sorted(rows, key=lambda row: order.get(row["status"], 3))]


ALIAS_PREDICATES = ("别名", "外号", "又名", "又称", "绰号", "小名", "代号", "称号")
ALIAS_SPLIT = re.compile(r"[、，,/／;；\s]+")
# What the materials write around another name ("行商别名蘅斛", "翙扣。"): the words before the predicate, the end mark.
ALIAS_LEAD = re.compile(rf"^.*?(?:{'|'.join(ALIAS_PREDICATES)})(?:是|为|叫|作|：|:)?")
ALIAS_END = "。.．！!？?”」』\"'）)"


def alias_map(c: sqlite3.Connection, project_id: str) -> dict[str, str]:
    """The work's other names for its people and things, each to the name it stands for: the character records' aliases and
    the facts that give one ("孟苒箴 / 别名 / 蓼仔"). A decision is about the name; the author may say the other."""
    found: dict[str, str] = {}
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_character_aliases'").fetchone():
        for row in c.execute("SELECT a.alias,ch.name FROM v2_character_aliases a JOIN v2_characters ch ON ch.id=a.character_id "
                             "WHERE a.project_id=? AND a.status='active' AND a.archived_at IS NULL", (project_id,)):
            found.setdefault("".join(row[0].split()), "".join(row[1].split()))
    marks = ",".join("?" for _ in ALIAS_PREDICATES)
    for row in c.execute(f"SELECT DISTINCT subject,value FROM v2_memory_records WHERE project_id=? AND predicate IN ({marks})", (project_id, *ALIAS_PREDICATES)):
        for alias in ALIAS_SPLIT.split(str(row[1]).strip("「」“”\"'")):
            alias = ALIAS_LEAD.sub("", alias.strip("「」“”\"'")).strip("「」“”\"'" + ALIAS_END)
            if len(alias) >= 2 and alias != row[0]:
                found.setdefault(alias, "".join(row[0].split()))
    return found


NEAR_CHARS = 300  # how close in the text another word for a thing must stand to its name


def work_text(c: sqlite3.Connection, project_id: str) -> str:
    return "\n".join(row[0] or "" for row in c.execute(
        "SELECT s.body FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE ch.project_id=? ORDER BY ch.chapter_number,s.id",
        (project_id,)))


def _near(text: str, first: str, second: str) -> int:
    """How many times `first` stands within NEAR_CHARS of `second` in the text."""
    seconds = [i for i in range(len(text)) if text.startswith(second, i)]
    count = 0
    start = text.find(first)
    while start != -1:
        count += any(abs(start - j) <= NEAR_CHARS for j in seconds)
        start = text.find(first, start + 1)
    return count


def thing_for(text: str, word: str, names: Any) -> str | None:
    """The thing of the work another word stands for: a name that ends in the same character (礼盏 for 空喉盏, 木牌 for 弯穗牌)
    and that the word stands near in the text. None when no name does, or two do as often."""
    word = "".join(word.split())
    if len(word) < 2 or word not in text:
        return None
    scored = sorted(((_near(text, word, name), name) for name in names
                     if len(name) >= 2 and name != word and name[-1] == word[-1] and word not in name and name not in word), reverse=True)
    if not scored or not scored[0][0] or (len(scored) > 1 and scored[1][0] == scored[0][0]):
        return None
    return scored[0][1]


def covers_chapter(item: dict[str, Any], chapter: int | None) -> bool:
    """Whether a decision holds for a chapter: one kept to some chapters ("第二至七章……") holds for those only; one for the whole
    work, or a chapter not known, always. A finding in chapter 9 is not passed over by a decision about chapters 2 to 7 (A4
    formal 1, its chapter-bound scope pairs)."""
    span = item.get("chapters")
    return not span or chapter is None or span[0] <= chapter <= span[1]


ABOUT_DECISIONS = ("决定", "定过", "记下", "先别收", "不用提醒")
THREAD_PAIRS_MIN = 2  # a thread kept open is named by two character pairs of its title ("白色渡船这条" for 白色渡船与失去的署名)


def _pairs(text: str) -> set[str]:
    kept = "".join(ch for ch in text if ch.isalnum())
    return {kept[i:i + 2] for i in range(len(kept) - 1)}


def relevant(c: sqlite3.Connection, project_id: str, text: str, chapters: tuple[int, int] | None = None,
             authors_words: bool = False) -> list[dict[str, Any]]:
    """The decisions a task's words or chapters touch: a name of theirs in the words (a thread kept open also by part of its
    title), or their chapters overlapping the task's; writing preferences always; and, when the words are the author's own
    and ask about the decisions themselves ("我之前决定哪些伏笔先别收"), every decision. Active or possibly out of date, the
    newest first, at most RELEVANT_MAX."""
    said = "".join(str(text or "").split())
    every = authors_words and any(word in said for word in ABOUT_DECISIONS)
    text: str | None = None
    others: dict[str, list[str]] = {}
    for alias, name in alias_map(c, project_id).items():
        others.setdefault(name, []).append(alias)
    picked = []
    for row in c.execute("SELECT * FROM v2_author_decisions WHERE project_id=? AND archived_at IS NULL AND status IN (?,?) ORDER BY created_at DESC,id",
                         (project_id, ACTIVE, STALE)):
        values = _values(row)
        names = ["".join(s.split()) for s in values["subjects"]]
        names += [alias for name in names for alias in others.get(name, [])]  # the author may say a decision's name by another
        named = any(len(name) >= 2 and name in said for name in names)
        if not named and row["kind"] != "keep_open":  # another word for the thing ("礼盏" for 空喉盏), said by the author
            text = text if text is not None else work_text(c, project_id)
            named = any(thing_for(text, said[i - size:i + 1], [name]) == name for name in names if len(name) >= 2
                        for i in range(len(said)) if said[i] == name[-1] for size in (1, 2, 3) if i - size >= 0)
        if not named and row["kind"] == "keep_open":
            named = any(len(_pairs(name) & _pairs(said)) >= THREAD_PAIRS_MIN for name in names)
        covered = bool(chapters and values["chapters"] and values["chapters"][0] <= chapters[1] and chapters[0] <= values["chapters"][1])
        if every or named or covered or row["kind"] == "style":
            picked.append(view(row))
        if len(picked) >= RELEVANT_MAX:
            break
    return picked


def kept_open(c: sqlite3.Connection, project_id: str) -> set[str]:
    """The threads the author said to keep open (a `keep_open` decision in force): nothing marks them resolved."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_author_decisions'").fetchone():
        return set()
    return {row[0] for row in c.execute("SELECT foreshadow_id FROM v2_author_decisions WHERE project_id=? AND archived_at IS NULL AND kind='keep_open' "
                                        "AND status IN (?,?) AND foreshadow_id IS NOT NULL", (project_id, ACTIVE, STALE))}


# What following a decision means, by its kind, said with it to the answering call (A4 formal 2: a decision given as "照着办"
# alone was passed over when the author asked whether to unify what they had said was meant, or to answer a thread kept open).
OBEY = {
    "intentional": "问到这件事时引用这条，说作者定过这是有意的；不要说它是错、不要建议统一成一处、不催作者选一边",
    "prefer": "问到这件事时按定下的那一章回答，引用这条；另一处只说和定下的不同，不要建议统一成另一处",
    "no_reminder": "这类不一致不要当成问题提出，也不建议改",
    "keep_open": "这条伏笔先别收：不要替作者给出答案或猜答案，不催作者交代，也不指在哪里收",
}
STALE_LINE = "作者定过的决定「{statement}」依据的章节后来改过，这条决定可能过时，请重新确认。"


def prompt_lines(items: list[dict[str, Any]], refs: list[str]) -> list[str]:
    """The decisions a task is given, for its first message: each with the number it is cited by and what following it
    means. Writing preferences are not about the work: they come as how to write the answer, with no number, never cited
    as what the answer rests on."""
    cited = [(item, ref) for item, ref in zip(items, refs) if item["kind"] != "style"]
    styles = [item for item in items if item["kind"] == "style"]
    lines = ["作者定过的决定（作者自己确认过，照着办，比第 11 条的出主意优先；回答里用到时引用它的编号，说明这是作者定过的）："] + [
        f"[{ref}] {item['kind_label']}：{item['statement']}（{item['scope']}）" + (f"——{OBEY[item['kind']]}" if item["kind"] in OBEY else "")
        + ("（这条依据的章节后来改过，可能过时：回答里要告诉作者，请作者重新确认）" if item["status"] == STALE else "")
        for item, ref in cited] if cited else []
    if styles:
        lines.append("作者对回答的写法偏好（照着写回答就好；这不是作品内容，不要引用，也不要在回答里复述）：" + "；".join(item["statement"] for item in styles))
    return lines


def mark_stale(c: sqlite3.Connection, project_id: str, chapter_numbers: set[int], stamp: str) -> int:
    """A revision of the chapters a decision stands on leaves it possibly out of date (it is not deleted). Returns how many."""
    marked = 0
    for row in c.execute("SELECT id,basis_chapter FROM v2_author_decisions WHERE project_id=? AND archived_at IS NULL AND status=?", (project_id, ACTIVE)).fetchall():
        if row["basis_chapter"] in chapter_numbers:
            c.execute("UPDATE v2_author_decisions SET status=?,updated_at=?,revision=revision+1 WHERE id=?", (STALE, stamp, row["id"]))
            marked += 1
    return marked


SAMPLE = (  # the sample work's two (v2.2 plan 6.6): what the column looks like before an author has said any
    {"kind": "keep_open", "thread": "廊桥钥匙的指向", "statement": "「廊桥钥匙的指向」先别收，后面还要写", "quote": "廊桥钥匙那条先别收，后面还要写"},
    {"kind": "no_reminder", "subjects": ["旧潮位牌"], "statement": "旧潮位牌前后几种叫法（旧牌、潮位牌）不用提醒", "quote": "旧潮位牌叫法不统一不用提醒"},
)


def seed_sample(c: sqlite3.Connection, project_id: str, stamp: str) -> None:
    """Put the sample work's decisions in, where the table is there (a migration may run before the assistant's tables)."""
    if not c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_author_decisions'").fetchone():
        return
    for item in SAMPLE:
        thread = None
        if item.get("thread"):
            thread = c.execute("SELECT id FROM v2_foreshadows WHERE project_id=? AND title=? AND archived_at IS NULL", (project_id, item["thread"])).fetchone()
        if item.get("thread") and thread is None:
            continue
        write(c, None, project_id, f"decision-{uuid.uuid4()}", {
            "kind": item["kind"], "statement": item["statement"], "subjects": [item["thread"]] if thread else item["subjects"], "chapters": None,
            "foreshadow_id": thread["id"] if thread else None, "prefer_chapter": None, "quote": item["quote"], "source": "box"}, "", stamp)


def purge(c: sqlite3.Connection, project_id: str) -> None:
    if c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='v2_author_decisions'").fetchone():
        c.execute("DELETE FROM v2_author_decisions WHERE project_id=?", (project_id,))


# --- the materials page ----------------------------------------------------------------------------------------------
class DecisionEdit(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=1)
    statement: str | None = Field(default=None, min_length=1, max_length=STATEMENT_MAX)
    subjects: list[str] | None = Field(default=None, max_length=SUBJECTS_MAX)
    chapters: list[int] | None = Field(default=None, min_length=2, max_length=2)
    whole_work: bool = False  # chapters back to null: the decision covers the whole work
    still_holds: bool = False  # the author has looked at a possibly out-of-date decision and it holds


class DecisionDelete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    base_revision: int = Field(ge=1)


def _owned(c: sqlite3.Connection, project_id: str, decision_id: str, base_revision: int) -> Any:
    row = c.execute("SELECT * FROM v2_author_decisions WHERE id=? AND project_id=? AND archived_at IS NULL", (decision_id, project_id)).fetchone()
    if row is None:
        raise DomainError("resource_not_found", 404)
    if row["revision"] != base_revision:
        raise DomainError("decision_revision_conflict", 409)
    return row


def edit(c: sqlite3.Connection, project_id: str, decision_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    row = _owned(c, project_id, decision_id, payload["base_revision"])
    statement = " ".join(payload["statement"].split()) if payload.get("statement") else row["statement"]
    subjects = [" ".join(s.split()) for s in payload["subjects"] if s.strip()] if payload.get("subjects") is not None else json.loads(row["subjects_json"])
    chapters = None if payload.get("whole_work") else payload.get("chapters") or (json.loads(row["chapters_json"]) if row["chapters_json"] else None)
    if chapters and not 1 <= chapters[0] <= chapters[1]:
        raise DomainError("decision_chapters_invalid", 422)
    status = ACTIVE if payload.get("still_holds") and row["status"] == STALE else row["status"]
    stamp = utcnow()
    c.execute("UPDATE v2_author_decisions SET statement=?,subjects_json=?,chapters_json=?,status=?,revision=revision+1,updated_at=? WHERE id=?",
              (statement, json.dumps(subjects, ensure_ascii=False), json.dumps(chapters) if chapters else None, status, stamp, decision_id))
    return {"decision": view(c.execute("SELECT * FROM v2_author_decisions WHERE id=?", (decision_id,)).fetchone())}


def delete(c: sqlite3.Connection, project_id: str, decision_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    _owned(c, project_id, decision_id, payload["base_revision"])
    stamp = utcnow()
    c.execute("UPDATE v2_author_decisions SET archived_at=?,updated_at=?,revision=revision+1 WHERE id=?", (stamp, stamp, decision_id))
    return {"deleted": decision_id}


def register_routes(app: Any, db: Any, user: Callable, csrf: Callable, key: Callable, ok: Callable, operation: Callable) -> None:
    base = "/api/projects/{project_id}/decisions"

    def write(name: str, request: Request, project_id: str, scope: str, idempotency_key: str | None, payload: dict[str, Any],
              factory: Callable[[sqlite3.Connection], dict[str, Any]]):
        csrf(request)
        operation(request, f"decision_{name}_failed")
        actor = user(request)
        with db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            db._project(c, actor["id"], project_id, True)
            data, status = db._idem(c, actor["id"], f"decision_{name}:{scope}", key(idempotency_key), payload, lambda: factory(c))
        return ok(request, data, status)

    @app.get(base)
    def list_decisions(project_id: str, request: Request):
        actor = user(request)
        with db.connection() as c:
            db._project(c, actor["id"], project_id)
            return ok(request, {"decisions": listing(c, project_id), "limit": DECISION_MAX, "kinds": KINDS})

    @app.patch(base + "/{decision_id}")
    def edit_decision(project_id: str, decision_id: str, payload: DecisionEdit, request: Request,
                      idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        body = payload.model_dump()
        return write("edit", request, project_id, f"{project_id}:{decision_id}", idempotency_key, body, lambda c: edit(c, project_id, decision_id, body))

    @app.post(base + "/{decision_id}/delete")
    def delete_decision(project_id: str, decision_id: str, payload: DecisionDelete, request: Request,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        body = payload.model_dump()
        return write("delete", request, project_id, f"{project_id}:{decision_id}", idempotency_key, body, lambda c: delete(c, project_id, decision_id, body))
