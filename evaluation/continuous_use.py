"""Continuous use (v2.2 plan 0.2): one author works through a whole manuscript for forty rounds, the chapters arriving as
they are written, and the materials are measured as they go.

Not a registered evaluation and no bar: it is for finding what single tasks cannot show (materials that grow messy with use,
duplicate facts, undo after many changes, cost and wait per round). A model plays the author: on each round the schedule
says what the author does (asks, has a change recorded, gets a fact wrong, starts a long task, undoes), and the model writes
the author's sentence from the chapters so far and the materials as they stand. The sentence goes into the input box as an
author's would (the route decides the use). Cards are confirmed, partly confirmed or declined by the schedule; an undo
always takes back the card confirmed the round before, so the materials can be held against what they were.

The work is a spent one (eval_set_a3_formal, w01, 30 chapters): it starts with the first 8 chapters and its starting
materials, and three chapters are appended every four rounds.

Memory (v2.2 plan 6.8): on round 5 the author makes a standing decision, that a thread still open is to stay open and is not to
be suggested for closing; its record card is always confirmed. Every later card is then searched for an item that closes or
drops that thread, and on round 37 the author asks which threads could be closed next.

    python -m evaluation.continuous_use --run-id u1 --max-cny 20 --assistant-rates 2,8 --judge-rates 9,27
"""
from __future__ import annotations

import argparse
import json
import pathlib
import re
import sys
import time

from evaluation.assistant_a1.run import ROOT, Ledger, PricedProvider, chapters, rates, response_data, write_json
from evaluation.assistant_a2 import run as a2
from evaluation.assistant_a3 import run as a3

from app import long_tasks as lt
from app.assistant_actions import ACTIONS

SET, WORK = "eval_set_a3_formal", "w01"
START_CHAPTERS, APPEND_EVERY, APPEND_CHAPTERS = 8, 4, 3
# What the author does on each round. An undo follows a round that confirmed a card.
SCHEDULE = ("ask", "change_new", "change_new", "undo", "decide", "change_thread", "change_wrong", "long_audit",
            "change_new", "ask", "no_change", "change_new", "undo", "ask", "change_thread", "long_trace",
            "change_new", "change_wrong", "ask", "change_new", "ask", "change_thread", "undo", "change_new",
            "ask", "long_audit", "change_new", "change_wrong", "ask", "change_thread", "no_change", "change_new",
            "ask", "change_new", "undo", "long_trace", "ask_open", "change_new", "change_thread", "ask")
# The n-th change card (from 1): declined, or only its first item confirmed (the rest declined); the others confirmed whole.
DECLINED, PARTLY = {5, 10}, {3, 8}
GUIDE = {
    "ask": "问助手一个关于前文的问题：某个人物知道什么、某件事是怎么发生的、某样东西现在在谁手里或在哪里。只问，不要求改资料。",
    "change_new": "根据最新写好的几章，让助手把一个新的变化记进资料：可以是新的事实，也可以是旧事实变了要改。说清是哪一章、什么变了。",
    "change_thread": "根据最新写好的几章，让助手处理一条伏笔：已经收了就标已回收，不打算写了就标放弃，新埋下的就加一条。",
    "change_wrong": "让助手把一件事记进资料，但你记错了：说的和最新几章正文写的不一样（地点、人物或结果说错）。像真作者一样自然地说，不要暴露自己记错。",
    "no_change": "说一句和资料有关、但其实不需要改的话，比如只想看看某条资料，或者确认一件资料里已经记着的事。",
    "long_audit": "请助手把还没收的伏笔都清点一遍。",
    "long_trace": "请助手把某个人物或某件重要东西从头到现在的经过梳理一遍（挑一个前文出现多次的）。",
    "decide": "对助手定下一条以后都要守的决定：伏笔「{thread}」你打算留到全书很后面才收，以后清点或梳理伏笔时都不要建议把它收掉或放弃。用自己的话说，点名这条伏笔。",
    "ask_open": "问助手接下来几章可以收哪些伏笔、哪些线该有个了结。只问，不要求改资料。",
}
CLOSING = {"resolve_thread", "abandon_thread"}
AUTHOR_SYSTEM = ("你在扮演一位正在连载长篇小说的作者，用写作软件里的 AI 助手管理自己的作品资料（事实和伏笔）。"
                 "每次只说一句或两句作者会在输入框里打的话：口语、具体，提到人物和章节时用作品里的名字。"
                 "只输出 JSON：{\"request\": \"作者这句话\"}。")
