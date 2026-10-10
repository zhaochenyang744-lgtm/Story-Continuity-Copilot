"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "../ui";

type ExportFormat = "txt" | "markdown" | "bundle";
const formats: { value: ExportFormat; label: string; note: string; extension: string }[] = [
  { value: "bundle", label: "完整资料包", note: "ZIP：正文、计划、人物、设定和已确认的事实", extension: "zip" },
  { value: "txt", label: "正文 TXT", note: "按章节顺序的纯文本", extension: "txt" },
  { value: "markdown", label: "正文 Markdown", note: "保留标题和格式标记", extension: "md" },
];

export function ExportPanel({ projectId }: { projectId: string }) {
  const [format, setFormat] = useState<ExportFormat>("bundle");
  const [includeDraft, setIncludeDraft] = useState(false);
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const controller = useRef<AbortController | null>(null);
  const active = useRef(projectId);
  useEffect(() => {
    active.current = projectId;
    return () => { active.current = ""; controller.current?.abort(); };
  }, [projectId]);
  const download = async () => {
    if (busy) return;
    const project = projectId;
    const request = new AbortController();
    controller.current = request;
    setBusy(true);
    setMessage("");
    const timeout = window.setTimeout(() => request.abort(), 60_000);
    try {
      const params = new URLSearchParams({ format, include_draft: String(includeDraft) });
      const response = await fetch(`/api/projects/${encodeURIComponent(project)}/export?${params}`, { credentials: "same-origin", cache: "no-store", signal: request.signal });
      if (!response.ok) {
        if (response.status === 401) throw new Error("登录已过期，请重新登录后导出。");
        if (response.status === 404) throw new Error("暂时访问不到这部作品，请刷新后重试。");
        if (response.status === 413) throw new Error("资料包太大，请先单独导出 TXT 或 Markdown 正文。");
        if (response.status === 409) throw new Error("草稿和已写章节的章节号重复了，请先取消“包含草稿”再导出。");
        throw new Error("暂时没能导出，请稍后重试。");
      }
      const blob = await response.blob();
      if (request.signal.aborted || active.current !== project) return;
      const encoded = /filename\*=UTF-8''([^;]+)/i.exec(response.headers.get("Content-Disposition") ?? "")?.[1];
      let filename = `story-export.${formats.find((item) => item.value === format)?.extension}`;
      if (encoded) { try { filename = decodeURIComponent(encoded); } catch { /* keep the fallback */ } }
      filename = filename.replace(/[<>:"/\\|?*\u0000-\u001f\u007f]/g, "-");
      const url = URL.createObjectURL(blob);
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
      setMessage("文件已生成，看一下浏览器的下载列表。");
    } catch (cause) {
      if (active.current !== project) return;
      setMessage((cause as Error).name === "AbortError" ? "等太久了，可以再试一次。" : (cause as Error).message);
    } finally {
      window.clearTimeout(timeout);
      if (active.current === project) setBusy(false);
    }
  };
  return (
    <div className="export">
      <fieldset className="choice-list">
        <legend className="sr-only">导出格式</legend>
        {formats.map((item) => (
          <label key={item.value} className="choice">
            <input type="radio" name="export-format" value={item.value} checked={format === item.value} onChange={() => setFormat(item.value)} disabled={busy} />
            <span><strong>{item.label}</strong><small>{item.note}</small></span>
          </label>
        ))}
      </fieldset>
      <label className="check"><input type="checkbox" checked={includeDraft} onChange={(event) => setIncludeDraft(event.target.checked)} disabled={busy} />包含已保存的草稿（会标注为草稿）</label>
      <p className="small-note">正在编辑的内容请先保存。</p>
      <div className="dialog-actions">
        <Button kind="primary" disabled={busy} busy={busy} onClick={() => void download()}>{busy ? "正在生成…" : "下载"}</Button>
      </div>
      <p className="export-message" role="status" aria-live="polite">{message}</p>
    </div>
  );
}
