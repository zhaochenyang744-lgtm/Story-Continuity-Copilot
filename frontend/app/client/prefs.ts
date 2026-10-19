"use client";

// What the author sets on this device: the theme and the size of the text they read and write in. Both live in
// localStorage only (every read and write is guarded: it can be blocked), and both are read before the first paint by
// the script in layout.tsx, so the page never flashes.
import { flushSync } from "react-dom";
import { useSyncExternalStore } from "react";

export type ThemeMode = "day" | "night" | "system";
export type FontSize = "small" | "medium" | "large";

export const themeKey = "story-continuity:theme";
export const fontSizeKey = "story-continuity:font-size";

const readKey = (key: string) => {
  try { return window.localStorage.getItem(key); } catch { return null; }
};
const writeKey = (key: string, value: string | null) => {
  try { if (value === null) window.localStorage.removeItem(key); else window.localStorage.setItem(key, value); } catch { /* applies to this visit only */ }
};

type State = { mode: ThemeMode; systemDark: boolean; fontSize: FontSize; loaded: boolean };
let state: State = { mode: "system", systemDark: false, fontSize: "medium", loaded: false };
const listeners = new Set<() => void>();
const emit = () => listeners.forEach((listener) => listener());
const set = (next: Partial<State>) => { state = { ...state, ...next }; };

export const resolveTheme = (mode: ThemeMode, systemDark: boolean): "day" | "night" => (mode === "system" ? (systemDark ? "night" : "day") : mode);

const sweepAllowed = () => !window.matchMedia("(prefers-reduced-motion: reduce)").matches;

/** Reads what this device remembers (once, when the app starts) and follows the system's light/dark setting. */
export function loadPrefs() {
  if (state.loaded || typeof window === "undefined") return;
  const stored = readKey(themeKey);
  const size = readKey(fontSizeKey);
  const query = window.matchMedia("(prefers-color-scheme: dark)");
  set({
    loaded: true,
    mode: stored === "day" || stored === "night" ? stored : "system",
    systemDark: query.matches,
    fontSize: size === "small" || size === "large" ? size : "medium",
  });
  document.documentElement.dataset.theme = resolveTheme(state.mode, state.systemDark);
  document.documentElement.dataset.fontSize = state.fontSize;
  query.addEventListener("change", (event) => {
    set({ systemDark: event.matches });
    if (state.mode === "system") document.documentElement.dataset.theme = resolveTheme("system", event.matches);
    emit();
  });
  emit();
}

/** Switches the theme. The new colours sweep across the page like paper through a press (unless motion is reduced). */
export function setThemeMode(mode: ThemeMode) {
  loadPrefs();
  const next = resolveTheme(mode, state.systemDark);
  writeKey(themeKey, mode === "system" ? null : mode);
  const apply = () => { set({ mode }); document.documentElement.dataset.theme = next; flushSync(emit); };
  const sweep = (document as Document & { startViewTransition?: (update: () => void) => unknown }).startViewTransition;
  if (sweep && sweepAllowed() && document.documentElement.dataset.theme !== next) sweep.call(document, apply);
  else apply();
}

/** The top bar's button: from a fixed theme to the other one; from "follow the system" to the opposite of what it shows now. */
export function toggleTheme() {
  loadPrefs();
  setThemeMode(resolveTheme(state.mode, state.systemDark) === "night" ? "day" : "night");
}

export function setFontSize(fontSize: FontSize) {
  loadPrefs();
  writeKey(fontSizeKey, fontSize === "medium" ? null : fontSize);
  set({ fontSize });
  document.documentElement.dataset.fontSize = fontSize;
  emit();
}

const subscribe = (listener: () => void) => { listeners.add(listener); return () => { listeners.delete(listener); }; };
const serverState: State = { mode: "system", systemDark: false, fontSize: "medium", loaded: false };

/** The chosen mode, the theme showing now, and the text size. */
export function usePrefs() {
  const current = useSyncExternalStore(subscribe, () => state, () => serverState);
  return { mode: current.mode, theme: resolveTheme(current.mode, current.systemDark), fontSize: current.fontSize };
}
