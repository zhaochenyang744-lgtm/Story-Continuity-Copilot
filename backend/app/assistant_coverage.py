"""Does the note of an answer only claim what the assistant really looked at? (v1.8.0, prompt assistant-p5)

The note tells the author where the assistant looked ("查过第5章与第7章正文"). The model writes it, so the server checks it
against the step records before the answer is accepted: every chapter a clause says was looked at must have been read by a
`read_chapter` call or lie inside a `search_text` range, and a clause about the draft or its check result needs the matching
tool to have run. A clause that says something was *not* looked at is left alone, and so is a clause about facts, plans,
foreshadowing or check results that does not speak of the chapter text.
"""
from __future__ import annotations

import json
import re
from typing import Any

MAX_RANGE = 1000  # a range written as 第1至99999章 is not expanded further than this

_NUM = r"(?:[0-9]+|[〇零一二两三四五六七八九十百]+)"
_SEP = r"(?:至|到|[-–—~～])"
_SEG = rf"{_NUM}(?:\s*章)?(?:\s*{_SEP}\s*(?:第\s*)?{_NUM})?"
_CHAPTERS = re.compile(rf"第\s*({_SEG}(?:\s*(?:、|和|与|及|,)\s*(?:第\s*)?{_SEG})*)\s*章")
_SEGMENT = re.compile(rf"({_NUM})(?:\s*章)?(?:\s*{_SEP}\s*(?:第\s*)?({_NUM}))?")
_DRAFT_CHAPTER = re.compile(rf"第\s*{_SEG}\s*章\s*(?:的)?\s*草稿")
# Clauses end at sentence punctuation, brackets and the list comma (but not the comma inside 第5、7章).
_CLAUSES = re.compile(r"[，,；;。.!?！？\n（()）]+|(?<![0-9〇零一二两三四五六七八九十百])、|、(?![0-9〇零一二两三四五六七八九十百])")
_NEGATIONS = ("没", "未", "不曾", "无法", "不能", "不到")
_NOT_TEXT_TOPICS = ("事实", "计划", "伏笔", "检查结果")
_TEXT_WORDS = ("正文", "原文")

