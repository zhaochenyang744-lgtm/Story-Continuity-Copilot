"use client";

import { useEffect, useRef, useState } from "react";
import { Editor, EditorContent, Extension, useEditor } from "@tiptap/react";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";
import type { JSONContent } from "@tiptap/core";
import { Mark } from "@tiptap/pm/model";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import type { DraftBodyFormat } from "../model";

/** Text editing keeps a cue only until typing starts, and only when Tab brought focus here. */
export function useWritingFocusOrigin() {
  useEffect(() => {
    let keyboard = false;
    const field = (target: EventTarget | null) =>
      target instanceof HTMLElement && target.matches("[data-writing-focus]") ? target : null;
    const clear = (target: EventTarget | null) => field(target)?.removeAttribute("data-focus-from");
    const keydown = (event: KeyboardEvent) => { if (event.key === "Tab") keyboard = true; };
    const pointerdown = () => { keyboard = false; clear(document.activeElement); };
    const focus = (event: FocusEvent) => {
      const target = field(event.target);
      if (keyboard) target?.setAttribute("data-focus-from", "keyboard");
      else clear(target);
    };
    const input = (event: Event) => clear(event.target);
    const blur = (event: FocusEvent) => clear(event.target);
    document.addEventListener("keydown", keydown, true);
    document.addEventListener("pointerdown", pointerdown, true);
    document.addEventListener("focus", focus, true);
    document.addEventListener("input", input, true);
    document.addEventListener("blur", blur, true);
    return () => {
      document.removeEventListener("keydown", keydown, true);
      document.removeEventListener("pointerdown", pointerdown, true);
      document.removeEventListener("focus", focus, true);
      document.removeEventListener("input", input, true);
      document.removeEventListener("blur", blur, true);
    };
  }, []);
}

type EditorBinding = {editor: Editor; promoteToMarkdown: () => void};
const editors = new Map<string, EditorBinding>();
const subscribers = new Set<() => void>();
const notify = () => subscribers.forEach((callback) => callback());
const tools = [["bold", "加粗", "B"], ["italic", "斜体", "I"], ["blockquote", "引用", "❞"], ["bulletList", "列表", "•≡"]] as const;

type JsonNode = JSONContent;

const supportedEditorKit = StarterKit.configure({
  code: false,
  codeBlock: false,
  heading: false,
  horizontalRule: false,
  link: false,
  orderedList: false,
  strike: false,
  underline: false,
});

function plainDocument(value: string) {
  return {
    type: "doc",
    content: value.split(/\r?\n/).map((line) => ({
      type: "paragraph",
      content: line ? [{type: "text", text: line}] : undefined,
    })),
  };
}

function nodeText(node: JsonNode): string {
  if (typeof node.text === "string") return node.text;
  if (node.type === "hardBreak") return "\n";
  return (node.content ?? []).map(nodeText).join("");
}

function parseMarkdownDocument(editor: Editor, value: string): JsonNode {
  const markdown = editor.markdown;
  if (!markdown) throw new Error("Markdown parser is unavailable");
  const content: JsonNode[] = [];
  const append = (nodes: JsonNode[]) => {
    for (const node of nodes) {
      const previous = content.at(-1);
      if (previous?.type === "bulletList" && node.type === "bulletList") {
        previous.content = [...(previous.content ?? []), ...(node.content ?? [])];
      } else {
        content.push(node);
      }
    }
  };
  const nested = /^(?: {0,3})[-+*][ \t]*\r?\n((?:[ \t]{2,}>[^\r\n]*(?:\r?\n|$))+)/gm;
  let cursor = 0;
  for (let match = nested.exec(value); match; match = nested.exec(value)) {
    append(markdown.parse(value.slice(cursor, match.index)).content ?? []);
    const quote = match[1].replace(/^[ \t]{2}/gm, "");
    append([{type: "bulletList", content: [{type: "listItem", content: [{type: "paragraph"}, ...(markdown.parse(quote).content ?? [])]}]}]);
    cursor = match.index + match[0].length;
  }
  append(markdown.parse(value.slice(cursor)).content ?? []);
  return {type: "doc", content};
}

