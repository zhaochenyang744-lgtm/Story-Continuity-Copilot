import { expect, test } from "@playwright/test";
import { readDraftBody } from "./support/app";

test("controlled edit run discards old selection and saves only the completed run's issue", async ({ page }, testInfo) => {
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const failedResponses: string[] = [];
  const patches: Array<{ body: string; edit_context?: { source_run_id: string; issue_id: string } }> = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "PATCH" && /\/api\/projects\/[^/]+\/drafts\//.test(new URL(request.url()).pathname)) {
      patches.push(request.postDataJSON());
    }
  });
  await page.goto("/login");
  await page.getByRole("button", { name: "访客体验 24 小时", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  // The anonymous session probe before login is expected to return 401.
  page.on("console", (message) => { if (message.type() === "error") consoleErrors.push(message.text()); });
  page.on("response", (response) => {
    if (response.status() >= 400) failedResponses.push(`${response.request().method()} ${response.url()} ${response.status()}`);
  });
  await page.locator(".global-nav").getByRole("button", { name: "作品管理", exact: true }).click();
  await page.locator(".project-rows li").filter({ hasText: "灰港回声" }).getByRole("button", { name: "打开", exact: true }).click();
  await page.locator(".project-nav").getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page.getByText("示例检查结果", { exact: true })).toBeVisible();
  const projectId = new URL(page.url()).pathname.split("/")[2];
  const originalBody = await readDraftBody(page);
  const projectResponse = await page.request.get(`/api/projects/${projectId}`);
  expect(projectResponse.status()).toBe(200);
  const oldRunId = (await projectResponse.json()).data.latest_run.run_id as string;
  const oldResponse = await page.request.get(`/api/projects/${projectId}/checks/${oldRunId}?include=issues,evidence`);
  expect(oldResponse.status()).toBe(200);
  const oldIssueIds = (await oldResponse.json()).data.issues.map((issue: { id: string }) => issue.id) as string[];

  let release!: () => void;
  let intercepted!: (runId: string) => void;
  const gate = new Promise<void>((resolve) => { release = resolve; });
  const held = new Promise<string>((resolve) => { intercepted = resolve; });
  await page.route(`**/api/projects/${projectId}/checks`, async (route) => {
    expect(route.request().method()).toBe("POST");
    const response = await route.fetch();
    expect(response.status()).toBe(202);
    const created = (await response.json()).data;
    expect(created.status).toBe("queued");
    intercepted(created.run_id);
    await gate;
    await route.fulfill({ response });
  });
  let newRunId: string;
  const drawer = page.getByRole("dialog", { name: "问题证据", exact: true });
  try {
    await page.getByRole("button", { name: "运行连续性检查", exact: true }).click();
    newRunId = await held;
    expect(newRunId).not.toBe(oldRunId);
    await page.locator(".issue-list .issue-row").first().click();
    await expect(drawer).toBeVisible();
    await expect(drawer.getByRole("button", { name: "前往修改", exact: true })).toBeDisabled();
    release();
    await expect(drawer).toBeHidden();
    await expect(page.getByRole("button", { name: "保存受控修订", exact: true })).toHaveCount(0);
    await expect.poll(() => readDraftBody(page)).toBe(originalBody);
    expect(patches).toEqual([]);
    // Bind completion to the newly created run, not the completed seed result.
    await expect(page.locator(".run-lifecycle .run-facts")).toContainText(newRunId);
    await expect(page.getByLabel("连续性检查运行状态", { exact: true })).toContainText("检查完成");
  } finally {
    release();
    await page.unrouteAll({ behavior: "wait" });
  }

  const completedResponse = await page.request.get(`/api/projects/${projectId}/checks/${newRunId}?include=issues,evidence`);
  expect(completedResponse.status()).toBe(200);
  const completed = (await completedResponse.json()).data as {
    status: string; issues: Array<{ id: string; claim_text: string; evidence_status: string; available_actions?: string[] }>;
  };
  expect(completed.status).toBe("completed");
  const editable = completed.issues.filter((issue) => issue.evidence_status === "sufficient"
    && (issue.available_actions === undefined || issue.available_actions.includes("edit")));
  expect(editable.length).toBeGreaterThanOrEqual(2);
  const [edited, other] = editable;
  await page.locator(".issue-list .issue-row").filter({ hasText: edited.claim_text }).click();
  await drawer.getByRole("button", { name: "前往修改", exact: true }).click();
  await expect(drawer).toBeHidden();
  await expect(page.getByRole("button", { name: "保存受控修订", exact: true })).toBeVisible();
  // A decision refreshes the same run. It must preserve the selected drawer
  // for review and the already active controlled edit of the other issue.
  await page.locator(".issue-list .issue-row").filter({ hasText: other.claim_text }).click();
  await drawer.getByRole("button", { name: "保留原意", exact: true }).click();
  await expect(drawer.getByRole("status")).toContainText("决定已记录");
  await expect(drawer).toBeVisible();
  await drawer.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(drawer).toBeHidden();
  await expect(page.getByRole("button", { name: "保存受控修订", exact: true })).toBeVisible();

  const editor = page.getByRole("textbox", { name: "草稿正文", exact: true });
  await editor.press("ControlOrMeta+A");
  await editor.press("Backspace");
  await expect.poll(() => readDraftBody(page)).toBe("");
  const body = "新检查完成后的受控修改，正文完整保留。";
  await page.keyboard.insertText(body);
  await expect.poll(() => readDraftBody(page)).toBe(body);
  await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
  await expect(page.locator(".workspace-draft-meta")).toContainText("第 2 次保存");
  await expect(page.getByRole("status").filter({ hasText: "受控修订已保存为第 2 次保存，作者决定也已记录。" })).toBeVisible();
  await expect.poll(() => readDraftBody(page)).toBe(body);
  expect(patches).toHaveLength(1);
  for (const patch of patches) {
    expect(patch.body).toBe(body);
    expect(patch.edit_context).toEqual({ source_run_id: newRunId, source_revision: 1, issue_id: edited.id });
    expect(oldIssueIds).not.toContain(patch.edit_context?.issue_id);
    expect(completed.issues.map((issue) => issue.id)).toContain(patch.edit_context?.issue_id);
  }
  await testInfo.attach("controlled-edit-bindings", {
    body: JSON.stringify({ oldRunId, oldIssueIds, newRunId, newIssueIds: completed.issues.map((issue) => issue.id), patches }, null, 2),
    contentType: "application/json",
  });
  expect(pageErrors).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(failedResponses).toEqual([]);
});
