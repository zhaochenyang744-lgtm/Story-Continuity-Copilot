import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin = process.env.E2E_BACKEND_ORIGIN;
if (!backendOrigin) throw new Error("E2E_BACKEND_ORIGIN is required");

async function register(page: Page) {
  const account = `v120${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("v1.2.0 作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  return { account, password };
}

async function screenshot(page: Page, name: string) {
  if (!process.env.E2E_OUTPUT_DIR) return;
  await page.waitForTimeout(450);
  await page.screenshot({ path: path.join(process.env.E2E_OUTPUT_DIR, name), fullPage: true });
}

async function screenshotViewport(page: Page, name: string) {
  if (!process.env.E2E_OUTPUT_DIR) return;
  await page.waitForTimeout(120);
  await page.screenshot({ path: path.join(process.env.E2E_OUTPUT_DIR, name), fullPage: false });
}

async function expectLoadedBitmap(
  page: Page,
  selector: string,
  expectedPath: string,
  expectedParentClass: string,
) {
  const image = page.locator(selector).first();
  await expect(image).toBeVisible();
  await expect(image).toHaveAttribute("src", new RegExp(expectedPath.split("/").at(-1) ?? expectedPath));
  expect(await image.evaluate((node) => node.tagName)).toBe("IMG");
  await expect
    .poll(() => image.evaluate((node) => (node as HTMLImageElement).naturalWidth))
    .toBeGreaterThan(0);
  const material = await image.evaluate((node) => {
    const element = node as HTMLImageElement;
    const style = getComputedStyle(element);
    const canvas = document.createElement("canvas");
    canvas.width = element.naturalWidth;
    canvas.height = element.naturalHeight;
    const context = canvas.getContext("2d", { willReadFrequently: true });
    if (!context) throw new Error("2D canvas unavailable");
    context.drawImage(element, 0, 0);
    const corners = [
      [0, 0],
      [canvas.width - 1, 0],
      [0, canvas.height - 1],
      [canvas.width - 1, canvas.height - 1],
    ].map(([x, y]) => context.getImageData(x, y, 1, 1).data[3]);

    return {
      backgroundColor: style.backgroundColor,
      borderRadius: style.borderRadius,
      borderWidths: [style.borderTopWidth, style.borderRightWidth, style.borderBottomWidth, style.borderLeftWidth],
      boxShadow: style.boxShadow,
      corners,
      parentClasses: Array.from(element.parentElement?.classList ?? []),
    };
  });
  expect(material.backgroundColor).toBe("rgba(0, 0, 0, 0)");
  expect(material.borderRadius).toBe("0px");
  expect(material.borderWidths).toEqual(["0px", "0px", "0px", "0px"]);
  expect(material.boxShadow).toBe("none");
  expect(material.corners).toEqual([0, 0, 0, 0]);
  expect(material.parentClasses).toContain(expectedParentClass);
}

test("v1.2.0 author workspace covers the eleven non-login visual targets", async ({ page }) => {
  const initialStatsResponse = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  const initialStats = (await initialStatsResponse.json()) as { provider_calls: number };
  await page.setViewportSize({ width: 1440, height: 900 });
  const credentials = await register(page);
  await expect(page.getByLabel("首次教学")).toBeVisible();
  await expectLoadedBitmap(page, ".empty-manuscript-visual", "/assets/v120/empty-manuscript-alpha.webp", "home-entry-composition");
  await expect(page.locator("svg.empty-manuscript-visual, svg.empty-library-visual, svg.tutorial-complete-visual")).toHaveCount(0);
  expect(
    await page
      .locator(".home-entry-composition")
      .evaluate((node) => getComputedStyle(node).gridTemplateColumns.split(" ").length),
  ).toBe(3);
  await expect(page.locator(".home-empty-state")).toHaveCount(2);
  await expect(page.getByRole("button", { name: "查看全部", exact: true })).toHaveCount(0);
  const homeSectionHeaders = page.locator(".home-section-grid .home-section-head");
  await expect(homeSectionHeaders).toHaveCount(2);
  const homeHeaderStyles = await homeSectionHeaders.evaluateAll((nodes) =>
    nodes.map((node) => {
      const style = getComputedStyle(node);
      const heading = node.querySelector("h2");
      const markerStyle = heading ? getComputedStyle(heading, "::before") : null;
      return {
        height: node.getBoundingClientRect().height,
        paddingLeft: style.paddingLeft,
        paddingRight: style.paddingRight,
        markerLeft: markerStyle?.left,
      };
    }),
  );
  expect(homeHeaderStyles[0]).toEqual(homeHeaderStyles[1]);
  const desktopSecondaryRegions = await page.locator(".home-section-grid").evaluate((grid) => {
    const gridStyle = getComputedStyle(grid);
    return {
      gridBorderTop: gridStyle.borderTopWidth,
      sections: Array.from(grid.querySelectorAll(":scope > .home-section")).map((section) => {
        const style = getComputedStyle(section);
        return {
          background: style.backgroundColor,
          borderTop: style.borderTopWidth,
          borderRight: style.borderRightWidth,
          borderBottom: style.borderBottomWidth,
          borderLeft: style.borderLeftWidth,
          borderRadius: style.borderRadius,
          boxShadow: style.boxShadow,
        };
      }),
    };
  });
  expect(desktopSecondaryRegions.gridBorderTop).toBe("1px");
  expect(desktopSecondaryRegions.sections).toEqual([
    { background: "rgba(0, 0, 0, 0)", borderTop: "0px", borderRight: "0px", borderBottom: "0px", borderLeft: "0px", borderRadius: "0px", boxShadow: "none" },
    { background: "rgba(0, 0, 0, 0)", borderTop: "0px", borderRight: "0px", borderBottom: "0px", borderLeft: "1px", borderRadius: "0px", boxShadow: "none" },
  ]);
  await screenshot(page, "01-home-first-run.png");

  await page.setViewportSize({ width: 1366, height: 720 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "01c-home-first-run-1366x720.png");

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.locator(".home-entry-composition")).toBeVisible();
  const mobileSecondRegion = await page.locator(".home-section-grid .home-section").nth(1).evaluate((section) => {
    const style = getComputedStyle(section);
    return { borderTop: style.borderTopWidth, borderLeft: style.borderLeftWidth, borderRadius: style.borderRadius };
  });
  expect(mobileSecondRegion).toEqual({ borderTop: "1px", borderLeft: "0px", borderRadius: "0px" });
  await screenshot(page, "01b-home-first-run-mobile.png");
  await page.setViewportSize({ width: 1440, height: 900 });

  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 1 / 5");
  await expect(page.getByLabel("五步教学进度").locator("li")).toHaveCount(5);
  expect(
    await page.locator(".project-nav .nav").evaluateAll((nodes) =>
      nodes.every((node) => {
        const style = getComputedStyle(node);
        return style.justifyContent === "flex-start" && style.textAlign === "left";
      }),
    ),
  ).toBe(true);
  await screenshot(page, "02-tutorial-overview.png");

  const idleRoute = page.url();
  const idleScrollY = await page.evaluate(() => window.scrollY);
  const focusBeforeIdle = await page.evaluateHandle(() => document.activeElement);
  await page.waitForTimeout(12_300);
  const idleHint = page.locator(".tutorial-guidance-hint");
  const idleTarget = page.locator('[data-tutorial-guidance-target="true"]');
  await expect(idleHint).toHaveText("下一步：打开 Story Memory");
  await expect(idleTarget).toHaveCount(1);
  await expect(idleTarget).toHaveAttribute("data-tutorial-guidance-key", "memory-navigation");
  await expect(idleTarget).toHaveAttribute("aria-describedby", /tutorial-guidance-hint/);
  expect(page.url()).toBe(idleRoute);
  expect(await page.evaluate(() => window.scrollY)).toBe(idleScrollY);
  expect(await page.evaluate((before) => document.activeElement === before, focusBeforeIdle)).toBe(true);
  await screenshotViewport(page, "16-tutorial-guidance-desktop.png");

  await page.getByRole("button", { name: "大纲", exact: true }).click();
  await expect(idleHint).toHaveCount(0);
  await expect(idleTarget).toHaveCount(0);
  await expect(page.locator(".outline-timeline li")).toHaveCount(10);
  await expect(page.locator(".outline-timeline")).toContainText("已完成");
  await expect(page.locator(".outline-timeline").getByText("complete", { exact: true })).toHaveCount(0);
  const outlineGeometry = await page.locator(".outline-timeline li").first().evaluate((node) => {
    const number = node.querySelector(".chapter-number");
    const title = node.querySelector("h2");
    if (!number || !title) throw new Error("outline typography is not measurable");
    return {
      rowHeight: node.getBoundingClientRect().height,
      numberSize: Number.parseFloat(getComputedStyle(number).fontSize),
      titleSize: Number.parseFloat(getComputedStyle(title).fontSize),
    };
  });
  expect(outlineGeometry.rowHeight).toBeGreaterThanOrEqual(78);
  expect(outlineGeometry.rowHeight).toBeLessThanOrEqual(88);
  expect(outlineGeometry.numberSize).toBeGreaterThanOrEqual(20);
  expect(outlineGeometry.numberSize).toBeLessThanOrEqual(24);
  expect(outlineGeometry.titleSize).toBeGreaterThanOrEqual(16);
  const completedOutline = page.locator('.outline-timeline li[data-status="completed"]').first();
  await expect(completedOutline).toBeVisible();
  await expect(completedOutline.locator(".status-pill")).toHaveClass(/completed/);
  await screenshot(page, "03-outline-timeline.png");

  await page.getByRole("button", { name: "角色库", exact: true }).click();
  await expect(page.locator(".character-detail")).toBeVisible();
  await screenshot(page, "04-character-archive.png");

  await page.getByRole("button", { name: "世界观", exact: true }).click();
  await expect(page.locator(".world-detail")).toBeVisible();
  await expect(page.getByText("暂未建立关联", { exact: true })).toBeVisible();
  await expect(page.getByText("当前接口尚未提供关联字段", { exact: true })).toHaveCount(0);
  await screenshot(page, "05-world-archive.png");

  await page.setViewportSize({ width: 390, height: 844 });
  const readonlyCopy = "当前窗口较窄，暂为只读浏览；放大窗口即可继续写作与检查。";
  const readonlyNotice = page.locator(".readonly").filter({ hasText: readonlyCopy });
  await expect(readonlyNotice).toBeVisible();
  expect(await readonlyNotice.evaluate((node) => node.textContent?.replace("◉", "").trim())).toBe(readonlyCopy);
  const readonlyStyle = await readonlyNotice.evaluate((node) => {
    const style = getComputedStyle(node);
    return { fontSize: Number.parseFloat(style.fontSize), lineHeight: Number.parseFloat(style.lineHeight) };
  });
  expect(readonlyStyle.fontSize).toBeGreaterThanOrEqual(13);
  expect(readonlyStyle.lineHeight).toBeGreaterThanOrEqual(readonlyStyle.fontSize * 1.5);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const titleBox = await page.getByRole("heading", { name: "世界观", exact: true }).boundingBox();
  if (!titleBox) throw new Error("world title is not measurable");
  expect(titleBox.y).toBeLessThanOrEqual(150);
  await screenshot(page, "06-mobile-world-tutorial.png");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "去 Story Memory", exact: true }).click();
  await expect(page.locator(".memory-row:not(.memory-head)")).toHaveCount(8);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText(
    "下一步：查看这条事实的章节来源",
  );
  await expect(
    page.locator('[data-tutorial-guidance-key="memory-source"]'),
  ).toHaveCount(1);

  await page.getByRole("button", { name: "大纲", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/outline$/);
  await expect(page.locator(".outline-timeline li")).toHaveCount(10);
  const outlineRouteAfterManualNavigation = page.url();
  const outlineScrollAfterManualNavigation = await page.evaluate(
    () => window.scrollY,
  );
  const outlineFocusAfterManualNavigation = await page.evaluateHandle(
    () => document.activeElement,
  );
  await page.waitForTimeout(900);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveCount(0);
  await expect(
    page.locator('[data-tutorial-guidance-target="true"]'),
  ).toHaveCount(0);
  expect(page.url()).toBe(outlineRouteAfterManualNavigation);
  expect(await page.evaluate(() => window.scrollY)).toBe(
    outlineScrollAfterManualNavigation,
  );
  expect(
    await page.evaluate(
      (before) => document.activeElement === before,
      outlineFocusAfterManualNavigation,
    ),
  ).toBe(true);

  await page.waitForTimeout(12_300);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText(
    "下一步：打开 Story Memory",
  );
  await expect(
    page.locator('[data-tutorial-guidance-key="memory-navigation"]'),
  ).toHaveCount(1);
  expect(page.url()).toBe(outlineRouteAfterManualNavigation);
  expect(await page.evaluate(() => window.scrollY)).toBe(
    outlineScrollAfterManualNavigation,
  );
  expect(
    await page.evaluate(
      (before) => document.activeElement === before,
      outlineFocusAfterManualNavigation,
    ),
  ).toBe(true);

  await page.getByRole("button", { name: "Story Memory", exact: true }).click();
  await expect(page.locator(".memory-row:not(.memory-head)")).toHaveCount(8);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveCount(0);
  await expect(page.getByText("尚未知晓", { exact: true })).toBeVisible();
  await expect(page.getByText("时间", { exact: true })).toBeVisible();
  await expect(page.getByText("接收记录", { exact: true })).toBeVisible();
  await expect(page.getByText(/^(complete|time|received)$/)).toHaveCount(0);
  const locateMemorySource = page.getByRole("button", { name: "定位事实来源", exact: true });
  await locateMemorySource.click();
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText("下一步：查看这条事实的章节来源");
  await expect(page.locator('[data-tutorial-guidance-key="memory-source"]')).toHaveCount(1);
  await expect(locateMemorySource).toBeFocused();
  await screenshot(page, "07-story-memory.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".memory-head")).toBeHidden();
  const memoryNav = page.getByRole("navigation", { name: "事实分类" });
  expect(await memoryNav.evaluate((node) => getComputedStyle(node).scrollbarWidth)).toBe("none");
  expect(await memoryNav.getByRole("button", { name: "全部事实", exact: true }).evaluate((node) => Number.parseFloat(getComputedStyle(node).minHeight))).toBeGreaterThanOrEqual(44);
  await memoryNav.getByRole("button", { name: "待确认", exact: true }).click();
  const activeFilterGeometry = await memoryNav.getByRole("button", { name: "待确认", exact: true }).evaluate((node) => {
    const button = node.getBoundingClientRect();
    const nav = node.parentElement?.getBoundingClientRect();
    return { buttonLeft: button.left, buttonRight: button.right, navLeft: nav?.left ?? 0, navRight: nav?.right ?? 0 };
  });
  expect(activeFilterGeometry.buttonLeft).toBeGreaterThanOrEqual(activeFilterGeometry.navLeft);
  expect(activeFilterGeometry.buttonRight).toBeLessThanOrEqual(activeFilterGeometry.navRight);
  await memoryNav.getByRole("button", { name: "全部事实", exact: true }).click();
  expect(await page.locator(".memory-row:not(.memory-head) .memory-field").first().evaluate((node) => getComputedStyle(node, "::before").content)).toBe('"属性"');
  expect(await page.locator(".memory-source:not(:disabled)").first().evaluate((node) => node.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "07b-mobile-story-memory.png");

  await page.emulateMedia({ reducedMotion: "reduce" });
  await locateMemorySource.click();
  await expect(page.locator(".tutorial-guidance-hint")).toBeVisible();
  const reducedGuidanceDuration = await page.locator('[data-tutorial-guidance-key="memory-source"]').evaluate((node) => {
    const duration = getComputedStyle(node).animationDuration.split(",")[0]?.trim() ?? "0s";
    return duration.endsWith("ms") ? Number.parseFloat(duration) / 1000 : Number.parseFloat(duration);
  });
  expect(reducedGuidanceDuration).toBeLessThanOrEqual(0.001);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshotViewport(page, "16b-tutorial-guidance-mobile.png");
  await page.emulateMedia({ reducedMotion: "no-preference" });

  const sourceTrigger = page.locator(".memory-source:not(:disabled)").first();
  await sourceTrigger.click();
  await expect(page.locator(".tutorial-guidance-hint")).toHaveCount(0);
  const sourceDrawer = page.getByRole("dialog", { name: /章节来源/ });
  await expect(sourceDrawer).toBeVisible();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/memory$/);
  await expect(sourceDrawer.getByRole("heading", { name: "被引用的原文片段", exact: true })).toBeVisible();
  await expect(sourceDrawer.getByRole("heading", { name: "可用上下文", exact: true })).toBeVisible();
  await expect(sourceDrawer.getByRole("heading", { name: "事实状态", exact: true })).toBeVisible();
  await expect(sourceDrawer.getByRole("heading", { name: "追加章节", exact: true })).toHaveCount(0);
  expect(await sourceDrawer.locator(".source-technical").evaluate((node) => (node as HTMLDetailsElement).open)).toBe(false);
  const sourceClose = sourceDrawer.getByRole("button", { name: "关闭章节来源", exact: true });
  await expect(sourceClose).toBeFocused();
  await page.waitForTimeout(12_300);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText("看完来源后，关闭并继续");
  await expect(page.locator('[data-tutorial-guidance-key="source-close"]')).toHaveCount(1);
  await expect(page.locator('[data-tutorial-guidance-target="true"]')).toHaveCount(1);
  await expect(sourceClose).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await sourceDrawer.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(sourceClose).toBeFocused();
  await screenshot(page, "07c-readonly-source-drawer-mobile.png");
  await page.keyboard.press("Escape");
  await expect(sourceDrawer).toHaveCount(0);
  await expect(sourceTrigger).toBeFocused();
  await expect(page.locator(".tutorial-guidance-hint")).toHaveCount(0);
  await expect(page.locator('[data-tutorial-guidance-target="true"]')).toHaveCount(0);
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 2 / 5");
  await page.setViewportSize({ width: 1440, height: 900 });

  // Business progress is canonical server state: a hard refresh and a new
  // authenticated session must both restore step 2 without persisting any
  // transient drawer, focus, pulse, or idle-timer state.
  await page.reload();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 2 / 5");
  await expect(page.getByRole("dialog", { name: /章节来源/ })).toHaveCount(0);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveCount(0);
  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  await page.getByLabel("账号").fill(credentials.account);
  await page.locator('input[name="password"]').fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByLabel("首次教学")).toBeVisible();
  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 2 / 5");
  await page.getByRole("button", { name: "Story Memory", exact: true }).click();
  await expect(page.locator(".memory-row:not(.memory-head)")).toHaveCount(8);

  await page.getByRole("button", { name: "去写作与检查", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 3 / 5");
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText("下一步：打开这条高风险问题");
  await expect(page.locator('[data-tutorial-guidance-key="high-risk-issue"]')).toHaveCount(1);
  await expect(page.locator(".evidence-layer")).toHaveCount(0);
  const titleInput = page.locator(".editor-title-input input");
  const draftInput = page.locator(".draft-field textarea");
  const writingTypography = await page.locator(".workspace-grid").evaluate((node) => {
    const title = node.querySelector(".editor-title-input input");
    const draft = node.querySelector(".draft-field textarea");
    if (!title || !draft) throw new Error("writing typography is not measurable");
    const titleStyle = getComputedStyle(title);
    const draftStyle = getComputedStyle(draft);
    return {
      titleSize: Number.parseFloat(titleStyle.fontSize),
      titleFamily: titleStyle.fontFamily,
      draftSize: Number.parseFloat(draftStyle.fontSize),
      draftLineHeight: Number.parseFloat(draftStyle.lineHeight),
      draftWidth: draft.getBoundingClientRect().width,
      draftPaddingLeft: Number.parseFloat(draftStyle.paddingLeft),
      draftPaddingRight: Number.parseFloat(draftStyle.paddingRight),
      focusToken: getComputedStyle(document.documentElement).getPropertyValue("--focus").trim(),
      violetFocusToken: getComputedStyle(document.documentElement).getPropertyValue("--violet-300").trim(),
    };
  });
  expect(writingTypography.titleSize).toBeGreaterThanOrEqual(20);
  expect(writingTypography.titleSize).toBeLessThanOrEqual(24);
  expect(writingTypography.titleFamily).toMatch(/serif/i);
  expect(writingTypography.draftLineHeight / writingTypography.draftSize).toBeGreaterThanOrEqual(1.85);
  expect(writingTypography.draftLineHeight / writingTypography.draftSize).toBeLessThanOrEqual(1.95);
  expect(writingTypography.draftWidth).toBeLessThanOrEqual(680);
  expect(writingTypography.draftPaddingLeft).toBeGreaterThanOrEqual(22);
  expect(writingTypography.draftPaddingRight).toBeGreaterThanOrEqual(22);
  expect(writingTypography.focusToken).toBe(writingTypography.violetFocusToken);
  await titleInput.focus();
  expect(await titleInput.evaluate((node) => getComputedStyle(node).borderTopColor)).not.toBe("rgba(0, 0, 0, 0)");
  await draftInput.focus();
  expect(await draftInput.evaluate((node) => getComputedStyle(node).outlineStyle)).toBe("solid");
  await expect(page.locator(".run-technical")).not.toHaveAttribute("open", "");
  await expect(page.locator(".workspace-technical")).not.toHaveAttribute("open", "");
  await expect(page.locator(".run-technical").getByText("模型服务用量", { exact: true })).toBeHidden();
  await page.locator(".run-technical > summary").click();
  await expect(page.locator(".run-technical").getByText("模型服务用量", { exact: true })).toBeVisible();
  await expect(page.locator(".run-technical").getByText("证据谱系", { exact: true })).toBeVisible();
  await page.locator(".run-technical > summary").click();
  const issueTrigger = page.locator(".issue-list button").first();
  await page.setViewportSize({ width: 1100, height: 820 });
  const issuesWidth = await page.locator(".issues").evaluate((node) => node.getBoundingClientRect().width);
  expect(issuesWidth).toBeGreaterThanOrEqual(310);
  expect(issuesWidth).toBeLessThanOrEqual(330);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "08a-workspace-1100.png");
  await page.setViewportSize({ width: 1440, height: 900 });
  await issueTrigger.click();
  const drawer = page.getByRole("dialog", { name: "问题证据" });
  await expect(drawer).toBeVisible();
  const drawerClose = drawer.getByRole("button", { name: "关闭", exact: true });
  await expect(drawerClose).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  expect(await drawer.evaluate((node) => node.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Tab");
  await expect(drawerClose).toBeFocused();
  await page.evaluate(() => (document.querySelector(".evidence-layer .close") as HTMLButtonElement | null)?.click());
  await expect(page.locator(".evidence-layer")).toHaveClass(/is-closing/);
  await expect(drawer).toHaveCount(0);
  await expect(issueTrigger).toBeFocused();

  await issueTrigger.click();
  await expect(drawer).toBeVisible();
  await expect(drawerClose).toBeFocused();
  await expect(drawer.getByRole("heading", { name: "当前草稿" })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "历史证据" })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "冲突说明" })).toBeVisible();
  await expect(drawer.getByRole("heading", { name: "作者决定" })).toBeVisible();
  await expect(drawer.getByText("Accept & edit", { exact: true })).toHaveCount(0);
  expect(
    await drawer
      .locator(".evidence-technical")
      .evaluate((node) => (node as HTMLDetailsElement).open),
  ).toBe(false);
  const claimSurfaces = await drawer.evaluate((node) => {
    const current = node.querySelector(".current-claim blockquote");
    const history = node.querySelector(".evidence-history blockquote");
    if (!current || !history) throw new Error("Evidence surfaces are not measurable");
    const currentStyle = getComputedStyle(current);
    const historyStyle = getComputedStyle(history);
    return {
      currentBackground: currentStyle.backgroundColor,
      currentBorder: currentStyle.borderLeftColor,
      historyBackground: historyStyle.backgroundColor,
      historyBorder: historyStyle.borderLeftColor,
    };
  });
  expect(claimSurfaces.currentBackground).not.toBe(claimSurfaces.historyBackground);
  expect(claimSurfaces.currentBorder).not.toBe(claimSurfaces.historyBorder);
  await expect(issueTrigger).toHaveClass(/selected/);
  await page.waitForTimeout(12_300);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText("请选择一种处理方式，教学不会替你决定");
  await expect(page.locator('[data-tutorial-guidance-key="author-decision"]')).toHaveCount(1);
  await expect(page.locator(".author-decision [data-tutorial-guidance-target]")).toHaveCount(0);
  await expect(page.locator('[data-tutorial-guidance-target="true"]')).toHaveCount(1);
  await expect(drawerClose).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(drawer.getByText("移动端可以浏览完整证据。请在桌面端继续完成作者决定。", { exact: true })).toBeVisible();
  await expect(drawer.locator(".author-decision")).toHaveCount(0);
  await page.waitForTimeout(12_300);
  await expect(page.locator(".tutorial-guidance-hint")).toHaveText("请在桌面端继续完成作者决定");
  await expect(page.locator('[data-tutorial-guidance-key="mobile-decision-note"]')).toHaveCount(1);
  await expect(page.locator('[data-tutorial-guidance-target="true"]')).toHaveCount(1);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  const mobileGuidanceWidth = await page.locator(".tutorial-guidance-hint").evaluate((node) => node.getBoundingClientRect().width);
  expect(mobileGuidanceWidth).toBeLessThanOrEqual(358);
  await screenshotViewport(page, "16b-tutorial-guidance-mobile.png");
  await page.setViewportSize({ width: 1440, height: 900 });
  await expect(drawer.getByRole("heading", { name: "作者决定", exact: true })).toBeVisible();
  await expect(page.locator(".tutorial-guidance-hint")).toHaveCount(0);
  const evidenceSourceTrigger = drawer.getByRole("button", { name: /查看来源/ }).first();
  const evidenceUrl = page.url();
  await evidenceSourceTrigger.click();
  const evidenceSourceDrawer = page.getByRole("dialog", { name: /章节来源/ });
  await expect(evidenceSourceDrawer).toBeVisible();
  expect(page.url()).toBe(evidenceUrl);
  await expect(page.locator(".evidence-layer")).toHaveCount(1);
  await expect(evidenceSourceDrawer.locator(".source-excerpt mark")).not.toHaveText("引用内容未提供");
  await expect(evidenceSourceDrawer.locator(".source-technical")).toContainText(/SourceSpan|来源片段/);
  await expect.poll(async () => {
    const sourceDrawerBox = await evidenceSourceDrawer.boundingBox();
    if (!sourceDrawerBox) return Number.POSITIVE_INFINITY;
    return Math.abs(sourceDrawerBox.x + sourceDrawerBox.width - 1440);
  }).toBeLessThanOrEqual(1);
  const evidenceSourceClose = evidenceSourceDrawer.getByRole("button", { name: "关闭章节来源", exact: true });
  await expect(evidenceSourceClose).toBeFocused();
  await screenshot(page, "08-source-chain-drawer.png");
  await page.keyboard.press("Escape");
  await expect(evidenceSourceDrawer).toHaveCount(0);
  await expect(evidenceSourceTrigger).toBeFocused();
  await expect(drawer).toBeVisible();
  await screenshot(page, "08-evidence-decision-drawer.png");

  await drawer.getByRole("button", { name: "保留当前写法", exact: true }).click();
  await expect(drawer.getByRole("status")).toContainText("决定已记录");
  await expect(issueTrigger).toHaveClass(/resolved/);
  await expect(issueTrigger).toHaveClass(/selected/);
  await drawerClose.click();
  await expect(drawer).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await issueTrigger.click();
  await expect(drawer).toBeVisible();
  const reducedAnimationSeconds = await page.locator(".evidence-layer .drawer").evaluate((node) => {
    const duration = getComputedStyle(node).animationDuration.split(",")[0]?.trim() ?? "0s";
    return duration.endsWith("ms") ? Number.parseFloat(duration) / 1000 : Number.parseFloat(duration);
  });
  expect(reducedAnimationSeconds).toBeLessThanOrEqual(0.001);
  await drawerClose.click();
  await expect(drawer).toHaveCount(0);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 5 / 5");
  await expect(page.locator(".tutorial-completion-bar")).toBeVisible();
  await expect(page.getByText("作者决定已记录", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "稍后完成", exact: true })).toBeVisible();
  const desktopCompletionHeight = await page.locator(".tutorial-completion-bar").evaluate((node) => node.getBoundingClientRect().height);
  expect(desktopCompletionHeight).toBeLessThanOrEqual(190);
  await screenshot(page, "08b-compact-tutorial-completion.png");
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await expect(page.locator(".tutorial-completion-bar")).toBeVisible();
  await screenshot(page, "08c-compact-tutorial-completion-mobile.png");
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "完成教学", exact: true }).click();
  await expect(page).toHaveURL(/\/onboarding\/complete$/);
  await expect(page.getByRole("heading", { name: "教学已完成", exact: true })).toBeVisible();
  await page.reload();
  await expect(page).toHaveURL(/\/onboarding\/complete$/);
  await expect(page.getByRole("heading", { name: "教学已完成", exact: true })).toBeVisible();
  await expectLoadedBitmap(page, ".tutorial-complete-visual", "/assets/v120/tutorial-complete-alpha.webp", "tutorial-complete-panel");
  await screenshot(page, "09-tutorial-complete.png");

  await page.getByRole("button", { name: "返回首页", exact: true }).click();
  await expect(page.getByText("从第一章开始建立连续性档案", { exact: true })).toBeVisible();
  await screenshot(page, "10-home-empty.png");

  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await expect(page.getByRole("heading", { name: "还没有真实作品", exact: true })).toBeVisible();
  await expectLoadedBitmap(page, ".empty-library-visual", "/assets/v120/empty-library-alpha.webp", "project-empty-state");
  await expect(page.locator(".project-toolbar")).toHaveCount(0);
  await expect(page.locator(".page-header > .actions")).toHaveCount(0);
  await expect(page.locator(".project-empty-state .actions")).toHaveCount(1);
  await expect(page.getByRole("button", { name: "导入作品", exact: true })).toHaveCount(1);
  await expect(page.getByRole("button", { name: "新建作品", exact: true })).toHaveCount(1);
  await screenshot(page, "11-projects-empty.png");

  const accountTrigger = page.getByRole("button", { name: "用户菜单", exact: true });
  await accountTrigger.click();
  const accountMenu = page.getByRole("menu", { name: "用户菜单", exact: true });
  await expect(accountMenu).toBeVisible();
  await expect(accountMenu.getByText("v1.2.0 作者", { exact: true })).toHaveCount(0);
  await expect(accountMenu.getByRole("menuitem", { name: "退出登录", exact: true })).toHaveClass(/danger/);
  await screenshot(page, "12-account-menu.png");
  await page.keyboard.press("Escape");
  await expect(accountMenu).toHaveCount(0);
  await expect(accountTrigger).toBeFocused();

  await page.setViewportSize({ width: 390, height: 844 });
  await accountTrigger.click();
  await expect(accountMenu).toBeVisible();
  const mobileMenuBox = await accountMenu.boundingBox();
  if (!mobileMenuBox) throw new Error("mobile account menu is not measurable");
  expect(390 - mobileMenuBox.x - mobileMenuBox.width).toBeGreaterThanOrEqual(15);
  expect(mobileMenuBox.width).toBeLessThanOrEqual(358);
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "12b-account-menu-mobile.png");
  await page.keyboard.press("Escape");
  await expect(accountTrigger).toBeFocused();

  await page.setViewportSize({ width: 1433, height: 898 });
  await page.getByRole("button", { name: "导入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/import$/);
  const importGeometry = await page.locator(".import-page").evaluate((node) => {
    const pageBox = node.getBoundingClientRect();
    const mainBox = node.closest("main")?.getBoundingClientRect();
    const stepsBox = node.querySelector(".import-steps")?.getBoundingClientRect();
    const panelBox = node.querySelector(".import-panel")?.getBoundingClientRect();
    if (!mainBox || !stepsBox || !panelBox) throw new Error("import layout is not measurable");
    return {
      centerDelta: Math.abs((pageBox.left + pageBox.right) / 2 - (mainBox.left + mainBox.right) / 2),
      panelStepWidthDelta: Math.abs(panelBox.width - stepsBox.width),
    };
  });
  expect(importGeometry.centerDelta).toBeLessThanOrEqual(1);
  expect(importGeometry.panelStepWidthDelta).toBeLessThanOrEqual(1);
  await screenshot(page, "13-import-balanced.png");

  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "13b-import-balanced-mobile.png");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/projects/new");
  await page.getByLabel("作品名称", { exact: true }).fill("真实模型尺寸验收作品");
  await page.getByLabel("类型", { exact: true }).fill("长篇小说");
  await page.getByLabel("简介", { exact: true }).fill("用于验证真实项目行、空检查状态与写作界面的响应式尺寸。");
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/workspace$/);
  await expect(page.locator(".issues-empty")).toContainText("检查结果会显示在这里");
  await expect(page.getByRole("button", { name: "运行连续性检查", exact: true })).toHaveCount(1);
  await expect(page.locator(".workspace-page-header").getByRole("button", { name: "运行连续性检查", exact: true })).toHaveCount(0);
  await screenshot(page, "14-no-run-single-action.png");

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.locator(".readonly").filter({ hasText: readonlyCopy })).toBeVisible();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await screenshot(page, "14b-no-run-readonly-mobile.png");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await expect(page.locator(".project-rows li")).toHaveCount(1);
  for (const viewport of [
    { width: 1440, height: 900, screenshotName: "15-project-columns-1440.png" },
    { width: 1100, height: 820, screenshotName: "15b-project-columns-1100.png" },
  ]) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const columnOffsets = await page.locator(".project-table").evaluate((node) => {
      const headerCells = Array.from(node.querySelectorAll(":scope > .project-rows-head > span"));
      const rowCells = Array.from(node.querySelectorAll(":scope > .project-rows > li:first-child > *"));
      if (headerCells.length !== 7 || rowCells.length !== 7) throw new Error("project columns are incomplete");
      return headerCells.map((cell, index) => Math.abs(cell.getBoundingClientRect().left - rowCells[index].getBoundingClientRect().left));
    });
    expect(Math.max(...columnOffsets)).toBeLessThanOrEqual(2);
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await screenshot(page, viewport.screenshotName);
  }

  const stats = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  expect(await stats.json()).toMatchObject({
    provider_calls: initialStats.provider_calls,
    provider_http_calls: 0,
  });
});
