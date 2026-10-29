import type { Locator, Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { api, expect, openTab, sampleWorkId, startVisitor, test } from "./support/app";
import { ask, box, finished, openAssistantTab, proposal, select, tasks, thread, toolbar } from "./support/assistant";
import { askView, runningView, serveTasks } from "./support/assistant-mock";
import { theme } from "./support/pages";
import { beginCheck, finishCheck, saveBody, selectIssue, setup, findings } from "./support/writing";

// The pictures of 07c: the assistant's column in its states, and the pages that show the new fields and corners, each in the
// day and the night theme. Nothing here asserts much; the other specs do that. Names are in Chinese, as the folder they are copied to.

const SENTENCE = "苏岑拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST。";

async function crop(target: Locator, name: string) {
  const directory = process.env.E2E_SCREENSHOTS_DIR;
  if (!directory) throw new Error("E2E_SCREENSHOTS_DIR is required");
  await mkdir(directory, { recursive: true });
  await target.page().evaluate(async () => { await document.fonts.ready; });
  await target.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" });
}
/** The same picture in the day and then the night theme. */
async function pair(page: Page, name: string, target: () => Locator, before?: () => Promise<void>) {
  for (const value of ["day", "night"] as const) {
    await theme(page, value);
    if (before) await before();
    await crop(target(), `${name}-${value === "day" ? "浅色" : "深色"}`);
  }
  await theme(page, "day");
}
const column = (page: Page) => page.locator("#writing-side");
const scrolled = (page: Page) => () => page.evaluate(() => window.scrollTo(0, 340));
/** The page, whole viewport, in both themes. */
async function pagePair(page: Page, name: string) {
  for (const value of ["day", "night"] as const) {
    await theme(page, value);
    await page.evaluate(() => window.scrollTo(0, 0));
    await crop(page.locator("body"), `${name}-${value === "day" ? "浅色" : "深色"}`).catch(async () => {
      await page.screenshot({ path: path.join(process.env.E2E_SCREENSHOTS_DIR!, `${name}-${value === "day" ? "浅色" : "深色"}.png`) });
    });
  }
  await theme(page, "day");
}
async function viewport(page: Page, name: string) {
  const directory = process.env.E2E_SCREENSHOTS_DIR!;
  await mkdir(directory, { recursive: true });
  for (const value of ["day", "night"] as const) {
    await theme(page, value);
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.screenshot({ path: path.join(directory, `${name}-${value === "day" ? "浅色" : "深色"}.png`), animations: "disabled" });
  }
  await theme(page, "day");
}

test.describe("07c 截图", () => {
  test("过程：运行中、跑完点开、引用悬停", async ({ page }) => {
    await setup(page);
    let list: unknown[] = [runningView("tool", { phase_started_at: new Date(Date.now() - 6000).toISOString() })];
    await serveTasks(page, () => list);
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).getByText("正在读第 10 章")).toBeVisible();
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "01-运行中的过程", () => column(page), async () => { await expect(thread(page).getByText(/\d+ 秒/)).toBeVisible({ timeout: 10_000 }); });
    // Finished and opened: the narration, the grouped actions, and what a search found (the unused one fainter).
    list = [askView()];
    await page.reload();
    await openAssistantTab(page);
    const task = tasks(page).first();
    await task.getByRole("button", { name: "怎么查的" }).click();
    await task.getByRole("button", { name: /^搜了 2 处正文/ }).click();
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "02-跑完后点开的过程", () => column(page));
    // The card over a citation.
    await task.getByRole("button", { name: "怎么查的" }).click();
    await task.locator(".a-cite button").first().hover();
    await expect(thread(page).locator(".a-pop")).toBeVisible();
    await pair(page, "03-引用悬停", () => column(page), async () => { await task.locator(".a-cite button").first().hover(); await expect(thread(page).locator(".a-pop")).toBeVisible(); });
  });

  test("回答：操作行、没用的原因", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "E2E_TWO 苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    await task.getByRole("button", { name: "没用", exact: true }).click();
    await expect(task.getByRole("group", { name: "哪里不好" })).toBeVisible();
    await task.getByRole("button", { name: "啰嗦", exact: true }).click();
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "04-回答操作和没用原因", () => column(page));
  });

  test("改法：逐字差异、改一改", async ({ page }) => {
    const id = await setup(page);
    await saveBody(page, id, SENTENCE);
    const result = await finishCheck(page, id, await beginCheck(page, id));
    const issue = result.issues.find((item: { claim_text: string }) => item.claim_text.includes("E2E_SUGGEST"));
    await selectIssue(page, issue);
    await findings(page).getByRole("button", { name: "让助手给改法", exact: true }).click();
    await finished(page);
    const task = tasks(page).last();
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "05-改法逐字差异", () => column(page));
    await proposal(task, "edit_this").getByRole("button", { name: "改一改", exact: true }).click();
    const area = proposal(task, "edit_this").getByRole("textbox", { name: "改后的句子" });
    await area.fill("（示意改法）拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST。");
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "06-改一改", () => column(page));
  });

  test("输入框：空着、带上下文、助手在查、额度用完", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await page.evaluate(() => window.scrollTo(0, 340));
    const compose = () => thread(page).locator(".a-compose");
    await box(page).blur();
    await pair(page, "07a-输入框-空着", compose);
    await select(page, "#draft-body", 14);
    await toolbar(page).getByRole("button", { name: /^问助手/ }).click();
    await box(page).fill("那她后来把罗盘还回去了吗？");
    await pair(page, "07b-输入框-带上下文", compose, async () => { await box(page).focus(); });
    // The assistant at work: the send square is a stop button.
    await box(page).fill("");
    let list: unknown[] = [runningView("thinking")];
    await serveTasks(page, () => list);
    await page.reload();
    await openAssistantTab(page);
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "07c-输入框-助手在查", compose);
    // Used up for today: dashed, no fill, the reason inside.
    list = [];
    const session = await api(page).get("/auth/session");
    const usage = await api(page).get("/account/usage");
    await api(page).post(`/test/v180/users/${session.user.id}/spend-characters/${usage.check_chars_remaining - 300}`);
    await openTab(page, id, "workspace");
    await page.reload();
    await openAssistantTab(page);
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "07d-输入框-额度用完", compose);
  });

  test("空对话和作品以外", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "08-空对话", () => column(page));
    await ask(page, "E2E_OFF 帮我写一首关于海港的诗");
    await finished(page);
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "09-作品以外", () => column(page));
  });

  test("手机宽度的助手面板", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "E2E_TWO 苏岑知道罗盘被调包了吗？");
    await finished(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect(thread(page)).toBeVisible();
    await thread(page).scrollIntoViewIfNeeded();
    await viewport(page, "10-手机宽度的助手面板");
  });

  test("全站：写作页、章节页、资料页、登录页", async ({ page, browser }) => {
    const id = await setup(page);
    await openTab(page, id, "workspace");
    await page.evaluate(() => window.scrollTo(0, 0));
    await viewport(page, "11-写作页");
    await openTab(page, id, "sources");
    await viewport(page, "12-章节页");
    await openTab(page, id, "memory");
    await viewport(page, "13-资料页");
    const other = await browser.newPage({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 1440, height: 960 } });
    await other.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await other.goto("/register");
    await other.getByLabel("账号", { exact: true }).fill("某某");
    await expect(other.getByRole("heading", { level: 1, name: "创建账号" })).toBeVisible();
    const directory = process.env.E2E_SCREENSHOTS_DIR!;
    for (const value of ["day", "night"] as const) {
      await other.evaluate((v) => { document.documentElement.dataset.theme = v; }, value);
      await other.screenshot({ path: path.join(directory, `14-登录页-${value === "day" ? "浅色" : "深色"}.png`) });
    }
    await other.close();
  });

  test("访客的空对话", async ({ page }) => {
    await startVisitor(page);
    const id = await sampleWorkId(page);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await page.evaluate(() => window.scrollTo(0, 340));
    await pair(page, "08b-访客的空对话", () => column(page));
  });
});
