"use client";

// An answer and what sits under it: the sentences (fading in once the answer has passed its checks), a card for each
// citation, the row of actions (copy, answer again, follow up, useful / not useful) and the cost line.
import { type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, type RefObject, useEffect, useRef, useState } from "react";
import { json, labelError, request } from "../../api";
import type { AssistantFeedbackReason, AssistantSource, AssistantTask } from "../../model";
import { clip, formatCount, writtenChars } from "../ui";
import { active, cardLabel, citedRefs, FOLLOW_UP_LIMIT_TEXT, OUT_OF_SCOPE_TEXT, refusalText, sentencesOf, spokenWhere, TASK_CHARS, whereLabel } from "./assistant-parts";

/** True once a task has been seen to run and then finish while this view was open: only such an answer fades in. */
export function useJustFinished(task: AssistantTask): boolean {
  const [seenRunning, setSeenRunning] = useState(() => active(task));
  const running = active(task);
  if (running && !seenRunning) setSeenRunning(true);
  return seenRunning && !running;
}

const CARD_WIDTH = 270;

/** A citation mark. Hovering or focusing it (a tap on a phone) opens a card with the chapter, the quoted words and a way to the original;
    the card stays for 300 ms after the pointer leaves, so the pointer can get into it. */
function Cite({ n, source, sourceId, locate }: { n: number; source: AssistantSource; /** The id of this mark's line in the list of sources under the answer. */ sourceId: string; locate: (source: AssistantSource) => void }) {
  const [at, setAt] = useState<{ left: number; top?: number; bottom?: number } | null>(null);
  const button = useRef<HTMLButtonElement>(null);
  const mark = useRef<HTMLElement>(null);
  const timer = useRef(0);
  // Whether the last pointer on this mark was a finger or a pen. A touch screen sends a mouse-over and a mouse-out after a tap;
  // they must not open or shut the card: a tap opens it, the next tap (or a tap elsewhere) shuts it.
  const touch = useRef(false);
  const pointer = (event: { pointerType: string }) => { touch.current = event.pointerType === "touch" || event.pointerType === "pen"; };
  // Whether the card was already open when a touch began.
  const wasOpen = useRef(false);
  // Putting focus back on the mark after Escape must not open the card again.
  const quiet = useRef(false);
  const shown = at !== null;
  // While the card is up, the quoted words in the list of sources are underlined (drawn from the left), so the mark and its source are tied together.
  useEffect(() => {
    if (!shown) return;
    const line = document.getElementById(sourceId);
    line?.classList.add("lit");
    return () => line?.classList.remove("lit");
  }, [shown, sourceId]);
  const open = () => {
    window.clearTimeout(timer.current);
    const box = button.current?.getBoundingClientRect();
    if (!box) return;
    const left = Math.min(Math.max(box.left + box.width / 2 - CARD_WIDTH / 2, 8), window.innerWidth - CARD_WIDTH - 8);
    setAt(box.top < 210 ? { left, top: box.bottom + 8 } : { left, bottom: window.innerHeight - box.top + 8 });
  };
  const closeSoon = () => {
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(() => setAt(null), 300);
  };
  const keep = () => window.clearTimeout(timer.current);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  // Scrolling anywhere moves the mark out from under a fixed card.
  useEffect(() => {
    if (!shown) return;
    const hide = () => setAt(null);
    // A tap anywhere else shuts the card (a finger on some phones never gives the mark focus, so no blur would).
    const away = (event: PointerEvent) => { if (!mark.current?.contains(event.target as Node)) setAt(null); };
    window.addEventListener("scroll", hide, true);
    window.addEventListener("resize", hide);
    document.addEventListener("pointerdown", away, true);
    return () => { window.removeEventListener("scroll", hide, true); window.removeEventListener("resize", hide); document.removeEventListener("pointerdown", away, true); };
  }, [shown]);
  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key !== "Escape" || !shown) return;
    event.stopPropagation();
    setAt(null);
    quiet.current = true;
    button.current?.focus();
    quiet.current = false;
  };
  return (
    <sup ref={mark} className="a-cite" onKeyDown={onKeyDown}>
      <button ref={button} type="button" aria-label={`出处 ${n}：${spokenWhere(source)}`} aria-expanded={shown}
        onPointerEnter={pointer} onPointerDown={(event) => { pointer(event); wasOpen.current = shown; }}
        onMouseEnter={() => { if (!touch.current) open(); }} onMouseLeave={() => { if (!touch.current) closeSoon(); }}
        onFocus={() => { if (!quiet.current) open(); }} onBlur={closeSoon}
        onClick={() => { if (touch.current && wasOpen.current) setAt(null); else open(); }}>{n}</button>
      {at && (
        <span className="a-pop" role="group" aria-label={`出处 ${n}`} style={{ left: at.left, top: at.top, bottom: at.bottom, width: CARD_WIDTH } as CSSProperties}
          onPointerEnter={pointer} onMouseEnter={keep} onMouseLeave={() => { if (!touch.current) closeSoon(); }} onFocus={keep} onBlur={closeSoon}>
          <span className="w">{cardLabel(source)}</span>
          <q>{clip(source.text, 150)}</q>
          {(source.chapter_number != null || source.anchor) && <button type="button" className="go" onClick={() => { setAt(null); locate(source); }}>去原文 →</button>}
        </span>
      )}
    </sup>
  );
}

