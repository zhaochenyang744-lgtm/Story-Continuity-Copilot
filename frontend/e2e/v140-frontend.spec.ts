import { expect, test, type Page, type Route } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";
import fixture from "./fixtures/v140/development.json";

type JsonRecord = Record<string, unknown>;

async function register(page: Page, suffix: string) {
  const prefix = process.env.E2E_ACCOUNT_PREFIX ?? "v140";
  const account = `${prefix}${suffix}${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("v1.4 前端自测作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  return { account, password };
}

async function screenshot(page: Page, name: string, fullPage = true) {
  const output = process.env.E2E_OUTPUT_DIR;
  if (!output) return;
  await page.screenshot({ path: path.join(output, name), fullPage });
}

async function noOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
}

async function patchReviewFixture(route: Route) {
  const response = await route.fetch();
  if (!response.ok()) return route.fulfill({ response });
  const json = await response.json() as { data?: JsonRecord } & JsonRecord;
  const run = (json.data ?? json) as JsonRecord;
  const issues = run.issues as JsonRecord[] | undefined;
  if (!issues?.length) return route.fulfill({ response, json });
  issues.forEach((issue, index) => {
    const sample = fixture.cases[index % fixture.cases.length];
    issue.nature = sample.nature;
    issue.reasoning = sample.reasoning;
    issue.evidence_status = sample.nature === "insufficient_evidence" ? "insufficient" : "sufficient";
    issue.available_actions = sample.nature === "insufficient_evidence"
      ? []
      : ["edit", ...("suggested_revision" in sample ? ["apply_suggestion"] : []), "keep_intentional", "false_positive"];
    issue.suggested_revision = "suggested_revision" in sample ? sample.suggested_revision : null;
  });
  if (issues.length < fixture.cases.length) {
    const sample = fixture.cases.at(-1)!;
    issues.push({
      ...issues[0],
      id: `frontend-fixture-unknown-${String(run.run_id ?? "run")}`,
      nature: sample.nature,
      reasoning: sample.reasoning,
      claim_text: sample.claim,
      suggested_revision: null,
      decision: null,
    });
  }
  await route.fulfill({ response, json });
}

async function beginTutorial(page: Page) {
  await page.getByRole("button", { name: "开始教学", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 1 / 5");
}

async function reachFullEvidence(page: Page, issueLabel?: string) {
  await page.getByRole("button", { name: "Story Memory", exact: true }).click();
  const progressResponse = page.waitForResponse((response) =>
    response.url().includes("/api/onboarding/progress") && response.request().method() === "POST",
  );
  await page.locator(".memory-source:not(:disabled)").first().click();
  const progressPayload = await (await progressResponse).json() as { data: { current_step: number } };
  expect(progressPayload.data.current_step).toBe(2);
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 2 / 5");
  await page.keyboard.press("Escape");
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  const issue = issueLabel
    ? page.locator(".issue-row").filter({ hasText: issueLabel }).first()
    : page.locator(".issue-row").first();
  await issue.click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 3 / 5");
  const drawer = page.getByRole("dialog", { name: "问题证据", exact: true });
  await drawer.getByRole("button", { name: "查看完整证据", exact: true }).click();
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 4 / 5");
  return drawer;
}

test("v1.4 trustworthy review separates semantics and guards suggestion application", async ({ page }) => {
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", patchReviewFixture);
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "review");
  await beginTutorial(page);
  await page.getByRole("button", { name: "Story Memory", exact: true }).click();
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  for (const label of ["明确矛盾", "状态变化", "可能矛盾", "证据不足", "性质待确认"]) {
    await expect(page.locator(".issue-list")).toContainText(label);
  }
  for (const size of [{ width: 1366, height: 768 }, { width: 1440, height: 900 }]) {
    await page.setViewportSize(size);
    const boxes = await Promise.all([
      page.locator("#draft-body").boundingBox(),
      page.locator(".issue-row").first().boundingBox(),
    ]);
    expect(boxes.every((box) => box && box.y < size.height && box.y + box.height > 0)).toBe(true);
  }
  await page.getByRole("button", { name: "Story Memory", exact: true }).click();
  const drawer = await reachFullEvidence(page, "状态变化");

  await expect(drawer.getByRole("heading", { name: "状态变化", exact: true })).toBeVisible();
  await expect(drawer.locator(".risk")).toContainText("影响");
  await expect(drawer.getByText("当前草稿", { exact: true })).toBeVisible();
  await expect(drawer.getByText("历史证据", { exact: true })).toBeVisible();
  await expect(drawer.getByText("判断理由", { exact: true })).toBeVisible();
  await expect(drawer.getByText(/只回到正文，不会自动改写或保存/)).toBeVisible();
  const body = page.locator("#draft-body");
  const original = await body.inputValue();
  await drawer.getByRole("button", { name: "预览修改建议", exact: true }).click();
  await expect(drawer.getByRole("region", { name: "修改差异预览" })).toContainText("修改前");
  await drawer.getByRole("button", { name: "取消预览", exact: true }).click();
  expect(await body.inputValue()).toBe(original);
  await drawer.getByRole("button", { name: "预览修改建议", exact: true }).click();
  await drawer.getByRole("button", { name: "应用到未保存草稿", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("修改建议已放入未保存草稿；请先检查正文，再决定是否保存。");
  await expect(body).toHaveValue(original.replace("温岚把罗盘放在潮汐档案室的桌上。", "温岚暂时把罗盘放在潮汐档案室的桌上。"));
  await expect(page.locator(".workspace-save-summary")).toContainText("未保存");
  await expect(page.locator(".run-meta")).toContainText("此检查针对先前正文");
  await page.locator(".issue-row").filter({ hasText: "状态变化" }).first().click();
  await expect(page.getByRole("dialog", { name: "问题证据", exact: true }).getByRole("button", { name: "预览修改建议", exact: true })).toBeDisabled();
  await page.keyboard.press("Escape");

  await screenshot(page, "v140-01-trustworthy-review-1440.png");
  for (const size of [
    { width: 390, height: 844 }, { width: 768, height: 900 }, { width: 1024, height: 768 },
    { width: 1280, height: 800 }, { width: 1366, height: 768 }, { width: 1440, height: 900 }, { width: 1920, height: 1080 },
  ]) {
    await page.setViewportSize(size);
    await noOverflow(page);
  }
  await page.setViewportSize({ width: 390, height: 844 });
  await expect(page.getByRole("navigation", { name: "手机浏览内容" })).toBeVisible();
  await expect(page.locator("#draft-body")).toHaveCount(0);
  await page.getByRole("button", { name: /问题/ }).click();
  await expect(page.locator(".issue-list")).toBeVisible();
  await screenshot(page, "v140-02-mobile-review-390.png");
});

test("v1.4 local recovery preserves same-revision edits and blocks cross-revision overwrite", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "recovery");
  await beginTutorial(page);
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  const body = page.locator("#draft-body");
  const original = await body.inputValue();
  await body.fill(`${original}\n当前设备恢复标记。`);
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith("story-continuity:draft:v1:")))).toBe(true);
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  const recovery = page.getByRole("dialog", { name: "发现当前设备的未保存草稿", exact: true });
  await expect(recovery).toBeVisible();
  await expect(recovery.getByLabel("当前设备恢复副本完整文本")).toContainText("当前设备恢复标记");
  await recovery.getByRole("button", { name: "恢复副本（尚未保存）", exact: true }).click();
  await expect(body).toContainText("当前设备恢复标记");
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.locator(".workspace-save-summary")).toContainText("已保存");

  const current = await page.evaluate(async () => {
    const projectId = location.pathname.split("/")[2];
    const projectResponse = await fetch(`/api/projects/${projectId}`);
    const project = (await projectResponse.json()).data;
    const draftResponse = await fetch(`/api/projects/${projectId}/drafts/${project.current_draft.id}`);
    return { projectId, draft: (await draftResponse.json()).data };
  }) as { projectId: string; draft: { id: string; revision: number; title: string; body: string } };
  await body.fill(`${current.draft.body}\n跨版本本地副本。`);
  await expect.poll(() => page.evaluate(() => Object.values(localStorage).some((value) => value.includes("跨版本本地副本")))).toBe(true);
  const external = await page.evaluate(async ({ projectId, draft }) => {
    const response = await fetch(`/api/projects/${projectId}/drafts/${draft.id}`, {
      method: "PATCH",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
      body: JSON.stringify({ base_revision: draft.revision, title: draft.title, body: `${draft.body}\n服务器并发更新。` }),
    });
    return response.status;
  }, current);
  expect(external).toBe(200);
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  const conflict = page.getByRole("dialog", { name: "发现两个不同版本的草稿", exact: true });
  await expect(conflict).toBeVisible();
  await expect(conflict.getByLabel("当前设备恢复副本完整文本")).toContainText("跨版本本地副本");
  await expect(conflict.getByLabel("服务器已保存版本完整文本")).toContainText("服务器并发更新");
  await conflict.getByRole("button", { name: "查看恢复副本（禁止直接覆盖）", exact: true }).click();
  await expect(page.getByText(/当前显示的是只读恢复副本/)).toBeVisible();
  await expect(body).toHaveAttribute("readonly", "");
  await expect(page.getByLabel("章节标题")).toBeDisabled();
  await expect(page.getByRole("button", { name: "进入沉浸写作", exact: true })).toBeDisabled();
  await expect(page.getByRole("button", { name: "保存草稿", exact: true })).toBeDisabled();
  const recoveryText = await body.inputValue();
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  await page.getByRole("dialog", { name: "发现两个不同版本的草稿", exact: true }).getByRole("button", { name: "查看恢复副本（禁止直接覆盖）", exact: true }).click();
  await expect(body).toHaveValue(recoveryText);
  await expect(body).toHaveAttribute("readonly", "");
  await screenshot(page, "v140-03-cross-revision-recovery.png");
});

test("v1.4 explicit empty actions and insufficient evidence remain browse-only", async ({ page }) => {
  let decisionCalls = 0;
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", async (route) => {
    const response = await route.fetch();
    if (!response.ok()) return route.fulfill({ response });
    const payload = await response.json() as { data?: JsonRecord } & JsonRecord;
    const run = (payload.data ?? payload) as JsonRecord;
    const issues = run.issues as JsonRecord[] | undefined;
    if (issues?.length) {
      issues[0].nature = "insufficient_evidence";
      issues[0].evidence_status = "insufficient";
      issues[0].available_actions = [];
      issues[0].decision = null;
    }
    await route.fulfill({ response, json: payload });
  });
  await page.route("**/api/projects/*/issues/*/decision", async (route) => { decisionCalls += 1; await route.continue(); });
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "actions");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await expect(drawer.getByText(/服务端未开放可提交操作/)).toBeVisible();
  await expect(drawer.getByText(/证据尚不充分/)).toBeVisible();
  for (const name of ["前往修改", "预览修改建议", "保留原意", "标记误报"]) {
    await expect(drawer.getByRole("button", { name, exact: true })).toHaveCount(0);
  }
  expect(decisionCalls).toBe(0);
});

test("v1.4 controlled save locks input and reports decision failure separately", async ({ page }) => {
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", patchReviewFixture);
  await page.setViewportSize({ width: 1366, height: 768 });
  await register(page, "partial");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  const body = page.locator("#draft-body");
  await body.fill(`${await body.inputValue()}\n受控修订自测。`);
  let patchCalls = 0;
  let decisionCalls = 0;
  await page.route("**/api/projects/*/drafts/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patchCalls += 1;
    await new Promise((resolve) => setTimeout(resolve, 450));
    await route.continue();
  });
  await page.route("**/api/projects/*/issues/*/decision", async (route) => {
    decisionCalls += 1;
    if (decisionCalls === 1) return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "decision_test_failure", message: "fixture decision failure", retryable: true } }) });
    await route.continue();
  });
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  await expect(body).toBeDisabled();
  await expect(page.locator(".workspace-save-summary")).toContainText("保存中");
  await expect(page.getByRole("status")).toContainText("正文已保存，但本条问题的修改决定未记录");
  await expect(page.locator(".workspace-save-summary")).toContainText("已保存");
  await expect(body).toHaveAttribute("readonly", "");
  await page.getByRole("button", { name: "重试记录决定", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("作者决定已补记");
  expect(patchCalls).toBe(1);
  expect(decisionCalls).toBe(2);
  await screenshot(page, "v140-04-partial-controlled-save.png", false);
});

test("v1.4 pending decision survives refresh and retries without another draft save", async ({ page }) => {
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", patchReviewFixture);
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "pendingrefresh");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  await page.locator("#draft-body").fill(`${await page.locator("#draft-body").inputValue()}\n刷新后补记。`);
  let patchCalls = 0;
  let decisionCalls = 0;
  const idempotencyKeys: string[] = [];
  await page.route("**/api/projects/*/drafts/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patchCalls += 1;
    await route.continue();
  });
  await page.route("**/api/projects/*/issues/*/decision", async (route) => {
    decisionCalls += 1;
    idempotencyKeys.push(route.request().headers()["idempotency-key"] ?? "");
    if (decisionCalls === 1) return route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "decision_test_failure", message: "fixture decision failure", retryable: true } }) });
    await route.continue();
  });
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith("story-continuity:pending-decision:v1:")))).toBe(true);
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toBeVisible();
  await expect(page.locator("#draft-body")).toHaveAttribute("readonly", "");
  const workspaceUrl = page.url();
  page.once("dialog", (dialog) => dialog.accept());
  await page.goto("/");
  await page.goto(workspaceUrl);
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toBeVisible();
  await expect(page.locator("#draft-body")).toHaveAttribute("readonly", "");
  await page.getByRole("button", { name: "重试记录决定", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("补记");
  expect(patchCalls).toBe(1);
  expect(decisionCalls).toBe(2);
  expect(idempotencyKeys[0]).toBeTruthy();
  expect(idempotencyKeys[1]).toBe(idempotencyKeys[0]);
  await expect.poll(() => page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith("story-continuity:pending-decision:v1:")))).toBe(false);
});

test("v1.4 lost decision response replays the same idempotent operation", async ({ page }) => {
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", patchReviewFixture);
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "lostresponse");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  await page.locator("#draft-body").fill(`${await page.locator("#draft-body").inputValue()}\n响应丢失补记。`);
  let patchCalls = 0;
  const serverStatuses: number[] = [];
  const idempotencyKeys: string[] = [];
  await page.route("**/api/projects/*/drafts/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patchCalls += 1;
    await route.continue();
  });
  await page.route("**/api/projects/*/issues/*/decision", async (route) => {
    idempotencyKeys.push(route.request().headers()["idempotency-key"] ?? "");
    const response = await route.fetch();
    serverStatuses.push(response.status());
    if (serverStatuses.length === 1) return route.fulfill({ status: 502, contentType: "application/json", body: JSON.stringify({ error: { code: "response_lost", message: "response lost after commit", retryable: true } }) });
    await route.fulfill({ response });
  });
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "重试记录决定", exact: true }).click();
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toHaveCount(0);
  expect(serverStatuses).toEqual([200, 200]);
  expect(patchCalls).toBe(1);
  expect(idempotencyKeys[1]).toBe(idempotencyKeys[0]);
  await expect(page.getByRole("status")).toContainText(/补记|已经记录/);
});

test("v1.4 newer server draft stops stale pending-decision replay", async ({ page }) => {
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", patchReviewFixture);
  await page.setViewportSize({ width: 1440, height: 900 });
  const credentials = await register(page, "pendingconflict");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  await page.locator("#draft-body").fill(`${await page.locator("#draft-body").inputValue()}\n待补记版本冲突。`);
  let patchCalls = 0;
  let decisionCalls = 0;
  await page.route("**/api/projects/*/drafts/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patchCalls += 1;
    await route.continue();
  });
  await page.route("**/api/projects/*/issues/*/decision", async (route) => {
    decisionCalls += 1;
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "decision_test_failure", message: "fixture decision failure", retryable: true } }) });
  });
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  const current = await page.evaluate(async () => {
    const projectId = location.pathname.split("/")[2];
    const project = (await (await fetch(`/api/projects/${projectId}`)).json()).data;
    const draft = (await (await fetch(`/api/projects/${projectId}/drafts/${project.current_draft.id}`)).json()).data;
    return { projectId, draft };
  }) as { projectId: string; draft: { id: string; revision: number; title: string; body: string } };
  const status = await page.evaluate(async ({ projectId, draft }) => (await fetch(`/api/projects/${projectId}/drafts/${draft.id}`, {
    method: "PATCH",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
    body: JSON.stringify({ base_revision: draft.revision, title: draft.title, body: `${draft.body}\n服务器更新。` }),
  })).status, current);
  expect(status).toBe(200);
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(page.getByText(/待补记记录与服务器当前草稿或决定不一致/)).toBeVisible();
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toBeDisabled();
  await expect(page.locator("#draft-body")).toHaveAttribute("readonly", "");
  const workspaceUrl = page.url();
  const foreignKey = "story-continuity:pending-decision:v1:foreign-user:foreign-project:foreign-draft";
  await page.evaluate((key) => localStorage.setItem(key, "foreign-record"), foreignKey);
  await page.getByRole("button", { name: "首页", exact: true }).click();
  const leaveBoundary = page.getByRole("dialog", { name: "待补记决定已失效", exact: true });
  await expect(leaveBoundary).toContainText(/旧决定不会再提交/);
  await leaveBoundary.getByRole("button", { name: "保留记录并离开", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await page.goto(workspaceUrl);
  await expect(page.getByText(/待补记记录与服务器当前草稿或决定不一致/)).toBeVisible();
  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "登录", exact: true })).toBeVisible();
  expect(await page.evaluate(() => Object.keys(localStorage).some((key) => key.startsWith("story-continuity:pending-decision:v1:") && !key.includes("foreign-user")))).toBe(true);
  await page.getByLabel("账号", { exact: true }).fill(credentials.account);
  await page.locator('input[name="password"]').fill(credentials.password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await page.goto(workspaceUrl);
  await expect(page.getByRole("button", { name: "停止追补并读取最新正文", exact: true })).toBeVisible();
  await page.getByRole("button", { name: "停止追补并读取最新正文", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(/保留在本机冲突历史.*服务器最新正文/);
  await expect(page.locator("#draft-body")).toHaveValue(/服务器更新。/);
  await expect(page.locator("#draft-body")).not.toHaveAttribute("readonly", "");
  const localState = await page.evaluate((key) => ({
    foreign: localStorage.getItem(key),
    pending: Object.keys(localStorage).filter((item) => item.startsWith("story-continuity:pending-decision:v1:") && !item.includes("foreign-user")),
    conflicts: Object.keys(localStorage).filter((item) => item.startsWith("story-continuity:pending-decision-conflicts:v1:")),
  }), foreignKey);
  expect(localState.foreign).toBe("foreign-record");
  expect(localState.pending).toEqual([]);
  expect(localState.conflicts).toHaveLength(1);
  expect(patchCalls).toBe(2);
  expect(decisionCalls).toBe(1);
});

test("v1.4 different server decision can be retained and left without replay", async ({ page }) => {
  const runPattern = "**/api/projects/*/checks/*?include=issues,evidence,metrics";
  await page.route(runPattern, patchReviewFixture);
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "pendingotherdecision");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  await page.locator("#draft-body").fill(`${await page.locator("#draft-body").inputValue()}\n不同决定冲突。`);
  let patchCalls = 0;
  let decisionCalls = 0;
  await page.route("**/api/projects/*/drafts/*", async (route) => {
    if (route.request().method() !== "PATCH") return route.continue();
    patchCalls += 1;
    await route.continue();
  });
  await page.route("**/api/projects/*/issues/*/decision", async (route) => {
    decisionCalls += 1;
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "decision_test_failure", retryable: true } }) });
  });
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  await expect(page.getByRole("button", { name: "重试记录决定", exact: true })).toBeVisible();
  const pendingIssueId = await page.evaluate(() => {
    const key = Object.keys(localStorage).find((item) => item.startsWith("story-continuity:pending-decision:v1:"));
    return key ? (JSON.parse(localStorage.getItem(key) ?? "{}") as { issueId?: string }).issueId : undefined;
  });
  expect(pendingIssueId).toBeTruthy();
  await page.unroute(runPattern, patchReviewFixture);
  await page.route(runPattern, async (route) => {
    const response = await route.fetch();
    const json = await response.json() as { data?: JsonRecord } & JsonRecord;
    const run = (json.data ?? json) as JsonRecord;
    const issues = run.issues as JsonRecord[];
    const pendingIssue = issues.find((issue) => issue.id === pendingIssueId);
    expect(pendingIssue).toBeTruthy();
    pendingIssue!.decision = { decision: "keep_intentional", resulting_revision: null };
    await route.fulfill({ response, json });
  });
  page.once("dialog", (dialog) => dialog.accept());
  await page.reload();
  await expect(page.getByText(/待补记记录与服务器当前草稿或决定不一致/)).toBeVisible();
  const workspaceUrl = page.url();
  await page.getByRole("button", { name: "首页", exact: true }).click();
  const leaveBoundary = page.getByRole("dialog", { name: "待补记决定已失效", exact: true });
  await leaveBoundary.getByRole("button", { name: "保留记录并离开", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  await page.goto(workspaceUrl);
  await expect(page.getByText(/待补记记录与服务器当前草稿或决定不一致/)).toBeVisible();
  expect(patchCalls).toBe(1);
  expect(decisionCalls).toBe(1);
});

test("v1.4 storage-unavailable pending decision gives an honest stay-on-page boundary", async ({ page }) => {
  await page.addInitScript(() => {
    const original = Storage.prototype.setItem;
    Storage.prototype.setItem = function (key, value) {
      if (key.startsWith("story-continuity:pending-decision:")) throw new DOMException("blocked", "SecurityError");
      return original.call(this, key, value);
    };
  });
  await page.route("**/api/projects/*/checks/*?include=issues,evidence,metrics", patchReviewFixture);
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "pendingstorage");
  await beginTutorial(page);
  const drawer = await reachFullEvidence(page);
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  await page.locator("#draft-body").fill(`${await page.locator("#draft-body").inputValue()}\n无存储补记。`);
  await page.route("**/api/projects/*/issues/*/decision", async (route) => {
    await route.fulfill({ status: 500, contentType: "application/json", body: JSON.stringify({ error: { code: "decision_test_failure", message: "fixture decision failure", retryable: true } }) });
  });
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(/无法持久保存重试记录|不要刷新或离开/);
  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page.getByRole("status")).toContainText(/留在此页重试成功后再退出登录/);
  await expect(page).toHaveURL(/\/projects\/[^/]+\/workspace/);
  await page.getByRole("button", { name: "首页", exact: true }).click();
  const boundary = page.getByRole("dialog", { name: "作者决定尚未确认" });
  await expect(boundary).toBeVisible();
  await expect(boundary).toContainText(/完成补记后才能安全切换/);
  await expect(boundary.getByRole("button", { name: "放弃修改", exact: true })).toHaveCount(0);
});

test("v1.4 mobile read mode sizes short and long chapters by content", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "mobilebody");
  await beginTutorial(page);
  await page.getByRole("button", { name: "写作与检查", exact: true }).click();
  await page.setViewportSize({ width: 390, height: 844 });
  const shortRead = page.locator(".draft-read");
  await expect(shortRead).toBeVisible();
  expect((await shortRead.boundingBox())!.height).toBeLessThan(420);
  await page.setViewportSize({ width: 1440, height: 900 });
  const longBody = Array.from({ length: 48 }, (_, index) => `第 ${index + 1} 段：潮声越过档案室，温岚逐页核对旧航线与人物去向。`).join("\n\n");
  await page.locator("#draft-body").fill(longBody);
  await page.getByRole("button", { name: "保存草稿", exact: true }).click();
  await expect(page.locator(".workspace-save-summary")).toContainText("已保存");
  await page.setViewportSize({ width: 390, height: 844 });
  const longRead = page.locator(".draft-read");
  await expect(longRead).toContainText("第 48 段");
  const dimensions = await longRead.evaluate((element) => ({ client: element.clientHeight, scroll: element.scrollHeight }));
  expect(dimensions.client).toBeGreaterThan(540);
  expect(dimensions.client).toBe(dimensions.scroll);
});

test("v1.4 profile is view-first and import copy matches HTTP behavior", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "copy");
  await page.goto("/account/profile");
  await expect(page.getByRole("heading", { name: "个人信息", exact: true })).toBeVisible();
  await expect(page.getByLabel("显示名称")).toHaveCount(0);
  await expect(page.getByText("真实数据", { exact: true })).toHaveCount(0);
  await expect(page.getByText("次级设置", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "编辑资料", exact: true }).click();
  await expect(page.getByLabel("显示名称")).toBeVisible();
  await page.goto("/projects/import");
  await expect(page.getByText(/文件会发送到当前应用服务进行预览/)).toBeVisible();
  await expect(page.getByText(/加密连接/)).toHaveCount(0);
  expect(new URL(page.url()).protocol).toBe("http:");
});

test("v1.4 tutorial restart never invokes destructive reopen endpoint", async ({ page }) => {
  let reopenCalls = 0;
  let progressRestartCalls = 0;
  await page.route("**/api/onboarding/reopen", async (route) => {
    reopenCalls += 1;
    await route.abort();
  });
  page.on("request", (request) => {
    if (request.url().includes("/api/onboarding/progress/restart") && request.method() === "POST") progressRestartCalls += 1;
  });
  await register(page, "tutorial");
  await beginTutorial(page);
  await page.getByRole("button", { name: "用户菜单" }).click();
  await page.getByRole("menuitem", { name: /重新打开教学/ }).click();
  await expect(page.getByText(/教学进度已回到第一步/)).toBeVisible();
  expect(progressRestartCalls).toBe(1);
  expect(reopenCalls).toBe(0);
});

test("v1.4 completed tutorial restarts through an explicit review of an existing stale decision", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await register(page, "decisionreview");
  await beginTutorial(page);
  const readData = async (url: string) => {
    const response = await page.request.get(url);
    expect(response.ok(), await response.text()).toBe(true);
    return ((await response.json()) as { data: JsonRecord }).data;
  };
  const post = (url: string, data: JsonRecord) => page.request.post(url, {
    data,
    headers: { "Idempotency-Key": randomUUID() },
  });
  const onboarding = await readData("/api/onboarding");
  const tutorial = onboarding.tutorial as JsonRecord;
  const projectId = String(tutorial.project_id);
  const project = await readData(`/api/projects/${projectId}`);
  const latestRun = project.latest_run as JsonRecord;
  const runId = String(latestRun.run_id);
  const run = await readData(`/api/projects/${projectId}/checks/${runId}?include=issues,evidence,metrics`);
  const issues = run.issues as JsonRecord[];
  const actionable = issues.filter((issue) => (issue.available_actions as string[]).includes("false_positive"));
  expect(actionable.length).toBeGreaterThan(0);
  for (const issue of actionable) {
    const decided = await post(`/api/projects/${projectId}/issues/${String(issue.id)}/decision`, {
      run_id: runId,
      source_revision: Number(run.source_revision),
      decision: "false_positive",
    });
    expect(decided.ok(), await decided.text()).toBe(true);
  }
  const currentDraft = project.current_draft as JsonRecord;
  const draft = await readData(`/api/projects/${projectId}/drafts/${String(currentDraft.id)}`);
  const saved = await page.request.patch(`/api/projects/${projectId}/drafts/${String(draft.id)}`, {
    data: { base_revision: Number(draft.revision), body: `${String(draft.body)}\n旧检查之后的新段落。` },
    headers: { "Idempotency-Key": randomUUID() },
  });
  expect(saved.ok(), await saved.text()).toBe(true);
  for (const event of ["memory_source_opened", "continuity_issue_located", "evidence_opened", "author_decision_recorded"]) {
    const advanced = await post("/api/onboarding/progress", {
      tutorial_version: "1.2.0",
      project_id: projectId,
      event,
    });
    expect(advanced.ok(), await advanced.text()).toBe(true);
  }
  const completed = await post("/api/onboarding/complete", { confirm: true });
  expect(completed.ok(), await completed.text()).toBe(true);
  const protectedBefore = JSON.stringify({
    project: await readData(`/api/projects/${projectId}`),
    draft: await readData(`/api/projects/${projectId}/drafts/${String(draft.id)}`),
    memory: await readData(`/api/projects/${projectId}/memory`),
    run: await readData(`/api/projects/${projectId}/checks/${runId}?include=issues,evidence,metrics`),
  });
  const restarted = await post("/api/onboarding/progress/restart", {
    tutorial_version: "1.2.0",
    project_id: projectId,
    base_revision: null,
    confirm: true,
  });
  expect(restarted.ok(), await restarted.text()).toBe(true);

  await page.goto(`/projects/${projectId}/memory`);
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 1 / 5");
  const drawer = await reachFullEvidence(page);
  await expect(drawer.getByText(/这是一条既有作者决定/)).toBeVisible();
  await expect(drawer.getByText(/正文或服务器版本已变化/)).toBeVisible();
  let decisionWrites = 0;
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/issues\/[^/]+\/decision$/.test(new URL(request.url()).pathname)) decisionWrites += 1;
  });
  const reviewResponse = page.waitForResponse((response) =>
    response.url().endsWith("/api/onboarding/progress") && response.request().method() === "POST",
  );
  await drawer.getByRole("button", { name: "我已复习这个决定，继续教学", exact: true }).click();
  const reviewPayload = await (await reviewResponse).json() as { data: { current_step: number; completed_events: string[] } };
  expect(reviewPayload.data.current_step).toBe(5);
  expect(reviewPayload.data.completed_events).toContain("author_decision_reviewed");
  expect(decisionWrites).toBe(0);
  await expect(page.getByLabel("教学进度", { exact: true })).toContainText("教学 5 / 5");
  await screenshot(page, "v140-05-existing-decision-review.png");
  await drawer.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(drawer).toHaveCount(0);
  await page.getByRole("button", { name: "完成教学", exact: true }).click();
  await expect(page.getByRole("heading", { name: "教学已完成", exact: true })).toBeVisible();
  const protectedAfter = JSON.stringify({
    project: await readData(`/api/projects/${projectId}`),
    draft: await readData(`/api/projects/${projectId}/drafts/${String(draft.id)}`),
    memory: await readData(`/api/projects/${projectId}/memory`),
    run: await readData(`/api/projects/${projectId}/checks/${runId}?include=issues,evidence,metrics`),
  });
  expect(protectedAfter).toBe(protectedBefore);
});
