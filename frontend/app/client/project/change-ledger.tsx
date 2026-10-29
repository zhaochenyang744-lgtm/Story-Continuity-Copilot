"use client";

// 助手改动记录 (v2.0): on the materials page, what the assistant changed with the author's word, the latest first, each with
// 撤销 or 恢复; and the little tags the facts and threads it wrote carry. The ledger is the server's (GET /assistant/changes).
// v2.1 adds the 采用改法 of the writing page (adopted, or adopted and then undone) and pages: 再看更早的 asks for the page after the
// last entry shown (a position, not a count), because an undo moves an entry to the top.
import { useCallback, useEffect, useMemo, useState } from "react";
import { type ApiFailure, json, labelError, request } from "../../api";
import type { AssistantAdoption, AssistantChange, AssistantProposal, LedgerEntry } from "../../model";
import { timeLabel } from "../labels";
import { Button, SectionHead, Tag } from "../ui";
import { ConflictPrompt, Flow, KIND_LABEL, useItemOps } from "./assistant-change";
import { proposalError } from "./assistant-fix";

export const isAdoption = (entry: LedgerEntry): entry is AssistantAdoption => entry.entry === "adoption";
const PAGE = 50;
const ADOPTION_KIND = { edit_this: "改这一句", add_setup: "补一句设定" } as const;
const keyOf = (item: LedgerEntry) => `${item.entry ?? "change"}:${item.id}`;

export type Ledger = {
  /** Null until the first answer. */
  items: LedgerEntry[] | null;
  /** Where the page after the last one shown starts; null when there is nothing earlier. */
  next: string | null;
  loadingMore: boolean;
  failure: string;
  reload: () => Promise<void>;
  more: () => Promise<void>;
  merge: (items: AssistantChange[]) => void;
  /** An adoption was undone: the entry stays, as undone. */
  settle: (proposal: AssistantProposal) => void;
};

type Page = { changes: LedgerEntry[]; next: string | null };

/** The ledger, read when the page opens and again whenever the materials were changed by the assistant (`stamp`). */
export function useLedger(projectId: string, stamp: number): Ledger {
  const [items, setItems] = useState<LedgerEntry[] | null>(null);
  const [next, setNext] = useState<string | null>(null);
  const [loadingMore, setLoadingMore] = useState(false);
  const [failure, setFailure] = useState("");
  const reload = useCallback(async () => {
    try {
      const data = await request<Page>(`/projects/${projectId}/assistant/changes?limit=${PAGE}`);
      setItems(data.changes); setNext(data.next ?? null); setFailure("");
    } catch (cause) { setFailure(labelError(cause)); }
  }, [projectId]);
  useEffect(() => { void Promise.resolve().then(reload); }, [reload, stamp]);
  const more = useCallback(async () => {
    if (!next) return;
    setLoadingMore(true);
    try {
      const data = await request<Page>(`/projects/${projectId}/assistant/changes?limit=${PAGE}&before=${encodeURIComponent(next)}`);
      // An entry that moved while the author was reading may come again: it is kept once.
      setItems((current) => {
        const seen = new Set((current ?? []).map(keyOf));
        return [...(current ?? []), ...data.changes.filter((item) => !seen.has(keyOf(item)))];
      });
      setNext(data.next ?? null); setFailure("");
    } catch (cause) { setFailure(labelError(cause)); } finally { setLoadingMore(false); }
  }, [projectId, next]);
  const merge = useCallback((changed: AssistantChange[]) => {
    const byId = new Map(changed.map((item) => [item.id, item]));
    setItems((current) => current && current.map((item) => (isAdoption(item) ? item : byId.get(item.id) ?? item)));
  }, []);
  const settle = useCallback((proposal: AssistantProposal) => {
    setItems((current) => current && current.map((item) => (isAdoption(item) && item.id === proposal.id
      ? { ...item, status: "undone" as const, undone_at: proposal.undone_at ?? new Date().toISOString() } : item)));
  }, []);
  return { items, next, loadingMore, failure, reload, more, merge, settle };
}

/** Which records carry a tag: a fact by the record it is in the current version, a thread by its id. The newest item of a record says what
    was done to it; a record the author has changed since (the item no longer holds) carries no tag, for the words would no longer be true. */
