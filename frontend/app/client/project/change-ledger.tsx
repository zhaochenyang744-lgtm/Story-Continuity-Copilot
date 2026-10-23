"use client";

// 助手改动记录 (v2.0): on the materials page, what the assistant changed with the author's word, the latest first, each with
// 撤销 or 恢复; and the little tags the facts and threads it wrote carry. The ledger is the server's (GET /assistant/changes).
import { useCallback, useEffect, useMemo, useState } from "react";
import { labelError, request } from "../../api";
import type { AssistantChange } from "../../model";
import { timeLabel } from "../labels";
import { Button, SectionHead, Tag } from "../ui";
import { ConflictPrompt, Flow, KIND_LABEL, useItemOps } from "./assistant-change";

export type Ledger = {
  /** Null until the first answer. */
  items: AssistantChange[] | null;
  failure: string;
  reload: () => Promise<void>;
  merge: (items: AssistantChange[]) => void;
};

/** The ledger, read when the page opens and again whenever the materials were changed by the assistant (`stamp`). */
export function useLedger(projectId: string, stamp: number): Ledger {
  const [items, setItems] = useState<AssistantChange[] | null>(null);
  const [failure, setFailure] = useState("");
  const reload = useCallback(async () => {
    try {
      const data = await request<{ changes: AssistantChange[] }>(`/projects/${projectId}/assistant/changes?limit=50`);
      setItems(data.changes); setFailure("");
    } catch (cause) { setFailure(labelError(cause)); }
  }, [projectId]);
  useEffect(() => { void Promise.resolve().then(reload); }, [reload, stamp]);
  const merge = useCallback((changed: AssistantChange[]) => {
    const byId = new Map(changed.map((item) => [item.id, item]));
    setItems((current) => current && current.map((item) => byId.get(item.id) ?? item));
  }, []);
  return { items, failure, reload, merge };
}

/** Which records carry a tag: a fact by the record it is in the current version, a thread by its id. The newest item of a record says what
    was done to it; a record the author has changed since (the item no longer holds) carries no tag, for the words would no longer be true. */
export type Marks = { facts: Map<string, string>; threads: Map<string, string> };
export function marksOf(items: AssistantChange[] | null): Marks {
  const marks: Marks = { facts: new Map(), threads: new Map() };
  for (const item of items ?? []) {
    if (item.status !== "applied" || item.changed_since) continue;
    if (item.target.kind === "foreshadow") {
      if (!marks.threads.has(item.target.id)) marks.threads.set(item.target.id, "助手按你的确认修改");
    } else if (item.target.record_id && !marks.facts.has(item.target.record_id)) {
      marks.facts.set(item.target.record_id, item.kind === "add_fact" ? "助手按你的确认添加" : "助手按你的确认修改");
    }
  }
  return marks;
}

/** The little tag a fact or thread carries when the assistant wrote it. */
export function AssistantMark({ text }: { text: string | undefined }) {
  return text ? <span className="assistant-mark"><Tag tone="state">{text}</Tag></span> : null;
}

export function ChangeLedger({ projectId, ledger, written, readOnly, openTask }: {
  projectId: string;
  ledger: Ledger;
  /** Something was undone or applied again: the page reads facts and threads again. */
  written: () => void;
  readOnly: boolean;
  /** 看对话: opens the assistant at the task the item came from (null where the assistant is not offered). */
  openTask: ((taskId: string) => void) | null;
}) {
  const ops = useItemOps(projectId, ledger.merge, written, () => void ledger.reload());
  const items = ledger.items;
  const list = useMemo(() => items ?? [], [items]);
  return (
    <section className="ledger" aria-label="助手改动记录" data-testid="change-ledger">
      <SectionHead level={3} title="助手改动记录" aside={<span className="label">只记你确认过的改动，最新的在前</span>} />
      {ledger.failure && <p className="note note-error" role="alert">{ledger.failure}</p>}
      {items === null && !ledger.failure && <p className="loading">正在读取…</p>}
      {items !== null && !list.length && <p className="empty">还没有助手改过的资料。</p>}
      {list.length > 0 && (
        <ol className="ledger-list">
          {list.map((item) => {
            const local = ops.local(item.id);
            return (
              <li key={item.id} data-change={item.id} data-label={item.label} data-kind={item.kind} data-status={item.status} className={item.status === "undone" ? "undone" : undefined}>
                <span className="ledger-time label">{timeLabel(item.undone_at ?? item.applied_at)}</span>
                <span className="ledger-copy">
                  <span className="ledger-head"><Tag tone="line">{KIND_LABEL[item.kind]}</Tag><strong>{item.title}</strong>{item.edited_by_author && <span className="label">你改过</span>}</span>
                  <Flow before={item.before} after={item.after} className="ledger-flow" />
                  {local.conflict && <ConflictPrompt page conflict={local.conflict} busy={Boolean(local.busy)} undo={() => ops.undo(item, true)} leave={() => ops.leave(item)} />}
                  {local.problem && (
                    <p className="note note-warn" role="alert"><span>{local.problem.text}</span></p>
                  )}
                </span>
                <span className="ledger-side">
                  <span className="ledger-state">{item.status === "applied" ? "已执行" : "已撤销"}</span>
                  <span className="actions">
                    {!readOnly && item.status === "applied" && <Button kind="text" disabled={local.busy || Boolean(local.conflict)} onClick={() => ops.undo(item)}>撤销</Button>}
                    {!readOnly && item.status === "undone" && <Button kind="text" disabled={local.busy} onClick={() => ops.redo(item)}>恢复</Button>}
                    {openTask && <Button kind="text" onClick={() => openTask(item.task_id)}>看对话</Button>}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
    </section>
  );
}
