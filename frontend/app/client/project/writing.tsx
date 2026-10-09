"use client";

import { type CSSProperties, type KeyboardEvent as ReactKeyboardEvent, useEffect, useRef, useState } from "react";
import { json, labelError, labelRunFailure } from "../../api";
import type { Draft, Issue, Run, SourceChangeSet, WritingAnalysisRun } from "../../model";
import { DraftWordCount, flashText, rewriteDraftText, RichDraftEditor, useDraftText, WritingTools, type FindingMark } from "../editor";
import { Odometer, reducedMotion, ScanLine, ThreadLayer, useFirstShow } from "../motion";
import {
  activeAnalysis,
  activeRun,
  alignmentStatusLabel,
  briefSectionLabel,
  clockLabel,
  decisionLabel,
  durationLabel,
  findingTone,
  memoryTypeLabel,
  memoryTypes,
  NO_FACT_CHANGES,
  predicateLabel,
  readableKeys,
  retryableAnalysis,
  retryableRun,
  sourceKindLabel,
  stageLabel,
  timeLabel,
} from "../labels";
import { bareChapterTitle, Button, chapterHeading, Dialog, formatCount, Menu, Num, pad2, SectionHead, Tag, usageShort, useFocusTrap, useScrollLock, writtenChars } from "../ui";
import { ChapterDesk, ChapterRail, TitleField } from "./chapter-desk";
import type { PageProps } from "./frame";
import { FindingTag, findingHeadline } from "./findings";
import { PredicateSelect } from "./materials";
import { issueAllows, issueHasSufficientEvidence, issueNeedsDecision, type ProjectState } from "./use-project";

/** 写作: a huge blue chapter number and the title, the chapters on the left, the draft with each
    finding's sentence marked and numbered, and the findings as cards that open in place. Both side
    columns stay on screen while the draft scrolls. A written chapter opens here too (?chapter=N). */
export function WritingPage(props: PageProps) {
  const { p, user, go, notices } = props;
  const [viewing, setViewing] = useState<number | null>(() => {
    if (typeof window === "undefined") return null;
    const requested = Number(new URLSearchParams(window.location.search).get("chapter"));
    return Number.isInteger(requested) && requested > 0 ? requested : null;
  });
  const open = (number: number | null) => {
    const known = number !== null && p.chapters.some((chapter) => chapter.number === number);
    setViewing(known ? number : null);
    window.history.replaceState(window.history.state, "", known ? `${window.location.pathname}?chapter=${number}` : window.location.pathname);
    window.scrollTo({ top: 0 });
  };
  if (viewing !== null && p.chapters.some((chapter) => chapter.number === viewing))
    return <ChapterDesk key={viewing} p={p} user={user} go={go} notices={notices} number={viewing} open={open} />;
  return <DraftDesk {...props} openChapter={open} />;
}

