"use client";

// The built-in assistant (v1.8.0). One conversation per work, kept on the server: the author asks, the
// assistant looks things up in the work itself and answers with where each sentence comes from. It only
// advises; nothing here writes to the draft or the materials except through the editor, one change at a time,
// when the author says so. The same AssistantThread is used in three places: the writing page's right
// column (and its phone pane), and a drawer opened from the top bar on the other pages. A pop-up bar over
// selected text brings a passage into a question. Four uses live in it: 问作品, 写前回顾, 帮我改这一处 and 查前文矛盾; the box's
// 自动 mode (the default) judges which one a sentence asks for, and the task it starts says so and can be changed.
import {
  createContext,
  type KeyboardEvent as ReactKeyboardEvent,
  type MouseEvent as ReactMouseEvent,
  type ReactNode,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import { json, labelError, labelRunFailure, request, type ApiFailure } from "../../api";
import type { AssistantContextInput, AssistantPage, AssistantSource, AssistantTask, Project, WritingAnalysisRun } from "../../model";
import { qaLayerLabel, qaStanceLabel, qaStatusLabel, readableKeys, stageLabel, timeLabel } from "../labels";
import { type CheckUsage, clip, formatCount, Menu, useFocusTrap, useScrollLock, writtenChars } from "../ui";
import { regenerateTask } from "./assistant-answer";
import { Composer, type ComposeChip, type Mode, type PlusPick } from "./assistant-compose";
import { FixView, type ProposalActions, useProposalActions, type WritingLink } from "./assistant-fix";
import { notFoundText, requestLocate } from "./assistant-locate";
import { active, isRecap, locateTarget, refusalText, RUNNING_NOW, spokenResult, TASK_CHARS, VISITOR_USED_UP } from "./assistant-parts";
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
  | { nonce: number; kind: "check"; text: string };
type Bridge = {
  setAnchor: (anchor: AssistantAnchor | null) => void;
  openDrawer: (incoming?: Omit<Incoming, "nonce">) => void;
  usageChanged: () => void;
};
/** The app provides it; pages tell it where the author is, and ask it to open the drawer. */
export const AssistantBridge = createContext<Bridge>({ setAnchor: () => undefined, openDrawer: () => undefined, usageChanged: () => undefined });

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
const PRIVACY_SEEN = "story-continuity:assistant-privacy-seen";

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
  variant: "column" | "drawer";
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

/** The tag 接着上一问 says which follow-up the next question would be, and how many are left. */
const followLabel = (task: AssistantTask) => {
  const number = (task.follow_up_depth ?? 0) + 1;
  return `接着上一问 · 第 ${number} 次追问，${number >= 2 ? "这是最后一次" : "还能再问 1 次"}`;
};
/** A finished question that a further question can follow (a recap, a fix, a check and an off-topic reply cannot be followed). */
const followable = (task: AssistantTask) =>
  task.kind === "ask" && task.status === "completed" && task.context.intent !== "check_selection" && Boolean(task.answer) && !isRecap(task.answer)
  && (task.answer as { status?: string }).status !== "out_of_scope" && (task.follow_up_depth ?? 0) < 2;

export function AssistantThread({ project, anchor, usage, visitor, go, incoming, command, picked, writing, material = NO_MATERIAL, top, topKey, onNavigate, variant }: ThreadProps) {
  const projectId = project.id;
  const bridge = useContext(AssistantBridge);
  const [tasks, setTasks] = useState<AssistantTask[] | null>(null);
  const [loadError, setLoadError] = useState("");
  const [legacy, setLegacy] = useState<WritingAnalysisRun[]>([]);
  const [text, setText] = useState("");
  const [mode, setMode] = useState<Mode>("auto");
  const [selection, setSelection] = useState("");
  const [followUp, setFollowUp] = useState<AssistantTask | null>(null);
  // The task whose automatic 接着上一问 tag the author took off: that answer is not followed unless asked for with its 接着问 button.
  const [followDropped, setFollowDropped] = useState<string | null>(null);
  // 自动: the sentence is being judged, and what the judgement was (kept on the mode button until the author changes the box).
  const [routing, setRouting] = useState(false);
  const [routedAs, setRoutedAs] = useState("");
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
  const announced = useRef(new Set<string>());
  const signature = useRef("");

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

  // New text keeps the view at the bottom, unless the author has scrolled up to read (then 「新回答 ↓」 says there is more);
  // a new task keeps its own top in view.
  useEffect(() => {
    const box = thread.current;
    if (!box) return;
    const now = (tasks ?? []).map((task) => `${task.id}:${task.status}:${task.steps.length}:${task.answer ? 1 : 0}`).join("|");
    const changed = now !== signature.current;
    signature.current = now;
    const id = pinned.current;
    const target = id ? box.querySelector<HTMLElement>(`[data-task="${id}"]`) : null;
    if (target) {
      quiet.current = performance.now() + 150;
      box.scrollTop += target.getBoundingClientRect().top - box.getBoundingClientRect().top - 8;
      if (!active(tasks?.find((task) => task.id === id) ?? { status: "completed" } as AssistantTask)) pinned.current = null;
    } else if (stick.current) {
      quiet.current = performance.now() + 150;
      box.scrollTop = box.scrollHeight;
    } else if (changed && !id && tasks && tasks.length > 0) {
      void Promise.resolve().then(() => setUnseen(true));
    }
  });

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
  const needed = usage?.account_type === "registered" ? usage.assistant_task_chars ?? TASK_CHARS : 0;
  const shortOfChars = usage?.account_type === "registered" && usage.check_chars_remaining < needed;
  const outOfTasks = usage?.account_type === "visitor" && usage.assistant_tasks_remaining !== undefined && usage.assistant_tasks_remaining <= 0;
  // The box is used up for good (until the allowance comes back): it says why, inside itself.
  const off = archived ? "作品已归档，只能浏览。"
    : shortOfChars ? `${refusalText({ code: "character_quota_exceeded", details: { remaining: usage?.account_type === "registered" ? usage.check_chars_remaining : 0 } }, false)}用掉的额度 24 小时后陆续返还。`
      : outOfTasks ? VISITOR_USED_UP
        : "";
  const blocked = off || (busy && !routing ? RUNNING_NOW : "");
  const cost = usage?.account_type === "registered" ? `约 ${formatCount(needed)} 字`
    : usage?.account_type === "visitor" && usage.assistant_tasks_remaining !== undefined ? `今天还可以问 ${usage.assistant_tasks_remaining} 次` : "";
  // What is left today goes after the cost when the line has room for it, and into its title when it has not.
  const costMore = usage?.account_type === "registered" ? `今天还剩 ${formatCount(usage.check_chars_remaining)} 字` : "";

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
  const replace = (next: AssistantTask) => setTasks((current) => current && current.map((task) => (task.id === next.id ? next : task)));

  const onWriting = variant === "column" && Boolean(writing);
  const chapterNumber = anchor.page === "writing" ? anchor.chapter_number : undefined;
  const recapReason = chapterNumber != null && chapterNumber <= 1 ? "第一章前面没有内容可以回顾" : writing?.draft.dirty ? "等草稿保存后再回顾" : "";
  const modes: Mode[] = onWriting ? (visitor ? ["auto", "ask", "recap"] : ["auto", "ask", "recap", "check"]) : ["auto", "ask"];
  const activeMode: Mode = modes.includes(mode) ? mode : "auto";
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
    setSending(true); setRefusal("");
    try {
      const created = await json<AssistantTask>(`/projects/${projectId}/assistant/tasks`, "POST", {
        kind: task.kind, ...(task.question ? { question: task.question } : {}), context: task.context,
        ...(task.followUpOf ? { follow_up_of: task.followUpOf } : {}), ...(task.editedFrom ? { edited_from: task.editedFrom } : {}),
        ...(task.routed ? { routed: true, route_source: task.routed.source, routed_input: task.routed.input } : {}),
      });
      stick.current = false;
      pinned.current = created.id;
      setUnseen(false);
      setOffTopic(null); setElsewhere(null);
      setTasks((current) => [...(current ?? []), created]);
      setAsked((current) => [...current, created.id]);
      // The note about where the words go has been on screen for a first question; this device now remembers it was seen.
      try { window.localStorage.setItem(PRIVACY_SEEN, "1"); } catch { /* shown again next time */ }
      return true;
    } catch (cause) {
      setRefusal(refusalText(cause, visitor, task.kind));
      return false;
    } finally { setSending(false); }
  };
  const afterSend = () => {
    setText(""); setSelection(""); setFollowUp(null); setRefine(null); setTip(""); setRoutedAs(""); setMode("auto");
    setChosen({ chapter: null, character: null });
    // The send button has just gone grey; keep the keyboard where the author is writing.
    field.current?.focus();
  };
  const checkShort = (picked: string) => usage?.account_type === "registered" && usage.check_chars_remaining < (usage.assistant_task_chars ?? TASK_CHARS) + writtenChars(picked);
  const shortOfCheck = () => setRefusal(refusalText({ code: "character_quota_exceeded", details: { remaining: usage?.account_type === "registered" ? usage.check_chars_remaining : 0 } }, false));
  // 自动: ask the server which use the sentence asks for (the mode button says so meanwhile), then start the task that use is, at once.
  const sendAuto = async () => {
    const input = text.trim();
    if (!input && !(selection && onWriting && !visitor)) return;
    const base: AssistantContextInput = { ...contextFor(selection), ...(refine ? { page: "writing" as const, issue_id: refine.issueId } : {}) };
    setRouting(true); setRoutedAs(""); setRefusal("");
    const verdict = await routeInput(projectId, input, base);
    setRouting(false);
    if (verdict.route === "out_of_scope") {
      setOffTopic({ input, context: base }); setElsewhere(null);
      afterSend();
      setRoutedAs("与作品无关");
      return;
    }
    setRoutedAs(USE_LABEL[verdict.route]);
    if (verdict.route === "recap" && !onWriting) {
      setElsewhere(input); setOffTopic(null);
      afterSend();
      setRoutedAs(USE_LABEL.recap);
      return;
    }
    if (verdict.route === "recap" && recapReason) { setRefusal(recapReason); return; }
    if (verdict.route === "check_passage" && checkShort(selection)) { shortOfCheck(); return; }
    const chosen = taskFor(verdict.route, input, base, verdict.route === "ask" ? following?.id : null);
    const made = chosen ?? taskFor("ask", input, base, following?.id);
    if (!made) { setRefusal("先写下想问的话，再发送。"); return; }
    const label = USE_LABEL[chosen ? verdict.route : "ask"];
    if (await post({ ...made, routed: { source: verdict.source, input } })) { afterSend(); setRoutedAs(label); }
  };
  const submit = async () => {
    if (blocked) return;
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
    if (activeMode === "auto" && !refine?.manual) { await sendAuto(); return; }
    const question = text.trim();
    if (!question) return;
    const sent = refine
      ? await post({ kind: "fix_issue", question, context: { page: "writing", issue_id: refine.issueId } })
      : await post({ kind: "ask", question, context: contextFor(selection), followUpOf: following?.id ?? null });
    if (sent) afterSend();
  };
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
      return uses;
    },
    change: (task, use) => void changeUse(task, use),
    cost,
    blocked,
  };
  const stop = async (task: AssistantTask) => {
    setStopping(true);
    try {
      const next = await json<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}/cancel`, "POST", {});
      replace(next);
      bridge.usageChanged();
    } catch (cause) { setRefusal(labelError(cause)); } finally { setStopping(false); }
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
  const latest = useRef({ post, blocked, contextFor, usage });
  useEffect(() => { latest.current = { post, blocked, contextFor, usage }; });
  useEffect(() => {
    if (!incoming || incoming.nonce === handled.current) return;
    handled.current = incoming.nonce;
    void Promise.resolve().then(() => {
      const { post: ask, blocked: reason, contextFor: build } = latest.current;
      setRefine(null);
      if (incoming.quick && !reason) { void ask({ kind: "ask", question: QUICK_QUESTION, context: build(incoming.text) }); return; }
      setSelection(incoming.text);
      if (incoming.quick) { setMode("ask"); setText(QUICK_QUESTION); setRefusal(reason); }
      field.current?.focus();
    });
  }, [incoming]);
  useEffect(() => {
    if (!command || command.nonce === handledCommand.current) return;
    handledCommand.current = command.nonce;
    void Promise.resolve().then(() => {
      const { post: start, blocked: reason, contextFor: build, usage: allowance } = latest.current;
      // A check also pays for the picked words.
      const short = command.kind === "check" && !reason && allowance?.account_type === "registered" && allowance.check_chars_remaining < (allowance.assistant_task_chars ?? TASK_CHARS) + writtenChars(command.text);
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
    setRefine({ issueId, number, manual }); setFollowUp(null); setSelection(""); setMode("auto"); setRoutedAs("");
    field.current?.focus();
  };
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
    window.requestAnimationFrame(() => { const box = field.current; if (box) { box.focus(); box.setSelectionRange(box.value.length, box.value.length); } });
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
    onChapter: (number) => { setChosen((all) => ({ ...all, chapter: number })); setDropped((all) => ({ ...all, chapter: false })); field.current?.focus(); },
    onCharacter: (id, name) => { setChosen((all) => ({ ...all, character: { id, name } })); setDropped((all) => ({ ...all, character: false })); field.current?.focus(); },
    onIssue: (issueId, number) => startRefine(issueId, number, false),
    onSelectHint: () => setTip("在正文里选中一段文字，再点浮出来的「问助手」，它就会带进这次提问。"),
  };

  const placeholder = activeMode === "recap" ? RECAP_PLACEHOLDER : activeMode === "check" ? CHECK_PLACEHOLDER : refine ? REFINE_PLACEHOLDER : ASK_PLACEHOLDER;
  const hint = busy && !routing ? RUNNING_NOW
    : activeMode === "check" ? `约 ${formatCount(TASK_CHARS + writtenChars(selection))} 字`
      : activeMode === "recap" && recapReason ? recapReason : cost;
  const hintMore = busy || !asking ? "" : costMore;
  // In 自动 a picked passage alone is enough to send (it is checked); a sentence is needed for anything else.
  const canSend = !off && !busy && (asking ? Boolean(text.trim()) || (activeMode === "auto" && Boolean(selection) && onWriting && !visitor) : activeMode === "recap" ? !recapReason : Boolean(selection));
  const modeText = activeMode !== "auto" || refine?.manual ? undefined : routing ? "判断中…" : routedAs ? `自动 · ${routedAs}` : undefined;
  const changeMode = (next: Mode) => { setMode(next); setRoutedAs(""); };
  const edited = (next: string) => { setText(next); setRoutedAs(""); };
  const starters = tasks?.length === 0 ? starterQuestions({
    lastChapter: project.current_draft.chapter_number > 1 ? project.current_draft.chapter_number - 1 : null,
    characters: material.characters,
    draftBody: material.draftBody,
  }) : null;
  const groups = arrange(tasks ?? []);
  const handlers: AskHandlers = {
    projectId, visitor, stopping, stop: (task) => void stop(task), retry, openChapter, locate, replace, blocked, readOnly: archived, asked,
    followUp: (task) => { setFollowUp(task); setRefine(null); changeMode("auto"); field.current?.focus(); },
    regenerate: (task) => void regenerate(task),
    resend,
  };

  return (
    <RerouteContext.Provider value={rerouting}>
    <div ref={root} className={`assistant assistant-${variant}`} data-testid="assistant-thread">
      <div className="a-bar">
        <span className="a-bar-note">只提建议，不改你的正文</span>
        <Menu label="更多" buttonLabel="助手：更多操作">
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
        <button type="button" className="a-skip" onClick={() => field.current?.focus()}>跳到输入框</button>
        {top}
        {privacy && <p className="a-privacy">使用助手会把相关片段发给 DeepSeek 处理，详见<a href="/privacy" target="_blank" rel="noopener noreferrer">隐私说明</a>。</p>}
        {legacy.length > 0 && <LegacyQuestions runs={legacy} go={(href) => { onNavigate?.(); go(href); }} />}
        {tasks === null && !loadError && <p className="a-quiet" role="status">正在读取对话…</p>}
        {loadError && <p className="a-note" role="alert">{loadError}</p>}
        {starters && (
          <Starters intro="问这部作品里的人、事、物。助手会自己去查正文和已确认的事实，每句回答都带着出处。"
            items={starters} ask={askStarter} recap={onWriting ? { run: rerunRecap, reason: blocked || recapReason } : null} />
        )}
        {groups.map((group) => {
          const task = group.latest;
          if (task.kind === "recap") return <RecapView key={group.id} task={task} projectId={projectId} visitor={visitor} stopping={stopping} stop={() => void stop(task)} retry={() => retry(task)} openChapter={openChapter} rerun={onWriting ? rerunRecap : null} replace={replace} />;
          if (task.kind === "fix_issue") {
            return <FixView key={group.id} task={task} projectId={projectId} visitor={visitor} stopping={stopping} stop={() => void stop(task)} retry={() => retry(task)}
              openChapter={openChapter} locate={locate} link={writing} actions={actions} refine={onWriting ? startRefine : null} replace={replace} rise={asked.includes(task.id)} />;
          }
          return <AskGroup key={group.id} group={group} handlers={handlers} />;
        })}
        {offTopic && <OutOfScopeNote input={offTopic.input} asAsk={askAnyway} blocked={blocked} />}
        {elsewhere !== null && <RecapElsewhereNote input={elsewhere} cost={cost} blocked={blocked} open={() => { wantRecapOnArrival(); go(`/projects/${projectId}/workspace`); }} />}
        {announce && <p className="sr-only">{announce}</p>}
      </div>
      {unseen && <button type="button" className="a-jump" onClick={jumpToLatest}><span className="d" aria-hidden="true" />新回答 ↓</button>}
      {tip && <p className="a-tip" role="status">{tip}</p>}
      {refusal && refusal !== blocked && <p className="a-block a-refused" role="alert">{refusal}</p>}
      <Composer chips={chips} text={text} setText={edited} placeholder={placeholder} fieldRef={field} maxLength={QUESTION_MAX} autoFocus={variant === "drawer"}
        mode={activeMode} modes={modes} setMode={changeMode} pick={pick} writing={onWriting} off={off} running={Boolean(runningId)} stopping={stopping}
        stop={() => { const running = tasks?.find(active); if (running) void stop(running); }}
        canSend={canSend} send={() => void submit()} hint={hint} hintMore={hintMore} modeName={refine && (refine.manual || activeMode !== "auto") ? "帮我改这一处" : undefined} modeText={modeText}
        fixed={activeMode === "recap" || activeMode === "check"} recall={recall} />
      {confirmClear && <ClearConfirm confirm={() => void clear()} cancel={() => { setConfirmClear(false); window.setTimeout(() => document.querySelector<HTMLElement>(".assistant .menu > summary")?.focus(), 0); }} />}
    </div>
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
function ClearConfirm({ confirm, cancel }: { confirm: () => void; cancel: () => void }) {
  const first = useRef<HTMLButtonElement>(null);
  const last = useRef<HTMLButtonElement>(null);
  useEffect(() => { first.current?.focus(); }, []);
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (event.key === "Escape") { event.preventDefault(); event.stopPropagation(); cancel(); return; }
    if (event.key !== "Tab") return;
    if (event.shiftKey && document.activeElement === first.current) { event.preventDefault(); last.current?.focus(); }
    else if (!event.shiftKey && document.activeElement === last.current) { event.preventDefault(); first.current?.focus(); }
  };
  return (
    <div className="a-confirm" role="alertdialog" aria-modal="true" aria-labelledby="a-confirm-title" aria-describedby="a-confirm-body" onKeyDown={onKeyDown}>
      <div className="a-confirm-box">
        <h3 id="a-confirm-title">清空对话</h3>
        <p id="a-confirm-body">清空后这部作品的对话不再显示。已用的字数不退。</p>
        <div className="a-confirm-actions">
          <button ref={first} type="button" className="a-link" onClick={cancel}>取消</button>
          <button ref={last} type="button" className="a-danger" onClick={confirm}>清空</button>
        </div>
      </div>
    </div>
  );
}

/** The drawer other pages open from the top bar: the same thread, on the right, full screen on a phone. */
export function AssistantDrawer({ close, beta = false, ...thread }: ThreadProps & { close: () => void; beta?: boolean }) {
  useScrollLock();
  const { ref, onKeyDown } = useFocusTrap<HTMLElement>(close);
  return (
    <div className="layer layer-drawer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <aside ref={ref} className="drawer assistant-drawer" role="dialog" aria-modal="true" aria-label="助手" onKeyDown={onKeyDown}>
        <header className="a-drawer-head">
          <h2>助手{beta && <span className="a-beta">测试版</span>}</h2>
          <button type="button" className="a-link" aria-label="关闭助手" onClick={close}>关闭 <kbd>Esc</kbd></button>
        </header>
        <AssistantThread {...thread} variant="drawer" onNavigate={() => { thread.onNavigate?.(); close(); }} />
      </aside>
    </div>
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
    and (where the text is the author's own draft) 查前文矛盾 has the passage checked against what came before. */
export function SelectionToolbar({ selector, onAsk, onQuick, onSelect, check }: {
  selector: string;
  onAsk: (text: string) => void;
  onQuick: (text: string) => void;
  /** Told what is selected (text of 4–600 characters) as it is selected, and null when the selection is gone. */
  onSelect?: (text: string | null) => void;
  /** The third button; leave it out where it makes no sense (a visitor, a written chapter). `remaining` is the day's characters left, null when not counted. */
  check?: { run: (text: string) => void; remaining: number | null };
}) {
  const [shown, setShown] = useState<{ text: string; x: number; y: number; below: boolean } | null>(null);
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
      // The bar sits above the words, never over the page's top bar or the editor's own tool row; where there is no room it goes below them.
      const tools = document.querySelector(selector)?.closest(".draft")?.querySelector(".draft-tools")?.getBoundingClientRect();
      const ceiling = Math.max(topbar + 8, tools ? tools.bottom + 4 : 0);
      const below = first.top - 8 - 32 < ceiling;
      const x = Math.min(Math.max((first.left + last.right) / 2, 120), window.innerWidth - 120);
      setShown({ text, x, y: below ? last.bottom + 8 : first.top - 8, below });
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
        if (current && bar.current?.contains(document.activeElement)) document.querySelector<HTMLElement>(selector)?.focus();
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
  if (!shown) return null;
  return (
    <div ref={bar} className={`a-selpop${shown.below ? " below" : ""}`} role="toolbar" aria-label="对选中的文字提问" style={{ left: shown.x, top: shown.y }}
      onMouseDown={(event) => event.preventDefault()}>
      <button type="button" className="first" aria-label="问助手：把选中的文字带进提问" onClick={() => { onAsk(shown.text); setShown(null); }}>问助手</button>
      <button type="button" aria-label="前面怎么写的：直接问这段前面怎么写的" onClick={() => { onQuick(shown.text); setShown(null); }}>前面怎么写的</button>
      {check && (() => {
        const cost = TASK_CHARS + writtenChars(shown.text);
        const short = check.remaining !== null && check.remaining < cost;
        return (
          <button type="button" disabled={short} title={short ? "今天的可检查字数不够这次检查" : undefined}
            aria-label={`查前文矛盾：检查这段和前文有没有矛盾，约 ${formatCount(cost)} 字`} onClick={() => { check.run(shown.text); setShown(null); }}>查前文矛盾 · 约 {formatCount(cost)} 字</button>
        );
      })()}
    </div>
  );
}
