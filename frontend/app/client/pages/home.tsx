"use client";

import { useEffect, useState } from "react";
import { request } from "../../api";
import type { Onboarding, Project, ProjectSummary, User } from "../../model";
import { Arrow, bareChapterTitle, Button, type CheckUsage, formatCount, Num, pad2, SectionHead, Tag } from "../ui";
import { CountUp } from "../motion";

type Home = {
  continue_work?: { project_id: string; project_title: string; draft_title: string; chapter_number?: number; draft_chars?: number; open_issue_count?: number } | null;
};

const isSample = (project: Pick<ProjectSummary, "data_origin">) => project.data_origin === "demo_seed" || project.data_origin === "tutorial_seed";

/** Open findings in a work, or whether it has been checked at all. */
export function WorkCheckTag({ project }: { project: Pick<ProjectSummary, "open_issue_count" | "continuity_status"> }) {
  if (project.open_issue_count) return <Tag tone="high">{project.open_issue_count} 处待看</Tag>;
  if (project.continuity_status === "checked_clear") return <Tag>已检查 · 无待看</Tag>;
  return <Tag tone="gap">还没检查</Tag>;
}

/** The black band used on 首页 and 概览: chapter number, what is being written, one blue action. */
export function ContinueBand({ number, label, title, meta, action, onClick, className = "" }: { number?: number; label: string; title: string; meta: string; action: string; onClick: () => void; className?: string }) {
  return (
    <button type="button" className={`band${className ? ` ${className}` : ""}`} onClick={onClick}>
      {number ? <Num className="band-num">{number}</Num> : null}
      <span className="band-copy">
        <span className="band-label">{label}</span>
        <span className="band-title">{title}</span>
      </span>
      <span className="band-meta">{meta}</span>
      <span className="band-go">{action}<Arrow /></span>
    </button>
  );
}