function DraftDesk({ p, usage, tutorialStep, open: openDialog, go, notices, openChapter }: PageProps & { openChapter: (number: number | null) => void }) {
  const project = p.project!;
  const [mobilePane, setMobilePane] = useState<"draft" | "issues">("draft");
  // What the right column shows: the check's findings, or a pre-writing review or plan comparison that has been started.
  // Coming from the plan page's 对照正文, whose comparison is running, the column opens on 对照计划.
  const [wantedSide, setWantedSide] = useState<SideItem>(() => (p.analysisBusy === "plan_alignment" || activeAnalysis(p.planAlignment) ? "plan" : "findings"));
  const [revealSide, setRevealSide] = useState(0);
  const [focus, setFocus] = useState(false);
  const [completing, setCompleting] = useState(false);
  const [tech, setTech] = useState(false);
  const [hovered, setHovered] = useState<string | null>(null);
  const [folding, setFolding] = useState<string | null>(null);
  const focusTrigger = useRef<HTMLButtonElement>(null);
  const issues = groupIssues(p.run?.issues ?? []);
  const isDone = (issue: Issue) => Boolean(issue.decision || issue.reused_decision || p.locallyResolvedIssueIds.includes(issue.id));
  const pending = issues.filter((issue) => issueNeedsDecision(issue, p.locallyResolvedIssueIds)).length;
  // The backend only offers a fact review for findings the author kept on purpose and that came with a proposed fact change.
  const hasFactChanges = issues.some((issue) => issue.has_memory_proposal && issue.decision?.decision === "keep_intentional" && !issue.decision.reused);
  const locked = p.readOnly || Boolean(p.draftRecoveryConflict) || Boolean(p.pendingControlledDecision);
  const blocked = locked || Boolean(p.busy);
  const hasPlans = Boolean(p.authorContext && p.authorContext.story_plans.length + p.authorContext.character_plans.length + p.authorContext.world_plans.length > 0);
  const hasBrief = Boolean(p.contextBrief) || p.analysisBusy === "context_brief";
  const hasAlignment = hasPlans && (Boolean(p.planAlignment) || p.analysisBusy === "plan_alignment");
  const side: SideItem = wantedSide === "brief" && hasBrief ? "brief" : wantedSide === "plan" && hasAlignment ? "plan" : "findings";
  const empty = !(p.saved?.body ?? p.draft?.body ?? "").trim();
  const chars = writtenChars(p.draft?.body ?? "");
  const chapterNumber = p.draft?.chapter_number ?? project.current_draft.chapter_number;
  const saving = ["保存草稿", "保存修改", "正在重试记录决定"].includes(p.busy);
  const saveState = saving || p.autosaveState === "saving" ? "saving" : p.saveFailed ? "failed" : p.dirty ? "unsaved" : "saved";
  const saveLabel = saveState === "saving" ? "保存中" : saveState === "failed" ? "没保存成功" : p.autosaveState === "conflict" && p.dirty ? "自动保存已暂停" : saveState === "unsaved" ? (p.autosaveState === "failed" ? "自动保存没成功" : "未保存") : `已保存 ${clockLabel(p.saved?.saved_at)}`;
  const saveDetail = p.saveFailed ? "正文还在这台设备上，可以再保存一次。"
    : p.dirty ? p.draftRecoveryUnavailable || (p.autosaveState === "conflict" ? "别处保存了更新的版本；文字留在这台设备上，请刷新后比较。" : p.autosaveState === "failed" ? "暂时没存到服务器，文字留在这台设备上，稍后会再试。" : "停笔几秒后会自动保存。")
      : "";
  const outdated = p.dirty || Boolean(p.run?.is_stale);
  const checking = activeRun(p.run);
  // 示例: ?demo=checking shows the reading line without a model (development builds only).
  const demoChecking = process.env.NODE_ENV !== "production" && typeof window !== "undefined" && new URLSearchParams(window.location.search).get("demo") === "checking";
  const scanning = checking || demoChecking;
  const reveal = useFirstShow(p.run?.status === "completed" ? p.run.run_id : null, issues.length);
  // Opening a finding brings the findings back; starting a review or comparison scrolls to the column if it is out of view.
  const selectedId = p.selected?.id ?? null;
  const [seenSelected, setSeenSelected] = useState(selectedId);
  if (seenSelected !== selectedId) {
    setSeenSelected(selectedId);
    if (selectedId) setWantedSide("findings");
  }
  useEffect(() => {
    if (!revealSide) return;
    const column = document.getElementById("writing-side");
    if (!column) return;
    const box = column.getBoundingClientRect();
    const covered = parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 0;
    if (box.top > window.innerHeight - covered || box.bottom < covered * 2) column.scrollIntoView({ block: "start", behavior: reducedMotion() ? "auto" : "smooth" });
  }, [revealSide]);
  const linkedId = hovered ?? p.selected?.id ?? null;
  const linkedIssue = issues.find((issue) => issue.id === linkedId) ?? null;
  const linkedChapters = [...new Set((linkedIssue?.evidence ?? []).map((item) => item.chapter_number))].slice(0, 3);
  const marks: FindingMark[] = issues.map((issue, index) => ({ id: issue.id, text: issue.claim_text ?? "", tone: findingTone(issue), index: index + 1, active: p.selected?.id === issue.id, hovered: hovered === issue.id, done: isDone(issue), reveal }));
  const pick = (id: string) => {
    const issue = issues.find((item) => item.id === id);
    const row = document.getElementById(`issue-${id}`);
    if (!issue || !row) return;
    if (p.selected?.id !== id) void p.select(issue, row);
    setWantedSide("findings");
    setMobilePane("issues");
    window.setTimeout(() => row.scrollIntoView({ block: "nearest", behavior: "smooth" }), 0);
  };
  // Opening a card from the list brings its sentence into view and rings it once.
  const openCard = (issue: Issue, trigger: HTMLElement) => {
    void p.select(issue, trigger);
    const mark = document.querySelector<HTMLElement>(`.finding-mark[data-finding="${CSS.escape(issue.id)}"]`);
    if (!mark) return;
    const box = mark.getBoundingClientRect();
    if (box.top < 96 || box.bottom > window.innerHeight - 24) mark.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
    if (issue.claim_text) flashText("draft-body", issue.claim_text, "mark-pulse", 900);
  };
  // A finding that has just been handled folds its card away.
  const decided = (issueId: string) => {
    if (reducedMotion()) { p.deselect(); return; }
    setFolding(issueId);
    window.setTimeout(() => { setFolding(null); p.deselect(); }, 1100);
  };
  const pointAt = (target: EventTarget | null) => {
    const id = (target as HTMLElement | null)?.closest?.("[data-finding]")?.getAttribute("data-finding") ?? null;
    if (id !== hovered) setHovered(id);
  };
  const over = usage ? (usage.account_type === "visitor" ? chars > usage.check_chars_per_check : chars > usage.check_chars_remaining) : false;
  // A visitor's check is refused above the per-check limit, so the button says so up front.
  const visitorLimit = usage?.account_type === "visitor" && chars > usage.check_chars_per_check ? usage.check_chars_per_check : null;
  const primary = p.dirty || p.controlled || p.pendingControlledDecision ? (
    <Button kind="primary" size="lg" disabled={Boolean(p.busy) || Boolean(p.draftRecoveryConflict) || Boolean(p.pendingDecisionConflict)} onClick={() => void p.save()}>{p.pendingControlledDecision ? "重试记录决定" : p.controlled ? "保存修改" : "保存"}</Button>
  ) : checking ? (
    <Button kind="primary" size="lg" disabled busy>正在检查…</Button>
  ) : p.run && retryableRun(p.run) ? (
    <Button kind="primary" size="lg" disabled={blocked} onClick={() => void p.retryRun()}>再检查一次</Button>
  ) : (
    <Button kind="primary" size="lg" disabled={blocked || !p.draft || empty || visitorLimit !== null} title={empty ? "先写下正文，再检查" : visitorLimit !== null ? `访客每次最多检查 ${formatCount(visitorLimit)} 字` : undefined} onClick={() => void p.check()}>{p.run ? "再检查一次" : "检查这一章"}</Button>
  );
  const finished = p.run?.status === "completed" && !checking;
  const analyse = (kind: "context_brief" | "plan_alignment") => {
    setWantedSide(kind === "context_brief" ? "brief" : "plan");
    setMobilePane("issues");
    setRevealSide((count) => count + 1);
    void p.startAnalysis(kind);
  };

  return (
    <section className="page writing" data-mobile-pane={mobilePane}>
      {notices}
      <header className="draft-head" aria-label={`草稿第 ${chapterNumber} 章`}>
        <Num className="draft-head-num"><Odometer value={chapterNumber} /></Num>
        <div className="draft-head-main">
          <h1 className="sr-only">{chapterHeading(chapterNumber, p.draft?.title ?? "")}</h1>
          <p className="label draft-head-meta">
            <span className="badge">草稿</span>
            <span>{formatCount(chars)} 字</span>
            <span className={`save-state ${saveState}`}><i key={saveState === "saved" ? p.saved?.saved_at : saveState} aria-hidden="true" />{saveLabel}</span>
          </p>
          <TitleField value={p.draft?.title ?? ""} placeholder="这一章的标题" disabled={blocked} onChange={(title) => p.draft && p.setDraft({ ...p.draft, title })} />
          {saveDetail && <p className="draft-save-detail">{saveDetail}</p>}
        </div>
        {!p.readOnly && (
          <div className="draft-head-side">
            <div className="draft-head-actions">
              <Button size="lg" disabled={Boolean(p.analysisBusy) || !p.draft || p.dirty} onClick={() => analyse("context_brief")}>{p.analysisBusy === "context_brief" ? "正在回顾" : "写前回顾"}</Button>
              {hasPlans && <Button size="lg" disabled={Boolean(p.analysisBusy) || !p.draft || p.dirty || empty} onClick={() => analyse("plan_alignment")}>{p.analysisBusy === "plan_alignment" ? "正在对照" : "对照计划"}</Button>}
              <Menu buttonLabel="更多：完成本章、技术详情、重置" danger={<button type="button" role="menuitem" className="danger" disabled={blocked} onClick={() => openDialog("reset")}>重置作品</button>}>
                <button type="button" role="menuitem" disabled={blocked || !p.draft || p.dirty || empty} onClick={() => setCompleting(true)}>完成本章，开始下一章</button>
                <button type="button" role="menuitem" disabled={!p.run} onClick={() => setTech(true)}>这次检查的技术详情</button>
              </Menu>
              {primary}
            </div>
            {!empty && usage && <p className={`label draft-head-allowance${over ? " over" : ""}`}>本次约 {formatCount(chars)} 字 · {usage.account_type === "visitor" ? `访客每次最多 ${formatCount(usage.check_chars_per_check)} 字，还可检查 ${usage.checks_remaining} 次${over ? "。这一章超过了上限，删减后才能检查，或者注册账号" : ""}` : usageShort(usage)}</p>}
          </div>
        )}
      </header>

      {(p.controlled || p.pendingControlledDecision) && (
        <div className="note note-warn">
          <span>{p.pendingDecisionConflict
            ? `${p.pendingDecisionConflict}${p.pendingDecisionStorageUnavailable ? ` ${p.pendingDecisionStorageUnavailable}` : ""}`
            : p.pendingControlledDecision ? `正文已经保存，编辑暂时锁定。请重试记录这一条的决定；不会再次保存正文。${p.pendingDecisionStorageUnavailable ? ` ${p.pendingDecisionStorageUnavailable}` : ""}`
              : "正在按选中的那一条改正文。保存时会一并记下你的处理。"}</span>
          {p.pendingDecisionConflict && <Button kind="text" disabled={Boolean(p.busy)} onClick={() => void p.stopConflictedPendingDecision()}>停止补记并读取最新正文</Button>}
        </div>
      )}
      {project.data_origin === "user_import" && project.memory_initialization_status !== "completed" && (
        <div className="note note-warn"><span>这部导入作品的事实还没整理。现在就能检查，系统会直接对照前文；整理并确认事实后，检查会更准。</span><Button kind="text" onClick={() => go(`/projects/${project.id}/memory`)}>去整理事实</Button></div>
      )}
      {p.coverage?.status === "update_pending" && (
        <div className="note note-warn"><span>正文追加到了第 {project.source_revision} 版；只有新增的段落会和已确认的资料一起审阅。</span>{p.memoryDelta?.status === "failed" ? <span>上次没有完成，也没有写入任何结果，可以放心重试。</span> : <Button kind="primary" disabled={blocked} onClick={() => void p.startIncrementalReview()}>检查新增的章节</Button>}</div>
      )}
      {p.draftRecoveryConflict && (
        <div className="note note-warn recovery-conflict-notice"><span>这里显示的是只读的本机副本，不能输入，也不会覆盖服务器上的新版本。可以复制文字，或比较后选服务器版本。</span><Button kind="text" onClick={p.openDraftRecoveryConflict}>比较两份正文</Button></div>
      )}

      <nav className="mobile-panes" aria-label="切换内容">
        {(["draft", "issues"] as const).map((pane) => (
          <button key={pane} type="button" aria-current={mobilePane === pane ? "page" : undefined} onClick={() => setMobilePane(pane)}>{pane === "draft" ? "正文" : `检查结果 ${issues.length}`}</button>
        ))}
      </nav>

      <div className="draft-grid">
        <ChapterRail chapters={p.chapters} current={null} draftNumber={chapterNumber} draftTitle={p.draft?.title ?? ""} linked={linkedChapters} open={openChapter} />

        <article className="draft" aria-label="草稿正文">
          <div className="draft-tools">
            {!locked ? <WritingTools targetId="draft-body" disabled={Boolean(p.busy) || !p.draft} /> : <span />}
            <span className="draft-tools-side">
              <span className="label"><DraftWordCount targetId="draft-body" body={p.draft?.body ?? ""} /></span>
              {!locked && <button type="button" ref={focusTrigger} className="link" disabled={!p.draft || Boolean(p.busy)} onClick={() => setFocus(true)}>专注写作</button>}
            </span>
          </div>
          <div id="draft-source" className="draft-field" onMouseOver={(event) => pointAt(event.target)} onMouseLeave={() => setHovered(null)}>
            {scanning && <ScanLine container="#draft-body" />}
            {p.readOnly ? (
              <RichDraftEditor id="draft-body" label="草稿正文（只读）" value={p.draft?.body ?? ""} format={p.draft?.body_format ?? "plain_text"} disabled onChange={() => undefined} marks={marks} onPickMark={pick} />
            ) : p.draftRecoveryConflict || p.pendingControlledDecision ? (
              <textarea id="draft-body" aria-label="草稿正文" value={p.draft?.body ?? ""} readOnly aria-readonly="true" />
            ) : (
              <RichDraftEditor id="draft-body" label="草稿正文" placeholder="开始写这一章……" value={p.draft?.body ?? ""} format={p.draft?.body_format ?? "plain_text"} disabled={Boolean(p.busy)} onChange={(body, body_format) => p.draft && p.setDraft({ ...p.draft, body, body_format })} marks={marks} onPickMark={pick} />
            )}
          </div>
        </article>

        <aside id="writing-side" className="findings" aria-label="检查与回顾">
          <SideTabs
            value={side}
            onChange={setWantedSide}
            items={[
              { id: "findings", label: "检查结果", count: issues.length },
              ...(hasBrief ? [{ id: "brief" as const, label: "写前回顾" }] : []),
              ...(hasAlignment ? [{ id: "plan" as const, label: "对照计划" }] : []),
            ]}
          />
          <div role="tabpanel" id="side-panel-findings" aria-labelledby="side-tab-findings" hidden={side !== "findings"}>
          {p.memoryDelta && p.memoryDelta.status !== "not_started" && (
            <div className="note note-info"><strong>新增章节的事实变化 · {p.memoryDelta.status === "in_review" ? "等你确认" : p.memoryDelta.status === "covered" ? "已完成" : stageLabel(p.memoryDelta.status)}</strong><span>没确认的不会进资料，也不会用于之后的检查。</span><Button kind="text" onClick={() => go(`/projects/${project.id}/memory`)}>去资料确认</Button></div>
          )}
          {p.run && (
            <div className="findings-head">
              <span className="label">{issues.length} 处{pending ? ` · ${pending} 处待定` : ""}{p.run.completed_at || p.run.created_at ? ` · ${clockLabel(p.run.completed_at ?? p.run.created_at)}` : ""}</span>
            </div>
          )}
          {p.run ? (
            <>
              {outdated && p.run.status === "completed" && <p className="findings-note">草稿在检查之后改过，下面的结果针对的是先前的正文。</p>}
              {p.run.result_origin === "demo_preset" && <p className="findings-note"><strong>示例结果</strong> · 示例作品预先放好的结果，用来展示怎么处理；这次没有调用模型。</p>}
              {p.run.status === "completed" && (p.run.metrics?.undecided_claim_count ?? 0) > 0 && (
                <p className="findings-note">{(p.run.metrics?.undecided_claims ?? []).some((row) => row.error_code === "provider_attempt_quota_exceeded") ? `额度用完，有 ${p.run.metrics?.undecided_claim_count} 句没检查，结果里不包括它们。` : `有 ${p.run.metrics?.undecided_claim_count} 句没能判断，结果里不包括它们。`}</p>
              )}
              {finished && pending === 0 && (
                <div className="findings-zero">
                  <Num>0</Num>
                  <p><strong>这一章前后不打架。</strong>{issues.length ? (hasFactChanges ? "都处理完了。最后确认哪些事实有变化，再记进资料。" : "都处理完了。") : "这次检查没有发现要处理的地方。"}</p>
                  {issues.length > 0 && !hasFactChanges && <p>{NO_FACT_CHANGES}</p>}
                  {issues.length > 0 && hasFactChanges && !p.readOnly && <Button kind="primary" disabled={blocked || p.run.lineage_status === "superseded_unlinked"} onClick={() => void p.review()}>审阅事实变化</Button>}
                </div>
              )}
              <RunStatus run={p.run} p={p} actions={!p.readOnly} visitor={usage?.account_type === "visitor"} />
              {p.pairedRun && <RunStatus run={p.pairedRun} p={p} actions={false} visitor={usage?.account_type === "visitor"} />}
              {checking && <div className="finding-skeleton" role="status" aria-label="正在检查这一章"><span /><span /><span /><span /><span /><span /></div>}
              <ol className={`finding-list${reveal ? " reveal" : ""}`}>
                {issues.map((issue, index) => {
                  const isOpen = p.selected?.id === issue.id;
                  const done = isDone(issue);
                  return (
                    <li key={issue.id} style={reveal ? { "--i": index } as CSSProperties : undefined} className={`finding${isOpen ? " open" : ""}${done ? " done" : ""}${hovered === issue.id && !isOpen ? " linked" : ""}`}
                      onMouseEnter={() => setHovered(issue.id)} onMouseLeave={() => setHovered(null)}>
                      <button id={`issue-${issue.id}`} data-testid={`finding-${issue.id}`} type="button" className={`issue-row severity-${issue.severity}`} aria-expanded={isOpen}
                        onFocus={() => setHovered(issue.id)} onBlur={() => setHovered(null)}
                        onClick={(event) => (isOpen ? p.deselect() : openCard(issue, event.currentTarget))}>
                        <Num className="finding-num">{index + 1}</Num>
                        <span className="finding-head">
                          <span className="finding-tags">
                            <FindingTag issue={issue} long />
                            {done ? <span className="label just-done">{issue.reused_decision ? "沿用之前的判断" : "已处理"}</span> : issue.to_revise ? <span className="label">待修改</span> : null}
                          </span>
                          <strong>{findingHeadline(issue)}</strong>
                        </span>
                      </button>
                      {isOpen && p.selected && (
                        <div className={folding === issue.id ? "collapse closing" : "collapse"}>
                          <div><FindingDetail key={issue.id} p={p} issue={p.selected} tutorialStep={tutorialStep} outdated={outdated} decided={decided} /></div>
                        </div>
                      )}
                    </li>
                  );
                })}
              </ol>
            </>
          ) : scanning ? (
            <div className="finding-skeleton" role="status" aria-label="正在检查这一章"><span /><span /><span /><span /><span /><span /></div>
          ) : <p className="findings-empty">{empty ? "先写下正文，再检查。" : "检查后，和前文冲突或说不通的地方会按顺序列在这里，每一处都附上前文出处。"}</p>}
          </div>
          {hasBrief && (
            <div role="tabpanel" id="side-panel-brief" aria-labelledby="side-tab-brief" hidden={side !== "brief"}>
              {p.contextBrief ? <AnalysisPanel run={p.contextBrief} p={p} /> : <p className="findings-empty" role="status">正在开始写前回顾…</p>}
            </div>
          )}
          {hasAlignment && (
            <div role="tabpanel" id="side-panel-plan" aria-labelledby="side-tab-plan" hidden={side !== "plan"}>
              {p.planAlignment ? <AnalysisPanel run={p.planAlignment} p={p} /> : <p className="findings-empty" role="status">正在开始对照计划…</p>}
            </div>
          )}
        </aside>
      </div>

      {p.changeSet && <FactReview p={p} />}

      <ThreadLayer from={linkedId && !reducedMotion() ? `.finding-mark[data-finding="${linkedId}"]` : null} to={linkedChapters.map((number) => `.draft-chapters li[data-chapter="${number}"] button`)} />
      {completing && <CompleteDraft p={p} close={() => setCompleting(false)} />}
      {tech && p.run && <TechDialog run={p.run} paired={p.pairedRun} close={() => setTech(false)} />}
      {focus && !locked && <FocusEditor p={p} close={() => { setFocus(false); window.setTimeout(() => focusTrigger.current?.focus(), 0); }} pick={(issue, element) => { setFocus(false); void p.select(issue, element); window.setTimeout(() => document.getElementById(`issue-${issue.id}`)?.scrollIntoView({ block: "center" }), 0); }} />}
    </section>
  );
}

