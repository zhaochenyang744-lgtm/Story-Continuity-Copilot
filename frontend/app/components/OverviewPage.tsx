"use client";

import { ReactNode, useEffect, useState } from "react";
import { request } from "../api";
import type { AuthorContext, Draft, ForeshadowSnapshot, Issue, Project } from "../model";
import { findingTone, RouteLegend, StoryRoute, type RouteChapter } from "./StoryRoute";
import { bareChapterTitle, formatCount, MoreMenu, pad2 } from "./ui";

type TimelineRow = { chapter_id: string | null; chapter_number: number; title: string; draft: boolean; status: RouteChapter["status"]; checked_at: string | null };
type CheckReport = { chapters: { chapter_number: number; issues: { nature?: string; severity?: string }[] }[] };
type CheckRun = { run_id: string; status: string; sample?: boolean; report: CheckReport | null };

const toneTag: Record<ReturnType<typeof findingTone>, [string, string]> = {
  high: ["tag high", "确定矛盾"],
  mid: ["tag mid", "可能矛盾"],
  gap: ["tag gap", "证据不足"],
  state: ["tag state", "状态更新"],
};
const severityShort = { high: "高", medium: "中", low: "低" } as const;

/** One line for a finding: the first sentence of the explanation, kept short. */
export const findingHeadline = (issue: Pick<Issue, "explanation" | "claim_text">) => {
  const text = (issue.explanation || issue.claim_text || "").trim();
  const first = text.split(/(?<=[。！？])/)[0] ?? text;
  return first.length > 34 ? `${first.slice(0, 33)}…` : first;
};

export function FindingTag({ issue, withLevel = true }: { issue: Pick<Issue, "nature" | "severity">; withLevel?: boolean }) {
  const tone = findingTone(issue);
  const [className, label] = toneTag[tone];
  return <span className={className}>{label}{withLevel && tone !== "state" ? ` · ${severityShort[issue.severity]}` : ""}</span>;
}

