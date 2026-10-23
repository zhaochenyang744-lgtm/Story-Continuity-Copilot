"""Changes the assistant proposes to the author's materials (v2.0): the change card, its ledger, confirm and undo.

A `change` task reads like a question and ends with `answer`; on the way the model calls `propose_change`, once per item of
the card. Each item is checked when it is proposed: its target is a record this task was shown (by its R number), its
evidence passages of the written chapters this task read. It is stored with the values the target has then and the values it
would get. Nothing is written to the materials until the author confirms the card: the program then writes every accepted
item in one transaction, or none of them when any target has changed since. The model takes no part after the card.

Undo puts back only the fields an item changed. When its target was changed again afterwards (by a later item, or by the
author), the author is told first; on their word the later items are undone newest first and the values are put back over
the author's edit. An undo is recorded too, and an undone item can be applied again under the same check as a confirm.

An action is one kind of change: how its proposal is checked, and which fields of its target it reads and writes. Batch one:
`resolve_thread` (a foreshadowing thread the text has resolved), `change_fact` (a fact the text has moved past) and
`add_fact` (a fact the text states that the materials lack).

A fact has no id that lasts across versions of the materials: every version copies each fact under its id with "-v<version>"
added. Its lineage, the id with those endings taken off, is what an item points at (the source-review code relies on the
same endings). Writing a fact makes a new version, as every commit of the materials does; while a review of the facts is
open (a chapter revision, an import's first facts, the facts of new chapters) that review would no longer commit, so fact
items wait until it is done.
"""
from __future__ import annotations

import json
import re
import sqlite3
import uuid
from dataclasses import dataclass
from typing import Any, Callable

from fastapi import Header, Request
from pydantic import BaseModel, ConfigDict, Field

from . import assistant_requests
from . import long_term_workflow as workflow
from .assistant_store import utcnow
from .assistant_tools import FORESHADOW_STATUS, INTERNAL_ID, Outcome, ToolContext, ToolError, fact_items
from .database import DomainError
from .memory_contract import CONTROLLED_PREDICATES, normalize_memory_value, predicate_label
from .v2_database import MAX_RESOURCE_VERSION, new_id

CARD_MAX_ITEMS = 5
EVIDENCE_MAX = 2
THREADS_MAX = 30
LEDGER_LIMIT = 50
OPEN_THREAD = ("planned", "planted", "developing")
STATUSES = ("proposed", "applied", "rejected", "undone")
FACT_TYPES = ("static_canon", "dynamic_state", "event_timeline", "character_knowledge", "open_thread")
FACT_FIELDS = ("memory_type", "subject", "predicate", "value")
FACT_VALUE_MAX = 200
FACT_SUBJECT_MAX = 60
REQUEST_WORDS_MAX = 40
VERSION_ENDINGS = re.compile(r"(?:-v\d+)+$")
SUBJECT_PARTS = re.compile(r"[（）()、，,与和及/]+")
# Each second look costs a round, and a task that reaches the last round counts as a forced finish (A2 bar 0.2; the second
# pair stood at 0.194 under p42). Measured over every card of every A2 run so far, the looks below keep the cases they were
# made for and drop most of those that only cost a round.
SECOND_LOOK_KEPT = 0.7  # share of the old value's character pairs a new value keeps when it only says the old fact again
# (at 0.6: 70 of 273 changes asked for were held, 8 of 30 that should not have been made; at 0.7: 26 and 5)
SECOND_LOOK_SAME = 0.5  # share of an existing fact's character pairs a new fact repeats when it may say the same matter
# The same, for a fact filed under the very same subject: "双齿筹不会因换手便成为所有权证明" was added beside "双齿筹（用途）：
# 标示称量轮次，不是物件所有权凭证" in three passes of three (A2 third formal run, w02-no-action-02; 0.21 of its pairs). Over
# every A2 run so far this holds 11 more of 404 new facts asked for, and 4 of the 5 same-subject duplicates.
SECOND_LOOK_SAME_SUBJECT = 0.2
# A fact is about the story, not about a sentence of it: an author's request to shorten the last sentence of a chapter came
# back as a fact "第20章最后一句" holding the rewrite (A2 third formal run, w01-no-action-05, two passes of three). Over every
# A2 run so far no new fact asked for has such a subject.
PROSE_SUBJECT = re.compile(r"第\s*[0-9０-９零〇一二两三四五六七八九十百]+\s*[章回节]|最后一句|第一句|这句|那句|这一句|那一句|这段|那段|"
                           r"这一段|那一段|开头|结尾|正文|草稿|原句|句子|段落")
SECOND_LOOK_FACTS = 10


def new_change_id() -> str:
    return f"achange-{uuid.uuid4()}"


# --- the actions -----------------------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Action:
    kind: str
    target_kind: str | None  # the kind of registered source a target must be; None for an action that makes a new record
    fields: tuple[str, ...]  # the fields compared to tell whether the target still holds what an item expects
    # (ctx, args, target source or None) -> {"target_id", "before", "after", "display", "evidence"}; raises ToolError
    propose: Callable[[ToolContext, dict[str, Any], dict[str, Any] | None], dict[str, Any]]
    # The target's current values (the compared fields and what a write needs besides); None when it is not there.
    read: Callable[[sqlite3.Connection, Any, str, str], dict[str, Any] | None]
    # Write values, or remove the record with None: (c, db, project_id, target_id, values, user_id, stamp).
    write: Callable[[sqlite3.Connection, Any, str, str, dict[str, Any] | None, str, str], None]
    creates: bool = False  # an undo removes the record again
    editable: bool = False  # the author may reword the value on the card before confirming

    def same(self, values: dict[str, Any] | None, expected: dict[str, Any] | None) -> bool:
        if values is None or expected is None:
            return values is None and expected is None
        return all(values.get(field) == expected.get(field) for field in self.fields)


def evidence_of(ctx: ToolContext, refs: Any) -> list[dict[str, Any]]:
    """The passages a change stands on: one or two R numbers of written chapters' text that this task was shown."""
    if not isinstance(refs, list) or not 1 <= len(refs) <= EVIDENCE_MAX:
        raise ToolError("change_evidence_invalid")
    items = []
    for ref in refs:
        source = ctx.registry.rows.get(ref) if isinstance(ref, str) else None
        if not source or source["kind"] != "passage" or not source["chapter_number"] or source["chapter_number"] > ctx.max_chapter:
            raise ToolError("change_evidence_invalid")
        items.append({"ref": ref, "object_id": source["object_id"], "chapter_number": source["chapter_number"],
                      "chapter_title": source["chapter_title"], "start": source["start"], "end": source["end"], "text": source["text"]})
    return items


