"use client";

import { FormEvent, useEffect, useState } from "react";
import type { TutorialEvent, User } from "../../model";
import { memoryTypeLabel, reviewStatusLabel, timeLabel } from "../labels";
import { Button, type CheckUsage, Dialog, Drawer } from "../ui";
import { ChaptersPage } from "./chapters";
import { ExportPanel } from "./export";
import { MaterialsPage } from "./materials";
import { OverviewPage } from "./overview";
import { PlanPage } from "./plan";
import { TutorialBar, TutorialGuidance } from "./tutorial";
import type { ProjectState, TutorialStep } from "./use-project";
import { WritingPage } from "./writing";

export type ProjectDialog = "export" | "meta" | "archive" | "reset";
export type PageProps = {
  p: ProjectState;
  user: User;
  usage: CheckUsage | null;
  tutorialStep: TutorialStep;
  open: (dialog: ProjectDialog) => void;
  go: (href: string) => void;
  notices: React.ReactNode;
};

/** One work: the tutorial bar when it is the sample, the current tab's page, and the shared dialogs. */
export function ProjectFrame({ p, tab, rawTab, user, usage, tutorialStep, finishTutorial, recordTutorialEvent, go }: {
  p: ProjectState;
  tab: string;
  rawTab: string;
  user: User;
  usage: CheckUsage | null;
  tutorialStep: TutorialStep;
  finishTutorial: (outcome: "complete" | "skip") => Promise<void>;
  recordTutorialEvent: (projectId: string, event: TutorialEvent) => Promise<unknown>;
  go: (href: string) => void;
}) {
  const project = p.project!;
  const [dialog, setDialog] = useState<ProjectDialog | null>(null);
  const [guidanceRequest, setGuidanceRequest] = useState(0);
  // Jump to an anchor (#issue-…, #chapter-…, #append) once the page has rendered.
  useEffect(() => {
    const hash = window.location.hash.slice(1);
    if (!hash) return;
    const timer = window.setTimeout(() => {
      const target = document.getElementById(hash);
      if (!target) return;
      for (let node = target.parentElement; node; node = node.parentElement) if (node instanceof HTMLDetailsElement) node.open = true;
      target.scrollIntoView({ block: "center" });
      target.focus({ preventScroll: true });
    }, 50);
    return () => window.clearTimeout(timer);
  }, [project.id, tab, p.chapters, p.memories]);

  const notices = (
    <>
      {p.tutorialActive && (
        <TutorialBar
          projectId={project.id}
          tab={tab}
          step={tutorialStep}
          restored={p.tutorialRestored}
          readOnly={p.readOnly}
          busy={Boolean(p.busy)}
          finish={finishTutorial}
          requestGuidance={() => setGuidanceRequest((value) => value + 1)}
          go={go}
        />
      )}
      {p.readOnly && (
        <p className="note note-info readonly" role="note">
          {project.status === "archived"
            ? "这部作品已归档，只能浏览。恢复后才能保存、检查和处理。"
            : p.tutorialActive && tutorialStep === 4
              ? "手机上可以浏览完整依据；请在电脑上继续作出决定。"
              : "窗口较窄，现在只能浏览。把窗口放宽就能继续写作和检查。"}
        </p>
      )}
    </>
  );
  const pageProps: PageProps = { p, user, usage, tutorialStep, open: setDialog, go, notices };
  let page;
  if (tab === "overview") page = <OverviewPage {...pageProps} />;
  else if (tab === "sources") page = <ChaptersPage {...pageProps} />;
  else if (tab === "memory") page = <MaterialsPage {...pageProps} initialView={rawTab === "characters" ? "people" : rawTab === "world" ? "settings" : null} />;
  else if (tab === "plan") page = <PlanPage {...pageProps} />;
  else page = <WritingPage {...pageProps} />;

  return (
    <>
      {page}
      {p.tutorialActive && (
        <TutorialGuidance projectId={project.id} step={tutorialStep} tab={tab} readOnly={p.readOnly} busy={Boolean(p.busy)} evidenceOpen={Boolean(p.selected)} sourceOpen={Boolean(p.sourceRecord)} requestId={guidanceRequest} />
      )}
      {dialog === "export" && <Dialog title="导出作品" close={() => setDialog(null)}><ExportPanel projectId={project.id} /></Dialog>}
      {dialog === "meta" && <MetaDialog p={p} close={() => setDialog(null)} />}
      {dialog === "archive" && (
        <Dialog title={project.status === "archived" ? "恢复作品" : "归档作品"} close={() => setDialog(null)}>
          <p>{project.status === "archived" ? `恢复《${project.title}》后，就可以继续写和检查。` : `归档后《${project.title}》只能浏览，不能写入；不会删除。随时可以恢复。`}</p>
          <div className="dialog-actions">
            <Button kind="primary" disabled={Boolean(p.busy)} onClick={async () => { if (await p.updateProject(project.status === "archived" ? { status: "active" } : { status: "archived", confirm_archive: true })) setDialog(null); }}>{project.status === "archived" ? "恢复作品" : "归档"}</Button>
            <Button kind="text" onClick={() => setDialog(null)}>取消</Button>
          </div>
        </Dialog>
      )}
      {dialog === "reset" && (
        <Dialog title="重置作品" close={() => setDialog(null)}>
          <p>
            《{project.title}》会回到
            {project.data_origin === "user_import" ? "刚导入时的样子：保留导入的章节，事实库清空，草稿回到初始状态。"
              : project.data_origin === "demo_seed" || project.is_tutorial ? "示例的初始状态：章节、已确认的事实、草稿和示例检查结果都恢复。"
                : "刚创建时的样子：资料清空，草稿回到初始状态。"}
          </p>
          <p>这部作品的检查结果、你的决定和没提交的修改都会清除。其他作品不受影响。<strong>重置后不能撤销。</strong></p>
          <div className="dialog-actions">
            <Button kind="danger" disabled={p.readOnly || Boolean(p.busy)} onClick={async () => { if (await p.reset()) setDialog(null); }}>确认重置</Button>
            <Button kind="text" onClick={() => setDialog(null)}>取消</Button>
          </div>
        </Dialog>
      )}
      {p.sourceRecord && <SourceDrawer p={p} />}
      {p.draftRecoveryPrompt && <RecoveryDialog p={p} />}
    </>
  );
}

