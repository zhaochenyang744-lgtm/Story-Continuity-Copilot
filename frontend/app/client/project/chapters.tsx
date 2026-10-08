"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { json, labelError, request, type ApiFailure } from "../../api";
import type { Draft, Issue, SourceChangeSet } from "../../model";
import { categoryLabel, dayLabel, timelineStatusHint, timelineStatusLabel, toneLabel } from "../labels";
import { bareChapterTitle, Button, formatCount, Num, PageHead, pad2, SectionHead, Tag } from "../ui";
import type { PageProps } from "./frame";
import type { ProjectState } from "./use-project";
import { CountUp, Odometer } from "../motion";

const MAX = 8;
type TimelineRow = { chapter_id: string | null; chapter_number: number; title: string; draft: boolean; status: string };
type CheckIssue = { sentence: string; nature?: string; category?: string; severity?: Issue["severity"]; explanation: string; evidence: { chapter_number: number; chapter_title: string; excerpt: string }[] };
type CheckRun = { run_id: string; status: string; stage: string; error_code?: string | null; created_at: string; completed_at?: string | null; sample?: boolean; report: { chapters: { chapter_id: string; chapter_number: number; chapter_title: string; issues: CheckIssue[]; undecided: number }[]; issue_count: number } | null };
type ReviewChapter = { id: string; title: string; number: number; source_revision: number; body: string; body_format?: "plain_text" | "markdown"; revision_editable?: boolean; body_notice?: string };
type Policy = { issue_id: string; decision: string; note?: string; claim_text?: string; explanation?: string; enabled: boolean; revision: number; is_current: boolean };
type SourceReview = { id: string; chapter_id: string; memory: { subject: string; predicate: string; value: string }; new_source_span_id: string; status: string; revision: number };
type Snapshot = { source_revision: number; memory_version: number; reusable_decisions: Policy[]; eligible_decisions?: Policy[]; source_revision_reviews: SourceReview[]; chapters: ReviewChapter[] };

const tone = (issue: Pick<CheckIssue, "nature" | "severity">) => (issue.nature === "confirmed_conflict" ? "high" : issue.nature === "insufficient_evidence" ? "gap" : issue.nature === "state_change" ? "state" : issue.severity === "high" ? "high" : "mid");
const reviewErrors: Record<string, string> = {
  chapter_full_text_unavailable: "这一章只存了部分段落，没有完整正文，暂时不能修订。",
  source_revision_context_review_required: "请先到资料里确认上一轮的事实变化，再回来修订。",
  source_revision_review_required: "章节修订过，请先逐条复核受影响的事实，再继续检查。",
  decision_reuse_unavailable: "这条判断缺少完整依据，请重新检查并作出决定后再沿用。",
  decision_reuse_stale: "判断依据已经变了，请重新检查后再决定是否沿用。",
  source_revision_conflict: "正文在别的窗口更新了，请刷新后重新核对。",
  chapter_revision_conflict: "这一章已有更新，请重新读取后再预览。",
  revision_preview_expired: "预览过期了，请重新预览。",
  source_revision_review_pending: "请先逐条复核下面受影响的事实，再继续检查。",
  source_review_pending: "请先复核受影响的事实。",
  memory_version_conflict: "资料已有更新，请刷新后重新核对。",
  policy_revision_conflict: "这条沿用设置已有更新，请刷新。",
  source_revision_no_change: "正文和标题都没变，不用提交。",
};
const explain = (cause: unknown) => reviewErrors[(cause as ApiFailure)?.code] ?? labelError(cause);

