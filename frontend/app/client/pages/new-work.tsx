"use client";

import { FormEvent, useState } from "react";
import { json } from "../../api";
import type { ProjectSummary } from "../../model";
import { Button, PageHead } from "../ui";

const genres = ["悬疑", "奇幻", "科幻", "言情", "历史", "现实", "其他"] as const;

/** 新建作品: one centred column. Only the title is required. */
export function NewWorkPage({ fail, go }: { fail: (cause: unknown) => void; go: (href: string) => void }) {
  const [genre, setGenre] = useState("");
  const [custom, setCustom] = useState("");
  const [summary, setSummary] = useState("");
  const [busy, setBusy] = useState(false);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setBusy(true);
    try {
      const data = await json<{ project: ProjectSummary }>("/projects", "POST", {
        title: String(form.get("title")),
        genre: genre === "其他" ? custom : genre,
        summary,
      });
      go(`/projects/${data.project.id}/workspace`);
    } catch (cause) { fail(cause); } finally { setBusy(false); }
  };
  return (
    <section className="page form-page">
      <PageHead title="新建作品" lede="写下书名就能开始。类型和简介以后也可以改。" />
      <form className="form" onSubmit={(event) => void submit(event)}>
        <label className="field">
          <span className="field-label">书名<span className="field-req">必填</span></span>
          <input className="input-xl" name="title" required maxLength={80} disabled={busy} autoComplete="off" placeholder="例如：潮汐之后" />
        </label>
        <fieldset className="field">
          <legend className="field-label">类型</legend>
          <div className="chips" role="radiogroup" aria-label="类型">
            {genres.map((item) => (
              <label key={item} className="chip chip-radio">
                <input className="sr-only" type="radio" name="genre-choice" value={item} checked={genre === item} onChange={() => setGenre(item)} disabled={busy} />
                {item}
              </label>
            ))}
          </div>
          {genre === "其他" && <input aria-label="其他类型" maxLength={80} placeholder="填写类型" value={custom} onChange={(event) => setCustom(event.target.value)} disabled={busy} />}
        </fieldset>
        <label className="field">
          <span className="field-label">简介<span className="field-count">{Array.from(summary).length} / 500</span></span>
          <textarea name="summary" maxLength={500} rows={4} value={summary} onChange={(event) => setSummary(event.target.value)} disabled={busy} placeholder="用一两句话说这部作品从哪里开始。" />
        </label>
        <div className="form-actions">
          <Button kind="primary" size="lg" type="submit" disabled={busy} busy={busy}>{busy ? "正在创建" : "创建并开始写第一章"}</Button>
          <Button kind="text" disabled={busy} onClick={() => go("/projects")}>取消</Button>
        </div>
      </form>
    </section>
  );
}