function MetaDialog({ p, close }: { p: ProjectState; close: () => void }) {
  const project = p.project!;
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (await p.updateProject({ title: String(form.get("title")), genre: String(form.get("genre")), summary: String(form.get("summary")) })) close();
  };
  return (
    <Dialog title="编辑作品信息" close={close}>
      <form className="form-inner" onSubmit={(event) => void submit(event)}>
        <p className="dialog-lede">只改书名和介绍，不动正文、资料和检查记录。</p>
        <label className="field"><span className="field-label">书名</span><input name="title" defaultValue={project.title} required maxLength={120} /></label>
        <label className="field"><span className="field-label">类型</span><input name="genre" defaultValue={project.genre} maxLength={60} placeholder="例如：悬疑" /></label>
        <label className="field"><span className="field-label">简介</span><textarea name="summary" defaultValue={project.summary} maxLength={500} rows={4} /></label>
        <div className="dialog-actions">
          <Button kind="primary" type="submit" disabled={p.readOnly || Boolean(p.busy)}>保存</Button>
          <Button kind="text" onClick={close}>取消</Button>
        </div>
      </form>
    </Dialog>
  );
}

/** 原文出处: the cited passage highlighted, with the rest of what the chapter offers around it. */
function SourceDrawer({ p }: { p: ProjectState }) {
  const record = p.sourceRecord!;
  const chapter = p.chapters.find((item) => item.id === record.chapterId || item.number === record.chapterNumber);
  const spans = chapter?.source_spans ?? [];
  const match = spans.find((span) => span.span_id === record.spanId);
  const context = spans.filter((span) => span.span_id !== record.spanId).slice(0, 3);
  return (
    <Drawer title={`第 ${record.chapterNumber} 章 · ${record.chapterTitle || "未命名"}`} kicker="原文出处" close={p.closeSource}>
      <p className="label">{match?.label === "chapter_revision" ? "修订后的正文" : match?.label ?? "引用的段落"}</p>
      <blockquote className="source-quote"><mark>{match?.text_excerpt || record.excerpt || "没有可显示的原文"}</mark></blockquote>
      <div className="source-tags">
        {record.memoryType
          ? <><span className="tag tag-line">{memoryTypeLabel(record.memoryType)}</span><span className={`tag ${record.reviewStatus === "author_confirmed" ? "tag-solid" : "tag-gap"}`}>{reviewStatusLabel(record.reviewStatus ?? "")}</span></>
          : <><span className="tag tag-line">{record.relation === "contradicts" ? "与草稿冲突" : record.relation === "supports" ? "支持" : "背景"}</span><span className={`tag ${record.sufficiency === "sufficient" ? "tag-solid" : "tag-gap"}`}>{record.sufficiency === "sufficient" ? "依据充分" : "依据不足"}</span></>}
      </div>
      {chapter?.summary && <><p className="label source-gap">这一章写了什么</p><p className="source-summary">{chapter.summary}</p></>}
      <p className="label source-gap">同一章的其他段落</p>
      {context.length ? context.map((span) => (
        <article key={span.span_id} className="source-context">
          <strong>{span.label === "chapter_revision" ? "修订后的正文" : span.label}</strong>
          <p>{span.text_excerpt}</p>
        </article>
      )) : <p className="muted">没有更多段落。</p>}
      <details className="tech">
        <summary>记录编号</summary>
        <p className="mono">记录 {record.recordId || "—"} · 段落 {record.spanId || "—"} · 章节 {record.chapterId || "—"}</p>
        {record.memoryType && <p className="mono">事实库第 {record.memoryValidFrom ?? "—"} 版起{record.memoryValidTo == null ? "至今有效" : `，第 ${record.memoryValidTo} 版失效`}</p>}
        <p className="mono">作品正文第 {p.project?.source_revision ?? "—"} 版</p>
      </details>
      <p className="small-note">原文在这里只读，不会从这里修改。</p>
    </Drawer>
  );
}

