"use client";

// The built-in assistant (v1.8.0). One conversation per work, kept on the server: the author asks, the
// assistant looks things up in the work itself and answers with where each sentence comes from. It only
// advises; nothing here writes to the draft or the materials except through the editor, one change at a time,
// when the author says so. The same AssistantThread is used in three places: the writing page's right
// column (and its phone pane), and a drawer opened from the top bar on the other pages. A pop-up bar over
// selected text brings a passage into a question. Six uses live in it: 问作品, 写前回顾, 帮我改这一处, 查前文矛盾, 改资料 (v2.0: the
// assistant proposes changes to the materials, which the author confirms) and 长任务 (v2.1: a plan the author approves, steps taken in the
// background, a report and cards to confirm); the box's
// 自动 mode (the default) judges which one a sentence asks for, and the task it starts says so and can be changed.
import {
  createContext,
  Fragment,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useContext,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { json, labelError, labelRunFailure, request, type ApiFailure } from "../../api";
import type { AssistantContextInput, AssistantPage, AssistantSource, AssistantTask, Project, WritingAnalysisRun } from "../../model";
import { qaLayerLabel, qaStanceLabel, qaStatusLabel, readableKeys, stageLabel, timeLabel } from "../labels";
import { type CheckUsage, clip, formatCount, isSampleWork, Menu, SAMPLE_FREE, writtenChars } from "../ui";
import { regenerateTask } from "./assistant-answer";
import { mergeChanges } from "./assistant-change";
import { Composer, type ComposeChip, type Mode, type PlusPick } from "./assistant-compose";
import { LocateContext, ThreeSquares } from "./assistant-process";
import { FixView, type ProposalActions, useProposalActions, type WritingLink } from "./assistant-fix";
import { notFoundText, requestLocate } from "./assistant-locate";
import { LongView } from "./assistant-long";
import { active, isRecap, locateTarget, longLive, quotaReason, refusalText, RUNNING_NOW, spokenResult, TASK_CHARS, turnTime, visitorOutsideSample } from "./assistant-parts";
import { noteLong, seenLong } from "./long-watch";
import { RecapView } from "./assistant-recap";
import { CHECK_QUESTION, type NewTask, OutOfScopeNote, RecapElsewhereNote, RerouteContext, type RerouteControl, routeInput, taskFor, type Use, USE_LABEL, wantRecapOnArrival } from "./assistant-route";
import { Starters, starterQuestions } from "./assistant-start";
import { arrange, AskGroup, type AskHandlers } from "./assistant-task";

export type { DraftLink, IssueInfo, WritingLink } from "./assistant-fix";

/** What the page the author is on tells the assistant: the page, and the chapter or person in view. */
export type AssistantAnchor = { page: AssistantPage; chapter_number?: number; character_id?: string; character_name?: string };
/** A passage the author picked in the text, on its way into the conversation. `quick` asks about it straight away. */
export type Incoming = { text: string; quick: boolean; nonce: number };
/** Something the page asks the assistant to start: a 写前回顾, a fix for one finding, or a check of a picked passage. */
export type Command =
  | { nonce: number; kind: "recap" }
  | { nonce: number; kind: "fix"; issueId: string }
  /** A finding becomes the context of the next question (a chip in the box); nothing is sent. */
  | { nonce: number; kind: "context"; issueId: string }
  | { nonce: number; kind: "check"; text: string };
type Bridge = {
  setAnchor: (anchor: AssistantAnchor | null) => void;
  /** Opens the drawer; with `focusTask` it scrolls to that task of the conversation once the conversation is read. */
  openDrawer: (incoming?: Omit<Incoming, "nonce">, focusTask?: string) => void;
  usageChanged: () => void;
  /** The assistant wrote to the materials (or took a change back): the page reads facts and threads again. */
  materialsChanged: () => void;
  /** A visitor leaves the visitor space for the page where an account is made (the assistant's 注册 button). */
  register: () => void;
};
/** The app provides it; pages tell it where the author is, and ask it to open the drawer. */
export const AssistantBridge = createContext<Bridge>({ setAnchor: () => undefined, openDrawer: () => undefined, usageChanged: () => undefined, materialsChanged: () => undefined, register: () => undefined });
/** Whether the assistant dock is open (one flag for every page), and the task a page asked to have brought into view. The writing page keeps its own
    dock (it hands the dock the draft and the findings) and reads this to show or hide it. */
export const DockContext = createContext<{ open: boolean; setOpen: (open: boolean) => void; focus: { taskId: string; nonce: number } | null; /** Open because this device remembered it, not because the author just asked: the cursor stays where it was. */ restored: boolean }>({ open: false, setOpen: () => undefined, focus: null, restored: false });
/** Whether the dock was left open, kept on this device; nothing readable or writable means closed. */
const DOCK_OPEN = "story-continuity:assistant-dock";
/** On a phone (720 wide or less) the panel takes the whole screen: it is never opened by the memory, and what the author does with it there is not remembered. */
const onPhone = () => window.innerWidth <= 720;
export const readDockOpen = () => { if (onPhone()) return false; try { return window.localStorage.getItem(DOCK_OPEN) === "open"; } catch { return false; } };
export const writeDockOpen = (open: boolean) => { if (onPhone()) return; try { window.localStorage.setItem(DOCK_OPEN, open ? "open" : "closed"); } catch { /* it is only a memory */ } };

/** A page registers where the author is for as long as it is shown; the top bar's 助手 button follows it. */
export function useAssistantAnchor(page: AssistantPage | null, detail: { chapter_number?: number; character_id?: string; character_name?: string } = {}) {
  const { setAnchor } = useContext(AssistantBridge);
  const { chapter_number, character_id, character_name } = detail;
  useEffect(() => {
    setAnchor(page ? { page, chapter_number, character_id, character_name } : null);
    return () => setAnchor(null);
  }, [setAnchor, page, chapter_number, character_id, character_name]);
}

const QUESTION_MAX = 300;
const QUICK_QUESTION = "这段前面怎么写的？";
const ASK_PLACEHOLDER = "问这部作品里的人、事、物……";
const REFINE_PLACEHOLDER = "对改法有什么要求？比如：保留苏岑的视角";
const RECAP_PLACEHOLDER = "不用写字，直接发送：回顾上一章停在哪、有哪些线还没收";
const CHECK_PLACEHOLDER = "在正文里选中要查的一段";
const CHANGE_PLACEHOLDER = "说要改资料里的什么：比如把第 12 章她左腕受伤记进事实";
const LONG_PLACEHOLDER = "说一件跨很多章的事：比如那些还吊着的伏笔都替我过一遍";
const LONG_VISITOR = "注册后可以用";
/** Whether an element is on screen now (not hidden by its tab, not closed): the top bar's dot goes out once the author has looked at the assistant. */
function useShown(target: { current: HTMLElement | null }) {
  const [shown, setShown] = useState(false);
  useEffect(() => {
    const node = target.current;
    if (!node || typeof IntersectionObserver === "undefined") return;
    const watch = new IntersectionObserver((entries) => setShown(entries[entries.length - 1]?.isIntersecting ?? false));
    watch.observe(node);
    return () => watch.disconnect();
  }, [target]);
  return shown;
}
const PRIVACY_SEEN = "story-continuity:assistant-privacy-seen";

/** The words typed in the box and not yet sent, kept per work for this visit (V01): closing the drawer or going to another page does not lose them.
    Only the words: a picked passage, person or chapter is not restored. Storage that cannot be read or written is the same as nothing kept. */
const unsentKey = (projectId: string) => `story-continuity:assistant-unsent:${projectId}`;
export function readUnsent(projectId: string): string {
  try { return window.sessionStorage.getItem(unsentKey(projectId)) ?? ""; } catch { return ""; }
}
export function keepUnsent(projectId: string, text: string) {
  try { if (text) window.sessionStorage.setItem(unsentKey(projectId), text); else window.sessionStorage.removeItem(unsentKey(projectId)); } catch { /* not kept */ }
}

/** A task is being followed while it runs, and while one of its changes is being rechecked. */
const watched = (task: AssistantTask) => active(task) || Boolean(task.proposals?.some((proposal) => proposal.recheck?.status === "running"));

export type ThreadProps = {
  project: Project;
  anchor: AssistantAnchor;
  usage: CheckUsage | null;
  visitor: boolean;
  go: (href: string) => void;
  /** A passage picked in the text, to carry into the question (or to ask about at once). */
  incoming?: Incoming | null;
  /** A task the page starts for the author. */
  command?: Command | null;
  /** A task of the conversation to bring into view (the materials page's 看对话). */
  focus?: { taskId: string; nonce: number } | null;
  /** The passage that is selected in the text right now (null once nothing is). In 查前文矛盾 it becomes the box's 「选中」 tag by itself. */
  picked?: Incoming | null;
  /** The writing page's draft and findings: what makes a change adoptable. Missing in the drawer. */
  writing?: WritingLink;
  /** What the box can add to a question, and what the empty conversation's starting questions are made from. */
  material?: ThreadMaterial;
  /** Shown above the conversation (the 对照计划 block). When `topKey` changes the conversation scrolls back to it. */
  top?: ReactNode;
  topKey?: number;
  /** Called just before the thread moves the author to a chapter (the drawer closes). */
  onNavigate?: () => void;
  /** The assistant is one panel docked at the right of every page. */
  variant: "dock";
};
export type ThreadMaterial = {
  chapters: { number: number; title: string }[];
  characters: { id: string; name: string }[];
  draftBody: string;
  /** The findings of the check on screen that can be handed over, and why none can when `issuesReason` is not empty. */
  issues: { id: string; number: number; label: string }[];
  issuesReason: string;
};
const NO_MATERIAL: ThreadMaterial = { chapters: [], characters: [], draftBody: "", issues: [], issuesReason: "" };

/** Tasks read on their own go into the conversation in the order they were asked, each once. */
const withTasks = (current: AssistantTask[] | null, extra: AssistantTask[]): AssistantTask[] => {
  const have = new Set((current ?? []).map((task) => task.id));
  return [...(current ?? []), ...extra.filter((task) => !have.has(task.id))].sort((a, b) => (a.created_at < b.created_at ? -1 : a.created_at > b.created_at ? 1 : 0));
};

/** The tag 接着上一问 says which follow-up the next question would be, and how many are left. */
const followLabel = (task: AssistantTask) => {
  const number = (task.follow_up_depth ?? 0) + 1;
  return `接着上一问 · 第 ${number} 次追问，${number >= 2 ? "这是最后一次" : "还能再问 1 次"}`;
};
/** A finished question that a further question can follow (a recap, a fix, a check and an off-topic reply cannot be followed). */
const followable = (task: AssistantTask) =>
  task.kind === "ask" && task.status === "completed" && task.context.intent !== "check_selection" && Boolean(task.answer) && !isRecap(task.answer)
  && (task.answer as { status?: string }).status !== "out_of_scope" && (task.follow_up_depth ?? 0) < 2;

export function AssistantThread({ project, anchor, usage, visitor, go, incoming, command, focus, picked, writing, material = NO_MATERIAL, top, topKey, onNavigate, variant }: ThreadProps) {
  const projectId = project.id;
  const bridge = useContext(AssistantBridge);
  const [tasks, setTasks] = useState<AssistantTask[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [clearedNonce, setClearedNonce] = useState(0);
  const [legacy, setLegacy] = useState<WritingAnalysisRun[]>([]);
  const [text, setText] = useState(() => readUnsent(projectId));
  useEffect(() => { keepUnsent(projectId, text); }, [projectId, text]);
  const [mode, setMode] = useState<Mode>("auto");
  const [selection, setSelection] = useState("");
  const [followUp, setFollowUp] = useState<AssistantTask | null>(null);
  // The task whose automatic 接着上一问 tag the author took off: that answer is not followed unless asked for with its 接着问 button.
  const [followDropped, setFollowDropped] = useState<string | null>(null);
  // 自动: the sentence is being judged. The question is in the conversation at once (`pending`), with a line saying so, and the box is empty.
  const [routing, setRouting] = useState(false);
  const [pending, setPending] = useState<{ input: string; selection: string } | null>(null);
  // The tasks that were started as a question because the judgement did not come in time (the line above their answer says so).
  const [timedOut, setTimedOut] = useState<string[]>([]);
  // The last send failed in a way that is worth trying again (the box still holds what was sent): the bar says so, with 重试.
  const [again, setAgain] = useState<{ run: () => void } | null>(null);
  // A sentence the judgement took for not being about the work: a local note under the conversation, no task.
  const [offTopic, setOffTopic] = useState<{ input: string; context: AssistantContextInput } | null>(null);
  // A 写前回顾 asked for off the writing page: a local note with the way there, no task.
  const [elsewhere, setElsewhere] = useState<string | null>(null);
  // A finding on the box. `manual` when the author asked for a fix on its card (the use is chosen, nothing is judged); a finding picked in
  // the 「＋」 menu is only context, and in 自动 the judgement decides what the sentence asks of it.
  const [refine, setRefine] = useState<{ issueId: string; number: number; manual: boolean } | null>(null);
  const [dropped, setDropped] = useState({ chapter: false, character: false });
  // What the 「＋」 menu added: it replaces the chapter or person the page would have brought.
  const [chosen, setChosen] = useState<{ chapter: number | null; character: { id: string; name: string } | null }>({ chapter: null, character: null });
  const [sending, setSending] = useState(false);
  const [stopping, setStopping] = useState(false);
  // 停止 while the sentence is still being judged (no task yet): the send is given up and nothing is created. While the task is being made (the post is
  // in flight) it is cancelled the moment it exists. `stoppedNote` is the question that was not sent, shown with its word 已停止.
  const routeAbort = useRef<{ aborted: boolean; undo: () => void } | null>(null);
  const stopAfterPost = useRef(false);
  const [stoppedNote, setStoppedNote] = useState<{ input: string; selection: string } | null>(null);
  const [refusal, setRefusal] = useState("");
  const [tip, setTip] = useState("");
  const [announce, setAnnounce] = useState("");
  const [confirmClear, setConfirmClear] = useState(false);
  const [unseen, setUnseen] = useState(false);
  // Questions asked in this view, whose bubbles rise into place (the ones read from the server are simply there).
  const [asked, setAsked] = useState<string[]>([]);
  const [privacy] = useState(() => { try { return window.localStorage.getItem(PRIVACY_SEEN) !== "1"; } catch { return false; } });
  const root = useRef<HTMLDivElement>(null);
  const thread = useRef<HTMLDivElement>(null);
  const field = useRef<HTMLTextAreaElement>(null);
  const stick = useRef(true);
  // A task that has just been asked: its top is kept in view while it fills up (a change and its recheck are long), until
  // it has ended or the author scrolls.
  const pinned = useRef<string | null>(null);
  // Scrolls the thread does by itself must not count as the author reading upwards (or back down to the end).
  const quiet = useRef(0);
  const handled = useRef(0);
  const handledCommand = useRef(0);
  const handledFocus = useRef(0);
  // The id of the task the last post made, for the notes that are kept about it.
  const lastCreated = useRef("");
  const announced = useRef(new Set<string>());
  const signature = useRef("");
  const cameHidden = useRef(false);

  // The conversation so far, oldest first. Anything that reads the work's old 问一问 history is a separate, read-only list.
  useEffect(() => {
    let live = true;
    request<{ tasks: AssistantTask[] }>(`/projects/${projectId}/assistant/tasks?limit=30`)
      .then((data) => { if (live) { setTasks(data.tasks); setLoadError(""); } }, (cause) => { if (live) setLoadError(labelError(cause)); });
    request<{ runs: WritingAnalysisRun[] }>(`/projects/${projectId}/analyses?analysis_type=story_qa&limit=20`)
      .then((data) => { if (live) setLegacy(data.runs ?? []); }, () => undefined);
    return () => { live = false; };
  }, [projectId]);

  // While a task runs (or one of its changes is being rechecked), ask for it once a second; the poll stops when
  // that is over, or when the thread goes away.
  const watchedId = tasks?.find(watched)?.id ?? null;
  useEffect(() => {
    if (!watchedId) return;
    let live = true;
    let timer = 0;
    const poll = async () => {
      try {
        const next = await request<AssistantTask>(`/projects/${projectId}/assistant/tasks/${watchedId}`);
        if (!live) return;
        setTasks((current) => current && current.map((task) => (task.id === next.id ? next : task)));
        if (!watched(next)) {
          bridge.usageChanged();
          if (next.status === "completed" && next.answer && !announced.current.has(next.id)) { announced.current.add(next.id); setAnnounce(spokenResult(next)); }
          return;
        }
      } catch (cause) {
        // Cleared from another window: nothing left to wait for.
        if (live && (cause as ApiFailure).code === "resource_not_found") { setTasks((current) => current && current.filter((task) => task.id !== watchedId)); return; }
      }
      if (live) timer = window.setTimeout(() => void poll(), 1000);
    };
    timer = window.setTimeout(() => void poll(), 1000);
    return () => { live = false; window.clearTimeout(timer); };
  }, [watchedId, projectId, bridge]);

  // A long task that is being worked on (the plan is made, or the steps are taken) is asked for every 2 seconds, until it stops to ask,
  // is over, or the thread goes away. The top bar's note of it is kept in step.
  const liveLongId = tasks?.find(longLive)?.id ?? null;
  const liveLongStatus = tasks?.find(longLive)?.status ?? null;
  useEffect(() => {
    if (!liveLongId) return;
    let live = true;
    let timer = 0;
    const poll = async () => {
      try {
        const next = await request<AssistantTask>(`/projects/${projectId}/assistant/long-tasks/${liveLongId}`);
        if (!live) return;
        setTasks((current) => current && current.map((task) => (task.id === next.id ? next : task)));
        noteLong(projectId, next.id, next.status);
        if (!longLive(next)) {
          bridge.usageChanged();
          if (!announced.current.has(`${next.id}:${next.status}`)) {
            announced.current.add(`${next.id}:${next.status}`);
            setAnnounce(next.status === "waiting_author" ? "长任务停下来了，等你回答一个问题" : next.status === "completed" ? "长任务做完了" : next.status === "stopped" ? "长任务停下了" : "长任务出错了");
          }
          return;
        }
      } catch (cause) {
        if (live && (cause as ApiFailure).code === "resource_not_found") { setTasks((current) => current && current.filter((task) => task.id !== liveLongId)); return; }
      }
      if (live) timer = window.setTimeout(() => void poll(), 2000);
    };
    timer = window.setTimeout(() => void poll(), liveLongStatus === "planning" ? 1000 : 2000);
    return () => { live = false; window.clearTimeout(timer); };
  }, [liveLongId, liveLongStatus, projectId, bridge]);
  // The conversation's list holds a long task as a plain task; its plan, steps, questions and cards come from its own address, read once.
  const longRead = useRef(new Set<string>());
  useEffect(() => {
    for (const task of tasks ?? []) {
      if (task.kind !== "long" || task.plan || longRead.current.has(task.id)) continue;
      longRead.current.add(task.id);
      request<AssistantTask>(`/projects/${projectId}/assistant/long-tasks/${task.id}`)
        .then((next) => setTasks((current) => current && current.map((item) => (item.id === next.id ? next : item))), () => undefined);
    }
  }, [tasks, projectId]);
  // The frame around the conversation (the drawer, the writing page's column) never scrolls: only the conversation does. The frames are
  // overflow: clip, and nothing here focuses without preventScroll; if something still moved a frame, it is put back when the window changes
  // size and when an answer has come in (V04, V10).
  const settled = (tasks ?? []).filter((task) => !active(task) && !longLive(task)).length;
  useEffect(() => {
    const settle = () => {
      const mine = root.current;
      if (!mine || mine.getClientRects().length === 0) return;
      for (const frame of [mine.closest<HTMLElement>(".a-dock")]) if (frame && frame.scrollTop !== 0) frame.scrollTop = 0;
    };
    settle();
    window.addEventListener("resize", settle);
    return () => window.removeEventListener("resize", settle);
  }, [settled]);
  // The author has the assistant in front of them and the latest long task is waiting for an answer or is over: the top bar's dot has been seen.
  const shown = useShown(root);
  const lastLong = [...(tasks ?? [])].reverse().find((task) => task.kind === "long" && task.plan) ?? null;
  const lastLongSeen = lastLong ? `${lastLong.id}:${lastLong.status}` : "";
  useEffect(() => {
    if (shown && lastLong) seenLong(projectId, lastLong.id, lastLong.status);
    // eslint-disable-next-line react-hooks/exhaustive-deps -- the task's id and status are the key
  }, [shown, lastLongSeen, projectId]);

  // New text keeps the view at the bottom, unless the author has scrolled up to read (then 「新回答 ↓」 says there is more);
  // a new task keeps its own top in view.
  useEffect(() => {
    const box = thread.current;
    if (!box) return;
    const now = (tasks ?? []).map((task) => `${task.id}:${task.status}:${task.steps.length}:${task.answer ? 1 : 0}:${task.progress?.done ?? ""}:${task.questions?.length ?? ""}:${task.changes?.length ?? ""}`).join("|") + (pending ? "|pending" : "");
    const changed = now !== signature.current;
    signature.current = now;
    // Out of sight (the panel or the column is hidden) nothing can be measured or scrolled: remember that something came, and show it when shown.
    if (!shown) { if (changed) cameHidden.current = true; return; }
    const id = pinned.current;
    const target = id ? box.querySelector<HTMLElement>(`[data-task="${id}"]`) : null;
    if (target) {
      quiet.current = performance.now() + 150;
      box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
      const pinnedTask = tasks?.find((task) => task.id === id) ?? { status: "completed" } as AssistantTask;
      if (!active(pinnedTask) && !longLive(pinnedTask)) pinned.current = null;
    } else if (stick.current) {
      // A few new lines glide into view; a long jump (or reduced motion) is taken at once.
      const gap = box.scrollHeight - box.clientHeight - box.scrollTop;
      if (gap > 0 && gap < 480 && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
        quiet.current = performance.now() + 500;
        box.scrollTo({ top: box.scrollHeight, behavior: "smooth" });
      } else {
        quiet.current = performance.now() + 150;
        box.scrollTop = box.scrollHeight;
      }
    } else if (changed && !id && tasks && tasks.length > 0 && box.scrollHeight - box.scrollTop - box.clientHeight > 80) {
      // Only when the new words are below what is in view: an answer already on screen needs no 「新回答 ↓」.
      void Promise.resolve().then(() => setUnseen(true));
    }
  });

  // Shown again (the panel opened, the column unfolded) after something came while it was out of sight: the latest turn is shown from its start
  // (an answer that finished unseen is read from the top, not the end), and 「新回答 ↓」 is not needed for it.
  useEffect(() => {
    const box = thread.current;
    if (!shown || !box || !cameHidden.current) return;
    cameHidden.current = false;
    const groups = box.querySelectorAll<HTMLElement>("[data-task]");
    const last = groups[groups.length - 1];
    if (!last) return;
    pinned.current = null;
    quiet.current = performance.now() + 300;
    box.scrollTop += last.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
    stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
    setUnseen(false);
  }, [shown]);

  // The block at the top has just been (re)started: show it, not the end of the conversation.
  useEffect(() => {
    if (!topKey) return;
    stick.current = false;
    pinned.current = null;
    quiet.current = performance.now() + 150;
    thread.current?.scrollTo({ top: 0 });
  }, [topKey]);

  const archived = project.status === "archived";
  const runningId = tasks?.find(active)?.id ?? null;
  const busy = Boolean(runningId) || sending || routing;
  // A sample work takes no characters: the box is never held back for the allowance there.
  const sample = isSampleWork(project);
  const needed = usage?.account_type === "registered" && !sample ? usage.assistant_task_chars ?? TASK_CHARS : 0;
  // The box is used up for good (until the allowance comes back): it says why, inside itself.
  const off = archived ? "作品已归档，只能浏览。" : quotaReason(usage, sample);
  const blocked = off || (busy && !routing ? RUNNING_NOW : "");
  const cost = usage?.account_type === "registered" ? (sample ? SAMPLE_FREE : `约 ${formatCount(needed)} 字`)
    : usage?.account_type === "visitor" && usage.assistant_tasks_remaining !== undefined ? `24 小时内还可以问 ${usage.assistant_tasks_remaining} 次` : "";
  // What is left today goes after the cost when the line has room for it, and into its title when it has not.
  const costMore = usage?.account_type === "registered" && !sample ? `24 小时内还剩 ${formatCount(usage.check_chars_remaining)} 字` : "";

  // The page hears whether a task is running (its 写前回顾 button waits for it) and which findings have an adopted change.
  const report = useRef(writing);
  useEffect(() => { report.current = writing; });
  useEffect(() => { report.current?.busyChanged(busy); }, [busy]);
  const adopted = useMemo(() => {
    const ids = (tasks ?? []).filter((task) => task.kind === "fix_issue" && task.context.issue_id && task.proposals?.some((proposal) => proposal.kind === "edit_this" && proposal.status === "adopted")).map((task) => task.context.issue_id!);
    return [...new Set(ids)].sort().join("|");
  }, [tasks]);
  useEffect(() => { report.current?.adoptedChanged(adopted ? adopted.split("|") : []); }, [adopted]);

  const actions: ProposalActions = useProposalActions(projectId, writing, setTasks, bridge.usageChanged);
  const replace = (next: AssistantTask) => {
    setTasks((current) => current && current.map((task) => (task.id === next.id ? next : task)));
    if (next.kind === "long") noteLong(projectId, next.id, next.status);
  };

  const onWriting = Boolean(writing);
  const chapterNumber = anchor.page === "writing" ? anchor.chapter_number : undefined;
  const recapReason = chapterNumber != null && chapterNumber <= 1 ? "第一章前面没有内容可以回顾" : writing?.draft.dirty ? "等草稿保存后再回顾" : "";
  const modes: Mode[] = onWriting ? (visitor ? ["auto", "ask", "recap", "change", "long"] : ["auto", "ask", "recap", "check", "change", "long"]) : ["auto", "ask", "change", "long"];
  // 长任务 is shown to a visitor but greyed, with the reason.
  const unavailable: Partial<Record<Mode, string>> = visitor ? { long: LONG_VISITOR } : {};
  const activeMode: Mode = modes.includes(mode) && !unavailable[mode] ? mode : "auto";
  const asking = activeMode === "auto" || activeMode === "ask";
  // The latest answer is followed on its own (the tag is on the box) while it can be, unless the author took the tag off, or the box
  // holds something that decides the use itself (a picked passage, a finding) or the author chose another mode.
  const latestTask = tasks && tasks.length > 0 ? tasks[tasks.length - 1] : null;
  const autoFollow = latestTask && followable(latestTask) && followDropped !== latestTask.id && asking && !selection && !refine ? latestTask : null;
  const following = asking && !refine ? followUp ?? autoFollow : null;

  // In 查前文矛盾 the passage selected in the text becomes the box's 「选中」 tag as it is selected. Clearing the selection leaves the
  // tag where it is (the author takes it off by hand), and a tag the author took off is not put back by the same selection.
  const pickedSeen = useRef(0);
  useEffect(() => {
    if (activeMode !== "check" || !picked || picked.nonce === pickedSeen.current) return;
    pickedSeen.current = picked.nonce;
    void Promise.resolve().then(() => setSelection(picked.text));
  }, [activeMode, picked]);

  const showChapter = chosen.chapter != null || (anchor.page !== "writing" && anchor.chapter_number != null && !dropped.chapter);
  const showCharacter = chosen.character != null || (Boolean(anchor.character_id) && !dropped.character);
  const contextFor = (picked: string): AssistantContextInput => {
    const chapter = chosen.chapter ?? (anchor.chapter_number != null && !(anchor.page !== "writing" && dropped.chapter) ? anchor.chapter_number : undefined);
    const character = chosen.character?.id ?? (anchor.character_id && !dropped.character ? anchor.character_id : undefined);
    return { page: anchor.page, ...(chapter != null ? { chapter_number: chapter } : {}), ...(picked ? { selection: picked } : {}), ...(character ? { character_id: character } : {}) };
  };

  const post = async (task: NewTask) => {
    setSending(true); setRefusal(""); setAgain(null); setStoppedNote(null);
    stopAfterPost.current = false;
    try {
      // A long task has its own address, and takes the sentence and the page (and chapter) only, and where it came from: the box judged
      // the sentence to be one ("route"), or the author chose the mode ("mode"); the server only counts it.
      const created = task.kind === "long"
        ? await json<AssistantTask>(`/projects/${projectId}/assistant/long-tasks`, "POST", {
          question: task.question, context: task.context, origin: task.routed && task.routed.source !== "manual" ? "route" : "mode" })
        : await json<AssistantTask>(`/projects/${projectId}/assistant/tasks`, "POST", {
          kind: task.kind, ...(task.question ? { question: task.question } : {}), context: task.context,
          ...(task.followUpOf ? { follow_up_of: task.followUpOf } : {}), ...(task.editedFrom ? { edited_from: task.editedFrom } : {}),
          ...(task.routed ? { routed: true, route_source: task.routed.source, routed_input: task.routed.input } : {}),
        });
      if (created.kind === "long") { noteLong(projectId, created.id, created.status); bridge.usageChanged(); }
      stick.current = false;
      pinned.current = created.id;
      lastCreated.current = created.id;
      setUnseen(false);
      setOffTopic(null); setElsewhere(null);
      setPending(null);
      setTasks((current) => [...(current ?? []), created]);
      setAsked((current) => [...current, created.id]);
      if (stopAfterPost.current) { stopAfterPost.current = false; void stop(created); }
      // The note about where the words go has been on screen for a first question; this device now remembers it was seen.
      try { window.localStorage.setItem(PRIVACY_SEEN, "1"); } catch { /* shown again next time */ }
      return true;
    } catch (cause) {
      setRefusal(refusalText(cause, visitor, task.kind));
      // A request that did not get through (no network, too slow, the server said to try again) can be sent again as it is.
      setAgain(!(cause as ApiFailure).code || (cause as ApiFailure).retryable ? { run: () => void post(task) } : null);
      return false;
    } finally { setSending(false); }
  };
  const afterSend = () => {
    setText(""); setSelection(""); setFollowUp(null); setRefine(null); setTip(""); setMode("auto");
    setChosen({ chapter: null, character: null });
    // The send button has just gone grey; keep the keyboard where the author is writing.
    field.current?.focus({ preventScroll: true });
  };
  const checkShort = (picked: string) => usage?.account_type === "registered" && !sample && usage.check_chars_remaining < (usage.assistant_task_chars ?? TASK_CHARS) + writtenChars(picked);
  const shortOfCheck = () => setRefusal(refusalText({ code: "character_quota_exceeded", details: { remaining: usage?.account_type === "registered" ? usage.check_chars_remaining : 0 } }, false));
  // 自动: the question goes into the conversation and the box empties at once; the server is asked which use the sentence asks for (a line in the
  // conversation says so meanwhile), then the task that use is starts. When nothing starts, the box gets its words back.
  const sendAuto = async () => {
    const input = text.trim();
    if (!input && !(selection && onWriting && !visitor)) return;
    const base: AssistantContextInput = { ...contextFor(selection), ...(refine ? { page: "writing" as const, issue_id: refine.issueId } : {}) };
    const kept = { text, selection, followUp, refine, chosen };
    const putBack = () => { setText(kept.text); setSelection(kept.selection); setFollowUp(kept.followUp); setRefine(kept.refine); setChosen(kept.chosen); };
    const abandon = (reason?: string) => { setPending(null); putBack(); if (reason) setRefusal(reason); };
    stick.current = true; pinned.current = null; setUnseen(false);
    setRouting(true); setRefusal(""); setAgain(null); setStoppedNote(null);
    setPending({ input, selection });
    afterSend();
    const ticket = { aborted: false, undo: () => { setPending(null); putBack(); setStoppedNote({ input, selection }); } };
    routeAbort.current = ticket;
    const verdict = await routeInput(projectId, input, base);
    // 停止 was pressed while the sentence was being judged: the send was already given up (ticket.undo), so nothing more happens.
    if (ticket.aborted) return;
    routeAbort.current = null;
    setRouting(false);
    if (verdict.route === "out_of_scope") {
      setOffTopic({ input, context: base }); setElsewhere(null); setPending(null);
      return;
    }
    if (verdict.route === "recap" && !onWriting) {
      setElsewhere(input); setOffTopic(null); setPending(null);
      return;
    }
    if (verdict.route === "recap" && recapReason) { abandon(recapReason); return; }
    if (verdict.route === "check_passage" && checkShort(kept.selection)) { abandon(); shortOfCheck(); return; }
    // A visitor has no long tasks: a sentence the judgement takes for one is asked as a question.
    const route = visitor && verdict.route === "long_task" ? "ask" : verdict.route;
    const chosenUse = taskFor(route, input, base, route === "ask" ? following?.id : null);
    const made = chosenUse ?? taskFor("ask", input, base, following?.id);
    if (!made) { abandon("先写下想问的话，再发送。"); return; }
    if (await post({ ...made, routed: { source: verdict.source, input } })) {
      if (verdict.timedOut) { const id = lastCreated.current; setTimedOut((current) => [...current, id]); }
    } else {
      // The box has its words back, so sending again is sending the box.
      setPending(null); putBack();
      setAgain((current) => (current ? { run: () => void submitNow.current() } : null));
    }
  };
  const submitNow = useRef<() => Promise<void>>(async () => undefined);
  const submit = async () => {
    if (blocked || routing || sending) return;
    if (activeMode === "recap") {
      if (recapReason) { setRefusal(recapReason); return; }
      if (await post({ kind: "recap", context: { page: "writing" } })) { setMode("auto"); setRefusal(""); }
      return;
    }
    if (activeMode === "check") {
      if (!selection) return;
      if (checkShort(selection)) { shortOfCheck(); return; }
      if (await post({ kind: "ask", question: CHECK_QUESTION, context: { ...contextFor(selection), intent: "check_selection" } })) afterSend();
      return;
    }
    if (activeMode === "change") {
      const question = text.trim();
      if (!question) return;
      if (await post({ kind: "change", question, context: contextFor(selection) })) afterSend();
      return;
    }
    if (activeMode === "long") {
      const made = taskFor("long_task", text.trim(), contextFor(""));
      if (!made) return;
      if (await post(made)) afterSend();
      return;
    }
    if (activeMode === "auto" && !refine?.manual) { await sendAuto(); return; }
    const question = text.trim();
    if (!question) return;
    const sent = refine
      ? await post({ kind: "fix_issue", question, context: { page: "writing", issue_id: refine.issueId } })
      : await post({ kind: "ask", question, context: contextFor(selection), followUpOf: following?.id ?? null });
    if (sent) afterSend();
  };
  useEffect(() => { submitNow.current = submit; });
  // The sentence the box judged not to be about the work, sent as a question after all.
  const askAnyway = () => {
    if (blocked) { setRefusal(blocked); return; }
    const made = offTopic ? taskFor("ask", offTopic.input, offTopic.context) : null;
    if (made) void post(made);
  };
  const retry = (task: AssistantTask) => {
    if (blocked) { setRefusal(blocked); return; }
    void post({ kind: task.kind, ...(task.question ? { question: task.question } : {}), context: { page: "writing", ...task.context } as AssistantContextInput, followUpOf: task.follow_up_of,
      ...(task.routed ? { routed: { source: task.route_source ?? "manual", input: task.routed_input ?? task.question ?? "" } } : {}) });
  };
  // 改成: a task the box chose the use of, sent as another use. While it waits or runs the server stops it, gives its characters back and
  // starts the new one in one step; once it is over it is the same sentence sent again, charged like any task.
  const changeUse = async (task: AssistantTask, use: Use) => {
    const input = (task.routed_input ?? task.question ?? "").trim();
    const next = taskFor(use, input, { page: anchor.page, ...task.context } as AssistantContextInput);
    if (!next) { setRefusal("这句话不能按这个用法发送。"); return; }
    if (!active(task)) {
      if (blocked) { setRefusal(blocked); return; }
      void post({ ...next, routed: { source: "manual", input } });
      return;
    }
    setSending(true); setRefusal("");
    try {
      const created = await json<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}/reroute`, "POST", { kind: use, context: next.context });
      stick.current = false;
      pinned.current = created.id;
      setUnseen(false);
      setTasks((current) => [...(current ?? []).map((item) => (item.id === task.id ? { ...item, status: "cancelled" as const, usage: { ...item.usage, chars_charged: 0 } } : item)), created]);
      setAsked((current) => [...current, created.id]);
      bridge.usageChanged();
    } catch (cause) { setRefusal(refusalText(cause, visitor)); } finally { setSending(false); }
  };
  const rerouting: RerouteControl = {
    options: (task) => {
      const uses: Use[] = [];
      if ((task.routed_input ?? task.question ?? "").trim()) uses.push("ask");
      if (onWriting && !recapReason && chapterNumber != null && chapterNumber > 1) uses.push("recap");
      if (onWriting && !visitor && task.context.selection) uses.push("check_passage");
      if (onWriting && task.context.issue_id) uses.push("fix_issue");
      if ((task.routed_input ?? task.question ?? "").trim()) uses.push("change");
      return uses;
    },
    change: (task, use) => void changeUse(task, use),
    cost,
    blocked,
  };
  // 停止 shows 已停止 at once (the task is marked stopped here before the server answers) and puts it back when the server says it could not.
  const stop = async (task: AssistantTask) => {
    setStopping(true);
    replace({ ...task, status: "cancelled" });
    try {
      const next = await json<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}/cancel`, "POST", {});
      replace(next);
      bridge.usageChanged();
    } catch (cause) { replace(task); setRefusal(labelError(cause)); } finally { setStopping(false); }
  };
  const stopFromBox = () => {
    if (routing && routeAbort.current) {
      const ticket = routeAbort.current;
      ticket.aborted = true; routeAbort.current = null;
      setRouting(false);
      ticket.undo();
      return;
    }
    const running = tasks?.find(active);
    if (running) { void stop(running); return; }
    if (sending) stopAfterPost.current = true;
  };
  const clear = async () => {
    setConfirmClear(false);
    try {
      await request(`/projects/${projectId}/assistant/tasks`, { method: "DELETE", headers: { "Idempotency-Key": crypto.randomUUID() } });
      setTasks([]); setFollowUp(null); setFollowDropped(null); setOffTopic(null); setElsewhere(null); setRefine(null); setRefusal(""); setUnseen(false);
    } catch (cause) { setRefusal(labelError(cause)); }
  };
  // The same question again: the new answer takes the old one's place, the old one folds under it.
  const regenerate = async (task: AssistantTask) => {
    if (blocked) { setRefusal(blocked); return; }
    setSending(true); setRefusal("");
    const result = await regenerateTask(projectId, task, visitor);
    setSending(false);
    if ("error" in result) { setRefusal(result.error); return; }
    stick.current = false;
    pinned.current = result.task.id;
    setUnseen(false);
    setTasks((current) => [...(current ?? []), result.task]);
  };
  // A question reworded and sent again: a new task that remembers which question it replaces.
  const resend = async (task: AssistantTask, question: string) =>
    post({ kind: "ask", question, context: { page: anchor.page, ...task.context } as AssistantContextInput, followUpOf: task.follow_up_of, editedFrom: task.id });

  // A picked passage arrives: either it becomes the question's context, or it is asked about at once.
  // A command arrives: a 写前回顾, a fix for one finding, or a check of a passage starts, or says why it cannot.
  const latest = useRef({ post, blocked, contextFor, usage, sample, material });
  useEffect(() => { latest.current = { post, blocked, contextFor, usage, sample, material }; });
  const refineOn = useRef<(issueId: string, number: number, manual?: boolean) => void>(() => undefined);
  useEffect(() => {
    if (!incoming || incoming.nonce === handled.current) return;
    handled.current = incoming.nonce;
    void Promise.resolve().then(() => {
      const { post: ask, blocked: reason, contextFor: build } = latest.current;
      setRefine(null);
      if (incoming.quick && !reason) { void ask({ kind: "ask", question: QUICK_QUESTION, context: build(incoming.text) }); return; }
      setSelection(incoming.text);
      if (incoming.quick) { setMode("ask"); setText(QUICK_QUESTION); setRefusal(reason); }
      field.current?.focus({ preventScroll: true });
    });
  }, [incoming]);
  useEffect(() => {
    if (!command || command.nonce === handledCommand.current) return;
    handledCommand.current = command.nonce;
    void Promise.resolve().then(() => {
      const { post: start, blocked: reason, contextFor: build, usage: allowance, sample: free, material: current } = latest.current;
      if (command.kind === "context") {
        const found = current.issues.find((item) => item.id === command.issueId);
        if (found) refineOn.current(found.id, found.number, false);
        return;
      }
      // A check also pays for the picked words (not on a sample work).
      const short = command.kind === "check" && !reason && !free && allowance?.account_type === "registered" && allowance.check_chars_remaining < (allowance.assistant_task_chars ?? TASK_CHARS) + writtenChars(command.text);
      if (reason || short) {
        setRefusal(reason || refusalText({ code: "character_quota_exceeded", details: { remaining: allowance?.account_type === "registered" ? allowance.check_chars_remaining : 0 } }, false));
        return;
      }
      setRefine(null);
      if (command.kind === "recap") void start({ kind: "recap", context: { page: "writing" } });
      else if (command.kind === "fix") void start({ kind: "fix_issue", context: { page: "writing", issue_id: command.issueId } });
      else void start({ kind: "ask", question: CHECK_QUESTION, context: { ...build(command.text), intent: "check_selection" } });
    });
  }, [command]);

  // 看对话: the task asked for is brought to the top of the conversation once the conversation has been read. A task older than the
  // latest 30 the conversation holds is read on its own (with the questions it follows and those that follow it) and put in its place;
  // one that was cleared is said to be.
  useEffect(() => {
    if (!focus || !tasks || focus.nonce === handledFocus.current) return;
    handledFocus.current = focus.nonce;
    stick.current = false; pinned.current = null;
    const { taskId, nonce } = focus;
    if (!tasks.some((task) => task.id === taskId)) {
      request<AssistantTask & { chain?: AssistantTask[] }>(`/projects/${projectId}/assistant/tasks/${taskId}?chain=1`).then(({ chain, ...task }) => {
        // The conversation's own scroll-to-task keeps the new entry in view (and does not call it a new answer).
        pinned.current = taskId;
        setTasks((current) => withTasks(current, [...(chain ?? []), task as AssistantTask]));
      }, (cause) => {
        if ((cause as ApiFailure).code === "resource_not_found") {
          quiet.current = performance.now() + 300;
          thread.current?.scrollTo({ top: 0 });
          setClearedNonce(nonce);
        } else setLoadError(labelError(cause));
      });
      return;
    }
    const box = thread.current;
    const target = box?.querySelector<HTMLElement>(`[data-task="${taskId}"]`);
    if (box && target) {
      quiet.current = performance.now() + 300;
      box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
    }
  }, [focus, tasks, projectId]);

  const openChapter = (number: number) => {
    onNavigate?.();
    const path = `/projects/${projectId}/sources`;
    if (window.location.pathname !== path) { go(`${path}#chapter-${number}`); return; }
    window.setTimeout(() => {
      const row = document.getElementById(`chapter-${number}`);
      if (!row) return;
      window.history.replaceState(window.history.state, "", `${path}#chapter-${number}`);
      row.scrollIntoView({ block: "center" });
      row.focus({ preventScroll: true });
    }, 60);
  };
  // 去原文: the chapter's text opens and the sentence is ringed once (for a fact, the passage it was taken from); when it cannot be found,
  // the chapter page says so.
  const locate = (source: AssistantSource) => {
    const target = locateTarget(source);
    if (!target) return;
    requestLocate(target.chapter, target.text, { missing: notFoundText(target.chapter) });
    onNavigate?.();
    if (writing) { writing.openChapter(target.chapter); return; }
    go(`/projects/${projectId}/workspace?chapter=${target.chapter}`);
  };
  const startRefine = (issueId: string, number: number, manual = true) => {
    setRefine({ issueId, number, manual }); setFollowUp(null); setSelection(""); setMode("auto");
    field.current?.focus({ preventScroll: true });
  };
  useEffect(() => { refineOn.current = startRefine; });
  const rerunRecap = () => {
    if (blocked) { setRefusal(blocked); return; }
    void post({ kind: "recap", context: { page: "writing" } });
  };
  const askStarter = (question: string) => {
    if (blocked) { setRefusal(off || RUNNING_NOW); return; }
    void post({ kind: "ask", question, context: contextFor("") });
  };
  const recall = () => {
    const last = [...(tasks ?? [])].reverse().find((task) => task.kind === "ask" && task.question && task.context.intent !== "check_selection");
    if (!last?.question) return;
    setText(last.question);
    window.requestAnimationFrame(() => { const box = field.current; if (box) { box.focus({ preventScroll: true }); box.setSelectionRange(box.value.length, box.value.length); } });
  };
  const jumpToLatest = () => {
    const box = thread.current;
    if (!box) return;
    stick.current = true; pinned.current = null; setUnseen(false);
    quiet.current = performance.now() + 400;
    box.scrollTo({ top: box.scrollHeight, behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  };

  // A fix for one finding reads that finding only: the chapter and the person in the box stay in view, greyed, and are not sent.
  const apart = refine ? { muted: true, note: "改法只看这一处" } : {};
  const chips: ComposeChip[] = [
    // On the writing page the box says which draft the assistant is looking at (not for 写前回顾, which reads only the chapters before it).
    ...(onWriting && chapterNumber != null && activeMode !== "recap" && !selection ? [{ key: "draft", label: `第 ${chapterNumber} 章草稿`, ...apart }] : []),
    ...(refine ? [{ key: "refine", label: `检查结果 · 第 ${refine.number} 处`, drop: () => setRefine(null) }] : []),
    ...(selection ? [{ key: "selection", label: `选中：「${clip(selection.replace(/\s+/g, " "), 18)}」`, quote: true, drop: () => setSelection("") }] : []),
    ...(showCharacter ? [{ key: "character", label: `人物 · ${chosen.character?.name ?? anchor.character_name ?? "这张人物卡"}`, ...apart, drop: () => { setChosen((all) => ({ ...all, character: null })); setDropped((all) => ({ ...all, character: true })); } }] : []),
    ...(showChapter ? [{ key: "chapter", label: `第 ${chosen.chapter ?? anchor.chapter_number} 章`, ...apart, drop: () => { setChosen((all) => ({ ...all, chapter: null })); setDropped((all) => ({ ...all, chapter: true })); } }] : []),
    ...(following ? [{ key: "follow", label: followLabel(following), drop: () => { setFollowUp(null); setFollowDropped(latestTask?.id ?? null); } }] : []),
  ];
  const pick: PlusPick = {
    chapters: material.chapters,
    characters: material.characters,
    issues: material.issues,
    issuesReason: material.issuesReason,
    onChapter: (number) => { setChosen((all) => ({ ...all, chapter: number })); setDropped((all) => ({ ...all, chapter: false })); field.current?.focus({ preventScroll: true }); },
    onCharacter: (id, name) => { setChosen((all) => ({ ...all, character: { id, name } })); setDropped((all) => ({ ...all, character: false })); field.current?.focus({ preventScroll: true }); },
    onIssue: (issueId, number) => startRefine(issueId, number, false),
    onSelectHint: () => setTip("在正文里选中一段文字，再点浮出来的「问助手」，它就会带进这次提问。"),
  };

  const placeholder = activeMode === "recap" ? RECAP_PLACEHOLDER : activeMode === "check" ? CHECK_PLACEHOLDER : activeMode === "change" ? CHANGE_PLACEHOLDER : activeMode === "long" ? LONG_PLACEHOLDER : refine ? REFINE_PLACEHOLDER : ASK_PLACEHOLDER;
  const hint = busy && !routing ? RUNNING_NOW
    : activeMode === "check" ? `约 ${formatCount(TASK_CHARS + writtenChars(selection))} 字`
      : activeMode === "recap" && recapReason ? recapReason
        : activeMode === "long" && usage?.account_type === "registered" && !sample ? `列计划约 ${formatCount(needed)} 字，开始另算` : cost;
  const hintMore = busy || !(asking || activeMode === "change" || activeMode === "long") ? "" : costMore;
  // In 自动 a picked passage alone is enough to send (it is checked); a sentence is needed for anything else.
  const canSend = !off && !busy && (asking ? Boolean(text.trim()) || (activeMode === "auto" && Boolean(selection) && onWriting && !visitor) : activeMode === "change" || activeMode === "long" ? Boolean(text.trim()) : activeMode === "recap" ? !recapReason : Boolean(selection));
  const changeMode = (next: Mode) => { setMode(next); };
  const edited = (next: string) => { setText(next); };
  const starters = tasks?.length === 0 && !visitorOutsideSample(usage, sample) ? starterQuestions({
    lastChapter: project.current_draft.chapter_number > 1 ? project.current_draft.chapter_number - 1 : null,
    characters: material.characters,
    draftBody: material.draftBody,
  }) : null;
  const groups = arrange(tasks ?? []);
  const empty = tasks !== null && tasks.length === 0 && !pending && !stoppedNote;
  const handlers: AskHandlers = {
    projectId, visitor, stopping, stop: (task) => void stop(task), retry, openChapter, locate, replace, blocked, off, readOnly: archived, asked, timedOut,
    merge: (items) => mergeChanges(setTasks, items),
    written: bridge.materialsChanged,
    goMaterials: () => { onNavigate?.(); go(`/projects/${projectId}/memory`); },
    followUp: (task) => { setFollowUp(task); setRefine(null); changeMode("auto"); field.current?.focus({ preventScroll: true }); },
    regenerate: (task) => void regenerate(task),
    resend,
  };

  return (
    <RerouteContext.Provider value={rerouting}>
    <LocateContext.Provider value={locate}>
    <div ref={root} className={`assistant${empty ? " assistant-empty" : ""}`} data-testid="assistant-thread" data-variant={variant}>
      {/* ⋯ sits in the panel's own head (the writing page's tab row, the panel's title row elsewhere): the bar takes no line of its own. */}
      <div className="a-bar">
        <Menu label="⋯" dots buttonLabel="助手：更多操作">
          <button type="button" role="menuitem" disabled={!tasks?.length} onClick={() => setConfirmClear(true)}>清空对话</button>
        </Menu>
      </div>
      <div ref={thread} className="a-thread" role="log" aria-live="polite" aria-label="助手对话"
        onWheel={() => { pinned.current = null; }} onTouchStart={() => { pinned.current = null; }}
        onScroll={(event) => {
          const box = event.currentTarget;
          if (performance.now() > quiet.current) {
            stick.current = box.scrollHeight - box.scrollTop - box.clientHeight < 80;
            if (stick.current) setUnseen(false);
          }
        }}>
        <button type="button" className="a-skip" onClick={() => field.current?.focus({ preventScroll: true })}>跳到输入框</button>
        {top}
        {privacy && !empty && <p className="a-privacy">使用助手会把相关片段发给 DeepSeek 处理，详见<a href="/privacy" target="_blank" rel="noopener noreferrer">隐私说明</a>。</p>}
        {legacy.length > 0 && <LegacyQuestions runs={legacy} go={(href) => { onNavigate?.(); go(href); }} />}
        {tasks === null && !loadError && <p className="a-quiet" role="status">正在读取对话…</p>}
        {focus && clearedNonce === focus.nonce && <p className="a-quiet" role="status" data-testid="assistant-cleared">这次对话已经清除。</p>}
        {loadError && <p className="a-note" role="alert">{loadError}</p>}
        {starters && (
          <Starters intro="助手会自己去查正文和你确认过的事实，每句回答都带着出处。只提建议，不改你的正文。"
            items={starters} ask={askStarter} recap={onWriting ? { run: rerunRecap, reason: blocked || recapReason, chapter: chapterNumber ?? null } : null} disabled={Boolean(off)} />
        )}
        {groups.map((group, index) => {
          const task = group.latest;
          // A question that follows the one just above hangs from it; any other turn starts under a thin line with its time.
          const above = index > 0 ? groups[index - 1] : null;
          const follow = Boolean(task.follow_up_of && above && [above.latest, ...above.older].some((item) => item.id === task.follow_up_of));
          const view = task.kind === "long"
            ? <LongView task={task} handlers={handlers} usage={usage} project={project} usageChanged={bridge.usageChanged}
              maxChapter={material.chapters.length ? Math.max(...material.chapters.map((chapter) => chapter.number)) : null} />
            : task.kind === "recap"
            ? <RecapView task={task} projectId={projectId} visitor={visitor} stopping={stopping} stop={() => void stop(task)} retry={() => retry(task)} locate={locate} rerun={onWriting ? rerunRecap : null} replace={replace} />
            : task.kind === "fix_issue"
              ? <FixView task={task} projectId={projectId} visitor={visitor} stopping={stopping} stop={() => void stop(task)} retry={() => retry(task)}
                openChapter={openChapter} locate={locate} link={writing} actions={actions} refine={onWriting ? startRefine : null} replace={replace} rise={asked.includes(task.id)} />
              : <AskGroup group={group} handlers={handlers} follow={follow} />;
          return (
            <Fragment key={group.id}>
              {above && !follow && <div className="a-turn-rule" role="separator"><time dateTime={task.created_at}>{turnTime(task.created_at)}</time></div>}
              {view}
            </Fragment>
          );
        })}
        {pending && (
          <div className="a-group a-pending" data-testid="route-pending">
            <div className="a-ask rise">{pending.selection && <span className="a-quote">{clip(pending.selection, 120)}</span>}{pending.input}</div>
            <div className="a-process" role="status"><span className="a-fold static"><ThreeSquares /> 正在判断用法…</span></div>
          </div>
        )}
        {stoppedNote && (
          <div className="a-group a-pending" data-testid="route-stopped">
            <div className="a-ask">{stoppedNote.selection && <span className="a-quote">{clip(stoppedNote.selection, 120)}</span>}{stoppedNote.input}</div>
            <p className="a-note" role="status">已停止，没有发出</p>
          </div>
        )}
        {offTopic && <OutOfScopeNote input={offTopic.input} asAsk={askAnyway} blocked={blocked} />}
        {elsewhere !== null && <RecapElsewhereNote input={elsewhere} cost={cost} blocked={blocked} open={() => { wantRecapOnArrival(); go(`/projects/${projectId}/workspace`); }} />}
        {announce && <p className="sr-only">{announce}</p>}
      </div>
      {unseen && <button type="button" className="a-jump" onClick={jumpToLatest}><span className="d" aria-hidden="true" />新回答 ↓</button>}
      {tip && <p className="a-tip" role="status">{tip}</p>}
      {refusal && refusal !== blocked && (
        <p className="a-block a-refused" role="alert">{refusal}{again && <> <button type="button" className="a-link a-retry" onClick={again.run}>重试</button></>}</p>
      )}
      <Composer chips={chips} text={text} setText={edited} placeholder={placeholder} fieldRef={field} maxLength={QUESTION_MAX} autoFocus={false}
        mode={activeMode} modes={modes} setMode={changeMode} pick={pick} writing={onWriting} off={off} running={Boolean(runningId) || routing || sending} stopping={stopping}
        stop={stopFromBox}
        canSend={canSend} send={() => void submit()} hint={hint} hintMore={hintMore} modeName={refine && (refine.manual || activeMode !== "auto") ? "帮我改这一处" : undefined}
        fixed={activeMode === "recap" || activeMode === "check"} recall={recall} unavailable={unavailable}
        usedUp={!archived && off ? { text: off, ...(visitor ? { action: { label: "注册", run: bridge.register } } : {}) } : null}
        note={empty ? <>提问时会把相关片段发给 DeepSeek 处理，详见<a href="/privacy" target="_blank" rel="noopener noreferrer">隐私说明</a>。</> : undefined} />
      {confirmClear && <ClearConfirm visitor={visitor} confirm={() => void clear()} cancel={() => { setConfirmClear(false); window.setTimeout(() => document.querySelector<HTMLElement>(".assistant .menu > summary")?.focus({ preventScroll: true }), 0); }} />}
    </div>
    </LocateContext.Provider>
    </RerouteContext.Provider>
  );
}

/** The old 资料页 问一问 history, kept readable. New questions go to the assistant. */
function LegacyQuestions({ runs, go }: { runs: WritingAnalysisRun[]; go: (href: string) => void }) {
  const link = (path: string | undefined) => (event: ReactMouseEvent<HTMLAnchorElement>) => { if (!path || event.metaKey || event.ctrlKey) return; event.preventDefault(); go(path); };
  return (
    <details className="a-legacy">
      <summary>以前在资料页问过的问题（只读）</summary>
      {runs.map((run) => (
        <section key={run.run_id} className="a-old" aria-label={run.question || "问题"}>
          <p className="a-old-q">{run.question || "问题"}<span> · {run.is_stale ? "正文改过，回答可能过时" : qaStatusLabel[run.analysis?.answer_status ?? ""] ?? stageLabel(run.status)} · {timeLabel(run.created_at)}</span></p>
          {["failed", "timed_out", "cancelled"].includes(run.status) && <p className="a-note">{labelRunFailure(run.error_code, "分析")}</p>}
          {run.analysis && (
            <>
              <p className="a-old-a">{run.analysis.answer}</p>
              {run.analysis.findings?.map((finding, index) => (
                <div key={index} className="a-old-f">
                  <span>{qaLayerLabel[finding.layer]} · {qaStanceLabel[finding.stance]}</span>
                  <p>{finding.text}</p>
                  {finding.evidence.map((source) => {
                    const path = (source as { source_path?: string }).source_path;
                    return <a key={`${source.source_type}:${source.source_id}`} href={path} onClick={link(path)}><strong>{readableKeys(source.label)}</strong> {source.excerpt}</a>;
                  })}
                </div>
              ))}
            </>
          )}
        </section>
      ))}
    </details>
  );
}

/** 清空对话: a small question laid over the panel, with its own focus. */
function ClearConfirm({ confirm, cancel, visitor }: { confirm: () => void; cancel: () => void; visitor: boolean }) {
  const first = useRef<HTMLButtonElement>(null);
  const last = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus({ preventScroll: true }); }, []);
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancel(); return; }
    if (event.key !== "Tab") return;
    if (event.shiftKey && document.activeElement === first.current) { event.preventDefault(); last.current?.focus({ preventScroll: true }); }
    else if (!event.shiftKey && document.activeElement === last.current) { event.preventDefault(); first.current?.focus({ preventScroll: true }); }
  };
  return (
    <div className="a-confirm" role="alertdialog" aria-modal="true" aria-labelledby="a-confirm-title" aria-describedby="a-confirm-body" onKeyDown={onKeyDown}>
      <div className="a-confirm-box">
        <h3 id="a-confirm-title">清空对话</h3>
        <p id="a-confirm-body">{visitor ? "清空后这部作品的对话不再显示。已用的次数不退。" : "清空后这部作品的对话不再显示。已用的字数不退。"}</p>
        <div className="a-confirm-actions">
          <button ref={first} type="button" className="a-link" onClick={cancel}>取消</button>
          <button ref={last} type="button" className="a-danger" onClick={confirm}>清空</button>
        </div>
      </div>
    </div>
  );
}

