"use client";

import { type CSSProperties, useEffect, useRef, useState } from "react";
import { type FindingTone } from "../labels";
import { reducedMotion } from "../motion";
import { bareChapterTitle, pad2 } from "../ui";

export type RouteChapter = {
  number: number;
  title: string;
  status: "checked" | "basis_changed" | "edited_unchecked" | "unchecked" | "empty";
  findings: ("high" | "mid")[];
};
export type RouteThread = { id: string; title: string; planted: number };
export type RoutePlan = { id: string; title: string; chapter: number; considering: boolean };

const INK = "var(--c-ink)";
const GROUND = "var(--c-ground)";
const BLUE = "var(--c-blue)";
const BLUE_TEXT = "var(--c-blue-text)";
const MUTED = "var(--c-muted)";
const LANE = 52;
const MAX_LANES = 6;
// Routes already drawn in this visit: the chart draws itself once, later visits show it at rest.
const drawn = new Set<string>();

/**
 * 故事航线: the written chapters as stations on one line (filled = checked), the draft in blue with
 * its open findings stacked above it, every unresolved foreshadowing thread as a line branching off
 * the chapter that planted it and running on past the draft, and the plans for coming chapters as
 * diamonds in the shaded "接下来" stretch (solid = 已定, dashed = 考虑中).
 */
