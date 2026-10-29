import { mkdir } from "node:fs/promises";
import type { Locator, Page } from "@playwright/test";
import { advanceTour, createWorkByApi, expect, newPage, openAccountMenu, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { box, openAssistantTab, thread } from "./support/assistant";
import { askView, serveTasks } from "./support/assistant-mock";
import { button } from "./support/writing";

// Pictures of the look (task 29): the main pages by day and by night at 1440 wide, and the home page, the writing page and the assistant at 375.
// Taken only when LOOK_SHOTS_DIR names a folder, so the ordinary run leaves no files. The look has no switch: this is the page as it is.
const dir = process.env.LOOK_SHOTS_DIR;
test.skip(!dir, "LOOK_SHOTS_DIR is not set");
test.use({ actionTimeout: 15_000 });

const FACT_SUMMARY = "一张受潮的旧潮图把修复师苏岑带回八年前的港口风夜，父亲的罗盘与一则关于白色渡船的无名纸条牵出被改写的记录。";

/** The theme is set on the root element directly: a menu or a dialog that is open covers the switch, and a click on it would close them. */
const setMood = (page: Page, value: "day" | "night") => page.evaluate((v) => { document.documentElement.dataset.theme = v; }, value);

/** The page as it stands, by day then by night: `NN-name-浅色.png` and `NN-name-深色.png`. */
async function pair(page: Page, name: string, options: { part?: () => Locator; before?: () => Promise<void>; fullPage?: boolean } = {}) {
  await mkdir(dir!, { recursive: true });
  for (const tone of ["day", "night"] as const) {
    await setMood(page, tone);
    if (options.before) await options.before();
    await page.evaluate(async () => { await document.fonts.ready; });
    // A whole-page picture resizes the window for a moment and the charts redraw; one picture is thrown away so the real one is taken at rest.
    if (options.fullPage) { await page.screenshot({ fullPage: true, animations: "disabled" }); await page.waitForTimeout(900); }
    await page.waitForTimeout(450);
    const path = `${dir}/${name}-${tone === "day" ? "浅色" : "深色"}.png`;
    if (options.part) await options.part().screenshot({ path, animations: "disabled" });
    else await page.screenshot({ path, fullPage: options.fullPage ?? false, animations: "disabled" });
  }
  await setMood(page, "day");
}

test("look screenshots: the main pages", async ({ page, browser }) => {
  test.setTimeout(900_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await registerAccount(page, "look");
  const id = await sampleWorkId(page);

  // 首页: the sample card holds its work, its action and its note (the tour has not begun).
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await pair(page, "01-首页-空", { fullPage: true });

  await advanceTour(page, id, 4);
  await openTab(page, id, "overview");
  await pair(page, "02-概览", { fullPage: true });

  // 写作 and the assistant.
  await serveTasks(page, () => [askView({ answer: { status: "answered", sentences: [{ text: "第 8 章写她左臂已经康复，端起整盘碗碟也不再疼。", refs: ["R1"] }, { text: "资料里记的还是第 2 章的轻伤，可以按第 8 章改。", refs: ["R1"] }], note: "查了人物资料和第 2、8 章。" } })]);
  await openTab(page, id, "workspace");
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
  await openAssistantTab(page);
  await thread(page).locator("[data-task]").first().waitFor();
  await pair(page, "03-写作和助手");
  await box(page).focus();
  await pair(page, "07-输入框聚焦", { part: () => thread(page).locator(".a-compose"), before: async () => { await box(page).focus(); } });
  await box(page).blur();
  await pair(page, "08-输入框平时", { part: () => thread(page).locator(".a-compose"), before: async () => { await box(page).blur(); } });

  // 写作: the findings, one of them open, and the focus mode.
  await page.getByRole("tab", { name: /^检查结果/ }).click();
  await page.getByTestId(/^finding-/).first().click();
  await pair(page, "10-检查结果-展开的发现");
  await button(page, "专注写作").click();
  await expect(page.getByRole("dialog", { name: "专注写作", exact: true })).toBeVisible();
  await page.waitForTimeout(300);
  await mkdir(dir!, { recursive: true });
  await page.screenshot({ path: `${dir}/11-专注写作-浅色.png`, animations: "disabled" });
  await page.getByRole("dialog", { name: "专注写作", exact: true }).getByRole("button", { name: "退出专注写作", exact: true }).click();

  await openTab(page, id, "sources");
  await pair(page, "04-章节", { fullPage: true });
  await page.locator(".chapter-expand").first().click({ timeout: 3000 }).catch(() => undefined);
  await pair(page, "04b-章节-展开的段落");

  await openTab(page, id, "memory");
  await pair(page, "05-资料", { fullPage: true });
  const nav = page.getByRole("navigation", { name: "资料分类", exact: true });
  await nav.getByRole("button", { name: /^人物/ }).click();
  await page.locator(".person-toggle").first().click({ timeout: 3000 }).catch(() => undefined);
  await pair(page, "05b-资料-人物", { fullPage: true });
  await nav.getByRole("button", { name: /^伏笔/ }).click();
  await pair(page, "05c-资料-伏笔", { fullPage: true });
  await button(page, "记一条伏笔").click();
  await page.getByRole("textbox", { name: "标题", exact: true }).fill("廊桥钥匙");
  await pair(page, "05d-资料-伏笔表单", { fullPage: true });

  await openTab(page, id, "plan");
  await pair(page, "06-计划", { fullPage: true });
  await button(page, "新建计划").click();
  await expect(page.getByRole("dialog", { name: "新建计划", exact: true })).toBeVisible();
  await pair(page, "06b-计划-弹窗");
  await page.keyboard.press("Escape");
  await expect(page.getByRole("dialog")).toHaveCount(0);

  // Menus, a dialog, the works page.
  await openTab(page, id, "overview");
  await page.locator(".overview-menu summary").click();
  await pair(page, "12-概览-更多菜单");
  await page.getByRole("menuitem", { name: "导出作品", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await pair(page, "13-导出对话框");
  await page.keyboard.press("Escape");
  await page.goto("/");
  await openAccountMenu(page);
  await pair(page, "14-账号菜单");
  await page.keyboard.press("Escape");
  await createWorkByApi(page, { title: "雾港旧事", genre: "悬疑", summary: "" });
  await createWorkByApi(page, { title: "北桥灯", genre: "都市", summary: "" });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "继续你的故事" })).toBeVisible();
  await pair(page, "09-首页-有作品", { fullPage: true });
  await page.goto("/projects");
  await expect(page.locator(".works-list li").first()).toBeVisible();
  await pair(page, "15-作品管理", { fullPage: true });

  // 概览 header: a very long title, a work with no summary.
  const long = await createWorkByApi(page, { title: "一个特别特别长的作品名字用来检查换行和左右两栏对齐是不是正常", genre: "奇幻", summary: FACT_SUMMARY.repeat(2) });
  await openTab(page, long, "overview");
  await pair(page, "16-概览-长标题");
  const bare = await createWorkByApi(page, { title: "潮汐之后", genre: "现实", summary: "" });
  await openTab(page, bare, "overview");
  await pair(page, "17-概览-无简介");

  // The sign-in page, signed out.
  const guest = await newPage(browser);
  await guest.setViewportSize({ width: 1440, height: 900 });
  await guest.goto("/login");
  await expect(guest.getByRole("heading", { level: 1, name: "欢迎回来", exact: true })).toBeVisible();
  await pair(guest, "18-登录页");
  await guest.context().close();

  // 375 wide: the home page, the writing page and the assistant.
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "继续你的故事" })).toBeVisible();
  await pair(page, "M1-首页-375", { fullPage: true });
  await openTab(page, id, "overview");
  await pair(page, "M2-概览-375", { fullPage: true });
  await openTab(page, id, "workspace");
  const panes = page.getByRole("navigation", { name: "切换内容", exact: true });
  await panes.getByRole("button", { name: "正文", exact: true }).click();
  await expect(page.locator(".draft")).toBeVisible();
  await pair(page, "M3-写作-375");
  await panes.getByRole("button", { name: /^检查结果/ }).click();
  await page.getByTestId(/^finding-/).first().click();
  await pair(page, "M4-检查结果-375");
  await panes.getByRole("button", { name: "助手", exact: true }).click();
  await expect(thread(page)).toBeVisible();
  await pair(page, "M5-助手-375");
});
