"use client";

// Small building blocks shared by every page: buttons, dialogs, the 更多 menu and line icons.
import { MouseEventHandler, ReactNode, Ref, useEffect, useRef, useState } from "react";
import { request } from "../api";

export function Button({
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

export function Chevron({ className = "" }: { className?: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" aria-hidden="true">
      <path d="m5.5 7.5 4.5 4.5 4.5-4.5" />
    </svg>
  );
}

export function MoreMenu({ children, danger }: { children: ReactNode; danger?: ReactNode }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const details = menu.current;
    if (!details) return;
    const close = (focusSummary: boolean) => {
      if (!details.open) return;
      details.removeAttribute("open");
      if (focusSummary) details.querySelector("summary")?.focus();
    };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && details.open) { event.stopPropagation(); close(true); } };
    const onPointer = (event: PointerEvent) => { if (!details.contains(event.target as Node)) close(false); };
    details.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => { details.removeEventListener("keydown", onKey); document.removeEventListener("pointerdown", onPointer); };
  }, []);
  return (
    <details className="more-menu" ref={menu}>
      <summary>更多<Chevron className="more-chevron" /></summary>
      {/* Choosing an item closes the menu so it does not stay open behind the dialog it opens. */}
      <div role="menu" aria-label="更多操作" onClick={(event) => { if ((event.target as HTMLElement).closest("button")) event.currentTarget.closest("details")?.removeAttribute("open"); }}>
        {children}
        {danger && <div className="more-menu-danger" role="group" aria-label="危险操作">{danger}</div>}
      </div>
    </details>
  );
}

export function I({ children }: { children: string }) {
  return (
    <span className="icon" aria-hidden="true">
      {children}
    </span>
  );
}

export function Icon({ name, inline = false }: { name: "home" | "library" | "overview" | "outline" | "users" | "world" | "memory" | "pen" | "save" | "play" | "profile" | "security" | "tutorial" | "logout" | "arrow-right" | "external" | "chevron-left" | "chevron-right" | "check-circle" | "text"; inline?: boolean }) {
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
    "arrow-right": <><path d="M5 12h14M13 6l6 6-6 6" /></>,
    external: <><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5" /></>,
    "chevron-left": <><path d="m15 6-6 6 6 6" /></>,
    "chevron-right": <><path d="m9 6 6 6-6 6" /></>,
    "check-circle": <><circle cx="12" cy="12" r="8.5" /><path d="m8.5 12.2 2.4 2.4 4.6-5" /></>,
    text: <><path d="M5 6h14M5 10h14M5 14h14M5 18h9" /></>,
  };
  return <svg className={inline ? "ui-icon ui-icon-inline" : "ui-icon"} viewBox="0 0 24 24" aria-hidden="true">{paths[name]}</svg>;
}

export function Dialog({
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

export type CheckUsage =
  | { account_type: "registered"; check_chars_limit: number; check_chars_used: number; check_chars_remaining: number; imports_limit: number; imports_remaining: number }
  | { account_type: "visitor"; check_chars_per_check: number; checks_limit: number; checks_remaining: number };

/** The rolling 24-hour check allowance. Re-read whenever refreshKey changes (a check ran, a page opened). */
export function useCheckUsage(refreshKey: string) {
  const [usage, setUsage] = useState<CheckUsage | null>(null);
  useEffect(() => {
    let live = true;
    request<CheckUsage>("/account/usage").then((next) => { if (live) setUsage(next); }).catch(() => { if (live) setUsage(null); });
    return () => { live = false; };
  }, [refreshKey]);
  return usage;
}

/** "可检查 54,000 字" for authors, "还可检查 3 次" for visitors. */
export const usageShort = (usage: CheckUsage | null) =>
  !usage ? "" : usage.account_type === "visitor" ? `还可检查 ${usage.checks_remaining} 次` : `可检查 ${usage.check_chars_remaining.toLocaleString("en-US")} 字`;

export const formatCount = (value: number) => value.toLocaleString("en-US");
export const pad2 = (value: number) => String(value).padStart(2, "0");

/** "第十一章：桌上的留白" → "桌上的留白", for places that already show the chapter number. */
export const bareChapterTitle = (title: string) =>
  title.replace(/^\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*[章回节]\s*[:：·.、\-—\s]*/, "").trim() || title.trim();
