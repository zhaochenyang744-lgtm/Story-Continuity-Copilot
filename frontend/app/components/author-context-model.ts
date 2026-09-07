import type { AuthorContext, Chapter } from "../model";

export type Kind = "story" | "character" | "world";
export type Nature = "setting" | "plan" | "idea";
export type AuthorDocument = {
  is_stale?: boolean;
  stale_reason?: string | null;
  id: string;
  kind: Kind;
  title: string;
  content: string;
  nature: Nature;
  disclosure: "unspecified" | "hidden" | "revealed";
  knowledge: string;
  from: number | null;
  to: number | null;
  revision: number;
  archived: boolean;
  origin: string;
  baseSignature?: string;
};
export type Passage = {
  id: string;
  chapterId: string;
  number: number;
  title: string;
  text: string;
  revision: number;
};
export type Resolution =
  "revise_text" | "revise_document" | "intentional" | "not_issue" | "later";
export type Comparison = {
  serverId?: string;
  serverStale?: boolean;
  superseded?: boolean;
  id: string;
  document: AuthorDocument;
  passage: Passage;
  sourceRevision: number;
  previousDocument?: AuthorDocument;
  resolution: Resolution;
  reason: string;
  at: string;
};
export type PreviewState = {
  version: 1;
  serial: number;
  documents: AuthorDocument[];
  comparisons: Comparison[];
  skipped: boolean;
};
export const EMPTY: PreviewState = {
  version: 1,
  serial: 0,
  documents: [],
  comparisons: [],
  skipped: false,
};
export const categories: Record<Kind, string> = {
  story: "大纲",
  character: "角色",
  world: "世界观",
};
export const natures: Record<Nature, string> = {
  setting: "明确设定",
  plan: "故事安排",
  idea: "待定想法",
};
export const disclosures = {
  unspecified: "尚未说明",
  hidden: "尚未向读者揭露",
  revealed: "已在正文披露",
};
export const resolutions: Record<Resolution, string> = {
  revise_text: "准备修改正文",
  revise_document: "已调整预览资料",
  intentional: "保留为有意安排",
  not_issue: "不是问题",
  later: "暂不处理",
};

