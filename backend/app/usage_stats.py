"""Read-only usage statistics for the assistant (v2.1): `stats-v1`.

    python -m app.usage_stats --db <demo.sqlite3> [--since 2026-10-01] [--until 2026-10-31] [--format json|markdown] [--out FILE]

What it is for: finding the most common failures of the assistant (to write our own development items from) and comparing each release
with the one before. The numbers are not release gates.

What it never does: write to the database (it opens it read-only), or read an author's text. Every query goes through `ALLOWED`, the
columns this script may read, table by table - ids, kinds, statuses, codes, counts, tokens, costs, character counts, times, prompt
versions, model labels, account types and whether a project is a sample. There are no `SELECT *`, no joins, and none of the columns that
hold text: questions, answers, passages, facts, threads, tool arguments, plans, step reports, card contents. The few `*_json` columns
on the list hold only what this release wrote there for counting (rule codes and counts, reason codes); each is read through a
parser that keeps nothing but known shapes, and every string that reaches the output has passed `_word` (a short ASCII code), so
a column that ever held a sentence would come out as "unrecognized", not as the sentence.

The output keeps the field names of `stats-v1`: a field is added, never renamed or repurposed, so two releases can be compared.
"""
from __future__ import annotations

import argparse
import json
import math
import re
import sqlite3
import statistics
import sys
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterable

SCHEMA = "stats-v1"

# The columns this script may read. Nothing else is ever selected.
ALLOWED: dict[str, tuple[str, ...]] = {
    "assistant_tasks": ("id", "project_id", "user_id", "kind", "status", "error_code", "internal_error_type", "steps_used", "input_tokens",
                        "output_tokens", "cost_cny", "chars_charged", "prompt_version", "model_label", "created_at", "started_at", "completed_at"),
    "assistant_steps": ("task_id", "ordinal", "kind", "tool_name", "result_count", "error_code", "elapsed_ms", "diagnostics_json"),
    "assistant_feedback": ("task_id", "verdict", "reasons_json"),
    "assistant_changes": ("id", "task_id", "kind", "status", "edited_by_author", "created_at", "decided_at", "applied_at", "undone_at"),
    "assistant_change_events": ("change_id", "event", "created_at"),
    "assistant_long_plans": ("task_id", "cap_cny", "origin", "range_edited", "cap_edited", "stopped_by", "plan_type", "chapters_planned"),
    "assistant_long_steps": ("task_id", "ordinal", "status", "attempt", "cost_cny", "chars_read", "started_at", "finished_at", "diagnostics_json"),
    "assistant_long_questions": ("task_id", "step", "kind"),
    "v2_projects": ("id", "data_origin"),
    "v2_users": ("id", "account_type"),
}
SAMPLE_ORIGINS = ("demo_seed", "tutorial_seed")  # as `author_home.SAMPLE_ORIGINS`; the script keeps no import of the app
FEEDBACK_REASONS = ("wrong", "verbose", "not_found", "bad_source")
SEGMENTS = ("registered", "visitor", "sample")
STATUS_GROUPS = {"completed": "completed", "failed": "failed", "cancelled": "stopped", "stopped": "stopped"}  # anything else is "unfinished"
SKIPPED_STATUSES = ("shadow",)  # the hidden second runs of a change task: not an author's task
WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:/\-]{0,79}")
STAMP = re.compile(r"\d{4}-\d\d-\d\dT[0-9:.+\-Z]{1,40}")
UNRECOGNIZED = "unrecognized"
CARD_COUNTS = ("proposed", "confirmed", "rejected", "undone", "edited")


def _word(value: Any, default: str | None = UNRECOGNIZED) -> str | None:
    """A short ASCII code, or `default`. Every string read from the database passes through here before it can reach the output."""
    if value is None:
        return None
    return value if isinstance(value, str) and WORD.fullmatch(value) else default


