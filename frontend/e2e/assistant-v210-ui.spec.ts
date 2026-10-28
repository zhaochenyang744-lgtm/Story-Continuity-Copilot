import { mkdir } from "node:fs/promises";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { expect, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { ask, box, finished, openAssistantTab, select, tasks, thread, toolbar, topbarAssistant } from "./support/assistant";
import { askView, runningView, serveTasks } from "./support/assistant-mock";
import { cardOf, changeItem, changeView, EDIT_THREAD_ASK, itemOf, openCard, openLedger, threadsView } from "./support/assistant-change";
import { theme } from "./support/pages";
import { findings, run, selectIssue, setup } from "./support/writing";

// v2.1 unified interface, the assistant and the writing page (task 18): how an answer is laid out, the line above it, the box, the change
// card, and the writing page's column. The answers that carry a `label` and a `lead` are served by hand (the test model writes neither); the
// rest runs on the real server. Pictures for the delivery report are taken only when ASSISTANT_SHOTS_DIR is set.

const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();
const rect = (locator: Locator) => locator.evaluate((node) => { const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height }; });
const style = (locator: Locator, property: string) => locator.evaluate((node, name) => getComputedStyle(node).getPropertyValue(name), property);

async function snap(page: Page, name: string) {
  const directory = process.env.ASSISTANT_SHOTS_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" });
}
/** The assistant on the writing page: the column's tab on a wide window, the 助手 pane of a phone. */
async function showAssistant(page: Page) {
  if ((page.viewportSize()?.width ?? 1440) < 1024) await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
  else await openAssistantTab(page);
}
/** The same state at 1440 and 390, by day and by night. `open` brings the state up at the width it is given. */
async function photograph(page: Page, name: string, open: () => Promise<void>, sizes: [number, number][] = [[1440, 1000], [390, 1500]]) {
  if (!process.env.ASSISTANT_SHOTS_DIR) return;
  for (const [width, height] of sizes) {
    for (const mode of ["day", "night"] as const) {
      await page.setViewportSize({ width, height });
      // The drawer covers the theme switch: it is closed for the switch and opened again.
      const drawer = page.getByRole("dialog", { name: "助手", exact: true });
      const wasOpen = (await drawer.count()) > 0;
      if (wasOpen) { await page.getByRole("button", { name: "关闭助手", exact: true }).click(); await expect(drawer).toHaveCount(0); }
      await theme(page, mode);
      if (wasOpen) { await topbarAssistant(page).click(); await expect(thread(page)).toBeVisible(); }
      await open();
      await snap(page, `${name}-${width}-${mode === "day" ? "浅色" : "深色"}`);
    }
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  }
}

const sources = {
  R1: { kind: "passage", chapter_number: 3, chapter_title: "第三章 移交单", start: 10, end: 40, text: "移交单上夹着一张窄纸，纸边被海风吹得发卷。", cited: true },
  R2: { kind: "passage", chapter_number: 3, chapter_title: "第三章 移交单", start: 60, end: 90, text: "窄纸上只写着一个数字，被人用指甲划去了。", cited: true },
  R3: { kind: "passage", chapter_number: 5, chapter_title: "第五章 白色渡船", start: 20, end: 60, text: "白色渡船靠岸时，船舷上的署名已经被油漆盖住。", cited: true },
  R4: { kind: "passage", chapter_number: 6, chapter_title: "第六章 廊桥", start: 5, end: 40, text: "苏岑把廊桥的钥匙收进了外套内袋，没有再拿出来。", cited: true },
  R5: { kind: "passage", chapter_number: 7, chapter_title: "第七章 旧尺", start: 5, end: 40, text: "旧尺的零点被人改过，刻度比原来短了一格。", cited: true },
};
/** A list answer: a lead and five points, each with its label; two points rest on neighbouring sources (3–4) and one on two that are not. */
const listView = askView({
  id: "atask-list", question: "现在还有哪些伏笔没收？", created_at: ago(300), completed_at: ago(280), started_at: ago(298), sources,
  answer: {
    status: "answered", note: null,
    sentences: [
      { text: "现在还有 5 条伏笔没收，伏笔记录里都还标着“已埋设”。", refs: ["R1"], lead: true },
      { text: "移交单上的窄纸第 3 章埋下，之后没有写到它从哪来。", refs: ["R2"], label: "移交单上的窄纸" },
      { text: "白色渡船的署名第 5 章埋下，第 8 章又提到一次，仍没有交代是谁。", refs: ["R3", "R4"], label: "白色渡船的署名" },
      { text: "廊桥钥匙第 6 章苏岑收起钥匙，后文没有再用到。", refs: ["R4"], label: "廊桥钥匙" },
      { text: "旧尺零点第 7 章发现零点被改过，原因还没写。", refs: ["R5", "R1"], label: "旧尺零点" },
    ],
  },
  coverage: { checked: ["第 1–10 章正文", "伏笔记录"], not_checked: ["本章草稿"] },
});
/** The same facts without a lead and with only two labels: it stays a paragraph. */
const paragraphView = askView({
  id: "atask-paragraph", question: "窄纸是谁放的？", created_at: ago(200), completed_at: ago(190), started_at: ago(198), sources,
  answer: {
    status: "answered", note: null,
    sentences: [
      { text: "窄纸夹在第 3 章的移交单里。", refs: ["R1"], label: "窄纸" },
      { text: "上面的数字被人划去了。", refs: ["R2"], label: "数字" },
      { text: "正文没有写是谁放的。", refs: [] },
    ],
  },
});
const notFoundView = askView({
  id: "atask-notfound", question: "苏岑小时候养的那只猫叫什么名字？", created_at: ago(120), completed_at: ago(110), started_at: ago(118), sources: {},
  answer: { status: "not_found", sentences: [], note: "查过第 1–10 章正文（搜过「猫」「小时候」）和苏岑的事实，没有找到。" },
  coverage: { checked: ["第 1–10 章正文（搜过：猫、小时候）", "苏岑的事实"], not_checked: ["本章草稿"] },
});
const editBefore = "旧潮位数字被覆贴，覆贴的人还不知道，不预设改动出于恶意。";
const cardItems = (over: Record<string, unknown> = {}) => [
  changeItem({ id: "achange-1", label: "C1", kind: "add_fact", title: "仓道里的旧潮位牌", before: "资料里没有", after: "背板至第 10 章尚未拆开（第 10 章）", editable: true, value: "背板至第 10 章尚未拆开",
    // The very passage the answer's own mark (R3) cites: the card shows it, the list under the answer does not.
    evidence: [{ chapter_number: 10, chapter_title: "第十章 五点四十分", start: 120, end: 150, text: "温岚把罗盘放进抽屉，锁上了。" }], ...over,
  }),
  changeItem({
    id: "achange-2", label: "C2", kind: "edit_thread", title: "移交单上的窄纸", before: editBefore, after: `${editBefore}背板至第 10 章仍未拆开。`, editable: true, value: `${editBefore}背板至第 10 章仍未拆开。`,
    evidence: [], request_words: "窄纸那条伏笔的说明也补上这句", ...over,
  }),
];