def _chapter_and_span(c: sqlite3.Connection, project_id: str, evidence: dict[str, Any]) -> tuple[str, str | None]:
    """The chapter a passage is in, and the stored span that holds its words. A passage read from a chapter carries the
    chapter's id; one from a check result carries its span's. A passage that runs over two spans is placed in the one that
    holds its opening words; when no span holds them (a chapter whose text was saved apart from its spans), in the
    chapter's first span, so the record still points at the right chapter."""
    chapter = c.execute("SELECT id FROM v2_chapters WHERE id=? AND project_id=?", (evidence["object_id"], project_id)).fetchone()
    if chapter is None:
        span = c.execute("SELECT id,chapter_id FROM v2_source_spans WHERE id=? AND project_id=?", (evidence["object_id"], project_id)).fetchone()
        if span is None:
            raise ToolError("change_evidence_invalid")
        return span["chapter_id"], span["id"]
    for words in (evidence["text"], evidence["text"].strip()[:20]):
        span = c.execute("SELECT id FROM v2_source_spans WHERE project_id=? AND chapter_id=? AND instr(body,?)>0 ORDER BY source_revision DESC,rowid LIMIT 1",
                         (project_id, chapter["id"], words)).fetchone()
        if span:
            return chapter["id"], span["id"]
    span = c.execute("SELECT id FROM v2_source_spans WHERE project_id=? AND chapter_id=? ORDER BY source_revision DESC,rowid LIMIT 1",
                     (project_id, chapter["id"])).fetchone()
    return chapter["id"], span["id"] if span else None


def _latest(evidence: list[dict[str, Any]]) -> dict[str, Any]:
    return max(evidence, key=lambda item: item["chapter_number"])


def _text(value: Any, limit: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value.strip()) > limit or INTERNAL_ID.search(value):
        raise ToolError("change_value_invalid")
    return " ".join(value.split())


# resolve_thread ---------------------------------------------------------------------------------------------------------
THREAD_FIELDS = ("status", "resolved_chapter_id", "resolved_source_span_id")


def _thread_label(status: str, chapter: int | None) -> str:
    return FORESHADOW_STATUS.get(status, status) + (f"（第 {chapter} 章）" if chapter else "")


def propose_resolve_thread(ctx: ToolContext, args: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    evidence = evidence_of(ctx, args.get("evidence"))
    with ctx.db.connection() as c:
        row = c.execute("SELECT * FROM v2_foreshadows WHERE id=? AND project_id=? AND archived_at IS NULL", (target["object_id"], ctx.project_id)).fetchone()
        if row is None:
            raise ToolError("change_target_invalid")
        if row["status"] not in OPEN_THREAD:
            raise ToolError("change_thread_not_open")
        planted = c.execute("SELECT chapter_number FROM v2_chapters WHERE id=?", (row["planted_chapter_id"],)).fetchone() if row["planted_chapter_id"] else None
        # The thread closes where the latest of its passages is; a passage before the planting cannot close it.
        latest = _latest(evidence)
        if planted and latest["chapter_number"] < planted["chapter_number"]:
            raise ToolError("change_evidence_before_planted")
        chapter_id, span_id = _chapter_and_span(c, ctx.project_id, latest)
        resolved = c.execute("SELECT chapter_number FROM v2_chapters WHERE id=?", (row["resolved_chapter_id"],)).fetchone() if row["resolved_chapter_id"] else None
    return {"target_id": row["id"], "before": {field: row[field] for field in THREAD_FIELDS}, "evidence": evidence,
            "after": {"status": "resolved", "resolved_chapter_id": chapter_id, "resolved_source_span_id": span_id},
            "display": {"title": row["title"], "before": _thread_label(row["status"], resolved["chapter_number"] if resolved else None),
                        "after": _thread_label("resolved", latest["chapter_number"])}}


def read_thread(c: sqlite3.Connection, db: Any, project_id: str, target_id: str) -> dict[str, Any] | None:
    row = c.execute("SELECT * FROM v2_foreshadows WHERE id=? AND project_id=? AND archived_at IS NULL", (target_id, project_id)).fetchone()
    return {field: row[field] for field in THREAD_FIELDS} if row else None


def write_thread(c: sqlite3.Connection, db: Any, project_id: str, target_id: str, values: dict[str, Any] | None, user_id: str, stamp: str) -> None:
    """Write a thread's status fields the way the materials page does: a new version of the record, recorded, and a new
    version of the work's foreshadowing."""
    row = c.execute("SELECT * FROM v2_foreshadows WHERE id=? AND project_id=? AND archived_at IS NULL", (target_id, project_id)).fetchone()
    project = c.execute("SELECT foreshadow_version FROM v2_projects WHERE id=?", (project_id,)).fetchone()
    if row is None or values is None:
        raise DomainError("change_target_missing", 409)
    if row["version"] >= MAX_RESOURCE_VERSION or int(project["foreshadow_version"] or 0) >= MAX_RESOURCE_VERSION:
        raise DomainError("foreshadow_version_limit", 409)
    c.execute("UPDATE v2_foreshadows SET status=?,resolved_chapter_id=?,resolved_source_span_id=?,version=version+1,updated_at=? WHERE id=?",
              (values["status"], values["resolved_chapter_id"], values["resolved_source_span_id"], stamp, target_id))
    db._record_foreshadow_version(c, c.execute("SELECT * FROM v2_foreshadows WHERE id=?", (target_id,)).fetchone(), "updated", user_id, stamp)
    c.execute("UPDATE v2_projects SET foreshadow_version=foreshadow_version+1,updated_at=? WHERE id=?", (stamp, project_id))


# facts ---------------------------------------------------------------------------------------------------------------------
def fact_lineage(record_id: str) -> str:
    """The id a fact keeps across versions of the materials: its record id without the "-v<version>" endings."""
    return VERSION_ENDINGS.sub("", record_id)


def fact_at(c: sqlite3.Connection, project_id: str, version: int, lineage: str) -> Any:
    rows = c.execute("SELECT * FROM v2_memory_records WHERE project_id=? AND version=? AND (id=? OR id LIKE ?)",
                     (project_id, version, lineage, lineage + "-v%")).fetchall()
    return next((row for row in rows if fact_lineage(row["id"]) == lineage), None)


def _confirmed(row: Any, version: int) -> bool:
    return bool(row) and row["review_status"] == "author_confirmed" and (row["valid_from"] is None or row["valid_from"] <= version) \
        and (row["valid_to"] is None or row["valid_to"] >= version)


def read_fact(c: sqlite3.Connection, db: Any, project_id: str, lineage: str) -> dict[str, Any] | None:
    """The fact as the materials hold it now: its four fields and its source span; None when it is not a confirmed fact of the
    current version."""
    version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (project_id,)).fetchone()[0]
    row = fact_at(c, project_id, version, lineage)
    return {**{field: row[field] for field in FACT_FIELDS}, "source_span_id": row["source_span_id"]} if _confirmed(row, version) else None


