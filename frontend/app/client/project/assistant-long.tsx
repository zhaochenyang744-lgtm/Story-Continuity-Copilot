"use client";

// 长任务 (v2.1 B) as the conversation shows it. The author's sentence, then, by the task's status: a line saying the plan is being made; the
// plan card (steps, what it will read and cost, 开始 / 改范围 / 不做); a progress line with a thin bar while the steps are taken in the
// background; a question card (blue edge) when the task stops to ask; and at the end the report (sections, each item a point with its label in
// bold and one mark for its sources) with the changes it proposes under it, one card for each kind, a high-risk change on a card of its own.
// The cards are the change card of 改资料 (assistant-change.tsx) with another title; nothing here writes the materials itself: it asks the
// server, and shows the answer. The conversation (assistant.tsx) asks for a task that is being worked on every 2 seconds and hands the new view in.
import { type CSSProperties, Fragment, type ReactNode, useId, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { AssistantChangeKind, AssistantSentence, AssistantSource, AssistantTask, LongPlanBody, LongQuestion, LongStepSpec } from "../../model";
import { type CheckUsage, formatCount, isSampleWork } from "../ui";
import { SentenceText } from "./assistant-answer";
import { ChangeCard, type LongGroup } from "./assistant-change";
import { citedRefs, Fold, sentencesOf, SourceList, sourceKey } from "./assistant-parts";
import { ThreeSquares, useSecondsSince } from "./assistant-process";
import { type AskHandlers, Question } from "./assistant-task";

const root = (projectId: string, taskId: string) => `/projects/${projectId}/assistant/long-tasks/${taskId}`;

/** 第 3 章, or 第 1–5 章. */
export const chapterSpan = (low: number, high: number) => (low === high ? `第 ${low} 章` : `第 ${low}–${high} 章`);
/** What the server adds to a plan and to a trace's report items for this page (the shared model types do not carry them). */
type PlanOf = LongPlanBody & { abandon?: string[] };
type ReportItem = AssistantSentence & { handover?: boolean };

/** Said on every plan card: what a long task does not read. */
export const SCOPE_NOTE = "长任务只读已写章节的正文，不对照本章草稿和计划。";

/** 要理的：…  /  要清点的：…: what the plan is about, so the author sees it before starting. The target is the author's own wording of it. */
export function planSubject(plan: PlanOf): string | null {
  if (plan.type === "trace") return plan.target ? `要理的：${plan.target}` : null;
  if (plan.type === "thread_audit") return "要清点的：还没收的伏笔";
  return null;
}

/** The threads the author named as given up: a long task goes by the text only, and says how to have them marked. */
export function abandonNote(names: string[] | undefined): string | null {
  if (!names?.length) return null;
  return `你点名放弃的${names.map((name) => `「${name}」`).join("")}：长任务只按正文判断。要直接标放弃，发一句「把「${names[0]}」标为放弃」，我给你改资料的卡片。`;
}

const yuan = (value: number) => `¥${value.toFixed(2)}`;
/** A ceiling is a round figure: ¥2, ¥0.5. */
const ceiling = (value: number) => `¥${Number(value.toFixed(2))}`;
/** What has been spent, as the line shows it: under a fen is "不到 ¥0.01". */
const spent = (value: number) => (value > 0 && value < 0.005 ? "不到 ¥0.01" : yuan(value));
const minutes = (seconds: number) => (seconds < 60 ? "不到 1 分钟" : `${Math.round(seconds / 60)} 分钟`);

/** The group titles: what the cards of one kind do, in few words (the item's own tag keeps the longer name). */
const GROUP_TITLE: Record<AssistantChangeKind, string> = {
  resolve_thread: "标已回收", abandon_thread: "标放弃", add_fact: "加事实", change_fact: "改事实", add_thread: "加伏笔", edit_thread: "改伏笔说明",
};

/** What the author is told when a task ends in failure (never the code). Every failed task has its characters given back. */
const FAILED_TEXT: Record<string, string> = {
  assistant_long_plan_failed: "没能列出计划，任务停了，字数已退回。换个说法再试一次。",
  assistant_long_report_invalid: "这一步的结果核对不过，任务停了，字数已退回。",
  assistant_long_provider_failed: "模型这一步没有回应，任务停了，字数已退回。",
  assistant_long_record_broken: "这个任务留下的记录对不上了，任务停了，字数已退回。",
};
export const failedText = (code: string | null) => (code && FAILED_TEXT[code]) || "长任务出错了。";

/** Why a request on a long task was refused, in the author's words. */
function problemText(cause: unknown, planNeeds = 0): string {
  const failure = cause as ApiFailure;
  switch (failure?.code) {
    case "character_quota_exceeded": {
      const remaining = failure.details?.remaining;
      return `今天的可检查字数不够（要读约 ${formatCount(planNeeds)} 字，还剩 ${typeof remaining === "number" ? formatCount(remaining) : "不到这么多"} 字）。缩小章节范围再开始。`;
    }
    case "assistant_long_chapters_invalid": return "章节范围不对：起、止都要是已经写出的章节，起不能大于止。";
    case "assistant_long_plan_closed": return "这个计划已经开始或已经结束，不能再改了。";
    case "assistant_long_no_question": return "这个问题已经回答过了。";
    case "assistant_long_cap_invalid": return "新的上限要比现在的高。";
    case "assistant_long_answer_invalid": return "这个回答不在可选的里面，刷新页面后再选。";
    case "assistant_long_not_active": return "这个任务已经结束了。";
    case "assistant_long_confirm_alone": return "这一条风险高，要单独确认。";
    default: return labelError(cause);
  }
}

/** The stepper of the plan: what each step reads and looks for. The last is the report. */
function StepList({ steps, produces }: { steps: LongStepSpec[]; produces: string[] }) {
  const made = (Object.keys(GROUP_TITLE) as AssistantChangeKind[]).filter((kind) => produces.includes(kind)).map((kind) => GROUP_TITLE[kind]);
  return (
    <ol className="a-long-steps" aria-label="步骤">
      {steps.map((step, index) => (
        <li key={index} data-step={index + 1}>
          <span className="n" aria-hidden="true">{index + 1}</span>
          {step.kind === "read"
            ? <><span className="where">{chapterSpan(step.chapters[0], step.chapters[1])}</span><span className="what">{step.look_for}</span></>
            : <><span className="where">汇总</span><span className="what">{made.length ? `报告，和${made.join("、")}的卡片` : "报告"}</span></>}
        </li>
      ))}
    </ol>
  );
}

/** 约读 N 字 · 预计 ¥x · 上限 ¥y 调整, and (below it) what that is against the day's allowance. */
function PlanCard({ task, plan, handlers, usage, sample, maxChapter, usageChanged }: {
  task: AssistantTask; plan: PlanOf; handlers: AskHandlers; usage: CheckUsage | null; sample: boolean; maxChapter: number | null; usageChanged: () => void;
}) {
  const { projectId, replace } = handlers;
  const cap = task.plan?.cap_cny ?? 2;
  const [form, setForm] = useState(false);
  const [low, setLow] = useState(String(plan.chapters[0]));
  const [high, setHigh] = useState(String(plan.chapters[1]));
  const [limit, setLimit] = useState(String(cap));
  const [busy, setBusy] = useState<"start" | "stop" | "edit" | null>(null);
  const [problem, setProblem] = useState("");
  const form_id = useId();
  const remaining = usage?.account_type === "registered" ? usage.check_chars_remaining : null;
  const short = !sample && remaining !== null && remaining < plan.est_chars;
  const act = async (name: "start" | "stop", then?: () => void) => {
    setBusy(name); setProblem("");
    try {
      replace(await json<AssistantTask>(`${root(projectId, task.id)}/${name}`, "POST", {}));
      then?.();
    } catch (cause) {
      setProblem(problemText(cause, plan.est_chars));
      if (["assistant_long_plan_closed", "assistant_long_not_active"].includes((cause as ApiFailure).code)) {
        try { replace(await request<AssistantTask>(root(projectId, task.id))); } catch { /* the card stays as it is */ }
      }
    } finally { setBusy(null); }
  };
  const open = () => { setLow(String(plan.chapters[0])); setHigh(String(plan.chapters[1])); setLimit(String(cap)); setProblem(""); setForm(true); };
  const submit = async (event: { preventDefault: () => void }) => {
    event.preventDefault();
    const from = Number(low), to = Number(high), ceilingValue = Number(limit);
    if (!Number.isInteger(from) || !Number.isInteger(to) || from < 1 || from > to || (maxChapter !== null && to > maxChapter)) {
      setProblem(problemText({ code: "assistant_long_chapters_invalid" })); return;
    }
    if (!Number.isFinite(ceilingValue) || ceilingValue < 0.5 || ceilingValue > 5) { setProblem("费用上限在 ¥0.5 到 ¥5 之间。"); return; }
    setBusy("edit"); setProblem("");
    try {
      replace(await json<AssistantTask>(`${root(projectId, task.id)}/plan`, "POST", { chapters: [from, to], cap_cny: ceilingValue }));
      setForm(false);
    } catch (cause) { setProblem(problemText(cause, plan.est_chars)); } finally { setBusy(null); }
  };
  const locked = handlers.readOnly || Boolean(busy);
  return (
    <section className="a-card a-long-plan" aria-label="长任务计划" data-testid="long-plan">
      <div className="a-card-head"><strong>长任务 · 计划</strong><span>点「开始」才读正文</span></div>
      {planSubject(plan) && <p className="a-long-quota" data-testid="long-subject">{planSubject(plan)}</p>}
      <StepList steps={plan.steps} produces={plan.produces} />
      <div className="a-long-est" data-testid="long-estimate">
        <span>约读 {formatCount(plan.est_chars)} 字 · 预计 {yuan(plan.est_cny)} · 上限 {ceiling(cap)}</span>
        <button type="button" className="a-link" aria-expanded={form} aria-controls={form_id} disabled={locked} onClick={() => (form ? setForm(false) : open())}>调整</button>
      </div>
      <p className={`a-long-quota${short ? " warn" : ""}`} data-testid="long-quota">
        {sample ? "示例作品不计字数。"
          : remaining === null ? ""
            : short ? `要读约 ${formatCount(plan.est_chars)} 字，你今天只剩 ${formatCount(remaining)} 字，不够读完。缩小章节范围再开始。`
              : `要读约 ${formatCount(plan.est_chars)} 字，你今天还剩 ${formatCount(remaining)} 字。`}
      </p>
      <p className="a-long-quota" data-testid="long-scope">{SCOPE_NOTE}</p>
      {abandonNote(plan.abandon) && <p className="a-long-quota" data-testid="long-abandon">{abandonNote(plan.abandon)}</p>}
      {form && (
        <form id={form_id} className="a-long-form" onSubmit={submit} aria-label="调整计划">
          <div className="row">
            <label>从第 <input className="a-field" type="number" inputMode="numeric" min={1} max={maxChapter ?? undefined} step={1} value={low} onChange={(event) => setLow(event.target.value)} aria-label="起始章" /> 章</label>
            <label>到第 <input className="a-field" type="number" inputMode="numeric" min={1} max={maxChapter ?? undefined} step={1} value={high} onChange={(event) => setHigh(event.target.value)} aria-label="结束章" /> 章</label>
            <label>费用上限 ¥ <input className="a-field" type="number" inputMode="decimal" min={0.5} max={5} step={0.1} value={limit} onChange={(event) => setLimit(event.target.value)} aria-label="费用上限" /></label>
          </div>
          <p className="hint">费用上限在 ¥0.5 到 ¥5 之间{maxChapter !== null ? `；这部作品写到第 ${maxChapter} 章` : ""}。改完步骤会重新列出。</p>
          <div className="row end">
            <button type="button" className="a-link" onClick={() => { setForm(false); setProblem(""); }}>取消</button>
            <button type="submit" className="a-btn" disabled={locked}>保存修改</button>
          </div>
        </form>
      )}
      {problem && <p className="a-note a-long-problem" role="alert">{problem}</p>}
      <div className="a-card-foot">
        <button type="button" className="a-btn quiet" disabled={locked} onClick={() => void act("stop")}>不做</button>
        <button type="button" className="a-btn quiet" disabled={locked} aria-expanded={form} onClick={() => (form ? setForm(false) : open())}>改范围</button>
        <button type="button" className="a-btn" disabled={locked} title={handlers.readOnly ? "作品已归档，只能浏览。" : undefined} onClick={() => { void act("start", usageChanged); }}>开始</button>
      </div>
    </section>
  );
}

/** 第 k/n 步 · 已用 ¥x · 用时 m 分钟, a thin bar, and 停止 at the right end: the process line's own look. */
function Progress({ task, handlers, paused }: { task: AssistantTask; handlers: AskHandlers; paused: boolean }) {
  const { done, total, cost_cny } = task.progress ?? { done: 0, total: 0, cost_cny: 0 };
  const seconds = useSecondsSince(task.started_at ?? task.created_at, !paused) ?? 0;
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const step = total ? Math.min(done + 1, total) : 0;
  const stop = async () => {
    setBusy(true); setProblem("");
    try { handlers.replace(await json<AssistantTask>(`${root(handlers.projectId, task.id)}/stop`, "POST", {})); }
    catch (cause) { setProblem(problemText(cause)); } finally { setBusy(false); }
  };
  return (
    <div className="a-steps a-long-progress" data-testid="long-progress" role="status">
      <div className="a-process">
        <span className="a-fold static">
          {!paused && <ThreeSquares />}
          <span className="lead">{paused ? "长任务 · 等你回答" : "长任务"}</span>
          <span className="tally"> · 第 {step}/{total} 步 · 已用 {spent(cost_cny)} · 用时 {minutes(seconds)}</span>
        </span>
        <span className="a-process-end"><button type="button" className="a-link a-stop" disabled={busy} onClick={() => void stop()}>停止</button></span>
      </div>
      <div className="a-long-bar" role="progressbar" aria-label="长任务进度" aria-valuemin={0} aria-valuemax={total} aria-valuenow={done}>
        <i style={{ width: `${total ? (done / total) * 100 : 0}%` } as CSSProperties} />
      </div>
      {problem && <p className="a-note" role="alert">{problem}</p>}
    </div>
  );
}

/** The ceilings the author may raise it to: above the one it stopped at, never above ¥5. */
function raises(current: number): number[] {
  const options = new Set<number>();
  for (const step of [0.5, 1, 2, 3]) { const value = Math.round((current + step) * 100) / 100; if (value > current && value <= 5) options.add(value); }
  if (current < 5) options.add(5);
  return [...options].sort((a, b) => a - b);
}

/** The task has stopped to ask. A budget question: a higher ceiling to go on with, or stop here. A decision: one of the two ways, each with a line of the
    original, or 你定. The card has a blue edge. */
function AskCard({ task, question, handlers }: { task: AssistantTask; question: LongQuestion; handlers: AskHandlers }) {
  const cap = task.plan?.cap_cny ?? 2;
  const choices = raises(cap);
  const [pick, setPick] = useState(String(choices.find((value) => value >= cap + 1) ?? choices[choices.length - 1] ?? 5));
  const [busy, setBusy] = useState(false);
  const [problem, setProblem] = useState("");
  const answer = async (choice: string, extra: { cap_cny?: number } = {}) => {
    setBusy(true); setProblem("");
    try { handlers.replace(await json<AssistantTask>(`${root(handlers.projectId, task.id)}/answer`, "POST", { question_id: question.id, choice, ...extra })); }
    catch (cause) {
      setProblem(problemText(cause));
      if ((cause as ApiFailure).code === "assistant_long_no_question") { try { handlers.replace(await request<AssistantTask>(root(handlers.projectId, task.id))); } catch { /* as it is */ } }
    } finally { setBusy(false); }
  };
  const locked = busy || handlers.readOnly;
  return (
    <section className="a-card a-long-ask" aria-label="长任务提问" data-testid="long-question" data-kind={question.kind}>
      <p className="a-long-q">{question.text}</p>
      {question.kind === "budget" ? (
        <div className="a-long-choice row">
          {choices.length > 0 ? (
            <div className="a-long-raise">
              <button type="button" className="a-btn" disabled={locked} onClick={() => void answer("continue", { cap_cny: Number(pick) })}>提高上限到 {ceiling(Number(pick))} 接着做</button>
              <label className="a-long-cap">
                <span className="sr-only">新的上限</span>
                <select className="a-select" value={pick} disabled={locked} aria-label="新的上限" onChange={(event) => setPick(event.target.value)}>
                  {choices.map((value) => <option key={value} value={value}>{ceiling(value)}</option>)}
                </select>
              </label>
            </div>
          ) : <p className="hint">上限已经是最高的 ¥5，不能再提高。</p>}
          <button type="button" className="a-btn quiet" disabled={locked} onClick={() => void answer("stop")}>到此为止</button>
        </div>
      ) : (
        <div className="a-long-choice">
          {(question.options ?? []).map((option) => (
            <button key={option.key} type="button" className="a-long-option" data-key={option.key} disabled={locked} onClick={() => void answer(option.key)}>
              <span>{option.label}</span>
              {option.quote && <small>「{option.quote}」</small>}
            </button>
          ))}
          {question.choices.includes("both") && <button type="button" className="a-long-option plain" data-key="both" disabled={locked} onClick={() => void answer("both")}>两处都保留（是有意的）</button>}
          {question.choices.includes("you_decide") && <button type="button" className="a-long-option plain" data-key="you_decide" disabled={locked} onClick={() => void answer("you_decide")}>你定（按最新一章）</button>}
        </div>
      )}
      {problem && <p className="a-note a-long-problem" role="alert">{problem}</p>}
    </section>
  );
}

/** What the author answered to a question about two sayings that differ, in the report's words. "你定" goes by the later of the two (the program's
    pick, option b) and says so. */
export function decisionLine(item: LongQuestion): string {
  const choice = item.answer?.choice;
  if (choice === "both") return "中途问过一处：你说两处都保留。";
  const option = item.options?.find((entry) => entry.key === choice);
  if (option) return `中途问过一处：你选了「${option.label}」。`;
  const latest = item.options?.find((entry) => entry.key === "b")?.chapter;
  return `中途问过一处：你让助手定${latest ? `，按第 ${latest} 章为准` : ""}。`;
}

/** What was asked on the way and what the author said, one quiet line each. */
function Asked({ task }: { task: AssistantTask }) {
  const lines = (task.questions ?? []).filter((item) => item.answer).map((item) => {
    const choice = item.answer!.choice;
    if (item.kind === "budget") return { key: item.id, text: choice === "continue" ? `中途问过费用：提高上限到 ${ceiling(item.answer!.cap_cny ?? task.plan?.cap_cny ?? 0)} 接着做了。` : "中途问过费用：你选了到此为止。" };
    return { key: item.id, text: decisionLine(item) };
  });
  if (!lines.length) return null;
  return <>{lines.map((line) => <p key={line.key} className="a-limit" data-testid="long-asked">{line.text}</p>)}</>;
}

/** 做完了 · 2 分钟 · ¥0.07: the line between the work and its result (停下了 when it was stopped). */
function EndLine({ task }: { task: AssistantTask }) {
  const began = Date.parse(task.started_at ?? task.created_at);
  const ended = task.completed_at ? Date.parse(task.completed_at) : NaN;
  const took = Number.isFinite(began) && Number.isFinite(ended) ? Math.max(0, Math.round((ended - began) / 1000)) : null;
  return (
    <div className="a-turn-rule a-long-end" data-testid="long-end">
      <span>{task.status === "completed" ? "做完了" : "停下了"}{took !== null && ` · ${minutes(took)}`} · {spent(task.progress?.cost_cny ?? 0)}</span>
    </div>
  );
}

/** What a kind of long task reads besides the chapters: the threads it audits, the facts it tidies (a trace reads the chapters only). */
const ALSO_READ: Record<string, string> = { thread_audit: "、伏笔记录", tidy: "、资料里的事实" };

/** 查过……；没查：……, written by the program from the steps that were done: the chapters read, and what a long task never reads (the draft). */
function Cover({ task }: { task: AssistantTask }) {
  const read = (task.long_steps ?? []).filter((step) => step.status === "done" && step.spec.kind === "read").map((step) => (step.spec as Extract<LongStepSpec, { kind: "read" }>).chapters);
  const planned = task.plan?.approved?.chapters ?? null;
  if (!read.length && !planned) return null;
  const low = read.length ? Math.min(...read.map((span) => span[0])) : null;
  const high = read.length ? Math.max(...read.map((span) => span[1])) : null;
  const left = planned && (low === null || high === null || low > planned[0] || high < planned[1])
    ? (low === null || high === null ? chapterSpan(planned[0], planned[1]) : high < planned[1] ? chapterSpan(high + 1, planned[1]) : chapterSpan(planned[0], low - 1))
    : null;
  return (
    <p className="a-cover" data-testid="long-cover">
      {low !== null && high !== null && <>查过{chapterSpan(low, high)}正文{ALSO_READ[task.plan?.approved?.type ?? ""] ?? ""}；</>}
      <strong>没查：{left ? `${left}、` : ""}本章草稿</strong>。
    </p>
  );
}

/** An item as a point: the server writes 「名字：……」; the label is set in bold with a space after it, so the colon between them goes. */
const pointOf = (item: AssistantSentence): AssistantSentence =>
  item.label && item.text.startsWith(`${item.label}：`) ? { ...item, text: `${item.label}${item.text.slice(item.label.length + 1)}` } : item;

/** The sections of a trace's report in the order they are read (H06): where the two sayings differ, then what changed hands or place, then the rest
    folded. Null for a report that is not a trace's, or one made before the server marked the items (it keeps its own sections). */
export const HANDOVER_TITLE = "换手和挪地方";
export const OTHER_TITLE = "其他描写";
export function traceSections(sections: Record<string, AssistantSentence[]> | undefined): Record<string, AssistantSentence[]> | null {
  const states = (sections?.["状态变化"] ?? []) as ReportItem[];
  if (!states.length || states.every((item) => item.handover === undefined)) return null;
  const handover = states.filter((item) => item.handover);
  const other = states.filter((item) => !item.handover);
  const differ = sections?.["对不上的地方"] ?? [];
  return { ...(differ.length ? { 对不上的地方: differ } : {}), ...(handover.length ? { [HANDOVER_TITLE]: handover } : {}), ...(other.length ? { [OTHER_TITLE]: other } : {}) };
}

/** 最后写到：第 10 章，右手仍托着罗盘 — made from the last state of the report, whose text is 「第 N 章：「…」」. */
export function lastWritten(states: AssistantSentence[] | undefined): string | null {
  const last = states?.[states.length - 1];
  const found = last ? /^(第 \d+ 章)：「([\s\S]*)」$/.exec(last.text) : null;
  return found ? `最后写到：${found[1]}，${found[2]}` : null;
}

/** 其他描写 N 条 ›: the items that are neither a handover nor a change of place, closed until the author opens them. */
function Collapsed({ title, children, count }: { title: string; children: ReactNode; count: number }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  return (
    <section className="a-long-section" aria-label={title} data-testid="long-other">
      <div className="a-sources-wrap">
        <button type="button" className="a-sources-fold" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((value) => !value)}>{title} {count} 条<Fold open={open} /></button>
        {open && <div id={panel}>{children}</div>}
      </div>
    </section>
  );
}

