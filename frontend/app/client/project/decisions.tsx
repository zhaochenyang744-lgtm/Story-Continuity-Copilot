"use client";

// 决定 (v2.2): what the author said to keep doing from now on ("这处是故意的", "以第三章为准", "冰下三声先别收"), remembered once they confirmed it
// on a card of the assistant. The list is the server's (GET /decisions); the author can read where each one came from, reword it, change what it
// covers, say that a possibly out-of-date one still holds, or delete it. Nothing here makes a decision: the records are made on the cards.
import { type FormEvent, useCallback, useEffect, useState } from "react";
import { type ApiFailure, json, labelError, request } from "../../api";
import type { AuthorDecision, DecisionList } from "../../model";
import { Button, Tag } from "../ui";

export const DECISION_LIMIT = 200;
const STATEMENT_MAX = 80;
const SUBJECTS_MAX = 6;
/** The way to the 决定 tab of the materials page (the server's review path for a decision that passed a finding over names the same place). */
export const decisionsPath = (projectId: string) => `/projects/${projectId}/memory?view=decisions`;

export type Decisions = {
  /** Null until the first answer. */
  list: DecisionList | null;
  failure: string;
  /** Reads the list again; gives the list read (null when it could not be). */
  reload: () => Promise<DecisionList | null>;
};

/** The decisions of the work, read when the page opens and again whenever the materials were changed by the assistant (`stamp`). */
export function useDecisions(projectId: string, stamp: number): Decisions {
  const [list, setList] = useState<DecisionList | null>(null);
  const [failure, setFailure] = useState("");
  const reload = useCallback(async () => {
    try { const read = await request<DecisionList>(`/projects/${projectId}/decisions`); setList(read); setFailure(""); return read; }
    catch (cause) { setFailure(labelError(cause)); return null; }
  }, [projectId]);
  useEffect(() => { void Promise.resolve().then(reload); }, [reload, stamp]);
  return { list, failure, reload };
}

type Draft = { statement: string; subjects: string; whole: boolean; from: string; to: string };
const draftOf = (decision: AuthorDecision): Draft => ({
  statement: decision.statement,
  subjects: decision.subjects.join("、"),
  whole: !decision.chapters,
  from: String(decision.chapters?.[0] ?? decision.basis_chapter ?? 1),
  to: String(decision.chapters?.[1] ?? decision.basis_chapter ?? 1),
});
const subjectsOf = (text: string) => text.split(/[、,，;；\s]+/).map((name) => name.trim()).filter(Boolean);

