"use client";

// The whole client: session, routing by path, the top bar, page-level messages, and the guards that
// stop an unsaved draft or an unrecorded decision from being lost on navigation or sign-out.
import { usePathname, useRouter } from "next/navigation";
import { startTransition, useCallback, useEffect, useLayoutEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { json, labelError, request, type ApiFailure } from "../api";
import type { Onboarding, TutorialEvent, TutorialProgress, User } from "../model";
import { AuthPage, PasswordResetConfirmPage, PasswordResetRequestPage, VerifyEmailPage } from "./pages/auth";
import { HomePage } from "./pages/home";
import { WorksPage } from "./pages/works";
import { NewWorkPage } from "./pages/new-work";
import { ImportPage } from "./pages/import";
import { ProfilePage, SecurityPage } from "./pages/account";
import { NotFoundPage, TutorialCompletePage } from "./pages/misc";
import { ProjectFrame } from "./project/frame";
import { hasUnsubmittedRevision } from "./project/chapter-desk";
import { useProject } from "./project/use-project";
import { Avatar, Wordmark } from "./identity";
import { Button, Chevron, Dialog, pad2, usageShort, useUsage } from "./ui";
import { timeLabel } from "./labels";

// Keep the session check for the module's life.
let bootstrappedUser: User | null | undefined;
let sessionBootstrap: Promise<User | null> | null = null;
let rememberedTheme: "day" | "night" | undefined;
// Where the current tab's underline was, so the next page can slide it across.
let lastTabMark: { kind: string; left: number; width: number } | null = null;
const themeKey = "story-continuity:theme";
const publicAuthPaths = ["/login", "/register", "/password-reset", "/password-reset/confirm", "/verify-email"];
// A signed-in author who opens one of these is sent home; nothing of them is drawn on the way.
const signedOutOnlyPaths = ["/login", "/register", "/password-reset", "/password-reset/confirm"];
export const TUTORIAL_VERSION = "1.2.0";

export const projectTabs = [
  ["overview", "概览"],
  ["workspace", "写作"],
  ["sources", "章节"],
  ["memory", "资料"],
  ["plan", "计划"],
] as const;
// Addresses from before v1.7.0 keep working.
const legacyTabs: Record<string, string> = { outline: "plan", characters: "memory", world: "memory" };

export function App() {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(() => bootstrappedUser ?? null);
  const [ready, setReady] = useState(() => bootstrappedUser !== undefined);
  const [theme, setTheme] = useState<"day" | "night">(() => rememberedTheme ?? "day");
  const [narrow, setNarrow] = useState(false);
  const [notice, setNotice] = useState("");
  const [error, setError] = useState<unknown>(null);
  // The address an error should follow to: an expired session sends the author to /login, where the reason is shown.
  const [errorFollowsTo, setErrorFollowsTo] = useState<string | null>(null);
  const [busy, setBusy] = useState("");
  const [onboarding, setOnboarding] = useState<Onboarding | null>(null);
  const [tutorialProgress, setTutorialProgress] = useState<TutorialProgress | null>(null);
  const [menuOpen, setMenuOpen] = useState(false);
  const [switchTo, setSwitchTo] = useState<string | null>(null);
  const [revisionLeave, setRevisionLeave] = useState<string | null>(null);
  const [switchSaving, setSwitchSaving] = useState(false);
  const [switchFailed, setSwitchFailed] = useState(false);
  const [confirmUnstoredLogout, setConfirmUnstoredLogout] = useState(false);
  const menuTrigger = useRef<HTMLButtonElement>(null);
  const switchPending = useRef(false);

  const parts = pathname.split("/").filter(Boolean);
  const projectId = parts[0] === "projects" && parts[1] && !["new", "import"].includes(parts[1]) ? parts[1] : null;
  const rawTab = parts[2] ?? "overview";
  const tab = legacyTabs[rawTab] ?? rawTab;

  const notify = useCallback((message: string) => { setError(null); setNotice(message); }, []);
  // Set once useProject exists below; an expired session drops the open work so nothing lingers.
  const clearProject = useRef<() => void>(() => undefined);
  const fail = useCallback((cause: unknown) => {
    setError(cause);
    setNotice("");
    if ((cause as ApiFailure).code === "authentication_required") {
      bootstrappedUser = null;
      setUser(null);
      clearProject.current();
      setErrorFollowsTo("/login");
      router.replace("/login");
    }
  }, [router]);
  const applyOnboarding = useCallback((next: Onboarding) => {
    setOnboarding(next);
    setTutorialProgress((current) => {
      if (!next.progress) return null;
      if (current && current.tutorial_project_id === next.progress.tutorial_project_id && current.tutorial_version === next.progress.tutorial_version && current.current_step > next.progress.current_step) return current;
      return next.progress;
    });
  }, []);
  const recordTutorialEvent = useCallback(async (tutorialProjectId: string, event: TutorialEvent, context?: { run_id: string; issue_id: string }) => {
    try {
      const next = await json<TutorialProgress>("/onboarding/progress", "POST", { tutorial_version: TUTORIAL_VERSION, project_id: tutorialProjectId, event, ...context });
      setTutorialProgress(next);
      setOnboarding((current) => (current ? { ...current, progress: next } : current));
      return next;
    } catch (cause) {
      try { applyOnboarding(await request<Onboarding>("/onboarding")); } catch { /* keep the first failure */ }
      console.warn("导览进度暂时没有记下，当前操作仍可继续。", cause);
    }
  }, [applyOnboarding]);

  const p = useProject({ projectId, user, narrow, onboarding, tutorialProgress, fail, notify, applyOnboarding, recordTutorialEvent });
  useEffect(() => { clearProject.current = p.clear; }, [p.clear]);

  // Theme: layout.tsx applies it before paint — the choice remembered on this device, otherwise the
  // system's light or dark setting.
  useEffect(() => {
    if (rememberedTheme !== undefined) return;
    const timer = window.setTimeout(() => {
      rememberedTheme = document.documentElement.dataset.theme === "night" ? "night" : "day";
      setTheme(rememberedTheme);
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);
  // Switching sweeps the new colours across the page from the switch's side, like paper through a press.
  const toggleTheme = () => {
    const next = theme === "night" ? "day" : "night";
    rememberedTheme = next;
    try { window.localStorage.setItem(themeKey, next); } catch { /* switches for this visit only */ }
    const apply = () => { document.documentElement.dataset.theme = next; flushSync(() => setTheme(next)); };
    const sweep = (document as Document & { startViewTransition?: (update: () => void) => unknown }).startViewTransition;
    if (sweep && !window.matchMedia("(prefers-reduced-motion: reduce)").matches) sweep.call(document, apply);
    else apply();
  };
  // A new address starts at the top (an #anchor is scrolled to by the page), without the last error.
  const [shownPath, setShownPath] = useState(pathname);
  if (shownPath !== pathname) {
    setShownPath(pathname);
    // The redirect to the login page keeps the "登录已过期" reason; any other new address starts without the last error.
    if (errorFollowsTo === pathname) setErrorFollowsTo(null);
    else { setError(null); setErrorFollowsTo(null); }
  }
  useEffect(() => { if (!window.location.hash) window.scrollTo({ top: 0 }); }, [pathname]);
  // Messages leave by themselves after a while; errors stay until closed.
  useEffect(() => {
    if (!notice) return;
    const timer = window.setTimeout(() => setNotice(""), 6000);
    return () => window.clearTimeout(timer);
  }, [notice]);
  // The current tab's underline slides over from where it was on the previous page.
  const tabs = useRef<HTMLElement>(null);
  const tabMark = useRef<HTMLSpanElement>(null);
  const tabKind = projectId ? "project" : "global";
  useLayoutEffect(() => {
    const nav = tabs.current, mark = tabMark.current;
    const current = nav?.querySelector<HTMLElement>(".topbar-tab[aria-current='page']");
    if (!nav || !mark) return;
    if (!current) { mark.style.opacity = "0"; return; }
    const left = current.offsetLeft, width = current.offsetWidth;
    Object.assign(mark.style, { opacity: "1", left: `${left}px`, top: `${current.offsetTop + current.offsetHeight - 4}px`, width: `${width}px`, transition: "none", transform: "none" });
    const previous = lastTabMark;
    lastTabMark = { kind: tabKind, left, width };
    if (!previous || previous.kind !== tabKind || (previous.left === left && previous.width === width) || window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    mark.style.transform = `translateX(${previous.left - left}px) scaleX(${previous.width / width})`;
    void mark.offsetWidth;
    mark.style.transition = "transform var(--dur-mid) var(--ease)";
    mark.style.transform = "none";
  }, [tabKind, tab, pathname, p.project?.id, user]);

  useEffect(() => {
    const update = () => setNarrow(window.innerWidth < 1024);
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, []);

  useEffect(() => {
    if (bootstrappedUser !== undefined) return;
    const bootstrap = sessionBootstrap ?? (sessionBootstrap = request<{ user: User | null }>("/auth/session?optional=true")
      .then((x) => { bootstrappedUser = x.user; return x.user; })
      .catch((cause) => { if ((cause as ApiFailure).code === "authentication_required") { bootstrappedUser = null; return null; } throw cause; })
      .finally(() => { sessionBootstrap = null; }));
    bootstrap.then((next) => setUser(next)).catch(fail).finally(() => setReady(true));
  }, [fail]);
  useEffect(() => {
    if (!ready) return;
    const isPublic = publicAuthPaths.includes(pathname);
    if (!user && !isPublic) { router.replace("/login"); return; }
    if (user && signedOutOnlyPaths.includes(pathname)) { router.replace("/"); return; }
    if (user && pathname === "/") request<Onboarding>("/onboarding").then(applyOnboarding).catch(fail);
  }, [ready, user, pathname, router, applyOnboarding, fail]);
  useEffect(() => {
    if (!menuOpen) return;
    const items = () => Array.from(document.querySelectorAll<HTMLElement>(".account-menu [role^='menuitem']"));
    requestAnimationFrame(() => items()[0]?.focus());
    const close = (event: KeyboardEvent) => {
      if (event.key === "Escape") { setMenuOpen(false); requestAnimationFrame(() => menuTrigger.current?.focus()); return; }
      if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
      const list = items();
      if (!list.length) return;
      event.preventDefault();
      const at = list.indexOf(document.activeElement as HTMLElement);
      list[(at + (event.key === "ArrowDown" ? 1 : list.length - 1)) % list.length].focus();
    };
    const outside = (event: PointerEvent) => { if (!(event.target as HTMLElement).closest(".account")) setMenuOpen(false); };
    window.addEventListener("keydown", close);
    document.addEventListener("pointerdown", outside);
    return () => { window.removeEventListener("keydown", close); document.removeEventListener("pointerdown", outside); };
  }, [menuOpen]);

  const updateUser = useCallback((next: User | null) => { bootstrappedUser = next; setUser(next); }, []);
  const go = (href: string) => {
    setMenuOpen(false);
    // Moving between the tabs of the open work keeps it (and any unsaved text) in memory; leaving the
    // work drops it, so that asks first.
    const target = href.split(/[?#]/)[0].split("/").filter(Boolean);
    const sameWork = Boolean(projectId) && target[0] === "projects" && target[1] === projectId;
    if ((p.dirty || p.pendingControlledDecision) && href !== pathname && !sameWork) { setSwitchFailed(false); setSwitchTo(href); }
    else if (hasUnsubmittedRevision() && href !== pathname) setRevisionLeave(href);
    else router.push(href);
  };

  // Leaving with unsaved text asks first; Ctrl/⌘+S saves.
  useEffect(() => {
    if (!p.dirty && !p.pendingControlledDecision) return;
    const warn = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", warn);
    return () => window.removeEventListener("beforeunload", warn);
  }, [p.dirty, p.pendingControlledDecision]);
  useEffect(() => {
    const shortcut = (event: KeyboardEvent) => {
      if (!(event.ctrlKey || event.metaKey) || event.key.toLocaleLowerCase() !== "s") return;
      event.preventDefault();
      if ((!p.dirty && !p.pendingControlledDecision) || p.busy || p.readOnly || p.draftRecoveryConflict || p.pendingDecisionConflict) return;
      void p.save();
    };
    window.addEventListener("keydown", shortcut);
    return () => window.removeEventListener("keydown", shortcut);
  });

  const submitAuth = async (form: FormData, kind: "login" | "register") => {
    setError(null); setNotice("");
    setBusy(kind === "login" ? "正在登录" : "正在创建账号");
    try {
      const body = kind === "login"
        ? { account_name: String(form.get("account_name")), password: String(form.get("password")) }
        : { account_name: String(form.get("account_name")), display_name: String(form.get("display_name")), password: String(form.get("password")), recovery_email: String(form.get("recovery_email")) };
      const data = await json<{ user: User }>(`/auth/${kind}`, "POST", body);
      startTransition(() => { updateUser(data.user); router.replace("/"); });
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const enterVisitor = async () => {
    setError(null); setNotice("");
    setBusy("正在创建访客空间");
    try {
      const data = await request<{ user: User }>("/auth/visitor", { method: "POST" });
      startTransition(() => { updateUser(data.user); router.replace("/"); });
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const performLogout = async () => {
    try {
      await request("/auth/logout", { method: "POST" });
      startTransition(() => { p.clear(); setTutorialProgress(null); setOnboarding(null); updateUser(null); router.replace("/login"); });
    } catch (cause) { fail(cause); }
  };
  const logout = async () => {
    setMenuOpen(false);
    if (p.pendingControlledDecision && !p.pendingDecisionConflict) {
      notify(p.pendingDecisionStorageUnavailable ? "正文已保存，但待补记的决定存不进浏览器。请留在此页重试成功后再退出。" : "正文已保存，但这一条的决定还没记下。请先补记再退出；不会重复保存正文。");
      return;
    }
    if (p.pendingControlledDecision && p.pendingDecisionConflict && !p.pendingDecisionPersisted) { setConfirmUnstoredLogout(true); return; }
    await performLogout();
  };
  const finishTutorial = async (outcome: "complete" | "skip") => {
    if (p.pendingControlledDecision) { notify("正文已保存，但这一条的决定还没记下。请先补记，再结束或跳过导览。"); return; }
    setBusy(outcome === "complete" ? "正在完成导览" : "正在跳过导览");
    try {
      await json(`/onboarding/${outcome}`, "POST", { confirm: true });
      setTutorialProgress(null);
      setOnboarding(null);
      p.clear();
      if (outcome === "complete") { setNotice(""); router.replace("/onboarding/complete"); }
      else { router.replace("/"); notify("已跳过导览。现在可以导入自己的作品。"); }
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };
  const reopenTutorial = async () => {
    setMenuOpen(false);
    const tutorial = onboarding?.tutorial;
    if (!tutorial) { notify("这个账号没有可以重新开始的示例作品。"); return; }
    setBusy("正在重新开始导览");
    try {
      const next = await json<Onboarding>("/onboarding/progress/restart", "POST", {
        tutorial_version: TUTORIAL_VERSION, project_id: tutorial.project_id, base_revision: tutorialProgress?.revision ?? onboarding?.progress?.revision ?? null, confirm: true,
      });
      applyOnboarding(next);
      p.markTutorialRestarted();
      notify("导览回到了第一步；正文、资料和处理记录都没有变。");
      go(`/projects/${tutorial.project_id}/overview`);
    } catch (cause) { fail(cause); } finally { setBusy(""); }
  };

  const usage = useUsage(user ? `${user.id}:${pathname}:${p.run?.run_id ?? ""}:${p.run?.status ?? ""}` : "");
  const tutorialStep = (p.project?.is_tutorial && tutorialProgress?.tutorial_project_id === p.project.id ? tutorialProgress.current_step : 1) as 1 | 2 | 3 | 4 | 5;

  let body;
  if (!ready || (user && signedOutOnlyPaths.includes(pathname))) body = <div className="boot" role="status">正在载入…</div>;
  else if (pathname === "/password-reset") body = <PasswordResetRequestPage go={(href) => router.push(href)} />;
  else if (pathname === "/password-reset/confirm") body = <PasswordResetConfirmPage go={(href) => router.push(href)} />;
  else if (pathname === "/verify-email") body = <VerifyEmailPage go={(href) => router.push(href)} refreshUser={updateUser} />;
  else if (!user) body = <AuthPage register={pathname === "/register"} busy={busy} error={error} submit={submitAuth} visitor={enterVisitor} go={(href) => { setError(null); setNotice(""); router.push(href); }} />;
  else if (pathname === "/account/profile") body = <ProfilePage user={user} updateUser={updateUser} go={go} />;
  else if (pathname === "/account/security") body = <SecurityPage user={user} updateUser={updateUser} go={go} />;
  else if (pathname === "/onboarding/complete") body = <TutorialCompletePage go={(href) => { p.clear(); window.scrollTo(0, 0); router.replace(href); }} />;
  else if (!projectId)
    body = pathname === "/projects/new" ? <NewWorkPage fail={fail} go={go} />
      : pathname === "/projects/import" ? <ImportPage user={user} fail={fail} go={go} />
        : pathname === "/projects" ? <WorksPage fail={fail} go={go} />
          : pathname === "/" ? <HomePage user={user} onboarding={onboarding} usage={usage} fail={fail} go={go} reopenTutorial={() => void reopenTutorial()} />
            : <NotFoundPage kind="page" go={go} />;
  else if (p.project) body = <ProjectFrame key={`${projectId}:${tab}`} p={p} tab={tab} rawTab={rawTab} user={user} usage={usage} tutorialStep={tutorialStep} finishTutorial={finishTutorial} recordTutorialEvent={recordTutorialEvent} go={go} />;
  else body = p.missingProjectId === projectId ? <NotFoundPage kind="project" go={go} /> : <div className="boot" role="status">{p.busy || "正在读取作品…"}</div>;

  const showFeedback = !publicAuthPaths.includes(pathname) && Boolean(user) && (notice || Boolean(error));
  return (
    <div className={`app${user ? "" : " app-auth"}`}>
      <a className="skip" href="#main" onClick={() => document.getElementById("main")?.focus()}>跳到主要内容</a>
      {user && (
        <header className="topbar">
          <div className="topbar-inner">
            <button type="button" className="topbar-brand" aria-label="首页" onClick={() => go("/")}><Wordmark /></button>
            {projectId && p.project && (
              <button type="button" className="topbar-work" aria-label={`更换当前作品：${p.project.title}`} onClick={() => go("/projects")}>
                <span>{p.project.title}</span><Chevron />
              </button>
            )}
            <nav ref={tabs} className={projectId ? "topbar-tabs" : "topbar-tabs global"} aria-label={projectId ? "作品" : "全局"}>
              <span ref={tabMark} className="tab-mark" aria-hidden="true" />
              {projectId
                ? p.project && projectTabs.map(([id, label], index) => (
                    <button key={id} type="button" className="topbar-tab" aria-current={id === tab ? "page" : undefined} onClick={() => go(`/projects/${p.project!.id}/${id}`)}>
                      <span className="topbar-tab-num" aria-hidden="true">{pad2(index + 1)}</span>{label}
                    </button>
                  ))
                : <>
                    <button type="button" className="topbar-tab" aria-current={pathname === "/" ? "page" : undefined} onClick={() => go("/")}>首页</button>
                    <button type="button" className="topbar-tab" aria-current={pathname.startsWith("/projects") ? "page" : undefined} onClick={() => go("/projects")}>作品管理</button>
                  </>}
            </nav>
            {usageShort(usage) && <span className="topbar-quota">{usageShort(usage)}</span>}
            {!projectId && !["/projects", "/projects/new", "/projects/import"].includes(pathname) && <Button kind="outline" className="topbar-new" onClick={() => go("/projects/new")}>新建作品</Button>}
            <ThemeSwitch theme={theme} toggle={toggleTheme} />
            <div className="account">
              <button ref={menuTrigger} type="button" className="account-trigger" aria-label={`账号菜单：${user.display_name}`} aria-haspopup="menu" aria-expanded={menuOpen} onClick={() => setMenuOpen((open) => !open)}>
                <Avatar user={user} />
              </button>
              {menuOpen && (
                <div className="account-menu" role="menu" aria-label="账号菜单">
                  <p className="account-menu-head"><strong>{user.display_name}</strong><span>{user.account_type === "visitor" ? <>访客空间 · 有效至 {timeLabel(user.visitor_expires_at)}</> : `@${user.account_name}`}</span></p>
                  {user.account_type !== "visitor" && <button type="button" role="menuitem" onClick={() => go("/account/profile")}>个人信息</button>}
                  {user.account_type !== "visitor" && <button type="button" role="menuitem" onClick={() => go("/account/security")}>账号安全</button>}
                  {user.account_type !== "visitor" && <button type="button" role="menuitem" onClick={() => void reopenTutorial()}>重新看一遍导览</button>}
                  <button type="button" role="menuitem" className="danger" onClick={() => void logout()}>退出登录</button>
                </div>
              )}
            </div>
          </div>
        </header>
      )}
      {!user && ready && <ThemeSwitch theme={theme} toggle={toggleTheme} floating />}
      <main id="main" tabIndex={-1} className={user ? "main" : "main main-auth"}>
        {showFeedback && (
          <div className={error ? "feedback error" : "feedback"} role={error ? "alert" : "status"}>
            <span key={error ? "error" : notice}>{error ? labelError(error) : notice}</span>
            <button type="button" className="feedback-close" aria-label="关闭提示" onClick={() => { setError(null); setNotice(""); }}>×</button>
          </div>
        )}
        {busy && user && <p className="sr-only" role="status">{busy}</p>}
        {narrow && user && !projectId && (pathname === "/" || pathname === "/projects") && (
          <p className="note note-info narrow-note" role="note">窗口较窄：可以浏览作品和检查结果；写作和检查需要电脑或更宽的窗口。</p>
        )}
        {body}
      </main>
      {switchTo && (
        <Dialog title={p.pendingDecisionConflict ? "待补记的决定已失效" : p.pendingControlledDecision ? "决定还没记下" : "草稿还没保存"} closeDisabled={switchSaving} close={() => { if (!switchPending.current) setSwitchTo(null); }}>
          <p>{p.pendingDecisionConflict
            ? p.pendingDecisionPersisted ? "服务器状态已经变了，旧的决定不会再提交。可以保留这条本机记录离开，或者停止补记并读取服务器上的最新正文。" : "服务器状态已经变了，旧的决定不会再提交。这个浏览器没能保存这条记录；离开会丢失它。"
            : p.pendingControlledDecision ? "正文已经保存，但这一条的决定还没记下。补记完成后才能安全离开；重试不会再次保存正文。"
              : "草稿还有没保存的修改。换页前先保存，或者放弃这些修改。"}</p>
          {switchFailed && Boolean(error) && <p className="inline-error" role="alert">没保存成功，还没离开。{labelError(error)} 标题和正文都还在。</p>}
          <div className="dialog-actions">
            {p.pendingDecisionConflict ? (
              <>
                <Button kind="primary" disabled={Boolean(p.busy) || switchSaving} onClick={() => { const target = switchTo; setSwitchTo(null); p.clear(); router.push(target); }}>{p.pendingDecisionPersisted ? "保留记录并离开" : "丢弃这条记录并离开"}</Button>
                <Button disabled={Boolean(p.busy) || switchSaving} onClick={() => { setSwitchTo(null); void p.stopConflictedPendingDecision(); }}>停止补记并读取最新正文</Button>
              </>
            ) : (
              <Button kind="primary" disabled={Boolean(p.busy) || switchSaving} onClick={async () => {
                switchPending.current = true; setSwitchSaving(true); setSwitchFailed(false);
                const ok = await p.save();
                switchPending.current = false; setSwitchSaving(false);
                if (!ok) { setSwitchFailed(true); return; }
                const target = switchTo; setSwitchTo(null); router.push(target);
              }}>{p.pendingControlledDecision ? "补记决定并离开" : "保存并离开"}</Button>
            )}
            {!p.pendingControlledDecision && !p.pendingDecisionConflict && (
              <Button disabled={switchSaving} onClick={() => { if (switchPending.current) return; if (p.saved) p.setDraft(p.saved); const target = switchTo; setSwitchTo(null); router.push(target); }}>不保存，直接离开</Button>
            )}
            <Button kind="text" disabled={switchSaving} onClick={() => { if (!switchPending.current) setSwitchTo(null); }}>留在这里</Button>
          </div>
        </Dialog>
      )}
      {revisionLeave && (
        <Dialog title="这一章的修改还没提交" close={() => setRevisionLeave(null)}>
          <p>改动已经存在这台设备上，回到这一章可以接着改；不提交就不会替换正文。</p>
          <div className="dialog-actions">
            <Button kind="primary" onClick={() => { const target = revisionLeave; setRevisionLeave(null); router.push(target); }}>先离开</Button>
            <Button kind="text" onClick={() => setRevisionLeave(null)}>留在这里</Button>
          </div>
        </Dialog>
      )}
      {confirmUnstoredLogout && (
        <Dialog title="退出会丢失这条记录" close={() => setConfirmUnstoredLogout(false)}>
          <p>这个浏览器没能保存这条已失效的待补记记录。退出后它会丢失；服务器上的正文和决定不会改变。</p>
          <div className="dialog-actions">
            <Button kind="danger" onClick={() => { setConfirmUnstoredLogout(false); void performLogout(); }}>仍然退出</Button>
            <Button kind="text" onClick={() => setConfirmUnstoredLogout(false)}>取消</Button>
          </div>
        </Dialog>
      )}
    </div>
  );
}

/** 日间 / 夜间: the moon switches to night, the sun back to day. */
function ThemeSwitch({ theme, toggle, floating = false }: { theme: "day" | "night"; toggle: () => void; floating?: boolean }) {
  const night = theme === "night";
  return (
    <button type="button" className={floating ? "theme-switch floating" : "theme-switch"} aria-label={night ? "切换到日间模式" : "切换到夜间模式"} title={night ? "日间模式" : "夜间模式"} onClick={toggle}>
      {night ? (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><circle cx="10" cy="10" r="4" /><path d="M10 1v2.5M10 16.5V19M1 10h2.5M16.5 10H19M3.6 3.6l1.8 1.8M14.6 14.6l1.8 1.8M3.6 16.4l1.8-1.8M14.6 5.4l1.8-1.8" /></svg>
      ) : (
        <svg width="20" height="20" viewBox="0 0 20 20" fill="currentColor" aria-hidden="true"><path d="M16.5 12.6A7 7 0 0 1 7.4 3.5a7 7 0 1 0 9.1 9.1Z" /></svg>
      )}
    </button>
  );
}