/** The report: a line that counts what is below it (the program's, from the sections) — for a trace the last state it wrote instead — a bold title
    for each section, its items as points, then what was looked at, the sources folded, and the server's note (中途停下了 …). */
function Report({ task, handlers }: { task: AssistantTask; handlers: AskHandlers }) {
  const original = sentencesOf(task);
  const traced = task.plan?.approved?.type === "trace" ? traceSections(original?.sections) : null;
  // A trace's report is shown in the order it is read, so the numbers of the marks follow it.
  const shown = traced && original ? { ...task, answer: { ...original, sections: traced } } : task;
  const answer = sentencesOf(shown);
  const sections = Object.entries(answer?.sections ?? {}).filter(([, items]) => items.length > 0);
  const refs = citedRefs(shown);
  const total = sections.reduce((sum, [, items]) => sum + items.length, 0);
  let order = 0;
  const locate = (source: AssistantSource) => handlers.locate(source);
  const points = (items: AssistantSentence[]) => (
    <ul className="a-points">
      {items.map((item, index) => <li key={index}><SentenceText task={shown} sentence={pointOf(item)} bold order={order++} refs={refs} locate={locate} /></li>)}
    </ul>
  );
  const last = traced ? lastWritten(original?.sections?.["状态变化"]) : null;
  const asked = <Asked task={task} />;
  const askedHere = traced ? sections.findIndex(([title]) => title !== "对不上的地方") : -1;  // the questions come after where the sayings differ
  return (
    <div className="a-long-report" data-testid="long-report">
      <div className="a-answer">
        {total === 0
          ? <p className="a-lead" data-testid="not-found-line">没有找到问题问到的内容。</p>
          : last ? <p className="a-lead" data-testid="long-last">{last}</p>
            : <p className="a-lead" data-testid="long-count">共 {total} 条：{sections.map(([title, items]) => `${title} ${items.length} 条`).join("，")}。</p>}
        {sections.map(([title, items], index) => (
          <Fragment key={title}>
            {traced && index === askedHere && asked}
            {title === OTHER_TITLE && traced
              ? <Collapsed title={title} count={items.length}>{points(items)}</Collapsed>
              : <section className="a-long-section" aria-label={title}><h4>{title}</h4>{points(items)}</section>}
          </Fragment>
        ))}
        {traced && askedHere < 0 && asked}
        {answer?.note && <p className="a-answer-note" data-testid="long-note">{answer.note}</p>}
      </div>
      {!traced && asked}
      <Cover task={task} />
      <SourceList task={shown} locate={locate} skip={new Set((task.changes ?? []).flatMap((item) => item.evidence.map(sourceKey)))} />
    </div>
  );
}

