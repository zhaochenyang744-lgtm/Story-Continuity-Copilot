import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin = process.env.E2E_BACKEND_ORIGIN;
if (!backendOrigin) throw new Error("E2E_BACKEND_ORIGIN is required");
const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix) throw new Error("E2E_ACCOUNT_PREFIX is required");

type DraftSnapshot = {
  id: string;
  revision: number;
  title: string;
  body: string;
};

async function register(page: Page) {
  const account = `${accountPrefix}immersive${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("沉浸写作验收作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
}

async function createProject(page: Page) {
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "新建作品", exact: true }).click();
  await page.getByLabel("作品名称", { exact: true }).fill("潮汐手稿");
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const projectId = page.url().match(/\/projects\/([^/]+)\//)?.[1];
  if (!projectId) throw new Error("project id missing");
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page.locator("#draft-body")).toBeVisible();
  return projectId;
}

async function screenshot(page: Page, name: string) {
  if (!process.env.E2E_OUTPUT_DIR) return;
  await page.waitForTimeout(180);
  await page.screenshot({ path: path.join(process.env.E2E_OUTPUT_DIR, name), fullPage: false });
}

async function expectNoHorizontalOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

test("v1.3.0 immersive writing shares draft state, saves explicitly, and stays desktop-only", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const statsBefore = (await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json()) as {
    provider_calls: number;
    provider_http_calls: number;
  };
  await register(page);
  const projectId = await createProject(page);

  const openingBody = "潮声落下。\n林默把未寄出的信压在航海图下。";
  await page.locator("#draft-body").fill(openingBody);
  const enter = page.getByRole("button", { name: "进入沉浸写作", exact: true });
  await enter.click();

  const immersive = page.getByRole("dialog", { name: "沉浸写作" });
  const immersiveBody = page.locator("#immersive-draft-body");
  await expect(immersive).toBeVisible();
  await expect(immersiveBody).toHaveValue(openingBody);
  await expect(page.getByRole("button", { name: "退出沉浸写作并返回写作与检查", exact: true })).toBeFocused();

  const displaySettings = immersive.getByRole("combobox");
  await expect(displaySettings).toHaveCount(3);
  await displaySettings.nth(0).selectOption("large");
  await displaySettings.nth(1).selectOption("airy");
  await displaySettings.nth(2).selectOption("narrow");
  await expect(immersive).toHaveAttribute("data-font-size", "large");
  await expect(immersive).toHaveAttribute("data-line-height", "airy");
  await expect(immersive).toHaveAttribute("data-column-width", "narrow");
  await expect(immersiveBody).toHaveCSS("font-size", "21px");
  expect(parseFloat(await immersiveBody.evaluate((element) => getComputedStyle(element).lineHeight))).toBeGreaterThan(42);
  const headerActions = immersive.locator(".immersive-header-actions");
  await headerActions.getByRole("button", { name: "收起连续性问题辅助栏", exact: true }).click();
  await expect(immersive).toHaveAttribute("data-issues", "closed");
  await expect(immersive.getByLabel("连续性问题辅助栏", { exact: true })).toBeHidden();
  await headerActions.getByRole("button", { name: "展开连续性问题辅助栏", exact: true }).click();
  await expect(immersive).toHaveAttribute("data-issues", "open");
  await expect(immersive.getByLabel("连续性问题辅助栏", { exact: true })).toBeVisible();

  const editedBody = `${openingBody}\n她决定在第三次雾钟前离港。`;
  await immersiveBody.fill(editedBody);
  await expect(immersive.getByLabel("实时写作统计", { exact: true })).toContainText("字符");
  await page.keyboard.press("Escape");
  await expect(immersive).toHaveCount(0);
  await expect(page.locator("#draft-body")).toHaveValue(editedBody);
  await expect(enter).toBeFocused();

  await enter.click();
  await expect(immersive).toHaveAttribute("data-font-size", "large");
  await expect(immersive).toHaveAttribute("data-line-height", "airy");
  await expect(immersive).toHaveAttribute("data-column-width", "narrow");
  await expect(immersiveBody).toHaveValue(editedBody);

  const successfulSave = page.waitForResponse(
    (response) => response.request().method() === "PATCH" && response.url().includes(`/api/projects/${projectId}/drafts/`),
  );
  await page.getByRole("button", { name: "显式保存草稿", exact: true }).click();
  expect((await successfulSave).status()).toBe(200);
  await expect(immersive.getByRole("status")).toContainText("已保存");
  await screenshot(page, "immersive-writing-01-desktop.png");

  const projectResponse = await page.request.get(`${backendOrigin}/api/projects/${projectId}`);
  expect(projectResponse.ok(), await projectResponse.text()).toBe(true);
  const project = (await projectResponse.json()) as { data: { current_draft: DraftSnapshot } };
  const current = project.data.current_draft;
  const externalWrite = await page.request.patch(`${backendOrigin}/api/projects/${projectId}/drafts/${current.id}`, {
    headers: { "Idempotency-Key": randomUUID() },
    data: {
      base_revision: current.revision,
      title: current.title,
      body: `${current.body}\n外部并发版本。`,
    },
  });
  expect(externalWrite.status(), await externalWrite.text()).toBe(200);

  const localConflictBody = `${editedBody}\n这段本地修改必须在冲突后继续保留。`;
  await immersiveBody.fill(localConflictBody);
  const failedSave = page.waitForResponse(
    (response) => response.request().method() === "PATCH" && response.url().includes(`/api/projects/${projectId}/drafts/`) && response.status() === 409,
  );
  await page.getByRole("button", { name: "显式保存草稿", exact: true }).click();
  expect((await failedSave).status()).toBe(409);
  await expect(immersiveBody).toHaveValue(localConflictBody);
  await expect(immersive.getByRole("status")).toContainText("保存失败");
  await expect(immersive.getByRole("status")).toContainText("草稿已被其他编辑更新");
  await screenshot(page, "immersive-writing-02-conflict-preserved.png");

  for (const viewport of [
    { width: 1366, height: 768 },
    { width: 1440, height: 900 },
    { width: 1708, height: 960 },
    { width: 1920, height: 1080 },
    { width: 1024, height: 768 },
  ]) {
    await page.setViewportSize(viewport);
    const geometry = await immersive.evaluate((element) => {
      const overlay = element.getBoundingClientRect();
      const writing = element.querySelector(".immersive-writing-column")?.getBoundingClientRect();
      const footer = element.querySelector(".immersive-footer")?.getBoundingClientRect();
      if (!writing || !footer) throw new Error("immersive writing geometry is not measurable");
      return {
        overlayWidth: overlay.width,
        overlayHeight: overlay.height,
        writingWidth: writing.width,
        footerBottomDelta: footer.bottom - overlay.bottom,
      };
    });
    expect(Math.abs(geometry.overlayWidth - viewport.width)).toBeLessThanOrEqual(1);
    expect(Math.abs(geometry.overlayHeight - viewport.height)).toBeLessThanOrEqual(1);
    expect(geometry.writingWidth).toBeGreaterThan(430);
    expect(geometry.writingWidth).toBeLessThanOrEqual(681);
    expect(geometry.footerBottomDelta).toBeLessThanOrEqual(1);
    await expectNoHorizontalOverflow(page);
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(immersive).toHaveCount(0);
  await expect(page.getByRole("button", { name: "进入沉浸写作", exact: true })).toHaveCount(0);
  await expect(page.locator("#draft-body")).toHaveCount(0);
  await expect(page.locator(".draft-read")).toContainText("这段本地修改必须在冲突后继续保留");
  await expect(page.getByLabel("章节标题", { exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存草稿", exact: true })).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  await screenshot(page, "immersive-writing-03-mobile-read-only.png");

  await page.setViewportSize({ width: 1366, height: 768 });
  await expect(immersive).toHaveCount(0);
  await expect(enter).toBeVisible();
  await expect(page.locator("#draft-body")).toHaveValue(localConflictBody);
  await enter.click();
  await expect(immersive).toBeVisible();
  await expect(immersiveBody).toHaveValue(localConflictBody);
  await page.getByRole("button", { name: "退出沉浸写作并返回写作与检查", exact: true }).click();
  await expect(page.locator("#draft-body")).toHaveValue(localConflictBody);

  const statsAfter = (await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json()) as {
    provider_calls: number;
    provider_http_calls: number;
  };
  expect(statsAfter.provider_calls).toBe(statsBefore.provider_calls);
  expect(statsAfter.provider_http_calls).toBe(statsBefore.provider_http_calls);
  expect(statsAfter.provider_http_calls).toBe(0);
});

test("save-and-switch navigates only after a successful draft save", async ({ page }) => {
  await page.setViewportSize({ width: 1366, height: 768 });
  await register(page);
  const projectId = await createProject(page);
  const workspaceUrl = page.url();
  const title = page.getByLabel("章节标题", { exact: true });
  const body = page.locator("#draft-body");

  const transientTitle = "潮汐手稿 · 本地待保存";
  const transientBody = "这段本地正文在临时保存失败后必须保留。";
  await title.fill(transientTitle);
  await body.fill(transientBody);
  await page.route(
    `**/api/projects/${projectId}/drafts/**`,
    async (route) => {
      await route.fulfill({
        status: 503,
        contentType: "application/json",
        body: JSON.stringify({
          error: { code: "temporary_save_failure", message: "temporary save failure", retryable: true },
          request_id: randomUUID(),
        }),
      });
    },
    { times: 1 },
  );

  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  let switchDialog = page.getByRole("dialog", { name: "未保存草稿" });
  await expect(switchDialog).toBeVisible();
  await switchDialog.getByRole("button", { name: "保存并切换", exact: true }).click();
  await expect(page).toHaveURL(workspaceUrl);
  await expect(switchDialog).toBeVisible();
  await expect(title).toHaveValue(transientTitle);
  await expect(body).toHaveValue(transientBody);
  await expect(switchDialog.getByRole("alert")).toContainText("保存失败，尚未切换");
  await expect(switchDialog.getByRole("alert")).toContainText("请求未完成");
  await expect(switchDialog.getByRole("button", { name: "保存并切换", exact: true })).toBeEnabled();

  let releaseDelayedSave!: () => void;
  const delayedSaveGate = new Promise<void>((resolve) => {
    releaseDelayedSave = resolve;
  });
  await page.route(
    `**/api/projects/${projectId}/drafts/**`,
    async (route) => {
      await delayedSaveGate;
      await route.continue();
    },
    { times: 1 },
  );
  const successfulRetry = page.waitForResponse(
    (response) => response.request().method() === "PATCH" && response.url().includes(`/api/projects/${projectId}/drafts/`) && response.status() === 200,
  );
  const delayedRequest = page.waitForRequest(
    (request) => request.method() === "PATCH" && request.url().includes(`/api/projects/${projectId}/drafts/`),
  );
  await switchDialog.getByRole("button", { name: "保存并切换", exact: true }).click();
  await delayedRequest;
  await expect(switchDialog.getByRole("button", { name: "保存并切换", exact: true })).toBeDisabled();
  await expect(switchDialog.getByRole("button", { name: "放弃修改", exact: true })).toBeDisabled();
  await expect(switchDialog.getByRole("button", { name: "取消", exact: true })).toBeDisabled();
  await expect(switchDialog.locator("button.close")).toBeDisabled();
  await page.keyboard.press("Escape");
  await expect(switchDialog).toBeVisible();
  await expect(page).toHaveURL(workspaceUrl);
  releaseDelayedSave();
  await successfulRetry;
  await expect(page).toHaveURL(/\/projects$/);
  await expect(switchDialog).toHaveCount(0);

  await page.goto(workspaceUrl);
  await expect(body).toHaveValue(transientBody);
  const conflictTitle = "潮汐手稿 · 冲突仍保留";
  const conflictBody = `${transientBody}\n另一窗口写入后，这段本地修改仍不能丢失。`;
  await title.fill(conflictTitle);
  await body.fill(conflictBody);

  const projectResponse = await page.request.get(`${backendOrigin}/api/projects/${projectId}`);
  expect(projectResponse.ok(), await projectResponse.text()).toBe(true);
  const project = (await projectResponse.json()) as { data: { current_draft: DraftSnapshot } };
  const current = project.data.current_draft;
  const externalWrite = await page.request.patch(`${backendOrigin}/api/projects/${projectId}/drafts/${current.id}`, {
    headers: { "Idempotency-Key": randomUUID() },
    data: {
      base_revision: current.revision,
      title: current.title,
      body: `${current.body}\n外部并发版本。`,
    },
  });
  expect(externalWrite.status(), await externalWrite.text()).toBe(200);

  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  switchDialog = page.getByRole("dialog", { name: "未保存草稿" });
  const conflictResponse = page.waitForResponse(
    (response) => response.request().method() === "PATCH" && response.url().includes(`/api/projects/${projectId}/drafts/`) && response.status() === 409,
  );
  await switchDialog.getByRole("button", { name: "保存并切换", exact: true }).click();
  await conflictResponse;
  await expect(page).toHaveURL(workspaceUrl);
  await expect(switchDialog).toBeVisible();
  await expect(title).toHaveValue(conflictTitle);
  await expect(body).toHaveValue(conflictBody);
  await expect(switchDialog.getByRole("alert")).toContainText("保存失败，尚未切换");
  await expect(switchDialog.getByRole("alert")).toContainText("草稿已被其他编辑更新");
  await expect(switchDialog.getByRole("button", { name: "保存并切换", exact: true })).toBeEnabled();

  await switchDialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(switchDialog).toHaveCount(0);
  await expect(page).toHaveURL(workspaceUrl);
  await expect(title).toHaveValue(conflictTitle);
  await expect(body).toHaveValue(conflictBody);
});
