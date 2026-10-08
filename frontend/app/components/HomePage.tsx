"use client";

import { useEffect, useState } from "react";
import { request } from "../api";
import type { Onboarding, Project, ProjectSummary, User } from "../model";
import { bareChapterTitle, Button, type CheckUsage, formatCount, pad2 } from "./ui";

export type Home = {
  continue_work?: {
    project_id: string;
    project_title: string;
    draft_id: string;
    draft_title: string;
    draft_revision: number;
    chapter_number?: number;
    draft_chars?: number;
    open_issue_count?: number;
    next_action: string;
  } | null;
  recent_projects: { project_id: string; title: string; status: ProjectSummary["status"]; updated_at: string }[];
  pending_continuity: { project_id: string; title: string; high: number; medium: number; low: number; continuity_status: "unchecked" | "checked_clear" | "pending" }[];
};

const isSample = (project: Pick<ProjectSummary, "data_origin">) => project.data_origin === "demo_seed" || project.data_origin === "tutorial_seed";

function Arrow({ size = 18 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 9h12M10 4l5 5-5 5" />
    </svg>
  );
}

/** Findings still open in a work: "4 处待看", or whether it has been checked at all. */
export function WorkCheckTag({ project }: { project: Pick<ProjectSummary, "open_issue_count" | "continuity_status"> }) {
  if (project.open_issue_count) return <span className="tag high">{project.open_issue_count} 处待看</span>;
  if (project.continuity_status === "checked_clear") return <span className="tag">已检查 · 无待看</span>;
  return <span className="tag gap">还没检查</span>;
}