/** The changes a report proposes, grouped by kind: a card for each kind, confirmed together (the ticked items are written, the rest turned down),
    and a card of its own for each high-risk item. Confirming one card leaves the others as they are. */
function Groups({ task, handlers }: { task: AssistantTask; handlers: AskHandlers }) {
  const { projectId } = handlers;
  const changes = task.changes ?? [];
  if (!changes.length) return null;
  const plain = changes.filter((item) => item.risk !== "high");
  const risky = changes.filter((item) => item.risk === "high");
  const refresh = () => request<AssistantTask>(root(projectId, task.id));
  const confirm = (accepted: string[], within: string[]) => json<AssistantTask>(`${root(projectId, task.id)}/changes/confirm`, "POST", { accepted, within });
  const reject = (within: string[]) => json<AssistantTask>(`${root(projectId, task.id)}/changes/reject`, "POST", { within });
  const kinds = [...new Set(plain.map((item) => item.kind))];
  const groups: (LongGroup & { key: string })[] = [
    ...kinds.map((kind) => ({ key: kind, title: GROUP_TITLE[kind], items: plain.filter((item) => item.kind === kind), alone: false, confirm, reject, refresh })),
    ...risky.map((item, index) => ({ key: item.id, title: GROUP_TITLE[item.kind], items: [item], alone: true, ...(risky.length > 1 ? { place: `${index + 1}/${risky.length}` } : {}), confirm, reject, refresh })),
  ];
  return (
    <div className="a-long-groups" data-testid="long-groups">
      {groups.map(({ key, ...group }) => (
        <ChangeCard key={key} task={task} projectId={projectId} readOnly={handlers.readOnly} replace={handlers.replace} merge={handlers.merge} locate={handlers.locate}
          written={handlers.written} goMaterials={handlers.goMaterials} group={group} />
      ))}
    </div>
  );
}

