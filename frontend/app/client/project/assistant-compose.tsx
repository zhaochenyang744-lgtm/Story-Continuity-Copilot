"use client";

// The box the author writes in: one frame with the context tags inside at the top, the text, and a bar below it.
// The bar has 「＋」 (add a chapter, a person or a finding to this question) and the mode (自动 / 问作品 / 写前回顾 / 查前文矛盾 / 改资料;
// 自动 lets the assistant judge which one the sentence asks for) on the left, the cost and one send square on the right; while the assistant works the square is a stop button.
import { type KeyboardEvent as ReactKeyboardEvent, type RefObject, useEffect, useLayoutEffect, useRef, useState } from "react";
import { chapterHeading } from "../ui";

export type ComposeChip = {
  key: string;
  label: string;
  /** the author's own words from the text, set in the serif face */
  quote?: boolean;
  /** Shown but not sent with this question: greyed and struck through, with `note` beside it. */
  muted?: boolean;
  note?: string;
  drop: () => void;
};
export type Mode = "auto" | "ask" | "recap" | "check" | "change";
export const MODE_LABEL: Record<Mode, string> = { auto: "自动", ask: "问作品", recap: "写前回顾", check: "查前文矛盾", change: "改资料" };
/** One line under each use in the menu: what choosing it does. */
export const MODE_HINT: Record<Mode, string> = {
  auto: "由助手判断这句话要做什么",
  ask: "查正文和资料回答",
  recap: "回顾上一章停在哪、哪些线没收",
  check: "检查选中的一段和前文有没有矛盾",
  change: "提出改动，你确认后才执行",
};

/** What the 「＋」 menu can add, and what choosing each does. */
export type PlusPick = {
  chapters: { number: number; title: string }[];
  characters: { id: string; name: string }[];
  /** The findings of the check on screen that can be handed to the assistant; `issuesReason` says why not when they cannot. */
  issues: { id: string; number: number; label: string }[];
  issuesReason: string;
  onChapter: (number: number) => void;
  onCharacter: (id: string, name: string) => void;
  onIssue: (id: string, number: number) => void;
  /** 在正文里选一段: only a hint, nothing is added. */
  onSelectHint: () => void;
};

const Cross = () => <svg viewBox="0 0 10 10" width="8" height="8" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M2 2l6 6M8 2 2 8" /></svg>;
const Plus = () => <svg viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M6 1v10M1 6h10" /></svg>;
const Caret = () => <svg viewBox="0 0 12 12" width="10" height="10" fill="none" stroke="currentColor" strokeWidth="1.6" aria-hidden="true"><path d="M2 4l4 4 4-4" /></svg>;
const Up = () => <svg viewBox="0 0 16 16" fill="none" stroke="currentColor" strokeWidth="2" aria-hidden="true"><path d="M8 13V3M3.5 7.5 8 3l4.5 4.5" /></svg>;
const Stop = () => <svg viewBox="0 0 16 16" aria-hidden="true"><rect x="4" y="4" width="8" height="8" fill="currentColor" /></svg>;

type View = "root" | "chapters" | "characters" | "issues";

/** A small menu opened by a button above it. Escape or a click outside closes it; the arrow keys move between its entries. */
function useMenu(close: () => void, anchor: RefObject<HTMLElement | null>) {
  const list = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const away = (event: PointerEvent) => { if (!anchor.current?.contains(event.target as Node)) close(); };
    document.addEventListener("pointerdown", away);
    return () => document.removeEventListener("pointerdown", away);
  }, [close, anchor]);
  const onKeyDown = (event: ReactKeyboardEvent) => {
    if (event.key === "Escape") { event.stopPropagation(); close(); return; }
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const items = Array.from(list.current?.querySelectorAll<HTMLElement>('[role^="menuitem"]:not(:disabled)') ?? []);
    if (!items.length) return;
    event.preventDefault();
    const at = items.indexOf(document.activeElement as HTMLElement);
    items[(at + (event.key === "ArrowDown" ? 1 : items.length - 1)) % items.length].focus();
  };
  return { list, onKeyDown };
}