async function withThread(page: Page, views: unknown[], tab: "workspace" | "overview" = "overview") {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => views);
  await openTab(page, id, tab);
  if (tab === "workspace") await openAssistantTab(page);
  else { await topbarAssistant(page).click(); await expect(thread(page)).toBeVisible(); }
  await expect(thread(page).locator("[data-task]")).toHaveCount(views.length);
  return id;
}

test("18 回答：带 lead 和三个以上 label 的排成分点，标签加粗，多个出处合并成一个标记；不带的仍是段落", async ({ page }) => {
  await withThread(page, [listView, paragraphView]);
  const list = tasks(page).first();
  const answer = list.locator(".a-answer");
  await expect(answer).toHaveAttribute("data-layout", "points");
  await expect(answer.locator(".a-lead")).toContainText("现在还有 5 条伏笔没收");
  await expect(answer.locator(".a-points > li")).toHaveCount(4);
  expect(await answer.locator(".a-points b").allTextContents()).toEqual(["移交单上的窄纸", "白色渡船的署名", "廊桥钥匙", "旧尺零点"]);
  expect(await style(answer.locator(".a-points b").first(), "font-weight")).toBe("700");
  // The sentences are shown as they were written: the label is a stretch of the sentence, not an addition to it.
  await expect(answer.locator(".a-points > li").nth(1)).toHaveText(/^白色渡船的署名第 5 章埋下，第 8 章又提到一次，仍没有交代是谁。/);
  // One mark to a sentence, however many sources: 3–4 for neighbours, 1、5 for the rest.
  for (let at = 0; at < 4; at += 1) expect(await answer.locator(".a-points > li").nth(at).locator(".a-cite").count()).toBe(1);
  expect(await answer.locator(".a-points > li").nth(0).locator(".a-cite button").textContent()).toBe("2");
  expect(await answer.locator(".a-points > li").nth(1).locator(".a-cite button").textContent()).toBe("3–4");
  expect(await answer.locator(".a-points > li").nth(3).locator(".a-cite button").textContent()).toBe("1、5");
  // The lead is body text, not a bullet.
  expect(await answer.locator(".a-lead").evaluate((node) => getComputedStyle(node).display)).toBe("block");
  expect(await style(answer.locator(".a-lead"), "font-size")).toBe("14px");
  expect(await style(answer.locator(".a-points li").first(), "line-height")).toBe("23.8px");
  // Without a lead and with two labels, it stays one paragraph and nothing is bold.
  const other = tasks(page).nth(1).locator(".a-answer");
  await expect(other).toHaveAttribute("data-layout", "paragraph");
  await expect(other.locator(".a-points")).toHaveCount(0);
  await expect(other.locator("b")).toHaveCount(0);
  await expect(other.locator(".a-body .a-s")).toHaveCount(3);
  await expect(other.locator(".a-body .a-s").first()).toContainText("窄纸夹在第 3 章的移交单里。");
  await photograph(page, "01-列举回答", async () => {
    await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = 0; });
  });
});

test("18 回答：出处标记默认淡灰，悬停变蓝；一个标记的卡片里列出它的每个出处", async ({ page }) => {
  await withThread(page, [listView]);
  const mark = tasks(page).first().locator(".a-points > li").nth(1).locator(".a-cite > button");
  const faint = await mark.evaluate((node) => { const probe = document.createElement("i"); probe.style.color = "var(--c-faint-text)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(mark, "color")).toBe(faint);
  expect(await style(mark, "background-color")).toBe("rgba(0, 0, 0, 0)");
  await mark.hover();
  const blue = await mark.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-blue-text)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  await expect.poll(() => style(mark, "color")).toBe(blue);
  expect(await style(mark, "background-color")).not.toBe("rgba(0, 0, 0, 0)");
  const card = page.getByRole("group", { name: "出处 3–4" });
  await expect(card).toBeVisible();
  await expect(card.locator(".a-pop-one")).toHaveCount(2);
  await expect(card).toContainText("第 5 章");
  await expect(card).toContainText("第 6 章");
});

test("18 过程行：一行 11px 灰字，回答紧跟在问题下面；额度提示不在回答上面", async ({ page }) => {
  await withThread(page, [listView]);
  const task = tasks(page).first();
  const line = task.getByTestId("process-line");
  // 38a: no count of places on the line (it would sit next to 「出处 N 处」 and the two numbers would fight).
  await expect(line).toHaveText(/^问作品 · \d+ 秒$/);
  expect(await style(line.locator(".a-fold"), "font-size")).toBe("11px");
  expect((await rect(line)).height).toBeLessThanOrEqual(24);
  // Only one line stands between the question and the answer (the kind of use is in it; nothing else is).
  const question = await rect(task.locator(".a-ask"));
  const first = await rect(task.locator(".a-lead"));
  expect(first.top - question.bottom).toBeLessThanOrEqual(40);
  await expect(task.getByTestId("routed-line")).toHaveCount(0);
  await expect(task.locator(".a-kind, .a-head")).toHaveCount(0);
  // 38a: the line is a plain label; the steps open under 「怎么查的」.
  await expect(line.locator(".a-fold")).not.toHaveJSProperty("tagName", "BUTTON");
  await task.getByRole("button", { name: "怎么查的" }).click();
  await expect(task.locator(".a-proc")).toBeVisible();
  await expect(task.locator(".a-proc .a-act").first()).toBeVisible();
});

test("18 回答末尾：找不到时第一行由前端写，下面只有 note 和“没查”；出处默认收成一行，展开后一条一行", async ({ page }) => {
  await withThread(page, [listView, notFoundView]);
  const missing = tasks(page).nth(1);
  await expect(missing.getByTestId("not-found-line")).toHaveText("没有找到问题问到的内容。");
  expect(await style(missing.getByTestId("not-found-line"), "font-size")).toBe("14px");
  // 38a: the model's 「查过……」 sentence goes under 「怎么查的」; an answer that found nothing says what was not looked at in plain grey, under the answer.
  await expect(missing.locator(".a-answer-note")).toHaveCount(0);
  await expect(missing.getByTestId("not-checked")).toHaveText("没查：本章草稿。");
  expect(await style(missing.getByTestId("not-checked"), "font-weight")).not.toBe("700");
  await missing.getByRole("button", { name: "怎么查的" }).click();
  // The program's line says where it looked; the model's own sentence is not said a second time next to it.
  await expect(missing.getByTestId("how-checked").locator(".a-cover")).toHaveText("查过第 1–10 章正文（搜过：猫、小时候）、苏岑的事实。");
  // A found answer: 查过……；没查：…… is inside the fold, which is shut until it is asked for.
  const found = tasks(page).first();
  await expect(found.locator(".a-cover")).toHaveCount(0);
  await found.getByRole("button", { name: "怎么查的" }).click();
  await expect(found.locator(".a-cover")).toHaveText("查过第 1–10 章正文、伏笔记录；没查：本章草稿。");
  // Sources: folded to one line.
  const fold = found.getByRole("button", { name: /^出处 \d+ 处/ });
  await expect(fold).toHaveText("出处 5 处");
  await expect(found.locator(".a-sources")).toHaveCount(0);
  await fold.click();
  const rows = found.locator(".a-source .a-where");
  await expect(rows).toHaveCount(5);
  await expect(rows.first()).toHaveText(/^第 3 章 · 移交单/);
  await expect(found.locator(".a-source-body")).toHaveCount(0);
  await rows.first().click();
  const body = found.locator(".a-source-body .a-text");
  await expect(body).toHaveText("移交单上夹着一张窄纸，纸边被海风吹得发卷。");
  expect(await style(body, "font-family")).toContain("Serif");
  await photograph(page, "02-找不到", async () => {
    await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = node.scrollHeight; });
  });
});