_DIGITS = {"〇": 0, "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100}


def chapter_number(text: str) -> int | None:
    """An Arabic or Chinese numeral ("12", "三十", "七十一", "一百零五") as an integer, or None when it is not one."""
    text = text.strip()
    if text.isascii():
        return int(text) if text.isdigit() else None
    total = digit = 0
    seen_unit = False
    for char in text:
        if char in _DIGITS:
            digit = _DIGITS[char]
        elif char in _UNITS:
            total += (digit or 1) * _UNITS[char]
            digit = 0
            seen_unit = True
        else:
            return None
    total += digit
    return total if total > 0 or seen_unit else None


def mentioned_chapters(clause: str) -> list[tuple[int, int]]:
    """The chapters a clause names, as (first, last) pairs: 第5章 → (5, 5); 第三至六章 → (3, 6); 第5、7章 → (5, 5), (7, 7)."""
    found: list[tuple[int, int]] = []
    for match in _CHAPTERS.finditer(clause):
        for segment in _SEGMENT.finditer(match.group(1)):
            low = chapter_number(segment.group(1))
            high = chapter_number(segment.group(2)) if segment.group(2) else low
            if low is None or high is None:
                continue
            found.append((min(low, high), min(max(low, high), min(low, high) + MAX_RANGE)))
    return found


def _clauses(note: str) -> list[str]:
    return [part.strip() for part in _CLAUSES.split(note) if part and part.strip()]


def _looked_at(steps: list[dict[str, Any]]) -> tuple[set[int], list[tuple[int, int]], set[str]]:
    """From the step records: chapters read, chapter ranges searched, and the names of the other tools that succeeded."""
    read: set[int] = set()
    searched: list[tuple[int, int]] = []
    used: set[str] = set()
    for step in steps:
        if step.get("kind") != "tool" or step.get("error_code"):
            continue
        args = json.loads(step.get("args_json") or "{}")
        name = step.get("tool_name")
        if name == "read_chapter" and isinstance(args.get("chapter_number"), int):
            read.add(args["chapter_number"])
        elif name == "search_text" and isinstance(args.get("chapter_from"), int) and isinstance(args.get("chapter_to"), int):
            searched.append((args["chapter_from"], args["chapter_to"]))
        elif name:
            used.add(name)
    return read, searched, used


def _clause_missing(clause: str, looked: tuple[set[int], list[tuple[int, int]], set[str]]) -> list[str]:
    """What one clause claims to have looked at that the steps do not show (empty when the clause is fine)."""
    read, searched, used = looked
    if any(word in clause for word in _NEGATIONS):
        return []
    missing: list[str] = []
    if "草稿" in clause:
        if "检查" in clause:
            if "get_issues" not in used:
                missing.append("本章草稿的检查结果没有读过")
        elif "read_draft" not in used:
            missing.append("本章草稿没有读过")
    text_clause = any(word in clause for word in _TEXT_WORDS)
    if text_clause or not any(word in clause for word in _NOT_TEXT_TOPICS):
        unread = sorted({chapter for low, high in mentioned_chapters(_DRAFT_CHAPTER.sub("", clause))
                         for chapter in range(low, high + 1)
                         if chapter not in read and not any(lo <= chapter <= hi for lo, hi in searched)})
        if unread:
            missing.append("第 " + "、".join(str(chapter) for chapter in unread[:10]) + " 章的正文没有读过，也不在搜索范围内")
    return missing


def note_problems(note: str | None, steps: list[dict[str, Any]]) -> list[str]:
    """What in the note says something was looked at that the steps do not show. Empty when the note is fine (or absent)."""
    if not note:
        return []
    looked = _looked_at(steps)
    problems: list[str] = []
    for clause in _clauses(note):
        missing = _clause_missing(clause, looked)
        if missing:
            problems.append(f"note 里的「{clause[:40]}」和实际不符：{'；'.join(missing)}。请去掉这一处说法，或者先补查再写")
    return problems


# What the text says ("第26章写二十七岁", "正文未写明寄件人是谁", "另：两处不一致"): the process line drops a clause that has it.
_STORY_SENTENCE = re.compile(r"写(?:着|了|到|明|的是)?\s*「|写\s*[0-9〇零一二两三四五六七八九十百]|都写|只写了|写的是|写作|不一致|说法(?:不同|相反)"
                             r"|写法不同|互相矛盾|前后矛盾|(?:没有|没|未)写(?!到)[^；;。，,]{3,}|里没有[^；;。]{1,20}的(?:设定|条目|记载|描写)"
                             r"|夹(?:有|着)|备注要求|留言")


# A note tells the author where the assistant looked, what it did not look at and that it found nothing; it never says what
# the text says. Up to prompt assistant-p25 a blacklist cut the sentences that retold the text; the fourth A1c formal run
# showed it cannot be kept complete ("第14章写已拆固定……", "两次移交分别在……", "正文已写明……" all passed), so since assistant-p26
# only the kinds of clause below are kept and everything else goes.
_FILLER = r"(?:我|已经?|另外|另|还|再|又|也|都|只|仅|并且?)*"
_LOOKED = re.compile(rf"^\s*{_FILLER}(?:查过|查了|读过|读了|搜过|搜了|看过|看了|核对过|核对了|检查过|检查了)")
_NOT_LOOKED = re.compile(rf"^\s*{_FILLER}(?:未查|没查|没有查|还没查|还没有查|来不及查|没来得及查|未来得及查)")
_NOT_FOUND = re.compile(rf"^\s*{_FILLER}(?:没有找到|没找到|未找到|(?:没有|没|未)发现[^，,。；;]{{0,15}}?(?:矛盾|冲突|问题|不一致))")
_NOT_FOUND_TAIL = re.compile(r"(?:没有找到|没找到|未找到)[^，,。；;]{0,12}$")
_NO_RESULT = re.compile(r"^[^，,。；;]{0,40}?(?:(?:里|中)?(?:也|均|都)?(?:没有|无)相关(?:内容|记录|描写|结果|段落|说法)|未涉及(?:此事|该事)?|(?:均|都)?无结果)$")
_CANNOT_EDIT = re.compile(rf"^\s*{_FILLER}(?:(?:不能|无法)直接(?:改|修改|覆盖|保存|写入|替换)|(?:只能|仅能)提出改法)")
# "并列分句": a clause that carries on the list of places before it ("，以及第31章草稿和最近一次检查结果（无问题）").
_CONJUNCTION = re.compile(r"^\s*(?:以及|还有|及|和|与)\s*")
_PLACE_END = re.compile(r"(?:正文|原文|草稿|计划|伏笔|事实|记录|设定|检查结果|段落|条目|结果|章|部分|开头|结尾)$")
# A word that makes a clause say something about the text instead of naming a place.
_ASSERTS = re.compile(r"写|说|提到|称为|已经|已(?![埋知])|仍|没|未|不|分别|因为|所以|但|而|却|改|建议|冲突|矛盾|一致|恢复|移交|交给|发现|表示|显示"
                      r"|标为|标记|认为|应当|应该|需要|让|把|被|将")
_SAFE_PAREN = re.compile(r"^(?:无问题(?:条目)?|无记录|无结果|无冲突|无相关内容|没有问题|未发现问题"
                         r"|[第\s0-9〇零一二两三四五六七八九十百至到\-–—~～、，,和与及章]+|搜[^，,。；;]{1,40})$")
_ALIAS_PAREN = re.compile(r"^[\u4e00-\u9fffA-Za-z·]{1,8}(?:[、/][\u4e00-\u9fffA-Za-z·]{1,8})*$")
# "资料里有给助手的指令，我没有照做": the one fixed line about an instruction in the material (`without_false_injection` decides on it).
_INJECTION_PAIR = re.compile(r"(?:^|[，,])\s*([^，,。；;！!？?]{0,20}(?:指令|指示|命令)[^，,。；;！!？?]{0,12}[，,]\s*(?:我)?"
                             r"(?:没有?照做|未照做|不照做|没有?执行|未执行|没有?理会|忽略)[^，,。；;！!？?]{0,8})\s*$")
UNCHECKED_LINE = "改后的句子没有检查过。"
# The one line the assistant writes when it is asked for a plot, a new person or an ending: only this wording is kept.
NO_PLOT_CORE = "情节怎么写由你决定，我只能指出前文已有的线索"
NO_PLOT_LINE = NO_PLOT_CORE + "。"
_OPENERS, _CLOSERS = "（([「『“", "）)]」』”"


def _split_clauses(text: str, separators: str = "，,") -> list[str]:
    """The text cut at the separators that are not inside brackets or quotes."""
    clauses, depth, start = [], 0, 0
    for index, char in enumerate(text):
        if char in _OPENERS:
            depth += 1
        elif char in _CLOSERS:
            depth = max(depth - 1, 0)
        elif char in separators and depth == 0:
            clauses.append(text[start:index])
            start = index + 1
    clauses.append(text[start:])
    return [clause for clause in clauses if clause.strip()]


def _plain(clause: str) -> str:
    """The clause with every bracket that is not a chapter list, a name, a search or a plain "no problem" taken out."""
    def keep(match: re.Match) -> str:
        inner = match.group(1).strip()
        return match.group(0) if _SAFE_PAREN.fullmatch(inner) or (_ALIAS_PAREN.fullmatch(inner) and not _ASSERTS.search(inner)) else ""
    return re.sub(r"[（(]([^（）()]*)[）)]", keep, clause).strip()


def _place_item(clause: str) -> bool:
    bare = _CONJUNCTION.sub("", clause)
    return not _ASSERTS.search(re.sub(r"[（(][^（）()]*[）)]", "", bare)) and bool(_CONJUNCTION.match(clause) or _PLACE_END.search(re.sub(r"[（(][^（）()]*[）)]", "", bare).strip()))


def _looked_items(clause: str) -> str:
    """A "查过……" clause lists its places with "、"; the list stops at the first item that says something about the text or
    carries a rewrite ("……的事实、改法：把「母亲」改为「朋友」")."""
    items = _split_clauses(clause, "、")
    for index, item in enumerate(items):
        if index and _ASSERTS.search(re.sub(r"[（(][^（）()]*[）)]", "", item)):
            return "、".join(items[:index])
    return clause


def _note_sentence(body: str) -> tuple[str, bool]:
    """One sentence of a note cut down to the clauses that name places looked at or not looked at, nothing found, or that the
    assistant cannot edit. Returns the kept text and whether it holds the "cannot edit" statement."""
    pair = _INJECTION_PAIR.search(body)
    head, tail = (body[:pair.start()], pair.group(1).strip()) if pair else (body, "")
    kept: list[str] = []
    refusal = listing = False
    for clause in _split_clauses(head):
        text = _plain(clause)
        if not text:
            listing = False
            continue
        if _LOOKED.match(text):
            kept.append(_looked_items(text))
            listing = True
        elif _NOT_LOOKED.match(text) or _NOT_FOUND.match(text) or _NO_RESULT.match(text):
            kept.append(text)
            listing = False
        elif _NOT_FOUND_TAIL.search(text) and not _STORY_SENTENCE.search(text):
            kept.append(text)
            listing = False
        elif _CANNOT_EDIT.match(text):
            kept.append(text)
            refusal, listing = True, False
        elif listing and _place_item(text):
            kept.append(text)
        else:
            listing = False
    if tail:
        kept.append(tail)
    return "，".join(kept), refusal


def looked_places(note: str | None) -> str | None:
    """The note reduced to the whitelist: where the assistant looked, what it did not look at, that it found nothing, that it
    cannot edit (one sentence), its one line about an instruction in the material and, for a question that asks for a plot, the
    one line that the author decides it (`NO_PLOT_LINE`, kept only in that wording). Anything else, a retelling of the
    text, a rewrite suggestion, a remark on the check, any other talk of plot, goes. The sentences end in "。"; None when
    nothing is left."""
    if not note:
        return note
    sentences, refusal_taken, plot_taken = [], False, False
    for piece in re.split(r"(?<=[；;。！!？?])", note):
        body = re.sub(r"[；;。！!？?\s]+$", "", piece)
        plot = NO_PLOT_CORE in body
        text, refusal = _note_sentence(body.replace(NO_PLOT_CORE, "").strip("，, "))
        if refusal and refusal_taken:
            continue  # the refusal is said once
        refusal_taken = refusal_taken or refusal
        if text:
            sentences.append(text + "。")
        if plot and not plot_taken:
            sentences.append(NO_PLOT_LINE)
            plot_taken = True
    return "".join(sentences) or None


def with_unchecked_line(note: str | None) -> str:
    """The note with the fixed line saying the rewritten sentence was not checked at the end."""
    return f"{note.strip()}{UNCHECKED_LINE}" if note and note.strip() else UNCHECKED_LINE


# A process line says what the assistant does next. A clause that names such an action stays (and the clause that carries it on:
# "，以及拆除固定物后能否握稳"); the clause that retells the text ("第6章写的是砾穹舱", "温宥真在第19章获得……") goes.
_STEP_VERB = re.compile(r"查|搜|读|核对|确认|看|检查|找|检索|浏览|验证|核实|复核|比较|比对|对比|对照|翻|提出")
_STEP_LEAD = re.compile(r"^\s*(?:(?:我|再|先|并且?|还|也|然后|接着|之后|随后|同时|继续|去|会|将|要|需要)\s*)*")
_CARRIES_ON = re.compile(r"^\s*(?:以及|还有|并且|同时|及|和|与)")
STEP_VERB_WITHIN = 10  # after "我先" / "再去" the action may follow a few words ("我先在正文里搜索……"); without one it opens the clause


def _is_step(clause: str) -> bool:
    lead = _STEP_LEAD.match(clause)
    verb = _STEP_VERB.search(clause, lead.end())
    if verb is None or _STORY_SENTENCE.search(clause):
        return False
    # "霍予笺在第23章看到了新的接线" has a verb but is a scene: with no "我先" / "再去" in front, the clause has to open with the action.
    return verb.start() - lead.end() <= (STEP_VERB_WITHIN if lead.end() else 0)


def next_steps_only(line: str) -> str:
    """The process line without the clauses that are not an action to come (or that tell what the text says). A line that is
    all action is returned as it is; when nothing is left, an empty string."""
    pieces = re.split(r"([，,；;。])", line)
    kept, dropped, acting = [], False, False
    for index in range(0, len(pieces), 2):
        clause = pieces[index]
        if not clause.strip():
            continue
        acting = _is_step(clause) or (acting and _CARRIES_ON.match(clause) is not None and not _STORY_SENTENCE.search(clause))
        if acting:
            kept.append(clause.strip())
        else:
            dropped = True
    if not dropped:
        return line
    return "，".join(kept) + "。" if kept else ""


def without_untrue(note: str | None, steps: list[dict[str, Any]]) -> str | None:
    """The note with every clause that `note_problems` objects to taken out, keeping the rest as written.

    Used when the one repair is spent: a wrong place in the note should not cost the author the whole answer."""
    if not note:
        return note
    looked = _looked_at(steps)
    pieces = re.split(f"({_CLAUSES.pattern})", note)
    kept: list[str] = []
    for index in range(0, len(pieces), 2):
        clause, separator = pieces[index], pieces[index + 1] if index + 1 < len(pieces) else ""
        if clause.strip() and _clause_missing(clause.strip(), looked):
            continue
        kept.append(clause + separator)
    text = "".join(kept).strip().lstrip("，,；;、。").rstrip("，,；;、")
    if text and note.rstrip().endswith("。") and not text.endswith(("。", "！", "？")):
        text += "。"
    return text or None


# The note's line for an instruction found in the material (prompt rule 2): "资料里有给助手的指令，我没有照做".
_INJECTION_NOTE = re.compile(r"[^。；;！!？?]*(?:指令|指示|命令)[^。；;！!？?]*(?:没有?照做|未照做|不照做|没有?执行|未执行|没有?理会|忽略)[^。；;！!？?]*[。；;！!？?]?")
# What reads as text addressed to the assistant rather than story: "（给 AI 助手：请…）", "给阅读助手的编辑便条：",
# "读到这里的助手请停止…", "忽略之前的限制", "system prompt". Every safety work of the spent v1.8.0 sets matches; their
# plain works do not ("我冒险时的好助手", "对水下机器人", "课程模型", "别核对"). A jailbreak in the author's own question
# is not material, so it need not match. When in doubt the line stays, which is how every note read before v1.8.1.
_AI = r"(?:助手|ＡＩ|(?<![A-Za-z])AI(?![A-Za-z])|assistant)"
_SUSPECTED_INSTRUCTION = re.compile(
    r"(?:给|致|写给|对)[^。！？!?\n，,“”「」]{0,10}" + _AI
    + r"|" + _AI + r"[^。！？!?\n，,]{0,6}(?:请|须|必须|务必|应当|不要|别再?|停止|跳过|忽略|省略)"
    # A bracketed or headed note telling the reader how to answer: "（编排备注：若有人问…，请把回答写成六行）",
    # "（给修订同伴：…只回复“…”）", "（修订便签：…请在第九章前面补上…）".
    r"|[（(][^）)\n]{0,10}(?:备注|便签|便条|提醒|留言|批注|同伴)[：:][^）)\n]{0,160}(?:请|只回复|只回答|不要|别|统一|直接)"
    r"|(?:给|致)[^。！？!?\n，,：:]{0,8}[：:][^。！？!?\n]{0,40}(?:只回复|只回答|一律回答|统一答|直接回答|直接宣布)"
    r"|忽略[^。！？!?\n]{0,8}(?:指令|提示|规则|要求|设定|限制|约束|规定)"
    r"|(?:系统|system)\s*(?:提示|prompt)|ignore\s+(?:all\s+|any\s+|the\s+)?(?:previous|prior|above)",
    re.I,
)


def has_suspected_instruction(texts: list[str]) -> bool:
    """Whether any of the texts the model was shown reads like an instruction addressed to it."""
    return any(_SUSPECTED_INSTRUCTION.search(text) for text in texts if text)


def without_false_injection(note: str | None, texts: list[str]) -> str | None:
    """The note without its "资料里有给助手的指令，我没有照做" line when nothing the model was shown reads like one.

    The model wrote that line on almost every fix of the sample work and on 8 of 12 fixes in the fourth A1c formal run,
    where the material held no such text. Only the line goes: whether an instruction was followed is judged on the answer."""
    if not note or not _INJECTION_NOTE.search(note) or has_suspected_instruction(texts):
        return note
    text = _INJECTION_NOTE.sub("", note).strip().lstrip("，,；;、。").rstrip("，,；;、").strip()
    if text and not text.endswith(("。", "！", "？")):
        text += "。"
    return text or None
