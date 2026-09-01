"use client";

import {
  FormEvent,
  MouseEventHandler,
  ReactNode,
  startTransition,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import { usePathname, useRouter } from "next/navigation";
import { json, labelError, request, type ApiFailure } from "../api";
import type {
  ChangeSet,
  Chapter,
  Draft,
  Issue,
  MemoryCoverage,
  MemoryDelta,
  MemoryInitialization,
  Memory,
  Onboarding,
  Project,
  ProjectSummary,
  Run,
  SourceChangeSet,
  User,
} from "../model";

// The optional catch-all page remounts its client tree between route segments.
// Keep the browser-owned session bootstrap for the lifetime of this module so
// ordinary in-app navigation does not turn into another authentication check.
let bootstrappedUser: User | null | undefined;
let sessionBootstrap: Promise<User | null> | null = null;
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
      running_continuity: "运行增量 Continuity",
      running_memory_delta: "运行 Memory Delta",
      cancelling: "正在安全取消",
      completed: "检查完成",
      timed_out: "检查超时",
      failed: "检查失败",
      cancelled: "已取消",
    }) as Record<string, string>
  )[s] ?? s;
const activeRun = (run: Run | null) => Boolean(run && ["queued", "running"].includes(run.status));
const retryableRun = (run: Run | null) => Boolean(run && ["failed", "timed_out", "cancelled"].includes(run.status) && (run.status !== "failed" || run.retryable));
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
      completed: "已完成",
    }) as Record<string, string>
  )[s ?? ""] ??
  s ??
  "—";
const memoryTypeLabel = (value: string) =>
  ({
    static_canon: "固定设定",
    dynamic_state: "当前状态",
    event_timeline: "事件时间线",
    character_knowledge: "角色所知",
    open_thread: "未解线索",
  })[value] ?? value;
const reviewStatusLabel = (value: string) =>
  value === "author_confirmed" ? "作者已确认" : value;
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
  })[value] ?? value;
const predicateLabel = (value: unknown) =>
  ({ holder: "持有人 / 存放状态", status: "状态", next_action: "下一步行动" })[
    String(value)
  ] ?? String(value);