function loadMarkdown(editor: Editor, value: string) {
  editor.commands.setContent(parseMarkdownDocument(editor, value), {emitUpdate: false});
}

function plainText(editor: Editor, newline: string) {
  const document = editor.getJSON() as JsonNode;
  return (document.content ?? []).map(nodeText).join(newline);
}

function markdownText(editor: Editor) {
  const markdown = editor.markdown;
  if (!markdown) return editor.getMarkdown();
  const document = structuredClone(editor.getJSON()) as JsonNode;
  const protectedLiterals: {token: string; value: string}[] = [];
  document.content = (document.content ?? []).map((block, index) => {
    const value = nodeText(block);
    if (block.type !== "paragraph" || !/^[-+*]$/.test(value)) return block;
    const token = `\ue100${index}\ue101`;
    protectedLiterals.push({token, value});
    return {...block, content: [{type: "text", text: token}]};
  });
  let value = markdown.serialize(document);
  for (const literal of protectedLiterals) value = value.replace(literal.token, `\\${literal.value}`);
  return value;
}

function hasRichStructure(editor: Editor) {
  const document = editor.getJSON() as JsonNode;
  return (document.content ?? []).some((block) =>
    block.type !== "paragraph" ||
    (block.content ?? []).some((inline) => inline.type !== "text" || Boolean(inline.marks?.length)),
  );
}

function markAsMarkdown(editor: Editor, formatRef: {current: DraftBodyFormat}) {
  if (formatRef.current === "markdown") return;
  formatRef.current = "markdown";
  editor.setOptions({editorProps: {attributes: {...editor.options.editorProps.attributes, "data-body-format": "markdown"}}});
}

export function useDraftText(targetId: string, fallback: string) {
  const [text, setText] = useState(fallback);
  useEffect(() => {
    const update = () => setText(editors.get(targetId)?.editor.getText({blockSeparator: "\n"}) ?? fallback);
    update();
    subscribers.add(update);
    return () => {subscribers.delete(update);};
  }, [targetId, fallback]);
  return text;
}

export function DraftWordCount({targetId, body}: {targetId: string; body: string}) {
  return <>{useDraftText(targetId, body).replace(/\s/g, "").length.toLocaleString()} 字</>;
}

export function replaceVisibleDraftText(targetId: string, before: string, after: string) {
  const editor = editors.get(targetId)?.editor;
  if (!editor?.isEditable || !before || before === after) return false;
  // Hard breaks and cross-block replacements cannot preserve structure safely.
  if (/[\r\n]/.test(before) || /[\r\n]/.test(after)) return false;
  const matches: {from: number; to: number; marks: readonly Mark[]; safe: boolean}[] = [];
  editor.state.doc.descendants((node, position) => {
    if (!node.isTextblock) return true;
    let visible = "";
    const boundaries = [0];
    node.forEach((child, offset) => {
      if (child.isText) {
        for (let index = 0; index < (child.text?.length ?? 0); index += 1) {
          visible += child.text?.[index] ?? "";
          boundaries.push(offset + index + 1);
        }
      } else if (child.type.name === "hardBreak") {
        visible += "\n";
        boundaries.push(offset + child.nodeSize);
      }
    });
    for (let index = visible.indexOf(before); index >= 0; index = visible.indexOf(before, index + 1)) {
      const start = boundaries[index], end = boundaries[index + before.length];
      let marks: readonly Mark[] | null = null;
      let safe = true;
      node.forEach((child, offset) => {
        if (offset >= end || offset + child.nodeSize <= start) return;
        if (!child.isText || (marks !== null && !Mark.sameSet(marks, child.marks))) safe = false;
        if (marks === null && child.isText) marks = child.marks;
      });
      matches.push({from: position + 1 + start, to: position + 1 + end, marks: marks ?? [], safe: safe && marks !== null});
    }
    return false;
  });
  if (matches.length !== 1 || !matches[0].safe) return false;
  return editor.chain().focus().command(({tr}) => {
    if (after) tr.replaceWith(matches[0].from, matches[0].to, editor.schema.text(after, matches[0].marks));
    else tr.delete(matches[0].from, matches[0].to);
    return true;
  }).run();
}

