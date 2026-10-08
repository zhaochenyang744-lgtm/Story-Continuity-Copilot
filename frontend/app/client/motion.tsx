"use client";

// Motion pieces that need a little script: the rolling counter, the thread from a finding to its
// evidence chapter, and the reading line during a check. The look lives in
// styles/motion.css; every piece here does nothing under prefers-reduced-motion.
import { useEffect, useLayoutEffect, useRef, useState } from "react";

export const reducedMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** A number whose digits roll like a mechanical counter when it changes (never on first show). */
export function Odometer({ value }: { value: number | string }) {
  const text = String(value);
  const [shown, setShown] = useState(text);
  const [from, setFrom] = useState<string | null>(null);
  if (shown !== text) {
    setShown(text);
    setFrom(reducedMotion() ? null : shown);
  }
  const width = Math.max(text.length, from?.length ?? 0);
  const next = text.padStart(width, " ");
  const previous = from?.padStart(width, " ") ?? null;
  // The leftmost changing digit starts last, so it finishes last.
  const last = previous === null ? -1 : [...next].findIndex((digit, index) => previous[index] !== digit);
  return (
    <span className="odo" aria-label={text} role="img">
      {[...next].map((digit, index) => {
        const old = previous?.[index];
        const rolls = previous !== null && old !== digit;
        return (
          <span
            key={`${index}:${rolls ? `${old}${digit}` : digit}`}
            className={rolls ? "odo-col roll" : "odo-col"}
            style={rolls ? { animationDelay: `${(width - 1 - index) * 90}ms` } : undefined}
            onAnimationEnd={index === last ? () => setFrom(null) : undefined}
            aria-hidden="true"
          >
            {rolls && <span>{old === " " ? " " : old}</span>}
            <span>{digit === " " ? " " : digit}</span>
          </span>
        );
      })}
    </span>
  );
}

type Point = { x: number; y: number };
type Thread = { key: string; start: Point; end: Point };

/** 牵线: blue threads from the element `from` points at to each of the `to` elements, drawn over the
    page and kept in place while it scrolls. Elements that are missing or hidden are skipped. */
export function ThreadLayer({ from, to }: { from: string | null; to: string[] }) {
  const [threads, setThreads] = useState<Thread[]>([]);
  const targets = to.join("|");
  useEffect(() => {
    if (!from || !targets || reducedMotion()) return;
    let frame = 0;
    const measure = () => {
      frame = 0;
      const source = document.querySelector<HTMLElement>(from);
      const lines = source ? Array.from(source.getClientRects()) : [];
      if (!lines.length) { setThreads([]); return; }
      // Leave from the left of the sentence's first line, clear of any wrapped line below it.
      const start = { x: Math.min(...lines.map((line) => line.left)) - 8, y: lines[0].top + lines[0].height / 2 };
      const next: Thread[] = [];
      for (const selector of targets.split("|")) {
        const target = document.querySelector<HTMLElement>(selector);
        const rect = target?.getBoundingClientRect();
        if (!target || !rect || !rect.width || target.offsetParent === null) continue;
        next.push({ key: `${from}->${selector}`, start, end: { x: rect.right + 10, y: rect.top + rect.height / 2 } });
      }
      setThreads(next);
    };
    const schedule = () => { if (!frame) frame = requestAnimationFrame(measure); };
    schedule();
    window.addEventListener("scroll", schedule, true);
    window.addEventListener("resize", schedule);
    return () => { cancelAnimationFrame(frame); window.removeEventListener("scroll", schedule, true); window.removeEventListener("resize", schedule); };
  }, [from, targets]);
  const shown = from && targets ? threads.filter((thread) => thread.key.startsWith(`${from}->`)) : [];
  if (!shown.length) return null;
  return (
    <svg className="thread-layer" aria-hidden="true">
      {shown.map(({ key, start, end }) => {
        // The same easy S as the story route's threads: leave level, bend, arrive level.
        const span = Math.max(40, start.x - end.x);
        const d = `M ${start.x} ${start.y} C ${start.x - span * 0.55} ${start.y}, ${end.x + span * 0.45} ${end.y}, ${end.x} ${end.y}`;
        return (
          <g key={key}>
            <circle className="thread-start" cx={start.x} cy={start.y} r={3} />
            <path d={d} pathLength={1} />
            <rect className="thread-end" x={end.x - 4} y={end.y - 4} width={8} height={8} />
          </g>
        );
      })}
    </svg>
  );
}

