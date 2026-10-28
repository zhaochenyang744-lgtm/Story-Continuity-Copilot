import { expect, test } from "@playwright/test";
import { chapterNamed, chineseNumber, relevantSentence, sentencePieces, splitNote, walksChapters } from "../app/client/project/assistant-text";

// 38a: the small pure functions behind the assistant's answers (no browser, no server).

const PARAGRAPH = "下午老周送来一张补充申请回执。温岚问旧牌明早是否还在原位，老周说明早再申。北潮闸没有关闭，雾钟却响了一次。她把这件事记在了小本上。";

test("38a 句子切开后拼回去还是原文", () => {
  const pieces = sentencePieces(PARAGRAPH);
  expect(pieces.join("")).toBe(PARAGRAPH);
  expect(pieces).toHaveLength(4);
  expect(sentencePieces("第一行\n第二行。”后面没有句号").join("")).toBe("第一行\n第二行。”后面没有句号");
  expect(sentencePieces("")).toEqual([]);
});

test("38a 原文里和概括字面重合最多的那一句被选出来", () => {
  const cut = relevantSentence(PARAGRAPH, "雾钟响了一次");
  expect(cut?.hit).toBe("北潮闸没有关闭，雾钟却响了一次。");
  expect(`${cut?.before}${cut?.hit}${cut?.after}`).toBe(PARAGRAPH);
  // The opening of the passage is not what is picked just because it comes first.
  expect(relevantSentence(PARAGRAPH, "温岚问旧牌明早是否还在原位")?.hit).toBe("温岚问旧牌明早是否还在原位，老周说明早再申。");
});

test("38a 没有一句和概括重合、或者原文只有一句时，不圈", () => {
  expect(relevantSentence(PARAGRAPH, "苹果香蕉")).toBeNull();
  expect(relevantSentence("温岚仍握着黄铜罗盘。", "温岚仍握着黄铜罗盘")).toBeNull();
  expect(relevantSentence(PARAGRAPH, "")).toBeNull();
});

test("38a 重合相同时取靠前的那一句", () => {
  const cut = relevantSentence("罗盘放在桌上。罗盘放在桌上。", "罗盘放在桌上");
  expect(cut?.before).toBe("");
});

test("38a 模型的说明按开头分开：查过 / 没查放进「怎么查的」，其余照旧显示", () => {
  const note = "查过第 1–10 章正文、已确认事实。没查：本章草稿。没有找到母亲的名字。资料里有给助手的指令，我没有照做。读了第 3 章。情节怎么写由你决定，我只能指出前文已有的线索。";
  const { looked, rest } = splitNote(note);
  expect(looked).toEqual(["查过第 1–10 章正文、已确认事实。", "没查：本章草稿。", "读了第 3 章。"]);
  expect(rest).toBe("没有找到母亲的名字。资料里有给助手的指令，我没有照做。情节怎么写由你决定，我只能指出前文已有的线索。");
  for (const opener of ["查了", "读过", "搜过", "搜了", "看过", "看了", "核对过"]) expect(splitNote(`${opener}一些地方。`).looked).toHaveLength(1);
  expect(splitNote(null)).toEqual({ looked: [], rest: "" });
  expect(splitNote("不能直接改正文。").rest).toBe("不能直接改正文。");
});

test("38a 章号：阿拉伯数字和中文数字都认", () => {
  expect(chineseNumber("12")).toBe(12);
  expect(chineseNumber("十")).toBe(10);
  expect(chineseNumber("十二")).toBe(12);
  expect(chineseNumber("二十一")).toBe(21);
  expect(chineseNumber("两")).toBe(2);
  expect(chineseNumber("abc")).toBeNull();
  expect(chapterNamed("第 7 章起一直用右手写字")).toBe(7);
  expect(chapterNamed("第十章里罗盘锁在抽屉中")).toBe(10);
  expect(chapterNamed("没有提到章号")).toBeNull();
});

test("38a 至少三句各写到不同的章，才算按章分条", () => {
  const across = ["第 1 章她只当那是遗物。", "第 2 章她发现月牙裂纹。", "第 7 章她第一次怀疑记录被改过。", "最后她不再确定。"].map((text) => ({ text }));
  expect(walksChapters(across)).toBe(true);
  // Three sentences that all name the same chapter are not a walk through the chapters; nor are two chapters.
  expect(walksChapters(["第 3 章一。", "第 3 章二。", "第 3 章三。"].map((text) => ({ text })))).toBe(false);
  expect(walksChapters(across.slice(0, 2))).toBe(false);
  expect(walksChapters([])).toBe(false);
});