function RecoveryDialog({ p }: { p: ProjectState }) {
  const prompt = p.draftRecoveryPrompt!;
  const conflict = prompt.snapshot.base_revision !== prompt.serverDraft.revision;
  return (
    <Dialog title={conflict ? "有两个不同版本的草稿" : "这台设备上有没保存的草稿"} close={() => undefined} closeDisabled wide>
      <p>{conflict ? "服务器上的草稿在这份本机副本之后又更新过。先比较两份全文；本机副本不会直接覆盖服务器。" : "这份内容还没保存到服务器。恢复后仍需要你点保存。"}</p>
      <div className="compare">
        <label className="field">
          <span className="field-label">本机副本<span className="label">基于第 {prompt.snapshot.base_revision} 次保存 · {timeLabel(prompt.snapshot.updated_at)}</span></span>
          <textarea readOnly rows={12} value={`${prompt.snapshot.title}\n\n${prompt.snapshot.body}`} aria-label="本机副本全文" />
        </label>
        <label className="field">
          <span className="field-label">服务器上的版本<span className="label">第 {prompt.serverDraft.revision} 次保存 · {timeLabel(prompt.serverDraft.saved_at)}</span></span>
          <textarea readOnly rows={12} value={`${prompt.serverDraft.title}\n\n${prompt.serverDraft.body}`} aria-label="服务器版本全文" />
        </label>
      </div>
      <div className="dialog-actions">
        <Button kind="primary" onClick={p.acceptRecovery}>{conflict ? "查看本机副本（不能直接覆盖）" : "恢复本机副本"}</Button>
        <Button onClick={p.keepServerDraft}>{conflict ? "用服务器版本，丢掉副本" : "用已保存的版本"}</Button>
      </div>
      <p className="small-note">本机副本只存在这个浏览器里，不含资料和检查结果。</p>
    </Dialog>
  );
}