export function HomePage({ user, onboarding, usage, fail, go, reopenTutorial }: {
  user: User;
  onboarding: Onboarding | null;
  usage: CheckUsage | null;
  fail: (cause: unknown) => void;
  go: (href: string) => void;
  reopenTutorial: () => void;
}) {
  const [home, setHome] = useState<Home | null>(null);
  const [projects, setProjects] = useState<ProjectSummary[] | null>(null);
  const [sample, setSample] = useState<Project | null>(null);
  useEffect(() => {
    let live = true;
    Promise.all([request<Home>("/home"), request<{ projects: ProjectSummary[] }>("/projects?q=&sort=updated_desc")])
      .then(([nextHome, list]) => { if (live) { setHome(nextHome); setProjects(list.projects); } })
      .catch((cause) => { if (live) fail(cause); });
    return () => { live = false; };
  }, [fail]);
  const sampleId = onboarding?.tutorial?.project_id ?? (projects ?? []).find(isSample)?.id ?? null;
  useEffect(() => {
    if (!sampleId) return;
    let live = true;
    request<Project>(`/projects/${sampleId}`).then((next) => { if (live) setSample(next); }).catch(() => undefined);
    return () => { live = false; };
  }, [sampleId]);
  const works = (projects ?? []).filter((item) => !isSample(item));
  const continuing = home?.continue_work ?? null;
  const visitor = user.account_type === "visitor";
  const firstRun = Boolean(onboarding?.show_first_run && onboarding.tutorial);

  return (
    <section className="page home">
      <header className="home-hero">
        <p className="label">{works.length ? "欢迎回来" : visitor ? "访客空间 · 24 小时" : "你好"}</p>
        <h1>{works.length || continuing ? "继续你的故事" : "从第一章开始"}</h1>
      </header>

      {continuing && (
        <ContinueBand
          number={continuing.chapter_number}
          label={`上次停在 · 《${continuing.project_title}》`}
          title={`${continuing.chapter_number ? `第 ${continuing.chapter_number} 章 · ` : ""}${bareChapterTitle(continuing.draft_title) || "未命名草稿"}`}
          meta={`草稿 ${formatCount(continuing.draft_chars ?? 0)} 字${continuing.open_issue_count ? ` · ${continuing.open_issue_count} 处待看` : ""}`}
          action="继续写"
          onClick={() => go(`/projects/${continuing.project_id}/workspace`)}
        />
      )}

      <div className="home-columns">
        <section className="home-works" aria-labelledby="home-works-title">
          <SectionHead id="home-works-title" title="你的作品" aside={works.length > 0 && <button type="button" className="link" onClick={() => go("/projects")}>作品管理</button>} />
          {projects === null ? (
            <p className="loading">正在读取…</p>
          ) : works.length ? (
            <ol className="work-list">
              {works.slice(0, 5).map((work) => (
                <li key={work.id}>
                  <button type="button" onClick={() => go(`/projects/${work.id}/overview`)}>
                    <span className="work-list-main">
                      <span className="work-list-title">{work.title}</span>
                      <span className="label">{[work.genre, `${work.chapter_count ?? 0} 章`, `${formatCount(work.word_count ?? 0)} 字`].filter(Boolean).join(" · ")}</span>
                    </span>
                    {work.current_draft && <span className="work-list-draft"><Num>{pad2(work.current_draft.chapter_number)}</Num><span className="label">在写</span></span>}
                    <WorkCheckTag project={work} />
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <>
              <p className="home-note">还没有自己的作品。把写好的稿子导进来，或者从第一章开始。</p>
              <div className="start-cards">
                <button type="button" className="start-card start-card-raised" onClick={() => go("/projects/import")}>
                  <Num>导入</Num>
                  <strong>导入已有作品</strong>
                  <span>Word、TXT、Markdown，最多 {visitor ? "1 万" : "35 万"}字。按标题自动分章。</span>
                  <span className="start-card-go blue">选择文件<Arrow size={16} /></span>
                </button>
                <button type="button" className="start-card" onClick={() => go("/projects/new")}>
                  <Num>新建</Num>
                  <strong>从空白开始</strong>
                  <span>写下书名和一句话简介，就可以开始第一章。</span>
                  <span className="start-card-go">新建作品<Arrow size={16} /></span>
                </button>
              </div>
            </>
          )}
        </section>

        {sampleId && (
          <section className="home-sample" aria-labelledby="home-sample-title">
            <SectionHead id="home-sample-title" title="示例作品" />
            <button type="button" className="sample-card" onClick={() => go(`/projects/${sampleId}/overview`)}>
              <span className="label">{sample ? [sample.genre, `${sample.chapter_count} 章`, `${formatCount(sample.word_count ?? 0)} 字`].filter(Boolean).join(" · ") : "示例"}</span>
              <span className="sample-card-title">{sample?.title ?? onboarding?.tutorial?.title ?? "示例作品"}</span>
              {sample?.summary && <span className="sample-card-summary">{sample.summary}</span>}
              {sample && <span className="sample-card-tags"><WorkCheckTag project={sample} /></span>}
            </button>
            {firstRun ? (
              <Button kind="primary" className="home-sample-action" onClick={() => go(`/projects/${sampleId}/overview`)}>开始导览</Button>
            ) : !visitor && onboarding?.tutorial ? (
              <button type="button" className="link home-sample-action" onClick={reopenTutorial}>重新看一遍导览</button>
            ) : null}
            <p className="small-note">示例作品不占你的作品数，也不计入额度。</p>
          </section>
        )}
      </div>

      {usage && (
        <section className="quota" aria-label="检查额度">
          <div className="quota-group">
            {usage.account_type === "visitor"
              ? <p className="quota-figure"><Num><CountUp id="home:quota" value={usage.checks_remaining} /></Num><span> / {usage.checks_limit} 次</span></p>
              : <p className="quota-figure"><Num><CountUp id="home:quota" value={usage.check_chars_remaining} /></Num><span> / {formatCount(usage.check_chars_limit)} 字</span></p>}
            <p className="figure-label">{usage.account_type === "visitor" ? "访客 · 24 小时内还可检查" : "24 小时内还可检查"}</p>
          </div>
          <div className="quota-bar">
            <div className="meter"><span style={{ width: `${usage.account_type === "visitor" ? (usage.checks_limit ? (usage.checks_remaining / usage.checks_limit) * 100 : 0) : usage.check_chars_limit ? (usage.check_chars_remaining / usage.check_chars_limit) * 100 : 0}%` }} /></div>
            <p>
              {usage.account_type === "visitor"
                ? <><span>每次最多 {formatCount(usage.check_chars_per_check)} 字</span><span>注册后可以检查更长的章节</span></>
                : <><span>按每章 2,500 字算，现在还能检查约 {Math.floor(usage.check_chars_remaining / 2500)} 章</span><span>用掉的额度 24 小时后陆续返还</span></>}
            </p>
          </div>
        </section>
      )}
    </section>
  );
}
