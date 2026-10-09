import { randomUUID } from "node:crypto";
import { api, createWorkByApi, expect, openTab, registerAccount, sampleWorkId, shot, tabLabels, tabOrder, test } from "./support/app";

const workTabs = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "作品", exact: true });
const globalTabs = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "全局", exact: true });

test("顶栏：首页和作品管理标出当前页；作品内五个标签依次排列，点哪个到哪个", async ({ page }) => {
  await registerAccount(page, "topbar");
  const workId = await createWorkByApi(page, { title: "顶栏试验之书" });

  // 全局: 首页 / 作品管理
  await expect(globalTabs(page).getByRole("button", { name: "首页", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(globalTabs(page).getByRole("button", { name: "作品管理", exact: true })).not.toHaveAttribute("aria-current", "page");
  await globalTabs(page).getByRole("button", { name: "作品管理", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(globalTabs(page).getByRole("button", { name: "作品管理", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(globalTabs(page).getByRole("button", { name: "首页", exact: true })).not.toHaveAttribute("aria-current", "page");
  await globalTabs(page).getByRole("button", { name: "首页", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(globalTabs(page).getByRole("button", { name: "首页", exact: true })).toHaveAttribute("aria-current", "page");

  // 作品内: 概览 写作 章节 资料 计划
  await openTab(page, workId, "overview");
  await expect(globalTabs(page)).toHaveCount(0);
  const buttons = workTabs(page).getByRole("button");
  await expect(buttons).toHaveCount(5);
  for (const [index, tab] of tabOrder.entries()) await expect(buttons.nth(index)).toHaveAccessibleName(tabLabels[tab]);
  expect(tabOrder.map((tab) => tabLabels[tab])).toEqual(["概览", "写作", "章节", "资料", "计划"]);
  await shot(page, "shell-overview");

  for (const tab of [...tabOrder, "overview" as const]) {
    await workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${workId}/${tab}$`));
    await expect(workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true })).toHaveAttribute("aria-current", "page");
    // Only the current one is marked.
    await expect(workTabs(page).locator("[aria-current='page']")).toHaveCount(1);
  }
});

test("切换标签不重读作品：作品详情接口的请求数不增加，页面也没有重新加载", async ({ page }) => {
  await registerAccount(page, "tabsame");
  const workId = await createWorkByApi(page, { title: "切换标签之书" });
  const detail = new URL(`/api/projects/${workId}`, "http://x").pathname;
  let reads = 0;
  page.on("request", (request) => { if (request.method() === "GET" && new URL(request.url()).pathname === detail) reads += 1; });

  await openTab(page, workId, "overview");
  await expect(page.getByRole("heading", { level: 1, name: "切换标签之书", exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(reads, "the work is read when it is opened").toBeGreaterThanOrEqual(1);
  const afterOpen = reads;
  // A marker that only a full page load would wipe.
  await page.evaluate(() => { (window as unknown as { __kept: boolean }).__kept = true; });

  for (const tab of [...tabOrder, "memory", "overview"] as const) {
    await workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${workId}/${tab}$`));
    await expect(workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true })).toHaveAttribute("aria-current", "page");
  }
  await page.waitForLoadState("networkidle");
  expect(reads, "switching tabs must not read the work again").toBe(afterOpen);
  expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);
  // A different work does read its own record.
  const other = await createWorkByApi(page, { title: "另一部" });
  await page.goto(`/projects/${other}/overview`);
  await expect(page.getByRole("heading", { level: 1, name: "另一部", exact: true })).toBeVisible();
});

test("切换作品：用顶栏的「更换当前作品」换到另一部，网址和标题都跟着换", async ({ page }) => {
  await registerAccount(page, "switchwork");
  const first = await createWorkByApi(page, { title: "第一部书" });
  const second = await createWorkByApi(page, { title: "第二部书" });
  await openTab(page, first, "overview");
  await expect(page.getByRole("heading", { level: 1, name: "第一部书", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "更换当前作品：第一部书", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await page.getByRole("main").getByRole("button", { name: /第二部书/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`/projects/${second}/overview$`));
  await expect(page.getByRole("heading", { level: 1, name: "第二部书", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "更换当前作品：第二部书", exact: true })).toBeVisible();
  await expect(page.getByText("第一部书")).toHaveCount(0);
  // The sample work can be switched to as well.
  const sample = await sampleWorkId(page);
  await page.goto(`/projects/${sample}/overview`);
  await expect(page.getByRole("button", { name: "更换当前作品：灰港回声", exact: true })).toBeVisible();
});

test("找不到页面：未知网址和不存在的作品都有自己的说明", async ({ page }) => {
  await registerAccount(page, "notfound");
  await page.goto("/不存在的路径");
  await expect(page.getByRole("heading", { level: 1, name: "找不到这个页面", exact: true })).toBeVisible();
  await expect(page.getByText("网址可能输错了，或者这个页面已经不在了。", { exact: true })).toBeVisible();
  await shot(page, "not-found");
  await page.getByRole("button", { name: "回到首页", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);

  const missing = `prj-${randomUUID()}`;
  expect((await api(page).raw("GET", `/projects/${missing}`)).status).toBe(404);
  await page.goto(`/projects/${missing}/overview`);
  await expect(page.getByRole("heading", { level: 1, name: "找不到这部作品", exact: true })).toBeVisible();
  await expect(page.getByText("它可能已经删除，或者不属于当前账号。其他作品不受影响。", { exact: true })).toBeVisible();
  await shot(page, "work-not-found");
  await page.getByRole("button", { name: "作品管理", exact: true }).last().click();
  await expect(page).toHaveURL(/\/projects$/);
});

test("跳到主要内容：第一次按 Tab 落在跳转链接上，回车后下一个焦点进入主要内容区", async ({ page }) => {
  test.fixme(true, "清单第 17 条：首页重渲染使跳转链接的焦点起点不稳定；按 08 任务要求保留原断言并标记待修");
  await registerAccount(page, "skiplink");
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "从第一章开始", exact: true })).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "跳到主要内容", exact: true });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main$/);
  // The browser moves its focus starting point to the main content: the next Tab lands on the first
  // control inside it, not back in the top bar.
  await page.keyboard.press("Tab");
  await expect.poll(() => page.evaluate(() => Boolean(document.getElementById("main")?.contains(document.activeElement)))).toBe(true);
});