/** The answer's sentences with a citation mark after each source it rests on; an off-topic question gets its fixed reply instead. */
export function AnswerBlock({ task, fade, locate, innerRef }: { task: AssistantTask; fade: boolean; locate: (source: AssistantSource) => void; innerRef?: RefObject<HTMLDivElement | null> }) {
  const answer = sentencesOf(task);
  if (!answer) return null;
  if (answer.status === "out_of_scope") return <p className="a-fixed" data-testid="out-of-scope">{task.out_of_scope_text || OUT_OF_SCOPE_TEXT}</p>;
  const refs = citedRefs(task);
  const number = (ref: string) => refs.indexOf(ref) + 1;
  return (
    <div ref={innerRef} className={`a-answer${fade ? " a-fade" : ""}`}>
      {answer.sentences.length > 0 && (
        <p>
          {answer.sentences.map((sentence, index) => (
            <span key={index} className="a-s" style={{ "--i": index } as CSSProperties}>
              {sentence.text}
              {sentence.refs.filter((ref) => refs.includes(ref)).map((ref) => <Cite key={ref} n={number(ref)} source={task.sources[ref]} sourceId={`a-src-${task.id}-${number(ref)}`} locate={locate} />)}
            </span>
          ))}
        </p>
      )}
      {answer.note && <p className="a-answer-note">{answer.note}</p>}
    </div>
  );
}

/** The answer as text to paste: its sentences with [n] after each source and the sources listed at the end; only the words with Shift. */
export function answerText(task: AssistantTask, withSources: boolean): string {
  const answer = sentencesOf(task);
  if (!answer) return "";
  const refs = citedRefs(task);
  const body = answer.sentences.map((sentence) => `${sentence.text}${withSources ? sentence.refs.filter((ref) => refs.includes(ref)).map((ref) => `[${refs.indexOf(ref) + 1}]`).join("") : ""}`).join("");
  const parts = [body, answer.note ?? ""].filter(Boolean);
  if (withSources && refs.length) parts.push(refs.map((ref, index) => `[${index + 1}] ${whereLabel(task.sources[ref])}`).join("\n"));
  return parts.join("\n\n");
}

const REASONS: { id: AssistantFeedbackReason; label: string }[] = [
  { id: "wrong", label: "不对" }, { id: "verbose", label: "啰嗦" }, { id: "not_found", label: "没找到" }, { id: "bad_source", label: "出处不准" },
];
const ThumbUp = () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M5 7v7H2V7h3Zm0 0 3-5c1.2 0 2 .8 1.7 2L9 7h4.2c.9 0 1.5.8 1.3 1.6l-1.2 4.6c-.2.5-.6.8-1.1.8H5" /></svg>;
const ThumbDown = () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true"><path d="M5 9V2H2v7h3Zm0 0 3 5c1.2 0 2-.8 1.7-2L9 9h4.2c.9 0 1.5-.8 1.3-1.6l-1.2-4.6C13.1 2.3 12.7 2 12.2 2H5" /></svg>;

/** 有用 / 没用: two small icons. 没用 asks what was wrong (any of four reasons), then folds away a second after the last choice. */
export function Feedback({ task, projectId, replace }: { task: AssistantTask; projectId: string; replace: (next: AssistantTask) => void }) {
  const verdict = task.feedback?.verdict ?? null;
  const [asking, setAsking] = useState(false);
  const [noted, setNoted] = useState(false);
  const [thanks, setThanks] = useState(false);
  const [picked, setPicked] = useState<AssistantFeedbackReason[]>(task.feedback?.reasons ?? []);
  const [error, setError] = useState("");
  const timer = useRef(0);
  const thanksTimer = useRef(0);
  useEffect(() => () => { window.clearTimeout(timer.current); window.clearTimeout(thanksTimer.current); }, []);
  const path = `/projects/${projectId}/assistant/tasks/${task.id}/feedback`;
  const put = async (body: { verdict: "up" } | { verdict: "down"; reasons: AssistantFeedbackReason[] }) => {
    try { replace(await request<AssistantTask>(path, { method: "PUT", body: JSON.stringify(body) })); setError(""); return true; }
    catch (cause) { setError(labelError(cause)); return false; }
  };
  const withdraw = async () => {
    window.clearTimeout(timer.current); window.clearTimeout(thanksTimer.current); setThanks(false);
    try { replace(await request<AssistantTask>(path, { method: "DELETE" })); setError(""); setAsking(false); setNoted(false); setPicked([]); }
    catch (cause) { setError(labelError(cause)); }
  };
  const thumbUp = async () => {
    if (verdict === "up") { await withdraw(); return; }
    window.clearTimeout(timer.current); setAsking(false); setNoted(false);
    if (await put({ verdict: "up" })) { setThanks(true); window.clearTimeout(thanksTimer.current); thanksTimer.current = window.setTimeout(() => setThanks(false), 1800); }
  };
  const thumbDown = async () => {
    if (verdict === "down") { await withdraw(); return; }
    window.clearTimeout(timer.current); window.clearTimeout(thanksTimer.current); setThanks(false); setNoted(false); setPicked([]);
    if (await put({ verdict: "down", reasons: [] })) setAsking(true);
  };
  const choose = (reason: AssistantFeedbackReason) => {
    const next = picked.includes(reason) ? picked.filter((item) => item !== reason) : [...picked, reason];
    setPicked(next);
    window.clearTimeout(timer.current);
    timer.current = window.setTimeout(async () => { if (await put({ verdict: "down", reasons: next })) { setAsking(false); setNoted(true); } }, 1000);
  };
  return (
    <>
      <span className="a-thumbs" role="group" aria-label="这个回答有没有用">
        <button type="button" aria-label="有用" title="有用" aria-pressed={verdict === "up"} onClick={() => void thumbUp()}><ThumbUp /></button>
        <button type="button" aria-label="没用" title="没用" aria-pressed={verdict === "down"} onClick={() => void thumbDown()}><ThumbDown /></button>
      </span>
      {asking && (
        <div className="a-why-not" role="group" aria-label="哪里不好">
          <span>哪里不好？</span>
          {REASONS.map((reason) => <button key={reason.id} type="button" aria-pressed={picked.includes(reason.id)} onClick={() => choose(reason.id)}>{reason.label}</button>)}
        </div>
      )}
      {noted && !asking && <span className="a-noted" role="status">已记下，谢谢。</span>}
      {thanks && verdict === "up" && <span className="a-noted inline" role="status">谢谢</span>}
      {error && <span className="a-warn-text" role="alert">{error}</span>}
    </>
  );
}

