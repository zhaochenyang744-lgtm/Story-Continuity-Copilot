"use client";

// Everything a work's pages share: loading, the draft and its saves (explicit, automatic, recovered
// from this device, or carrying an author decision), checks and their polling, decisions, the fact
// review that follows, imported-work fact initialisation, and author plans. Pages only render it.
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { json, jsonWithIdempotency, request, type ApiFailure } from "../../api";
import { readDraftRecovery, removeDraftRecovery, writeDraftRecovery, type DraftRecoverySnapshot } from "../../draft-recovery";
import {
  pendingDecisionSchemaVersion,
  readPendingDecision,
  removePendingDecision,
  stopPendingDecision,
  writePendingDecision,
  type PendingControlledDecision,
} from "../../pending-decision";
import type {
  AuthorContext,
  ChangeSet,
  Chapter,
  Draft,
  Issue,
  Memory,
  MemoryCoverage,
  MemoryDelta,
  MemoryInitialization,
  Onboarding,
  Project,
  Run,
  TutorialEvent,
  User,
  WritingAnalysisRun,
} from "../../model";
import { replaceVisibleDraftText } from "../editor";
import { NO_FACT_CHANGES, activeAnalysis, activeRun, categoryLabel, retryableAnalysis, retryableRun, timeLabel } from "../labels";

export const BULK_REVIEW_THRESHOLD = 12;
const BULK_DECISION_BATCH = 200;
const AUTOSAVE_IDLE_MS = 5_000;
const AUTOSAVE_MIN_INTERVAL_MS = 30_000;

export type AutosaveState = "idle" | "saving" | "saved" | "failed" | "conflict";
export type TutorialStep = 1 | 2 | 3 | 4 | 5;
export type DraftRecoveryPrompt = { snapshot: DraftRecoverySnapshot; serverDraft: Draft };
export type Character = { id: string; name: string; role_type: string; identity: string; goal: string; current_state: string; knowledge_boundary: string };
export type WorldEntry = { id: string; entry_type: string; name: string; summary: string };
export type SourceRecord = {
  recordId: string;
  subject: string;
  chapterId: string;
  chapterNumber: number;
  chapterTitle: string;
  spanId: string;
  excerpt: string;
  sourcePath?: string;
  sourceRevision?: number;
  memoryType?: string;
  reviewStatus?: string;
  memoryValidFrom?: number | null;
  memoryValidTo?: number | null;
  relation?: string;
  sufficiency?: string;
};
export type EvidenceItem = NonNullable<Issue["evidence"]>[number];

export const issueAllows = (issue: Issue, action: NonNullable<Issue["available_actions"]>[number]) =>
  issue.available_actions === undefined || issue.available_actions.includes(action);
export const issueHasSufficientEvidence = (issue: Issue) =>
  issue.evidence_status === "sufficient" && Boolean(issue.evidence?.some((item) => item.sufficiency === "sufficient"));
// Match v2_database.create_changeset's required decisions, including legacy_v3 issues whose
// available_actions field is absent. Read-only hints do not block review.
export const issueRequiresDecision = (issue: Issue) =>
  issue.evidence_status === "sufficient" && (issue.available_actions === undefined || issue.available_actions.length > 0);
export const issueNeedsDecision = (issue: Issue, resolved: string[]) =>
  issueRequiresDecision(issue) && !issue.decision && !issue.reused_decision && !resolved.includes(issue.id);

const checkPath = (projectId: string, runId: string) => `/projects/${projectId}/checks/${runId}?include=issues,evidence,metrics`;
const draftChanged = (a: Draft | null, b: Draft | null) => Boolean(a && b && (a.title !== b.title || a.body !== b.body || a.body_format !== b.body_format));

