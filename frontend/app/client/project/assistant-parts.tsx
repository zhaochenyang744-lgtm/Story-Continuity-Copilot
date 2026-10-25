"use client";

// What every kind of assistant task shares: how a refusal or a failure is worded, the numbered sources under an answer, and
// the 查过 / 没查 line. The views for each kind (ask, 写前回顾, 帮我改这一处) are built from these.
import { useId, useState } from "react";
import { labelError, type ApiFailure } from "../../api";
import type { AssistantAnswer, AssistantSource, AssistantTask, RecapAnswer } from "../../model";
import { bareChapterTitle, type CheckUsage, chapterHeading, formatCount } from "../ui";

/** The phrase the 查过 / 没查 line carries when a task was cut short; it is said as a line of its own above the answer. */
export const LIMIT_MARK = "步数或预算已到";
export const LIMIT_LINE = "查到上限了，先按已找到的回答。";
export const OUT_OF_SCOPE_TEXT = "我只能查这部作品里写过的内容，可以换个关于作品的问题。";
export const SOURCE_KIND: Record<string, string> = { fact: "已确认事实", plan: "计划", foreshadow: "伏笔记录", draft: "本章草稿", issue: "检查结果" };
export const VISITOR_USED_UP = "访客可以在示例作品上问 3 次，今天已经用完。注册后可以在自己的作品上用助手。";
export const RUNNING_NOW = "上一个问题还在查";
export const FOLLOW_UP_LIMIT_TEXT = "这一串已经追问两次了，可以问一个新问题";
/** What a task costs before anything is added: 500 characters (the server reads the figure from the usage). */
export const TASK_CHARS = 500;

export const active = (task: AssistantTask) => task.status === "queued" || task.status === "running";
export const isRecap = (answer: AssistantTask["answer"]): answer is RecapAnswer => Boolean(answer && "kind" in answer && answer.kind === "recap");
/** The answer of an ask or a fix_issue task (a recap's answer has another shape). */
export const sentencesOf = (task: AssistantTask): AssistantAnswer | null => (task.answer && !isRecap(task.answer) ? task.answer : null);

export const whereLabel = (source: AssistantSource) =>
  source.chapter_number != null ? chapterHeading(source.chapter_number, source.chapter_title ?? "") : SOURCE_KIND[source.kind] ?? "资料";
/** The label on a citation card: a fact says it is a summary (it is not the author's own words), a passage names its chapter. */
export const cardLabel = (source: AssistantSource) =>
  source.kind === "fact" && source.chapter_number != null ? `事实摘要 · 第 ${source.chapter_number} 章` : whereLabel(source);
/** Where 去原文 takes the author, and what to look for there: the passage itself, or for a fact the passage it was taken from.
    Null when the source has no chapter. A fact without a source passage still opens its chapter, with nothing to find. */
export function locateTarget(source: AssistantSource): { chapter: number; text: string } | null {
  if (source.kind === "fact") {
    const chapter = source.anchor?.chapter_number ?? source.chapter_number;
    return chapter == null ? null : { chapter, text: source.anchor?.text ?? "" };
  }
  return source.chapter_number == null ? null : { chapter: source.chapter_number, text: source.text };
}
/** "第 9 章 仓道的高台", the way a screen reader gets it. */
export const spokenWhere = (source: AssistantSource) =>
  source.chapter_number != null ? `第 ${source.chapter_number} 章${bareChapterTitle(source.chapter_title ?? "") ? ` ${bareChapterTitle(source.chapter_title ?? "")}` : ""}` : SOURCE_KIND[source.kind] ?? "资料";
/** Why no new question can be asked at all (the day's allowance is used up), or empty: said inside the box, on the buttons that would ask, and in the bar over picked words. */
export function quotaReason(usage: CheckUsage | null, sample: boolean): string {
  if (usage?.account_type === "registered" && !sample && usage.check_chars_remaining < (usage.assistant_task_chars ?? TASK_CHARS)) {
    return `${refusalText({ code: "character_quota_exceeded", details: { remaining: usage.check_chars_remaining } }, false)}用掉的额度 24 小时后陆续返还。`;
  }
  if (usage?.account_type === "visitor" && usage.assistant_tasks_remaining !== undefined && usage.assistant_tasks_remaining <= 0) return VISITOR_USED_UP;
  return "";
}

/** The time on the line between two turns: 今天 21:40, or 10月25日 21:40 for another day. */
export function turnTime(iso: string, now = new Date()): string {
  const at = new Date(iso);
  if (Number.isNaN(at.getTime())) return "";
  const clock = at.toLocaleTimeString("zh-CN", { hour: "2-digit", minute: "2-digit", hour12: false });
  const same = at.getFullYear() === now.getFullYear() && at.getMonth() === now.getMonth() && at.getDate() === now.getDate();
  return same ? `今天 ${clock}` : `${at.getMonth() + 1}月${at.getDate()}日 ${clock}`;
}

