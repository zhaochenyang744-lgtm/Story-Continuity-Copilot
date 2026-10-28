"use client";

// What the assistant did, told to the author: the lines the model wrote beside its work, the actions grouped by kind
// ("查了 2 条事实：苏岑、黄铜罗盘", "搜了 2 处正文"), failed steps on their own line, and the step in progress with a three-square mark and
// its seconds. Once the task is over the whole thing folds into one line, 「查了 N 处 · M 秒 ›」. The wording of an action is made here,
// from the tool and the number of calls; nothing the model wrote reaches the author except its one line before each round of work.
import { type ReactNode, useEffect, useId, useState } from "react";
import type { AssistantSource, AssistantStep, AssistantTask } from "../../model";
import { active, Fold, hitLimit, notChecked, sentencesOf, whereLabel } from "./assistant-parts";
import { splitNote } from "./assistant-text";

/** At most this many characters of a passage are shown on either side of the word that turned it up (or at the start, when no word is known). */
// About a line and a half in the 340px right column (07g found 40/80 ran to three lines there).
const AROUND = 18;
const OPENING = 42;
/** A passage a search turned up, cut to a line or two: the words around the one searched for, or its opening. */
export function snippetOf(text: string, word: string): string {
  const flat = text.replace(/\s+/g, " ").trim();
  const at = word ? flat.indexOf(word) : -1;
  if (at < 0) return flat.length > OPENING ? `${flat.slice(0, OPENING)}…` : flat;
  const from = Math.max(0, at - AROUND);
  const to = Math.min(flat.length, at + word.length + AROUND);
  return `${from > 0 ? "…" : ""}${flat.slice(from, to)}${to < flat.length ? "…" : ""}`;
}

/** The text the server gives a step that failed for no particular reason. */
const GENERIC_FAILURE = "这一步没成功";
/** A row of the process: a line of narration, a group of actions, a failed step, a re-written answer. */
type Row =
  | { type: "say"; key: string; text: string }
  | { type: "group"; key: string; tool: string; text: string; count: string; refs: string[]; /** For a search: the words searched for, by the passage they turned up. */ words: Record<string, string> }
  | { type: "fail"; key: string; text: string }
  | { type: "repair"; key: string; text: string };

const chapterNumbers = (steps: AssistantStep[]) => steps.map((step) => /第\s*(\d+)\s*章/.exec(step.summary)?.[1]).filter((value): value is string => Boolean(value));
const afterColon = (summary: string) => summary.split(/[：:]/).slice(1).join("：").replace(/」?\s*·.*$/, "").replace(/^「|」$/g, "").trim();

/** One line for a group of successful steps of one tool. */
function groupText(tool: string, steps: AssistantStep[]): string {
  const n = steps.length;
  switch (tool) {
    case "lookup_facts": {
      const names = [...new Set(steps.map((step) => afterColon(step.summary)).filter(Boolean))];
      return `查了 ${n} 条事实${names.length ? `：${names.join("、")}` : ""}`;
    }
    case "search_text": return `搜了 ${n} 处正文`;
    case "read_chapter": {
      const numbers = [...new Set(chapterNumbers(steps))];
      return numbers.length ? `读了第 ${numbers.join("、")} 章` : "读了章节";
    }
    case "read_draft": return "读了本章草稿";
    case "get_plans": return "看了计划和伏笔";
    case "get_issues": return "读了检查结果";
    case "propose_edit": return `提出了 ${n} 个改法`;
    case "check_passage": return "定点检查了这一段";
    default: return steps[0]?.summary ?? "查了一步";
  }
}
/** The action a failed step was trying, as a name. */
function failedAction(step: AssistantStep): string {
  switch (step.tool) {
    case "lookup_facts": return "查事实";
    case "search_text": return "搜正文";
    case "propose_edit": return "提出改法";
    case "get_issues": return "读检查结果";
    case "get_plans": return "看计划和伏笔";
    case "read_draft": return "读本章草稿";
    case "check_passage": return "定点检查这一段";
    case "read_chapter": { const number = chapterNumbers([step])[0]; return number ? `读第 ${number} 章` : "读章节"; }
    default: return step.summary.replace(/[：:].*$/, "");
  }
}