type SideItem = "findings" | "brief" | "plan";
/** The right column's switch: a tablist with one tab per item; the arrow keys, Home and End move between them. */
function SideTabs({ items, value, onChange }: { items: { id: SideItem; label: string; count?: number }[]; value: SideItem; onChange: (next: SideItem) => void }) {
  const onKeyDown = (event: ReactKeyboardEvent<HTMLDivElement>) => {
    if (!["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    // Counted from the tab that has focus, which is not always the chosen one.
    const focused = (event.target as HTMLElement).closest<HTMLElement>('[role="tab"]')?.id.replace("side-tab-", "");
    const at = Math.max(0, items.findIndex((item) => item.id === (focused ?? value)));
    const next = event.key === "Home" ? 0 : event.key === "End" ? items.length - 1 : (at + (event.key === "ArrowRight" ? 1 : items.length - 1)) % items.length;
    onChange(items[next].id);
    document.getElementById(`side-tab-${items[next].id}`)?.focus();
  };
  return (
    <div className="side-tabs" role="tablist" aria-label="右栏内容" onKeyDown={onKeyDown}>
      {items.map((item) => (
        <button key={item.id} type="button" role="tab" id={`side-tab-${item.id}`} className="side-tab" aria-selected={item.id === value} aria-controls={`side-panel-${item.id}`} tabIndex={item.id === value ? 0 : -1} onClick={() => onChange(item.id)}>
          <span>{item.label}</span>{item.count !== undefined && <> <span className="num side-tab-count">{item.count}</span></>}
        </button>
      ))}
    </div>
  );
}

/** 完成本章: the draft becomes a written chapter and the next draft begins; the big number rolls on. */
function CompleteDraft({ p, close }: { p: ProjectState; close: () => void }) {
  const project = p.project!;
  const [preview, setPreview] = useState<SourceChangeSet | null>(null);
  const [busy, setBusy] = useState("正在准备");
  const [error, setError] = useState("");
  useEffect(() => {
    let live = true;
    void Promise.resolve()
      .then(() => json<{ source_change_set: SourceChangeSet }>(`/projects/${project.id}/source-change-sets/preview`, "POST", { mode: "append", input_method: "draft_complete", base_source_revision: project.source_revision ?? 1, draft_id: p.draft?.id }))
      .then((data) => { if (live) setPreview(data.source_change_set); }, (cause) => { if (live) setError(labelError(cause)); })
      .finally(() => { if (live) setBusy(""); });
    return () => { live = false; };
    // Prepared once, when the dialog opens.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  const commit = async () => {
    if (!preview) return;
    setBusy("正在完成"); setError("");
    try {
      const data = await json<{ source_change_set: SourceChangeSet; next_draft: Draft }>(`/projects/${project.id}/source-change-sets/${preview.id}/commit`, "POST", { confirm: true, content_sha256: preview.content_sha256 });
      close();
      p.adoptNextDraft(data.next_draft);
      window.scrollTo({ top: 0, behavior: reducedMotion() ? "auto" : "smooth" });
      await Promise.all([p.refreshReferences(), p.refreshSummary()]);
      p.notify(`第 ${p.draft?.chapter_number ?? ""} 章写完了。现在开始第 ${data.next_draft?.chapter_number ?? ""} 章。`);
    } catch (cause) { setError(labelError(cause)); setBusy(""); }
  };
  const chapter = preview?.chapters[0];
  return (
    <Dialog title="完成本章，开始下一章" close={close} closeDisabled={busy === "正在完成"}>
      <p>把草稿《{bareChapterTitle(p.draft?.title ?? "") || "未命名"}》定为第 {p.draft?.chapter_number ?? "—"} 章，然后开始下一章的草稿。写完的章节以后还能在写作页打开修改。</p>
      {chapter && <p className="complete-line"><Num>{pad2(p.draft?.chapter_number ?? chapter.order)}</Num><strong>{bareChapterTitle(chapter.title) || "未命名"}</strong><span className="label">{formatCount(chapter.character_count)} 字</span></p>}
      {error && <p className="inline-error" role="alert">{error}</p>}
      <div className="dialog-actions">
        <Button kind="primary" disabled={!preview || Boolean(busy)} busy={Boolean(busy)} onClick={() => void commit()}>{busy || "完成本章"}</Button>
        <Button kind="text" disabled={busy === "正在完成"} onClick={close}>取消</Button>
      </div>
    </Dialog>
  );
}

/** Findings on the same sentence stay next to each other, in the order the run returned them. */
function groupIssues(issues: Issue[]) {
  const groups = new Map<string, Issue[]>();
  for (const issue of issues) groups.set(issue.claim_span_id || issue.id, [...(groups.get(issue.claim_span_id || issue.id) ?? []), issue]);
  return [...groups.values()].flat();
}

/** The open finding: why it was flagged, the earlier passages it rests on, the suggested change, and
    what the author can do. Actions follow the finding's kind; the first one is blue. */
function FindingDetail({ p, issue, tutorialStep, outdated, decided: onDecided }: { p: ProjectState; issue: Issue; tutorialStep: number; outdated: boolean; decided: (issueId: string) => void }) {
  const [toRevise, setToRevise] = useState(Boolean(issue.to_revise));
  const [applying, setApplying] = useState(false);
  const [markBusy, setMarkBusy] = useState(false);
  const [error, setError] = useState("");
  const tutorial = p.tutorialActive;
  const [evidenceRevealed, setEvidenceRevealed] = useState(false);
  const gate = tutorial && tutorialStep < 4 && !evidenceRevealed;
  const tone = findingTone(issue);
  const evidence = issue.evidence ?? [];
  const suggestion = issue.suggested_revision?.before && issue.suggested_revision.after ? issue.suggested_revision : null;
  const ready = issueHasSufficientEvidence(issue);
  const decided = Boolean(issue.decision);
  const blockedDecision = Boolean(p.busy) || decided || outdated || !ready || applying;
  const canKeep = issueAllows(issue, "keep_intentional");
  const canDismiss = issueAllows(issue, "false_positive");
  const toggleMark = async () => {
    if (!p.run) return;
    setMarkBusy(true); setError("");
    try {
      const next = await json<{ to_revise: boolean }>(`/projects/${p.run.project_id}/issues/${issue.id}/mark`, "POST", { to_revise: !toRevise });
      setToRevise(next.to_revise);
      p.markToRevise(issue.id, next.to_revise);
    } catch (cause) { setError(labelError(cause)); } finally { setMarkBusy(false); }
  };
  type Action = { key: string; label: string; run: () => void; disabled: boolean; pressed?: boolean };
  const actions: Action[] = [];
  if (!decided) {
    const all: Record<string, Action | null> = {
      apply: suggestion && issueAllows(issue, "apply_suggestion") ? { key: "apply", label: "采用改法", disabled: blockedDecision, run: () => {
        setApplying(true);
        // Bring the sentence into view first, so the change is seen where it happens.
        const mark = document.querySelector<HTMLElement>(`.finding-mark[data-finding="${issue.id}"]`);
        const box = mark?.getBoundingClientRect();
        const away = Boolean(mark && box && (box.top < 96 || box.bottom > window.innerHeight - 24));
        if (away) mark!.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
        window.setTimeout(() => void rewriteDraftText("draft-body", suggestion.before, suggestion.after, () => p.applySuggestion(issue)).then((ok) => {
          setApplying(false);
          if (!ok) setError("没能在草稿里准确找到这句话（可能已经改过）。正文没有变动，请手动修改。");
        }), away && !reducedMotion() ? 520 : 0);
      } } : null,
      mark: { key: "mark", label: toRevise ? "取消待修改" : "标为待修改", disabled: markBusy || !p.run, pressed: toRevise, run: () => void toggleMark() },
      keep: canKeep ? { key: "keep", label: tone === "state" ? "保留这个变化" : "是有意的", disabled: blockedDecision, run: () => void p.decide(issue, "keep_intentional").then((ok) => { if (ok && !tutorial) onDecided(issue.id); }) } : null,
      dismiss: canDismiss ? { key: "dismiss", label: "不是问题", disabled: blockedDecision, run: () => void p.decide(issue, "false_positive").then((ok) => { if (ok && !tutorial) onDecided(issue.id); }) } : null,
      edit: issueAllows(issue, "edit") ? { key: "edit", label: "改正文", disabled: Boolean(p.busy) || !evidence.length || outdated, run: () => p.startControlledEdit(issue) } : null,
    };
    // The preview's order: the action that fits the kind of finding first, then 标为待修改 / 是有意的 / 不是问题.
    const first = { high: ["apply", "edit", "mark"], mid: ["keep", "mark"], gap: ["mark"], state: ["keep", "dismiss"] }[tone].find((key) => all[key]);
    for (const key of [first, "mark", "keep", "dismiss", "apply", "edit"]) {
      const action = key ? all[key] : null;
      if (action && !actions.includes(action)) actions.push(action);
    }
  }

  return (
    <div className="finding-detail">
      <p className="finding-explain">{issue.explanation}</p>
      {gate ? (
        <div className="finding-gate">
          <p>下一步会展开前文依据和判断理由；这里只推进导览，不会替你处理这一条。</p>
          <Button kind="primary" className="tutorial-primary-action" disabled={Boolean(p.busy)} onClick={() => { setEvidenceRevealed(true); void p.beginEvidence(); }}>查看完整依据</Button>
        </div>
      ) : (
        <>
          <p className="label finding-label">依据</p>
          {evidence.length ? (
            <ul className="finding-evidence">
              {evidence.map((item) => (
                <li key={item.id}>
                  <button type="button" onClick={(event) => p.openEvidenceSource(issue, item, event.currentTarget)}>
                    <span className="finding-evidence-where">第 {item.chapter_number} 章{item.chapter_title ? ` · ${bareChapterTitle(item.chapter_title)}` : ""}</span>
                    <span className="finding-evidence-text">{item.excerpt}</span>
                  </button>
                </li>
              ))}
            </ul>
          ) : <p className="finding-hint">找不到可以核对的前文，暂时不能对这一条作决定。</p>}
          {issue.reasoning && issue.reasoning !== issue.explanation && <details className="finding-reasoning"><summary>为什么这样判断</summary><p>{issue.reasoning}</p></details>}
          {suggestion && (
            <>
              <p className="label finding-label">改法</p>
              <del className="finding-before">{suggestion.before}</del>
              <ins className="finding-after">{suggestion.after}</ins>
            </>
          )}
          {tone === "state" && !decided && issue.has_memory_proposal && <p className="finding-hint">这不是错误。保留后，全部处理完时点「审阅事实变化」，把新的状态记进资料。</p>}
          {outdated && <p className="finding-hint warn">草稿在检查之后改过，这一条针对的是先前的正文。重新检查后再决定。</p>}
          {!decided && !ready && <p className="finding-hint">依据不够充分，只能标为待修改，或者补写前文后重新检查。</p>}
          {!p.readOnly ? (
            <div className="author-decision">
              {issue.reused_decision && <p className="finding-decided">沿用你之前对同一句的判断。<a href={issue.reused_decision.review_path}>管理沿用的判断</a></p>}
              {decided && <p className="finding-decided"><Tag tone="solid">{decisionLabel(issue.decision?.decision)}</Tag>已记下，这一条留在列表里备查。</p>}
              {tutorial && tutorialStep === 4 && decided && <Button kind="primary" className="tutorial-decision-review" disabled={Boolean(p.busy)} onClick={() => void p.reviewDecision(issue)}>复习过了，继续导览</Button>}
              {actions.length > 0 && (
                <div className="finding-actions">
                  {actions.map((action, index) => <Button key={action.key} kind={index === 0 ? "primary" : "text"} className={action.key === "mark" ? "to-revise-action" : undefined} pressed={action.pressed} disabled={action.disabled} onClick={action.run}>{action.label}</Button>)}
                </div>
              )}
              {error && <p className="inline-error" role="alert">{error}</p>}
            </div>
          ) : <p className={tutorial ? "readonly tutorial-mobile-decision-note" : "readonly"}>{tutorial ? "手机上可以浏览完整依据；请在电脑上继续作出决定。" : "只读，不能在这里处理。"}</p>}
        </>
      )}
    </div>
  );
}

function Sources({ sources }: { sources: { source_id: string; source_type: string; label: string; excerpt: string }[] }) {
  if (!sources.length) return <p className="small-note">没有引用正文。</p>;
  return (
    <details className="sources">
      <summary>出处 {sources.length}</summary>
      <ul>{sources.map((source) => <li key={`${source.source_type}:${source.source_id}`}><strong>{readableKeys(source.label)}<span className="label"> · {sourceKindLabel(source.source_type)}</span></strong><p>{source.excerpt}</p></li>)}</ul>
    </details>
  );
}

/** 写前回顾 and 对照计划 results. */
function AnalysisPanel({ run, p }: { run: WritingAnalysisRun; p: ProjectState }) {
  const brief = run.analysis_type === "context_brief";
  const coverage = run.analysis?.draft_coverage;
  return (
    <section className={`analysis${run.is_stale ? " stale" : ""}`} aria-label={brief ? "写前回顾" : "对照计划"}>
      <SectionHead title={brief ? "写前回顾" : "对照计划"} aside={<span className="label">{run.is_stale ? "草稿改过，结果可能过时" : stageLabel(run.status)}</span>} />
      {activeAnalysis(run) && <p className="small-note">{stageLabel(run.stage)}。编辑器照常可用。</p>}
      {["failed", "timed_out", "cancelled"].includes(run.status) && <p className="inline-error">{labelRunFailure(run.error_code, brief ? "回顾" : "对照")}</p>}
      {run.analysis && (
        <>
          <p className="analysis-summary">{run.analysis.summary}</p>
          {brief && coverage && coverage.status !== "covered" && <p className="small-note">{coverage.status === "empty" ? "草稿还没有正文。" : "只覆盖了草稿的一部分（正文较长或部分句子没有引用）。"}</p>}
          {run.analysis.summary_sources && <Sources sources={run.analysis.summary_sources} />}
          <ol className="analysis-items">
            {run.analysis.items.map((item, index) => "section" in item ? (
              <li key={`${item.section}:${index}`}><span className="label">{briefSectionLabel[item.section]}</span><p>{readableKeys(item.text)}</p><Sources sources={item.sources} /></li>
            ) : "story_plan_id" in item ? (
              <li key={item.story_plan_id}><span className="analysis-item-head"><strong>{item.story_plan_title}</strong><Tag tone={item.status === "planned_covered" ? "solid" : item.status === "insufficient_evidence" ? "gap" : "mid"}>{alignmentStatusLabel[item.status]}</Tag></span><p>{item.explanation}</p><Sources sources={item.evidence} /></li>
            ) : null)}
          </ol>
        </>
      )}
      <footer className="analysis-foot">
        <span className="label">依据：第 {run.draft_revision ?? "—"} 次保存的草稿</span>
        {!p.readOnly && (
          <span className="actions">
            {activeAnalysis(run) && <Button kind="small" disabled={Boolean(p.analysisBusy)} onClick={() => void p.analysisAction(run, "cancel")}>取消</Button>}
            {retryableAnalysis(run) && <Button kind="small" disabled={Boolean(p.analysisBusy)} onClick={() => void p.analysisAction(run, "retry")}>重试</Button>}
          </span>
        )}
      </footer>
    </section>
  );
}

/** A check that is running, or that stopped without finishing: its stage, and cancel or retry.
    A finished check needs no line of its own; its time sits in the findings head. */
function RunStatus({ run, p, actions, visitor }: { run: Run; p: ProjectState; actions: boolean; visitor: boolean }) {
  if (run.status === "completed") return null;
  const kind = run.run_type === "memory_delta" ? "事实变化" : "检查";
  const blocked = Boolean(p.busy) || p.readOnly;
  const running = activeRun(run);
  return (
    <div className={`run-status status-${run.status}`} aria-live="polite">
      <p className="run-status-line">
        <strong>{running ? stageLabel(run.stage) : `${kind}没有完成`}</strong>
        <span className="label">{(run.attempt_number ?? 1) > 1 ? `第 ${run.attempt_number} 次 · ` : ""}{timeLabel(run.created_at)}</span>
      </p>
      {!running && <p className="inline-error">{labelRunFailure(run.error_code, run.run_type === "memory_delta" ? "事实整理" : "检查")}{actions && retryableRun(run) ? (visitor ? "重试会再用掉一次检查机会。" : "重试不会再扣字数。") : ""}</p>}
      {run.stage === "cancelling" && <p className="small-note">正在等模型返回；之后返回的结果会被丢弃，不会保存。</p>}
      {actions && (running || retryableRun(run)) && (
        <div className="finding-actions">
          {running && <Button kind="small" disabled={blocked} onClick={() => void p.cancelRun()}>{run.stage === "cancelling" ? "正在取消" : "取消检查"}</Button>}
          {retryableRun(run) && <Button kind="text" disabled={blocked} onClick={() => void p.retryRun()}>重试</Button>}
        </div>
      )}
    </div>
  );
}

/** 更多 → 这次检查的技术详情. */
function TechDialog({ run, paired, close }: { run: Run; paired: Run | null; close: () => void }) {
  return (
    <Dialog title="这次检查的技术详情" close={close}>
      {[run, ...(paired ? [paired] : [])].map((item) => {
        const metrics = item.provider_metrics ?? item.metrics;
        const provenance = item.provenance ?? item.metrics?.provenance;
        return (
          <dl key={item.run_id} className="tech-grid">
            <div><dt>{item.run_type === "memory_delta" ? "事实变化" : "检查"}</dt><dd>{item.status === "completed" ? "已完成" : stageLabel(item.stage)} · {timeLabel(item.completed_at ?? item.created_at)}</dd></div>
            <div><dt>编号</dt><dd>{item.run_id}</dd></div>
            <div><dt>耗时</dt><dd>检查 {durationLabel(item.duration_ms)} · 模型 {durationLabel(metrics?.latency_ms)}</dd></div>
            <div><dt>用量</dt><dd>{metrics?.input_tokens == null ? "不可用" : `输入 ${metrics.input_tokens} / 输出 ${metrics.output_tokens ?? 0}`}{metrics?.cost_available ? ` · ¥${metrics.cost_cny}` : ""}</dd></div>
            <div><dt>依据版本</dt><dd>正文第 {item.source_revision} 版 · 事实库第 {item.source_memory_version ?? provenance?.source_memory_version ?? "—"} 版</dd></div>
            {provenance && <div><dt>模型</dt><dd>{provenance.provider_label} / {provenance.model_label} · {provenance.prompt_version}</dd></div>}
          </dl>
        );
      })}
    </Dialog>
  );
}

/** After all findings are handled: which facts changed, each to accept, reject or edit. */
function FactReview({ p }: { p: ProjectState }) {
  const blocked = p.readOnly || Boolean(p.busy);
  const changeSet = p.changeSet!;
  return (
    <form id="fact-review" className="fact-review" aria-label="审阅事实变化" onSubmit={(event) => void p.commit(event)}>
      <SectionHead title="审阅事实变化" aside={<span className="label">{changeSet.items.length} 条</span>} />
      <p className="lede">这些变化不会自动写进资料。逐条决定，全部确认后一次更新。</p>
      {changeSet.items.map((item) => (
        <article key={item.id} className="change">
          <div className="change-flow">
            <div><p className="label">之前</p><p className="change-text">{item.before ? `${String(item.before.subject)} · ${predicateLabel(item.before.predicate)}：${String(item.before.value)}` : "（资料里还没有）"}</p></div>
            <span className="change-arrow" aria-hidden="true">→</span>
            <div><p className="label">之后</p><p className="change-text">{memoryTypeLabel(String(item.after.memory_type))} · {String(item.after.subject)} · {predicateLabel(item.after.predicate)}：{String(item.after.value)}</p></div>
          </div>
          <fieldset className="radio-row">
            <legend className="sr-only">处理这一条</legend>
            <label><input type="radio" name={item.id} value="accepted" defaultChecked disabled={blocked} />记下</label>
            <label><input type="radio" name={item.id} value="rejected" disabled={blocked} />不记</label>
            <label><input type="radio" name={item.id} value="edited" disabled={blocked} />改一下再记</label>
          </fieldset>
          <div className="edit-fields">
            <label className="field"><span className="field-label">类型</span><select name={`edit:${item.id}:memory_type`} defaultValue={String(item.after.memory_type)} disabled={blocked}>{memoryTypes.map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label>
            <label className="field"><span className="field-label">对象</span><input name={`edit:${item.id}:subject`} defaultValue={String(item.after.subject)} disabled={blocked} /></label>
            <label className="field"><span className="field-label">关系</span><PredicateSelect name={`edit:${item.id}:predicate`} value={String(item.after.predicate)} disabled={blocked} /></label>
            <label className="field wide"><span className="field-label">内容</span><textarea name={`edit:${item.id}:value`} defaultValue={String(item.after.value)} disabled={blocked} rows={2} /></label>
          </div>
        </article>
      ))}
      <Button kind="primary" size="lg" type="submit" disabled={blocked}>确认并更新资料</Button>
    </form>
  );
}

type FocusSize = "small" | "medium" | "large";
/** 专注写作: the draft alone on the page, with type settings and an optional list of findings. */
function FocusEditor({ p, close, pick }: { p: ProjectState; close: () => void; pick: (issue: Issue, element: HTMLElement) => void }) {
  useScrollLock();
  const { ref, onKeyDown } = useFocusTrap<HTMLElement>(close);
  const [size, setSize] = useState<FocusSize>("medium");
  const [leading, setLeading] = useState<"compact" | "comfortable" | "airy">("comfortable");
  const [width, setWidth] = useState<"narrow" | "medium" | "wide">("medium");
  const [listOpen, setListOpen] = useState(false);
  const text = useDraftText("focus-draft-body", p.draft?.body ?? "");
  const saving = ["保存草稿", "保存修改", "正在重试记录决定"].includes(p.busy);
  const issues = p.run?.issues ?? [];
  return (
    <section ref={ref} className="focus" role="dialog" aria-modal="true" aria-label="专注写作" data-size={size} data-leading={leading} data-width={width} data-list={listOpen ? "open" : "closed"} onKeyDown={onKeyDown}>
      <header className="focus-head">
        <span className="label">第 {p.draft?.chapter_number ?? "—"} 章 · {p.project?.title}</span>
        <div className="focus-settings" aria-label="显示设置">
          <WritingTools targetId="focus-draft-body" disabled={Boolean(p.busy) || Boolean(p.pendingControlledDecision) || !p.draft} />
          <label>字号<select value={size} onChange={(event) => setSize(event.target.value as FocusSize)}><option value="small">17</option><option value="medium">19</option><option value="large">21</option></select></label>
          <label>行距<select value={leading} onChange={(event) => setLeading(event.target.value as typeof leading)}><option value="compact">紧</option><option value="comfortable">中</option><option value="airy">松</option></select></label>
          <label>栏宽<select value={width} onChange={(event) => setWidth(event.target.value as typeof width)}><option value="narrow">窄</option><option value="medium">中</option><option value="wide">宽</option></select></label>
        </div>
        <Button kind="small" expanded={listOpen} onClick={() => setListOpen((value) => !value)}>检查结果 {issues.length}</Button>
        <Button kind="small" onClick={close} label="退出专注写作">退出</Button>
      </header>
      {p.controlled && <p className="focus-note">这次修改对应选中的那一条；保存时会一并记下你的处理。</p>}
      <div className="focus-canvas">
        <div className="focus-paper">
          <div className="focus-column">
            <label className="focus-title"><span className="sr-only">章节标题</span><input value={p.draft?.title ?? ""} disabled={Boolean(p.busy) || Boolean(p.pendingControlledDecision)} onChange={(event) => p.draft && p.setDraft({ ...p.draft, title: event.target.value })} /></label>
            <RichDraftEditor id="focus-draft-body" label="草稿正文" value={p.draft?.body ?? ""} format={p.draft?.body_format ?? "plain_text"} disabled={Boolean(p.busy) || Boolean(p.pendingControlledDecision)} onChange={(body, body_format) => p.draft && p.setDraft({ ...p.draft, body, body_format })} />
          </div>
        </div>
        <aside className="focus-list" aria-label="检查结果">
          {p.run ? (
            <ol>
              {issues.map((issue, index) => (
                <li key={issue.id}>
                  <button type="button" onClick={(event) => pick(issue, event.currentTarget)}>
                    <Num>{index + 1}</Num>
                    <span><FindingTag issue={issue} /><span className="focus-claim">{issue.claim_text || issue.explanation}</span></span>
                  </button>
                </li>
              ))}
              {!issues.length && <li className="small-note">这次检查没有需要处理的地方。</li>}
            </ol>
          ) : <p className="small-note">还没检查。</p>}
        </aside>
      </div>
      <footer className="focus-foot">
        <span className="label">{formatCount(writtenChars(text))} 字</span>
        <span className={`save-state ${saving ? "saving" : p.dirty ? "unsaved" : "saved"}`}><i aria-hidden="true" />{saving ? "保存中" : p.dirty ? "未保存 · 停笔几秒后自动保存" : "已保存"}</span>
        <Button kind="primary" disabled={!p.draft || (!p.dirty && !p.pendingControlledDecision) || Boolean(p.busy)} busy={saving} onClick={() => void p.save()}>{saving ? "正在保存" : p.pendingControlledDecision ? "重试记录决定" : p.controlled ? "保存修改" : "保存"}</Button>
      </footer>
    </section>
  );
}