/** The refs a task's answer cites, in the order they first appear: their position is the number shown. `sources` holds every
    passage the task turned up, cited or not, so a source only counts here when the answer's sentences name it and it is marked cited. */
export function citedRefs(task: AssistantTask): string[] {
  const order: string[] = [];
  for (const sentence of sentencesOf(task)?.sentences ?? []) for (const ref of sentence.refs) if (!order.includes(ref) && task.sources[ref] && task.sources[ref].cited !== false) order.push(ref);
  return order;
}
/** What a screen reader hears when a task has finished. */
export function spokenResult(task: AssistantTask): string {
  if (isRecap(task.answer)) return `写前回顾完成了：第 ${task.answer.chapter_number} 章`;
  const answer = sentencesOf(task);
  const first = answer?.sentences[0]?.text ?? answer?.note ?? "";
  return task.kind === "fix_issue" ? `助手给出了改法：${first}` : task.kind === "change" ? `助手给出了资料改动，等你确认：${first}` : `助手回答了：${first}`;
}

/** Why a new task was refused, in the author's words (never the code). */
export function refusalText(cause: unknown, visitor: boolean, kind: AssistantTask["kind"] = "ask"): string {
  const code = (cause as ApiFailure)?.code;
  switch (code) {
    case "character_quota_exceeded": {
      const remaining = ((cause as ApiFailure).details ?? {}).remaining;
      return `今天的可检查字数不够这次${kind === "ask" ? "提问" : "任务"}（约 500 字，还剩 ${typeof remaining === "number" ? formatCount(remaining) : "不到 500"} 字）。`;
    }
    case "workflow_quota_exceeded":
      return visitor ? VISITOR_USED_UP : labelError(cause);
    case "assistant_visitor_sample_only": return "访客只能在示例作品上使用助手。";
    case "assistant_check_visitor_forbidden": return "访客不能用「查前文矛盾」，注册账号后可以用。";
    case "assistant_task_running": return "上一个问题还在查，等它结束再问。";
    case "assistant_project_budget_exceeded": return "这部作品今天的助手用量已到上限，明天再试。";
    case "assistant_follow_up_limit": return `${FOLLOW_UP_LIMIT_TEXT}。`;
    case "assistant_reroute_invalid": return "这个任务已经结束了，不能再改成别的用法；可以在它的下面重新选一次。";
    case "assistant_follow_up_invalid": return "接着问的那个问题已经不在了，去掉“接着问”再发一次。";
    case "assistant_context_invalid": return kind === "ask" ? "带入的人物已经不在了，去掉它再发一次。" : "没有找到当前这一章的草稿，刷新页面后再试。";
    case "recap_nothing_before": return "第一章前面没有内容可以回顾。";
    case "assistant_issue_not_current": return "这条检查结果已经过时了。再检查一次后，再让助手给改法。";
    case "assistant_kind_unavailable": return "这个功能需要更新后的页面才能使用。";
    case "assistant_not_available": return "助手暂时还没有对你的账号开放。";
    case "assistant_route_input_required": return "先写下想问或想改的话，再发送。";
    case "invalid_request": return "这次的内容不完整，没有开始，也没有计字数。刷新页面后再试一次。";
    case "assistant_regenerate_invalid": return "这个回答不能重新回答了，换个问法再问一次。";
    case "assistant_edit_invalid": return "原来的问题已经不在了，直接重新提问吧。";
    case "assistant_task_not_completed": return "这个回答还没有结束。";
    case "provider_unavailable": return "助手暂时不可用，这次没有开始，也没有计字数。稍后再试。";
    default: return labelError(cause);
  }
}

const NOUN: Record<AssistantTask["kind"], string> = { ask: "回答", recap: "回顾", fix_issue: "回答和改法", change: "回答和改动" };

/** What went wrong with a task that ended without an answer; "没有计字数" only when nothing was charged. */
export function failureText(task: AssistantTask, visitor: boolean): { text: string; retry: boolean } {
  const free = !visitor && task.usage.chars_charged === 0 ? "，没有计字数" : "";
  switch (task.error_code) {
    case "provider_unavailable":
    case "provider_timeout":
    case "provider_failure":
      return { text: `模型这次没有回应${free}。可以重试；正文和资料都没有改动。`, retry: true };
    case "citation_validation_failed":
      return { text: `${NOUN[task.kind]}里有引用对不上原文，已丢弃${free}。请重试${task.kind === "ask" ? "或换个问法" : ""}。`, retry: true };
    case "assistant_budget_exhausted":
    case "assistant_no_answer":
    case "assistant_protocol_error":
      return { text: `这次没能给出带出处的${NOUN[task.kind]}${free}。${task.kind === "ask" ? "可以缩小范围再问一次。" : "可以稍后再试。"}`, retry: false };
    default:
      return { text: `这次没有完成${free}。可以重试。`, retry: true };
  }
}

