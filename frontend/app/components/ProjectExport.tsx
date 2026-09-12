"use client";

import { useEffect, useId, useRef, useState } from "react";
import styles from "./ProjectExport.module.css";

type ExportFormat = "txt" | "markdown" | "bundle";
const formats: { value: ExportFormat; label: string; extension: string }[] = [
  { value: "bundle", label: "完整资料包（ZIP）", extension: "zip" },
  { value: "txt", label: "正文（TXT）", extension: "txt" },
  { value: "markdown", label: "正文（Markdown）", extension: "md" },
];

export function ProjectExport({ projectId, disabled = false }: { projectId: string; disabled?: boolean }) {
  return <ProjectExportPanel key={projectId} projectId={projectId} disabled={disabled} />;
}

function ProjectExportPanel({ projectId, disabled }: { projectId: string; disabled: boolean }) {
  const [format, setFormat] = useState<ExportFormat>("bundle");
  const [includeDraft, setIncludeDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const selectId = useId();
  const controller = useRef<AbortController | null>(null);
  const activeProject = useRef(projectId);

  useEffect(() => {
    activeProject.current = projectId;
    return () => { activeProject.current = ""; controller.current?.abort(); };
  }, [projectId]);

  async function download() {
    if (busy || disabled) return;
    const project = projectId;
    const requestController = new AbortController();
    controller.current = requestController;
    setBusy(true);
    setMessage("");
    const timeout = window.setTimeout(() => requestController.abort(), 60_000);
    try {
      const params = new URLSearchParams({ format, include_draft: String(includeDraft) });
      const response = await fetch(`/api/projects/${encodeURIComponent(project)}/export?${params}`, {
        credentials: "same-origin", cache: "no-store", signal: requestController.signal,
      });
      if (!response.ok) {
        if (response.status === 401) throw new Error("登录已过期，请重新登录后导出。");
        if (response.status === 404) throw new Error("暂时无法访问这部作品，请刷新后重试。");
        if (response.status === 413) throw new Error("资料包较大，请先单独导出 TXT 或 Markdown 正文。");
        if (response.status === 409) throw new Error("草稿和入库章节编号重叠，请先关闭“包含草稿”导出正文。");
        throw new Error("暂时没能导出，请稍后重试。");
      }
      const blob = await response.blob();
      if (requestController.signal.aborted || activeProject.current !== project) return;
      const encodedName = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get("Content-Disposition") ?? "")?.[1];
      let filename = `story-export.${formats.find(item => item.value === format)?.extension}`;
      if (encodedName) {
        try { filename = decodeURIComponent(encodedName); } catch { /* Use safe fallback. */ }
      }
      filename = filename.replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, "-");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      setMessage("已生成导出文件，请在浏览器下载列表中查看。");
    } catch (cause) {
      if (activeProject.current !== project) return;
      setMessage((cause as Error).name === "AbortError" ? "导出等待超时，可以重试。" : (cause as Error).message);
    } finally {
      window.clearTimeout(timeout);
      if (activeProject.current === project) setBusy(false);
    }
  }

  return (
    <section aria-label="作品导出" className={styles.panel}>
      <h3>导出作品</h3>
      <p>正文按章节顺序导出。完整资料包还包括故事规划、人物、世界设定和已确认事实。</p>
      <label htmlFor={selectId}>导出格式</label>
      <select id={selectId} value={format} onChange={event => setFormat(event.target.value as ExportFormat)} disabled={busy || disabled}>
        {formats.map(item => <option key={item.value} value={item.value}>{item.label}</option>)}
      </select>
      <label className={styles.draft}>
        <input type="checkbox" checked={includeDraft} onChange={event => setIncludeDraft(event.target.checked)} disabled={busy || disabled} />
        包含当前已保存草稿（单独标注为未入库）
      </label>
      <p className="muted">如需导出正在编辑的内容，请先保存草稿。资料包会保留归档资料和原始正文格式。</p>
      <button type="button" className={styles.download} disabled={busy || disabled} onClick={() => void download()}>
        {busy ? "正在生成…" : "下载作品"}
      </button>
      <p role="status" aria-live="polite">{message}</p>
    </section>
  );
}
