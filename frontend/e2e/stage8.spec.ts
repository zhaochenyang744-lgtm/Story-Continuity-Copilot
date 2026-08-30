import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

const screenshots = path.resolve(process.cwd(), "../artifacts/stage8-screenshots");
const globalNavButton = (page: import("@playwright/test").Page, name: "首页" | "作品管理") =>
  page.locator(".global-nav").getByRole("button", { name, exact: true });
const projectNavButton = (page: import("@playwright/test").Page, name: string) =>
  page.locator(".project-nav").getByRole("button", { name, exact: true });
const openProject = (page: import("@playwright/test").Page, title: string) =>
  page.locator(".project-rows li").filter({ hasText: title }).getByRole("button", { name: "打开", exact: true });

test("fresh account completes the preset Grey Harbor author review without a Provider call", async ({ page }) => {
  await mkdir(screenshots, { recursive: true });
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const checkPosts: string[] = [];
  let expectedSessionUnauthorized = 0;
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (message.text() === "Failed to load resource: the server responded with a status of 401 (Unauthorized)" && expectedSessionUnauthorized > 0) {
      expectedSessionUnauthorized -= 1;
      return;
    }
    consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (request.method() === "POST" && /\/api\/projects\/[^/]+\/checks$/.test(pathname)) checkPosts.push(pathname);
  });
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (!pathname.startsWith("/api/") || response.status() < 400) return;
    if (pathname === "/api/auth/session" && response.status() === 401) {
      expectedSessionUnauthorized += 1;
      return;
    }
    failedRequests.push(`${response.request().method()} ${pathname} ${response.status()}`);
  });

  const account = `stage8${Date.now()}${Math.random().toString(16).slice(2, 8)}`;
  const password = `test-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("阶段八本地作者");
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "创建本地账号" }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  await expect(page.locator(".home-issue-list li").filter({ hasText: "纸月档案" })).toContainText("尚未检查");

  await globalNavButton(page, "作品管理").click();
  await expect(page.locator(".project-rows li").filter({ hasText: "纸月档案" })).toContainText("尚未检查");
  await expect(page.locator(".project-rows li").filter({ hasText: "灰港回声" })).toContainText("4 项待处理");
  await openProject(page, "灰港回声").click();
  await expect(page.getByRole("button", { name: /更换当前作品.*灰港回声/ })).toBeVisible();
  await projectNavButton(page, "写作与检查").click();
  await expect(page.getByText("预置演示审阅数据", { exact: true })).toBeVisible();
  await expect(page.getByText("本次未调用 Provider", { exact: false })).toBeVisible();
  await expect(page.locator(".issue-list li")).toHaveCount(4);

  const firstIssue = page.locator(".issue-list li").first();
  await firstIssue.getByRole("button").click();
  const drawer = page.getByRole("dialog", { name: "问题证据" });
  await expect(drawer.getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();
  await expect(drawer.getByText(/第 \d+ 章《.+》/).first()).toBeVisible();
  await expect(drawer.locator(".evidence p").filter({ hasText: "来源修订" })).toContainText("r1");
  await expect(drawer.locator("blockquote")).not.toBeEmpty();
  await page.screenshot({ path: path.join(screenshots, "grey-harbor-readable-evidence.png"), fullPage: true });
  await drawer.getByRole("link", { name: "回到当前作品的章节来源" }).click();
  await expect(page.getByRole("heading", { name: "章节来源" })).toBeVisible();
  await expect(page).toHaveURL(/\/sources#span-/);
  await expect(page.locator(".read-list li").first()).toBeVisible();
  await projectNavButton(page, "写作与检查").click();

  for (const claim of ["温岚把罗盘", "罗盘暂时离开", "苏岑决定先核对"]) {
    await page.locator(".issue-list li").filter({ hasText: claim }).getByRole("button").click();
    await drawer.getByRole("button", { name: "Keep intentional" }).click();
    await expect(drawer).toBeHidden();
  }
  await page.locator(".issue-list li").filter({ hasText: "表面冲突" }).getByRole("button").click();
  await drawer.getByRole("button", { name: "Mark false positive" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator(".issue-list li").filter({ hasText: "已决策" })).toHaveCount(4);

  await page.getByRole("button", { name: "审阅 Memory 变更" }).click();
  const review = page.getByRole("form", { name: "Memory Update Review" });
  await expect(review.locator("article.diff")).toHaveCount(3);
  await review.getByLabel("接受（写入候选）").nth(0).check();
  await review.getByLabel("拒绝（不写入）").nth(1).check();
  await review.getByLabel("编辑后接受").nth(2).check();
  await review.locator("article.diff").nth(2).getByLabel("事实内容").fill("先核对异常雾钟，再追查白色渡船");
  await page.screenshot({ path: path.join(screenshots, "memory-review-three-actions.png"), fullPage: true });
  await review.getByRole("button", { name: "确认并提交审核结果" }).click();
  await expect(page.getByText("MemoryVersion 5 已创建", { exact: false })).toBeVisible();
  await projectNavButton(page, "Story Memory").click();
  await expect(page.getByText("先核对异常雾钟，再追查白色渡船", { exact: false })).toBeVisible();
  await expect(page.getByText("作者已确认", { exact: false }).first()).toBeVisible();

  await page.getByRole("button", { name: /更换当前作品.*灰港回声/ }).click();
  await openProject(page, "纸月档案").click();
  await expect(page.getByRole("heading", { name: "纸月档案" })).toBeVisible();
  await expect(page.locator(".memory-panel").getByText("尚未检查", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /更换当前作品.*纸月档案/ }).click();
  await openProject(page, "灰港回声").click();
  await page.getByRole("button", { name: "Reset 当前作品" }).click();
  const reset = page.getByRole("dialog", { name: "恢复当前作品" });
  await expect(reset).toContainText("当前内容会被覆盖");
  await expect(reset).toContainText("其他作品和其他账户不受影响");
  await expect(reset).toContainText("恢复后无法撤销");
  await reset.getByRole("button", { name: "确认恢复" }).click();
  await expect(page.getByText("Memory V4", { exact: false }).first()).toBeVisible();
  await projectNavButton(page, "写作与检查").click();
  await expect(page.locator(".issue-list li")).toHaveCount(4);
  await expect(page.locator(".issue-list li").filter({ hasText: "已决策" })).toHaveCount(0);
  await expect(page.getByText("预置演示审阅数据", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  expect(checkPosts).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