/** 章节: every written chapter with its check status; tick up to eight and check them together. */
export function ChaptersPage({ p, user, usage, go, notices }: PageProps) {
  const project = p.project!;
  const visitor = user.account_type === "visitor";
  const [timeline, setTimeline] = useState<TimelineRow[] | null>(null);
  const [runs, setRuns] = useState<CheckRun[]>([]);
  const [snapshot, setSnapshot] = useState<Snapshot | null>(null);
  const [picked, setPicked] = useState<string[]>([]);
  const [open, setOpen] = useState<string | null>(null);
  const [estimate, setEstimate] = useState<{ characters: number; estimated_cny: number } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [reviewError, setReviewError] = useState("");
  const load = useCallback(async () => {
    const base = `/projects/${project.id}`;
    const [list, rows, review] = await Promise.all([
      request<{ runs: CheckRun[] }>(`${base}/chapter-checks?limit=3`).catch(() => ({ runs: [] as CheckRun[] })),
      request<{ chapters: TimelineRow[] }>(`${base}/chapter-timeline`),
      request<Snapshot>(`${base}/long-term-review`).then((value) => ({ value, failure: "" }), (cause) => ({ value: null, failure: explain(cause) })),
    ]);
    setRuns(list.runs); setTimeline(rows.chapters);
    if (review.value) setSnapshot(review.value);
    setReviewError(review.failure);
  }, [project.id]);
  useEffect(() => {
    let live = true;
    void Promise.resolve().then(load).catch((cause) => { if (live) setError(labelError(cause)); });
    return () => { live = false; };
  }, [load, project.source_revision]);
  const active = runs.some((run) => ["queued", "running"].includes(run.status));
  useEffect(() => {
    if (!active) return;
    const timer = window.setTimeout(() => void load().catch(() => undefined), 3000);
    return () => window.clearTimeout(timer);
  }, [active, runs, load]);
  useEffect(() => {
    if (!picked.length) return;
    let live = true;
    json<{ characters: number; estimated_cny: number }>(`/projects/${project.id}/chapter-checks/estimate`, "POST", { chapter_ids: picked })
      .then((next) => { if (live) setEstimate(next); }).catch(() => { if (live) setEstimate(null); });
    return () => { live = false; };
  }, [project.id, picked]);
  const start = async () => {
    setBusy(true); setError("");
    try {
      await json(`/projects/${project.id}/chapter-checks`, "POST", { chapter_ids: picked });
      setPicked([]);
      await load();
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(false); }
  };

  const bodies = new Map((snapshot?.chapters ?? []).map((chapter) => [chapter.id, chapter]));
  const latest = visitor ? runs.find((run) => run.sample) : runs[0];
  const lastResult = new Map<number, CheckIssue[]>();
  const sampleResult = new Set<number>();
  for (const run of runs) if (run.status === "completed" && run.report) for (const chapter of run.report.chapters) if (!lastResult.has(chapter.chapter_number)) {
    lastResult.set(chapter.chapter_number, chapter.issues);
    if (run.sample) sampleResult.add(chapter.chapter_number);
  }
  const rows = timeline ?? p.chapters.map((chapter) => ({ chapter_id: chapter.id, chapter_number: chapter.number, title: chapter.title, draft: false, status: "unchecked" }));
  const written = rows.filter((row) => !row.draft && row.chapter_id);
  const draftRow = rows.find((row) => row.draft);
  const totalChars = project.chapter_word_count ?? (snapshot?.chapters ?? []).reduce((sum, chapter) => sum + chapter.body.replace(/\s+/g, "").length, 0);
  const checkedCount = written.filter((row) => row.status === "checked").length;
  const shown = picked.length ? estimate : null;
  const over = Boolean(shown && usage?.account_type === "registered" && shown.characters > usage.check_chars_remaining);
  const pendingReviews = snapshot?.source_revision_reviews.filter((item) => item.status === "pending") ?? [];
  const draftIssues = (p.run?.issues ?? []).filter((issue) => !issue.decision && !issue.reused_decision && !p.locallyResolvedIssueIds.includes(issue.id)).length;
  const canPick = !visitor && !p.readOnly;
  const openChapter = (number: number) => go(`/projects/${project.id}/workspace?chapter=${number}`);

  return (
    <section className="page chapters">
      {notices}
      <PageHead
        title="章节"
        lede={visitor ? "访客只能检查当前草稿；注册后可以一次勾选最多 8 章一起检查。" : "勾选最多 8 章一起检查。每一章只和它前面的章节对照。"}
        aside={
          <div className="head-figures-actions">
            <dl className="figures">
              <div><dt className="sr-only">章节</dt><dd><Num><CountUp id={`${project.id}:chapters`} value={written.length} /></Num></dd><dd className="figure-label">章</dd></div>
              <div><dt className="sr-only">字数</dt><dd><Num><CountUp id={`${project.id}:words`} value={totalChars} /></Num></dd><dd className="figure-label">字</dd></div>
              <div><dt className="sr-only">已检查</dt><dd><Num><CountUp id={`${project.id}:checked`} value={checkedCount} /></Num></dd><dd className="figure-label">章已检查</dd></div>
            </dl>
            {!p.readOnly && <Button size="lg" onClick={() => document.getElementById("append")?.scrollIntoView({ block: "start", behavior: "smooth" })}>追加章节</Button>}
          </div>
        }
      />
      {pendingReviews.length > 0 && <div className="note note-warn"><span>有 {pendingReviews.length} 条事实因为章节修订需要复核。复核完之前不能运行检查。</span><Button kind="text" onClick={() => document.getElementById("source-reviews")?.scrollIntoView({ block: "start", behavior: "smooth" })}>去复核</Button></div>}
      {error && <div className="note note-error" role="alert">{error}</div>}
      {reviewError && <div className="note note-warn" role="status"><span>章节正文和修订记录没读出来：{reviewError} 字数暂时不可用。</span><Button kind="text" onClick={() => void load().catch((cause) => setError(labelError(cause)))}>重新读取</Button></div>}
      <div className="table-scroll">
        <div className={canPick ? "chapter-table" : "chapter-table no-pick"} role="table" aria-label="全部章节">
          <div className="chapter-row chapter-row-head" role="row">
            {canPick && <span role="columnheader">选</span>}<span role="columnheader">章</span><span role="columnheader">标题</span><span role="columnheader">字数</span><span role="columnheader">状态</span><span role="columnheader">上次结果</span><span role="columnheader"><span className="sr-only">打开</span></span>
          </div>
          {written.map((row) => {
            const id = row.chapter_id!;
            const on = picked.includes(id);
            const chapter = p.chapters.find((item) => item.id === id);
            const spans = (chapter?.source_spans ?? []).filter((span) => span.is_current !== false);
            const body = bodies.get(id);
            const result = lastResult.get(row.chapter_number);
            const isOpen = open === id;
            return (
              <div key={id} id={`chapter-${row.chapter_number}`} tabIndex={-1} className={`chapter-item${on ? " picked" : ""}`} role="rowgroup">
                <div className="chapter-row" role="row">
                  {canPick && <span role="cell" className="chapter-pick">
                    <input type="checkbox" aria-label={`选择第 ${row.chapter_number} 章`} checked={on} disabled={(!on && picked.length >= MAX) || busy || active} onChange={() => setPicked((current) => (on ? current.filter((item) => item !== id) : [...current, id]))} />
                  </span>}
                  <span role="cell"><Num className="chapter-num">{pad2(row.chapter_number)}</Num></span>
                  <span role="cell" className="chapter-title">
                    <strong>{bareChapterTitle(row.title) || "未命名"}</strong>
                    {(spans.length > 0 || body) && <button type="button" className="chapter-expand" aria-expanded={isOpen} onClick={() => setOpen(isOpen ? null : id)}>{isOpen ? "收起" : `段落 ${spans.length}`}</button>}
                  </span>
                  <span role="cell" className="mono">{body ? formatCount(body.body.replace(/\s+/g, "").length) : "—"}</span>
                  <span role="cell" className="chapter-status" title={timelineStatusHint[row.status]}><i className={`status-mark ${row.status}`} aria-hidden="true" />{timelineStatusLabel[row.status] ?? "未检查"}</span>
                  <span role="cell" className="chapter-result">{sampleResult.has(row.chapter_number) && <span className="label" title="示例作品预先放好的结果，不算检查过">示例</span>}{result ? result.length ? <Tag tone={result.some((issue) => tone(issue) === "high") ? "high" : "mid"}>{result.length} 处{result.length === 1 ? toneLabel[tone(result[0])] : ""}</Tag> : <span className="muted">无问题</span> : <span className="muted">—</span>}</span>
                  <span role="cell"><button type="button" className="link" onClick={() => openChapter(row.chapter_number)}>{p.readOnly ? "打开" : "打开修改"}</button></span>
                </div>
                {isOpen && (
                  <div className="chapter-passages">
                    <ul>
                      {(chapter?.source_spans ?? []).map((span) => (
                        <li key={span.span_id} id={`span-${span.span_id}`} className={span.is_current === false ? "old" : undefined}>
                          <strong>{span.label === "chapter_revision" ? "修订后的正文" : span.label}{span.is_current === false ? " · 修订前" : ""}</strong>
                          <span>{span.text_excerpt}</span>
                        </li>
                      ))}
                    </ul>
                    <Button kind="small" onClick={() => openChapter(row.chapter_number)}>{p.readOnly ? "在写作页打开" : "在写作页打开修改"}</Button>
                    {body?.body_notice && <p className="small-note">{body.body_notice}</p>}
                  </div>
                )}
              </div>
            );
          })}
          {draftRow && (
            <div className="chapter-item draft" role="rowgroup">
              <div className="chapter-row" role="row">
                {canPick && <span role="cell" className="chapter-pick" />}
                <span role="cell"><Num className="chapter-num blue">{pad2(draftRow.chapter_number)}</Num></span>
                <span role="cell" className="chapter-title"><strong>{bareChapterTitle(draftRow.title) || "未命名"}</strong><span className="badge">草稿</span></span>
                <span role="cell" className="mono">{formatCount((p.draft?.body ?? "").replace(/\s+/g, "").length)}</span>
                <span role="cell">在写作页检查</span>
                <span role="cell"><button type="button" className="link blue" onClick={() => go(`/projects/${project.id}/workspace`)}>去写作{draftIssues ? ` · ${draftIssues} 处` : ""}</button></span>
                <span role="cell" />
              </div>
            </div>
          )}
        </div>
      </div>
      {!written.length && <p className="empty">还没有已写的章节。在写作页写完一章后点「完成本章」，或者在下面追加。</p>}

      {canPick && written.length > 0 && (
        <div className="select-bar" aria-live="polite">
          <span className="select-count"><Num><Odometer value={picked.length} /></Num><span> / {MAX} 章</span></span>
          <span className="select-summary">
            {picked.length
              ? <>约 {formatCount(shown?.characters ?? 0)} 字 · 预计{shown ? (shown.estimated_cny >= 0.01 ? `约 ¥${shown.estimated_cny.toFixed(2)}` : "不到 ¥0.01") : "…"}{usage?.account_type === "registered" && ` · 可检查 ${formatCount(usage.check_chars_remaining)} 字`}{over && " · 额度不够"}</>
              : "勾选要检查的章节，最多 8 章"}
          </span>
          <button type="button" className="select-go" disabled={busy || active || !picked.length || over} onClick={() => void start()}>{active ? "正在检查…" : "检查选中的章节"}</button>
        </div>
      )}

      {latest && <LatestResult run={latest} />}
      <AppendSection p={p} go={go} reload={load} />
      <SourceReviews snapshot={snapshot} projectId={project.id} readOnly={p.readOnly} reload={async () => { await load(); await p.refreshReferences(); }} />
      <ReusePolicies snapshot={snapshot} projectId={project.id} readOnly={p.readOnly} reload={load} />
    </section>
  );
}