export function useProject({
  projectId,
  user,
  narrow,
  fail,
  notify,
  applyOnboarding,
  recordTutorialEvent,
}: {
  projectId: string | null;
  user: User | null;
  narrow: boolean;
  fail: (cause: unknown) => void;
  notify: (message: string) => void;
  applyOnboarding: (next: Onboarding) => void;
  recordTutorialEvent: (projectId: string, event: TutorialEvent, context?: { run_id: string; issue_id: string }) => Promise<unknown>;
}) {
  const [project, setProject] = useState<Project | null>(null);
  const [missingProjectId, setMissingProjectId] = useState("");
  const [chapters, setChapters] = useState<Chapter[]>([]);
  const [memories, setMemories] = useState<Memory[]>([]);
  const [characters, setCharacters] = useState<Character[]>([]);
  const [world, setWorld] = useState<WorldEntry[]>([]);
  const [authorContext, setAuthorContext] = useState<AuthorContext | null>(null);
  const [authorBusy, setAuthorBusy] = useState("");
  const [draft, setDraft] = useState<Draft | null>(null);
  const [saved, setSaved] = useState<Draft | null>(null);
  const [run, setRun] = useState<Run | null>(null);
  const [pairedRun, setPairedRun] = useState<Run | null>(null);
  const [initialization, setInitialization] = useState<MemoryInitialization | null>(null);
  const [memoryDelta, setMemoryDelta] = useState<MemoryDelta | null>(null);
  const [coverage, setCoverage] = useState<MemoryCoverage | null>(null);
  const [contextBrief, setContextBrief] = useState<WritingAnalysisRun | null>(null);
  const [planAlignment, setPlanAlignment] = useState<WritingAnalysisRun | null>(null);
  const [analysisBusy, setAnalysisBusy] = useState<"context_brief" | "plan_alignment" | "">("");
  const [busy, setBusy] = useState("");
  const [selected, setSelected] = useState<Issue | null>(null);
  const [controlled, setControlled] = useState<Issue | null>(null);
  const [pendingControlledDecision, setPendingControlledDecision] = useState<PendingControlledDecision | null>(null);
  const [locallyResolvedIssueIds, setLocallyResolvedIssueIds] = useState<string[]>([]);
  const [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [saveFailed, setSaveFailed] = useState(false);
  const [autosaveRecord, setAutosaveRecord] = useState<{ key: string; state: AutosaveState }>({ key: "", state: "idle" });
  const [draftRecoveryPrompt, setDraftRecoveryPrompt] = useState<DraftRecoveryPrompt | null>(null);
  const [draftRecoveryConflict, setDraftRecoveryConflict] = useState<DraftRecoveryPrompt | null>(null);
  const [draftRecoveryUnavailable, setDraftRecoveryUnavailable] = useState("");
  const [pendingDecisionStorageUnavailable, setPendingDecisionStorageUnavailable] = useState("");
  const [pendingDecisionConflict, setPendingDecisionConflict] = useState("");
  const [pendingDecisionPersisted, setPendingDecisionPersisted] = useState(false);
  const [sourceRecord, setSourceRecord] = useState<SourceRecord | null>(null);
  const [tutorialRestored, setTutorialRestored] = useState(false);
  const epoch = useRef(0);
  const activeRequest = useRef<AbortController | null>(null);
  const tutorialSeen = useRef<string | null>(null);
  // "重新看一遍导览" asks for the 已回到第 N 步 note; loading the work afterwards must not take it back.
  const tutorialRestarted = useRef(false);
  const selectTrigger = useRef<HTMLElement | null>(null);
  const sourceTrigger = useRef<HTMLElement | null>(null);

  // Recording any tour step ends the "已回到第 N 步" note.
  const tutorialEvent = (id: string, event: TutorialEvent, context?: { run_id: string; issue_id: string }) => {
    tutorialRestarted.current = false;
    setTutorialRestored(false);
    return recordTutorialEvent(id, event, context);
  };
  const markTutorialRestarted = () => { tutorialRestarted.current = true; setTutorialRestored(true); };
  const readOnly = narrow || project?.status === "archived";
  const dirty = draftChanged(draft, saved);

  // A new or retried run replaces the issues; drop a selection or edit that no longer exists in it.
  const [issueRunId, setIssueRunId] = useState(run?.run_id);
  if (issueRunId !== run?.run_id) {
    setIssueRunId(run?.run_id);
    if (selected && !run?.issues?.some((issue) => issue.id === selected.id)) setSelected(null);
    if (controlled && !run?.issues?.some((issue) => issue.id === controlled.id)) {
      setControlled(null);
      notify("检查结果更新了，请在新结果里重新选择要改的那一条；没保存的正文还在编辑器里。");
    }
  }

  const clear = useCallback(() => {
    activeRequest.current?.abort();
    activeRequest.current = null;
    epoch.current += 1;
    setProject(null); setChapters([]); setMemories([]); setDraft(null); setSaved(null); setRun(null); setPairedRun(null);
    setInitialization(null); setMemoryDelta(null); setCoverage(null); setAuthorContext(null); setAuthorBusy("");
    setCharacters([]); setWorld([]); setSelected(null); setSourceRecord(null); setControlled(null); setPendingControlledDecision(null);
    setLocallyResolvedIssueIds([]); setChangeSet(null); setSaveFailed(false); setDraftRecoveryPrompt(null); setDraftRecoveryConflict(null);
    setDraftRecoveryUnavailable(""); setPendingDecisionStorageUnavailable(""); setPendingDecisionConflict(""); setPendingDecisionPersisted(false);
    setTutorialRestored(false); setContextBrief(null); setPlanAlignment(null); setMissingProjectId("");
  }, []);

  const loadProject = useCallback(async (id: string) => {
    clear();
    const n = ++epoch.current, controller = new AbortController();
    activeRequest.current = controller;
    const signal = controller.signal;
    setBusy("正在读取作品");
    try {
      const p = await request<Project>(`/projects/${id}`, { signal });
      // Restore the run record before fanning out: on a cold refresh it must not queue behind the larger payloads.
      const latest = p.latest_run ? await request<Run>(checkPath(id, p.latest_run.run_id), { signal }) : null;
      const imported = p.data_origin === "user_import";
      const [c, m, d, chars, w, author, initialized, memoryCoverage, delta, projectOnboarding, briefLatest, alignmentLatest] = await Promise.all([
        request<{ chapters: Chapter[] }>(`/projects/${id}/chapters?include=excerpt`, { signal }),
        request<{ records: Memory[] }>(`/projects/${id}/memory`, { signal }),
        request<Draft>(`/projects/${id}/drafts/${p.current_draft.id}`, { signal }),
        request<{ characters: Character[] }>(`/projects/${id}/characters`, { signal }),
        request<{ entries: WorldEntry[] }>(`/projects/${id}/world`, { signal }),
        request<AuthorContext>(`/projects/${id}/author-intent?include_archived=true`, { signal }),
        imported ? request<MemoryInitialization>(`/projects/${id}/memory/initialization`, { signal }) : Promise.resolve(null),
        imported ? request<MemoryCoverage>(`/projects/${id}/memory/coverage`, { signal }) : Promise.resolve(null),
        imported ? request<MemoryDelta>(`/projects/${id}/memory/delta`, { signal }) : Promise.resolve(null),
        p.is_tutorial ? request<Onboarding>("/onboarding", { signal }) : Promise.resolve(null),
        request<{ run: WritingAnalysisRun | null }>(`/projects/${id}/analyses?analysis_type=context_brief`, { signal }),
        request<{ run: WritingAnalysisRun | null }>(`/projects/${id}/analyses?analysis_type=plan_alignment`, { signal }),
      ]);
      if (n !== epoch.current) return;
      setProject(p);
      if (projectOnboarding) applyOnboarding(projectOnboarding);
      setChapters(c.chapters);
      setMemories(m.records);
      setDraft(d);
      setSaved(d);
      const seenThisSession = tutorialSeen.current === p.id;
      if (p.is_tutorial) tutorialSeen.current = p.id;
      const restarted = tutorialRestarted.current && p.is_tutorial;
      tutorialRestarted.current = false;
      setTutorialRestored(restarted || Boolean(!seenThisSession && projectOnboarding?.progress && projectOnboarding.progress.current_step > 1));
      if (user) {
        try {
          const snapshot = readDraftRecovery(window.localStorage, { userId: user.id, projectId: p.id, draftId: d.id });
          setDraftRecoveryUnavailable("");
          setDraftRecoveryPrompt(snapshot && (snapshot.title !== d.title || snapshot.body !== d.body || (snapshot.body_format ?? "plain_text") !== d.body_format) ? { snapshot, serverDraft: d } : null);
        } catch {
          setDraftRecoveryPrompt(null);
          setDraftRecoveryUnavailable("这个浏览器不允许在本机保存恢复副本，请及时保存到服务器。");
        }
      }
      setCharacters(chars.characters);
      setWorld(w.entries);
      setAuthorContext(author);
      setInitialization(initialized);
      setMemoryDelta(delta);
      setCoverage(memoryCoverage);
      setContextBrief(briefLatest.run);
      setPlanAlignment(alignmentLatest.run);
      let primaryRun = latest;
      let siblingRun: Run | null = null;
      if (latest?.incremental_batch_id && delta?.id === latest.incremental_batch_id && delta.continuity_run_id && delta.memory_delta_run_id) {
        const readRun = (runId: string) => (latest.run_id === runId ? Promise.resolve(latest) : request<Run>(checkPath(id, runId), { signal }));
        [primaryRun, siblingRun] = await Promise.all([readRun(delta.continuity_run_id), readRun(delta.memory_delta_run_id)]);
      }
      if (user) {
        const identity = { userId: user.id, projectId: p.id, draftId: d.id };
        try {
          const pending = readPendingDecision(window.localStorage, identity);
          setPendingDecisionStorageUnavailable("");
          setPendingDecisionPersisted(Boolean(pending));
          if (pending) {
            const checkedRun = primaryRun?.run_id === pending.runId ? primaryRun : await request<Run>(checkPath(id, pending.runId), { signal });
            if (n !== epoch.current) return;
            const checkedIssue = checkedRun?.issues?.find((item) => item.id === pending.issueId);
            const alreadyMatches = checkedRun?.run_id === pending.runId && checkedRun.source_revision === pending.sourceRevision
              && checkedIssue?.decision?.decision === pending.decision && checkedIssue.decision.resulting_revision === pending.resultingRevision;
            if (alreadyMatches) {
              try {
                removePendingDecision(window.localStorage, identity);
                setPendingDecisionPersisted(false);
              } catch {
                setPendingDecisionStorageUnavailable("服务器已确认原来的决定，但这个浏览器清理不了本机的补记记录；下次进入仍会安全核对。");
              }
              setLocallyResolvedIssueIds((ids) => [...new Set([...ids, pending.issueId])]);
              setPendingControlledDecision(null);
              setPendingDecisionConflict("");
              notify("已和服务器核对：之前的决定已经记下，正文没有重复保存。");
            } else if (checkedRun?.run_id === pending.runId && checkedRun.source_revision === pending.sourceRevision && checkedIssue && !checkedIssue.decision && d.revision === pending.resultingRevision) {
              setPendingControlledDecision(pending);
              setControlled(checkedIssue);
              setPendingDecisionConflict("");
              notify("恢复了一条还没记下的决定。正文已经保存；重试只会记下这条决定，不会再次保存正文。");
            } else {
              setPendingControlledDecision(pending);
              setControlled(checkedIssue ?? null);
              setPendingDecisionConflict("本机待补记的决定和服务器上的草稿或决定对不上；已停止自动重试，正文没有再次保存。");
              notify("有一条待补记的决定没法自动确认。记录仍按当前账号、作品和草稿保留，请先核对服务器上的最新状态。");
            }
          }
        } catch {
          setPendingControlledDecision(null);
          setPendingDecisionPersisted(false);
          setPendingDecisionStorageUnavailable("这个浏览器读不到待补记的决定。如果之前保存正文后决定没确认，请不要认为它已经记下。");
        }
      }
      // The latest check may belong to a draft that has since been completed into a chapter; the
      // current draft starts without findings. (Incremental source reviews are not tied to a draft.)
      const forOtherDraft = (item: Run | null) => Boolean(item && !item.incremental_batch_id && item.draft_id && item.draft_id !== d.id);
      setRun(forOtherDraft(primaryRun) ? null : primaryRun);
      setPairedRun(forOtherDraft(primaryRun) ? null : siblingRun);
    } catch (cause) {
      if ((cause as ApiFailure).code === "resource_not_found" && n === epoch.current) setMissingProjectId(id);
      else if ((cause as Error).name !== "AbortError") fail(cause);
    } finally {
      if (n === epoch.current) setBusy("");
    }
  }, [applyOnboarding, clear, fail, notify, user]);

  useEffect(() => {
    if (!user) return;
    if (projectId) void Promise.resolve().then(() => loadProject(projectId));
    else void Promise.resolve().then(clear);
  }, [projectId, user, loadProject, clear]);

  const refreshReferences = useCallback(async () => {
    if (!project) return;
    const id = project.id;
    const [updated, chapterData, memoryData] = await Promise.all([
      request<Project>(`/projects/${id}`),
      request<{ chapters: Chapter[] }>(`/projects/${id}/chapters?include=excerpt`),
      request<{ records: Memory[] }>(`/projects/${id}/memory`),
    ]);
    if (window.location.pathname.split("/")[2] !== id) return;
    setProject(updated); setChapters(chapterData.chapters); setMemories(memoryData.records);
  }, [project]);

  /** Re-read the work's summary (counts, latest check, source version) and, for an imported work,
      its fact coverage — without touching the draft or anything being edited. */
  const refreshSummary = useCallback(async () => {
    if (!projectId) return;
    const requestEpoch = epoch.current;
    try {
      const next = await request<Project>(`/projects/${projectId}`);
      if (requestEpoch !== epoch.current) return;
      setProject((current) => (current?.id === next.id ? { ...current, ...next } : current));
      if (next.data_origin === "user_import") {
        const nextCoverage = await request<MemoryCoverage>(`/projects/${projectId}/memory/coverage`);
        if (requestEpoch === epoch.current) setCoverage(nextCoverage);
      }
    } catch { /* the page keeps what it has; the next action reports any error */ }
  }, [projectId]);

  /** After chapters are appended (or the draft is completed) the work continues with a new draft:
      switch to it and drop everything that belonged to the old one. */
  const adoptNextDraft = (next: Draft | null | undefined) => {
    if (next) { setDraft(next); setSaved(next); }
    setRun(null); setPairedRun(null); setSelected(null); setControlled(null); setChangeSet(null);
    setLocallyResolvedIssueIds([]); setContextBrief(null); setPlanAlignment(null);
  };

  // Poll an active check (and its paired fact run). One request at a time; a hidden tab polls when shown again.
  useEffect(() => {
    if (!run || !projectId || (!activeRun(run) && !activeRun(pairedRun))) return;
    let inFlight = false, stopped = false;
    const poll = () => {
      if (inFlight || stopped) return;
      inFlight = true;
      Promise.all((pairedRun ? [run, pairedRun] : [run]).map((item) => request<Run>(checkPath(projectId, item.run_id))))
        .then((next) => {
          if (stopped) return;
          setRun(next[0]);
          setPairedRun(next[1] ?? null);
          if (next.every((item) => !activeRun(item))) {
            const undecided = next[0].metrics?.undecided_claim_count ?? 0;
            const quotaStopped = (next[0].metrics?.undecided_claims ?? []).some((row) => row.error_code === "provider_attempt_quota_exceeded");
            notify(next[0].status !== "completed" ? "" : quotaStopped
              ? `检查到一半额度用完了，有 ${undecided} 句还没检查，结果里不包括它们。已检查的部分可以先看。`
              : undecided > 0 ? `检查完成，有 ${undecided} 句没能判断，结果里不包括它们。` : "检查完成。");
            void refreshSummary();
            if (next[0].incremental_batch_id)
              request<MemoryDelta>(`/projects/${projectId}/memory/delta`).then((delta) => { setMemoryDelta(delta); setCoverage(delta.coverage ?? null); }).catch(fail);
          }
        })
        .catch((cause) => { if (!stopped) fail(cause); })
        .finally(() => { inFlight = false; });
    };
    const timer = window.setInterval(poll, 1000);
    const onVisible = () => { if (document.visibilityState === "visible") poll(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { stopped = true; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [run, pairedRun, projectId, fail, notify, refreshSummary]);

  useEffect(() => {
    if (!projectId || (!activeAnalysis(contextBrief) && !activeAnalysis(planAlignment))) return;
    let inFlight = false, stopped = false;
    const poll = () => {
      if (inFlight || stopped) return;
      inFlight = true;
      const rows = [contextBrief, planAlignment].filter((item): item is WritingAnalysisRun => Boolean(item && activeAnalysis(item)));
      Promise.all(rows.map((item) => request<WritingAnalysisRun>(`/projects/${projectId}/analyses/${item.run_id}`)))
        .then((next) => { if (!stopped) next.forEach((item) => (item.analysis_type === "context_brief" ? setContextBrief(item) : setPlanAlignment(item))); })
        .catch((cause) => { if (!stopped) fail(cause); })
        .finally(() => { inFlight = false; });
    };
    const timer = window.setInterval(poll, 1000);
    const onVisible = () => { if (document.visibilityState === "visible") poll(); };
    document.addEventListener("visibilitychange", onVisible);
    return () => { stopped = true; window.clearInterval(timer); document.removeEventListener("visibilitychange", onVisible); };
  }, [contextBrief, planAlignment, projectId, fail]);

  const markSavedRevision = (revision: number) => {
    setContextBrief((current) => (current && current.draft_revision !== revision ? { ...current, is_stale: true, lineage_status: "bound_state_changed" } : current));
    setPlanAlignment((current) => (current && current.draft_revision !== revision ? { ...current, is_stale: true, lineage_status: "bound_state_changed" } : current));
    setRun((current) => (current && current.source_revision !== revision ? { ...current, current_revision: revision, is_stale: true, lineage_status: "stale" } : current));
    setPairedRun((current) => (current && current.source_revision !== revision ? { ...current, current_revision: revision, is_stale: true, lineage_status: "stale" } : current));
  };

  const readPendingRun = (pending: PendingControlledDecision) => request<Run>(checkPath(pending.projectId, pending.runId));
  const pendingMatches = (pending: PendingControlledDecision, checkedRun: Run) => {
    if (checkedRun.run_id !== pending.runId || checkedRun.source_revision !== pending.sourceRevision) return false;
    const issue = checkedRun.issues?.find((item) => item.id === pending.issueId);
    return issue?.decision?.decision === pending.decision && issue.decision.resulting_revision === pending.resultingRevision;
  };
  const finishPending = async (pending: PendingControlledDecision, checkedRun: Run, message: string) => {
    if (!pendingMatches(pending, checkedRun)) return false;
    try {
      removePendingDecision(window.localStorage, pending);
      setPendingDecisionStorageUnavailable("");
      setPendingDecisionPersisted(false);
    } catch {
      setPendingDecisionStorageUnavailable("决定已确认，但这个浏览器清理不了本机的补记记录；下次进入会再核对一次，不会重复保存正文。");
    }
    setLocallyResolvedIssueIds((ids) => [...new Set([...ids, pending.issueId])]);
    setPendingControlledDecision(null);
    setPendingDecisionConflict("");
    setControlled(null);
    setRun((current) => (current?.run_id === checkedRun.run_id ? checkedRun : current));
    if (project?.is_tutorial) {
      try { await tutorialEvent(project.id, "author_decision_recorded"); } catch { /* The decision stands on its own. */ }
    }
    notify(message);
    return true;
  };

  const stopConflictedPendingDecision = async () => {
    if (!pendingControlledDecision || !pendingDecisionConflict) return;
    const pending = pendingControlledDecision;
    try {
      stopPendingDecision(window.localStorage, pending, pendingDecisionConflict);
    } catch {
      setPendingDecisionStorageUnavailable("没能把这条旧决定存进本机的冲突记录，所以还没停止补记，页面上的记录也没丢。");
      notify("本机存储不可用：没有清理待补记的决定。现在离开的话，页面上这条没存下的记录会丢失。");
      return;
    }
    setPendingDecisionPersisted(false);
    setPendingControlledDecision(null);
    setPendingDecisionConflict("");
    setPendingDecisionStorageUnavailable("");
    setControlled(null);
    await loadProject(pending.projectId);
    notify("已停止补记这条失效的旧决定，它留在本机的冲突记录里；现在显示服务器上的最新正文。没有提交决定，也没有再次保存正文。");
  };

  const save = async (): Promise<boolean> => {
    if (!projectId || !draft || readOnly) return false;
    if (draftRecoveryConflict) {
      notify("恢复副本基于服务器上较旧的版本，不能直接覆盖。请先比较两份正文。");
      return false;
    }
    if (pendingControlledDecision) {
      const pending = pendingControlledDecision;
      if (pendingDecisionConflict) {
        notify("待补记的决定和服务器状态有冲突，已停止自动重试；不会再次保存正文。");
        return false;
      }
      if (pending.userId !== (user?.id ?? "") || pending.projectId !== projectId || pending.draftId !== draft.id || pending.resultingRevision !== draft.revision) {
        notify("待记录的决定和当前草稿对不上，请重新打开作品后再处理。");
        return false;
      }
      const requestEpoch = epoch.current;
      setSaveFailed(false);
      setBusy("正在重试记录决定");
      try {
        await jsonWithIdempotency(`/projects/${pending.projectId}/issues/${pending.issueId}/decision`, "POST", {
          run_id: pending.runId, source_revision: pending.sourceRevision, decision: pending.decision, resulting_revision: pending.resultingRevision,
        }, pending.idempotencyKey);
        if (requestEpoch !== epoch.current) return true;
        const checkedRun = await readPendingRun(pending);
        if (requestEpoch !== epoch.current) return true;
        if (await finishPending(pending, checkedRun, `正文第 ${pending.resultingRevision} 次保存保持不变；决定已经补记。`)) return true;
        setPendingDecisionConflict("服务器返回的决定和本机待补记的不一致；已停止重试，正文没有再次保存。");
        notify("服务器上的决定不一样，不能把本机的操作当成成功。请留在此页，核对最新的检查结果。");
        return false;
      } catch (cause) {
        if ((cause as ApiFailure).code === "already_decided") {
          try {
            const checkedRun = await readPendingRun(pending);
            if (requestEpoch !== epoch.current) return true;
            if (await finishPending(pending, checkedRun, `服务器上已有同样的决定；正文第 ${pending.resultingRevision} 次保存不变，补记完成。`)) return true;
            setPendingDecisionConflict("服务器上已有另一条决定；本机待补记的记录仍保留，正文没有重复保存。");
            notify("服务器上的决定和本机待补记的不同，已停止自动重试，不能当作成功。");
            return false;
          } catch { /* Keep the already_decided outcome when verification is unavailable. */ }
        }
        if (requestEpoch === epoch.current) notify("正文已经保存；决定还没记下。再点一次只会重试记录决定，不会重复保存正文。");
        return false;
      } finally {
        if (requestEpoch === epoch.current) setBusy("");
      }
    }
    const requestEpoch = epoch.current;
    const requestUserId = user?.id ?? "";
    const requestProjectId = projectId;
    const requestDraft = { ...draft };
    const requestControlled = controlled;
    const requestRun = run;
    if (requestControlled && (requestRun?.status !== "completed" || !requestRun.issues?.some((issue) => issue.id === requestControlled.id))) {
      notify("检查结果更新了，请在新结果里重新选择要改的那一条；没保存的正文还在编辑器里。");
      return false;
    }
    setSaveFailed(false);
    setBusy(requestControlled ? "保存修改" : "保存草稿");
    try {
      const body: Record<string, unknown> = { base_revision: requestDraft.revision, title: requestDraft.title, body: requestDraft.body, body_format: requestDraft.body_format };
      if (requestControlled && requestRun) body.edit_context = { source_run_id: requestRun.run_id, source_revision: requestRun.source_revision, issue_id: requestControlled.id };
      const result = await json<{ revision: number; saved_at: string }>(`/projects/${requestProjectId}/drafts/${requestDraft.id}`, "PATCH", body);
      if (requestEpoch !== epoch.current) return true;
      const next = { ...requestDraft, revision: result.revision, saved_at: result.saved_at };
      setDraft(next);
      setSaved(next);
      if (requestUserId) {
        try { removeDraftRecovery(window.localStorage, { userId: requestUserId, projectId: requestProjectId, draftId: requestDraft.id }); }
        catch { setDraftRecoveryUnavailable("正文已保存，但这个浏览器清理不了本机的恢复记录。"); }
      }
      markSavedRevision(result.revision);
      if (requestControlled && requestRun) {
        const pending: PendingControlledDecision = {
          schema_version: pendingDecisionSchemaVersion,
          userId: requestUserId,
          projectId: requestProjectId,
          draftId: requestDraft.id,
          runId: requestRun.run_id,
          issueId: requestControlled.id,
          sourceRevision: requestRun.source_revision,
          resultingRevision: result.revision,
          decision: "accept_and_edit",
          idempotencyKey: crypto.randomUUID(),
          createdAt: new Date().toISOString(),
        };
        setPendingControlledDecision(pending);
        setPendingDecisionConflict("");
        let stored = true;
        try {
          writePendingDecision(window.localStorage, pending);
          setPendingDecisionStorageUnavailable("");
          setPendingDecisionPersisted(true);
        } catch {
          stored = false;
          setPendingDecisionPersisted(false);
          setPendingDecisionStorageUnavailable("这个浏览器存不下待补记的记录。请留在此页重试；刷新、退出或切换作品会失去重试入口。");
        }
        try {
          await jsonWithIdempotency(`/projects/${requestProjectId}/issues/${requestControlled.id}/decision`, "POST", {
            run_id: requestRun.run_id, source_revision: requestRun.source_revision, decision: pending.decision, resulting_revision: result.revision,
          }, pending.idempotencyKey);
        } catch {
          if (requestEpoch === epoch.current)
            notify(!stored
              ? "正文已保存，但决定还没确认；这个浏览器存不下重试记录。请留在此页重试，不要刷新或离开。"
              : "正文已保存，但这一条的处理还没记下。再点一次只会重试记录决定，不会重复保存正文。");
          return true;
        }
        if (requestEpoch !== epoch.current) return true;
        const checkedRun = await readPendingRun(pending);
        if (requestEpoch !== epoch.current) return true;
        if (!(await finishPending(pending, checkedRun, `修改已保存（第 ${result.revision} 次保存），这一条的处理也记下了。`))) {
          setPendingDecisionConflict("服务器返回的决定和本机操作不一致；正文没有重复保存。");
          notify("正文已保存，但没法确认服务器上的决定和本机操作一致；已停止自动完成。");
        }
      } else notify(`已保存 ${timeLabel(result.saved_at)}`);
      return true;
    } catch (cause) {
      setSaveFailed(true);
      fail(cause);
      return false;
    } finally {
      setBusy("");
    }
  };

  // Autosave (v1.6.1): a few seconds after typing stops, at most every 30 s, without locking the
  // editor. Saves that carry a decision keep the explicit button; a newer revision elsewhere stops it.
  const autosaveInFlight = useRef(false);
  const lastAutosaveAt = useRef(0);
  const autosaveKey = `${projectId ?? ""}:${draft?.id ?? ""}`;
  const autosaveState: AutosaveState = autosaveRecord.key === autosaveKey ? autosaveRecord.state : "idle";
  const setAutosaveState = (state: AutosaveState) => setAutosaveRecord({ key: autosaveKey, state });
  const autosaveBlocked = !projectId || !draft || !saved || readOnly || Boolean(busy) || Boolean(controlled) || Boolean(pendingControlledDecision)
    || Boolean(draftRecoveryConflict) || Boolean(draftRecoveryPrompt) || autosaveState === "conflict";
  const autosave = async () => {
    if (autosaveBlocked || !dirty || autosaveInFlight.current || !draft || !saved || !projectId) return;
    const requestEpoch = epoch.current;
    const requestDraft = { ...draft };
    autosaveInFlight.current = true;
    setAutosaveState("saving");
    try {
      const result = await json<{ revision: number; saved_at: string }>(`/projects/${projectId}/drafts/${requestDraft.id}`, "PATCH", {
        base_revision: saved.revision, title: requestDraft.title, body: requestDraft.body, body_format: requestDraft.body_format,
      });
      lastAutosaveAt.current = Date.now();
      if (requestEpoch !== epoch.current) return;
      setSaved({ ...requestDraft, revision: result.revision, saved_at: result.saved_at });
      setDraft((current) => (current && current.id === requestDraft.id ? { ...current, revision: result.revision, saved_at: result.saved_at } : current));
      markSavedRevision(result.revision);
      setSaveFailed(false);
      setAutosaveState("saved");
    } catch (cause) {
      lastAutosaveAt.current = Date.now();
      if (requestEpoch !== epoch.current) return;
      if ((cause as ApiFailure).code === "revision_conflict") {
        setAutosaveState("conflict");
        notify("这一章在别处保存了更新的版本，自动保存已暂停，避免覆盖。你的文字还在本机；请刷新后再比较。");
      } else setAutosaveState("failed");
    } finally {
      autosaveInFlight.current = false;
    }
  };
  const autosaveRef = useRef(autosave);
  useEffect(() => { autosaveRef.current = autosave; });
  useEffect(() => {
    if (autosaveBlocked || !dirty) return;
    const wait = Math.max(AUTOSAVE_IDLE_MS, AUTOSAVE_MIN_INTERVAL_MS - (Date.now() - lastAutosaveAt.current));
    const timer = window.setTimeout(() => void autosaveRef.current(), wait);
    return () => window.clearTimeout(timer);
  }, [draft, saved, autosaveBlocked, dirty]);

  // Keep a copy of unsaved text on this device.
  useEffect(() => {
    if (!user || !project || !draft || !saved || draftRecoveryPrompt || draftRecoveryConflict) return;
    const identity = { userId: user.id, projectId: project.id, draftId: draft.id };
    try {
      if (draftChanged(draft, saved)) writeDraftRecovery(window.localStorage, identity, draft);
      else removeDraftRecovery(window.localStorage, identity);
    } catch {
      queueMicrotask(() => setDraftRecoveryUnavailable("这个浏览器不允许在本机保存恢复副本，请及时保存到服务器。"));
    }
  }, [draft, draftRecoveryConflict, draftRecoveryPrompt, project, saved, user]);

  const acceptRecovery = () => {
    if (!draftRecoveryPrompt) return;
    const conflict = draftRecoveryPrompt.snapshot.base_revision !== draftRecoveryPrompt.serverDraft.revision;
    setDraft({ ...draftRecoveryPrompt.serverDraft, title: draftRecoveryPrompt.snapshot.title, body: draftRecoveryPrompt.snapshot.body, body_format: draftRecoveryPrompt.snapshot.body_format ?? "plain_text" });
    setSaved(draftRecoveryPrompt.serverDraft);
    setDraftRecoveryConflict(conflict ? draftRecoveryPrompt : null);
    setDraftRecoveryPrompt(null);
    notify(conflict ? "编辑器里显示的是恢复副本。服务器上已有更新的版本，所以不能直接覆盖；可以随时回来比较。" : "已恢复本机副本，还没保存到服务器。");
  };
  const keepServerDraft = () => {
    if (!draftRecoveryPrompt || !user) return;
    try { removeDraftRecovery(window.localStorage, { userId: user.id, projectId: draftRecoveryPrompt.serverDraft.project_id, draftId: draftRecoveryPrompt.serverDraft.id }); }
    catch { setDraftRecoveryUnavailable("已选择服务器版本，但这个浏览器清理不了旧的恢复记录。"); }
    setDraft(draftRecoveryPrompt.serverDraft);
    setSaved(draftRecoveryPrompt.serverDraft);
    setDraftRecoveryConflict(null);
    setDraftRecoveryPrompt(null);
    notify("已使用服务器上保存的版本。");
  };

  const check = async () => {
    if (!projectId || !draft || dirty || readOnly) return;
    setBusy("正在提交检查");
    setChangeSet(null);
    try {
      const created = await json<Run>(`/projects/${projectId}/checks`, "POST", { draft_id: draft.id, draft_revision: draft.revision, client_request_id: crypto.randomUUID() });
      setRun({ ...created, current_revision: draft.revision, is_stale: false, superseded: false, lineage_status: "current", error_code: null, completed_at: null });
      setPairedRun(null);
      notify("开始检查了，完成后结果会出现在草稿旁边。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const cancelRun = async () => {
    if (!projectId || !run || !activeRun(run) || readOnly) return;
    setBusy("正在取消检查");
    try {
      await json(`/projects/${projectId}/checks/${run.run_id}/cancel`, "POST", { client_request_id: crypto.randomUUID() });
      const refreshed = await Promise.all((pairedRun ? [run, pairedRun] : [run]).map((item) => request<Run>(checkPath(projectId, item.run_id))));
      setRun(refreshed[0]);
      setPairedRun(refreshed[1] ?? null);
      if (refreshed[0].incremental_batch_id) {
        const delta = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
        setMemoryDelta(delta); setCoverage(delta.coverage ?? null);
      }
      notify(refreshed[0].status === "cancelled" ? "已取消，没有保存部分结果。" : "正在取消；之后返回的结果会被丢弃。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const retryRun = async () => {
    if (!projectId || !run || !retryableRun(run) || readOnly) return;
    setBusy("正在重新检查");
    try {
      const retried = await json<{ paired: boolean; run?: Run; continuity_run_id?: string; memory_delta_run_id?: string }>(`/projects/${projectId}/checks/${run.run_id}/retry`, "POST", { client_request_id: crypto.randomUUID() });
      const nextId = retried.paired ? retried.continuity_run_id : retried.run?.run_id;
      if (!nextId) throw Object.assign(new Error("Retry response missing Run"), { code: "internal_run_error" });
      const next = await request<Run>(checkPath(projectId, nextId));
      setRun(next);
      if (retried.paired) {
        if (!retried.memory_delta_run_id) throw Object.assign(new Error("Retry response missing paired Run"), { code: "internal_run_error" });
        setPairedRun(await request<Run>(checkPath(projectId, retried.memory_delta_run_id)));
        const delta = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
        setMemoryDelta(delta); setCoverage(delta.coverage ?? null);
      } else setPairedRun(null);
      notify(`开始第 ${next.attempt_number ?? "—"} 次检查；之前的记录保留不变。`);
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };

  const startAnalysis = async (analysisType: "context_brief" | "plan_alignment") => {
    if (!projectId || !draft || dirty || readOnly) return;
    setAnalysisBusy(analysisType);
    try {
      const created = await json<WritingAnalysisRun>(`/projects/${projectId}/analyses`, "POST", { analysis_type: analysisType, draft_id: draft.id, draft_revision: draft.revision, client_request_id: crypto.randomUUID() });
      const next = { ...created, is_stale: false, lineage_status: "current", error_code: null } as WritingAnalysisRun;
      if (analysisType === "context_brief") setContextBrief(next); else setPlanAlignment(next);
      notify(analysisType === "context_brief" ? "写前回顾开始了，完成后显示在草稿下方。" : "对照计划开始了，完成后按计划逐条显示。");
    } catch (cause) { fail(cause); } finally { setAnalysisBusy(""); }
  };
  const analysisAction = async (target: WritingAnalysisRun, action: "cancel" | "retry") => {
    if (!projectId || readOnly || !["context_brief", "plan_alignment"].includes(target.analysis_type)) return;
    if (action === "cancel" ? !activeAnalysis(target) : !retryableAnalysis(target)) return;
    const analysisType = target.analysis_type as "context_brief" | "plan_alignment";
    setAnalysisBusy(analysisType);
    try {
      let runId = target.run_id;
      if (action === "cancel") await json(`/projects/${projectId}/analyses/${target.run_id}/cancel`, "POST", { client_request_id: crypto.randomUUID() });
      else runId = (await json<{ run: WritingAnalysisRun }>(`/projects/${projectId}/analyses/${target.run_id}/retry`, "POST", { client_request_id: crypto.randomUUID() })).run.run_id;
      const next = await request<WritingAnalysisRun>(`/projects/${projectId}/analyses/${runId}`);
      if (analysisType === "context_brief") setContextBrief(next); else setPlanAlignment(next);
    } catch (cause) { fail(cause); } finally { setAnalysisBusy(""); }
  };

  const select = async (issue: Issue, element: HTMLElement | null) => {
    selectTrigger.current = element;
    if (project?.is_tutorial) {
      try { await tutorialEvent(project.id, "continuity_issue_located"); } catch { /* resynchronised by the caller */ }
    }
    setSelected(issue);
  };
  const deselect = () => {
    setSelected(null);
    window.setTimeout(() => selectTrigger.current?.focus(), 0);
  };

  /** Records 保留原意 / 不是问题 for one finding; resolves true once it is recorded. */
  const decide = async (issue: Issue, decision: "keep_intentional" | "false_positive"): Promise<boolean> => {
    if (!projectId || !run || readOnly) return false;
    if (!issueAllows(issue, decision) || !issueHasSufficientEvidence(issue)) {
      notify("这一条依据不够充分，或者不能这样处理；现在只能查看依据。");
      return false;
    }
    setBusy("正在记录决定");
    try {
      const recorded = await json<{ decision: string; resulting_revision: number | null }>(`/projects/${projectId}/issues/${issue.id}/decision`, "POST", {
        run_id: run.run_id,
        source_revision: run.source_revision,
        decision,
        ...(run.current_revision !== run.source_revision ? { resulting_revision: run.current_revision } : {}),
      });
      setLocallyResolvedIssueIds((ids) => [...new Set([...ids, issue.id])]);
      if (project?.is_tutorial) await tutorialEvent(project.id, "author_decision_recorded");
      const refreshed = await request<Run>(checkPath(projectId, run.run_id));
      setRun(refreshed);
      setSelected(refreshed.issues?.find((item) => item.id === issue.id) ?? { ...issue, decision: { decision: recorded.decision ?? decision, resulting_revision: recorded.resulting_revision ?? null } });
      notify(decision === "keep_intentional"
        ? (refreshed.issues ?? []).some((item) => issueNeedsDecision(item, [...locallyResolvedIssueIds, issue.id])) ? "记下了：保留原意。继续处理其他的。" : "记下了：保留原意。全部处理完后，可以审阅事实变化。"
        : "记下了：这一条不是问题，不会写进资料。");
      return true;
    } catch (cause) { fail(cause); return false; } finally { setBusy(""); }
  };
  const markToRevise = (issueId: string, toRevise: boolean) =>
    setRun((current) => (current ? { ...current, issues: current.issues?.map((item) => (item.id === issueId ? { ...item, to_revise: toRevise } : item)) } : current));
  const startControlledEdit = (issue: Issue) => {
    if (!issueAllows(issue, "edit")) { notify("这一条不能直接改正文。"); return; }
    setControlled(issue);
    setSelected(null);
    window.setTimeout(() => document.getElementById("draft-body")?.focus(), 0);
  };
  const applySuggestion = (issue: Issue) => {
    const suggestion = issue.suggested_revision;
    if (!issueAllows(issue, "apply_suggestion") || !issueHasSufficientEvidence(issue)) return false;
    if (!draft || !suggestion?.before || !suggestion.after) return false;
    if (draft.body_format === "markdown") {
      if (!replaceVisibleDraftText("draft-body", suggestion.before, suggestion.after)) return false;
    } else {
      const parts = draft.body.split(suggestion.before);
      if (parts.length !== 2) return false;
      setDraft({ ...draft, body: `${parts[0]}${suggestion.after}${parts[1]}` });
    }
    setControlled(issue);
    setSelected(null);
    notify("改法已放进草稿，还没保存。看一遍正文，再点「保存修改」。");
    window.setTimeout(() => document.getElementById("draft-body")?.focus(), 0);
    return true;
  };
  const reviewDecision = async (issue: Issue) => {
    if (!project?.is_tutorial || !run) return;
    await tutorialEvent(project.id, "author_decision_reviewed", { run_id: run.run_id, issue_id: issue.id });
    notify("复习过这条已有的决定了；没有新建或改写决定，可以继续导览。");
  };
  const beginEvidence = async () => {
    if (project?.is_tutorial) await tutorialEvent(project.id, "evidence_opened");
  };

  const review = async () => {
    if (!projectId || !run || readOnly) return;
    setBusy("正在整理事实变化");
    try {
      const data = await json<{ change_set: ChangeSet }>(`/projects/${projectId}/memory/change-sets`, "POST", { run_id: run.run_id, source_run_revision: run.source_revision, resolved_revision: run.current_revision });
      setChangeSet(data.change_set);
      window.setTimeout(() => document.getElementById("fact-review")?.scrollIntoView({ block: "start", behavior: "smooth" }), 0);
    } catch (cause) {
      if ((cause as ApiFailure).code === "no_reviewable_changes") notify(NO_FACT_CHANGES);
      else fail(cause);
    } finally { setBusy(""); }
  };
  const commit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !changeSet || readOnly) return;
    setBusy("正在更新资料");
    try {
      const form = new FormData(event.currentTarget);
      const accepted_item_ids = changeSet.items.filter((i) => ["accepted", "edited"].includes(String(form.get(i.id)))).map((i) => i.id);
      const rejected_item_ids = changeSet.items.filter((i) => String(form.get(i.id)) === "rejected").map((i) => i.id);
      const edited_items = changeSet.items.filter((i) => String(form.get(i.id)) === "edited").map((i) => ({
        item_id: i.id,
        memory_type: String(form.get(`edit:${i.id}:memory_type`)),
        subject: String(form.get(`edit:${i.id}:subject`)),
        predicate: String(form.get(`edit:${i.id}:predicate`)),
        value: String(form.get(`edit:${i.id}:value`)),
      }));
      if (accepted_item_ids.length + rejected_item_ids.length !== changeSet.items.length) throw Object.assign(new Error("invalid selection"), { code: "invalid_item_selection", retryable: false });
      const result = await json<{ status: string; memory_version: { current: number } }>(`/projects/${projectId}/memory/change-sets/${changeSet.id}/commit`, "POST", {
        confirm: true, accepted_item_ids, rejected_item_ids, edited_items, note: "作者在写作页审核",
      });
      setChangeSet(null);
      setMemories((await request<{ records: Memory[] }>(`/projects/${projectId}/memory`)).records);
      setProject((p) => (p ? { ...p, current_memory_version: result.memory_version.current } : p));
      notify(result.status === "committed" ? "资料已更新。" : "全部没记，资料保持不变。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };

  const startMemoryInitialization = async () => {
    if (!projectId || readOnly) return;
    setBusy("正在从正文整理事实");
    try {
      await json(`/projects/${projectId}/memory/initializations?view=compact`, "POST", { source_revision: 1 });
      const initialized = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(initialized);
      setCoverage(initialized.coverage ?? null);
      setProject((current) => (current ? { ...current, memory_initialization_status: "in_review" } : current));
      notify("候选事实已整理好，还没写进资料。请对照原文逐条确认。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const reopenMemoryCandidate = async (candidateId: string, baseDecisionStatus: "accepted" | "rejected" | "edited") => {
    if (!projectId || !initialization?.id || readOnly) return;
    if (!window.confirm("重新评估会把这条候选恢复为待确认；原来的决定仍留在记录里。继续吗？")) return;
    setBusy("正在重新打开候选");
    try {
      await json(`/projects/${projectId}/memory/initializations/${initialization.id}/candidates/${candidateId}/reopen?view=compact`, "POST", { confirm: true, base_decision_status: baseDecisionStatus });
      const refreshed = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(refreshed);
      setCoverage(refreshed.coverage ?? null);
      notify("这条候选恢复为待确认了；原来的决定留在记录里。没有自动接受任何事实。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const submitMemoryInitialization = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !initialization?.id || readOnly) return;
    const form = new FormData(event.currentTarget);
    const chosen = new Map(Array.from(event.currentTarget.querySelectorAll<HTMLInputElement>("input[data-memory-candidate-id]:checked")).map((input) => [input.dataset.memoryCandidateId!, input.value]));
    const undecided = initialization.candidates.filter((candidate) => candidate.decision_status === "pending");
    if (undecided.filter((candidate) => candidate.review_priority === "core").some((candidate) => !chosen.get(candidate.id))) {
      fail(Object.assign(new Error("请先决定所有核心候选"), { code: "invalid_candidate_decision", retryable: false }));
      return;
    }
    if (undecided.some((candidate) => chosen.get(candidate.id) === "edited" && form.get(`memory-init:${candidate.id}:evidence-confirmed`) !== "confirmed")) {
      fail(Object.assign(new Error("请确认编辑后的事实仍有原文依据"), { code: "evidence_confirmation_required", retryable: false }));
      return;
    }
    setBusy("正在建立第 1 版事实库");
    try {
      const decideOne = async (candidate: MemoryInitialization["candidates"][number]) => {
        const decision = chosen.get(candidate.id)!;
        const after = decision === "edited" ? {
          memory_type: String(form.get(`memory-init:${candidate.id}:memory_type`)),
          subject: String(form.get(`memory-init:${candidate.id}:subject`)),
          predicate: String(form.get(`memory-init:${candidate.id}:predicate`)),
          value: String(form.get(`memory-init:${candidate.id}:value`)),
        } : undefined;
        await json(`/projects/${projectId}/memory/initializations/${initialization.id}/candidates/${candidate.id}/decision?view=compact`, "POST", { decision, ...(after ? { after, evidence_span_id: candidate.source.span_id } : {}) });
      };
      const decided = undecided.filter((candidate) => chosen.has(candidate.id));
      if (initialization.candidates.length > BULK_REVIEW_THRESHOLD) {
        // A long import: plain accept/reject go in batches; edits still need one request each.
        const plain = decided.filter((candidate) => chosen.get(candidate.id) !== "edited");
        for (let start = 0; start < plain.length; start += BULK_DECISION_BATCH)
          await json(`/projects/${projectId}/memory/initializations/${initialization.id}/decisions?view=compact`, "POST", { decisions: plain.slice(start, start + BULK_DECISION_BATCH).map((candidate) => ({ candidate_id: candidate.id, decision: chosen.get(candidate.id)! })) });
        for (const candidate of decided.filter((item) => chosen.get(item.id) === "edited")) await decideOne(candidate);
      } else for (const candidate of decided) await decideOne(candidate);
      const reviewed = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(reviewed);
      setCoverage(reviewed.coverage ?? null);
      const committed = await json<{ memory_version: number; coverage?: MemoryCoverage }>(`/projects/${projectId}/memory/initializations/${initialization.id}/commit?view=compact`, "POST", { confirm: true });
      const refreshed = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(refreshed);
      setCoverage(committed.coverage ?? refreshed.coverage ?? null);
      setMemories((await request<{ records: Memory[] }>(`/projects/${projectId}/memory`)).records);
      setProject((current) => (current ? { ...current, current_memory_version: committed.memory_version, memory_initialization_status: refreshed.status === "committed" ? "completed" : "in_review" } : current));
      notify(refreshed.status === "committed"
        ? committed.coverage?.status === "ready_partial" ? "核心事实已确认；次要的候选还待确认，不会写进资料。现在可以开始检查。" : "第 1 版事实库建好了，现在可以检查。"
        : "没有确认任何核心事实；检查仍会直接对照原文。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const startIncrementalReview = async () => {
    if (!projectId || !project || readOnly) return;
    setBusy("正在检查新章节");
    try {
      const result = await json<{ delta: MemoryDelta }>(`/projects/${projectId}/incremental-reviews`, "POST", { source_revision: project.source_revision });
      let latest = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
      if (latest.continuity_run_id && latest.memory_delta_run_id) {
        const [continuity, deltaRun] = await Promise.all([request<Run>(checkPath(projectId, latest.continuity_run_id)), request<Run>(checkPath(projectId, latest.memory_delta_run_id))]);
        setRun(continuity);
        setPairedRun(deltaRun);
        if (!activeRun(continuity) && !activeRun(deltaRun) && latest.status === "processing") latest = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
      }
      setMemoryDelta(latest);
      setCoverage(latest.coverage ?? result.delta.coverage ?? null);
      notify(latest.status === "in_review" ? "新章节检查完了，事实变化也整理好了；还没写进资料。" : "新章节开始检查了；检查和事实变化都完成后显示结果。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const submitMemoryDelta = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !memoryDelta?.id || readOnly) return;
    const form = new FormData(event.currentTarget);
    const pending = memoryDelta.candidates.filter((x) => x.decision_status === "pending");
    if (pending.filter((x) => x.review_priority === "core").some((x) => !form.get(`memory-delta:${x.id}`))) {
      fail(Object.assign(new Error("请先决定所有核心候选"), { code: "unresolved_required_decisions" }));
      return;
    }
    setBusy("正在更新资料");
    try {
      for (const candidate of pending.filter((x) => form.get(`memory-delta:${x.id}`))) {
        const decision = String(form.get(`memory-delta:${candidate.id}`));
        const after = decision === "edited" ? {
          memory_type: String(form.get(`memory-delta:${candidate.id}:memory_type`)),
          subject: String(form.get(`memory-delta:${candidate.id}:subject`)),
          predicate: String(form.get(`memory-delta:${candidate.id}:predicate`)),
          value: String(form.get(`memory-delta:${candidate.id}:value`)),
        } : undefined;
        await json(`/projects/${projectId}/memory/deltas/${memoryDelta.id}/candidates/${candidate.id}/decision`, "POST", { decision, ...(after ? { after, evidence_span_id: candidate.source.span_id } : {}) });
      }
      const committed = await json<{ delta: MemoryDelta; memory_version: number }>(`/projects/${projectId}/memory/deltas/${memoryDelta.id}/commit`, "POST", { confirm: true });
      setMemoryDelta(committed.delta);
      setCoverage(committed.delta.coverage ?? null);
      setMemories((await request<{ records: Memory[] }>(`/projects/${projectId}/memory`)).records);
      setProject((current) => (current ? { ...current, current_memory_version: committed.memory_version } : current));
      notify(committed.memory_version > (memoryDelta.base_memory_version ?? 0) ? "资料已更新，更新记录已保存。" : memoryDelta.candidates.length ? "一条也没接受；出处都核对过，资料保持不变。" : "这一章没有新的事实变化；资料保持不变。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };

  const reset = async () => {
    if (!projectId) return false;
    setBusy("正在重置作品");
    try {
      await json(`/projects/${projectId}/reset`, "POST", { confirm: true, reason: "demo_recovery" });
      await loadProject(projectId);
      notify("作品已重置；其他作品没有变化。");
      return true;
    } catch (cause) { fail(cause); return false; } finally { setBusy(""); }
  };
  const updateProject = async (payload: Record<string, unknown>) => {
    if (!projectId || !project) return false;
    if (typeof project.metadata_revision !== "number") {
      fail(Object.assign(new Error("metadata_revision unavailable"), { code: "metadata_revision_unavailable", retryable: false }));
      return false;
    }
    setBusy("正在更新作品");
    try {
      const data = await json<{ project: Project }>(`/projects/${projectId}`, "PATCH", { base_metadata_revision: project.metadata_revision, ...payload });
      setProject((current) => (current ? { ...current, ...data.project } : data.project));
      notify(data.project.status === "archived" ? "作品已归档，现在只能浏览；恢复后可以继续写。" : "作品信息已更新。");
      return true;
    } catch (cause) { fail(cause); return false; } finally { setBusy(""); }
  };

  const refreshAuthorContext = useCallback(async (id: string, requestEpoch: number, signal?: AbortSignal) => {
    const next = await request<AuthorContext>(`/projects/${id}/author-intent?include_archived=true`, { signal });
    if (requestEpoch !== epoch.current || projectId !== id) return null;
    setAuthorContext(next);
    setProject((current) => (current?.id === id ? { ...current, author_context_version: next.author_context_version } : current));
    return next;
  }, [projectId]);
  const mutateAuthorContext = useCallback(async (endpoint: string, method: "POST" | "PATCH", payload: Record<string, unknown>, busyLabel: string) => {
    if (!projectId) throw new Error("author_context_project_missing");
    const id = projectId, requestEpoch = epoch.current, signal = activeRequest.current?.signal;
    setAuthorBusy(busyLabel);
    try {
      await json(`/projects/${id}/author-intent/${endpoint}`, method, payload, signal);
      return await refreshAuthorContext(id, requestEpoch, signal);
    } catch (cause) {
      if ((cause as ApiFailure).code === "author_context_version_conflict") {
        try { await refreshAuthorContext(id, requestEpoch, signal); } catch { /* keep the conflict as the failure */ }
      } else if ((cause as ApiFailure).code === "authentication_required") fail(cause);
      throw cause;
    } finally {
      if (requestEpoch === epoch.current && projectId === id) setAuthorBusy("");
    }
  }, [fail, projectId, refreshAuthorContext]);

  const openMemorySource = async (memory: Memory, element: HTMLElement) => {
    if (!memory.source) return;
    sourceTrigger.current = element;
    setSourceRecord({
      recordId: memory.id, subject: memory.subject, chapterId: memory.source.chapter_id, chapterNumber: memory.source.chapter_number,
      chapterTitle: memory.source.chapter_title, spanId: memory.source.span_id, excerpt: memory.source.excerpt, sourcePath: memory.source.source_path,
      memoryType: memory.memory_type, reviewStatus: memory.review_status, memoryValidFrom: memory.valid_from, memoryValidTo: memory.valid_to,
    });
    if (project?.is_tutorial) {
      try { await tutorialEvent(project.id, "memory_source_opened"); } catch { /* the drawer stays open */ }
    }
  };
  const openEvidenceSource = (issue: Issue, evidence: EvidenceItem, element: HTMLElement) => {
    sourceTrigger.current = element;
    setSourceRecord({
      recordId: evidence.id, subject: `${categoryLabel(issue.category)}的依据`, chapterId: evidence.chapter_id, chapterNumber: evidence.chapter_number,
      chapterTitle: evidence.chapter_title, spanId: evidence.span_id, excerpt: evidence.excerpt, sourcePath: evidence.source_path,
      sourceRevision: evidence.source_revision, relation: evidence.relation, sufficiency: evidence.sufficiency,
    });
  };
  const closeSource = () => {
    setSourceRecord(null);
    window.setTimeout(() => sourceTrigger.current?.focus(), 0);
  };

  return {
    // state
    project, missingProjectId, chapters, memories, characters, world, authorContext, authorBusy, draft, saved, run, pairedRun,
    initialization, memoryDelta, coverage, contextBrief, planAlignment, analysisBusy, busy, selected, controlled,
    pendingControlledDecision, locallyResolvedIssueIds, changeSet, saveFailed, autosaveState, draftRecoveryPrompt,
    draftRecoveryConflict, draftRecoveryUnavailable, pendingDecisionStorageUnavailable, pendingDecisionConflict,
    pendingDecisionPersisted, sourceRecord, tutorialRestored, readOnly, dirty, narrow,
    // actions
    notify, clear, loadProject, refreshReferences, refreshSummary, adoptNextDraft, setDraft, save, check, cancelRun, retryRun, startAnalysis, analysisAction,
    select, deselect, decide, markToRevise, startControlledEdit, applySuggestion, reviewDecision, beginEvidence,
    review, commit, startMemoryInitialization, reopenMemoryCandidate, submitMemoryInitialization, startIncrementalReview,
    submitMemoryDelta, reset, updateProject, mutateAuthorContext, openMemorySource, openEvidenceSource, closeSource,
    acceptRecovery, keepServerDraft, stopConflictedPendingDecision, markTutorialRestarted, openDraftRecoveryConflict: () => draftRecoveryConflict && setDraftRecoveryPrompt(draftRecoveryConflict),
  };
}

export type ProjectState = ReturnType<typeof useProject>;