NEW_CHAPTER_CHARS = 1500
MATERIAL_LINES = 80


class Work(a3.Work):
    """A3's work, started with the first chapters only and the starting materials they bear."""

    def prepare(self, work, upto):
        self.response("POST", "/api/auth/register", json={"account_name": self.account, "display_name": "U", "password": a2.PASSWORD,
                                                          "recovery_email": "u@example.test"})
        response_data(self.client.post("/api/auth/login", json={"account_name": self.account, "password": a2.PASSWORD}))
        source = "".join(chapters(work["source"])[:upto])
        preview = self.request("POST", "/api/imports/preview", files={"file": ("work.md", source.encode("utf-8"), "text/markdown")})
        self.project = self.request("POST", f"/api/imports/{preview['import_id']}/commit", json={
            "confirm": True, "title": work["title"], "chapter_preview_ids": [c["preview_id"] for c in preview["detected"]["chapters"]]})["project"]["id"]
        self.base = f"/api/projects/{self.project}"
        self.listing = self.request("GET", self.base + "/chapters?include=excerpt")["chapters"]
        by_number = {c["number"]: c for c in self.listing}
        self.facts = self._put_facts([f for f in work["facts"] if f["chapter"] <= upto], by_number)
        self.threads, version = [], 0
        for item in work["threads"]:
            if item["planted_chapter"] > upto:
                continue
            planted, resolved = by_number[item["planted_chapter"]], by_number.get(item.get("resolved_chapter"))
            body = {"base_foreshadow_version": version, "title": item["title"], "description": item["description"],
                    "status": item["status"] if resolved or item["status"] != "resolved" else "planted",
                    "planted_chapter_id": planted["id"], "planted_source_span_id": planted["source_spans"][0]["span_id"]}
            if resolved:
                body.update(resolved_chapter_id=resolved["id"], resolved_source_span_id=resolved["source_spans"][0]["span_id"])
            self.threads.append(self.request("POST", self.base + "/foreshadows", json=body)["item"]["id"])
            version += 1
        # The thread the author will decide to keep open: the earliest planted one the whole book leaves open.
        self.kept_open = min((t for t in work["threads"] if t["planted_chapter"] <= upto and not t.get("resolved_chapter")
                              and t["status"] != "resolved"), key=lambda t: t["planted_chapter"])["title"]
        self.revision, self.written = 1, upto
        self.start = a2.snapshot(self.app.state.database, self.project)
        self.initialization = {"facts": len(self.facts), "threads": len(self.threads)}

    def append(self, text):
        """New chapters as an author adds them (paste, append)."""
        change = self.request("POST", self.base + "/source-change-sets/preview", json={
            "mode": "append", "input_method": "paste", "base_source_revision": self.revision, "content": text})["source_change_set"]
        self.request("POST", self.base + f"/source-change-sets/{change['id']}/commit", json={"confirm": True, "content_sha256": change["content_sha256"]})
        self.revision += 1
        self.listing = self.request("GET", self.base + "/chapters?include=excerpt")["chapters"]

    def materials(self):
        snap = a2.snapshot(self.app.state.database, self.project)
        facts = [f for f in snap["facts"].values()]
        threads = [t for t in snap["threads"].values() if not t.get("archived_at")]
        return snap, facts, threads


# --- measures --------------------------------------------------------------------------------------------------------
def squeeze(text):
    return "".join(ch for ch in str(text or "") if ch.isalnum())


def pairs(text):
    text = squeeze(text)
    return {text[i:i + 2] for i in range(len(text) - 1)}


def tidiness(facts, threads):
    """How messy the materials are: facts filed twice under one subject and property, facts under one subject that say much the
    same (half of the shorter one's character pairs), and threads with the same title."""
    slots, same = {}, []
    for fact in facts:
        slots.setdefault((squeeze(fact["subject"]), squeeze(fact["predicate"])), []).append(fact)
    by_subject = {}
    for fact in facts:
        by_subject.setdefault(squeeze(fact["subject"]), []).append(fact)
    for subject, held in by_subject.items():
        for i, a in enumerate(held):
            for b in held[i + 1:]:
                pa, pb = pairs(a["value"]), pairs(b["value"])
                if pa and pb and len(pa & pb) / min(len(pa), len(pb)) >= 0.5:
                    same.append([f"{a['subject']}·{a['predicate']}：{a['value']}", f"{b['subject']}·{b['predicate']}：{b['value']}"])
    titles = {}
    for thread in threads:
        titles.setdefault(squeeze(thread["title"]), []).append(thread["title"])
    return {"facts": len(facts), "threads": len(threads),
            "open_threads": sum(t["status"] == "planted" for t in threads),
            "twice_in_one_slot": [[f"{f['subject']}·{f['predicate']}：{f['value']}" for f in group] for group in slots.values() if len(group) > 1],
            "much_the_same": same, "same_thread_title": [group for group in titles.values() if len(group) > 1]}


