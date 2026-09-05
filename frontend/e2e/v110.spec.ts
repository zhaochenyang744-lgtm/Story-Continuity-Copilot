import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const outputDir = process.env.E2E_OUTPUT_DIR!;

async function register(page: Page, prefix: string, displayNameSameAsAccount = false) {
  const account = `${prefix}${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill(displayNameSameAsAccount ? account : "v1.1.0 作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  return { account, password };
}

async function expectMobileGeometry(page: Page, heading: string) {
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  expect(await page.locator(".global-nav").evaluate((node) => node.getBoundingClientRect().height)).toBe(56);
  const headingBox = await page.getByRole("heading", { name: heading, exact: true }).boundingBox();
  if (!headingBox) throw new Error(`${heading} is not measurable`);
  expect(headingBox.y).toBeLessThanOrEqual(150);
  const targets = await page.locator("button:visible, summary:visible, [role=switch]:visible").evaluateAll((nodes) => nodes.map((node) => {
    const box = node.getBoundingClientRect();
    return { text: node.textContent?.trim(), width: box.width, height: box.height };
  }));
  expect(targets.filter((target) => target.width < 44 || target.height < 44)).toEqual([]);
}

async function expectHomeSectionHeaderAlignment(page: Page) {
  const offsets = await page.locator(".home-section").evaluateAll((sections) => sections.map((section) => {
    const header = section.querySelector(":scope > .home-section-head, :scope > h2");
    const content = section.querySelector(":scope > .home-work-list, :scope > .home-issue-list, :scope > .compact-empty");
    if (!header || !content) throw new Error("home section alignment nodes are missing");
    const sectionBox = section.getBoundingClientRect();
    const headerBox = header.getBoundingClientRect();
    const contentBox = content.getBoundingClientRect();
    const dividerMidpoint = (sectionBox.top + contentBox.top) / 2;
    const headerMidpoint = headerBox.top + headerBox.height / 2;
    return Math.abs(dividerMidpoint - headerMidpoint);
  }));
  expect(offsets).toHaveLength(2);
  expect(offsets.every((offset) => offset <= 1)).toBe(true);
}

async function apiData<T>(page: Page, endpoint: string): Promise<T> {
  return page.evaluate(async (url) => {
    const response = await fetch(url, { credentials: "same-origin" });
    const payload = await response.json();
    if (!response.ok) throw new Error(`${response.status}:${payload.error?.code}`);
    return payload.data as T;
  }, endpoint);
}

test("login fits a 1366x720 viewport with in-field password controls", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 720 });
  await page.goto("/login");
  const card = page.locator(".auth");
  const password = page.locator('input[name="password"]');
  const toggle = page.getByRole("button", { name: "显示密码", exact: true });
  await expect(card).toBeVisible();
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  const [cardBox, passwordBox, toggleBox] = await Promise.all([card.boundingBox(), password.boundingBox(), toggle.boundingBox()]);
  if (!cardBox || !passwordBox || !toggleBox) throw new Error("login layout is not measurable");
  expect(cardBox.y + cardBox.height).toBeLessThanOrEqual(720);
  expect(toggleBox.x).toBeGreaterThan(passwordBox.x + passwordBox.width - 80);
  expect(toggleBox.y).toBeGreaterThanOrEqual(passwordBox.y);
  expect(toggleBox.height).toBeGreaterThanOrEqual(44);
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(page.getByRole("button", { name: "忘记密码？", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "还没有账号？创建账号", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "访客体验 24 小时", exact: true })).toBeVisible();
  await page.screenshot({ path: path.join(outputDir, "1366x720-login.png"), fullPage: true });
});

test("visual system uses an accessible manuscript mark, role-based fonts, and reduced static frames", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "v110visual");
  await expect(page.locator(".global-nav img.brand-lockup")).toHaveCount(1);
  await expect(page.locator(".global-nav img.brand-lockup")).toHaveAttribute("alt", "Story Continuity");
  const fonts = await page.evaluate(() => ({
    body: getComputedStyle(document.body).fontFamily,
    heading: getComputedStyle(document.querySelector("h1")!).fontFamily,
    bodySize: parseFloat(getComputedStyle(document.body).fontSize),
  }));
  expect(fonts.body).toContain("Inter");
  expect(fonts.heading).toMatch(/Songti|STSong|Noto Serif|Source Han Serif/i);
  expect(fonts.bodySize).toBeGreaterThanOrEqual(14);

  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  await expect(page.getByRole("heading", { name: "教学模式 · 灰港回声", exact: true })).toBeVisible();
  const primaryPanelStyles = await page.locator(".overview-page .overview-primary-card").evaluateAll((nodes) => nodes.map((node) => {
    const style = getComputedStyle(node);
    return {
      borderRadius: style.borderRadius,
      backgroundImage: style.backgroundImage,
      boxShadow: style.boxShadow,
    };
  }));
  const referencePanelStyles = await page.locator(".overview-page .overview-reference-card").evaluateAll((nodes) => nodes.map((node) => {
    const style = getComputedStyle(node);
    return {
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
    };
  }));
  expect(primaryPanelStyles).toHaveLength(2);
  expect(primaryPanelStyles.every((style) =>
    style.borderRadius === "12px" &&
    style.backgroundImage.includes("linear-gradient") &&
    style.boxShadow !== "none"
  )).toBe(true);
  expect(referencePanelStyles).toHaveLength(3);
  expect(referencePanelStyles.every((style) =>
    style.borderRadius === "10px" &&
    style.boxShadow === "none"
  )).toBe(true);
});

test("first-run tutorial is isolated, resumable, and mobile read-only actions are hidden", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const initialStats = await page.request.get("/api/test/stage12/stats");
  const initialProviderCalls = (await initialStats.json()).provider_calls as number;
  const credentials = await register(page, "v110tutorial");
  const onboarding = await apiData<{ status: string; real_project_count: number; tutorial: { project_id: string } }>(page, "/api/onboarding");
  const projects = await apiData<{ projects: unknown[] }>(page, "/api/projects");
  expect(onboarding.status).toBe("active");
  expect(onboarding.real_project_count).toBe(0);
  expect(projects.projects).toEqual([]);
  await expect(page.getByLabel("首次教学")).toBeVisible();
  await expect(page.getByText("从第一章开始建立连续性档案", { exact: true })).toHaveCount(0);
  const homeWidth = await page.locator(".home-page").evaluate((node) => node.getBoundingClientRect().width);
  expect(homeWidth).toBeGreaterThanOrEqual(1080);
  expect(homeWidth).toBeLessThanOrEqual(1160);
  await expectHomeSectionHeaderAlignment(page);
  await page.screenshot({ path: path.join(outputDir, "1440-first-run-home.png"), fullPage: true });

  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  await expect(page.getByRole("heading", { name: "教学模式 · 灰港回声", exact: true })).toBeVisible();
  await expect(page.getByLabel("教学模式")).toContainText("不计入真实作品");
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 1 / 5");
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("认识作品资料与 Story Memory");
  await expect(page.getByRole("button", { name: "跳过教学", exact: true })).toBeVisible();
  await expect(page.getByText("预置演示审阅数据", { exact: false }).first()).toBeVisible();
  const projectWidth = await page.locator(".project-page").evaluate((node) => node.getBoundingClientRect().width);
  expect(projectWidth).toBeLessThanOrEqual(1160);
  await expect(page.locator(".project-page-header .more-menu")).toBeVisible();

  await expectMobileGeometry(page, "教学模式 · 灰港回声");
  await expect(page.locator(".readonly").filter({ hasText: "当前窗口较窄，暂为只读浏览；放大窗口即可继续写作与检查。" })).toBeVisible();
  await expect(page.getByRole("button", { name: "Reset 当前作品", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "完成当前章节", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "运行连续性检查", exact: true })).toHaveCount(0);
  const primaryPanelStyles = await page.locator(".overview-page .overview-primary-card").evaluateAll((nodes) => nodes.map((node) => {
    const style = getComputedStyle(node);
    return {
      borderLeftWidth: style.borderLeftWidth,
      borderRightWidth: style.borderRightWidth,
      borderRadius: style.borderRadius,
      backgroundImage: style.backgroundImage,
      boxShadow: style.boxShadow,
    };
  }));
  const referencePanelStyles = await page.locator(".overview-page .overview-reference-card").evaluateAll((nodes) => nodes.map((node) => {
    const style = getComputedStyle(node);
    return {
      borderLeftWidth: style.borderLeftWidth,
      borderRightWidth: style.borderRightWidth,
      borderRadius: style.borderRadius,
      boxShadow: style.boxShadow,
    };
  }));
  expect(primaryPanelStyles).toHaveLength(2);
  expect(primaryPanelStyles.every((style) =>
    style.borderLeftWidth === "1px" &&
    style.borderRightWidth === "1px" &&
    style.borderRadius === "12px" &&
    style.backgroundImage.includes("linear-gradient") &&
    style.boxShadow !== "none"
  )).toBe(true);
  expect(referencePanelStyles).toHaveLength(3);
  expect(referencePanelStyles.every((style) =>
    style.borderLeftWidth === "1px" &&
    style.borderRightWidth === "1px" &&
    style.borderRadius === "10px" &&
    style.boxShadow === "none"
  )).toBe(true);
  await page.screenshot({ path: path.join(outputDir, "390-tutorial-step1.png"), fullPage: true });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: path.join(outputDir, "1440-tutorial-step1.png"), fullPage: true });
  await page.getByRole("button", { name: "Story Memory", exact: true }).click();
  await page.locator(".memory-source:not(:disabled)").first().click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 2 / 5");
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("进入连续性检查");
  await page.screenshot({ path: path.join(outputDir, "1440-tutorial-step2.png"), fullPage: true });
  await page.getByRole("button", { name: "关闭章节来源", exact: true }).click();
  await page.getByRole("button", { name: "去写作与检查", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 3 / 5");
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("对照当前草稿与历史证据");
  await page.locator(".issue-list button").first().click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 4 / 5");
  const evidence = page.getByRole("dialog", { name: "问题证据" });
  await expect(evidence.getByRole("heading", { name: "作者决定", exact: true })).toBeVisible();
  await evidence.getByRole("button", { name: "保留当前写法", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 5 / 5");
  await page.screenshot({ path: path.join(outputDir, "1440-tutorial-step5.png"), fullPage: true });
  await evidence.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(evidence).toHaveCount(0);
  await page.getByRole("button", { name: "完成教学", exact: true }).click();
  await expect(page.getByRole("heading", { name: "教学已完成", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "返回首页", exact: true }).click();
  await expect(page.getByText("从第一章开始建立连续性档案", { exact: true })).toBeVisible();
  await expect(page.getByText("导入 TXT / Markdown，或从空白作品开始。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "导入第一部作品", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建空白作品", exact: true })).toBeVisible();
  await expectHomeSectionHeaderAlignment(page);
  await page.screenshot({ path: path.join(outputDir, "390-empty-home.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.screenshot({ path: path.join(outputDir, "1440-empty-home.png"), fullPage: true });
  await page.reload();
  await expect(page.getByLabel("首次教学")).toHaveCount(0);
  expect((await apiData<{ status: string }>(page, "/api/onboarding")).status).toBe("completed");

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await expect(page.getByRole("menu", { name: "用户菜单", exact: true })).toBeVisible();
  await page.waitForTimeout(180);
  await page.screenshot({ path: path.join(outputDir, "1440-account-menu.png"), fullPage: true });
  await page.getByRole("menuitem", { name: "重新打开教学", exact: true }).click();
  await expect(page.getByRole("heading", { name: "教学模式 · 灰港回声", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "跳过教学", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await expect(page.getByRole("menu", { name: "用户菜单", exact: true })).toBeVisible();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await page.getByLabel("账号").fill(credentials.account);
  await page.locator('input[name="password"]').fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  await expect(page.getByLabel("首次教学")).toHaveCount(0);
  expect((await apiData<{ status: string }>(page, "/api/onboarding")).status).toBe("skipped");
  const stats = await page.request.get("/api/test/stage12/stats");
  expect(await stats.json()).toMatchObject({ provider_calls: initialProviderCalls, provider_http_calls: 0 });
});

test("direct import exits first run and project management adapts from desktop row to mobile card", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "v110import");
  await page.getByRole("button", { name: "导入第一部作品", exact: true }).click();
  await page.locator('input[type="file"]').setInputFiles({
    name: "first-story.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 第一章\n这是第一部真实作品。\n# 第二章\n故事继续。", "utf-8"),
  });
  await page.getByRole("button", { name: "解析并预览章节", exact: true }).click();
  await expect(page.getByRole("heading", { name: "章节预览", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "继续确认", exact: true }).click();
  await page.getByLabel("作品名").fill("第一部真实作品");
  await page.getByLabel("类型").fill("悬疑");
  await page.getByRole("button", { name: "确认导入", exact: true }).click();
  await expect(page.getByRole("heading", { name: "第一部真实作品", exact: true })).toBeVisible();
  const afterImport = await apiData<{ status: string; real_project_count: number }>(page, "/api/onboarding");
  expect(afterImport).toMatchObject({ status: "completed", real_project_count: 1 });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page.locator(".readonly").filter({ hasText: "当前窗口较窄，暂为只读浏览；放大窗口即可继续写作与检查。" })).toBeVisible();
  const workspaceHeading = page.locator(".workspace-page h1");
  const workspaceHeadingBox = await workspaceHeading.boundingBox();
  if (!workspaceHeadingBox) throw new Error("real workspace heading is not measurable");
  expect(workspaceHeadingBox.y).toBeLessThanOrEqual(150);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(outputDir, "390-real-workspace.png"), fullPage: true });

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.screenshot({ path: path.join(outputDir, "1440-projects.png"), fullPage: true });
  const issueSwitch = page.getByRole("switch", { name: "仅有待处理问题", exact: true });
  await expect(issueSwitch).toHaveAttribute("aria-checked", "false");
  await issueSwitch.click();
  await expect(issueSwitch).toHaveAttribute("aria-checked", "true");
  await page.getByPlaceholder("搜索标题或简介").fill("不存在的作品");
  await page.getByRole("button", { name: "应用条件", exact: true }).click();
  await expect(page.locator(".search-empty")).toContainText("没有匹配当前条件的作品");
  await page.getByRole("button", { name: "清除条件", exact: true }).click();
  await expect(issueSwitch).toHaveAttribute("aria-checked", "false");
  await expect(page.getByPlaceholder("搜索标题或简介")).toHaveValue("");
  const row = page.locator(".project-rows li").filter({ hasText: "第一部真实作品" });
  await expect(row).toHaveCount(1);
  await expect(page.locator(".project-rows li").filter({ hasText: "教学模式" })).toHaveCount(0);
  const desktopButtons = await row.locator(".actions button").evaluateAll((buttons) => buttons.map((button) => {
    const box = button.getBoundingClientRect();
    return { width: box.width, y: box.y, whiteSpace: getComputedStyle(button).whiteSpace };
  }));
  expect(desktopButtons).toHaveLength(2);
  expect(Math.abs(desktopButtons[0].y - desktopButtons[1].y)).toBeLessThanOrEqual(1);
  expect(desktopButtons.every((button) => button.whiteSpace === "nowrap")).toBe(true);
  expect(desktopButtons.reduce((sum, button) => sum + button.width, 0)).toBeGreaterThanOrEqual(150);

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const mobileButtons = await row.locator(".actions button").evaluateAll((buttons) => buttons.map((button) => {
    const box = button.getBoundingClientRect();
    return { width: box.width, height: box.height, y: box.y };
  }));
  expect(mobileButtons).toHaveLength(2);
  expect(Math.abs(mobileButtons[0].width - mobileButtons[1].width)).toBeLessThanOrEqual(2);
  expect(Math.abs(mobileButtons[0].y - mobileButtons[1].y)).toBeLessThanOrEqual(1);
  expect(mobileButtons.every((button) => button.height >= 44)).toBe(true);
  await page.screenshot({ path: path.join(outputDir, "390-project-card.png"), fullPage: true });
});

test("account menu avoids duplicate identity text and keeps keyboard focus behavior", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const { account } = await register(page, "v110account", true);
  const trigger = page.getByRole("button", { name: "用户菜单", exact: true });
  await expect(trigger.locator("svg.account-caret")).toHaveCount(1);
  await expect(trigger.locator(".account-helper")).toHaveText("个人账号");
  await trigger.click();
  const menu = page.getByRole("menu", { name: "用户菜单", exact: true });
  await expect(menu.getByText(account, { exact: true })).toHaveCount(0);
  await expect(menu.locator("small")).toHaveCount(0);
  await expect(menu.getByRole("menuitem")).toHaveText(["个人信息", "账号安全", "重新打开教学", "退出登录"]);
  await expect(menu.locator("svg.ui-icon")).toHaveCount(4);
  const [triggerBox, menuBox] = await Promise.all([trigger.boundingBox(), menu.boundingBox()]);
  if (!triggerBox || !menuBox) throw new Error("account menu is not measurable");
  expect(Math.abs(triggerBox.width - menuBox.width)).toBeLessThanOrEqual(1);
  await page.keyboard.press("Escape");
  await expect(menu).toHaveCount(0);
  await expect(trigger).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await trigger.click();
  await expect(page.getByRole("menu", { name: "用户菜单", exact: true })).toBeVisible();
  await page.waitForTimeout(180);
  const mobileMenuBox = await page.getByRole("menu", { name: "用户菜单", exact: true }).boundingBox();
  if (!mobileMenuBox) throw new Error("mobile account menu is not measurable");
  expect(Math.abs(mobileMenuBox.x + mobileMenuBox.width - (390 - 16))).toBeLessThanOrEqual(1);
  expect(mobileMenuBox.width).toBeLessThanOrEqual(358);
  await page.screenshot({ path: path.join(outputDir, "390-account-menu.png"), fullPage: true });
});
