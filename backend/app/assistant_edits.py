"""Validated edit proposals and a shared, metered screened passage check."""
from __future__ import annotations

import re
import threading
import uuid
from typing import Any

from .assistant_store import utcnow
from .assistant_tools import INTERNAL_ID, Outcome, ToolContext, ToolError, _draft, _text_arg
from .engine import ContinuityEngine
from .provider import ProviderDispatchDenied


def check_after_text(after: Any) -> None:
    if not isinstance(after, str) or not after.strip():
        raise ToolError("proposal_after_missing")
    if INTERNAL_ID.search(after):  # the sentence goes into the author's chapter
        raise ToolError("proposal_text_internal_id")


def check_after(kind: str, before: str, after: Any) -> None:
    """The rules a new sentence obeys, whether the model or the author wrote it; raises `ToolError(code)` when it breaks one."""
    check_after_text(after)
    if kind == "edit_this":
        if before == after or len(after) > len(before) * 2 + 60:
            raise ToolError("proposal_after_invalid")
        # Adopting checks that the saved draft no longer holds `before`; an `after` that keeps
        # the whole original sentence (words only added around it) could never be adopted.
        if before in after:
            raise ToolError("proposal_after_contains_before")
    elif len(after) > 120:
        raise ToolError("proposal_after_invalid")


def propose(ctx: ToolContext, args: dict) -> Outcome:
    if ctx.scope.get("issue_nature") == "state_change":
        raise ToolError("no_edit_for_state_change")
    kind = args.get("kind")
    if kind not in ("edit_this", "add_setup", "intentional"):
        raise ToolError("invalid_arguments")
    rationale = _text_arg(args, "rationale", 120)
    before, after = args.get("before"), args.get("after")
    n = ctx.scope["chapter_number"]
    chapter = None
    if kind == "intentional":
        if before is not None or after is not None or args.get("chapter_number") is not None:
            raise ToolError("invalid_arguments")
        before = after = ""
    else:
        if before is not None and not isinstance(before, str):
            raise ToolError("invalid_arguments")
        check_after_text(after)
        if kind == "edit_this":
            # The model often names the chapter being written; only another chapter is wrong here.
            if args.get("chapter_number") not in (None, n):
                raise ToolError("edit_this_is_for_the_current_draft")
            body = _draft(ctx)["body"]
            if not before or not before.strip():
                raise ToolError("proposal_before_not_unique")
            # Count overlapping matches as well (str.count alone would miss them).
            positions = [m.start() for m in re.finditer("(?=" + re.escape(before) + ")", body)]
            if len(positions) != 1:
                raise ToolError("proposal_before_not_unique")
            sentence = ctx.scope["issue_sentence"]
            sentence_positions = [m.start() for m in re.finditer("(?=" + re.escape(sentence) + ")", body)] if sentence else []
            start = positions[0]
            if not any(start < pos + len(sentence) and pos < start + len(before) for pos in sentence_positions):
                raise ToolError("proposal_issue_not_overlapped")
            check_after("edit_this", before, after)
            chapter = n
        else:
            chapter = args.get("chapter_number")
            if isinstance(chapter, bool) or not isinstance(chapter, int) or not 1 <= chapter < n:
                raise ToolError("proposal_chapter_invalid")
            written = ctx.chapters().get(chapter)
            if written is None:
                raise ToolError("proposal_chapter_invalid")
            check_after("add_setup", before or "", after)
            if before and before not in written["body"]:
                raise ToolError("proposal_anchor_not_found")
            before = before or ""
    with ctx.db.connection() as c:
        c.execute("BEGIN IMMEDIATE")
        held, last = c.execute("SELECT COUNT(*),COALESCE(MAX(ordinal),0) FROM assistant_proposals WHERE task_id=?", (ctx.task["id"],)).fetchone()
        ordinal = last + 1
        if held >= 3:
            raise ToolError("proposal_limit_exceeded")
        c.execute("INSERT INTO assistant_proposals(id,task_id,ordinal,kind,target,chapter_number,before,after,rationale,"
                  "draft_id,draft_revision,status,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                  (f"proposal-{uuid.uuid4()}", ctx.task["id"], ordinal, kind, "chapter" if kind == "add_setup" else "draft",
                   chapter, before, after, rationale, ctx.task["draft_id"], ctx.task["draft_revision"], "proposed", utcnow()))
    return Outcome({"proposal": f"P{ordinal}"}, args, 1)


