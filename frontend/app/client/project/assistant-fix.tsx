"use client";

// 帮我改这一处 as an assistant task: why a finding was raised, and up to three ways to deal with it. The assistant
// only proposes. A change reaches the draft through the editor and its autosave; only after the saved text shows the
// change is it recorded here as adopted. Nothing in this file writes the draft, the facts or the author's decision itself.
// A change is shown as the words that go and the words that come; before adopting, the new sentence can be reworded.
import { type Dispatch, type SetStateAction, useEffect, useRef, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { AssistantProposal, AssistantSource, AssistantTask, Issue, ProposalRecheck, RecheckIssue } from "../../model";
import { findingTone } from "../labels";
import { formatCount, Num, writtenChars } from "../ui";
import { diffView } from "./assistant-diff";
import { requestLocate } from "./assistant-locate";
import { AnswerBlock, Feedback, useJustFinished } from "./assistant-answer";
import { active, CoverLine, failureText, LimitLine, SourceList, StoppedNote } from "./assistant-parts";
import { Steps } from "./assistant-process";
import { ChosenLine, RerouteMenu } from "./assistant-route";
import { FindingTag, findingHeadline } from "./findings";

/** What the thread needs from the writing page's draft to apply, undo and wait for a save. */
export type DraftLink = {
  /** Non-empty when the draft cannot take a change now (read only, locked), in words. */
  blocked: string;
  /** The revision of the saved draft, and whether the editor holds anything not saved yet. */
  revision: number;
  dirty: boolean;
  autosave: "idle" | "saving" | "saved" | "failed" | "conflict";
  /** How often `text` is in the editor right now (overlapping matches counted). */
  count: (text: string) => number;
  /** Put `after` in the place of `before`; false when the editor could not find it exactly. `proofread` marks the change (the old words struck, the new ones dropping in); otherwise it only glows. */
  replace: (before: string, after: string, mode?: "proofread") => Promise<boolean>;
  /** Save the draft now rather than after the idle wait; the usual autosave still follows if this one is skipped. */
  saveNow: () => void;
};
/** A finding of the latest check, as the writing page shows it, with what 标为有意为之 would do. */
export type IssueInfo = {
  number: number;
  issue: Issue;
  keep: { done: boolean; reason: string; run: () => Promise<boolean> };
};
export type WritingLink = {
  draft: DraftLink;
  issue: (issueId: string) => IssueInfo | null;
  /** Open a written chapter in the writing page. */
  openChapter: (number: number) => void;
  /** The findings that have an adopted assistant change, for the little tag in the list. */
  adoptedChanged: (issueIds: string[]) => void;
  busyChanged: (busy: boolean) => void;
};

const CHANGED = "原句已经改过，可以按要求重新给改法。";
const RECHECK_LIMIT = 600;

/** The sentence a change puts in the draft: the author's wording when they reworded it, else the assistant's. */
export const effectiveAfter = (proposal: Pick<AssistantProposal, "after" | "after_edited">) => proposal.after_edited ?? proposal.after;

/** The server's rules for a reworded sentence, asked of the page too, so a sentence the server would refuse never reaches the draft.
    Returns the words for what is wrong (empty when it is fine). */
export function afterProblem(before: string, after: string): string {
  if (!after.trim()) return proposalError("proposal_after_missing");
  if (after === before) return "和原句一样，还没有改动。";
  if (after.includes(before)) return proposalError("proposal_after_contains_before");
  const most = Array.from(before).length * 2 + 60;
  if (Array.from(after).length > most) return `比原句长太多，最多 ${most} 字。`;
  return "";
}

/** The words for what went wrong with a change or a recheck (never the code). */
export function proposalError(code: string | undefined, cause?: unknown): string {
  switch (code) {
    case "proposal_not_applied": return "保存的正文和改法对不上，没有记录为已采用。编辑器里的改动还在，由你决定。";
    case "proposal_state_invalid": return "这条改法的状态已经变了，刷新页面再看。";
    case "invalid_request": return "这一步缺少必要的内容，没有记录。保存草稿并刷新页面后再试一次。";
    case "proposal_task_not_completed": return "这个任务还没有完成，不能操作它的改法。";
    case "proposal_recheck_running": return "这条改法正在复查，等复查结束再操作。";
    case "proposal_after_missing": return "改后的句子不能为空。";
    // The page checks the sentence itself before it asks, so this one only comes back for a sentence changed behind its back.
    case "proposal_after_invalid": return "改后的句子没有通过检查：和原句一样，或者比原句长太多。";
    case "proposal_after_contains_before": return "改后的句子里原样留着原句，请把原句改掉。";
    case "proposal_text_internal_id": return "改后的句子里有不能出现的内部编号，请删掉。";
    case "assistant_check_visitor_forbidden": return "访客不能复查，注册账号后可以用。";
    case "passage_too_long": return "改后的句子超过 600 字，不能复查。";
    case "passage_check_incomplete": return "复查没能把每句都判断完，所以不下结论，也没有计字数。可以重试。";
    case "character_quota_exceeded": return "今天的可检查字数不够复查这一句。";
    case "resource_not_found": return "这条改法已经不在了（对话可能被清空了）。";
    case "assistant_proposal_adopt_failed":
    case "assistant_proposal_dismiss_failed":
    case "assistant_proposal_undo_failed":
    case "assistant_proposal_recheck_failed": return "这一步没有成功，请再试一次。";
    case "request_timeout": return "这一步花的时间比平时长，结果可能已经保存。刷新页面看看。";
    case "provider_timeout":
    case "provider_error":
    case "provider_failure":
    case "provider_unavailable":
    case "input_budget_exceeded":
    case "output_truncated":
    case "invalid_json":
    case "budget_paused":
    case "assistant_budget_exhausted":
    case "internal_error": return "模型这次没有给出复查结果，没有计字数。可以重试。";
    default: return cause ? labelError(cause) : "复查没有完成，没有计字数。可以重试。";
  }
}

type Local = { busy?: "adopt" | "undo" | "dismiss" | "recheck"; waiting?: "adopt" | "undo"; error?: string; revert?: string };
type Waiting = { taskId: string; action: "adopt" | "undo"; base: number; /** The author's wording, when it is not the assistant's. */ after?: string };
export type ProposalActions = {
  local: (proposalId: string) => Local;
  adopt: (task: AssistantTask, proposal: AssistantProposal, reworded?: string) => void;
  undo: (task: AssistantTask, proposal: AssistantProposal) => void;
  dismiss: (task: AssistantTask, proposal: AssistantProposal) => void;
  recheck: (task: AssistantTask, proposal: AssistantProposal) => void;
  /** Put the old sentence back in the draft after the server refused the new one (nothing was recorded). */
  revert: (proposal: AssistantProposal) => void;
};

/** What the author can do with a change, in the order the server needs it: edit, wait for the save, then record. */
export function useProposalActions(projectId: string, link: WritingLink | undefined, setTasks: Dispatch<SetStateAction<AssistantTask[] | null>>, usageChanged: () => void): ProposalActions {
  const [locals, setLocals] = useState<Record<string, Local>>({});
  const waiting = useRef<Record<string, Waiting>>({});
  const applied = useRef<Record<string, string>>({});
  const latest = useRef(link);
  useEffect(() => { latest.current = link; });
  const set = (id: string, next: Local | null) => setLocals((current) => {
    const copy = { ...current };
    if (next) copy[id] = next; else delete copy[id];
    return copy;
  });
  const change = (taskId: string, id: string, update: (proposal: AssistantProposal) => AssistantProposal) =>
    setTasks((current) => current && current.map((task) => (task.id === taskId ? { ...task, proposals: task.proposals?.map((item) => (item.id === id ? update(item) : item)) } : task)));
  const path = (taskId: string, id: string, action: string) => `/projects/${projectId}/assistant/tasks/${taskId}/proposals/${id}/${action}`;

  // The edit is in the editor; once the autosave has put it on the server the change can be recorded.
  const settle = async (id: string, wait: Waiting, revision: number) => {
    set(id, { busy: wait.action });
    try {
      const next = await json<AssistantProposal>(path(wait.taskId, id, wait.action), "POST", wait.action === "adopt" ? { draft_revision: revision, ...(wait.after !== undefined ? { after: wait.after } : {}) } : {});
      change(wait.taskId, id, () => next);
      set(id, null);
    } catch (cause) {
      const code = (cause as ApiFailure).code;
      // The server refused the reworded sentence after it had been put in the draft: say why, and offer to take it back.
      set(id, { error: proposalError(code, cause), ...(wait.action === "adopt" && applied.current[id] ? { revert: applied.current[id] } : {}) });
    }
  };
  useEffect(() => {
    const draft = link?.draft;
    if (!draft) return;
    for (const [id, wait] of Object.entries(waiting.current)) {
      if (draft.dirty || draft.revision <= wait.base) continue;
      delete waiting.current[id];
      void settle(id, wait, draft.revision);
    }
  });

  const replaceThenWait = async (task: AssistantTask, proposal: AssistantProposal, action: "adopt" | "undo", reworded?: string) => {
    const draft = latest.current?.draft;
    const sentence = action === "adopt" ? (reworded ?? proposal.after) : effectiveAfter(proposal);
    const [from, to] = action === "adopt" ? [proposal.before, sentence] : [sentence, proposal.before];
    if (!draft || waiting.current[proposal.id]) return;
    if (draft.count(from) !== 1) { set(proposal.id, { error: action === "adopt" ? CHANGED : "采用后这句又改过，请手动改回。" }); return; }
    if (action === "adopt") {
      const problem = afterProblem(proposal.before, sentence);
      if (problem) { set(proposal.id, { error: problem }); return; }
    }
    set(proposal.id, { busy: action });
    const ok = await draft.replace(from, to, action === "adopt" ? "proofread" : undefined);
    if (!ok) { set(proposal.id, { error: "没能在草稿里准确找到这句话（可能已经改过）。正文没有变动，请手动修改。" }); return; }
    if (action === "adopt") applied.current[proposal.id] = sentence;
    waiting.current[proposal.id] = { taskId: task.id, action, base: latest.current?.draft.revision ?? draft.revision, ...(action === "adopt" && reworded !== undefined && reworded !== proposal.after ? { after: reworded } : {}) };
    set(proposal.id, { waiting: action });
    // The author asked for this change; save it now so it can be recorded without waiting up to half a minute.
    (latest.current?.draft ?? draft).saveNow();
  };

  return {
    local: (id) => locals[id] ?? {},
    adopt: (task, proposal, reworded) => void replaceThenWait(task, proposal, "adopt", reworded),
    undo: (task, proposal) => void replaceThenWait(task, proposal, "undo"),
    revert: (proposal) => void (async () => {
      const draft = latest.current?.draft;
      const sentence = applied.current[proposal.id];
      if (!draft || !sentence) return;
      if (draft.count(sentence) !== 1) { set(proposal.id, { error: "这句话在草稿里又改过，请手动改回原句。" }); return; }
      set(proposal.id, { busy: "undo" });
      if (!(await draft.replace(sentence, proposal.before))) { set(proposal.id, { error: "没能在草稿里准确找到这句话。正文没有变动，请手动改回原句。" }); return; }
      delete applied.current[proposal.id];
      set(proposal.id, null);
      draft.saveNow();
    })(),
    dismiss: (task, proposal) => void (async () => {
      set(proposal.id, { busy: "dismiss" });
      try {
        const next = await json<AssistantProposal>(path(task.id, proposal.id, "dismiss"), "POST", {});
        change(task.id, proposal.id, () => next);
        set(proposal.id, null);
      } catch (cause) { set(proposal.id, { error: proposalError((cause as ApiFailure).code, cause) }); }
    })(),
    recheck: (task, proposal) => void (async () => {
      set(proposal.id, { busy: "recheck" });
      try {
        // A recheck is a whole check of one sentence; the client's own 15 second limit is too short for it.
        const result = await json<ProposalRecheck>(path(task.id, proposal.id, "recheck"), "POST", {}, AbortSignal.timeout(150_000));
        change(task.id, proposal.id, (item) => ({ ...item, recheck: result }));
        set(proposal.id, null);
      } catch (cause) {
        const code = (cause as ApiFailure).code;
        const timedOut = ["TimeoutError", "AbortError"].includes((cause as Error)?.name);
        set(proposal.id, { error: proposalError(timedOut ? "request_timeout" : code, cause) });
        // The server keeps what it finished: bring the task back as it is now, a running recheck is then followed.
        void request<AssistantTask>(`/projects/${projectId}/assistant/tasks/${task.id}`).then((fresh) => setTasks((current) => current && current.map((item) => (item.id === fresh.id ? fresh : item))), () => undefined);
      } finally { usageChanged(); }
    })(),
  };
}

const KIND_TITLE = { edit_this: "改法 · 改本章这句", intentional: "改法 · 这是有意的" } as const;
const KIND_NOTE = { edit_this: "只动这一句", add_setup: "会新增设定", intentional: "不改正文" } as const;

function RecheckResult({ recheck }: { recheck: Extract<ProposalRecheck, { status: "clean" | "issues" }> }) {
  if (recheck.status === "clean") return <p className="a-recheck-clean" role="status">复查没有发现问题</p>;
  return (
    <div className="a-recheck-issues" role="status">
      <p className="a-label">复查发现 {recheck.issues.length} 处问题</p>
      {recheck.issues.map((found: RecheckIssue, index) => (
        <div key={index} className="a-recheck-issue">
          <FindingTag issue={{ nature: found.nature, severity: found.severity }} long />
          <p>{found.explanation}</p>
          {found.evidence.length > 0 && (
            <ul className="a-evidence" aria-label="依据">
              {found.evidence.map((item) => (
                <li key={item.ref}>
                  <span className="a-evidence-where">{item.chapter != null ? `第 ${item.chapter} 章` : "前文"}{item.chapter_title ? ` · ${item.chapter_title.replace(/^第\s*\d+\s*章[\s·:：-]*/, "")}` : ""}</span>
                  <span className="a-evidence-text">{item.text}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      ))}
    </div>
  );
}

/** The change as words: struck where the old words go, green where the new ones come (the whole sentences when most of it changed). */
function Diff({ before, after, setup = false }: { before: string; after: string; setup?: boolean }) {
  if (setup) {
    return (
      <p className="a-diff">
        {before && <span className="a-ctx">{before}</span>}
        <ins><span className="sr-only">加上：</span>{after}</ins>
      </p>
    );
  }
  const { parts, whole } = diffView(before, after);
  return (
    <p className={`a-diff${whole ? " whole" : ""}`}>
      {parts.map((part, index) => part.kind === "same" ? <span key={index}>{part.text}</span>
        : part.kind === "del" ? <del key={index}><span className="sr-only">删去：</span>{part.text}</del>
          : <ins key={index}><span className="sr-only">改为：</span>{part.text}</ins>)}
    </p>
  );
}

function Proposal({ task, proposal, link, visitor, actions, openChapter }: {
  task: AssistantTask;
  proposal: AssistantProposal;
  link: WritingLink | undefined;
  visitor: boolean;
  actions: ProposalActions;
  openChapter: (number: number) => void;
}) {
  const local = actions.local(proposal.id);
  const busy = Boolean(local.busy || local.waiting);
  const dismissed = proposal.status === "dismissed";
  const adopted = proposal.status === "adopted";
  const draft = link?.draft;
  const title = proposal.kind === "add_setup" ? `改法 · 补第 ${proposal.chapter_number} 章` : KIND_TITLE[proposal.kind];
  const insertion = useRef<HTMLModElement>(null);
  const [copyFailed, setCopyFailed] = useState(false);
  const [editing, setEditing] = useState(false);
  // What the author typed in the box; null while they have not touched it. It is kept when something is refused.
  const [typed, setTyped] = useState<string | null>(null);
  const [wholeOpen, setWholeOpen] = useState(false);
  const recheck = proposal.recheck;
  const rechecking = local.busy === "recheck" || recheck?.status === "running";
  const sentence = adopted ? effectiveAfter(proposal) : typed ?? proposal.after;
  const reworded = sentence !== proposal.after;
  const afterChars = writtenChars(effectiveAfter(proposal));
  const problem = proposal.kind === "edit_this" && !adopted && typed !== null ? afterProblem(proposal.before, typed) : "";

  const reasonToAdopt = !draft ? "回到写作页才能采用这条改法。" : draft.blocked || (draft.count(proposal.before) !== 1 ? CHANGED : problem);
  const reasonToUndo = !draft ? "回到写作页才能撤销。" : draft.blocked || (draft.count(effectiveAfter(proposal)) !== 1 ? "采用后这句又改过，请手动改回。" : "");
  const waiting = local.waiting
    ? <p className="a-why" role="status">{local.waiting === "adopt" ? "已放进草稿，保存后记为已采用……" : "已改回，保存后记为已撤销……"}{draft && ["failed", "conflict"].includes(draft.autosave) ? "自动保存没成功，保存成功后才会记录。" : ""}</p>
    : null;

  const goToChapter = async () => {
    const chapter = proposal.chapter_number;
    if (chapter == null) return;
    // On the chapter's page the author is told where to paste: after the sentence this one goes behind (which is found and rung),
    // or, when the assistant named no such sentence, at a suitable place in the chapter.
    if (!copyFailed) {
      try { await navigator.clipboard.writeText(sentence); }
      catch {
        // No clipboard: leave the sentence selected so it can be copied by hand, and stay.
        const node = insertion.current;
        if (node) { const range = document.createRange(); range.selectNodeContents(node); const selection = window.getSelection(); selection?.removeAllRanges(); selection?.addRange(range); }
        setCopyFailed(true);
        return;
      }
    }
    const lead = copyFailed ? "" : "已复制，";
    requestLocate(chapter, proposal.before, proposal.before
      ? { found: `${lead}粘到这一句后面`, missing: `${lead}没找到那一句，请粘到第 ${chapter} 章合适的位置` }
      : { found: `${lead}请粘到第 ${chapter} 章合适的位置` });
    (link ? link.openChapter : openChapter)(chapter);
  };

  const canReword = !dismissed && !adopted && !busy && (proposal.kind === "edit_this" || proposal.kind === "add_setup");
  return (
    <section className={`a-opt${dismissed ? " dismissed" : ""}`} aria-label={title} data-proposal={proposal.proposal} data-kind={proposal.kind} data-status={proposal.status}>
      <div className="a-opt-h">
        <strong>{title}</strong>
        <span className="a-opt-note">{KIND_NOTE[proposal.kind]}</span>
        {(reworded || proposal.edited_by_author) && !dismissed && sentence !== proposal.before && <span className="a-edited">已手改</span>}
        {dismissed && <span className="a-state quiet">不用</span>}
      </div>
      {proposal.rationale && <p className="a-why">{proposal.rationale}</p>}

      {proposal.kind === "edit_this" && <Diff before={proposal.before} after={sentence} />}
      {proposal.kind === "add_setup" && (
        <>
          <p className="a-setup-at">{proposal.before ? <><span className="sr-only">放在这一句后面：</span>{proposal.before}</> : `放在第 ${proposal.chapter_number} 章合适的位置`}</p>
          <p className="a-diff"><ins ref={insertion}><span className="sr-only">加上：</span>{sentence}</ins></p>
          <p className="a-why">前面已完成的章节不能一键改，请手动粘贴。</p>
        </>
      )}
      {editing && canReword && (
        <textarea className="a-edit" aria-label="改后的句子" value={sentence} rows={3} maxLength={proposal.kind === "add_setup" ? 120 : undefined}
          aria-invalid={Boolean(problem) || undefined} onChange={(event) => setTyped(event.target.value)} />
      )}
      {problem && editing && <p className="a-why a-warn" role="alert">{problem}</p>}
      {proposal.kind === "edit_this" && (
        <>
          <button type="button" className="a-whole" aria-expanded={wholeOpen} onClick={() => setWholeOpen((value) => !value)}>整句对照 {wholeOpen ? "⌃" : "›"}</button>
          {wholeOpen && (
            <div className="a-whole-body">
              <span className="b"><span className="sr-only">原句：</span>{proposal.before}</span>
              <span className="f"><span className="sr-only">新句：</span>{sentence}</span>
            </div>
          )}
        </>
      )}

      {proposal.kind === "edit_this" && !dismissed && (
        <div className="a-opt-a">
          {adopted ? (
            <button type="button" className="a-btn" disabled={busy || Boolean(reasonToUndo)} onClick={() => actions.undo(task, proposal)}>已采用 · 撤销</button>
          ) : (
            <>
              <button type="button" className="a-btn" disabled={busy || Boolean(reasonToAdopt)} onClick={() => actions.adopt(task, proposal, reworded ? sentence : undefined)}>采用</button>
              <button type="button" className="a-link" disabled={busy} onClick={() => setEditing((value) => !value)}>{editing ? "改好了" : "改一改"}</button>
              <button type="button" className="a-link" disabled={busy} onClick={() => actions.dismiss(task, proposal)}>不用</button>
            </>
          )}
          {adopted && !visitor && effectiveAfter(proposal).length <= RECHECK_LIMIT && recheck?.status !== "failed" && (
            <button type="button" className="a-link" disabled={busy || rechecking} onClick={() => actions.recheck(task, proposal)}>复查这一句 · 约 {formatCount(afterChars)} 字</button>
          )}
        </div>
      )}
      {proposal.kind === "edit_this" && !dismissed && !local.waiting && !local.error && !(editing && problem) && (adopted ? reasonToUndo : reasonToAdopt) && <p className="a-why" role="status">{adopted ? reasonToUndo : reasonToAdopt}</p>}
      {waiting}

      {proposal.kind === "add_setup" && !dismissed && (
        <div className="a-opt-a">
          <button type="button" className="a-btn-quiet" onClick={() => void goToChapter()}>{copyFailed ? `去第 ${proposal.chapter_number} 章` : `复制这句，去第 ${proposal.chapter_number} 章`}</button>
          <button type="button" className="a-link" disabled={busy} onClick={() => setEditing((value) => !value)}>{editing ? "改好了" : "改一改"}</button>
          <button type="button" className="a-link" disabled={busy} onClick={() => actions.dismiss(task, proposal)}>不用</button>
          {copyFailed && <span className="a-why" role="status">请手动复制：这句已经选中。</span>}
        </div>
      )}

      {proposal.kind === "intentional" && (() => {
        const info = link?.issue(task.context.issue_id ?? "") ?? null;
        const done = info?.keep.done ?? false;
        const reason = !link ? "回到写作页才能标记。" : !info ? "检查结果已经更新，这一条找不到了。" : info.keep.reason;
        return done ? <p className="a-why" role="status">已标为有意为之。</p> : (
          <div className="a-opt-a">
            <button type="button" className="a-btn-quiet" disabled={Boolean(reason) || busy}
              onClick={() => { if (info) void info.keep.run(); }}>标为有意为之</button>
            {reason && <span className="a-why">{reason}</span>}
          </div>
        );
      })()}

      {local.error && (
        <p className="a-why a-warn" role="alert">
          {local.error}
          {local.revert && <> <button type="button" className="a-link" disabled={busy} onClick={() => actions.revert(proposal)}>把原句改回草稿</button></>}
        </p>
      )}

      {adopted && proposal.kind === "edit_this" && (
        <div className="a-recheck">
          {rechecking && <p className="a-why" role="status"><span className="a-spin" aria-hidden="true" />正在复查这一句……</p>}
          {!rechecking && recheck && (recheck.status === "clean" || recheck.status === "issues") && <RecheckResult recheck={recheck} />}
          {!rechecking && recheck?.status === "failed" && (
            <p className="a-why a-warn" role="status">{proposalError(recheck.error_code)} <button type="button" className="a-link" disabled={busy} onClick={() => actions.recheck(task, proposal)}>重试</button></p>
          )}
        </div>
      )}
    </section>
  );
}

export function FixView({ task, projectId, visitor, stopping, stop, retry, openChapter, locate, link, actions, refine, replace, rise = false }: {
  task: AssistantTask;
  projectId: string;
  visitor: boolean;
  stopping: boolean;
  stop: () => void;
  retry: () => void;
  openChapter: (number: number) => void;
  locate: (source: AssistantSource) => void;
  link: WritingLink | undefined;
  actions: ProposalActions;
  /** 按要求重新给改法 (asks the thread to prepare the next question); null when it cannot be done. */
  refine: ((issueId: string, number: number) => void) | null;
  replace: (next: AssistantTask) => void;
  /** The question was asked in this view just now: its bubble rises into place. */
  rise?: boolean;
}) {
  const running = active(task);
  const fade = useJustFinished(task);
  const issueId = task.context.issue_id ?? "";
  const info = link?.issue(issueId) ?? null;
  // The finding this task is about is the first passage it registered; `sources` holds every passage it turned up, cited or not.
  const fallback = Object.values(task.sources).find((source) => source.kind === "issue");
  const explaining = info ? findingTone(info.issue) === "state" : false;
  const failure = task.status === "failed" ? failureText(task, visitor) : null;
  return (
    <article className="a-task" aria-live="off" data-task={task.id} data-status={task.status} data-kind="fix_issue">
      {task.question && <div className={`a-ask${rise ? " rise" : ""}`}>{task.question}</div>}
      <Steps task={task} locate={locate} lead={explaining ? "解释这一处" : "帮我改这一处"}
        end={running ? <button type="button" className="a-link a-stop" disabled={stopping} onClick={stop}>停止</button> : <RerouteMenu task={task} />} />
      <ChosenLine task={task} />
      {info ? (
        <div className="a-issue">
          <Num className="a-issue-num">{info.number}</Num>
          <span className="a-issue-text"><FindingTag issue={info.issue} long /><strong>{findingHeadline(info.issue)}</strong></span>
        </div>
      ) : fallback ? <p className="a-issue-fallback">{fallback.text}</p> : null}
      <StoppedNote task={task} visitor={visitor} />
      {failure && (
        <p className="a-note" role="status">{failure.text}{failure.retry && <> <button type="button" className="a-link" onClick={retry}>重试</button></>}</p>
      )}
      <LimitLine task={task} />
      <AnswerBlock task={task} fade={fade} locate={locate} />
      {(task.proposals ?? []).map((proposal) => (
        <Proposal key={proposal.id} task={task} proposal={proposal} link={link} visitor={visitor} actions={actions} openChapter={openChapter} />
      ))}
      <SourceList task={task} locate={locate} />
      <CoverLine task={task} />
      {task.status === "completed" && (
        <div className="a-foot">
          {refine && info && <button type="button" className="a-link" onClick={() => refine(issueId, info.number)}>按要求重新给改法</button>}
          <Feedback task={task} projectId={projectId} replace={replace} />
          {!visitor && task.usage.chars_charged > 0 && <span className="a-cost-line">计 {formatCount(task.usage.chars_charged)} 字</span>}
        </div>
      )}
    </article>
  );
}