test("18 轮次：轮与轮之间一条细线，线上写时间；追问接在上一轮下面，缩进并带竖线，没有自己的线", async ({ page }) => {
  const second = askView({ id: "atask-second", question: "旧尺是谁改的？", created_at: ago(100), completed_at: ago(90), started_at: ago(98), follow_up_of: "atask-list", follow_up_depth: 1, sources: {}, answer: { status: "not_found", sentences: [], note: null }, coverage: null });
  const days = (count: number) => new Date(Date.now() - count * 86_400_000).toISOString();
  const old = askView({ id: "atask-old", question: "很早以前的问题", created_at: days(4), completed_at: days(4), started_at: days(4), sources: {}, answer: { status: "not_found", sentences: [], note: null }, coverage: null });
  await withThread(page, [old, { ...listView, created_at: days(3) }, second, notFoundView]);
  const rules = thread(page).locator(".a-turn-rule");
  // old → list: a line with a date; list → second (a follow-up): none; second → notFound: a line with today's time.
  await expect(rules).toHaveCount(2);
  await expect(rules.first()).toHaveText(/^\d{1,2}月\d{1,2}日 \d{2}:\d{2}$/);
  await expect(rules.last()).toHaveText(/^今天 \d{2}:\d{2}$/);
  const follow = thread(page).locator('[data-task="atask-second"]');
  await expect(follow).toHaveClass(/a-follow/);
  expect(await style(follow, "margin-left")).toBe("12px");
  expect(await style(follow, "border-left-width")).toBe("2px");
});

test("18 写前回顾：字号和普通回答一套，出处是句末的角标，点开看全文", async ({ page }) => {
  const recap = {
    ...askView({ id: "atask-recap", kind: "recap", question: null, context: { page: "writing" }, created_at: ago(60), completed_at: ago(50), started_at: ago(58), coverage: { checked: ["第 1–10 章正文"], not_checked: ["本章草稿"] } }),
    answer: {
      kind: "recap", chapter_number: 11,
      sections: {
        previous_ending: [{ summary: "上一章停在苏岑把钥匙收进外套内袋，没有再拿出来。", refs: ["R4"] }],
        character_state: [{ summary: "苏岑的左腕有旧伤，第 7 章起一直用右手写字。", refs: ["R5", "R1"] }],
        open_threads: [{ summary: "移交单上的窄纸：数字被划去，来历没有交代。", refs: ["R2"] }],
        plan: [],
      },
    },
    sources,
  };
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => [recap]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const view = tasks(page).first();
  await expect(view.getByTestId("process-line")).toHaveText(/^写前回顾 · 第 11 章/);
  expect(await style(view.locator(".a-ri").first(), "font-size")).toBe("14px");
  // 38a: no grey quote line under an item; the passage is behind the mark at the end of the sentence, shown whole.
  await expect(view.locator(".a-ri-src, .a-quote-line")).toHaveCount(0);
  const mark = view.locator(".a-ri .a-cite > button").first();
  await mark.click();
  const quote = page.locator(".a-pop q").first();
  expect(await style(quote, "font-size")).toBe("12px");
  await expect(quote).toContainText("收进了外套内袋");
  await photograph(page, "06-写前回顾", async () => {
    await page.goto(`/projects/${id}/workspace`);
    await showAssistant(page);
  }, [[1440, 900], [390, 1500]]);
});

test("18 字号：助手里只用 14、13、12、11 四档", async ({ page }) => {
  const waiting = changeView(cardItems(), { id: "atask-fs" });
  await withThread(page, [listView, notFoundView, waiting]);
  const sizes = await thread(page).evaluate((root) => {
    const found = new Map<string, string>();
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    for (let node = walker.nextNode(); node; node = walker.nextNode()) {
      const text = (node.textContent ?? "").trim();
      const element = node.parentElement;
      if (!text || !element || element.closest(".sr-only, .a-skip, svg, option")) continue;
      const size = getComputedStyle(element).fontSize;
      if (!found.has(size)) found.set(size, text.slice(0, 20));
    }
    return Object.fromEntries(found);
  });
  expect(Object.keys(sizes).sort(), JSON.stringify(sizes)).toEqual(["11px", "12px", "13px", "14px"]);
});

