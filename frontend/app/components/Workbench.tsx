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
  Memory,
  Project,
  ProjectSummary,
  Run,
  User,
} from "../model";

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
      completed: "检查完成",
      failed: "检查失败",
    }) as Record<string, string>
  )[s] ?? s;
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
function Button({
  children,
  className = "secondary",
  disabled,
  ariaPressed,
  ariaCurrent,
  onClick,
  type = "button",
}: {
  children: ReactNode;
  className?: string;
  disabled?: boolean;
  ariaPressed?: boolean;
  ariaCurrent?: "page";
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
      onClick={onClick}
    >
      {children}
    </button>
  );
}
function I({ children }: { children: string }) {
  return (
    <span className="icon" aria-hidden="true">
      {children}
    </span>
  );
}
function Icon({ name }: { name: "home" | "library" | "overview" | "outline" | "users" | "world" | "memory" | "pen" | "save" | "play" }) {
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
  };
  return <svg className="ui-icon" viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export function Workbench() {
  const router = useRouter(),
    pathname = usePathname();
  const [user, setUser] = useState<User | null>(null),
    [ready, setReady] = useState(false),
    [home, setHome] = useState<Home | null>(null),
    [projects, setProjects] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<Project | null>(null),
    [chapters, setChapters] = useState<Chapter[]>([]),
    [memories, setMemories] = useState<Memory[]>([]),
    [draft, setDraft] = useState<Draft | null>(null),
    [saved, setSaved] = useState<Draft | null>(null),
    [run, setRun] = useState<Run | null>(null);
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
    [onlyIssues, setOnlyIssues] = useState(false);
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
  const small = typeof window !== "undefined" && window.innerWidth < 1024,
    readOnly = small || project?.status === "archived",
    dirty = Boolean(
      draft &&
      saved &&
      (draft.title !== saved.title || draft.body !== saved.body),
    );
  function clear() {
    setProject(null);
    setChapters([]);
    setMemories([]);
    setDraft(null);
    setSaved(null);
    setRun(null);
    setOutline(null);
    setCharacters([]);
    setWorld([]);
    setSelected(null);
    setControlled(null);
    setLocallyResolvedIssueIds([]);
    setChangeSet(null);
    setUserMenuOpen(false);
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
        setUser(null);
        clear();
        router.replace("/login");
      }
    },
    [router],
  );
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
  const loadProject = useCallback(
    async (id: string) => {
      activeProjectRequest.current?.abort();
      const n = ++epoch.current,
        controller = new AbortController();
      activeProjectRequest.current = controller;
      clear();
      setBusy("正在读取作品");
      try {
        const p = await request<Project>(`/projects/${id}`, {
          signal: controller.signal,
        });
        const [c, m, d, o, chars, w] = await Promise.all([
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
        if (p.latest_run) {
          const latest = await request<Run>(
            `/projects/${id}/checks/${p.latest_run.run_id}?include=issues,evidence,metrics`,
            { signal: controller.signal },
          );
          if (n === epoch.current) setRun(latest);
        }
      } catch (e) {
        if ((e as Error).name !== "AbortError") fail(e);
      } finally {
        if (n === epoch.current) setBusy("");
      }
    },
    [fail],
  );
  useEffect(() => {
    if (["/login", "/register"].includes(pathname)) {
      const timer = window.setTimeout(() => setReady(true), 0);
      return () => window.clearTimeout(timer);
    }
    request<{ user: User }>("/auth/session")
      .then((x) => setUser(x.user))
      .catch((e) => {
        if ((e as ApiFailure).code !== "authentication_required") fail(e);
      })
      .finally(() => setReady(true));
  }, [fail, pathname]);
  useEffect(() => {
    if (!ready) return;
    const auth = ["/login", "/register"].includes(pathname);
    if (!user && !auth) {
      router.replace("/login");
      return;
    }
    if (user && auth) {
      router.replace("/");
      return;
    }
    if (!user) return;
    if (projectId) void Promise.resolve().then(() => loadProject(projectId));
    else {
      if (pathname === "/") request<Home>("/home").then(setHome).catch(fail);
      if (pathname.startsWith("/projects")) void Promise.resolve().then(() => loadProjects());
    }
  }, [
    ready,
    user,
    pathname,
    projectId,
    loadProject,
    loadProjects,
    router,
    fail,
  ]);
  useEffect(() => {
    if (!run || !projectId || !["queued", "running"].includes(run.status))
      return;
    const timer = window.setInterval(
      () =>
        request<Run>(
          `/projects/${projectId}/checks/${run.run_id}?include=issues,evidence,metrics`,
        )
          .then((next) => {
            setRun(next);
            if (!["queued", "running"].includes(next.status))
              setNotice(
                next.status === "completed"
                  ? "检查完成，等待作者审阅。"
                  : labelError({ code: next.error_code }),
              );
          })
          .catch(fail),
      1000,
    );
    return () => window.clearInterval(timer);
  }, [run, projectId, fail]);
  const submitAuth = async (
    e: FormEvent<HTMLFormElement>,
    kind: "login" | "register",
  ) => {
    e.preventDefault();
    const f = new FormData(e.currentTarget);
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
            };
      const data = await json<{ user: User }>(`/auth/${kind}`, "POST", body);
      startTransition(() => {
        setUser(data.user);
        router.replace("/");
      });
    } catch (x) {
      fail(x);
    } finally {
      setBusy("");
    }
  };
  const logout = async () => {
    try {
      await request("/auth/logout", { method: "POST" });
      startTransition(() => {
        clear();
        setUser(null);
        router.replace("/login");
      });
    } catch (e) {
      fail(e);
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
      setNotice("检查已排队；只轮询此 Run，不展示模型推理过程。");
    } catch (e) {
      fail(e);
    } finally {
      setBusy("");
    }
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
          .filter((i) => String(form.get(i.id)) === "accepted")
          .map((i) => i.id),
        rejected_item_ids = changeSet.items
          .filter((i) => String(form.get(i.id)) === "rejected")
          .map((i) => i.id);
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
  else if (!user)
    body = (
      <Auth
        register={pathname === "/register"}
        busy={busy}
        error={error}
        submit={submitAuth}
        go={(h) => router.push(h)}
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
        draft={draft}
        saved={saved}
        run={run}
        locallyResolvedIssueIds={locallyResolvedIssueIds}
        readOnly={readOnly}
        busy={busy}
        controlled={controlled}
        changeSet={changeSet}
        setDraft={setDraft}
        save={save}
        check={check}
        select={(i, el) => {
          trigger.current = el;
          setSelected(i);
        }}
        review={review}
        commit={commit}
        reset={() => setResetOpen(true)}
        meta={() => setMetaOpen(true)}
        archive={() => setArchiveOpen(true)}
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
            <span className="brand-mark" aria-hidden="true" />
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
              <span className="account-name">{user.display_name}</span>
              <span className="account-caret" aria-hidden="true">⌄</span>
            </button>
            {userMenuOpen && (
              <div className="user-menu" role="menu" aria-label="用户菜单">
                <p>{user.display_name}<small>{user.account_name}</small></p>
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => void logout()}
                >
                  退出登录
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
              <small>当前作品</small>
              <strong>{project.title}</strong>
            </span>
            <span className="project-switch-mark" aria-hidden="true">⌄</span>
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
          <div className="project-nav-foot">
            <Button className="quiet" onClick={() => setMetaOpen(true)}>
              编辑作品信息
            </Button>
          </div>
        </aside>
      )}
      <main id="main">
        {projectId && readOnly && project && (
          <p className="readonly" role="note">
            <I>◉</I>
            {project.status === "archived"
              ? "作品已归档：仅可浏览，恢复后才可保存、检查、决策、提交或 Reset。"
              : "浏览只读：小于 1024px 可阅读资料与证据；作者操作仅在桌面可用。"}
          </p>
        )}
        {(notice || Boolean(error)) && (
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
        <Dialog title="确认项目级 Reset" close={() => setResetOpen(false)}>
          <p>
            将恢复《{project.title}》。
            {project.data_origin === "user_import"
              ? "保留已确认导入的 Chapter 和 SourceSpan；清除后续 Run、Issue、Decision、ChangeSet，并恢复空 Memory V1 与下一章草稿 r1。"
              : project.data_origin === "demo_seed"
                ? "恢复此预置作品的独立 seed、Memory 与草稿；不会改变其他作品或其他账户。"
                : "恢复空 Outline、角色、世界观、Memory V1 与草稿 r1；不会改变其他作品。"}
          </p>
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
  go,
}: {
  register: boolean;
  busy: string;
  error: unknown;
  submit: (
    e: FormEvent<HTMLFormElement>,
    k: "login" | "register",
  ) => Promise<void>;
  go: (href: string) => void;
}) {
  return (
    <section className="auth-layout">
      <section className="auth">
        <div className="auth-brand" aria-label="Story Continuity">
          <span className="brand-mark" aria-hidden="true" />
          <span aria-label="Story Continuity">
            Story
            <br />
            Continuity
          </span>
        </div>
        <div className="auth-heading">
          <p className="eyebrow">AUTHOR WORKBENCH</p>
          <h1>{register ? "创建账号" : "登录"}</h1>
          <p className="auth-lede">{register ? "创建本地账号，开始管理你的作品。" : "继续你的作品与连续性工作。"}</p>
        </div>
        <form onSubmit={(e) => void submit(e, register ? "register" : "login")}>
          <label>
            账号
            <input
              name="account_name"
              autoComplete="username"
              required
              minLength={3}
            />
          </label>
          {register && (
          <label>
            显示名称
            <input name="display_name" required maxLength={60} />
          </label>
          )}
          <label>
            密码
            <input
              name="password"
              type="password"
              autoComplete={register ? "new-password" : "current-password"}
              required
              minLength={10}
            />
          </label>
          {Boolean(error) && (
            <p className="inline-error" role="alert">
              {labelError(error)}
            </p>
          )}
          <div className="auth-actions">
            <Button className="primary" type="submit" disabled={Boolean(busy)}>
              {busy || (register ? "创建本地账号" : "登录")}
            </Button>
            <Button className="quiet" onClick={() => go(register ? "/login" : "/register")}>
              {register ? "前往登录" : "前往注册"}
            </Button>
          </div>
        </form>
      </section>
    </section>
  );
}
function HomePage({
  home,
  open,
  go,
}: {
  home: Home | null;
  open: (id: string) => void;
  go: (h: string) => void;
}) {
  return (
    <section className="home-page">
      <header className="home-heading">
        <p className="breadcrumb">全局 / 首页</p>
        <h1>继续你的故事</h1>
      </header>
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
      ) : (
        <div className="empty home-empty">
          尚无继续工作。创建或导入作品后，这里会显示真实状态。
        </div>
      )}
      <section className="home-section">
        <header className="home-section-head">
          <h2>最近作品</h2>
          <Button onClick={() => go("/projects")}>查看全部作品</Button>
        </header>
        <ul className="home-work-list">
          {(home?.recent_projects ?? []).map((project) => (
            <li key={project.project_id}>
              <button onClick={() => open(project.project_id)}>
                <strong>《{project.title}》</strong>
                <span>{statusLabel(project.status)}</span>
                <i aria-hidden="true">→</i>
              </button>
            </li>
          ))}
        </ul>
      </section>
      <section className="home-section home-issues-section">
        <h2>待处理连续性问题</h2>
        {(home?.pending_continuity ?? []).length ? (
          <ul className="home-issue-list">
            {home!.pending_continuity.map((x) => {
              const total = x.high + x.medium + x.low;
              const tone = x.high ? "high" : x.medium ? "medium" : "low";
              return (
                <li key={x.project_id}>
                  <button onClick={() => open(x.project_id)}>
                    <span>
                      <strong>《{x.title}》</strong>
                      <small>
                        高风险 {x.high} · 中风险 {x.medium} · 低风险 {x.low}
                      </small>
                    </span>
                    <b className={`risk ${tone}`}>
                      <I>{tone === "high" ? "▲" : tone === "medium" ? "●" : "✓"}</I>
                      {total} 项待处理
                    </b>
                  </button>
                </li>
              );
            })}
          </ul>
        ) : (
          <div className="empty">当前没有待处理的连续性问题。</div>
        )}
      </section>
    </section>
  );
}
function Rows({
  rows,
  open,
}: {
  rows: Array<
    Pick<ProjectSummary, "title" | "status"> &
      Partial<
        Pick<
          ProjectSummary,
          "genre" | "summary" | "current_memory_version" | "open_issue_count"
        >
      > &
      Partial<Pick<ProjectSummary, "id">> & { project_id?: string }
  >;
  open: (id: string) => void;
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
              {p.open_issue_count ?? 0} 项待处理
            </span>
            <Button className="quiet project-open" onClick={() => open(projectId)}>打开</Button>
          </li>
        );
      })}
      </ul>
    </>
  ) : (
    <div className="empty">没有符合条件的作品。</div>
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
        <label>
          <span className="sr-only">搜索</span>
          <input placeholder="搜索标题或简介" value={q} onChange={(e) => set("q", e.target.value)} />
        </label>
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
        <label className="check">
          <input
            type="checkbox"
            checked={onlyIssues}
            onChange={(e) => set("issues", e.target.checked)}
          />
          仅有待处理问题
        </label>
        <Button className="primary" disabled={Boolean(busy)} onClick={refresh}>
          应用条件
        </Button>
        <Button onClick={clear}>
          清除条件
        </Button>
      </div>
      <Rows rows={rows} open={open} />
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
  draft: Draft | null;
  saved: Draft | null;
  run: Run | null;
  locallyResolvedIssueIds: string[];
  readOnly: boolean;
  busy: string;
  controlled: Issue | null;
  changeSet: ChangeSet | null;
  setDraft: (v: Draft) => void;
  save: () => Promise<void>;
  check: () => Promise<void>;
  select: (i: Issue, el: HTMLElement) => void;
  review: () => Promise<void>;
  commit: (event: FormEvent<HTMLFormElement>) => Promise<void>;
  reset: () => void;
  meta: () => void;
  archive: () => void;
  go: (href: string) => void;
}) {
  const dirty = Boolean(
      p.draft &&
      p.saved &&
      (p.draft.title !== p.saved.title || p.draft.body !== p.saved.body),
    ),
    blocked = p.readOnly || Boolean(p.busy);
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
            <Button onClick={p.reset}>Reset 当前作品</Button>
            <Button onClick={p.archive}>
              {p.project.status === "archived" ? "恢复作品" : "归档作品"}
            </Button>
            <Button onClick={p.meta}>编辑信息</Button>
            <Button className="primary" onClick={() => p.go(`/projects/${p.project.id}/workspace`)}>
              <Icon name="pen" />继续草稿
            </Button>
          </div>
        </header>
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
            <dl className="overview-kv">
              <div><dt>待处理</dt><dd>{p.project.open_issue_count ?? 0} 项</dd></div>
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
              <strong>{p.project.latest_run ? stage(p.project.latest_run.status) : "尚无 Run"}</strong>
              <span>{p.project.latest_run ? `Run ${p.project.latest_run.run_id}` : "保存草稿后可运行连续性检查。"}</span>
            </div>
            <Button className="secondary" onClick={() => p.go(`/projects/${p.project.id}/workspace`)}>打开审阅</Button>
          </div>
        </section>
        {p.project.data_origin === "user_import" && (
          <section className="warning import-context">
            <I>!</I>导入作品尚待作者确认 Story Memory；初始化前检查会安全返回 insufficient_project_context。
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
            <p>Memory V{p.project.current_memory_version}</p>
          </div>
        </header>
        {p.memories.length ? (
          <ul className="read-list">
            {p.memories.map((m) => (
              <li key={m.id}>
                <strong>
                  {m.subject} · {m.predicate}：{m.value}
                </strong>
                <span>
                  {m.memory_type} · 有效范围 {m.valid_from ?? "—"}–
                  {m.valid_to ?? "今"} · {m.review_status}
                </span>
                <small>
                  来源：{m.source?.chapter_id ?? "不可用"}/
                  {m.source?.span_id ?? "不可用"}
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
  return (
    <section className="project-page workspace-page">
      <header className="page-header project-page-header workspace-page-header">
        <div>
          <p className="breadcrumb">项目 / {p.project.title} / 写作与检查</p>
          <h1>{p.draft?.title || "正在读取草稿"}</h1>
          <p>草稿 revision {p.draft?.revision ?? "—"}</p>
        </div>
        <div className="actions">
          <Button disabled={blocked} onClick={p.reset}>
            Reset 当前作品
          </Button>
          {dirty || p.controlled ? (
            <Button
              className="primary"
              disabled={blocked}
              onClick={() => void p.save()}
            >
              <Icon name="save" />
              {p.controlled ? "保存受控修订" : "保存草稿"}
            </Button>
          ) : (
            <Button
              className="primary"
              disabled={blocked || !p.draft}
              onClick={() => void p.check()}
            >
              <Icon name="play" />
              运行连续性检查
            </Button>
          )}
        </div>
      </header>
      {p.controlled && (
        <p className="warning">
          <I>!</I>受控编辑：只接受 source r{p.run?.source_revision} → r
          {(p.run?.source_revision ?? 0) + 1}，保存后会提交 Accept & edit 决策。
        </p>
      )}
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
            <span>{p.run ? `${stage(p.run.stage)} · evidence ${p.run.status === "completed" ? "可用" : "处理中"}` : "尚未运行连续性检查"}</span>
            <span>{p.draft ? `${new Blob([p.draft.body]).size.toLocaleString()} bytes` : "读取中"}</span>
          </footer>
        </section>
        <aside className="issues">
          <header className="issues-top">
            <h2>待审阅问题 <span>{p.run?.issues?.length ?? 0}</span></h2>
            <span className="issues-filter" aria-hidden="true">⌘</span>
          </header>
          {p.run ? (
            <>
              <p className="run-meta" aria-label="连续性检查运行状态">
                {stage(p.run.stage)} · source revision {p.run.source_revision} · {p.run.is_stale ? "已过期" : "当前版本"}
              </p>
              {p.run.status === "failed" && (
                <p className="inline-error">
                  {labelError({ code: p.run.error_code })}
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
                      <strong>{x.category}</strong>
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
      {p.changeSet && (
        <form className="review" aria-label="Memory Update Review" onSubmit={(event) => void p.commit(event)}>
          <header>
            <div>
              <p className="eyebrow">NESTED WORKFLOW</p>
              <h2>Memory Update Review</h2>
              <p>
                base V{p.changeSet.base_memory_version} → target V
                {p.changeSet.target_memory_version}；逐项决定后才会写入。
              </p>
            </div>
          </header>
          {p.changeSet.items.map((x) => (
            <article key={x.id} className="diff">
              <div>
                <strong>Before</strong>
                <pre>{JSON.stringify(x.before, null, 2)}</pre>
              </div>
              <div>
                <strong>After</strong>
                <pre>{JSON.stringify(x.after, null, 2)}</pre>
              </div>
              <fieldset>
                <legend>作者审核</legend>
                <label><input type="radio" name={x.id} value="accepted" defaultChecked disabled={blocked} />接受（写入候选）</label>
                <label><input type="radio" name={x.id} value="rejected" disabled={blocked} />拒绝（不写入）</label>
              </fieldset>
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
function Read({
  title,
  breadcrumb,
  note,
  items,
  empty,
}: {
  title: string;
  breadcrumb: string;
  note: string;
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
        <h2>{issue.category}</h2>
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
            <dt>Run / revision</dt>
            <dd>
              {run?.run_id} · source r{run?.source_revision} / current r
              {run?.current_revision}
            </dd>
          </div>
          <div>
            <dt>stale / superseded / lineage</dt>
            <dd>
              {String(run?.is_stale)} / {String(run?.superseded)} /{" "}
              {run?.lineage_status}
            </dd>
          </div>
        </dl>
        {evidence.length ? (
          <section>
            <h3>Evidence</h3>
            {evidence.map((x) => (
              <article className="evidence" key={x.id}>
                <strong>
                  {x.chapter_id}/{x.span_id}
                </strong>
                <p>{x.excerpt}</p>
                <small>
                  {x.relation} · 充分性：{x.sufficiency}
                </small>
                <p>
                  相关 Memory：
                  {x.related_memory_ids.join("；") || "无"}
                </p>
              </article>
            ))}
          </section>
        ) : (
          <p className="warning">
            <I>!</I>没有可解析 Evidence；不能做作者决策。
          </p>
        )}
        <div className="drawer-actions">
          <Button
            className="primary"
            disabled={readOnly || Boolean(busy) || !evidence.length}
            onClick={accept}
          >
            Accept & edit
          </Button>
          <Button
            disabled={readOnly || Boolean(busy) || !evidence.length}
            onClick={() => void decide(issue, "keep_intentional")}
          >
            Keep intentional
          </Button>
          <Button
            disabled={readOnly || Boolean(busy) || !evidence.length}
            onClick={() => void decide(issue, "false_positive")}
          >
            Mark false positive
          </Button>
        </div>
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