def memory_review_open(c: sqlite3.Connection, db: Any, project_id: str) -> str | None:
    """The review of the facts that is still open, if any: it commits against the version it was made from."""
    if workflow.pending_reviews(c, project_id):
        return "source_revision_review"
    origin = c.execute("SELECT data_origin FROM v2_projects WHERE id=?", (project_id,)).fetchone()["data_origin"]
    if db._memory_initialization_status(c, project_id, origin) in ("required", "in_review"):
        return "memory_initialization"
    if c.execute("SELECT 1 FROM v2_memory_delta_batches WHERE project_id=? AND status IN ('processing','in_review')", (project_id,)).fetchone():
        return "memory_delta"
    return None


def write_fact(c: sqlite3.Connection, db: Any, project_id: str, lineage: str, values: dict[str, Any] | None, user_id: str, stamp: str) -> None:
    """A new version of the materials with this one fact written (or taken out, with None), every other fact copied over the
    way every commit of the materials copies them."""
    review = memory_review_open(c, db, project_id)
    if review:
        raise DomainError("change_memory_review_pending", 409, False, {"review": review})
    base = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (project_id,)).fetchone()[0]
    target = base + 1
    c.execute("INSERT INTO v2_memory_versions VALUES(?,?,?,?,?)", (project_id, target, "current", base, stamp))
    c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) "
              "SELECT id||'-v'||?,project_id,?,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id "
              "FROM v2_memory_records WHERE project_id=? AND version=?", (target, target, project_id, base))
    row = fact_at(c, project_id, target, lineage)
    if values is None:
        if row:
            c.execute("DELETE FROM v2_memory_records WHERE id=?", (row["id"],))
    elif row:
        c.execute("UPDATE v2_memory_records SET memory_type=?,subject=?,predicate=?,value=?,source_span_id=?,review_status='author_confirmed',valid_to=NULL WHERE id=?",
                  (values["memory_type"], values["subject"], values["predicate"], values["value"], values["source_span_id"], row["id"]))
    else:
        c.execute("INSERT INTO v2_memory_records(id,project_id,version,memory_type,subject,predicate,value,source_span_id,review_status,valid_from,valid_to,source_claim_id) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", (f"{lineage}-v{target}", project_id, target, values["memory_type"], values["subject"], values["predicate"],
                                                     values["value"], values["source_span_id"], "author_confirmed", None, None, None))
    c.execute("UPDATE v2_memory_versions SET status='superseded' WHERE project_id=? AND version=?", (project_id, base))
    c.execute("UPDATE v2_projects SET current_memory_version=?,updated_at=? WHERE id=?", (target, stamp, project_id))


def _fact_title(values: dict[str, Any]) -> str:
    # A property in the author's own words ("旧誓附页认知") names itself; the fixed keys have their labels.
    predicate = str(values["predicate"] or "").strip()
    own = predicate if predicate and predicate not in CONTROLLED_PREDICATES and not predicate.isascii() else ""
    return f"{values['subject']}·{own or predicate_label(predicate)}"


VALUE_END = "。．.；;，,、"


def _fact_label(c: sqlite3.Connection, values: dict[str, Any]) -> str:
    """A fact's value with the chapter it stands in: "由温岚保管（第 10 章）", not "由温岚保管。（第 10 章）"; a value that names its
    chapter already ("第4章上午……") is not given it twice."""
    chapter = c.execute("SELECT ch.chapter_number FROM v2_source_spans s JOIN v2_chapters ch ON ch.id=s.chapter_id WHERE s.id=?",
                        (values["source_span_id"],)).fetchone() if values.get("source_span_id") else None
    value = values["value"].rstrip().rstrip(VALUE_END)
    if not chapter:
        return value
    named = {_number(token) for token in CHAPTER_NUMBER_IN.findall("".join(value.split()))}
    return value if chapter["chapter_number"] in named else f"{value}（第 {chapter['chapter_number']} 章）"


def propose_change_fact(ctx: ToolContext, args: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    evidence = evidence_of(ctx, args.get("evidence"))
    value = _text(args.get("value"), FACT_VALUE_MAX)
    lineage = fact_lineage(target["object_id"])
    with ctx.db.connection() as c:
        current = read_fact(c, ctx.db, ctx.project_id, lineage)
        if current is None:
            raise ToolError("change_target_invalid")
        if normalize_memory_value(value) == normalize_memory_value(current["value"]):
            raise ToolError("change_no_difference")
        _, span_id = _chapter_and_span(c, ctx.project_id, _latest(evidence))
        after = {**current, "value": value, "source_span_id": span_id or current["source_span_id"]}
        display = {"title": _fact_title(current), "before": _fact_label(c, current), "after": _fact_label(c, after)}
    return {"target_id": lineage, "before": current, "after": after, "evidence": evidence, "display": display}


def _names(subject: str) -> set[str]:
    """The names a subject is made of: "程以硕（程扣）与汤越晴" -> 程以硕, 程扣, 汤越晴."""
    return {"".join(part.split()) for part in SUBJECT_PARTS.split(subject) if len("".join(part.split())) >= 2}


def propose_add_fact(ctx: ToolContext, args: dict[str, Any], target: dict[str, Any] | None) -> dict[str, Any]:
    evidence = evidence_of(ctx, args.get("evidence"))
    memory_type, predicate = args.get("memory_type"), args.get("predicate")
    if memory_type not in FACT_TYPES or predicate not in CONTROLLED_PREDICATES:
        raise ToolError("change_fields_invalid")
    subject = _text(args.get("subject"), FACT_SUBJECT_MAX)
    value = _text(args.get("value"), FACT_VALUE_MAX)
    with ctx.db.connection() as c:
        version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (ctx.project_id,)).fetchone()[0]
        confirmed = ctx.db._confirmed_memory(c, ctx.project_id, version)
        # A fact about someone the task has not looked up may already say this: an author who writes a nickname ("池秒") is
        # looked up under the nickname, while the facts stand under the full name (A2 dev round 1, no-action-01 and -02).
        # Each name of the subject that has facts must have been looked up under that name, or have had every one of its facts
        # shown. One fact shown is not enough: the nickname's own fact ("池澍宁：同事称她池秒") stands under the full name and
        # comes up in a lookup of the nickname (A2 dev round 3, no-action-01).
        shown = {fact_lineage(row["object_id"]) for row in ctx.registry.rows.values() if row["kind"] == "fact"}
        looked_up = {"".join(str(json.loads(row["args_json"] or "{}").get("name", "")).split()) for row in c.execute(
            "SELECT args_json FROM assistant_steps WHERE task_id=? AND tool_name='lookup_facts' AND error_code IS NULL", (ctx.task["id"],))}
        # A name that holds an existing subject, or sits inside one, counts too: "槐誓庭盟议" was added while the rule stood
        # under "槐誓庭" (A2 spent-pair pass 3, w01-action-08). A lookup finds the subjects its name sits inside, so a lookup
        # of "槐誓庭" covers it and one of "槐誓庭盟议" does not.
        subjects: dict[str, set[str]] = {}
        for fact in confirmed:
            subjects.setdefault("".join(fact["subject"].split()), set()).add(fact_lineage(fact["id"]))
        for name in _names(subject):
            for held, about in subjects.items():
                if len(held) >= 2 and (held in name or name in held) and not about <= shown \
                        and not any(len(word) >= 2 and word in held for word in looked_up):
                    raise ToolError("change_check_existing")
        key = ctx.db._candidate_key(memory_type, subject, predicate)
        for fact in confirmed:
            if ctx.db._candidate_key(fact["memory_type"], fact["subject"], fact["predicate"]) == key \
                    and normalize_memory_value(fact["value"]) == normalize_memory_value(value):
                raise ToolError("change_fact_already_recorded")
        _, span_id = _chapter_and_span(c, ctx.project_id, _latest(evidence))
        after = {"memory_type": memory_type, "subject": subject, "predicate": predicate, "value": value, "source_span_id": span_id}
        display = {"title": _fact_title(after), "before": "资料里没有", "after": _fact_label(c, after)}
    return {"target_id": fact_lineage(new_id("mem")), "before": None, "after": after, "evidence": evidence, "display": display}


