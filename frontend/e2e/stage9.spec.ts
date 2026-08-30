import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const originalWork = path.resolve(process.cwd(), "e2e/fixtures/stage9-mist-harbor.md");

const projectNav = (page: import("@playwright/test").Page, name: string) =>
  page.locator(".project-nav").getByRole("button", { name, exact: true });

test("imported markdown follows author-reviewed Memory V1 initialization before its first check", async ({ page }) => {
  const consoleErrors: string[] = [];
  const failedRequests: string[] = [];
  const initializationDecisionBodies: Array<Record<string, unknown>> = [];
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
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (!pathname.startsWith("/api/") || response.status() < 400) return;
    if (pathname === "/api/auth/session" && response.status() === 401) {
      expectedSessionUnauthorized += 1;
      return;
    }
    failedRequests.push(`${response.request().method()} ${pathname} ${response.status()}`);
  });
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/memory\/initializations\/[^/]+\/candidates\/[^/]+\/decision$/.test(new URL(request.url()).pathname))
      initializationDecisionBodies.push(request.postDataJSON() as Record<string, unknown>);
  });

  await page.goto("/register");
  await page.getByLabel("账号").fill(`stage9${Date.now()}`);
  await page.getByLabel("显示名称").fill("阶段九作者");
  await page.getByLabel("密码").fill(`test-${randomUUID()}`);
  await page.getByRole("button", { name: "创建本地账号" }).click();
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "导入作品", exact: true }).click();

  await page.locator('input[name="file"]').setInputFiles({
    name: "mist-harbor.md",
    mimeType: "text/markdown",
    buffer: await readFile(originalWork),
  });
  await page.getByRole("button", { name: "解析并预览章节" }).click();
  await expect(page.getByRole("heading", { name: "章节预览" })).toBeVisible();
  await page.getByRole("button", { name: "继续确认" }).click();
  await page.getByLabel("作品名").fill("雾港原创测试");
  await page.getByLabel("说明").fill("阶段 9 原创确定性 Markdown 作品");
  await page.getByRole("button", { name: "确认导入" }).click();
  await expect(page.getByRole("heading", { name: "雾港原创测试" })).toBeVisible();
  await expect(page.getByText("不会自动生成 Story Memory", { exact: false })).toHaveCount(0);

  await page.getByRole("button", { name: "初始化 Story Memory" }).click();
  await expect(page.getByText("候选已生成，尚未写入 Story Memory", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "审核候选与 Evidence" }).click();
  const review = page.getByRole("form", { name: "Story Memory 初始化审核" });
  await expect(review.getByText("尚未成为 canon", { exact: false }).first()).toBeVisible();
  await expect(review.locator("article.memory-init-candidate")).toHaveCount(3);
  await expect(review.getByText("SourceSpan", { exact: false }).first()).toBeVisible();
  const harbor = review.locator("article.memory-init-candidate").filter({ hasText: "雾港钟声" });
  const key = review.locator("article.memory-init-candidate").filter({ hasText: "银钥匙" });
  const dawn = review.locator("article.memory-init-candidate").filter({ hasText: "清晨门扉" });
  await expect(harbor.locator("blockquote")).toContainText("钟声响起后");
  await harbor.getByLabel("接受（写入 V1）").check();
  await key.getByLabel("拒绝（不写入）").check();
  await dawn.getByLabel("编辑后接受").check();
  await dawn.getByLabel("事实内容").fill("确认北堤门只在清晨开启");
  await review.getByRole("button", { name: "确认核心审核并建立 Memory V1" }).click();
  await expect(review).toBeVisible();
  expect(initializationDecisionBodies).toEqual([]);
  await dawn.getByLabel("我确认编辑后的事实仍由上方 Evidence 支持").check();
  const editedDecisionRequest = page.waitForRequest((request) => {
    if (request.method() !== "POST" || !/\/memory\/initializations\/[^/]+\/candidates\/[^/]+\/decision$/.test(new URL(request.url()).pathname)) return false;
    return (request.postDataJSON() as Record<string, unknown>).decision === "edited";
  });
  await review.getByRole("button", { name: "确认核心审核并建立 Memory V1" }).click();
  expect((await editedDecisionRequest).postDataJSON()).toMatchObject({ evidence_span_id: expect.any(String) });
  await expect(page.getByText("雾港钟声", { exact: false })).toBeVisible();
  await expect(page.getByText("银钥匙", { exact: true })).toHaveCount(0);

  await projectNav(page, "写作与检查").click();
  await page.locator("#draft-body").fill("林默把银钥匙交给了陌生人。钟声仍在雾港回荡。");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page.getByRole("button", { name: "运行连续性检查" }).click();
  await expect(page.locator(".issue-list li").first()).toBeVisible();
  await page.locator(".issue-list li").first().getByRole("button").click();
  const drawer = page.getByRole("dialog", { name: "问题证据" });
  await expect(drawer.getByRole("heading", { name: "Evidence", exact: true })).toBeVisible();
  await expect(drawer.locator("blockquote")).not.toBeEmpty();

  expect(failedRequests).toEqual([]);
  expect(consoleErrors).toEqual([]);
});
