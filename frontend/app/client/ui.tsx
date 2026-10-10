"use client";

// The 版面 building blocks. Every page is assembled from these; nothing here knows about data.
import { CSSProperties, KeyboardEvent as ReactKeyboardEvent, MouseEventHandler, ReactNode, Ref, useEffect, useRef, useState } from "react";
import { request } from "../api";

type ButtonKind = "primary" | "outline" | "text" | "small" | "danger" | "plain";
export function Button({
  children,
  kind = "outline",
  size,
  className = "",
  disabled,
  pressed,
  current,
  busy,
  label,
  expanded,
  buttonRef,
  title,
  id,
  type = "button",
  onClick,
}: {
  children: ReactNode;
  /** primary: the one blue action; outline: 2px black frame; text: underlined; small: thin frame; danger: destructive. */
  kind?: ButtonKind;
  size?: "lg";
  className?: string;
  disabled?: boolean;
  pressed?: boolean;
  current?: boolean;
  busy?: boolean;
  label?: string;
  expanded?: boolean;
  buttonRef?: Ref<HTMLButtonElement>;
  title?: string;
  id?: string;
  type?: "button" | "submit";
  onClick?: MouseEventHandler<HTMLButtonElement>;
}) {
  return (
    <button
      ref={buttonRef}
      id={id}
      type={type}
      className={`btn btn-${kind}${size ? ` btn-${size}` : ""}${className ? ` ${className}` : ""}`}
      disabled={disabled}
      aria-pressed={pressed}
      aria-current={current ? "page" : undefined}
      aria-busy={busy || undefined}
      aria-label={label}
      aria-expanded={expanded}
      title={title}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

export function Arrow({ size = 18 }: { size?: number }) {
  return (
    <svg className="arrow" width={size} height={size} viewBox="0 0 18 18" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M3 9h12M10 4l5 5-5 5" />
    </svg>
  );
}
export function Chevron({ size = 12 }: { size?: number }) {
  return (
    <svg className="chevron" width={size} height={size} viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true">
      <path d="M2 4l4 4 4-4" />
    </svg>
  );
}

/** How many digits and separators the numerals will show, for the stylesheet to size them to the room
    they have (see --num-digit in tokens.css). Several texts add up: they share one row. */
export function fitVars(...texts: string[]): CSSProperties {
  const joined = texts.join("");
  return { "--digits": joined.replace(/\D/g, "").length, "--commas": joined.replace(/\d/g, "").length } as CSSProperties;
}

/** Big Archivo numerals. `fit` is the number as it is shown: with it, a stylesheet may shrink the numerals to fit their box. */
export function Num({ children, className = "", fit }: { children: ReactNode; className?: string; fit?: string }) {
  return <span className={`num${className ? ` ${className}` : ""}`} style={fit === undefined ? undefined : fitVars(fit)}>{children}</span>;
}

export function Tag({ tone = "line", children }: { tone?: "high" | "mid" | "gap" | "state" | "solid" | "blue" | "line" | "considering"; children: ReactNode }) {
  return <span className={`tag tag-${tone}`}>{children}</span>;
}

/** Page head: a 72px title, one line of context, figures or actions on the right, a 1px rule under it. */
export function PageHead({ title, lede, aside, rule = true }: { title: ReactNode; lede?: ReactNode; aside?: ReactNode; rule?: boolean }) {
  return (
    <header className={`page-head${rule ? "" : " no-rule"}`}>
      <div className="page-head-main">
        <h1>{title}</h1>
        {lede && <p className="page-head-lede">{lede}</p>}
      </div>
      {aside && <div className="page-head-aside">{aside}</div>}
    </header>
  );
}

/** Section head: a 28px title on a 1px rule, a link or count at the right. */
export function SectionHead({ title, id, aside, level = 2, strong = false }: { title: ReactNode; id?: string; aside?: ReactNode; level?: 2 | 3; strong?: boolean }) {
  const Heading = level === 2 ? "h2" : "h3";
  return (
    <div className={`section-head${strong ? " strong" : ""}`}>
      <Heading id={id}>{title}</Heading>
      {aside && <div className="section-head-aside">{aside}</div>}
    </div>
  );
}

/** Black-fill tabs with a count in Archivo, on a 2px rule. */
export function Tabs<T extends string>({ items, value, onChange, label, size = "lg", trailing }: {
  items: { id: T; label: string; count?: number | string }[];
  value: T;
  onChange: (next: T) => void;
  label: string;
  size?: "lg" | "md";
  trailing?: ReactNode;
}) {
  return (
    <div className={`tabs tabs-${size}`}>
      <nav aria-label={label}>
        {items.map((item) => (
          <button key={item.id} type="button" className="tab" aria-current={item.id === value ? "page" : undefined} onClick={() => onChange(item.id)}>
            <span>{item.label}</span>
            {item.count !== undefined && item.count !== "" && <span className="num tab-count">{item.count}</span>}
          </button>
        ))}
      </nav>
      {trailing && <div className="tabs-trailing">{trailing}</div>}
    </div>
  );
}

/** Outlined filter chips; the chosen one is filled black. */
export function Chips<T extends string>({ items, value, onChange, label }: { items: { id: T; label: string; count?: number }[]; value: T; onChange: (next: T) => void; label: string }) {
  return (
    <div className="chips" role="group" aria-label={label}>
      {items.map((item) => (
        <button key={item.id} type="button" className="chip" aria-pressed={item.id === value} onClick={() => onChange(item.id)}>
          {item.label}{item.count !== undefined ? ` ${item.count}` : ""}
        </button>
      ))}
    </div>
  );
}

export function Note({ tone = "info", children, role }: { tone?: "info" | "warn" | "error" | "ok"; children: ReactNode; role?: "status" | "alert" | "note" }) {
  return <div className={`note note-${tone}`} role={role ?? (tone === "error" ? "alert" : "status")}>{children}</div>;
}

export function useScrollLock() {
  useEffect(() => {
    const root = document.documentElement;
    const previous = root.style.overflow;
    const padding = root.style.paddingRight;
    const scrollbar = Math.max(0, window.innerWidth - root.clientWidth);
    root.style.overflow = "hidden";
    if (scrollbar > 0) root.style.paddingRight = `${scrollbar}px`;
    return () => { root.style.overflow = previous; root.style.paddingRight = padding; };
  }, []);
}

/** The button that opened the menu this control sits in (a details menu's summary, or the account menu's button). */
function menuButtonOf(element: HTMLElement): HTMLElement | null {
  const details = element.closest("details");
  if (details?.classList.contains("menu")) return details.querySelector<HTMLElement>("summary");
  return element.closest('[role="menu"]')?.parentElement?.querySelector<HTMLElement>('[aria-haspopup="menu"]') ?? null;
}
// What last had focus outside any dialog, noted as it happens: by the time a dialog is drawn, the menu item
// that opened it may already be closed or gone.
let lastFocus: { element: HTMLElement; menuButton: HTMLElement | null } | null = null;
if (typeof document !== "undefined") document.addEventListener("focusin", (event) => {
  const target = event.target;
  if (target instanceof HTMLElement && !target.closest('[role="dialog"]')) lastFocus = { element: target, menuButton: menuButtonOf(target) };
});
/** Gives focus back to what had it when the dialog opened; if that is gone or hidden, to the button of the menu it was in. */
function restoreFocus(from: typeof lastFocus) {
  for (const element of [from?.element, from?.menuButton]) {
    if (!element?.isConnected) continue;
    element.focus();
    if (document.activeElement === element) return;
  }
}

/** Keeps Tab inside a dialog, closes it on Escape, and gives focus back when it closes (a dialog and a drawer alike). */
export function useFocusTrap<T extends HTMLElement>(close: () => void, closeDisabled = false) {
  const ref = useRef<T>(null);
  const [from] = useState(() => lastFocus);
  const giveBack = useRef<number | undefined>(undefined);
  useEffect(() => {
    // A remount that follows straight after a cleanup (development's strict mode does this) must not have focus taken from it.
    window.clearTimeout(giveBack.current);
    const first = ref.current?.querySelector<HTMLElement>("[data-autofocus]") ?? ref.current?.querySelector<HTMLElement>('input:not([disabled]), textarea:not([disabled]), select:not([disabled]), button:not([disabled])');
    first?.focus();
    return () => { giveBack.current = window.setTimeout(() => restoreFocus(from), 0); };
  }, [from]);
  const onKeyDown = (event: ReactKeyboardEvent<HTMLElement>) => {
    if (event.key === "Escape") {
      event.preventDefault();
      event.stopPropagation();
      if (!closeDisabled) close();
      return;
    }
    if (event.key !== "Tab") return;
    const focusable = Array.from(ref.current?.querySelectorAll<HTMLElement>('button:not([disabled]), a[href], input:not([disabled]), select:not([disabled]), textarea:not([disabled]), details > summary, [tabindex]:not([tabindex="-1"])') ?? []);
    const first = focusable[0], last = focusable[focusable.length - 1];
    if (!first || !last) return;
    if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
    else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
  };
  return { ref, onKeyDown };
}

/** A centred modal: black frame, offset shadow. */
export function Dialog({ title, children, close, closeDisabled = false, wide = false, kicker }: { title: string; children: ReactNode; close: () => void; closeDisabled?: boolean; wide?: boolean; kicker?: string }) {
  useScrollLock();
  const { ref, onKeyDown } = useFocusTrap<HTMLElement>(close, closeDisabled);
  return (
    <div className="layer" role="presentation" data-testid="dialog-overlay">
      <section ref={ref} className={`dialog${wide ? " wide" : ""}`} role="dialog" aria-modal="true" aria-label={title} onKeyDown={onKeyDown}>
        <header className="dialog-head">
          <div>
            {kicker && <p className="label">{kicker}</p>}
            <h2>{title}</h2>
          </div>
          <button type="button" className="dialog-close" disabled={closeDisabled} onClick={close} aria-label="关闭">×</button>
        </header>
        <div className="dialog-body">{children}</div>
      </section>
    </div>
  );
}

/** A right-hand panel over the page, used for 原文出处. */
export function Drawer({ title, kicker, children, close }: { title: string; kicker?: string; children: ReactNode; close: () => void }) {
  useScrollLock();
  const { ref, onKeyDown } = useFocusTrap<HTMLElement>(close);
  return (
    <div className="layer layer-drawer" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) close(); }}>
      <aside ref={ref} className="drawer" role="dialog" aria-modal="true" aria-label={title} onKeyDown={onKeyDown}>
        <header className="dialog-head">
          <div>
            {kicker && <p className="label">{kicker}</p>}
            <h2>{title}</h2>
          </div>
          <button type="button" className="dialog-close close" onClick={close} aria-label="关闭" data-autofocus>×</button>
        </header>
        <div className="drawer-body">{children}</div>
      </aside>
    </div>
  );
}