/** The task's steps as rows, in the order things happened. A task from before the groups existed gets groups by round and tool. */
export function processRows(steps: AssistantStep[]): Row[] {
  const rows: Row[] = [];
  const groups = new Map<string, { steps: AssistantStep[]; at: number }>();
  steps.forEach((step, index) => {
    if (step.kind === "say") { rows.push({ type: "say", key: `s${index}`, text: step.summary }); return; }
    if (step.kind === "repair") { rows.push({ type: "repair", key: `r${index}`, text: step.error_text || "引用没对上，重新整理回答" }); return; }
    if (step.kind !== "tool") return;
    if (step.error_code) {
      const reason = step.error_text || GENERIC_FAILURE;
      rows.push({ type: "fail", key: `f${index}`, text: reason === GENERIC_FAILURE ? `${failedAction(step)}没成功` : `${failedAction(step)}没通过：${reason}` });
      return;
    }
    const id = step.group ?? `g${step.round}-${step.tool}`;
    const known = groups.get(id);
    if (known) { known.steps.push(step); return; }
    groups.set(id, { steps: [step], at: rows.length });
    rows.push({ type: "group", key: id, tool: step.tool ?? "", text: "", count: "", refs: [], words: {} });
  });
  for (const [id, { steps: members, at }] of groups) {
    const tool = members[0].tool ?? "";
    const refs = [...new Set(members.flatMap((step) => step.refs ?? []))];
    const found = members.reduce((sum, step) => sum + (step.result_count ?? 0), 0);
    const words: Record<string, string> = {};
    if (tool === "search_text") for (const step of members) for (const ref of step.refs ?? []) words[ref] ??= /「([^」]+)」/.exec(step.summary)?.[1] ?? "";
    rows[at] = { type: "group", key: id, tool, text: groupText(tool, members), count: tool === "search_text" ? `${found} 段` : "", refs, words };
  }
  return rows;
}

/** How many places the task looked at: its actions that went through. */
export const lookedAt = (steps: AssistantStep[]) => steps.filter((step) => step.kind === "tool" && !step.error_code).length;

/** What is being done right now, in the present tense. */
export function nowText(task: AssistantTask): string {
  if (task.phase === "tool") {
    switch (task.phase_tool) {
      case "read_chapter": return task.phase_chapter != null ? `正在读第 ${task.phase_chapter} 章` : "正在读章节";
      case "search_text": return "正在搜正文";
      case "lookup_facts": return "正在查事实";
      case "read_draft": return "正在读本章草稿";
      case "get_plans": return "正在看计划和伏笔";
      case "get_issues": return "正在读检查结果";
      case "propose_edit": return "正在提出改法";
      case "check_passage": return "正在定点检查这一段";
      default: return "正在查";
    }
  }
  return "正在想下一步";
}

/** Whole seconds since an ISO time, or null when there is none. Re-read every second while `on`. */
export function useSecondsSince(iso: string | null | undefined, on: boolean): number | null {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    if (!on) return;
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [on]);
  const since = iso ? Date.parse(iso) : NaN;
  return Number.isFinite(since) ? Math.max(0, Math.floor((now - since) / 1000)) : null;
}

/** The three small squares that step along on the line in progress (still when motion is reduced). */
export function ThreeSquares() {
  return <span className="a-three" aria-hidden="true"><i /><i /><i /></span>;
}

/** What an action turned up. A passage is a line or two around the word searched for, then its chapter (which opens the original);
    a fact is its one line. */
