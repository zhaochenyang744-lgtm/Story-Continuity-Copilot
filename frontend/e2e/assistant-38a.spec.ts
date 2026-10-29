import type { Locator, Page } from "@playwright/test";
import { api, createWork, expect, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { ask, box, finished, openAssistantTab, sideTab, tasks, thread, topbarAssistant } from "./support/assistant";
import { askView, serveTasks } from "./support/assistant-mock";
import { view } from "./support/pages";
import { ago, askSources, noted, passage, recapView } from "./support/assistant-38a";

// 38a: the assistant's answers, the 写前回顾, the 去原文 link, the drawer's and the column's frames, the unsent words, a visitor on a work of their own.

const rect = (locator: Locator) => locator.evaluate((node) => { const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height }; });
const style = (locator: Locator, property: string) => locator.evaluate((node, name) => getComputedStyle(node).getPropertyValue(name), property);

/** The first sentence (8 characters or more) of a written chapter of the sample work. */
async function sentenceOfChapter(page: Page, id: string, number: number) {
  const chapter = ((await api(page).get(`/projects/${id}/long-term-review`)).chapters as { number: number; title: string; body: string }[]).find((item) => item.number === number)!;
  const sentence = /[^。！？\n]{8,}[。！？]/.exec(chapter.body)![0].trim();
  return { sentence, title: chapter.title };
}
const readingChapter = (page: Page, number: number) => page.getByRole("textbox", { name: `第 ${number} 章正文（只读）`, exact: true });

test.describe("38a 去原文打开的是引用的那一章（H02）", () => {
  for (const tab of ["overview", "memory", "plan"] as const) {
    test(`从${{ overview: "概览", memory: "资料", plan: "计划" }[tab]}页的助手抽屉里点出处的「去原文」：打开第 2 章的阅读页，引用的那句被圈出`, async ({ page }) => {
      await registerAccount(page, "a38");
      await page.emulateMedia({ reducedMotion: "no-preference" });  // the ring is not drawn when motion is reduced
      const id = await sampleWorkId(page);
      const { sentence, title } = await sentenceOfChapter(page, id, 2);
      await serveTasks(page, () => [askView({
        id: "atask-h02", question: "罗盘有什么特征？", steps: [], coverage: null,
        sources: { R1: passage(2, title, sentence) },
        answer: { status: "answered", note: null, sentences: [{ text: "第 2 章写了这一点。", refs: ["R1"] }] },
      })]);
      await openTab(page, id, tab);
      await topbarAssistant(page).click();
      await expect(thread(page)).toBeVisible();
      await tasks(page).first().getByRole("button", { name: /^出处 1 处/ }).click();
      await tasks(page).first().locator(".a-where").first().click();
      await tasks(page).first().getByRole("button", { name: "去原文 →" }).click();
      await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=2$`));
      await expect(readingChapter(page, 2)).toBeVisible();
      await expect(page.locator("#chapter-body .mark-pulse").first()).toContainText(sentence.slice(0, 8), { timeout: 6_000 });
    });
  }

  test("写作页右栏里点「去原文」：同样打开那一章；概览页章节列表的 ?chapter=N 链接也打开那一章", async ({ page }) => {
    await registerAccount(page, "a38");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    const id = await sampleWorkId(page);
    const { sentence, title } = await sentenceOfChapter(page, id, 2);
    await serveTasks(page, () => [askView({
      id: "atask-h02", question: "罗盘有什么特征？", steps: [], coverage: null,
      sources: { R1: passage(2, title, sentence) },
      answer: { status: "answered", note: null, sentences: [{ text: "第 2 章写了这一点。", refs: ["R1"] }] },
    })]);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await tasks(page).first().getByRole("button", { name: /^出处 1 处/ }).click();
    await tasks(page).first().locator(".a-where").first().click();
    await tasks(page).first().getByRole("button", { name: "去原文 →" }).click();
    await expect(page).toHaveURL(/\/workspace\?chapter=2$/);
    await expect(readingChapter(page, 2)).toBeVisible();
    await expect(page.locator("#chapter-body .mark-pulse").first()).toContainText(sentence.slice(0, 8), { timeout: 6_000 });
  });

  test("概览页「接下来」里的已写章节：点开是那一章的阅读页，不是草稿", async ({ page }) => {
    await registerAccount(page, "a38");
    const id = await sampleWorkId(page);
    await openTab(page, id, "overview");
    await page.getByRole("button", { name: /^第 3 章 · / }).first().click();
    await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=3$`));
    await expect(readingChapter(page, 3)).toBeVisible();
  });
});