# --- the author ------------------------------------------------------------------------------------------------------
def author_says(provider, ledger, kind, work, source_chapters, history, number):
    _, facts, threads = work.materials()
    newest = source_chapters[max(0, work.written - APPEND_CHAPTERS):work.written]
    lines = [f"- {f['subject']}·{f['predicate']}：{f['value']}" for f in facts][-MATERIAL_LINES:]
    lines += [f"- 伏笔「{t['title']}」（{'已回收' if t['status'] == 'resolved' else '已放弃' if t['status'] == 'abandoned' else '还没收'}）" for t in threads]
    user = "\n".join([
        f"这是第 {number} 轮。作品已经写到第 {work.written} 章。",
        "最新写好的几章（节选）：", *[chapter[:NEW_CHAPTER_CHARS] for chapter in newest],
        "现在资料里记着的：", *lines,
        "你前几轮对助手说过的话和结果：", *(history[-5:] or ["（还没有）"]),
        f"这一轮你要做的：{GUIDE[kind].format(thread=work.kept_open)}", "不要重复前几轮说过的事。"])
    ledger.phase, ledger.task_id = "author", f"r{number}"
    result = provider.route([{"role": "system", "content": AUTHOR_SYSTEM}, {"role": "user", "content": user}], 400, 60, role="requests")
    try:
        said = json.loads((result.message or {}).get("content") or "{}").get("request")
    except ValueError:
        said = None
    return said if isinstance(said, str) and said.strip() else None


# --- one round -------------------------------------------------------------------------------------------------------
def card_items(work, task_id):
    return [item for item in work.card(task_id) if item["status"] == "proposed"]


def decide_card(work, task_id, items, card_number, long_task=False, always=()):
    """Confirm the whole card, its first item only, or none, by the schedule; the items in `always` (decision records) are
    confirmed whatever the schedule says. Returns what was confirmed."""
    accepted = [] if card_number in DECLINED else items[:1] if card_number in PARTLY and len(items) > 1 else items
    accepted = list(always) + accepted
    path = f"/assistant/long-tasks/{task_id}" if long_task else f"/assistant/tasks/{task_id}"
    statuses = []
    if accepted:
        if long_task:  # a group at a time, a high-risk item alone (as the card shows it)
            groups, by_kind = [], {}
            for item in accepted:
                if ACTIONS[item["kind"]].risk == "high":
                    groups.append([item])
                else:
                    by_kind.setdefault(item["kind"], []).append(item)
            groups += list(by_kind.values())
            for group in groups:
                ids = [i["id"] for i in group]
                statuses.append(work.response("POST", work.base + path + "/changes/confirm", json={"accepted": ids, "within": ids}).status_code)
        else:
            statuses.append(work.response("POST", work.base + path + "/changes/confirm", json={"accepted": [i["id"] for i in accepted]}).status_code)
    if len(accepted) < len(items) and not long_task:
        statuses.append(work.response("POST", work.base + path + "/changes/reject", json={}).status_code)
    return accepted, statuses