function Found({ refs, sources, words, locate }: { refs: string[]; sources: Record<string, AssistantSource>; words: Record<string, string>; locate?: (source: AssistantSource) => void }) {
  const shown = refs.filter((ref) => sources[ref]);
  if (!shown.length) return null;
  return (
    <div className="a-found">
      {shown.map((ref) => {
        const source = sources[ref];
        const passage = source.kind === "passage";
        return (
          <p key={ref} className={source.cited ? undefined : "unused"}>
            {!passage && <span className="w">{whereLabel(source)}{source.cited ? "" : " · 没有引用"}</span>}
            <span className="snip">{passage ? snippetOf(source.text, words[ref] ?? "") : source.text}</span>
            {passage && (
              <>
                {" "}
                {locate && source.chapter_number != null
                  ? <button type="button" className="a-from" onClick={() => locate(source)}>{whereLabel(source)}</button>
                  : <span className="a-from">{whereLabel(source)}</span>}
                {!source.cited && <span className="a-from"> · 没有引用</span>}
              </>
            )}
          </p>
        );
      })}
    </div>
  );
}

function Action({ row, sources, locate }: { row: Extract<Row, { type: "group" }>; sources: Record<string, AssistantSource>; locate?: (source: AssistantSource) => void }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  const hasFound = row.refs.some((ref) => sources[ref]);
  return (
    <div className="a-act ok" data-tool={row.tool}>
      <span className="mk" aria-hidden="true" />
      {hasFound
        ? <button type="button" className="open" aria-expanded={open} aria-controls={id} onClick={() => setOpen((value) => !value)}>{row.text}<span className="more" aria-hidden="true"> {open ? "⌃" : "›"}</span></button>
        : <span>{row.text}</span>}
      <span className="secs">{row.count}</span>
      {open && <div id={id} className="a-found-wrap"><Found refs={row.refs} sources={sources} words={row.words} locate={locate} /></div>}
    </div>
  );
}

function NowLine({ task }: { task: AssistantTask }) {
  const seconds = useSecondsSince(task.phase_started_at, true);
  return (
    <div className="a-act now" data-phase={task.phase ?? "thinking"}>
      <span className="mk"><ThreeSquares /></span>
      <span>{nowText(task)}</span>
      <span className="secs">{seconds !== null && seconds >= 3 ? `${seconds} 秒` : ""}</span>
    </div>
  );
}

/** The rows of a task's process: its narration, the actions it took (each opens to what it found) and the steps that failed. */
function ProcessRows({ rows, sources, locate }: { rows: Row[]; sources: Record<string, AssistantSource>; locate?: (source: AssistantSource) => void }) {
  return (
    <>
      {rows.map((row) => {
        if (row.type === "say") return <p key={row.key} className="a-say">{row.text}</p>;
        if (row.type === "group") return <Action key={row.key} row={row} sources={sources} locate={locate} />;
        return (
          <div key={row.key} className={`a-act ${row.type === "fail" ? "bad" : "ok"}`}>
            <span className="mk" aria-hidden="true" />
            <span>{row.text}</span>
            <span className="secs" />
          </div>
        );
      })}
    </>
  );
}

/** The line above an answer: what the task is (问作品, 改资料 …), what it looked at and how long it took, in one small grey line that opens to
    the steps; `end` is what stands at its right end (改成 …, 停止). The steps are listed as they happen, then folded into the line. An author
    who opens the fold keeps it open. */