/** 最近一次检查: one column per checked chapter, its sentences and the passages they were checked against. */
function LatestResult({ run }: { run: CheckRun }) {
  return (
    <section className="latest" aria-labelledby="latest-title">
      <SectionHead id="latest-title" title={run.sample ? "示例结果" : run.status === "completed" ? "最近一次检查" : "正在检查"} aside={<span className="label">{run.report ? `第 ${run.report.chapters.map((c) => c.chapter_number).join("、")} 章 · ${run.report.issue_count ? `${run.report.issue_count} 处` : "没有问题"} · ` : ""}{dayLabel(run.completed_at ?? run.created_at)}</span>} />
      {run.sample && <p className="small-note">示例作品预先放好的结果，展示多章检查会得到什么；没有调用模型。</p>}
      {["failed", "timed_out", "cancelled"].includes(run.status) && <p className="inline-error">{labelError({ code: run.error_code })}</p>}
      {["queued", "running"].includes(run.status) && <p className="small-note" role="status">正在检查，完成后结果出现在这里。</p>}
      <div className="latest-grid">
        {run.report?.chapters.map((chapter) => (
          <article key={chapter.chapter_id} className={chapter.issues.length ? "latest-chapter wide" : "latest-chapter"}>
            <header><Num>{pad2(chapter.chapter_number)}</Num><strong>{bareChapterTitle(chapter.chapter_title) || "未命名"}</strong></header>
            {!chapter.issues.length && <p className="muted">没有发现问题{chapter.undecided ? `；${chapter.undecided} 句没能判断` : ""}</p>}
            {chapter.issues.map((issue, index) => (
              <div key={index} className="latest-issue">
                <Tag tone={tone(issue)}>{toneLabel[tone(issue)]}{issue.severity ? ` · ${{ high: "高", medium: "中", low: "低" }[issue.severity]}` : ""}{issue.category ? ` · ${categoryLabel(issue.category)}` : ""}</Tag>
                <blockquote className={`latest-quote tone-${tone(issue)}`}>{issue.sentence}</blockquote>
                {issue.explanation && <p>{issue.explanation}</p>}
                {issue.evidence.map((item, at) => (
                  <div key={at} className="latest-evidence"><span className="label">依据 · 第 {item.chapter_number} 章 · {bareChapterTitle(item.chapter_title) || "未命名"}</span><p>{item.excerpt}</p></div>
                ))}
              </div>
            ))}
          </article>
        ))}
      </div>
    </section>
  );
}