def _stamp(value: Any) -> str | None:
    return value if isinstance(value, str) and STAMP.fullmatch(value) else None


def _number(value: Any) -> float | int | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value) else None


def _code_counts(value: Any) -> dict[str, int]:
    if not isinstance(value, dict):
        return {}
    return {code: count for key, count in value.items() if (code := _word(key)) and isinstance(count, int) and not isinstance(count, bool) and count >= 0}


# --- reading ------------------------------------------------------------------------------------------------------------------
def open_readonly(path: str | Path) -> sqlite3.Connection:
    """The database opened so that nothing can be written to it: the SQLite `mode=ro` flag and `query_only` besides."""
    file = Path(path).resolve()
    if not file.is_file():
        raise FileNotFoundError(f"no database at {file}")
    connection = sqlite3.connect(f"{file.as_uri()}?mode=ro", uri=True)
    connection.execute("PRAGMA query_only=ON")
    connection.row_factory = sqlite3.Row
    return connection


class Reader:
    """Every read of the database. A table or column outside `ALLOWED` is not readable here; a column the database does not have
    (an older release) comes back as None."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection
        self.present = {row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        self.missing: dict[str, list[str]] = {}

    def rows(self, table: str, where: str = "", params: Iterable[Any] = ()) -> list[dict[str, Any]]:
        wanted = ALLOWED[table]
        if table not in self.present:
            self.missing[table] = list(wanted)
            return []
        have = {row[1] for row in self.connection.execute(f"PRAGMA table_info({table})")}
        absent = [column for column in wanted if column not in have]
        if absent:
            self.missing[table] = absent
        columns = [column for column in wanted if column in have]
        found = self.connection.execute(f"SELECT {','.join(columns)} FROM {table}{' WHERE ' + where if where else ''}", tuple(params)).fetchall()
        return [{**dict.fromkeys(wanted), **dict(zip(columns, row))} for row in found]


def _seconds(start: Any, end: Any) -> float | None:
    try:
        return max(0.0, (datetime.fromisoformat(end) - datetime.fromisoformat(start)).total_seconds())
    except (TypeError, ValueError):
        return None


def _week(stamp: Any) -> str:
    try:
        year, week, _ = datetime.fromisoformat(stamp).isocalendar()
        return f"{year}-W{week:02d}"
    except (TypeError, ValueError):
        return "unknown"


def _json(value: Any) -> Any:
    try:
        return json.loads(value) if isinstance(value, str) and value else None
    except ValueError:
        return None


def _diagnostics(value: Any) -> dict[str, Any]:
    """A step's `diagnostics_json` kept to its known shape: rule codes and counts."""
    data = _json(value)
    data = data if isinstance(data, dict) else {}
    codes = data.get("problem_codes")
    return {"problem_codes": [code for item in codes if (code := _word(item))] if isinstance(codes, list) else [],
            "repairs": _number(data.get("repairs")) or 0, "dropped": _number(data.get("dropped")) or 0,
            "dropped_codes": _code_counts(data.get("dropped_codes")), "apply_dropped_codes": _code_counts(data.get("apply_dropped_codes"))}


def _reasons(value: Any) -> list[str]:
    data = _json(value)
    return [item for item in data if item in FEEDBACK_REASONS] if isinstance(data, list) else []


