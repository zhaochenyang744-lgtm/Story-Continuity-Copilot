"use client";

import { useEffect, useState } from "react";
import { request } from "../../api";
import type { ForeshadowSnapshot } from "../../model";
import { experienceSimulation } from "../env";
import { findingTone } from "../labels";
import { ContinueBand } from "../pages/home";
import { bareChapterTitle, Button, clip, formatCount, Menu, Num, pad2, SectionHead, Tag, writtenChars } from "../ui";
import type { PageProps } from "./frame";
import { FindingTag, findingHeadline, openIssues } from "./findings";
import { RouteLegend, StoryRoute, type RouteChapter } from "./story-route";

type TimelineRow = { chapter_id: string | null; chapter_number: number; title: string; draft: boolean; status: RouteChapter["status"] };
type CheckRun = { status: string; sample?: boolean; report: { chapters: { chapter_number: number; issues: { nature?: string; severity?: string }[] }[] } | null };

/** 概览: the title set very large with the work's figures, the continue band, the story route, then
    what is open in the draft and what comes next. */
export function OverviewPage({ p, open, go, notices }: PageProps) {
  const project = p.project!;
  const [timeline, setTimeline] = useState<TimelineRow[] | null>(null);
  const [threads, setThreads] = useState<ForeshadowSnapshot["records"]>([]);
  const [considering, setConsidering] = useState<Set<string>>(() => new Set());
  const [checkRuns, setCheckRuns] = useState<CheckRun[]>([]);
  useEffect(() => {
    let live = true;
    const base = `/projects/${project.id}`;
    request<{ chapters: TimelineRow[] }>(`${base}/chapter-timeline`).then((r) => { if (live) setTimeline(r.chapters); }).catch(() => { if (live) setTimeline([]); });
    request<ForeshadowSnapshot>(`${base}/foreshadows`).then((r) => { if (live) setThreads(r.records); }).catch(() => undefined);
    request<{ considering: { kind: string; plan_id: string }[] }>(`${base}/plan-states`).then((r) => { if (live) setConsidering(new Set(r.considering.map((item) => `${item.kind}:${item.plan_id}`))); }).catch(() => undefined);
    request<{ runs: CheckRun[] }>(`${base}/chapter-checks?limit=5`).then((r) => { if (live) setCheckRuns(r.runs); }).catch(() => undefined);
    return () => { live = false; };
  }, [project.id, project.source_revision, project.latest_run?.run_id]);

  const sample = Boolean(project.is_tutorial || project.data_origin === "demo_seed");
  const draftNumber = p.draft?.chapter_number ?? project.current_draft.chapter_number;
  const draftChars = writtenChars(p.draft?.body ?? "");
  const written = (timeline ?? []).filter((row) => !row.draft);
  const checked = written.filter((row) => row.status === "checked").length;
  const issues = openIssues(p.run?.issues, p.locallyResolvedIssueIds);
  // Findings from real chapter checks (not the sample preset), newest report per chapter.
  const chapterFindings = new Map<number, ("high" | "mid")[]>();
  for (const run of checkRuns) {
    if (run.sample || run.status !== "completed" || !run.report) continue;
    for (const chapter of run.report.chapters) {
      if (!chapterFindings.has(chapter.chapter_number))
        chapterFindings.set(chapter.chapter_number, chapter.issues.map((issue) => (issue.nature === "confirmed_conflict" || issue.severity === "high" ? "high" : "mid")));
    }
  }
  const openThreads = threads.filter((record) => !record.archived_at && record.planted && (record.status === "planted" || record.status === "developing"));
  const plans = (p.authorContext?.story_plans ?? []).filter((plan) => !plan.archived && plan.status !== "completed").map((plan) => ({ plan, weighing: considering.has(`story:${plan.id}`) }));
  const routePlans = plans.filter(({ plan }) => plan.target_chapter_number != null && plan.target_chapter_number >= draftNumber).map(({ plan, weighing }) => ({ id: plan.id, title: plan.title, chapter: plan.target_chapter_number!, considering: weighing }));
  const nextPlans = [...plans].sort((a, b) => (a.plan.target_chapter_number ?? 9_999) - (b.plan.target_chapter_number ?? 9_999) || a.plan.position - b.plan.position).slice(0, 5);
  const imported = project.data_origin === "user_import" && project.memory_initialization_status !== "completed";

  return (
    <section className="page overview">
      {notices}
      <header className="overview-hero">
        <div className="overview-hero-main">
          <p className="label overview-kicker">
            {sample && <span className="badge">示例作品</span>}
            {project.genre && <span>{project.genre}</span>}
            {project.genre && <span aria-hidden="true">/</span>}
            <span>{project.chapter_count ? `写到第 ${project.chapter_count} 章` : "还没有已写的章节"}</span>
            {project.status === "archived" && <span className="badge">已归档</span>}
          </p>
          <h1 className="overview-title">{project.title}</h1>
          {project.summary && <p className="overview-summary">{project.summary}</p>}
        </div>
        <div className="overview-hero-side">
          <div className="overview-menu">
            <Menu buttonLabel="更多：导出、编辑信息、归档" danger={!p.readOnly ? <button type="button" role="menuitem" className="danger" onClick={() => open("reset")}>重置作品</button> : undefined}>
              <button type="button" role="menuitem" onClick={() => open("export")}>导出作品</button>
              {!p.readOnly && !project.is_tutorial && <button type="button" role="menuitem" onClick={() => open("meta")}>编辑作品信息</button>}
              {!project.is_tutorial && !p.narrow && <button type="button" role="menuitem" onClick={() => open("archive")}>{project.status === "archived" ? "恢复作品" : "归档作品"}</button>}
            </Menu>
          </div>
          <dl className="overview-figures">
            <div>
              <dt className="sr-only">已写章节</dt>
              <dd><Num>{project.chapter_count}</Num></dd>
              <dd className="figure-label">章已写{timeline ? ` · ${checked} 章已检查` : ""}</dd>
            </div>
            <div>
              <dt className="sr-only">待看</dt>
              <dd><Num className="blue">{issues.length}</Num></dd>
              <dd className="figure-label">处待看</dd>
            </div>
            <div className="wide">
              <dt className="sr-only">字数</dt>
              <dd><Num>{formatCount(project.word_count ?? 0)}</Num></dd>
              <dd className="figure-label">字正文{draftChars ? ` · 另有草稿 ${formatCount(draftChars)} 字` : ""}</dd>
            </div>
          </dl>
        </div>
      </header>

      {imported && (
        <div className="note note-warn import-note">
          <span>{p.initialization?.status === "draft" ? "从正文整理出的事实在等你逐条确认；没确认的不会写进资料。" : "导入的正文已经可以检查。把事实整理进资料后，检查会更准。"}</span>
          {p.initialization?.status === "required" && <Button kind="primary" disabled={p.readOnly || Boolean(p.busy)} onClick={() => void p.startMemoryInitialization()}>整理事实</Button>}
          {p.initialization?.status === "draft" && <Button disabled={Boolean(p.busy)} onClick={() => go(`/projects/${project.id}/memory`)}>去确认</Button>}
          {experienceSimulation && <span className="small-note">隔离模拟环境：候选来自固定示例数据，不代表对任意正文的真实分析；不会调用真实模型。</span>}
        </div>
      )}

      <ContinueBand
        className="overview-band"
        number={draftNumber}
        label={p.readOnly ? "草稿 · 只读" : "继续写 · 草稿"}
        title={bareChapterTitle(p.draft?.title ?? "") || "这一章还没有标题"}
        meta={`${formatCount(draftChars)} 字 · ${project.latest_run ? `上次检查找到 ${p.run?.issues?.length ?? 0} 处${issues.length ? `，${issues.length} 处待看` : ""}` : "还没检查"}`}
        action={p.readOnly ? "查看草稿" : "打开草稿"}
        onClick={() => go(`/projects/${project.id}/workspace`)}
      />

      <section className="overview-route" aria-labelledby="route-title">
        <SectionHead id="route-title" title="故事航线" aside={<RouteLegend />} />
        {timeline === null ? <p className="loading">正在读取各章的情况…</p> : (
          <StoryRoute
            chapters={written.map((row) => ({ number: row.chapter_number, title: row.title, status: row.status, findings: chapterFindings.get(row.chapter_number) ?? [] }))}
            draft={{ number: draftNumber, title: p.draft?.title ?? "", findings: issues.map(findingTone) }}
            threads={openThreads.map((record) => ({ id: record.id, title: record.title, planted: record.planted!.chapter_number }))}
            plans={routePlans}
          />
        )}
      </section>

      <div className="overview-columns">
        <section aria-labelledby="overview-open">
          <SectionHead id="overview-open" title="草稿里待看" aside={<button type="button" className="link" onClick={() => go(`/projects/${project.id}/workspace`)}>去写作页处理</button>} />
          {issues.length ? (
            <ol className="rows">
              {issues.slice(0, 6).map((issue, index) => (
                <li key={issue.id}>
                  <button type="button" onClick={() => go(`/projects/${project.id}/workspace#issue-${issue.id}`)}>
                    <Num className="rows-num">{index + 1}</Num>
                    <span className="rows-copy"><strong>{findingHeadline(issue)}</strong>{issue.claim_text && <span>“{clip(issue.claim_text, 40)}”</span>}</span>
                    <FindingTag issue={issue} />
                  </button>
                </li>
              ))}
            </ol>
          ) : <p className="empty">{project.latest_run ? "上次检查之后，草稿里没有待看的地方。" : "这一章还没检查。写完一段后，在写作页点「检查这一章」。"}</p>}
          {issues.length > 0 && (p.dirty || p.run?.is_stale) && <p className="small-note">草稿在检查之后又改过，这些结果针对的是先前的正文。</p>}
          {issues.length > 6 && <p className="small-note">还有 {issues.length - 6} 处，在写作页查看。</p>}
        </section>
        <section aria-labelledby="overview-next">
          <SectionHead id="overview-next" title="接下来" aside={<button type="button" className="link" onClick={() => go(`/projects/${project.id}/plan`)}>全部计划</button>} />
          {nextPlans.length ? (
            <ul className="rows">
              {nextPlans.map(({ plan, weighing }) => (
                <li key={plan.id}>
                  <button type="button" onClick={() => go(`/projects/${project.id}/plan#plan-${plan.id}`)}>
                    <Num className={`rows-num wide${plan.target_chapter_number === draftNumber ? " blue" : ""}`}>{plan.target_chapter_number ? pad2(plan.target_chapter_number) : "—"}</Num>
                    <span className="rows-copy"><strong>{plan.title}</strong>{(plan.summary || plan.goal) && <span>{clip(plan.summary || plan.goal, 40)}</span>}</span>
                    {weighing ? <Tag tone="considering">考虑中</Tag> : <span className="decided">已定</span>}
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="empty">还没写下接下来的打算。在「计划」里记下要写的情节，它们会出现在航线的「接下来」一段。</p>}
        </section>
      </div>
    </section>
  );
}