/** The one line a source takes in the list under an answer (and in a change card's 依据): 第 3 章 · 章名. */
export const sourceRow = (source: AssistantSource) => (source.kind === "fact" && source.chapter_number != null ? cardLabel(source) : whereLabel(source));

/** A source in the list: its one line, which opens to the original words (in the serif face) and the way to them. */
export function SourceItem({ id, n, source, locate }: { id: string; n: number; source: AssistantSource; locate: (source: AssistantSource) => void }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <li id={id} tabIndex={-1} className="a-source">
      <b aria-hidden="true">{n}</b>
      <span>
        <button type="button" className="a-where" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((value) => !value)}>
          {sourceRow(source)}<Fold open={open} />
        </button>
        {open && (
          <span id={panel} className="a-source-body">
            <span className="a-text q">{source.text}</span>
            {source.chapter_number != null && <button type="button" className="a-go" onClick={() => locate(source)}>去原文 →</button>}
          </span>
        )}
      </span>
    </li>
  );
}

/** The small › that turns to point down when its line is open. */
export function Fold({ open }: { open: boolean }) {
  return <svg className={`a-fold-mark${open ? " open" : ""}`} width="8" height="8" viewBox="0 0 8 8" aria-hidden="true"><path d="M2 1l3 3-3 3" fill="none" stroke="currentColor" strokeWidth="1.2" /></svg>;
}

/** What a source is, for telling two of them apart: the same chapter and words. */
export const sourceKey = (source: { chapter_number?: number | null; text: string }) => `${source.chapter_number ?? ""}:${source.text}`;

/** 出处 N 处 ›: folded to one line; opened, one line for each source. `skip` leaves out sources that something else on the screen already shows
    (a change card's 依据); the numbers stay the ones the marks in the answer carry. */
export function SourceList({ task, locate, skip }: { task: AssistantTask; locate: (source: AssistantSource) => void; skip?: Set<string> }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const shown = citedRefs(task).map((ref, index) => ({ ref, n: index + 1 })).filter(({ ref }) => !skip?.has(sourceKey(task.sources[ref])));
  if (!shown.length) return null;
  return (
    <div className="a-sources-wrap">
      <button type="button" className="a-sources-fold" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((value) => !value)}>出处 {shown.length} 处<Fold open={open} /></button>
      {open && (
        <ol id={panel} className="a-sources" aria-label="出处">
          {shown.map(({ ref, n }) => <SourceItem key={ref} id={`a-src-${task.id}-${n}`} n={n} source={task.sources[ref]} locate={locate} />)}
        </ol>
      )}
    </div>
  );
}

/** 查过……；没查：……: the program's one note on what the task looked at and what it did not. When nothing was found, only what it did not look at. */
export function CoverLine({ task, onlyMissed = false }: { task: AssistantTask; onlyMissed?: boolean }) {
  // 「步数或预算已到」 is said once, above the answer, as 「查到上限了」; it is not repeated here.
  const left = (task.coverage?.not_checked ?? []).filter((item) => !item.includes(LIMIT_MARK));
  const done = onlyMissed ? [] : task.coverage?.checked ?? [];
  if (!done.length && !left.length) return null;
  return (
    <p className="a-cover">
      {done.length > 0 && <>查过{done.join("、")}</>}
      {done.length > 0 && left.length > 0 && "；"}
      {left.length > 0 && <strong>没查：{left.join("、")}</strong>}
      。
    </p>
  );
}

/** A task that was stopped: it says what the stop cost (the words spent up to then are not given back). */
export function StoppedNote({ task, visitor }: { task: AssistantTask; visitor: boolean }) {
  if (task.status !== "cancelled") return null;
  const spent = !visitor && task.usage.chars_charged > 0;
  return <p className="a-note">{spent ? `已停止，计 ${formatCount(task.usage.chars_charged)} 字` : "已停止，没有计字数"}</p>;
}

/** Said above the answer when the task ended because the steps or the budget ran out, not because it was finished. */
export function LimitLine({ task }: { task: AssistantTask }) {
  if (!(task.coverage?.not_checked ?? []).some((item) => item.includes(LIMIT_MARK))) return null;
  return <p className="a-limit">{LIMIT_LINE}</p>;
}