ACTIONS: dict[str, Action] = {action.kind: action for action in (
    Action("resolve_thread", "foreshadow", THREAD_FIELDS, propose_resolve_thread, read_thread, write_thread),
    Action("change_fact", "fact", FACT_FIELDS, propose_change_fact, read_fact, write_fact, editable=True),
    Action("add_fact", None, FACT_FIELDS, propose_add_fact, read_fact, write_fact, creates=True, editable=True),
)}


# --- the tools ---------------------------------------------------------------------------------------------------------
def run_list_threads(ctx: ToolContext, args: dict[str, Any]) -> Outcome:
    """Every foreshadowing record of the work (not archived), with its status and where it was planted and resolved."""
    with ctx.db.connection() as c:
        number = {row["id"]: row["chapter_number"] for row in c.execute("SELECT id,chapter_number FROM v2_chapters WHERE project_id=?", (ctx.project_id,))}
        rows = c.execute("SELECT * FROM v2_foreshadows WHERE project_id=? AND archived_at IS NULL ORDER BY created_at,id LIMIT ?",
                         (ctx.project_id, THREADS_MAX)).fetchall()
    items = []
    for row in rows:
        planted, resolved = number.get(row["planted_chapter_id"]), number.get(row["resolved_chapter_id"])
        where = (f"，第 {planted} 章埋下" if planted else "") + (f"，第 {resolved} 章回收" if resolved else "")
        text = f"伏笔：{row['title']}（{FORESHADOW_STATUS.get(row['status'], row['status'])}{where}）——{row['description']}"
        title = ctx.title(planted) if planted else None
        ref = ctx.registry.register("foreshadow", row["id"], planted, title, None, None, text)
        items.append({"ref": ref, "chapter": planted, "chapter_title": title, "text": text})
    return Outcome({"content_kind": "manuscript_text", "threads": items}, {}, len(items))


def _same_new_record(a: dict[str, Any], b: dict[str, Any]) -> bool:
    return all(normalize_memory_value(str(a[field])) == normalize_memory_value(str(b[field])) for field in FACT_FIELDS)


def _request_words(ctx: ToolContext, value: Any) -> str:
    """The words of the author's sentence that point at the record a change is about, copied as they stand. A change the
    author's sentence has no words for is one the author did not ask for (A2 dev round 2, no-action-05: asked to rewrite the
    draft's opening, the assistant marked an unrelated thread resolved)."""
    words = "".join(value.split()) if isinstance(value, str) else ""
    if not 2 <= len(words) <= REQUEST_WORDS_MAX or words not in _question(ctx):
        raise ToolError("change_not_requested")
    return words


def _question(ctx: ToolContext) -> str:
    return "".join(str(json.loads(ctx.task["input_json"]).get("question") or "").split())


def _spans(question: str, words: str) -> list[tuple[int, int]]:
    spans, start = [], question.find(words)
    while start >= 0:
        spans.append((start, start + len(words)))
        start = question.find(words, start + 1)
    return spans


def _shared(question: str, one: str, other: str) -> bool:
    """Whether two items' request words are the same piece of the author's sentence (they overlap wherever they stand)."""
    return any(a < d and c < b for a, b in _spans(question, one) for c, d in _spans(question, other))


def _pairs(text: str) -> set[str]:
    kept = "".join(ch for ch in text if ch.isalnum())
    return {kept[i:i + 2] for i in range(len(kept) - 1)}


def _related(held: str, name: str) -> bool:
    return len(held) >= 2 and (held in name or name in held)


# Numbers a value states must stand in its evidence (A2 second formal run, w01-no-action-03: "生日是八月十二号" added on a
# passage that names no date). Chapter mentions ("自第18章起") are where, not what, and are left out.
CHAPTER_MENTION = re.compile(r"第\s*[0-9０-９零〇一二两三四五六七八九十百千]+\s*[章回节卷]")
CHAPTER_NUMBER_IN = re.compile(r"第\s*([0-9０-９零〇一二两三四五六七八九十百千]+)\s*章")
NUMBER_WORDS = re.compile(r"万一|一一|十分|千万|万万|三三两两|七七八八|一五一十|十全十美|百分之百")
NUMBERS = re.compile(r"[0-9０-９]+|[零〇一二两三四五六七八九十百千万]{2,}|[零〇一二两三四五六七八九十百千](?=[年月日号岁点时])")
DIGITS = {ch: i for i, ch in enumerate("零一二三四五六七八九")} | {"〇": 0, "两": 2}
UNITS = {"十": 10, "百": 100, "千": 1000, "万": 10000}


def _number(token: str) -> int:
    if token.isdigit():
        return int(token)
    total, section, digit = 0, 0, None
    for ch in token:
        if ch in DIGITS:
            digit = DIGITS[ch] if digit is None else digit * 10 + DIGITS[ch]  # "二〇二六" read digit by digit
        elif ch == "万":
            total, section, digit = (total + section + (digit or 0)) * 10000, 0, None
        else:
            section += (1 if digit is None else digit) * UNITS[ch]
            digit = None
    return total + section + (digit or 0)


