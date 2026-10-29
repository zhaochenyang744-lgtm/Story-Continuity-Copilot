"use client";

// 写前回顾 as an assistant task: four groups, each item one sentence with a small mark at its end (the same mark as an answer's: it opens to the
// passage it rests on, whole, with the sentence that says the same set apart, and to a way to the original).
// The server picks the candidates and quotes the passages; the model only chooses, orders and summarises.
import type { AssistantSource, AssistantTask, RecapAnswer, RecapSection } from "../../model";
import { formatCount } from "../ui";
import { Feedback, SentenceText } from "./assistant-answer";
import { active, cardLabel, failureText, isRecap, LimitLine, notChecked, StoppedNote } from "./assistant-parts";
import { Steps } from "./assistant-process";
import { ChosenLine, RerouteMenu } from "./assistant-route";

const SECTIONS: { id: RecapSection; label: string }[] = [
  { id: "previous_ending", label: "上一章停在哪" },
  { id: "character_state", label: "出场人物的最新状态" },
  { id: "open_threads", label: "还没收的线" },
  { id: "plan", label: "计划里这一章的事" },
];

/** The refs the recap rests on, in the order they first appear: a mark's number is its place in it. */
export function recapRefs(task: AssistantTask, answer: RecapAnswer): string[] {
  const order: string[] = [];
  for (const { id } of SECTIONS) for (const item of answer.sections[id]) for (const ref of item.refs) if (task.sources[ref] && !order.includes(ref)) order.push(ref);
  return order;
}

/** What the program did not look at, besides the draft (a recap never reads it; the top line already says which chapters it read). */
export const recapMissed = (task: AssistantTask) => notChecked(task).filter((item) => !item.startsWith("本章草稿"));

export function RecapView({ task, projectId, visitor, stopping, stop, retry, locate, rerun, replace }: {
  task: AssistantTask;
  projectId: string;
  replace: (next: AssistantTask) => void;
  visitor: boolean;
  stopping: boolean;
  stop: () => void;
  retry: () => void;
  /** 去原文 in a mark's card. */
  locate: (source: AssistantSource) => void;
  /** 重新回顾; null where it makes no sense (the drawer on other pages). */
  rerun: (() => void) | null;
}) {
  const running = active(task);
  const answer = isRecap(task.answer) ? task.answer : null;
  const failure = task.status === "failed" ? failureText(task, visitor) : null;
  const charged = !visitor && task.usage.chars_charged > 0;
  const refs = answer ? recapRefs(task, answer) : [];
  // A plan has no chapter of its own in the sources: it is the plan for the chapter being written.
  const labelOf = (source: AssistantSource) => (source.kind === "plan" && source.chapter_number == null && answer ? `计划 · 第 ${answer.chapter_number} 章` : cardLabel(source));
  const sentence = (item: { summary: string; refs: string[] }) => (
    <SentenceText task={task} sentence={{ text: item.summary, refs: item.refs.filter((ref) => task.sources[ref]) }} bold={false} order={0} refs={refs} locate={locate} whole labelOf={labelOf} />
  );
  const missed = recapMissed(task);
  return (
    <article className="a-task" aria-live="off" data-task={task.id} data-status={task.status} data-kind="recap">
      <Steps task={task} named lead={`写前回顾${answer ? ` · 第 ${answer.chapter_number} 章（只看第 1–${answer.chapter_number - 1} 章）` : ""}`}
        end={<><RerouteMenu task={task} />{running && <button type="button" className="a-link a-stop" disabled={stopping} onClick={stop}>停止</button>}</>} />
      <ChosenLine task={task} />
      <StoppedNote task={task} visitor={visitor} />
      {failure && (
        <p className="a-note" role="status">{failure.text}{failure.retry && <> <button type="button" className="a-link" onClick={retry}>重试</button></>}</p>
      )}
      <LimitLine task={task} />
      {answer && SECTIONS.map(({ id, label }) => answer.sections[id].length > 0 && (
        <section key={id} className="a-recap-sec" aria-label={label} data-section={id}>
          <p className="a-label">{label}</p>
          {id === "previous_ending"
            ? answer.sections[id].map((item, index) => <p key={index} className="a-ri lead">{sentence(item)}</p>)
            : <ul className="a-ri-list">{answer.sections[id].map((item, index) => <li key={index} className="a-ri">{sentence(item)}</li>)}</ul>}
        </section>
      ))}
      {missed.length > 0 && <p className="a-cover" data-testid="recap-missed">没查：{missed.join("、")}。</p>}
      {task.status === "completed" && (
        <div className="a-foot">
          {rerun && <button type="button" className="a-link" onClick={rerun}>重新回顾</button>}
          <Feedback task={task} projectId={projectId} replace={replace} />
          {charged && <span className="a-cost-line">计 {formatCount(task.usage.chars_charged)} 字</span>}
        </div>
      )}
    </article>
  );
}
