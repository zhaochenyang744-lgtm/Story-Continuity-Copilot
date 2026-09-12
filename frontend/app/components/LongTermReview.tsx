"use client";

import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../api";

type Chapter = { id: string; title: string; number: number; source_revision: number; body: string; body_format?: "plain_text" | "markdown"; revision_editable?: boolean; body_notice?: string };
type Policy = { id?: string; issue_id: string; decision: string; note?: string; claim_text?: string; explanation?: string; enabled: boolean; revision: number; is_current: boolean; invalidation_reason?: string };
type Review = { id: string; chapter_id: string; source_revision: number; memory: { id: string; type?: string; subject: string; predicate: string; value: string }; new_source_span_id: string; status: string; revision: number };
type Snapshot = { project_id: string; source_revision: number; memory_version: number; reusable_decisions: Policy[]; eligible_decisions?: Policy[]; source_revision_reviews: Review[]; chapters: Chapter[] };
type Preview = { id: string; content_sha256: string; before: { title: string; body: string }; after: { title: string; body: string; body_format?: string }; impact: { affected_memory_count: number; affected_analysis_count: number; affected_memory?: unknown[] }; target_source_revision: number };
type EditRecovery = { user_id: string; project_id: string; chapter: Chapter; title: string; body: string; base_source_revision: number };

const errors: Record<string, string> = {
  chapter_full_text_unavailable: "此章节只保存了来源片段，缺少完整正文，暂不能修订。可以查看现有来源，或导入完整作品后继续。",
  source_revision_context_review_required: "请先到 Story Memory 完成初始化或上一轮资料更新的候选确认，再返回修订历史章节。",
  source_revision_review_required: "历史章节已修订，请先逐项复核受影响的事实，再继续 AI 检查。",
  decision_reuse_unavailable: "这条历史判断缺少完整依据，请先重新检查并作出决定后启用复用。",
  decision_reuse_stale: "判断依据已经变化，请重新检查后再决定是否复用。",
  source_revision_conflict: "正文已在其他窗口更新。请刷新修订资料，再重新核对。",
  chapter_revision_conflict: "这章已有更新，请重新读取后再预览。",
  revision_preview_expired: "修订预览已过期，请重新预览。",
  source_revision_review_pending: "请先逐项复核下方受影响的事实，再继续 AI 检查。",
  source_review_pending: "请先完成受影响事实的复核。",
  memory_version_conflict: "事实资料已有更新，请刷新资料后重新核对。",
  policy_revision_conflict: "这条复用设置已有更新，请刷新资料。",
  source_revision_no_change: "正文和标题没有变化，无需提交修订。",
};
function explain(cause: unknown) { return errors[(cause as ApiFailure)?.code] ?? labelError(cause); }

