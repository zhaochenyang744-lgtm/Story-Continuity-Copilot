import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const fixture = path.resolve(
  process.cwd(),
  "frontend/e2e/fixtures/stage9-mist-harbor.md",
);

async function api(page: Page, url: string) {
  return page.evaluate(async (path) => (await fetch(path)).json(), url);
}

async function initializedProject(page: Page) {
  const account = `stage11l${Date.now()}${Math.floor(Math.random() * 1000)}`;
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("11L 作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator("#auth-password").fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "导入作品", exact: true }).click();
  await page
    .locator('input[name="file"]')
    .setInputFiles({
      name: "base.md",
      mimeType: "text/markdown",
      buffer: await readFile(fixture),
    });
  await page.getByRole("button", { name: "解析并预览章节" }).click();
  await page.getByRole("button", { name: "继续确认" }).click();
  await page.getByLabel("作品名").fill("11L 两轮作品");
  const importCommitted = page.waitForResponse(
    (response) =>
      /\/imports\/[^/]+\/commit$/.test(new URL(response.url()).pathname) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "确认导入" }).click();
  const importResult = await importCommitted;
  expect(importResult.status()).toBe(201);
  const id = (await importResult.json()).data.project.id as string;
  await page.waitForURL(new RegExp(`/projects/${id}/overview$`));
  const startInitialization = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname.endsWith("/memory/initializations") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "初始化 Story Memory" }).click();
  expect((await startInitialization).status()).toBe(201);
  await page.getByRole("button", { name: "审核候选与 Evidence" }).click();
  const initialReview = await page.evaluate(async (projectId) => {
    const view = await (
      await fetch(`/api/projects/${projectId}/memory/initialization`)
    ).json();
    if (!view.data?.id) throw new Error(JSON.stringify(view));
    const initialization = view.data;
    const decisionStatuses: number[] = [];
    for (const candidate of initialization.candidates.filter(
      (item: { review_priority: string }) => item.review_priority === "core",
    )) {
      const response = await fetch(
        `/api/projects/${projectId}/memory/initializations/${initialization.id}/candidates/${candidate.id}/decision`,
        {
          method: "POST",
          headers: {
            "Content-Type": "application/json",
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({ decision: "accepted" }),
        },
      );
      decisionStatuses.push(response.status);
    }
    const committed = await fetch(
      `/api/projects/${projectId}/memory/initializations/${initialization.id}/commit`,
      {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
          "Idempotency-Key": crypto.randomUUID(),
        },
        body: JSON.stringify({ confirm: true }),
      },
    );
    return {
      decisionStatuses,
      commitStatus: committed.status,
      data: (await committed.json()).data,
    };
  }, id);
  expect(initialReview.decisionStatuses.length).toBeGreaterThan(0);
  expect(initialReview.decisionStatuses).toEqual(
    initialReview.decisionStatuses.map(() => 200),
  );
  expect(initialReview.commitStatus).toBe(200);
  expect(initialReview.data).toMatchObject({
    memory_version: 1,
    coverage: {
      status: "ready_partial",
      counts: { supporting_pending: 2, pending_canon_count: 0 },
    },
  });
  return { id, account, password };
}

async function append(page: Page, id: string, revision: number, body: string) {
  await page.goto(`/projects/${id}/sources`);
  await page.getByLabel("章节正文").fill(body);
  const preview = page.waitForResponse(
    (response) =>
      response.url().includes("source-change-sets/preview") &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "预览追加" }).click();
  const previewResponse = await preview;
  expect(previewResponse.status()).toBe(201);
  const previewPayload = await previewResponse.json();
  expect(previewPayload.data.source_change_set).toMatchObject({
    project_id: id,
    base_source_revision: revision,
    target_source_revision: revision + 1,
    status: "previewed",
  });
  const commit = page.waitForResponse(
    (response) =>
      /source-change-sets\/.+\/commit/.test(response.url()) &&
      response.request().method() === "POST",
  );
  await page.getByRole("button", { name: "确认追加并创建下一章草稿" }).click();
  const committed = await commit;
  expect(committed.status()).toBe(200);
  expect((await committed.json()).data.source_change_set).toMatchObject({
    project_id: id,
    target_source_revision: revision + 1,
    status: "committed",
  });
}

