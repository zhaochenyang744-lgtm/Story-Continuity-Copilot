"use client";

// A question to the assistant, as the conversation shows it: the author's question (which can be reworded and sent again), the
// steps, the answer with its sources and the row of actions under it. Answers asked for again fold the older ones into
// 「之前的回答」; a question that was reworded folds the old question and its answers into 「已改问」.
import { type CSSProperties, type ReactNode, useRef, useState } from "react";
import type { AssistantSource, AssistantTask } from "../../model";
import { clip } from "../ui";
import { AnswerBlock, TaskFoot, useJustFinished } from "./assistant-answer";
import { active, CoverLine, failureText, LimitLine, sentencesOf, SourceList, StoppedNote } from "./assistant-parts";
import { Steps } from "./assistant-process";
import { RoutedLine } from "./assistant-route";

/** One entry of the conversation: the answer shown now, the older answers to the same question, and whether the whole question was reworded since. */
export type Group = { id: string; latest: AssistantTask; older: AssistantTask[]; reworded: boolean };

/** The tasks as the conversation lists them. A task asked again takes the place of the one it repeats (that one folds into
    「之前的回答」); a question that has been reworded stays where it was, folded; the reworded one is a new entry at the end. */
export function arrange(tasks: AssistantTask[]): Group[] {
  const byId = new Map(tasks.map((task) => [task.id, task]));
  const rootOf = (task: AssistantTask): string => {
    let at = task;
    for (let hops = 0; hops < 50; hops += 1) {
      const parent = at.regenerated_from ? byId.get(at.regenerated_from) : undefined;
      if (!parent) break;
      at = parent;
    }
    return at.id;
  };
  const groups = new Map<string, AssistantTask[]>();
  for (const task of tasks) {
    const root = rootOf(task);
    groups.set(root, [...(groups.get(root) ?? []), task]);
  }
  const edited = new Set(tasks.map((task) => task.edited_from).filter((id): id is string => Boolean(id)));
  return [...groups.entries()].map(([id, members]) => ({
    id, latest: members[members.length - 1], older: members.slice(0, -1).reverse(), reworded: members.some((task) => edited.has(task.id)),
  }));
}

type Handlers = {
  projectId: string;
  visitor: boolean;
  stopping: boolean;
  stop: (task: AssistantTask) => void;
  retry: (task: AssistantTask) => void;
  openChapter: (number: number) => void;
  locate: (source: AssistantSource) => void;
  followUp: (task: AssistantTask) => void;
  regenerate: (task: AssistantTask) => void;
  replace: (next: AssistantTask) => void;
  /** Why a new question cannot start now (empty when it can). */
  blocked: string;
  /** Send a reworded question; resolves true when it was sent. */
  resend: (task: AssistantTask, question: string) => Promise<boolean>;
  /** The author is not allowed to rework questions (archived work). */
  readOnly: boolean;
  /** The tasks asked while this view was open: their question bubbles rise into place. */
  asked: string[];
};

/** The author's question; pointing at it shows 「改」, which turns it into a box to reword and send again. */
function Question({ task, handlers, children }: { task: AssistantTask; handlers: Handlers; children?: ReactNode }) {
  const [editing, setEditing] = useState(false);
  const [text, setText] = useState(task.question ?? "");
  const [sending, setSending] = useState(false);
  const box = useRef<HTMLTextAreaElement>(null);
  const check = task.context.intent === "check_selection";
  const canEdit = task.kind === "ask" && !check && !handlers.readOnly;
  const cost = handlers.visitor ? "用 1 次" : "约 500 字";
  if (editing) {
    return (
      <div className="a-resend">
        <textarea ref={box} className="a-edit" aria-label="修改问题" value={text} rows={2} maxLength={300} autoFocus onChange={(event) => setText(event.target.value)} />
        <div className="a-resend-row">
          <button type="button" className="a-link" onClick={() => { setEditing(false); setText(task.question ?? ""); }}>取消</button>
          <button type="button" className="a-btn" disabled={sending || Boolean(handlers.blocked) || !text.trim() || text.trim() === (task.question ?? "").trim()} title={handlers.blocked || undefined}
            onClick={async () => { setSending(true); const sent = await handlers.resend(task, text.trim()); setSending(false); if (sent) setEditing(false); }}>重新发送 · {cost}</button>
        </div>
      </div>
    );
  }
  return (
    <div className={`a-ask${handlers.asked.includes(task.id) ? " rise" : ""}`}>
      {canEdit && <button type="button" className="a-ask-edit" aria-label="修改这个问题" onClick={() => { setText(task.question ?? ""); setEditing(true); }}>改</button>}
      {task.context.selection && <span className="a-quote">{clip(task.context.selection, 120)}</span>}
      {task.question}
      {children}
    </div>
  );
}