export function LongTermReview({ projectId, userId, readOnly, onChanged }: { projectId: string; userId: string; readOnly: boolean; onChanged: () => Promise<void> }) {
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState("");
  const [editing, setEditing] = useState<Chapter | null>(null);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null);
  const [recovery, setRecovery] = useState<EditRecovery | null>(null);
  const [storageWarning, setStorageWarning] = useState("");
  const alive = useRef(true);
  const recoveryKey = `story-continuity:chapter-revision:v1:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}`;
  const base = `/projects/${encodeURIComponent(projectId)}`;
  const reload = useCallback(async (signal?: AbortSignal) => {
    const result = await request<Snapshot>(`${base}/long-term-review`, { signal });
    if (alive.current) setSnapshot(result);
  }, [base]);
  useEffect(() => {
    alive.current = true;
    const controller = new AbortController();
    void reload(controller.signal).then(() => {
      if (controller.signal.aborted) return;
      try {
        const raw = localStorage.getItem(recoveryKey);
        if (!raw) return;
        const saved = JSON.parse(raw) as EditRecovery;
        if (saved.user_id === userId && saved.project_id === projectId && typeof saved.title === "string" && typeof saved.body === "string" && typeof saved.chapter?.id === "string" && Number.isInteger(saved.chapter.source_revision) && Number.isInteger(saved.base_source_revision)) setRecovery(saved);
      } catch { setStorageWarning("当前设备无法读取历史章节的恢复副本，请完成提交后再离开。"); }
    }).catch((cause) => { if (!controller.signal.aborted) setError(explain(cause)); });
    return () => { alive.current = false; controller.abort(); };
  }, [reload, recoveryKey, userId, projectId]);
  const dirty = Boolean(editing && (title !== editing.title || body !== editing.body));
  useEffect(() => {
    if (!dirty) return;
    const warn = (event: BeforeUnloadEvent) => { event.preventDefault(); };
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [dirty]);
  useEffect(() => {
    if (!editing || !snapshot || !dirty) return;
    const timer = window.setTimeout(() => {
      try {
        localStorage.setItem(recoveryKey, JSON.stringify({ user_id: userId, project_id: projectId, chapter: editing, title, body, base_source_revision: snapshot.source_revision } satisfies EditRecovery));
      } catch { setStorageWarning("当前设备无法保留修订副本，请完成提交后再离开。"); }
    }, 0);
    return () => window.clearTimeout(timer);
  }, [editing, snapshot, dirty, recoveryKey, userId, projectId, title, body]);
  function discardRecovery() {
    try { localStorage.removeItem(recoveryKey); } catch { setStorageWarning("当前设备的恢复副本未能清除，请检查浏览器存储权限。"); }
    setRecovery(null);
  }

  async function act(label: string, operation: () => Promise<void>) {
    if (busy || readOnly) return;
    setBusy(label); setError(""); setNotice("");
    try { await operation(); }
    catch (cause) { if (alive.current) setError(explain(cause)); }
    finally { if (alive.current) setBusy(""); }
  }
  function startEdit(chapter: Chapter) {
    setEditing(chapter); setTitle(chapter.title); setBody(chapter.body); setPreview(null); setError(""); setNotice("");
  }
  async function makePreview(event: FormEvent) {
    event.preventDefault();
    if (!editing || !snapshot) return;
    await act("生成修订预览", async () => {
      const result = await json<{ revision_preview: Preview }>(`${base}/chapters/${encodeURIComponent(editing.id)}/revisions/preview`, "POST", {
        base_source_revision: snapshot.source_revision, base_chapter_revision: editing.source_revision, title, body,
        body_format: editing.body_format ?? "plain_text",
      });
      if (alive.current) setPreview(result.revision_preview);
    });
  }
  async function commitRevision() {
    if (!preview) return;
    await act("提交章节修订", async () => {
      await json(`${base}/chapter-revisions/${encodeURIComponent(preview.id)}/commit`, "POST", { confirm: true, content_sha256: preview.content_sha256 });
      if (!alive.current) return;
      discardRecovery();
      setEditing(null); setPreview(null);
      await reload(); await onChanged();
      if (alive.current) setNotice("章节修订已保存。旧正文和审阅记录仍然保留；请逐项处理下方需要复核的事实。完成后可继续检查新正文。");
    });
  }
  const pending = snapshot?.source_revision_reviews.filter((item) => item.status === "pending") ?? [];
  const policyRows = [...(snapshot?.reusable_decisions ?? [])];
  for (const item of snapshot?.eligible_decisions ?? []) if (!policyRows.some((p) => p.issue_id === item.issue_id)) policyRows.push(item);

  return <section className="long-term-review" id="long-term-review" aria-labelledby="long-term-heading">
    <header className="maintenance-heading">
      <div><p className="eyebrow">作品修订</p><h2 id="long-term-heading">修订历史章节与复核事实</h2><p>先预览正文变化，再确认受影响的资料。每一次修订都保留旧版本。</p></div>
      <button type="button" disabled={Boolean(busy) || dirty} onClick={() => { setError(""); void reload().catch((cause) => setError(explain(cause))); }}>刷新修订资料</button>
    </header>
    {error && <p className="notice error" role="alert">{error}</p>}
    {notice && <p className="notice" role="status">{notice}</p>}
    {storageWarning && <p className="warning" role="status">{storageWarning}</p>}
    {recovery && !editing && !readOnly && <section className="revision-preview" aria-label="恢复历史章节修订">
      <h3>发现当前设备的未提交章节修订</h3><p>{recovery.title}</p>
      <p>恢复副本不会覆盖服务器正文。若服务器章节已有更新，请重新核对两个版本。</p>
      <button type="button" onClick={() => {
        const current = snapshot?.chapters.find((c) => c.id === recovery.chapter.id);
        if (!current) { setError("这章已不在当前作品中。恢复副本仍保留在本机。"); return; }
        if (current.revision_editable === false) { setError(errors.chapter_full_text_unavailable); return; }
        setEditing(recovery.chapter); setTitle(recovery.title); setBody(recovery.body); setPreview(null);
        if (current.source_revision !== recovery.chapter.source_revision || snapshot?.source_revision !== recovery.base_source_revision) setError("服务器正文已有更新。已保留本机编辑内容；请先复制需要的文字，放弃本次编辑，再读取当前章节核对，不能直接覆盖新版本。");
        else setNotice("已恢复本机修订，尚未提交到服务器。");
      }}>恢复本机修订</button><button type="button" onClick={discardRecovery}>删除本机修订副本</button>
    </section>}
    {!snapshot && !error && <p role="status">正在读取章节与复核记录…</p>}
    {readOnly && <p className="muted">当前为阅读模式，可查看修订资料；请在桌面打开可编辑的作品以提交修改。</p>}
    {snapshot && <>
      <details className="maintenance-details" open={Boolean(editing)}>
        <summary>已入库章节 <span>{snapshot.chapters.length} 章</span></summary>
        {!editing ? <ul className="maintenance-chapters">{snapshot.chapters.map((chapter) => <li key={chapter.id}>
          <span>第 {chapter.number} 章 · {chapter.title}{chapter.body_notice && <small className="muted"> · {chapter.body_notice}</small>}</span>
          <button type="button" disabled={readOnly || chapter.revision_editable === false || Boolean(busy) || pending.length > 0} onClick={() => startEdit(chapter)}>修订本章</button>
        </li>)}</ul> : <form onSubmit={(event) => void makePreview(event)} className="chapter-revision-form">
          <label>修订章节标题<input value={title} maxLength={120} required disabled={readOnly || Boolean(busy)} onChange={(event) => { setTitle(event.target.value); setPreview(null); }} /></label>
          <label>修订章节正文<textarea value={body} required rows={14} disabled={readOnly || Boolean(busy)} onChange={(event) => { setBody(event.target.value); setPreview(null); }} /></label>
          <p className="muted">{editing.body_format === "markdown" ? "本章使用 Markdown，格式标记会随正文保存。" : "本章按纯文本保存。"} 未提交修订会保留在当前设备，恢复后仍需预览并明确提交。</p>
          <div className="actions"><button type="submit" disabled={readOnly || Boolean(busy) || !dirty}>预览修订影响</button><button type="button" disabled={readOnly || Boolean(busy)} onClick={() => { discardRecovery(); setEditing(null); setPreview(null); }}>放弃本次编辑</button></div>
        </form>}
        {preview && <section className="revision-preview" aria-label="章节修订预览">
          <h3>确认这次正文修订</h3>
          <p>{preview.impact.affected_memory_count} 条已确认事实需要复核，{preview.impact.affected_analysis_count} 条分析记录可能过期。</p>
          <div className="revision-comparison"><section><h4>修订前 · {preview.before.title}</h4><pre>{preview.before.body}</pre></section><section><h4>修订后 · {preview.after.title}</h4><pre>{preview.after.body}</pre></section></div>
          <p>提交会替换当前章节正文，并保留历史版本。受影响的事实需由你逐项确认后再用于新的 AI 检查。</p>
          <button type="button" className="primary" disabled={Boolean(busy) || readOnly} onClick={() => void commitRevision()}>{busy === "提交章节修订" ? "提交中…" : "确认提交章节修订"}</button>
        </section>}
      </details>
      <section className="source-reviews" aria-labelledby="source-reviews-heading">
        <h3 id="source-reviews-heading">待复核的事实 <span>{pending.length}</span></h3>
        {pending.length === 0 ? <p className="muted">当前没有因历史正文修订而待复核的事实。</p> : <p>逐项阅读新正文，确认这条事实是否仍有依据。全部处理后可继续进行 AI 检查。</p>}
        {pending.map((review) => <FactReview key={review.id} review={review} chapter={snapshot.chapters.find((c) => c.id === review.chapter_id)} disabled={readOnly || Boolean(busy)} resolve={async (decision, note) => {
          await act("记录事实复核", async () => {
            await json(`${base}/source-reviews/${encodeURIComponent(review.id)}/resolve`, "POST", {
              base_revision: review.revision, base_memory_version: snapshot.memory_version, decision, confirm: true, note,
              ...(decision === "retain" ? { evidence_span_id: review.new_source_span_id } : {}),
            });
            await reload(); if (alive.current) await onChanged();
          });
        }} />)}
      </section>
      <details className="maintenance-details">
        <summary>复用已作出的作者判断 <span>{policyRows.filter((item) => item.enabled && item.is_current).length} 条生效</span></summary>
        <p>仅对正文、证据和相关资料均未改变的同类问题沿用你的判断。资料变化后会重新核对，原问题与来源仍可查看。</p>
        {!policyRows.length && <p className="muted">对检查结果明确选择保留原意或标记误报后，可在这里启用判断复用。</p>}
        {policyRows.map((policy) => <article className="decision-policy" key={policy.issue_id}>
          <p>{policy.claim_text || policy.explanation || "已审阅的问题"}</p><p>{policy.note || "作者已作出判断。"}</p>
          <p className="muted">{policy.enabled ? policy.is_current ? "判断复用已启用" : "相关资料已变化，当前不再复用" : "判断复用未启用"}</p>
          <button type="button" disabled={readOnly || Boolean(busy) || (!policy.enabled && !policy.is_current)} onClick={() => void act("更新判断复用", async () => {
            await json(`${base}/issues/${encodeURIComponent(policy.issue_id)}/reuse`, "POST", { enabled: !policy.enabled, base_policy_revision: policy.revision ?? 0 });
            await reload();
          })}>{policy.enabled ? "停止复用" : "启用判断复用"}</button>
        </article>)}
      </details>
    </>}
  </section>;
}

function FactReview({ review, chapter, disabled, resolve }: { review: Review; chapter?: Chapter; disabled: boolean; resolve: (decision: "retain" | "invalidate", note: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  return <article className="fact-source-review">
    <h4>{review.memory.subject} · {review.memory.value}</h4>
    <details><summary>阅读修订后的依据 · {chapter?.title ?? "当前章节"}</summary><pre>{chapter?.body ?? "请刷新修订资料以读取正文。"}</pre></details>
    <label>复核说明（必填）<input value={note} maxLength={1000} required onChange={(event) => setNote(event.target.value)} disabled={disabled} placeholder="说明仍然成立的依据，或停止沿用的原因" /></label>
    <div className="actions"><button type="button" disabled={disabled || !chapter || !note.trim()} onClick={() => void resolve("retain", note)}>确认仍有依据，保留事实</button><button type="button" disabled={disabled || !note.trim()} onClick={() => void resolve("invalidate", note)}>停止沿用这条事实</button></div>
  </article>;
}