/** A finding to show in the draft: the sentence it is about, its tone and its number in the list.
    hovered: its card or sentence is being pointed at; done: already handled; reveal: draw it in. */
export type FindingMark = {id: string; text: string; tone: "high" | "mid" | "gap" | "state"; index: number; active: boolean; hovered?: boolean; done?: boolean; reveal?: boolean};
type FindingMarkState = {marks: FindingMark[]; pick: ((id: string) => void) | null};
const findingMarkKey = new PluginKey<FindingMarkState>("findingMarks");
type ProseNode = import("@tiptap/pm/model").Node;

/** Every textblock's visible characters and the document position after each one. */
function eachTextblock(doc: ProseNode, visit: (visible: string, positionOf: (index: number) => number) => boolean | void) {
  let stop = false;
  doc.descendants((node, position) => {
    if (stop) return false;
    if (!node.isTextblock) return true;
    let visible = "";
    const boundaries = [0];
    node.forEach((child, offset) => {
      if (child.isText) {
        for (let index = 0; index < (child.text?.length ?? 0); index += 1) {
          visible += child.text?.[index] ?? "";
          boundaries.push(offset + index + 1);
        }
      } else {
        visible += child.type.name === "hardBreak" ? "\n" : "￼";
        boundaries.push(offset + child.nodeSize);
      }
    });
    if (visit(visible, (index) => position + 1 + boundaries[index]) === true) stop = true;
    return false;
  });
}

/** Where a piece of visible text sits in the document (its first occurrence inside one paragraph). */
function findVisible(doc: ProseNode, text: string) {
  let found: {from: number; to: number} | null = null;
  if (!text) return found;
  eachTextblock(doc, (visible, positionOf) => {
    const at = visible.indexOf(text);
    if (at < 0) return false;
    found = {from: positionOf(at), to: positionOf(at + text.length)};
    return true;
  });
  return found as {from: number; to: number} | null;
}

function findingDecorations(doc: ProseNode, state: FindingMarkState) {
  if (!state.marks.length) return DecorationSet.empty;
  const decorations: Decoration[] = [];
  const pending = new Map(state.marks.map((mark) => [mark.id, mark]));
  eachTextblock(doc, (visible, positionOf) => {
    for (const mark of [...pending.values()]) {
      const at = mark.text ? visible.indexOf(mark.text) : -1;
      if (at < 0) continue;
      pending.delete(mark.id);
      const from = positionOf(at), to = positionOf(at + mark.text.length);
      const flags = `${mark.active ? " active" : ""}${mark.hovered ? " hovered" : ""}${mark.done ? " done" : ""}${mark.reveal ? " reveal" : ""}`;
      decorations.push(Decoration.inline(from, to, {class: `finding-mark tone-${mark.tone}${flags}`, "data-finding": mark.id, ...(mark.reveal ? {style: `--i: ${mark.index - 1}`} : {})}));
      decorations.push(Decoration.widget(to, () => {
        const badge = document.createElement("button");
        badge.type = "button";
        badge.className = `finding-badge${flags}`;
        if (mark.reveal) badge.style.setProperty("--i", String(mark.index - 1));
        badge.dataset.finding = mark.id;
        badge.textContent = String(mark.index);
        badge.contentEditable = "false";
        badge.setAttribute("aria-label", `第 ${mark.index} 处${mark.done ? "（已处理）" : ""}`);
        badge.addEventListener("mousedown", (event) => { event.preventDefault(); state.pick?.(mark.id); });
        badge.addEventListener("keydown", (event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); state.pick?.(mark.id); } });
        return badge;
      }, {side: 1, ignoreSelection: true, key: `finding-${mark.id}-${mark.index}${flags}`}));
    }
    return pending.size === 0;
  });
  return DecorationSet.create(doc, decorations);
}

const FindingMarks = Extension.create({
  name: "findingMarks",
  addProseMirrorPlugins() {
    return [new Plugin<FindingMarkState>({
      key: findingMarkKey,
      state: {
        init: () => ({marks: [], pick: null}),
        apply: (tr, value) => (tr.getMeta(findingMarkKey) as FindingMarkState | undefined) ?? value,
      },
      props: {
        decorations: (editorState) => {
          const state = findingMarkKey.getState(editorState);
          return state ? findingDecorations(editorState.doc, state) : DecorationSet.empty;
        },
      },
    })];
  },
});

