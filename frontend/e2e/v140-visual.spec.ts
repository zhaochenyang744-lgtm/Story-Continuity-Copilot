import { expect, test, type Page } from "@playwright/test";
import path from "node:path";

const screenshotRoot = process.env.E2E_VISUAL_SCREENSHOT_DIR;
const account = process.env.E2E_VISUAL_ACCOUNT ?? "v140visualpreview";
const password = process.env.E2E_VISUAL_PASSWORD ?? "Visual-preview-140!";

async function capture(page: Page, name: string, fullPage = false) {
  if (!screenshotRoot) return;
  await page.evaluate(async () => {
    const finiteAnimations = document
      .getAnimations()
      .filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity);
    await Promise.allSettled(finiteAnimations.map((animation) => animation.finished));
  });
  await page.screenshot({ path: path.join(screenshotRoot, `${name}.png`), fullPage });
}

async function expectNoHorizontalOverflow(page: Page) {
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

async function waitForShell(page: Page) {
  await expect(page.getByRole("navigation", { name: "全局导航" })).toBeVisible();
}

test("v1.4 visual candidate covers the complete product language", async ({ page }) => {
  await page.setViewportSize({ width: 1707, height: 960 });
  await page.goto("/register");
  await expect(page.getByRole("heading", { name: "创建账号", exact: true })).toBeVisible();
  await capture(page, "01-auth-register-1707");

  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("显示名称", { exact: true }).fill("视觉验收作者");
  await page.getByLabel("恢复邮箱", { exact: true }).fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await capture(page, "02-home-first-run-1707");

  await page.goto("/projects");
  await waitForShell(page);
  await expect(page.getByRole("heading", { name: "还没有真实作品", exact: true })).toBeVisible();
  await capture(page, "03-projects-empty-1707");

  await page.goto("/projects/import");
  await expect(page.getByRole("heading", { name: "导入已有作品", exact: true })).toBeVisible();
  await capture(page, "04-import-file-1707");

  await page.goto("/account/profile");
  await expect(page.getByRole("heading", { name: "视觉验收作者", exact: true })).toBeVisible();
  await capture(page, "05-author-profile-1707");

  await page.goto("/account/security");
  await expect(page.getByRole("heading", { name: "恢复邮箱", exact: true })).toBeVisible();
  await capture(page, "06-account-security-1707");

  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { name: "新建作品", exact: true })).toBeVisible();
  await capture(page, "07-new-work-1707");
  await page.getByLabel("作品名称").fill("潮汐之后");
  await page.getByRole("radio", { name: "其他", exact: true }).check();
  await page.getByLabel("其他作品类型", { exact: true }).fill("近未来悬疑");
  await page.getByLabel("简介").fill("一座沿海城市在退潮后显露出被遗忘的证据。");
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page.getByRole("heading", { name: "潮汐之后", exact: true })).toBeVisible();
  const projectId = new URL(page.url()).pathname.split("/")[2];
  expect(projectId).toBeTruthy();
  await capture(page, "08-project-overview-1707");

  const productPages: Array<[string, string, string]> = [
    ["outline", "大纲", "09-project-outline-1707"],
    ["characters", "角色库", "10-project-characters-1707"],
    ["world", "世界观", "11-project-world-1707"],
    ["memory", "Story Memory", "12-project-memory-1707"],
    ["workspace", "检查结果会显示在这里", "13-workspace-empty-1707"],
  ];
  for (const [route, heading, file] of productPages) {
    await page.goto(`/projects/${projectId}/${route}`);
    await expect(page.getByText(heading, { exact: true }).first()).toBeVisible();
    await capture(page, file);
  }

  await page.getByRole("button", { name: "进入沉浸写作", exact: true }).click();
  await expect(page.locator(".immersive-editor")).toBeVisible();
  await capture(page, "14-immersive-writing-1707");
  await page.keyboard.press("Escape");
  await expect(page.locator(".immersive-editor")).toHaveCount(0);

  await page.setViewportSize({ width: 1366, height: 768 });
  await page.goto(`/projects/${projectId}/workspace`);
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, "15-workspace-1366");

  await page.setViewportSize({ width: 1024, height: 900 });
  await page.goto(`/projects/${projectId}/workspace`);
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expect.poll(async () => (await page.locator(".project-nav").boundingBox())?.height ?? Infinity).toBeLessThan(220);
  await capture(page, "15b-workspace-1024");

  await page.setViewportSize({ width: 768, height: 900 });
  await page.goto("/projects/import");
  await expect(page.getByTestId("import-dropzone")).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, "16-import-tablet-768");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, "17-home-mobile-390");

  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { name: "作品信息", exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, "18-new-work-mobile-390");

  await page.goto(`/projects/${projectId}/workspace`);
  await expect(page.getByRole("navigation", { name: "手机浏览内容" })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await expect.poll(async () => (await page.locator(".workspace-grid .editor").boundingBox())?.height ?? Infinity).toBeLessThan(450);
  await capture(page, "19-workspace-mobile-draft-390");
  await page.getByRole("button", { name: /问题/ }).click();
  await expect(page.locator(".issues")).toBeVisible();
  await capture(page, "20-workspace-mobile-issues-390");

  await page.goto("/account/profile");
  await expect(page.getByRole("heading", { name: "视觉验收作者", exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await capture(page, "21-author-profile-mobile-390");
});