export function StoryRoute({ id, chapters, draft, threads, plans, onOpen }: {
  /** the work; the chart draws itself the first time it is shown for it in this visit */
  id: string;
  chapters: RouteChapter[];
  draft: { number: number; title: string; findings: FindingTone[] } | null;
  threads: RouteThread[];
  plans: RoutePlan[];
  /** a chapter's station was chosen (the draft's too, with `draft` true) */
  onOpen: (number: number, draft: boolean) => void;
}) {
  const scroller = useRef<HTMLDivElement>(null);
  const [available, setAvailable] = useState(1180);
  const [drawing] = useState(() => !drawn.has(id) && !reducedMotion());
  // Pointing at a chapter: which threads were already open by then.
  const [at, setAt] = useState<number | null>(null);
  useEffect(() => {
    if (!drawing) return;
    const timer = window.setTimeout(() => drawn.add(id), 1600);
    return () => window.clearTimeout(timer);
  }, [drawing, id]);
  useEffect(() => {
    const el = scroller.current;
    if (!el) return;
    const measure = () => setAvailable(Math.max(320, el.clientWidth));
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, []);
  const draftNumber = draft?.number ?? (chapters.at(-1)?.number ?? 0) + 1;
  const lastPlan = Math.max(0, ...plans.map((plan) => plan.chapter));
  const lastNumber = Math.max(draftNumber + 1, lastPlan, chapters.at(-1)?.number ?? 0);
  const firstNumber = Math.min(1, chapters[0]?.number ?? 1);
  const span = Math.max(1, lastNumber - firstNumber);
  const left = 40;
  const right = 44;
  const step = Math.max(30, Math.min(120, (available - left - right) / span));
  const width = Math.round(left + span * step + right);
  const x = (n: number) => left + (n - firstNumber) * step;
  const shown = threads.filter((thread) => thread.planted < draftNumber).sort((a, b) => a.planted - b.planted).slice(0, MAX_LANES);
  const hiddenThreads = threads.length - shown.length;
  const top = 64;
  const baseline = top + shown.length * LANE + 92;
  const height = baseline + 92;
  const futureStart = x(draftNumber) + step / 2;
  const end = width - 24;
  const titleChars = Math.max(0, Math.floor((step - 8) / 13.5));
  const labelEvery = step >= 44 ? 1 : step >= 34 ? 2 : 5;
  const showNumber = (n: number) => n === draftNumber || n === firstNumber || (n - firstNumber) % labelEvery === 0;
  const clip = (text: string) => (text.length > titleChars ? `${text.slice(0, Math.max(1, titleChars - 1))}…` : text);
  const plansByChapter = new Map<number, RoutePlan[]>();
  for (const plan of plans) if (plan.chapter > draftNumber || (plan.chapter === draftNumber && !draft)) plansByChapter.set(plan.chapter, [...(plansByChapter.get(plan.chapter) ?? []), plan]);
  const chapterByNumber = new Map(chapters.map((chapter) => [chapter.number, chapter]));
  const checked = chapters.filter((chapter) => chapter.status === "checked").length;

  useEffect(() => {
    const el = scroller.current;
    if (el && el.scrollWidth > el.clientWidth) el.scrollLeft = Math.max(0, futureStart - el.clientWidth + 260);
  }, [futureStart]);

  const summary = [
    `共 ${chapters.length} 章，已检查 ${checked} 章`,
    draft ? `第 ${draft.number} 章草稿${draft.findings.length ? `有 ${draft.findings.length} 处待看` : ""}` : "",
    threads.length ? `${threads.length} 条伏笔未回收` : "",
    plansByChapter.size ? `接下来 ${[...plansByChapter.values()].flat().length} 条计划` : "",
  ].filter(Boolean).join("；");

  return (
    <div className="route-scroll" ref={scroller}>
      <div className="route-frame" style={{ width, height }} onMouseLeave={() => setAt(null)}>
      <svg className={`route${drawing ? " drawing" : ""}${at !== null ? " scrubbing" : ""}`} viewBox={`0 0 ${width} ${height}`} width={width} height={height} role="img" aria-label={`故事航线：${summary}`}>
        <rect x={futureStart} y={10} width={Math.max(0, width - futureStart)} height={height - 20} fill="var(--c-blue-tint)" />
        <text x={futureStart + 12} y={34} className="route-mono" fill={BLUE_TEXT}>接下来</text>
        {at !== null && (
          <g className="route-cursor" aria-hidden="true">
            <line x1={x(at)} y1={36} x2={x(at)} y2={baseline - 14} />
            <text x={x(at) + 8} y={30} className="route-mono">第 {at} 章时 · {shown.filter((thread) => thread.planted <= at).length} 条伏笔悬着</text>
          </g>
        )}

        {shown.map((thread, index) => {
          const y = top + index * LANE;
          const xp = x(thread.planted);
          // The preview's sweep: rise straight for the first third, then bend over a run of about
          // 0.8× the height, arriving level on the lane (capped so it never reaches the future band).
          const rise = baseline - 8 - y;
          const bend = Math.min(rise * 0.8, (futureStart - xp) * 0.8);
          const passed = Math.max(0, draftNumber - thread.planted);
          return (
            <g key={thread.id} data-testid={`route-thread-${thread.id}`} className={`route-thread-line${at !== null ? (thread.planted <= at ? " lit" : " dim") : ""}`} style={{ "--i": index } as CSSProperties}>
              <path d={`M ${xp} ${baseline - 8} C ${xp} ${y + rise / 3}, ${xp + bend * 0.37} ${y}, ${xp + bend} ${y} L ${futureStart} ${y}`} fill="none" stroke={INK} strokeWidth="2" />
              <path className="route-flow" d={`M ${futureStart} ${y} L ${end - 7} ${y}`} fill="none" stroke={INK} strokeWidth="2" strokeDasharray="5 6" />
              <rect x={end - 7} y={y - 7} width="14" height="14" fill={GROUND} stroke={INK} strokeWidth="2" />
              <text x={xp + bend + 8} y={y - 12} className="route-thread route-thread-label">
                <tspan className="route-thread-title">{thread.title}</tspan>
                <tspan dx="12" className="route-mono" fill={MUTED}>第 {thread.planted} 章埋下 · 已过 {passed} 章</tspan>
              </text>
            </g>
          );
        })}
        {hiddenThreads > 0 && <text x={left} y={top - 26} className="route-mono" fill={MUTED}>另有 {hiddenThreads} 条伏笔未画出，见资料 · 伏笔</text>}

        <line x1={x(firstNumber)} y1={baseline} x2={x(draftNumber)} y2={baseline} stroke={INK} strokeWidth="3" />
        <line x1={x(draftNumber)} y1={baseline} x2={end} y2={baseline} stroke={INK} strokeWidth="3" strokeDasharray="6 6" />

        {Array.from({ length: lastNumber - firstNumber + 1 }, (_, i) => firstNumber + i).map((n) => {
          const cx = x(n);
          const chapter = chapterByNumber.get(n);
          const isDraft = Boolean(draft) && n === draftNumber;
          const future = plansByChapter.get(n);
          const future_ = n > draftNumber || (n === draftNumber && !draft);
          const label = isDraft ? draft!.title : chapter ? chapter.title : future ? future[0].title : "";
          const sub = isDraft
            ? `草稿${draft!.findings.length ? ` · ${draft!.findings.length} 处` : ""}`
            : chapter?.findings.length ? `${chapter.findings.length} 处`
              : future?.every((plan) => plan.considering) ? "考虑中"
                : future && future.length > 1 ? `${future.length} 条计划` : "";
          return (
            <g key={n}>
              {chapter && (
                <rect x={cx - 7} y={baseline - 7} width="14" height="14" fill={chapter.status === "checked" ? INK : GROUND} stroke={INK} strokeWidth="2">
                  <title>{`第 ${n} 章 · ${bareChapterTitle(chapter.title)} · ${chapter.status === "checked" ? "已检查" : chapter.status === "unchecked" || chapter.status === "empty" ? "未检查" : "改过，请再检查一次"}`}</title>
                </rect>
              )}
              {chapter && (chapter.status === "basis_changed" || chapter.status === "edited_unchecked") && <path d={`M ${cx - 6} ${baseline + 6} L ${cx + 6} ${baseline - 6} L ${cx + 6} ${baseline + 6} Z`} fill={INK} />}
              {chapter?.findings.slice(0, 3).map((tone, index) => (
                <rect key={index} x={cx - 6} y={baseline - 32 - index * 15} width="12" height="12" fill={tone === "high" ? "var(--c-red)" : "var(--c-yellow)"} />
              ))}
              {isDraft && (
                <>
                  <rect x={cx - 10} y={baseline - 10} width="20" height="20" fill={BLUE}><title>{`第 ${n} 章草稿 · ${bareChapterTitle(draft!.title)}`}</title></rect>
                  {draft!.findings.slice(0, 5).map((tone, index) => {
                    const y = baseline - 34 - index * 15;
                    if (tone === "gap") return <rect key={index} x={cx - 5} y={y + 1} width="10" height="10" fill="none" stroke={INK} strokeWidth="1.5" strokeDasharray="2 2" />;
                    if (tone === "state") return <rect key={index} x={cx - 5} y={y + 1} width="10" height="10" fill="var(--c-blue-tint)" stroke={BLUE} strokeWidth="1.5" />;
                    return <rect key={index} x={cx - 6} y={y} width="12" height="12" fill={tone === "high" ? "var(--c-red)" : "var(--c-yellow)"} />;
                  })}
                </>
              )}
              {future && future_ && (
                <rect x={cx - 7} y={baseline - 7} width="14" height="14" transform={`rotate(45 ${cx} ${baseline})`} fill={future.every((plan) => plan.considering) ? GROUND : BLUE} stroke={BLUE} strokeWidth="2" strokeDasharray={future.every((plan) => plan.considering) ? "3 2" : undefined}>
                  <title>{future.map((plan) => `第 ${n} 章 · ${plan.title}${plan.considering ? "（考虑中）" : ""}`).join("\n")}</title>
                </rect>
              )}
              {showNumber(n) && (chapter || isDraft || future) && (
                <text x={cx} y={baseline + 40} textAnchor="middle" className="route-num" fill={n >= draftNumber ? BLUE_TEXT : INK}>{pad2(n)}</text>
              )}
              {titleChars >= 3 && label && (
                <text x={cx} y={baseline + 62} textAnchor="middle" className={isDraft ? "route-label current" : "route-label"} fill={n >= draftNumber ? BLUE_TEXT : "var(--c-ink-2)"}>{clip(bareChapterTitle(label))}</text>
              )}
              {sub && <text x={cx} y={baseline + 82} textAnchor="middle" className="route-mono small" fill={MUTED}>{sub}</text>}
            </g>
          );
        })}
      </svg>
      {/* One button over each written chapter and the draft: pointing at it or focusing it shows which threads were open by then, choosing it opens that chapter. */}
      {Array.from({ length: Math.max(0, draftNumber - firstNumber + 1) }, (_, i) => firstNumber + i).map((n) => {
        const chapter = chapterByNumber.get(n);
        const isDraft = Boolean(draft) && n === draftNumber;
        if (!chapter && !isDraft) return null;
        const title = bareChapterTitle(chapter ? chapter.title : draft!.title);
        const tip = chapter ? `第 ${n} 章 · ${title} · ${chapter.status === "checked" ? "已检查" : chapter.status === "unchecked" || chapter.status === "empty" ? "未检查" : "改过，请再检查一次"}` : `第 ${n} 章草稿 · ${title}`;
        return (
          <button key={`point-${n}`} type="button" data-testid={`route-chapter-${n}`} className="route-point" aria-label={title ? `第 ${n} 章 · ${title}` : `第 ${n} 章`} title={tip}
            style={{ left: Math.max(0, x(n) - step / 2), width: step, top: 10, height: height - 20 }}
            onMouseEnter={() => setAt(n)} onFocus={() => setAt(n)} onBlur={() => setAt(null)} onClick={() => onOpen(n, isDraft)} />
        );
      })}
      </div>
    </div>
  );
}

export function RouteLegend() {
  return (
    <ul className="route-legend" aria-label="图例">
      <li><span className="key checked" />已检查</li>
      <li><span className="key unchecked" />未检查</li>
      <li><span className="key changed" />改后未重查</li>
      <li><span className="key draft" />草稿</li>
      <li><span className="key thread" />未回收的伏笔</li>
      <li><span className="key plan" />计划</li>
    </ul>
  );
}