/** Short-lived highlights (a pulse, a strike-through, the glow of new words). They follow edits
    and remove themselves; they never touch the text. */
type FlashMeta = {add?: {from: number; to: number; className: string; key: string}; remove?: string};
const flashKey = new PluginKey<DecorationSet>("flashes");
const Flashes = Extension.create({
  name: "flashes",
  addProseMirrorPlugins() {
    return [new Plugin<DecorationSet>({
      key: flashKey,
      state: {
        init: () => DecorationSet.empty,
        apply: (tr, set) => {
          let next = set.map(tr.mapping, tr.doc);
          const meta = tr.getMeta(flashKey) as FlashMeta | undefined;
          if (meta?.remove) next = next.remove(next.find(undefined, undefined, (spec) => spec.key === meta.remove));
          if (meta?.add) next = next.add(tr.doc, [Decoration.inline(meta.add.from, meta.add.to, {class: meta.add.className}, {key: meta.add.key})]);
          return next;
        },
      },
      props: {decorations: (state) => flashKey.getState(state)},
    })];
  },
});

const reduceMotion = () => typeof window !== "undefined" && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
let flashCounter = 0;

/** Highlight a piece of text in an editor for a moment with one of the motion classes. */
export function flashText(targetId: string, text: string, className: string, ms: number) {
  const editor = editors.get(targetId)?.editor;
  if (!editor || editor.isDestroyed || reduceMotion()) return;
  const range = findVisible(editor.state.doc, text);
  if (!range) return;
  const key = `flash-${(flashCounter += 1)}`;
  editor.view.dispatch(editor.state.tr.setMeta(flashKey, {add: {...range, className, key}}).setMeta("addToHistory", false));
  window.setTimeout(() => {
    if (!editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(flashKey, {remove: key}).setMeta("addToHistory", false));
  }, ms);
}

/** 改字: strike the old words through, then let `commit` replace them and make the new words glow.
    `commit` does the real replacement and reports whether it worked. */
export function rewriteDraftText(targetId: string, before: string, after: string, commit: () => boolean): Promise<boolean> {
  const editor = editors.get(targetId)?.editor;
  const range = editor && !editor.isDestroyed ? findVisible(editor.state.doc, before) : null;
  const glow = () => window.setTimeout(() => flashText(targetId, after, "rewrite-fresh", 1800), 60);
  if (!editor || !range || reduceMotion()) {
    const ok = commit();
    if (ok) glow();
    return Promise.resolve(ok);
  }
  const key = `strike-${(flashCounter += 1)}`;
  editor.view.dispatch(editor.state.tr.setMeta(flashKey, {add: {...range, className: "rewrite-strike", key}}).setMeta("addToHistory", false));
  return new Promise((resolve) => window.setTimeout(() => {
    if (!editor.isDestroyed) editor.view.dispatch(editor.state.tr.setMeta(flashKey, {remove: key}).setMeta("addToHistory", false));
    const ok = commit();
    if (ok) glow();
    resolve(ok);
  }, 560));
}