async function start(page: Page, id: string, revision: number) {
  await page.goto(`/projects/${id}/workspace`);
  const started = page.waitForResponse(
    (response) =>
      response.url().endsWith("/incremental-reviews") &&
      response.request().method() === "POST",
  );
  await page
    .locator(".warning")
    .filter({ hasText: `资料版本第 ${revision} 版` })
    .getByRole("button", { name: "运行增量检查" })
    .click();
  const response = await started;
  expect(response.status()).toBe(202);
  const data = (await response.json()).data;
  expect(data).toMatchObject({
    delta: { source_revision: revision },
    continuity_run_id: expect.any(String),
    memory_delta_run_id: expect.any(String),
  });
  expect(data.continuity_run_id).not.toBe(data.memory_delta_run_id);
  for (const runId of [data.continuity_run_id, data.memory_delta_run_id])
    await expect
      .poll(
        async () =>
          (await api(page, `/api/projects/${id}/checks/${runId}`)).data.status,
        { timeout: 10_000 },
      )
      .toBe("completed");
  await expect
    .poll(
      async () =>
        (await api(page, `/api/projects/${id}/memory/delta`)).data.status,
      { timeout: 10_000 },
    )
    .toBe("in_review");
  return data;
}

async function submitCore(page: Page, edit = false) {
  await page
    .getByRole("button", { name: "打开更新审核与证据" })
    .click();
  const review = page.getByRole("form", { name: "Memory Delta 审核" });
  const cores = review
    .locator("article.memory-delta-candidate")
    .filter({ hasText: "核心变化 · 必须决定" });
  await expect(cores.first()).toBeVisible();
  const coreCount = await cores.count();
  expect(coreCount).toBeGreaterThan(0);
  for (let index = 0; index < coreCount; index += 1) {
    const core = cores.nth(index);
    if (edit && index === 0) {
      await core.getByRole("radio", { name: "编辑后接受" }).check();
      await core.getByLabel("事实内容").fill("11L 编辑后的受控事实");
    } else await core.getByRole("radio", { name: "接受", exact: true }).check();
  }
  const commit = page.waitForResponse(
    (response) =>
      /\/memory\/deltas\/[^/]+\/commit$/.test(
        new URL(response.url()).pathname,
      ) && response.request().method() === "POST",
  );
  await review.getByRole("button", { name: "确认提交并更新 Story Memory" }).click();
  expect((await commit).status()).toBe(200);
}

