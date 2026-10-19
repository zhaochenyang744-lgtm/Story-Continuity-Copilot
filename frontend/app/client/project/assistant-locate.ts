// 去原文: the passage an author asked to see, handed from the assistant to the chapter page that is about to open.
// The page takes it once the chapter's text is on screen, rings the sentence, and says what happened when it could not find it.
export type LocateRequest = {
  chapter: number;
  /** The words to find; empty when there is nothing to look for (the chapter is just opened). */
  text: string;
  /** Said once the sentence has been found and rung. */
  found?: string;
  /** Said when the sentence was not found (or there was nothing to look for). */
  missing?: string;
  at: number;
};
let pending: LocateRequest | null = null;

export function requestLocate(chapter: number, text: string, say: { found?: string; missing?: string } = {}) {
  pending = { chapter, text, ...say, at: Date.now() };
}

/** What to show in this chapter, once; nothing when none was asked for, or the request is old. */
export function takeLocate(chapter: number): LocateRequest | null {
  const wanted = pending;
  if (!wanted || wanted.chapter !== chapter || Date.now() - wanted.at > 20_000) return null;
  pending = null;
  return wanted;
}

/** The default words for a sentence that could not be found. */
export const notFoundText = (chapter: number) => `没在第 ${chapter} 章找到对应的原句，已打开这一章`;
