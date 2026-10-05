import { expect, test } from "@playwright/test";
import { registerAccount, tutorialProjectId } from "./support/app";
import { startVisitor } from "./support/batch2";

// v1.6.0: tick written chapters on the chapter-management page and check them, each against earlier
// chapters only; the estimate is shown before anything is spent and results are grouped by chapter.
test("an author ticks written chapters, sees the estimate, and gets results per chapter", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await registerAccount(page, { prefix: "v160cc" });
  const projectId = await tutorialProjectId(page);
  await page.goto(`/projects/${projectId}/sources`);
  const panel = page.getByRole("region", { name: "检查已写章节", exact: true });
  await expect(panel).toBeVisible();
  const start = panel.getByRole("button", { name: "检查选中的章节", exact: true });
  await expect(start).toBeDisabled();
  await panel.getByRole("checkbox", { name: /第 2 章/ }).check();
  await panel.getByRole("checkbox", { name: /第 9 章/ }).check();
  await expect(panel.getByRole("status")).toContainText("已选 2/8 章");
  await expect(panel.getByRole("status")).toContainText("字 · 预计");
  await expect(panel.getByRole("status")).toContainText("今天还可检查");
  await start.click();
  await expect(panel.locator(".chapter-check-chapter")).toHaveCount(2, { timeout: 20_000 });
  await expect(panel.locator(".chapter-check-chapter").first()).toContainText("第 2 章");
  await expect(panel.locator(".chapter-check-chapter").last()).toContainText("第 9 章");
});

test("at most eight chapters can be ticked", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await registerAccount(page, { prefix: "v160cc8" });
  const projectId = await tutorialProjectId(page);
  await page.goto(`/projects/${projectId}/sources`);
  const panel = page.getByRole("region", { name: "检查已写章节", exact: true });
  const boxes = panel.getByRole("checkbox");
  await expect(boxes).toHaveCount(10);
  for (let index = 0; index < 8; index++) await boxes.nth(index).check();
  await expect(boxes.nth(8)).toBeDisabled();
  await expect(panel.getByRole("status")).toContainText("已选 8/8 章");
});

test("visitors are told multi-chapter checks need an account", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 960 });
  await startVisitor(page);
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.locator(".project-rows li").filter({ hasText: "灰港回声" }).getByRole("button", { name: "打开", exact: true }).click();
  await page.getByRole("button", { name: "章节管理", exact: true }).click();
  const panel = page.locator(".chapter-check-panel");
  await expect(panel).toContainText("注册账号后可以一次勾选最多 8 章");
  await expect(panel.getByRole("checkbox")).toHaveCount(0);
});