export function RichDraftEditor({id, value, format, disabled, label, placeholder, onChange, marks, onPickMark}: {
  id: string;
  value: string;
  format: DraftBodyFormat;
  disabled: boolean;
  label: string;
  placeholder?: string;
  onChange: (body: string, format: DraftBodyFormat) => void;
  /** Sentences to highlight with a numbered badge; clicking a badge calls onPickMark. */
  marks?: FindingMark[];
  onPickMark?: (id: string) => void;
}) {
  const lastValue = useRef(value);
  const lastFormat = useRef(format);
  const formatRef = useRef(format);
  const newlineRef = useRef(value.includes("\r\n") ? "\r\n" : "\n");
  const change = useRef(onChange);
  const editor = useEditor({
    extensions: [supportedEditorKit, Markdown.configure({markedOptions: {breaks: true}}), FindingMarks, Flashes],
    immediatelyRender: false,
    content: format === "markdown" ? value : plainDocument(value),
    contentType: format === "markdown" ? "markdown" : undefined,
    editable: !disabled,
    editorProps: {attributes: {id, role: "textbox", "aria-label": label, "aria-multiline": "true", "aria-readonly": String(disabled), class: "rich-draft-body", "data-writing-focus": "", tabindex: "0", spellcheck: "false", "data-placeholder": placeholder ?? "", "data-body-format": format}},
    onUpdate: ({editor: current}) => {
      if (formatRef.current === "plain_text" && hasRichStructure(current)) markAsMarkdown(current, formatRef);
      const nextFormat = formatRef.current;
      const body = nextFormat === "markdown" ? markdownText(current) : plainText(current, newlineRef.current);
      lastValue.current = body;
      lastFormat.current = nextFormat;
      change.current(body, nextFormat);
    },
    onCreate: ({editor: current}) => {
      if (formatRef.current === "markdown") loadMarkdown(current, value);
    },
    onSelectionUpdate: notify,
    onTransaction: notify,
  });
  useEffect(() => {change.current = onChange;}, [onChange]);
  const pickRef = useRef(onPickMark);
  useEffect(() => {pickRef.current = onPickMark;}, [onPickMark]);
  const markKey = JSON.stringify(marks ?? []);
  useEffect(() => {
    if (!editor || editor.isDestroyed) return;
    const next: FindingMarkState = {marks: JSON.parse(markKey) as FindingMark[], pick: (markId) => pickRef.current?.(markId)};
    editor.view.dispatch(editor.state.tr.setMeta(findingMarkKey, next).setMeta("addToHistory", false));
  }, [editor, markKey]);
  useEffect(() => {
    if (!editor) return;
    const binding = {
      editor,
      promoteToMarkdown: () => {
        markAsMarkdown(editor, formatRef);
        lastFormat.current = "markdown";
      },
    };
    editors.set(id, binding);
    notify();
    return () => {if (editors.get(id) === binding) editors.delete(id); notify();};
  }, [editor, id]);
  useEffect(() => {
    if (!editor) return;
    editor.setEditable(!disabled, false);
    editor.setOptions({editorProps: {attributes: {...editor.options.editorProps.attributes, "aria-readonly": String(disabled), "aria-label": label}}});
  }, [editor, disabled, label]);
  useEffect(() => {
    if (!editor || (lastValue.current === value && lastFormat.current === format)) return;
    lastValue.current = value;
    lastFormat.current = format;
    formatRef.current = format;
    newlineRef.current = value.includes("\r\n") ? "\r\n" : "\n";
    if (format === "markdown") {
      loadMarkdown(editor, value);
    } else {
      editor.commands.setContent(plainDocument(value), {emitUpdate: false});
    }
    editor.setOptions({editorProps: {attributes: {...editor.options.editorProps.attributes, "data-body-format": format}}});
    notify();
  }, [editor, format, value]);
  return <EditorContent editor={editor} className="rich-draft-host" />;
}

export function WritingTools({targetId, disabled}: {targetId: string; disabled: boolean; onChange?: (body: string) => void}) {
  const [, refresh] = useState(0);
  useEffect(() => {const update = () => refresh((value) => value + 1); subscribers.add(update); return () => {subscribers.delete(update);};}, []);
  const binding = editors.get(targetId);
  const editor = binding?.editor;
  function apply(tool: typeof tools[number][0]) {
    if (!editor?.isEditable || disabled) return;
    binding?.promoteToMarkdown();
    const chain = editor.chain().focus();
    if (tool === "bold") chain.toggleBold().run();
    else if (tool === "italic") chain.toggleItalic().run();
    else if (tool === "blockquote") chain.toggleBlockquote().run();
    else chain.toggleBulletList().run();
  }
  return <div className="writing-tools" role="group" aria-label="写作工具">
    {tools.map(([key, label, icon]) => <button key={key} type="button" className={`writing-tool tool-${key}`}
      title={label} aria-label={label} aria-pressed={editor?.isActive(key) ?? false} disabled={disabled || !editor}
      onMouseDown={(event) => event.preventDefault()} onClick={() => apply(key)}>{icon}</button>)}
  </div>;
}