/** Where a menu opened from the box goes: up when there is room above it (below the fixed top bar and inside whatever clips it),
    otherwise down; when neither side has room for all of it, the side with more room, with the menu scrolling inside. */
function usePlacement(anchor: RefObject<HTMLElement | null>, view: string) {
  useLayoutEffect(() => {
    const frame = anchor.current;
    const menu = frame?.querySelector<HTMLElement>(".cx-menu");
    if (!menu || !frame) return;
    const place = () => {
      menu.classList.remove("down", "constrained");
      menu.style.maxHeight = "";
      const need = menu.offsetHeight;
      const rect = frame.getBoundingClientRect();
      let top = (parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--topbar-h")) || 64) + 2;
      let bottom = window.innerHeight;
      for (let node = frame.parentElement; node && node !== document.body; node = node.parentElement) {
        const style = getComputedStyle(node);
        if (style.overflowY === "visible") continue;
        const box = node.getBoundingClientRect();
        top = Math.max(top, box.top);
        bottom = Math.min(bottom, box.bottom);
      }
      const above = rect.top - top - 12;
      const below = bottom - rect.bottom - 12;
      const down = need > above && below > above;
      const room = Math.max(96, down ? below : above);
      if (down) menu.classList.add("down");
      if (need > room) { menu.classList.add("constrained"); menu.style.maxHeight = `${room}px`; }
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [anchor, view]);
}

function PlusMenu({ pick, close, anchor, writing }: { pick: PlusPick; close: () => void; anchor: RefObject<HTMLElement | null>; writing: boolean }) {
  const [view, setView] = useState<View>("root");
  const { list, onKeyDown } = useMenu(close, anchor);
  usePlacement(anchor, view);
  useEffect(() => { list.current?.querySelector<HTMLElement>('[role^="menuitem"]:not(:disabled)')?.focus({ preventScroll: true }); }, [view, list]);
  const done = (action: () => void) => () => { action(); close(); };
  return (
    <div ref={list} className="cx-menu" role="menu" aria-label="加进这次提问" onKeyDown={onKeyDown}>
      {view === "root" && (
        <>
          <span className="head" aria-hidden="true">加进这次提问</span>
          <button type="button" role="menuitem" disabled={!pick.chapters.length} onClick={() => setView("chapters")}>某一章<span className="k">选章节</span></button>
          <button type="button" role="menuitem" disabled={!pick.characters.length} onClick={() => setView("characters")}>某个人物<span className="k">选人物</span></button>
          {writing && pick.issues.length > 0 && (
            <button type="button" role="menuitem" disabled={Boolean(pick.issuesReason)} title={pick.issuesReason || undefined} onClick={() => setView("issues")}>某条检查结果<span className="k">本章</span></button>
          )}
          <span className="sep" role="separator" />
          <button type="button" role="menuitem" onClick={done(pick.onSelectHint)}>在正文里选一段<span className="k">选中后点「问助手」</span></button>
        </>
      )}
      {view === "chapters" && (
        <>
          <button type="button" role="menuitem" className="back" onClick={() => setView("root")}>‹ 某一章</button>
          <div className="scroll">
            {pick.chapters.map((chapter) => (
              <button key={chapter.number} type="button" role="menuitem" onClick={done(() => pick.onChapter(chapter.number))}>{chapterHeading(chapter.number, chapter.title)}</button>
            ))}
          </div>
        </>
      )}
      {view === "characters" && (
        <>
          <button type="button" role="menuitem" className="back" onClick={() => setView("root")}>‹ 某个人物</button>
          <div className="scroll">
            {pick.characters.map((person) => <button key={person.id} type="button" role="menuitem" onClick={done(() => pick.onCharacter(person.id, person.name))}>{person.name}</button>)}
          </div>
        </>
      )}
      {view === "issues" && (
        <>
          <button type="button" role="menuitem" className="back" onClick={() => setView("root")}>‹ 某条检查结果</button>
          <div className="scroll">
            {pick.issues.map((issue) => <button key={issue.id} type="button" role="menuitem" onClick={done(() => pick.onIssue(issue.id, issue.number))}><span>{issue.number}　{issue.label}</span></button>)}
          </div>
        </>
      )}
    </div>
  );
}

function ModeMenu({ modes, mode, setMode, close, anchor }: { modes: Mode[]; mode: Mode; setMode: (mode: Mode) => void; close: () => void; anchor: RefObject<HTMLElement | null> }) {
  const { list, onKeyDown } = useMenu(close, anchor);
  usePlacement(anchor, "mode");
  useEffect(() => { list.current?.querySelector<HTMLElement>('[aria-checked="true"]')?.focus({ preventScroll: true }); }, [list]);
  return (
    <div ref={list} className="cx-menu mode" role="menu" aria-label="这次让助手做什么" onKeyDown={onKeyDown}>
      <span className="head" aria-hidden="true">这次让助手做什么</span>
      {modes.map((item) => (
        <button key={item} type="button" role="menuitemradio" aria-label={MODE_LABEL[item]} aria-checked={item === mode} onClick={() => { setMode(item); close(); }}>
          <span className="what"><span className="name">{MODE_LABEL[item]}</span><span className="d">{MODE_HINT[item]}</span></span>
        </button>
      ))}
    </div>
  );
}

export type ComposerProps = {
  chips: ComposeChip[];
  text: string;
  setText: (text: string) => void;
  placeholder: string;
  fieldRef: RefObject<HTMLTextAreaElement | null>;
  maxLength: number;
  autoFocus?: boolean;
  mode: Mode;
  /** The modes offered here (just 问作品 away from the writing page). */
  modes: Mode[];
  setMode: (mode: Mode) => void;
  pick: PlusPick;
  writing: boolean;
  /** Set when the box cannot be used at all (no characters left, an archived work): the reason, written inside the box. */
  off: string;
  /** A task is running: the send square becomes a stop button. */
  running: boolean;
  stopping: boolean;
  stop: () => void;
  canSend: boolean;
  send: () => void;
  /** The cost line, or what is missing in this mode. */
  hint: string;
  /** What follows the cost when there is room for it (how much is left today); it goes into the hint's title when there is not. */
  hintMore?: string;
  /** Set when the mode is not the author's choice (a fix for one finding): its name, shown in place of the mode, without a menu. */
  modeName?: string;
  /** The text box cannot be typed in (查前文矛盾 asks about the picked words only). */
  fixed?: boolean;
  /** ↑ with an empty box. */
  recall: () => void;
};

const STOP_GRACE_MS = 700;

export function Composer(props: ComposerProps) {
  const { chips, text, setText, placeholder, fieldRef, maxLength, autoFocus, mode, modes, setMode, pick, writing, off, running, stopping, stop, canSend, send, hint, hintMore, modeName, fixed, recall } = props;
  const [open, setOpen] = useState<null | "plus" | "mode">(null);
  const [focused, setFocused] = useState(false);
  // The send square turns into the stop button under the author's pointer; a second click of a double click meant for 发送 must
  // not stop the task it just started, so the stop button ignores clicks for a moment after it appears.
  const stopArmedAt = useRef(0);
  useEffect(() => { if (running) stopArmedAt.current = performance.now(); }, [running]);
  const frame = useRef<HTMLFormElement>(null);
  const plusButton = useRef<HTMLButtonElement>(null);
  const modeButton = useRef<HTMLButtonElement>(null);
  const length = Array.from(text).length;
  const counting = length >= 250;
  const onKeyDown = (event: ReactKeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key === "ArrowUp" && !text && !event.shiftKey && !event.nativeEvent.isComposing) { event.preventDefault(); recall(); return; }
    // Enter sends; Shift+Enter breaks the line; Enter that confirms an IME candidate does neither.
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing || event.keyCode === 229) return;
    event.preventDefault();
    send();
  };
  const closePlus = () => { setOpen(null); window.setTimeout(() => plusButton.current?.focus(), 0); };
  const closeMode = () => { setOpen(null); window.setTimeout(() => modeButton.current?.focus(), 0); };
  return (
    <div className="a-compose">
      <form className={`cx${off ? " off" : ""}`} onSubmit={(event) => { event.preventDefault(); if (!running) send(); }} aria-label="向助手提问" ref={frame}>
        {off ? (
          <p className="cx-text ph" role="status">{off}</p>
        ) : (
          <>
            {chips.length > 0 && (
              <div className="cx-chips">
                {chips.map((chip) => (
                  <span key={chip.key} className={`cx-chip a-chip${chip.quote ? " quote" : ""}${chip.muted ? " muted" : ""}`}>
                    <span className="label">{chip.label}</span>
                    {chip.muted && chip.note && <span className="apart">{chip.note}</span>}
                    <button type="button" aria-label={`去掉：${chip.label}`} onClick={chip.drop}><Cross /></button>
                  </span>
                ))}
              </div>
            )}
            <textarea ref={fieldRef} className="cx-text" value={text} maxLength={maxLength} rows={1} aria-label="向助手提问" placeholder={placeholder}
              data-autofocus={autoFocus ? true : undefined} readOnly={fixed} aria-readonly={fixed || undefined}
              onChange={(event) => setText(event.target.value)} onKeyDown={onKeyDown} onFocus={() => setFocused(true)} onBlur={() => setFocused(false)} />
          </>
        )}
        <div className="cx-bar">
          {!off && (
            <>
              <button ref={plusButton} type="button" className="cx-ghost cx-plus" aria-label="添加上下文" aria-haspopup="menu" aria-expanded={open === "plus"} onClick={() => setOpen(open === "plus" ? null : "plus")}><Plus /></button>
              <button ref={modeButton} type="button" className="cx-ghost cx-mode" aria-label={`这次做什么：${modeName ?? MODE_LABEL[mode]}`} aria-haspopup={modeName ? undefined : "menu"} aria-expanded={modeName ? undefined : open === "mode"} disabled={Boolean(modeName) || modes.length < 2} onClick={() => setOpen(open === "mode" ? null : "mode")}>
                {modeName ?? MODE_LABEL[mode]}{!modeName && modes.length > 1 && <span className="caret"><Caret /></span>}
              </button>
            </>
          )}
          <span className="cx-fill" />
          {running ? (
            <button type="button" className="cx-send stop" aria-label="停止" disabled={stopping} onClick={() => { if (performance.now() - stopArmedAt.current >= STOP_GRACE_MS) stop(); }}><Stop /></button>
          ) : (
            <button type="submit" className="cx-send" aria-label="发送" disabled={!canSend}><Up /></button>
          )}
        </div>
        {open === "plus" && <PlusMenu pick={pick} writing={writing} close={closePlus} anchor={frame} />}
        {open === "mode" && <ModeMenu modes={modes} mode={mode} setMode={setMode} close={closeMode} anchor={frame} />}
      </form>
      {/* Under the frame, at its right: one place for the counter, the key hint and the cost. The key hint takes the cost's place while the box has focus, so the line never reflows. */}
      <div className="a-quota-row">
        <p className="a-ai-note">回答由 AI 生成，可能出错，请点出处核对。</p>
        {!off && (
          <span className={`cx-note${length >= maxLength ? " warn" : ""}`} title={hintMore ? `${hint} · ${hintMore}` : undefined}>
            {counting ? `${length} / ${maxLength}`
              : focused && !running ? <span className="cx-keys">Enter 发送</span>
                : <>{hint}{hintMore && <span className="more"> · {hintMore}</span>}</>}
          </span>
        )}
      </div>
    </div>
  );
}