# --- numbers --------------------------------------------------------------------------------------------------------------------
def _rate(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def _spread(values: list[float | int | None]) -> dict[str, float | None]:
    """The median and the P90 (nearest rank) of the numbers there are; None for both when there are none."""
    found = sorted(value for value in values if value is not None)
    if not found:
        return {"median": None, "p90": None}
    return {"median": round(float(statistics.median(found)), 4), "p90": round(float(found[max(0, math.ceil(0.9 * len(found)) - 1)]), 4)}


def _share(counter: Counter, total: int) -> dict[str, float | None]:
    return {key: _rate(count, total) for key, count in sorted(counter.items())}


# --- the data, per task ------------------------------------------------------------------------------------------------------------
def load(reader: Reader, since: str | None, until: str | None) -> list[dict[str, Any]]:
    """Every task in the time range with the records that hang on it, as plain dicts of codes and numbers."""
    clauses, params = ["status NOT IN ('shadow')"], []
    if since:
        clauses.append("created_at>=?")
        params.append(since)
    if until:
        clauses.append("created_at<?")
        params.append((date.fromisoformat(until) + timedelta(days=1)).isoformat())
    tasks = reader.rows("assistant_tasks", " AND ".join(clauses), params)
    projects = {row["id"]: row["data_origin"] for row in reader.rows("v2_projects")}
    users = {row["id"]: row["account_type"] for row in reader.rows("v2_users")}
    by_task: dict[str, dict[str, list]] = {table: defaultdict(list) for table in
                                           ("steps", "feedback", "changes", "plans", "long_steps", "questions")}
    for name, table in (("steps", "assistant_steps"), ("feedback", "assistant_feedback"), ("changes", "assistant_changes"),
                        ("plans", "assistant_long_plans"), ("long_steps", "assistant_long_steps"), ("questions", "assistant_long_questions")):
        for row in reader.rows(table):
            by_task[name][row["task_id"]].append(row)
    events: dict[str, set[str]] = defaultdict(set)
    for row in reader.rows("assistant_change_events"):
        events[row["change_id"]].add(_word(row["event"]) or UNRECOGNIZED)
    found = []
    for row in tasks:
        task_id = _word(row["id"])
        origin = projects.get(row["project_id"])
        segment = "sample" if origin in SAMPLE_ORIGINS else {"registered": "registered", "visitor": "visitor"}.get(users.get(row["user_id"]) or "", "registered")
        status = _word(row["status"])
        steps = sorted(by_task["steps"].get(row["id"], []), key=lambda step: step["ordinal"] or 0)
        checks = [_diagnostics(step["diagnostics_json"]) for step in steps]
        plan = (by_task["plans"].get(row["id"]) or [None])[0]
        long_steps = sorted(by_task["long_steps"].get(row["id"], []), key=lambda step: step["ordinal"] or 0)
        long_checks = [_diagnostics(step["diagnostics_json"]) for step in long_steps]
        cards = []
        for change in by_task["changes"].get(row["id"], []):
            seen = events.get(change["id"], set())
            cards.append({"kind": _word(change["kind"]), "proposed": 1,
                          "confirmed": int("applied" in seen or change["applied_at"] is not None or change["status"] in ("applied", "undone")),
                          "rejected": int(change["status"] == "rejected" or "rejected" in seen),
                          "undone": int("undone" in seen or change["status"] == "undone" or change["undone_at"] is not None),
                          "edited": int(bool(change["edited_by_author"]))})
        feedback = by_task["feedback"].get(row["id"], [])
        down = [item for item in feedback if item["verdict"] == "down"]
        found.append({
            "id": task_id, "kind": _word(row["kind"]), "segment": segment, "status": status, "status_group": STATUS_GROUPS.get(status or "", "unfinished"),
            "error_code": _word(row["error_code"]), "internal_error_type": _word(row["internal_error_type"]), "prompt_version": _word(row["prompt_version"]),
            "model": _word(row["model_label"]), "week": _week(row["created_at"]), "created_at": _stamp(row["created_at"]),
            "steps_used": _number(row["steps_used"]), "input_tokens": _number(row["input_tokens"]), "output_tokens": _number(row["output_tokens"]),
            "cost_cny": _number(row["cost_cny"]), "chars_charged": _number(row["chars_charged"]),
            "elapsed_seconds": _seconds(row["started_at"], row["completed_at"]),
            "feedback": {"up": sum(item["verdict"] == "up" for item in feedback), "down": len(down),
                         "reasons": Counter(reason for item in down for reason in _reasons(item["reasons_json"]))},
            "cards": cards,
            "steps": [{"ordinal": _number(step["ordinal"]), "kind": _word(step["kind"]), "tool": _word(step["tool_name"]), "result_count": _number(step["result_count"]),
                       "error_code": _word(step["error_code"]), "rule_codes": check["problem_codes"], "repairs": check["repairs"], "dropped": check["dropped"],
                       "elapsed_ms": _number(step["elapsed_ms"])} for step, check in zip(steps, checks)],
            "checks": checks + long_checks,
            "long": None if plan is None else {
                "plan_type": _word(plan["plan_type"], None), "origin": _word(plan["origin"], None), "range_edited": bool(plan["range_edited"]),
                "cap_edited": bool(plan["cap_edited"]), "stopped_by": _word(plan["stopped_by"], None), "chapters_planned": _number(plan["chapters_planned"]),
                "cap_cny": _number(plan["cap_cny"]), "questions": Counter(_word(q["kind"]) for q in by_task["questions"].get(row["id"], [])),
                "steps": [{"ordinal": _number(step["ordinal"]), "status": _word(step["status"]), "attempt": _number(step["attempt"]), "cost_cny": _number(step["cost_cny"]),
                           "chars_read": _number(step["chars_read"]), "seconds": _seconds(step["started_at"], step["finished_at"]),
                           "rule_codes": check["problem_codes"], "repairs": check["repairs"], "dropped": check["dropped"],
                           "dropped_codes": check["dropped_codes"], "apply_dropped_codes": check["apply_dropped_codes"]}
                          for step, check in zip(long_steps, long_checks)]}})
    return found


# --- summaries ---------------------------------------------------------------------------------------------------------------------
def _cards(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    by_kind: dict[str, Counter] = defaultdict(Counter)
    for task in tasks:
        for card in task["cards"]:
            by_kind[card["kind"] or UNRECOGNIZED].update({name: card[name] for name in CARD_COUNTS})

    def line(counts: Counter) -> dict[str, Any]:
        proposed, confirmed = counts["proposed"], counts["confirmed"]
        return {**{name: counts[name] for name in CARD_COUNTS}, "confirm_rate": _rate(confirmed, proposed), "reject_rate": _rate(counts["rejected"], proposed),
                "undo_rate": _rate(counts["undone"], confirmed)}
    total: Counter = Counter()
    for counts in by_kind.values():
        total.update(counts)
    return {"all": line(total), "by_kind": {kind: line(counts) for kind, counts in sorted(by_kind.items())}}


def _rules(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    failed, failed_tasks, dropped, apply_dropped = Counter(), Counter(), Counter(), Counter()
    repairs = repaired_tasks = 0
    for task in tasks:
        codes = [code for check in task["checks"] for code in check["problem_codes"]]
        failed.update(codes)
        failed_tasks.update(set(codes))
        for check in task["checks"]:
            dropped.update(check["dropped_codes"])
            apply_dropped.update(check["apply_dropped_codes"])
        if task["kind"] == "long":
            repairs += sum(check["repairs"] for check in task["checks"])
            repaired_tasks += any(check["repairs"] for check in task["checks"])
        else:  # a plain task has one repair at most; each of its rows says "1" once it is spent
            spent = max((check["repairs"] for check in task["checks"]), default=0)
            repairs += spent
            repaired_tasks += bool(spent)
    return {"failed_codes": dict(sorted(failed.items(), key=lambda item: (-item[1], item[0]))),
            "failed_code_tasks": dict(sorted(failed_tasks.items(), key=lambda item: (-item[1], item[0]))),
            "repairs": repairs, "repaired_tasks": repaired_tasks, "dropped": sum(dropped.values()),
            "dropped_codes": dict(sorted(dropped.items(), key=lambda item: (-item[1], item[0]))),
            "apply_dropped_codes": dict(sorted(apply_dropped.items(), key=lambda item: (-item[1], item[0])))}


def _long(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    longs = [task for task in tasks if task["long"] is not None]
    steps = [step for task in longs for step in task["long"]["steps"]]
    total = len(longs)
    asked = [task for task in longs if task["long"]["questions"]]
    stopped = Counter(task["long"]["stopped_by"] or "none" for task in longs)
    planned = [task for task in longs if task["long"]["plan_type"] not in (None, "none")]
    return {"tasks": total,
            "plan_types": dict(sorted(Counter(task["long"]["plan_type"] or "unknown" for task in longs).items())),
            "origin": dict(sorted(Counter(task["long"]["origin"] or "unknown" for task in longs).items())),
            "planned": len(planned), "range_edited": sum(task["long"]["range_edited"] for task in planned),
            "range_edited_rate": _rate(sum(task["long"]["range_edited"] for task in planned), len(planned)),
            "cap_edited": sum(task["long"]["cap_edited"] for task in planned), "cap_edited_rate": _rate(sum(task["long"]["cap_edited"] for task in planned), len(planned)),
            "asked": len(asked), "asked_rate": _rate(len(asked), total),
            "question_kinds": dict(sorted(sum((task["long"]["questions"] for task in longs), Counter()).items())),
            "stopped_by": dict(sorted(stopped.items())), "cost_cap_stop_rate": _rate(stopped["cost_cap"], total),
            "steps": {"total": len(steps), "with_repair": sum(bool(step["repairs"]) for step in steps), "repairs": sum(step["repairs"] for step in steps),
                      "with_dropped": sum(bool(step["dropped"]) for step in steps), "dropped": sum(step["dropped"] for step in steps),
                      "not_done": sum(step["status"] != "done" for step in steps)},
            "step_seconds": _spread([step["seconds"] for step in steps]), "chapters_planned": _spread([task["long"]["chapters_planned"] for task in planned])}


def summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """The numbers of one group of tasks. The cards come first: whether authors keep what the assistant proposes is the clearest signal."""
    total = len(tasks)
    status = Counter(task["status_group"] for task in tasks)
    up = sum(task["feedback"]["up"] for task in tasks)
    down = sum(task["feedback"]["down"] for task in tasks)
    reasons = sum((task["feedback"]["reasons"] for task in tasks), Counter())
    return {
        "cards": _cards(tasks),
        "tasks": total,
        "status": {name: status[name] for name in ("completed", "failed", "stopped", "unfinished")},
        "status_rate": {name: _rate(status[name], total) for name in ("completed", "failed", "stopped", "unfinished")},
        "error_codes": dict(sorted(Counter(task["error_code"] for task in tasks if task["error_code"]).items(), key=lambda item: (-item[1], item[0]))),
        "feedback": {"up": up, "down": down, "down_rate": _rate(down, up + down), "down_reasons": {reason: reasons[reason] for reason in FEEDBACK_REASONS}},
        "steps": _spread([task["steps_used"] for task in tasks]),
        "elapsed_seconds": _spread([task["elapsed_seconds"] for task in tasks]),
        "cost_cny": _spread([task["cost_cny"] for task in tasks]),
        "chars_charged": _spread([task["chars_charged"] for task in tasks]),
        "input_tokens": _spread([task["input_tokens"] for task in tasks]),
        "output_tokens": _spread([task["output_tokens"] for task in tasks]),
        "rules": _rules(tasks),
        "long": _long(tasks),
    }


def _traces(tasks: list[dict[str, Any]], limit: int) -> tuple[list[dict[str, Any]], int]:
    """One entry per task that got a thumbs-down, failed or had a card undone: the task's shape, never a word of it."""
    picked = []
    for task in tasks:
        why = [reason for reason, hit in (("thumbs_down", task["feedback"]["down"]), ("failed", task["status"] == "failed"),
                                          ("card_undone", any(card["undone"] for card in task["cards"]))) if hit]
        if not why:
            continue
        picked.append({"task_id": task["id"], "why": why, "segment": task["segment"], "kind": task["kind"], "prompt_version": task["prompt_version"],
                       "model": task["model"], "status": task["status"], "error_code": task["error_code"], "internal_error_type": task["internal_error_type"],
                       "created_at": task["created_at"],
                       "feedback": {"down": task["feedback"]["down"], "reasons": dict(sorted(task["feedback"]["reasons"].items()))},
                       "cost_cny": task["cost_cny"], "elapsed_seconds": task["elapsed_seconds"], "steps_used": task["steps_used"],
                       "cards": {name: sum(card[name] for card in task["cards"]) for name in CARD_COUNTS},
                       "steps": task["steps"],
                       **({"long": {key: (dict(value) if isinstance(value, Counter) else value) for key, value in task["long"].items()}}
                          if task["long"] is not None else {})})
    picked.sort(key=lambda item: item["created_at"] or "")
    return picked[-limit:] if limit else picked, max(0, len(picked) - limit) if limit else 0


def build(connection: sqlite3.Connection, since: str | None = None, until: str | None = None, trace_limit: int = 500) -> dict[str, Any]:
    reader = Reader(connection)
    tasks = load(reader, since, until)
    segments = {}
    for name in SEGMENTS:
        mine = [task for task in tasks if task["segment"] == name]
        groups = defaultdict(list)
        for task in mine:
            groups[(task["kind"] or UNRECOGNIZED, task["prompt_version"] or UNRECOGNIZED, task["week"])].append(task)
        segments[name] = {"overall": summarize(mine),
                          "groups": [{"kind": kind, "prompt_version": prompt, "week": week, **summarize(group)} for (kind, prompt, week), group in sorted(groups.items())]}
    traces, cut = _traces(tasks, trace_limit)
    return {"schema": SCHEMA,
            "meta": {"generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"), "since": since, "until": until, "tasks": len(tasks),
                     "tasks_by_segment": {name: sum(task["segment"] == name for task in tasks) for name in SEGMENTS},
                     "traces": len(traces), "traces_cut": cut, "missing_columns": reader.missing},
            "segments": segments, "traces": traces}


# --- markdown -----------------------------------------------------------------------------------------------------------------------
def _pct(value: float | None) -> str:
    return "–" if value is None else f"{value * 100:.1f}%"


def _num(value: float | int | None) -> str:
    return "–" if value is None else f"{value:g}"


def _spread_text(spread: dict[str, Any]) -> str:
    return f"{_num(spread['median'])} / {_num(spread['p90'])}"


def _table(head: list[str], rows: list[list[Any]]) -> list[str]:
    if not rows:
        return ["（无）", ""]
    return ["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *("| " + " | ".join(str(cell) for cell in row) + " |" for row in rows), ""]


def _counts_text(counts: dict[str, Any]) -> str:
    return "、".join(f"{key} {value}" for key, value in counts.items()) or "无"


def _summary_markdown(summary: dict[str, Any], heading: str) -> list[str]:
    lines = [heading, ""]
    cards = summary["cards"]
    lines += ["卡片（提出 / 确认 / 拒绝 / 撤销 / 作者改过）：", ""]
    lines += _table(["动作", "提出", "确认", "拒绝", "撤销", "改过", "确认率", "拒绝率", "撤销率（占确认）"],
                    [[kind, c["proposed"], c["confirmed"], c["rejected"], c["undone"], c["edited"], _pct(c["confirm_rate"]), _pct(c["reject_rate"]), _pct(c["undo_rate"])]
                     for kind, c in [("全部", cards["all"]), *cards["by_kind"].items()] if c["proposed"]])
    status, rate = summary["status"], summary["status_rate"]
    feedback = summary["feedback"]
    lines += [f"- 任务 {summary['tasks']}：完成 {status['completed']}（{_pct(rate['completed'])}），失败 {status['failed']}（{_pct(rate['failed'])}），"
              f"停下 {status['stopped']}（{_pct(rate['stopped'])}），没结束 {status['unfinished']}",
              f"- 失败码：{_counts_text(summary['error_codes'])}",
              f"- 点赞 {feedback['up']}，点踩 {feedback['down']}，差评率 {_pct(feedback['down_rate'])}；原因：{_counts_text(feedback['down_reasons'])}",
              f"- 中位数 / P90：步数 {_spread_text(summary['steps'])}；耗时（秒）{_spread_text(summary['elapsed_seconds'])}；费用（元）{_spread_text(summary['cost_cny'])}；"
              f"扣字数 {_spread_text(summary['chars_charged'])}"]
    rules = summary["rules"]
    lines += [f"- 核对没过的规则（次数）：{_counts_text(rules['failed_codes'])}",
              f"- 修过的任务 {rules['repaired_tasks']}，修的次数 {rules['repairs']}；修完仍丢掉的条目 {rules['dropped']}（{_counts_text(rules['dropped_codes'])}）；"
              f"交上去后被程序丢掉：{_counts_text(rules['apply_dropped_codes'])}"]
    long = summary["long"]
    if long["tasks"]:
        steps = long["steps"]
        lines += [f"- 长任务 {long['tasks']}：计划类型 {_counts_text(long['plan_types'])}；来源 {_counts_text(long['origin'])}；"
                  f"改范围 {_pct(long['range_edited_rate'])}，改上限 {_pct(long['cap_edited_rate'])}；中途提问 {_pct(long['asked_rate'])}（{_counts_text(long['question_kinds'])}）；"
                  f"结束原因 {_counts_text(long['stopped_by'])}；到费用上限停 {_pct(long['cost_cap_stop_rate'])}",
                  f"- 长任务每步：共 {steps['total']} 步，修过 {steps['with_repair']}（{steps['repairs']} 次），丢过条目 {steps['with_dropped']} 步（{steps['dropped']} 条）；"
                  f"每步耗时（秒）{_spread_text(long['step_seconds'])}"]
    return lines + [""]


def to_markdown(stats: dict[str, Any]) -> str:
    meta = stats["meta"]
    lines = [f"# 助手使用统计（{stats['schema']}）", "",
             f"生成于 {meta['generated_at']}；时间范围 {meta['since'] or '最早'} 至 {meta['until'] or '现在'}；任务 {meta['tasks']}"
             f"（注册作者 {meta['tasks_by_segment']['registered']}，访客 {meta['tasks_by_segment']['visitor']}，示例作品 {meta['tasks_by_segment']['sample']}，三类分开统计、不相加）。",
             "只有数字和编码，没有作者的任何文字。这些数字用来找最常见的毛病、和上一版比较，不是上线门槛。", ""]
    if meta["missing_columns"]:
        lines += ["缺少的列（数据库是较早的版本，按空值处理）：" + "；".join(f"{table}: {', '.join(columns)}" for table, columns in meta["missing_columns"].items()), ""]
    names = {"registered": "注册作者", "visitor": "访客", "sample": "示例作品"}
    for name in SEGMENTS:
        segment = stats["segments"][name]
        lines += _summary_markdown(segment["overall"], f"## {names[name]}：全时段")
        rows = [[g["kind"], g["prompt_version"], g["week"], g["tasks"], _pct(g["status_rate"]["completed"]), _pct(g["status_rate"]["failed"]),
                 _pct(g["feedback"]["down_rate"]), g["cards"]["all"]["proposed"], _pct(g["cards"]["all"]["confirm_rate"]), _pct(g["cards"]["all"]["reject_rate"]),
                 _pct(g["cards"]["all"]["undo_rate"]), _spread_text(g["cost_cny"]), sum(g["rules"]["failed_codes"].values())] for g in segment["groups"]]
        lines += [f"### {names[name]}：按种类 × 提示词版本 × 周", ""]
        lines += _table(["种类", "提示词版本", "周", "任务", "完成", "失败", "差评率", "卡片提出", "确认率", "拒绝率", "撤销率", "费用 中位/P90", "核对没过次数"], rows)
    lines += ["## 需要看的任务（点踩、失败、有卡片被撤销）", ""]
    if meta["traces_cut"]:
        lines += [f"（只列最近 {len(stats['traces'])} 条，更早的 {meta['traces_cut']} 条没有列；加 --trace-limit 0 可全部列出）", ""]
    for trace in stats["traces"]:
        card = trace["cards"]
        lines += [f"### {trace['task_id']} · {trace['kind']} · {trace['prompt_version']} · {trace['model']} · {'+'.join(trace['why'])}",
                  f"- {trace['segment']}；状态 {trace['status']}；失败码 {trace['error_code'] or '无'}；费用 {_num(trace['cost_cny'])}；耗时 {_num(trace['elapsed_seconds'])} 秒；"
                  f"点踩原因 {_counts_text(trace['feedback']['reasons'])}；卡片 提出{card['proposed']} 确认{card['confirmed']} 拒绝{card['rejected']} 撤销{card['undone']}", ""]
        if trace["steps"]:
            lines += _table(["#", "种类", "工具", "返回条数", "失败码", "规则编号", "耗时(ms)"],
                            [[s["ordinal"], s["kind"], s["tool"] or "–", _num(s["result_count"]), s["error_code"] or "–", ", ".join(s["rule_codes"]) or "–", _num(s["elapsed_ms"])]
                             for s in trace["steps"]])
        elif "long" in trace:
            long = trace["long"]
            lines += [f"- 长任务：计划 {long['plan_type'] or '?'}，来源 {long['origin'] or '?'}，改范围 {long['range_edited']}，改上限 {long['cap_edited']}，结束原因 {long['stopped_by'] or '无'}", ""]
            lines += _table(["步", "状态", "尝试", "费用", "秒", "规则编号", "修", "丢"],
                            [[s["ordinal"], s["status"], _num(s["attempt"]), _num(s["cost_cny"]), _num(s["seconds"]), ", ".join(s["rule_codes"]) or "–", s["repairs"], s["dropped"]]
                             for s in long["steps"]])
        else:
            lines += [""]
    if not stats["traces"]:
        lines += ["（无）", ""]
    return "\n".join(lines).rstrip() + "\n"


# --- command line --------------------------------------------------------------------------------------------------------------------
def _date(text: str) -> str:
    try:
        return date.fromisoformat(text).isoformat()
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a date like 2026-10-01") from None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.usage_stats", description="Read-only usage statistics for the assistant (numbers and codes only).")
    parser.add_argument("--db", required=True, help="path of demo.sqlite3 (opened read-only)")
    parser.add_argument("--since", type=_date, help="first day, YYYY-MM-DD (UTC, by when the task was created)")
    parser.add_argument("--until", type=_date, help="last day, YYYY-MM-DD, included")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--out", help="write here instead of standard output")
    parser.add_argument("--trace-limit", type=int, default=500, help="at most this many tasks in the trace list (the latest); 0 for all")
    args = parser.parse_args(argv)
    try:
        connection = open_readonly(args.db)
    except (FileNotFoundError, sqlite3.Error) as error:
        print(f"cannot open the database read-only: {error}", file=sys.stderr)
        return 2
    try:
        stats = build(connection, args.since, args.until, args.trace_limit)
    finally:
        connection.close()
    text = to_markdown(stats) if args.format == "markdown" else json.dumps(stats, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        Path(args.out).write_text(text, encoding="utf-8")
    else:
        if hasattr(sys.stdout, "reconfigure"):
            sys.stdout.reconfigure(encoding="utf-8")
        sys.stdout.write(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