export function OverviewPage({
  project,
  draft,
  openIssues,
  runOutdated,
  authorContext,
  readOnly,
  notices,
  menu,
  go,
}: {
  project: Project;
  draft: Draft | null;
  openIssues: Issue[];
  runOutdated: boolean;
  authorContext: AuthorContext | null;
  readOnly: boolean;
  notices: ReactNode;
  menu: ReactNode;
  go: (href: string) => void;
}) {
  const [timeline, setTimeline] = useState<TimelineRow[] | null>(null);
  const [threads, setThreads] = useState<ForeshadowSnapshot["records"]>([]);
  const [considering, setConsidering] = useState<Set<string>>(() => new Set());
  const [checkRuns, setCheckRuns] = useState<CheckRun[]>([]);
  useEffect(() => {
    let live = true;
    const base = `/projects/${project.id}`;
    request<{ chapters: TimelineRow[] }>(`${base}/chapter-timeline`).then((result) => { if (live) setTimeline(result.chapters); }).catch(() => { if (live) setTimeline([]); });
    request<ForeshadowSnapshot>(`${base}/foreshadows`).then((result) => { if (live) setThreads(result.records); }).catch(() => undefined);
    request<{ considering: { kind: string; plan_id: string }[] }>(`${base}/plan-states`).then((result) => { if (live) setConsidering(new Set(result.considering.map((item) => `${item.kind}:${item.plan_id}`))); }).catch(() => undefined);
    request<{ runs: CheckRun[] }>(`${base}/chapter-checks?limit=5`).then((result) => { if (live) setCheckRuns(result.runs); }).catch(() => undefined);
    return () => { live = false; };
  }, [project.id, project.source_revision, project.latest_run?.run_id]);

  const sample = Boolean(project.is_tutorial || project.data_origin === "demo_seed");
  const draftNumber = draft?.chapter_number ?? project.current_draft.chapter_number;
  const draftChars = (draft?.body ?? "").replace(/\s+/g, "").length;
  const written = (timeline ?? []).filter((row) => !row.draft);
  const checkedCount = written.filter((row) => row.status === "checked").length;
  // Findings from real chapter checks (not the sample preset), newest report per chapter.
  const chapterFindings = new Map<number, ("high" | "mid")[]>();
  for (const run of checkRuns) {
    if (run.sample || run.status !== "completed" || !run.report) continue;
    for (const chapter of run.report.chapters) {
      if (chapterFindings.has(chapter.chapter_number)) continue;
      chapterFindings.set(chapter.chapter_number, chapter.issues.map((issue) => (issue.nature === "confirmed_conflict" || issue.severity === "high" ? "high" : "mid")));
    }
  }
  const openThreads = threads.filter((record) => !record.archived_at && record.planted && (record.status === "planted" || record.status === "developing"));
  const upcoming = (authorContext?.story_plans ?? [])
    .filter((plan) => !plan.archived && plan.status !== "completed")
    .map((plan) => ({ plan, considering: considering.has(`story:${plan.id}`) }));
  const routePlans = upcoming
    .filter(({ plan }) => plan.target_chapter_number != null && plan.target_chapter_number >= draftNumber)
    .map(({ plan, considering: weighing }) => ({ id: plan.id, title: plan.title, chapter: plan.target_chapter_number!, considering: weighing }));
  const nextPlans = [...upcoming].sort((a, b) => (a.plan.target_chapter_number ?? 9_999) - (b.plan.target_chapter_number ?? 9_999) || a.plan.position - b.plan.position).slice(0, 5);
  const tones = openIssues.map(findingTone);

  return (
    <section className="project-page overview-page">
      <header className="overview-hero">
        <div className="overview-hero-main">
          <p className="label overview-kicker">
            {sample && <span className="sample-badge">示例作品</span>}
            {project.genre && <span>{project.genre}</span>}
            {project.genre && <span aria-hidden="true">/</span>}
            <span>{project.chapter_count ? `写到第 ${project.chapter_count} 章` : "还没有已写的章节"}</span>
          </p>
          <h1 className="overview-title">{project.title}</h1>
          {project.summary && <p className="overview-summary">{project.summary}</p>}
        </div>
        <div className="overview-hero-side">
          <div className="overview-menu">{menu}</div>
          <dl className="overview-figures">
            <div>
              <dt className="sr-only">已写章节</dt>
              <dd className="num">{project.chapter_count}</dd>
              <dd className="overview-figure-label">章已写{timeline ? ` · ${checkedCount} 章已检查` : ""}</dd>
            </div>
            <div>
              <dt className="sr-only">待看</dt>
              <dd className="num blue">{openIssues.length}</dd>
              <dd className="overview-figure-label">处待看</dd>
            </div>
            <div className="wide">
              <dt className="sr-only">字数</dt>
              <dd className="num">{formatCount(project.word_count ?? 0)}</dd>
              <dd className="overview-figure-label">字正文{draftChars ? ` · 另有草稿 ${formatCount(draftChars)} 字` : ""}</dd>
            </div>
          </dl>
        </div>
      </header>

      {notices}

      <button type="button" className="continue-band overview-continue" onClick={() => go(`/projects/${project.id}/workspace`)}>
        <span className="num continue-band-num">{draftNumber}</span>
        <span className="continue-band-copy">
          <span className="continue-band-label">{readOnly ? "草稿 · 只读" : "继续写 · 草稿"}</span>
          <span className="continue-band-title">{bareChapterTitle(draft?.title ?? "") || "这一章还没有标题"}</span>
        </span>
        <span className="continue-band-meta">{formatCount(draftChars)} 字{project.latest_run ? ` · 上次检查找到 ${openIssues.length} 处` : " · 还没检查"}</span>
        <span className="continue-band-go">{readOnly ? "查看草稿" : "打开草稿"}<svg width="18" height="18" viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M3 9h12M10 4l5 5-5 5" /></svg></span>
      </button>

      <section className="overview-route" aria-labelledby="route-title">
        <div className="section-head">
          <h2 id="route-title">故事航线</h2>
          <RouteLegend />
        </div>
        {timeline === null ? (
          <p className="label overview-loading">正在读取各章的情况…</p>
        ) : (
          <StoryRoute
            chapters={written.map((row) => ({ number: row.chapter_number, title: row.title, status: row.status, findings: chapterFindings.get(row.chapter_number) ?? [] }))}
            draft={{ number: draftNumber, title: draft?.title ?? "", findings: tones }}
            threads={openThreads.map((record) => ({ id: record.id, title: record.title, planted: record.planted!.chapter_number }))}
            plans={routePlans}
          />
        )}
      </section>

      <div className="overview-columns">
        <section aria-labelledby="overview-findings-title">
          <div className="section-head">
            <h2 id="overview-findings-title">草稿里待看</h2>
            <button type="button" className="section-link" onClick={() => go(`/projects/${project.id}/workspace`)}>去写作页处理</button>
          </div>
          {openIssues.length ? (
            <ol className="overview-list">
              {openIssues.slice(0, 6).map((issue, index) => (
                <li key={issue.id}>
                  <button type="button" onClick={() => go(`/projects/${project.id}/workspace#issue-${issue.id}`)}>
                    <span className="num overview-list-num">{index + 1}</span>
                    <span className="overview-list-copy">
                      <strong>{findingHeadline(issue)}</strong>
                      <span>{issue.claim_text ? `“${issue.claim_text.length > 40 ? `${issue.claim_text.slice(0, 39)}…` : issue.claim_text}”` : ""}</span>
                    </span>
                    <FindingTag issue={issue} />
                  </button>
                </li>
              ))}
            </ol>
          ) : (
            <p className="overview-empty">{project.latest_run ? "上次检查之后，草稿里没有待看的地方。" : "这一章还没检查。写完一段后，在写作页点「检查这一章」。"}</p>
          )}
          {openIssues.length > 0 && runOutdated && <p className="overview-note">草稿在检查之后又改过，这些结果针对的是先前的正文。</p>}
          {openIssues.length > 6 && <p className="overview-note">还有 {openIssues.length - 6} 处，在写作页查看。</p>}
        </section>

        <section aria-labelledby="overview-next-title">
          <div className="section-head">
            <h2 id="overview-next-title">接下来</h2>
            <button type="button" className="section-link" onClick={() => go(`/projects/${project.id}/plan`)}>全部计划</button>
          </div>
          {nextPlans.length ? (
            <ul className="overview-list">
              {nextPlans.map(({ plan, considering: weighing }) => (
                <li key={plan.id}>
                  <button type="button" onClick={() => go(`/projects/${project.id}/plan`)}>
                    <span className={`num overview-list-num wide${plan.target_chapter_number === draftNumber ? " blue" : ""}`}>{plan.target_chapter_number ? pad2(plan.target_chapter_number) : "—"}</span>
                    <span className="overview-list-copy">
                      <strong>{plan.title}</strong>
                      {(plan.summary || plan.goal) && <span>{(plan.summary || plan.goal).length > 40 ? `${(plan.summary || plan.goal).slice(0, 39)}…` : plan.summary || plan.goal}</span>}
                    </span>
                    {weighing ? <span className="tag considering">考虑中</span> : <span className="overview-decided">已定</span>}
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <p className="overview-empty">还没有写下接下来的打算。在「计划」里记下要写的情节，它们会出现在航线的「接下来」一段。</p>
          )}
        </section>
      </div>
    </section>
  );
}