test("1440 two real product rounds preserve lineage through refresh, re-login, and project switching", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  const pageErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() !== "error") return;
    if (
      message.text() ===
      "Failed to load resource: the server responded with a status of 401 (Unauthorized)"
    )
      return;
    consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => pageErrors.push(error.message));
  await page.setViewportSize({ width: 1440, height: 900 });
  const author = await initializedProject(page);
  await append(
    page,
    author.id,
    1,
    "# 追加章节\n第一轮：林默将银钥匙交给守塔人。",
  );
  const first = await start(page, author.id, 2);
  await expect(page.getByRole("heading", { name: /连续性问题/ })).toBeVisible();
  await expect(
    page.getByRole("region", { name: "Memory 更新建议" }),
  ).toBeVisible();
  for (const runId of [first.continuity_run_id, first.memory_delta_run_id]) {
    const run = await api(
      page,
      `/api/projects/${author.id}/checks/${runId}?include=issues,evidence,metrics`,
    );
    expect(run.data).toMatchObject({
      source_revision: 2,
      source_change_set_id: expect.any(String),
      source_span_ids: expect.any(Array),
      lineage_status: "incremental_source_revision",
      is_stale: false,
    });
  }
  await page.locator(".issue-list button").first().click();
  const drawer = page.getByRole("dialog", { name: "问题证据" });
  await expect(drawer).toBeVisible();
  await expect(drawer.getByText("证据", { exact: true })).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  await page
    .getByRole("button", { name: "打开更新审核与证据" })
    .click();
  const firstReview = page.getByRole("form", { name: "Memory Delta 审核" });
  await firstReview
    .getByRole("button", { name: "确认提交并更新 Story Memory" })
    .click();
  await expect(page.locator(".feedback.error")).toContainText("请求未完成");
  const firstCores = firstReview
    .locator("article.memory-delta-candidate")
    .filter({ hasText: "核心变化 · 必须决定" });
  await expect(firstCores.first()).toBeVisible();
  const firstCoreCount = await firstCores.count();
  expect(firstCoreCount).toBeGreaterThan(0);
  for (let index = 0; index < firstCoreCount; index += 1)
    await firstCores
      .nth(index)
      .getByRole("radio", { name: "接受", exact: true })
      .check();
  const firstCommit = page.waitForResponse((response) =>
    /\/memory\/deltas\/[^/]+\/commit$/.test(new URL(response.url()).pathname),
  );
  await firstReview
    .getByRole("button", { name: "确认提交并更新 Story Memory" })
    .click();
  expect((await firstCommit).status()).toBe(200);
  const afterFirst = await api(page, `/api/projects/${author.id}/memory`);
  expect(afterFirst.data.memory_version).toBe(2);
  await page.reload();
  expect(
    (await api(page, `/api/projects/${author.id}/memory`)).data.memory_version,
  ).toBe(2);
  const other = await page.evaluate(
    async () =>
      (
        await (
          await fetch("/api/projects", {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "Idempotency-Key": crypto.randomUUID(),
            },
            body: JSON.stringify({ title: "11L 隔离项目" }),
          })
        ).json()
      ).data.project.id,
  );
  const otherBefore = await api(page, `/api/projects/${other}`);
  await page.goto(`/projects/${other}`);
  expect((await api(page, `/api/projects/${other}`)).data).toEqual(
    otherBefore.data,
  );
  await page.goto(`/projects/${author.id}/memory`);
  await page.getByRole("button", { name: "用户菜单" }).click();
  const loggedOut = page.waitForResponse(
    (response) =>
      new URL(response.url()).pathname === "/api/auth/logout" &&
      response.request().method() === "POST",
  );
  await page.getByRole("menuitem", { name: "退出登录" }).click();
  expect((await loggedOut).status()).toBe(204);
  await page.waitForURL(/\/login$/);
  await page.getByLabel("账号").fill(author.account);
  await page.locator("#auth-password").fill(author.password);
  await page.getByRole("button", { name: "登录" }).click();
  await expect
    .poll(
      async () =>
        (await api(page, "/api/auth/session")).data?.user?.account_name,
      { timeout: 10_000 },
    )
    .toBe(author.account);
  await page.goto(`/projects/${author.id}/workspace`);
  expect((await api(page, `/api/projects/${author.id}`)).data).toMatchObject({
    source_revision: 2,
    current_memory_version: 2,
  });
  await append(
    page,
    author.id,
    2,
    "# 再次追加\n第二轮：守塔人开始保管银钥匙。",
  );
  const second = await start(page, author.id, 3);
  await submitCore(page, true);
  const finalMemory = await api(page, `/api/projects/${author.id}/memory`);
  expect(finalMemory.data.memory_version).toBe(3);
  expect(
    finalMemory.data.records.map((record: { value: string }) => record.value),
  ).toContain("11L 编辑后的受控事实");
  const otherAfter = await api(page, `/api/projects/${other}`);
  expect(otherAfter.data).toEqual(otherBefore.data);
  expect(second.continuity_run_id).not.toBe(second.memory_delta_run_id);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});

test("1024 remains writable for a Delta decision and commit", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1024, height: 900 });
  const author = await initializedProject(page);
  await append(
    page,
    author.id,
    1,
    "# 追加章节\n第一轮：林默将银钥匙交给守塔人。",
  );
  await start(page, author.id, 2);
  await submitCore(page);
  expect(
    (await api(page, `/api/projects/${author.id}/memory`)).data.memory_version,
  ).toBe(2);
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});

test("390 is browse-only for the prepared incremental review", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const author = await initializedProject(page);
  await append(
    page,
    author.id,
    1,
    "# 追加章节\n第一轮：林默将银钥匙交给守塔人。",
  );
  await start(page, author.id, 2);
  await page
    .getByRole("button", { name: "打开更新审核与证据" })
    .click();
  await page.setViewportSize({ width: 390, height: 844 });
  const review = page.getByRole("form", { name: "Memory Delta 审核" });
  await expect(review).toBeVisible();
  for (const control of await review.locator("input,select,textarea").all())
    await expect(control).toBeDisabled();
  await expect(
    review.getByRole("button", { name: "确认提交并更新 Story Memory" }),
  ).toBeDisabled();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBeTruthy();
});
