"use client";

// 写前回顾 as an assistant task: four columns, each item a sentence with the passages it rests on right under it.
// The server picks the candidates and quotes the passages; the model only chooses, orders and summarises.
import { useState } from "react";
import type { AssistantSource, AssistantTask, RecapAnswer, RecapSection } from "../../model";
import { formatCount } from "../ui";
import { Feedback } from "./assistant-answer";
import { active, CoverLine, failureText, isRecap, LimitLine, StoppedNote } from "./assistant-parts";
import { Steps } from "./assistant-process";
import { RoutedLine } from "./assistant-route";

const SECTIONS: { id: RecapSection; label: string }[] = [
  { id: "previous_ending", label: "上一章停在哪" },
  { id: "character_state", label: "出场人物的最新状态" },
  { id: "open_threads", label: "还没收的线" },
  { id: "plan", label: "计划里这一章的事" },
];
/** At most this many passages are shown under one item; the rest fold into 「还有 N 段」. */
const SHOWN = 2;

/** Where a passage comes from, in the small grey line under it. */
function originOf(source: AssistantSource, section: RecapSection, target: number): string {
  if (source.kind === "plan") return `计划 · 第 ${target} 章`;
  const chapter = source.chapter_number != null ? `第 ${source.chapter_number} 章` : "";
  if (source.kind === "fact") return `已确认事实 · ${chapter}`;
  return section === "open_threads" ? `伏笔记录 · ${chapter}` : chapter;
}

function Item({ task, answer, section, item, openChapter }: {
  task: AssistantTask;
  answer: RecapAnswer;
  section: RecapSection;
  item: { summary: string; refs: string[] };
  openChapter: (number: number) => void;
}) {
  const [all, setAll] = useState(false);
  const [wide, setWide] = useState<string[]>([]);
  const sources = item.refs.filter((ref) => task.sources[ref]);
  const shown = all ? sources : sources.slice(0, SHOWN);
  return (
    <div className="a-ri">
      <p>{item.summary}</p>
      {shown.map((ref) => {
        const source = task.sources[ref];
        const open = wide.includes(ref);
        return (
          <div key={ref} className="a-ri-src">
            <button type="button" className={`a-text${open ? " wide" : ""}`} aria-expanded={open}
              onClick={() => setWide((current) => (open ? current.filter((value) => value !== ref) : [...current, ref]))}>{source.text}</button>
            {source.chapter_number != null
              ? <button type="button" className="a-from" onClick={() => openChapter(source.chapter_number!)}>{originOf(source, section, answer.chapter_number)}</button>
              : <span className="a-from">{originOf(source, section, answer.chapter_number)}</span>}
          </div>
        );
      })}
      {sources.length > SHOWN && !all && <button type="button" className="a-link a-more" onClick={() => setAll(true)}>还有 {sources.length - SHOWN} 段</button>}
    </div>
  );
}

export function RecapView({ task, projectId, visitor, stopping, stop, retry, openChapter, rerun, replace }: {
  task: AssistantTask;
  projectId: string;
  replace: (next: AssistantTask) => void;
  visitor: boolean;
  stopping: boolean;
  stop: () => void;
  retry: () => void;
  openChapter: (number: number) => void;
  /** 重新回顾; null where it makes no sense (the drawer on other pages). */
  rerun: (() => void) | null;
}) {
  const running = active(task);
  const answer = isRecap(task.answer) ? task.answer : null;
  const failure = task.status === "failed" ? failureText(task, visitor) : null;
  const charged = !visitor && task.usage.chars_charged > 0;
  return (
    <article className="a-task" aria-live="off" data-task={task.id} data-status={task.status} data-kind="recap">
      <div className="a-head">
        <span className="a-kind">写前回顾{answer ? ` · 第 ${answer.chapter_number} 章` : ""}</span>
        {answer && <span className="a-scope">只看第 1–{answer.chapter_number - 1} 章</span>}
        {running && <span className="a-state quiet">正在查</span>}
        {running && <button type="button" className="a-link a-stop" disabled={stopping} onClick={stop}>停止</button>}
      </div>
      <RoutedLine task={task} />
      <Steps task={task} />
      <StoppedNote task={task} visitor={visitor} />
      {failure && (
        <p className="a-note" role="status">{failure.text}{failure.retry && <> <button type="button" className="a-link" onClick={retry}>重试</button></>}</p>
      )}
      <LimitLine task={task} />
      {answer && SECTIONS.map(({ id, label }) => answer.sections[id].length > 0 && (
        <section key={id} className="a-recap-sec" aria-label={label}>
          <p className="a-label">{label}</p>
          {answer.sections[id].map((item, index) => <Item key={index} task={task} answer={answer} section={id} item={item} openChapter={openChapter} />)}
        </section>
      ))}
      <CoverLine task={task} />
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
