// Small pure helpers of the assistant's answers, kept apart from the views so they can be tested on their own (e2e/assistant-38a-units.spec.ts).

/** A text cut into sentences; the pieces put back together are the text itself (newlines stay with the sentence they end). */
export function sentencePieces(text: string): string[] {
  const pieces = text.match(/[^。！？!?\n]*(?:[。！？!?]+[”’」』）)]*|\n)|[^。！？!?\n]+$/g);
  return pieces ?? (text ? [text] : []);
}

/** Characters that make a pair of characters too common to say what a sentence is about. */
const COMMON = "的了是在把被和与也都就还着过而并但又之其以及他她它这那不有";
/** The two-character pieces of a text that say something: no space, punctuation, digit or very common character in them. */
function pairsOf(text: string): Set<string> {
  const chars = Array.from(text.replace(/[\s\d，。、；：！？,.;:!?"'“”‘’「」『』（）()《》【】—…·\-]/g, " "));
  const pairs = new Set<string>();
  for (let at = 0; at + 1 < chars.length; at += 1) {
    const [a, b] = [chars[at], chars[at + 1]];
    if (a === " " || b === " " || COMMON.includes(a) || COMMON.includes(b)) continue;
    pairs.add(a + b);
  }
  return pairs;
}

/** The sentence of `text` that says what `summary` says, found by the words they share (two characters or more); null when no sentence shares any.
    Returns the text cut into what comes before it, the sentence and what comes after, so the page can set the sentence apart. */
export function relevantSentence(text: string, summary: string): { before: string; hit: string; after: string } | null {
  const pieces = sentencePieces(text);
  if (pieces.filter((piece) => piece.trim()).length < 2) return null;
  const wanted = pairsOf(summary);
  if (!wanted.size) return null;
  let best = -1;
  let bestScore = 0;
  pieces.forEach((piece, index) => {
    if (!piece.trim()) return;
    let score = 0;
    for (const pair of pairsOf(piece)) if (wanted.has(pair)) score += 1;
    if (score > bestScore) { best = index; bestScore = score; }
  });
  if (best < 0) return null;
  return { before: pieces.slice(0, best).join(""), hit: pieces[best], after: pieces.slice(best + 1).join("") };
}

/** The openings of a sentence of the model's note that tell where it looked (or did not): they go under 「怎么查的」, not under the answer. */
const PROCESS_NOTE = /^\s*(?:查过|查了|读过|读了|搜过|搜了|看过|看了|核对过|没查|未查)/;

/** The model's note split in two: the sentences that say where it looked, and the rest (nothing found, a refusal, a line about an instruction in
    the material, 「情节怎么写由你决定……」), which stay under the answer. */
export function splitNote(note: string | null | undefined): { looked: string[]; rest: string } {
  if (!note) return { looked: [], rest: "" };
  const looked: string[] = [];
  let rest = "";
  for (const piece of note.split(/(?<=[；;。！!？?])/)) {
    if (!piece.trim()) continue;
    if (PROCESS_NOTE.test(piece)) looked.push(piece.trim());
    else rest += piece;
  }
  return { looked, rest: rest.trim() };
}

const DIGITS: Record<string, number> = { 〇: 0, 零: 0, 一: 1, 二: 2, 两: 2, 三: 3, 四: 4, 五: 5, 六: 6, 七: 7, 八: 8, 九: 9 };
/** 12 for 「十二」, 3 for 「三」, 21 for 「二十一」; null for what is not a number up to 999. */
export function chineseNumber(text: string): number | null {
  if (/^\d+$/.test(text)) return Number(text);
  let total = 0;
  let current = 0;
  let seen = false;
  for (const char of text) {
    if (char in DIGITS) { current = DIGITS[char]; seen = true; }
    else if (char === "十") { total += (current || 1) * 10; current = 0; seen = true; }
    else if (char === "百") { total += (current || 1) * 100; current = 0; seen = true; }
    else return null;
  }
  return seen ? total + current : null;
}
/** The chapter a sentence first names (「第 7 章」「第十章」), or null. */
export function chapterNamed(text: string): number | null {
  const found = /第\s*([0-9〇零一二两三四五六七八九十百]+)\s*章/.exec(text);
  return found ? chineseNumber(found[1]) : null;
}
/** True when at least `from` of the sentences each name a different chapter: an answer that walks through the chapters one by one. */
export function walksChapters(sentences: { text: string }[], from = 3): boolean {
  return new Set(sentences.map((sentence) => chapterNamed(sentence.text)).filter((number): number is number => number !== null)).size >= from;
}