test("38a 访客在自己的作品上打开助手：一开始就说清楚，没有输入框、建议问题和次数（V11）", async ({ page }) => {
  await startVisitor(page);
  await createWork(page, { title: "38a 访客自己的作品", genre: "悬疑", summary: "" });
  await topbarAssistant(page).click().catch(() => undefined);
  if (!(await thread(page).isVisible())) await openAssistantTab(page);
  await expect(thread(page)).toBeVisible();
  await expect(thread(page).getByRole("status").filter({ hasText: "访客只能在示例作品上用助手。注册后可以在自己的作品上用。" })).toBeVisible();
  await expect(box(page)).toHaveCount(0);
  await expect(thread(page).locator(".a-starters, .a-start")).toHaveCount(0);
  await expect(thread(page)).not.toContainText("今天还可以问");
});

test("38a 没发出去的追问不丢：关掉抽屉、换一页再打开，文字还在；发出去以后清掉；只恢复文字（V01）", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await expect(box(page)).toBeVisible();
  await box(page).fill("她接下来打算怎么查？");
  await page.getByRole("button", { name: "关闭助手", exact: true }).click();
  await expect(thread(page)).toHaveCount(0);
  await page.getByRole("navigation", { name: "作品" }).getByRole("button", { name: "计划", exact: true }).click();
  await expect(page).toHaveURL(/\/plan/);
  await topbarAssistant(page).click();
  await expect(box(page)).toHaveValue("她接下来打算怎么查？");
  // Sent: the words are gone, and stay gone after the drawer is closed and opened again.
  await box(page).fill("E2E_TWO 苏岑知道罗盘被调包了吗？");
  await page.getByRole("button", { name: "发送", exact: true }).click();
  await finished(page);
  await expect(box(page)).toHaveValue("");
  await page.getByRole("button", { name: "关闭助手", exact: true }).click();
  await topbarAssistant(page).click();
  await expect(box(page)).toHaveValue("");
  // A work of its own: the words of one work are not shown in another's box (the key carries the work).
  await box(page).fill("只在这部作品里");
  const keys = await page.evaluate(() => Object.keys(window.sessionStorage).filter((key) => key.includes("assistant-unsent")));
  expect(keys).toHaveLength(1);
  expect(keys[0]).toContain(id);
});

test("38a 抽屉打开、输入框有焦点时改变窗口宽度：标题和关闭按钮留在画面里，抽屉外框不滚，输入框贴着抽屉底部（V04）", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  const views = [1, 2, 3].map((n) => askView({ id: `atask-v04-${n}`, question: `第 ${n} 个问题：罗盘有什么特征？`, created_at: ago(400 - n * 60), started_at: ago(398 - n * 60), completed_at: ago(390 - n * 60) }));
  await serveTasks(page, () => views);
  await page.setViewportSize({ width: 1280, height: 800 });
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await expect(thread(page).locator("[data-task]")).toHaveCount(3);
  const drawer = page.getByRole("dialog", { name: "助手", exact: true });
  for (const [width, height] of [[1280, 800], [390, 844], [768, 1000], [1280, 800]] as const) {
    await page.setViewportSize({ width, height });
    await box(page).focus();
    await page.keyboard.press("Shift+Tab");
    await page.keyboard.press("Tab");
    const frame = await rect(drawer);
    const title = await rect(drawer.getByRole("heading", { name: "助手" }));
    expect(title.top, `${width}: the title is on screen`).toBeGreaterThanOrEqual(0);
    expect(title.bottom).toBeLessThanOrEqual(height);
    await expect(drawer.getByRole("button", { name: "关闭助手", exact: true })).toBeInViewport();
    expect(await drawer.evaluate((node) => node.scrollTop)).toBe(0);
    expect(await drawer.locator(".assistant").evaluate((node) => node.scrollTop)).toBe(0);
    expect(await page.locator(".layer-drawer").evaluate((node) => node.scrollTop)).toBe(0);
    const field = await rect(drawer.locator("form.cx"));
    expect(frame.bottom - field.bottom, `${width}: the box stands at the foot of the drawer`).toBeLessThan(60);
    // The frame is as tall as the window and no taller: a frame that grew to its content would put the box (and the end of the conversation) below the screen.
    expect(frame.bottom, `${width}: the drawer ends with the window`).toBeLessThanOrEqual(height + 1);
    expect(field.bottom, `${width}: the box is on screen`).toBeLessThanOrEqual(height);
  }
});