/** 更多: a small outlined button that opens a list of actions; dangerous ones sit below a rule. */
export function Menu({ children, danger, label = "更多", buttonLabel }: { children: ReactNode; danger?: ReactNode; label?: string; buttonLabel?: string }) {
  const menu = useRef<HTMLDetailsElement>(null);
  useEffect(() => {
    const details = menu.current;
    if (!details) return;
    const close = (focus: boolean) => { if (!details.open) return; details.removeAttribute("open"); if (focus) details.querySelector("summary")?.focus(); };
    const onKey = (event: KeyboardEvent) => { if (event.key === "Escape" && details.open) { event.stopPropagation(); close(true); } };
    const onPointer = (event: PointerEvent) => { if (!details.contains(event.target as Node)) close(false); };
    details.addEventListener("keydown", onKey);
    document.addEventListener("pointerdown", onPointer);
    return () => { details.removeEventListener("keydown", onKey); document.removeEventListener("pointerdown", onPointer); };
  }, []);
  return (
    <details className="menu" ref={menu}>
      <summary aria-label={buttonLabel}>{label}<Chevron size={10} /></summary>
      <div className="menu-list" role="menu" onClick={(event) => { if ((event.target as HTMLElement).closest("button")) event.currentTarget.closest("details")?.removeAttribute("open"); }}>
        {children}
        {danger && <div className="menu-danger">{danger}</div>}
      </div>
    </details>
  );
}