test("18 操作行：点赞点踩是单色线条图标，和操作行文字同一种灰；没有 emoji", async ({ page }) => {
  await withThread(page, [listView]);
  const task = tasks(page).first();
  const up = task.getByRole("button", { name: "有用", exact: true });
  await expect(up.locator("svg")).toHaveCount(1);
  expect(await task.locator(".a-foot").textContent()).not.toMatch(/[\u{1F300}-\u{1FAFF}\u{2600}-\u{27BF}]/u);
  const muted = await task.locator(".a-foot").evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-muted)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(up, "color")).toBe(muted);
  expect(await style(task.getByRole("button", { name: "复制" }), "color")).toBe(muted);
});

test("18 额度用完：重新回答、接着问置灰，悬停写原因；写作页选中文字的工具条也置灰", async ({ page }) => {
  await startVisitor(page);
  const id = await sampleWorkId(page);
  await page.route("**/api/account/usage", async (route) => {
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: { account_type: "visitor", check_chars_per_check: 6000, checks_limit: 3, checks_remaining: 3, assistant_tasks_limit: 3, assistant_tasks_remaining: 0 }, request_id: "mock" }) });
  });
  await serveTasks(page, () => [listView]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const task = tasks(page).first();
  const reason = "访客可以在示例作品上问 3 次，今天已经用完";
  for (const name of ["重新回答", "接着问"]) {
    const control = task.getByRole("button", { name, exact: true });
    await expect(control).toBeDisabled();
    expect(await control.getAttribute("title")).toContain(reason);
  }
  await select(page, "#draft-body", 12);
  await expect(toolbar(page)).toBeVisible();
  for (const control of await toolbar(page).getByRole("button").all()) {
    await expect(control).toBeDisabled();
    expect(await control.getAttribute("title")).toContain(reason);
  }
});

test("18 变更卡片：白底、一圈细环的容器（没有边框），标题行、细线、底部按钮；长文本在一段里标出差异；依据收成一行；高风险有红边", async ({ page }) => {
  const abandon = changeItem({ id: "achange-3", label: "C3", kind: "abandon_thread", title: "廊桥钥匙", before: "已埋设", after: "已放弃", risk: "high", evidence: [], request_words: "廊桥钥匙我不追了", editable: false, value: null });
  await withThread(page, [changeView([...cardItems(), abandon])]);
  const card = cardOf(page);
  expect(await style(card, "border-top-width")).toBe("0px");
  expect(await style(card, "border-top-left-radius")).toBe("10px");
  expect(await style(card, "background-color")).toBe("rgb(255, 255, 255)");
  expect(await style(card, "box-shadow")).not.toBe("none");
  await expect(card.locator(".a-chg-head strong")).toHaveText("资料改动 · 3 条");
  await expect(card.locator(".a-chg-note-r")).toHaveText("确认后才会执行，可以撤销");
  const buttons = card.locator(".a-chg-foot button");
  await expect(buttons).toHaveText(["不要", "确认 3 条"]);
  // Items are set apart by a thin rule.
  expect(await style(itemOf(card, "C1"), "border-bottom-width")).toBe("1px");
  // The long note is one text with the added words marked; the short items use the arrow.
  const diff = itemOf(card, "C2").locator(".a-chg-diff");
  await expect(diff.locator("ins")).toContainText("背板至第 10 章仍未拆开。");
  await expect(diff).toContainText(editBefore);
  await expect(itemOf(card, "C2").locator(".chg-before")).toHaveCount(0);
  expect(await style(diff.locator("ins"), "text-decoration-line")).toBe("none");
  const wash = await diff.locator("ins").evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-ins)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(diff.locator("ins"), "background-color")).toBe(wash);
  await expect(itemOf(card, "C1").locator(".chg-before")).toContainText("资料里没有");
  await expect(itemOf(card, "C3").locator(".chg-before")).toContainText("已埋设");
  // 依据 is one folded line and appears once; without a passage it says the author's word is the ground.
  await expect(itemOf(card, "C1").getByTestId("change-basis").locator("button")).toHaveText("依据：第 10 章 · 五点四十分");
  await expect(itemOf(card, "C2").getByTestId("change-basis").locator("button")).toHaveText("依据：你的话");
  await expect(card.locator(".a-sources")).toHaveCount(0);
  await itemOf(card, "C1").getByTestId("change-basis").locator("button").click();
  await expect(itemOf(card, "C1").locator(".a-source")).toHaveCount(1);
  // The thread's own list of sources leaves out what the card already stands on.
  await expect(tasks(page).first().getByRole("button", { name: /^出处 \d+ 处/ })).toHaveCount(0);
  // A high-risk item has a red edge 3px wide.
  expect(await style(itemOf(card, "C3"), "box-shadow")).toMatch(/inset/);
  expect(await style(itemOf(card, "C3"), "box-shadow")).toMatch(/3px/);
  expect(await style(itemOf(card, "C1"), "box-shadow")).toBe("none");
  await photograph(page, "03a-变更卡片-确认前", async () => {
    await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = node.scrollHeight; });
  });
});

test("18 变更卡片：确认以后顶上换成“已写入资料 · 撤销”；没执行和已撤销的条目正文变淡，状态词对比度够，不再写“确认后才会执行”", async ({ page }) => {
  const when = ago(30);
  const written = cardItems({ status: "applied", decided_at: when, applied_at: when });
  await withThread(page, [changeView(written, { id: "atask-applied" })]);
  const card = cardOf(page);
  const done = card.getByTestId("change-written");
  await expect(done).toContainText("已写入资料 · 2 条");
  await expect(done.getByRole("button", { name: "撤销", exact: true })).toBeVisible();
  const tint = await done.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-blue-tint)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(done, "background-color")).toBe(tint);
  await expect(card.locator(".a-chg-note-r")).toHaveCount(0);
  await expect(card.locator(".a-chg-foot")).toHaveCount(0);
  await photograph(page, "03b-变更卡片-确认后", async () => {
    await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = node.scrollHeight; });
  });
});