def run_long(work, request, record):
    created = work.long("POST", "", {"question": request, "context": {"page": "materials"}})
    if created.status_code != 202:
        record["error"] = f"long_create_http_{created.status_code}"
        return None
    task_id = created.json()["data"]["id"]
    view = work.view(task_id)
    started = time.perf_counter()
    if view["status"] == lt.AWAITING_PLAN:
        record["plan"] = view["plan"]["proposed"]
        work.long("POST", f"/{task_id}/start")
        for _ in range(12):
            view = work.view(task_id)
            if view["status"] == lt.WAITING:
                question = next(q for q in view["questions"] if q["answer"] is None)
                choice = "stop" if question["kind"] == "budget" else "you_decide"
                record.setdefault("questions", []).append({"text": question.get("text"), "choice": choice})
                work.long("POST", f"/{task_id}/answer", {"question_id": question["id"], "choice": choice})
                continue
            if view["status"] in (lt.QUEUED, lt.RUNNING):
                work.app.state.long_tasks.sweep()
                continue
            break
    if view["status"] in lt.ACTIVE:
        record["error"] = "long_task_left_active"
        work.long("POST", f"/{task_id}/stop")
        view = work.view(task_id)
    record["seconds"] = time.perf_counter() - started
    record["status"], record["error_code"] = view["status"], view.get("error_code")
    with work.app.state.database.connection() as c:
        row = c.execute("SELECT cost_cny FROM assistant_tasks WHERE id=?", (task_id,)).fetchone()
    record["cost_cny"] = row["cost_cny"] if row else 0
    record["answer"] = view.get("answer")
    return task_id


def play(work, provider, ledger, source_chapters, out, run_id):
    report = {"run_id": run_id, "set": SET, "work": WORK, "start": {"chapters": work.written, **tidiness(*work.materials()[1:])},
              "rounds": [], "git_commit": a2.git("rev-parse", "HEAD")}
    report["kept_open"] = work.kept_open
    history, cards, last_confirmed, decided = [], 0, None, None
    for number, kind in enumerate(SCHEDULE, 1):
        record = {"round": number, "kind": kind, "chapters": work.written}
        if kind == "undo":
            if not last_confirmed:
                record["skipped"] = "nothing_confirmed_last_round"
            else:
                before, items = last_confirmed
                record["undo_statuses"] = [work.response("POST", work.base + f"/assistant/changes/{item['id']}/undo", json={"confirm": False}).status_code
                                           for item in reversed(items)]
                after = work.materials()[0]
                record["undo_exact"] = all(code == 200 for code in record["undo_statuses"]) and a2.undo_restored(before, after, items)
                history.append(f"第{number}轮：撤销了上一轮确认的 {len(items)} 条改动")
            last_confirmed = None
        else:
            last_confirmed = None
            request = author_says(provider, ledger, kind, work, source_chapters, history, number)
            record["request"] = request
            if request is None:
                record["error"] = "author_said_nothing"
            else:
                ledger.task_id = f"r{number}"
                ledger.phase = "route"
                routed = work.route({"input": request, "context": {"page": "materials"}})
                record["route"] = routed.get("route")
                use = record["route"] if record["route"] in ("ask", "change", "long_task") else None
                ledger.phase = "assistant"
                task_id = None
                if use == "long_task":
                    task_id = run_long(work, request, record)
                elif use:
                    view, _ = a1_retry(lambda: work.assistant({"kind": use, "question": request, "context": {"page": "materials"}}))
                    task_id = view.get("id")
                    record.update(status=view.get("status"), error_code=view.get("error_code"), seconds=view.get("elapsed_seconds"),
                                  cost_cny=(view.get("token_usage") or {}).get("cost_cny"), answer=view.get("answer"),
                                  consensus_runs=(view.get("consensus") or {}).get("runs"))
                else:
                    record["status"] = "not_run"
                every = card_items(work, task_id) if task_id else []
                record["card"] = [{"kind": i["kind"], "title": i["display"].get("title"), "before": i["display"].get("before"),
                                   "after": i["display"].get("after")} for i in every]
                records = [i for i in every if i["kind"] == "add_decision"]
                items = [i for i in every if i["kind"] != "add_decision"]
                if decided and any(i["kind"] in CLOSING and work.kept_open in json.dumps(i["display"], ensure_ascii=False) for i in items):
                    record["kept_open_reraised"] = True
                if kind == "ask_open":
                    record["kept_open_named"] = work.kept_open in json.dumps(record.get("answer"), ensure_ascii=False)
                if every:
                    if items:
                        cards += 1
                        record["card_number"] = cards
                    before = work.materials()[0]
                    accepted, statuses = decide_card(work, task_id, items, cards if items else 0, long_task=use == "long_task", always=records)
                    record.update(confirmed=len(accepted), decision_records=len(records), decision_statuses=statuses)
                    if records and all(code == 200 for code in statuses):
                        decided = decided or number
                    if accepted and all(code == 200 for code in statuses):
                        last_confirmed = (before, accepted)
                outcome = (f"{len(items)} 条改动，确认 {record.get('confirmed', 0)} 条" if items else "没有改动")
                history.append(f"第{number}轮：你说「{request}」→ 助手按{record.get('route')}处理，{outcome}")
        if number % APPEND_EVERY == 0 and work.written < len(source_chapters):
            upto = min(len(source_chapters), work.written + APPEND_CHAPTERS)
            work.append("".join(source_chapters[work.written:upto]))
            record["appended"] = [work.written + 1, upto]
            work.written = upto
        record["materials"] = tidiness(*work.materials()[1:])
        record["author_cost_cny"] = sum(c["cost_cny"] for c in ledger.calls if c["phase"] == "author" and c["task_id"] == f"r{number}")
        report["rounds"].append(record)
        report["spent_cny"] = ledger.spent
        write_json(out, report)
        print(json.dumps({"round": number, "kind": kind, "route": record.get("route"), "card": len(record.get("card") or []),
                          "facts": record["materials"]["facts"], "spent": round(ledger.spent, 3)}, ensure_ascii=False), flush=True)
    return report