export type CheckUsage =
  | { account_type: "registered"; check_chars_limit: number; check_chars_used: number; check_chars_remaining: number; imports_limit: number; imports_remaining: number }
  | { account_type: "visitor"; check_chars_per_check: number; checks_limit: number; checks_remaining: number };

/** The rolling 24-hour check allowance, re-read whenever refreshKey changes. */
export function useUsage(refreshKey: string) {
  const [usage, setUsage] = useState<CheckUsage | null>(null);
  useEffect(() => {
    if (!refreshKey) return;
    let live = true;
    request<CheckUsage>("/account/usage").then((next) => { if (live) setUsage(next); }).catch(() => { if (live) setUsage(null); });
    return () => { live = false; };
  }, [refreshKey]);
  return usage;
}
export const usageShort = (usage: CheckUsage | null) =>
  !usage ? "" : usage.account_type === "visitor" ? `还可检查 ${usage.checks_remaining} 次` : `可检查 ${usage.check_chars_remaining.toLocaleString("en-US")} 字`;

export const formatCount = (value: number) => value.toLocaleString("en-US");
export const pad2 = (value: number) => String(value).padStart(2, "0");
export const writtenChars = (text: string) => text.replace(/\s+/g, "").length;
export const clip = (text: string, max: number) => (text.length > max ? `${text.slice(0, max - 1)}…` : text);
/** "第 11 章 · 桌上的留白", or just "第 11 章" when the title is empty or only repeats the chapter number. */
export const chapterHeading = (number: number, title: string) => {
  const name = title.replace(/^\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*[章回节]\s*[:：·.、\-—\s]*/, "").trim();
  return name ? `第 ${number} 章 · ${name}` : `第 ${number} 章`;
};
/** "第十一章：桌上的留白" → "桌上的留白", for places that already show the chapter number. */
export const bareChapterTitle = (title: string) =>
  title.replace(/^\s*第\s*[0-9零〇一二三四五六七八九十百千两]+\s*[章回节]\s*[:：·.、\-—\s]*/, "").trim() || title.trim();