test("18 变更卡片：已撤销和没执行的条目——状态词对比度至少 4.5:1，不再写“确认后才会执行”", async ({ page }) => {
  const undone = cardItems({ status: "undone", decided_at: ago(40), applied_at: ago(40), undone_at: ago(20) });
  const rejected = cardItems({ status: "rejected", decided_at: ago(40) });
  await withThread(page, [changeView(undone, { id: "atask-undone" }), changeView(rejected, { id: "atask-rejected", created_at: ago(10) })]);
  const contrast = (locator: Locator) => locator.evaluate((node) => {
    const parse = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 4).map(Number);
    const luminance = ([r, g, b]: number[]) => { const channel = (v: number) => { const s = v / 255; return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4; }; return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b); };
    let background = [0, 0, 0, 0];
    for (let at: Element | null = node; at; at = at.parentElement) { const color = parse(getComputedStyle(at).backgroundColor); if (color.length === 4 && color[3] > 0 || color.length === 3) { background = color; break; } }
    const text = parse(getComputedStyle(node).color);
    const [a, b] = [luminance(text), luminance(background)];
    return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
  });
  for (const [index, word] of [[0, "已撤销"], [1, "没有执行"]] as const) {
    const card = thread(page).getByRole("region", { name: "资料改动" }).nth(index);
    await expect(card.locator(".a-chg-note-r")).toHaveCount(0);
    await expect(card).not.toContainText("确认后才会执行");
    const state = card.locator(".a-chg-state").first();
    await expect(state).toHaveText(word);
    expect(await contrast(state), `${word}: the word itself`).toBeGreaterThanOrEqual(4.5);
    expect(await contrast(card.locator(".a-chg-diff").first()), "the quiet words are still readable").toBeGreaterThanOrEqual(4.5);
  }
  await photograph(page, "03c-变更卡片-撤销后", async () => {
    await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = 0; });
  });
});

test("18 变更卡片和改动记录：确认后顶上是“已写入资料 · 撤销”，撤销按钮和资料页改动记录里的是同一种；记录同时写确认和撤销的时间", async ({ page }) => {
  const id = await setup(page);
  const { card } = await openCard(page, id, EDIT_THREAD_ASK);
  await card.getByRole("button", { name: /^确认 \d+ 条$/ }).click();
  const done = card.getByTestId("change-written");
  await expect(done).toContainText("已写入资料");
  const inCard = done.getByRole("button", { name: "撤销", exact: true });
  await expect(inCard).toBeVisible();
  const looks = ["font-size", "font-weight", "color", "border-bottom-width", "border-bottom-style", "border-radius", "min-height", "background-color", "padding-left", "padding-right"];
  const cardLook = await inCard.evaluate((node, names) => Object.fromEntries(names.map((name) => [name, getComputedStyle(node).getPropertyValue(name)])), looks);
  const cardClass = await inCard.getAttribute("class");
  await threadsView(page, id);
  const ledger = await openLedger(page);
  const inLedger = ledger.getByRole("button", { name: "撤销", exact: true }).first();
  const ledgerLook = await inLedger.evaluate((node, names) => Object.fromEntries(names.map((name) => [name, getComputedStyle(node).getPropertyValue(name)])), looks);
  // The two buttons are the same component and look the same.
  expect(await inLedger.getAttribute("class")).toBe(cardClass);
  expect(cardLook).toEqual(ledgerLook);
  await inLedger.click();
  const entry = ledger.locator("li").first();
  await expect(entry.locator(".ledger-at")).toHaveCount(2);
  await expect(entry.locator(".ledger-at").first()).toHaveText(/^确认 /);
  await expect(entry.locator(".ledger-at").last()).toHaveText(/^撤销 /);
});

test("18 输入框：白底、没有边框、一圈细环加淡影，聚焦时环和外圈一起加深不变蓝；空着一行高，长高到六行再滚动；发送键是圆形", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => []);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  const frame = thread(page).locator("form.cx");
  const surface = await frame.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-surface)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(frame, "background-color")).toBe(surface);
  const ringOf = (name: string) => page.evaluate((token) => { const probe = document.createElement("i"); probe.style.cssText = `box-shadow: var(${token}); transition: none`; document.body.append(probe); const value = getComputedStyle(probe).boxShadow; probe.remove(); return value; }, name);
  await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; }" });
  // (The page puts the cursor in the box when the drawer opens; take it out to see the box at rest.)
  await box(page).evaluate((node) => (node as HTMLElement).blur());
  expect(await style(frame, "border-top-width")).toBe("0px");
  expect(await style(frame, "box-shadow")).toBe(await ringOf("--ring-rest"));
  expect(await style(frame, "border-top-left-radius")).toBe("10px");
  expect(await style(thread(page).locator(".a-compose"), "border-top-width")).toBe("0px");
  const field = box(page);
  const empty = await rect(field);
  expect(empty.height).toBeLessThanOrEqual(26);
  await field.focus();
  const blue = await frame.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-blue)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(frame, "box-shadow")).toBe(await ringOf("--ring-focus"));
  expect(await style(frame, "box-shadow")).not.toContain(blue);
  await field.fill("一\n二\n三");
  expect((await rect(field)).height).toBeGreaterThan(empty.height + 30);
  await field.fill(Array.from({ length: 12 }, (_, at) => `第 ${at + 1} 行`).join("\n"));
  const tall = await rect(field);
  expect(tall.height).toBeLessThanOrEqual(6 * 1.65 * 14 + 2);
  expect(await field.evaluate((node) => node.scrollHeight > node.clientHeight)).toBe(true);
  // The scrollbars of the box and of the conversation are thin ones of our own, and dark where the page is dark.
  const line0 = await frame.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-line)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  for (const target of [field, thread(page).locator(".a-thread")]) {
    expect(await style(target, "scrollbar-width")).toBe("thin");
    expect(await style(target, "scrollbar-color")).toContain(line0);
  }
  await page.evaluate(() => { document.documentElement.dataset.theme = "night"; });
  const lineNight = await frame.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-line)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(lineNight).not.toBe(line0);
  for (const target of [field, thread(page).locator(".a-thread")]) expect(await style(target, "scrollbar-color")).toContain(lineNight);
  await page.evaluate(() => { document.documentElement.dataset.theme = "day"; });
  // Controls: the + and the mode are one kind of small button; the arrow is a drawing, not a character.
  const plus = thread(page).getByRole("button", { name: "添加上下文", exact: true });
  const mode = thread(page).getByRole("button", { name: /^这次做什么：/ });
  expect((await rect(plus)).height).toBe(32);
  expect((await rect(mode)).height).toBe(32);
  expect(await plus.getAttribute("class")).toContain("cx-ghost");
  expect(await mode.getAttribute("class")).toContain("cx-ghost");
  expect(await style(mode, "border-top-width")).toBe("0px");
  await expect(mode.locator("svg")).toHaveCount(1);
  expect(await mode.textContent()).not.toContain("▼");
  // The send key: round, blue when it can send, a ring of the line colour when it cannot.
  const send = thread(page).getByRole("button", { name: "发送", exact: true });
  expect(await style(send, "border-top-left-radius")).toBe("50%");
  expect((await rect(send)).width).toBe(32);
  expect(await style(send, "background-color")).toBe(blue);
  await field.fill("");
  await expect(send).toBeDisabled();
  await expect.poll(() => style(send, "background-color")).toBe("rgba(0, 0, 0, 0)");
  const line = await frame.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-line)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(send, "border-top-color")).toBe(line);
  // The allowance is in the body face, 12px, under the frame at its right.
  const note = thread(page).locator(".cx-note");
  await field.evaluate((node) => (node as HTMLElement).blur());
  expect(await style(note, "font-size")).toBe("12px");
  expect(await style(note, "font-family")).not.toContain("Mono");
  const under = await rect(note);
  const framed = await rect(frame);
  expect(under.top).toBeGreaterThanOrEqual(framed.bottom - 1);
  expect(Math.abs(under.right - framed.right)).toBeLessThanOrEqual(2);
  await photograph(page, "04a-输入框-空", async () => { await box(page).evaluate((node) => (node as HTMLElement).blur()); });
  await photograph(page, "04b-输入框-输入中", async () => { await box(page).fill("现在还有哪些伏笔没收？是不是都已经交代了"); await box(page).focus(); });
});

