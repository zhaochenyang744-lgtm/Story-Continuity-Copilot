"use client";

import { useEffect, useRef, useState } from "react";
import { Button, Num } from "../ui";
import type { TutorialStep } from "./use-project";

const reduced = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** The sample work's five-step tour, as a black bar above the page. */
export function TutorialBar({ projectId, tab, step, restored, readOnly, busy, finish, requestGuidance, go }: {
  projectId: string;
  tab: string;
  step: TutorialStep;
  restored: boolean;
  readOnly: boolean;
  busy: boolean;
  finish: (outcome: "complete" | "skip") => Promise<void>;
  requestGuidance: () => void;
  go: (href: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const copy = {
    1: { title: "在资料里找到一条事实", task: "打开资料，找一条已经确认的事实，看它出自哪一章。", action: tab === "memory" ? "指给我看" : "去资料" },
    2: { title: "去写作页看检查结果", task: "出处看过了。接下来到写作页，找到第一条检查结果。", action: "去写作页" },
    3: { title: "对照草稿和前文", task: "在检查结果里点开一条，先看它属于哪种问题，再对照草稿、前文依据和判断理由。", action: tab === "workspace" ? "指给我看" : "回到写作页" },
    4: { title: "作出一次决定", task: readOnly ? "手机上可以浏览完整依据；请在电脑上作出决定。" : "如果这一条已经处理过，复习一下依据和结果再继续；否则选择采用改法、改正文、是有意的或不是问题。", action: readOnly ? "查看提示" : "指给我看" },
    5: { title: "决定记下了", task: "这一条已经处理。结束导览后，回到首页导入你自己的作品。", action: "完成导览" },
  }[step];
  const afterScroll = () => {
    if (reduced()) { window.setTimeout(requestGuidance, 0); return; }
    let done = false, settle = 0;
    const finishWait = () => { if (done) return; done = true; window.removeEventListener("scroll", onScroll, true); window.clearTimeout(settle); window.clearTimeout(fallback); requestGuidance(); };
    const onScroll = () => { window.clearTimeout(settle); settle = window.setTimeout(finishWait, 240); };
    window.addEventListener("scroll", onScroll, true);
    onScroll();
    const fallback = window.setTimeout(finishWait, 2000);
  };
  const locate = (selector: string) => {
    const target = document.querySelector<HTMLElement>(selector);
    afterScroll();
    target?.scrollIntoView({ block: "center", behavior: reduced() ? "auto" : "smooth" });
  };
  const navigate = (href: string, selector?: string) => {
    go(href);
    window.setTimeout(() => {
      const target = selector ? document.querySelector<HTMLElement>(selector) : null;
      target?.scrollIntoView({ block: "center", behavior: "auto" });
      window.setTimeout(requestGuidance, target ? 100 : 400);
    }, 500);
  };
  const act = () => {
    if (step === 1) { if (tab === "memory") locate(".memory-source:not(:disabled)"); else navigate(`/projects/${projectId}/memory`); return; }
    if (step === 2) { navigate(`/projects/${projectId}/workspace`, ".issue-row"); return; }
    if (step === 3) { if (tab === "workspace") locate(".issue-row"); else navigate(`/projects/${projectId}/workspace`); return; }
    if (step === 4) { locate(readOnly ? ".tutorial-mobile-decision-note" : ".tutorial-decision-review, .author-decision, .issue-row"); return; }
    void finish("complete");
  };
  return (
    <section className={`tour${open ? " open" : ""}`} aria-label="导览">
      <div className="tour-progress">
        <span className="label tour-count">导览 {step} / 5</span>
        <ol aria-label="五步导览">
          {([1, 2, 3, 4, 5] as TutorialStep[]).map((item) => (
            <li key={item} className={item === step ? "current" : item < step ? "done" : undefined} aria-current={item === step ? "step" : undefined}>{item < step ? "✓" : item}</li>
          ))}
        </ol>
      </div>
      <div className="tour-copy">
        <strong>{copy.title}</strong>
        {restored && <span>已回到第 {step} 步，可以从这里继续。</span>}
        {open && <span>{copy.task} 示例作品不计入你的作品，也不计入额度。</span>}
      </div>
      <div className="tour-actions">
        <button type="button" className="tour-link" aria-expanded={open} onClick={() => setOpen((value) => !value)}>{open ? "收起" : "这一步做什么"}</button>
        {step === 5
          ? <button type="button" className="tour-link" disabled={busy} onClick={() => go("/")}>稍后再说</button>
          : <button type="button" className="tour-link" disabled={busy} onClick={() => void finish("skip")}>跳过导览</button>}
        <Button kind="primary" className="tutorial-primary-action" disabled={busy} onClick={act}>{copy.action}</Button>
      </div>
    </section>
  );
}

type Target = { element: HTMLElement; key: string; message: string };
const inView = (element: HTMLElement) => {
  const rect = element.getBoundingClientRect();
  return rect.width > 0 && rect.height > 0 && rect.bottom > 0 && rect.top < window.innerHeight && rect.right > 0 && rect.left < document.documentElement.clientWidth;
};
function resolveTarget({ evidenceOpen, readOnly, sourceOpen, step, tab }: { evidenceOpen: boolean; readOnly: boolean; sourceOpen: boolean; step: TutorialStep; tab: string }): Target | null {
  if (sourceOpen) {
    const close = document.querySelector<HTMLElement>(".layer-drawer .close");
    return close ? { element: close, key: "source-close", message: "看完出处后，关掉它继续" } : null;
  }
  const primary = document.querySelector<HTMLElement>(".tutorial-primary-action:not(:disabled)");
  if (step === 1) {
    if (tab !== "memory") return primary ? { element: primary, key: "memory-navigation", message: "下一步：打开资料" } : null;
    const source = document.querySelector<HTMLElement>(".memory-source:not(:disabled)");
    if (source && inView(source)) return { element: source, key: "memory-source", message: "下一步：看这条事实出自哪一章" };
    return primary ? { element: primary, key: "memory-locate", message: "点这里找到下一步" } : null;
  }
  if (step === 2) return primary ? { element: primary, key: "workspace-navigation", message: "下一步：去写作页" } : null;
  if (step === 3) {
    if (tab !== "workspace") return primary ? { element: primary, key: "workspace-return", message: "下一步：回到写作页" } : null;
    // With a finding already open, the next click is its 「查看完整依据」, not the row (which would close it).
    const gate = evidenceOpen ? document.querySelector<HTMLElement>(".finding-gate .tutorial-primary-action:not(:disabled)") : null;
    if (gate) return { element: gate, key: "evidence-gate", message: "下一步：查看这一条的完整依据" };
    const issue = document.querySelector<HTMLElement>(".issue-row");
    if (issue && inView(issue)) return { element: issue, key: "reviewable-issue", message: "下一步：点开第一条检查结果" };
    return primary ? { element: primary, key: "issue-locate", message: "点这里找到下一步" } : null;
  }
  if (step === 4) {
    if (evidenceOpen) {
      const decision = document.querySelector<HTMLElement>(readOnly ? ".tutorial-mobile-decision-note" : ".author-decision");
      return decision ? { element: decision, key: readOnly ? "mobile-decision-note" : "author-decision", message: readOnly ? "请在电脑上继续作出决定" : "选一种处理方式，导览不会替你决定" } : null;
    }
    const issue = document.querySelector<HTMLElement>(".issue-row");
    return issue ? { element: issue, key: "decision-return", message: "下一步：重新点开这一条" } : primary ? { element: primary, key: "decision-locate", message: "点这里找到下一步" } : null;
  }
  return primary ? { element: primary, key: "tutorial-complete", message: "完成导览后就可以导入自己的作品" } : null;
}

/** A small black pointer next to the next thing to click. Appears on request, or after 12 s idle. */
export function TutorialGuidance({ projectId, step, tab, readOnly, busy, evidenceOpen, sourceOpen, requestId }: {
  projectId: string;
  step: TutorialStep;
  tab: string;
  readOnly: boolean;
  busy: boolean;
  evidenceOpen: boolean;
  sourceOpen: boolean;
  requestId: number;
}) {
  const [hint, setHint] = useState<{ left: number; top: number; width: number; placement: "above" | "below"; message: string } | null>(null);
  const [activity, setActivity] = useState(0);
  const handled = useRef(0);
  const pulsed = useRef(new Set<string>());
  const grace = useRef(0);
  const hintId = "tutorial-guidance-hint";
  const contextKey = `${projectId}:${step}:${tab}:${sourceOpen}:${evidenceOpen}:${readOnly}`;
  useEffect(() => {
    const mark = (event: Event) => {
      if (event.type === "scroll" && window.performance.now() < grace.current) return;
      setActivity((value) => value + 1);
    };
    const events = ["click", "keydown", "touchstart", "wheel", "scroll"];
    events.forEach((name) => window.addEventListener(name, mark, { capture: true, passive: true }));
    return () => events.forEach((name) => window.removeEventListener(name, mark, true));
  }, []);
  useEffect(() => {
    if (requestId > handled.current) grace.current = window.performance.now() + 1200;
    let idle: ReturnType<typeof setTimeout> | null = null;
    let ready = false;
    let attached: HTMLElement | null = null;
    let previous: string | null = null;
    const detach = () => {
      if (!attached) return;
      attached.classList.remove("tutorial-guidance-target", "is-pulsing");
      attached.removeAttribute("data-tutorial-guidance-target");
      attached.removeAttribute("data-tutorial-guidance-key");
      if (previous === null) attached.removeAttribute("aria-describedby"); else attached.setAttribute("aria-describedby", previous);
      attached = null;
      previous = null;
    };
    const place = (target: HTMLElement, message: string) => {
      const rect = target.getBoundingClientRect();
      const viewport = document.documentElement.clientWidth;
      const width = Math.min(272, Math.max(180, viewport - 32));
      const left = Math.min(viewport - width - 16, Math.max(16, rect.left + rect.width / 2 - width / 2));
      const placement = rect.bottom + 92 > window.innerHeight && rect.top > 100 ? "above" : "below";
      setHint({ left, message, placement, top: placement === "above" ? rect.top - 10 : rect.bottom + 10, width });
    };
    const attach = (target: Target, automatic: boolean) => {
      detach();
      attached = target.element;
      previous = attached.getAttribute("aria-describedby");
      attached.setAttribute("aria-describedby", [...new Set(`${previous ?? ""} ${hintId}`.trim().split(/\s+/))].join(" "));
      attached.setAttribute("data-tutorial-guidance-target", "true");
      attached.setAttribute("data-tutorial-guidance-key", target.key);
      attached.classList.add("tutorial-guidance-target");
      const pulseKey = `${projectId}:${step}`;
      if (automatic && !pulsed.current.has(pulseKey)) { pulsed.current.add(pulseKey); attached.classList.add("is-pulsing"); }
      place(attached, target.message);
    };
    const resolve = () => resolveTarget({ evidenceOpen, readOnly, sourceOpen, step, tab });
    const attempt = () => {
      if (!ready || busy || attached || idle) return;
      const target = resolve();
      if (!target) return;
      if (requestId > handled.current) { handled.current = requestId; attach(target, false); return; }
      idle = setTimeout(() => { idle = null; const current = resolve(); if (current) attach(current, true); }, 12_000);
    };
    const init = window.setTimeout(() => { setHint(null); ready = true; if (!busy) attempt(); }, 0);
    const observer = new MutationObserver(attempt);
    observer.observe(document.body, { childList: true, subtree: true });
    const reposition = () => { if (!attached) return; const current = resolve(); if (current?.element === attached) place(attached, current.message); };
    window.addEventListener("resize", reposition);
    return () => { if (idle) clearTimeout(idle); window.clearTimeout(init); observer.disconnect(); window.removeEventListener("resize", reposition); detach(); };
  }, [activity, busy, contextKey, evidenceOpen, projectId, readOnly, requestId, sourceOpen, step, tab]);
  if (!hint) return null;
  return <div id={hintId} className={`tour-hint ${hint.placement}`} role="status" aria-live="polite" style={{ left: hint.left, top: hint.top, width: hint.width }}><Num className="tour-hint-step">{step}</Num>{hint.message}</div>;
}