/** One question's answer: steps, the answer, sources, the row of actions. */
function AskBody({ task, handlers, latest, showQuestion }: { task: AssistantTask; handlers: Handlers; latest: boolean; showQuestion: boolean }) {
  const running = active(task);
  const fade = useJustFinished(task);
  const answerBox = useRef<HTMLDivElement>(null);
  const answer = task.answer && !("kind" in task.answer) ? task.answer : null;
  const offTopic = answer?.status === "out_of_scope";
  const state = running ? { text: "正在查", tone: "quiet" }
    : task.status === "cancelled" ? { text: "已停止", tone: "quiet" }
      : task.status === "failed" ? { text: "没有完成", tone: "quiet" }
        : answer?.status === "answered" ? { text: "有答案", tone: "blue" }
          : answer?.status === "not_found" ? { text: "正文里找不到", tone: "quiet" }
            : answer?.status === "inconsistent" ? { text: "前后不一致", tone: "quiet" } : { text: "", tone: "quiet" };
  const failure = task.status === "failed" ? failureText(task, handlers.visitor) : null;
  return (
    <article className="a-task" aria-live="off" data-answer={task.id}>
      {showQuestion && <Question task={task} handlers={handlers} />}
      <div className="a-head">
        <span className="a-kind">{task.context.intent === "check_selection" ? "查前文矛盾" : "问作品"}</span>
        {state.text && <span className={`a-state ${state.tone}`}>{state.text}</span>}
        {running && <button type="button" className="a-link a-stop" disabled={handlers.stopping} onClick={() => handlers.stop(task)}>停止</button>}
      </div>
      <RoutedLine task={task} />
      <Steps task={task} locate={handlers.locate} />
      <StoppedNote task={task} visitor={handlers.visitor} />
      {failure && (
        <p className="a-note" role="status">{failure.text}{failure.retry && <> <button type="button" className="a-link" onClick={() => handlers.retry(task)}>重试</button></>}</p>
      )}
      <LimitLine task={task} />
      <AnswerBlock task={task} fade={fade} locate={handlers.locate} innerRef={answerBox} />
      {/* What the answer rests on and the row of actions come in after its last sentence has begun to appear. */}
      <div className={`a-rest${fade ? " a-fade" : ""}`} style={{ "--n": sentencesOf(task)?.sentences.length ?? 0 } as CSSProperties}>
        {!offTopic && <SourceList task={task} locate={handlers.locate} />}
        {!offTopic && <CoverLine task={task} />}
        <TaskFoot task={task} projectId={handlers.projectId} visitor={handlers.visitor} blocked={handlers.blocked} answer={offTopic ? null : answerBox}
          followUp={latest && !offTopic ? () => handlers.followUp(task) : null} followUpLimit={(task.follow_up_depth ?? 0) >= 2} regenerate={latest && !offTopic ? () => handlers.regenerate(task) : null} replace={handlers.replace} />
      </div>
    </article>
  );
}

/** An entry of the conversation: the question once, the latest answer, and the older answers to it folded under 「之前的回答」. */
export function AskGroup({ group, handlers }: { group: Group; handlers: Handlers }) {
  const { latest, older } = group;
  const body = (
    <>
      <Question task={latest} handlers={handlers} />
      <AskBody task={latest} handlers={handlers} latest={latest.status === "completed" && latest.kind === "ask"} showQuestion={false} />
      {older.length > 0 && (
        <details className="a-older">
          <summary>之前的回答 · {older.length}</summary>
          <div className="a-fold-body">
            {older.map((task) => <AskBody key={task.id} task={task} handlers={handlers} latest={false} showQuestion={false} />)}
          </div>
        </details>
      )}
    </>
  );
  // `data-task` marks the whole entry (question and answers): the thread scrolls to it and the tests find it by it.
  if (!group.reworded) return <div className="a-group" data-task={latest.id} data-status={latest.status} data-kind="ask">{body}</div>;
  return (
    <details className="a-group a-reworded" data-task={latest.id} data-status={latest.status} data-kind="ask">
      <summary>已改问 · {clip(latest.question ?? "", 24)}</summary>
      <div className="a-fold-body">{body}</div>
    </details>
  );
}

export type { Handlers as AskHandlers };