test("18 输入框：模式菜单每项下面有说明，一轮结束后按钮回到“自动”", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await thread(page).getByRole("button", { name: "这次做什么：自动" }).click();
  const menu = thread(page).getByRole("menu", { name: "这次让助手做什么" });
  await expect(menu.getByRole("menuitemradio", { name: "问作品", exact: true })).toContainText("查正文和资料回答");
  await expect(menu.getByRole("menuitemradio", { name: "改资料", exact: true })).toContainText("提出改动，你确认后才执行");
  await menu.getByRole("menuitemradio", { name: "问作品", exact: true }).click();
  await ask(page, "苏岑知道罗盘被调包了吗？");
  await finished(page);
  await expect(thread(page).getByRole("button", { name: "这次做什么：自动", exact: true })).toBeVisible();
  // A question judged by the box does not leave 「自动 · 问作品」 on the button either.
  await ask(page, "罗盘现在在谁手里？");
  await finished(page, 2);
  await expect(thread(page).getByRole("button", { name: "这次做什么：自动", exact: true })).toBeVisible();
});

test("18 回车以后：问题马上进对话，输入框马上清空，对话里有一行“正在判断用法…”", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  let release: () => void = () => undefined;
  const held = new Promise<void>((resolve) => { release = resolve; });
  await page.route("**/assistant/route", async (route) => { await held; await route.continue(); });
  await box(page).fill("苏岑知道罗盘被调包了吗？");
  await box(page).press("Enter");
  await expect(box(page)).toHaveValue("");
  const pending = thread(page).getByTestId("route-pending");
  await expect(pending).toContainText("苏岑知道罗盘被调包了吗？");
  await expect(pending).toContainText("正在判断用法…");
  await expect(thread(page).getByRole("button", { name: "这次做什么：自动" })).toBeVisible();
  release();
  await finished(page);
  await expect(pending).toHaveCount(0);
  await expect(tasks(page)).toHaveCount(1);
});

test("18 输入框：任务运行中，发送键换成圆形的停止键，过程行写“正在查”和停止", async ({ page }) => {
  await withThread(page, [runningView("tool")]);
  const stop = thread(page).locator(".cx-send.stop");
  await expect(stop).toBeVisible();
  expect(await style(stop, "border-top-left-radius")).toBe("50%");
  expect((await rect(stop)).width).toBe(32);
  const line = tasks(page).first().getByTestId("process-line");
  await expect(line).toContainText("问作品 · 正在查");
  await expect(line.getByRole("button", { name: "停止", exact: true })).toBeVisible();
  await photograph(page, "04c-输入框-运行中", async () => {
    await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = node.scrollHeight; });
  });
});

test("18 判断用法的请求超过 15 秒没回来，就按“问作品”建任务，过程行写明", async ({ page }) => {
  test.setTimeout(120_000);
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await page.route("**/assistant/route", () => new Promise(() => undefined));
  const started = Date.now();
  await ask(page, "E2E_CHANGE_FACT 温岚那条事实过时了，按最后一章改一下");
  await expect(thread(page).getByTestId("route-pending")).toBeVisible();
  await expect(thread(page).locator("[data-task]")).toHaveCount(1, { timeout: 40_000 });
  expect(Date.now() - started).toBeGreaterThanOrEqual(14_500);
  await finished(page);
  const line = tasks(page).first().getByTestId("process-line");
  await expect(line).toContainText("没等到判断，按问作品处理");
  await expect(tasks(page).first().locator(".a-chg-card")).toHaveCount(0);
});

test("18 请求失败：红色系的提示条带“重试”，输入内容照旧保留", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await page.route(/\/assistant\/tasks$/, async (route) => { if (route.request().method() === "POST") await route.abort(); else await route.fallback(); });
  await box(page).fill("苏岑知道罗盘被调包了吗？");
  await box(page).press("Enter");
  const bar = thread(page).locator(".a-refused");
  await expect(bar).toBeVisible();
  await expect(box(page)).toHaveValue("苏岑知道罗盘被调包了吗？");
  const red = await bar.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-red-text)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  expect(await style(bar, "color")).toBe(red);
  expect(await style(bar, "border-top-color")).toBe(red);
  await expect(thread(page).getByTestId("route-pending")).toHaveCount(0);
  await page.unroute(/\/assistant\/tasks$/);
  await bar.getByRole("button", { name: "重试", exact: true }).click();
  await finished(page);
  await expect(box(page)).toHaveValue("");
});

