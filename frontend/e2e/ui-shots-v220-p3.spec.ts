import { mkdir } from "node:fs/promises";
import type { Page } from "@playwright/test";
import { advanceTour, api, archiveWorkByApi, createWorkByApi, expect, newPage, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { button, decide, finding, findings, run, selectIssue } from "./support/writing";

// Pictures for the v2.2 UI delivery, phase three (task 19): every place the page fixes changed, as it was (前) and as it is (后); 1440 by day and by night, and 375
// by day. The same file is run against the build before the changes and the build after them; UI_SHOTS3_TAG says which. Taken only when UI_SHOTS3_DIR names a folder.
const dir = process.env.UI_SHOTS3_DIR;
const tag = process.env.UI_SHOTS3_TAG ?? "后";
test.skip(!dir, "UI_SHOTS3_DIR is not set");
test.use({ actionTimeout: 15_000 });

const setMood = (page: Page, value: "day" | "night") => page.evaluate((v) => { document.documentElement.dataset.theme = v; }, value);
const hideDevBadge = (page: Page) => page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });
const dockOpen = (page: Page, open: boolean) => page.evaluate((wanted) => {
  try { window.localStorage.setItem("story-continuity:assistant-dock", wanted ? "open" : "closed"); } catch { /* nothing to keep */ }
}, open);

type Scene = (page: Page) => Promise<void>;
async function photograph(page: Page, name: string, scene: Scene, options: { fullPage?: boolean } = {}) {
  await mkdir(dir!, { recursive: true });
  for (const size of [1440, 375] as const) {
    await page.setViewportSize({ width: size, height: size === 375 ? 812 : 900 });
    await scene(page);
    await hideDevBadge(page);
    for (const mood of size === 1440 ? (["day", "night"] as const) : (["day"] as const)) {
      await setMood(page, mood);
      await page.evaluate(async () => { await document.fonts.ready; });
      await page.waitForTimeout(400);
      await page.screenshot({ path: `${dir}/${name}-${tag}-${size === 1440 ? "1440" : "375"}-${mood === "day" ? "浅色" : "深色"}.png`, fullPage: options.fullPage ?? false, animations: "disabled" });
    }
    await setMood(page, "day");
  }
}

