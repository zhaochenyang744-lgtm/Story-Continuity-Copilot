import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const lifecycle = (page: Page) => page.getByLabel("Agent Run 生命周期");
const fixture = path.resolve(process.cwd(), "frontend/e2e/fixtures/stage9-mist-harbor.md");
const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix?.startsWith("stage12v2")) {
  throw new Error("E2E_ACCOUNT_PREFIX must start with stage12v2");
}

async function registerAndOpen(page: Page, prefix: string) {
  await page.goto("/register");
  await page.getByLabel("账号").fill(`${accountPrefix}-${prefix}-${Date.now()}`);
  await page.getByLabel("显示名称").fill("阶段十二作者");
  await page.getByLabel("恢复邮箱").fill(`${accountPrefix}-${prefix}-${Date.now()}@example.test`);
  await page.locator("#auth-password").fill(`safe-${randomUUID()}`);
  const registration = page.waitForResponse((response) => response.request().method() === "POST" && new URL(response.url()).pathname === "/api/auth/register");
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  expect((await registration).status()).toBe(201);
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "作品管理" })).toBeVisible();
  const row = page.locator(".project-rows li").filter({ hasText: "灰港回声" });
  await row.getByRole("button", { name: "打开" }).click();
  await page.locator(".project-nav").getByRole("button", { name: "写作与检查" }).click();
  await expect(page.locator(".workspace-page")).toBeVisible();
}

async function saveMarker(page: Page, marker: string) {
  const editor = page.getByLabel("草稿正文");
  await editor.fill(`${await editor.inputValue()}\n${marker}`);
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.getByLabel("草稿修订", { exact: true })).toContainText("已保存");
}

async function run(page: Page) {
  await page.getByRole("button", { name: "运行连续性检查" }).click();
  await expect(lifecycle(page)).toBeVisible();
}

async function providerStats(page: Page) {
  return (await (await page.request.get("/api/test/stage12/stats")).json()) as {
    provider_mode: string;
    external_provider_http_enabled: boolean;
    provider_calls: number;
    provider_http_calls: number;
    blocked: boolean;
    test_root: string;
  };
}

async function expectProviderIsolation(page: Page) {
  const stats = await providerStats(page);
  expect(stats.provider_mode).toBe("injected_stub");
  expect(stats.external_provider_http_enabled).toBe(false);
  expect(stats.provider_http_calls).toBe(0);
  expect(stats.test_root).toContain("story-stage12-v2-");
}

async function prepareIncrementalProject(page: Page, marker = "") {
  await page.goto("/register");
  await page.getByLabel("账号").fill(`${accountPrefix}-pair-${Date.now()}`);
  await page.getByLabel("显示名称").fill("阶段十二增量作者");
  await page.getByLabel("恢复邮箱").fill(`${accountPrefix}-pair-${Date.now()}@example.test`);
  await page.locator("#auth-password").fill(`safe-${randomUUID()}`);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "导入作品", exact: true }).click();
  await page.locator('input[name="file"]').setInputFiles({
    name: "base.md",
    mimeType: "text/markdown",
    buffer: await readFile(fixture),
  });
  await page.getByRole("button", { name: "解析并预览章节" }).click();
  await page.getByRole("button", { name: "继续确认" }).click();
  await page.getByLabel("作品名").fill("阶段十二增量双 Run");
  await page.getByRole("button", { name: "确认导入" }).click();
  await page.getByRole("button", { name: "初始化 Story Memory" }).click();
  await page.getByRole("button", { name: "审核候选与 Evidence" }).click();
  const initialization = page.getByRole("form", { name: "Story Memory 初始化审核" });
  await initialization
    .locator("article.memory-init-candidate")
    .filter({ hasText: "核心候选（必须决定）" })
    .getByLabel("接受（写入 V1）")
    .check();
  const initializationCommitted = page.waitForResponse(
    (response) =>
      /\/memory\/initializations\/[^/]+\/commit$/.test(
        new URL(response.url()).pathname,
      ) && response.request().method() === "POST",
  );
  await initialization
    .getByRole("button", { name: "确认核心审核并建立 Memory V1" })
    .click();
  expect((await initializationCommitted).status()).toBe(200);
  await expect(
    initialization.getByText("已安全建立部分 Memory", { exact: true }),
  ).toBeVisible();
  const projectId = new URL(page.url()).pathname.split("/")[2];
  await page.goto(`/projects/${projectId}/sources`);
  await page
    .getByLabel("章节正文")
    .fill(`# 增量章节\n林默将银钥匙交给守塔人。\n${marker}`);
  const previewed = page.waitForResponse(
    (response) =>
      response.url().includes("source-change-sets/preview") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "预览追加" }).click();
  expect((await previewed).status()).toBe(201);
  const committed = page.waitForResponse(
    (response) =>
      /source-change-sets\/.+\/commit/.test(response.url()) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "确认追加并创建下一章草稿" }).click();
  expect((await committed).status()).toBe(200);
  return projectId;
}