for (const [width, height] of [[1440, 900], [1024, 768]] as const) {
  test(`18 写作页 ${width}×${height}：右栏从顶栏下面开始，高度等于视口减去顶栏；不滚动就能看到助手输入框`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await registerAccount(page, "a18");
    const id = await sampleWorkId(page);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    expect(await page.evaluate(() => window.scrollY)).toBe(0);
    const topbar = await rect(page.locator(".topbar"));
    const column = await rect(findings(page));
    expect(Math.abs(column.top - topbar.bottom)).toBeLessThanOrEqual(2);
    expect(Math.abs(column.height - (height - topbar.bottom))).toBeLessThanOrEqual(2);
    const form = await rect(thread(page).locator("form.cx"));
    expect(form.bottom, "the box is on the first screen").toBeLessThanOrEqual(height);
    expect(form.top).toBeGreaterThan(topbar.bottom);
    // The conversation scrolls in the middle, the box stays at the foot while the page is scrolled.
    await page.mouse.wheel(0, 600);
    const after = await rect(thread(page).locator("form.cx"));
    expect(Math.abs(after.bottom - form.bottom)).toBeLessThanOrEqual(1);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
    if (width === 1440) {
      await photograph(page, "05-写作页首屏", async () => { await page.goto(`/projects/${id}/workspace`); await expect(page.locator(".draft-head")).toBeVisible(); if ((page.viewportSize()?.width ?? 0) >= 1024) await openAssistantTab(page); }, [[1440, 900], [390, 844]]);
      await photograph(page, "05b-写作页助手窗格", async () => { await page.goto(`/projects/${id}/workspace`); await expect(page.locator(".draft-head")).toBeVisible(); await showAssistant(page); }, [[390, 844]]);
    }
  });
}

test("18 顶栏：写作页也有“助手”按钮，点它切到右栏的助手页签并把光标放进输入框；其他页照旧打开抽屉", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await openTab(page, id, "workspace");
  const tab = findings(page).getByRole("tab", { name: /^助手/ });
  await findings(page).getByRole("tab", { name: /^检查结果/ }).click();
  await expect(tab).toHaveAttribute("aria-selected", "false");
  await expect(topbarAssistant(page)).toBeVisible();
  await topbarAssistant(page).click();
  await expect(tab).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("dialog", { name: "助手", exact: true })).toHaveCount(0);
  await expect(box(page)).toBeFocused();
  // Already there: the cursor goes into the box again.
  await page.locator("body").click({ position: { x: 5, y: 300 } });
  await topbarAssistant(page).click();
  await expect(box(page)).toBeFocused();
  await openTab(page, id, "sources");
  await topbarAssistant(page).click();
  await expect(page.getByRole("dialog", { name: "助手", exact: true })).toBeVisible();
});

test("18 选中文字的工具条：放在选区下方，不探出正文栏左边", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await openTab(page, id, "workspace");
  await select(page, "#draft-body", 12);
  await expect(toolbar(page)).toBeVisible();
  const bar = await rect(toolbar(page));
  const selection = await page.evaluate(() => { const box = window.getSelection()!.getRangeAt(0).getBoundingClientRect(); return { top: box.top, bottom: box.bottom, left: box.left }; });
  const body = await rect(page.locator("#draft-body"));
  expect(bar.top).toBeGreaterThanOrEqual(selection.bottom);
  expect(bar.left).toBeGreaterThanOrEqual(body.left - 1);
});

test("18 示例作品里禁用的“让助手给改法”：原因写在按钮旁边", async ({ page }) => {
  const id = await setup(page);
  await selectIssue(page, (await run(page, id)).issues[0]);
  const action = findings(page).getByRole("button", { name: "让助手给改法", exact: true });
  await expect(action).toBeDisabled();
  const reason = findings(page).getByTestId("assist-reason");
  await expect(reason).toContainText("示例结果不能交给助手");
  const a = await rect(action);
  const b = await rect(reason);
  // Beside the button: to its right, on the same lines.
  expect(b.left).toBeGreaterThanOrEqual(a.right - 1);
  expect(b.top).toBeLessThan(a.bottom);
  expect(b.bottom).toBeGreaterThan(a.top);
  expect(await style(reason, "font-size")).toBe("13px");
});

test("18 章号：窄屏下缩到章名的 0.6 倍放在章名上面，章名 text-wrap: balance；宽屏保持原样", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, id, "workspace");
  const number = page.locator(".draft-head-num");
  const title = page.locator(".draft-title textarea");
  const n = await rect(number);
  const t = await rect(title);
  expect(n.bottom).toBeLessThanOrEqual(t.top + 1);
  const titleSize = parseFloat(await style(title, "font-size"));
  const numberSize = parseFloat(await style(number, "font-size"));
  expect(numberSize / titleSize).toBeCloseTo(0.6, 1);
  expect(await style(title, "text-wrap-style")).toBe("balance");
  await page.setViewportSize({ width: 1440, height: 900 });
  const wide = await rect(number);
  const wideTitle = await rect(title);
  expect(wide.right).toBeLessThanOrEqual(wideTitle.left + 1);
  expect(parseFloat(await style(number, "font-size"))).toBeGreaterThan(90);
});

test("18 手机：出处标记、复制、重新回答、接着问、点赞点踩、撤销、改动勾选框的点按区域至少 40×40", async ({ page }) => {
  const when = ago(30);
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const applied = changeView(cardItems({ status: "applied", applied_at: when, decided_at: when }).slice(0, 1), { id: "atask-hit-applied", created_at: ago(20) });
  const waiting = changeView(cardItems(), { id: "atask-hit-waiting", created_at: ago(10) });
  await serveTasks(page, () => [listView, applied, waiting]);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await expect(thread(page).locator("[data-task]")).toHaveCount(3);
  const reaches = async (locator: Locator, minimum = 40) => {
    // What a finger can hit: the points around the centre, up to the half of 40px, all land on this control (or inside it).
    const result = await locator.evaluate((node, min) => {
      const box = node.getBoundingClientRect();
      const cx = box.left + box.width / 2;
      const cy = box.top + box.height / 2;
      const half = min / 2 - 1;
      const owns = (x: number, y: number) => { const at = document.elementFromPoint(x, y); return Boolean(at && (node === at || node.contains(at) || at.closest("label")?.contains(node))); };
      return [[-half, -half], [half, -half], [-half, half], [half, half]].every(([dx, dy]) => owns(cx + dx, cy + dy));
    }, minimum);
    return result;
  };
  const list = tasks(page).first();
  await list.scrollIntoViewIfNeeded();
  await list.locator(".a-points li").nth(1).scrollIntoViewIfNeeded();
  expect(await reaches(list.locator(".a-points li").nth(1).locator(".a-cite button"))).toBe(true);
  for (const name of ["复制", "重新回答", "接着问", "有用", "没用"]) {
    const control = list.getByRole("button", { name, exact: true });
    await control.scrollIntoViewIfNeeded();
    const size = await rect(control);
    expect(size.height, `${name}: height`).toBeGreaterThanOrEqual(40);
    expect(size.width, `${name}: width`).toBeGreaterThanOrEqual(40);
  }
  const card = thread(page).getByRole("region", { name: "资料改动" });
  const done = card.first().getByRole("button", { name: "撤销", exact: true });
  await done.scrollIntoViewIfNeeded();
  expect((await rect(done)).height).toBeGreaterThanOrEqual(40);
  const waitingCard = card.last();
  const pick = waitingCard.locator('input[type="checkbox"]').first();
  await pick.scrollIntoViewIfNeeded();
  expect(await reaches(pick)).toBe(true);
  for (const name of ["不要"]) {
    const control = waitingCard.getByRole("button", { name, exact: true });
    expect((await rect(control)).height).toBeGreaterThanOrEqual(40);
  }
  const edit = waitingCard.getByRole("button", { name: "改内容" }).first();
  await edit.scrollIntoViewIfNeeded();
  expect((await rect(edit)).height).toBeGreaterThanOrEqual(40);
  // The words do not grow: the mark and the line of actions keep their sizes.
  expect(await style(list.locator(".a-points li").first(), "font-size")).toBe("14px");
  expect(await style(list.locator(".a-foot .a-link").first(), "font-size")).toBe("12px");
  await photograph(page, "07-多轮对话和变更卡片-手机", async () => { await page.goto(`/projects/${id}/overview`); await topbarAssistant(page).click(); }, [[390, 1500]]);
});