export function HomePage({
  user,
  home,
  onboarding,
  projects,
  usage,
  open,
  go,
  reopenTutorial,
}: {
  user: User;
  home: Home | null;
  onboarding: Onboarding | null;
  projects: ProjectSummary[] | null;
  usage: CheckUsage | null;
  open: (id: string, tab?: string) => void;
  go: (href: string) => void;
  reopenTutorial: () => void;
}) {
  const works = (projects ?? []).filter((item) => !isSample(item) && item.status !== "archived");
  const sampleId = onboarding?.tutorial?.project_id ?? (projects ?? []).find(isSample)?.id ?? null;
  const [sample, setSample] = useState<Project | null>(null);
  useEffect(() => {
    if (!sampleId) return;
    let live = true;
    request<Project>(`/projects/${sampleId}`).then((next) => { if (live) setSample(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [sampleId]);
  const continuing = home?.continue_work ?? null;
  const visitor = user.account_type === "visitor";
  const firstRun = Boolean(onboarding?.show_first_run && onboarding.tutorial);
  const importLimit = visitor ? "1 万" : "35 万";

  return (
    <section className="home-page">
      <header className="home-hero">
        <p className="label">{works.length ? "欢迎回来" : visitor ? "访客空间" : "你好"}</p>
        <h1>{works.length || continuing ? "继续你的故事" : "从第一章开始"}</h1>
      </header>

      {continuing && (
        <button type="button" className="continue-band" onClick={() => open(continuing.project_id, "workspace")}>
          {continuing.chapter_number ? <span className="num continue-band-num">{continuing.chapter_number}</span> : null}
          <span className="continue-band-copy">
            <span className="continue-band-label">上次停在 · 《{continuing.project_title}》</span>
            <span className="continue-band-title">{continuing.chapter_number ? `第 ${continuing.chapter_number} 章 · ` : ""}{bareChapterTitle(continuing.draft_title) || "未命名草稿"}</span>
          </span>
          <span className="continue-band-meta">
            草稿 {formatCount(continuing.draft_chars ?? 0)} 字{continuing.open_issue_count ? ` · ${continuing.open_issue_count} 处待看` : ""}
          </span>
          <span className="continue-band-go">继续写<Arrow /></span>
        </button>
      )}

      <div className="home-columns">
        <section className="home-works" aria-labelledby="home-works-title">
          <div className="section-head">
            <h2 id="home-works-title">你的作品</h2>
            {works.length > 0 && <button type="button" className="section-link" onClick={() => go("/projects")}>作品管理</button>}
          </div>
          {projects === null ? (
            <p className="home-note label">正在读取…</p>
          ) : works.length ? (
            <ol className="home-work-list">
              {works.slice(0, 5).map((work) => (
                <li key={work.id}>
                  <button type="button" onClick={() => open(work.id)}>
                    <span className="home-work-main">
                      <span className="home-work-title">{work.title}</span>
                      <span className="label">{[work.genre, `${work.chapter_count ?? 0} 章`, `${formatCount(work.word_count ?? 0)} 字`].filter(Boolean).join(" · ")}</span>
                    </span>
                    {work.current_draft && <span className="home-work-draft"><span className="num">{pad2(work.current_draft.chapter_number)}</span><span className="label">在写</span></span>}
                    <WorkCheckTag project={work} />
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <>
              <p className="home-note">还没有自己的作品。把写好的稿子导进来，或者从第一章开始。</p>
              <div className="home-start">
                <button type="button" className="home-start-card primary" onClick={() => go("/projects/import")}>
                  <span className="num">导入</span>
                  <strong>导入已有作品</strong>
                  <span>Word、TXT、Markdown，最多 {importLimit}字。按标题自动分章。</span>
                  <span className="home-start-go">选择文件<Arrow size={16} /></span>
                </button>
                <button type="button" className="home-start-card" onClick={() => go("/projects/new")}>
                  <span className="num">新建</span>
                  <strong>从空白开始</strong>
                  <span>写下书名和一句话简介，就可以开始第一章。</span>
                  <span className="home-start-go">新建作品<Arrow size={16} /></span>
                </button>
              </div>
            </>
          )}
        </section>

        {sampleId && (
          <section className="home-sample" aria-labelledby="home-sample-title">
            <div className="section-head">
              <h2 id="home-sample-title">示例作品</h2>
            </div>
            <button type="button" className="home-sample-card" onClick={() => open(sampleId)}>
              <span className="label">{sample ? [sample.genre, `${sample.chapter_count} 章`, `${formatCount(sample.word_count ?? 0)} 字`].filter(Boolean).join(" · ") : "示例"}</span>
              <span className="home-sample-title">{sample?.title ?? onboarding?.tutorial?.title ?? "示例作品"}</span>
              {sample?.summary && <span className="home-sample-summary">{sample.summary}</span>}
              {sample && <span className="home-sample-tags"><WorkCheckTag project={sample} /></span>}
            </button>
            {firstRun ? (
              <div className="home-sample-actions">
                <Button className="primary" onClick={() => open(sampleId)}>开始导览</Button>
              </div>
            ) : !visitor && onboarding?.tutorial ? (
              <button type="button" className="section-link home-sample-tour" onClick={reopenTutorial}>重新看一遍导览</button>
            ) : null}
            <p className="home-note small">示例作品不占你的作品数，也不计入额度。</p>
          </section>
        )}
      </div>

      {usage && (
        <section className="home-quota" aria-label="检查额度">
          {usage.account_type === "visitor" ? (
            <>
              <div>
                <p className="label">访客 · 24 小时内可检查</p>
                <p className="num home-quota-figure">{usage.checks_remaining}<span> / {usage.checks_limit} 次</span></p>
              </div>
              <div className="home-quota-bar">
                <div className="meter"><span style={{ width: `${usage.checks_limit ? (usage.checks_remaining / usage.checks_limit) * 100 : 0}%` }} /></div>
                <p><span>每次最多 {formatCount(usage.check_chars_per_check)} 字</span><span>注册后可以检查更长的章节</span></p>
              </div>
            </>
          ) : (
            <>
              <div>
                <p className="label">24 小时内可检查</p>
                <p className="num home-quota-figure">{formatCount(usage.check_chars_remaining)}<span> / {formatCount(usage.check_chars_limit)} 字</span></p>
              </div>
              <div className="home-quota-bar">
                <div className="meter"><span style={{ width: `${usage.check_chars_limit ? (usage.check_chars_remaining / usage.check_chars_limit) * 100 : 0}%` }} /></div>
                <p><span>按每章 2,500 字算，现在还能检查约 {Math.floor(usage.check_chars_remaining / 2500)} 章</span><span>用掉的额度 24 小时后陆续返还</span></p>
              </div>
            </>
          )}
        </section>
      )}
    </section>
  );
}
