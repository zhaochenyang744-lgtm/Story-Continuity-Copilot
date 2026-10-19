import type { Locator, Page } from "@playwright/test";
import { api, expect, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { ask, askForFix, box, checkedWork, chip, chooseMode, finished, openAssistantTab, openPlus, select, tasks, thread, toolbar, topbarAssistant } from "./support/assistant";
import { askView, fixView, proposalView, serveTasks } from "./support/assistant-mock";
import { theme } from "./support/pages";
import { setup } from "./support/writing";

// 07f screenshots of the fixed things, light and dark. They are written only when SHOTS_07F_DIR names a folder (the runner passes that
// variable through); an ordinary run skips this file.
const dir = process.env.SHOTS_07F_DIR;
test.skip(!dir, "SHOTS_07F_DIR is not set");

const mood = async (page: Page, value: "day" | "night") => { await theme(page, value); await page.waitForTimeout(700); };
const snap = async (target: Page | Locator, name: string, value: "day" | "night") => { await target.screenshot({ path: `${dir}/${name}-${value === "day" ? "浅色" : "深色"}.png` }); };
const both = async (page: Page, take: (value: "day" | "night") => Promise<void>) => {
  for (const value of ["day", "night"] as const) { await mood(page, value); await take(value); }
  await mood(page, "day");
};
const compose = (page: Page) => thread(page).locator(".a-compose");

test.describe("07f 截图", () => {
  test("01 输入框聚焦：右栏 340 宽、抽屉 400 宽、手机 375 宽；11 花费提示", async ({ page, browser }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await box(page).focus();
    await both(page, async (value) => { await box(page).focus(); await snap(compose(page), "01-输入框聚焦-右栏", value); });
    await box(page).blur();
    await both(page, async (value) => snap(compose(page), "11-花费提示-右栏", value));
    await openTab(page, id, "overview");
    // (The drawer covers the theme switch: each theme is chosen first, then the drawer opened.)
    for (const value of ["day", "night"] as const) {
      await mood(page, value);
      await topbarAssistant(page).click();
      await box(page).focus();
      await snap(compose(page), "01-输入框聚焦-抽屉", value);
      await page.keyboard.press("Escape");
    }
    await mood(page, "day");
    const phone = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const small = await phone.newPage();
    await small.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(small, "shotbar");
    const sample = await sampleWorkId(small);
    await openTab(small, sample, "workspace");
    await small.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await both(small, async (value) => { await box(small).focus(); await snap(compose(small), "01-输入框聚焦-手机", value); });
    await both(small, async (value) => { await box(small).blur(); await snap(compose(small), "11-花费提示-手机", value); });
    await phone.close();
  });

  test("03 查前文矛盾；05 帮我改这一处的标签", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await chooseMode(page, "查前文矛盾");
    await select(page, "#draft-body", 16);
    await expect(chip(page, "选中：「")).toBeVisible();
    await both(page, async (value) => { await select(page, "#draft-body", 16); await page.waitForTimeout(400); await expect(toolbar(page)).toBeVisible(); await page.evaluate(() => window.scrollTo(0, 0)); await snap(page, "03-查前文矛盾", value); });
  });

  test("05 帮我改这一处：标签", async ({ page }) => {
    const { issue } = await checkedWork(page);
    await askForFix(page, issue);
    await tasks(page).last().getByRole("button", { name: "按要求重新给改法", exact: true }).click();
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^某一章/ }).click();
    await thread(page).locator(".cx-menu .scroll [role=menuitem]").first().click();
    await both(page, async (value) => snap(compose(page), "05-检查结果标签", value));
  });

  test("06 提示条和提示框；07 概览按钮", async ({ page, browser }) => {
    const id = await setup(page);
    await openTab(page, id, "overview");
    await both(page, async (value) => snap(page.locator(".band").first(), "07-概览横幅", value));
    const phone = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 700 } });
    const small = await phone.newPage();
    await small.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(small, "shotnote");
    await small.goto("/projects");
    await expect(small.locator(".narrow-note")).toBeVisible();
    await both(small, async (value) => snap(small.locator(".narrow-note"), "06-提示框-手机", value));
    await small.evaluate(() => {
      const toast = document.createElement("div");
      toast.className = "feedback";
      toast.style.animation = "none";
      toast.innerHTML = "<span>已复制，粘到这一句后面</span><button class='feedback-close' aria-label='关闭提示'>×</button>";
      toast.id = "shot-toast";
      document.body.append(toast);
    });
    await both(small, async (value) => snap(small.locator("#shot-toast"), "06-提示条", value));
    await phone.close();
  });

  test("13 补铺垫的改法和跳转后的提示", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const id = await setup(page);
    const first = ((await api(page).get(`/projects/${id}/long-term-review`)).chapters as { number: number; body: string }[]).find((item) => item.number === 1)!;
    const anchor = first.body.split(/\n+/).map((line) => line.trim()).find((line) => line.length > 12)!.split("。")[0] + "。";
    await serveTasks(page, () => [fixView([proposalView({ id: "aprop-setup", proposal: "P2", kind: "add_setup", chapter_number: 1, before: anchor, after: "（示意）前文补这一句。" })])]);
    await page.reload();
    await openAssistantTab(page);
    await both(page, async (value) => snap(tasks(page).first().locator('[data-kind="add_setup"]'), "13-补铺垫的改法", value));
    await page.emulateMedia({ reducedMotion: "no-preference", colorScheme: "light" });
    await tasks(page).first().getByRole("button", { name: "复制这句，去第 1 章", exact: true }).click();
    await expect(page.locator(".feedback")).toContainText("已复制，粘到这一句后面", { timeout: 6_000 });
    await both(page, async (value) => { await page.waitForTimeout(100); await snap(page, "13-跳转后", value); });
  });

  test("16 菜单的键盘焦点；17 旧回答", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    for (const value of ["day", "night"] as const) {
      await mood(page, value);
      await openPlus(page);
      await thread(page).getByRole("menuitem", { name: /^某一章/ }).click();
      const menu = thread(page).getByRole("menu", { name: "加进这次提问" });
      const third = (await menu.getByRole("menuitem").nth(3).boundingBox())!;
      await page.mouse.move(third.x + third.width / 2, third.y + third.height / 2);
      await page.keyboard.press("ArrowDown");
      const [top, form] = [(await menu.boundingBox())!, (await page.locator(".cx").boundingBox())!];
      await page.screenshot({ path: `${dir}/16-菜单焦点-${value === "day" ? "浅色" : "深色"}.png`, clip: { x: Math.max(0, Math.min(top.x, form.x) - 8), y: Math.max(0, top.y - 8), width: Math.max(top.width, form.width) + 16, height: form.y + form.height - top.y + 16 } });
      await page.keyboard.press("Escape");
    }
    await mood(page, "day");
    await serveTasks(page, () => [askView({ id: "atask-old" }), askView({ id: "atask-new", regenerated_from: "atask-old" })]);
    await page.reload();
    await openAssistantTab(page);
    await tasks(page).first().locator("details.a-older > summary").click();
    await both(page, async (value) => snap(tasks(page).first(), "17-旧回答展开", value));
  });

  test("31 手机上的助手窗格", async ({ browser }) => {
    test.setTimeout(150_000);
    const phone = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 } });
    const small = await phone.newPage();
    await small.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(small, "shotpane");
    const id = await sampleWorkId(small);
    await openTab(small, id, "workspace");
    await small.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    for (const [index, question] of ["苏岑是谁？", "温岚是谁？", "罗盘在谁手里？", "老周是谁？"].entries()) { await ask(small, question); await finished(small, index + 1); }
    await small.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await small.waitForTimeout(600);
    await both(small, async (value) => snap(small, "31-手机助手窗格", value));
    await phone.close();
  });

  for (const size of [{ width: 1440, height: 400 }, { width: 1024, height: 400 }]) {
    test(`32 矮窗口 ${size.width}×${size.height} 的菜单`, async ({ page }) => {
      await setup(page);
      await openAssistantTab(page);
      await ask(page, "苏岑知道罗盘被调包了吗？");
      await finished(page);
      await page.setViewportSize(size);
      await box(page).scrollIntoViewIfNeeded();
      await openPlus(page);
      await both(page, async (value) => snap(page, `32-矮窗口菜单-${size.width}x${size.height}`, value));
    });
  }

  test("33 事实摘要的卡片和找不到时的提示", async ({ page }) => {
    const id = await setup(page);
    const chapter = ((await api(page).get(`/projects/${id}/long-term-review`)).chapters as { number: number; title: string }[]).find((item) => item.number === 9)!;
    const source = { R1: { kind: "fact", chapter_number: 9, chapter_title: chapter.title, start: null, end: null, text: "苏岑：把罗盘交给温岚保管", cited: true, anchor: { text: "这句话在第九章里根本没有出现过。", chapter_number: 9 } } };
    await serveTasks(page, () => [askView({ sources: source, steps: [], answer: { status: "answered", sentences: [{ text: "前文写过这件事。", refs: ["R1"] }], note: null } })]);
    await page.reload();
    await openAssistantTab(page);
    await both(page, async (value) => {
      await tasks(page).first().locator(".a-cite button").first().hover();
      const [card, entry] = [(await page.locator(".a-pop").boundingBox())!, (await tasks(page).first().boundingBox())!];
      const [x, y] = [Math.max(0, Math.min(card.x, entry.x) - 8), Math.max(0, Math.min(card.y, entry.y) - 8)];
      await page.screenshot({ path: `${dir}/33-事实卡片-${value === "day" ? "浅色" : "深色"}.png`, clip: { x, y, width: Math.max(card.x + card.width, entry.x + entry.width) + 8 - x, height: Math.max(card.y + card.height, entry.y + entry.height) + 8 - y } });
    });
    await tasks(page).first().locator(".a-cite button").first().hover();
    await tasks(page).first().getByRole("button", { name: "去原文 →" }).click();
    await expect(page.locator(".feedback")).toContainText("没在第 9 章找到对应的原句", { timeout: 6_000 });
    await both(page, async (value) => { await snap(page, "33-找不到提示", value); });
  });
});