/** 追加章节: paste, upload, or turn the current draft into a written chapter. */
function AppendSection({ p, go, reload }: { p: ProjectState; go: (href: string) => void; reload: () => Promise<void> }) {
  const project = p.project!;
  const [method, setMethod] = useState<"draft_complete" | "paste" | "file">(() => (typeof window !== "undefined" && window.location.hash === "#complete-draft" && p.draft ? "draft_complete" : "paste"));
  const [content, setContent] = useState("");
  const [filename, setFilename] = useState("");
  const [preview, setPreview] = useState<SourceChangeSet | null>(null);
  const [nextDraft, setNextDraft] = useState<Draft | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  if (p.readOnly && !preview) return null;
  const makePreview = async () => {
    setBusy("正在预览"); setError("");
    try {
      const data = await json<{ source_change_set: SourceChangeSet }>(`/projects/${project.id}/source-change-sets/preview`, "POST", {
        mode: "append", input_method: method, base_source_revision: project.source_revision ?? 1,
        ...(method === "draft_complete" ? { draft_id: p.draft?.id } : { content, ...(method === "file" ? { filename } : {}) }),
      });
      setPreview(data.source_change_set);
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(""); }
  };
  const commit = async () => {
    if (!preview) return;
    setBusy("正在追加"); setError("");
    try {
      const data = await json<{ source_change_set: SourceChangeSet; next_draft: Draft }>(`/projects/${project.id}/source-change-sets/${preview.id}/commit`, "POST", { confirm: true, content_sha256: preview.content_sha256 });
      setPreview(data.source_change_set);
      setNextDraft(data.next_draft);
      // The work moves on to the next chapter's draft; refresh everything that depends on it.
      p.adoptNextDraft(data.next_draft);
      await Promise.all([p.refreshReferences(), p.refreshSummary(), reload()]);
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(""); }
  };
  return (
    <section id="append" className="append" aria-labelledby="append-title">
      <span id="complete-draft" />
      <SectionHead id="append-title" title="追加章节" />
      {!p.readOnly && !preview && (
        <>
          <div className="tabs tabs-md">
            <nav aria-label="追加方式">
              {(["draft_complete", "paste", "file"] as const).map((value) => (
                <button key={value} type="button" className="tab" aria-current={method === value ? "page" : undefined} disabled={Boolean(busy)} onClick={() => setMethod(value)}>
                  {value === "draft_complete" ? "完成当前草稿" : value === "paste" ? "粘贴正文" : "上传文件"}
                </button>
              ))}
            </nav>
          </div>
          {method === "draft_complete" ? (
            <p className="append-lede">把草稿《{bareChapterTitle(p.draft?.title ?? "") || "未命名"}》定为第 {p.draft?.chapter_number ?? "—"} 章，然后开始下一章的草稿。{p.dirty && " 草稿还有没保存的修改，请先保存。"}</p>
          ) : (
            <>
              <label className="field"><span className="field-label">章节正文</span><textarea rows={8} value={content} onChange={(event) => setContent(event.target.value)} disabled={Boolean(busy)} placeholder="粘贴一章或多章。带「第 X 章」标题的会自动分章。" /></label>
              {method === "file" && (
                <label className="field"><span className="field-label">文件</span><input type="file" accept=".md,.txt,text/markdown,text/plain" disabled={Boolean(busy)} onChange={async (event) => { const file = event.currentTarget.files?.[0]; if (!file) return; setFilename(file.name); setContent(await file.text()); }} /><span className="small-note">{filename || "UTF-8 编码的 .md 或 .txt"}</span></label>
              )}
            </>
          )}
          <div className="form-actions"><Button kind="primary" disabled={Boolean(busy) || (method === "draft_complete" ? !p.draft || p.dirty : !content.trim())} onClick={() => void makePreview()}>{busy || "预览"}</Button></div>
        </>
      )}
      {error && <div className="note note-error" role="alert">{error} 内容还在，请刷新后重试。</div>}
      {preview && (
        <div className="append-preview">
          <p className="label">{preview.status === "previewed" ? "预览 · 还没写入" : "已追加"}</p>
          <ol className="rows">
            {preview.chapters.map((chapter) => <li key={chapter.preview_id}><span className="rows-static"><Num className="rows-num wide">{pad2(chapter.order)}</Num><span className="rows-copy"><strong>{chapter.title}</strong><span>{formatCount(chapter.character_count)} 字</span></span></span></li>)}
          </ol>
          {!p.readOnly && (preview.status === "previewed" ? (
            <div className="form-actions"><Button kind="primary" disabled={Boolean(busy)} onClick={() => void commit()}>确认追加</Button><Button kind="text" disabled={Boolean(busy)} onClick={() => setPreview(null)}>重新编辑</Button></div>
          ) : (
            <div className="form-actions">{nextDraft && <span>下一章草稿：第 {nextDraft.chapter_number} 章</span>}<Button kind="primary" onClick={() => go(`/projects/${project.id}/workspace`)}>去写下一章</Button></div>
          ))}
        </div>
      )}
    </section>
  );
}