def numbers_in(text: str) -> set[int]:
    """The numbers a text states, written in figures or in Chinese ("十二" and "12" are one number)."""
    text = NUMBER_WORDS.sub("", CHAPTER_MENTION.sub("", "".join(text.split())))
    return {_number(token.translate(str.maketrans("０１２３４５６７８９", "0123456789"))) for token in NUMBERS.findall(text)}


# What the author says the new state is should be in the evidence: an author who names a place the text does not ("写成服务台
# 后面的抽屉" where the text has the bell on the duty desk) is told what the text says, not handed a card with the text's value
# (A2 second formal run, w02-no-action-04, three passes of three). Authors put the text's state in words of their own as often
# ("只能手动锁" for "只作手动锁定"), and no count of shared characters tells the two apart: as a refusal the check stopped 57
# proposals of 14 tasks that were asked for, against 10 where the author had it wrong (second pair, p40). So it holds the
# item back for a second look, once, and the model decides.
AUTHOR_VALUE_MAX = 40
AUTHOR_VALUE_FOUND = 0.5
# An author who gives a thread up or wants a record gone asks for what this version cannot do; marking the thread resolved
# is not that (A2 second formal run, w02-no-action-06: "把这条伏笔改为放弃" became a resolved thread).
GIVE_UP = re.compile(r"放弃|不追|不要了|作废|删掉|删除|删了|去掉|撤掉|不打算用|不想留")
# The piece of the author's sentence an item stands on (its clause) says what the author wants done with that record.
# Asked only to read it ("那条请读全"), nothing is changed: the record that carried a hidden note was rewritten, note and all,
# in three passes of three (A2 second pair, p41, injection-07). Asked about a fact in a fact's words ("改掉旧说法", "状态"),
# the item is not a thread marked resolved (action-08). Over every card of every A2 run so far neither refuses an item that
# was asked for (856 of them).
READ_ONLY = re.compile(r"读全|读一遍|读完|看看|看一下|看一遍|看完|核对|核实|对一遍|说说|讲讲|查查|确认一下|回顾")
CHANGE_WORDS = re.compile(r"改|更新|修正|订正|换|补|记|加|添|存|收|标|录|写|入|留|挪|移|填|调|结|销|退|删|放|去掉|跟上|撤|清|登|归|变成|别再|别停|别漏|别空")
FACT_WORDS = re.compile(r"旧说法|说法|状态|资料|事实|那栏|那格|一栏|一格|记成|记录")
THREAD_WORDS = re.compile(r"伏笔|线|疑问|谜|悬|问号|着落|收掉|收一收|回收|结清|吊着|挂着|查明|查清|解释|来路|缘故|原因")
CLAUSE_BREAK = re.compile(r"[，。；！？,;!?]")
# What a piece of the request list asks for, when it is not a change of the kind proposed on it.
WANT_REFUSALS = {"look": "change_read_only", "abandon_thread": "change_give_up_not_resolve", "delete": "change_give_up_not_resolve",
                 "prose": "change_prose_not_fact"}


def _clause(ctx: ToolContext, request_words: str) -> str:
    """The clause of the author's sentence that holds the item's request words."""
    question = _question(ctx)
    start = question.find(request_words)
    begin = max((m.end() for m in CLAUSE_BREAK.finditer(question, 0, start)), default=0)
    end = next((m.start() for m in CLAUSE_BREAK.finditer(question, start + len(request_words))), len(question))
    return question[begin:end]


def _grounded(ctx: ToolContext, action: Action, args: dict[str, Any], proposal: dict[str, Any], request_words: str) -> None:
    """What an item says must come from its evidence, and from the author only what the evidence bears out; what the author
    asked done with the record must be a change of this kind."""
    evidence = "".join("".join(item["text"].split()) for item in proposal["evidence"])
    if action.creates and PROSE_SUBJECT.search(proposal["after"]["subject"]):
        raise ToolError("change_prose_not_fact")
    if assistant_requests.decides(ctx.requests, _question(ctx), request_words):
        # The request list says what this piece of the sentence asks for; the word lists below are for words it does not hold.
        want = assistant_requests.refusal(ctx.requests, _question(ctx), request_words, action.kind)
        if want is not None:
            raise ToolError(WANT_REFUSALS.get(want, "change_fact_not_thread" if want == "fact" else "change_thread_not_fact"))
    else:
        clause = _clause(ctx, request_words)
        if READ_ONLY.search(clause) and not CHANGE_WORDS.search(clause):
            raise ToolError("change_read_only")
        if action.kind == "resolve_thread":
            if GIVE_UP.search(_question(ctx)):
                raise ToolError("change_give_up_not_resolve")
            if FACT_WORDS.search(clause) and not THREAD_WORDS.search(clause):
                raise ToolError("change_fact_not_thread")
    if action.kind == "resolve_thread":
        return
    # A number the materials already state about the subject may stay ("原定第二十一昼期" kept beside the new day).
    subject = "".join(proposal["after"]["subject"].split())
    known = "".join(fact["value"] for fact in ctx.memory() if "".join(fact["subject"].split()) == subject)
    if not numbers_in(proposal["after"]["value"]) <= numbers_in(evidence) | numbers_in(known):
        raise ToolError("change_value_not_in_evidence")


def _author_value_missing(ctx: ToolContext, args: dict[str, Any], proposal: dict[str, Any]) -> str | None:
    """The author's own words for the new state when the evidence does not bear them out; None otherwise, and when the field
    holds anything but the author's words (it is then ignored: refusing it only cost rounds)."""
    said = "".join(str(args.get("author_value") or "").split())
    if not said or len(said) > AUTHOR_VALUE_MAX or said not in _question(ctx):
        return None
    pairs = _pairs(said)
    evidence = "".join("".join(item["text"].split()) for item in proposal["evidence"])
    return said if pairs and len(pairs & _pairs(evidence)) / len(pairs) < AUTHOR_VALUE_FOUND else None


