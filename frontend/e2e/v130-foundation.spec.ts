import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin = process.env.E2E_BACKEND_ORIGIN;
if (!backendOrigin) throw new Error("E2E_BACKEND_ORIGIN is required");
const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix) throw new Error("E2E_ACCOUNT_PREFIX is required");

async function register(page: Page) {
  const account = `${accountPrefix}foundation${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("v1.3.0 作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
}

async function shot(page: Page, name: string) {
  if (!process.env.E2E_OUTPUT_DIR) return;
  await page.waitForTimeout(180);
  await page.screenshot({ path: path.join(process.env.E2E_OUTPUT_DIR, name), fullPage: true });
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

async function expectTutorialAligned(page: Page) {
  const geometry = await page.locator(".project-page").evaluate((projectPage) => {
    const pageBox = projectPage.getBoundingClientRect();
    const tutorialBox = projectPage.querySelector(".tutorial-mode-bar")?.getBoundingClientRect();
    if (!tutorialBox) throw new Error("tutorial bar is not measurable");
    return {
      left: Math.abs(tutorialBox.left - pageBox.left),
      right: Math.abs(tutorialBox.right - pageBox.right),
    };
  });
  expect(geometry.left).toBeLessThanOrEqual(1);
  expect(geometry.right).toBeLessThanOrEqual(1);
  await expectNoHorizontalOverflow(page);
}

test("v1.3.0 foundation interactions and layout remain scoped and responsive", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page);

  const iconGeometry = await page.locator(".home-empty-mark .ui-icon").evaluateAll((icons) =>
    icons.map((icon) => {
      const svg = icon as SVGGraphicsElement;
      const box = svg.getBoundingClientRect();
      const parent = svg.parentElement?.getBoundingClientRect();
      const drawing = svg.getBBox();
      if (!parent) throw new Error("empty-state icon parent is not measurable");
      return {
        containerCenterDelta: Math.abs((box.left + box.right) / 2 - (parent.left + parent.right) / 2),
        drawingCenterX: drawing.x + drawing.width / 2,
        drawingWidth: drawing.width,
      };
    }),
  );
  expect(iconGeometry).toHaveLength(2);
  expect(iconGeometry[0].containerCenterDelta).toBeLessThanOrEqual(0.5);
  expect(iconGeometry[0].drawingCenterX).toBe(iconGeometry[1].drawingCenterX);
  expect(iconGeometry[0].drawingWidth).toBe(iconGeometry[1].drawingWidth);
  await shot(page, "01-home-empty-icons-desktop.png");

  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "导入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/import$/);
  await page.getByRole("button", { name: "取消导入", exact: true }).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.locator(".project-rows li")).toHaveCount(0);

  await page.getByRole("button", { name: "导入作品", exact: true }).click();
  const projectsBefore = await page.request.get(`${backendOrigin}/api/projects`);
  const countBefore = ((await projectsBefore.json()) as { data: { projects: unknown[] } }).data.projects.length;
  await page.locator('input[type="file"]').setInputFiles({
    name: "cancel-preview.md",
    mimeType: "text/markdown",
    buffer: Buffer.from("# 第一章\n这是尚未确认的临时导入内容。", "utf8"),
  });
  const previewResponse = page.waitForResponse((response) => response.url().includes("/api/imports/preview") && response.status() === 201);
  await page.getByRole("button", { name: "解析并预览章节", exact: true }).click();
  const preview = (await (await previewResponse).json()) as { data: { import_id: string; detected: { chapters: { preview_id: string }[] } } };
  await expect(page.getByRole("heading", { name: "章节预览", exact: true })).toBeVisible();
  const cancelResponse = page.waitForResponse((response) => response.url().includes(`/api/imports/${preview.data.import_id}/cancel`));
  await page.getByRole("button", { name: "取消导入", exact: true }).click();
  expect((await cancelResponse).status()).toBe(200);
  await expect(page).toHaveURL(/\/projects$/);
  const projectsAfter = await page.request.get(`${backendOrigin}/api/projects`);
  expect(((await projectsAfter.json()) as { data: { projects: unknown[] } }).data.projects.length).toBe(countBefore);
  const cancelledCommit = await page.request.post(`${backendOrigin}/api/imports/${preview.data.import_id}/commit`, {
    headers: { "Idempotency-Key": randomUUID() },
    data: { confirm: true, title: "不应创建", chapter_preview_ids: preview.data.detected.chapters.map((chapter) => chapter.preview_id) },
  });
  expect(cancelledCommit.status()).toBe(404);

  await page.goto("/projects/new");
  const createGeometry = await page.locator(".create-project-page").evaluate((createPage) => {
    const pageBox = createPage.getBoundingClientRect();
    const mainBox = createPage.closest("main")?.getBoundingClientRect();
    const headerBox = createPage.querySelector(".page-header")?.getBoundingClientRect();
    const formBox = createPage.querySelector(".form-panel")?.getBoundingClientRect();
    if (!mainBox || !headerBox || !formBox) throw new Error("create layout is not measurable");
    return {
      centerDelta: Math.abs((pageBox.left + pageBox.right) / 2 - (mainBox.left + mainBox.right) / 2),
      headerLeftDelta: Math.abs(headerBox.left - formBox.left),
      widthDelta: Math.abs(headerBox.width - formBox.width),
    };
  });
  expect(createGeometry.centerDelta).toBeLessThanOrEqual(1);
  expect(createGeometry.headerLeftDelta).toBeLessThanOrEqual(1);
  expect(createGeometry.widthDelta).toBeLessThanOrEqual(1);
  await expectNoHorizontalOverflow(page);
  await shot(page, "02-create-project-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectNoHorizontalOverflow(page);
  await shot(page, "03-create-project-mobile.png");

  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/");
  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  const tabs = ["项目概览", "大纲", "角色库", "世界观", "Story Memory", "写作与检查"];
  for (const tab of tabs) {
    await page.getByRole("button", { name: tab, exact: true }).click();
    await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 1 / 5");
    await expectTutorialAligned(page);
  }
  await shot(page, "04-tutorial-workspace-desktop.png");
  await page.setViewportSize({ width: 390, height: 844 });
  await expectTutorialAligned(page);
  await shot(page, "05-tutorial-workspace-mobile.png");
});