/** 待复核的事实: facts whose source chapter was revised; each is kept or retired with a note. */
function SourceReviews({ snapshot, projectId, readOnly, reload }: { snapshot: Snapshot | null; projectId: string; readOnly: boolean; reload: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const pending = snapshot?.source_revision_reviews.filter((item) => item.status === "pending") ?? [];
  if (!snapshot || !pending.length) return null;
  const resolve = async (review: SourceReview, decision: "retain" | "invalidate", note: string) => {
    setBusy(true); setError("");
    try {
      await json(`/projects/${encodeURIComponent(projectId)}/source-reviews/${encodeURIComponent(review.id)}/resolve`, "POST", {
        base_revision: review.revision, base_memory_version: snapshot.memory_version, decision, confirm: true, note, ...(decision === "retain" ? { evidence_span_id: review.new_source_span_id } : {}),
      });
      await reload();
    } catch (cause) { setError(explain(cause)); } finally { setBusy(false); }
  };
  return (
    <section id="source-reviews" className="source-reviews" aria-labelledby="source-reviews-title">
      <SectionHead id="source-reviews-title" title="待复核的事实" aside={<Num>{pending.length}</Num>} />
      <p className="lede">这些事实出自修订过的章节。读一下新正文，确认它们还成立吗。</p>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {pending.map((review) => <FactReviewRow key={review.id} review={review} chapter={snapshot.chapters.find((item) => item.id === review.chapter_id)} disabled={readOnly || busy} resolve={resolve} />)}
    </section>
  );
}
function FactReviewRow({ review, chapter, disabled, resolve }: { review: SourceReview; chapter?: ReviewChapter; disabled: boolean; resolve: (review: SourceReview, decision: "retain" | "invalidate", note: string) => Promise<void> }) {
  const [note, setNote] = useState("");
  return (
    <article className="fact-check">
      <strong>{review.memory.subject} · {review.memory.value}</strong>
      <details><summary>读修订后的正文 · {chapter ? bareChapterTitle(chapter.title) : "当前章节"}</summary><pre className="prose-pre">{chapter?.body ?? "请刷新后读取正文。"}</pre></details>
      <label className="field"><span className="field-label">说明（必填）</span><input value={note} maxLength={1000} required disabled={disabled} onChange={(event) => setNote(event.target.value)} placeholder="为什么还成立，或者为什么不再沿用" /></label>
      <div className="form-actions">
        <Button kind="primary" disabled={disabled || !chapter || !note.trim()} onClick={() => void resolve(review, "retain", note)}>还成立，保留</Button>
        <Button disabled={disabled || !note.trim()} onClick={() => void resolve(review, "invalidate", note)}>不再沿用</Button>
      </div>
    </article>
  );
}

/** 沿用的判断: earlier "保留原意 / 不是问题" decisions that apply again while nothing they rest on has changed. */
function ReusePolicies({ snapshot, projectId, readOnly, reload }: { snapshot: Snapshot | null; projectId: string; readOnly: boolean; reload: () => Promise<void> }) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const panel = useRef<HTMLDetailsElement>(null);
  if (!snapshot) return null;
  const rows = [...snapshot.reusable_decisions];
  for (const item of snapshot.eligible_decisions ?? []) if (!rows.some((row) => row.issue_id === item.issue_id)) rows.push(item);
  const toggle = async (policy: Policy) => {
    setBusy(true); setError("");
    try {
      await json(`/projects/${encodeURIComponent(projectId)}/issues/${encodeURIComponent(policy.issue_id)}/reuse`, "POST", { enabled: !policy.enabled, base_policy_revision: policy.revision ?? 0 });
      await reload();
    } catch (cause) { setError(explain(cause)); } finally { setBusy(false); }
  };
  return (
    <details ref={panel} className="reuse" id="decision-reuse">
      <summary><span>沿用的判断</span><span className="label">{rows.filter((item) => item.enabled && item.is_current).length} 条生效</span></summary>
      <p className="lede">你选过「保留原意」或「不是问题」的句子，只要正文、依据和相关资料都没变，下次检查直接沿用你的判断。</p>
      {error && <p className="inline-error" role="alert">{error}</p>}
      {!rows.length && <p className="muted">还没有可以沿用的判断。</p>}
      <ul className="reuse-list">
        {rows.map((policy) => (
          <li key={policy.issue_id}>
            <span className="reuse-text"><strong>{policy.claim_text || policy.explanation || "处理过的句子"}</strong><span className="label">{policy.enabled ? policy.is_current ? "正在沿用" : "相关资料变了，暂停沿用" : "没有沿用"}</span></span>
            <Button kind="small" disabled={readOnly || busy || (!policy.enabled && !policy.is_current)} onClick={() => void toggle(policy)}>{policy.enabled ? "停止沿用" : "沿用"}</Button>
          </li>
        ))}
      </ul>
    </details>
  );
}