/** Where the dock sits: the page is pushed aside when the window is wide enough for the page and the panel together (1440 on the writing page,
    where the draft, the findings and the assistant are side by side; 1200 elsewhere), and the panel lies over the page's right edge when it is not. */
export type DockMode = "push" | "overlay";
export const dockModeFor = (writing: boolean): DockMode => (typeof window !== "undefined" && window.innerWidth >= (writing ? 1440 : 1200) ? "push" : "overlay");
function useDockMode(writing: boolean): DockMode {
  const [mode, setMode] = useState<DockMode>(() => dockModeFor(writing));
  useEffect(() => {
    const update = () => setMode(dockModeFor(writing));
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [writing]);
  return mode;
}

/** The assistant, one panel for every page: docked at the right under the top bar, about 400px wide. Open, it pushes the page aside (the root
    element says so for the stylesheet); in a narrower window it lies over the page's edge instead. The same button, the key Ctrl + / and
    Esc close it. `open` false keeps the thread alive (a running task goes on) but hides the panel. */
export function AssistantDock({ open, close, beta = false, quiet = false, ...thread }: Omit<ThreadProps, "variant"> & { open: boolean; close: () => void; beta?: boolean; quiet?: boolean }) {
  const mode = useDockMode(Boolean(thread.writing));
  const frame = useRef<HTMLElement>(null);
  useEffect(() => {
    if (!open) return;
    const root = document.documentElement;
    root.dataset.dock = mode;
    const fit = () => root.style.setProperty("--dock-top", `${document.querySelector<HTMLElement>(".topbar")?.offsetHeight ?? 64}px`);
    fit();
    window.addEventListener("resize", fit);
    // Only what this panel set is taken back: another page's panel may already have said otherwise.
    return () => { if (root.dataset.dock === mode) delete root.dataset.dock; root.style.removeProperty("--dock-top"); window.removeEventListener("resize", fit); };
  }, [open, mode]);
  // Opened, the cursor is in the box (V: the author does not walk past the whole conversation).
  useEffect(() => {
    if (!open || quiet) return;
    const timer = window.setTimeout(() => frame.current?.querySelector<HTMLTextAreaElement>('textarea[aria-label="向助手提问"]')?.focus({ preventScroll: true }), 40);
    return () => window.clearTimeout(timer);
  }, [open, quiet]);
  return (
    <aside ref={frame} id="assistant-dock" className={`a-dock ${mode}`} aria-label="助手" hidden={!open} data-testid="assistant-dock">
      <header className="a-dock-head">
        <h2>助手{beta && <span className="a-beta">测试版</span>}</h2>
        <button type="button" className="a-link" aria-label="关闭助手" onClick={close}>收起<kbd> Esc</kbd></button>
      </header>
      <AssistantThread {...thread} variant="dock" onNavigate={() => { thread.onNavigate?.(); if (mode === "overlay") close(); }} />
    </aside>
  );
}

/** The assistant on the writing page: the 助手 tab of the right column, in the column's place instead of a panel over the page. Built always
    (hidden while the column shows the findings or is folded away), so a running task goes on. */
export function AssistantPane({ open, quiet = false, ...thread }: Omit<ThreadProps, "variant"> & { open: boolean; quiet?: boolean }) {
  const frame = useRef<HTMLElement>(null);
  // Opened, the cursor is in the box, as in the panel.
  useEffect(() => {
    if (!open || quiet) return;
    const timer = window.setTimeout(() => frame.current?.querySelector<HTMLTextAreaElement>('textarea[aria-label="向助手提问"]')?.focus({ preventScroll: true }), 40);
    return () => window.clearTimeout(timer);
  }, [open, quiet]);
  return (
    <section ref={frame} id="assistant-dock" className="a-pane" role="tabpanel" aria-labelledby="side-tab-assistant" aria-label="助手" hidden={!open} data-testid="assistant-dock">
      <AssistantThread {...thread} variant="dock" />
    </section>
  );
}

/** What the author selected, without the finding badges the editor draws among the words. */
function selectedText(range: Range): string {
  const fragment = range.cloneContents();
  fragment.querySelectorAll('[contenteditable="false"], .sr-only').forEach((node) => node.remove());
  const block = Array.from(fragment.childNodes).some((node) => node instanceof Element && /^(P|DIV|LI|UL|OL|BLOCKQUOTE|H[1-6])$/.test(node.tagName));
  const text = Array.from(fragment.childNodes).map((node) => node.textContent ?? "").join(block ? "\n" : "");
  return text.replace(/[ \t]*\n[ \t]*/g, "\n").trim();
}

/** A small black bar over text picked with 4–600 characters: 问助手 carries it into a question, 前面怎么写的 asks at once,
    and (where the text is the author's own draft) 查前文矛盾 has the passage checked against what came before. The bar sits under the picked
    words; it goes above them only when that is clear of the line above (it would cover words of the previous paragraph), and it never sticks out of the
    text column's left edge. `blocked` is why no question can be asked now (the allowance is used up): the buttons are greyed and say so when pointed at. */
export function SelectionToolbar({ selector, onAsk, onQuick, onSelect, check, blocked = "" }: {
  selector: string;
  onAsk: (text: string) => void;
  onQuick: (text: string) => void;
  /** Told what is selected (text of 4–600 characters) as it is selected, and null when the selection is gone. */
  onSelect?: (text: string | null) => void;
  /** The third button; leave it out where it makes no sense (a visitor, a written chapter). `remaining` is the day's characters left, null when not counted. */
  check?: { run: (text: string) => void; remaining: number | null; free?: boolean };
  blocked?: string;
}) {
  const [shown, setShown] = useState<{ text: string; x: number; y: number; above: boolean; edge: number } | null>(null);
  const [width, setWidth] = useState(0);
  const bar = useRef<HTMLDivElement>(null);
  const told = useRef(onSelect);
  useEffect(() => { told.current = onSelect; });
  useEffect(() => {
    let frame = 0;
    let pointerDown = false;
    const within = (node: Node | null) => Boolean(node && (node instanceof Element ? node : node.parentElement)?.closest(selector));
    const evaluate = () => {
      frame = 0;
      if (pointerDown) return;
      const selection = window.getSelection();
      if (!selection || selection.rangeCount === 0 || selection.isCollapsed) {
        told.current?.(null);
        if (!bar.current?.contains(document.activeElement)) setShown(null);
        return;
      }
      if (!within(selection.anchorNode) || !within(selection.focusNode)) {
        if (!bar.current?.contains(document.activeElement)) setShown(null);
        return;
      }
      const range = selection.getRangeAt(0);
      const text = selectedText(range);
      const count = [...text].length;
      if (count < 4 || count > 600) { told.current?.(null); setShown(null); return; }
      told.current?.(text);
      const rects = Array.from(range.getClientRects());
      const first = rects[0] ?? range.getBoundingClientRect();
      const last = rects[rects.length - 1] ?? first;
      const topbar = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 64;
      // Above the words only if there is room under the page's top bar and the editor's own tool row, and nothing of the text lies where the bar would
      // go (the line above, or the paragraph before); otherwise below, where the words end.
      const column = document.querySelector(selector);
      const tools = column?.closest(".draft")?.querySelector(".draft-tools")?.getBoundingClientRect();
      const ceiling = Math.max(topbar + 8, tools ? tools.bottom + 4 : 0);
      const barTop = first.top - 8 - 32;
      const start = range.startContainer instanceof Element ? range.startContainer : range.startContainer.parentElement;
      const startBlock = start?.closest("p, li, h1, h2, h3, h4, blockquote") ?? null;
      const covered = column
        ? Array.from(column.querySelectorAll("p, li, h1, h2, h3, h4, blockquote")).some((block) => {
          const box = block.getBoundingClientRect();
          if (box.height <= 0 || box.bottom <= barTop || box.top >= first.top - 8) return false;
          // The paragraph the words are in only covers them when they are not on its first line.
          if (startBlock && (block === startBlock || block.contains(startBlock))) return first.top - box.top > (parseFloat(getComputedStyle(block).lineHeight) || 30) * 0.9;
          return true;
        })
        : false;
      const above = barTop >= ceiling && !covered;
      const edge = Math.max(8, column ? column.getBoundingClientRect().left : 8);
      setShown({ text, x: (first.left + last.right) / 2, y: above ? first.top - 8 : last.bottom + 8, above, edge });
    };
    const schedule = () => { if (!frame) frame = window.requestAnimationFrame(evaluate); };
    const hide = () => setShown(null);
    const down = (event: PointerEvent) => {
      if (bar.current?.contains(event.target as Node)) return;
      pointerDown = true;
      setShown(null);
    };
    const up = () => { pointerDown = false; schedule(); };
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setShown((current) => {
        if (current && bar.current?.contains(document.activeElement)) document.querySelector<HTMLElement>(selector)?.focus({ preventScroll: true });
        return null;
      });
    };
    document.addEventListener("selectionchange", schedule);
    document.addEventListener("pointerdown", down, true);
    document.addEventListener("pointerup", up, true);
    document.addEventListener("keydown", key);
    window.addEventListener("scroll", hide, true);
    return () => {
      window.cancelAnimationFrame(frame);
      document.removeEventListener("selectionchange", schedule);
      document.removeEventListener("pointerdown", down, true);
      document.removeEventListener("pointerup", up, true);
      document.removeEventListener("keydown", key);
      window.removeEventListener("scroll", hide, true);
    };
  }, [selector]);
  // The bar is centred on the words, then kept inside the text column's left edge and the window's right.
  useLayoutEffect(() => { if (shown && bar.current) setWidth(bar.current.offsetWidth); }, [shown]);
  if (!shown) return null;
  const left = Math.max(shown.edge, Math.min(shown.x - width / 2, window.innerWidth - width - 8));
  return (
    <div ref={bar} className={`a-selpop${shown.above ? " above" : ""}`} role="toolbar" aria-label="对选中的文字提问" style={{ left, top: shown.y }}
      onMouseDown={(event) => event.preventDefault()}>
      <button type="button" className="first" disabled={Boolean(blocked)} title={blocked || undefined} aria-label="问助手：把选中的文字带进提问" onClick={() => { onAsk(shown.text); setShown(null); }}>问助手</button>
      <button type="button" disabled={Boolean(blocked)} title={blocked || undefined} aria-label="前面怎么写的：直接问这段前面怎么写的" onClick={() => { onQuick(shown.text); setShown(null); }}>前面怎么写的</button>
      {check && (() => {
        const cost = TASK_CHARS + writtenChars(shown.text);
        const short = check.remaining !== null && check.remaining < cost;
        const label = check.free ? "查前文矛盾" : `查前文矛盾 · 约 ${formatCount(cost)} 字`;
        return (
          <button type="button" disabled={short || Boolean(blocked)} title={blocked || (short ? "24 小时内可检查的字数不够这次检查" : undefined)}
            aria-label={`查前文矛盾：检查这段和前文有没有矛盾${check.free ? "，示例作品不计字数" : `，约 ${formatCount(cost)} 字`}`} onClick={() => { check.run(shown.text); setShown(null); }}>{label}</button>
        );
      })()}
    </div>
  );
}