def a1_retry(fn):
    from evaluation.assistant_a1.run import retry
    return retry(fn)


def summary(report):
    rounds = report["rounds"]
    ran = [r for r in rounds if r.get("seconds") is not None]
    by = {}
    for r in ran:
        by.setdefault(r.get("route"), []).append(r)
    end = rounds[-1]["materials"]
    carded = "、".join(str(r["round"]) for r in rounds if r.get("decision_records"))
    reraised = "、".join(f"第{r['round']}轮" for r in rounds if r.get("kept_open_reraised"))
    lines = [f"# 连续使用 {report['run_id']}（{report['git_commit'][:7]}）", "",
             f"从第 {report['start']['chapters']} 章写到第 {rounds[-1]['chapters']} 章，{len(rounds)} 轮。", "",
             "| 用法 | 次数 | 平均费用 | 最长等待（秒） |", "|---|---|---|---|"]
    for route, items in sorted(by.items(), key=lambda kv: str(kv[0])):
        costs = [r.get("cost_cny") or 0 for r in items]
        lines.append(f"| {route} | {len(items)} | ¥{sum(costs) / len(costs):.3f} | {max(r['seconds'] or 0 for r in items):.0f} |")
    lines += ["", f"资料：事实 {report['start']['facts']} → {end['facts']}，伏笔 {report['start']['threads']} → {end['threads']}（还开着 {end['open_threads']}）。",
              f"同一人物同一属性记了两条：{len(end['twice_in_one_slot'])} 组；同一人物两条说得差不多：{len(end['much_the_same'])} 对；同名伏笔：{len(end['same_thread_title'])} 组。",
              "撤销：" + "、".join(f"第{r['round']}轮 {'复原' if r.get('undo_exact') else '没有复原'}" for r in rounds if "undo_exact" in r),
              f"决定：「{report['kept_open']}」先别收，记录卡片在第 {carded or '—'} 轮出现；之后又被建议收掉或放弃：{reraised or '没有'}；"
              f"问该收哪些伏笔时{'提到了它' if any(r.get('kept_open_named') for r in rounds) else '没有提到它'}。", "",
              f"总花费 ¥{report['spent_cny']:.2f}（作者模型 ¥{sum(r.get('author_cost_cny', 0) for r in rounds):.2f}）。"]
    return "\n".join(lines)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--run-id", required=True)
    p.add_argument("--max-cny", type=float, default=20)
    p.add_argument("--assistant-rates", type=rates, required=True)
    p.add_argument("--judge-rates", type=rates, required=True)
    args = p.parse_args()
    results = ROOT / "evaluation/results"
    out = results / f"continuous-{args.run_id}.json"
    if out.exists():
        raise SystemExit("run_output_already_exists")
    data = a3.load_set(SET)
    source = next(w for w in data["works"] if w["key"] == WORK)
    source_chapters = chapters(source["source"])
    ledger = Ledger(args.max_cny, args.assistant_rates, args.judge_rates)
    provider = PricedProvider(ledger)
    work = Work(source, START_CHAPTERS, provider, args.assistant_rates, root=results / f"ws-continuous-{args.run_id}")
    try:
        report = play(work, provider, ledger, source_chapters, out, args.run_id)
    finally:
        work.close()
    text = summary(report)
    out.with_suffix(".md").write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    sys.exit(main())
