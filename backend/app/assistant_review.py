"""A second reader for the card (v2.1): one small call per fact or thread item, after the runs have agreed on the card.

The loop's own second look asks the model that proposed an item to look again, and the model, wanting the change, proposes it
once more (A2 sixth formal run: a fact already recorded under the full name restated under a nickname through change_fact;
a thread marked resolved on the author's word when the passage settles another thing). This call is shown only the item, the
author's sentence, what the materials hold and the passages, and asks one question; an item it answers against leaves the
card. When the call fails the item stays: the author still confirms every item.
"""
from __future__ import annotations

import concurrent.futures
import contextvars
import json
from typing import Any

REVIEW_TIMEOUT_SECONDS = 8
REVIEW_MAX_TOKENS = 200
FACTS_SHOWN = 8
PASSAGE_CHARS = 600

SYSTEM_PROMPT = "你替小说作者核对写作助手准备放进变更卡片的一条资料改动。只回答 JSON：{\"verdict\": \"...\", \"reason\": \"一句话\"}。"

FACT_QUESTION = """作者在写作助手里说：「{request}」
助手准备{doing}：{item}
资料里已经有这些事实：
{held}

资料里已有的事实，是不是已经说了助手这条要写的意思？
- 外号、别名和本名是同一个人；只是换了说法、写得更简略或更详细、多带了一个外号，都算已经说了。
- 只有资料里确实没有这个意思，或者原来那条说的已经和正文后来写的不一样、需要改成新的样子，才算没说。
verdict 填 said（已经说了）或 new（没说）。"""

THREAD_QUESTION = """作者在写作助手里说：「{request}」
助手准备把这条伏笔标成已回收：
标题：{title}
说明：{note}
依据的原文：
{passages}

这几段原文有没有把这条伏笔说的事收住（交代了结果、谜底或去向）？
- 作者的说法和原文不一样时，以原文为准。
- 原文收住的是另一件相近的东西或事，或者只交代了一部分、原文自己说还没弄清，都不算收住。
verdict 填 closed（收住了）、open（没收住）或 unclear（看不出来）。"""

FACT_KINDS = ("add_fact", "change_fact")
DROP = {"said": "recorded", "open": "not_closed"}  # the verdict that takes an item off the card, and why


def question(c: Any, ctx_memory: list[dict[str, Any]], request: str, item: Any) -> str | None:
    """The question for one card item (a row of assistant_changes), or None for a kind this review does not read."""
    after, before = json.loads(item["after_json"] or "{}"), json.loads(item["before_json"] or "null")
    if item["kind"] in FACT_KINDS:
        subject = "".join(str(after.get("subject") or "").split())
        names = _names(ctx_memory, subject)
        held = [fact for fact in ctx_memory if _squeeze(fact["subject"]) in names or any(name in _squeeze(fact["value"]) for name in names)]
        if not held:
            return None  # nothing it could already say
        lines = "\n".join(f"- {fact['subject']}·{fact['predicate']}：{fact['value']}" for fact in held[-FACTS_SHOWN:])
        doing = ("把这条事实\n  原来：" + str((before or {}).get("value") or "") + "\n  改成") if item["kind"] == "change_fact" else "在资料里加一条新事实"
        return FACT_QUESTION.format(request=request, doing=doing, item=f"{after.get('subject')}·{after.get('predicate')}：{after.get('value')}", held=lines)
    if item["kind"] == "resolve_thread":
        row = c.execute("SELECT title,description FROM v2_foreshadows WHERE id=?", (item["target_id"],)).fetchone()
        evidence = json.loads(item["evidence_json"] or "[]")
        passages = "\n".join(f"- 第 {e.get('chapter_number')} 章：{str(e.get('text') or '')[:PASSAGE_CHARS]}" for e in evidence if e.get("text"))
        if not row or not passages:
            return None
        return THREAD_QUESTION.format(request=request, title=row["title"], note=row["description"] or "（没有说明）", passages=passages)
    return None


def _squeeze(text: Any) -> str:
    return "".join(str(text or "").split())


def _names(memory: list[dict[str, Any]], subject: str) -> set[str]:
    """The subject and its other names: a fact of another subject whose value names it (the alias fact "朋友叫他杉栖" under
    柴闻序 makes 柴闻序 a name of 杉栖), and the names such a fact's value gives the subject."""
    names = {subject} if subject else set()
    for fact in memory:
        owner, value = _squeeze(fact["subject"]), _squeeze(fact["value"])
        if subject and subject in value and owner != subject:
            names.add(owner)
        if owner == subject:
            names.update(other for other in (_squeeze(f["subject"]) for f in memory) if other and other != subject and len(other) >= 2 and other in value)
    return {name for name in names if len(name) >= 2}


def parse(content: Any, kind: str) -> str | None:
    try:
        verdict = json.loads(content if isinstance(content, str) else "").get("verdict")
    except (ValueError, AttributeError):
        return None
    allowed = ("said", "new") if kind in FACT_KINDS else ("closed", "open", "unclear")
    return verdict if verdict in allowed else None


def call_model(provider: Any, question: str) -> Any:
    """One review call, back within the timeout (the transport is told the same limit)."""
    context = contextvars.copy_context()
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=1)
    messages = [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": question}]
    try:
        future = pool.submit(context.run, provider.route, messages, REVIEW_MAX_TOKENS, REVIEW_TIMEOUT_SECONDS, role="requests")
        return future.result(timeout=REVIEW_TIMEOUT_SECONDS)
    finally:
        pool.shutdown(wait=False)