/** A long task, whatever stage it is at. */
export function LongView({ task, handlers, usage, project, maxChapter, usageChanged }: {
  task: AssistantTask; handlers: AskHandlers; usage: CheckUsage | null; project: { data_origin?: string }; maxChapter: number | null; usageChanged: () => void;
}) {
  const status = task.status;
  const proposed = task.plan?.proposed ?? null;
  const waiting = (task.questions ?? []).find((item) => !item.answer) ?? null;
  const ended = status === "completed" || status === "stopped";
  // A task stopped (or ended with a line) before it began has no steps and no report to speak of: its one line stands alone.
  const began = Boolean(task.plan?.approved);
  return (
    <div className="a-group a-long" data-task={task.id} data-status={status} data-kind="long">
      <Question task={task} handlers={handlers} />
      <article className="a-task" aria-live="off" data-answer={task.id}>
        {!task.plan && status !== "failed" && <div className="a-process" role="status"><span className="a-fold static"><ThreeSquares /> 长任务 · 正在读取…</span></div>}
        {status === "planning" && task.plan && <div className="a-process" role="status" data-testid="long-planning"><span className="a-fold static"><ThreeSquares /> 长任务 · 正在列计划…</span></div>}
        {status === "awaiting_plan" && proposed && (
          <PlanCard key={`${proposed.chapters.join("-")}:${task.plan?.cap_cny}`} task={task} plan={proposed} handlers={handlers} usage={usage} sample={isSampleWork(project)} maxChapter={maxChapter} usageChanged={usageChanged} />
        )}
        {(status === "long_queued" || status === "long_running" || status === "waiting_author") && task.progress && <Progress task={task} handlers={handlers} paused={status === "waiting_author"} />}
        {status === "waiting_author" && waiting && <AskCard key={waiting.id} task={task} question={waiting} handlers={handlers} />}
        {status === "failed" && <p className="a-block a-refused a-long-failed" role="status" data-testid="long-failed">{failedText(task.error_code)}</p>}
        {ended && began && <EndLine task={task} />}
        {ended && began && <Report task={task} handlers={handlers} />}
        {ended && !began && <p className="a-note" data-testid="long-note">{sentencesOf(task)?.note ?? "没有开始就停下了。"}</p>}
        {ended && began && <Groups task={task} handlers={handlers} />}
      </article>
    </div>
  );
}