test("38a 写作页右栏回答完以后：对话区顶边不在右栏顶边之上，输入框贴着右栏底部（V10）", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  for (const question of ["E2E_TWO 苏岑知道罗盘被调包了吗？", "E2E_TWO 温岚把罗盘放在哪里？"]) {
    await ask(page, question);
    await finished(page, question.includes("苏岑") ? 1 : 2);
  }
  const column = page.locator("#writing-side");
  const columnBox = await rect(column);
  const log = await rect(thread(page).locator(".a-thread"));
  expect(log.top, "the conversation starts under the column's top").toBeGreaterThanOrEqual(columnBox.top - 1);
  const field = await rect(thread(page).locator("form.cx"));
  expect(columnBox.bottom - field.bottom, "the box stands at the foot of the column").toBeLessThan(80);
  expect(columnBox.bottom, "the column ends with the window").toBeLessThanOrEqual(900 + 1);
  expect(field.bottom, "the box is on screen").toBeLessThanOrEqual(900);
  expect(await column.evaluate((node) => node.scrollTop)).toBe(0);
  expect(await page.locator("#side-panel-assistant").evaluate((node) => node.scrollTop)).toBe(0);
});

test("38a 窄屏标签和内容对得上：桌面上选助手，缩到 832 高亮的是助手；窄屏上选检查结果，放大后右栏是检查结果（V08）", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, id, "workspace");
  const panes = page.getByRole("navigation", { name: "切换内容", exact: true });
  await sideTab(page).click();
  await page.setViewportSize({ width: 832, height: 900 });
  await expect(panes.getByRole("button", { name: "助手", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(thread(page)).toBeVisible();
  // On the narrow screen, choose 检查结果; widened, the column shows the findings.
  await panes.getByRole("button", { name: /^检查结果/ }).click();
  await expect(panes.getByRole("button", { name: /^检查结果/ })).toHaveAttribute("aria-current", "page");
  await expect(thread(page)).toBeHidden();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(page.getByRole("tab", { name: /^检查结果/ })).toHaveAttribute("aria-selected", "true");
  await expect(thread(page)).toBeHidden();
  // The other way: the column on the findings, narrowed, then 助手 chosen on the narrow screen, widened: the column shows the assistant.
  await page.setViewportSize({ width: 832, height: 900 });
  await expect(panes.getByRole("button", { name: /^检查结果/ })).toHaveAttribute("aria-current", "page");
  await panes.getByRole("button", { name: "助手", exact: true }).click();
  await expect(thread(page)).toBeVisible();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
  await expect(thread(page)).toBeVisible();
  // 正文 only means something on the narrow screen: back on the desktop the column keeps the last side picked.
  await page.setViewportSize({ width: 832, height: 900 });
  await panes.getByRole("button", { name: "正文", exact: true }).click();
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
});

test("38a 资料页伏笔的来源行写「埋下：第 N 章 · 章名」，章名取自章节列表，不显示 append（V06）", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  const chapters = (await api(page).get(`/projects/${id}/long-term-review`)).chapters as { number: number; title: string }[];
  expect(((await api(page).get(`/projects/${id}/foreshadows?include_archived=true`)).records as { planted: unknown }[]).some((record) => record.planted)).toBe(true);
  // A chapter finished from the draft leaves 「append」 as the label of its source passage; the page must not show it.
  await page.route(`**/api/projects/${id}/foreshadows?*`, async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    const response = await route.fetch();
    const body = await response.json();
    for (const record of body.data.records ?? []) if (record.planted) record.planted.source_label = "append";
    await route.fulfill({ response, json: body });
  });
  await openTab(page, id, "memory");
  await view(page, "伏笔", "threads");
  const links = page.locator(".thread-links a", { hasText: "埋下：" });
  await expect(links.first()).toBeVisible();
  const text = await links.first().innerText();
  expect(text).not.toContain("append");
  const number = Number(/第 (\d+) 章/.exec(text)![1]);
  const title = chapters.find((chapter) => chapter.number === number)!.title.replace(/^第.{1,4}章[\s·：:]*/, "");
  expect(text).toBe(`埋下：第 ${number} 章${title ? ` · ${title}` : ""}`);
});