function DecisionRow({ decision, readOnly, busy, editing, startEdit, stopEdit, save, conflict, loadLatest, holds, remove, openTask, openFinding }: {
  decision: AuthorDecision;
  readOnly: boolean;
  busy: boolean;
  editing: boolean;
  startEdit: () => void;
  stopEdit: () => void;
  save: (draft: Draft) => void;
  conflict: boolean;
  loadLatest: () => void;
  holds: () => void;
  remove: () => void;
  /** 看对话: opens the assistant at the task the decision came from (null where the assistant is not offered). */
  openTask: ((taskId: string) => void) | null;
  /** 回到那条检查结果: the writing page at the finding a check note's decision was made from (null once the finding is no longer in the check). */
  openFinding: ((issueId: string) => void) | null;
}) {
  const [draft, setDraft] = useState<Draft>(() => draftOf(decision));
  const [fromWhere, setFromWhere] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const stale = decision.status === "stale";
  const superseded = decision.status === "superseded";
  const subjects = subjectsOf(draft.subjects);
  const from = Number(draft.from), to = Number(draft.to);
  const rangeBad = !draft.whole && (!Number.isInteger(from) || !Number.isInteger(to) || from < 1 || to < from);
  const invalid = !draft.statement.trim() || subjects.length > SUBJECTS_MAX || rangeBad;
  const hasTask = (decision.source === "box" || decision.source === "long_choice") && Boolean(decision.source_ref);
  const fromCheck = decision.source === "check_note" && Boolean(decision.source_ref);
  return (
    <li id={`decision-${decision.id}`} className={superseded ? "retired" : undefined} data-decision={decision.id} data-kind={decision.kind} data-status={decision.status}>
      <span className="decision-kind"><Tag tone="line">{decision.kind_label}</Tag></span>
      <span className="decision-copy">
        {editing ? (
          <form className="thread-form decision-form" aria-label="改这条决定" onSubmit={(event: FormEvent) => { event.preventDefault(); if (!invalid) save(draft); }}>
            <label className="field"><span className="field-label">决定内容<span className="field-count">{draft.statement.length} / {STATEMENT_MAX}</span></span>
              <input value={draft.statement} maxLength={STATEMENT_MAX} onChange={(event) => setDraft({ ...draft, statement: event.target.value })} /></label>
            <label className="field"><span className="field-label">管哪些人或物</span>
              <input value={draft.subjects} onChange={(event) => setDraft({ ...draft, subjects: event.target.value })} placeholder="用顿号隔开，例如：苏岑、冰下三声" aria-invalid={subjects.length > SUBJECTS_MAX || undefined} />
              {subjects.length > SUBJECTS_MAX && <span className="field-hint" role="alert">最多写 {SUBJECTS_MAX} 个。</span>}</label>
            <fieldset className="radio-row decision-range">
              <legend className="field-label">管哪几章</legend>
              <label><input type="radio" name={`range-${decision.id}`} checked={draft.whole} onChange={() => setDraft({ ...draft, whole: true })} />全书</label>
              <label><input type="radio" name={`range-${decision.id}`} checked={!draft.whole} onChange={() => setDraft({ ...draft, whole: false })} />指定章节</label>
              {!draft.whole && (
                <span className="decision-chapters">
                  第 <input type="number" min={1} inputMode="numeric" aria-label="起始章" value={draft.from} onChange={(event) => setDraft({ ...draft, from: event.target.value })} /> 章到第 <input type="number" min={1} inputMode="numeric" aria-label="结束章" value={draft.to} onChange={(event) => setDraft({ ...draft, to: event.target.value })} /> 章
                </span>
              )}
            </fieldset>
            {rangeBad && <p className="field-hint" role="alert">起始章要在结束章之前，章号从 1 起。</p>}
            {conflict && <div className="note note-warn" role="alert"><span>这条决定在别处改过；你填的内容还在。载入最新版本，核对后再保存。</span><Button kind="text" disabled={busy} onClick={loadLatest}>载入最新版本</Button></div>}
            <div className="form-actions">
              <Button kind="primary" type="submit" disabled={busy || invalid}>保存</Button>
              <Button kind="text" disabled={busy} onClick={stopEdit}>取消</Button>
            </div>
          </form>
        ) : (
          <>
            <strong className="decision-statement">{decision.statement}</strong>
            <span className="decision-scope">{decision.scope}</span>
            {stale && <span className="decision-flag" data-testid="decision-stale"><Tag tone="mid">可能过时</Tag><span className="small-note">它依据的{decision.basis_chapter ? `第 ${decision.basis_chapter} 章` : "章节"}后来改过，请看一下。</span></span>}
            {superseded && <span className="decision-flag" data-testid="decision-superseded"><Tag tone="line">已取代</Tag><span className="small-note">后来记下的另一条决定取代了它，助手不再照这一条办。</span></span>}
            <button type="button" className="link decision-from" aria-expanded={fromWhere} onClick={() => setFromWhere((open) => !open)}>{fromWhere ? "收起" : "从哪来"}</button>
            {fromWhere && (
              <span className="decision-source">
                <span className="small-note">{decision.source_label}{decision.basis_chapter ? ` · 依据第 ${decision.basis_chapter} 章` : ""}</span>
                <span className="decision-quote">你说的：「{decision.quote}」</span>
                {hasTask && openTask && <button type="button" className="link" onClick={() => openTask(decision.source_ref!)}>看对话</button>}
                {fromCheck && openFinding && <button type="button" className="link" onClick={() => openFinding(decision.source_ref!)}>回到那条检查结果</button>}
              </span>
            )}
          </>
        )}
      </span>
      <span className="decision-side">
        {!readOnly && !editing && (
          <span className="actions">
            {stale && <Button kind="small" disabled={busy} onClick={holds}>仍然有效</Button>}
            {!superseded && <Button kind="text" disabled={busy} onClick={() => { setDraft(draftOf(decision)); startEdit(); }}>编辑</Button>}
            {!confirming && <Button kind="text" disabled={busy} onClick={() => setConfirming(true)}>删除</Button>}
          </span>
        )}
        {confirming && !editing && (
          <span className="decision-confirm" role="alert">
            <span>删除后助手不再照这条办。确定删除？</span>
            <span className="actions">
              <Button kind="small" disabled={busy} onClick={() => { setConfirming(false); remove(); }}>确认删除</Button>
              <Button kind="text" disabled={busy} onClick={() => setConfirming(false)}>取消</Button>
            </span>
          </span>
        )}
      </span>
    </li>
  );
}

