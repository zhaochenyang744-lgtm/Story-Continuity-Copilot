import { askView } from "./assistant-mock";

// The served tasks of the 38a specs and of the pictures (assistant-38a-shots.spec.ts).

export const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();
export const passage = (chapter: number, title: string, text: string, over: Record<string, unknown> = {}) => ({ kind: "passage", chapter_number: chapter, chapter_title: title, start: 0, end: text.length, text, cited: true, ...over });

export const LONG_PASSAGE = `${Array.from({ length: 24 }, (_, at) => `傍晚的仓道里一直很安静，第${at + 1}遍巡查没有任何异常。`).join("")}下午老周送来一张补充申请回执。北潮闸没有关闭，雾钟却响了一次。她把这件事记在了小本上。`;
export const recapSources = {
  R1: passage(10, "第十章 五点四十分", LONG_PASSAGE),
  R2: { kind: "foreshadow", chapter_number: 5, chapter_title: "第五章 白色渡船", start: null, end: null, text: "廊桥钥匙的指向：「廊桥钥匙」这个代号的含义，还没核明。", cited: true },
  R3: { kind: "fact", chapter_number: 10, chapter_title: "第十章 五点四十分", start: null, end: null, text: "温岚：截至第 10 章末仍握着黄铜罗盘", cited: true, anchor: { text: "温岚仍握着黄铜罗盘。", chapter_number: 10 } },
  R4: { kind: "plan", chapter_number: null, chapter_title: null, start: null, end: null, text: "第 11 章：温岚把罗盘收进随身袋", cited: true },
  R5: passage(4, "第四章 廊桥", "温岚没有问那个代号指什么，只是把钥匙翻过来看了看。"),
};
export const recapView = (id: string, notChecked: string[], over: Record<string, unknown> = {}) => ({
  ...askView({ id, kind: "recap", question: null, context: { page: "writing" }, created_at: ago(60), completed_at: ago(50), started_at: ago(58), coverage: { checked: ["第 1–10 章正文"], not_checked: notChecked } }),
  answer: {
    kind: "recap", chapter_number: 11,
    sections: {
      previous_ending: [{ summary: "上一章停在雾钟响了一次，北潮闸却没有关。", refs: ["R1"] }],
      character_state: [{ summary: "温岚仍握着黄铜罗盘。", refs: ["R3"] }],
      open_threads: [{ summary: "「廊桥钥匙」这个代号的含义还没核明。", refs: ["R2", "R5"] }],
      plan: [{ summary: "温岚把罗盘收进随身袋。", refs: ["R4"] }],
    },
  },
  sources: recapSources,
  ...over,
});

export const askSources = {
  R1: passage(9, "第九章 仓道的高台", "苏岑把罗盘交给温岚，说“你先替我收着”。"),
  R2: passage(10, "第十章 五点四十分", "温岚把罗盘放进抽屉，锁上了。"),
};
export const noted = (id: string, note: string, over: Record<string, unknown> = {}) => askView({
  id, question: "罗盘现在在谁手里？", sources: askSources, created_at: ago(70), started_at: ago(68), completed_at: ago(64),
  answer: { status: "answered", note, sentences: [{ text: "罗盘在温岚手里。", refs: ["R2"] }, { text: "第 9 章苏岑把它交了出去。", refs: ["R1"] }] },
  coverage: { checked: ["第 1–10 章正文", "已确认事实"], not_checked: ["计划"] },
  ...over,
});