// ── 写前回顾 ────────────────────────────────────────────────────────────────────────────────────────

test("38a 写前回顾：一条一句、句末是角标；没有灰色原文行和来源行；浮层按真实类型标来源、整段显示并圈出相关那一句", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => [recapView("atask-recap-38a", ["本章草稿（写前回顾不看草稿）"])]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const view = tasks(page).first();
  // The line on top: what the task is and which chapters it read, then the folded process; no count of places.
  await expect(view.getByTestId("process-line")).toHaveText(/^写前回顾 · 第 11 章（只看第 1–10 章） · 过程 · \d+ 秒$/);
  await expect(view).not.toContainText("查了");
  // No grey quote lines, no source lines, no 「还有 N 段」, no line saying the draft was not read.
  await expect(view.locator(".a-ri-src, .a-quote-line, .a-from, .a-more")).toHaveCount(0);
  await expect(view).not.toContainText("还有");
  await expect(view).not.toContainText("没查");
  await expect(view.getByTestId("how-checked")).toHaveCount(0);
  // Four groups in their order; the title is small, grey, not bold.
  await expect(view.locator(".a-label")).toHaveText(["上一章停在哪", "出场人物的最新状态", "还没收的线", "计划里这一章的事"]);
  expect(await style(view.locator(".a-label").first(), "font-weight")).toBe("400");
  expect(await style(view.locator(".a-label").first(), "letter-spacing")).toBe("normal");
  expect(await style(view.locator(".a-label").first(), "font-size")).toBe("11px");
  // The previous ending is the opening, in body size; the other groups are lists with a little space between items and no rules.
  expect(await style(view.locator("p.a-ri.lead"), "font-size")).toBe("14px");
  await expect(view.locator("ul.a-ri-list")).toHaveCount(3);
  expect(await style(view.locator("ul.a-ri-list > li").first(), "border-bottom-width")).toBe("0px");
  // Each item is one sentence with one mark at its end.
  for (const item of await view.locator(".a-ri").all()) expect(await item.locator(".a-cite").count()).toBe(1);
  await expect(view.locator(".a-ri .a-cite > button")).toHaveText(["1", "2", "3–4", "5"]);
  // 还没收的线: a foreshadow record and a passage, each named for what it is.
  await view.locator("li.a-ri", { hasText: "廊桥钥匙" }).locator(".a-cite > button").click();
  const card = page.getByRole("group", { name: "出处 3–4" });
  await expect(card.locator(".w")).toHaveText(["伏笔记录 · 第 5 章", "第 4 章 · 廊桥"]);
  await expect(card.getByRole("button", { name: "去原文 →" })).toHaveCount(2);
  // A fact says so; a plan names the chapter it is for.
  await view.locator("li.a-ri", { hasText: "仍握着" }).locator(".a-cite > button").click();
  await expect(page.getByRole("group", { name: "出处 2" }).locator(".w")).toHaveText("事实摘要 · 第 10 章");
  await view.locator("li.a-ri", { hasText: "随身袋" }).locator(".a-cite > button").click();
  await expect(page.getByRole("group", { name: "出处 5" }).locator(".w")).toHaveText("计划 · 第 11 章");
  await expect(page.getByRole("group", { name: "出处 5" }).getByRole("button", { name: "去原文 →" })).toHaveCount(0);
  // The long passage is shown whole; the sentence that says what the summary says is set apart and brought into view inside the card.
  await view.locator("p.a-ri.lead .a-cite > button").click();
  const long = page.getByRole("group", { name: "出处 1" });
  await expect(long.locator("mark")).toHaveText("北潮闸没有关闭，雾钟却响了一次。");
  await expect(long.locator("q.full")).toContainText("第1遍巡查");
  await expect.poll(() => long.locator("q.full").evaluate((node) => node.scrollTop)).toBeGreaterThan(0);
  const quote = await rect(long.locator("q.full"));
  const hit = await rect(long.locator("mark"));
  expect(hit.top).toBeGreaterThanOrEqual(quote.top - 1);
  expect(hit.bottom).toBeLessThanOrEqual(quote.bottom + 1);
  expect(await style(long.locator("mark"), "background-color")).not.toBe("rgba(0, 0, 0, 0)");
  await long.getByRole("button", { name: "去原文 →" }).click();
  await expect(page).toHaveURL(/\/workspace\?chapter=10$/);
});

