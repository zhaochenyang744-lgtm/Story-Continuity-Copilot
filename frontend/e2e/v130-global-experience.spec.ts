import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin = process.env.E2E_BACKEND_ORIGIN;
if (!backendOrigin) throw new Error("E2E_BACKEND_ORIGIN is required");
const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix) throw new Error("E2E_ACCOUNT_PREFIX is required");

async function register(page: Page, prefix: string) {
  const account = `${accountPrefix}${prefix}${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await expect(page.locator('.auth-brand img.brand-lockup[alt="Story Continuity"]')).toBeVisible();
  await expect(page.getByRole("heading", { name: "创建账号", exact: true })).toBeVisible();
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("初始作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  return { account, password };
}

async function screenshot(page: Page, name: string) {
  if (!process.env.E2E_OUTPUT_DIR) return;
  await page.waitForTimeout(180);
  await page.screenshot({ path: path.join(process.env.E2E_OUTPUT_DIR, name), fullPage: true });
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

async function createProject(page: Page, title: string) {
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "新建作品", exact: true }).click();
  await page.getByLabel("作品名称", { exact: true }).fill(title);
  await page.getByLabel("类型", { exact: true }).fill("长篇悬疑");
  await page.getByLabel("简介", { exact: true }).fill("用于验证全局体验层级。");
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
}

test("personal profile persists display identity without changing the login account", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const initialStats = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  const initial = (await initialStats.json()) as { provider_calls: number; provider_http_calls: number };
  const credentials = await register(page, "profile");

  await expect(page.locator('.global-nav .brand-lockup[alt="Story Continuity"]')).toBeVisible();
  const favicon = page.locator('link[rel="icon"]').first();
  await expect(favicon).toHaveAttribute("href", /\/icon\.svg/);
  await createProject(page, "灰港手稿");
  await expect(page.locator(".project-nav")).toBeVisible();

  const expandedGeometry = await page.evaluate(() => {
    const global = document.querySelector<HTMLElement>(".global-nav")?.getBoundingClientRect();
    const project = document.querySelector<HTMLElement>(".project-nav")?.getBoundingClientRect();
    if (!global || !project) throw new Error("desktop navigation geometry missing");
    return { globalWidth: global.width, projectLeft: project.left };
  });
  await page.getByRole("button", { name: "收起全局侧栏", exact: true }).click();
  await expect(page.locator(".workbench")).toHaveClass(/global-nav-collapsed/);
  await expect.poll(() => page.locator(".global-nav").evaluate((node) => node.getBoundingClientRect().width)).toBeLessThan(expandedGeometry.globalWidth - 100);
  await expect.poll(() => page.locator(".project-nav").evaluate((node) => node.getBoundingClientRect().left)).toBeLessThan(expandedGeometry.projectLeft - 100);
  const collapsedGeometry = await page.evaluate(() => {
    const global = document.querySelector<HTMLElement>(".global-nav")?.getBoundingClientRect();
    const project = document.querySelector<HTMLElement>(".project-nav")?.getBoundingClientRect();
    if (!global || !project) throw new Error("collapsed navigation geometry missing");
    return { globalWidth: global.width, projectLeft: project.left, stored: localStorage.getItem("story-continuity:global-nav-collapsed") };
  });
  expect(collapsedGeometry.globalWidth).toBeLessThan(expandedGeometry.globalWidth - 100);
  expect(collapsedGeometry.projectLeft).toBeLessThan(expandedGeometry.projectLeft - 100);
  expect(collapsedGeometry.stored).toBe("true");
  await page.reload();
  await expect(page.getByRole("button", { name: "展开全局侧栏", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "展开全局侧栏", exact: true }).click();
  await expect(page.locator(".workbench")).not.toHaveClass(/global-nav-collapsed/);

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  const menu = page.getByRole("menu", { name: "用户菜单", exact: true });
  await expect(menu.getByRole("menuitem", { name: "个人信息", exact: true })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "账号安全", exact: true })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "重新打开教学", exact: true })).toBeVisible();
  await expect(menu.getByRole("menuitem", { name: "退出登录", exact: true })).toBeVisible();
  await menu.getByRole("menuitem", { name: "个人信息", exact: true }).click();
  await expect(page).toHaveURL(/\/account\/profile$/);
  await expect(page.getByRole("heading", { name: "创作概况", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "我的作品", exact: true })).toBeVisible();
  await expect(page.getByText("灰港手稿", { exact: true })).toBeVisible();
  await expect(page.locator(".author-stat-list")).toContainText("真实作品1");
  await expect(page.locator(".author-stat-list")).toContainText("已写章节0");
  await expect(page.locator(".author-stat-list")).toContainText("正文与草稿字数0");
  await expect(page.locator(".compact-avatar-picker")).toHaveCount(0);
  await expect(page.getByText(credentials.account, { exact: true }).first()).toBeVisible();
  await page.getByLabel("显示名称", { exact: true }).fill("灰港编辑");
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "更换头像", exact: true })).toBeVisible();
  await page.getByText("档案蓝", { exact: true }).click();
  await expect(page.getByRole("radio", { name: /档案蓝/ })).toBeChecked();
  await expect(page.locator('.avatar-picker-dialog img[src*="archive-blue.webp"]')).toBeVisible();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  await page.getByRole("button", { name: "保存资料", exact: true }).click();
  await expect(page.getByText("个人信息已保存。", { exact: true })).toBeVisible();
  await expect(page.locator(".account-name")).toHaveText("灰港编辑");
  await expect(page.locator(".account-avatar")).toHaveClass(/avatar-archive_blue/);
  await screenshot(page, "global-01-profile-desktop.png");

  await page.reload();
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue("灰港编辑");
  await page.getByRole("button", { name: "更换头像", exact: true }).click();
  await expect(page.getByRole("radio", { name: /档案蓝/ })).toBeChecked();
  await page.getByRole("button", { name: "完成", exact: true }).click();
  const session = await page.request.get(`${backendOrigin}/api/auth/session`);
  const persisted = (await session.json()) as { data: { user: { account_name: string; display_name: string; avatar_preset: string } } };
  expect(persisted.data.user).toMatchObject({ account_name: credentials.account, display_name: "灰港编辑", avatar_preset: "archive_blue" });

  await page.setViewportSize({ width: 390, height: 844 });
  await noOverflow(page);
  await screenshot(page, "global-02-profile-390.png");
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  await expect(page.locator('.auth-brand img.brand-lockup[alt="Story Continuity"]')).toBeVisible();
  await screenshot(page, "global-03-login-brand.png");
  await page.getByLabel("账号").fill(credentials.account);
  await page.locator('input[name="password"]').fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.locator(".account-name")).toHaveText("灰港编辑");
  await expect(page.locator(".account-avatar")).toHaveClass(/avatar-archive_blue/);
  const finalStats = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  const final = (await finalStats.json()) as { provider_calls: number; provider_http_calls: number };
  expect(final.provider_calls).toBe(initial.provider_calls);
  expect(final.provider_http_calls).toBe(0);
});

test("overview hierarchy expands and centers at wide sizes while remaining readable at 390px", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "overview");
  await createProject(page, "概览层级验证");
  await expect(page.locator(".overview-primary-card")).toHaveCount(2);
  await expect(page.locator(".overview-reference-card")).toHaveCount(3);
  await expect(page.locator(".latest-run-card")).toHaveCount(1);
  await expect(page.locator(".current-draft-panel")).toContainText("0 个章节");
  await expect(page.locator(".current-draft-panel .draft-progress")).toHaveCount(0);
  await expect(page.getByRole("button", { name: "打开当前草稿", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "查看 Story Memory", exact: true })).toBeVisible();
  await screenshot(page, "global-03-overview-1440.png");

  await page.setViewportSize({ width: 1920, height: 1080 });
  const at1920 = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>("main")?.getBoundingClientRect();
    const content = document.querySelector<HTMLElement>(".overview-page")?.getBoundingClientRect();
    if (!main || !content) throw new Error("overview geometry missing");
    return { left: content.left, width: content.width, centerDelta: Math.abs((content.left + content.right) / 2 - (main.left + main.right) / 2) };
  });
  expect(at1920.width).toBeGreaterThan(1200);
  expect(at1920.width).toBeLessThanOrEqual(1441);
  expect(at1920.centerDelta).toBeLessThanOrEqual(1);
  await noOverflow(page);
  await screenshot(page, "global-04-overview-1920.png");

  await page.setViewportSize({ width: 2560, height: 1080 });
  const at2560 = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>("main")?.getBoundingClientRect();
    const content = document.querySelector<HTMLElement>(".overview-page")?.getBoundingClientRect();
    if (!main || !content) throw new Error("overview geometry missing");
    return { left: content.left, width: content.width, centerDelta: Math.abs((content.left + content.right) / 2 - (main.left + main.right) / 2) };
  });
  expect(at2560.left).toBeGreaterThan(at1920.left + 250);
  expect(at2560.width).toBeLessThanOrEqual(1441);
  expect(at2560.centerDelta).toBeLessThanOrEqual(1);
  await noOverflow(page);
  await screenshot(page, "global-05-overview-2560.png");

  await page.goto("/projects/new");
  const createCenter = await page.locator(".create-project-page").evaluate((node) => {
    const box = node.getBoundingClientRect();
    const main = node.closest("main")?.getBoundingClientRect();
    if (!main) throw new Error("create page main missing");
    return Math.abs((box.left + box.right) / 2 - (main.left + main.right) / 2);
  });
  expect(createCenter).toBeLessThanOrEqual(1);

  await page.goBack();
  await expect(page.locator(".overview-page")).toBeVisible();
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".overview-primary-card")).toHaveCount(2);
  await expect(page.locator(".overview-reference-card")).toHaveCount(3);
  await noOverflow(page);
  await screenshot(page, "global-06-overview-390.png");
});

test("writing issues preserve real Evidence, SourceSpan, keyboard focus, and provider isolation", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const initialStats = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  const initial = (await initialStats.json()) as { provider_calls: number; provider_http_calls: number };
  await register(page, "evidence");
  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await expect(page.locator(".issue-list li").first()).toBeVisible();
  await screenshot(page, "global-07-writing-check.png");

  const issueTrigger = page.locator(".issue-list li").first().getByRole("button");
  await issueTrigger.click();
  const evidence = page.getByRole("dialog", { name: "问题证据", exact: true });
  await expect(evidence).toBeVisible();
  await expect(evidence.getByText("对照当前草稿与已写章节来源，再作出作者决定。", { exact: true })).toBeVisible();
  await expect(evidence.getByRole("button", { name: "关闭", exact: true })).toBeFocused();
  const sourceTrigger = evidence.getByRole("button", { name: /查看来源/ }).first();
  const evidenceUrl = page.url();
  await sourceTrigger.click();
  const source = page.getByRole("dialog", { name: /章节来源/ });
  await expect(source).toBeVisible();
  expect(page.url()).toBe(evidenceUrl);
  await expect(source.locator(".source-technical")).toContainText(/SourceSpan|来源片段/);
  await expect(source.locator(".source-excerpt mark")).not.toHaveText("引用内容未提供");
  await screenshot(page, "global-08-evidence-source.png");
  await page.keyboard.press("Escape");
  await expect(source).toHaveCount(0);
  await expect(sourceTrigger).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(evidence).toHaveCount(0);
  await expect(issueTrigger).toBeFocused();
  await noOverflow(page);

  const finalStats = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  const final = (await finalStats.json()) as { provider_calls: number; provider_http_calls: number };
  expect(final.provider_calls).toBe(initial.provider_calls);
  expect(final.provider_http_calls).toBe(0);
});