export function Steps({ task, locate, lead, end, named = false }: { task: AssistantTask; locate?: (source: AssistantSource) => void; lead: string; end?: ReactNode;
  /** The folded line names what it opens: 「过程 · 8 秒」 (a 写前回顾, whose line already says what the task is). */
  named?: boolean }) {
  const running = active(task);
  const [manual, setManual] = useState<boolean | null>(null);
  // The list folds by itself when the task ends; seen while this view was open, that moment is told by two figures settling into place.
  const [wasRunning, setWasRunning] = useState(running);
  if (running && !wasRunning) setWasRunning(true);
  const justFolded = wasRunning && !running && manual === null;
  const rows = processRows(task.steps);
  const shownRows = rows.length > 0;
  const open = running || (manual ?? false);
  // A list that is being folded stays on the page until its height has gone (the figures of the line above it are untouched).
  const [wasOpen, setWasOpen] = useState(open);
  const [folding, setFolding] = useState(false);
  if (open !== wasOpen) { setWasOpen(open); setFolding(!open); }
  useEffect(() => {
    if (!folding) return;
    const timer = window.setTimeout(() => setFolding(false), 600);
    return () => window.clearTimeout(timer);
  }, [folding]);
  const began = Date.parse(task.started_at ?? task.created_at);
  const ended = task.completed_at ? Date.parse(task.completed_at) : NaN;
  const took = Number.isFinite(began) && Number.isFinite(ended) ? Math.max(1, Math.round((ended - began) / 1000)) : null;
  const figure = (value: number, order: number) => <span className={justFolded ? "a-drop" : undefined} style={justFolded ? { animationDelay: `${order * 80}ms` } : undefined}>{value}</span>;
  const tally = named || took !== null;
  return (
    <div className="a-steps" role={running ? "status" : undefined}>
      <div className="a-process" data-testid="process-line">
        {running ? <span className="a-fold static"><span className="lead">{lead}</span> · 正在查</span>
          : shownRows ? (
            <button type="button" className="a-fold" aria-expanded={open} onClick={() => setManual(!open)}>
              <span className="lead">{lead}</span>
              {tally && <span className="tally">{named && " · 过程"}{took !== null && <> · {figure(took, 0)} 秒</>}</span>}
              <Fold open={open} />
            </button>
          ) : <span className="a-fold static"><span className="lead">{lead}</span>{took !== null && <span className="tally"> · {figure(took, 0)} 秒</span>}</span>}
        {end && <span className="a-process-end">{end}</span>}
      </div>
      {(open || folding) && (
        <div className={`a-proc-wrap${folding && !open ? " folding" : ""}${open && manual === true ? " unfolding" : ""}`}>
          <div className="a-proc-clip">
            <div className="a-proc">
              <ProcessRows rows={rows} sources={task.sources} locate={locate} />
              {running && <NowLine task={task} />}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** 怎么查的 ›: under an answer, folded. Opened it holds the steps the task took and, in plain grey, 查过……；没查：……, then the sentences of the model's
    note that tell where it looked (the rest of the note stays under the answer). The program's own 没查 line is lifted out under the answer, and the fold
    leaves it out, when the answer found nothing (`onlyMissed`) or the task ran into its limit. */
export function CoverLine({ task, onlyMissed = false }: { task: AssistantTask; onlyMissed?: boolean }) {
  const [open, setOpen] = useState(false);
  const panel = useId();
  const left = notChecked(task);
  const lifted = (onlyMissed || hitLimit(task)) && left.length > 0;
  const done = task.coverage?.checked ?? [];
  const rows = processRows(task.steps);
  const noted = splitNote(sentencesOf(task)?.note).looked;
  const line = [done.length > 0 ? `查过${done.join("、")}` : "", !lifted && left.length > 0 ? `没查：${left.join("、")}` : ""].filter(Boolean).join("；");
  if (active(task)) return null;
  return (
    <>
      {lifted && <p className="a-cover" data-testid="not-checked">没查：{left.join("、")}。</p>}
      {(rows.length > 0 || line || noted.length > 0) && (
        <div className="a-how-wrap" data-testid="how-checked">
          <button type="button" className="a-sources-fold" aria-expanded={open} aria-controls={panel} onClick={() => setOpen((value) => !value)}>怎么查的<Fold open={open} /></button>
          {open && (
            <div id={panel} className="a-how">
              {rows.length > 0 && <div className="a-proc"><ProcessRows rows={rows} sources={task.sources} /></div>}
              {line && <p className="a-cover">{line}。</p>}
              {noted.length > 0 && !line && <p className="a-cover">{noted.join("")}</p>}
            </div>
          )}
        </div>
      )}
    </>
  );
}