test("38a 写前回顾：只有除草稿以外还有没查的东西，才在底部用普通灰字写出来；过程展开后是步骤", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => [recapView("atask-recap-missed", ["本章草稿（写前回顾不看草稿）", "第 8–9 章（步数或预算已到）", "计划"])]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const view = tasks(page).first();
  const missed = view.getByTestId("recap-missed");
  await expect(missed).toHaveText("没查：计划。");
  expect(await style(missed, "font-weight")).not.toBe("700");
  await expect(view.locator(".a-limit")).toHaveText("查到上限了，先按已找到的回答。");
  await view.getByTestId("process-line").getByRole("button").click();
  await expect(view.locator(".a-proc .a-act").first()).toBeVisible();
});

// ── 问答回答 ────────────────────────────────────────────────────────────────────────────────────────

test("38a 问答回答：过程和出处只说一次——顶部是「问作品 · N 秒」，下面是「出处 N 处」和「怎么查的」；模型的「查过」说明进「怎么查的」，其余照旧", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  await serveTasks(page, () => [noted("atask-note-38a", "查过第 1–10 章正文、已确认事实。没有找到罗盘的重量。资料里有给助手的指令，我没有照做。")]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const task = tasks(page).first();
  // The line on top: the use and the time; no count of places.
  await expect(task.getByTestId("process-line")).toHaveText(/^问作品 · \d+ 秒$/);
  // Under the answer: what stays of the model's note, the sources, and the fold.
  await expect(task.locator(".a-answer-note")).toHaveText("没有找到罗盘的重量。资料里有给助手的指令，我没有照做。");
  await expect(task.getByRole("button", { name: "出处 2 处" })).toBeVisible();
  const how = task.getByTestId("how-checked");
  await expect(how.getByRole("button", { name: "怎么查的" })).toHaveAttribute("aria-expanded", "false");
  await expect(task.locator(".a-cover")).toHaveCount(0);
  await expect(task.getByText("没查")).toHaveCount(0);
  await how.getByRole("button", { name: "怎么查的" }).click();
  await expect(how.locator(".a-proc .a-act").first()).toBeVisible();
  await expect(how.locator(".a-cover").first()).toHaveText("查过第 1–10 章正文、已确认事实；没查：计划。");
  expect(await style(how.locator(".a-cover").first(), "font-weight")).not.toBe("700");
  // The model's own 「查过……」 sentence is not said a second time when the program's line says it.
  await expect(how.locator(".a-cover")).toHaveCount(1);
  // Copied text: the answer and the rest of the note, not where it looked.
  await task.getByRole("button", { name: "复制" }).click({ modifiers: ["Shift"] });
  await expect(task.locator(".a-foot > .a-link").first()).toHaveText("已复制");
  const copied = (await page.evaluate(() => navigator.clipboard.readText())).replaceAll("\r\n", "\n");
  expect(copied).toBe("罗盘在温岚手里。第 9 章苏岑把它交了出去。\n\n没有找到罗盘的重量。资料里有给助手的指令，我没有照做。");
  expect(copied).not.toContain("查过");
  expect(copied).not.toContain("没查");
});