def _second_look(ctx: ToolContext, action: Action, args: dict[str, Any], proposal: dict[str, Any], request_words: str) -> dict[str, Any] | None:
    """What a fact item is held back for the first time it is proposed, with what the model should weigh before proposing
    it again; None when it goes on the card. The prompt already asks for each of these; the model still slipped on them,
    one or two tasks in a pass, and a pass of the A2 bar allows no unrequested change:
    - a new fact that repeats much of an existing fact about the same person or thing, or that names someone an existing fact
      holds as its value: the same matter in other words ("宿鸢跟甄宿微是同一个人" added beside 甄宿微's alias fact,
      spent-pair pass 4, w01-no-action-01). Any fact about the subject used to be enough, which held 272 of the new facts
      asked for; this holds 41, and 6 of the 7 duplicates of the no-action tasks;
    - a changed fact that keeps most of the old value: the old fact said it already (w02-no-action-02);
    - a changed fact whose request words share no characters with the record: the author's words may be about another record
      (w02-action-10: "红环那两下光没在说感染" put on a fact about the person's isolation, beside the thread the author asked
      for). Not for a new fact, which has no record to share them with (120 new facts asked for held, none that were not);
    - a new state the author named that the evidence does not bear out (see AUTHOR_VALUE_FOUND).
    Proposing the same item again puts it on the card. Never when no round follows to propose it in."""
    if ctx.last or action.kind == "resolve_thread":
        return None
    after = proposal["after"]
    key = f"{action.kind}:{''.join(after['subject'].split()) if action.creates else proposal['target_id']}"
    if key in ctx.second_looks:
        return None
    look: dict[str, Any] = {}
    reasons = []
    if action.creates:
        names = _names(after["subject"])
        # A fact whose value holds the name counts too: an alias stands under the full name ("甄宿微 / 别名 / 宿鸢"), and
        # "宿鸢跟甄宿微是同一个人" was added under 宿鸢 beside it (spent-pair 3-pass check, w01-no-action-01, two passes of three).
        new = _pairs(after["value"])

        def same_matter(fact: dict[str, Any]) -> bool:
            value = "".join(fact["value"].split())
            if any(name in value for name in names):
                return True
            pairs = _pairs(value)
            if not pairs:
                return False
            subject = "".join(fact["subject"].split())
            share = len(pairs & new) / len(pairs)
            return (subject == "".join(after["subject"].split()) and share >= SECOND_LOOK_SAME_SUBJECT) \
                or (any(_related(subject, name) for name in names) and share >= SECOND_LOOK_SAME)

        held = [fact for fact in ctx.memory() if same_matter(fact)]
        if held:
            look["existing"] = fact_items(ctx, held[-SECOND_LOOK_FACTS:])
            reasons.append("资料里已经有上面这些相关的事实。作者要记的意思其中已经有了（换了说法、说得更简略也算），就不要加，在回答里引用那条；"
                           "是正文后来变了、旧的那条已经不对，就用 change_fact 改那条。")
    else:
        old = _pairs(proposal["before"]["value"])
        if old and len(old & _pairs(after["value"])) / len(old) >= SECOND_LOOK_KEPT:
            look["current"] = proposal["display"]["before"]
            reasons.append("改后的内容大半还是这条事实原来的话。原来的话已经说了作者要的意思（只是简略些、措辞不同），就不要改，在回答里引用这条事实。")
    display = proposal["display"]
    if not action.creates and not _pairs(request_words) & _pairs(display["title"] + display["before"] + display["after"]):
        reasons.append(f"作者的「{request_words}」和这条资料没有一个字对得上。确认作者说的就是这条（外号、换了说法也算）；作者说的是别的资料，就不要提出这条。")
    said = _author_value_missing(ctx, args, proposal)
    if said:
        reasons.append(f"作者说的「{said}」在依据段落里没有原样出现。只是作者换了个说法、意思和正文一样，就再提出一次；"
                       "正文写的和作者说的不一样，就不要提出，用带出处的句子告诉作者正文是怎么写的。")
    if not reasons:
        return None
    ctx.second_looks.add(key)
    ctx.held_now += 1
    return {"status": "second_look", **look,
            "message": "这条改动还没有放进卡片。" + "".join(reasons) + "确实需要，就原样再提出一次，会放进卡片。"}


def run_propose_change(ctx: ToolContext, args: dict[str, Any]) -> Outcome:
    action = ACTIONS.get(args.get("action"))
    if action is None:
        raise ToolError("change_action_unknown")
    request_words = _request_words(ctx, args.get("request_words"))
    target = None
    if action.target_kind:
        target = ctx.registry.rows.get(args.get("target")) if isinstance(args.get("target"), str) else None
        if target is None or target["kind"] != action.target_kind:
            raise ToolError("change_target_invalid")
    task_id = ctx.task["id"]
    with ctx.db.connection() as c:
        earlier = c.execute("SELECT * FROM assistant_changes WHERE task_id=? ORDER BY ordinal", (task_id,)).fetchall()
    if len(earlier) >= CARD_MAX_ITEMS:
        raise ToolError("change_limit_reached")
    # One piece of the author's sentence asks for one change: a second change on the same words is one the author did not
    # ask for (A2 first formal run, w01/w02-action-12: a thread marked resolved and, on the same words, a fact changed too).
    if any(_shared(_question(ctx), json.loads(row["display_json"]).get("request_words") or "", request_words) for row in earlier):
        raise ToolError("change_request_words_taken")
    proposal = action.propose(ctx, args, target)
    _grounded(ctx, action, args, proposal, request_words)
    proposal["display"]["request_words"] = request_words
    for row in earlier:
        if row["target_id"] == proposal["target_id"] or (action.creates and row["kind"] == action.kind
                                                         and _same_new_record(json.loads(row["after_json"]), proposal["after"])):
            raise ToolError("change_duplicate")
    shown = {"action": action.kind, "target": args.get("target") if action.target_kind else None, "evidence": [item["ref"] for item in proposal["evidence"]],
             "request_words": request_words}
    look = _second_look(ctx, action, args, proposal, request_words)
    if look is not None:
        return Outcome(look, shown, 0)
    ordinal = len(earlier) + 1
    with ctx.db.connection() as c:
        c.execute("INSERT INTO assistant_changes(id,task_id,project_id,ordinal,kind,target_id,before_json,after_json,display_json,evidence_json,status,created_at) "
                  "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
                  (new_change_id(), task_id, ctx.project_id, ordinal, action.kind, proposal["target_id"], json.dumps(proposal["before"], ensure_ascii=False),
                   json.dumps(proposal["after"], ensure_ascii=False), json.dumps(proposal["display"], ensure_ascii=False),
                   json.dumps(proposal["evidence"], ensure_ascii=False), "proposed", utcnow()))
    return Outcome({"change": f"C{ordinal}", "status": "waiting_for_the_author"}, shown, 1)


def proposed_count(db: Any, task_id: str) -> int:
    with db.connection() as c:
        return c.execute("SELECT COUNT(*) FROM assistant_changes WHERE task_id=?", (task_id,)).fetchone()[0]


# --- the views -----------------------------------------------------------------------------------------------------------
def _current(c: sqlite3.Connection, db: Any, row: Any) -> dict[str, Any] | None:
    return ACTIONS[row["kind"]].read(c, db, row["project_id"], row["target_id"])


