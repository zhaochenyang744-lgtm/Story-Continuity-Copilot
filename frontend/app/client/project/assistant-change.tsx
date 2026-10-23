"use client";

// 改资料 (v2.0) as the conversation shows it: under the answer, a card of the changes the assistant proposes to the author's
// materials (add a fact, change a fact, mark a thread resolved). The assistant only proposes; nothing is written before the
// author confirms, and the program writes every confirmed item at once. A written item can be undone and applied again, here
// and in the materials page's ledger. Nothing in this file writes the materials itself: it asks the server, and shows the answer.
import { type Dispatch, type SetStateAction, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { AssistantChange, AssistantChangeKind, AssistantSource, AssistantTask } from "../../model";
import { Button } from "../ui";
import { SourceItem } from "./assistant-parts";

export const KIND_LABEL: Record<AssistantChangeKind, string> = { add_fact: "加事实", change_fact: "改事实", resolve_thread: "标伏笔已回收" };
const VALUE_MAX = 200;

/** What a change was written to: the page asks for it again once the materials have moved. */
export type ChangeWritten = () => void;

type Later = { id: string; title: string; after: string };
export type Conflict = { later: Later[]; author: boolean };
/** An error in words; `review` adds the way to the materials page. */
export type ChangeProblem = { text: string; review: boolean };

/** The words for what went wrong with a card or an item (never the code). `step` is what was being done. */
export function changeProblem(cause: unknown, step: "confirm" | "undo" | "redo" = "confirm"): ChangeProblem {
  const failure = cause as ApiFailure;
  const verb = step === "confirm" ? "确认" : step === "undo" ? "撤销" : "恢复";
  switch (failure?.code) {
    case "change_target_changed": {
      const labels = Array.isArray(failure.details?.changes) ? (failure.details?.changes as string[]).join("、") : "";
      const which = labels ? `（${labels}）` : "";
      return { text: step === "confirm" ? `资料已经变了${which}，这张卡片不能再确认。可以再让助手看一次。` : `资料已经变了${which}，这一条不能再恢复。`, review: false };
    }
    case "change_memory_review_pending": return { text: `资料页还有没确认的事实变化，先处理完再${verb}事实。`, review: true };
    case "change_undo_conflict": return { text: "这条资料后来又被改过，撤销会把后来的改动一起退回。再点一次撤销，确认后才会退回。", review: false };
    case "invalid_request": return { text: "这一步的内容不完整，没有改动资料。刷新页面后再试一次。", review: false };
    case "change_already_decided": return { text: "这张卡片已经确认或不要过了，已经换成现在的样子。", review: false };
    case "change_state_invalid": return { text: "这一条的状态已经变了，已经换成现在的样子。", review: false };
    case "change_target_missing": return { text: "要改的资料已经不在了，这一条不能再操作。", review: false };
    case "invalid_item_selection": return { text: "勾选的条目和这张卡片对不上，刷新页面再看。", review: false };
    case "change_value_invalid": return { text: `改写的内容不能为空，也不能超过 ${VALUE_MAX} 字。`, review: false };
    case "change_task_not_completed": return { text: "助手还没有答完，等它结束再确认。", review: false };
    case "resource_not_found": return { text: "这张卡片已经不在了（对话可能被清空了）。", review: false };
    case "request_timeout": return { text: "这一步花的时间比平时长，结果可能已经保存。刷新页面看看。", review: false };
    case "foreshadow_version_limit": return { text: "这条伏笔的改动次数到上限了，不能再改。", review: false };
    default: return { text: failure?.code ? labelError(cause) : `这一步没有成功，请再试一次。`, review: false };
  }
}

/** The passage an item rests on, as a source of the assistant's answer: the same citation line, the same 去原文. */
const asSource = (item: AssistantChange["evidence"][number]): AssistantSource => ({
  kind: "passage", chapter_number: item.chapter_number, chapter_title: item.chapter_title, start: item.start, end: item.end, text: item.text, cited: true,
});

/** Undo and redo of single items, for the card and for the ledger: the server's refusals are kept per item. */
type Local = { busy?: boolean; problem?: ChangeProblem; conflict?: Conflict };
export type ItemOps = {
  local: (id: string) => Local;
  undo: (item: AssistantChange, confirm?: boolean) => void;
  redo: (item: AssistantChange) => void;
  /** 算了: drop the question about undoing over later changes. */
  leave: (item: AssistantChange) => void;
};
export function useItemOps(projectId: string, merge: (items: AssistantChange[]) => void, written: ChangeWritten, refresh: (item: AssistantChange) => void): ItemOps {
  const [locals, setLocals] = useState<Record<string, Local>>({});
  const set = (id: string, next: Local | null) => setLocals((current) => {
    const copy = { ...current };
    if (next) copy[id] = next; else delete copy[id];
    return copy;
  });
  const run = async (item: AssistantChange, step: "undo" | "redo", confirm: boolean) => {
    set(item.id, { busy: true });
    try {
      const data = await json<{ changes: AssistantChange[] }>(`/projects/${projectId}/assistant/changes/${item.id}/${step}`, "POST", step === "undo" ? { confirm } : {});
      merge(data.changes);
      set(item.id, null);
      written();
    } catch (cause) {
      const failure = cause as ApiFailure;
      if (step === "undo" && failure.code === "change_undo_conflict") {
        const later = Array.isArray(failure.details?.later_changes) ? (failure.details?.later_changes as Later[]) : [];
        set(item.id, { conflict: { later, author: Boolean(failure.details?.author_changed) } });
        return;
      }
      set(item.id, { problem: changeProblem(cause, step) });
      // The item may have moved on without this page knowing: read it again.
      if (["change_state_invalid", "change_target_changed", "change_target_missing"].includes(failure.code)) refresh(item);
    }
  };
  return {
    local: (id) => locals[id] ?? {},
    undo: (item, confirm = false) => void run(item, "undo", confirm),
    redo: (item) => void run(item, "redo", false),
    leave: (item) => set(item.id, null),
  };
}

/** The question when an item cannot be undone alone: later changes to the same record, or the author's own edit, would go with it. */
export function ConflictPrompt({ conflict, busy, undo, leave, page = false }: { conflict: Conflict; busy: boolean; undo: () => void; leave: () => void; page?: boolean }) {
  const body = (
    <>
      {conflict.later.length > 0 && (
        <>
          <p>这条后来又被改过：</p>
          <ul>{conflict.later.map((item) => <li key={item.id}><strong>{item.title}</strong>：{item.after}</li>)}</ul>
        </>
      )}
      {conflict.author && <p>你后来也改过这条资料。</p>}
      <p>撤销会把这些后来的修改一起退回。</p>
    </>
  );
  if (page) {
    return (
      <div className="note note-warn ledger-conflict" role="alert">
        <div className="ledger-conflict-text">{body}</div>
        <span className="actions">
          <Button kind="small" disabled={busy} onClick={undo}>仍然撤销</Button>
          <Button kind="text" disabled={busy} onClick={leave}>算了</Button>
        </span>
      </div>
    );
  }
  return (
    <div className="a-chg-conflict" role="alert">
      {body}
      <div className="a-opt-a">
        <button type="button" className="a-btn" disabled={busy} onClick={undo}>仍然撤销</button>
        <button type="button" className="a-link" disabled={busy} onClick={leave}>算了</button>
      </div>
    </div>
  );
}

/** Before → after, the old words quiet and the new ones plain. */
export function Flow({ before, after, className = "a-chg-flow" }: { before: string; after: string; className?: string }) {
  return (
    <p className={className}>
      <span className="chg-before"><span className="sr-only">改前：</span>{before}</span>
      <span className="chg-arrow" aria-hidden="true">→</span>
      <span className="chg-after"><span className="sr-only">改后：</span>{after}</span>
    </p>
  );
}

const STATE_TEXT = { applied: "已执行", rejected: "没有执行", undone: "已撤销" } as const;

/** The server leaves a fact's closing full stop off before "（第 N 章）"; the preview of a rewording does the same. */
const VALUE_END = /[。．.；;，,、]+$/;

/** Each item's evidence, as the label of an earlier item of the card that stands on the very same passages (shown once). */
function sharedEvidence(items: AssistantChange[]): Record<string, string> {
  const first = new Map<string, string>();
  const same: Record<string, string> = {};
  for (const item of items) {
    if (!item.evidence.length) continue;
    const key = JSON.stringify(item.evidence.map((passage) => [passage.chapter_number, passage.text]));
    const earlier = first.get(key);
    if (earlier) same[item.id] = earlier;
    else first.set(key, item.label);
  }
  return same;
}

function Item({ item, ops, picked, setPicked, typed, setTyped, editing, setEditing, locate, readOnly, goMaterials, decided, alone, sameEvidenceAs }: {
  item: AssistantChange;
  ops: ItemOps;
  picked: boolean;
  setPicked: (value: boolean) => void;
  typed: string | undefined;
  setTyped: (value: string) => void;
  editing: boolean;
  setEditing: (value: boolean) => void;
  locate: (source: AssistantSource) => void;
  readOnly: boolean;
  goMaterials: () => void;
  /** The card has been decided: the items show what became of them. */
  decided: boolean;
  /** The only item of its card: the author's whole sentence is about it, so its words are not repeated under it. */
  alone: boolean;
  /** The label of an earlier item on the same passages: they are listed there, not again. */
  sameEvidenceAs?: string;
}) {
  const local = ops.local(item.id);
  const proposed = item.status === "proposed";
  const reworded = proposed && item.editable && typed !== undefined && typed.trim() !== (item.value ?? "").trim();
  const base = (item.value ?? "").replace(VALUE_END, "");
  const shownAfter = reworded && item.value !== null && item.after.startsWith(base) ? typed!.trim().replace(VALUE_END, "") + item.after.slice(base.length) : item.after;
  const name = `${item.label} ${item.title}`;
  return (
    <section className={`a-opt a-chg${item.status === "rejected" ? " dismissed" : ""}`} aria-label={name} data-change={item.id} data-label={item.label} data-kind={item.kind} data-status={item.status}>
      <div className="a-opt-h">
        {proposed && !decided && (
          <label className="a-chg-pick">
            <input type="checkbox" checked={picked} disabled={readOnly} onChange={(event) => setPicked(event.target.checked)} />
            <span className="sr-only">采用这一条：{name}</span>
          </label>
        )}
        <span className="a-label" aria-hidden="true">{item.label}</span>
        <strong>{item.title}</strong>
        <span className="a-opt-note">{KIND_LABEL[item.kind]}</span>
        {proposed && item.changed_since && <span className="a-edited warn">这条资料已经变了</span>}
        {(reworded || (!proposed && item.edited_by_author)) && <span className="a-edited">你改过</span>}
        {item.status !== "proposed" && <span className={`a-state ${item.status === "applied" ? "blue" : "quiet"}`}>{STATE_TEXT[item.status]}</span>}
      </div>
      <Flow before={item.before} after={shownAfter} />
      {item.request_words && !alone && <p className="a-why a-chg-asked"><span className="sr-only">对应你说的</span>「{item.request_words}」</p>}
      {proposed && item.editable && editing && (
        <textarea className="a-edit" aria-label={`改后的内容：${item.title}`} value={typed ?? item.value ?? ""} rows={3} maxLength={VALUE_MAX}
          aria-invalid={!(typed ?? item.value ?? "").trim() || undefined} onChange={(event) => setTyped(event.target.value)} />
      )}
      {proposed && item.editable && editing && !(typed ?? item.value ?? "").trim() && <p className="a-why a-warn" role="alert">改写的内容不能为空。</p>}
      {sameEvidenceAs && <p className="a-why a-chg-same">依据同 {sameEvidenceAs}</p>}
      {item.evidence.length > 0 && !sameEvidenceAs && (
        <ol className="a-sources a-chg-evidence" aria-label="依据">
          {item.evidence.map((passage, index) => <SourceItem key={index} id={`a-chg-src-${item.id}-${index + 1}`} n={index + 1} source={asSource(passage)} locate={locate} />)}
        </ol>
      )}
      {(proposed && item.editable && !decided && !readOnly) && (
        <div className="a-opt-a">
          <button type="button" className="a-link" aria-expanded={editing} onClick={() => setEditing(!editing)}>{editing ? "改好了" : "改内容"}</button>
        </div>
      )}
      {item.status === "applied" && !readOnly && (
        <div className="a-opt-a">
          <button type="button" className="a-link" disabled={local.busy || Boolean(local.conflict)} onClick={() => ops.undo(item)}>撤销</button>
        </div>
      )}
      {item.status === "undone" && !readOnly && (
        <div className="a-opt-a">
          <button type="button" className="a-link" disabled={local.busy} onClick={() => ops.redo(item)}>恢复</button>
        </div>
      )}
      {local.conflict && <ConflictPrompt conflict={local.conflict} busy={Boolean(local.busy)} undo={() => ops.undo(item, true)} leave={() => ops.leave(item)} />}
      {local.problem && (
        <p className="a-note" role="alert">
          {local.problem.text}
          {local.problem.review && <> <button type="button" className="a-link" onClick={goMaterials}>去资料页</button></>}
        </p>
      )}
    </section>
  );
}

export type CardProps = {
  task: AssistantTask;
  projectId: string;
  /** The work is archived: the card can be read, not decided. */
  readOnly: boolean;
  replace: (next: AssistantTask) => void;
  /** Items that changed on the server (an undo may bring more than the one asked for) go into the conversation. */
  merge: (items: AssistantChange[]) => void;
  locate: (source: AssistantSource) => void;
  written: ChangeWritten;
  goMaterials: () => void;
};

/** The card: one block per item, a tick box in front of each that waits, and 确认 / 不要 below. */
export function ChangeCard({ task, projectId, readOnly, replace, merge, locate, written, goMaterials }: CardProps) {
  const items = task.changes ?? [];
  // What the author chose; an item they have not touched is ticked unless the materials have moved away from what it expects.
  const [choice, setChoice] = useState<Record<string, boolean>>({});
  const [typed, setTyped] = useState<Record<string, string>>({});
  const [editing, setEditing] = useState<Record<string, boolean>>({});
  const [busy, setBusy] = useState<"confirm" | "reject" | null>(null);
  const [problem, setProblem] = useState<ChangeProblem | null>(null);
  const refreshTask = () => request<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}`).then(replace, () => undefined);
  const ops = useItemOps(projectId, merge, written, () => void refreshTask());
  if (!items.length) return null;
  const waiting = items.some((item) => item.status === "proposed");
  const picked = (item: AssistantChange) => choice[item.id] ?? !item.changed_since;
  const chosen = items.filter((item) => item.status === "proposed" && picked(item));
  const emptied = chosen.some((item) => item.editable && typed[item.id] !== undefined && !typed[item.id].trim());
  const edits = Object.fromEntries(chosen.filter((item) => item.editable && typed[item.id] !== undefined && typed[item.id].trim() !== (item.value ?? "").trim()).map((item) => [item.id, typed[item.id].trim()]));
  const decide = async (step: "confirm" | "reject") => {
    setBusy(step); setProblem(null);
    try {
      const next = await json<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}/changes/${step}`, "POST", step === "confirm" ? { accepted: chosen.map((item) => item.id), edits } : {});
      replace(next);
      if (step === "confirm") written();
    } catch (cause) {
      setProblem(changeProblem(cause, "confirm"));
      // The card may have moved on (decided in another window, or the materials changed): show it as it is now.
      if (["change_target_changed", "change_already_decided", "change_state_invalid", "change_target_missing"].includes((cause as ApiFailure).code)) await refreshTask();
    } finally { setBusy(null); }
  };
  const why = readOnly ? "作品已归档，只能浏览。" : "";
  const shared = sharedEvidence(items);
  return (
    <section className="a-chg-card" aria-label="资料改动" data-change-card={task.id} data-waiting={waiting || undefined}>
      <div className="a-chg-head">
        <strong>资料改动 · {items.length} 条</strong>
        <span className="a-opt-note">确认后才会执行，之后可以撤销</span>
      </div>
      {items.map((item) => (
        <Item key={item.id} item={item} ops={ops} picked={picked(item)} setPicked={(value) => setChoice((all) => ({ ...all, [item.id]: value }))}
          typed={typed[item.id]} setTyped={(value) => setTyped((all) => ({ ...all, [item.id]: value }))}
          editing={Boolean(editing[item.id])} setEditing={(value) => setEditing((all) => ({ ...all, [item.id]: value }))}
          locate={locate} readOnly={readOnly} goMaterials={goMaterials} decided={!waiting} alone={items.length === 1} sameEvidenceAs={shared[item.id]} />
      ))}
      {waiting && (
        <div className="a-opt-a a-chg-actions">
          <button type="button" className="a-btn" disabled={Boolean(busy) || readOnly || chosen.length === 0 || emptied} title={why || undefined} onClick={() => void decide("confirm")}>确认（{chosen.length} 条）</button>
          <button type="button" className="a-link" disabled={Boolean(busy) || readOnly} title={why || undefined} onClick={() => void decide("reject")}>不要</button>
        </div>
      )}
      {problem && (
        <p className="a-note" role="alert">
          {problem.text}
          {problem.review && <> <button type="button" className="a-link" onClick={goMaterials}>去资料页</button></>}
        </p>
      )}
    </section>
  );
}

/** Items that came back from the server go into the tasks that hold them. */
export function mergeChanges(setTasks: Dispatch<SetStateAction<AssistantTask[] | null>>, items: AssistantChange[]) {
  const byId = new Map(items.map((item) => [item.id, item]));
  setTasks((current) => current && current.map((task) => (task.changes?.some((item) => byId.has(item.id)) ? { ...task, changes: task.changes.map((item) => byId.get(item.id) ?? item) } : task)));
}
