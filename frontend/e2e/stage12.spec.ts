import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { importMarkdown, readDraftBody, registerAccount, setDraftBody } from "./support/app";
import { startVisitor } from "./support/batch2";
import { bindRun, continuityLifecycle, openRunDetails, readLifecycleRun, startLifecycleRun } from "./support/batch3";

const lifecycle = continuityLifecycle;
const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix?.startsWith("stage12v2")) {
  throw new Error("E2E_ACCOUNT_PREFIX must start with stage12v2");
}

async function visitorAndOpen(page: Page) {
  await startVisitor(page);
  await page.goto("/projects");
  await expect(page.getByRole("heading", { name: "作品管理" })).toBeVisible();
  const row = page.locator(".project-rows li").filter({ hasText: "灰港回声" });
  await row.getByRole("button", { name: "打开" }).click();
  await page.locator(".project-nav").getByRole("button", { name: "写作与检查" }).click();
  await expect(page.locator(".workspace-page")).toBeVisible();
}

async function saveMarker(page: Page, marker: string) {
  // The engine splits by Chinese sentence punctuation and sends only each
  // batch's claims to the stub. Put the marker in one sourced claim so the
  // entire run exercises the intended terminal state and one 144/52 call.
  const body = `${marker} 温岚仍握着黄铜罗盘；与此同时，黄铜罗盘也在苏岑的外套内袋。`;
  await setDraftBody(page, body);
  await page.getByRole("button", { name: "保存草稿" }).click();
  await expect(page.locator(".workspace-save-summary strong")).toHaveText("已保存");
  await expect.poll(() => readDraftBody(page)).toBe(body);
}