// A sentence ends with a mark; however the line breaks, the mark stays with the last words of its sentence and never stands alone on a line.
const longLine = (length: number, end: string) => `${"他走进仓道，雨水顺着帽檐往下淌，".repeat(3).slice(0, length - 1)}${end}`;
const wrapped = askView({
  id: "atask-wrap", question: "一串长句", created_at: ago(60), completed_at: ago(50), started_at: ago(58), sources,
  answer: {
    status: "answered", note: null,
    sentences: [
      { text: longLine(41, "。"), refs: ["R1"], lead: true },
      ...Array.from({ length: 4 }, (_, at) => ({ text: `第${at + 1}条${longLine(30 + at * 3, "。")}`, refs: ["R2"], label: `第${at + 1}条` })),
    ],
  },
});
const crowdedParagraph = askView({
  id: "atask-wrap-para", question: "再来一串", created_at: ago(30), completed_at: ago(20), started_at: ago(28), sources,
  answer: { status: "answered", note: null, sentences: Array.from({ length: 16 }, (_, at) => ({ text: longLine(14 + at * 2, "。"), refs: [at % 2 ? "R3" : "R2", "R4"] })) },
});

for (const [width, height] of [[1440, 1000], [390, 1500]] as const) {
  test(`18 出处标记不单独掉到下一行：${width} 宽，分点和段落都一样`, async ({ page }) => {
    await page.setViewportSize({ width, height });
    await withThread(page, [wrapped, crowdedParagraph]);
    const measure = () => page.locator(".a-answer .a-s").evaluateAll((nodes) => nodes.map((node) => {
      const tail = node.querySelector(".a-tail");
      const mark = node.querySelector(".a-cite > button");
      if (!tail || !mark) return null;
      // The last character before the mark, and how many lines the sentence takes.
      const text = Array.from(tail.childNodes).find((child) => child.nodeType === Node.TEXT_NODE) as Text;
      const range = document.createRange();
      range.setStart(text, text.length - 1);
      range.setEnd(text, text.length);
      const whole = document.createRange();
      whole.selectNodeContents(node);
      const lines = new Set(Array.from(whole.getClientRects()).filter((box) => box.width > 1).map((box) => Math.round(box.top / 6))).size;
      return { gap: Math.abs(mark.getBoundingClientRect().top - range.getBoundingClientRect().top), lines, copied: node.textContent };
    }));
    const probe = await measure();
    const rows = probe.filter((row) => row !== null);
    expect(rows.length).toBe(21);
    for (const row of rows) expect(row!.gap, `a mark stands on the line of its sentence's last character: ${row!.copied}`).toBeLessThanOrEqual(12);
    expect(rows.filter((row) => row!.lines > 1).length, "the test has sentences that do break").toBeGreaterThan(8);
    // What is copied is still the sentence (the pieces are one text).
    expect(rows[1]!.copied).toContain("第1条");
    // The check can see the fault: let the mark break away from its words and some marks do land on a line of their own.
    await page.addStyleTag({ content: ".a-tail { white-space: normal !important; }" });
    const loose = (await measure()).filter((row) => row !== null && row.gap > 12);
    expect(loose.length, "without the rule some marks stand alone").toBeGreaterThan(0);
  });
}

test("18 手机：写作页的助手窗格填满顶栏和窗格切换以下的屏幕，输入框和它下面的小字都在屏幕里", async ({ page }) => {
  await registerAccount(page, "a18");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, id, "workspace");
  await showAssistant(page);
  await expect(thread(page)).toBeVisible();
  await page.waitForTimeout(400);
  const note = await rect(thread(page).locator(".a-ai-note"));
  const form = await rect(thread(page).locator("form.cx"));
  expect(note.bottom, "the line under the box is on screen").toBeLessThanOrEqual(844);
  expect(form.bottom).toBeLessThan(note.top);
  expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
});

test("18 顶栏：832 左右的宽度也是一行，写作页多了“助手”按钮之后也一样", async ({ page }) => {
  // (assistant-v190.spec.ts measures the bar at every width from 768 to 1280, and the writing page at 768, 832 and 900, button included.)
  const id = await setup(page);
  await expect(topbarAssistant(page)).toBeVisible();
  for (const width of [900, 860, 832, 800, 768]) {
    await page.setViewportSize({ width, height: 900 });
    const bar = await rect(page.locator(".topbar"));
    expect(bar.height, `writing at ${width}: one row`).toBeLessThanOrEqual(70);
    const tops = await page.locator(".topbar-brand, .topbar-work, .topbar-tabs, #assistant-open, .theme-switch, .account-trigger").evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().top)));
    expect(Math.max(...tops) - Math.min(...tops), `writing at ${width}: the parts start on one row`).toBeLessThanOrEqual(24);
    expect(await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth)).toBeLessThanOrEqual(0);
  }
  expect(id).toBeTruthy();
});