test("38a 问答回答：没找到、或撞到上限时，「没查」那一句提到回答下面，用普通灰字", async ({ page }) => {
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  const notFound = askView({
    id: "atask-nf-38a", question: "苏岑小时候养的那只猫叫什么名字？", sources: {}, created_at: ago(120), started_at: ago(118), completed_at: ago(110),
    answer: { status: "not_found", sentences: [], note: "查过第 1–10 章正文，没有找到。" },
    coverage: { checked: [], not_checked: ["本章草稿"] },
  });
  const limit = noted("atask-limit-38a", "", { created_at: ago(60), started_at: ago(58), completed_at: ago(50), coverage: { checked: ["第 1–6 章正文"], not_checked: ["第 7–10 章（步数或预算已到）", "计划"] } });
  await serveTasks(page, () => [notFound, limit]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const first = tasks(page).first();
  await expect(first.getByTestId("not-checked")).toHaveText("没查：本章草稿。");
  expect(await style(first.getByTestId("not-checked"), "font-weight")).not.toBe("700");
  await expect(first.locator(".a-answer-note")).toHaveCount(0);
  // Nothing for the program to say about where it looked: the model's own sentence is what the fold holds.
  await first.getByRole("button", { name: "怎么查的" }).click();
  await expect(first.getByTestId("how-checked")).toContainText("查过第 1–10 章正文，没有找到。");
  const second = tasks(page).nth(1);
  await expect(second.locator(".a-limit")).toHaveText("查到上限了，先按已找到的回答。");
  await expect(second.getByTestId("not-checked")).toHaveText("没查：计划。");
});

test("38a 跨章的回答分条：三句各写到不同的「第 N 章」就一条一行，不加粗任何东西；复制也是一条一行（H03）", async ({ page, context }) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await registerAccount(page, "a38");
  const id = await sampleWorkId(page);
  const view = askView({
    id: "atask-walk-38a", question: "从第 1 章到第 10 章，苏岑对记录的认识有什么变化？", sources: askSources, created_at: ago(70), started_at: ago(68), completed_at: ago(64),
    answer: {
      status: "answered", note: null,
      sentences: [
        { text: "第 1 章苏岑只把它当成父亲的遗物。", refs: ["R1"] },
        { text: "第 2 章他发现月牙裂纹，开始留意罗盘。", refs: ["R2"] },
        { text: "第 7 章他第一次怀疑记录被人改过。", refs: [] },
        { text: "第 10 章他把罗盘交给了温岚，不再确定。", refs: ["R2"] },
      ],
    },
    coverage: { checked: ["第 1–10 章正文"], not_checked: [] },
  });
  await serveTasks(page, () => [view]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  const task = tasks(page).first();
  const answer = task.locator(".a-answer");
  await expect(answer).toHaveAttribute("data-layout", "chapters");
  await expect(answer.locator(".a-points > li")).toHaveCount(4);
  await expect(answer.locator("b")).toHaveCount(0);
  await task.getByRole("button", { name: "复制" }).click({ modifiers: ["Shift"] });
  await expect(task.locator(".a-foot > .a-link").first()).toHaveText("已复制");
  expect((await page.evaluate(() => navigator.clipboard.readText())).replaceAll("\r\n", "\n")).toBe("第 1 章苏岑只把它当成父亲的遗物。\n第 2 章他发现月牙裂纹，开始留意罗盘。\n第 7 章他第一次怀疑记录被人改过。\n第 10 章他把罗盘交给了温岚，不再确定。");
});
