"use client";

import { useState } from "react";
import { RichDraftEditor, WritingTools, replaceVisibleDraftText } from "../../app/client/editor";

const cases = {
  bold: { body: "**旧句**", before: "旧句", after: "新句" },
  italic: { body: "*旧句*", before: "旧句", after: "新句" },
  list: { body: "- **旧句**", before: "旧句", after: "新句" },
  quote: { body: "> *旧句*", before: "旧句", after: "新句" },
  mixed: { body: "**旧**句", before: "旧句", after: "新句" },
  newline: { body: "第一句  \n第二句", before: "第一句\n第二句", after: "新句" },
  crlf: { body: "第一句\r\n第二句", before: "第一句\r\n第二句", after: "新句" },
  repeatedText: { body: "旧句。旧句。", before: "旧句", after: "新句" },
  repeatedParagraph: { body: "旧句。\n\n旧句。", before: "旧句", after: "新句" },
} as const;

type Case = keyof typeof cases;

export function RichSuggestionHarness() {
  const [name, setName] = useState<Case>("bold");
  const [value, setValue] = useState<string>(cases.bold.body);
  const [result, setResult] = useState("未应用");
  const [revision, setRevision] = useState(0);
  const select = (next: Case) => { setName(next); setValue(cases[next].body); setResult("未应用"); setRevision((old) => old + 1); };
  return <main style={{maxWidth:760,margin:"24px auto",padding:16}}>
    <h1>富文本建议替换浏览器测试</h1><p>隔离测试页；调用实际 WritingTools 替换函数，不连接作品数据。</p>
    <label htmlFor="rich-case">场景</label><select id="rich-case" value={name} onChange={(event) => select(event.target.value as Case)}>{Object.keys(cases).map((key) => <option key={key} value={key}>{key}</option>)}</select>
    <WritingTools targetId="rich-test-body" disabled={false} />
    <RichDraftEditor key={revision} id="rich-test-body" label="富文本测试正文" value={value} format="markdown" disabled={false} onChange={(body) => setValue(body)} />
    <button type="button" onClick={() => setResult(replaceVisibleDraftText("rich-test-body",cases[name].before,cases[name].after) ? "已放入未保存正文" : "已拒绝，正文不变，需人工处理")}>采用建议</button>
    <p role="status">{result}</p><pre data-testid="serialized-body">{value}</pre>
  </main>;
}