/** The row under a finished answer, and the cost line: 复制 · 重新回答 · 接着问 · 有用 / 没用, then 「计 500 字」 at the right (not for a visitor). */
export function TaskFoot({ task, projectId, visitor, blocked, answer, followUp, followUpLimit = false, regenerate, replace }: {
  task: AssistantTask;
  projectId: string;
  visitor: boolean;
  /** Why a new task cannot start now, or empty. */
  blocked: string;
  answer: RefObject<HTMLDivElement | null> | null;
  /** 接着问 (asks only, and not for an off-topic reply). */
  followUp: (() => void) | null;
  /** The chain has had its two follow-ups: 接着问 is greyed, with the reason. */
  followUpLimit?: boolean;
  /** 重新回答 (asks only, and not for an off-topic reply). */
  regenerate: (() => void) | null;
  replace: (next: AssistantTask) => void;
}) {
  const [copied, setCopied] = useState("");
  const timer = useRef(0);
  useEffect(() => () => window.clearTimeout(timer.current), []);
  if (task.status !== "completed") return null;
  const charged = !visitor && task.usage.chars_charged > 0;
  const say = (text: string) => { setCopied(text); window.clearTimeout(timer.current); timer.current = window.setTimeout(() => setCopied(""), 1600); };
  const copy = async (event: { shiftKey: boolean }) => {
    const text = answerText(task, !event.shiftKey);
    try { await navigator.clipboard.writeText(text); say("已复制"); }
    catch {
      // No clipboard: leave the answer selected so it can be copied by hand.
      const node = answer?.current;
      if (node) { const range = document.createRange(); range.selectNodeContents(node); const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range); }
      say("已选中，按 Ctrl+C 复制");
    }
  };
  return (
    <div className="a-foot">
      {answer && <button type="button" className="a-link a-copy" title="按住 Shift 点，只复制正文" onClick={(event) => void copy(event)}>{copied || "复制"}</button>}
      {regenerate && (
        <span className="a-regen">
          <button type="button" className="a-link" disabled={Boolean(blocked)} title={blocked || undefined} onClick={regenerate}>重新回答</button>
          <span className="a-hint">{visitor ? "用 1 次" : estimateOf(task)}</span>
        </span>
      )}
      {followUp && (followUpLimit
        ? <button type="button" className="a-link" disabled title={FOLLOW_UP_LIMIT_TEXT}>接着问</button>
        : <button type="button" className="a-link" onClick={followUp}>接着问</button>)}
      <Feedback task={task} projectId={projectId} replace={replace} />
      {charged && <span className="a-cost-line">计 {formatCount(task.usage.chars_charged)} 字</span>}
    </div>
  );
}

/** What asking the same thing again costs, as the first time was worked out: a check of a picked passage also pays for the passage. */
export const estimateOf = (task: AssistantTask) =>
  `约 ${formatCount(TASK_CHARS + (task.context.intent === "check_selection" ? writtenChars(task.context.selection ?? "") : 0))} 字`;

/** A task started again: the new one in the old one's place, asked for through the server (which charges it like a new question). */
export async function regenerateTask(projectId: string, task: AssistantTask, visitor: boolean): Promise<{ task: AssistantTask } | { error: string }> {
  try { return { task: await json<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}/regenerate`, "POST", {}) }; }
  catch (cause) { return { error: refusalText(cause, visitor, task.kind) }; }
}
