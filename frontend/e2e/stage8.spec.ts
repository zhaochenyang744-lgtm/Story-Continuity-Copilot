import { expect, test } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { registerAccount } from "./support/app";
import { projectMoreAction, startVisitor } from "./support/batch2";

const screenshots = path.resolve(process.env.E2E_SCREENSHOTS_DIR ?? "../artifacts/stage8-screenshots");
const globalNavButton = (page: import("@playwright/test").Page, name: "首页" | "作品管理") =>
  page.locator(".global-nav").getByRole("button", { name, exact: true });
const projectNavButton = (page: import("@playwright/test").Page, name: string) =>
  page.locator(".project-nav").getByRole("button", { name, exact: true });
const openProject = (page: import("@playwright/test").Page, title: string) =>
  page.locator(".project-rows li").filter({ hasText: title }).getByRole("button", { name: "打开", exact: true });

test("fresh account restores login and visitor completes the preset Grey Harbor review without a Provider call", async ({ page }) => {
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

  const { account, password } = await registerAccount(page, { prefix: "stage8" });

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  await startVisitor(page);
  await expect(page.locator(".home-issue-list li").filter({ hasText: "纸月档案" })).toContainText("尚未检查");

  await globalNavButton(page, "作品管理").click();
  await expect(page.locator(".project-rows li").filter({ hasText: "纸月档案" })).toContainText("尚未检查");
  await expect(page.locator(".project-rows li").filter({ hasText: "灰港回声" })).toContainText("4 项待处理");
  await openProject(page, "灰港回声").click();
  await expect(page.getByRole("button", { name: /更换当前作品.*灰港回声/ })).toBeVisible();
  await projectNavButton(page, "写作与检查").click();
  await expect(page.getByText("示例检查结果", { exact: true })).toBeVisible();
  await expect(page.getByText("本次没有调用模型", { exact: false })).toBeVisible();
  await expect(page.locator(".issue-list .issue-row")).toHaveCount(4);

  const firstIssue = page.locator(".issue-list .issue-row").first();
  await firstIssue.click();
  const drawer = page.getByRole("dialog", { name: "问题证据" });
  await expect(drawer.getByRole("heading", { name: "历史证据", exact: true })).toBeVisible();
  await expect(drawer.getByText(/第 \d+ 章《.+》/).first()).toBeVisible();
  await expect(drawer.locator(".evidence blockquote").first()).not.toBeEmpty();
  await page.screenshot({ path: path.join(screenshots, "grey-harbor-readable-evidence.png"), fullPage: true });
  await drawer.getByRole("button", { name: "查看来源", exact: true }).click();
  const source = page.getByRole("dialog", { name: /的章节来源$/ });
  await expect(source.getByRole("heading", { name: /第 \d+ 章《.+》/ })).toBeVisible();
  await expect(source.locator(".source-drawer-header")).toContainText("原文第 1 版");
  await expect(source.locator(".source-excerpt blockquote")).not.toBeEmpty();
  await source.locator("summary").click();
  await expect(source.locator(".source-technical")).toContainText(new URL(page.url()).pathname.replace(/workspace$/, "sources#span-"));
  await page.keyboard.press("Escape");
  await expect(source).toBeHidden();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();

  for (const claim of ["温岚把罗盘", "罗盘暂时离开", "苏岑决定先核对"]) {
    await page.locator(".issue-list .issue-row").filter({ hasText: claim }).click();
    await drawer.getByRole("button", { name: "保留原意" }).click();
    await expect(drawer).toBeHidden();
  }
  await page.locator(".issue-list .issue-row").filter({ hasText: "表面冲突" }).click();
  await drawer.getByRole("button", { name: "标记误报" }).click();
  await expect(drawer).toBeHidden();
  await expect(page.locator(".issue-list .issue-row").filter({ hasText: "决定已记录" })).toHaveCount(4);

  await page.getByRole("button", { name: "审阅事实变化" }).click();
  const review = page.getByRole("form", { name: "事实库更新审阅" });
  await expect(review.locator("article.diff")).toHaveCount(3);
  await review.getByLabel("接受（写入候选）").nth(0).check();
  await review.getByLabel("拒绝（不写入）").nth(1).check();
  await review.getByLabel("编辑后接受").nth(2).check();
  await review.locator("article.diff").nth(2).getByLabel("事实内容").fill("先核对异常雾钟，再追查白色渡船");
  await page.screenshot({ path: path.join(screenshots, "memory-review-three-actions.png"), fullPage: true });
  await review.getByRole("button", { name: "确认并提交审核结果" }).click();
  await expect(page.getByText("MemoryVersion 5 已创建", { exact: false })).toBeVisible();
  await projectNavButton(page, "事实库").click();
  await expect(page.getByText("先核对异常雾钟，再追查白色渡船", { exact: false })).toBeVisible();
  await expect(page.getByText("作者已确认", { exact: false }).first()).toBeVisible();

  await page.getByRole("button", { name: /更换当前作品.*灰港回声/ }).click();
  await openProject(page, "纸月档案").click();
  await expect(page.getByRole("heading", { name: "纸月档案" })).toBeVisible();
  await expect(page.locator(".memory-panel").getByText("尚未检查", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: /更换当前作品.*纸月档案/ }).click();
  await openProject(page, "灰港回声").click();
  await projectMoreAction(page, "重置当前作品");
  const reset = page.getByRole("dialog", { name: "重置当前作品" });
  await expect(reset).toContainText("当前内容会被覆盖");
  await expect(reset).toContainText("其他作品和其他账户不受影响");
  await expect(reset).toContainText("重置后无法撤销");
  await reset.getByRole("button", { name: "确认重置" }).click();
  await expect(page.getByText("事实库第 4 版", { exact: false }).first()).toBeVisible();
  await projectNavButton(page, "写作与检查").click();
  await expect(page.locator(".issue-list .issue-row")).toHaveCount(4);
  await expect(page.locator(".issue-list .issue-row").filter({ hasText: "决定已记录" })).toHaveCount(0);
  await expect(page.getByText("示例检查结果", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
  expect(checkPosts).toEqual([]);
  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
