"use client";

import { useCallback, useEffect, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { Chapter, DraftBodyFormat } from "../../model";
import { DraftWordCount, RichDraftEditor, WritingTools } from "../editor";
import { Odometer } from "../motion";
import { bareChapterTitle, Button, chapterHeading, Dialog, formatCount, Num, pad2, writtenChars } from "../ui";
import type { PageProps } from "./frame";

/** A written chapter as the revision endpoints know it. */
type ReviewChapter = { id: string; title: string; number: number; source_revision: number; body: string; body_format?: DraftBodyFormat; revision_editable?: boolean; body_notice?: string };
type Snapshot = { source_revision: number; source_revision_reviews: { status: string }[]; chapters: ReviewChapter[] };
type RevisionPreview = { id: string; content_sha256: string; before: { title: string; body: string }; after: { title: string; body: string }; impact: { affected_memory_count: number; affected_analysis_count: number } };
type Recovery = { chapter: ReviewChapter; title: string; body: string; body_format?: DraftBodyFormat; base_source_revision: number };

const errors: Record<string, string> = {
  chapter_full_text_unavailable: "这一章只存了部分段落，没有完整正文，暂时不能修改。",
  source_revision_context_review_required: "请先到资料里确认上一轮的事实变化，再回来修改。",
  source_revision_review_required: "章节改过，请先到章节页逐条复核受影响的事实。",
  source_revision_conflict: "正文在别的窗口更新了，请刷新后重新核对。",
  chapter_revision_conflict: "这一章已有更新，请重新读取后再预览。",
  revision_preview_expired: "预览过期了，请重新预览。",
  source_revision_review_pending: "请先到章节页逐条复核受影响的事实。",
  source_review_pending: "请先复核受影响的事实。",
  source_revision_no_change: "正文和标题都没变，不用提交。",
};
const explain = (cause: unknown) => errors[(cause as ApiFailure)?.code] ?? labelError(cause);

/** The local copy of an unsubmitted chapter edit (same key the chapters page used before). */
export const revisionRecoveryKey = (userId: string, projectId: string) => `story-continuity:chapter-revision:v1:${encodeURIComponent(userId)}:${encodeURIComponent(projectId)}`;

// The app asks before leaving a page while a chapter edit is open.
let unsubmittedRevision = false;
export const hasUnsubmittedRevision = () => unsubmittedRevision;

/** "第十一章：桌上的留白" → ["第十一章：", "桌上的留白"]: the number is shown big beside the title, so only
    the name is edited; the prefix is kept as written. */
export function titleParts(title: string): [string, string] {
  const match = title.match(/^(\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*[章回节]\s*[:：·.、\-—\s]*)([\s\S]*)$/);
  return match && match[2].trim() ? [match[1], match[2]] : ["", title];
}

/** The chapter title in the head: wraps instead of scrolling; Enter does nothing. */
export function TitleField({ value, onChange, disabled, placeholder }: { value: string; onChange: (next: string) => void; disabled: boolean; placeholder?: string }) {
  const [prefix, name] = titleParts(value);
  return (
    <label className="draft-title">
      <span className="sr-only">章节标题</span>
      <textarea data-writing-focus rows={1} value={name} placeholder={placeholder} disabled={disabled} maxLength={120}
        onKeyDown={(event) => { if (event.key === "Enter") event.preventDefault(); }}
        onChange={(event) => onChange(`${prefix}${event.target.value.replace(/[\r\n]+/g, "")}`)} />
    </label>
  );
}

/** 章节 on the left of the writing page: the written chapters, then the draft. Pointing at a
    finding lights the chapters its evidence comes from. */
export function ChapterRail({ chapters, current, draftNumber, draftTitle, linked = [], open }: {
  chapters: Chapter[];
  /** the chapter shown, or null for the draft */
  current: number | null;
  draftNumber: number;
  draftTitle: string;
  linked?: number[];
  open: (number: number | null) => void;
}) {
  return (
    <nav className="draft-chapters" aria-label="章节">
      <p className="label">章节</p>
      <ol>
        {chapters.map((chapter) => (
          <li key={chapter.id} data-chapter={chapter.number} className={linked.includes(chapter.number) ? "linked" : undefined}>
            <button type="button" aria-current={current === chapter.number ? "page" : undefined} onClick={() => open(chapter.number)}>
              <span className="mono">{pad2(chapter.number)}</span>{bareChapterTitle(chapter.title) || "未命名"}
            </button>
          </li>
        ))}
        <li className="draft-row">
          <button type="button" aria-current={current === null ? "page" : undefined} onClick={() => open(null)}>
            <span className="mono">{pad2(draftNumber)}</span>{bareChapterTitle(draftTitle) || "草稿"}<span className="badge">草稿</span>
          </button>
        </li>
      </ol>
    </nav>
  );
}

/** A written chapter on the writing page: read it, or change it in the same editor as the draft.
    Before anything is replaced the author sees which confirmed facts it touches; the old text is
    kept as a revision. */
export function ChapterDesk({ p, user, go, notices, number, open }: Pick<PageProps, "p" | "user" | "go" | "notices"> & { number: number; open: (number: number | null) => void }) {
  const project = p.project!;
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [loadError, setLoadError] = useState("");
  const [editing, setEditing] = useState(false);
  const [title, setTitle] = useState("");
  const [body, setBody] = useState("");
  const [format, setFormat] = useState<DraftBodyFormat>("plain_text");
  const [preview, setPreview] = useState<RevisionPreview | null>(null);
  const [compare, setCompare] = useState(false);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [storageWarning, setStorageWarning] = useState("");
  const [recovery, setRecovery] = useState<Recovery | null>(null);
  const [conflict, setConflict] = useState(false);
  const key = revisionRecoveryKey(user.id, project.id);

  const load = useCallback(async () => {
    const next = await request<Snapshot>(`/projects/${project.id}/long-term-review`);
    setSnapshot(next);
    return next;
  }, [project.id]);
  useEffect(() => {
    let live = true;
    void Promise.resolve().then(load).then(() => { if (live) setLoadError(""); }, (cause) => { if (live) setLoadError(explain(cause)); });
    try {
      const raw = localStorage.getItem(key);
      const saved = raw ? JSON.parse(raw) as Recovery : null;
      if (saved && typeof saved.title === "string" && typeof saved.body === "string" && typeof saved.chapter?.id === "string") void Promise.resolve().then(() => { if (live) setRecovery(saved); });
    } catch { /* nothing to restore */ }
    return () => { live = false; };
  }, [load, key]);

  const chapter = snapshot?.chapters.find((item) => item.number === number) ?? null;
  const listed = p.chapters.find((item) => item.number === number);
  const pendingReviews = snapshot?.source_revision_reviews.filter((item) => item.status === "pending").length ?? 0;
  const dirty = editing && Boolean(chapter) && (title !== chapter!.title || body !== chapter!.body);
  const shownTitle = editing ? title : chapter?.title ?? listed?.title ?? "";
  const shownBody = editing ? body : chapter?.body ?? "";
  const canEdit = Boolean(chapter) && !p.readOnly && chapter!.revision_editable !== false && pendingReviews === 0;
  const ownRecovery = recovery && chapter && recovery.chapter.id === chapter.id ? recovery : null;

  // Keep a local copy while editing, and ask before the tab closes.
  useEffect(() => {
    unsubmittedRevision = dirty;
    if (!dirty || !snapshot || !chapter) return;
    try { localStorage.setItem(key, JSON.stringify({ user_id: user.id, project_id: project.id, chapter, title, body, body_format: format, base_source_revision: snapshot.source_revision })); }
    catch { void Promise.resolve().then(() => setStorageWarning("这台设备存不下修改副本，请提交后再离开。")); }
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => { window.removeEventListener("beforeunload", warn); unsubmittedRevision = false; };
  }, [dirty, snapshot, chapter, key, user.id, project.id, title, body, format]);

  const startEdit = (from?: Recovery) => {
    if (!chapter) return;
    setTitle(from?.title ?? chapter.title);
    setBody(from?.body ?? chapter.body);
    setFormat(from?.body_format ?? chapter.body_format ?? "plain_text");
    setConflict(Boolean(from && (from.chapter.source_revision !== chapter.source_revision || from.base_source_revision !== snapshot?.source_revision)));
    setPreview(null); setError(""); setEditing(true);
    if (from) setRecovery(null);
    window.setTimeout(() => document.getElementById("chapter-body")?.focus(), 0);
  };
  const discard = () => {
    try { localStorage.removeItem(key); } catch { /* fine */ }
    unsubmittedRevision = false;
    setEditing(false); setPreview(null); setError(""); setConflict(false); setRecovery(null);
  };
  const makePreview = async () => {
    if (!snapshot || !chapter) return;
    setBusy("正在预览"); setError("");
    try {
      const result = await json<{ revision_preview: RevisionPreview }>(`/projects/${project.id}/chapters/${encodeURIComponent(chapter.id)}/revisions/preview`, "POST", {
        base_source_revision: snapshot.source_revision, base_chapter_revision: chapter.source_revision, title, body, body_format: format,
      });
      setPreview(result.revision_preview);
    } catch (cause) { setError(explain(cause)); } finally { setBusy(""); }
  };
  const commit = async () => {
    if (!preview) return;
    setBusy("正在提交"); setError("");
    try {
      await json(`/projects/${project.id}/chapter-revisions/${encodeURIComponent(preview.id)}/commit`, "POST", { confirm: true, content_sha256: preview.content_sha256 });
      try { localStorage.removeItem(key); } catch { /* fine */ }
      unsubmittedRevision = false;
      const affected = preview.impact.affected_memory_count;
      setEditing(false); setPreview(null);
      await Promise.all([load(), p.refreshReferences(), p.refreshSummary()]);
      p.notify(affected ? `第 ${number} 章已更新，旧版本保留。有 ${affected} 条事实需要到章节页复核。` : `第 ${number} 章已更新，旧版本保留。`);
    } catch (cause) { setError(explain(cause)); } finally { setBusy(""); }
  };

  const primary = !editing ? (
    <Button kind="primary" size="lg" disabled={!canEdit} onClick={() => startEdit()}>修改这一章</Button>
  ) : preview ? (
    <Button kind="primary" size="lg" disabled={Boolean(busy)} busy={busy === "正在提交"} onClick={() => void commit()}>{busy === "正在提交" ? "正在提交" : "确认提交修改"}</Button>
  ) : (
    <Button kind="primary" size="lg" disabled={!dirty || Boolean(busy) || conflict} busy={busy === "正在预览"} onClick={() => void makePreview()}>{busy === "正在预览" ? "正在预览" : "预览修改影响"}</Button>
  );

  return (
    <section className="page writing chapter-mode">
      {notices}
      <header className="draft-head">
        <Num className="draft-head-num ink"><Odometer value={number} /></Num>
        <div className="draft-head-main">
          <h1 className="sr-only">{chapterHeading(number, shownTitle)}</h1>
          <p className="label draft-head-meta">
            <span className="badge badge-line">已完成</span>
            <span>{formatCount(writtenChars(shownBody))} 字</span>
            {editing && <span className={`save-state ${dirty ? "unsaved" : "saved"}`}><i aria-hidden="true" />{dirty ? "有改动，还没提交" : "还没改动"}</span>}
          </p>
          <TitleField value={shownTitle} disabled={!editing || Boolean(busy) || Boolean(preview)} onChange={(next) => { setTitle(next); setPreview(null); }} />
        </div>
        <div className="draft-head-side">
          <div className="draft-head-actions">
            <Button size="lg" onClick={() => open(null)}>回到草稿</Button>
            {!p.readOnly && primary}
          </div>
        </div>
      </header>

      <div className="draft-grid">
        <ChapterRail chapters={p.chapters} current={number} draftNumber={p.draft?.chapter_number ?? project.current_draft.chapter_number} draftTitle={p.draft?.title ?? ""} open={open} />

        <article className="draft" aria-label={`第 ${number} 章正文`}>
          {editing && (
            <div className="draft-tools">
              <WritingTools targetId="chapter-body" disabled={Boolean(busy) || Boolean(preview)} />
              <span className="label"><DraftWordCount targetId="chapter-body" body={body} /></span>
            </div>
          )}
          <div className="draft-field">
            {chapter ? (
              <RichDraftEditor key={`${chapter.id}:${editing ? "edit" : "read"}`} id="chapter-body" label={`第 ${number} 章正文${editing ? "" : "（只读）"}`} value={shownBody} format={editing ? format : chapter.body_format ?? "plain_text"} disabled={!editing || Boolean(busy) || Boolean(preview)}
                onChange={(next, nextFormat) => { setBody(next); setFormat(nextFormat); setPreview(null); }} />
            ) : <p className="findings-empty">{loadError || "正在读取这一章…"}</p>}
          </div>
        </article>

        <aside className="findings chapter-panel" aria-labelledby="chapter-panel-title">
          <div className="findings-head">
            <h2 id="chapter-panel-title">{editing ? "修改这一章" : "已完成的章节"}</h2>
            <span className="label">第 {number} 章</span>
          </div>
          {loadError && <p className="inline-error" role="alert">{loadError}</p>}
          {!editing && (
            <>
              <p className="panel-copy">可以直接在这里修改。提交前会先列出哪些已确认的事实受影响，旧版本会保留。</p>
              {chapter?.revision_editable === false && <p className="finding-hint warn">{errors.chapter_full_text_unavailable}</p>}
              {chapter?.body_notice && <p className="finding-hint">{chapter.body_notice}</p>}
              {pendingReviews > 0 && (
                <div className="panel-note">
                  <p>有 {pendingReviews} 条事实因为之前的修改等你复核，复核完才能再改章节。</p>
                  <Button kind="text" onClick={() => go(`/projects/${project.id}/sources#source-reviews`)}>去章节页复核</Button>
                </div>
              )}
              {ownRecovery && !p.readOnly && (
                <div className="panel-note">
                  <p>这台设备上有这一章没提交的修改。</p>
                  <span className="actions">
                    <Button kind="text" disabled={!canEdit} onClick={() => startEdit(ownRecovery)}>接着改</Button>
                    <Button kind="text" onClick={discard}>删除副本</Button>
                  </span>
                </div>
              )}
              {recovery && !ownRecovery && <p className="finding-hint">这台设备上还有第 {recovery.chapter.number} 章没提交的修改，打开那一章可以接着改。</p>}
            </>
          )}
          {editing && !preview && (
            <>
              <p className="panel-copy">改完点「预览修改影响」。没提交的修改会先留在这台设备上。</p>
              {conflict && <p className="finding-hint warn">服务器上的这一章在副本之后更新过。请先复制需要的文字，放弃这次修改，再对照最新正文重新修改。</p>}
              {storageWarning && <p className="finding-hint warn">{storageWarning}</p>}
              <p className="small-note">{format === "markdown" ? "这一章用 Markdown 保存，格式会一起保存。" : "这一章按纯文本保存。"}</p>
              <div className="finding-actions"><Button kind="text" disabled={Boolean(busy)} onClick={discard}>放弃修改</Button></div>
            </>
          )}
          {editing && preview && (
            <>
              <div className="impact">
                <p><Num>{preview.impact.affected_memory_count}</Num><span>条已确认的事实需要复核</span></p>
                <p><Num>{preview.impact.affected_analysis_count}</Num><span>条分析可能过时</span></p>
              </div>
              <p className="panel-copy">提交后替换这一章的正文，旧版本保留。受影响的事实要你在章节页逐条确认后，才会用于新的检查。</p>
              <div className="finding-actions">
                <Button kind="text" onClick={() => setCompare(true)}>看前后对照</Button>
                <Button kind="text" disabled={Boolean(busy)} onClick={() => setPreview(null)}>继续修改</Button>
              </div>
            </>
          )}
          {error && <p className="inline-error" role="alert">{error}</p>}
        </aside>
      </div>

      {compare && preview && (
        <Dialog title={`第 ${number} 章 · 前后对照`} wide close={() => setCompare(false)}>
          <div className="compare">
            <div><p className="label">修改前 · {bareChapterTitle(preview.before.title)}</p><pre className="prose-pre">{preview.before.body}</pre></div>
            <div><p className="label">修改后 · {bareChapterTitle(preview.after.title)}</p><pre className="prose-pre">{preview.after.body}</pre></div>
          </div>
        </Dialog>
      )}
    </section>
  );
}