test("ui screenshots 3: the page fixes", async ({ page, browser }) => {
  test.setTimeout(1_500_000);
  await page.setViewportSize({ width: 1440, height: 900 });

  // 01 作品管理，还没有作品（一个新账号）
  const fresh = await newPage(browser);
  await registerAccount(fresh, "p3empty");
  await photograph(fresh, "01-作品管理-没有作品", async (p) => { await p.goto("/projects"); await expect(p.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible(); await p.waitForTimeout(300); });
  await fresh.context().close();

  // The working account: the sample, two works of its own, one of them archived.
  await registerAccount(page, "p3shots");
  const sample = await sampleWorkId(page);
  await api(page).post("/onboarding/skip", { confirm: true }).catch(() => undefined);
  await dockOpen(page, false);
  const own = await createWorkByApi(page, { title: "雾港旧事", genre: "悬疑", summary: "一封寄错地址的信，牵出港口多年前的一桩旧案。" });
  await createWorkByApi(page, { title: "北堤来客", genre: "历史", summary: "北堤上的一桩旧案。" });
  const old = await createWorkByApi(page, { title: "归档的旧稿", genre: "现实", summary: "" });
  await archiveWorkByApi(page, old);

  // 02 作品管理，有作品，卡片的更多
  await photograph(page, "02-作品管理-卡片的更多", async (p) => {
    await p.goto("/projects");
    await expect(p.getByRole("main").getByRole("listitem").filter({ hasText: "雾港旧事" })).toBeVisible();
    await p.getByRole("main").getByRole("listitem").filter({ hasText: "雾港旧事" }).getByLabel("更多：雾港旧事", { exact: true }).click();
    await p.waitForTimeout(200);
  });
  await page.keyboard.press("Escape");

  // 03 归档作品的概览（只读时的说明）
  await photograph(page, "03-归档作品的概览", async (p) => { await openTab(p, old, "overview"); await p.waitForTimeout(500); }, { fullPage: true });

  // 04 检查结果展开后的动作（还没处理）
  const result = await run(page, sample);
  await photograph(page, "04-检查结果展开-动作", async (p) => {
    await openTab(p, sample, "workspace");
    if (p.viewportSize()!.width < 1024) await p.getByRole("navigation", { name: "切换内容" }).getByRole("button", { name: /^检查结果/ }).click();
    await selectIssue(p, result.issues[0]);
    await finding(p, result.issues[0].id).scrollIntoViewIfNeeded();
    await p.waitForTimeout(300);
  });

  // 05 助手面板打开时顶栏的按钮，和收起的提示
  await photograph(page, "05-助手面板-顶栏按钮", async (p) => {
    await dockOpen(p, true);
    await openTab(p, sample, "workspace");
    if (!(await p.locator("#assistant-dock").isVisible())) await p.locator("#assistant-open").click();
    await expect(p.locator("#assistant-dock")).toBeVisible();
    await p.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await p.waitForTimeout(300);
  });
  await dockOpen(page, false);

  // 06 检查结果：前三条处理完，证据不足那条还没看（在桌面宽度的写作页上处理）
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, sample, "workspace");
  for (const issue of result.issues) {
    if (issue.nature === "insufficient_evidence") continue;
    await decide(page, sample, issue, issue.nature === "state_change" ? "保留这个变化" : "是有意的", "keep_intentional");
  }
  await photograph(page, "06-检查结果-还有证据不足没看", async (p) => {
    await openTab(p, sample, "workspace");
    if (p.viewportSize()!.width < 1024) await p.getByRole("navigation", { name: "切换内容" }).getByRole("button", { name: /^检查结果/ }).click();
    await findings(p).evaluate((node) => { node.scrollTop = 0; });
    await p.waitForTimeout(300);
  });

  // 07 章节页选两章，字数和预计
  await photograph(page, "07-章节-选两章的字数", async (p) => {
    await openTab(p, sample, "sources");
    const boxes = p.getByRole("checkbox", { name: /^选择第 \d+ 章$/ });
    if (await boxes.count()) { for (const index of [0, 1]) { const box = boxes.nth(index); if (!(await box.isChecked())) await box.check(); } }
    await p.getByTestId("chapter-selection").scrollIntoViewIfNeeded().catch(() => undefined);
    await p.waitForTimeout(600);
  });

  // 08 旧章修订的预览
  await photograph(page, "08-旧章修订-预览", async (p) => {
    await p.goto(`/projects/${sample}/workspace?chapter=3`);
    await expect(p.getByRole("textbox", { name: "第 3 章正文（只读）", exact: true })).toBeVisible();
    if (p.viewportSize()!.width >= 1024) {
      await button(p, "修改这一章").click();
      await p.getByRole("textbox", { name: "第 3 章正文", exact: true }).press("Control+End");
      await p.keyboard.insertText("测试值班员在门边记下了新的潮水高度。");
      await button(p, "预览修改影响").click();
      await expect(p.getByText("条已确认的事实需要复核", { exact: true })).toBeVisible();
      await p.waitForTimeout(400);
    }
  });
  await page.goto("/projects");
  await page.evaluate(() => { try { Object.keys(window.localStorage).filter((key) => key.includes("revision")).forEach((key) => window.localStorage.removeItem(key)); } catch { /* none */ } });

  // 09 计划页，归档的计划
  const version = async () => (await api(page).get(`/projects/${own}/author-intent`)).author_context_version as number;
  await api(page).post(`/projects/${own}/author-intent/story-plans`, { base_author_context_version: await version(), title: "旧潮位牌的下落", summary: "拆开背板，看见里面的东西。", goal: "让读者知道牌是被人动过的", status: "planned" });
  const plan = (await api(page).get(`/projects/${own}/author-intent`)).story_plans.find((item: { title: string }) => item.title === "旧潮位牌的下落");
  await api(page).post(`/projects/${own}/author-intent/story-plans/${plan.id}/archive`, { base_author_context_version: await version(), confirm: true });
  await photograph(page, "09-计划-归档的计划", async (p) => {
    await openTab(p, own, "plan");
    await p.getByRole("button", { name: /^(已归档 1 条|收起)/ }).click();
    const entry = p.locator(".plan-archived").getByRole("button", { name: /旧潮位牌的下落/ });
    if (await entry.count()) await entry.click();
    await p.locator(".plan-archived").scrollIntoViewIfNeeded();
    await p.waitForTimeout(300);
  });

  // 10 资料：事实，设定
  await photograph(page, "10-资料-事实", async (p) => { await openTab(p, sample, "memory"); await p.waitForTimeout(500); });
  await photograph(page, "11-资料-设定", async (p) => {
    await openTab(p, sample, "memory");
    await p.getByRole("button", { name: /^设定/ }).first().click();
    await p.waitForTimeout(500);
  }, { fullPage: true });

  // 12 后端连不上
  await photograph(page, "12-后端连不上", async (p) => {
    await p.route("**/api/auth/session**", (route) => route.abort());
    await p.goto("/projects");
    await p.waitForTimeout(900);
  });
  await page.unroute("**/api/auth/session**");

  // 13 访客的用量说明
  const guest = await newPage(browser);
  await startVisitor(guest);
  await photograph(guest, "13-访客的用量说明", async (p) => { await p.goto("/settings/usage"); await p.waitForTimeout(700); });
  await guest.context().close();

  // 14 导览第 2 步：到了写作页
  const tour = await newPage(browser);
  await registerAccount(tour, "p3tour");
  const tourWork = await sampleWorkId(tour);
  await advanceTour(tour, tourWork, 2);
  await photograph(tour, "14-导览-到了写作页", async (p) => { await openTab(p, tourWork, "workspace"); await p.waitForTimeout(700); });
  await tour.context().close();
});