function Button({
  children,
  className = "secondary",
  disabled,
  ariaPressed,
  ariaCurrent,
  ariaBusy,
  ariaLabel,
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
  onClick?: MouseEventHandler<HTMLButtonElement>;
  type?: "button" | "submit";
}) {
  return (
    <button
      type={type}
      className={className}
      disabled={disabled}
      aria-disabled={disabled || undefined}
      aria-pressed={ariaPressed}
      aria-current={ariaCurrent}
      aria-busy={ariaBusy || undefined}
      aria-label={ariaLabel}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" role="img" aria-label="Story Continuity 品牌标志">
      <path className="brand-page-back" d="M7.5 5.5h13a2 2 0 0 1 2 2v17h-13a2 2 0 0 1-2-2Z" />
      <path className="brand-page-front" d="M11.5 8.5h13v18h-11a2 2 0 0 1-2-2Z" />
      <path className="brand-line" d="M15 13h6.5M15 17h6.5M15 21h4" />
      <path className="brand-clue" d="m6 22 5-4 4 2 7-7" />
      <circle className="brand-node" cx="6" cy="22" r="1.5" />
      <circle className="brand-node" cx="22" cy="13" r="1.5" />
    </svg>
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
    <svg className="empty-manuscript-visual" viewBox="0 0 280 150" role="img" aria-label="第一章手稿与连续性时间线">
      <text x="16" y="98">01</text>
      <path className="empty-paper" d="M105 22h111l22 22v84H105Z" />
      <path className="empty-fold" d="M216 22v22h22" />
      <path className="empty-line" d="M126 59h83M126 73h70M126 87h83M126 101h51" />
      <path className="empty-timeline" d="M92 120h151" />
      <circle cx="111" cy="120" r="5" />
      <circle cx="168" cy="120" r="5" />
      <circle cx="224" cy="120" r="5" />
    </svg>
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
function Icon({ name }: { name: "home" | "library" | "overview" | "outline" | "users" | "world" | "memory" | "pen" | "save" | "play" | "security" | "tutorial" | "logout" }) {
  const paths: Record<string, ReactNode> = {
    home: <><path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-6H9v6H4a1 1 0 0 1-1-1Z" /></>,
    library: <><rect x="4" y="3" width="13" height="18" rx="2" /><path d="M8 7h5M8 11h5M8 15h4" /></>,
    overview: <><rect x="4" y="4" width="6" height="6" rx="1" /><rect x="14" y="4" width="6" height="6" rx="1" /><rect x="4" y="14" width="6" height="6" rx="1" /><rect x="14" y="14" width="6" height="6" rx="1" /></>,
    outline: <><path d="M8 6h12M8 12h12M8 18h12" /><path d="M4 6h.01M4 12h.01M4 18h.01" /></>,
    users: <><circle cx="9" cy="8" r="3" /><path d="M3 20c.5-3 2.5-5 6-5s5.5 2 6 5M17 11c2.2 0 4 1.7 4 4M16.5 5.2a3 3 0 0 1 0 5.6" /></>,
    world: <><path d="M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18Z" /><path d="M3.5 12h17M12 3c2.5 2.5 2.5 13.5 0 18M12 3c-2.5 2.5-2.5 13.5 0 18" /></>,
    memory: <><path d="M12 4a3 3 0 0 1 5.5 1.6A3.5 3.5 0 1 1 18 12c0 4-2.3 7-6 8-3.7-1-6-4-6-8a3.5 3.5 0 1 1 .5-6.4A3 3 0 0 1 12 4Z" /><path d="M9.5 12h5M12 9.5v5" /></>,
    pen: <><path d="m4 20 4.2-1 10-10a2.8 2.8 0 0 0-4-4l-10 10Z" /><path d="m13 6 4 4M4 20l1-4" /></>,
    save: <><path d="M5 3h12l3 3v15H4V4a1 1 0 0 1 1-1Z" /><path d="M8 3v6h8V3M8 21v-7h8v7" /></>,
    play: <><path d="m8 5 11 7-11 7Z" /></>,
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
    [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null),
    [chapters, setChapters] = useState<Chapter[]>([]),
    [memories, setMemories] = useState<Memory[]>([]),
    [draft, setDraft] = useState<Draft | null>(null),
    [saved, setSaved] = useState<Draft | null>(null),
    [run, setRun] = useState<Run | null>(null),
    [pairedRun, setPairedRun] = useState<Run | null>(null),
    [initialization, setInitialization] = useState<MemoryInitialization | null>(null),
    [memoryDelta, setMemoryDelta] = useState<MemoryDelta | null>(null),
    [coverage, setCoverage] = useState<MemoryCoverage | null>(null);
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
    [resetOpen, setResetOpen] = useState(false),
    [metaOpen, setMetaOpen] = useState(false),
    [archiveOpen, setArchiveOpen] = useState(false),
    [userMenuOpen, setUserMenuOpen] = useState(false),
    [preview, setPreview] = useState<ImportPreview | null>(null),
    [q, setQ] = useState(""),
    [filter, setFilter] = useState(""),
    [sort, setSort] = useState("updated_desc"),
    [onlyIssues, setOnlyIssues] = useState(false),
    [small, setSmall] = useState(false);
  const epoch = useRef(0),
    activeProjectRequest = useRef<AbortController | null>(null),
    trigger = useRef<HTMLElement | null>(null),
    userMenuTrigger = useRef<HTMLButtonElement | null>(null),
    projectModuleNav = useRef<HTMLElement | null>(null);
  const parts = pathname.split("/").filter(Boolean);
  const projectId =
    parts[0] === "projects" && parts[1] && !["new", "import"].includes(parts[1])
      ? parts[1]
      : null;
  const tab = parts[2] ?? "overview";
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
    setOutline(null);
    setCharacters([]);
    setWorld([]);
    setSelected(null);
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
  const updateBootstrappedUser = useCallback((next: User | null) => {
    bootstrappedUser = next;
    setUser(next);
  }, []);
  const go = (href: string) => {
    if (dirty && href !== pathname) setSwitchTo(href);
    else router.push(href);
  };
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
  const loadHome = useCallback(async () => {
    try {
      const [nextHome, nextOnboarding] = await Promise.all([
        request<Home>("/home"),
        request<Onboarding>("/onboarding"),
      ]);
      setHome(nextHome);
      setOnboarding(nextOnboarding);
    } catch (cause) {
      fail(cause);
    }
  }, [fail]);
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
        const [c, m, d, o, chars, w, initialized, memoryCoverage, delta] = await Promise.all([
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
        ]);
        if (n !== epoch.current) return;
        setProject(p);
        setChapters(c.chapters);
        setMemories(m.records);
        setDraft(d);
        setSaved(d);
        setOutline(o as never);
        setCharacters(chars.characters as never);
        setWorld(w.entries as never);
        setInitialization(initialized);
        setMemoryDelta(delta);
        setCoverage(memoryCoverage);
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
    [fail],
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
    }
  }, [
    ready,
    user,
    pathname,
    projectId,
    loadProject,
    loadProjects,
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
      clear();
      router.replace("/");
      setNotice(outcome === "complete" ? "教学已完成。现在可以导入第一部真实作品。" : "已跳过教学。现在可以导入第一部真实作品。");
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const reopenTutorial = async () => {
    setBusy("正在恢复教学样例");
    try {
      const data = await json<{ tutorial: { project_id: string } }>("/onboarding/reopen", "POST", { confirm: true });
      setUserMenuOpen(false);
      router.push(`/projects/${data.tutorial.project_id}/overview`);
    } catch (cause) {
      fail(cause);
    } finally {
      setBusy("");
    }
  };
  const save = async () => {
    if (!projectId || !draft || readOnly) return;
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
        setControlled(null);
        setRun(
          await request<Run>(
            `/projects/${projectId}/checks/${run.run_id}?include=issues,evidence,metrics`,
          ),
        );
        setNotice(`已按受控谱系保存 revision ${result.revision}。`);
      } else setNotice(`草稿已保存为 revision ${result.revision}。`);
    } catch (e) {
      fail(e);
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
      await json(`/projects/${projectId}/issues/${issue.id}/decision`, "POST", {
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
      setRun(
        await request<Run>(
          `/projects/${projectId}/checks/${run.run_id}?include=issues,evidence,metrics`,
        ),
      );
      setSelected(null);
      setNotice(
        decision === "keep_intentional"
          ? "已保留作者意图；可进入 Memory Review。"
          : "已标记为误报，不会写入 Story Memory。",
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
      const latest = await request<MemoryDelta>(`/projects/${projectId}/memory/delta`);
      setMemoryDelta(latest); setCoverage(latest.coverage ?? result.delta.coverage ?? null);
      if (latest.continuity_run_id && latest.memory_delta_run_id) {
        const [continuity, deltaRun] = await Promise.all([
          request<Run>(`/projects/${projectId}/checks/${latest.continuity_run_id}?include=issues,evidence,metrics`),
          request<Run>(`/projects/${projectId}/checks/${latest.memory_delta_run_id}?include=issues,evidence,metrics`),
        ]);
        setRun(continuity);
        setPairedRun(deltaRun);
      }
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
      setNotice(committed.memory_version > (memoryDelta.base_memory_version ?? 0) ? `Memory V${committed.memory_version} 已建立。` : "增量核心候选全部拒绝；已覆盖来源但 Memory 版本未变。");
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
  else if (pathname === "/account/security")
    body = <AccountSecurity user={user} updateUser={updateBootstrappedUser} go={go} />;
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
          cancel={() => setPreview(null)}
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
        memories={memories}
        initialization={initialization}
        memoryDelta={memoryDelta}
        coverage={coverage}
        draft={draft}
        saved={saved}
        run={run}
        pairedRun={pairedRun}
        locallyResolvedIssueIds={locallyResolvedIssueIds}
        readOnly={readOnly}
        busy={busy}
        controlled={controlled}
        changeSet={changeSet}
        setDraft={setDraft}
        save={save}
        check={check}
        cancelRun={cancelRun}
        retryRun={retryRun}
        select={(i, el) => {
          trigger.current = el;
          setSelected(i);
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
        go={go}
      />
    ) : (
      <div className="boot">{busy || "正在读取当前作品…"}</div>
    );
  return (
    <div className={`workbench${user ? "" : " auth-shell"}`}>
      <a className="skip" href="#main">
        跳到主要内容
      </a>
      {user && (
        <aside className="global-nav" aria-label="全局工作台">
          <div className="brand">
            <BrandMark />
            <span aria-label="Story Continuity">
              Story
              <br />
              Continuity
            </span>
          </div>
          <p className="nav-kicker">AUTHOR WORKBENCH</p>
          <nav aria-label="全局导航">
            <Button
              className={pathname === "/" ? "nav current" : "nav"}
              onClick={() => go("/")}
            >
              <Icon name="home" />
              首页
            </Button>
            <Button
              className={
                pathname.startsWith("/projects") ? "nav current" : "nav"
              }
              onClick={() => go("/projects")}
            >
              <Icon name="library" />
              作品管理
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
              <span className="account-avatar" aria-hidden="true">{user.display_name.slice(0, 1)}</span>
              <span className="account-copy">
                <span className="account-name">{user.display_name}</span>
                <span className="account-helper">{user.account_type === "visitor" ? "访客空间" : "个人账号"}</span>
              </span>
              <Chevron className="account-caret" />
            </button>
            {userMenuOpen && (
              <div className="user-menu" role="menu" aria-label="用户菜单">
                <p><strong>{user.display_name}</strong>{user.display_name.trim().toLocaleLowerCase() !== user.account_name.trim().toLocaleLowerCase() && <small>{user.account_name}</small>}</p>
                {user.account_type === "visitor" && <p className="visitor-expiry">访客空间有效至 <time>{timestampLabel(user.visitor_expires_at)}</time></p>}
                {user.account_type !== "visitor" && (
                  <button type="button" role="menuitem" onClick={() => go("/account/security")}><Icon name="security" />账号安全</button>
                )}
                {user.account_type !== "visitor" && (
                  <button type="button" role="menuitem" onClick={() => void reopenTutorial()}><Icon name="tutorial" />重新打开教学</button>
                )}
                <button
                  type="button"
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
      {selected && (
        <Evidence
          issue={selected}
          run={run}
          readOnly={readOnly}
          busy={busy}
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
      {switchTo && (
        <Dialog title="未保存草稿" close={() => setSwitchTo(null)}>
          <p>
            切换作品会清理旧作品的草稿、Run、Issue、Evidence 和 Memory Review
            状态。
          </p>
          <div className="actions">
            <Button
              className="primary"
              disabled={Boolean(busy)}
              onClick={async () => {
                await save();
                const t = switchTo;
                setSwitchTo(null);
                router.push(t);
              }}
            >
              保存并切换
            </Button>
            <Button
              onClick={() => {
                setDraft(saved);
                router.push(switchTo);
                setSwitchTo(null);
              }}
            >
              放弃修改
            </Button>
            <Button onClick={() => setSwitchTo(null)}>取消</Button>
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
        <div className="auth-brand" aria-label="Story Continuity">
          <BrandMark />
          <span aria-label="Story Continuity">
            Story Continuity
          </span>
        </div>
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
  return (
    <section className="home-page">
      <header className="home-heading">
        <p className="breadcrumb">全局 / 首页</p>
        <h1>继续你的故事</h1>
      </header>
      {onboarding?.show_first_run && onboarding.tutorial && (
        <section className="tutorial-entry" aria-label="首次教学">
          <div>
            <p className="eyebrow">首次使用 · 教学模式</p>
            <h2>用隔离样例走一遍核心流程</h2>
            <p>教学作品不会进入真实作品列表、搜索、数量或待处理问题。你可以随时完成或跳过。</p>
          </div>
          <div className="actions">
            <Button onClick={() => go("/projects/import")}>导入第一部作品</Button>
            <Button className="primary" onClick={() => open(onboarding.tutorial!.project_id)}>开始教学</Button>
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
              {home.continue_work.next_action === "continue_draft"
                ? "继续写作"
                : home.continue_work.next_action}
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
        <section className="empty-workspace">
          <EmptyManuscriptVisual />
          <div className="empty-workspace-copy">
            <p className="eyebrow">真实作品空间 · 尚未建立</p>
            <h2>你的第一部作品将从这里建立连续性档案。</h2>
            <p>导入 TXT / Markdown，或从空白作品开始。</p>
          </div>
          <div className="actions">
            <Button className="primary" onClick={() => go("/projects/import")}>导入第一部作品</Button>
            <Button onClick={() => go("/projects/new")}>新建空白作品</Button>
          </div>
        </section>
      ) : null}
      <div className="home-section-grid">
        <section className="home-section">
          <header className="home-section-head">
            <h2>最近作品</h2>
            <Button onClick={() => go("/projects")}>查看全部</Button>
          </header>
          {(home?.recent_projects ?? []).length ? (
            <ul className="home-work-list">
              {home!.recent_projects.map((item) => (
                <li key={item.project_id}>
                  <button onClick={() => open(item.project_id)}>
                    <strong>《{item.title}》</strong>
                    <span>{statusLabel(item.status)}</span>
                    <i aria-hidden="true">→</i>
                  </button>
                </li>
              ))}
            </ul>
          ) : <div className="empty compact-empty">还没有真实作品。</div>}
        </section>
        <section className="home-section home-issues-section">
          <h2>待处理问题</h2>
          {(home?.pending_continuity ?? []).length ? (
            <ul className="home-issue-list">
              {home!.pending_continuity.map((x) => {
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
          ) : <div className="empty compact-empty">当前没有待处理问题。</div>}
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
    <>
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
    </>
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
  return (
    <section className="projects-page">
      <header className="page-header">
        <div>
          <p className="breadcrumb">全局 / 作品管理</p>
          <h1>作品管理</h1>
        </div>
        <div className="actions">
          <Button onClick={() => go("/projects/import")}>导入作品</Button>
          <Button className="primary" onClick={() => go("/projects/new")}>
            新建作品
          </Button>
        </div>
      </header>
      <div className="filters project-toolbar">
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
      </div>
      <Rows
        rows={rows}
        open={open}
        append={(id) => go(`/projects/${id}/sources`)}
        filtered={Boolean(q || filter || onlyIssues || sort !== "updated_desc")}
      />
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
  commit,
  disabled,
}: {
  busy: string;
  error: unknown;
  preview: ImportPreview | null;
  previewFile: (file: File) => Promise<boolean>;
  cancel: () => void;
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
  const resetToFile = () => {
    cancel();
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
            <Button type="button" onClick={resetToFile} disabled={Boolean(busy)}>取消导入</Button>
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
            <Button onClick={resetToFile} disabled={Boolean(busy)}>返回重新选择</Button>
            <Button className="primary" onClick={() => setStep("confirm")} disabled={disabled || Boolean(busy)}>
              继续确认
            </Button>
            <Button onClick={resetToFile} disabled={Boolean(busy)}>取消导入</Button>
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
            <Button type="button" onClick={resetToFile} disabled={Boolean(busy)}>取消导入</Button>
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
          <p className="eyebrow">AGENT RUN · {run.run_type === "memory_delta" ? "MEMORY DELTA" : "CONTINUITY"}</p>
          <h2>{stage(run.stage)}</h2>
          <p>attempt {run.attempt_number ?? 1} · Run {run.run_id}</p>
        </div>
        <div className="run-actions">
          <span className={`run-state state-${run.status}`}>{stage(run.status)}</span>
          {actions && activeRun(run) && <Button disabled={blocked} onClick={() => void cancelRun()}>{run.stage === "cancelling" ? "正在取消" : "取消 Run"}</Button>}
          {actions && retryableRun(run) && <Button className="primary" disabled={blocked} onClick={() => void retryRun()}>重试为新 Run</Button>}
        </div>
      </header>
      {unfinished && <p className="run-safety" role="alert">{labelError({ code: run.error_code })} 本轮未写入部分 Issue、Evidence、Decision 或 Memory 结果。</p>}
      {run.stage === "cancelling" && <p className="run-safety" role="status">正在等待当前 Provider 阶段返回；迟到结果将被丢弃，不会进入业务表。</p>}
      <dl className="run-facts">
        <div><dt>创建 / 开始 / 结束</dt><dd>{timestampLabel(run.created_at)}<br />{timestampLabel(run.started_at)}<br />{timestampLabel(run.completed_at)}</dd></div>
        <div><dt>耗时</dt><dd>Run {durationLabel(run.duration_ms)}<br />Provider {durationLabel(metrics?.latency_ms)}</dd></div>
        <div><dt>Provider 用量</dt><dd>{metrics?.input_tokens == null ? "tokens 不可用" : `${metrics.input_tokens} in / ${metrics.output_tokens ?? 0} out`}<br />{metrics?.cost_available ? `实际 cost ¥${metrics.cost_cny}` : "cost unavailable（不估算）"}</dd></div>
        <div><dt>Lineage</dt><dd>source r{run.source_revision} · Memory V{run.source_memory_version ?? provenance?.source_memory_version ?? "—"}<br />root {run.root_run_id ?? run.run_id}</dd></div>
      </dl>
      {provenance && <details className="run-provenance"><summary>查看 provenance 与状态事件</summary><dl><div><dt>Provider / model</dt><dd>{provenance.provider_label} / {provenance.model_label}</dd></div><div><dt>Prompt / schema</dt><dd>{provenance.prompt_version} / {provenance.schema_version}</dd></div><div><dt>Retrieval</dt><dd>{provenance.retrieval_method_version}</dd></div></dl><ol>{(run.transitions ?? []).map((event) => <li key={event.sequence}><strong>{event.sequence}. {stage(event.stage)}</strong><span>{event.status} · {timestampLabel(event.created_at)}{event.error_code ? ` · ${event.error_code}` : ""}</span></li>)}</ol></details>}
    </section>
  );
}

function ProjectContextNotices({
  project,
  tab,
  readOnly,
  busy,
  finishTutorial,
  go,
}: {
  project: Project;
  tab: string;
  readOnly: boolean;
  busy: string;
  finishTutorial: (outcome: "complete" | "skip") => Promise<void>;
  go: (href: string) => void;
}) {
  const tutorialStep = tab === "workspace" ? 2 : tab === "sources" ? 3 : 1;
  const tutorialCopy = {
    1: {
      title: "了解作品资料与 Story Memory",
      task: "查看项目概览、人物与 Story Memory，理解连续性档案如何组织。",
      action: "下一步：查看连续性问题",
    },
    2: {
      title: "查看连续性问题与 Evidence",
      task: "浏览预置问题及 Evidence，理解判断如何回到原文证据。",
      action: "下一步：导入自己的作品",
    },
    3: {
      title: "完成教学并导入自己的作品",
      task: "确认追加章节的入口，然后结束隔离教学并建立真实作品。",
      action: "完成教学",
    },
  }[tutorialStep];
  return (
    <>
      {project.is_tutorial && (
        <section className="tutorial-mode-bar" aria-label="教学模式">
          <div className="tutorial-progress" aria-label="教学进度">
            <p><strong>{tutorialStep} / 3</strong><span>隔离教学</span></p>
            <div>
              <strong>{tutorialCopy.title}</strong>
              <span>{tutorialCopy.task}</span>
              <small>固定样例不会计入作品数量、搜索或待处理问题。</small>
            </div>
          </div>
          <div className="actions">
            <Button className="quiet" disabled={Boolean(busy)} onClick={() => void finishTutorial("skip")}>跳过教学</Button>
            <Button
              className="primary"
              disabled={Boolean(busy)}
              onClick={() => tutorialStep === 1
                ? go(`/projects/${project.id}/workspace`)
                : tutorialStep === 2
                  ? go(`/projects/${project.id}/sources`)
                  : void finishTutorial("complete")}
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
            : "移动端只读浏览：可查看资料与 Evidence；编辑和检查请回到桌面。"}
        </p>
      )}
    </>
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
  memories: Memory[];
  initialization: MemoryInitialization | null;
  memoryDelta: MemoryDelta | null;
  coverage: MemoryCoverage | null;
  draft: Draft | null;
  saved: Draft | null;
  run: Run | null;
  pairedRun: Run | null;
  locallyResolvedIssueIds: string[];
  readOnly: boolean;
  busy: string;
  controlled: Issue | null;
  changeSet: ChangeSet | null;
  setDraft: (v: Draft) => void;
  save: () => Promise<void>;
  check: () => Promise<void>;
  cancelRun: () => Promise<void>;
  retryRun: () => Promise<void>;
  select: (i: Issue, el: HTMLElement) => void;
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
  go: (href: string) => void;
}) {
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
        finishTutorial={p.finishTutorial}
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
        <div className="overview-grid">
          <section className="overview-panel current-draft-panel">
            <p className="eyebrow">当前草稿</p>
            <h2>第 {p.project.current_draft.chapter_number} 章</h2>
            <p>revision {p.project.current_draft.revision} · 当前可继续写作与审阅。</p>
            <div className="draft-progress" aria-hidden="true"><span /></div>
            <div className="overview-meta">
              <span>{p.project.chapter_count} 个章节</span>
              <span>已保存</span>
            </div>
          </section>
          <section className="overview-panel memory-panel" aria-label="Story Memory">
            <p className="eyebrow">STORY MEMORY</p>
            <h2>Memory V{p.project.current_memory_version}</h2>
            <p className="term-help">Story Memory 是作者确认、供后续连续性检查使用的事实集合；版本号代表一次明确提交后的完整快照。</p>
            <dl className="overview-kv">
              <div><dt>当前来源</dt><dd>Source r{p.project.source_revision ?? "—"}</dd></div>
              <div><dt>Memory coverage</dt><dd>{p.coverage?.status ?? "尚未提供"}</dd></div>
              <div><dt>检查状态</dt><dd>{p.project.continuity_status === "unchecked" ? "尚未检查" : p.project.continuity_status === "checked_clear" ? "已检查 · 0 项待处理" : `${p.project.open_issue_count ?? 0} 项待处理`}</dd></div>
              <div><dt>最近 Run</dt><dd>{p.project.latest_run ? stage(p.project.latest_run.status) : "尚无"}</dd></div>
            </dl>
          </section>
        </div>
        <section className="project-section">
          <h2>资料摘要</h2>
          <div className="overview-grid overview-reference-grid">
            <section className="overview-panel">
              <h3>大纲</h3>
              <p>{p.project.chapter_count ? `已建立 ${p.project.chapter_count} 个章节节点。` : "尚未建立章节节点。"}</p>
              <Button className="quiet" onClick={() => p.go(`/projects/${p.project.id}/outline`)}>查看大纲</Button>
            </section>
            <section className="overview-panel">
              <h3>角色与世界观</h3>
              <p>项目资料、角色状态与世界观条目会独立维护。</p>
              <Button className="quiet" onClick={() => p.go(`/projects/${p.project.id}/characters`)}>查看角色库</Button>
            </section>
          </div>
        </section>
        <section className="project-section latest-run-section">
          <h2>最近检查</h2>
          <div className="latest-run-row">
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
      <Read
        title="大纲"
        breadcrumb={`项目 / ${p.project.title} / 大纲`}
        note="查看当前章节结构。"
        context={contextNotices}
        items={(p.outline?.chapter_nodes ?? []).map((x) => (
          <li key={x.id}>
            <strong>
              第 {x.chapter_number} 章 · {x.title}
            </strong>
            <span>
              {statusLabel(x.status)} · {x.summary}
            </span>
          </li>
        ))}
        empty="此作品还没有大纲节点。"
      />
    );
  if (p.tab === "characters")
    return (
      <Read
        title="角色库"
        breadcrumb={`项目 / ${p.project.title} / 角色库`}
        note="查看角色身份、目标、当前状态和知识边界。"
        context={contextNotices}
        items={p.characters.map((x) => (
          <li key={x.id}>
            <strong>
              {x.name} · {x.role_type}
            </strong>
            <span>
              {x.identity}；目标：{x.goal}；状态：{x.current_state}；知识边界：
              {x.knowledge_boundary}
            </span>
          </li>
        ))}
        empty="此作品还没有角色记录。"
      />
    );
  if (p.tab === "world")
    return (
      <Read
        title="世界观"
        breadcrumb={`项目 / ${p.project.title} / 世界观`}
        note="查看地点、组织、规则、物件与术语。"
        context={contextNotices}
        items={p.world.map((x) => (
          <li key={x.id}>
            <strong>
              {x.name} · {x.entry_type}
            </strong>
            <span>{x.summary}</span>
          </li>
        ))}
        empty="此作品还没有世界观记录。"
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
          </section>
        )}
        {p.memoryDelta && p.memoryDelta.status !== "not_started" && p.memoryDelta.status !== "covered" ? (
          <MemoryDeltaReview delta={p.memoryDelta} blocked={blocked} submit={p.submitMemoryDelta} />
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
          <ul className="read-list">
            {p.memories.map((m) => (
              <li key={m.id}>
                <strong>
                  {m.subject} · {predicateLabel(m.predicate)}：{m.value}
                </strong>
                <span>
                  {memoryTypeLabel(m.memory_type)} · 有效范围（适用章节）{m.valid_from ?? "未标明"}–
                  {m.valid_to ?? "当前"} · {reviewStatusLabel(m.review_status)}
                </span>
                <small>
                  来源：{m.source ? `第 ${m.source.chapter_number} 章《${m.source.chapter_title}》` : "不可用"}
                  {m.source
                    ? ` · ${m.source.excerpt}`
                    : "（来源不可解析，已安全显示）"}
                </small>
              </li>
            ))}
          </ul>
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
          <p>草稿 revision {p.draft?.revision ?? "—"}</p>
        </div>
        {!p.readOnly && (
          <div className="actions">
            {dirty || p.controlled ? (
              <Button className="primary" disabled={blocked} onClick={() => void p.save()}>
                <Icon name="save" />
                {p.controlled ? "保存受控修订" : "保存草稿"}
              </Button>
            ) : (!p.run || (!activeRun(p.run) && !retryableRun(p.run))) ? (
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
          <I>!</I>受控编辑：只接受 source r{p.run?.source_revision} → r
          {(p.run?.source_revision ?? 0) + 1}，保存后会提交 Accept & edit 决策。
        </p>
      )}
      {p.project.data_origin === "user_import" && p.project.memory_initialization_status !== "completed" && (
        <p className="warning">
          <I>!</I>先在 Story Memory 中完成初始化审核；空 Memory V1 不会启动连续性检查。
          <Button className="quiet" onClick={() => p.go(`/projects/${p.project.id}/memory`)}>前往审核</Button>
        </p>
      )}
      {p.coverage?.status === "update_pending" && (
        <p className="warning"><I>!</I>Source r{p.project.source_revision} 已追加；仅新 SourceSpan 与已确认 Memory 会进入增量审阅。{p.memoryDelta?.status === "failed" ? "本次运行失败，未写入任何 Issue 或候选，可安全重试。" : <Button className="primary" disabled={blocked} onClick={() => void p.startIncrementalReview()}>运行增量检查</Button>}</p>
      )}
      {p.run && <RunLifecycle run={p.run} blocked={blocked} cancelRun={p.cancelRun} retryRun={p.retryRun} actions={!p.readOnly} />}
      {p.pairedRun && <RunLifecycle run={p.pairedRun} blocked={blocked} cancelRun={p.cancelRun} retryRun={p.retryRun} actions={false} />}
      <div className="workspace-grid">
        <section className="editor">
          <header className="editor-top">
            <div className="editor-title">
              <strong>{p.draft?.title || "当前草稿"}</strong>
              <span aria-label="草稿修订">draft · revision {p.draft?.revision ?? "—"} · {dirty ? "未保存" : "已保存"}</span>
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
          <label className="draft-field">
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
            <span>{p.run ? `${stage(p.run.stage)} · Evidence ${p.run.status === "completed" ? "可用" : activeRun(p.run) ? "处理中" : "不可用"}` : "尚未运行连续性检查"}</span>
            <span>{p.draft ? `${new Blob([p.draft.body]).size.toLocaleString()} bytes` : "读取中"}</span>
          </footer>
        </section>
        <aside className="issues">
          <header className="issues-top">
            <h2>Issues <span>{p.run?.issues?.length ?? 0}</span></h2>
            <span className="issues-filter" aria-hidden="true">⌘</span>
          </header>
          {p.run ? (
            <>
              <p className="run-meta" aria-label="连续性检查运行状态">
                {stage(p.run.stage)} · source revision {p.run.source_revision} · {p.run.is_stale ? "已过期" : "当前版本"}
              </p>
              {p.run.result_origin === "demo_preset" && <p className="preset-note" role="note"><strong>预置演示审阅数据</strong> · 用于本地体验完整审阅链路，本次未调用 Provider，也不代表模型实时判断。</p>}
              {["failed", "timed_out", "cancelled"].includes(p.run.status) && (
                <p className="inline-error">
                  {labelError({ code: p.run.error_code })} 未写入、也不展示部分结果。
                </p>
              )}
              <ul className="issue-list">
                {(p.run.issues ?? []).map((x) => (
                  <li key={x.id}>
                    <Button onClick={(e) => p.select(x, e.currentTarget)}>
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
                      <span>{x.claim_text || x.explanation}</span>
                      <small>{x.decision || p.locallyResolvedIssueIds.includes(x.id) ? "已决策" : "查看 Evidence"}</small>
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
            <div className="empty">尚无 Run。保存当前草稿后可提交检查。</div>
          )}
        </aside>
      </div>
      {p.memoryDelta && p.memoryDelta.status !== "not_started" && (
        <section className="project-section" aria-label="Memory Delta"><h2>Memory Delta</h2><p>Delta Run 与 Continuity Run 分开持久化。pending 候选不进入 canon，也不进入 Provider 输入。</p><p>source r{p.memoryDelta.source_revision} · {p.memoryDelta.status} · 核心待审 {p.memoryDelta.coverage?.counts.core_pending ?? 0}</p><Button onClick={() => p.go(`/projects/${p.project.id}/memory`)}>打开 Delta 审核与 Evidence</Button></section>
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
function MemoryDeltaReview({ delta, blocked, submit }: { delta: MemoryDelta; blocked: boolean; submit: (event: FormEvent<HTMLFormElement>) => Promise<void> }) {
  if (["processing", "cancelling"].includes(delta.status)) return <div className="empty" role="status">正在分别运行 Continuity 与 Memory Delta；只有双 Run 全部完成后才会显示结果。</div>;
  if (["failed", "timed_out", "cancelled"].includes(delta.status)) return <div className="notice error" role="alert">增量运行未完成：{labelError({ code: delta.error_code })} 没有写入 Issue、候选或 MemoryVersion，请在 Run 生命周期中安全重试。</div>;
  return <form className="review memory-init-review" aria-label="Memory Delta 审核" onSubmit={(event) => void submit(event)}><header><div><p className="eyebrow">MEMORY DELTA</p><h2>新增 Source r{delta.source_revision} 的候选</h2><p>核心候选必须全部决定；辅助候选可 pending，且不进入 canon 或 Provider 输入。当前 coverage：{delta.coverage?.status}。</p></div></header>{delta.candidates.map((candidate) => <article key={candidate.id} className="diff memory-init-candidate"><div className="candidate-source"><strong>Evidence · 第 {candidate.source.chapter_number} 章《{candidate.source.chapter_title}》</strong><p>{candidate.source.excerpt}</p><small>SourceSpan {candidate.source.span_id} · source r{candidate.source_revision}</small></div><div><strong>候选事实</strong><p>{memoryTypeLabel(candidate.memory_type)} · {candidate.subject} · {predicateLabel(candidate.predicate)}：{candidate.value}</p><small>delta · {candidate.review_priority === "core" ? "核心候选（必须决定）" : "辅助候选（可继续待审）"} · 尚未成为 canon</small></div>{candidate.decision_status === "pending" ? <><fieldset><legend>作者审核（未预选）</legend><label><input type="radio" name={`memory-delta:${candidate.id}`} value="accepted" disabled={blocked} />接受</label><label><input type="radio" name={`memory-delta:${candidate.id}`} value="rejected" disabled={blocked} />拒绝</label><label><input type="radio" name={`memory-delta:${candidate.id}`} value="edited" disabled={blocked} />编辑后接受</label></fieldset><div className="candidate-edit"><label>事实类型<select name={`memory-delta:${candidate.id}:memory_type`} defaultValue={candidate.memory_type} disabled={blocked}>{["static_canon","dynamic_state","event_timeline","character_knowledge","open_thread"].map((type) => <option key={type} value={type}>{memoryTypeLabel(type)}</option>)}</select></label><label>对象<input name={`memory-delta:${candidate.id}:subject`} defaultValue={candidate.subject} disabled={blocked} /></label><label>关系<input name={`memory-delta:${candidate.id}:predicate`} defaultValue={candidate.predicate} disabled={blocked} /></label><label>事实内容<textarea name={`memory-delta:${candidate.id}:value`} defaultValue={candidate.value} disabled={blocked} /></label></div></> : <p>已由作者决定：{candidate.decision_status}；{candidate.decision_status === "rejected" ? "不写入 canon。" : "将在核心闭合提交时写入新 MemoryVersion。"}</p>}</article>)}<footer className="actions"><Button className="primary" type="submit" disabled={blocked || !delta.candidates.length}>提交已决定的核心候选</Button></footer></form>;
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
    <Read title="现有章节来源" breadcrumb="Evidence 可回源" note="历史 Evidence 保持指向原 SourceSpan。" items={chapters.flatMap((chapter) => (chapter.source_spans ?? []).map((span) => <li key={span.span_id} id={`span-${span.span_id}`}><strong>第 {chapter.number} 章《{chapter.title}》 · {span.label}</strong><span>{span.text_excerpt}</span></li>))} empty="此作品还没有可回源的章节片段。" />
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
function Evidence({
  issue,
  run,
  readOnly,
  busy,
  close,
  accept,
  decide,
}: {
  issue: Issue;
  run: Run | null;
  readOnly: boolean;
  busy: string;
  close: () => void;
  accept: () => void;
  decide: (i: Issue, d: "keep_intentional" | "false_positive") => Promise<void>;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const listener = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [close]);
  const evidence = issue.evidence ?? [];
  return (
    <div className="modal-layer" role="presentation">
      <aside
        className="drawer"
        role="dialog"
        aria-modal="true"
        aria-label="问题证据"
      >
        <Button className="close" onClick={close}>
          <span ref={ref}>×</span>
          <span className="sr-only">关闭</span>
        </Button>
        <p className="eyebrow">EVIDENCE</p>
        <h2>{categoryLabel(issue.category)}</h2>
        <p>
          <span className={`risk ${issue.severity}`}>
            <I>▲</I>
            {statusLabel(issue.severity)}
          </span>{" "}
          {issue.claim_text || issue.explanation}
        </p>
        <dl className="metadata">
          <div>
            <dt>问题句</dt>
            <dd>{issue.claim_text || issue.explanation}</dd>
          </div>
          <div>
            <dt>草稿位置</dt>
            <dd>{issue.claim_span_id}</dd>
          </div>
          <div>
            <dt>检查记录 / 来源修订</dt>
            <dd>
              {run?.run_id} · source r{run?.source_revision} / current r
              {run?.current_revision}
            </dd>
          </div>
          <div>
            <dt>谱系状态</dt>
            <dd>
              {run?.is_stale ? "证据已过期" : "当前草稿谱系可用"} · {run?.lineage_status}
            </dd>
          </div>
        </dl>
        {evidence.length ? (
          <section>
            <h3>Evidence</h3>
            <p>可核对的来源证据</p>
            {evidence.map((x) => (
              <article className="evidence" key={x.id}>
                <strong>
                  第 {x.chapter_number} 章《{x.chapter_title}》
                </strong>
                <p><strong>来源修订：</strong>草稿 r{x.source_revision}</p>
                <blockquote>{x.excerpt}</blockquote>
                {x.excerpt_context !== x.excerpt && <p>上下文：{x.excerpt_context}</p>}
                <small>
                  {x.relation === "contradicts" ? "与当前表述冲突" : x.relation === "supports" ? "支持当前表述" : "提供上下文"} · {x.sufficiency === "sufficient" ? "证据充分" : "证据不足"}
                </small>
                <p>
                  相关 Memory：
                  {x.related_memory_ids.join("；") || "无"}
                </p>
                <a href={x.source_path}>回到当前作品的章节来源</a>
              </article>
            ))}
          </section>
        ) : (
          <p className="warning">
            <I>!</I>没有可解析 Evidence；不能做作者决策。
          </p>
        )}
        {!readOnly && (
          <div className="drawer-actions">
            <Button className="primary" disabled={Boolean(busy) || !evidence.length} onClick={accept}>Accept & edit</Button>
            <Button disabled={Boolean(busy) || !evidence.length} onClick={() => void decide(issue, "keep_intentional")}>Keep intentional</Button>
            <Button disabled={Boolean(busy) || !evidence.length} onClick={() => void decide(issue, "false_positive")}>Mark false positive</Button>
          </div>
        )}
        {readOnly && <p className="readonly">浏览只读：作者决策不可用。</p>}
      </aside>
    </div>
  );
}
function Dialog({
  title,
  children,
  close,
}: {
  title: string;
  children: ReactNode;
  close: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const listener = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", listener);
    return () => window.removeEventListener("keydown", listener);
  }, [close]);
  return (
    <div className="modal-layer" role="presentation">
      <section
        className="dialog"
        role="dialog"
        aria-modal="true"
        aria-label={title}
      >
        <Button className="close" onClick={close}>
          <span ref={ref}>×</span>
          <span className="sr-only">关闭</span>
        </Button>
        <h2>{title}</h2>
        {children}
      </section>
    </div>
  );
}
