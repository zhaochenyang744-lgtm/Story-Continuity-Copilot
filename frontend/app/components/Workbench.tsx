"use client";

import {
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  MouseEvent as ReactMouseEvent,
  MouseEventHandler,
  Ref,
  ReactNode,
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import Image from "next/image";
import { usePathname, useRouter } from "next/navigation";
import { json, labelError, request, type ApiFailure } from "../api";
import type {
  AuthorCharacterPlan,
  AuthorContext,
  AuthorStoryPlan,
  AuthorWorldPlan,
  ChangeSet,
  Chapter,
  CharacterAliasSnapshot,
  Draft,
  ForeshadowCandidate,
  ForeshadowRecord,
  ForeshadowSnapshot,
  Issue,
  MemoryCoverage,
  MemoryDelta,
  MemoryInitialization,
  Memory,
  Onboarding,
  Project,
  ProjectSummary,
  RevisionPlanCandidate,
  RevisionTask,
  RevisionTaskPriority,
  RevisionTaskSnapshot,
  Run,
  SourceChangeSet,
  TutorialEvent,
  TutorialProgress,
  User,
  WritingAnalysisRun,
} from "../model";

// The optional catch-all page remounts its client tree between route segments.
// Keep the browser-owned session bootstrap for the lifetime of this module so
// ordinary in-app navigation does not turn into another authentication check.
let bootstrappedUser: User | null | undefined;
let sessionBootstrap: Promise<User | null> | null = null;
let rememberedGlobalNavCollapsed: boolean | undefined;
const globalNavStorageKey = "story-continuity:global-nav-collapsed";
const publicAuthPaths = ["/login", "/register", "/password-reset", "/password-reset/confirm", "/verify-email"];
const isPublicAuthPath = (value: string) => publicAuthPaths.includes(value);

type Home = {
  continue_work?: {
    project_id: string;
    project_title: string;
    draft_id: string;
    draft_title: string;
    draft_revision: number;
    next_action: string;
  } | null;
  recent_projects: {
    project_id: string;
    title: string;
    status: ProjectSummary["status"];
    updated_at: string;
  }[];
  pending_continuity: {
    project_id: string;
    title: string;
    high: number;
    medium: number;
    low: number;
    continuity_status: "unchecked" | "checked_clear" | "pending";
  }[];
};
type ImportPreview = {
  import_id: string;
  file: { name: string; size: number; sha256: string; format: string };
  detected: {
    strategy: string;
    chapter_count: number;
    chapters: {
      preview_id: string;
      title: string;
      order: number;
      character_count: number;
      excerpt: string;
    }[];
  };
  warnings: string[];
};
type EvidenceItem = NonNullable<Issue["evidence"]>[number];
type ReadonlySourceRecord = {
  recordId: string;
  subject: string;
  chapterId: string;
  chapterNumber: number;
  chapterTitle: string;
  spanId: string;
  excerpt: string;
  sourcePath?: string;
  sourceRevision?: number;
  memoryType?: string;
  reviewStatus?: string;
  relation?: string;
  sufficiency?: string;
};
type ProjectVisualStatus = "active" | "paused" | "completed" | "archived";
type TutorialStep = 1 | 2 | 3 | 4 | 5;

function useDocumentScrollLock() {
  useEffect(() => {
    const root = document.documentElement;
    const previousOverflow = root.style.overflow;
    const previousPaddingRight = root.style.paddingRight;
    const scrollbarWidth = Math.max(0, window.innerWidth - root.clientWidth);
    root.style.overflow = "hidden";
    if (scrollbarWidth > 0) root.style.paddingRight = `${scrollbarWidth}px`;
    return () => {
      root.style.overflow = previousOverflow;
      root.style.paddingRight = previousPaddingRight;
    };
  }, []);
}

const tabs = [
  ["overview", "项目概览"],
  ["outline", "大纲"],
  ["characters", "角色库"],
  ["world", "世界观"],
  ["memory", "Story Memory"],
  ["workspace", "写作与检查"],
] as const;
const stage = (s: string): string =>
  (
    ({
      queued: "已排队",
      preparing_draft: "准备草稿",
      retrieving_confirmed_facts: "检索已确认事实",
      comparing_evidence: "比对证据",
      assembling_reviewable_results: "整理可审阅结果",
      binding_context: "绑定写作上下文",
      analyzing_layers: "分层分析计划、事实与正文",
      assembling_results: "整理分析结果",
      running_continuity: "运行增量 Continuity",
      running_memory_delta: "运行 Memory Delta",
      running: "运行中",
      pending: "待处理",
      processing: "处理中",
      succeeded: "已完成",
      cancelling: "正在安全取消",
      completed: "检查完成",
      timed_out: "检查超时",
      failed: "检查失败",
      cancelled: "已取消",
    }) as Record<string, string>
  )[s] ?? "未知检查状态";
const activeRun = (run: Run | null) => Boolean(run && ["queued", "running"].includes(run.status));
const retryableRun = (run: Run | null) => Boolean(run && ["failed", "timed_out", "cancelled"].includes(run.status) && (run.status !== "failed" || run.retryable));
const activeAnalysis = (run: WritingAnalysisRun | null) => Boolean(run && ["queued", "running"].includes(run.status));
const retryableAnalysis = (run: WritingAnalysisRun | null) => Boolean(run && ["failed", "timed_out", "cancelled"].includes(run.status) && (run.status !== "failed" || run.retryable));
const durationLabel = (value?: number | null) => value == null ? "尚不可用" : value < 1000 ? `${value} ms` : `${(value / 1000).toFixed(2)} s`;
const timestampLabel = (value?: string | null) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
const statusLabel = (s?: string): string =>
  (
    ({
      high: "高风险",
      medium: "中风险",
      low: "低风险",
      active: "进行中",
      archived: "已归档",
      paused: "已暂停",
      complete: "已完成",
      completed: "已完成",
      checked_clear: "检查通过",
      unchecked: "尚未检查",
      pending: "待处理",
    }) as Record<string, string>
  )[s ?? ""] ?? (s ? "未知状态" : "—");
const projectVisualStatus = (status: string): ProjectVisualStatus => {
  if (status === "complete" || status === "completed") return "completed";
  if (status === "paused" || status === "archived") return status;
  return "active";
};
const memoryTypeLabel = (value: string) =>
  ({
    static_canon: "固定设定",
    dynamic_state: "当前状态",
    event_timeline: "事件时间线",
    character_knowledge: "角色所知",
    open_thread: "未解线索",
  })[value] ?? "未分类事实";
const reviewStatusLabel = (value: string) =>
  ({ author_confirmed: "作者已确认", pending: "待确认", rejected: "已拒绝" })[value] ?? "待确认";
const evidenceStatusLabel = (value: string) =>
  ({ sufficient: "证据充分", insufficient: "证据不足", unavailable: "证据不可用" })[value] ?? "证据状态未知";
const coverageStatusLabel = (value?: string) =>
  ({ required: "待初始化", in_review: "审核中", ready_partial: "部分就绪", ready_current: "当前版本就绪", update_pending: "待审核更新" })[value ?? ""] ?? "尚未提供";
const categoryLabel = (value: string) =>
  ({
    attribute: "属性事实",
    location_action: "位置与动作",
    timeline: "时间线",
    character_knowledge: "角色所知",
    object_state: "物件状态",
    relationship: "角色关系",
    world_rule: "世界规则",
    event_status: "事件进展",
  })[value] ?? "其他连续性问题";
const predicateLabel = (value: unknown) =>
  ({
    holder: "持有人 / 存放状态",
    status: "状态",
    next_action: "下一步行动",
    ring_condition: "触发条件",
    does_not_know: "尚未知晓",
    location: "所在位置",
    relationship: "关系",
    goal: "目标",
    occurred_at: "发生时间",
    time: "时间",
    received: "接收记录",
  })[
    String(value)
  ] ?? "其他属性";
const roleTypeLabel = (value: string) =>
  ({ protagonist: "主角", antagonist: "对立角色", ally: "支持角色", supporting: "配角" })[value] ?? "其他角色";
const worldTypeLabel = (value: string) =>
  ({ location: "地点", rule: "规则", organization: "组织", object: "物件", term: "术语" })[value] ?? "其他资料";
const decisionStatusLabel = (value: string) =>
  ({ pending: "待决定", accepted: "已接受", rejected: "已拒绝", edited: "编辑后接受" })[value] ?? "决定状态未知";
const nextActionLabel = (value: string) =>
  ({ continue_draft: "继续写作", review_issues: "审阅问题", initialize_memory: "建立 Story Memory" })[value] ?? "继续处理作品";
const lineageStatusLabel = (value?: string | null) =>
  ({ current: "当前版本", stale: "已过期", pending_decision_validation: "等待决策校验" })[value ?? ""] ?? "谱系状态未知";
const tutorialEvents: Record<TutorialStep, TutorialEvent | null> = {
  1: null,
  2: "memory_source_opened",
  3: "continuity_issue_located",
  4: "evidence_opened",
  5: "author_decision_recorded",
};
function Button({
  children,
  className = "secondary",
  disabled,
  ariaPressed,
  ariaCurrent,
  ariaBusy,
  ariaLabel,
  ariaExpanded,
  buttonRef,
  title,
  onClick,
  type = "button",
}: {
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  ariaPressed?: boolean;
  ariaCurrent?: "page";
  ariaBusy?: boolean;
  ariaLabel?: string;
  ariaExpanded?: boolean;
  buttonRef?: Ref<HTMLButtonElement>;
  title?: string;
  onClick?: MouseEventHandler<HTMLButtonElement>;
  type?: "button" | "submit";
}) {
  return (
    <button
      ref={buttonRef}
      type={type}
      className={className}
      disabled={disabled}
      aria-disabled={disabled || undefined}
      aria-pressed={ariaPressed}
      aria-current={ariaCurrent}
      aria-busy={ariaBusy || undefined}
      aria-label={ariaLabel}
      aria-expanded={ariaExpanded}
      title={title}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

type TutorialGuidanceTarget = {
  element: HTMLElement;
  key: string;
  message: string;
};
type TutorialHintState = {
  left: number;
  message: string;
  placement: "above" | "below";
  top: number;
  width: number;
};

let tutorialGuidanceRequestSequence = 0;
let tutorialGuidanceConsumedSequence = 0;
const tutorialGuidanceRequestEvent = "story-tutorial-guidance-request";

function emitTutorialGuidanceRequest() {
  tutorialGuidanceRequestSequence += 1;
  window.dispatchEvent(new Event(tutorialGuidanceRequestEvent));
}

const tutorialTargetInViewport = (element: HTMLElement) => {
  const rect = element.getBoundingClientRect();
  return (
    rect.width > 0 &&
    rect.height > 0 &&
    rect.bottom > 0 &&
    rect.top < window.innerHeight &&
    rect.right > 0 &&
    rect.left < document.documentElement.clientWidth
  );
};

function resolveTutorialGuidanceTarget({
  evidenceOpen,
  readOnly,
  sourceOpen,
  step,
  tab,
}: {
  evidenceOpen: boolean;
  readOnly: boolean;
  sourceOpen: boolean;
  step: TutorialStep;
  tab: string;
}): TutorialGuidanceTarget | null {
  if (sourceOpen) {
    const close = document.querySelector<HTMLElement>(".source-layer .close");
    return close
      ? { element: close, key: "source-close", message: "看完来源后，关闭并继续" }
      : null;
  }
  const primary = document.querySelector<HTMLElement>(
    ".tutorial-primary-action:not(:disabled)",
  );
  if (step === 1) {
    if (tab !== "memory")
      return primary
        ? { element: primary, key: "memory-navigation", message: "下一步：打开 Story Memory" }
        : null;
    const source = document.querySelector<HTMLElement>(
      ".memory-source:not(:disabled)",
    );
    if (source && tutorialTargetInViewport(source))
      return {
        element: source,
        key: "memory-source",
        message: "下一步：查看这条事实的章节来源",
      };
    return primary
      ? { element: primary, key: "memory-locate", message: "点击定位下一步" }
      : null;
  }
  if (step === 2)
    return primary
      ? { element: primary, key: "workspace-navigation", message: "下一步：进入连续性检查" }
      : null;
  if (step === 3) {
    if (tab !== "workspace")
      return primary
        ? { element: primary, key: "workspace-return", message: "下一步：返回写作与检查" }
        : null;
    const issue =
      document.querySelector<HTMLElement>(".issue-row.severity-high") ??
      document.querySelector<HTMLElement>(".issue-row");
    if (issue && tutorialTargetInViewport(issue))
      return {
        element: issue,
        key: "high-risk-issue",
        message: "下一步：打开这条高风险问题",
      };
    return primary
      ? { element: primary, key: "issue-locate", message: "点击定位下一步" }
      : null;
  }
  if (step === 4) {
    if (evidenceOpen) {
      const decision = document.querySelector<HTMLElement>(
        readOnly ? ".tutorial-mobile-decision-note" : ".author-decision",
      );
      return decision
        ? {
            element: decision,
            key: readOnly ? "mobile-decision-note" : "author-decision",
            message: readOnly
              ? "请在桌面端继续完成作者决定"
              : "请选择一种处理方式，教学不会替你决定",
          }
        : null;
    }
    const issue =
      document.querySelector<HTMLElement>(".issue-row.severity-high") ??
      document.querySelector<HTMLElement>(".issue-row");
    return issue
      ? { element: issue, key: "decision-return", message: "下一步：重新打开待审问题" }
      : primary
        ? { element: primary, key: "decision-locate", message: "点击定位下一步" }
        : null;
  }
  return primary
    ? {
        element: primary,
        key: "tutorial-complete",
        message: "完成教学后即可导入自己的作品",
      }
    : null;
}

function TutorialGuidance({
  active,
  busy,
  evidenceOpen,
  projectId,
  readOnly,
  requestId,
  sourceOpen,
  step,
  tab,
}: {
  active: boolean;
  busy: boolean;
  evidenceOpen: boolean;
  projectId: string;
  readOnly: boolean;
  requestId: number;
  sourceOpen: boolean;
  step: TutorialStep;
  tab: string;
}) {
  const [activityEpoch, setActivityEpoch] = useState(0);
  const [hint, setHint] = useState<TutorialHintState | null>(null);
  const handledRequest = useRef(0);
  const manualScrollGraceUntil = useRef(0);
  const pulsedSteps = useRef(new Set<string>());
  const hintId = "tutorial-guidance-hint";
  const contextKey = `${projectId}:${step}:${tab}:${sourceOpen ? "source" : "page"}:${evidenceOpen ? "evidence" : "plain"}:${readOnly ? "readonly" : "editable"}`;

  useEffect(() => {
    if (!active) return;
    const markActivity = (event: Event) => {
      if (
        event.type === "scroll" &&
        window.performance.now() < manualScrollGraceUntil.current
      )
        return;
      setActivityEpoch((value) => value + 1);
    };
    window.addEventListener("click", markActivity, true);
    window.addEventListener("keydown", markActivity, true);
    window.addEventListener("touchstart", markActivity, true);
    window.addEventListener("wheel", markActivity, { capture: true, passive: true });
    window.addEventListener("scroll", markActivity, true);
    return () => {
      window.removeEventListener("click", markActivity, true);
      window.removeEventListener("keydown", markActivity, true);
      window.removeEventListener("touchstart", markActivity, true);
      window.removeEventListener("wheel", markActivity, true);
      window.removeEventListener("scroll", markActivity, true);
    };
  }, [active]);

  useEffect(() => {
    if (requestId > handledRequest.current)
      manualScrollGraceUntil.current = window.performance.now() + 1_200;
    let idleTimer: ReturnType<typeof setTimeout> | null = null;
    let initialized = false;
    let attached: HTMLElement | null = null;
    let previousDescription: string | null = null;
    const detach = () => {
      if (!attached) return;
      attached.classList.remove("tutorial-guidance-target", "is-pulsing");
      attached.removeAttribute("data-tutorial-guidance-target");
      attached.removeAttribute("data-tutorial-guidance-key");
      if (previousDescription === null) attached.removeAttribute("aria-describedby");
      else attached.setAttribute("aria-describedby", previousDescription);
      attached = null;
      previousDescription = null;
    };
    const position = (target: HTMLElement, message: string) => {
      const rect = target.getBoundingClientRect();
      const viewportWidth = document.documentElement.clientWidth;
      const width = Math.min(272, Math.max(180, viewportWidth - 32));
      const left = Math.min(
        viewportWidth - width - 16,
        Math.max(16, rect.left + rect.width / 2 - width / 2),
      );
      const placement =
        rect.bottom + 92 > window.innerHeight && rect.top > 100 ? "above" : "below";
      setHint({
        left,
        message,
        placement,
        top: placement === "above" ? rect.top - 10 : rect.bottom + 10,
        width,
      });
    };
    const attach = (target: TutorialGuidanceTarget, automatic: boolean) => {
      detach();
      attached = target.element;
      previousDescription = attached.getAttribute("aria-describedby");
      const descriptions = new Set(
        `${previousDescription ?? ""} ${hintId}`.trim().split(/\s+/).filter(Boolean),
      );
      attached.setAttribute("aria-describedby", [...descriptions].join(" "));
      attached.setAttribute("data-tutorial-guidance-target", "true");
      attached.setAttribute("data-tutorial-guidance-key", target.key);
      attached.classList.add("tutorial-guidance-target");
      const pulseKey = `${projectId}:${step}`;
      if (automatic && !pulsedSteps.current.has(pulseKey)) {
        pulsedSteps.current.add(pulseKey);
        attached.classList.add("is-pulsing");
      }
      position(attached, target.message);
    };
    const resolve = () =>
      resolveTutorialGuidanceTarget({
        evidenceOpen,
        readOnly,
        sourceOpen,
        step,
        tab,
      });
    const attempt = () => {
      if (!initialized || !active || busy || attached || idleTimer) return;
      const target = resolve();
      if (!target) return;
      if (requestId > handledRequest.current) {
        handledRequest.current = requestId;
        if (requestId > tutorialGuidanceConsumedSequence) {
          tutorialGuidanceConsumedSequence = requestId;
          attach(target, false);
          return;
        }
      }
      idleTimer = setTimeout(() => {
        idleTimer = null;
        const current = resolve();
        if (current) attach(current, true);
      }, 12_000);
    };
    const initializeTimer = window.setTimeout(() => {
      setHint(null);
      initialized = true;
      if (active && !busy) attempt();
    }, 0);
    const observer = new MutationObserver(attempt);
    observer.observe(document.body, { childList: true, subtree: true });
    const updatePosition = () => {
      if (!attached) return;
      const current = resolve();
      if (current?.element === attached) position(attached, current.message);
    };
    window.addEventListener("resize", updatePosition);
    return () => {
      if (idleTimer) clearTimeout(idleTimer);
      window.clearTimeout(initializeTimer);
      observer.disconnect();
      window.removeEventListener("resize", updatePosition);
      detach();
    };
  }, [active, activityEpoch, busy, contextKey, evidenceOpen, projectId, readOnly, requestId, sourceOpen, step, tab]);

  if (!hint) return null;
  return (
    <div
      id={hintId}
      className={`tutorial-guidance-hint ${hint.placement}`}
      role="status"
      aria-live="polite"
      style={{ left: hint.left, top: hint.top, width: hint.width }}
    >
      {hint.message}
    </div>
  );
}
function BrandMark() {
  return (
    <span className="brand-asset">
      <Image className="brand-lockup" src="/assets/brand/story-continuity-lockup.svg" alt="Story Continuity" width={196} height={48} priority />
      <Image className="brand-symbol" src="/assets/brand/story-continuity-mark.svg" alt="Story Continuity" width={48} height={48} priority />
    </span>
  );
}

const avatarPresets: { id: User["avatar_preset"]; label: string; description: string; src: string }[] = [
  { id: "continuity_violet", label: "连续线", description: "沉静的紫色编辑肖像", src: "/assets/avatars/continuity-violet.webp" },
  { id: "archive_blue", label: "档案蓝", description: "冷静的蓝色档案肖像", src: "/assets/avatars/archive-blue.webp" },
  { id: "folio_rose", label: "书页玫", description: "温和的玫色书页肖像", src: "/assets/avatars/folio-rose.webp" },
  { id: "signal_amber", label: "信号琥珀", description: "清晰的琥珀色创作肖像", src: "/assets/avatars/signal-amber.webp" },
];

const avatarSource = (preset: User["avatar_preset"] | undefined) =>
  avatarPresets.find((item) => item.id === preset)?.src ?? avatarPresets[0].src;

function ProfileAvatar({ user, className = "" }: { user: User; className?: string }) {
  return (
    <span className={`profile-avatar avatar-${user.avatar_preset || "continuity_violet"} ${className}`.trim()} aria-hidden="true">
      <Image className="profile-avatar-image" src={avatarSource(user.avatar_preset)} alt="" width={512} height={512} sizes="(max-width: 760px) 72px, 112px" />
    </span>
  );
}
function Chevron({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <path d="m5.5 7.5 4.5 4.5 4.5-4.5" />
    </svg>
  );
}
function EmptyManuscriptVisual() {
  return (
    <Image
      className="empty-manuscript-visual"
      src="/assets/v120/empty-manuscript-alpha.webp"
      alt="空白手稿由紫色连续性线索相连"
      width={1358}
      height={838}
      sizes="(max-width: 1023px) 230px, 280px"
    />
  );
}
function EmptyLibraryVisual() {
  return (
    <Image
      className="empty-library-visual"
      src="/assets/v120/empty-library-alpha.webp"
      alt="打开的空白手稿档案与紫色连续性线索"
      width={1672}
      height={745}
      sizes="(max-width: 1023px) 360px, 480px"
    />
  );
}
function TutorialCompleteVisual() {
  return (
    <Image
      className="tutorial-complete-visual"
      src="/assets/v120/tutorial-complete-alpha.webp"
      alt="连续性线索已收束的完整手稿档案"
      width={944}
      height={1187}
      sizes="(max-width: 1023px) 280px, 360px"
    />
  );
}
function MoreMenu({ children }: { children: ReactNode }) {
  return (
    <details className="more-menu">
      <summary>更多<Chevron className="more-chevron" /></summary>
      <div role="menu" aria-label="更多操作">{children}</div>
    </details>
  );
}
function I({ children }: { children: string }) {
  return (
    <span className="icon" aria-hidden="true">
      {children}
    </span>
  );
}
function Icon({ name }: { name: "home" | "library" | "overview" | "outline" | "users" | "world" | "memory" | "pen" | "save" | "play" | "profile" | "security" | "tutorial" | "logout" }) {
  const paths: Record<string, ReactNode> = {
    home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z" /></>,
    library: <><rect x="4" y="3" width="16" height="18" rx="2" /><path d="M8 7h8M8 11h8M8 15h6" /></>,
    overview: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    outline: <><path d="M8 6h12M8 12h12M8 18h12" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 20c.5-3 2.5-5 6-5s5.5 2 6 5M17 11c2.2 0 4 1.7 4 4M16.5 5.2a3 3 0 0 1 0 5.6" /></>,
    world: <><path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z" /><path d="M3.5 12h17M12 3c2.5 2.5 2.5 13.5 0 18M12 3c-2.5 2.5-2.5 13.5 0 18" /></>,
    memory: <><path d="M12 4a3 3 0 0 1 5.5 1.6A3.5 3.5 0 1 1 18 12c0 4-2.3 7-6 8-3.7-1-6-4-6-8a3.5 3.5 0 1 1 .5-6.4A3 3 0 0 1 12 4Z" /><path d="M9.5 12h5M12 9.5v5" /></>,
    pen: <><path d="m4 20 4.2-1 10-10a2.8 2.8 0 0 0-4-4l-10 10Z" /><path d="m13 6 4 4M4 20l1-4" /></>,
    save: <><path d="M5 3h12l3 3v15H4V4a1 1 0 0 1 1-1Z" /><path d="M8 3v6h8V3M8 21v-7h8v7" /></>,
    play: <><path d="m8 5 11 7-11 7Z" /></>,
    profile: <><circle cx="12" cy="8" r="4" /><path d="M4 21c.7-4.4 3.3-7 8-7s7.3 2.6 8 7" /></>,
    security: <><path d="M12 3 5 6v5c0 4.7 2.8 8.1 7 10 4.2-1.9 7-5.3 7-10V6Z" /><path d="m9 12 2 2 4-4" /></>,
    tutorial: <><path d="M4 5.5A2.5 2.5 0 0 1 6.5 3H11v16H6.5A2.5 2.5 0 0 0 4 21.5ZM20 5.5A2.5 2.5 0 0 0 17.5 3H13v16h4.5a2.5 2.5 0 0 1 2.5 2.5Z" /></>,
    logout: <><path d="M10 4H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h5M14 8l4 4-4 4M8 12h10" /></>,
  };
  return <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export function Workbench() {
  const router = useRouter(),
    pathname = usePathname();
  const [user, setUser] = useState<User | null>(() => bootstrappedUser ?? null),
    [ready, setReady] = useState(() => bootstrappedUser !== undefined),
    [home, setHome] = useState<Home | null>(null),
    [onboarding, setOnboarding] = useState<Onboarding | null>(null),
    [projects, setProjects] = useState<ProjectSummary[]>([]),
    [authorProjects, setAuthorProjects] = useState<ProjectSummary[] | null>(null);
  const [globalNavCollapsed, setGlobalNavCollapsed] = useState(() => rememberedGlobalNavCollapsed ?? false);
  const [project, setProject] = useState<Project | null>(null),
    [chapters, setChapters] = useState<Chapter[]>([]),
    [memories, setMemories] = useState<Memory[]>([]),
    [draft, setDraft] = useState<Draft | null>(null),
    [saved, setSaved] = useState<Draft | null>(null),
    [run, setRun] = useState<Run | null>(null),
    [pairedRun, setPairedRun] = useState<Run | null>(null),
    [contextBrief, setContextBrief] = useState<WritingAnalysisRun | null>(null),
    [planAlignment, setPlanAlignment] = useState<WritingAnalysisRun | null>(null),
    [analysisBusy, setAnalysisBusy] = useState<"context_brief" | "plan_alignment" | "">(""),
    [initialization, setInitialization] = useState<MemoryInitialization | null>(null),
    [memoryDelta, setMemoryDelta] = useState<MemoryDelta | null>(null),
    [coverage, setCoverage] = useState<MemoryCoverage | null>(null);
  const [authorContext, setAuthorContext] = useState<AuthorContext | null>(null),
    [authorBusy, setAuthorBusy] = useState("");
  const [outline, setOutline] = useState<{
      chapter_nodes?: {
        id: string;
        chapter_number: number;
        title: string;
        summary: string;
        status: string;
      }[];
    } | null>(null),
    [characters, setCharacters] = useState<
      {
        id: string;
        name: string;
        role_type: string;
        identity: string;
        goal: string;
        current_state: string;
        knowledge_boundary: string;
      }[]
    >([]),
    [world, setWorld] = useState<
      { id: string; entry_type: string; name: string; summary: string }[]
    >([]);
  const [busy, setBusy] = useState(""),
    [notice, setNotice] = useState(""),
    [error, setError] = useState<unknown>(null),
    [selected, setSelected] = useState<Issue | null>(null),
    [controlled, setControlled] = useState<Issue | null>(null),
    [locallyResolvedIssueIds, setLocallyResolvedIssueIds] = useState<string[]>(
      [],
    ),
    [changeSet, setChangeSet] = useState<ChangeSet | null>(null);
  const [switchTo, setSwitchTo] = useState<string | null>(null),
    [switchSaving, setSwitchSaving] = useState(false),
    [switchSaveFailed, setSwitchSaveFailed] = useState(false),
    [resetOpen, setResetOpen] = useState(false),
    [metaOpen, setMetaOpen] = useState(false),
    [archiveOpen, setArchiveOpen] = useState(false),
    [userMenuOpen, setUserMenuOpen] = useState(false),
    [preview, setPreview] = useState<ImportPreview | null>(null),
    [q, setQ] = useState(""),
    [filter, setFilter] = useState(""),
    [sort, setSort] = useState("updated_desc"),
    [onlyIssues, setOnlyIssues] = useState(false),
    [small, setSmall] = useState(false),
    [sourceRecord, setSourceRecord] = useState<ReadonlySourceRecord | null>(null),
    [tutorialProgress, setTutorialProgress] = useState<TutorialProgress | null>(null);
  const [tutorialGuidanceRequest, setTutorialGuidanceRequest] = useState(
    tutorialGuidanceRequestSequence,
  );
  const epoch = useRef(0),
    activeProjectRequest = useRef<AbortController | null>(null),
    switchSavePending = useRef(false),
    trigger = useRef<HTMLElement | null>(null),
    sourceTrigger = useRef<HTMLButtonElement | null>(null),
    userMenuTrigger = useRef<HTMLButtonElement | null>(null),
    projectModuleNav = useRef<HTMLElement | null>(null);
  const parts = pathname.split("/").filter(Boolean);
  const projectId =
    parts[0] === "projects" && parts[1] && !["new", "import"].includes(parts[1])
      ? parts[1]
      : null;
  const tab = parts[2] ?? "overview";
  useEffect(() => {
    if (rememberedGlobalNavCollapsed !== undefined) return;
    const timer = window.setTimeout(() => {
      try {
        rememberedGlobalNavCollapsed = window.localStorage.getItem(globalNavStorageKey) === "true";
        setGlobalNavCollapsed(rememberedGlobalNavCollapsed);
      } catch {
        rememberedGlobalNavCollapsed = false;
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  useEffect(() => {
    const syncTutorialGuidanceRequest = () =>
      setTutorialGuidanceRequest(tutorialGuidanceRequestSequence);
    window.addEventListener(
      tutorialGuidanceRequestEvent,
      syncTutorialGuidanceRequest,
    );
    syncTutorialGuidanceRequest();
    return () =>
      window.removeEventListener(
        tutorialGuidanceRequestEvent,
        syncTutorialGuidanceRequest,
      );
  }, []);
  useEffect(() => {
    const update = () => setSmall(window.innerWidth < 1024);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);
  const readOnly = small || project?.status === "archived",
    dirty = Boolean(
      draft &&
      saved &&
      (draft.title !== saved.title || draft.body !== saved.body),
    );
  const activeTutorialStep: TutorialStep =
    project?.is_tutorial &&
    tutorialProgress?.tutorial_project_id === project.id
      ? tutorialProgress.current_step
      : 1;
  function clear() {
    activeProjectRequest.current?.abort();
    activeProjectRequest.current = null;
    epoch.current += 1;
    setProject(null);
    setChapters([]);
    setMemories([]);
    setDraft(null);
    setSaved(null);
    setRun(null);
    setPairedRun(null);
    setInitialization(null);
    setMemoryDelta(null);
    setCoverage(null);
    setAuthorContext(null);
    setAuthorBusy("");
    setOutline(null);
    setCharacters([]);
    setWorld([]);
    setSelected(null);
    setSourceRecord(null);
    setTutorialProgress(null);
    setControlled(null);
    setLocallyResolvedIssueIds([]);
    setChangeSet(null);
    setUserMenuOpen(false);
    setHome(null);
    setOnboarding(null);
    setProjects([]);
  }
  useEffect(() => {
    if (!userMenuOpen) return;
    const close = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setUserMenuOpen(false);
      requestAnimationFrame(() => userMenuTrigger.current?.focus());
    };
    window.addEventListener("keydown", close);
    return () => window.removeEventListener("keydown", close);
  }, [userMenuOpen]);
  useEffect(() => {
    if (!projectId || !projectModuleNav.current) return;
    const nav = projectModuleNav.current;
    const frame = requestAnimationFrame(() => {
      nav
        .querySelector<HTMLElement>('[aria-current="page"]')
        ?.scrollIntoView({
          block: "nearest",
          inline: "nearest",
          // Keep route changes deterministic and motion-free; this also
          // satisfies reduced-motion without introducing a second behavior.
          behavior: "auto",
        });
    });
    return () => cancelAnimationFrame(frame);
  }, [projectId, project?.id, tab]);
  const fail = useCallback(
    (cause: unknown) => {
      setError(cause);
      setNotice("");
      if ((cause as ApiFailure).code === "authentication_required") {
        bootstrappedUser = null;
        setUser(null);
        clear();
        router.replace("/login");
      }
    },
    [router],
  );
  const applyOnboarding = useCallback((next: Onboarding) => {
    setOnboarding(next);
    setTutorialProgress(next.progress);
  }, []);
  const resyncTutorialProgress = useCallback(async () => {
    const next = await request<Onboarding>("/onboarding");
    applyOnboarding(next);
    return next.progress;
  }, [applyOnboarding]);
  const recordTutorialEvent = useCallback(
    async (tutorialProjectId: string, event: TutorialEvent) => {
      try {
        const next = await json<TutorialProgress>("/onboarding/progress", "POST", {
          tutorial_version: "1.2.0",
          project_id: tutorialProjectId,
          event,
        });
        setTutorialProgress(next);
        setOnboarding((current) =>
          current ? { ...current, progress: next } : current,
        );
        return next;
      } catch (cause) {
        try {
          await resyncTutorialProgress();
        } catch {
          // Preserve the first write failure for the author-facing error.
        }
        fail(cause);
        throw cause;
      }
    },
    [fail, resyncTutorialProgress],
  );
  const updateBootstrappedUser = useCallback((next: User | null) => {
    bootstrappedUser = next;
    setUser(next);
  }, []);
  const go = (href: string) => {
    setUserMenuOpen(false);
    if (dirty && href !== pathname) {
      setSwitchSaveFailed(false);
      setSwitchTo(href);
    }
    else router.push(href);
  };
  const toggleGlobalNav = useCallback(() => {
    setUserMenuOpen(false);
    setGlobalNavCollapsed((current) => {
      const next = !current;
      rememberedGlobalNavCollapsed = next;
      try {
        window.localStorage.setItem(globalNavStorageKey, String(next));
      } catch {
        // Layout remains usable when browser storage is unavailable.
      }
      return next;
    });
  }, []);
  const loadProjects = useCallback(async (criteria?: {
    q: string;
    filter: string;
    sort: string;
    onlyIssues: boolean;
  }) => {
    const next = criteria ?? { q, filter, sort, onlyIssues };
    try {
      const data = await request<{ projects: ProjectSummary[] }>(
        `/projects?q=${encodeURIComponent(next.q)}${next.filter ? `&status=${next.filter}` : ""}${next.onlyIssues ? "&has_open_issues=true" : ""}&sort=${next.sort}`,
      );
      setProjects(data.projects);
    } catch (e) {
      fail(e);
    }
  }, [q, filter, onlyIssues, sort, fail]);
  const loadAuthorProjects = useCallback(async () => {
    setAuthorProjects(null);
    try {
      const [current, archived] = await Promise.all([
        request<{ projects: ProjectSummary[] }>("/projects?q=&sort=updated_desc"),
        request<{ projects: ProjectSummary[] }>("/projects?q=&status=archived&sort=updated_desc"),
      ]);
      setAuthorProjects([...current.projects, ...archived.projects].sort((a, b) => b.updated_at.localeCompare(a.updated_at)));
    } catch (cause) {
      fail(cause);
    }
  }, [fail]);
  const loadHome = useCallback(async () => {
    try {
      const [nextHome, nextOnboarding] = await Promise.all([
        request<Home>("/home"),
        request<Onboarding>("/onboarding"),
      ]);
      setHome(nextHome);
      applyOnboarding(nextOnboarding);
    } catch (cause) {
      fail(cause);
    }
  }, [applyOnboarding, fail]);
  const loadProject = useCallback(
    async (id: string) => {
      clear();
      const n = ++epoch.current,
        controller = new AbortController();
      activeProjectRequest.current = controller;
      setBusy("正在读取作品");
      try {
        const p = await request<Project>(`/projects/${id}`, {
          signal: controller.signal,
        });
        // Restore the lifecycle record before fan-out. On a cold refresh this
        // is the safety-critical state: it must not sit behind the browser's
        // same-origin connection queue for the larger workspace payloads.
        const latest = p.latest_run
          ? await request<Run>(
              `/projects/${id}/checks/${p.latest_run.run_id}?include=issues,evidence,metrics`,
              { signal: controller.signal },
            )
          : null;
        const [c, m, d, o, chars, w, author, initialized, memoryCoverage, delta, projectOnboarding, briefLatest, alignmentLatest] = await Promise.all([
          request<{ chapters: Chapter[] }>(
            `/projects/${id}/chapters?include=excerpt`,
            { signal: controller.signal },
          ),
          request<{ records: Memory[] }>(`/projects/${id}/memory`, {
            signal: controller.signal,
          }),
          request<Draft>(`/projects/${id}/drafts/${p.current_draft.id}`, {
            signal: controller.signal,
          }),
          request<{ chapter_nodes?: [] }>(`/projects/${id}/outline`, {
            signal: controller.signal,
          }),
          request<{ characters: [] }>(`/projects/${id}/characters`, {
            signal: controller.signal,
          }),
          request<{ entries: [] }>(`/projects/${id}/world`, {
            signal: controller.signal,
          }),
          request<AuthorContext>(`/projects/${id}/author-intent?include_archived=true`, {
            signal: controller.signal,
          }),
          p.data_origin === "user_import"
            ? request<MemoryInitialization>(`/projects/${id}/memory/initialization`, {
                signal: controller.signal,
              })
            : Promise.resolve(null),
          p.data_origin === "user_import"
            ? request<MemoryCoverage>(`/projects/${id}/memory/coverage`, {
                signal: controller.signal,
              })
            : Promise.resolve(null),
          p.data_origin === "user_import"
            ? request<MemoryDelta>(`/projects/${id}/memory/delta`, { signal: controller.signal })
            : Promise.resolve(null),
          p.is_tutorial
            ? request<Onboarding>("/onboarding", { signal: controller.signal })
            : Promise.resolve(null),
          request<{ run: WritingAnalysisRun | null }>(`/projects/${id}/analyses?analysis_type=context_brief`, { signal: controller.signal }),
          request<{ run: WritingAnalysisRun | null }>(`/projects/${id}/analyses?analysis_type=plan_alignment`, { signal: controller.signal }),
        ]);
        if (n !== epoch.current) return;
        setProject(p);
        if (projectOnboarding) applyOnboarding(projectOnboarding);
        setChapters(c.chapters);
        setMemories(m.records);
        setDraft(d);
        setSaved(d);
        setOutline(o as never);
        setCharacters(chars.characters as never);
        setWorld(w.entries as never);
        setAuthorContext(author);
        setInitialization(initialized);
        setMemoryDelta(delta);
        setCoverage(memoryCoverage);
        setContextBrief(briefLatest.run);
        setPlanAlignment(alignmentLatest.run);
        let primaryRun = latest;
        let siblingRun: Run | null = null;
        if (
          latest?.incremental_batch_id &&
          delta?.id === latest.incremental_batch_id &&
          delta.continuity_run_id &&
          delta.memory_delta_run_id
        ) {
          const readRun = (runId: string) =>
            latest.run_id === runId
              ? Promise.resolve(latest)
              : request<Run>(
                  `/projects/${id}/checks/${runId}?include=issues,evidence,metrics`,
                  { signal: controller.signal },
                );
          [primaryRun, siblingRun] = await Promise.all([
            readRun(delta.continuity_run_id),
            readRun(delta.memory_delta_run_id),
          ]);
        }
        setRun(primaryRun);
        setPairedRun(siblingRun);
      } catch (e) {
        if ((e as Error).name !== "AbortError") fail(e);
      } finally {
        if (n === epoch.current) setBusy("");
      }
    },
    [applyOnboarding, fail],
  );
  const refreshAuthorContext = useCallback(
    async (id: string, requestEpoch: number, signal?: AbortSignal) => {
      const next = await request<AuthorContext>(
        `/projects/${id}/author-intent?include_archived=true`,
        { signal },
      );
      if (requestEpoch !== epoch.current || projectId !== id) return null;
      setAuthorContext(next);
      setProject((current) =>
        current?.id === id
          ? { ...current, author_context_version: next.author_context_version }
          : current,
      );
      return next;
    },
    [projectId],
  );
  const mutateAuthorContext = useCallback(
    async (
      endpoint: string,
      method: "POST" | "PATCH",
      payload: Record<string, unknown>,
      busyLabel: string,
    ) => {
      if (!projectId) throw new Error("author_context_project_missing");
      const id = projectId;
      const requestEpoch = epoch.current;
      const signal = activeProjectRequest.current?.signal;
      setAuthorBusy(busyLabel);
      try {
        await json<unknown>(
          `/projects/${id}/author-intent/${endpoint}`,
          method,
          payload,
          signal,
        );
        return await refreshAuthorContext(id, requestEpoch, signal);
      } catch (cause) {
        if ((cause as ApiFailure).code === "author_context_version_conflict") {
          try {
            await refreshAuthorContext(id, requestEpoch, signal);
          } catch {
            // Keep the original conflict as the author-facing failure.
          }
        } else if ((cause as ApiFailure).code === "authentication_required") {
          fail(cause);
        }
        throw cause;
      } finally {
        if (requestEpoch === epoch.current && projectId === id) setAuthorBusy("");
      }
    },
    [fail, projectId, refreshAuthorContext],
  );
  useEffect(() => {
    if (bootstrappedUser !== undefined) return;
    const bootstrap =
      sessionBootstrap ??
      (sessionBootstrap = request<{ user: User | null }>("/auth/session?optional=true")
        .then((x) => {
          bootstrappedUser = x.user;
          return x.user;
        })
        .catch((e) => {
          if ((e as ApiFailure).code === "authentication_required") {
            bootstrappedUser = null;
            return null;
          }
          throw e;
        })
        .finally(() => {
          sessionBootstrap = null;
        }));
    bootstrap
      .then((nextUser) => setUser(nextUser))
      .catch(fail)
      .finally(() => setReady(true));
  }, [fail]);
  useEffect(() => {
    if (!ready) return;
    const auth = isPublicAuthPath(pathname);
    if (!user && !auth) {
      router.replace("/login");
      return;
    }
    if (user && ["/login", "/register", "/password-reset", "/password-reset/confirm"].includes(pathname)) {
      router.replace("/");
      return;
    }
    if (!user) return;
    if (projectId) void Promise.resolve().then(() => loadProject(projectId));
    else {
      if (pathname === "/") void Promise.resolve().then(() => loadHome());
      if (pathname.startsWith("/projects")) void Promise.resolve().then(() => loadProjects());
      if (pathname === "/account/profile") void Promise.resolve().then(() => loadAuthorProjects());
    }
  }, [
    ready,
    user,
    pathname,
    projectId,
    loadProject,
    loadProjects,
    loadAuthorProjects,
    loadHome,
    router,
    fail,
  ]);
  useEffect(() => {
    if (!run || !projectId || (!activeRun(run) && !activeRun(pairedRun)))
      return;
    const timer = window.setInterval(
      () => {
        const currentRuns = pairedRun ? [run, pairedRun] : [run];
        Promise.all(
          currentRuns.map((item) =>
            request<Run>(
              `/projects/${projectId}/checks/${item.run_id}?include=issues,evidence,metrics`,
            ),
          ),
        )
          .then((nextRuns) => {
            const next = nextRuns[0];
            setRun(next);
            setPairedRun(nextRuns[1] ?? null);
            if (nextRuns.every((item) => !activeRun(item))) {
              setNotice(
                next.status === "completed"
                  ? "检查完成，等待作者审阅。"
                  : `${labelError({ code: next.error_code })} 未完成 Run 不会写入或展示部分结果。`,
              );
              if (next.incremental_batch_id)
                request<MemoryDelta>(`/projects/${projectId}/memory/delta`).then((delta) => {
                  setMemoryDelta(delta);
                  setCoverage(delta.coverage ?? null);
                }).catch(fail);
            }
          })
          .catch(fail);
      },
      1000,
    );
    return () => window.clearInterval(timer);
  }, [run, pairedRun, projectId, fail]);
  useEffect(() => {
    if (!projectId || (!activeAnalysis(contextBrief) && !activeAnalysis(planAlignment))) return;
    const timer=window.setInterval(() => {
      const rows=[contextBrief,planAlignment].filter((item): item is WritingAnalysisRun => Boolean(item && activeAnalysis(item)));
      Promise.all(rows.map((item) => request<WritingAnalysisRun>(`/projects/${projectId}/analyses/${item.run_id}`)))
        .then((next) => next.forEach((item) => item.analysis_type === "context_brief" ? setContextBrief(item) : setPlanAlignment(item)))
        .catch(fail);
    },1000);
    return () => window.clearInterval(timer);
  },[contextBrief,planAlignment,projectId,fail]);
  const submitAuth = async (
    e: FormEvent<HTMLFormElement>,
    kind: "login" | "register",
  ) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setError(null);
    setNotice("");
    setBusy(kind === "login" ? "正在登录" : "正在创建本地账号");
    try {
      const body =
        kind === "login"
          ? {
              account_name: String(f.get("account_name")),
              password: String(f.get("password")),
            }
          : {
              account_name: String(f.get("account_name")),
              display_name: String(f.get("display_name")),
              password: String(f.get("password")),
              recovery_email: String(f.get("recovery_email")),
            };
      const data = await json<{ user: User }>(`/auth/${kind}`, "POST", body);
      startTransition(() => {
        bootstrappedUser = data.user;
        setUser(data.user);
        router.replace("/");
      });
    } catch (x) {
      fail(x);
    } finally {
      setBusy("");
    }
  };
  const enterVisitor = async () => {
    setError(null);
    setNotice("");
    setBusy("正在创建 24 小时访客空间");
    try {
      const data = await request<{ user: User }>("/auth/visitor", { method: "POST" });
      startTransition(() => {
        bootstrappedUser = data.user;
        setUser(data.user);
        router.replace("/");
      });
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const logout = async () => {
    try {
      await request("/auth/logout", { method: "POST" });
      startTransition(() => {
        clear();
        setTutorialProgress(null);
        bootstrappedUser = null;
        setUser(null);
        router.replace("/login");
      });
    } catch (e) {
      fail(e);
    }
  };
  const finishTutorial = async (outcome: "complete" | "skip") => {
    setBusy(outcome === "complete" ? "正在完成教学" : "正在跳过教学");
    try {
      await json(`/onboarding/${outcome}`, "POST", { confirm: true });
      setTutorialProgress(null);
      setOnboarding(null);
      if (outcome === "complete") {
        clear();
        setNotice("");
        router.replace("/onboarding/complete");
      } else {
        clear();
        router.replace("/");
        setNotice("已跳过教学。现在可以导入第一部真实作品。");
      }
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const reopenTutorial = async () => {
    setBusy("正在恢复教学样例");
    try {
      const data = await json<{ tutorial: { project_id: string }; progress: TutorialProgress }>("/onboarding/reopen", "POST", { confirm: true });
      setUserMenuOpen(false);
      setTutorialProgress(data.progress);
      router.push(`/projects/${data.tutorial.project_id}/overview`);
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const save = async (): Promise<boolean> => {
    if (!projectId || !draft || readOnly) return false;
    setError(null);
    setNotice("");
    setBusy(controlled ? "保存受控修订" : "保存草稿");
    try {
      const body: Record<string, unknown> = {
        base_revision: draft.revision,
        title: draft.title,
        body: draft.body,
      };
      if (controlled && run)
        body.edit_context = {
          source_run_id: run.run_id,
          source_revision: run.source_revision,
          issue_id: controlled.id,
        };
      const result = await json<{ revision: number; saved_at: string }>(
        `/projects/${projectId}/drafts/${draft.id}`,
        "PATCH",
        body,
      );
      const next = {
        ...draft,
        revision: result.revision,
        saved_at: result.saved_at,
      };
      setDraft(next);
      setSaved(next);
      setContextBrief((current)=>current&&current.draft_revision!==result.revision?{...current,is_stale:true,lineage_status:"bound_state_changed"}:current);
      setPlanAlignment((current)=>current&&current.draft_revision!==result.revision?{...current,is_stale:true,lineage_status:"bound_state_changed"}:current);
      if (controlled && run) {
        await json(
          `/projects/${projectId}/issues/${controlled.id}/decision`,
          "POST",
          {
            run_id: run.run_id,
            source_revision: run.source_revision,
            decision: "accept_and_edit",
            resulting_revision: result.revision,
          },
        );
        setLocallyResolvedIssueIds((ids) => [
          ...new Set([...ids, controlled.id]),
        ]);
        if (project?.is_tutorial)
          await recordTutorialEvent(project.id, "author_decision_recorded");
        setControlled(null);
        setRun(
          await request<Run>(
            `/projects/${projectId}/checks/${run.run_id}?include=issues,evidence,metrics`,
          ),
        );
        setNotice(`已按受控谱系保存 revision ${result.revision}。`);
      } else setNotice(`草稿已保存为 revision ${result.revision}。`);
      return true;
    } catch (e) {
      fail(e);
      return false;
    } finally {
      setBusy("");
    }
  };
  const check = async () => {
    if (!projectId || !draft || dirty || readOnly) return;
    setBusy("正在提交连续性检查");
    setChangeSet(null);
    try {
      const created = await json<Run>(`/projects/${projectId}/checks`, "POST", {
        draft_id: draft.id,
        draft_revision: draft.revision,
        client_request_id: crypto.randomUUID(),
      });
      setRun({
        ...created,
        current_revision: draft.revision,
        is_stale: false,
        superseded: false,
        lineage_status: "current",
        error_code: null,
        completed_at: null,
      });
      setPairedRun(null);
      setNotice("检查已排队；只轮询此 Run，不展示模型推理过程。");
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const startAnalysis = async (analysisType: "context_brief" | "plan_alignment") => {
    if (!projectId || !draft || dirty || readOnly) return;
    setAnalysisBusy(analysisType);
    try {
      const created=await json<WritingAnalysisRun>(`/projects/${projectId}/analyses`,"POST",{analysis_type:analysisType,draft_id:draft.id,draft_revision:draft.revision,client_request_id:crypto.randomUUID()});
      const next={...created,is_stale:false,lineage_status:"current",error_code:null} as WritingAnalysisRun;
      if (analysisType==="context_brief") setContextBrief(next); else setPlanAlignment(next);
      setNotice(analysisType==="context_brief" ? "章节简报已排队；完成后会在草稿上方显示。" : "计划偏离检查已排队；完成后会按计划逐项显示。" );
    } catch (cause) { fail(cause); } finally { setAnalysisBusy(""); }
  };
  const cancelAnalysis = async (target: WritingAnalysisRun) => {
    if (!projectId || readOnly || !activeAnalysis(target) || !["context_brief","plan_alignment"].includes(target.analysis_type)) return;
    const analysisType=target.analysis_type as "context_brief"|"plan_alignment";
    setAnalysisBusy(analysisType);
    try {
      await json(`/projects/${projectId}/analyses/${target.run_id}/cancel`,"POST",{client_request_id:crypto.randomUUID()});
      const next=await request<WritingAnalysisRun>(`/projects/${projectId}/analyses/${target.run_id}`);
      if (target.analysis_type==="context_brief") setContextBrief(next); else setPlanAlignment(next);
    } catch (cause) { fail(cause); } finally { setAnalysisBusy(""); }
  };
  const retryAnalysis = async (target: WritingAnalysisRun) => {
    if (!projectId || readOnly || !retryableAnalysis(target) || !["context_brief","plan_alignment"].includes(target.analysis_type)) return;
    const analysisType=target.analysis_type as "context_brief"|"plan_alignment";
    setAnalysisBusy(analysisType);
    try {
      const retried=await json<{run:WritingAnalysisRun}>(`/projects/${projectId}/analyses/${target.run_id}/retry`,"POST",{client_request_id:crypto.randomUUID()});
      const next=await request<WritingAnalysisRun>(`/projects/${projectId}/analyses/${retried.run.run_id}`);
      if (target.analysis_type==="context_brief") setContextBrief(next); else setPlanAlignment(next);
    } catch (cause) { fail(cause); } finally { setAnalysisBusy(""); }
  };
  const cancelRun = async () => {
    if (!projectId || !run || !activeRun(run) || readOnly) return;
    setBusy("正在安全取消 Run");
    try {
      await json(`/projects/${projectId}/checks/${run.run_id}/cancel`, "POST", { client_request_id: crypto.randomUUID() });
      const refreshedRuns = await Promise.all(
        (pairedRun ? [run, pairedRun] : [run]).map((item) =>
          request<Run>(`/projects/${projectId}/checks/${item.run_id}?include=issues,evidence,metrics`),
        ),
      );
      const refreshed = refreshedRuns[0];
      setRun(refreshed);
      setPairedRun(refreshedRuns[1] ?? null);
      if (refreshed.incremental_batch_id) {
        const delta = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
        setMemoryDelta(delta); setCoverage(delta.coverage ?? null);
      }
      setNotice(refreshed.status === "cancelled" ? "Run 已取消；未写入部分结果。" : "已请求协作式取消；Provider 返回后会丢弃迟到结果。等待安全终态。 ");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const retryRun = async () => {
    if (!projectId || !run || !retryableRun(run) || readOnly) return;
    setBusy("正在创建新 Run");
    try {
      const retried = await json<{ paired: boolean; run?: Run; continuity_run_id?: string; memory_delta_run_id?: string; batch_id?: string }>(`/projects/${projectId}/checks/${run.run_id}/retry`, "POST", { client_request_id: crypto.randomUUID() });
      const nextId = retried.paired ? retried.continuity_run_id : retried.run?.run_id;
      if (!nextId) throw Object.assign(new Error("Retry response missing Run"), { code: "internal_run_error" });
      const next = await request<Run>(`/projects/${projectId}/checks/${nextId}?include=issues,evidence,metrics`);
      setRun(next);
      if (retried.paired) {
        if (!retried.memory_delta_run_id) throw Object.assign(new Error("Retry response missing paired Run"), { code: "internal_run_error" });
        setPairedRun(await request<Run>(`/projects/${projectId}/checks/${retried.memory_delta_run_id}?include=issues,evidence,metrics`));
        const delta = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
        setMemoryDelta(delta); setCoverage(delta.coverage ?? null);
      } else setPairedRun(null);
      setNotice(`已创建 attempt ${next.attempt_number ?? "—"} 的新 Run；原 Run 保持不可变。`);
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const decide = async (
    issue: Issue,
    decision: "keep_intentional" | "false_positive",
  ) => {
    if (!projectId || !run || readOnly) return;
    setBusy("正在记录作者决策");
    try {
      const recorded = await json<{ decision: string; resulting_revision: number | null }>(`/projects/${projectId}/issues/${issue.id}/decision`, "POST", {
        run_id: run.run_id,
        source_revision: run.source_revision,
        decision,
        ...(run.current_revision !== run.source_revision
          ? { resulting_revision: run.current_revision }
          : {}),
      });
      setLocallyResolvedIssueIds((ids) => [
        ...new Set([...ids, issue.id]),
      ]);
      if (project?.is_tutorial)
        await recordTutorialEvent(project.id, "author_decision_recorded");
      const refreshed = await request<Run>(
        `/projects/${projectId}/checks/${run.run_id}?include=issues,evidence,metrics`,
      );
      setRun(refreshed);
      setSelected(
        refreshed.issues?.find((candidate) => candidate.id === issue.id) ?? {
          ...issue,
          decision: {
            decision: recorded.decision ?? decision,
            resulting_revision: recorded.resulting_revision ?? null,
          },
        },
      );
      setNotice(
        decision === "keep_intentional"
          ? "决定已记录：保留作者意图；可继续审阅后续 Memory 变更。"
          : "决定已记录：此问题已标记为误报，不会写入 Story Memory。",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const review = async () => {
    if (!projectId || !run || readOnly) return;
    setBusy("正在创建 Memory Update Review");
    try {
      const data = await json<{ change_set: ChangeSet }>(
        `/projects/${projectId}/memory/change-sets`,
        "POST",
        {
          run_id: run.run_id,
          source_run_revision: run.source_revision,
          resolved_revision: run.current_revision,
        },
      );
      setChangeSet(data.change_set);
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const commit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !changeSet || readOnly) return;
    setBusy("正在提交 Story Memory 更新");
    try {
      const form = new FormData(event.currentTarget);
      const accepted_item_ids = changeSet.items
          .filter((i) => ["accepted", "edited"].includes(String(form.get(i.id))))
          .map((i) => i.id),
        rejected_item_ids = changeSet.items
          .filter((i) => String(form.get(i.id)) === "rejected")
          .map((i) => i.id);
      const edited_items = changeSet.items
        .filter((i) => String(form.get(i.id)) === "edited")
        .map((i) => ({
          item_id: i.id,
          memory_type: String(form.get(`edit:${i.id}:memory_type`)),
          subject: String(form.get(`edit:${i.id}:subject`)),
          predicate: String(form.get(`edit:${i.id}:predicate`)),
          value: String(form.get(`edit:${i.id}:value`)),
        }));
      if (accepted_item_ids.length + rejected_item_ids.length !== changeSet.items.length) throw Object.assign(new Error("invalid selection"), { code: "invalid_item_selection", retryable: false });
      const result = await json<{
        status: string;
        memory_version: { current: number };
      }>(
        `/projects/${projectId}/memory/change-sets/${changeSet.id}/commit`,
        "POST",
        {
          confirm: true,
          accepted_item_ids,
          rejected_item_ids,
          edited_items,
          note: "作者在 Workspace 审核",
        },
      );
      setChangeSet(null);
      setMemories(
        (await request<{ records: Memory[] }>(`/projects/${projectId}/memory`))
          .records,
      );
      setProject((p) =>
        p ? { ...p, current_memory_version: result.memory_version.current } : p,
      );
      setNotice(
        result.status === "committed"
          ? `MemoryVersion ${result.memory_version.current} 已创建。`
          : "全部项目已拒绝，Story Memory 版本未变。",
      );
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const startMemoryInitialization = async () => {
    if (!projectId || readOnly) return;
    setBusy("正在生成 Story Memory 候选");
    try {
      await json<{ initialization: Pick<MemoryInitialization, "id" | "project_id" | "status" | "source_revision"> }>(
        `/projects/${projectId}/memory/initializations?view=compact`,
        "POST",
        { source_revision: 1 },
      );
      const initialized = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(initialized);
      setCoverage(initialized.coverage ?? null);
      setProject((current) =>
        current ? { ...current, memory_initialization_status: "in_review" } : current,
      );
      setNotice("候选已生成，尚未写入 Story Memory。请逐项审核原文与 SourceSpan。");
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const submitMemoryInitialization = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!projectId || !initialization?.id || readOnly) return;
    const form = new FormData(event.currentTarget);
    const selectedDecisions = new Map(
      Array.from(
        event.currentTarget.querySelectorAll<HTMLInputElement>(
          'input[data-memory-candidate-id]:checked',
        ),
      ).map((input) => [input.dataset.memoryCandidateId!, input.value]),
    );
    const undecided = initialization.candidates.filter((candidate) => candidate.decision_status === "pending");
    const coreUndecided = undecided.filter((candidate) => candidate.review_priority === "core");
    if (coreUndecided.some((candidate) => !selectedDecisions.get(candidate.id))) {
      const failure = new Error("请先决定所有核心候选") as ApiFailure;
      failure.code = "invalid_candidate_decision";
      failure.retryable = false;
      fail(failure);
      return;
    }
    if (undecided.some((candidate) => selectedDecisions.get(candidate.id) === "edited" && form.get(`memory-init:${candidate.id}:evidence-confirmed`) !== "confirmed")) {
      const failure = new Error("请确认编辑后的 Evidence") as ApiFailure;
      failure.code = "evidence_confirmation_required";
      failure.retryable = false;
      fail(failure);
      return;
    }
    setBusy("正在记录作者审核并建立 Memory V1");
    try {
      for (const candidate of undecided.filter((candidate) => selectedDecisions.has(candidate.id))) {
        const decision = selectedDecisions.get(candidate.id)!;
        const after =
          decision === "edited"
            ? {
                memory_type: String(form.get(`memory-init:${candidate.id}:memory_type`)),
                subject: String(form.get(`memory-init:${candidate.id}:subject`)),
                predicate: String(form.get(`memory-init:${candidate.id}:predicate`)),
                value: String(form.get(`memory-init:${candidate.id}:value`)),
              }
            : undefined;
        await json<{ candidate_id: string; decision_status: string }>(
          `/projects/${projectId}/memory/initializations/${initialization.id}/candidates/${candidate.id}/decision?view=compact`,
          "POST",
          { decision, ...(after ? { after, evidence_span_id: candidate.source.span_id } : {}) },
        );
      }
      const reviewedInitialization = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(reviewedInitialization);
      setCoverage(reviewedInitialization.coverage ?? null);
      const committed = await json<{
        initialization: Pick<MemoryInitialization, "id" | "project_id" | "status" | "source_revision">;
        memory_version: number;
        coverage?: MemoryCoverage;
      }>(
        `/projects/${projectId}/memory/initializations/${initialization.id}/commit?view=compact`,
        "POST",
        { confirm: true },
      );
      const refreshedInitialization = await request<MemoryInitialization>(`/projects/${projectId}/memory/initialization`);
      setInitialization(refreshedInitialization);
      setCoverage(committed.coverage ?? refreshedInitialization.coverage ?? null);
      setMemories(
        (await request<{ records: Memory[] }>(`/projects/${projectId}/memory`)).records,
      );
      setProject((current) =>
        current
          ? {
              ...current,
              current_memory_version: committed.memory_version,
              memory_initialization_status: refreshedInitialization.status === "committed" ? "completed" : "in_review",
            }
          : current,
      );
      setNotice(
        refreshedInitialization.status === "committed"
          ? committed.coverage?.status === "ready_partial"
            ? "核心候选已确认；辅助候选仍待审，不会进入 canon。现在可以安全开始首次检查。"
            : "Memory V1 已由作者审核后建立；现在可以运行首次检查。"
          : "核心候选未形成已确认事实；首次检查仍会安全返回上下文不足。",
      );
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const startIncrementalReview = async () => {
    if (!projectId || !project || readOnly) return;
    setBusy("正在运行增量检查与 Memory Delta");
    try {
      const result = await json<{ delta: MemoryDelta }>(`/projects/${projectId}/incremental-reviews`, "POST", { source_revision: project.source_revision });
      let latest = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
      if (latest.continuity_run_id && latest.memory_delta_run_id) {
        const [continuity, deltaRun] = await Promise.all([
          request<Run>(`/projects/${projectId}/checks/${latest.continuity_run_id}?include=issues,evidence,metrics`),
          request<Run>(`/projects/${projectId}/checks/${latest.memory_delta_run_id}?include=issues,evidence,metrics`),
        ]);
        setRun(continuity);
        setPairedRun(deltaRun);
        if (!activeRun(continuity) && !activeRun(deltaRun) && latest.status === "processing")
          latest = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
      }
      setMemoryDelta(latest); setCoverage(latest.coverage ?? result.delta.coverage ?? null);
      setNotice(latest.status === "in_review" ? "增量双 Run 已完成；候选尚未成为 canon。" : "增量 Continuity 与 Memory Delta 已排队；只在双 Run 完成后展示结果。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const submitMemoryDelta = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault(); if (!projectId || !memoryDelta?.id || readOnly) return;
    const form = new FormData(event.currentTarget); const pending = memoryDelta.candidates.filter((x) => x.decision_status === "pending");
    if (pending.filter((x) => x.review_priority === "core").some((x) => !form.get(`memory-delta:${x.id}`))) { fail(Object.assign(new Error("请先决定所有核心候选"), { code: "unresolved_required_decisions" })); return; }
    setBusy("正在提交增量 Memory 审核");
    try {
      for (const candidate of pending.filter((x) => form.get(`memory-delta:${x.id}`))) {
        const decision = String(form.get(`memory-delta:${candidate.id}`));
        const after = decision === "edited" ? { memory_type:String(form.get(`memory-delta:${candidate.id}:memory_type`)), subject:String(form.get(`memory-delta:${candidate.id}:subject`)), predicate:String(form.get(`memory-delta:${candidate.id}:predicate`)), value:String(form.get(`memory-delta:${candidate.id}:value`)) } : undefined;
        await json(`/projects/${projectId}/memory/deltas/${memoryDelta.id}/candidates/${candidate.id}/decision`, "POST", { decision, ...(after ? { after, evidence_span_id:candidate.source.span_id } : {}) });
      }
      const committed = await json<{ delta: MemoryDelta; memory_version:number }>(`/projects/${projectId}/memory/deltas/${memoryDelta.id}/commit`, "POST", { confirm:true });
      setMemoryDelta(committed.delta); setCoverage(committed.delta.coverage ?? null); setMemories((await request<{records:Memory[]}>(`/projects/${projectId}/memory`)).records); setProject((current) => current ? {...current,current_memory_version:committed.memory_version} : current);
      setNotice(committed.memory_version > (memoryDelta.base_memory_version ?? 0) ? `Memory V${committed.memory_version} 与审计 ChangeSet 已原子建立。` : memoryDelta.candidates.length ? "事实变化均未被接受；来源覆盖已审计，Memory 版本未变。" : "本次没有事实变化候选；来源覆盖已审计，Memory 版本未变。");
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const reset = async () => {
    if (!projectId) return;
    setBusy("正在恢复当前作品");
    try {
      await json(`/projects/${projectId}/reset`, "POST", {
        confirm: true,
        reason: "demo_recovery",
      });
      setResetOpen(false);
      await loadProject(projectId);
      setNotice("当前作品已按其数据来源恢复；其他作品没有改变。");
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
  };
  const create = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
    setBusy("正在创建作品");
    try {
      const data = await json<{ project: ProjectSummary }>(
        "/projects",
        "POST",
        {
          title: String(f.get("title")),
          genre: String(f.get("genre")),
          summary: String(f.get("summary")),
        },
      );
      router.push(`/projects/${data.project.id}/overview`);
    } catch (x) {
      fail(x);
    } finally {
      setBusy("");
    }
  };
  const previewFile = async (file: File): Promise<boolean> => {
    setBusy("正在预览导入文件");
    try {
      const form = new FormData();
      form.append("file", file);
      setPreview(
        await request<ImportPreview>("/imports/preview", {
          method: "POST",
          headers: { "Idempotency-Key": crypto.randomUUID() },
          body: form,
        }),
      );
      return true;
    } catch (x) {
      fail(x);
      return false;
    } finally {
      setBusy("");
    }
  };
  const importCommit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!preview) return;
    const f = new FormData(e.currentTarget);
    setBusy("正在创建导入作品");
    try {
      const data = await json<{ project: { id: string } }>(
        `/imports/${preview.import_id}/commit`,
        "POST",
        {
          confirm: true,
          title: String(f.get("title")),
          genre: String(f.get("genre")),
          summary: String(f.get("summary")),
          chapter_preview_ids: preview.detected.chapters.map(
            (c) => c.preview_id,
          ),
        },
      );
      router.push(`/projects/${data.project.id}/overview`);
    } catch (x) {
      fail(x);
    } finally {
      setBusy("");
    }
  };
  const discardImport = async (leaveImport: boolean): Promise<boolean> => {
    const activePreview = preview;
    if (!activePreview) {
      setPreview(null);
      if (leaveImport) router.push("/projects");
      return true;
    }
    setBusy("正在取消导入");
    try {
      await json(`/imports/${activePreview.import_id}/cancel`, "POST", {
        confirm: true,
      });
      setPreview(null);
      if (leaveImport) router.push("/projects");
      return true;
    } catch (cause) {
      fail(cause);
      return false;
    } finally {
      setBusy("");
    }
  };
  const updateProject = async (payload: Record<string, unknown>) => {
    if (!projectId || !project) return;
    if (typeof project.metadata_revision !== "number") {
      const error = new Error("metadata_revision unavailable") as ApiFailure;
      error.code = "metadata_revision_unavailable";
      error.retryable = false;
      fail(error);
      return;
    }
    setBusy("正在更新作品");
    try {
      const data = await json<{ project: Project }>(
        `/projects/${projectId}`,
        "PATCH",
        { base_metadata_revision: project.metadata_revision, ...payload },
      );
      setProject((current) => (current ? { ...current, ...data.project } : data.project));
      setMetaOpen(false);
      setArchiveOpen(false);
      setNotice(
        data.project.status === "archived"
          ? "作品已归档，现在只能浏览；恢复后可继续编辑。"
          : "作品信息已更新。",
      );
    } catch (x) {
      fail(x);
    } finally {
      setBusy("");
    }
  };
  let body: ReactNode;
  if (!ready)
    body = (
      <div className="boot" role="status">
        正在恢复本地会话…
      </div>
    );
  else if (pathname === "/password-reset")
    body = <PasswordResetRequestPage go={go} />;
  else if (pathname === "/password-reset/confirm")
    body = <PasswordResetConfirmPage go={go} />;
  else if (pathname === "/verify-email")
    body = <VerifyEmailPage go={go} refreshUser={updateBootstrappedUser} />;
  else if (!user)
    body = (
      <Auth
        register={pathname === "/register"}
        busy={busy}
        error={error}
        submit={submitAuth}
        visitor={enterVisitor}
        go={(h) => {
          setError(null);
          setNotice("");
          router.push(h);
        }}
      />
    );
  else if (pathname === "/account/profile")
    body = <AccountProfile user={user} projects={authorProjects} updateUser={updateBootstrappedUser} go={go} />;
  else if (pathname === "/account/security")
    body = <AccountSecurity user={user} updateUser={updateBootstrappedUser} go={go} />;
  else if (pathname === "/onboarding/complete")
    body = (
      <TutorialCompletePage
        go={(href) => {
          clear();
          window.scrollTo({ top: 0, left: 0, behavior: "auto" });
          router.replace(href);
        }}
      />
    );
  else if (!projectId)
    body =
      pathname === "/projects/new" ? (
        <New busy={busy} error={error} submit={create} />
      ) : pathname === "/projects/import" ? (
        <Import
          busy={busy}
          error={error}
          preview={preview}
          previewFile={previewFile}
          cancel={() => discardImport(true)}
          restart={() => discardImport(false)}
          commit={importCommit}
          disabled={small}
        />
      ) : pathname.startsWith("/projects") ? (
        <Projects
          rows={projects}
          busy={busy}
          q={q}
          filter={filter}
          sort={sort}
          onlyIssues={onlyIssues}
          set={(k, v) => {
            if (k === "q") setQ(v as string);
            if (k === "filter") setFilter(v as string);
            if (k === "sort") setSort(v as string);
            if (k === "issues") setOnlyIssues(v as boolean);
          }}
          refresh={() => void loadProjects()}
          clear={() => {
            const reset = { q: "", filter: "", sort: "updated_desc", onlyIssues: false };
            setQ(reset.q);
            setFilter(reset.filter);
            setSort(reset.sort);
            setOnlyIssues(reset.onlyIssues);
            void loadProjects(reset);
          }}
          open={(id) => go(`/projects/${id}/overview`)}
          go={go}
        />
      ) : (
        <HomePage
          home={home}
          onboarding={onboarding}
          open={(id) => go(`/projects/${id}/overview`)}
          go={go}
        />
      );
  else
    body = project ? (
      <ProjectPage
        tab={tab}
        project={project}
        chapters={chapters}
        outline={outline}
        characters={characters}
        world={world}
        authorContext={authorContext}
        authorBusy={authorBusy}
        memories={memories}
        initialization={initialization}
        memoryDelta={memoryDelta}
        coverage={coverage}
        draft={draft}
        saved={saved}
        run={run}
        pairedRun={pairedRun}
        contextBrief={contextBrief}
        planAlignment={planAlignment}
        analysisBusy={analysisBusy}
        locallyResolvedIssueIds={locallyResolvedIssueIds}
        selectedIssueId={selected?.id ?? null}
        tutorialStep={activeTutorialStep}
        requestTutorialGuidance={emitTutorialGuidanceRequest}
        readOnly={readOnly}
        busy={busy}
        error={error}
        controlled={controlled}
        changeSet={changeSet}
        setDraft={setDraft}
        save={save}
        check={check}
        cancelRun={cancelRun}
        retryRun={retryRun}
        startAnalysis={startAnalysis}
        cancelAnalysis={cancelAnalysis}
        retryAnalysis={retryAnalysis}
        select={async (i, el) => {
          trigger.current = el;
          setSelected(i);
          if (project.is_tutorial) {
            try {
              await recordTutorialEvent(project.id, "continuity_issue_located");
              await recordTutorialEvent(project.id, "evidence_opened");
            } catch {
              // The shared error path has resynchronized canonical progress.
            }
          }
        }}
        review={review}
        commit={commit}
        startMemoryInitialization={startMemoryInitialization}
        submitMemoryInitialization={submitMemoryInitialization}
        startIncrementalReview={startIncrementalReview}
        submitMemoryDelta={submitMemoryDelta}
        reset={() => setResetOpen(true)}
        meta={() => setMetaOpen(true)}
        archive={() => setArchiveOpen(true)}
        finishTutorial={finishTutorial}
        advanceTutorial={(event) => recordTutorialEvent(project.id, event)}
        mutateAuthorContext={mutateAuthorContext}
        openMemorySource={async (memory, element) => {
          if (!memory.source) return;
          sourceTrigger.current = element;
          setSourceRecord({
            recordId: memory.id,
            subject: memory.subject,
            chapterId: memory.source.chapter_id,
            chapterNumber: memory.source.chapter_number,
            chapterTitle: memory.source.chapter_title,
            spanId: memory.source.span_id,
            excerpt: memory.source.excerpt,
            sourcePath: memory.source.source_path,
            memoryType: memory.memory_type,
            reviewStatus: memory.review_status,
          });
          if (project.is_tutorial) {
            try {
              await recordTutorialEvent(project.id, "memory_source_opened");
            } catch {
              // Keep the real source drawer open and surface the save failure.
            }
          }
        }}
        go={go}
      />
    ) : (
      <div className="boot">{busy || "正在读取当前作品…"}</div>
    );
  return (
    <div className={`workbench${user ? "" : " auth-shell"}${user && globalNavCollapsed ? " global-nav-collapsed" : ""}`}>
      <a className="skip" href="#main">
        跳到主要内容
      </a>
      {user && (
        <aside className="global-nav" aria-label="全局工作台" data-collapsed={globalNavCollapsed ? "true" : "false"}>
          <div className="global-nav-head">
            <div className="brand">
              <BrandMark />
            </div>
            <button
              type="button"
              className="global-nav-toggle"
              aria-label={globalNavCollapsed ? "展开全局侧栏" : "收起全局侧栏"}
              title={globalNavCollapsed ? "展开全局侧栏" : "收起全局侧栏"}
              aria-expanded={!globalNavCollapsed}
              onClick={toggleGlobalNav}
            >
              <svg viewBox="0 0 20 20" aria-hidden="true"><path d={globalNavCollapsed ? "m7 4 6 6-6 6" : "m13 4-6 6 6 6"} /></svg>
            </button>
          </div>
          <p className="nav-kicker">AUTHOR WORKBENCH</p>
          <nav aria-label="全局导航">
            <Button
              className={pathname === "/" ? "nav current" : "nav"}
              ariaLabel="首页"
              title={globalNavCollapsed ? "首页" : undefined}
              onClick={() => go("/")}
            >
              <Icon name="home" />
              <span className="nav-label">首页</span>
            </Button>
            <Button
              className={
                pathname.startsWith("/projects") ? "nav current" : "nav"
              }
              ariaLabel="作品管理"
              title={globalNavCollapsed ? "作品管理" : undefined}
              onClick={() => go("/projects")}
            >
              <Icon name="library" />
              <span className="nav-label">作品管理</span>
            </Button>
          </nav>
          <div className="account">
            <button
              ref={userMenuTrigger}
              type="button"
              className="account-trigger"
              aria-label="用户菜单"
              aria-haspopup="menu"
              aria-expanded={userMenuOpen}
              onClick={() => setUserMenuOpen((open) => !open)}
            >
              <ProfileAvatar user={user} className="account-avatar" />
              <span className="account-copy">
                <span className="account-name">{user.display_name}</span>
                <span className="account-helper">{user.account_type === "visitor" ? "访客空间" : "个人账号"}</span>
              </span>
              <Chevron className="account-caret" />
            </button>
            {userMenuOpen && (
              <div className="user-menu" role="menu" aria-label="用户菜单">
                {user.account_type === "visitor" && <p className="visitor-expiry">访客空间有效至 <time>{timestampLabel(user.visitor_expires_at)}</time></p>}
                {user.account_type !== "visitor" && (
                  <button type="button" role="menuitem" onClick={() => go("/account/profile")}><Icon name="profile" />个人信息</button>
                )}
                {user.account_type !== "visitor" && (
                  <button type="button" role="menuitem" onClick={() => go("/account/security")}><Icon name="security" />账号安全</button>
                )}
                {user.account_type !== "visitor" && (
                  <button type="button" role="menuitem" onClick={() => void reopenTutorial()}><Icon name="tutorial" />重新打开教学</button>
                )}
                <button
                  type="button"
                  className="danger"
                  role="menuitem"
                  onClick={() => void logout()}
                >
                  <Icon name="logout" />退出登录
                </button>
              </div>
            )}
          </div>
        </aside>
      )}
      {projectId && project && (
        <aside className="project-nav" aria-label="当前作品">
          <Button className="project-switch" onClick={() => go("/projects")}>
            <span>
              <small>更换当前作品</small>
              <strong>{project.title}</strong>
            </span>
            <Chevron className="project-switch-mark" />
          </Button>
          <div className="project-context">
            <span className={`status-pill ${project.status}`}>
              <span aria-hidden="true">●</span>
              {statusLabel(project.status)}
            </span>
            <span>Memory V{project.current_memory_version}</span>
          </div>
          <nav ref={projectModuleNav} aria-label="项目导航">
            {tabs.map(([id, label]) => (
              <Button
                key={id}
                className={id === tab ? "nav current" : "nav"}
                ariaCurrent={id === tab ? "page" : undefined}
                onClick={() => go(`/projects/${project.id}/${id}`)}
              >
                <Icon
                  name={
                    ({
                      overview: "overview",
                      outline: "outline",
                      characters: "users",
                      world: "world",
                      memory: "memory",
                      workspace: "pen",
                    } as const)[id]
                  }
                />
                {label}
              </Button>
            ))}
          </nav>
        </aside>
      )}
      <main id="main">
        {(!isPublicAuthPath(pathname) && (notice || Boolean(error))) && (
          <div
            className={error ? "feedback error" : "feedback"}
            role={error ? "alert" : "status"}
          >
            {error ? labelError(error) : notice}
            <Button
              onClick={() => {
                setError(null);
                setNotice("");
              }}
            >
              关闭
            </Button>
          </div>
        )}
        {body}
      </main>
      {sourceRecord && project && (
        <SourceDrawer
          record={sourceRecord}
          chapters={chapters}
          projectTitle={project.title}
          currentSourceRevision={project.source_revision}
          close={() => {
            setSourceRecord(null);
            setTimeout(() => sourceTrigger.current?.focus(), 0);
          }}
        />
      )}
      {selected && (
        <Evidence
          issue={selected}
          run={run}
          readOnly={readOnly}
          tutorial={Boolean(project?.is_tutorial)}
          busy={busy}
          openSource={(evidence, element) => {
            sourceTrigger.current = element;
            setSourceRecord({
              recordId: evidence.id,
              subject: `${categoryLabel(selected.category)}的历史证据`,
              chapterId: evidence.chapter_id,
              chapterNumber: evidence.chapter_number,
              chapterTitle: evidence.chapter_title,
              spanId: evidence.span_id,
              excerpt: evidence.excerpt,
              sourcePath: evidence.source_path,
              sourceRevision: evidence.source_revision,
              relation: evidence.relation,
              sufficiency: evidence.sufficiency,
            });
          }}
          close={() => {
            setSelected(null);
            setTimeout(() => trigger.current?.focus(), 0);
          }}
          accept={() => {
            setControlled(selected);
            setSelected(null);
            setTimeout(() => document.getElementById("draft-body")?.focus(), 0);
          }}
          decide={decide}
        />
      )}
      {project?.is_tutorial && (
        <TutorialGuidance
          active
          busy={Boolean(busy)}
          evidenceOpen={Boolean(selected)}
          projectId={project.id}
          readOnly={readOnly}
          requestId={tutorialGuidanceRequest}
          sourceOpen={Boolean(sourceRecord)}
          step={activeTutorialStep}
          tab={tab}
        />
      )}
      {switchTo && (
        <Dialog
          title="未保存草稿"
          closeDisabled={switchSaving}
          close={() => {
            if (!switchSavePending.current) setSwitchTo(null);
          }}
        >
          <p>
            切换作品会清理旧作品的草稿、Run、Issue、Evidence 和 Memory Review
            状态。
          </p>
          {switchSaveFailed && Boolean(error) && (
            <p className="inline-error" role="alert">
              保存失败，尚未切换。{labelError(error)} 当前标题和正文仍保留。
            </p>
          )}
          <div className="actions">
            <Button
              className="primary"
              disabled={Boolean(busy) || switchSaving}
              onClick={async () => {
                switchSavePending.current = true;
                setSwitchSaving(true);
                setSwitchSaveFailed(false);
                const savedBeforeSwitch = await save();
                switchSavePending.current = false;
                setSwitchSaving(false);
                if (!savedBeforeSwitch) {
                  setSwitchSaveFailed(true);
                  return;
                }
                const t = switchTo;
                setSwitchTo(null);
                router.push(t);
              }}
            >
              保存并切换
            </Button>
            <Button
              disabled={switchSaving}
              onClick={() => {
                if (switchSavePending.current) return;
                setDraft(saved);
                router.push(switchTo);
                setSwitchTo(null);
              }}
            >
              放弃修改
            </Button>
            <Button disabled={switchSaving} onClick={() => {
              if (!switchSavePending.current) setSwitchTo(null);
            }}>取消</Button>
          </div>
        </Dialog>
      )}
      {resetOpen && project && (
        <Dialog title="恢复当前作品" close={() => setResetOpen(false)}>
          <p>
            将把《{project.title}》恢复到
            {project.data_origin === "user_import"
              ? "刚导入完成时的状态：保留已确认导入的章节和原文来源，恢复空的第一版 Story Memory 与下一章初始草稿。"
              : project.data_origin === "demo_seed"
                ? "预置演示状态：恢复章节、已确认事实、初始草稿，以及可直接审阅的演示检查结果。"
                : "刚创建时的空白状态，包括空资料、第一版 Story Memory 与初始草稿。"}
          </p>
          <p>当前内容会被覆盖；本作品的连续性检查、问题、作者决定和尚未提交的候选变更都会被清除。其他作品和其他账户不受影响。</p>
          <p><strong>恢复后无法撤销。</strong></p>
          <div className="actions">
            <Button
              className="primary"
              disabled={readOnly || Boolean(busy)}
              onClick={() => void reset()}
            >
              确认恢复
            </Button>
            <Button onClick={() => setResetOpen(false)}>取消</Button>
          </div>
        </Dialog>
      )}
      {metaOpen && project && (
        <Dialog title="编辑作品信息" close={() => setMetaOpen(false)}>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              const f = new FormData(e.currentTarget);
              void updateProject({
                title: String(f.get("title")),
                genre: String(f.get("genre")),
                summary: String(f.get("summary")),
              });
            }}
          >
            <label>
              作品名
              <input name="title" defaultValue={project.title} />
            </label>
            <label>
              类型
              <input name="genre" defaultValue={project.genre} />
            </label>
            <label>
              说明
              <textarea name="summary" defaultValue={project.summary} />
            </label>
            <div className="actions">
              <Button
                className="primary"
                type="submit"
                disabled={readOnly || Boolean(busy)}
              >
                保存元数据
              </Button>
              <Button onClick={() => setMetaOpen(false)}>取消</Button>
            </div>
          </form>
        </Dialog>
      )}
      {archiveOpen && project && (
        <Dialog
          title={project.status === "archived" ? "恢复作品" : "归档作品"}
          close={() => setArchiveOpen(false)}
        >
          <p>
            {project.status === "archived"
              ? `恢复《${project.title}》后，作者操作会重新可用。`
              : `归档《${project.title}》后将保持可浏览但不可写入；不会永久删除。`}
          </p>
          <div className="actions">
            <Button
              className="primary"
              disabled={Boolean(busy)}
              onClick={() =>
                void updateProject({
                  status: project.status === "archived" ? "active" : "archived",
                  ...(project.status === "archived"
                    ? {}
                    : { confirm_archive: true }),
                })
              }
            >
              {project.status === "archived" ? "恢复作品" : "确认归档"}
            </Button>
            <Button onClick={() => setArchiveOpen(false)}>取消</Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

function Auth({
  register,
  busy,
  error,
  submit,
  visitor,
  go,
}: {
  register: boolean;
  busy: string;
  error: unknown;
  submit: (
    e: FormEvent<HTMLFormElement>,
    k: "login" | "register",
  ) => Promise<void>;
  visitor: () => Promise<void>;
  go: (href: string) => void;
}) {
  const accountInput = useRef<HTMLInputElement | null>(null);
  const [passwordVisible, setPasswordVisible] = useState(false);
  const errorId = "auth-error";
  const hasError = Boolean(error);
  const authErrorLabel =
    (error as ApiFailure | null)?.code === "authentication_required"
      ? "会话已失效，请重新登录。"
      : labelError(error);
  useEffect(() => {
    if (hasError) {
      accountInput.current?.focus();
      return;
    }
    if (window.innerWidth > 760) accountInput.current?.focus();
  }, [hasError, register]);
  return (
    <section className="auth-layout">
      <section className="auth">
        <div className="auth-brand"><BrandMark /></div>
        <div className="auth-heading">
          <h1>{register ? "创建账号" : "登录"}</h1>
          <p className="auth-lede">{register ? "创建本地账号，开始管理你的作品。" : "继续你的作品与连续性工作。"}</p>
        </div>
        <form onSubmit={(e) => void submit(e, register ? "register" : "login")}>
          <label>
            账号
            <input
              ref={accountInput}
              name="account_name"
              autoComplete="username"
              required
              minLength={register ? 3 : undefined}
              aria-invalid={hasError || undefined}
              aria-describedby={hasError ? errorId : undefined}
            />
          </label>
          {register && (
          <label>
            显示名称
            <input name="display_name" required maxLength={60} />
          </label>
          )}
          {register && (
            <label>
              恢复邮箱
              <input name="recovery_email" type="email" autoComplete="email" required maxLength={254} />
            </label>
          )}
          <div className="auth-password-label">
            <label htmlFor="auth-password">密码</label>
            <span className="auth-password-field">
              <input
                id="auth-password"
                name="password"
                type={passwordVisible ? "text" : "password"}
                autoComplete={register ? "new-password" : "current-password"}
                required
                minLength={register ? 10 : undefined}
                aria-invalid={hasError || undefined}
                aria-describedby={hasError ? errorId : undefined}
              />
              <Button
                className="quiet auth-password-toggle"
                ariaPressed={passwordVisible}
                ariaLabel={passwordVisible ? "隐藏密码" : "显示密码"}
                onClick={() => setPasswordVisible((visible) => !visible)}
                disabled={Boolean(busy)}
              >
                {passwordVisible ? "隐藏" : "显示"}
              </Button>
            </span>
          </div>
          {register && <p className="auth-rules">账号至少 3 个字符，密码至少 10 个字符。恢复邮箱验证后可用于密码找回。</p>}
          {!register && (
            <Button className="quiet auth-forgot" disabled={Boolean(busy)} onClick={() => go("/password-reset")}>忘记密码？</Button>
          )}
          <div className="auth-error-slot">
            {hasError && (
              <p id={errorId} className="inline-error" role="alert">
                {authErrorLabel}
              </p>
            )}
          </div>
          <div className="auth-actions">
            <Button className="primary" type="submit" disabled={Boolean(busy)} ariaBusy={Boolean(busy)}>
              <span>{register ? "创建账号" : "登录"}</span>
              <span className="auth-button-spinner" aria-hidden="true" data-active={Boolean(busy)} />
            </Button>
            <Button className="quiet auth-switch-link" disabled={Boolean(busy)} onClick={() => go(register ? "/login" : "/register")}>
              {register ? "已有账号？返回登录" : "还没有账号？创建账号"}
            </Button>
            {!register && <Button className="secondary auth-visitor" disabled={Boolean(busy)} onClick={() => void visitor()}>访客体验 24 小时</Button>}
          </div>
        </form>
      </section>
    </section>
  );
}

function PasswordResetRequestPage({ go }: { go: (href: string) => void }) {
  const [state, setState] = useState<"request" | "sending" | "sent" | "rate-limited" | "failed">("request");
  const [message, setMessage] = useState("");
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    setState("sending");
    setMessage("");
    try {
      await json("/auth/password-reset/request", "POST", { recovery_email: String(form.get("recovery_email")) });
      setState("sent");
      setMessage("如果该邮箱已验证，我们已发送一封 15 分钟内有效的重置邮件。");
    } catch (cause) {
      const code = (cause as ApiFailure).code;
      setState(code === "recovery_rate_limited" ? "rate-limited" : "failed");
      setMessage(labelError(cause));
    }
  };
  return (
    <section className="auth-layout">
      <section className="auth recovery-panel">
        <div className="auth-brand"><BrandMark />Story Continuity</div>
        <div className="auth-heading"><h1>找回密码</h1><p className="auth-lede">输入已验证的恢复邮箱。无论账号是否存在，响应都保持一致。</p></div>
        <form onSubmit={(event) => void submit(event)}>
          <label>恢复邮箱<input name="recovery_email" type="email" autoComplete="email" required maxLength={254} /></label>
          <div className="auth-error-slot" aria-live="polite">
            {message && <p className={state === "failed" || state === "rate-limited" ? "inline-error" : "inline-success"} role={state === "failed" ? "alert" : "status"}>{message}</p>}
          </div>
          <div className="auth-actions">
            <Button className="primary" type="submit" disabled={state === "sending"} ariaBusy={state === "sending"}>{state === "sending" ? "正在提交" : "发送重置邮件"}</Button>
            <Button className="quiet" onClick={() => go("/login")}>返回登录</Button>
          </div>
        </form>
      </section>
    </section>
  );
}

function consumeTokenFromFragment(): string {
  const token = new URLSearchParams(window.location.hash.replace(/^#/, "")).get("token") ?? "";
  history.replaceState(history.state, "", `${window.location.pathname}${window.location.search}`);
  return token;
}

function PasswordResetConfirmPage({ go }: { go: (href: string) => void }) {
  const [state, setState] = useState<"confirm" | "sending" | "success" | "invalid" | "rate-limited">("confirm");
  const [message, setMessage] = useState("");
  const token = useRef("");
  useEffect(() => {
    token.current = consumeTokenFromFragment();
  }, []);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = new FormData(event.currentTarget);
    if (!token.current) {
      setState("invalid");
      setMessage("安全链接无效或已过期，请重新发起。");
      return;
    }
    setState("sending");
    try {
      await json("/auth/password-reset/confirm", "POST", { token: token.current, password: String(form.get("password")) });
      setState("success");
      setMessage("密码已更新，所有旧会话均已撤销。请使用新密码登录。");
    } catch (cause) {
      const code = (cause as ApiFailure).code;
      setState(code === "recovery_rate_limited" ? "rate-limited" : "invalid");
      setMessage(labelError(cause));
    }
  };
  return (
    <section className="auth-layout">
      <section className="auth recovery-panel">
        <div className="auth-brand"><BrandMark />Story Continuity</div>
        <div className="auth-heading"><h1>设置新密码</h1><p className="auth-lede">安全链接只能使用一次，并在 15 分钟后过期。</p></div>
        {state === "success" ? (
          <div className="auth-actions" aria-live="polite"><p className="inline-success" role="status">{message}</p><Button className="primary" onClick={() => go("/login")}>前往登录</Button></div>
        ) : (
          <form onSubmit={(event) => void submit(event)}>
            <label>新密码<input name="password" type="password" autoComplete="new-password" minLength={10} required /></label>
            <p className="auth-rules">至少 10 个字符，且不能全部相同。</p>
            <div className="auth-error-slot" aria-live="assertive">
              {message && <p className="inline-error" role="alert">{message}</p>}
            </div>
            <div className="auth-actions">
              <Button className="primary" type="submit" disabled={state === "sending"} ariaBusy={state === "sending"}>{state === "sending" ? "正在更新" : "更新密码"}</Button>
              <Button className="quiet" onClick={() => go("/password-reset")}>重新发起</Button>
            </div>
          </form>
        )}
      </section>
    </section>
  );
}

function VerifyEmailPage({ go, refreshUser }: { go: (href: string) => void; refreshUser: (user: User | null) => void }) {
  const [message, setMessage] = useState("正在验证恢复邮箱…");
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    const token = consumeTokenFromFragment();
    if (!token) {
      queueMicrotask(() => {
        setFailed(true);
        setMessage("安全链接无效或已过期，请重新发送验证邮件。");
      });
      return;
    }
    json("/auth/recovery-email/verify", "POST", { token })
      .then(async () => {
        const session = await request<{ user: User | null }>("/auth/session?optional=true");
        refreshUser(session.user);
        setMessage("恢复邮箱已验证，可用于密码找回。");
      })
      .catch((cause) => { setFailed(true); setMessage(labelError(cause)); });
  }, [refreshUser]);
  return (
    <section className="auth-layout"><section className="auth recovery-panel">
      <div className="auth-brand"><BrandMark />Story Continuity</div>
      <div className="auth-heading"><h1>验证恢复邮箱</h1><p className={failed ? "inline-error" : "inline-success"} role={failed ? "alert" : "status"} aria-live="polite">{message}</p></div>
      <div className="auth-actions"><Button className="primary" onClick={() => go("/")}>返回工作台</Button></div>
    </section></section>
  );
}

function formatWritingCount(value: number) {
  return new Intl.NumberFormat("zh-CN").format(value);
}

function AvatarPickerDialog({
  user,
  selected,
  busy,
  select,
  close,
}: {
  user: User;
  selected: User["avatar_preset"];
  busy: boolean;
  select: (preset: User["avatar_preset"]) => void;
  close: () => void;
}) {
  const { modalRef, firstRef, containFocus } = useModalFocus<HTMLInputElement>(close);
  return (
    <div className="modal-layer avatar-picker-layer" role="presentation">
      <section ref={modalRef} className="dialog avatar-picker-dialog" role="dialog" aria-modal="true" aria-labelledby="avatar-picker-title" onKeyDown={containFocus}>
        <Button className="close" ariaLabel="关闭头像选择" onClick={close}>×</Button>
        <p className="eyebrow">资料设置</p>
        <h2 id="avatar-picker-title">更换头像</h2>
        <p>选择随应用保存的本地编辑头像。</p>
        <fieldset className="avatar-picker compact-avatar-picker">
          <legend className="sr-only">头像预设</legend>
          <div>
            {avatarPresets.map((preset, index) => (
              <label key={preset.id} className={selected === preset.id ? "selected" : ""}>
                <input ref={index === 0 ? firstRef : undefined} className="sr-only" type="radio" name="avatar_preset" value={preset.id} checked={selected === preset.id} onChange={() => select(preset.id)} disabled={busy} />
                <ProfileAvatar user={{ ...user, avatar_preset: preset.id }} />
                <span><strong>{preset.label}</strong><small>{preset.description}</small></span>
              </label>
            ))}
          </div>
        </fieldset>
        <div className="actions"><Button className="primary" onClick={close}>完成</Button></div>
      </section>
    </div>
  );
}

function AccountProfile({ user, projects, updateUser, go }: { user: User; projects: ProjectSummary[] | null; updateUser: (user: User) => void; go: (href: string) => void }) {
  const [displayName, setDisplayName] = useState(user.display_name);
  const [avatarPreset, setAvatarPreset] = useState<User["avatar_preset"]>(user.avatar_preset || "continuity_violet");
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [avatarOpen, setAvatarOpen] = useState(false);
  const avatarTrigger = useRef<HTMLButtonElement>(null);
  const previewUser = { ...user, display_name: displayName, avatar_preset: avatarPreset };
  const changed = displayName.trim() !== user.display_name || avatarPreset !== user.avatar_preset;
  const projectRows = projects ?? [];
  const totalChapters = projectRows.reduce((total, project) => total + (project.chapter_count ?? 0), 0);
  const totalWords = projectRows.reduce((total, project) => total + (project.word_count ?? 0), 0);
  const activeProjects = projectRows.filter((project) => project.status === "active").length;
  const completedProjects = projectRows.filter((project) => project.status === "completed").length;
  const continueProject = projectRows.find((project) => project.status === "active" && project.current_draft) ?? projectRows.find((project) => project.status !== "archived");
  const closeAvatarPicker = () => {
    setAvatarOpen(false);
    setTimeout(() => avatarTrigger.current?.focus(), 0);
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setBusy(true); setMessage(""); setError("");
    try {
      const data = await json<{ user: User }>("/auth/profile", "PATCH", {
        base_profile_revision: user.profile_revision,
        display_name: displayName,
        avatar_preset: avatarPreset,
      });
      updateUser(data.user);
      setDisplayName(data.user.display_name);
      setAvatarPreset(data.user.avatar_preset);
      setAvatarOpen(false);
      setMessage("个人信息已保存。");
    } catch (cause) {
      if ((cause as ApiFailure).code === "profile_revision_conflict") {
        try {
          const session = await request<{ user: User }>("/auth/session");
          updateUser(session.user);
        } catch {
          // Preserve the first write failure and the author's unsubmitted choices.
        }
      }
      setError(labelError(cause));
    } finally {
      setBusy(false);
    }
  };
  return (
    <section className="content account-profile-page">
      <header className="author-center-header">
        <div className="author-center-identity">
          <button ref={avatarTrigger} type="button" className="avatar-edit-trigger" aria-label="更换头像" title="更换头像" aria-haspopup="dialog" aria-expanded={avatarOpen} onClick={() => setAvatarOpen(true)}>
            <ProfileAvatar user={previewUser} className="profile-hero-avatar" />
            <span>更换</span>
          </button>
          <div>
            <p className="eyebrow">作者中心</p>
            <h1>{user.display_name}</h1>
            <p><span>@{user.account_name}</span><span>个人账号</span></p>
          </div>
        </div>
        <Button onClick={() => go("/")}>返回工作台</Button>
      </header>
      <form className="author-center-form" onSubmit={(event) => void submit(event)}>
        <div className="author-center-main">
          <section className="author-summary" aria-labelledby="author-summary-title">
            <header className="section-heading"><div><p className="eyebrow">真实数据</p><h2 id="author-summary-title">创作概况</h2></div>{continueProject && <Button className="quiet" onClick={() => go(`/projects/${continueProject.id}/${continueProject.current_draft && continueProject.status !== "archived" ? "workspace" : "overview"}`)}>继续创作</Button>}</header>
            <dl className="author-stat-list">
              <div><dt>真实作品</dt><dd>{projects === null ? "—" : formatWritingCount(projectRows.length)}</dd></div>
              <div><dt>已写章节</dt><dd>{projects === null ? "—" : formatWritingCount(totalChapters)}</dd></div>
              <div><dt>正文与草稿字数</dt><dd>{projects === null ? "—" : formatWritingCount(totalWords)}</dd></div>
              <div><dt>创作状态</dt><dd>{projects === null ? "读取中" : `${activeProjects} 部进行中 · ${completedProjects} 部完成`}</dd></div>
            </dl>
            <p className="author-stat-note">字数按真实章节正文与当前草稿去除空白后统计；教学作品不计入。</p>
          </section>
          <section className="author-works" aria-labelledby="author-works-title">
            <header className="section-heading"><div><p className="eyebrow">创作空间</p><h2 id="author-works-title">我的作品</h2></div><Button className="quiet" onClick={() => go("/projects")}>全部作品</Button></header>
            {projects === null ? (
              <p className="author-works-state" role="status">正在读取真实作品…</p>
            ) : projectRows.length ? (
              <ul>
                {projectRows.slice(0, 5).map((item) => (
                  <li key={item.id}>
                    <button type="button" onClick={() => go(`/projects/${item.id}/${item.current_draft && item.status !== "archived" ? "workspace" : "overview"}`)}>
                      <span className="author-work-copy"><strong>{item.title}</strong><small>{item.genre || "未填写类型"} · {item.chapter_count ?? 0} 章 · {formatWritingCount(item.word_count ?? 0)} 字</small></span>
                      <span className={`status-pill ${item.status}`}>{statusLabel(item.status)}</span>
                      <span className="author-work-action">{item.status === "archived" ? "查看" : "继续"} →</span>
                    </button>
                  </li>
                ))}
              </ul>
            ) : (
              <div className="author-works-state empty"><strong>还没有真实作品</strong><p>从空白作品开始，或导入已有 TXT / Markdown。</p><div className="actions"><Button onClick={() => go("/projects/import")}>导入作品</Button><Button className="primary" onClick={() => go("/projects/new")}>新建作品</Button></div></div>
            )}
          </section>
        </div>
        <aside className="profile-settings" aria-labelledby="profile-settings-title">
          <header><p className="eyebrow">次级设置</p><h2 id="profile-settings-title">资料设置</h2><p>调整工作台展示资料，不改变登录凭据。</p></header>
          <div className="profile-name-field">
            <label htmlFor="profile-display-name">显示名称</label>
            <input id="profile-display-name" value={displayName} onChange={(event) => setDisplayName(event.target.value)} required maxLength={60} autoComplete="name" aria-describedby="profile-display-name-help" disabled={busy} />
            <small id="profile-display-name-help">仅用于工作台展示。</small>
          </div>
          <dl className="profile-account-fact">
            <div><dt>登录账号</dt><dd>{user.account_name}</dd></div>
            <div><dt>账户类型</dt><dd>个人账号</dd></div>
          </dl>
          <div className="profile-feedback" aria-live="polite">
            {message && <p className="inline-success" role="status">{message}</p>}
            {error && <p className="inline-error" role="alert">{error}</p>}
          </div>
          <div className="profile-actions"><Button className="primary" type="submit" disabled={busy || !changed} ariaBusy={busy}>{busy ? "正在保存" : "保存资料"}</Button><Button className="quiet" onClick={() => go("/account/security")}>账号与安全</Button></div>
        </aside>
      </form>
      {avatarOpen && <AvatarPickerDialog user={previewUser} selected={avatarPreset} busy={busy} select={setAvatarPreset} close={closeAvatarPicker} />}
    </section>
  );
}

function AccountSecurity({ user, updateUser, go }: { user: User; updateUser: (user: User) => void; go: (href: string) => void }) {
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [email, setEmail] = useState("");
  const refresh = async () => {
    const session = await request<{ user: User }>("/auth/session");
    updateUser(session.user);
  };
  const send = async (resend: boolean) => {
    setBusy(true); setError(""); setMessage("");
    try {
      await json(resend ? "/auth/recovery-email/resend" : "/auth/recovery-email", "POST", { recovery_email: email });
      await refresh();
      setMessage(resend ? "验证邮件已重新发送。" : "恢复邮箱已绑定，验证邮件已发送。");
    } catch (cause) { setError(labelError(cause)); }
    finally { setBusy(false); }
  };
  const recovery = user.recovery_email ?? { configured: false, verified: false, masked: null };
  return (
    <section className="content account-security">
      <header className="page-heading"><div><p className="eyebrow">账号安全</p><h1>恢复邮箱</h1><p>邮箱只用于账户恢复和必要安全通知。</p></div><Button onClick={() => go("/")}>返回工作台</Button></header>
      <section className="security-status" aria-live="polite">
        <h2>当前状态</h2>
        <p>{recovery.configured ? recovery.masked : "尚未绑定"} · {recovery.verified ? "已验证" : "未验证"}</p>
        {user.account_type === "visitor" && <p className="inline-error">访客空间不支持绑定恢复邮箱。</p>}
      </section>
      {user.account_type !== "visitor" && (
        <form className="security-form" onSubmit={(event) => { event.preventDefault(); void send(false); }}>
          <label>恢复邮箱<input name="recovery_email" type="email" autoComplete="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} /></label>
          <div className="auth-actions"><Button className="primary" type="submit" disabled={busy}>{recovery.configured ? "更换并发送验证" : "绑定并发送验证"}</Button>{recovery.configured && !recovery.verified && <Button type="button" disabled={busy || !email} onClick={() => void send(true)}>重新发送</Button>}</div>
          {message && <p className="inline-success" role="status">{message}</p>}
          {error && <p className="inline-error" role="alert">{error}</p>}
        </form>
      )}
    </section>
  );
}
function TutorialCompletePage({ go }: { go: (href: string) => void }) {
  const steps = [
    "认识作品资料与 Story Memory",
    "查看一条事实来源",
    "打开高风险问题与 Evidence",
    "作出作者决定",
    "完成一次检查",
  ];
  return (
    <section className="tutorial-complete-page">
      <header className="home-heading"><p className="breadcrumb">全局 / 首页</p><h1>继续你的故事</h1></header>
      <section className="tutorial-complete-panel" aria-labelledby="tutorial-complete-title">
        <TutorialCompleteVisual />
        <div className="tutorial-complete-copy">
          <p className="eyebrow">隔离教学 · 已结束</p>
          <h2 id="tutorial-complete-title">教学已完成</h2>
          <p>你已经走完一次连续性检查流程。</p>
          <ol>{steps.map((step, index) => <li key={step}><span>{index + 1}</span>{step}</li>)}</ol>
          <div className="tutorial-complete-actions">
            <Button className="primary" onClick={() => go("/projects/import")}>导入自己的作品</Button>
            <Button onClick={() => go("/projects/new")}>创建空白作品</Button>
            <Button className="quiet" onClick={() => go("/")}>返回首页</Button>
          </div>
          <small>教学项目不计入真实作品。</small>
        </div>
      </section>
    </section>
  );
}
function HomePage({
  home,
  onboarding,
  open,
  go,
}: {
  home: Home | null;
  onboarding: Onboarding | null;
  open: (id: string) => void;
  go: (h: string) => void;
}) {
  const recentProjects = home?.recent_projects ?? [];
  const pendingContinuity = home?.pending_continuity ?? [];
  return (
    <section className="home-page">
      <header className="home-heading">
        <p className="breadcrumb">全局 / 首页</p>
        <h1>继续你的故事</h1>
      </header>
      {onboarding?.show_first_run && onboarding.tutorial && (
        <section className="tutorial-entry home-entry-composition" aria-label="首次教学">
          <EmptyManuscriptVisual />
          <div className="home-entry-copy">
            <p className="eyebrow">首次使用 · 教学模式</p>
            <h2>从隔离样例开始建立连续性档案</h2>
            <p>教学作品不计入真实作品、搜索或待处理问题；完成后再导入自己的故事。</p>
          </div>
          <div className="actions home-entry-actions">
            <Button className="primary" onClick={() => open(onboarding.tutorial!.project_id)}>开始教学</Button>
            <Button onClick={() => go("/projects/import")}>导入第一部作品</Button>
          </div>
        </section>
      )}
      {home?.continue_work ? (
        <section className="home-continue">
          <div>
            <p className="kicker">继续当前工作</p>
            <h2>
              《{home.continue_work.project_title}》 · {home.continue_work.draft_title}
            </h2>
            <p>
              草稿 revision {home.continue_work.draft_revision} · 下一步：
              {nextActionLabel(home.continue_work.next_action)}
            </p>
          </div>
          <Button
            className="primary"
            onClick={() => open(home.continue_work!.project_id)}
          >
            继续工作
          </Button>
        </section>
      ) : !onboarding?.show_first_run ? (
        <section className="empty-workspace home-entry-composition">
          <EmptyManuscriptVisual />
          <div className="empty-workspace-copy home-entry-copy">
            <p className="eyebrow">真实作品空间 · 尚未建立</p>
            <h2>从第一章开始建立连续性档案</h2>
            <p>导入 TXT / Markdown，或从空白作品开始。</p>
          </div>
          <div className="actions home-entry-actions">
            <Button className="primary" onClick={() => go("/projects/import")}>导入第一部作品</Button>
            <Button onClick={() => go("/projects/new")}>新建空白作品</Button>
          </div>
        </section>
      ) : null}
      <div className="home-section-grid">
        <section className="home-section">
          <header className="home-section-head">
            <h2>最近作品</h2>
            {recentProjects.length > 0 && <Button onClick={() => go("/projects")}>查看全部</Button>}
          </header>
          {recentProjects.length ? (
            <ul className="home-work-list">
              {recentProjects.map((item) => (
                <li key={item.project_id}>
                  <button onClick={() => open(item.project_id)}>
                    <strong>《{item.title}》</strong>
                    <span>{statusLabel(item.status)}</span>
                    <i aria-hidden="true">→</i>
                  </button>
                </li>
              ))}
            </ul>
          ) : (
            <div className="home-empty-state compact-empty">
              <span className="home-empty-mark" aria-hidden="true"><Icon name="library" /></span>
              <p>导入作品后，最近编辑的故事会显示在这里。</p>
            </div>
          )}
        </section>
        <section className="home-section home-issues-section">
          <header className="home-section-head">
            <h2>待处理问题</h2>
          </header>
          {pendingContinuity.length ? (
            <ul className="home-issue-list">
              {pendingContinuity.map((x) => {
                const total = x.high + x.medium + x.low;
                const tone = x.continuity_status === "unchecked" ? "unchecked" : x.high ? "high" : x.medium ? "medium" : "low";
                return (
                  <li key={x.project_id}>
                    <button onClick={() => open(x.project_id)}>
                      <span>
                        <strong>《{x.title}》</strong>
                        <small>高 {x.high} · 中 {x.medium} · 低 {x.low}</small>
                      </span>
                      <b className={`risk ${tone}`}>
                        <I>{tone === "high" ? "▲" : tone === "medium" ? "●" : tone === "unchecked" ? "○" : "✓"}</I>
                        {x.continuity_status === "unchecked" ? "尚未检查" : x.continuity_status === "checked_clear" ? "已清" : `${total} 项`}
                      </b>
                    </button>
                  </li>
                );
              })}
            </ul>
          ) : (
            <div className="home-empty-state compact-empty">
              <span className="home-empty-mark" aria-hidden="true"><Icon name="overview" /></span>
              <p>运行第一次连续性检查后，问题会按风险显示在这里。</p>
            </div>
          )}
        </section>
      </div>
    </section>
  );
}
function Rows({
  rows,
  open,
  append,
  filtered = false,
}: {
  rows: Array<
    Pick<ProjectSummary, "title" | "status"> &
      Partial<
        Pick<
          ProjectSummary,
          "genre" | "summary" | "current_memory_version" | "open_issue_count" | "continuity_status"
        >
      > &
      Partial<Pick<ProjectSummary, "id">> & { project_id?: string }
  >;
  open: (id: string) => void;
  append?: (id: string) => void;
  filtered?: boolean;
}) {
  return rows.length ? (
    <div className="project-table">
      <div className="project-rows-head" aria-hidden="true">
        <span />
        <span>作品</span>
        <span>简介</span>
        <span>状态</span>
        <span>Memory</span>
        <span>待处理</span>
        <span />
      </div>
      <ul className="project-rows">
      {rows.map((p, index) => {
        const projectId = p.id ?? p.project_id;
        if (!projectId) return null;
        const issueTone =
          (p.open_issue_count ?? 0) > 2
            ? "high"
            : (p.open_issue_count ?? 0) > 0
              ? "medium"
              : "low";
        return (
          <li key={projectId}>
            <span className={`project-mark ${p.status}`} aria-hidden="true">
              {String(index + 1).padStart(2, "0")}
            </span>
            <div className="project-row-main">
              <strong className="project-title">
                {p.title}
              </strong>
              <small>{p.genre || "未分类"}</small>
            </div>
            <small className="project-summary">{p.summary || "—"}</small>
            <span className={`status-pill ${p.status}`}><I>●</I>{statusLabel(p.status)}</span>
            <span className="project-memory">Memory V{p.current_memory_version ?? "—"}</span>
            <span className={`issue-count ${issueTone}`}>
              <I>
                {issueTone === "high"
                  ? "▲"
                  : issueTone === "medium"
                    ? "●"
                    : "✓"}
              </I>
              {p.continuity_status === "unchecked"
                ? "尚未检查"
                : p.continuity_status === "checked_clear"
                  ? "已检查 · 0 项待处理"
                  : `${p.open_issue_count ?? 0} 项待处理`}
            </span>
            <div className="actions">
              <Button className="quiet project-open" onClick={() => open(projectId)}>打开</Button>
              {append && p.status !== "archived" && <Button className="quiet" onClick={() => append(projectId)}>追加章节</Button>}
            </div>
          </li>
        );
      })}
      </ul>
    </div>
  ) : (
    <div className={filtered ? "empty search-empty" : "empty project-list-empty"}>
      {filtered ? "没有匹配当前条件的作品。调整或清除条件后再试。" : "还没有真实作品。"}
    </div>
  );
}
function Projects({
  rows,
  busy,
  q,
  filter,
  sort,
  onlyIssues,
  set,
  refresh,
  clear,
  open,
  go,
}: {
  rows: ProjectSummary[];
  busy: string;
  q: string;
  filter: string;
  sort: string;
  onlyIssues: boolean;
  set: (key: string, value: string | boolean) => void;
  refresh: () => void;
  clear: () => void;
  open: (id: string) => void;
  go: (h: string) => void;
}) {
  const filtered = Boolean(q || filter || onlyIssues || sort !== "updated_desc");
  return (
    <section className="projects-page">
      <header className="page-header">
        <div>
          <p className="breadcrumb">全局 / 作品管理</p>
          <h1>作品管理</h1>
        </div>
        {(rows.length > 0 || filtered) && <div className="actions">
          <Button onClick={() => go("/projects/import")}>导入作品</Button>
          <Button className="primary" onClick={() => go("/projects/new")}>
            新建作品
          </Button>
        </div>}
      </header>
      {(rows.length > 0 || filtered) && <div className="filters project-toolbar">
        <label className="project-search">
          <span className="sr-only">搜索</span>
          <input placeholder="搜索标题或简介" value={q} onChange={(e) => set("q", e.target.value)} />
        </label>
        <div className="project-filter-group" aria-label="状态与排序">
          <label>
            <span className="sr-only">状态</span>
            <select
              value={filter}
              onChange={(e) => set("filter", e.target.value)}
            >
              <option value="">未归档</option>
              <option value="active">进行中</option>
              <option value="paused">已暂停</option>
              <option value="completed">已完成</option>
              <option value="archived">已归档</option>
            </select>
          </label>
          <label>
            <span className="sr-only">排序</span>
            <select value={sort} onChange={(e) => set("sort", e.target.value)}>
              <option value="updated_desc">最近更新</option>
              <option value="title_asc">作品名</option>
            </select>
          </label>
        </div>
        <button
          type="button"
          className="issue-switch"
          role="switch"
          aria-checked={onlyIssues}
          onClick={() => set("issues", !onlyIssues)}
        >
          <span className="switch-track" aria-hidden="true"><span /></span>
          仅有待处理问题
        </button>
        <Button disabled={Boolean(busy)} onClick={refresh}>
          应用条件
        </Button>
        <Button className="quiet clear-filters" onClick={clear}>
          清除条件
        </Button>
      </div>}
      {!rows.length && !filtered ? (
        <section className="project-empty-state" aria-labelledby="project-empty-title">
          <EmptyLibraryVisual />
          <div>
            <p className="eyebrow">真实作品空间</p>
            <h2 id="project-empty-title">还没有真实作品</h2>
            <p>集中管理你的真实作品与连续性检查。</p>
            <hr />
            <p>导入已有 TXT / Markdown，或从空白作品开始。</p>
            <div className="actions"><Button onClick={() => go("/projects/import")}>导入作品</Button><Button className="primary" onClick={() => go("/projects/new")}>新建作品</Button></div>
          </div>
        </section>
      ) : (
        <Rows
          rows={rows}
          open={open}
          append={(id) => go(`/projects/${id}/sources`)}
          filtered={filtered}
        />
      )}
    </section>
  );
}
function New({
  busy,
  error,
  submit,
}: {
  busy: string;
  error: unknown;
  submit: (e: FormEvent<HTMLFormElement>) => Promise<void>;
}) {
  return (
    <section className="create-project-page">
      <header className="page-header">
        <div>
          <p className="breadcrumb">全局 / 作品管理 / 新建作品</p>
          <h1>新建作品</h1>
        </div>
      </header>
      <form className="form-panel" onSubmit={(e) => void submit(e)}>
        <label>
          作品名称
          <input name="title" required maxLength={80} placeholder="例如：潮汐之后" />
        </label>
        <label>
          类型
          <input name="genre" maxLength={80} />
        </label>
        <label>
          简介
          <textarea name="summary" maxLength={500} placeholder="用一两句话说明这部作品的起点。" />
        </label>
        {Boolean(error) && <p className="inline-error">{labelError(error)}</p>}
        <Button className="primary" type="submit" disabled={Boolean(busy)}>
          {busy || "创建并进入作品"}
        </Button>
      </form>
    </section>
  );
}
function Import({
  busy,
  error,
  preview,
  previewFile,
  cancel,
  restart,
  commit,
  disabled,
}: {
  busy: string;
  error: unknown;
  preview: ImportPreview | null;
  previewFile: (file: File) => Promise<boolean>;
  cancel: () => Promise<boolean>;
  restart: () => Promise<boolean>;
  commit: (e: FormEvent<HTMLFormElement>) => Promise<void>;
  disabled: boolean;
}) {
  const fileInput = useRef<HTMLInputElement>(null);
  const [selectedFile, setSelectedFile] = useState<File | null>(null);
  const [dragging, setDragging] = useState(false);
  const [localError, setLocalError] = useState("");
  const [step, setStep] = useState<"file" | "preview" | "confirm">("file");

  const selectFile = (file?: File) => {
    if (!file) return;
    setSelectedFile(file);
    setLocalError("");
  };
  const resetToFile = async () => {
    if (!(await restart())) return;
    setStep("file");
    setSelectedFile(null);
    setLocalError("");
    if (fileInput.current) fileInput.current.value = "";
  };
  const cancelAndExit = async () => {
    if (!(await cancel())) return;
    setStep("file");
    setSelectedFile(null);
    setLocalError("");
    if (fileInput.current) fileInput.current.value = "";
  };
  const beginPreview = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!selectedFile) {
      setLocalError("请先选择一个 UTF-8 TXT 或 Markdown 文件。");
      return;
    }
    if (await previewFile(selectedFile)) setStep("preview");
  };

  return (
    <section className="import-page">
      <header className="page-header">
        <div>
          <p className="eyebrow">IMPORT</p>
          <h1>导入已有作品</h1>
          <p>先在本地解析章节；确认后才创建作品，不会自动生成 Story Memory。</p>
        </div>
      </header>
      <ol className="import-steps" aria-label="导入步骤">
        {[
          ["file", "选择文件"],
          ["preview", "章节预览"],
          ["confirm", "确认导入"],
        ].map(([id, label], index) => {
          const order = index + 1;
          const active = step === id;
          const complete = (step === "preview" && order === 1) || (step === "confirm" && order < 3);
          return (
            <li key={id} className={active ? "active" : complete ? "complete" : ""}>
              <span aria-hidden="true">{complete ? "✓" : order}</span>
              <strong>{label}</strong>
            </li>
          );
        })}
      </ol>
      {step === "file" && (
        <form className="form-panel import-panel" onSubmit={(event) => void beginPreview(event)}>
          <div>
            <p className="eyebrow">步骤 1/3</p>
            <h2>选择要导入的文件</h2>
            <p className="muted">选择文件后将调用预览接口，只显示截断章节片段。</p>
          </div>
          <input
            ref={fileInput}
            className="sr-only"
            name="file"
            type="file"
            accept=".txt,.md,.markdown,text/plain,text/markdown"
            tabIndex={-1}
            onChange={(event) => selectFile(event.currentTarget.files?.[0])}
            disabled={disabled || Boolean(busy)}
          />
          <div
            className={`import-dropzone${dragging ? " dragging" : ""}`}
            data-testid="import-dropzone"
            onDragEnter={(event) => { event.preventDefault(); setDragging(true); }}
            onDragOver={(event) => event.preventDefault()}
            onDragLeave={() => setDragging(false)}
            onDrop={(event) => {
              event.preventDefault();
              setDragging(false);
              selectFile(event.dataTransfer.files[0]);
            }}
          >
            <span className="import-file-mark" aria-hidden="true">⇧</span>
            <strong>把文件拖到这里，或者选择本地文件</strong>
            <span>{selectedFile ? `${selectedFile.name} · ${selectedFile.size.toLocaleString()} bytes` : "尚未选择文件"}</span>
            <Button type="button" onClick={() => fileInput.current?.click()} disabled={disabled || Boolean(busy)}>
              选择本地文件
            </Button>
          </div>
          <ul className="import-guidance">
            <li>仅支持 UTF-8 的 .txt、.md、.markdown，文件不超过 5 MiB。</li>
            <li>在本地选择文件后解析章节，不会上传原始文件或显示完整正文。</li>
            <li>预览只展示文件名、元数据与截断章节片段；你可在确认前取消。</li>
          </ul>
          {Boolean(localError || error) && <p className="inline-error">{localError || (error ? labelError(error) : "")}</p>}
          <div className="actions">
            <Button type="button" onClick={() => void cancelAndExit()} disabled={Boolean(busy)}>取消导入</Button>
            <Button className="primary" type="submit" disabled={disabled || Boolean(busy)}>
              {busy || "解析并预览章节"}
            </Button>
          </div>
        </form>
      )}
      {preview && step === "preview" && (
        <section className="form-panel import-panel" aria-labelledby="import-preview-heading">
          <div>
            <p className="eyebrow">步骤 2/3</p>
            <h2 id="import-preview-heading">章节预览</h2>
            <p className="muted">确认截断片段与章节拆分后，再填写作品元数据。</p>
          </div>
          <dl className="metadata">
            <div>
              <dt>文件</dt>
              <dd>
                {preview.file.name} · {preview.file.size.toLocaleString()} bytes
                · {preview.file.format}
              </dd>
            </div>
            <div>
              <dt>SHA-256</dt>
              <dd className="mono break">{preview.file.sha256}</dd>
            </div>
            <div>
              <dt>策略</dt>
              <dd>
                {preview.detected.strategy} · {preview.detected.chapter_count}{" "}
                章
              </dd>
            </div>
          </dl>
          {preview.warnings.length > 0 && (
            <p className="warning">
              <I>!</I>
              {preview.warnings.join("；")}
            </p>
          )}
          <ol className="chapter-preview">
            {preview.detected.chapters.map((c) => (
              <li key={c.preview_id}>
                <strong>
                  {c.order}. {c.title}
                </strong>
                <span>{c.character_count} 字</span>
                <p>{c.excerpt}</p>
              </li>
            ))}
          </ol>
          <div className="actions">
            <Button onClick={() => void resetToFile()} disabled={Boolean(busy)}>返回重新选择</Button>
            <Button className="primary" onClick={() => setStep("confirm")} disabled={disabled || Boolean(busy)}>
              继续确认
            </Button>
            <Button onClick={() => void cancelAndExit()} disabled={Boolean(busy)}>取消导入</Button>
          </div>
        </section>
      )}
      {preview && step === "confirm" && (
        <form className="form-panel import-panel" onSubmit={(e) => void commit(e)}>
          <div>
            <p className="eyebrow">步骤 3/3</p>
            <h2>确认导入</h2>
            <p className="muted">将以当前预览的 {preview.detected.chapter_count} 章原子创建作品；提交后不能重复使用这次预览。</p>
          </div>
          <dl className="metadata import-confirmation">
            <div>
              <dt>已选文件</dt>
              <dd>{preview.file.name} · {preview.file.size.toLocaleString()} bytes</dd>
            </div>
            <div>
              <dt>章节</dt>
              <dd>{preview.detected.chapter_count} 章 · {preview.detected.strategy}</dd>
            </div>
          </dl>
          <label>
            作品名
            <input name="title" required />
          </label>
          <label>
            类型
            <input name="genre" />
          </label>
          <label>
            说明
            <textarea name="summary" />
          </label>
          {Boolean(error) && <p className="inline-error">{labelError(error)}</p>}
          <div className="actions">
            <Button type="button" onClick={() => setStep("preview")} disabled={Boolean(busy)}>返回章节预览</Button>
            <Button type="button" onClick={() => void cancelAndExit()} disabled={Boolean(busy)}>取消导入</Button>
            <Button className="primary" type="submit" disabled={disabled || Boolean(busy)}>{busy || "确认导入"}</Button>
          </div>
        </form>
      )}
    </section>
  );
}

function RunLifecycle({ run, blocked, cancelRun, retryRun, actions = true }: { run: Run; blocked: boolean; cancelRun: () => Promise<void>; retryRun: () => Promise<void>; actions?: boolean }) {
  const metrics = run.provider_metrics ?? run.metrics;
  const provenance = run.provenance ?? run.metrics?.provenance;
  const unfinished = run.status !== "completed" && !activeRun(run);
  return (
    <section className={`run-lifecycle status-${run.status}`} aria-label={`${run.run_type === "memory_delta" ? "Memory Delta" : "Continuity"} Agent Run 生命周期`} aria-live="polite">
      <header>
        <div>
          <p className="eyebrow">{run.run_type === "memory_delta" ? "STORY MEMORY 检查" : "连续性检查"}</p>
          <h2>{stage(run.stage)}</h2>
          <p>第 {run.attempt_number ?? 1} 次尝试 · {run.status === "completed" ? "结果已准备好，可继续审阅。" : "保留当前页面即可查看状态变化。"}</p>
        </div>
        <div className="run-actions">
          <span className={`run-state state-${run.status}`}>{stage(run.status)}</span>
          {actions && activeRun(run) && <Button disabled={blocked} onClick={() => void cancelRun()}>{run.stage === "cancelling" ? "正在取消" : "取消检查"}</Button>}
          {actions && retryableRun(run) && <Button className="primary" disabled={blocked} onClick={() => void retryRun()}>重新检查</Button>}
        </div>
      </header>
      {unfinished && <p className="run-safety" role="alert">{labelError({ code: run.error_code })} 本轮未写入任何部分问题、证据、作者决定或 Memory 结果。</p>}
      {run.stage === "cancelling" && <p className="run-safety" role="status">正在等待当前模型服务返回；迟到结果将被丢弃，不会进入业务表。</p>}
      <details className="run-technical">
        <summary>技术详情</summary>
        <dl className="run-facts">
          <div><dt>运行编号</dt><dd>{run.run_id}<br />根运行 {run.root_run_id ?? run.run_id}</dd></div>
          <div><dt>创建 / 开始 / 结束</dt><dd>{timestampLabel(run.created_at)}<br />{timestampLabel(run.started_at)}<br />{timestampLabel(run.completed_at)}</dd></div>
          <div><dt>运行耗时</dt><dd>检查 {durationLabel(run.duration_ms)}<br />模型服务 {durationLabel(metrics?.latency_ms)}</dd></div>
          <div><dt>模型服务用量</dt><dd>{metrics?.input_tokens == null ? "用量不可用" : `输入 ${metrics.input_tokens} / 输出 ${metrics.output_tokens ?? 0}`}<br />{metrics?.cost_available ? `实际费用 ¥${metrics.cost_cny}` : "费用不可用（不估算）"}</dd></div>
          <div><dt>证据谱系</dt><dd>来源 r{run.source_revision} · Memory V{run.source_memory_version ?? provenance?.source_memory_version ?? "—"}<br />{lineageStatusLabel(run.lineage_status)}</dd></div>
        </dl>
        {provenance && <section className="run-provenance"><h3>处理版本与状态事件</h3><dl><div><dt>服务 / 模型</dt><dd>{provenance.provider_label} / {provenance.model_label}</dd></div><div><dt>提示词 / 数据结构</dt><dd>{provenance.prompt_version} / {provenance.schema_version}</dd></div><div><dt>检索版本</dt><dd>{provenance.retrieval_method_version}</dd></div></dl><ol>{(run.transitions ?? []).map((event) => <li key={event.sequence}><strong>{event.sequence}. {stage(event.stage)}</strong><span>{stage(event.status)} · {timestampLabel(event.created_at)}{event.error_code ? ` · ${event.error_code}` : ""}</span></li>)}</ol></section>}
      </details>
    </section>
  );
}

const briefSectionLabel: Record<string,string>={related_plan:"相关计划",confirmed_fact:"已确认事实",character_state:"角色状态",world_rule:"世界规则",open_thread:"未解事项",recent_source:"近期正文"};
const alignmentStatusLabel: Record<string,string>={planned_covered:"已覆盖",planned_missing:"计划缺失",planned_early:"提前发生",planned_changed:"发生变化",insufficient_evidence:"证据不足"};

function AnalysisSources({sources}:{sources:{source_id:string;source_type:string;label:string;excerpt:string}[]}) {
  if (!sources.length) return <p className="analysis-no-source">当前结论未引用正文证据。</p>;
  return <details className="analysis-sources"><summary>查看来源 · {sources.length}</summary><ul>{sources.map((source)=><li key={`${source.source_type}:${source.source_id}`}><strong>{source.label}</strong><p>{source.excerpt}</p><small>{source.source_type} · {source.source_id}</small></li>)}</ul></details>;
}

function WritingAnalysisPanel({run,readOnly,busy,cancel,retry}:{run:WritingAnalysisRun;readOnly:boolean;busy:boolean;cancel:(run:WritingAnalysisRun)=>Promise<void>;retry:(run:WritingAnalysisRun)=>Promise<void>}) {
  const title=run.analysis_type==="context_brief"?"章节简报":"计划偏离";
  return <section className={`writing-analysis-result status-${run.status}${run.is_stale?" stale":""}`} aria-label={`${title}结果`}>
    <header><div><p className="eyebrow">AI 写作辅助 · {run.analysis_type==="context_brief"?"写作前":"保存后"}</p><h3>{title}</h3></div><span className={`run-state state-${run.status}`}>{run.is_stale?"依据已变化":stage(run.status)}</span></header>
    {activeAnalysis(run)&&<p className="analysis-pending">{stage(run.stage)}。编辑器仍可继续使用；本轮不会展示中间推理。</p>}
    {["failed","timed_out","cancelled"].includes(run.status)&&<p className="inline-error">{labelError({code:run.error_code})} 未写入、也不展示部分结果。</p>}
    {run.analysis&&<><p className="analysis-summary">{run.analysis.summary}</p>{run.analysis.summary_sources&&<AnalysisSources sources={run.analysis.summary_sources}/>}<ol className="analysis-items">{run.analysis.items.map((item,index)=>"section" in item?<li key={`${item.section}:${index}`}><span className="analysis-kicker">{briefSectionLabel[item.section]}</span><p>{item.text}</p><AnalysisSources sources={item.sources}/></li>:"story_plan_id" in item?<li key={item.story_plan_id}><div className="analysis-item-head"><strong>{item.story_plan_title}</strong><span className={`alignment-status status-${item.status}`}>{alignmentStatusLabel[item.status]}</span></div><p>{item.explanation}</p><AnalysisSources sources={item.evidence}/></li>:null)}</ol></>}
    <footer><small>草稿 r{run.draft_revision} · 来源 r{run.source_revision} · Memory V{run.source_memory_version} · Author Context V{run.author_context_version}</small>{!readOnly&&<div className="analysis-result-actions">{activeAnalysis(run)&&<Button disabled={busy} onClick={()=>void cancel(run)}>取消</Button>}{retryableAnalysis(run)&&<Button disabled={busy} onClick={()=>void retry(run)}>重试</Button>}</div>}</footer>
  </section>;
}

const foreshadowStatusLabel:Record<ForeshadowRecord["status"],string>={planned:"计划中",planted:"已埋设",developing:"发展中",resolved:"已回收",abandoned:"已放弃"};
const qaStatusLabel:Record<string,string>={answered:"已有答案",partial:"部分回答",insufficient:"证据不足",conflicting:"证据冲突"};
const qaLayerLabel:Record<string,string>={confirmed:"已确认事实",written:"已写正文",planned:"当前作者计划"};
const qaStanceLabel:Record<string,string>={supports:"支持",contradicts:"冲突",context:"背景"};

type ForeshadowEditor={title:string;description:string;status:ForeshadowRecord["status"];planted_reference:string;resolved_reference:string};
const emptyForeshadowEditor:ForeshadowEditor={title:"",description:"",status:"planned",planted_reference:"",resolved_reference:""};

function splitForeshadowReference(value:string){const [chapter_id,source_span_id]=value.split("|");return {chapter_id:chapter_id||null,source_span_id:source_span_id||null};}
function recordEditor(record:ForeshadowRecord):ForeshadowEditor{return {title:record.title,description:record.description,status:record.status,planted_reference:record.planted?`${record.planted.chapter_id}|${record.planted.source_span_id??""}`:"",resolved_reference:record.resolved?`${record.resolved.chapter_id}|${record.resolved.source_span_id??""}`:""};}
function candidateEditor(candidate:ForeshadowCandidate):ForeshadowEditor{return {title:candidate.title,description:candidate.description,status:candidate.suggested_status,planted_reference:candidate.planted_chapter_id?`${candidate.planted_chapter_id}|${candidate.planted_source_span_id??""}`:"",resolved_reference:candidate.resolved_chapter_id?`${candidate.resolved_chapter_id}|${candidate.resolved_source_span_id??""}`:""};}

function protectSourceNavigation(event:ReactMouseEvent<HTMLAnchorElement>,href:string|undefined,navigate?:((href:string)=>void)){
  if(!navigate||!href||event.defaultPrevented||event.button!==0||event.metaKey||event.ctrlKey||event.shiftKey||event.altKey)return;
  const target=new URL(href,window.location.href),current=new URL(window.location.href);
  if(target.origin===current.origin&&target.pathname===current.pathname&&target.search===current.search)return;
  event.preventDefault();navigate(href);
}

function EvidenceLinks({sources,navigate}:{sources:{source_id:string;source_type:string;label:string;excerpt:string;source_path?:string;relation?:string}[];navigate?:(href:string)=>void}){
  if(!sources.length)return <p className="analysis-no-source">没有可采信证据。</p>;
  return <ul className="source-links bounded-source-links">{sources.map((source)=><li key={`${source.source_type}:${source.source_id}:${source.relation??""}`}><a href={source.source_path} onClick={(event)=>protectSourceNavigation(event,source.source_path,navigate)} aria-label={`查看证据：${source.label}（${source.source_type}）`}><span><strong>{source.label}</strong>{source.relation&&<em>{source.relation==="resolved"?"回收":source.relation==="developing"?"发展":"埋设"}</em>}</span><small>{source.excerpt}</small></a></li>)}</ul>;
}

function ForeshadowReferenceSelect({label,value,setValue,chapters,disabled}:{label:string;value:string;setValue:(value:string)=>void;chapters:Chapter[];disabled:boolean}){
  return <label>{label}<select value={value} disabled={disabled} onChange={(event)=>setValue(event.target.value)}><option value="">不关联</option>{chapters.flatMap((chapter)=>[<option key={`chapter:${chapter.id}`} value={`${chapter.id}|`}>第 {chapter.number} 章《{chapter.title}》</option>,...(chapter.source_spans??[]).map((span)=><option key={span.span_id} value={`${chapter.id}|${span.span_id}`}>第 {chapter.number} 章 · {span.label}</option>)])}</select></label>;
}

function BoundedStoryTools({project,draft,chapters,readOnly,dirty,go}:{project:Project;draft:Draft|null;chapters:Chapter[];readOnly:boolean;dirty:boolean;go:(href:string)=>void}){
  const [snapshot,setSnapshot]=useState<ForeshadowSnapshot|null>(null);
  const [qaRuns,setQaRuns]=useState<WritingAnalysisRun[]>([]),[scanRuns,setScanRuns]=useState<WritingAnalysisRun[]>([]);
  const [question,setQuestion]=useState(""),[scope,setScope]=useState<("confirmed"|"written"|"planned")[]>(["confirmed","written","planned"]);
  const [editor,setEditor]=useState<ForeshadowEditor>(emptyForeshadowEditor),[editingId,setEditingId]=useState<string|null>(null),[editingBaseVersion,setEditingBaseVersion]=useState<number|null>(null);
  const [candidateEdits,setCandidateEdits]=useState<Record<string,ForeshadowEditor>>({});
  const [busy,setBusy]=useState(""),[notice,setNotice]=useState(""),[conflict,setConflict]=useState(false);
  const refreshEpoch=useRef(0),refreshAbort=useRef<AbortController|null>(null);
  const draftRevision=draft?.revision;
  const refresh=useCallback(async(silent=false)=>{
    const epoch=++refreshEpoch.current;
    refreshAbort.current?.abort();
    const controller=new AbortController();
    refreshAbort.current=controller;
    try{
      const [records,qa,scan]=await Promise.all([
        request<ForeshadowSnapshot>(`/projects/${project.id}/foreshadows?include_archived=true`,{signal:controller.signal}),
        request<{run:WritingAnalysisRun|null;runs:WritingAnalysisRun[]}>(`/projects/${project.id}/analyses?analysis_type=story_qa&limit=20`,{signal:controller.signal}),
        request<{run:WritingAnalysisRun|null;runs:WritingAnalysisRun[]}>(`/projects/${project.id}/analyses?analysis_type=foreshadow_scan&limit=20`,{signal:controller.signal}),
      ]);
      if(controller.signal.aborted||epoch!==refreshEpoch.current)return;
      setSnapshot(records);setQaRuns(qa.runs??[]);setScanRuns(scan.runs??[]);
    }catch(error){if((error as Error).name!=="AbortError"&&!silent&&epoch===refreshEpoch.current)setNotice(labelError(error));}
    finally{if(refreshAbort.current===controller)refreshAbort.current=null;}
  },[project.id]);
  const hasActiveRun=qaRuns.some(activeAnalysis)||scanRuns.some(activeAnalysis);
  useEffect(()=>{void draftRevision;const timer=window.setTimeout(()=>void refresh(),0);return()=>{window.clearTimeout(timer);refreshEpoch.current+=1;refreshAbort.current?.abort();};},[refresh,draftRevision]);
  useEffect(()=>{if(!hasActiveRun)return;const timer=window.setInterval(()=>void refresh(true),700);return()=>window.clearInterval(timer);},[refresh,hasActiveRun]);
  const activeQa=qaRuns.find(activeAnalysis),activeScan=scanRuns.find(activeAnalysis);
  const editorPayload=(value:ForeshadowEditor)=>{const planted=splitForeshadowReference(value.planted_reference),resolved=splitForeshadowReference(value.resolved_reference);return {title:value.title,description:value.description,status:value.status,planted_chapter_id:planted.chapter_id,planted_source_span_id:planted.source_span_id,resolved_chapter_id:resolved.chapter_id,resolved_source_span_id:resolved.source_span_id};};
  const saveRecord=async(event:FormEvent)=>{event.preventDefault();if(!snapshot||(editingId&&editingBaseVersion===null))return;setBusy("record");setNotice("");setConflict(false);try{const next=editingId?await json<ForeshadowSnapshot>(`/projects/${project.id}/foreshadows/${editingId}`,"PATCH",{base_version:editingBaseVersion,...editorPayload(editor)}):await json<ForeshadowSnapshot>(`/projects/${project.id}/foreshadows`,"POST",{base_foreshadow_version:snapshot.foreshadow_version,...editorPayload(editor)});setSnapshot(next);setEditingId(null);setEditingBaseVersion(null);setEditor(emptyForeshadowEditor);setNotice(editingId?"作者伏笔记录已更新。":"作者伏笔记录已创建。");await refresh(true);}catch(error){setConflict((error as ApiFailure).code==="foreshadow_version_conflict");setNotice(labelError(error));}finally{setBusy("");}};
  const loadLatest=async()=>{setBusy("reload");setNotice("正在载入最新伏笔版本；当前输入不会被清空。");try{const latest=await request<ForeshadowSnapshot>(`/projects/${project.id}/foreshadows?include_archived=true`);setSnapshot(latest);if(editingId){const current=latest.records.find((item)=>item.id===editingId);if(current)setEditingBaseVersion(current.version);}setConflict(false);setNotice("已载入最新伏笔版本；当前输入仍保留，请检查后主动重试保存。");await refresh(true);}catch(error){setNotice(labelError(error));}finally{setBusy("");}};
  const archiveRecord=async(record:ForeshadowRecord)=>{setBusy(record.id);setNotice("");try{const next=await json<ForeshadowSnapshot>(`/projects/${project.id}/foreshadows/${record.id}/archive`,"POST",{base_version:record.version});setSnapshot(next);setNotice("伏笔记录已归档，历史版本仍可追溯。");await refresh(true);}catch(error){setNotice(labelError(error));}finally{setBusy("");}};
  const start=async(kind:"story_qa"|"foreshadow_scan")=>{if(!draft)return;if(dirty){setNotice("请先保存当前草稿；有界问答与伏笔扫描只分析已保存版本。");return;}setBusy(kind);setNotice("");try{await json<WritingAnalysisRun>(`/projects/${project.id}/analyses`,"POST",{analysis_type:kind,draft_id:draft.id,draft_revision:draft.revision,...(kind==="story_qa"?{question,scope}:{})});if(kind==="story_qa")setQuestion("");setNotice(kind==="story_qa"?"问题已提交；回答只使用所选依据。":"伏笔扫描已提交；候选不会自动成为作者记录。");await refresh(true);}catch(error){setNotice(labelError(error));}finally{setBusy("");}};
  const runAction=async(run:WritingAnalysisRun,action:"cancel"|"retry")=>{setBusy(run.run_id);setNotice("");try{await json(`/projects/${project.id}/analyses/${run.run_id}/${action}`,"POST",{client_request_id:crypto.randomUUID()});await refresh(true);}catch(error){setNotice(labelError(error));}finally{setBusy("");}};
  const decide=async(run:WritingAnalysisRun,candidate:ForeshadowCandidate,decision:"accepted"|"edited"|"rejected")=>{if(!snapshot)return;setBusy(candidate.id);setNotice("");try{const edited=candidateEdits[candidate.id]??candidateEditor(candidate);await json(`/projects/${project.id}/analyses/${run.run_id}/foreshadow-candidates/${candidate.id}/decision`,"POST",{base_foreshadow_version:snapshot.foreshadow_version,decision,...(decision==="edited"?{edited:editorPayload(edited)}:{})});setNotice(decision==="rejected"?"AI 候选已拒绝，不会创建作者记录。":"AI 候选已由作者确认并创建记录。");await refresh(true);}catch(error){setNotice(labelError(error));}finally{setBusy("");}};
  const changeCandidate=(candidate:ForeshadowCandidate,patch:Partial<ForeshadowEditor>)=>setCandidateEdits((current)=>({...current,[candidate.id]:{...(current[candidate.id]??candidateEditor(candidate)),...patch}}));
  const toggleScope=(value:"confirmed"|"written"|"planned")=>setScope((current)=>current.includes(value)?(current.length===1?current:current.filter((item)=>item!==value)):[...current,value]);
  const renderRunActions=(run:WritingAnalysisRun)=>!readOnly&&<div className="analysis-result-actions">{activeAnalysis(run)&&<Button disabled={Boolean(busy)} onClick={()=>void runAction(run,"cancel")}>取消</Button>}{retryableAnalysis(run)&&<Button disabled={Boolean(busy)||run.is_stale} onClick={()=>void runAction(run,"retry")}>重试</Button>}</div>;
  return <details className="bounded-story-tools" role="region" aria-label="有界问答与伏笔管理">
    <summary className="bounded-tools-header"><div><p className="eyebrow">次级 AI 工具</p><h2>有界问答与伏笔管理</h2><p>按需展开，不遮挡正文；已有回答与伏笔记录也在这里。</p></div><small>作者伏笔 V{snapshot?.foreshadow_version??project.foreshadow_version??0} · 回答 {qaRuns.length} · 扫描 {scanRuns.length}</small></summary>
    <div className="bounded-tools-intro">回答按依据分层；AI 扫描只提出候选。正文、Story Memory、Author Context 与其他作者资料都不会被自动修改。</div>
    {notice&&<p className="notice" role="status">{notice}</p>}
    {conflict&&<div className="bounded-conflict" role="alert"><p>服务器上的伏笔版本已变化；你的标题、说明与引用选择仍保留。载入最新版本后检查差异，再主动重试保存。</p><Button className="secondary" disabled={Boolean(busy)} onClick={()=>void loadLatest()}>载入最新版本</Button></div>}
    {dirty&&!readOnly&&<p className="bounded-dirty-note" role="note">当前草稿有未保存修改。已有结果仍可浏览；提问与扫描会保持禁用，保存后会自动刷新并标记旧结果。</p>}
    <div className="bounded-tools-grid">
      <section className="bounded-tool" aria-label="有界问答">
        <header><div><p className="eyebrow">当前作品问题</p><h3>有界问答</h3></div>{activeQa&&<span className="run-state state-running">{stage(activeQa.status)}</span>}</header>
        {!readOnly&&<form className="qa-form" onSubmit={(event)=>{event.preventDefault();void start("story_qa");}}><label>你的问题<textarea value={question} maxLength={1000} onChange={(event)=>setQuestion(event.target.value)} placeholder="例如：林默目前是否知道北门会提前开启？" /></label><fieldset><legend>限定依据</legend>{(["confirmed","written","planned"] as const).map((value)=><label key={value}><input type="checkbox" checked={scope.includes(value)} onChange={()=>toggleScope(value)} />{qaLayerLabel[value]}</label>)}</fieldset><Button className="secondary" type="submit" disabled={Boolean(busy)||Boolean(activeQa)||!question.trim()||!draft||dirty}>提交问题</Button></form>}
        {readOnly&&!qaRuns.length&&<p className="muted">窄窗口仅浏览已有回答；请在宽屏窗口提问。</p>}
        <div className="bounded-run-list">{qaRuns.map((run)=><article key={run.run_id} className={`bounded-run status-${run.status}${run.is_stale?" stale":""}`}><header><strong>{run.question||"历史问题"}</strong><span>{run.is_stale?"依据已变化":qaStatusLabel[run.analysis?.answer_status??""]??stage(run.status)}</span></header>{activeAnalysis(run)&&<p className="analysis-pending">{stage(run.stage)}；不会展示中间推理。</p>}{["failed","timed_out","cancelled"].includes(run.status)&&<p className="inline-error">{labelError({code:run.error_code})}</p>}{run.analysis&&<><p className="qa-answer">{run.analysis.answer}</p>{run.analysis.findings?.map((finding,index)=><section className={`qa-finding stance-${finding.stance}`} key={`${finding.layer}:${index}`}><header><span>{qaLayerLabel[finding.layer]}</span><em>{qaStanceLabel[finding.stance]}</em></header><p>{finding.text}</p><EvidenceLinks sources={finding.evidence} navigate={go}/></section>)}</>}<footer><small>草稿 r{run.draft_revision} · 来源 r{run.source_revision} · Story Memory V{run.source_memory_version} · Author Context V{run.author_context_version} · 作者伏笔 V{run.foreshadow_version??0} · 检索 {run.retrieval?.method_version??"—"}</small>{renderRunActions(run)}</footer></article>)}</div>
      </section>
      <section className="bounded-tool" aria-label="伏笔管理">
        <header><div><p className="eyebrow">作者记录是主数据</p><h3>伏笔记录</h3></div>{!readOnly&&<Button className="secondary" disabled={Boolean(busy)||Boolean(activeScan)||!draft||dirty} onClick={()=>void start("foreshadow_scan")}>{activeScan?"扫描中":"扫描已写正文"}</Button>}</header>
        {!readOnly&&<form className="foreshadow-form" onSubmit={saveRecord}><label>标题<input value={editor.title} maxLength={120} onChange={(event)=>setEditor({...editor,title:event.target.value})} /></label><label>说明<textarea value={editor.description} maxLength={1200} onChange={(event)=>setEditor({...editor,description:event.target.value})} /></label><label>状态<select value={editor.status} onChange={(event)=>setEditor({...editor,status:event.target.value as ForeshadowRecord["status"]})}>{Object.entries(foreshadowStatusLabel).map(([value,label])=><option key={value} value={value}>{label}</option>)}</select></label><ForeshadowReferenceSelect label="埋设章节 / 来源" value={editor.planted_reference} setValue={(value)=>setEditor({...editor,planted_reference:value})} chapters={chapters} disabled={Boolean(busy)}/><ForeshadowReferenceSelect label="回收章节 / 来源" value={editor.resolved_reference} setValue={(value)=>setEditor({...editor,resolved_reference:value})} chapters={chapters} disabled={Boolean(busy)}/><div className="form-actions"><Button className="primary" type="submit" disabled={Boolean(busy)||!editor.title.trim()||!editor.description.trim()||(Boolean(editingId)&&editingBaseVersion===null)}>{editingId?"保存修改":"新建作者记录"}</Button>{editingId&&<Button type="button" onClick={()=>{setEditingId(null);setEditingBaseVersion(null);setEditor(emptyForeshadowEditor);}}>取消编辑</Button>}</div></form>}
        <div className="foreshadow-records">{snapshot?.records.map((record)=><article key={record.id} id={`foreshadow-${record.id}`} className={record.archived_at?"archived":""}><header><div><strong>{record.title}</strong><small>作者记录 · V{record.version}</small></div><span>{record.archived_at?"已归档":foreshadowStatusLabel[record.status]}</span></header><p>{record.description}</p><div className="foreshadow-links">{record.planted&&<a href={record.planted.source_path} onClick={(event)=>protectSourceNavigation(event,record.planted?.source_path,go)}>埋设：第 {record.planted.chapter_number} 章{record.planted.source_label?` · ${record.planted.source_label}`:""}</a>}{record.resolved&&<a href={record.resolved.source_path} onClick={(event)=>protectSourceNavigation(event,record.resolved?.source_path,go)}>回收：第 {record.resolved.chapter_number} 章{record.resolved.source_label?` · ${record.resolved.source_label}`:""}</a>}</div>{!readOnly&&!record.archived_at&&<footer><Button className="quiet" disabled={Boolean(busy)} onClick={()=>{setEditingId(record.id);setEditingBaseVersion(record.version);setEditor(recordEditor(record));}}>编辑</Button><Button className="quiet" disabled={Boolean(busy)} onClick={()=>void archiveRecord(record)}>归档</Button></footer>}</article>)}{snapshot&&!snapshot.records.length&&<p className="muted">还没有作者伏笔记录；AI 候选不会自动出现在这里。</p>}</div>
        {scanRuns.map((run)=><article key={run.run_id} className={`foreshadow-scan bounded-run status-${run.status}${run.is_stale?" stale":""}`}><header><div><strong>AI 伏笔候选</strong><small>{timestampLabel(run.created_at)}</small></div><span>{run.is_stale?"依据已变化":stage(run.status)}</span></header>{activeAnalysis(run)&&<p className="analysis-pending">{stage(run.stage)}；扫描只读取已绑定内容。</p>}{["failed","timed_out","cancelled"].includes(run.status)&&<p className="inline-error">{labelError({code:run.error_code})}</p>}{run.analysis&&<><p>{run.analysis.summary}</p>{(run.analysis.candidates as ForeshadowCandidate[]|undefined)?.map((candidate)=><section className="foreshadow-candidate" key={candidate.id} id={`foreshadow-candidate-${candidate.id}`}><header><div><strong>{candidate.title}</strong><small>AI 候选 · {foreshadowStatusLabel[candidate.suggested_status]}</small></div><span>{candidate.decision_status==="pending"?"待作者决定":candidate.decision_status==="rejected"?"作者已拒绝":candidate.decision_status==="edited"?"编辑后接受":"作者已接受"}</span></header><p>{candidate.description}</p><EvidenceLinks sources={candidate.evidence} navigate={go}/>{!readOnly&&candidate.decision_status==="pending"&&!run.is_stale&&<div className="candidate-review"><details><summary>编辑后接受</summary>{(()=>{const value=candidateEdits[candidate.id]??candidateEditor(candidate);return <div className="candidate-edit-fields"><label>标题<input value={value.title} maxLength={120} onChange={(event)=>changeCandidate(candidate,{title:event.target.value})} /></label><label>说明<textarea value={value.description} maxLength={1200} onChange={(event)=>changeCandidate(candidate,{description:event.target.value})} /></label><label>状态<select value={value.status} onChange={(event)=>changeCandidate(candidate,{status:event.target.value as ForeshadowRecord["status"]})}>{Object.entries(foreshadowStatusLabel).map(([option,label])=><option key={option} value={option}>{label}</option>)}</select></label><ForeshadowReferenceSelect label="埋设章节 / 来源" value={value.planted_reference} setValue={(next)=>changeCandidate(candidate,{planted_reference:next})} chapters={chapters} disabled={Boolean(busy)}/><ForeshadowReferenceSelect label="回收章节 / 来源" value={value.resolved_reference} setValue={(next)=>changeCandidate(candidate,{resolved_reference:next})} chapters={chapters} disabled={Boolean(busy)}/><Button className="primary" disabled={Boolean(busy)||!value.title.trim()||!value.description.trim()} onClick={()=>void decide(run,candidate,"edited")}>保存为作者记录</Button></div>;})()}</details><div className="form-actions"><Button className="secondary" disabled={Boolean(busy)} onClick={()=>void decide(run,candidate,"accepted")}>接受</Button><Button className="quiet" disabled={Boolean(busy)} onClick={()=>void decide(run,candidate,"rejected")}>拒绝</Button></div></div>}</section>)}</>}<footer><small>草稿 r{run.draft_revision} · 来源 r{run.source_revision} · Story Memory V{run.source_memory_version} · Author Context V{run.author_context_version} · 作者伏笔 V{run.foreshadow_version??0} · 检索 {run.retrieval?.method_version??"—"}</small>{renderRunActions(run)}</footer></article>)}
      </section>
    </div>
  </details>;
}

const revisionPriorityLabel:Record<RevisionTaskPriority,string>={high:"高",medium:"中",low:"低"};
const revisionTaskStatusLabel:Record<RevisionTask["status"],string>={todo:"待处理",in_progress:"进行中",completed:"已完成"};
type RevisionCandidateEditor={title:string;instruction:string;priority:RevisionTaskPriority};
const revisionCandidateEditor=(candidate:RevisionPlanCandidate):RevisionCandidateEditor=>({title:candidate.title,instruction:candidate.instruction,priority:candidate.priority});

function RevisionPlanTools({project,draft,run,readOnly,dirty,busy,recheck,go}:{project:Project;draft:Draft|null;run:Run|null;readOnly:boolean;dirty:boolean;busy:boolean;recheck:()=>Promise<void>;go:(href:string)=>void}){
  const [snapshot,setSnapshot]=useState<RevisionTaskSnapshot|null>(null);
  const [runs,setRuns]=useState<WritingAnalysisRun[]>([]);
  const [selected,setSelected]=useState<string[]>([]);
  const [candidateEdits,setCandidateEdits]=useState<Record<string,RevisionCandidateEditor>>({});
  const [localBusy,setLocalBusy]=useState(""),[notice,setNotice]=useState(""),[conflict,setConflict]=useState(false);
  const refreshEpoch=useRef(0),refreshAbort=useRef<AbortController|null>(null);
  const draftRevision=draft?.revision;
  const sourceRunId=run?.run_id;
  const refresh=useCallback(async(silent=false)=>{
    const epoch=++refreshEpoch.current;
    refreshAbort.current?.abort();
    const controller=new AbortController();refreshAbort.current=controller;
    try{
      const [tasks,plans]=await Promise.all([
        request<RevisionTaskSnapshot>(`/projects/${project.id}/revision-tasks?include_completed=true`,{signal:controller.signal}),
        request<{run:WritingAnalysisRun|null;runs:WritingAnalysisRun[]}>(`/projects/${project.id}/analyses?analysis_type=revision_plan&limit=20`,{signal:controller.signal}),
      ]);
      if(controller.signal.aborted||epoch!==refreshEpoch.current)return;
      setSnapshot(tasks);setRuns(plans.runs??[]);
      return true;
    }catch(error){if((error as Error).name!=="AbortError"&&!silent&&epoch===refreshEpoch.current)setNotice(labelError(error));return false;}
    finally{if(refreshAbort.current===controller)refreshAbort.current=null;}
  },[project.id]);
  const hasActive=runs.some(activeAnalysis);
  useEffect(()=>{void draftRevision;void sourceRunId;const timer=window.setTimeout(()=>{setSelected([]);void refresh();},0);return()=>{window.clearTimeout(timer);refreshEpoch.current+=1;refreshAbort.current?.abort();};},[refresh,draftRevision,sourceRunId]);
  useEffect(()=>{if(!hasActive)return;const timer=window.setInterval(()=>void refresh(true),700);return()=>window.clearInterval(timer);},[refresh,hasActive]);
  const eligible=(run?.status==="completed"&&!run.is_stale?run.issues??[]:[]).filter((issue)=>issue.status==="open"&&!issue.decision&&(issue.evidence??[]).some((source)=>source.sufficiency==="sufficient"));
  const eligibleIds=new Set(eligible.map((issue)=>issue.id)),effectiveSelected=selected.filter((issueId)=>eligibleIds.has(issueId));
  const toggleIssue=(issueId:string)=>setSelected((current)=>{const visible=current.filter((id)=>eligibleIds.has(id));return visible.includes(issueId)?visible.filter((id)=>id!==issueId):visible.length<8?[...visible,issueId]:visible;});
  const start=async()=>{if(!draft||!effectiveSelected.length)return;if(dirty){setNotice("请先显式保存当前草稿；修订建议只绑定已保存版本。");return;}setLocalBusy("start");setNotice("");try{await json(`/projects/${project.id}/analyses`,"POST",{analysis_type:"revision_plan",draft_id:draft.id,draft_revision:draft.revision,issue_ids:effectiveSelected});setSelected([]);setNotice("修订建议已提交；每条候选仍需作者接受、编辑后接受或拒绝。");await refresh(true);}catch(error){setNotice(labelError(error));}finally{setLocalBusy("");}};
  const runAction=async(target:WritingAnalysisRun,action:"cancel"|"retry")=>{setLocalBusy(target.run_id);setNotice("");try{await json(`/projects/${project.id}/analyses/${target.run_id}/${action}`,"POST",{client_request_id:crypto.randomUUID()});await refresh(true);}catch(error){setNotice(labelError(error));}finally{setLocalBusy("");}};
  const changeCandidate=(candidate:RevisionPlanCandidate,patch:Partial<RevisionCandidateEditor>)=>setCandidateEdits((current)=>({...current,[candidate.id]:{...(current[candidate.id]??revisionCandidateEditor(candidate)),...patch}}));
  const decide=async(target:WritingAnalysisRun,candidate:RevisionPlanCandidate,decision:"accepted"|"edited"|"rejected")=>{if(!snapshot)return;setLocalBusy(candidate.id);setNotice("");setConflict(false);try{const edited=candidateEdits[candidate.id]??revisionCandidateEditor(candidate);const result=await json<{revision_tasks:RevisionTaskSnapshot}>(`/projects/${project.id}/analyses/${target.run_id}/revision-candidates/${candidate.id}/decision`,"POST",{base_task_version:snapshot.task_version,decision,...(decision==="edited"?{edited}:{})});setSnapshot(result.revision_tasks);setNotice(decision==="rejected"?"修订候选已拒绝，没有创建任务。":"修订候选已确认并创建持久任务；正文仍需作者手动修改并保存。");await refresh(true);}catch(error){setConflict((error as ApiFailure).code==="revision_task_version_conflict");setNotice(labelError(error));}finally{setLocalBusy("");}};
  const updateTask=async(task:RevisionTask,status:RevisionTask["status"])=>{setLocalBusy(task.id);setNotice("");setConflict(false);try{const next=await json<RevisionTaskSnapshot>(`/projects/${project.id}/revision-tasks/${task.id}`,"PATCH",{base_version:task.version,status});setSnapshot(next);setNotice(status==="completed"?"任务已标记完成。连续性问题仍保持原状态，也不会自动复检或修改 Story Memory。":"任务进度已更新；它与建议所绑定的旧分析状态相互独立。");}catch(error){setConflict((error as ApiFailure).code==="revision_task_version_conflict");setNotice(labelError(error));}finally{setLocalBusy("");}};
  const loadLatest=async()=>{setLocalBusy("reload");setNotice("正在载入最新任务版本；候选编辑内容会继续保留。");try{if(await refresh(true)){setConflict(false);setNotice("已载入最新任务与候选状态；候选编辑内容仍保留，请核对后主动重试。");}else setNotice("载入最新任务失败；当前候选编辑内容仍保留，请稍后重试。");}finally{setLocalBusy("");}};
  const returnToDraft=()=>{const editor=document.getElementById("draft-body");editor?.scrollIntoView({behavior:"smooth",block:"center"});window.setTimeout(()=>editor?.focus(),250);};
  const activeRun=runs.find(activeAnalysis);
  return <details className="bounded-story-tools revision-plan-tools" role="region" aria-label="修订计划与任务">
    <summary className="bounded-tools-header"><div><p className="eyebrow">作者掌控的修订闭环</p><h2>修订计划与任务</h2><p>从当前连续性问题生成有界行动建议；确认后仅创建任务，不会改写正文或事实。</p></div><small>任务 V{snapshot?.task_version??0} · 活动 {snapshot?.tasks.filter((task)=>task.status!=="completed").length??0} · 历史计划 {runs.length}</small></summary>
    <div className="bounded-tools-intro">先选择当前检查中的问题，再逐条决定候选。接受任务后回到同一草稿手动修改、显式保存，并在需要时主动重新检查。</div>
    {notice&&<p className="notice" role="status">{notice}</p>}
    {conflict&&<div className="bounded-conflict" role="alert"><p>服务器上的修订任务版本已变化；候选编辑内容仍保留。请载入最新版本、核对状态后再主动重试。</p><Button className="secondary" disabled={Boolean(localBusy)} onClick={()=>void loadLatest()}>载入最新任务</Button></div>}
    {dirty&&!readOnly&&<p className="bounded-dirty-note" role="note">当前草稿有未保存修改：不能生成、重试建议或重新检查；已接受任务仍可更新进度。</p>}
    <div className="revision-plan-layout">
      <section className="revision-plan-column" aria-label="从连续性问题生成修订建议">
        <header><div><p className="eyebrow">当前有效检查</p><h3>选择问题</h3></div>{activeRun&&<span className="run-state state-running">{stage(activeRun.status)}</span>}</header>
        {!readOnly&&<>{eligible.length?<fieldset className="revision-issue-picker"><legend>最多选择 8 条</legend>{eligible.map((issue)=><label key={issue.id}><input type="checkbox" checked={effectiveSelected.includes(issue.id)} disabled={Boolean(localBusy)||(!effectiveSelected.includes(issue.id)&&effectiveSelected.length>=8)} onChange={()=>toggleIssue(issue.id)} /><span><strong>{categoryLabel(issue.category)} · {statusLabel(issue.severity)}</strong><small>{issue.claim_text||issue.explanation}</small></span></label>)}</fieldset>:<p className="muted">当前没有来自同一次有效检查、证据充分且未作决定的问题。请先保存草稿并运行连续性检查。</p>}<Button className="secondary" disabled={Boolean(localBusy)||busy||Boolean(activeRun)||dirty||!draft||!effectiveSelected.length} onClick={()=>void start()}>{activeRun?"生成中":`生成修订建议${effectiveSelected.length?`（${effectiveSelected.length}）`:""}`}</Button></>}
        {readOnly&&!runs.length&&<p className="muted">窄窗口仅浏览已有修订建议与任务；请在宽屏窗口生成或作出决定。</p>}
        <div className="revision-run-list">{runs.map((target)=><article key={target.run_id} className={`revision-run status-${target.status}${target.is_stale?" stale":""}`}><header><div><strong>AI 修订建议</strong><small>{timestampLabel(target.created_at)} · {target.issue_ids?.length??0} 个问题</small></div><span>{target.is_stale?"依据已变化":stage(target.status)}</span></header>{activeAnalysis(target)&&<p className="analysis-pending">{stage(target.stage)}；不会展示中间推理或部分结果。</p>}{["failed","timed_out","cancelled"].includes(target.status)&&<p className="inline-error">{labelError({code:target.error_code})} 未创建任何候选。</p>}{target.analysis&&<><p>{target.analysis.summary}</p>{(target.analysis.candidates as RevisionPlanCandidate[]|undefined)?.map((candidate)=><section className="revision-candidate" key={candidate.id} id={`revision-candidate-${candidate.id}`}><header><div><strong>{candidate.title}</strong><small>优先级 {revisionPriorityLabel[candidate.priority]} · 对应 Issue {candidate.issue_id}</small></div><span>{candidate.decision_status==="pending"?"待作者决定":candidate.decision_status==="rejected"?"作者已拒绝":candidate.decision_status==="edited"?"编辑后接受":"作者已接受"}</span></header><p>{candidate.instruction}</p><EvidenceLinks sources={candidate.evidence} navigate={go}/>{!readOnly&&candidate.decision_status==="pending"&&!target.is_stale&&<div className="candidate-review"><details><summary>编辑后接受</summary>{(()=>{const value=candidateEdits[candidate.id]??revisionCandidateEditor(candidate);return <div className="candidate-edit-fields"><label>任务标题<input value={value.title} maxLength={120} onChange={(event)=>changeCandidate(candidate,{title:event.target.value})} /></label><label>行动说明<textarea value={value.instruction} maxLength={1200} onChange={(event)=>changeCandidate(candidate,{instruction:event.target.value})} /></label><label>优先级<select value={value.priority} onChange={(event)=>changeCandidate(candidate,{priority:event.target.value as RevisionTaskPriority})}>{(["high","medium","low"] as const).map((priority)=><option key={priority} value={priority}>{revisionPriorityLabel[priority]}</option>)}</select></label><Button className="primary" disabled={Boolean(localBusy)||!value.title.trim()||!value.instruction.trim()} onClick={()=>void decide(target,candidate,"edited")}>编辑后创建任务</Button></div>;})()}</details><div className="form-actions"><Button className="secondary" disabled={Boolean(localBusy)} onClick={()=>void decide(target,candidate,"accepted")}>接受并创建任务</Button><Button className="quiet" disabled={Boolean(localBusy)} onClick={()=>void decide(target,candidate,"rejected")}>拒绝</Button></div></div>}{candidate.decision?.after&&<p className="revision-created-link">已创建任务：<a href={`#revision-task-${candidate.decision.after.id}`}>{candidate.decision.after.title}</a></p>}</section>)}</>}
          <footer><small>草稿 r{target.draft_revision} · 来源 r{target.source_revision} · Story Memory V{target.source_memory_version} · Author Context V{target.author_context_version} · 作者伏笔 V{target.foreshadow_version??0}</small>{!readOnly&&<div className="analysis-result-actions">{activeAnalysis(target)&&<Button disabled={Boolean(localBusy)} onClick={()=>void runAction(target,"cancel")}>取消</Button>}{retryableAnalysis(target)&&<Button disabled={Boolean(localBusy)||target.is_stale||dirty} onClick={()=>void runAction(target,"retry")}>重试</Button>}</div>}</footer></article>)}</div>
      </section>
      <section className="revision-plan-column" aria-label="持久修订任务">
        <header><div><p className="eyebrow">独立任务层</p><h3>修订任务</h3></div><span className="version-chip">V{snapshot?.task_version??0}</span></header>
        <p className="revision-boundary">任务进度是作者的工作记录。标记完成不会解决 Issue、运行检查或修改正文、Story Memory 与 Author Context。</p>
        <div className="revision-task-list">{snapshot?.tasks.map((task)=><article key={task.id} id={`revision-task-${task.id}`} className={`revision-task priority-${task.priority} status-${task.status}`}><header><div><strong>{task.title}</strong><small>优先级 {revisionPriorityLabel[task.priority]} · 任务 V{task.version}</small></div><span>{revisionTaskStatusLabel[task.status]}</span></header><p>{task.instruction}</p><EvidenceLinks sources={task.evidence} navigate={go}/>{!readOnly&&<footer><Button className="quiet" disabled={Boolean(localBusy)||busy} onClick={returnToDraft}>回到同一草稿</Button><label>任务进度<select aria-label={`${task.title}任务进度`} value={task.status} disabled={Boolean(localBusy)||busy} onChange={(event)=>void updateTask(task,event.target.value as RevisionTask["status"])}>{(["todo","in_progress","completed"] as const).map((status)=><option key={status} value={status}>{revisionTaskStatusLabel[status]}</option>)}</select></label></footer>}</article>)}{snapshot&&!snapshot.tasks.length&&<p className="muted">尚无修订任务。AI 候选只有在作者接受后才会进入这里。</p>}</div>
        {!readOnly&&<div className="revision-loop-actions"><Button className="secondary" disabled={Boolean(localBusy)||busy||dirty||!draft} onClick={()=>void recheck()}>显式重新检查</Button><small>请先手动修改并保存草稿；任务完成状态不会触发此操作。</small></div>}
      </section>
    </div>
  </details>;
}

function ProjectContextNotices({
  project,
  tab,
  readOnly,
  busy,
  tutorialStep,
  finishTutorial,
  advanceTutorial,
  requestTutorialGuidance,
  go,
}: {
  project: Project;
  tab: string;
  readOnly: boolean;
  busy: string;
  tutorialStep: TutorialStep;
  finishTutorial: (outcome: "complete" | "skip") => Promise<void>;
  advanceTutorial: (event: TutorialEvent) => Promise<TutorialProgress>;
  requestTutorialGuidance: () => void;
  go: (href: string) => void;
}) {
  const tutorialCopy = {
    1: {
      title: "认识作品资料与 Story Memory",
      task: "打开 Story Memory，找到一条已经确认的事实，并查看它的章节来源。",
      action: tab === "memory" ? "定位事实来源" : "去 Story Memory",
    },
    2: {
      title: "进入连续性检查",
      task: "来源已经打开。接下来进入写作与检查，找到预设的高风险问题。",
      action: "去写作与检查",
    },
    3: {
      title: "对照当前草稿与历史证据",
      task: "在问题列表中打开高风险项，核对当前草稿、历史证据和冲突说明。",
      action: tab === "workspace" ? "定位高风险问题" : "返回写作与检查",
    },
    4: {
      title: "作出一次作者决定",
      task: readOnly
        ? "移动端可以浏览完整证据。请在桌面端继续完成作者决定。"
        : "在证据抽屉底部选择保留写法、接受建议并编辑，或标记为误报。",
      action: readOnly ? "查看桌面端提示" : "定位作者决定",
    },
    5: {
      title: "作者决定已记录",
      task: "作者决定已经记录。结束隔离教学后，你会回到没有真实作品的工作台。",
      action: "完成教学",
    },
  }[tutorialStep];
  const requestAfterContextChange = (delay = 0) =>
    window.setTimeout(requestTutorialGuidance, delay);
  const requestWhenScrollSettles = () => {
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      requestAfterContextChange();
      return;
    }
    let done = false;
    let settleTimer = 0;
    let fallbackTimer = 0;
    const finish = () => {
      if (done) return;
      done = true;
      window.removeEventListener("scroll", onScroll, true);
      window.clearTimeout(settleTimer);
      window.clearTimeout(fallbackTimer);
      requestTutorialGuidance();
    };
    const onScroll = () => {
      window.clearTimeout(settleTimer);
      settleTimer = window.setTimeout(finish, 240);
    };
    window.addEventListener("scroll", onScroll, true);
    onScroll();
    fallbackTimer = window.setTimeout(finish, 2_000);
  };
  const locate = (selector: string) => {
    const target = document.querySelector<HTMLElement>(selector);
    requestWhenScrollSettles();
    target?.scrollIntoView({
      block: "center",
      behavior: window.matchMedia("(prefers-reduced-motion: reduce)").matches
        ? "auto"
        : "smooth",
    });
  };
  const navigate = (href: string, selector?: string) => {
    go(href);
    window.setTimeout(() => {
      const target = selector
        ? document.querySelector<HTMLElement>(selector)
        : null;
      target?.scrollIntoView({
        block: "center",
        behavior: "auto",
      });
      requestAfterContextChange(target ? 100 : 400);
    }, 500);
  };
  const runTutorialAction = async () => {
    if (tutorialStep === 1) {
      if (tab === "memory")
        locate(".memory-source:not(:disabled)");
      else navigate(`/projects/${project.id}/memory`);
      return;
    }
    if (tutorialStep === 2) {
      try {
        await advanceTutorial("continuity_issue_located");
        navigate(`/projects/${project.id}/workspace`, ".issue-row.severity-high");
      } catch {
        // The shared request path keeps the author on the current step and
        // resynchronizes the canonical server progress.
      }
      return;
    }
    if (tutorialStep === 3) {
      if (tab === "workspace")
        locate(".issue-row.severity-high");
      else navigate(`/projects/${project.id}/workspace`);
      return;
    }
    if (tutorialStep === 4) {
      locate(
        readOnly
          ? ".tutorial-mobile-decision-note"
          : ".author-decision, .issue-row.severity-high, .issue-row",
      );
      return;
    }
    if (tutorialStep === 5) void finishTutorial("complete");
  };
  return (
    <>
      {project.is_tutorial && (
        <section className={tutorialStep === 5 ? "tutorial-mode-bar tutorial-completion-bar" : "tutorial-mode-bar"} aria-label="教学模式">
          <div className="tutorial-progress" aria-label="教学进度">
            <div className="tutorial-step-count">
              <strong>教学 {tutorialStep} / 5</strong>
              <ol aria-label="五步教学进度">
                {([1, 2, 3, 4, 5] as TutorialStep[]).map((step) => (
                  <li
                    key={step}
                    className={step === tutorialStep ? "current" : step < tutorialStep ? "complete" : ""}
                    aria-current={step === tutorialStep ? "step" : undefined}
                    data-event={tutorialEvents[step] ?? "start"}
                  >
                    {step < tutorialStep ? "✓" : step}
                  </li>
                ))}
              </ol>
            </div>
            <div className="tutorial-copy">
              <strong>{tutorialCopy.title}</strong>
              <span>{tutorialCopy.task}</span>
              <small>隔离样例不计入真实作品、搜索或待处理问题。</small>
            </div>
          </div>
          <div className="actions">
            {tutorialStep === 5
              ? <Button className="quiet" disabled={Boolean(busy)} onClick={() => go("/")}>稍后完成</Button>
              : <Button className="quiet" disabled={Boolean(busy)} onClick={() => void finishTutorial("skip")}>跳过教学</Button>}
            <Button
              className="primary tutorial-primary-action"
              disabled={Boolean(busy)}
              onClick={() => void runTutorialAction()}
            >
              {tutorialCopy.action}
            </Button>
          </div>
        </section>
      )}
      {readOnly && (
        <p className="readonly" role="note">
          <I>◉</I>
          {project.status === "archived"
            ? "作品已归档：仅可浏览，恢复后才可保存、检查、决策、提交或 Reset。"
            : project.is_tutorial && tutorialStep === 4
              ? "移动端可以浏览完整证据。请在桌面端继续完成作者决定。"
            : "当前窗口较窄，暂为只读浏览；放大窗口即可继续写作与检查。"}
        </p>
      )}
    </>
  );
}

type ImmersiveFontSize = "small" | "medium" | "large";
type ImmersiveLineHeight = "compact" | "comfortable" | "airy";
type ImmersiveColumnWidth = "narrow" | "medium" | "wide";

function manuscriptCounts(value: string) {
  return {
    words: Array.from(value.replace(/\s+/g, "")).length,
    characters: Array.from(value).length,
  };
}

function ImmersiveEditor({
  project,
  draft,
  saved,
  run,
  busy,
  error,
  controlled,
  selectedIssueId,
  locallyResolvedIssueIds,
  fontSize,
  lineHeight,
  columnWidth,
  issuesOpen,
  setFontSize,
  setLineHeight,
  setColumnWidth,
  setIssuesOpen,
  setDraft,
  save,
  select,
  close,
}: {
  project: Project;
  draft: Draft | null;
  saved: Draft | null;
  run: Run | null;
  busy: string;
  error: unknown;
  controlled: Issue | null;
  selectedIssueId: string | null;
  locallyResolvedIssueIds: string[];
  fontSize: ImmersiveFontSize;
  lineHeight: ImmersiveLineHeight;
  columnWidth: ImmersiveColumnWidth;
  issuesOpen: boolean;
  setFontSize: (value: ImmersiveFontSize) => void;
  setLineHeight: (value: ImmersiveLineHeight) => void;
  setColumnWidth: (value: ImmersiveColumnWidth) => void;
  setIssuesOpen: (value: boolean) => void;
  setDraft: (draft: Draft) => void;
  save: () => Promise<boolean>;
  select: (issue: Issue, element: HTMLElement) => Promise<void> | void;
  close: () => void;
}) {
  const { modalRef, firstRef, containFocus } = useModalFocus<HTMLButtonElement>(close);
  const dirty = Boolean(draft && saved && (draft.title !== saved.title || draft.body !== saved.body));
  const saving = busy === "保存草稿" || busy === "保存受控修订";
  const counts = manuscriptCounts(draft?.body ?? "");
  const saveState = saving ? "saving" : error ? "failed" : dirty ? "unsaved" : "saved";
  const saveLabel = saving ? "保存中" : error ? "保存失败" : dirty ? "未保存" : "已保存";
  const issues = run?.issues ?? [];
  return (
    <section
      ref={modalRef}
      className="immersive-editor"
      role="dialog"
      aria-modal="true"
      aria-label="沉浸写作"
      data-font-size={fontSize}
      data-line-height={lineHeight}
      data-column-width={columnWidth}
      data-issues={issuesOpen ? "open" : "closed"}
      onKeyDown={containFocus}
    >
      <header className="immersive-header">
        <div className="immersive-identity">
          <span>第 {draft?.chapter_number ?? "—"} 章 · revision {draft?.revision ?? "—"}</span>
          <strong>{project.title}</strong>
        </div>
        <div className="immersive-display-settings" aria-label="写作显示设置">
          <label>
            <span>正文字号</span>
            <select value={fontSize} onChange={(event) => setFontSize(event.target.value as ImmersiveFontSize)}>
              <option value="small">17 px</option>
              <option value="medium">19 px</option>
              <option value="large">21 px</option>
            </select>
          </label>
          <label>
            <span>行距</span>
            <select value={lineHeight} onChange={(event) => setLineHeight(event.target.value as ImmersiveLineHeight)}>
              <option value="compact">1.65</option>
              <option value="comfortable">1.85</option>
              <option value="airy">2.05</option>
            </select>
          </label>
          <label>
            <span>正文列</span>
            <select value={columnWidth} onChange={(event) => setColumnWidth(event.target.value as ImmersiveColumnWidth)}>
              <option value="narrow">窄</option>
              <option value="medium">中</option>
              <option value="wide">宽</option>
            </select>
          </label>
        </div>
        <div className="immersive-header-actions">
          <Button
            ariaLabel={issuesOpen ? "收起连续性问题辅助栏" : "展开连续性问题辅助栏"}
            ariaExpanded={issuesOpen}
            onClick={() => setIssuesOpen(!issuesOpen)}
          >
            问题 {issues.length}
          </Button>
          <Button buttonRef={firstRef} ariaLabel="退出沉浸写作并返回写作与检查" onClick={close}>退出沉浸</Button>
        </div>
      </header>
      {controlled && <p className="immersive-lineage-note" role="note">受控修订仍绑定当前 Issue 与来源版本；保存会沿用原决定谱系。</p>}
      <div className="immersive-canvas">
        <div className="immersive-manuscript" role="document" aria-label="沉浸写作正文">
          <div className="immersive-writing-column">
            <label className="immersive-title-field">
              <span className="sr-only">沉浸写作章节标题</span>
              <input
                value={draft?.title ?? ""}
                disabled={Boolean(busy)}
                onChange={(event) => draft && setDraft({ ...draft, title: event.target.value })}
              />
            </label>
            <label className="immersive-body-field">
              <span className="sr-only">沉浸写作草稿正文</span>
              <textarea
                id="immersive-draft-body"
                value={draft?.body ?? ""}
                disabled={Boolean(busy)}
                spellCheck={false}
                onChange={(event) => draft && setDraft({ ...draft, body: event.target.value })}
              />
            </label>
          </div>
        </div>
        <aside id="immersive-issues" className="immersive-issues" aria-label="连续性问题辅助栏">
          <header>
            <div><p className="eyebrow">检查辅助</p><h2>连续性问题</h2></div>
            <Button className="quiet" ariaLabel="收起连续性问题辅助栏" onClick={() => setIssuesOpen(false)}>收起</Button>
          </header>
          {run ? (
            <>
              <p className="run-meta">{stage(run.stage)} · {run.is_stale ? "检查依据已过期" : "基于当前保存版本"}</p>
              <ul className="immersive-issue-list">
                {issues.map((issue) => (
                  <li key={issue.id}>
                    <Button
                      className={selectedIssueId === issue.id ? "selected" : ""}
                      ariaPressed={selectedIssueId === issue.id}
                      onClick={(event) => select(issue, event.currentTarget)}
                    >
                      <span><strong>{categoryLabel(issue.category)}</strong><small>{statusLabel(issue.severity)}</small></span>
                      <span>{issue.claim_text || issue.explanation}</span>
                      <small>{issue.decision || locallyResolvedIssueIds.includes(issue.id) ? "决定已记录" : "查看证据"}</small>
                    </Button>
                  </li>
                ))}
              </ul>
              {!issues.length && <p className="immersive-issues-empty">当前检查没有可审阅 Issue。</p>}
            </>
          ) : <p className="immersive-issues-empty">尚未运行连续性检查。退出沉浸模式后可回到完整检查布局。</p>}
        </aside>
      </div>
      <footer className="immersive-footer">
        <div className="immersive-counts" aria-label="实时写作统计">
          <span><strong>{counts.words.toLocaleString("zh-CN")}</strong> 字</span>
          <span><strong>{counts.characters.toLocaleString("zh-CN")}</strong> 字符</span>
        </div>
        <p className={`immersive-save-state ${saveState}`} role="status" aria-live="polite">
          <strong>{saveLabel}</strong>
          <span>{error ? labelError(error) : "仅在点击保存时写入；退出沉浸模式不会丢失当前输入。"}</span>
        </p>
        <Button
          className="primary"
          ariaLabel="显式保存草稿"
          disabled={!draft || !dirty || Boolean(busy)}
          ariaBusy={saving}
          onClick={() => void save()}
        >
          <Icon name="save" />{saving ? "正在保存" : controlled ? "保存受控修订" : "保存草稿"}
        </Button>
      </footer>
    </section>
  );
}

function ProjectPage(p: {
  tab: string;
  project: Project;
  chapters: Chapter[];
  outline: {
    chapter_nodes?: {
      id: string;
      chapter_number: number;
      title: string;
      summary: string;
      status: string;
    }[];
  } | null;
  characters: {
    id: string;
    name: string;
    role_type: string;
    identity: string;
    goal: string;
    current_state: string;
    knowledge_boundary: string;
  }[];
  world: { id: string; entry_type: string; name: string; summary: string }[];
  authorContext: AuthorContext | null;
  authorBusy: string;
  memories: Memory[];
  initialization: MemoryInitialization | null;
  memoryDelta: MemoryDelta | null;
  coverage: MemoryCoverage | null;
  draft: Draft | null;
  saved: Draft | null;
  run: Run | null;
  pairedRun: Run | null;
  contextBrief: WritingAnalysisRun | null;
  planAlignment: WritingAnalysisRun | null;
  analysisBusy: "context_brief" | "plan_alignment" | "";
  locallyResolvedIssueIds: string[];
  selectedIssueId: string | null;
  tutorialStep: TutorialStep;
  requestTutorialGuidance: () => void;
  readOnly: boolean;
  busy: string;
  error: unknown;
  controlled: Issue | null;
  changeSet: ChangeSet | null;
  setDraft: (v: Draft) => void;
  save: () => Promise<boolean>;
  check: () => Promise<void>;
  cancelRun: () => Promise<void>;
  retryRun: () => Promise<void>;
  startAnalysis: (kind: "context_brief" | "plan_alignment") => Promise<void>;
  cancelAnalysis: (run: WritingAnalysisRun) => Promise<void>;
  retryAnalysis: (run: WritingAnalysisRun) => Promise<void>;
  select: (i: Issue, el: HTMLElement) => Promise<void> | void;
  review: () => Promise<void>;
  commit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  startMemoryInitialization: () => Promise<void>;
  submitMemoryInitialization: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  startIncrementalReview: () => Promise<void>;
  submitMemoryDelta: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  reset: () => void;
  meta: () => void;
  archive: () => void;
  finishTutorial: (outcome: "complete" | "skip") => Promise<void>;
  advanceTutorial: (event: TutorialEvent) => Promise<TutorialProgress>;
  mutateAuthorContext: (
    endpoint: string,
    method: "POST" | "PATCH",
    payload: Record<string, unknown>,
    busyLabel: string,
  ) => Promise<AuthorContext | null>;
  openMemorySource: (memory: Memory, element: HTMLButtonElement) => Promise<void> | void;
  go: (href: string) => void;
}) {
  const [immersiveOpen, setImmersiveOpen] = useState(false);
  const [immersiveFontSize, setImmersiveFontSize] = useState<ImmersiveFontSize>("medium");
  const [immersiveLineHeight, setImmersiveLineHeight] = useState<ImmersiveLineHeight>("comfortable");
  const [immersiveColumnWidth, setImmersiveColumnWidth] = useState<ImmersiveColumnWidth>("medium");
  const [immersiveIssuesOpen, setImmersiveIssuesOpen] = useState(true);
  const immersiveTrigger = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    const hash=window.location.hash.slice(1);
    if(!hash)return;
    const reveal=window.setTimeout(()=>{
      const target=document.getElementById(hash);
      if(!target)return;
      let ancestor=target.parentElement;
      while(ancestor){if(ancestor instanceof HTMLDetailsElement)ancestor.open=true;ancestor=ancestor.parentElement;}
      target.scrollIntoView({block:"center"});
      target.focus({preventScroll:true});
    },0);
    return()=>window.clearTimeout(reveal);
  },[p.project.id,p.tab,p.chapters,p.memories]);
  useEffect(() => {
    const closeOnNarrowViewport = () => {
      if (window.innerWidth < 1024) setImmersiveOpen(false);
    };
    window.addEventListener("resize", closeOnNarrowViewport);
    return () => window.removeEventListener("resize", closeOnNarrowViewport);
  }, []);
  const closeImmersive = () => {
    setImmersiveOpen(false);
    setTimeout(() => immersiveTrigger.current?.focus(), 0);
  };
  const dirty = Boolean(
      p.draft &&
      p.saved &&
      (p.draft.title !== p.saved.title || p.draft.body !== p.saved.body),
    ),
    blocked = p.readOnly || Boolean(p.busy),
    contextNotices = (
      <ProjectContextNotices
        project={p.project}
        tab={p.tab}
        readOnly={p.readOnly}
        busy={p.busy}
        tutorialStep={p.tutorialStep}
        finishTutorial={p.finishTutorial}
        advanceTutorial={p.advanceTutorial}
        requestTutorialGuidance={p.requestTutorialGuidance}
        go={p.go}
      />
    );
  if (p.tab === "overview")
    return (
      <section className="project-page overview-page">
        <header className="page-header project-page-header">
          <div>
            <p className="breadcrumb">项目 / {p.project.title} / 项目概览</p>
            <h1>{p.project.title}</h1>
            <p>{p.project.summary || "此作品尚未填写说明。"}</p>
          </div>
          <div className="actions">
            <Button className="primary" onClick={() => p.go(`/projects/${p.project.id}/workspace`)}>
              <Icon name="pen" />{p.readOnly ? "查看草稿" : "继续草稿"}
            </Button>
            {!p.readOnly && (
              <MoreMenu>
                <Button onClick={p.reset}>Reset 当前作品</Button>
                {!p.project.is_tutorial && <Button onClick={p.archive}>{p.project.status === "archived" ? "恢复作品" : "归档作品"}</Button>}
                {!p.project.is_tutorial && <Button onClick={p.meta}>编辑作品信息</Button>}
              </MoreMenu>
            )}
          </div>
        </header>
        {contextNotices}
        <div className="overview-grid overview-primary-grid">
          <section className="overview-panel overview-primary-card current-draft-panel">
            <p className="eyebrow">当前草稿</p>
            <h2>第 {p.project.current_draft.chapter_number} 章</h2>
            <p>第 {p.project.current_draft.revision} 次保存 · 当前可继续写作与审阅。</p>
            <div className="overview-meta">
              <span>{p.project.chapter_count} 个章节</span>
              <span>已保存</span>
            </div>
            <Button className="quiet overview-card-action" onClick={() => p.go(`/projects/${p.project.id}/workspace`)}>打开当前草稿</Button>
          </section>
          <section className="overview-panel overview-primary-card memory-panel" aria-label="Story Memory">
            <p className="eyebrow">STORY MEMORY</p>
            <h2>Memory V{p.project.current_memory_version}</h2>
            <p className="term-help">Story Memory 是作者确认、供后续连续性检查使用的事实集合；版本号代表一次明确提交后的完整快照。</p>
            <dl className="overview-kv">
              <div><dt>当前资料版本</dt><dd>{p.project.source_revision == null ? "尚未提供" : `第 ${p.project.source_revision} 版`}</dd></div>
              <div><dt>Memory 覆盖</dt><dd>{coverageStatusLabel(p.coverage?.status)}</dd></div>
              <div><dt>检查状态</dt><dd>{p.project.continuity_status === "unchecked" ? "尚未检查" : p.project.continuity_status === "checked_clear" ? "已检查 · 0 项待处理" : `${p.project.open_issue_count ?? 0} 项待处理`}</dd></div>
              <div><dt>最近检查</dt><dd>{p.project.latest_run ? stage(p.project.latest_run.status) : "尚无"}</dd></div>
            </dl>
            <Button className="quiet overview-card-action" onClick={() => p.go(`/projects/${p.project.id}/memory`)}>查看 Story Memory</Button>
          </section>
        </div>
        <section className="project-section">
          <h2>资料摘要</h2>
          <div className="overview-grid overview-reference-grid">
            <section className="overview-panel overview-reference-card">
              <h3>大纲</h3>
              <p>{p.project.chapter_count ? `${p.project.chapter_count} 个已写章节` : "尚无已写章节"} · {p.authorContext?.story_plans.length ?? 0} 条创作规划</p>
              <Button className="quiet overview-card-action" onClick={() => p.go(`/projects/${p.project.id}/outline`)}>查看大纲</Button>
            </section>
            <section className="overview-panel overview-reference-card">
              <h3>角色</h3>
              <p>{p.characters.length} 条正文档案 · {p.authorContext?.character_plans.length ?? 0} 条角色规划</p>
              <Button className="quiet overview-card-action" onClick={() => p.go(`/projects/${p.project.id}/characters`)}>查看角色库</Button>
            </section>
            <section className="overview-panel overview-reference-card">
              <h3>世界观</h3>
              <p>{p.world.length} 条正文资料 · {p.authorContext?.world_plans.length ?? 0} 条设定规划</p>
              <Button className="quiet overview-card-action" onClick={() => p.go(`/projects/${p.project.id}/world`)}>查看世界观</Button>
            </section>
          </div>
        </section>
        <section className="project-section latest-run-section">
          <h2>最近检查</h2>
          <div className={`latest-run-row latest-run-card ${p.project.continuity_status ?? "unchecked"}`}>
            <div>
              <strong>{p.project.latest_run ? stage(p.project.latest_run.status) : "尚未检查"}</strong>
              <span>{p.project.latest_run ? (p.project.latest_run.result_origin === "demo_preset" ? "预置演示审阅数据 · 未调用 Provider" : `检查记录 ${p.project.latest_run.run_id}`) : "保存草稿后可运行连续性检查。"}</span>
            </div>
            <Button className="secondary" onClick={() => p.go(`/projects/${p.project.id}/workspace`)}>打开审阅</Button>
          </div>
        </section>
        {p.project.data_origin === "user_import" && (
          <section className="warning import-context">
            <I>!</I>
            {p.project.memory_initialization_status === "completed"
              ? "导入来源已由作者确认并建立 Memory V1。"
              : p.initialization?.status === "draft"
                ? "Story Memory 候选正在等待逐项作者审核；候选不会自动成为 canon。"
                : "导入作品尚待作者确认 Story Memory；初始化前检查会安全返回 insufficient_project_context。"}
            {p.initialization?.status === "required" && (
              <Button className="primary" disabled={blocked} onClick={() => void p.startMemoryInitialization()}>
                初始化 Story Memory
              </Button>
            )}
            {p.initialization?.status === "draft" && (
              <Button className="secondary" disabled={blocked} onClick={() => p.go(`/projects/${p.project.id}/memory`)}>
                审核候选与 Evidence
              </Button>
            )}
          </section>
        )}
      </section>
    );
  if (p.tab === "outline")
    return (
      <AuthorPlanningPage
        key="story-planning"
        kind="story"
        projectId={p.project.id}
        projectTitle={p.project.title}
        projectIsTutorial={Boolean(p.project.is_tutorial)}
        authorContext={p.authorContext}
        readOnly={p.readOnly}
        busy={p.authorBusy}
        mutate={p.mutateAuthorContext}
        context={contextNotices}
        reference={<OutlineReference chapters={p.outline?.chapter_nodes ?? []} />}
      />
    );
  if (p.tab === "characters")
    return (
      <AuthorPlanningPage
        key="character-planning"
        kind="character"
        projectId={p.project.id}
        projectTitle={p.project.title}
        projectIsTutorial={Boolean(p.project.is_tutorial)}
        authorContext={p.authorContext}
        readOnly={p.readOnly}
        busy={p.authorBusy}
        mutate={p.mutateAuthorContext}
        context={contextNotices}
        reference={<CharacterArchive projectId={p.project.id} characters={p.characters} draft={p.draft} readOnly={p.readOnly} />}
      />
    );
  if (p.tab === "world")
    return (
      <AuthorPlanningPage
        key="world-planning"
        kind="world"
        projectId={p.project.id}
        projectTitle={p.project.title}
        projectIsTutorial={Boolean(p.project.is_tutorial)}
        authorContext={p.authorContext}
        readOnly={p.readOnly}
        busy={p.authorBusy}
        mutate={p.mutateAuthorContext}
        context={contextNotices}
        reference={<WorldArchive entries={p.world} />}
      />
    );
  if (p.tab === "memory")
    return (
      <section className="project-page">
        <header className="page-header">
          <div>
            <p className="breadcrumb">项目 / {p.project.title} / Story Memory</p>
            <h1>Story Memory</h1>
            <p>Memory V{p.project.current_memory_version} · 每个版本都是作者明确提交后的完整事实快照。</p>
          </div>
        </header>
        {contextNotices}
        {p.memoryDelta?.coverage_audit && (
          <section className="notice" aria-label="增量来源覆盖审计">
            <strong>来源覆盖审计：{p.memoryDelta.coverage_audit.status}</strong>
            <p>Audit {p.memoryDelta.coverage_audit.id} · source r{p.memoryDelta.coverage_audit.source_revision} · {p.memoryDelta.coverage_audit.details.candidate_ids?.length ?? 0} 个候选均保留决定与 Evidence 谱系。</p>
            {p.memoryDelta.change_set && <p>ChangeSet {p.memoryDelta.change_set.id} · Memory V{p.memoryDelta.change_set.base_memory_version} → V{p.memoryDelta.change_set.target_memory_version} · {p.memoryDelta.change_set.items.length} 条审计项。</p>}
          </section>
        )}
        {p.memoryDelta && p.memoryDelta.status !== "not_started" && p.memoryDelta.status !== "covered" ? (
          <MemoryDeltaReview delta={p.memoryDelta} blocked={blocked} submit={p.submitMemoryDelta} openSource={p.openMemorySource} />
        ) : p.project.data_origin === "user_import" && p.initialization && (!p.memories.length || p.coverage?.status === "ready_partial") ? (
          <MemoryInitializationReview
            initialization={p.initialization}
            coverage={p.coverage}
            blocked={blocked}
            start={p.startMemoryInitialization}
            submit={p.submitMemoryInitialization}
            goToCheck={() => p.go(`/projects/${p.project.id}/workspace`)}
          />
        ) : p.memories.length ? (
          <MemoryRecords
            records={p.memories}
            openSource={p.openMemorySource}
          />
        ) : (
          <div className="empty">
            <strong>Memory V1 为空</strong>
            <p>
              {p.project.memory_initialization_status === "required"
                ? "导入作品尚待作者确认的 Story Memory；检查会返回 insufficient_project_context。"
                : "新作品没有已确认事实。"}
            </p>
          </div>
        )}
      </section>
    );
  if (p.tab === "sources")
    return (
      <SourceAppend project={p.project} draft={p.draft} chapters={p.chapters} readOnly={p.readOnly} context={contextNotices} />
    );
  return (
    <section className="project-page workspace-page">
      <header className="page-header project-page-header workspace-page-header">
        <div>
          <p className="breadcrumb">项目 / {p.project.title} / 写作与检查</p>
          <h1>{p.draft?.title || "正在读取草稿"}</h1>
          <p>{dirty ? "当前草稿有尚未保存的修改。" : "当前草稿已保存，可以继续写作或检查。"}</p>
        </div>
        {!p.readOnly && (
          <div className="actions">
            <Button
              buttonRef={immersiveTrigger}
              ariaLabel="进入沉浸写作"
              disabled={!p.draft || Boolean(p.busy)}
              onClick={() => setImmersiveOpen(true)}
            >
              <Icon name="pen" />沉浸写作
            </Button>
            {dirty || p.controlled ? (
              <Button className="primary" disabled={blocked} onClick={() => void p.save()}>
                <Icon name="save" />
                {p.controlled ? "保存受控修订" : "保存草稿"}
              </Button>
            ) : (p.run && !activeRun(p.run) && !retryableRun(p.run)) ? (
              <Button className="primary" disabled={blocked || !p.draft} onClick={() => void p.check()}>
                <Icon name="play" />
                运行连续性检查
              </Button>
            ) : null}
            <MoreMenu>
              <Button disabled={blocked} onClick={p.reset}>Reset 当前作品</Button>
              <Button disabled={blocked || !p.draft || dirty} onClick={() => p.go(`/projects/${p.project.id}/sources`)}>完成当前章节</Button>
            </MoreMenu>
          </div>
        )}
      </header>
      {contextNotices}
      {p.controlled && (
        <p className="warning">
          <I>!</I>受控编辑：只接受资料版本第 {p.run?.source_revision ?? "?"} 版 → 第
          {(p.run?.source_revision ?? 0) + 1} 版，保存后会提交“接受建议并编辑”决定。
        </p>
      )}
      {p.project.data_origin === "user_import" && p.project.memory_initialization_status !== "completed" && (
        <p className="warning">
          <I>!</I>先在 Story Memory 中完成初始化审核；空 Memory V1 不会启动连续性检查。
          <Button className="quiet" onClick={() => p.go(`/projects/${p.project.id}/memory`)}>前往审核</Button>
        </p>
      )}
      {p.coverage?.status === "update_pending" && (
        <p className="warning"><I>!</I>资料版本第 {p.project.source_revision} 版已追加；只有新增来源片段与已确认 Memory 会进入增量审阅。{p.memoryDelta?.status === "failed" ? "本次检查失败，未写入任何问题或候选，可安全重试。" : <Button className="primary" disabled={blocked} onClick={() => void p.startIncrementalReview()}>运行增量检查</Button>}</p>
      )}
      <section className="writing-assist" aria-label="AI 写作辅助">
        <header><div><p className="eyebrow">AI 写作辅助</p><h2>计划、事实与正文分层对照</h2><p>简报用于写作前准备；偏离检查只分析已保存草稿，不会修改正文或 Story Memory。</p></div>{!p.readOnly&&<div className="writing-assist-actions"><Button className="secondary" disabled={Boolean(p.analysisBusy)||!p.draft||dirty} onClick={()=>void p.startAnalysis("context_brief")}>{p.analysisBusy==="context_brief"?"正在生成":"生成章节简报"}</Button><Button className="secondary" disabled={Boolean(p.analysisBusy)||!p.draft||dirty||!p.draft.body.trim()} onClick={()=>void p.startAnalysis("plan_alignment")}>{p.analysisBusy==="plan_alignment"?"正在检查":"检查计划偏离"}</Button></div>}</header>
        {p.readOnly&&!p.contextBrief&&!p.planAlignment&&<p className="muted">当前窄窗口仅支持浏览已有分析结果；请在宽屏窗口生成或重试。</p>}
        {(p.contextBrief||p.planAlignment)&&<div className="writing-analysis-grid">{p.contextBrief&&<WritingAnalysisPanel run={p.contextBrief} readOnly={p.readOnly} busy={Boolean(p.analysisBusy)} cancel={p.cancelAnalysis} retry={p.retryAnalysis}/>} {p.planAlignment&&<WritingAnalysisPanel run={p.planAlignment} readOnly={p.readOnly} busy={Boolean(p.analysisBusy)} cancel={p.cancelAnalysis} retry={p.retryAnalysis}/>}</div>}
      </section>
      {p.run && <RunLifecycle run={p.run} blocked={blocked} cancelRun={p.cancelRun} retryRun={p.retryRun} actions={!p.readOnly} />}
      {p.pairedRun && <RunLifecycle run={p.pairedRun} blocked={blocked} cancelRun={p.cancelRun} retryRun={p.retryRun} actions={false} />}
      <div className="workspace-grid">
        <section className="editor">
          <header className="editor-top">
            <div className="editor-title">
              <strong>{dirty ? "正在编辑" : "当前草稿"}</strong>
              <span>第 {p.draft?.chapter_number ?? "—"} 章 · revision {p.draft?.revision ?? "—"}</span>
            </div>
            <span className={dirty ? "save-state unsaved" : "save-state"}>{dirty ? "● 未保存" : "✓ 已保存"}</span>
          </header>
          <label className="editor-title-input">
            <span className="sr-only">章节标题</span>
            <input
              value={p.draft?.title ?? ""}
              disabled={blocked}
              onChange={(e) =>
                p.draft && p.setDraft({ ...p.draft, title: e.target.value })
              }
            />
          </label>
          <label id="draft-source" className="draft-field">
            <span className="sr-only">草稿正文</span>
            {p.readOnly ? (
              <article className="draft-read">{p.draft?.body}</article>
            ) : (
              <textarea
                id="draft-body"
                value={p.draft?.body ?? ""}
                disabled={Boolean(p.busy)}
                onChange={(e) =>
                  p.draft && p.setDraft({ ...p.draft, body: e.target.value })
                }
              />
            )}
          </label>
          <footer className="run-bar">
            <span>{p.run ? `${stage(p.run.stage)} · 证据${p.run.status === "completed" ? "可用" : activeRun(p.run) ? "处理中" : "不可用"}` : "尚未运行连续性检查"}</span>
          </footer>
          <details className="workspace-technical">
            <summary>技术详情</summary>
            <dl className="metadata">
              <div><dt>草稿修订</dt><dd>{p.draft?.revision ?? "未提供"}</dd></div>
              <div><dt>草稿大小</dt><dd>{p.draft ? `${new Blob([p.draft.body]).size.toLocaleString()} bytes` : "读取中"}</dd></div>
              <div><dt>草稿记录</dt><dd>{p.draft?.id ?? "未提供"}</dd></div>
            </dl>
          </details>
        </section>
        <aside className="issues">
          <header className="issues-top">
            <div><h2>连续性问题 <span>{p.run?.issues?.length ?? 0}</span></h2><p>按风险查看问题与对应证据</p></div>
          </header>
          {p.run ? (
            <>
              <p className="run-meta" aria-label="连续性检查运行状态">
                {stage(p.run.stage)} · {p.run.is_stale ? "检查依据已过期" : "基于当前版本"}
              </p>
              {p.run.result_origin === "demo_preset" && <p className="preset-note" role="note"><strong>预置演示审阅数据</strong> · 用于本地体验完整审阅链路，本次未调用外部模型服务，也不代表模型实时判断。</p>}
              {["failed", "timed_out", "cancelled"].includes(p.run.status) && (
                <p className="inline-error">
                  {labelError({ code: p.run.error_code })} 未写入、也不展示部分结果。
                </p>
              )}
              <ul className="issue-list">
                {(p.run.issues ?? []).map((x) => (
                  <li key={x.id}>
                    <Button
                      className={`issue-row severity-${x.severity}${p.selectedIssueId === x.id ? " selected" : ""}${x.decision || p.locallyResolvedIssueIds.includes(x.id) ? " resolved" : ""}`}
                      ariaPressed={p.selectedIssueId === x.id}
                      onClick={(e) => p.select(x, e.currentTarget)}
                    >
                      <span className="issue-row-head">
                        <span className={`risk ${x.severity}`}>
                          <I>
                            {x.severity === "high"
                              ? "▲"
                              : x.severity === "medium"
                                ? "●"
                                : "○"}
                          </I>
                          {statusLabel(x.severity)}
                        </span>
                        <strong>{categoryLabel(x.category)}</strong>
                      </span>
                      <span className="issue-claim">{x.claim_text || x.explanation}</span>
                      <small className="issue-action-label">{x.decision || p.locallyResolvedIssueIds.includes(x.id) ? "决定已记录" : "查看证据"}</small>
                      <span className="issue-arrow" aria-hidden="true">›</span>
                    </Button>
                  </li>
                ))}
              </ul>
              {p.run.status === "completed" && !(p.run.issues ?? []).length && (
                <div className="empty">
                  没有可审阅 Issue。系统不会伪造结果。
                </div>
              )}
              {p.run.status === "completed" &&
                (p.run.issues ?? []).length > 0 &&
                !(p.run.issues ?? []).some(
                  (x) =>
                    !x.decision && !p.locallyResolvedIssueIds.includes(x.id),
                ) && (
                  <Button
                    className="primary"
                    disabled={
                      blocked || p.run.lineage_status === "superseded_unlinked"
                    }
                    onClick={() => void p.review()}
                  >
                    审阅 Memory 变更
                  </Button>
                )}
            </>
          ) : (
            <div className="empty issues-empty">
              <h3>检查结果会显示在这里</h3>
              <p>系统会按风险列出与历史事实可能冲突的内容，并提供可追溯证据。</p>
              {!p.readOnly && <Button className="primary" disabled={blocked || !p.draft || dirty} onClick={() => void p.check()}>运行连续性检查</Button>}
            </div>
          )}
        </aside>
      </div>
      <BoundedStoryTools key={p.project.id} project={p.project} draft={p.draft} chapters={p.chapters} readOnly={p.readOnly} dirty={dirty} go={p.go} />
      <RevisionPlanTools key={`revision:${p.project.id}`} project={p.project} draft={p.draft} run={p.run} readOnly={p.readOnly} dirty={dirty} busy={Boolean(p.busy)} recheck={p.check} go={p.go} />
      {immersiveOpen && !p.readOnly && (
        <ImmersiveEditor
          project={p.project}
          draft={p.draft}
          saved={p.saved}
          run={p.run}
          busy={p.busy}
          error={p.error}
          controlled={p.controlled}
          selectedIssueId={p.selectedIssueId}
          locallyResolvedIssueIds={p.locallyResolvedIssueIds}
          fontSize={immersiveFontSize}
          lineHeight={immersiveLineHeight}
          columnWidth={immersiveColumnWidth}
          issuesOpen={immersiveIssuesOpen}
          setFontSize={setImmersiveFontSize}
          setLineHeight={setImmersiveLineHeight}
          setColumnWidth={setImmersiveColumnWidth}
          setIssuesOpen={setImmersiveIssuesOpen}
          setDraft={p.setDraft}
          save={p.save}
          select={p.select}
          close={closeImmersive}
        />
      )}
      {p.memoryDelta && p.memoryDelta.status !== "not_started" && (
        <section className="project-section" aria-label="Memory 更新建议"><h2>Memory 更新建议</h2><p>连续性问题与事实更新建议会分别保存；未确认的候选不会进入正式事实，也不会用于后续模型检查。</p><p>资料版本第 {p.memoryDelta.source_revision ?? "?"} 版 · 状态 {p.memoryDelta.status} · 核心待审 {p.memoryDelta.coverage?.counts.core_pending ?? 0}</p><Button onClick={() => p.go(`/projects/${p.project.id}/memory`)}>打开更新审核与证据</Button></section>
      )}
      {p.changeSet && (
        <form className="review" aria-label="Memory Update Review" onSubmit={(event) => void p.commit(event)}>
          <header>
            <div>
              <p className="eyebrow">NESTED WORKFLOW</p>
              <h2>Memory Update Review</h2>
              <p>
                base V{p.changeSet.base_memory_version} → target V
                {p.changeSet.target_memory_version}；候选不会自动写入。逐项接受、拒绝或编辑，并由作者明确提交后，才会原子创建新版本。
              </p>
            </div>
          </header>
          {p.changeSet.items.map((x) => (
            <article key={x.id} className="diff">
              <div>
                <strong>更新前</strong>
                <p>{x.before ? `${String(x.before.subject)} · ${predicateLabel(x.before.predicate)}：${String(x.before.value)}` : "新增事实（当前版本中没有此记录）"}</p>
              </div>
              <div>
                <strong>候选内容</strong>
                <p>{memoryTypeLabel(String(x.after.memory_type))} · {String(x.after.subject)} · {predicateLabel(x.after.predicate)}：{String(x.after.value)}</p>
              </div>
              <fieldset>
                <legend>作者审核</legend>
                <label><input type="radio" name={x.id} value="accepted" defaultChecked disabled={blocked} />接受（写入候选）</label>
                <label><input type="radio" name={x.id} value="rejected" disabled={blocked} />拒绝（不写入）</label>
                <label><input type="radio" name={x.id} value="edited" disabled={blocked} />编辑后接受</label>
              </fieldset>
              <div className="candidate-edit" aria-label="编辑候选事实">
                <label>事实类型<select name={`edit:${x.id}:memory_type`} defaultValue={String(x.after.memory_type)} disabled={blocked}>{["static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"].map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label>
                <label>对象<input name={`edit:${x.id}:subject`} defaultValue={String(x.after.subject)} disabled={blocked} /></label>
                <label>关系<input name={`edit:${x.id}:predicate`} defaultValue={String(x.after.predicate)} disabled={blocked} /></label>
                <label>事实内容<textarea name={`edit:${x.id}:value`} defaultValue={String(x.after.value)} disabled={blocked} /></label>
              </div>
            </article>
          ))}
          <Button
            className="primary"
            disabled={blocked}
            type="submit"
          >
            确认并提交审核结果
          </Button>
        </form>
      )}
    </section>
  );
}
function MemoryDeltaReview({ delta, blocked, submit, openSource }: { delta: MemoryDelta; blocked: boolean; submit: (event: FormEvent<HTMLFormElement>) => Promise<void>; openSource: (memory: Memory, element: HTMLButtonElement) => Promise<void> | void }) {
  const [choices, setChoices] = useState<Record<string, string>>({});
  if (["processing", "cancelling"].includes(delta.status)) return <div className="empty" role="status">正在运行连续性检查与 Story Memory 更新分析；两项都完成后才会显示审核结果。</div>;
  if (["failed", "timed_out", "cancelled"].includes(delta.status)) return <div className="notice error" role="alert">更新分析未完成：{labelError({ code: delta.error_code })} 没有写入 Issue、候选或 Memory 版本，请从当前来源安全重试。</div>;
  const kindLabel = { new_fact: "新增事实", changed_fact: "变更事实", invalidated_fact: "失效事实" } as const;
  const sourceMemory = (candidate: MemoryDelta["candidates"][number]): Memory => ({
    id: candidate.id,
    memory_type: candidate.memory_type,
    subject: candidate.subject,
    predicate: candidate.predicate,
    value: candidate.value,
    valid_from: null,
    valid_to: null,
    review_status: "pending",
    source: { chapter_id: candidate.source.chapter_id, chapter_number: candidate.source.chapter_number, chapter_title: candidate.source.chapter_title, span_id: candidate.source.span_id, excerpt: candidate.source.excerpt, source_path: candidate.source.source_path },
  });
  return (
    <form className="review memory-init-review memory-delta-review" aria-label="Memory Delta 审核" onSubmit={(event) => void submit(event)}>
      <header>
        <div>
          <p className="eyebrow">STORY MEMORY · SOURCE R{delta.source_revision}</p>
          <h2>核对事实变化</h2>
          <p>每条变化都绑定当前来源与 Memory V{delta.base_memory_version}。核心变化必须全部决定；辅助建议只有明确决定后才会提交。当前覆盖：{coverageStatusLabel(delta.coverage?.status)}。</p>
        </div>
      </header>
      {!delta.candidates.length && <div className="empty"><strong>没有发现事实变化候选</strong><p>仍需确认本次来源已完成覆盖审计；确认后不会创建新 Memory 版本。</p></div>}
      {delta.candidates.map((candidate) => {
        const selected = choices[candidate.id] ?? "";
        return (
          <article key={candidate.id} className={`diff memory-init-candidate memory-delta-candidate kind-${candidate.change_kind}`}>
            <header className="delta-candidate-heading">
              <span className="delta-kind">{kindLabel[candidate.change_kind]}</span>
              <span>{candidate.review_priority === "core" ? "核心变化 · 必须决定" : "辅助建议 · 可继续待审"}</span>
            </header>
            <div className="delta-fact-flow">
              <section className="delta-fact before-fact">
                <strong>当前已确认事实</strong>
                {candidate.before ? <><p>{memoryTypeLabel(candidate.before.memory_type)} · {candidate.before.subject} · {predicateLabel(candidate.before.predicate)}：{candidate.before.value}</p><small>Memory V{delta.base_memory_version} · {candidate.before.id}</small>{candidate.before.source && <Button type="button" className="link-button" onClick={(event) => void openSource(candidate.before as Memory, event.currentTarget)}>查看原事实来源</Button>}</> : <p className="muted">当前 Story Memory 中没有对应事实。</p>}
              </section>
              <span className="delta-arrow" aria-hidden="true">→</span>
              <section className="delta-fact proposed-fact">
                <strong>AI 提议</strong>
                {candidate.change_kind === "invalidated_fact" ? <><p>停止沿用这条事实，不生成相反事实。</p><small>理由：{candidate.invalidation_reason}</small></> : <p>{memoryTypeLabel(candidate.memory_type)} · {candidate.subject} · {predicateLabel(candidate.predicate)}：{candidate.value}</p>}
              </section>
            </div>
            <section className="candidate-source delta-evidence">
              <strong>新修订 Evidence · 第 {candidate.source.chapter_number} 章《{candidate.source.chapter_title}》</strong>
              <blockquote>{candidate.source.excerpt}</blockquote>
              <small>SourceSpan {candidate.source.span_id} · source r{candidate.source_revision}</small>
              <Button type="button" className="link-button" onClick={(event) => void openSource(sourceMemory(candidate), event.currentTarget)}>查看新修订来源</Button>
            </section>
            {candidate.decision_status === "pending" ? <>
              <fieldset className="delta-decision"><legend>作者决定（未预选）</legend>
                <label><input type="radio" name={`memory-delta:${candidate.id}`} value="accepted" checked={selected === "accepted"} onChange={() => setChoices((current) => ({ ...current, [candidate.id]: "accepted" }))} disabled={blocked} />接受</label>
                <label><input type="radio" name={`memory-delta:${candidate.id}`} value="rejected" checked={selected === "rejected"} onChange={() => setChoices((current) => ({ ...current, [candidate.id]: "rejected" }))} disabled={blocked} />拒绝</label>
                {candidate.change_kind !== "invalidated_fact" && <label><input type="radio" name={`memory-delta:${candidate.id}`} value="edited" checked={selected === "edited"} onChange={() => setChoices((current) => ({ ...current, [candidate.id]: "edited" }))} disabled={blocked} />编辑后接受</label>}
              </fieldset>
              {selected === "edited" && candidate.change_kind !== "invalidated_fact" && <div className="candidate-edit" aria-label="编辑事实变化">
                <label>事实类型<select name={`memory-delta:${candidate.id}:memory_type`} defaultValue={candidate.memory_type} disabled={blocked}>{["static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"].map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label>
                <label>对象<input name={`memory-delta:${candidate.id}:subject`} defaultValue={candidate.subject} maxLength={80} disabled={blocked} /></label>
                <label>关系<input name={`memory-delta:${candidate.id}:predicate`} defaultValue={candidate.predicate} maxLength={80} disabled={blocked} /></label>
                <label>事实内容<textarea name={`memory-delta:${candidate.id}:value`} defaultValue={candidate.value} maxLength={240} disabled={blocked} /></label>
              </div>}
            </> : <p className="candidate-decision">作者已{candidate.decision_status === "rejected" ? "拒绝" : candidate.decision_status === "edited" ? "编辑后接受" : "接受"}此变化；{candidate.decision_status === "rejected" ? "不会改变 Story Memory。" : "等待原子提交。"}</p>}
          </article>
        );
      })}
      <footer className="actions"><Button className="primary" type="submit" disabled={blocked}>{delta.candidates.length ? "确认提交并更新 Story Memory" : "确认无候选并完成覆盖"}</Button></footer>
    </form>
  );
}

function MemoryInitializationReview({
  initialization,
  coverage,
  blocked,
  start,
  submit,
  goToCheck,
}: {
  initialization: MemoryInitialization;
  coverage: MemoryCoverage | null;
  blocked: boolean;
  start: () => Promise<void>;
  submit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  goToCheck: () => void;
}) {
  if (initialization.status === "required")
    return (
      <div className="empty memory-init-empty">
        <strong>等待初始化</strong>
        <p>系统会从当前导入章节与 SourceSpan 生成候选；候选不会自动成为 canon。</p>
        <Button className="primary" disabled={blocked} onClick={() => void start()}>
          初始化 Story Memory
        </Button>
      </div>
    );
  if (initialization.status === "rejected")
    return (
      <div className="empty memory-init-empty">
        <strong>Memory V1 保持为空</strong>
        <p>所有候选均被作者拒绝。连续性检查仍会安全返回上下文不足；可 Reset 导入作品后重新开始。</p>
      </div>
    );
  return (
    <form className="review memory-init-review" aria-label="Story Memory 初始化审核" onSubmit={(event) => void submit(event)}>
      <header>
        <div>
          <p className="eyebrow">IMPORTED SOURCE · REVISION {initialization.source_revision}</p>
          <h2>初始化候选审核</h2>
          <p>核心候选必须全部决定；辅助候选可继续 pending，且不会进入 canon 或 Provider 输入。{coverage ? ` 当前覆盖：${coverage.status}；核心待审 ${coverage.counts.core_pending}，辅助待审 ${coverage.counts.supporting_pending}。` : ""}</p>
        </div>
      </header>
      {initialization.candidates.map((candidate) => (
        <article key={candidate.id} className="diff memory-init-candidate">
          <div className="candidate-source">
            <strong>原文 Evidence</strong>
            <p>第 {candidate.source.chapter_number} 章《{candidate.source.chapter_title}》 · {candidate.source.label}</p>
            <code>SourceSpan · {candidate.source.span_id}</code>
            <blockquote>{candidate.source.text}</blockquote>
            <a href={candidate.source.source_path}>查看章节来源</a>
          </div>
          <div>
            <strong>候选事实</strong>
            <p>{memoryTypeLabel(candidate.memory_type)} · {candidate.subject} · {predicateLabel(candidate.predicate)}：{candidate.value}</p>
            <small>来源修订 r{candidate.source_revision} · {candidate.candidate_origin} · {candidate.review_priority === "core" ? "核心候选（必须决定）" : "辅助候选（可继续待审）"} · 尚未成为 canon</small>
          </div>
          {candidate.decision_status === "pending" ? (
            <>
              <fieldset>
                <legend>作者审核（未预选）</legend>
                <label><input type="radio" name={`memory-init:${candidate.id}`} value="accepted" data-memory-candidate-id={candidate.id} disabled={blocked} />接受（写入 V1）</label>
                <label><input type="radio" name={`memory-init:${candidate.id}`} value="rejected" data-memory-candidate-id={candidate.id} disabled={blocked} />拒绝（不写入）</label>
                <label><input type="radio" name={`memory-init:${candidate.id}`} value="edited" data-memory-candidate-id={candidate.id} disabled={blocked} />编辑后接受</label>
              </fieldset>
              <div className="candidate-edit" aria-label="编辑候选事实">
                <label>事实类型<select name={`memory-init:${candidate.id}:memory_type`} defaultValue={candidate.memory_type} disabled={blocked}>{["static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"].map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label>
                <label>对象<input name={`memory-init:${candidate.id}:subject`} defaultValue={candidate.subject} disabled={blocked} /></label>
                <label>关系<input name={`memory-init:${candidate.id}:predicate`} defaultValue={candidate.predicate} disabled={blocked} /></label>
                <label>事实内容<textarea name={`memory-init:${candidate.id}:value`} defaultValue={candidate.value} disabled={blocked} /></label>
                <label className="evidence-confirmation"><input type="checkbox" name={`memory-init:${candidate.id}:evidence-confirmed`} value="confirmed" disabled={blocked} />我确认编辑后的事实仍由上方 Evidence 支持</label>
              </div>
            </>
          ) : (
            <p className="candidate-decision">作者已{candidate.decision_status === "rejected" ? "拒绝" : candidate.decision_status === "edited" ? "编辑后接受" : "接受"}此候选。</p>
          )}
        </article>
      ))}
      {initialization.status === "draft" && (
        <Button className="primary" disabled={blocked} type="submit">确认核心审核并建立 Memory V1</Button>
      )}
      {coverage?.status === "ready_partial" && (
        <div className="notice success" role="status">
          <strong>已安全建立部分 Memory</strong>
          <p>所有核心候选已最终决定并至少确认一条；{coverage.counts.supporting_pending} 条辅助候选仍 pending，不在 canon 或 Provider 输入中。</p>
          <Button className="primary" disabled={blocked} type="button" onClick={goToCheck}>开始连续性检查</Button>
        </div>
      )}
      {coverage?.status === "in_review" && coverage.counts.core_pending === 0 && coverage.counts.confirmed_core === 0 && (
        <div className="notice error" role="alert">核心候选均未被确认；尚不能开始连续性检查。</div>
      )}
    </form>
  );
}
function SourceAppend({ project, draft, chapters, readOnly, context }: { project: Project; draft: Draft | null; chapters: Chapter[]; readOnly: boolean; context?: ReactNode }) {
  const router=useRouter();
  const [method, setMethod] = useState<"draft_complete" | "paste" | "file">("paste"), [content, setContent] = useState(""), [filename, setFilename] = useState(""), [preview, setPreview] = useState<SourceChangeSet | null>(null), [nextDraft, setNextDraft] = useState<Draft | null>(null), [busy, setBusy] = useState(""), [error, setError] = useState("");
  const base = project.source_revision ?? 1;
  const makePreview = async () => {
    setBusy("正在生成追加预览"); setError("");
    try {
      const data = await json<{ source_change_set: SourceChangeSet }>(`/projects/${project.id}/source-change-sets/preview`, "POST", { mode: "append", input_method: method, base_source_revision: base, ...(method === "draft_complete" ? { draft_id: draft?.id } : { content, ...(method === "file" ? { filename } : {}) }) });
      setPreview(data.source_change_set);
    } catch (cause) { setError(labelError(cause)); } finally { setBusy(""); }
  };
  const commit = async () => {
    if (!preview) return; setBusy("正在原子追加章节"); setError("");
    try { const data = await json<{ source_change_set: SourceChangeSet; next_draft: Draft }>(`/projects/${project.id}/source-change-sets/${preview.id}/commit`, "POST", { confirm: true, content_sha256: preview.content_sha256 }); setPreview(data.source_change_set); setNextDraft(data.next_draft); }
    catch (cause) { setError(labelError(cause)); } finally { setBusy(""); }
  };
  return <section className="project-page read-page"><header className="page-header"><div><p className="breadcrumb">项目 / {project.title} / 章节来源</p><h1>追加章节</h1><p>目标作品：{project.title} · source r{base} → r{base + 1}。P0 只追加，既有来源不覆盖。</p></div></header>{context}
    {!readOnly && <section className="project-section"><h2>新增来源</h2><fieldset disabled={Boolean(busy)}><legend>入口</legend>{(["draft_complete", "paste", "file"] as const).map((value) => <label key={value}><input type="radio" checked={method === value} onChange={() => setMethod(value)} />{value === "draft_complete" ? "完成当前章节" : value === "paste" ? "粘贴追加" : "追加文件"}</label>)}</fieldset>
    {method === "draft_complete" ? <p>将完成当前草稿《{draft?.title ?? "—"}》并追加为新章节。</p> : <><label>章节正文<textarea value={content} onChange={(event) => setContent(event.target.value)} disabled={readOnly || Boolean(busy)} /></label>{method === "file" && <label>追加文件<input type="file" accept=".md,.txt,text/markdown,text/plain" disabled={readOnly || Boolean(busy)} onChange={async (event) => { const file = event.currentTarget.files?.[0]; if (!file) return; setFilename(file.name); setContent(await file.text()); }} /><small>{filename || "仅支持 UTF-8 .md / .txt"}</small></label>}</>}
    <Button className="primary" disabled={Boolean(busy) || (method !== "draft_complete" && !content.trim())} onClick={() => void makePreview()}>{busy || "预览追加"}</Button></section>}
    {error && <div className="notice error" role="alert">{error} 请保留当前内容，重新获取当前 source revision 后重试。</div>}
    {preview && <section className="notice success" role="status"><strong>SourceChangeSet 预览 · {preview.status}</strong><p>SHA-256 {preview.content_sha256} · {preview.chapter_count} 个章节 / {preview.source_span_count} 个 SourceSpan · r{preview.base_source_revision} → r{preview.target_source_revision}</p><small>预览于 {preview.previewed_at}；创建审计已记录。文件仅记录 basename。</small><ul>{preview.chapters.map((chapter) => <li key={chapter.preview_id}>第 {chapter.order} 个追加章节《{chapter.title}》· {chapter.character_count} 字</li>)}</ul>{!readOnly && (preview.status === "previewed" ? <Button className="primary" disabled={Boolean(busy)} onClick={() => void commit()}>确认追加并创建下一章草稿</Button> : <><p>已提交 source r{preview.target_source_revision}。</p>{nextDraft && <p>下一章草稿：第 {nextDraft.chapter_number} 章《{nextDraft.title}》 · {nextDraft.id}</p>}<Button className="primary" onClick={() => router.push(`/projects/${project.id}/workspace`)}>进入下一章草稿</Button></>)}</section>}
    <Read title="现有章节来源" breadcrumb="Evidence 可回源" note="历史 Evidence 保持指向原 SourceSpan。" items={chapters.flatMap((chapter) => [<li key={`chapter-${chapter.id}`} id={`chapter-${chapter.id}`} className="source-chapter-anchor"><strong>第 {chapter.number} 章《{chapter.title}》</strong><span>{chapter.summary||"本章来源"}</span></li>,...(chapter.source_spans ?? []).map((span) => <li key={span.span_id} id={`span-${span.span_id}`}><strong>第 {chapter.number} 章《{chapter.title}》 · {span.label}</strong><span>{span.text_excerpt}</span></li>)])} empty="此作品还没有可回源的章节片段。" />
  </section>;
}

function Read({
  title,
  breadcrumb,
  note,
  context,
  items,
  empty,
}: {
  title: string;
  breadcrumb: string;
  note: string;
  context?: ReactNode;
  items: ReactNode[];
  empty: string;
}) {
  return (
    <section className="project-page read-page">
      <header className="page-header">
        <div>
          <p className="breadcrumb">{breadcrumb}</p>
          <h1>{title}</h1>
          <p>{note}</p>
        </div>
      </header>
      {context}
      {items.length ? (
        <ul className="read-list">{items}</ul>
      ) : (
        <div className="empty">{empty}</div>
      )}
    </section>
  );
}

type AuthorPlanKind = "story" | "character" | "world";
type AuthorPlanSelection =
  | { kind: "story"; item: AuthorStoryPlan }
  | { kind: "character"; item: AuthorCharacterPlan }
  | { kind: "world"; item: AuthorWorldPlan };
type AuthorPlanDialogState =
  | { kind: "story"; item: AuthorStoryPlan | null }
  | { kind: "character"; item: AuthorCharacterPlan | null }
  | { kind: "world"; item: AuthorWorldPlan | null };
type AuthorMutation = (
  endpoint: string,
  method: "POST" | "PATCH",
  payload: Record<string, unknown>,
  busyLabel: string,
) => Promise<AuthorContext | null>;

const authorPlanCopy = {
  story: {
    title: "大纲",
    planning: "创作规划",
    reference: "已写章节",
    newLabel: "新建规划",
    noun: "故事规划",
    description: "安排后续章节的故事方向；已写章节保持为只读正文资料。",
    empty: "还没有创作规划。这里记录作者对后续故事的安排，不会自动成为正文事实。",
  },
  character: {
    title: "角色库",
    planning: "角色规划",
    reference: "正文档案",
    newLabel: "新建角色规划",
    noun: "角色规划",
    description: "规划角色后续目标与状态；正文档案继续展示已经写入故事的资料。",
    empty: "还没有角色规划。可以先记录角色接下来要追求的目标与计划状态。",
  },
  world: {
    title: "世界观",
    planning: "设定规划",
    reference: "正文资料",
    newLabel: "新建设定规划",
    noun: "设定规划",
    description: "规划后续要使用的地点、规则与组织；正文资料保持只读。",
    empty: "还没有设定规划。可以先记录后续创作准备使用的世界设定。",
  },
} as const;

const authorStoryStatusLabel = (value: AuthorStoryPlan["status"]) =>
  ({ planned: "待开始", in_progress: "进行中", paused: "已暂停", completed: "已完成" })[value];

function AuthorPlanningPage({
  kind,
  projectId,
  projectTitle,
  projectIsTutorial,
  authorContext,
  readOnly,
  busy,
  mutate,
  context,
  reference,
}: {
  kind: AuthorPlanKind;
  projectId: string;
  projectTitle: string;
  projectIsTutorial: boolean;
  authorContext: AuthorContext | null;
  readOnly: boolean;
  busy: string;
  mutate: AuthorMutation;
  context?: ReactNode;
  reference: ReactNode;
}) {
  const copy = authorPlanCopy[kind];
  const [mode, setMode] = useState<"planning" | "reference">(() =>
    typeof window !== "undefined" && window.location.hash.startsWith("#plan-")
      ? "planning"
      : projectIsTutorial ? "reference" : "planning",
  );
  const [showArchived, setShowArchived] = useState(false);
  const [dialog, setDialog] = useState<AuthorPlanDialogState | null>(null);
  const [archiveTarget, setArchiveTarget] = useState<AuthorPlanSelection | null>(null);
  const [pageError, setPageError] = useState("");
  const [feedback, setFeedback] = useState("");
  const returnFocus = useRef<HTMLButtonElement | null>(null);
  const records: AuthorPlanSelection[] = !authorContext
    ? []
    : kind === "story"
      ? authorContext.story_plans.map((item) => ({ kind, item }))
      : kind === "character"
        ? authorContext.character_plans.map((item) => ({ kind, item }))
        : authorContext.world_plans.map((item) => ({ kind, item }));
  const activeRecords = records.filter(({ item }) => !item.archived);
  const visibleRecords = showArchived ? records : activeRecords;
  const endpoint = kind === "story" ? "story-plans" : kind === "character" ? "character-plans" : "world-plans";
  const disabled = readOnly || Boolean(busy) || !authorContext;

  const restoreFocus = () => requestAnimationFrame(() => returnFocus.current?.focus());
  const closeDialog = () => {
    setDialog(null);
    restoreFocus();
  };
  const closeArchive = () => {
    setArchiveTarget(null);
    restoreFocus();
  };
  const openCreate = (button: HTMLButtonElement) => {
    returnFocus.current = button;
    setPageError("");
    setFeedback("");
    setDialog({ kind, item: null } as AuthorPlanDialogState);
  };
  const openEdit = (selection: AuthorPlanSelection, button: HTMLButtonElement) => {
    returnFocus.current = button;
    setPageError("");
    setFeedback("");
    setDialog(selection);
  };
  const savePlan = async (fields: Record<string, unknown>, state: AuthorPlanDialogState) => {
    if (!authorContext) return;
    const itemId = state.item?.id;
    await mutate(
      itemId ? `${endpoint}/${itemId}` : endpoint,
      itemId ? "PATCH" : "POST",
      { base_author_context_version: authorContext.author_context_version, ...fields },
      itemId ? `正在保存${copy.noun}` : `正在新建${copy.noun}`,
    );
    setFeedback(itemId ? `${copy.noun}已更新。` : `${copy.noun}已创建。`);
    closeDialog();
  };
  const move = async (selection: AuthorPlanSelection, offset: -1 | 1) => {
    if (!authorContext) return;
    const index = activeRecords.findIndex(({ item }) => item.id === selection.item.id);
    const nextIndex = index + offset;
    if (index < 0 || nextIndex < 0 || nextIndex >= activeRecords.length) return;
    const orderedIds = activeRecords.map(({ item }) => item.id);
    [orderedIds[index], orderedIds[nextIndex]] = [orderedIds[nextIndex], orderedIds[index]];
    setPageError("");
    setFeedback("");
    try {
      await mutate(
        `${endpoint}/reorder`,
        "POST",
        {
          base_author_context_version: authorContext.author_context_version,
          ordered_ids: orderedIds,
        },
        `正在调整${copy.noun}顺序`,
      );
      setFeedback("规划顺序已更新。");
    } catch (cause) {
      setPageError(
        (cause as ApiFailure).code === "author_context_version_conflict"
          ? "内容已在其他窗口更新，已载入最新版本，请确认后重试。"
          : labelError(cause),
      );
    }
  };
  const archivePlan = async () => {
    if (!authorContext || !archiveTarget) return;
    setPageError("");
    setFeedback("");
    try {
      await mutate(
        `${endpoint}/${archiveTarget.item.id}/archive`,
        "POST",
        { base_author_context_version: authorContext.author_context_version, confirm: true },
        `正在归档${copy.noun}`,
      );
      setFeedback(`${copy.noun}已归档。`);
      closeArchive();
    } catch (cause) {
      setPageError(
        (cause as ApiFailure).code === "author_context_version_conflict"
          ? "内容已在其他窗口更新，已载入最新版本，请确认后重试。"
          : labelError(cause),
      );
    }
  };

  return (
    <section className={`project-page archive-page author-planning-page author-${kind}-page`} data-project-id={projectId}>
      <header className="page-header author-planning-header">
        <div>
          <p className="breadcrumb">项目 / {projectTitle} / {copy.title}</p>
          <h1>{copy.title}</h1>
          <p>{copy.description}</p>
        </div>
        <div className="author-planning-status">
          <span>作者规划 v{authorContext?.author_context_version ?? "—"}</span>
          {mode === "planning" && !readOnly && (
            <Button className="primary" disabled={disabled} onClick={(event) => openCreate(event.currentTarget)}>
              {copy.newLabel}
            </Button>
          )}
        </div>
      </header>
      {context}
      <nav className="author-mode-switch" aria-label={`${copy.title}资料模式`}>
        <Button className={mode === "planning" ? "current" : "quiet"} ariaPressed={mode === "planning"} onClick={() => setMode("planning")}>{copy.planning}</Button>
        <Button className={mode === "reference" ? "current" : "quiet"} ariaPressed={mode === "reference"} onClick={() => setMode("reference")}>{copy.reference}</Button>
      </nav>
      {mode === "reference" ? (
        <div className="author-reference-pane" aria-label={copy.reference}>{reference}</div>
      ) : (
        <section className="author-planning-pane" aria-label={copy.planning} aria-busy={Boolean(busy)}>
          <div className="author-planning-toolbar">
            <div>
              <strong>{copy.planning}</strong>
              <span>{activeRecords.length} 条进行中的规划{records.some(({ item }) => item.archived) ? ` · ${records.length - activeRecords.length} 条已归档` : ""}</span>
            </div>
            {records.some(({ item }) => item.archived) && (
              <Button className="quiet" ariaPressed={showArchived} onClick={() => setShowArchived((current) => !current)}>
                {showArchived ? "隐藏已归档" : "查看已归档"}
              </Button>
            )}
          </div>
          {readOnly && <p className="author-mobile-note" role="note">移动端可以浏览作者规划；请在桌面端创建、编辑、排序或归档。</p>}
          {pageError && <p className="notice error author-plan-notice" role="alert">{pageError}</p>}
          {feedback && <p className="notice success author-plan-notice" role="status">{feedback}</p>}
          {!authorContext ? (
            <div className="empty archive-empty">正在读取作者规划。</div>
          ) : visibleRecords.length ? (
            <ol className="author-plan-list">
              {visibleRecords.map((selection) => {
                const index = activeRecords.findIndex(({ item }) => item.id === selection.item.id);
                return (
                  <AuthorPlanRow
                    key={selection.item.id}
                    selection={selection}
                    readOnly={readOnly}
                    busy={Boolean(busy)}
                    canMoveUp={!selection.item.archived && index > 0}
                    canMoveDown={!selection.item.archived && index >= 0 && index < activeRecords.length - 1}
                    edit={(button) => openEdit(selection, button)}
                    moveUp={() => void move(selection, -1)}
                    moveDown={() => void move(selection, 1)}
                    archive={(button) => {
                      returnFocus.current = button;
                      setPageError("");
                      setFeedback("");
                      setArchiveTarget(selection);
                    }}
                  />
                );
              })}
            </ol>
          ) : (
            <div className="empty author-plan-empty">
              <strong>{showArchived ? "没有已归档规划" : copy.empty}</strong>
            </div>
          )}
        </section>
      )}
      {dialog && (
        <AuthorPlanDialog
          state={dialog}
          busy={busy}
          close={closeDialog}
          save={(fields) => savePlan(fields, dialog)}
        />
      )}
      {archiveTarget && (
        <AuthorArchiveDialog
          selection={archiveTarget}
          busy={busy}
          error={pageError}
          close={closeArchive}
          confirm={() => void archivePlan()}
        />
      )}
    </section>
  );
}

function authorPlanName(selection: AuthorPlanSelection) {
  return selection.kind === "story" ? selection.item.title : selection.item.name;
}

function AuthorPlanRow({
  selection,
  readOnly,
  busy,
  canMoveUp,
  canMoveDown,
  edit,
  moveUp,
  moveDown,
  archive,
}: {
  selection: AuthorPlanSelection;
  readOnly: boolean;
  busy: boolean;
  canMoveUp: boolean;
  canMoveDown: boolean;
  edit: (button: HTMLButtonElement) => void;
  moveUp: () => void;
  moveDown: () => void;
  archive: (button: HTMLButtonElement) => void;
}) {
  const name = authorPlanName(selection);
  const item = selection.item;
  return (
    <li id={`plan-${item.id}`} className={item.archived ? "archived" : ""} data-author-plan-id={item.id}>
      <div className="author-plan-order" aria-hidden="true">{String(item.position).padStart(2, "0")}</div>
      <article>
        <header>
          <div>
            <h2>{name}</h2>
            {item.archived && <span className="status-pill archived"><I>●</I>已归档</span>}
          </div>
          {selection.kind === "story" ? <p>{selection.item.summary || "尚未填写摘要。"}</p> : selection.kind === "character" ? <p>{roleTypeLabel(selection.item.role_type)}</p> : <p>{worldTypeLabel(selection.item.category)}</p>}
        </header>
        {selection.kind === "story" ? (
          <dl className="author-plan-fields">
            <div><dt>创作目标</dt><dd>{selection.item.goal || "尚未填写"}</dd></div>
            <div><dt>状态</dt><dd>{authorStoryStatusLabel(selection.item.status)}</dd></div>
            <div><dt>目标章节</dt><dd>{selection.item.target_chapter_number ? `第 ${selection.item.target_chapter_number} 章` : "尚未指定"}</dd></div>
          </dl>
        ) : selection.kind === "character" ? (
          <dl className="author-plan-fields">
            <div><dt>角色目标</dt><dd>{selection.item.goal || "尚未填写"}</dd></div>
            <div><dt>计划状态</dt><dd>{selection.item.planned_state || "尚未填写"}</dd></div>
            <div><dt>备注</dt><dd>{selection.item.notes || "尚未填写"}</dd></div>
          </dl>
        ) : (
          <dl className="author-plan-fields">
            <div><dt>设定描述</dt><dd>{selection.item.description}</dd></div>
            <div><dt>备注</dt><dd>{selection.item.notes || "尚未填写"}</dd></div>
          </dl>
        )}
      </article>
      {!readOnly && !item.archived && (
        <div className="author-plan-actions" aria-label={`${name} 操作`}>
          <Button className="quiet" disabled={busy} ariaLabel={`编辑 ${name}`} onClick={(event) => edit(event.currentTarget)}>编辑</Button>
          <Button className="quiet order-action" disabled={busy || !canMoveUp} ariaLabel={`上移 ${name}`} onClick={moveUp}>↑<span>上移</span></Button>
          <Button className="quiet order-action" disabled={busy || !canMoveDown} ariaLabel={`下移 ${name}`} onClick={moveDown}>↓<span>下移</span></Button>
          <Button className="quiet archive-action" disabled={busy} ariaLabel={`归档 ${name}`} onClick={(event) => archive(event.currentTarget)}>归档</Button>
        </div>
      )}
    </li>
  );
}

function useModalFocus<T extends HTMLElement = HTMLInputElement>(close: () => void) {
  const modalRef = useRef<HTMLElement>(null);
  const firstRef = useRef<T>(null);
  useDocumentScrollLock();
  useEffect(() => firstRef.current?.focus(), []);
  const containFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      modalRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  return { modalRef, firstRef, containFocus };
}

function AuthorPlanDialog({
  state,
  busy,
  close,
  save,
}: {
  state: AuthorPlanDialogState;
  busy: string;
  close: () => void;
  save: (fields: Record<string, unknown>) => Promise<void>;
}) {
  const storyItem = state.kind === "story" ? state.item : null;
  const characterItem = state.kind === "character" ? state.item : null;
  const worldItem = state.kind === "world" ? state.item : null;
  const [title, setTitle] = useState(storyItem?.title ?? "");
  const [summary, setSummary] = useState(storyItem?.summary ?? "");
  const [goal, setGoal] = useState(storyItem?.goal ?? characterItem?.goal ?? "");
  const [status, setStatus] = useState<AuthorStoryPlan["status"]>(storyItem?.status ?? "planned");
  const [targetChapter, setTargetChapter] = useState(storyItem?.target_chapter_number ? String(storyItem.target_chapter_number) : "");
  const [name, setName] = useState(characterItem?.name ?? worldItem?.name ?? "");
  const [roleType, setRoleType] = useState<AuthorCharacterPlan["role_type"]>(characterItem?.role_type ?? "supporting");
  const [plannedState, setPlannedState] = useState(characterItem?.planned_state ?? "");
  const [notes, setNotes] = useState(characterItem?.notes ?? worldItem?.notes ?? "");
  const [category, setCategory] = useState<AuthorWorldPlan["category"]>(worldItem?.category ?? "location");
  const [description, setDescription] = useState(worldItem?.description ?? "");
  const [error, setError] = useState("");
  const { modalRef, firstRef, containFocus } = useModalFocus(close);
  const copy = authorPlanCopy[state.kind];
  const editing = Boolean(state.item);
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setError("");
    const fields: Record<string, unknown> = state.kind === "story"
      ? { title, summary, goal, status, target_chapter_number: targetChapter ? Number(targetChapter) : null }
      : state.kind === "character"
        ? { name, role_type: roleType, goal, planned_state: plannedState, notes }
        : { name, category, description, notes };
    try {
      await save(fields);
    } catch (cause) {
      setError(
        (cause as ApiFailure).code === "author_context_version_conflict"
          ? "内容已在其他窗口更新，已载入最新版本，请确认后重试。"
          : labelError(cause),
      );
    }
  };
  return (
    <div className="modal-layer author-plan-layer" role="presentation">
      <section ref={modalRef} className="dialog author-plan-dialog" role="dialog" aria-modal="true" aria-label={`${editing ? "编辑" : "新建"}${copy.noun}`} onKeyDown={containFocus}>
        <button type="button" className="close" disabled={Boolean(busy)} onClick={close}><span aria-hidden="true">×</span><span className="sr-only">关闭</span></button>
        <header><p className="eyebrow">作者规划</p><h2>{editing ? `编辑${copy.noun}` : `新建${copy.noun}`}</h2><p>这些内容用于安排未来创作，不会写入正文档案或 Story Memory。</p></header>
        <form onSubmit={(event) => void submit(event)}>
          {state.kind === "story" ? (
            <>
              <label>标题<input ref={firstRef} value={title} onChange={(event) => setTitle(event.target.value)} maxLength={120} required disabled={Boolean(busy)} /></label>
              <label>摘要<textarea value={summary} onChange={(event) => setSummary(event.target.value)} maxLength={2000} disabled={Boolean(busy)} /></label>
              <label>创作目标<textarea value={goal} onChange={(event) => setGoal(event.target.value)} maxLength={2000} disabled={Boolean(busy)} /></label>
              <div className="author-plan-form-row"><label>状态<select value={status} onChange={(event) => setStatus(event.target.value as AuthorStoryPlan["status"])} disabled={Boolean(busy)}><option value="planned">待开始</option><option value="in_progress">进行中</option><option value="paused">已暂停</option><option value="completed">已完成</option></select></label><label>目标章节<input type="number" min={1} value={targetChapter} onChange={(event) => setTargetChapter(event.target.value)} disabled={Boolean(busy)} /></label></div>
            </>
          ) : state.kind === "character" ? (
            <>
              <label>姓名<input ref={firstRef} value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required disabled={Boolean(busy)} /></label>
              <label>角色类型<select value={roleType} onChange={(event) => setRoleType(event.target.value as AuthorCharacterPlan["role_type"])} disabled={Boolean(busy)}><option value="protagonist">主角</option><option value="ally">支持角色</option><option value="antagonist">对立角色</option><option value="supporting">配角</option><option value="other">其他角色</option></select></label>
              <label>角色目标<textarea value={goal} onChange={(event) => setGoal(event.target.value)} maxLength={2000} disabled={Boolean(busy)} /></label>
              <label>计划状态<textarea value={plannedState} onChange={(event) => setPlannedState(event.target.value)} maxLength={2000} disabled={Boolean(busy)} /></label>
              <label>备注<textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={4000} disabled={Boolean(busy)} /></label>
            </>
          ) : (
            <>
              <label>名称<input ref={firstRef} value={name} onChange={(event) => setName(event.target.value)} maxLength={120} required disabled={Boolean(busy)} /></label>
              <label>分类<select value={category} onChange={(event) => setCategory(event.target.value as AuthorWorldPlan["category"])} disabled={Boolean(busy)}><option value="location">地点</option><option value="organization">组织</option><option value="rule">规则</option><option value="object">物件</option><option value="term">术语</option><option value="other">其他资料</option></select></label>
              <label>描述<textarea value={description} onChange={(event) => setDescription(event.target.value)} maxLength={4000} required disabled={Boolean(busy)} /></label>
              <label>备注<textarea value={notes} onChange={(event) => setNotes(event.target.value)} maxLength={4000} disabled={Boolean(busy)} /></label>
            </>
          )}
          {error && <p className="inline-error" role="alert">{error}</p>}
          <div className="actions"><Button type="button" disabled={Boolean(busy)} onClick={close}>取消</Button><Button className="primary" type="submit" disabled={Boolean(busy)} ariaBusy={Boolean(busy)}>{busy || "保存"}</Button></div>
        </form>
      </section>
    </div>
  );
}

function AuthorArchiveDialog({
  selection,
  busy,
  error,
  close,
  confirm,
}: {
  selection: AuthorPlanSelection;
  busy: string;
  error: string;
  close: () => void;
  confirm: () => void;
}) {
  const { modalRef, firstRef, containFocus } = useModalFocus<HTMLButtonElement>(close);
  return (
    <div className="modal-layer author-plan-layer" role="presentation">
      <section ref={modalRef} className="dialog author-archive-dialog" role="dialog" aria-modal="true" aria-label={`归档 ${authorPlanName(selection)}`} onKeyDown={containFocus}>
        <button type="button" className="close" disabled={Boolean(busy)} onClick={close}><span aria-hidden="true">×</span><span className="sr-only">关闭</span></button>
        <h2>归档“{authorPlanName(selection)}”？</h2>
        <p>归档后默认隐藏；当前产品不提供恢复操作。正文资料不会受到影响。</p>
        {error && <p className="inline-error" role="alert">{error}</p>}
        <div className="actions"><Button type="button" disabled={Boolean(busy)} onClick={close}>取消</Button><button ref={firstRef} type="button" className="danger" disabled={Boolean(busy)} onClick={confirm} aria-busy={Boolean(busy) || undefined}>{busy || "确认归档"}</button></div>
      </section>
    </div>
  );
}

function OutlineReference({
  chapters,
}: {
  chapters: { id: string; chapter_number: number; title: string; summary: string; status: string }[];
}) {
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const visible = chapters.filter(
    (chapter) =>
      (!query || `${chapter.title} ${chapter.summary}`.toLocaleLowerCase().includes(query.toLocaleLowerCase())) &&
      (!status || projectVisualStatus(chapter.status) === status),
  );
  return (
    <section className="outline-page">
      <div className="archive-toolbar">
        <label><span className="sr-only">搜索章节</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索章节" /></label>
        <label><span className="sr-only">章节状态</span><select value={status} onChange={(event) => setStatus(event.target.value)}><option value="">全部状态</option><option value="completed">已完成</option><option value="active">进行中</option><option value="paused">已暂停</option><option value="archived">已归档</option></select></label>
      </div>
      {visible.length ? (
        <ol className="outline-timeline">
          {visible.map((chapter) => {
            const visualStatus = projectVisualStatus(chapter.status);
            return (
            <li key={chapter.id} data-status={visualStatus}>
              <span className="timeline-node" aria-hidden="true" />
              <span className="chapter-number">{String(chapter.chapter_number).padStart(2, "0")}</span>
              <div><h2>{chapter.title}</h2><p>{chapter.summary || "此章节尚未填写摘要。"}</p></div>
              <span className={`status-pill ${visualStatus}`}><I>●</I>{statusLabel(visualStatus)}</span>
              <Icon name="library" />
            </li>
            );
          })}
        </ol>
      ) : <div className="empty archive-empty">{chapters.length ? "没有匹配当前条件的章节。" : "此作品还没有大纲节点。"}</div>}
    </section>
  );
}

function CharacterArchive({
  projectId,
  characters,
  draft,
  readOnly,
}: {
  projectId: string;
  characters: { id: string; name: string; role_type: string; identity: string; goal: string; current_state: string; knowledge_boundary: string }[];
  draft: Draft | null;
  readOnly: boolean;
}) {
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(() => {
    if (typeof window === "undefined") return characters[0]?.id ?? "";
    const requested = new URLSearchParams(window.location.search).get("character");
    return characters.some((character) => character.id === requested) ? requested! : characters[0]?.id ?? "";
  });
  const visible = characters.filter((character) =>
    `${character.name} ${character.identity} ${character.role_type}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  const selected = visible.find((character) => character.id === selectedId) ?? visible[0];
  const [aliasSnapshot,setAliasSnapshot]=useState<CharacterAliasSnapshot|null>(null);
  const [aliasInput,setAliasInput]=useState("");
  const [aliasBusy,setAliasBusy]=useState(false);
  const [impactInput,setImpactInput]=useState("");
  const [impactRuns,setImpactRuns]=useState<WritingAnalysisRun[]>([]);
  const [impactBusy,setImpactBusy]=useState(false);
  const [toolNotice,setToolNotice]=useState("");
  const refreshAliases=useCallback(async(characterId:string)=>{
    const next=await request<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${characterId}/aliases?include_archived=true`);setAliasSnapshot(next);
  },[projectId]);
  const refreshImpact=useCallback(async()=>{
    const next=await request<{run:WritingAnalysisRun|null;runs:WritingAnalysisRun[]}>(`/projects/${projectId}/analyses?analysis_type=change_impact`);setImpactRuns(next.runs??[]);
  },[projectId]);
  useEffect(()=>{
    if(!selected?.id)return;
    let live=true;
    Promise.all([request<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${selected.id}/aliases?include_archived=true`),request<{run:WritingAnalysisRun|null;runs:WritingAnalysisRun[]}>(`/projects/${projectId}/analyses?analysis_type=change_impact`)]).then(([aliases,impacts])=>{if(live){setAliasSnapshot(aliases);setImpactRuns(impacts.runs??[]);}}).catch((error)=>{if(live)setToolNotice(labelError(error));});
    return()=>{live=false;};
  },[projectId,selected?.id]);
  const proposalFor=(run:WritingAnalysisRun)=>run.proposal??run.analysis?.proposal??null;
  const activeImpactRun=impactRuns.find((run)=>["queued","running"].includes(run.status))??null;
  const impactRun=selected?impactRuns.find((run)=>{const proposal=proposalFor(run);return proposal?.target_type==="character"&&proposal.target_id===selected.id;})??null:null;
  const currentAliasSnapshot=selected&&aliasSnapshot?.character_id===selected.id?aliasSnapshot:null;
  const targetName=(run:WritingAnalysisRun)=>{const proposal=proposalFor(run);if(!proposal)return "未记录对象";if(proposal.target_type==="character")return characters.find((character)=>character.id===proposal.target_id)?.name??"未知角色";return proposal.target_type;};
  useEffect(()=>{
    if(!activeImpactRun)return;
    const timer=window.setInterval(()=>{void refreshImpact();},700);
    return()=>window.clearInterval(timer);
  },[activeImpactRun,refreshImpact]);
  useEffect(()=>{
    if(typeof window==="undefined"||!window.location.hash)return;
    const target=window.location.hash.slice(1);
    const frame=window.requestAnimationFrame(()=>document.getElementById(target)?.scrollIntoView({block:"center"}));
    return()=>window.cancelAnimationFrame(frame);
  },[selected?.id,currentAliasSnapshot?.updated_at]);
  const addAlias=async()=>{
    if(!selected||!currentAliasSnapshot||!aliasInput.trim())return;setAliasBusy(true);setToolNotice("");
    try{const next=await json<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${selected.id}/aliases`,"POST",{base_version:currentAliasSnapshot.version,alias:aliasInput});setAliasSnapshot(next);setAliasInput("");setToolNotice("别名已保存为独立角色资料。");}catch(error){setToolNotice(labelError(error));}finally{setAliasBusy(false);}
  };
  const editAlias=async(aliasId:string,value:string)=>{
    if(!selected||!currentAliasSnapshot)return;setAliasBusy(true);setToolNotice("");
    try{setAliasSnapshot(await json<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${selected.id}/aliases/${aliasId}`,"PATCH",{base_version:currentAliasSnapshot.version,alias:value}));setToolNotice("别名已更新。");}catch(error){setToolNotice(labelError(error));}finally{setAliasBusy(false);}
  };
  const archiveAlias=async(aliasId:string)=>{
    if(!selected||!currentAliasSnapshot)return;setAliasBusy(true);setToolNotice("");
    try{setAliasSnapshot(await json<CharacterAliasSnapshot>(`/projects/${projectId}/characters/${selected.id}/aliases/${aliasId}/archive`,"POST",{base_version:currentAliasSnapshot.version}));setToolNotice("别名已归档，历史记录仍保留。");}catch(error){setToolNotice(labelError(error));}finally{setAliasBusy(false);}
  };
  const startImpact=async()=>{
    if(!selected||!draft||!impactInput.trim())return;setImpactBusy(true);setToolNotice("");
    try{const created=await json<WritingAnalysisRun>(`/projects/${projectId}/analyses`,"POST",{analysis_type:"change_impact",draft_id:draft.id,draft_revision:draft.revision,proposal:{target_type:"character",target_id:selected.id,proposed_change:impactInput},client_request_id:crypto.randomUUID()});setImpactRuns((current)=>[created,...current.filter((run)=>run.run_id!==created.run_id)]);setImpactInput("");await refreshImpact();setToolNotice("修改影响分析已创建；它不会自动改写任何资料。");}catch(error){setToolNotice(labelError(error));}finally{setImpactBusy(false);}
  };
  const actionImpact=async(action:"cancel"|"retry")=>{
    if(!impactRun)return;setImpactBusy(true);setToolNotice("");
    try{await json(`/projects/${projectId}/analyses/${impactRun.run_id}/${action}`,"POST",{client_request_id:crypto.randomUUID()});await refreshImpact();}catch(error){setToolNotice(labelError(error));}finally{setImpactBusy(false);}
  };
  return (
    <section className="character-page">
      <div className="archive-toolbar character-toolbar">
        <label><span className="sr-only">搜索角色</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索角色" /></label>
        <span>{visible.length} 个角色</span>
      </div>
      {selected ? (
        <div className="archive-split">
          <ul className="archive-index" aria-label="角色列表">
            {visible.map((character) => (
              <li key={character.id}><button type="button" className={character.id === selected.id ? "current" : ""} onClick={() => setSelectedId(character.id)}><span className="character-monogram" aria-hidden="true">{character.name.slice(0, 1)}</span><span><strong>{character.name}</strong><small>{character.identity || roleTypeLabel(character.role_type)}</small></span></button></li>
            ))}
          </ul>
          <article id={`character-${selected.id}`} className="archive-detail character-detail">
            <header><span className="character-monogram large" aria-hidden="true">{selected.name.slice(0, 1)}</span><div><h2>{selected.name}</h2><p>{selected.identity || roleTypeLabel(selected.role_type)}</p></div></header>
            <dl className="detail-grid">
              <div><dt><Icon name="users" />角色定位</dt><dd>{selected.identity || roleTypeLabel(selected.role_type)}</dd></div>
              <div><dt><Icon name="overview" />当前目标</dt><dd>{selected.goal || "尚未记录"}</dd></div>
              <div><dt><Icon name="pen" />当前状态</dt><dd>{selected.current_state || "尚未记录"}</dd></div>
              <div><dt><Icon name="memory" />知识边界</dt><dd>{selected.knowledge_boundary || "尚未记录"}</dd></div>
            </dl>
            <section className="character-alias-panel" aria-label="角色别名资料">
              <header><div><p className="eyebrow">明确资料层</p><h3>角色别名</h3></div><span className="version-chip">v{currentAliasSnapshot?.version??0}</span></header>
              <p className="muted">主名：{selected.name}。这里只记录作者确认的称呼，AI 不会把猜测写成别名。</p>
              <div className="alias-list">
                {currentAliasSnapshot?.aliases.map((item)=><AliasRow key={item.id} item={item} readOnly={readOnly} busy={aliasBusy} save={editAlias} archive={archiveAlias}/>)}
                {!currentAliasSnapshot?.aliases.length&&<p className="empty-inline">尚无别名。</p>}
              </div>
              {!readOnly&&<div className="alias-create"><input value={aliasInput} maxLength={80} onChange={(event)=>setAliasInput(event.target.value)} placeholder="添加作者确认的别名"/><Button className="secondary" disabled={aliasBusy||!aliasInput.trim()||(currentAliasSnapshot?.aliases.filter((item)=>item.status==="active").length??0)>=20} onClick={()=>void addAlias()}>添加别名</Button></div>}
            </section>
            <section className="change-impact-panel" aria-label="修改影响分析">
              <header><div><p className="eyebrow">AI 写作辅助 · 只读分析</p><h3>修改影响分析</h3></div>{impactRun&&<span className={`run-state state-${impactRun.status}`}>{impactRun.is_stale?"依据已变化":stage(impactRun.status)}</span>}</header>
              <p className="muted">明确写下拟修改内容；结果只指出受影响资料并给出证据，不生成替换正文，也不自动保存。</p>
              {!readOnly&&<div className="impact-create"><textarea value={impactInput} maxLength={4000} onChange={(event)=>setImpactInput(event.target.value)} placeholder={`例如：把“${selected.name}”的公开身份改为港务调查员`} /><Button className="secondary" disabled={impactBusy||Boolean(activeImpactRun)||!draft||!impactInput.trim()} onClick={()=>void startImpact()}>分析影响</Button></div>}
              {activeImpactRun&&activeImpactRun.run_id!==impactRun?.run_id&&<p className="analysis-pending">“{targetName(activeImpactRun)}”的影响分析正在{stage(activeImpactRun.status)}；完成或取消前不能创建另一项分析。</p>}
              {impactRun&&<div className="impact-context"><p><strong>分析对象：</strong>角色 · {targetName(impactRun)} <code>{proposalFor(impactRun)?.target_id}</code></p><p><strong>拟修改内容：</strong>{proposalFor(impactRun)?.proposed_change}</p><small>本 Run 绑定：草稿 r{impactRun.draft_revision} · 来源 r{impactRun.source_revision} · Story Memory V{impactRun.source_memory_version} · Author Context V{impactRun.author_context_version} · 别名 V{impactRun.alias_version??0} · 检索 {impactRun.retrieval?.method_version??"—"}</small></div>}
              {impactRun?.analysis&&<div className={`impact-result evidence-${impactRun.analysis.evidence_status??"supported"}`}><strong>{impactRun.analysis.summary}</strong>{impactRun.analysis.evidence_status==="insufficient"&&<p className="analysis-no-source">未形成可采信影响项；Provider 的无证据自由文本未被保留。</p>}{impactRun.analysis.items.map((item,index)=>"impact" in item?<article key={`${item.target_id}-${index}`}><h4>{item.label}</h4><p>{item.impact}</p><ul className="source-links">{item.evidence.map((source)=><li key={`${source.source_type}-${source.source_id}`}><a href={source.source_path} aria-label={`查看证据：${source.label}（${source.source_type}）`}>{source.label}<small>{source.source_type}</small></a></li>)}</ul></article>:null)}</div>}
              {impactRun&&!readOnly&&<div className="analysis-actions">{["queued","running"].includes(impactRun.status)&&<Button className="quiet" disabled={impactBusy} onClick={()=>void actionImpact("cancel")}>取消</Button>}{["failed","timed_out","cancelled"].includes(impactRun.status)&&impactRun.retryable&&<Button className="quiet" disabled={impactBusy||impactRun.is_stale} onClick={()=>void actionImpact("retry")}>重试</Button>}</div>}
              {!impactRun&&impactRuns.length>0&&<p className="empty-inline">当前角色尚无影响分析；其他对象的运行仅列在历史中。</p>}
              {impactRuns.length>0&&<details><summary>分析版本（{impactRuns.length}）</summary><ol className="impact-history">{impactRuns.map((run)=><li key={run.run_id}><span>{targetName(run)} · <code>{proposalFor(run)?.target_id??"—"}</code> · 第 {run.attempt_number??1} 次 · {stage(run.status)}</span><small>{proposalFor(run)?.proposed_change??"未记录提案"} · {run.is_stale?"依据已变化":"依据当前"}</small></li>)}</ol></details>}
            </section>
            {toolNotice&&<p className="notice compact" role="status">{toolNotice}</p>}
          </article>
        </div>
      ) : <div className="empty archive-empty">{characters.length ? "没有匹配的角色。" : "此作品还没有角色记录。"}</div>}
    </section>
  );
}

function AliasRow({item,readOnly,busy,save,archive}:{item:CharacterAliasSnapshot["aliases"][number];readOnly:boolean;busy:boolean;save:(id:string,value:string)=>Promise<void>;archive:(id:string)=>Promise<void>}){
  const [value,setValue]=useState(item.alias);
  return <div id={`alias-${item.id}`} className={`alias-row ${item.status}`}><input aria-label={`${item.alias} 别名`} value={value} disabled={readOnly||busy||item.status==="archived"} onChange={(event)=>setValue(event.target.value)}/><span>{item.status==="active"?"使用中":"已归档"}</span>{!readOnly&&item.status==="active"&&<><Button className="quiet" disabled={busy||!value.trim()||value===item.alias} onClick={()=>void save(item.id,value)}>保存</Button><Button className="quiet danger" disabled={busy} onClick={()=>void archive(item.id)}>归档</Button></>}</div>;
}

function WorldArchive({
  entries,
}: {
  entries: { id: string; entry_type: string; name: string; summary: string }[];
}) {
  const categories = ["location", "rule", "organization", "object", "term"];
  const requestedWorld=typeof window!=="undefined"?new URLSearchParams(window.location.search).get("world"):null;
  const requestedWorldEntry=entries.find((entry)=>entry.id===requestedWorld);
  const [category, setCategory] = useState(requestedWorldEntry?.entry_type??entries[0]?.entry_type ?? "location");
  const [query, setQuery] = useState("");
  const [selectedId, setSelectedId] = useState(requestedWorldEntry?.id??entries[0]?.id ?? "");
  const visible = entries.filter((entry) => entry.entry_type === category && `${entry.name} ${entry.summary}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()));
  const selected = visible.find((entry) => entry.id === selectedId) ?? visible[0];
  return (
    <section className="world-page">
      <div className="world-controls">
        <nav aria-label="世界观分类">{categories.map((value) => <button type="button" key={value} className={category === value ? "current" : ""} aria-current={category === value ? "page" : undefined} onClick={() => { setCategory(value); setSelectedId(""); }}>{worldTypeLabel(value)}</button>)}</nav>
        <label><span className="sr-only">搜索世界设定</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索世界设定" /></label>
      </div>
      {selected ? (
        <div className="archive-split world-split">
          <section className="world-index"><h2>{worldTypeLabel(category)}</h2><ul>{visible.map((entry) => <li key={entry.id}><button type="button" className={entry.id === selected.id ? "current" : ""} onClick={() => setSelectedId(entry.id)}>{entry.name}</button></li>)}</ul></section>
          <article id={`world-${selected.id}`} className="archive-detail world-detail"><h2>{selected.name}</h2><dl><div><dt>类型</dt><dd>{worldTypeLabel(selected.entry_type)}</dd></div><div><dt>设定摘要</dt><dd>{selected.summary || "尚未记录摘要"}</dd></div><div><dt>关联</dt><dd>暂未建立关联</dd></div></dl></article>
        </div>
      ) : <div className="empty archive-empty">{entries.length ? `“${worldTypeLabel(category)}”分类暂无匹配条目。` : "此作品还没有世界观记录。"}</div>}
    </section>
  );
}

function MemoryRecords({ records, openSource }: { records: Memory[]; openSource: (record: Memory, element: HTMLButtonElement) => void }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const filterNav = useRef<HTMLElement>(null);
  const filters = [
    ["all", "全部事实"],
    ["character_knowledge", "角色知识"],
    ["event_timeline", "时间线"],
    ["dynamic_state", "当前状态"],
    ["static_canon", "世界规则"],
    ["open_thread", "待确认"],
  ];
  const visible = records.filter((record) =>
    (filter === "all" || record.memory_type === filter) &&
    `${record.subject} ${predicateLabel(record.predicate)} ${record.value}`.toLocaleLowerCase().includes(query.toLocaleLowerCase()),
  );
  useEffect(() => {
    filterNav.current
      ?.querySelector<HTMLElement>('[aria-current="page"]')
      ?.scrollIntoView({ block: "nearest", inline: "center", behavior: "auto" });
  }, [filter]);
  return (
    <section className="memory-records" aria-label="Story Memory 事实档案">
      <div className="memory-controls">
        <div className="memory-filter-rail">
          <nav ref={filterNav} aria-label="事实分类">{filters.map(([value, label]) => <button type="button" key={value} className={filter === value ? "current" : ""} aria-current={filter === value ? "page" : undefined} onClick={() => setFilter(value)}>{label}</button>)}</nav>
        </div>
        <label><span className="sr-only">搜索事实</span><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="搜索事实" /></label>
      </div>
      {visible.length ? (
        <div className="memory-table" role="table" aria-label="事实档案">
          <div className="memory-row memory-head" role="row"><span>主体</span><span>属性</span><span>事实值</span><span>有效范围</span><span>状态</span><span>来源</span></div>
          {visible.map((record) => (
            <div id={`memory-${record.id}`} className="memory-row" role="row" key={record.id}>
              <strong role="cell" className="memory-subject">{record.subject}</strong>
              <span role="cell" className="memory-field" data-label="属性">{predicateLabel(record.predicate)}</span>
              <span role="cell" className="memory-field" data-label="当前值">{record.value}</span>
              <span role="cell" className="memory-field" data-label="有效范围">第 {record.valid_from ?? "?"} 章—{record.valid_to == null ? "当前章" : `第 ${record.valid_to} 章`}</span>
              <span role="cell" data-label="状态" className={`memory-status ${record.valid_to != null ? "retired" : record.review_status === "author_confirmed" ? "confirmed" : "pending"}`}><I>{record.valid_to != null ? "—" : record.review_status === "author_confirmed" ? "✓" : "○"}</I>{record.valid_to != null ? "已失效" : reviewStatusLabel(record.review_status)}</span>
              <Button className="quiet memory-source" ariaLabel={record.source ? `查看 ${record.subject} 的来源` : `${record.subject} 暂无来源`} disabled={!record.source} onClick={(event) => openSource(record, event.currentTarget)}>{record.source ? `第 ${record.source.chapter_number} 章 ↗` : "不可用"}</Button>
              <small className="memory-kind">{memoryTypeLabel(record.memory_type)}</small>
            </div>
          ))}
        </div>
      ) : <div className="empty archive-empty">没有匹配当前条件的事实。</div>}
    </section>
  );
}

function SourceDrawer({
  record,
  chapters,
  projectTitle,
  currentSourceRevision,
  close,
}: {
  record: ReadonlySourceRecord;
  chapters: Chapter[];
  projectTitle: string;
  currentSourceRevision?: number;
  close: () => void;
}) {
  useDocumentScrollLock();
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [leaving, setLeaving] = useState(false);
  const chapter = chapters.find((item) => item.id === record.chapterId || item.number === record.chapterNumber);
  const sourceSpans = chapter?.source_spans ?? [];
  const matchingSpan = sourceSpans.find((span) => span.span_id === record.spanId);
  const contextSpans = sourceSpans
    .filter((span) => span.span_id !== record.spanId)
    .slice(0, 2);

  useEffect(() => {
    closeRef.current?.focus();
  }, []);

  const requestClose = () => {
    if (leaving) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      close();
      return;
    }
    setLeaving(true);
    window.setTimeout(close, 140);
  };

  const containFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      requestClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      drawerRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    );
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };

  return (
    <div className={`modal-layer drawer-layer source-layer${leaving ? " is-closing" : ""}`} role="presentation">
      <aside
        className="drawer source-drawer"
        role="dialog"
        aria-modal="true"
        aria-label={`${record.subject} 的章节来源`}
        ref={drawerRef}
        onKeyDown={containFocus}
      >
        <button type="button" className="close" ref={closeRef} onClick={requestClose}>
          <span aria-hidden="true">×</span>
          <span className="sr-only">关闭章节来源</span>
        </button>
        <header className="drawer-header source-drawer-header">
          <p className="eyebrow">章节来源</p>
          <h2>第 {record.chapterNumber} 章《{record.chapterTitle || "标题未提供"}》</h2>
          <p>
            {matchingSpan?.source_revision == null && record.sourceRevision == null ? "来源修订未提供" : `来源修订 r${matchingSpan?.source_revision ?? record.sourceRevision}`}
            {matchingSpan?.label ? ` · ${matchingSpan.label}` : ""}
          </p>
        </header>
        <section className="evidence-section source-excerpt">
          <h3>被引用的原文片段</h3>
          <blockquote><mark>{matchingSpan?.text_excerpt || record.excerpt || "引用内容未提供"}</mark></blockquote>
        </section>
        <section className="evidence-section source-context">
          <h3>可用上下文</h3>
          {chapter?.summary ? <div className="source-summary"><strong>章节摘要</strong><p>{chapter.summary}</p></div> : <p className="source-unavailable">章节摘要未提供。</p>}
          {contextSpans.length ? contextSpans.map((span) => (
            <article key={span.span_id}>
              <strong>{span.label}</strong>
              <p>{span.text_excerpt}</p>
            </article>
          )) : <p className="source-unavailable">当前接口未提供更多同章片段。</p>}
        </section>
        <section className="evidence-section source-tags">
          <h3>{record.memoryType ? "事实状态" : "证据关系"}</h3>
          <div>
            {record.memoryType ? (
              <><span>{memoryTypeLabel(record.memoryType)}</span><span className={record.reviewStatus === "author_confirmed" ? "confirmed" : "pending"}>{reviewStatusLabel(record.reviewStatus ?? "")}</span></>
            ) : (
              <><span>{record.relation || "关系未提供"}</span><span>{record.sufficiency || "充分性未提供"}</span></>
            )}
          </div>
        </section>
        <details className="evidence-technical source-technical">
          <summary>技术详情</summary>
          <dl className="metadata">
            <div><dt>来源记录</dt><dd>{record.recordId || "未提供"}</dd></div>
            <div><dt>SourceSpan</dt><dd>{record.spanId || "未提供"}</dd></div>
            <div><dt>章节记录</dt><dd>{record.chapterId || "未提供"}</dd></div>
            <div><dt>作品当前来源修订</dt><dd>{currentSourceRevision == null ? "未提供" : `r${currentSourceRevision}`}</dd></div>
            <div><dt>来源路径（只读记录）</dt><dd>{record.sourcePath || "未提供"}</dd></div>
          </dl>
        </details>
        <footer className="drawer-assurance"><Icon name="security" />《{projectTitle}》的来源内容保持只读，不会从此处进入追加或编辑流程。</footer>
      </aside>
    </div>
  );
}

function Evidence({
  issue,
  run,
  readOnly,
  tutorial,
  busy,
  openSource,
  close,
  accept,
  decide,
}: {
  issue: Issue;
  run: Run | null;
  readOnly: boolean;
  tutorial: boolean;
  busy: string;
  openSource: (evidence: EvidenceItem, element: HTMLButtonElement) => void;
  close: () => void;
  accept: () => void;
  decide: (i: Issue, d: "keep_intentional" | "false_positive") => Promise<void>;
}) {
  useDocumentScrollLock();
  const drawerRef = useRef<HTMLElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const [leaving, setLeaving] = useState(false);
  useEffect(() => {
    closeRef.current?.focus();
  }, []);
  const requestClose = () => {
    if (leaving) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) {
      close();
      return;
    }
    setLeaving(true);
    window.setTimeout(close, 140);
  };
  const containFocus = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      requestClose();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(
      drawerRef.current?.querySelectorAll<HTMLElement>(
        'button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])',
      ) ?? [],
    ).filter((element) => !element.hasAttribute("hidden"));
    if (!focusable.length) {
      event.preventDefault();
      closeRef.current?.focus();
      return;
    }
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (event.shiftKey && document.activeElement === first) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && document.activeElement === last) {
      event.preventDefault();
      first.focus();
    }
  };
  const evidence = issue.evidence ?? [];
  return (
    <div className={`modal-layer drawer-layer evidence-layer${leaving ? " is-closing" : ""}`} role="presentation">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="问题证据"
        ref={drawerRef}
        onKeyDown={containFocus}
      >
        <button type="button" className="close" ref={closeRef} onClick={requestClose}>
          <span aria-hidden="true">×</span>
          <span className="sr-only">关闭</span>
        </button>
        <header className="drawer-header">
          <p className="eyebrow">证据</p>
          <div><h2>{categoryLabel(issue.category)}</h2><span className={`risk ${issue.severity}`}><I>{issue.severity === "high" ? "▲" : issue.severity === "medium" ? "●" : "○"}</I>{statusLabel(issue.severity)}</span></div>
          <p className="drawer-context">对照当前草稿与已写章节来源，再作出作者决定。</p>
        </header>
        <section className={`evidence-section current-claim severity-${issue.severity}`}>
          <h3>当前草稿</h3>
          <blockquote>{issue.claim_text || issue.explanation}</blockquote>
        </section>
        {evidence.length ? (
          <section className="evidence-section evidence-history">
            <h3>历史证据</h3>
            {evidence.map((x) => (
              <article className="evidence" key={x.id}>
                <blockquote>{x.excerpt}</blockquote>
                {x.excerpt_context !== x.excerpt && <p>上下文：{x.excerpt_context}</p>}
                <footer><strong>第 {x.chapter_number} 章《{x.chapter_title || "标题未提供"}》</strong><Button className="quiet evidence-source-link" onClick={(event) => openSource(x, event.currentTarget)}>查看来源 ↗</Button></footer>
              </article>
            ))}
          </section>
        ) : (
          <p className="warning">
            <I>!</I>没有可解析 Evidence；不能做作者决策。
          </p>
        )}
        <section className="evidence-section conflict-explanation">
          <h3>冲突说明</h3>
          <p>{issue.explanation}</p>
        </section>
        {!readOnly && (
          <section className="evidence-section author-decision">
            <h3>作者决定</h3>
            {issue.decision ? <p className="decision-feedback" role="status"><I>✓</I>决定已记录；此问题保留在列表中，便于后续追溯。</p> : <p>请选择如何处理此问题。</p>}
            <div className="drawer-actions">
              <Button className="primary" disabled={Boolean(busy) || !evidence.length || Boolean(issue.decision)} onClick={accept}>接受建议并编辑</Button>
              <Button disabled={Boolean(busy) || !evidence.length || Boolean(issue.decision)} onClick={() => void decide(issue, "keep_intentional")}>保留当前写法</Button>
              <Button className="quiet false-positive-action" disabled={Boolean(busy) || !evidence.length || Boolean(issue.decision)} onClick={() => void decide(issue, "false_positive")}>标记为误报</Button>
            </div>
          </section>
        )}
        {readOnly && (
          <p className={tutorial ? "readonly tutorial-mobile-decision-note" : "readonly"}>
            {tutorial
              ? "移动端可以浏览完整证据。请在桌面端继续完成作者决定。"
              : "浏览只读：作者决策不可用。"}
          </p>
        )}
        <details className="evidence-technical">
          <summary>技术详情</summary>
          <dl className="metadata">
            <div><dt>草稿位置</dt><dd>{issue.claim_span_id}</dd></div>
            <div><dt>检查记录 / 来源修订</dt><dd>{run?.run_id} · source r{run?.source_revision} / current r{run?.current_revision}</dd></div>
            <div><dt>谱系状态</dt><dd>{run?.is_stale ? "证据已过期" : "当前草稿谱系可用"} · {lineageStatusLabel(run?.lineage_status)}</dd></div>
            <div><dt>证据状态</dt><dd>{evidenceStatusLabel(issue.evidence_status)}</dd></div>
          </dl>
        </details>
        <footer className="drawer-assurance"><Icon name="security" />你的决定只应用于本次问题，并更新相应检查结果。</footer>
      </aside>
    </div>
  );
}
function Dialog({
  title,
  children,
  close,
  closeDisabled = false,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
  closeDisabled?: boolean;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const listener = (e: KeyboardEvent) => {
      if (e.key === "Escape" && !closeDisabled) close();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [close, closeDisabled]);
  return (
    <div className="modal-layer" role="presentation">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <Button className="close" disabled={closeDisabled} onClick={close}>
          <span ref={ref}>×</span>
          <span className="sr-only">关闭</span>
        </Button>
        <h2>{title}</h2>
        {children}
      </section>
    </div>
  );
}
