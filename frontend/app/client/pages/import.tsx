"use client";

import { FormEvent, useRef, useState } from "react";
import { json, request } from "../../api";
import type { User } from "../../model";
import { importStrategyLabel, importWarningLabel } from "../labels";
import { Button, formatCount, Num, PageHead, pad2 } from "../ui";

type ImportPreview = {
  import_id: string;
  file: { name: string; size: number; sha256: string; format: string };
  detected: {
    strategy: string;
    chapter_count: number;
    chapters: { preview_id: string; title: string; order: number; character_count: number; excerpt: string; source_line_start?: number; source_line_end?: number }[];
    audit?: { source_line_count: number; retained_body_characters: number; coverage_complete: boolean; order_preserved: boolean; no_duplicate_source_assignment: boolean; directory_index_blocks: { excluded_line_count: number }[] };
  };
  warnings: string[];
};
const formatName = (format: string) => ({ md: "Markdown", markdown: "Markdown", txt: "纯文本", docx: "Word" } as Record<string, string>)[format] ?? format;
const PAGE = 8;

/** 导入: choose a file → check how it was split into chapters → name the work. Nothing is created until the last step. */
export function ImportPage({ user, fail, go }: { user: User; fail: (cause: unknown) => void; go: (href: string) => void }) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [file, setFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [preview, setPreview] = useState<ImportPreview | null>(null);
  const [step, setStep] = useState<1 | 2 | 3>(1);
  const [page, setPage] = useState(1);
  const [busy, setBusy] = useState("");
  const [localError, setLocalError] = useState("");
  const visitor = user.account_type === "visitor";

  const choose = (next?: File) => { if (!next) return; setFile(next); setLocalError(""); };
  const send = async () => {
    if (!file) { fileInput.current?.click(); return; }
    setBusy("正在分章");
    try {
      const form = new FormData();
      form.append("file", file);
      setPreview(await request<ImportPreview>("/imports/preview", { method: "POST", headers: { "Idempotency-Key": crypto.randomUUID() }, body: form }));
      setPage(1);
      setStep(2);
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const discard = async (leave: boolean) => {
    if (preview) {
      setBusy("正在取消");
      try { await json(`/imports/${preview.import_id}/cancel`, "POST", { confirm: true }); }
      catch (cause) { fail(cause); setBusy(""); return; }
      setBusy("");
    }
    setPreview(null);
    setStep(1);
    setFile(null);
    if (fileInput.current) fileInput.current.value = "";
    if (leave) go("/projects");
  };
  const commit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!preview) return;
    const form = new FormData(event.currentTarget);
    setBusy("正在创建作品");
    try {
      const data = await json<{ project: { id: string } }>(`/imports/${preview.import_id}/commit`, "POST", {
        confirm: true,
        title: String(form.get("title")),
        genre: String(form.get("genre")),
        summary: String(form.get("summary")),
        chapter_preview_ids: preview.detected.chapters.map((chapter) => chapter.preview_id),
      });
      go(`/projects/${data.project.id}/overview`);
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const pages = Math.max(1, Math.ceil((preview?.detected.chapters.length ?? 0) / PAGE));
  const current = Math.min(page, pages);
  const audit = preview?.detected.audit;
  const clean = Boolean(audit && audit.coverage_complete && audit.order_preserved && audit.no_duplicate_source_assignment);
  const defaultTitle = preview?.file.name.replace(/\.(docx|txt|md|markdown)$/i, "") ?? "";

  return (
    <section className="page import">
      <PageHead title="导入作品" lede="把写好的稿子带进来。先看分章对不对，确认后才会创建作品。" />
      <ol className="steps" aria-label="导入步骤">
        {["选择文件", "检查分章", "确认作品信息"].map((label, index) => (
          <li key={label} aria-current={step === index + 1 ? "step" : undefined} className={step > index + 1 ? "done" : undefined}>
            <Num>{pad2(index + 1)}</Num><span>{label}</span>
          </li>
        ))}
      </ol>

      {step === 1 && (
        <div className="import-step">
          <input ref={fileInput} className="sr-only" type="file" tabIndex={-1} accept=".docx,.txt,.md,.markdown,application/vnd.openxmlformats-officedocument.wordprocessingml.document,text/plain,text/markdown" onChange={(event) => choose(event.currentTarget.files?.[0])} disabled={Boolean(busy)} />
          <div
            className={`dropzone${dragging ? " dragging" : ""}${file ? " chosen" : ""}`}
            data-testid="import-dropzone"
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => { event.preventDefault(); setDragging(false); choose(event.dataTransfer.files[0]); }}
          >
            {file ? (
              <>
                <span className="label">已选择</span>
                <strong className="dropzone-name">{file.name}</strong>
                <span>{formatCount(file.size)} 字节</span>
                <Button kind="small" onClick={() => fileInput.current?.click()} disabled={Boolean(busy)}>换一个文件</Button>
              </>
            ) : (
              <>
                <strong className="dropzone-title">把文件拖到这里</strong>
                <span>或者</span>
                <Button onClick={() => fileInput.current?.click()} disabled={Boolean(busy)}>选择文件</Button>
              </>
            )}
          </div>
          <ul className="import-rules">
            <li><strong>Word、TXT、Markdown</strong>Word 按「标题 1 / 标题 2」分章；TXT 和 Markdown 请用 UTF-8 编码。文件不超过 {visitor ? "1" : "5"} MB，最多 {visitor ? "1 万" : "35 万"}字。</li>
            <li><strong>点下一步才发送</strong>文件发到本站服务器分章，只用于生成预览。</li>
            <li><strong>确认前随时可以取消</strong>预览不会创建作品，也不会整理事实。</li>
          </ul>
          {localError && <p className="inline-error">{localError}</p>}
          <div className="form-actions">
            <Button kind="primary" size="lg" disabled={Boolean(busy)} busy={Boolean(busy)} onClick={() => void send()}>{busy || (file ? "下一步：检查分章" : "选择文件")}</Button>
            <Button kind="text" disabled={Boolean(busy)} onClick={() => void discard(true)}>取消导入</Button>
          </div>
        </div>
      )}

      {preview && step === 2 && (
        <div className="import-step">
          <div className="import-summary">
            <div><Num>{preview.detected.chapter_count}</Num><span>章</span></div>
            <div><Num>{formatCount(audit?.retained_body_characters ?? preview.detected.chapters.reduce((sum, chapter) => sum + chapter.character_count, 0))}</Num><span>字</span></div>
            <p>
              <strong>{preview.file.name}</strong> · {formatName(preview.file.format)} · {importStrategyLabel(preview.detected.strategy)}
              <br />
              {audit ? (clean ? "原文全部保留，顺序不变，没有重复或遗漏。" : "分章需要你核对：请逐章看一下下面的开头。") : ""}
              {audit && audit.directory_index_blocks.length > 0 ? ` 已跳过 ${audit.directory_index_blocks.reduce((total, block) => total + block.excluded_line_count, 0)} 行目录。` : ""}
            </p>
          </div>
          {preview.warnings.length > 0 && <p className="note note-warn" role="note">{preview.warnings.map(importWarningLabel).join("；")}</p>}
          <ol className="chapter-preview" aria-label="分章预览">
            {preview.detected.chapters.slice((current - 1) * PAGE, current * PAGE).map((chapter) => (
              <li key={chapter.preview_id}>
                <Num>{pad2(chapter.order)}</Num>
                <div>
                  <strong>{chapter.title}</strong>
                  <p>{chapter.excerpt}</p>
                </div>
                <span className="label">{formatCount(chapter.character_count)} 字{chapter.source_line_start && chapter.source_line_end ? ` · 第 ${chapter.source_line_start}–${chapter.source_line_end} 行` : ""}</span>
              </li>
            ))}
          </ol>
          {pages > 1 && (
            <nav className="pager" aria-label="分章预览翻页">
              <Button kind="small" disabled={current === 1} onClick={() => setPage(current - 1)}>上一页</Button>
              <span className="label" aria-live="polite">{current} / {pages}</span>
              <Button kind="small" disabled={current === pages} onClick={() => setPage(current + 1)}>下一页</Button>
            </nav>
          )}
          <details className="tech">
            <summary>文件校验</summary>
            <p className="mono">SHA-256 {preview.file.sha256}</p>
            {audit && <p className="mono">{formatCount(audit.source_line_count)} 行 · 保留 {formatCount(audit.retained_body_characters)} 个正文字符</p>}
          </details>
          <div className="form-actions">
            <Button kind="primary" size="lg" disabled={Boolean(busy)} onClick={() => setStep(3)}>分章没问题，下一步</Button>
            <Button disabled={Boolean(busy)} onClick={() => void discard(false)}>重新选择文件</Button>
            <Button kind="text" disabled={Boolean(busy)} onClick={() => void discard(true)}>取消导入</Button>
          </div>
        </div>
      )}

      {preview && step === 3 && (
        <form className="import-step form" onSubmit={(event) => void commit(event)}>
          <p className="import-confirm">将把 <strong>{preview.file.name}</strong> 的 {preview.detected.chapter_count} 章创建为一部新作品。</p>
          <label className="field">
            <span className="field-label">书名<span className="field-req">必填</span></span>
            <input className="input-xl" name="title" required maxLength={80} defaultValue={defaultTitle} />
          </label>
          <label className="field"><span className="field-label">类型</span><input name="genre" maxLength={80} placeholder="例如：悬疑" /></label>
          <label className="field"><span className="field-label">简介</span><textarea name="summary" maxLength={500} rows={3} /></label>
          <div className="form-actions">
            <Button kind="primary" size="lg" type="submit" disabled={Boolean(busy)} busy={Boolean(busy)}>{busy || "导入并创建作品"}</Button>
            <Button disabled={Boolean(busy)} onClick={() => setStep(2)}>返回检查分章</Button>
            <Button kind="text" disabled={Boolean(busy)} onClick={() => void discard(true)}>取消导入</Button>
          </div>
        </form>
      )}
    </section>
  );
}
