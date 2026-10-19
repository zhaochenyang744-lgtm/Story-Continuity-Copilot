// 改法 as a text difference: which words go and which come, character by character (longest common subsequence), so a change of
// two characters in a long sentence shows as two struck and two added instead of one sentence struck and another written.

export type DiffPart = { kind: "same" | "del" | "ins"; text: string };

/** The parts of `before` → `after`. A stretch where the two differ is one struck piece followed by one added piece. */
export function charDiff(before: string, after: string): DiffPart[] {
  const a = Array.from(before);
  const b = Array.from(after);
  const n = a.length;
  const m = b.length;
  const width = m + 1;
  // table[i * width + j] = length of the longest common subsequence of a[i…] and b[j…]
  const table = new Uint16Array((n + 1) * width);
  for (let i = n - 1; i >= 0; i -= 1) {
    for (let j = m - 1; j >= 0; j -= 1) {
      table[i * width + j] = a[i] === b[j] ? table[(i + 1) * width + j + 1] + 1 : Math.max(table[(i + 1) * width + j], table[i * width + j + 1]);
    }
  }
  const parts: DiffPart[] = [];
  const push = (kind: DiffPart["kind"], text: string) => {
    if (!text) return;
    const last = parts[parts.length - 1];
    if (last && last.kind === kind) last.text += text; else parts.push({ kind, text });
  };
  let i = 0;
  let j = 0;
  let removed = "";
  let added = "";
  const flush = () => { push("del", removed); push("ins", added); removed = ""; added = ""; };
  while (i < n && j < m) {
    if (a[i] === b[j]) { flush(); push("same", a[i]); i += 1; j += 1; }
    else if (table[(i + 1) * width + j] >= table[i * width + j + 1]) { removed += a[i]; i += 1; }
    else { added += b[j]; j += 1; }
  }
  while (i < n) { removed += a[i]; i += 1; }
  while (j < m) { added += b[j]; j += 1; }
  flush();
  return parts;
}

/** What to show for a change: the character difference, or (when more than half of the two sentences changed, where the pieces
    would only be confetti) the whole old sentence struck and the whole new one added. */
export function diffView(before: string, after: string): { parts: DiffPart[]; whole: boolean } {
  const parts = charDiff(before, after);
  const changed = parts.filter((part) => part.kind !== "same").reduce((sum, part) => sum + Array.from(part.text).length, 0);
  const total = Array.from(before).length + Array.from(after).length;
  if (changed > total / 2) return { parts: [{ kind: "del", text: before }, { kind: "ins", text: after }], whole: true };
  return { parts, whole: false };
}