async function run(page: Page) {
  return startLifecycleRun(page);
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
  await registerAccount(page, { prefix: `${accountPrefix}pair` });
  await importMarkdown(page, "stage9-mist-harbor.md", "阶段十二增量双 Run");
  await page.getByRole("button", { name: "初始化事实库" }).click();
  await page.getByRole("button", { name: "审核候选与原文依据" }).click();
  const initialization = page.getByRole("form", { name: "事实库初始化审核" });
  await initialization
    .locator("article.memory-init-candidate")
    .filter({ hasText: "核心候选（必须决定）" })
    .getByLabel("接受（写入第 1 版事实库）")
    .check();
  const initializationCommitted = page.waitForResponse(
    (response) =>
      /\/memory\/initializations\/[^/]+\/commit$/.test(
        new URL(response.url()).pathname,
      ) && response.request().method() === "POST",
  );
  await initialization
    .getByRole("button", { name: "确认核心审核并建立第 1 版事实库" })
    .click();
  expect((await initializationCommitted).status()).toBe(200);
  await expect(
    initialization.getByText("已建立部分事实库", { exact: true }),
  ).toBeVisible();
  const projectId = new URL(page.url()).pathname.split("/")[2];
  await page.goto(`/projects/${projectId}/sources`);
  await page
    .getByLabel("章节正文")
    .fill(`# 增量章节\n${marker} 林默将银钥匙交给守塔人。`);
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
    await visitorAndOpen(page);
    await saveMarker(page, "STAGE12_SUCCESS");
    const runId = await run(page);
    await expect(lifecycle(page)).toContainText("检查完成", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("输入 144 / 输出 52");
    await expect(lifecycle(page)).toContainText("实际费用 ¥0.0042");
    await expect(lifecycle(page).getByRole("button", { name: "取消检查" })).toHaveCount(0);
    await page.reload();
    await bindRun(lifecycle(page), runId);
    await expect(lifecycle(page)).toContainText("检查完成");
    await expect(lifecycle(page)).toContainText("browser-e2e-test-provider");
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("navigation", { name: "手机浏览内容" }).getByRole("button", { name: "资料", exact: true }).click();
    await expect(lifecycle(page)).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.getBoundingClientRect().width)).toBe(true);
    await expectProviderIsolation(page);
  });

  test("running cancel restores after refresh and discards the late success", async ({ page }) => {
    await page.request.get("/api/test/stage12/reset");
    await visitorAndOpen(page);
    await saveMarker(page, "STAGE12_BLOCK");
    const runId = await run(page);
    await expect.poll(async () => (await providerStats(page)).blocked).toBe(true);
    await expect(lifecycle(page).getByRole("button", { name: "取消检查" })).toBeVisible();
    await expect(lifecycle(page).getByRole("button", { name: "重新检查" })).toHaveCount(0);
    await page.reload();
    await bindRun(lifecycle(page), runId);
    await expect(lifecycle(page).getByRole("button", { name: "取消检查" })).toBeVisible();
    await lifecycle(page).getByRole("button", { name: "取消检查" }).click();
    await expect(lifecycle(page)).toContainText("正在安全取消");
    await page.request.get("/api/test/stage12/release");
    await expect(lifecycle(page)).toContainText("已取消", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("未写入部分结果");
    await expect(page.locator(".issue-row")).toHaveCount(0);
    const cancelled = await readLifecycleRun(page, runId);
    expect(cancelled.status).toBe("cancelled");
    expect(cancelled).not.toHaveProperty("issues");
    await expectProviderIsolation(page);
  });

  test("timeout is terminal, honest, retryable, and shows no partial Issues", async ({ page }) => {
    await visitorAndOpen(page);
    await saveMarker(page, "STAGE12_TIMEOUT");
    const runId = await run(page);
    await expect(lifecycle(page)).toContainText("检查超时", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("模型响应超时");
    await expect(lifecycle(page).getByRole("button", { name: "重新检查" })).toBeVisible();
    await expect(lifecycle(page).getByRole("button", { name: "取消检查" })).toHaveCount(0);
    await expect(page.locator(".issue-row")).toHaveCount(0);
    const timedOut = await readLifecycleRun(page, runId);
    expect(timedOut.status).toBe("timed_out");
    expect(timedOut).not.toHaveProperty("issues");
    await expectProviderIsolation(page);
  });

  test("failed Run retries as attempt 2 while the original lineage remains immutable", async ({ page }) => {
    await visitorAndOpen(page);
    await saveMarker(page, "STAGE12_FAIL_ONCE");
    const originalRun = await run(page);
    await expect(lifecycle(page)).toContainText("检查失败", { timeout: 15_000 });
    const original = await readLifecycleRun(page, originalRun);
    expect(original).toMatchObject({ status: "failed", attempt_number: 1, root_run_id: originalRun });
    const retried = page.waitForResponse((response) => response.request().method() === "POST" &&
      new URL(response.url()).pathname.endsWith(`/checks/${originalRun}/retry`));
    await lifecycle(page).getByRole("button", { name: "重新检查" }).click();
    const retryResponse = await retried;
    expect(retryResponse.status()).toBe(202);
    const retryId = (await retryResponse.json()).data.run.run_id as string;
    expect(retryId).not.toBe(originalRun);
    await bindRun(lifecycle(page), retryId);
    await expect(lifecycle(page)).toContainText("第 2 次尝试", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("检查完成", { timeout: 15_000 });
    await openRunDetails(lifecycle(page));
    await expect(lifecycle(page)).toContainText(`根运行 ${originalRun}`);
    await page.reload();
    await bindRun(lifecycle(page), retryId);
    await expect(lifecycle(page)).toContainText("第 2 次尝试");
    await expect(lifecycle(page)).toContainText("检查完成");
    expect(await readLifecycleRun(page, originalRun)).toEqual(original);
    await expectProviderIsolation(page);
  });

  test("non-retryable failed Run stays terminal and never offers Retry", async ({ page }) => {
    await page.request.get("/api/test/stage12/reset");
    await visitorAndOpen(page);
    await saveMarker(page, "STAGE12_BLOCK");
    const runId = await run(page);
    await expect.poll(async () => (await providerStats(page)).blocked).toBe(true);
    const projectId = new URL(page.url()).pathname.split("/")[2];
    expect(runId).toBeTruthy();
    const forced = await page.request.post(
      `/api/test/stage12/projects/${projectId}/runs/${runId}/fail-nonretryable`,
    );
    expect(forced.status()).toBe(200);
    expect((await forced.json()).changed).toBe(true);
    await page.request.get("/api/test/stage12/release");
    await expect(lifecycle(page)).toContainText("检查失败", { timeout: 15_000 });
    await expect(lifecycle(page)).toContainText("模型返回的结果未通过结构校验");
    await expect(lifecycle(page).getByRole("button", { name: "重新检查" })).toHaveCount(0);
    await expect(page.locator(".issue-row")).toHaveCount(0);
    const failed = await readLifecycleRun(page, runId);
    expect(failed).toMatchObject({ status: "failed", retryable: false });
    expect(failed).not.toHaveProperty("issues");
    await expectProviderIsolation(page);
  });

  test("Retry idempotency conflicts and project/account isolation fail closed", async ({ page, browser }) => {
    await visitorAndOpen(page);
    await saveMarker(page, "STAGE12_TIMEOUT");
    const runId = await run(page);
    await expect(lifecycle(page)).toContainText("检查超时", { timeout: 15_000 });
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
      .filter({ hasText: "资料版本第 2 版" })
      .getByRole("button", { name: "运行增量检查" })
      .click();
    const startedResponse = await started;
    expect(startedResponse.status()).toBe(202);
    const pair = (await startedResponse.json()).data as {
      continuity_run_id: string;
      memory_delta_run_id: string;
    };
    expect(pair.continuity_run_id).not.toBe(pair.memory_delta_run_id);
    const continuity = page.getByLabel("连续性检查进度", { exact: true });
    const memoryDelta = page.getByLabel("事实变化检查进度", { exact: true });
    await bindRun(continuity, pair.continuity_run_id);
    await bindRun(memoryDelta, pair.memory_delta_run_id);
    await expect(continuity).toContainText("检查完成", { timeout: 15_000 });
    await expect(memoryDelta).toContainText("检查完成", { timeout: 15_000 });
    await expect(continuity).toContainText(pair.continuity_run_id);
    await expect(memoryDelta).toContainText(pair.memory_delta_run_id);
    await page.reload();
    await bindRun(continuity, pair.continuity_run_id);
    await bindRun(memoryDelta, pair.memory_delta_run_id);
    await expect(continuity).toContainText(pair.continuity_run_id);
    await expect(memoryDelta).toContainText(pair.memory_delta_run_id);
    await page.setViewportSize({ width: 390, height: 844 });
    await page.getByRole("navigation", { name: "手机浏览内容" }).getByRole("button", { name: "资料", exact: true }).click();
    await expect(continuity).toBeVisible();
    await expect(memoryDelta).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.getBoundingClientRect().width)).toBe(true);
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
      .filter({ hasText: "资料版本第 2 版" })
      .getByRole("button", { name: "运行增量检查" })
      .click();
    const startedResponse = await started;
    expect(startedResponse.status()).toBe(202);
    const pair = (await startedResponse.json()).data as { continuity_run_id: string; memory_delta_run_id: string };
    const continuity = page.getByLabel("连续性检查进度", { exact: true });
    const memoryDelta = page.getByLabel("事实变化检查进度", { exact: true });
    await bindRun(continuity, pair.continuity_run_id);
    await bindRun(memoryDelta, pair.memory_delta_run_id);
    await expect(continuity).toContainText("检查超时", { timeout: 15_000 });
    await expect(memoryDelta).toContainText("检查超时", { timeout: 15_000 });
    await expect(continuity).toContainText("这次没有保存任何结果");
    await expect(memoryDelta).toContainText("这次没有保存任何结果");
    await expect(page.locator(".issue-row")).toHaveCount(0);
    const continuityRun = await readLifecycleRun(page, pair.continuity_run_id);
    expect(continuityRun.status).toBe("timed_out");
    expect(continuityRun).not.toHaveProperty("issues");
    const memoryDeltaRun = await readLifecycleRun(page, pair.memory_delta_run_id);
    expect(memoryDeltaRun.status).toBe("timed_out");
    expect(memoryDeltaRun).not.toHaveProperty("issues");
    const delta = await page.evaluate(async (id) =>
      (await (await fetch(`/api/projects/${id}/memory/delta`)).json()).data,
      projectId,
    );
    expect(delta).toMatchObject({ status: "failed", error_code: "provider_timeout" });
    await expectProviderIsolation(page);
  });
});
