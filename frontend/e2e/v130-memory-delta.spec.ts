import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";

const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix) throw new Error("E2E_ACCOUNT_PREFIX is required");

const initialSource = `# 雾港初章

钟声响起后，所有船只必须停泊在雾港。E2E_FACT_LIFECYCLE

# 北堤钥匙

林默一直保管银钥匙。

# 清晨门扉

林默知道北堤门只在清晨开启。`;

async function postJson<T>(page: Page, path: string, data: unknown): Promise<T> {
  const response = await page.request.post(`/api${path}`, {
    data,
    headers: { "Idempotency-Key": randomUUID() },
  });
  const raw = await response.text();
  const body = raw.startsWith("{") ? JSON.parse(raw) : { raw };
  expect(response.ok(), `${path}: ${response.status()} ${JSON.stringify(body)}`).toBeTruthy();
  return body.data as T;
}

async function prepare(page: Page) {
  await page.setViewportSize({ width: 1440, height: 900 });
  const account = `${accountPrefix}fact${Date.now()}${Math.floor(Math.random() * 1000)}`;
  await postJson(page, "/auth/register", {
    account_name: account,
    display_name: "事实审核作者",
    password: `safe-${randomUUID()}`,
  });
  const previewResponse = await page.request.post("/api/imports/preview", {
    multipart: {
      file: {
        name: "fact-lifecycle.md",
        mimeType: "text/markdown",
        buffer: Buffer.from(initialSource),
      },
    },
    headers: { "Idempotency-Key": randomUUID() },
  });
  const previewBody = await previewResponse.json();
  expect(previewResponse.ok(), JSON.stringify(previewBody)).toBeTruthy();
  const preview = previewBody.data;
  const imported = await postJson<{ project: { id: string } }>(page, `/imports/${preview.import_id}/commit`, {
    confirm: true,
    title: "v1.3.0 事实生命周期",
    chapter_preview_ids: preview.detected.chapters.map((chapter: { preview_id: string }) => chapter.preview_id),
  });
  const projectId = imported.project.id;
  const initialized = await postJson<{ initialization: { id: string; candidates: Array<{ id: string; subject: string }> } }>(page, `/projects/${projectId}/memory/initializations`, { source_revision: 1 });
  const acceptedSubjects = new Set(["林默", "废弃船票"]);
  for (const candidate of initialized.initialization.candidates.filter((item) => acceptedSubjects.has(item.subject))) {
    await postJson(page, `/projects/${projectId}/memory/initializations/${initialized.initialization.id}/candidates/${candidate.id}/decision`, { decision: "accepted" });
  }
  await postJson(page, `/projects/${projectId}/memory/initializations/${initialized.initialization.id}/commit`, { confirm: true });
  const sourcePreview = await postJson<{ source_change_set: { id: string; content_sha256: string } }>(page, `/projects/${projectId}/source-change-sets/preview`, {
    mode: "append",
    input_method: "paste",
    base_source_revision: 1,
    content: "# 新修订\n林默将银钥匙交给守塔人，废弃船票不再有效，北堤门开启时间待确认。",
  });
  await postJson(page, `/projects/${projectId}/source-change-sets/${sourcePreview.source_change_set.id}/commit`, {
    confirm: true,
    content_sha256: sourcePreview.source_change_set.content_sha256,
  });
  await postJson(page, `/projects/${projectId}/incremental-reviews`, { source_revision: 2 });
  await expect.poll(async () => {
    const response = await page.request.get(`/api/projects/${projectId}/memory/delta`);
    return (await response.json()).data.status;
  }, { timeout: 15_000 }).toBe("in_review");
  await page.goto(`/projects/${projectId}/memory`);
  return { projectId, review: page.getByRole("form", { name: "Memory Delta 审核" }) };
}

test("desktop reviews new changed and invalidated facts and preserves choices across commit failure", async ({ page }) => {
  const { review } = await prepare(page);
  await expect(review.locator("article.memory-delta-candidate")).toHaveCount(3);
  const changed = review.locator("article.memory-delta-candidate").filter({ hasText: "变更事实" });
  const invalidated = review.locator("article.memory-delta-candidate").filter({ hasText: "失效事实" });
  const added = review.locator("article.memory-delta-candidate").filter({ hasText: "新增事实" });
  await expect(changed).toContainText("当前已确认事实");
  await expect(changed).toContainText("AI 提议");
  await expect(invalidated).toContainText("不生成相反事实");
  await expect(invalidated.getByRole("radio", { name: "编辑后接受" })).toHaveCount(0);
  await changed.getByRole("button", { name: "查看原事实来源" }).click();
  await expect(page.getByRole("dialog", { name: /林默 的章节来源/ })).toBeVisible();
  await page.keyboard.press("Escape");
  await changed.getByRole("radio", { name: "编辑后接受" }).check();
  await changed.getByLabel("事实内容").fill("编辑后抵达北堤");
  await invalidated.getByRole("radio", { name: "接受", exact: true }).check();
  await added.getByRole("radio", { name: "拒绝", exact: true }).check();
  let failedOnce = false;
  await page.route(/\/api\/projects\/[^/]+\/memory\/deltas\/[^/]+\/commit$/, async (route) => {
    if (!failedOnce) {
      failedOnce = true;
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "memory_delta_stale", message: "injected browser retry" } }) });
    } else await route.continue();
  });
  await review.getByRole("button", { name: "确认提交并更新 Story Memory" }).click();
  await expect(page.locator(".feedback.error")).toContainText("基线已变化");
  await expect(changed.getByRole("radio", { name: "编辑后接受" })).toBeChecked();
  await expect(changed.getByLabel("事实内容")).toHaveValue("编辑后抵达北堤");
  await expect(invalidated.getByRole("radio", { name: "接受", exact: true })).toBeChecked();
  await page.unroute(/\/api\/projects\/[^/]+\/memory\/deltas\/[^/]+\/commit$/);
  await review.getByRole("button", { name: "确认提交并更新 Story Memory" }).click();
  const audit = page.getByLabel("增量来源覆盖审计");
  await expect(audit).toContainText("ChangeSet");
  await expect(audit).toContainText("Memory V1 → V2");
  await expect(page.getByText("编辑后抵达北堤", { exact: true })).toBeVisible();
  await expect(page.getByRole("cell", { name: "已失效", exact: true })).toBeVisible();
  const stats = await (await page.request.get("/api/test/stage12/stats")).json();
  expect(stats).toMatchObject({ provider_mode: "injected_stub", external_provider_http_enabled: false, provider_http_calls: 0 });
});

test("390px remains browse-only without horizontal overflow", async ({ page }) => {
  const { review } = await prepare(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(review).toBeVisible();
  for (const input of await review.locator("input, select, textarea").all()) await expect(input).toBeDisabled();
  await expect(review.getByRole("button", { name: "确认提交并更新 Story Memory" })).toBeDisabled();
  await expect(review.getByRole("button", { name: "查看新修订来源" }).first()).toBeEnabled();
  const overflow = await page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(overflow).toBeLessThanOrEqual(1);
  const stats = await (await page.request.get("/api/test/stage12/stats")).json();
  expect(stats.provider_http_calls).toBe(0);
});
