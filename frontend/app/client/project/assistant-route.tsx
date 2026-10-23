"use client";

// 自动 (v1.9.0): the input box judges which use a sentence asks for, and a task it started says so, with a way to change it.
// This file holds what both sides of that need: the request that asks the server, the task each use is started as, the small
// line on a task card (按「写前回顾」处理 · 改成 ▾) and the local note for a sentence that is not about the work.
import { createContext, useContext } from "react";
import { json } from "../../api";
import type { AssistantContextInput, AssistantRoute, AssistantRouting, AssistantTask } from "../../model";
import { Menu } from "../ui";
import { active } from "./assistant-parts";

/** The uses a task can be started as; `out_of_scope` starts nothing. */
export type Use = Exclude<AssistantRoute, "out_of_scope">;
export const USE_LABEL: Record<Use, string> = { ask: "问作品", recap: "写前回顾", fix_issue: "帮我改这一处", check_passage: "查前文矛盾", change: "改资料" };
export const CHECK_QUESTION = "这段和前文有没有矛盾？";
/** The judgement is waited for this long; after it the sentence is an ordinary question. */
export const ROUTE_WAIT_MS = 8000;
export const OUT_OF_SCOPE_LOCAL = "这和作品无关，助手只回答这部作品里的事。";

/** A task about to be created: the same request the manual modes send, plus how the use was chosen. */
export type NewTask = {
  kind: AssistantTask["kind"];
  question?: string;
  context: AssistantContextInput;
  followUpOf?: string | null;
  editedFrom?: string | null;
  routed?: { source: "rule" | "model" | "manual"; input: string };
};

/** Ask the server which use `input` asks for. Anything but a clear answer in time is an unsure `ask`. */
export async function routeInput(projectId: string, input: string, context: AssistantContextInput): Promise<AssistantRouting> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), ROUTE_WAIT_MS);
  try {
    return await json<AssistantRouting>(`/projects/${projectId}/assistant/route`, "POST", { input, context }, controller.signal);
  } catch {
    return { route: "ask", source: "model", unsure: true };
  } finally { window.clearTimeout(timer); }
}

/** The task a use is started as, or null when the context cannot carry it out (a fix needs a finding, a check needs a picked passage). */
export function taskFor(use: Use, input: string, context: AssistantContextInput, followUpOf?: string | null): NewTask | null {
  const { intent: _intent, ...plain } = context;
  void _intent;
  if (use === "recap") return { kind: "recap", context: { page: "writing" } };
  if (use === "fix_issue") return plain.issue_id ? { kind: "fix_issue", ...(input ? { question: input } : {}), context: { page: "writing", issue_id: plain.issue_id } } : null;
  if (use === "change") return input ? { kind: "change", question: input, context: plain } : null;
  if (use === "check_passage") return plain.selection ? { kind: "ask", question: CHECK_QUESTION, context: { ...plain, intent: "check_selection" } } : null;
  return input ? { kind: "ask", question: input, context: plain, followUpOf: followUpOf ?? null } : null;
}

/** The use a task was started as. */
export const usageOf = (task: AssistantTask): Use =>
  task.kind === "recap" ? "recap" : task.kind === "fix_issue" ? "fix_issue" : task.kind === "change" ? "change" : task.context.intent === "check_selection" ? "check_passage" : "ask";

export type RerouteControl = {
  /** The other uses this task's sentence can be sent as here. */
  options: (task: AssistantTask) => Use[];
  change: (task: AssistantTask, use: Use) => void;
  /** What sending it again costs ("约 500 字"), shown beside 改成 once the task is over. */
  cost: string;
  /** Why a new task cannot start now (another one is running), or empty. */
  blocked: string;
};
export const RerouteContext = createContext<RerouteControl | null>(null);

/** 按「写前回顾」处理 · 改成 ▾ — at the top of a task the box chose the use of. While the task waits or runs, changing it stops it
    and gives its characters back; once it is over, changing it sends the sentence again and is charged like any task. */
export function RoutedLine({ task }: { task: AssistantTask }) {
  const control = useContext(RerouteContext);
  if (!task.routed || !control || task.status === "cancelled") return null;
  const current = usageOf(task);
  const options = control.options(task).filter((use) => use !== current);
  const live = active(task);
  return (
    <p className="a-routed" data-testid="routed-line">
      <span className="a-routed-use">按「{USE_LABEL[current]}」处理</span>
      {options.length > 0 && (
        <>
          <Menu label="改成" buttonLabel="改成别的用法">
            {options.map((use) => (
              <button key={use} type="button" role="menuitem" disabled={!live && Boolean(control.blocked)} title={!live && control.blocked ? control.blocked : undefined}
                onClick={() => control.change(task, use)}>{USE_LABEL[use]}</button>
            ))}
          </Menu>
          {!live && <span className="a-hint">{control.cost}</span>}
        </>
      )}
    </p>
  );
}

export const RECAP_ELSEWHERE = "写前回顾要在写作页里用：它回顾你正在写的这一章之前的内容。";

/** "去写作页做写前回顾": the writing page that opens within a few seconds starts a 写前回顾. Kept in memory, not in the address
    (an in-app move updates the address after the new page has first rendered); a move that was stopped does not start it later. */
const recapOnArrival = { at: 0 };
export const wantRecapOnArrival = () => { recapOnArrival.at = Date.now(); };
export const recapWanted = () => Date.now() - recapOnArrival.at < 10_000;
export const recapTaken = () => { recapOnArrival.at = 0; };

/** A 写前回顾 asked for off the writing page: nothing was made or charged here; the button takes the author to the writing page,
    where it starts (and is charged) like the page's own 写前回顾. */
export function RecapElsewhereNote({ input, cost, open, blocked }: { input: string; cost: string; open: () => void; blocked: string }) {
  return (
    <div className="a-offnote" data-testid="route-recap-elsewhere">
      {input && <div className="a-ask"><span>{input}</span></div>}
      <p className="a-note" role="status">{RECAP_ELSEWHERE}</p>
      <button type="button" className="a-link" disabled={Boolean(blocked)} title={blocked || undefined} onClick={open}>
        去写作页做写前回顾{cost ? ` · ${cost}` : ""}
      </button>
    </div>
  );
}

/** A sentence the judgement says is not about the work: no task was made and nothing was charged. */
export function OutOfScopeNote({ input, asAsk, blocked }: { input: string; asAsk: () => void; blocked: string }) {
  return (
    <div className="a-offnote" data-testid="route-out-of-scope">
      <div className="a-ask"><span>{input}</span></div>
      <p className="a-note" role="status">{OUT_OF_SCOPE_LOCAL}</p>
      <button type="button" className="a-link" disabled={Boolean(blocked)} title={blocked || undefined} onClick={asAsk}>还是当作问作品</button>
    </div>
  );
}