def validate_proposals(ctx: ToolContext) -> list[str]:
    """Problems that stop the answer being accepted. A proposal whose reason carries an internal id is withdrawn here
    (so the author never sees it) and the model is asked to propose it again, once, through the usual repair."""
    with ctx.db.connection() as c:
        proposals = c.execute("SELECT id,ordinal,kind,rationale FROM assistant_proposals WHERE task_id=? ORDER BY ordinal", (ctx.task["id"],)).fetchall()
        leaking = [row for row in proposals if INTERNAL_ID.search(row["rationale"] or "")]
        for row in leaking:
            c.execute("DELETE FROM assistant_proposals WHERE id=?", (row["id"],))
    problems = [f"改法 P{row['ordinal']} 的理由里出现了内部标识，已撤回；请去掉标识后重新提出这条改法。" for row in leaking]
    kinds = [row["kind"] for row in proposals if row not in leaking]
    if ctx.scope.get("issue_nature") == "state_change":
        return problems + (["状态变化不能有改法，请解释并引导作者去资料页确认。"] if kinds else [])
    if len(set(kinds)) < 2 or "edit_this" not in kinds:
        # Say what is there and what is missing: the bare rule was not enough to correct two edit_this proposals.
        have = "、".join(f"{kind} ×{kinds.count(kind)}" for kind in dict.fromkeys(kinds)) or "还没有"
        missing = ("一个 edit_this（改本章这一句）" if "edit_this" not in kinds else
                   "一个不同 kind 的改法：最简单的是 intentional（只填 rationale，说明这样写也可能是作者有意的），"
                   "或 add_setup（chapter_number 填本章之前的章，after 是要补的话）")
        problems.append(f"至少提出两种不同 kind 的改法，其中一个必须是 edit_this。现在已有：{have}；还缺{missing}。"
                        "先调用 propose_edit，再用 answer 收尾。")
    return problems


class MeteredProvider:
    """Account for each review response, including repairs, before allowing another dispatch."""
    continuity_batch_concurrency = 1

    def __init__(self, provider: Any, cost_of: Any, ceiling: float, on_result: Any = None):
        self.provider, self.cost_of, self.ceiling, self.on_result = provider, cost_of, ceiling, on_result
        self.input_tokens = self.output_tokens = 0
        self.cost = 0.0
        self.lock = threading.Lock()

    def __getattr__(self, name):
        return getattr(self.provider, name)

    def evaluate(self, request):
        with self.lock:
            if self.cost >= self.ceiling:
                raise ProviderDispatchDenied("assistant_budget_exhausted")
            result = self.provider.evaluate(request)
            self.input_tokens += result.input_tokens or 0
            self.output_tokens += result.output_tokens or 0
            self.cost += self.cost_of(result)
            if self.on_result:
                self.on_result(result)
            if self.cost > self.ceiling:
                raise ProviderDispatchDenied("assistant_budget_exhausted")
            return result


def passage_input(ctx: ToolContext, text: str) -> dict:
    from .v2_database import split_continuity_claims
    n = ctx.scope.get("chapter_number") if ctx.scope.get("draft_readable") else ctx.max_chapter + 1
    n = n or ctx.max_chapter + 1
    sources = [s for s in ctx.spans() if s["chapter_number"] < n]
    with ctx.db.connection() as c:
        memory = [dict(row) for row in ctx.db._memory_as_of_chapter(c, ctx.project_id, n)]
    claims = [{"id": f"claim-assistant-{i}", "text": sentence, "chapter_number": n, "context": "assistant-passage"}
              for i, sentence in enumerate(split_continuity_claims(text), 1)]
    return {"pipeline": "screened", "claims": claims, "memory": memory, "sources": sources,
            "contexts": {"assistant-passage": text}, "draft": {"id": ctx.task["draft_id"] or ctx.task["id"],
            "revision": ctx.task["draft_revision"] or ctx.task["source_revision"], "body": text}}


def check(ctx: ToolContext, text: str, meter: MeteredProvider) -> dict:
    data = passage_input(ctx, text)
    result = ContinuityEngine(meter).execute(data)
    if meter.cost > meter.ceiling:
        raise ToolError("assistant_budget_exhausted")
    if result.get("status") != "completed" or result.get("undecided_claims"):
        raise ToolError(result.get("error_code") or "passage_check_incomplete")
    sources = {s["id"]: s for s in data["sources"]}
    claims = {c["id"]: c["text"] for c in data["claims"]}
    issues = []
    for issue in result.get("issues", []):
        evidence = []
        for e in issue.get("evidence", []):
            source = sources.get(e.get("source_span_id") or e.get("span_id"))
            if source is None:
                continue
            excerpt = e.get("excerpt") or e.get("prompt_excerpt") or source["body"]
            at = source["body"].find(excerpt)
            ref = ctx.registry.register("passage", source["id"], source["chapter_number"], ctx.title(source["chapter_number"]),
                                        at if at >= 0 else None, at + len(excerpt) if at >= 0 else None, excerpt)
            evidence.append({"ref": ref, "chapter": source["chapter_number"], "chapter_title": ctx.title(source["chapter_number"]), "text": excerpt})
        issues.append({"sentence": claims.get(issue.get("claim_span_id"), ""), "category": issue.get("category"),
                       "nature": issue.get("nature"), "severity": issue.get("severity"), "explanation": issue.get("explanation") or "",
                       "evidence": evidence})
    return {"status": "issues" if issues else "clean", "issues": issues}


def run_check(ctx: ToolContext, args: dict) -> Outcome:
    if ctx.scope.get("visitor"):
        raise ToolError("assistant_check_visitor_forbidden")
    if isinstance(args.get("text"), str) and len(args["text"]) > 600:
        raise ToolError("invalid_arguments")
    text = _text_arg(args, "text", 600)
    if ctx.check is None:
        raise ToolError("tool_not_available")
    result = ctx.check(text)
    high = ctx.scope["chapter_number"] - 1 if ctx.scope.get("draft_readable") and ctx.scope.get("chapter_number") else ctx.max_chapter
    return Outcome({"content_kind": "manuscript_text", **result}, {"text": text, "chapter_to": high}, len(result["issues"]))
