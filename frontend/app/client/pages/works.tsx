"use client";

import { useEffect, useState } from "react";
import { request } from "../../api";
import type { ProjectSummary } from "../../model";
import { workStatusLabel } from "../labels";
import { Arrow, Button, Chips, formatCount, Menu, Num, PageHead, pad2, Tag } from "../ui";
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
  }, [fail]);
  useEffect(() => {
    let live = true;
    request<{ projects: ProjectSummary[] }>(`/projects?q=${encodeURIComponent(query)}${status ? `&status=${status}` : ""}${onlyOpen ? "&has_open_issues=true" : ""}&sort=${sort}`)
      .then((data) => { if (live) setRows(data.projects.filter((item) => !isSample(item))); })
      .catch((cause) => { if (live) fail(cause); });
    return () => { live = false; };
  }, [query, status, sort, onlyOpen, fail]);
  const filtered = Boolean(query || status || onlyOpen);
  const totalWords = (all ?? []).reduce((sum, item) => sum + (item.word_count ?? 0), 0);
  const active = (all ?? []).filter((item) => item.status === "active").length;
  const hasWorks = Boolean(all?.length);

  return (
    <section className="page works">
      <PageHead
        title="作品管理"
        lede={hasWorks ? "所有作品按最近修改排列。示例作品不在这里。" : "导入写好的稿子，或者从空白开始。"}
        aside={
          <div className="head-figures-actions">
            {hasWorks && (
              <dl className="figures">
                <div><dt className="sr-only">作品</dt><dd><Num><CountUp id="works:count" value={all!.length} /></Num></dd><dd className="figure-label">部作品</dd></div>
                <div><dt className="sr-only">进行中</dt><dd><Num><CountUp id="works:active" value={active} /></Num></dd><dd className="figure-label">进行中</dd></div>
                <div><dt className="sr-only">字数</dt><dd><Num><CountUp id="works:words" value={totalWords} /></Num></dd><dd className="figure-label">字</dd></div>
              </dl>
            )}
            <div className="actions">
              <Button size="lg" onClick={() => go("/projects/import")}>导入作品</Button>
              <Button kind="primary" size="lg" onClick={() => go("/projects/new")}>新建作品</Button>
            </div>
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
            items={[{ id: "", label: "未归档" }, { id: "active", label: "进行中" }, { id: "paused", label: "暂停" }, { id: "completed", label: "已完成" }, { id: "archived", label: "已归档" }]}
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
        <div className="start-cards works-empty">
          <button type="button" className="start-card start-card-raised" onClick={() => go("/projects/import")}>
            <Num>导入</Num><strong>导入已有作品</strong><span>Word、TXT、Markdown。按标题自动分章，确认后才创建作品。</span><span className="start-card-go blue">选择文件<Arrow size={16} /></span>
          </button>
          <button type="button" className="start-card" onClick={() => go("/projects/new")}>
            <Num>新建</Num><strong>从空白开始</strong><span>写下书名和一句话简介，就可以开始第一章。</span><span className="start-card-go">新建作品<Arrow size={16} /></span>
          </button>
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
                  </Menu>
                )}
              </span>
            </li>
          ))}
        </ol>
      ) : (
        <p className="empty">{filtered ? "没有符合条件的作品。换个条件试试。" : "没有未归档的作品。选「已归档」可以看到归档的作品。"}</p>
      )}
    </section>
  );
}
