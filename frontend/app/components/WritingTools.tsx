"use client";

import { useEffect, useRef, useState } from "react";
import { Editor, EditorContent, useEditor } from "@tiptap/react";
import type { JSONContent } from "@tiptap/core";
import StarterKit from "@tiptap/starter-kit";
import { Markdown } from "@tiptap/markdown";
import type { DraftBodyFormat } from "../model";

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
  const matches: {from: number; to: number}[] = [];
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
      matches.push({from: position + 1 + boundaries[index], to: position + 1 + boundaries[index + before.length]});
    }
    return false;
  });
  if (matches.length !== 1) return false;
  return editor.chain().focus().command(({tr}) => {
    const parts = after.replace(/\r\n/g, "\n").split("\n");
    const content = parts.flatMap((part, index) => [
      ...(index ? [editor.schema.nodes.hardBreak.create()] : []),
      ...(part ? [editor.schema.text(part)] : []),
    ]);
    if (content.length) tr.replaceWith(matches[0].from, matches[0].to, content);
    else tr.delete(matches[0].from, matches[0].to);
    return true;
  }).run();
}

export function RichDraftEditor({id, value, format, disabled, label, placeholder, onChange}: {
  id: string;
  value: string;
  format: DraftBodyFormat;
  disabled: boolean;
  label: string;
  placeholder?: string;
  onChange: (body: string, format: DraftBodyFormat) => void;
}) {
  const lastValue = useRef(value);
  const lastFormat = useRef(format);
  const formatRef = useRef(format);
  const newlineRef = useRef(value.includes("\r\n") ? "\r\n" : "\n");
  const change = useRef(onChange);
  const editor = useEditor({
    extensions: [supportedEditorKit, Markdown.configure({markedOptions: {breaks: true}})],
    immediatelyRender: false,
    content: format === "markdown" ? value : plainDocument(value),
    contentType: format === "markdown" ? "markdown" : undefined,
    editable: !disabled,
    editorProps: {attributes: {id, role: "textbox", "aria-label": label, "aria-multiline": "true", class: "rich-draft-body", tabindex: "0", spellcheck: "false", "data-placeholder": placeholder ?? "", "data-body-format": format}},
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
  useEffect(() => {editor?.setEditable(!disabled, false);}, [editor, disabled]);
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