/** 决定: the list in the server's order: those that may be out of date first, then those in force, then those replaced. */
export function DecisionsView({ projectId, decisions, readOnly, openTask, findingIds, go }: {
  projectId: string; decisions: Decisions; readOnly: boolean; openTask: ((taskId: string) => void) | null;
  /** The findings of the check now on the writing page, and the way to another page: a decision made from a check note can lead back to its finding. */
  findingIds: ReadonlySet<string>; go: (href: string) => void;
}) {
  const [editing, setEditing] = useState<{ id: string; revision: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const { list, failure, reload } = decisions;
  // The line about the last thing done here belongs to the list it left behind: when the list is read again for another reason (a card of the
  // assistant was confirmed, the work was changed elsewhere) the line is not about this list any more and goes.
  const [said, setSaid] = useState<{ text: string; list: DecisionList | null }>({ text: "", list: null });
  const notice = said.text && said.list === list ? said.text : "";
  const setNotice = (text: string, at: DecisionList | null = list) => setSaid({ text, list: at });
  const [conflict, setConflict] = useState(false);
  const items = list?.decisions ?? [];
  const limit = list?.limit ?? DECISION_LIMIT;
  const run = async (work: () => Promise<unknown>, done: string): Promise<boolean> => {
    setBusy(true); setNotice(""); setConflict(false);
    try { await work(); setNotice(done, (await reload()) ?? list); return true; }
    catch (cause) {
      const failed = cause as ApiFailure;
      setConflict(failed.code === "decision_revision_conflict");
      if (failed.code === "resource_not_found") { setEditing(null); setNotice(labelError(cause), (await reload()) ?? list); }
      else setNotice(labelError(cause));
      return false;
    } finally { setBusy(false); }
  };
  const save = async (decision: AuthorDecision, draft: Draft) => {
    const ok = await run(() => json(`/projects/${projectId}/decisions/${decision.id}`, "PATCH", {
      base_revision: editing?.id === decision.id ? editing.revision : decision.revision, statement: draft.statement.trim(), subjects: subjectsOf(draft.subjects),
      ...(draft.whole ? { whole_work: true } : { chapters: [Number(draft.from), Number(draft.to)] }),
    }), "这条决定改好了。");
    if (ok) setEditing(null);
  };
  // The newest version of the decision being edited: the words the author typed stay, the revision to save against moves on.
  const loadLatest = async () => {
    setBusy(true);
    try {
      const latest = await reload();
      if (!latest) return;
      const record = latest.decisions.find((item) => item.id === editing?.id);
      if (record) { setEditing({ id: record.id, revision: record.revision }); setConflict(false); setNotice("载入了最新版本；你填的内容还在，核对后再保存。", latest); }
      else { setEditing(null); setConflict(false); setNotice("这条决定已经不在了。", latest); }
    } finally { setBusy(false); }
  };
  const holds = (decision: AuthorDecision) => void run(() => json(`/projects/${projectId}/decisions/${decision.id}`, "PATCH", { base_revision: decision.revision, still_holds: true }), "好，这条决定仍然有效。");
  const remove = (decision: AuthorDecision) => void run(() => json(`/projects/${projectId}/decisions/${decision.id}/delete`, "POST", { base_revision: decision.revision }), "这条决定删掉了。");
  return (
    <div className="materials-view decisions">
      {failure && <p className="note note-error" role="alert">{failure}</p>}
      {list === null && !failure && <p className="loading">正在读取…</p>}
      {list !== null && <p className="small-note decision-count" data-testid="decision-count">已记 {items.length} / {limit} 条</p>}
      {notice && <p className="small-note" role="status">{notice}</p>}
      {list !== null && !items.length && (
        <p className="empty">你在助手里说过的、以后也要照办的决定会记在这里，比如“这处是故意的”“以第三章为准”。每一条都要你确认才会记下。</p>
      )}
      {items.length > 0 && (
        <ol className="decision-list" aria-label="决定列表">
          {items.map((decision) => (
            <DecisionRow key={decision.id} decision={decision} readOnly={readOnly} busy={busy} editing={editing?.id === decision.id}
              startEdit={() => { setEditing({ id: decision.id, revision: decision.revision }); setNotice(""); setConflict(false); }}
              stopEdit={() => { setEditing(null); setConflict(false); setNotice(""); }}
              save={(draft) => void save(decision, draft)} conflict={conflict && editing?.id === decision.id} loadLatest={() => void loadLatest()}
              holds={() => holds(decision)} remove={() => remove(decision)} openTask={openTask}
              openFinding={decision.source === "check_note" && decision.source_ref && findingIds.has(decision.source_ref) ? (issueId) => go(`/projects/${projectId}/workspace#issue-${issueId}`) : null} />
          ))}
        </ol>
      )}
    </div>
  );
}