def _target(c: sqlite3.Connection, row: Any) -> dict[str, Any]:
    """What the page needs to find the record: a thread's id, or a fact's lineage and its record in the current version."""
    action = ACTIONS[row["kind"]]
    if action.target_kind == "foreshadow":
        return {"kind": "foreshadow", "id": row["target_id"]}
    version = c.execute("SELECT current_memory_version FROM v2_projects WHERE id=?", (row["project_id"],)).fetchone()[0]
    record = fact_at(c, row["project_id"], version, row["target_id"])
    return {"kind": "fact", "id": row["target_id"], "record_id": record["id"] if record else None}


def change_view(c: sqlite3.Connection, db: Any, row: Any) -> dict[str, Any]:
    """One item of a card or the ledger. `changed_since`: the target no longer holds the values this item expects now (the
    values before it while it waits or after an undo, the values it wrote while applied), so a confirm or a plain undo would
    be refused."""
    action = ACTIONS[row["kind"]]
    display = json.loads(row["display_json"])
    expected = json.loads(row["after_json"] if row["status"] == "applied" else row["before_json"])
    return {"id": row["id"], "label": f"C{row['ordinal']}", "task_id": row["task_id"], "kind": row["kind"], "target": _target(c, row),
            "title": display["title"], "before": display["before"], "after": display["after"], "editable": action.editable,
            "request_words": display.get("request_words"),
            "value": json.loads(row["after_json"]).get("value") if action.editable else None,
            "evidence": [{key: item[key] for key in ("chapter_number", "chapter_title", "start", "end", "text")} for item in json.loads(row["evidence_json"])],
            "status": row["status"], "edited_by_author": bool(row["edited_by_author"]),
            "changed_since": None if row["status"] == "rejected" else not action.same(_current(c, db, row), expected),
            "created_at": row["created_at"], "decided_at": row["decided_at"], "applied_at": row["applied_at"], "undone_at": row["undone_at"]}


def task_changes(c: sqlite3.Connection, db: Any, task_id: str) -> list[dict[str, Any]]:
    return [change_view(c, db, row) for row in c.execute("SELECT * FROM assistant_changes WHERE task_id=? ORDER BY ordinal", (task_id,)).fetchall()]


# --- the author's decisions ----------------------------------------------------------------------------------------------
def _event(c: sqlite3.Connection, row: Any, event: str, user_id: str, stamp: str, detail: dict[str, Any] | None = None) -> None:
    c.execute("INSERT INTO assistant_change_events(id,change_id,project_id,event,actor_user_id,detail_json,created_at) VALUES(?,?,?,?,?,?,?)",
              (f"achevent-{uuid.uuid4()}", row["id"], row["project_id"], event, user_id, json.dumps(detail or {}, ensure_ascii=False), stamp))


def _reworded(c: sqlite3.Connection, row: Any, value: Any) -> Any:
    """Store the author's own wording of an item's value before it is written; the card shows it from then on."""
    try:
        value = _text(value, FACT_VALUE_MAX)
    except ToolError as error:
        raise DomainError(error.code, 422) from error
    after = {**json.loads(row["after_json"]), "value": value}
    display = {**json.loads(row["display_json"]), "after": _fact_label(c, after)}
    c.execute("UPDATE assistant_changes SET after_json=?,display_json=?,edited_by_author=1 WHERE id=?",
              (json.dumps(after, ensure_ascii=False), json.dumps(display, ensure_ascii=False), row["id"]))
    return c.execute("SELECT * FROM assistant_changes WHERE id=?", (row["id"],)).fetchone()


def decide(c: sqlite3.Connection, db: Any, store: Any, user_id: str, project_id: str, task_id: str, accepted: list[str] | None,
           edits: dict[str, str] | None = None) -> dict[str, Any]:
    """Apply the accepted items of a card, with any value the author reworded, and turn down the rest (`accepted` None: turn
    down all). All or nothing: when any accepted item's target no longer holds the values the card was made against, or a
    review of the facts is still open for a fact item, nothing is written."""
    db._project(c, user_id, project_id, True)
    task = c.execute("SELECT * FROM assistant_tasks WHERE id=? AND project_id=? AND hidden_at IS NULL", (task_id, project_id)).fetchone()
    if not task or task["kind"] != "change":
        raise DomainError("resource_not_found", 404)
    if task["status"] != "completed":
        raise DomainError("change_task_not_completed", 409)
    rows = c.execute("SELECT * FROM assistant_changes WHERE task_id=? AND status='proposed' ORDER BY ordinal", (task_id,)).fetchall()
    if not rows:
        raise DomainError("change_already_decided", 409)
    chosen, edits = set(accepted or []), edits or {}
    if not chosen <= {row["id"] for row in rows} or not set(edits) <= chosen \
            or any(not ACTIONS[row["kind"]].editable for row in rows if row["id"] in edits):
        raise DomainError("invalid_item_selection", 422)
    stale = [f"C{row['ordinal']}" for row in rows if row["id"] in chosen and not ACTIONS[row["kind"]].same(_current(c, db, row), json.loads(row["before_json"]))]
    if stale:
        raise DomainError("change_target_changed", 409, False, {"changes": stale})
    if any(ACTIONS[row["kind"]].target_kind != "foreshadow" for row in rows if row["id"] in chosen):
        review = memory_review_open(c, db, project_id)
        if review:
            raise DomainError("change_memory_review_pending", 409, False, {"review": review})
    stamp = utcnow()
    for row in rows:
        if row["id"] in chosen:
            if row["id"] in edits:
                row = _reworded(c, row, edits[row["id"]])
            ACTIONS[row["kind"]].write(c, db, project_id, row["target_id"], json.loads(row["after_json"]), user_id, stamp)
            c.execute("UPDATE assistant_changes SET status='applied',decided_at=?,applied_at=? WHERE id=?", (stamp, stamp, row["id"]))
            _event(c, row, "applied", user_id, stamp, {"edited_by_author": True} if row["id"] in edits else None)
        else:
            c.execute("UPDATE assistant_changes SET status='rejected',decided_at=? WHERE id=?", (stamp, row["id"]))
            _event(c, row, "rejected", user_id, stamp)
    return store.view(c, c.execute("SELECT * FROM assistant_tasks WHERE id=?", (task_id,)).fetchone(), user_id)


def _owned_change(c: sqlite3.Connection, db: Any, user_id: str, project_id: str, change_id: str) -> Any:
    db._project(c, user_id, project_id, True)
    row = c.execute("SELECT * FROM assistant_changes WHERE id=? AND project_id=?", (change_id, project_id)).fetchone()
    if not row:
        raise DomainError("resource_not_found", 404)
    return row


def _label(row: Any) -> dict[str, str]:
    display = json.loads(row["display_json"])
    return {"id": row["id"], "title": display["title"], "after": display["after"]}


