"use client";

import { useEffect, useState } from "react";
import { json, request } from "../../api";
import type { ProjectSummary } from "../../model";
import { workStatusLabel } from "../labels";
import { Button, Chips, Dialog, fitVars, formatCount, Menu, Num, PageHead, pad2, Tag } from "../ui";
import { CountUp } from "../motion";
import { WorkCheckTag } from "./home";

type StatusFilter = "" | "active" | "paused" | "completed" | "archived";
const isSample = (project: Pick<ProjectSummary, "data_origin">) => project.data_origin === "demo_seed" || project.data_origin === "tutorial_seed";

/** 作品管理: every work as one numbered row; filters apply as you type. */
export function WorksPage({ fail, go }: { fail: (cause: unknown) => void; go: (href: string) => void }) {
  const [q, setQ] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState<StatusFilter>("");
  const [sort, setSort] = useState("updated_desc");
  const [onlyOpen, setOnlyOpen] = useState(false);
  const [rows, setRows] = useState<ProjectSummary[] | null>(null);
  const [all, setAll] = useState<ProjectSummary[] | null>(null);
  const [reload, setReload] = useState(0);
  const [manage, setManage] = useState<{ kind: "rename" | "archive"; work: ProjectSummary } | null>(null);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    const timer = window.setTimeout(() => setQuery(q.trim()), 250);
    return () => window.clearTimeout(timer);
  }, [q]);
  useEffect(() => {
    let live = true;
    Promise.all([request<{ projects: ProjectSummary[] }>("/projects?q=&sort=updated_desc"), request<{ projects: ProjectSummary[] }>("/projects?q=&status=archived&sort=updated_desc")])
      .then(([current, archived]) => { if (live) setAll([...current.projects, ...archived.projects].filter((item) => !isSample(item))); })
      .catch((cause) => { if (live) fail(cause); });
    return () => { live = false; };
  }, [fail, reload]);
  useEffect(() => {
    let live = true;
    request<{ projects: ProjectSummary[] }>(`/projects?q=${encodeURIComponent(query)}${status ? `&status=${status}` : ""}${onlyOpen ? "&has_open_issues=true" : ""}&sort=${sort}`)
      .then((data) => { if (live) setRows(data.projects.filter((item) => !isSample(item))); })
      .catch((cause) => { if (live) fail(cause); });
    return () => { live = false; };
  }, [query, status, sort, onlyOpen, fail, reload]);
  const filtered = Boolean(query || status || onlyOpen);
  const totalWords = (all ?? []).filter((item) => item.status !== "archived").reduce((sum, item) => sum + (item.word_count ?? 0), 0);
  // Like the list's default view, the count leaves archived works out.
  const kept = (all ?? []).filter((item) => item.status !== "archived");
  const active = kept.filter((item) => item.status === "active").length;
  const hasWorks = Boolean(all?.length);

  return (
    <section className="page works">
      <PageHead
        title="作品管理"
        lede={hasWorks ? "所有作品按最近修改排列。示例作品不在这里。" : "导入写好的稿子，或者从空白开始。"}
        aside={
          <div className="head-figures-actions">
            {hasWorks && (
              <dl className="figures" style={fitVars(formatCount(kept.length), formatCount(active), formatCount(totalWords))}>
                <div><dt className="sr-only">作品</dt><dd><Num><CountUp id="works:count" value={kept.length} /></Num></dd><dd className="figure-label">部作品</dd></div>
                <div><dt className="sr-only">进行中</dt><dd><Num><CountUp id="works:active" value={active} /></Num></dd><dd className="figure-label">进行中</dd></div>
                <div><dt className="sr-only">字数</dt><dd><Num><CountUp id="works:words" value={totalWords} /></Num></dd><dd className="figure-label">字</dd></div>
              </dl>
            )}
            {hasWorks && (
              <div className="actions">
                <Button kind="primary" onClick={() => go("/projects/import")}>导入作品</Button>
                <Button onClick={() => go("/projects/new")}>新建作品</Button>
              </div>
            )}
          </div>
        }
      />
      {hasWorks && (
        <div className="works-filters">
          <label className="search">
            <span className="sr-only">搜索作品</span>
            <input value={q} onChange={(event) => setQ(event.target.value)} placeholder="搜索书名或简介" />
          </label>
          <Chips<StatusFilter>
            label="作品状态"
            value={status}
            onChange={setStatus}
            items={[{ id: "", label: "未归档" }, { id: "active", label: "进行中" }, { id: "paused", label: "已暂停" }, { id: "completed", label: "已完成" }, { id: "archived", label: "已归档" }]}
          />
          <button type="button" className="chip" aria-pressed={onlyOpen} onClick={() => setOnlyOpen((value) => !value)}>只看有待看的</button>
          <label className="sort">
            <span className="sr-only">排序</span>
            <select value={sort} onChange={(event) => setSort(event.target.value)}>
              <option value="updated_desc">最近修改</option>
              <option value="title_asc">书名</option>
            </select>
          </label>
        </div>
      )}
      {rows === null || all === null ? (
        <p className="loading">正在读取…</p>
      ) : !hasWorks ? (
        <div className="works-empty">
          <section className="works-empty-card" aria-label="导入已有作品">
            <h2>导入已有的稿子</h2>
            <p>Word、TXT、Markdown 都行，按标题自动分章，确认后才创建作品。</p>
            <Button kind="primary" onClick={() => go("/projects/import")}>选择文件</Button>
          </section>
          <section className="works-empty-card" aria-label="新建作品">
            <h2>从空白开始</h2>
            <p>写下书名和一句话简介，就可以开始第一章。</p>
            <Button onClick={() => go("/projects/new")}>新建作品</Button>
          </section>
        </div>
      ) : rows.length ? (
        <ol className="works-list">
          {rows.map((work, index) => (
            <li key={work.id} className={work.status === "archived" ? "archived" : undefined}>
              <Num className="works-index">{pad2(index + 1)}</Num>
              <button type="button" className="works-main" onClick={() => go(`/projects/${work.id}/overview`)}>
                <span className="works-title">{work.title}</span>
                <span className="works-summary">{work.summary || "没有简介"}</span>
                <span className="label">{[work.genre, `${work.chapter_count ?? 0} 章`, `${formatCount(work.word_count ?? 0)} 字`].filter(Boolean).join(" · ")}</span>
              </button>
              <span className="works-state">
                {work.status !== "active" && <Tag tone={work.status === "archived" ? "gap" : "line"}>{workStatusLabel(work.status)}</Tag>}
                <WorkCheckTag project={work} />
              </span>
              <span className="works-draft">{work.current_draft ? <><Num>{pad2(work.current_draft.chapter_number)}</Num><span className="label">在写</span></> : null}</span>
              <span className="works-actions">
                <Button kind="small" onClick={() => go(`/projects/${work.id}/${work.current_draft && work.status !== "archived" ? "workspace" : "overview"}`)}>{work.status === "archived" ? "查看" : "继续写"}</Button>
                {work.status !== "archived" && (
                  <Menu label="…" buttonLabel={`更多：${work.title}`}>
                    <button type="button" role="menuitem" onClick={() => go(`/projects/${work.id}/sources#append`)}>追加章节</button>
                    <button type="button" role="menuitem" onClick={() => go(`/projects/${work.id}/overview`)}>打开概览</button>
                    <button type="button" role="menuitem" onClick={() => setManage({ kind: "rename", work })}>重命名</button>
                    <button type="button" role="menuitem" className="danger" onClick={() => setManage({ kind: "archive", work })}>归档作品</button>
                  </Menu>
                )}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty">{filtered ? "没有符合条件的作品。换个条件试试。" : "没有未归档的作品。选「已归档」可以看到归档的作品。"}</p>
      )}
      {manage && <ManageDialog key={manage.kind + manage.work.id} manage={manage} saving={saving} close={() => setManage(null)} save={async (payload) => {
        setSaving(true);
        try {
          // The list does not always carry the revision the server wants for a change; the work itself does.
          const revision = typeof manage.work.metadata_revision === "number" ? manage.work.metadata_revision : (await request<{ project: ProjectSummary } | ProjectSummary>(`/projects/${manage.work.id}`) as { metadata_revision?: number }).metadata_revision;
          await json(`/projects/${manage.work.id}`, "PATCH", { base_metadata_revision: revision, ...payload });
          setManage(null);
          setReload((value) => value + 1);
        } catch (cause) { fail(cause); } finally { setSaving(false); }
      }} />}
    </section>
  );
}

/** 重命名 and 归档 from the list itself: the same changes as the work's own page, without going there first. */
function ManageDialog({ manage, saving, close, save }: { manage: { kind: "rename" | "archive"; work: ProjectSummary }; saving: boolean; close: () => void; save: (payload: Record<string, unknown>) => Promise<void> }) {
  const { work } = manage;
  const [title, setTitle] = useState(work.title);
  if (manage.kind === "rename") {
    return (
      <Dialog title="重命名作品" close={close}>
        <form className="form-inner" onSubmit={(event) => { event.preventDefault(); if (title.trim()) void save({ title: title.trim() }); }}>
          <label className="field"><span className="field-label">书名</span><input value={title} onChange={(event) => setTitle(event.target.value)} required maxLength={120} autoFocus /></label>
          <div className="dialog-actions">
            <Button kind="primary" type="submit" disabled={saving || !title.trim() || title.trim() === work.title}>保存</Button>
            <Button kind="text" onClick={close}>取消</Button>
          </div>
        </form>
      </Dialog>
    );
  }
  return (
    <Dialog title="归档作品" close={close}>
      <p>{`归档后《${work.title}》只能浏览，不能写入；不会删除。随时可以恢复。`}</p>
      <div className="dialog-actions">
        <Button kind="destroy" disabled={saving} onClick={() => void save({ status: "archived", confirm_archive: true })}>归档</Button>
        <Button kind="text" onClick={close}>取消</Button>
      </div>
    </Dialog>
  );
}