test.describe("Stage 12 Agent Run lifecycle", () => {
  test("success exposes actual metrics and provenance, survives refresh, and fits 390px", async ({ page }) => {
    await expectProviderIsolation(page);
    await page.setViewportSize({ width: 1440, height: 960 });
    await registerAndOpen(page, "stage12success");
    await saveMarker(page, "STAGE12_SUCCESS");
    await run(page);
    await expect(lifecycle(page)).toContainText("检查完成", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("144 in / 52 out");
    await expect(lifecycle(page)).toContainText("实际 cost ¥0.0042");
    await expect(lifecycle(page).getByRole("button", { name: "取消 Run" })).toHaveCount(0);
    await page.reload();
    await expect(lifecycle(page)).toContainText("检查完成");
    await lifecycle(page).getByText("查看 provenance 与状态事件").click();
    await expect(lifecycle(page)).toContainText("browser-e2e-test-provider");
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(lifecycle(page)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expectProviderIsolation(page);
  });

  test("running cancel restores after refresh and discards the late success", async ({ page }) => {
    await page.request.get("/api/test/stage12/reset");
    await registerAndOpen(page, "stage12cancel");
    await saveMarker(page, "STAGE12_BLOCK");
    await run(page);
    await expect.poll(async () => (await providerStats(page)).blocked).toBe(true);
    await expect(lifecycle(page).getByRole("button", { name: "取消 Run" })).toBeVisible();
    await expect(lifecycle(page).getByRole("button", { name: "重试为新 Run" })).toHaveCount(0);
    await page.reload();
    await expect(lifecycle(page).getByRole("button", { name: "取消 Run" })).toBeVisible();
    await lifecycle(page).getByRole("button", { name: "取消 Run" }).click();
    await expect(lifecycle(page)).toContainText("正在安全取消");
    await page.request.get("/api/test/stage12/release");
    await expect(lifecycle(page)).toContainText("已取消", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("未写入部分 Issue、Evidence、Decision 或 Memory 结果");
    await expect(page.locator(".issue-list li")).toHaveCount(0);
    await expectProviderIsolation(page);
  });

  test("timeout is terminal, honest, retryable, and shows no partial Issues", async ({ page }) => {
    await registerAndOpen(page, "stage12timeout");
    await saveMarker(page, "STAGE12_TIMEOUT");
    await run(page);
    await expect(lifecycle(page)).toContainText("检查超时", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("Provider 响应超时");
    await expect(lifecycle(page).getByRole("button", { name: "重试为新 Run" })).toBeVisible();
    await expect(lifecycle(page).getByRole("button", { name: "取消 Run" })).toHaveCount(0);
    await expect(page.locator(".issue-list li")).toHaveCount(0);
    await expectProviderIsolation(page);
  });

  test("failed Run retries as attempt 2 while the original lineage remains immutable", async ({ page }) => {
    await registerAndOpen(page, "stage12retry");
    await saveMarker(page, "STAGE12_FAIL_ONCE");
    await run(page);
    await expect(lifecycle(page)).toContainText("检查失败", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("attempt 1");
    const original = await lifecycle(page).textContent();
    const originalRun = original?.match(/run-[0-9a-f-]+/)?.[0];
    expect(originalRun).toBeTruthy();
    await lifecycle(page).getByRole("button", { name: "重试为新 Run" }).click();
    await expect(lifecycle(page)).toContainText("attempt 2", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("检查完成", { timeout: 15_000 });
    await lifecycle(page).getByText("查看 provenance 与状态事件").click();
    await expect(lifecycle(page)).toContainText(`root ${originalRun}`);
    await page.reload();
    await expect(lifecycle(page)).toContainText("attempt 2");
    await expect(lifecycle(page)).toContainText("检查完成");
    await expectProviderIsolation(page);
  });

  test("non-retryable failed Run stays terminal and never offers Retry", async ({ page }) => {
    await page.request.get("/api/test/stage12/reset");
    await registerAndOpen(page, "nonretryable");
    await saveMarker(page, "STAGE12_BLOCK");
    await run(page);
    await expect.poll(async () => (await providerStats(page)).blocked).toBe(true);
    const runText = await lifecycle(page).textContent();
    const runId = runText?.match(/run-[0-9a-f-]+/)?.[0];
    const projectId = new URL(page.url()).pathname.split("/")[2];
    expect(runId).toBeTruthy();
    const forced = await page.request.post(
      `/api/test/stage12/projects/${projectId}/runs/${runId}/fail-nonretryable`,
    );
    expect(forced.status()).toBe(200);
    expect((await forced.json()).changed).toBe(true);
    await page.request.get("/api/test/stage12/release");
    await expect(lifecycle(page)).toContainText("检查失败", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("Provider 结果未通过结构校验");
    await expect(lifecycle(page).getByRole("button", { name: "重试为新 Run" })).toHaveCount(0);
    await expect(page.locator(".issue-list li")).toHaveCount(0);
    await expectProviderIsolation(page);
  });

  test("Retry idempotency conflicts and project/account isolation fail closed", async ({ page, browser }) => {
    await registerAndOpen(page, "isolation-owner");
    await saveMarker(page, "STAGE12_TIMEOUT");
    await run(page);
    await expect(lifecycle(page)).toContainText("检查超时", { timeout: 15_000 });
    const originalText = await lifecycle(page).textContent();
    const runId = originalText?.match(/run-[0-9a-f-]+/)?.[0];
    const projectId = new URL(page.url()).pathname.split("/")[2];
    expect(runId).toBeTruthy();
    const projects = await page.evaluate(async () =>
      (await (await fetch("/api/projects")).json()).data.projects,
    ) as { id: string }[];
    const otherProjectId = projects.find((item) => item.id !== projectId)?.id;
    expect(otherProjectId).toBeTruthy();
    const key = randomUUID();
    const retry = (body: object) =>
      page.request.post(`/api/projects/${projectId}/checks/${runId}/retry`, {
        headers: { "Idempotency-Key": key },
        data: body,
      });
    const first = await retry({ client_request_id: "browser-retry-1" });
    const replay = await retry({ client_request_id: "browser-retry-1" });
    const conflict = await retry({ client_request_id: "browser-retry-2" });
    expect([first.status(), replay.status(), conflict.status()]).toEqual([202, 202, 409]);
    expect((await first.json()).data).toEqual((await replay.json()).data);
    const wrongProject = await page.request.post(
      `/api/projects/${otherProjectId}/checks/${runId}/retry`,
      { headers: { "Idempotency-Key": randomUUID() }, data: {} },
    );
    expect(wrongProject.status()).toBe(404);

    const outsiderContext = await browser.newContext({ baseURL: process.env.E2E_BASE_URL });
    const outsider = await outsiderContext.newPage();
    await outsider.goto("/register");
    await outsider.getByLabel("账号").fill(`${accountPrefix}-isolation-outsider-${Date.now()}`);
    await outsider.getByLabel("显示名称").fill("隔离账号");
    await outsider.getByLabel("恢复邮箱").fill(`${accountPrefix}-outsider-${Date.now()}@example.test`);
    await outsider.locator("#auth-password").fill(`safe-${randomUUID()}`);
    const outsiderRegistered = outsider.waitForResponse(
      (response) =>
        new URL(response.url()).pathname === "/api/auth/register" &&
        response.request().method() === "POST",
    );
    await outsider.getByRole("button", { name: "创建账号", exact: true }).click();
    expect((await outsiderRegistered).status()).toBe(201);
    await expect(outsider.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
    const crossAccount = await outsider.request.post(
      `/api/projects/${projectId}/checks/${runId}/retry`,
      { headers: { "Idempotency-Key": randomUUID() }, data: {} },
    );
    expect(crossAccount.status()).toBe(404);
    await outsiderContext.close();
    await expectProviderIsolation(page);
  });

  test("paired incremental Continuity and Memory Delta restore together at desktop and 390px", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    await expectProviderIsolation(page);
    const projectId = await prepareIncrementalProject(page);
    await page.goto(`/projects/${projectId}/workspace`);
    const started = page.waitForResponse(
      (response) =>
        response.url().endsWith("/incremental-reviews") &&
        response.request().method() === "POST",
    );
    await page
      .locator(".warning")
      .filter({ hasText: "Source r2" })
      .getByRole("button", { name: "运行增量检查" })
      .click();
    const startedResponse = await started;
    expect(startedResponse.status()).toBe(202);
    const pair = (await startedResponse.json()).data as {
      continuity_run_id: string;
      memory_delta_run_id: string;
    };
    expect(pair.continuity_run_id).not.toBe(pair.memory_delta_run_id);
    const continuity = page.getByLabel("Continuity Agent Run 生命周期", { exact: true });
    const memoryDelta = page.getByLabel("Memory Delta Agent Run 生命周期", { exact: true });
    await expect(continuity).toContainText("检查完成", { timeout: 15_000 });
    await expect(memoryDelta).toContainText("检查完成", { timeout: 15_000 });
    await expect(continuity).toContainText(pair.continuity_run_id);
    await expect(memoryDelta).toContainText(pair.memory_delta_run_id);
    await page.reload();
    await expect(continuity).toContainText(pair.continuity_run_id);
    await expect(memoryDelta).toContainText(pair.memory_delta_run_id);
    await page.setViewportSize({ width: 390, height: 844 });
    await expect(continuity).toBeVisible();
    await expect(memoryDelta).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await expectProviderIsolation(page);
  });

  test("incremental timeout terminates both sibling Runs without partial UI results", async ({ page }) => {
    await page.setViewportSize({ width: 1440, height: 960 });
    const projectId = await prepareIncrementalProject(page, "STAGE12_TIMEOUT");
    await page.goto(`/projects/${projectId}/workspace`);
    const started = page.waitForResponse(
      (response) =>
        response.url().endsWith("/incremental-reviews") &&
        response.request().method() === "POST",
    );
    await page
      .locator(".warning")
      .filter({ hasText: "Source r2" })
      .getByRole("button", { name: "运行增量检查" })
      .click();
    expect((await started).status()).toBe(202);
    const continuity = page.getByLabel("Continuity Agent Run 生命周期", { exact: true });
    const memoryDelta = page.getByLabel("Memory Delta Agent Run 生命周期", { exact: true });
    await expect(continuity).toContainText("检查超时", { timeout: 15_000 });
    await expect(memoryDelta).toContainText("检查超时", { timeout: 15_000 });
    await expect(continuity).toContainText("未写入部分 Issue、Evidence、Decision 或 Memory 结果");
    await expect(memoryDelta).toContainText("未写入部分 Issue、Evidence、Decision 或 Memory 结果");
    await expect(page.locator(".issue-list li")).toHaveCount(0);
    const delta = await page.evaluate(async (id) =>
      (await (await fetch(`/api/projects/${id}/memory/delta`)).json()).data,
      projectId,
    );
    expect(delta).toMatchObject({ status: "failed", error_code: "provider_timeout" });
    await expectProviderIsolation(page);
  });
});
