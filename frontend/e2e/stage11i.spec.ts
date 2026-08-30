import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const originalWork = path.resolve(process.cwd(), "e2e/fixtures/stage9-mist-harbor.md");

async function importAndOpenReview(page: import("@playwright/test").Page, title: string) {
  await page.goto("/register");
  await page.getByLabel("账号").fill(`stage11i${Date.now()}${Math.floor(Math.random() * 1000)}`);
  await page.getByLabel("显示名称").fill("阶段十一作者");
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
  await page.getByRole("button", { name: "继续确认" }).click();
  await page.getByLabel("作品名").fill(title);
  await page.getByLabel("说明").fill("阶段 11I 确定性假 Provider 浏览器用例");
  await page.getByRole("button", { name: "确认导入" }).click();
  await page.getByRole("button", { name: "初始化 Story Memory" }).click();
  await page.getByRole("button", { name: "审核候选与 Evidence" }).click();
  return page.getByRole("form", { name: "Story Memory 初始化审核" });
}

test("all core final plus a confirmed core keeps supporting pending outside canon and starts Check", async ({ page }) => {
  const review = await importAndOpenReview(page, "11I 部分确认");
  const core = review.locator("article.memory-init-candidate").filter({ hasText: "核心候选（必须决定）" });
  const supporting = review.locator("article.memory-init-candidate").filter({ hasText: "辅助候选（可继续待审）" });
  await expect(core).toHaveCount(1);
  await expect(supporting).toHaveCount(2);
  await core.getByLabel("接受（写入 V1）").check();
  await review.getByRole("button", { name: "确认核心审核并建立 Memory V1" }).click();
  await expect(review.getByText("已安全建立部分 Memory", { exact: true })).toBeVisible();
  await expect(review.getByText("不在 canon 或 Provider 输入中", { exact: false })).toBeVisible();
  const projectId = new URL(page.url()).pathname.split("/")[2];
  const coverage = await page.evaluate(async (id) => (await fetch(`/api/projects/${id}/memory/coverage`)).json(), projectId);
  const memory = await page.evaluate(async (id) => (await fetch(`/api/projects/${id}/memory`)).json(), projectId);
  expect(coverage.data).toMatchObject({
    status: "ready_partial",
    counts: { core_pending: 0, supporting_pending: 2, confirmed_core: 1, pending_canon_count: 0 },
  });
  expect(memory.data.records).toHaveLength(1);
  await review.getByRole("button", { name: "开始连续性检查" }).click();
  await expect(page.locator("#draft-body")).toBeVisible();
  await page.locator("#draft-body").fill("钟声响起后，所有船只继续离开雾港。");
  await page.getByRole("button", { name: "保存草稿" }).click();
  await page.getByRole("button", { name: "运行连续性检查" }).click();
  await expect(page.locator(".issue-list li").first()).toBeVisible();
});

test("all final decisions reaches ready_current", async ({ page }) => {
  const decisions: string[] = [];
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/candidates\/[^/]+\/decision$/.test(new URL(request.url()).pathname))
      decisions.push((request.postDataJSON() as { decision: string }).decision);
  });
  const review = await importAndOpenReview(page, "11I 全部处理");
  const core = review.locator("article.memory-init-candidate").filter({ hasText: "核心候选（必须决定）" });
  const supporting = review.locator("article.memory-init-candidate").filter({ hasText: "辅助候选（可继续待审）" });
  await expect(core).toHaveCount(1);
  await expect(supporting).toHaveCount(2);
  for (const candidate of await supporting.all()) {
    const reject = candidate.locator('input[value="rejected"]');
    await reject.check();
    await expect(reject).toBeChecked();
  }
  await core.getByLabel("接受（写入 V1）").check();
  await expect(review.locator('input[name^="memory-init:"]:checked')).toHaveCount(3);
  const selectedIds = await review.locator('input[data-memory-candidate-id]:checked').evaluateAll((inputs) => inputs.map((input) => input.getAttribute("data-memory-candidate-id")));
  expect(new Set(selectedIds).size).toBe(3);
  await review.getByRole("button", { name: "确认核心审核并建立 Memory V1" }).click();
  await expect(page.getByText("Memory V1 已由作者审核后建立", { exact: false })).toBeVisible();
  expect(decisions).toEqual(expect.arrayContaining(["accepted", "rejected", "rejected"]));
  const projectId = new URL(page.url()).pathname.split("/")[2];
  const coverage = await page.evaluate(async (id) => (await fetch(`/api/projects/${id}/memory/coverage`)).json(), projectId);
  expect(coverage.data).toMatchObject({ status: "ready_current", counts: { supporting_pending: 0, confirmed_core: 1, pending_canon_count: 0 } });
});

test("all core rejected remains in_review and Check fails closed", async ({ page }) => {
  const failedChecks: number[] = [];
  page.on("response", (response) => {
    if (new URL(response.url()).pathname.endsWith("/checks") && response.request().method() === "POST") failedChecks.push(response.status());
  });
  const review = await importAndOpenReview(page, "11I 核心全拒绝");
  const core = review.locator("article.memory-init-candidate").filter({ hasText: "核心候选（必须决定）" });
  await expect(core).toHaveCount(1);
  await core.getByLabel("拒绝（不写入）").check();
  await review.getByRole("button", { name: "确认核心审核并建立 Memory V1" }).click();
  await expect(review.getByText("核心候选均未被确认；尚不能开始连续性检查。", { exact: true })).toBeVisible();
  const projectId = new URL(page.url()).pathname.split("/")[2];
  const coverage = await page.evaluate(async (id) => (await fetch(`/api/projects/${id}/memory/coverage`)).json(), projectId);
  expect(coverage.data).toMatchObject({ status: "in_review", counts: { confirmed_core: 0, pending_canon_count: 0 } });
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await page.getByRole("button", { name: "运行连续性检查" }).click();
  await expect(page.getByText("Story Memory 尚待初始化", { exact: false })).toBeVisible();
  expect(failedChecks).toEqual([422]);
});

test("390px is browse-only: initialization decisions and commit are disabled", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const review = await importAndOpenReview(page, "11I 窄屏只读");
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(review.getByText("初始化候选审核", { exact: true })).toBeVisible();
  for (const input of await review.locator("input, select, textarea").all()) await expect(input).toBeDisabled();
  await expect(review.getByRole("button", { name: "确认核心审核并建立 Memory V1" })).toBeDisabled();
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  const save = page.getByRole("button", { name: "保存草稿" });
  const check = page.getByRole("button", { name: "运行连续性检查" });
  expect((await save.count()) === 0 || await save.isDisabled()).toBe(true);
  expect((await check.count()) === 0 || await check.isDisabled()).toBe(true);
});
