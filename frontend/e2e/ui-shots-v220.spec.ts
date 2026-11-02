import { mkdir, writeFile } from "node:fs/promises";
import type { Locator, Page } from "@playwright/test";
import { advanceTour, createWorkByApi, expect, newPage, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { button } from "./support/writing";

// Pictures for the v2.2 UI delivery (task 19): the main pages by day and by night at 1440 wide, and the main ones again at 375 wide by day.
// Taken only when UI_SHOTS_DIR names a folder (the ordinary run leaves no files). The page is shown as it is; nothing here changes it.
const dir = process.env.UI_SHOTS_DIR;
test.skip(!dir, "UI_SHOTS_DIR is not set");
test.use({ actionTimeout: 15_000 });

const FACT_SUMMARY = "一张受潮的旧潮图把修复师苏岑带回八年前的港口风夜，父亲的罗盘与一则关于白色渡船的无名纸条牵出被改写的记录。";

const setMood = (page: Page, value: "day" | "night") => page.evaluate((v) => { document.documentElement.dataset.theme = v; }, value);

type Size = 1440 | 375;

/** What a 375-wide page does that it should not: a page wider than the screen, a box with a visible sideways scroll bar, the work's name cut to less than four characters. */
const narrow: string[] = [];
async function auditNarrow(page: Page, name: string) {
  const found = await page.evaluate(() => {
    const out: string[] = [];
    const root = document.documentElement;
    if (root.scrollWidth > root.clientWidth + 1) out.push(`page is ${root.scrollWidth} wide on a ${root.clientWidth} screen`);
    for (const el of Array.from(document.querySelectorAll<HTMLElement>("*"))) {
      const style = getComputedStyle(el);
      if ((style.overflowX === "auto" || style.overflowX === "scroll") && el.scrollWidth > el.clientWidth + 1 && el.clientWidth > 0) {
        const bar = el.offsetHeight - el.clientHeight - parseFloat(style.borderTopWidth) - parseFloat(style.borderBottomWidth);
        out.push(`.${String(el.className).split(" ")[0] || el.tagName} scrolls sideways (${el.scrollWidth} in ${el.clientWidth}), bar ${bar > 0 ? "VISIBLE" : "hidden"}`);
      }
    }
    const work = document.querySelector<HTMLElement>(".topbar-work span");
    if (work) out.push(`topbar work name: ${Math.round(work.getBoundingClientRect().width)}px wide, text needs ${work.scrollWidth}px`);
    return out;
  });
  narrow.push(`## ${name}`, ...found.map((line) => `- ${line}`));
}

/** The page as it stands, by day then by night (night only at 1440): `NN-name-1440-浅色.png`. */
async function take(page: Page, name: string, size: Size, options: { part?: () => Locator; before?: () => Promise<void>; fullPage?: boolean } = {}) {
  await mkdir(dir!, { recursive: true });
  for (const tone of size === 1440 ? (["day", "night"] as const) : (["day"] as const)) {
    await setMood(page, tone);
    if (options.before) await options.before();
    await page.evaluate(async () => { await document.fonts.ready; });
    if (options.fullPage) { await page.screenshot({ fullPage: true, animations: "disabled" }); await page.waitForTimeout(900); }
    await page.waitForTimeout(450);
    const path = `${dir}/${name}-${size}-${tone === "day" ? "浅色" : "深色"}.png`;
    if (options.part) await options.part().screenshot({ path, animations: "disabled" });
    else await page.screenshot({ path, fullPage: options.fullPage ?? false, animations: "disabled" });
  }
  if (size === 375) await auditNarrow(page, name);
  await setMood(page, "day");
}

const memoryNav = (page: Page) => page.getByRole("navigation", { name: "资料分类", exact: true });

test("ui screenshots: the main pages", async ({ page, browser }) => {
  test.setTimeout(1_200_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  await registerAccount(page, "ui");

  // 作品管理 with nothing in it, then the home page.
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  await take(page, "02a-作品管理-空", 1440, { fullPage: true });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await take(page, "01-首页", 1440, { fullPage: true });

  const id = await sampleWorkId(page);
  await advanceTour(page, id, 4);
  await openTab(page, id, "overview");
  await take(page, "03-概览", 1440, { fullPage: true });

  await openTab(page, id, "workspace");
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
  await take(page, "04a-写作", 1440);
  await page.getByRole("tab", { name: /^检查结果/ }).click();
  await page.getByTestId(/^finding-/).first().click();
  await take(page, "04b-写作-检查结果", 1440);
  await button(page, "专注写作").click();
  await expect(page.getByRole("dialog", { name: "专注写作", exact: true })).toBeVisible();
  await page.waitForTimeout(300);
  await take(page, "04c-专注写作", 1440);
  await page.getByRole("dialog", { name: "专注写作", exact: true }).getByRole("button", { name: "退出专注写作", exact: true }).click();

  await openTab(page, id, "sources");
  await take(page, "05-章节", 1440, { fullPage: true });

  await openTab(page, id, "memory");
  await take(page, "06a-资料-事实", 1440, { fullPage: true });
  await memoryNav(page).getByRole("button", { name: /^人物/ }).click();
  await take(page, "06b-资料-人物", 1440, { fullPage: true });
  await memoryNav(page).getByRole("button", { name: /^设定/ }).click();
  await take(page, "06c-资料-设定", 1440, { fullPage: true });
  await memoryNav(page).getByRole("button", { name: /^伏笔/ }).click();
  await take(page, "06d-资料-伏笔", 1440, { fullPage: true });
  await memoryNav(page).getByRole("button", { name: /^决定/ }).click();
  await take(page, "06e-资料-决定", 1440, { fullPage: true });

  await openTab(page, id, "plan");
  await take(page, "07a-计划", 1440, { fullPage: true });
  await button(page, "新建计划").click();
  await expect(page.getByRole("dialog", { name: "新建计划", exact: true })).toBeVisible();
  await take(page, "07b-计划-新建", 1440);
  await page.keyboard.press("Escape");

  // The sample work cannot be archived; two works of the author's own can.
  const first = await createWorkByApi(page, { title: "雾港旧事", genre: "悬疑", summary: "" });
  await createWorkByApi(page, { title: "北桥灯", genre: "都市", summary: FACT_SUMMARY });
  await openTab(page, first, "overview");
  await page.locator(".overview-menu summary").click();
  await page.getByRole("menuitem", { name: "归档作品", exact: true }).click();
  await expect(page.getByRole("dialog")).toBeVisible();
  await take(page, "08-归档作品-确认", 1440);
  await page.keyboard.press("Escape");

  await page.goto("/settings/general");
  await expect(page.getByRole("heading", { level: 1, name: "设置", exact: true })).toBeVisible();
  await take(page, "09-设置", 1440, { fullPage: true });

  await page.goto("/projects");
  await expect(page.locator(".works-list li").first()).toBeVisible();
  await take(page, "02b-作品管理-有作品", 1440, { fullPage: true });
  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await take(page, "10a-新建作品", 1440, { fullPage: true });
  await page.goto("/projects/import");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await take(page, "10b-导入作品", 1440, { fullPage: true });

  const guest = await newPage(browser);
  await guest.setViewportSize({ width: 1440, height: 900 });
  await guest.goto("/login");
  await expect(guest.getByRole("heading", { level: 1, name: "欢迎回来", exact: true })).toBeVisible();
  await take(guest, "11a-登录", 1440);
  await guest.goto("/register");
  await expect(guest.getByRole("heading", { level: 1 })).toBeVisible();
  await take(guest, "11b-注册", 1440);
  await guest.setViewportSize({ width: 375, height: 812 });
  await guest.goto("/login");
  await expect(guest.getByRole("heading", { level: 1, name: "欢迎回来", exact: true })).toBeVisible();
  await take(guest, "M11-登录", 375, { fullPage: true });
  await guest.context().close();

  // 375 wide, by day.
  await page.setViewportSize({ width: 375, height: 812 });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1 })).toBeVisible();
  await take(page, "M01-首页", 375, { fullPage: true });
  await page.goto("/projects");
  await expect(page.locator(".works-list li").first()).toBeVisible();
  await take(page, "M02-作品管理", 375, { fullPage: true });
  await openTab(page, id, "overview");
  await take(page, "M03-概览", 375, { fullPage: true });
  await openTab(page, id, "workspace");
  const panes = page.getByRole("navigation", { name: "切换内容", exact: true });
  await panes.getByRole("button", { name: "正文", exact: true }).click();
  await expect(page.locator(".draft")).toBeVisible();
  await take(page, "M04a-写作", 375);
  await panes.getByRole("button", { name: /^检查结果/ }).click();
  await page.getByTestId(/^finding-/).first().click();
  await take(page, "M04b-检查结果", 375);
  await openTab(page, id, "sources");
  await take(page, "M05-章节", 375, { fullPage: true });
  await openTab(page, id, "memory");
  await take(page, "M06a-资料-事实", 375, { fullPage: true });
  await memoryNav(page).getByRole("button", { name: /^人物/ }).click();
  await take(page, "M06b-资料-人物", 375, { fullPage: true });
  await memoryNav(page).getByRole("button", { name: /^决定/ }).click();
  await take(page, "M06c-资料-决定", 375, { fullPage: true });
  await openTab(page, id, "plan");
  await take(page, "M07-计划", 375, { fullPage: true });
  await page.goto("/settings/general");
  await expect(page.getByRole("heading", { level: 1, name: "设置", exact: true })).toBeVisible();
  await take(page, "M09-设置", 375, { fullPage: true });
  await page.goto("/projects/new");
  await take(page, "M10-新建作品", 375, { fullPage: true });
  await writeFile(`${dir}/narrow-375.md`, narrow.join(String.fromCharCode(10)));
});
