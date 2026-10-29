"use client";

// The top bar's little dot for a long task (v2.1 B). A long task goes on in the background while the author is somewhere else, so the page
// keeps a note per work of the long task it is following: its id, the status it was last seen in, and the status the author has looked at.
// The dot is on while the task is waiting for an answer or is over and the author has not yet looked at that. The note lives in this browser's
// localStorage (it is a convenience, not a record: without it the dot simply never shows).
import { useEffect, useSyncExternalStore } from "react";
import { request } from "../../api";

const KEY = "story-continuity:long-task";
const EVENT = "story-continuity:long-task-changed";
const POLL_MS = 4000;
/** The statuses a task passes through by itself (asked for until it leaves them). */
const LIVE = ["planning", "long_queued", "long_running"];
/** The statuses the author should look at. */
const SETTLED = ["waiting_author", "completed", "stopped", "failed"];

type Note = { id: string; last: string; seen: string };
type Notes = Record<string, Note>;

function read(): Notes {
  try { return JSON.parse(window.localStorage.getItem(KEY) ?? "{}") as Notes; } catch { return {}; }
}
function write(notes: Notes) {
  try { window.localStorage.setItem(KEY, JSON.stringify(notes)); } catch { /* the dot is a convenience: without storage it does not show */ }
  window.dispatchEvent(new Event(EVENT));
}

/** A long task has been made (or seen again in a status): remember the status; `seen` is what the author has looked at. */
export function noteLong(projectId: string, id: string, status: string, seen = false) {
  const notes = read();
  const known = notes[projectId];
  const next: Note = known?.id === id ? { ...known, last: status } : { id, last: status, seen: "" };
  if (seen && SETTLED.includes(status)) next.seen = `${id}:${status}`;
  if (known && known.id === next.id && known.last === next.last && known.seen === next.seen) return;
  write({ ...notes, [projectId]: next });
}
/** The author is looking at the assistant: whatever the task is in now has been seen. */
export function seenLong(projectId: string, id?: string, status?: string) {
  const note = read()[projectId];
  if (!note || (id && note.id !== id)) return;
  noteLong(projectId, note.id, status ?? note.last, true);
}

const subscribe = (notify: () => void) => {
  window.addEventListener(EVENT, notify);
  window.addEventListener("storage", notify);
  return () => { window.removeEventListener(EVENT, notify); window.removeEventListener("storage", notify); };
};

/** True while the work's long task waits for an answer or is over, and the author has not looked at that yet. While the task is going on, the
    top bar follows it on its own (every 4 seconds); when the assistant is open it has its own, faster, look at the task and tells the note. */
export function useLongDot(projectId: string | null, on: boolean): boolean {
  const snapshot = useSyncExternalStore(subscribe, () => (projectId ? JSON.stringify(read()[projectId] ?? null) : "null"), () => "null");
  const note = JSON.parse(snapshot) as Note | null;
  const id = note?.id ?? null;
  const following = Boolean(on && projectId && id && LIVE.includes(note!.last));
  useEffect(() => {
    if (!following || !projectId || !id) return;
    let live = true;
    let timer = 0;
    const poll = async () => {
      try {
        const next = await request<{ id: string; status: string }>(`/projects/${projectId}/assistant/long-tasks/${id}`);
        if (!live) return;
        noteLong(projectId, id, next.status);
        if (!LIVE.includes(next.status)) return;
      } catch { /* try again; a task that is gone leaves the note as it is */ }
      if (live) timer = window.setTimeout(() => void poll(), POLL_MS);
    };
    timer = window.setTimeout(() => void poll(), POLL_MS);
    return () => { live = false; window.clearTimeout(timer); };
  }, [following, projectId, id]);
  return Boolean(on && note && SETTLED.includes(note.last) && note.seen !== `${note.id}:${note.last}`);
}