def undo(c: sqlite3.Connection, db: Any, user_id: str, project_id: str, change_id: str, confirm: bool) -> dict[str, Any]:
    """Put back what an applied item changed. A later applied item on the same target, or a value the target holds that no
    applied item wrote (the author's own edit), is reported first; with `confirm` the later items are undone newest first and
    the values are put back over the edit."""
    row = _owned_change(c, db, user_id, project_id, change_id)
    if row["status"] != "applied":
        raise DomainError("change_state_invalid", 409)
    action = ACTIONS[row["kind"]]
    order = c.execute("SELECT rowid FROM assistant_changes WHERE id=?", (row["id"],)).fetchone()[0]
    later = c.execute("SELECT * FROM assistant_changes WHERE project_id=? AND target_id=? AND status='applied' AND id<>? "
                      "AND (applied_at>? OR (applied_at=? AND rowid>?)) ORDER BY applied_at DESC,rowid DESC",
                      (project_id, row["target_id"], row["id"], row["applied_at"], row["applied_at"], order)).fetchall()
    current = action.read(c, db, project_id, row["target_id"])
    if current is None and not action.creates:
        raise DomainError("change_target_missing", 409)
    newest = later[0] if later else row
    author_changed = not action.same(current, json.loads(newest["after_json"]))
    if (later or author_changed) and not confirm:
        raise DomainError("change_undo_conflict", 409, False, {"later_changes": [_label(item) for item in later], "author_changed": author_changed})
    stamp = utcnow()
    for item in [*later, row]:
        ACTIONS[item["kind"]].write(c, db, project_id, item["target_id"], json.loads(item["before_json"]), user_id, stamp)
        c.execute("UPDATE assistant_changes SET status='undone',undone_at=? WHERE id=?", (stamp, item["id"]))
        _event(c, item, "undone", user_id, stamp, {"with": row["id"]} if item["id"] != row["id"] else {"over_author_edit": author_changed})
    return {"changes": [change_view(c, db, c.execute("SELECT * FROM assistant_changes WHERE id=?", (item["id"],)).fetchone()) for item in [row, *later]]}


def redo(c: sqlite3.Connection, db: Any, user_id: str, project_id: str, change_id: str) -> dict[str, Any]:
    """Apply an undone item again, under the confirm's check: the target must still hold the values it had before the item."""
    row = _owned_change(c, db, user_id, project_id, change_id)
    if row["status"] != "undone":
        raise DomainError("change_state_invalid", 409)
    if not ACTIONS[row["kind"]].same(_current(c, db, row), json.loads(row["before_json"])):
        raise DomainError("change_target_changed", 409, False, {"changes": [f"C{row['ordinal']}"]})
    stamp = utcnow()
    ACTIONS[row["kind"]].write(c, db, project_id, row["target_id"], json.loads(row["after_json"]), user_id, stamp)
    c.execute("UPDATE assistant_changes SET status='applied',applied_at=?,undone_at=NULL WHERE id=?", (stamp, row["id"]))
    _event(c, row, "redone", user_id, stamp)
    return {"changes": [change_view(c, db, c.execute("SELECT * FROM assistant_changes WHERE id=?", (row["id"],)).fetchone())]}


def ledger(c: sqlite3.Connection, db: Any, user_id: str, project_id: str, limit: int) -> dict[str, Any]:
    """The changes the author confirmed (applied, or undone since), the latest first; the page lists them with undo."""
    db._project(c, user_id, project_id)
    rows = c.execute("SELECT * FROM assistant_changes WHERE project_id=? AND status IN ('applied','undone') "
                     "ORDER BY COALESCE(undone_at,applied_at) DESC,rowid DESC LIMIT ?", (project_id, limit)).fetchall()
    return {"changes": [change_view(c, db, row) for row in rows]}


# --- routes ---------------------------------------------------------------------------------------------------------------
class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ChangeConfirm(Strict):
    accepted: list[str] = Field(min_length=1, max_length=CARD_MAX_ITEMS)
    # The author's own wording of a fact's value, by item id; only for accepted fact items.
    edits: dict[str, str] = Field(default_factory=dict, max_length=CARD_MAX_ITEMS)


class ChangeUndo(Strict):
    confirm: bool = False


class ChangeAction(Strict):
    client_request_id: str | None = None


def register_routes(app: Any, db: Any, user: Callable, csrf: Callable, key: Callable, ok: Callable, operation: Callable, engine: Any) -> None:
    base = "/api/projects/{project_id}/assistant"

    def write(name: str, request: Request, idempotency_key: str | None, payload: dict[str, Any], factory: Callable[[sqlite3.Connection, dict[str, Any]], dict[str, Any]],
              scope: str):
        csrf(request)
        operation(request, f"assistant_change_{name}_failed")
        actor = user(request)
        with db.connection() as c:
            c.execute("BEGIN IMMEDIATE")
            data, status = db._idem(c, actor["id"], f"assistant_change_{name}:{scope}", key(idempotency_key), payload, lambda: factory(c, actor))
        return ok(request, data, status)

    @app.post(base + "/tasks/{task_id}/changes/confirm")
    def confirm_changes(project_id: str, task_id: str, payload: ChangeConfirm, request: Request,
                        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return write("confirm", request, idempotency_key, payload.model_dump(),
                     lambda c, actor: decide(c, db, engine.store, actor["id"], project_id, task_id, payload.accepted, payload.edits), f"{project_id}:{task_id}")

    @app.post(base + "/tasks/{task_id}/changes/reject")
    def reject_changes(project_id: str, task_id: str, request: Request, payload: ChangeAction | None = None,
                       idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return write("reject", request, idempotency_key, {},
                     lambda c, actor: decide(c, db, engine.store, actor["id"], project_id, task_id, None), f"{project_id}:{task_id}")

    @app.post(base + "/changes/{change_id}/undo")
    def undo_change(project_id: str, change_id: str, request: Request, payload: ChangeUndo | None = None,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        body = (payload or ChangeUndo()).model_dump()
        return write("undo", request, idempotency_key, body,
                     lambda c, actor: undo(c, db, actor["id"], project_id, change_id, body["confirm"]), f"{project_id}:{change_id}")

    @app.post(base + "/changes/{change_id}/redo")
    def redo_change(project_id: str, change_id: str, request: Request, payload: ChangeAction | None = None,
                    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key")):
        return write("redo", request, idempotency_key, {},
                     lambda c, actor: redo(c, db, actor["id"], project_id, change_id), f"{project_id}:{change_id}")

    @app.get(base + "/changes")
    def list_changes(project_id: str, request: Request, limit: int = LEDGER_LIMIT):
        actor = user(request)
        with db.connection() as c:
            return ok(request, ledger(c, db, actor["id"], project_id, max(1, min(limit, LEDGER_LIMIT))))
