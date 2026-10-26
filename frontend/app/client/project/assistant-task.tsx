"use client";

// A question to the assistant, as the conversation shows it: the author's question (which can be reworded and sent again), the
// steps, the answer with its sources and the row of actions under it. Answers asked for again fold the older ones into
// 「之前的回答」; a question that was reworded folds the old question and its answers into 「已改问」.
import { type CSSProperties, type ReactNode, useRef, useState } from "react";
import type { AssistantChange, AssistantSource, AssistantTask } from "../../model";
import { clip } from "../ui";
import { AnswerBlock, TaskFoot, useJustFinished } from "./assistant-answer";
import { ChangeCard } from "./assistant-change";
import { active, CoverLine, failureText, LimitLine, sentencesOf, SourceList, sourceKey, StoppedNote } from "./assistant-parts";
import { Steps } from "./assistant-process";
import { ChosenLine, RerouteMenu, routedLead } from "./assistant-route";

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
  /** The tasks that were started as a question because the judgement of their use did not come in time. */
  timedOut: string[];
  /** Why no new question can be asked at all (the allowance is used up), or empty. */
  off: string;
  /** 改资料: items the server sent back go into the conversation; the materials were written (the page reads them again); the way to the materials page. */
  merge: (items: AssistantChange[]) => void;
  written: () => void;
  goMaterials: () => void;
};

/** The author's question; pointing at it shows 「改」, which turns it into a box to reword and send again. */
export function Question({ task, handlers, children }: { task: AssistantTask; handlers: Handlers; children?: ReactNode }) {
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

/** One question's answer: the line above it, the answer, what was and was not looked at, the sources, the row of actions. */
function AskBody({ task, handlers, latest, showQuestion }: { task: AssistantTask; handlers: Handlers; latest: boolean; showQuestion: boolean }) {
  const running = active(task);
  const fade = useJustFinished(task);
  const answerBox = useRef<HTMLDivElement>(null);
  const answer = task.answer && !("kind" in task.answer) ? task.answer : null;
  const offTopic = answer?.status === "out_of_scope";
  const notFound = answer?.status === "not_found";
  const failure = task.status === "failed" ? failureText(task, handlers.visitor) : null;
  // What the line above says besides the use: only what the answer's own words do not (a card waiting to be decided, an answer that disagrees with itself).
  const state = !running && task.kind === "change" && task.changes?.some((item) => item.status === "proposed") ? " · 等你确认" : !running && answer?.status === "inconsistent" ? " · 前后不一致" : "";
  const lead = routedLead(task, handlers.timedOut.includes(task.id)) + state;
  // The passages a change card already stands on are not listed again under the answer.
  const cardHas = new Set((task.changes ?? []).flatMap((item) => item.evidence.map(sourceKey)));
  return (
    <article className="a-task" aria-live="off" data-answer={task.id}>
      {showQuestion && <Question task={task} handlers={handlers} />}
      <Steps task={task} locate={handlers.locate} lead={lead}
        end={<><RerouteMenu task={task} />{running && <button type="button" className="a-link a-stop" disabled={handlers.stopping} onClick={() => handlers.stop(task)}>停止</button>}</>} />
      <ChosenLine task={task} />
      <StoppedNote task={task} visitor={handlers.visitor} />
      {failure && (
        <p className="a-note" role="status">{failure.text}{failure.retry && <> <button type="button" className="a-link" onClick={() => handlers.retry(task)}>重试</button></>}</p>
      )}
      <LimitLine task={task} />
      <AnswerBlock task={task} fade={fade} locate={handlers.locate} innerRef={answerBox} />
      {/* What the answer rests on and the row of actions come in after its last sentence has begun to appear. */}
      <div className={`a-rest${fade ? " a-fade" : ""}`} style={{ "--n": sentencesOf(task)?.sentences.length ?? 0 } as CSSProperties}>
        {!offTopic && <CoverLine task={task} onlyMissed={notFound} />}
        {!offTopic && <SourceList task={task} locate={handlers.locate} skip={cardHas} />}
        {task.kind === "change" && task.status === "completed" && (
          <ChangeCard task={task} projectId={handlers.projectId} readOnly={handlers.readOnly} replace={handlers.replace} merge={handlers.merge} locate={handlers.locate}
            written={handlers.written} goMaterials={handlers.goMaterials} />
        )}
        <TaskFoot task={task} projectId={handlers.projectId} visitor={handlers.visitor} blocked={handlers.blocked} off={handlers.off} answer={offTopic ? null : answerBox}
          followUp={latest && !offTopic ? () => handlers.followUp(task) : null} followUpLimit={(task.follow_up_depth ?? 0) >= 2} regenerate={latest && !offTopic ? () => handlers.regenerate(task) : null} replace={handlers.replace} />
      </div>
    </article>
  );
}

/** An entry of the conversation: the question once, the latest answer, and the older answers to it folded under 「之前的回答」. */
/** `follow`: this question follows the one just above it, so it hangs from it (indented, with a line down its left) and has no line of its own between turns. */
export function AskGroup({ group, handlers, follow = false }: { group: Group; handlers: Handlers; follow?: boolean }) {
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
  if (!group.reworded) return <div className={`a-group${follow ? " a-follow" : ""}`} data-task={latest.id} data-status={latest.status} data-kind={latest.kind}>{body}</div>;
  return (
    <details className={`a-group a-reworded${follow ? " a-follow" : ""}`} data-task={latest.id} data-status={latest.status} data-kind={latest.kind}>
      <summary>已改问 · {clip(latest.question ?? "", 24)}</summary>
      <div className="a-fold-body">{body}</div>
    </details>
  );
}

export type { Handlers as AskHandlers };