export function formalDocuments(
  context: AuthorContext | null,
): AuthorDocument[] {
  if (!context) return [];
  const base = {
    nature: "plan" as const,
    disclosure: "unspecified" as const,
    knowledge: "",
    from: null,
    to: null,
    revision: context.author_context_version,
    origin: "已有作者规划",
  };
  return [
    ...context.story_plans.map((item) => ({
      ...base,
      id: `story:${item.id}`,
      kind: "story" as const,
      title: item.title,
      content: [
        item.summary,
        item.goal && `故事目标：${item.goal}`,
        item.target_chapter_number &&
          `计划章节：第 ${item.target_chapter_number} 章`,
      ]
        .filter(Boolean)
        .join("\n\n"),
      archived: item.archived,
      baseSignature: JSON.stringify(item),
    })),
    ...context.character_plans.map((item) => ({
      ...base,
      id: `character:${item.id}`,
      kind: "character" as const,
      title: item.name,
      content: [
        item.goal && `目标：${item.goal}`,
        item.planned_state && `计划状态：${item.planned_state}`,
        item.notes,
      ]
        .filter(Boolean)
        .join("\n\n"),
      archived: item.archived,
      baseSignature: JSON.stringify(item),
    })),
    ...context.world_plans.map((item) => ({
      ...base,
      id: `world:${item.id}`,
      kind: "world" as const,
      title: item.name,
      content: [item.description, item.notes].filter(Boolean).join("\n\n"),
      archived: item.archived,
      baseSignature: JSON.stringify(item),
    })),
  ];
}
export function mergeDocuments(
  formal: AuthorDocument[],
  drafts: AuthorDocument[],
) {
  const result = new Map(formal.map((d) => [d.id, d]));
  for (const draft of drafts) result.set(draft.id, draft);
  return [...result.values()];
}
export function passagesFrom(chapters: Chapter[], revision: number): Passage[] {
  return chapters.flatMap((chapter) =>
    (chapter.source_spans ?? [])
      .filter((span) => span.text_excerpt.trim())
      .map((span) => ({
        id: span.span_id,
        chapterId: chapter.id,
        number: chapter.number,
        title: chapter.title,
        text: span.text_excerpt,
        revision: span.source_revision ?? revision,
      })),
  );
}
export function documentError(document: AuthorDocument): string {
  if (!document.title.trim() || !document.content.trim())
    return "请填写资料标题和内容。";
  if (
    document.title.length > 160 ||
    document.content.length > 30000 ||
    document.knowledge.length > 3000
  )
    return "标题最多 160 字，内容最多 30,000 字，知情说明最多 3,000 字。";
  if (
    [document.from, document.to].some(
      (n) => n !== null && (!Number.isSafeInteger(n) || n < 1 || n > 999999),
    )
  )
    return "适用章节须为 1 至 999999 的整数，也可以留空。";
  if (
    document.from !== null &&
    document.to !== null &&
    document.from > document.to
  )
    return "结束章节不能早于起始章节。";
  return "";
}
export function outOfRange(document: AuthorDocument, passage: Passage) {
  return (
    (document.from !== null && passage.number < document.from) ||
    (document.to !== null && passage.number > document.to)
  );
}
export function formalConflict(
  document: AuthorDocument,
  formal: AuthorDocument[],
) {
  return Boolean(document.stale_reason === "legacy_changed" || (document.is_stale && !document.archived)) || Boolean(
    document.baseSignature &&
    formal.find((d) => d.id === document.id)?.baseSignature !==
      document.baseSignature,
  );
}
export function comparisonStale(
  item: Comparison,
  documents: AuthorDocument[],
  passages: Passage[],
  sourceRevision: number,
) {
  const document = documents.find((d) => d.id === item.document.id),
    passage = passages.find((p) => p.id === item.passage.id);
  return (
    !document ||
    document.archived ||
    JSON.stringify(document) !== JSON.stringify(item.document) ||
    sourceRevision !== item.sourceRevision ||
    !passage ||
    JSON.stringify(passage) !== JSON.stringify(item.passage)
  );
}
export function parseState(raw: string | null): PreviewState {
  if (raw === null) return EMPTY;
  const state = JSON.parse(raw) as PreviewState;
  const validDoc = (d: AuthorDocument) =>
    d &&
    Object.hasOwn(categories, d.kind) &&
    Object.hasOwn(natures, d.nature) &&
    Object.hasOwn(disclosures, d.disclosure) &&
    [d.id, d.title, d.content, d.knowledge, d.origin].every(
      (v) => typeof v === "string",
    ) &&
    Number.isSafeInteger(d.revision) &&
    d.revision >= 0 &&
    typeof d.archived === "boolean" &&
    [d.from, d.to].every(
      (n) => n === null || (Number.isSafeInteger(n) && n! >= 1),
    ) &&
    (d.baseSignature === undefined || typeof d.baseSignature === "string");
  if (
    state?.version !== 1 ||
    !Number.isSafeInteger(state.serial) ||
    state.serial < 0 ||
    typeof state.skipped !== "boolean" ||
    !Array.isArray(state.documents) ||
    !state.documents.every(validDoc) ||
    !Array.isArray(state.comparisons) ||
    !state.comparisons.every(
      (c) =>
        c &&
        typeof c.id === "string" &&
        validDoc(c.document) &&
        (c.previousDocument === undefined || validDoc(c.previousDocument)) &&
        c.passage &&
        [
          c.passage.id,
          c.passage.chapterId,
          c.passage.title,
          c.passage.text,
          c.reason,
          c.at,
        ].every((v) => typeof v === "string") &&
        Number.isSafeInteger(c.passage.number) &&
        Number.isSafeInteger(c.passage.revision) &&
        Number.isSafeInteger(c.sourceRevision) &&
        Object.hasOwn(resolutions, c.resolution),
    )
  )
    throw Error("Invalid preview state");
  return state;
}