/** While a check runs: a line that reads down `container`'s paragraphs, pausing on each. */
export function ScanLine({ container }: { container: string }) {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    if (reducedMotion()) return;
    let step = 0;
    const tick = () => {
      const host = document.querySelector<HTMLElement>(container);
      const blocks = host ? Array.from(host.children) as HTMLElement[] : [];
      if (!host || !blocks.length) return;
      const top = host.getBoundingClientRect().top;
      step = step >= blocks.length ? 0 : step + 1;
      const block = blocks[Math.max(0, step - 1)];
      setHeight(step === 0 ? 0 : block.getBoundingClientRect().bottom - top);
    };
    const first = window.setTimeout(tick, 0);
    const timer = window.setInterval(tick, 700);
    return () => { window.clearTimeout(first); window.clearInterval(timer); };
  }, [container]);
  return <div className="scan" style={{ height }} aria-hidden="true"><span className="scan-label">正在对照前文</span></div>;
}

/** True the first time a check's results are shown in this browser session, for a few seconds. */
export function useFirstShow(id: string | null, count: number) {
  const [reveal, setReveal] = useState<string | null>(null);
  useEffect(() => {
    if (!id || !count || reducedMotion()) return;
    const key = `story-continuity:shown:${id}`;
    try { if (sessionStorage.getItem(key)) return; } catch { return; }
    // Marked as seen only when it actually starts, so a re-run effect still shows it once.
    const show = window.setTimeout(() => { try { sessionStorage.setItem(key, "1"); } catch { /* shown anyway */ } setReveal(id); }, 0);
    const hide = window.setTimeout(() => setReveal(null), count * 280 + 1400);
    return () => { window.clearTimeout(show); window.clearTimeout(hide); };
  }, [id, count]);
  return reveal === id;
}

// Figures already counted in this visit (survives page switches, which remount the page).
const counted = new Set<string>();

/** 排版: a figure that sets itself the first time it is shown in this visit — it counts up from
    zero while its digits widen from condensed to full width. Later shows are still. */
export function CountUp({ value, id }: { value: number; id: string }) {
  const host = useRef<HTMLSpanElement>(null);
  const live = useRef<HTMLSpanElement>(null);
  const text = formatNumber(value);
  useLayoutEffect(() => {
    const node = live.current, wrap = host.current;
    if (!node || !wrap) return;
    if (counted.has(id) || reducedMotion() || value === 0) { node.textContent = text; return; }
    let frame = 0;
    const start = performance.now();
    node.textContent = "0";
    wrap.classList.add("run");
    const tick = (now: number) => {
      const t = Math.min(1, (now - start) / 900);
      node.textContent = formatNumber(Math.round(value * (1 - Math.pow(1 - t, 3))));
      if (t < 1) frame = requestAnimationFrame(tick);
      else { counted.add(id); wrap.classList.remove("run"); }
    };
    frame = requestAnimationFrame(tick);
    return () => { cancelAnimationFrame(frame); node.textContent = text; wrap.classList.remove("run"); };
  }, [id, value, text]);
  return (
    <span ref={host} className="count">
      <span className="count-ghost" aria-hidden="true">{text}</span>
      <span ref={live} className="count-live" aria-hidden="true">{text}</span>
      <span className="sr-only">{text}</span>
    </span>
  );
}
const formatNumber = (value: number) => value.toLocaleString("en-US");