export type Marks = { facts: Map<string, string>; threads: Map<string, string> };
export function marksOf(items: LedgerEntry[] | null): Marks {
  const marks: Marks = { facts: new Map(), threads: new Map() };
  for (const item of items ?? []) {
    if (isAdoption(item) || item.status !== "applied" || item.changed_since) continue;
    if (item.target.kind === "foreshadow") {
      if (!marks.threads.has(item.target.id)) marks.threads.set(item.target.id, item.kind === "add_thread" ? "助手按你的确认添加" : "助手按你的确认修改");
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

/** When the entry was written and, if it was taken back, when: both stay on the entry. */
function Times({ at, atLabel, undone }: { at: string | null; atLabel: string; undone: string | null }) {
  return (
    <span className="ledger-time label">
      {at && <span className="ledger-at">{atLabel} {timeLabel(at)}</span>}
      {undone && <span className="ledger-at">撤销 {timeLabel(undone)}</span>}
    </span>
  );
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
  const [adoptions, setAdoptions] = useState<Record<string, { busy?: boolean; problem?: string }>>({});
  const setAdoption = (id: string, next: { busy?: boolean; problem?: string } | null) => setAdoptions((current) => {
    const copy = { ...current };
    if (next) copy[id] = next; else delete copy[id];
    return copy;
  });
  // 撤销采用 only records the undo; the draft is not touched (the writing page's card puts the sentence back in the editor itself).
  const undoAdoption = async (item: AssistantAdoption) => {
    setAdoption(item.id, { busy: true });
    try {
      ledger.settle(await json<AssistantProposal>(`/projects/${projectId}/assistant/tasks/${item.task_id}/proposals/${item.id}/undo`, "POST", {}));
      setAdoption(item.id, null);
    } catch (cause) {
      const code = (cause as ApiFailure)?.code;
      setAdoption(item.id, { problem: proposalError(code, cause) });
      // The entry may have moved on without this page knowing: read the ledger again.
      if (code === "proposal_state_invalid" || code === "resource_not_found") void ledger.reload();
    }
  };
  return (
    <section className="ledger" aria-label="助手改动记录" data-testid="change-ledger">
      <SectionHead level={3} title="助手改动记录" aside={<span className="label">只记你确认过的改动，最新的在前</span>} />
      {ledger.failure && <p className="note note-error" role="alert">{ledger.failure}</p>}
      {items === null && !ledger.failure && <p className="loading">正在读取…</p>}
      {items !== null && !list.length && <p className="empty">还没有助手改过的资料。</p>}
      {list.length > 0 && (
        <ol className="ledger-list">
          {list.map((item) => {
            if (isAdoption(item)) {
              const local = adoptions[item.id] ?? {};
              return (
                <li key={`adoption:${item.id}`} data-adoption={item.id} data-label={item.label} data-kind={item.kind} data-status={item.status} className={item.status === "undone" ? "undone" : undefined}>
                  <Times at={item.adopted_at} atLabel="采用" undone={item.undone_at} />
                  <span className="ledger-copy">
                    <span className="ledger-head">
                      <Tag tone="line">采用改法</Tag>
                      <strong>{item.chapter_number != null ? `第 ${item.chapter_number} 章` : "改法"}</strong>
                      <span className="label">{ADOPTION_KIND[item.kind]}</span>
                      {item.edited_by_author && <span className="label">你改过</span>}
                    </span>
                    <Flow before={item.before || "（新增一句）"} after={item.after} className="ledger-flow" />
                    {local.problem && <p className="note note-warn" role="alert"><span>{local.problem}</span></p>}
                  </span>
                  <span className="ledger-side">
                    <span className="ledger-state">{item.status === "adopted" ? "已采用" : "已撤销采用"}</span>
                    <span className="actions">
                      {!readOnly && item.status === "adopted" && <Button kind="text" disabled={local.busy} onClick={() => void undoAdoption(item)}>撤销采用</Button>}
                      {openTask && <Button kind="text" onClick={() => openTask(item.task_id)}>看对话</Button>}
                    </span>
                    {!readOnly && item.status === "adopted" && <span className="label ledger-note">只记为撤销，不改你的正文。</span>}
                  </span>
                </li>
              );
            }
            const local = ops.local(item.id);
            return (
              <li key={item.id} data-change={item.id} data-label={item.label} data-kind={item.kind} data-status={item.status} className={item.status === "undone" ? "undone" : undefined}>
                <Times at={item.applied_at} atLabel="确认" undone={item.undone_at} />
                <span className="ledger-copy">
                  <span className="ledger-head"><Tag tone="line">{KIND_LABEL[item.kind]}</Tag><strong>{item.title}</strong>{item.edited_by_author && <span className="label">你改过</span>}</span>
                  <Flow before={item.before} after={item.after} className="ledger-flow" />
                  {local.conflict && <ConflictPrompt page conflict={local.conflict} busy={Boolean(local.busy)} undo={() => ops.undo(item, true)} leave={() => ops.leave(item)} />}
                  {local.problem && (
                    <p className="note note-warn" role="alert"><span>{local.problem.text}</span></p>
                  )}
                </span>
                <span className="ledger-side">
                  <span className="ledger-state">{item.status === "applied" ? "已写入" : "已撤销"}</span>
                  <span className="actions">
                    {!readOnly && item.status === "applied" && <Button kind="text" disabled={local.busy || Boolean(local.conflict)} onClick={() => void ops.undo(item)}>撤销</Button>}
                    {!readOnly && item.status === "undone" && <Button kind="text" disabled={local.busy} onClick={() => void ops.redo(item)}>恢复</Button>}
                    {openTask && <Button kind="text" onClick={() => openTask(item.task_id)}>看对话</Button>}
                  </span>
                </span>
              </li>
            );
          })}
        </ol>
      )}
      {ledger.next && (
        <div className="ledger-more">
          <Button kind="small" disabled={ledger.loadingMore} onClick={() => void ledger.more()}>{ledger.loadingMore ? "正在读取…" : "再看更早的"}</Button>
        </div>
      )}
    </section>
  );
}
