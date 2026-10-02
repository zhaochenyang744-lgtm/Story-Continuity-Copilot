import { expect, type Page } from "@playwright/test";

// Only visitor spaces contain the three product demo projects.
export async function startVisitor(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "访客体验 24 小时", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
}

export async function projectMoreAction(page: Page, name: string) {
  await page.locator("details.more-menu > summary").click();
  await page.getByRole("menu", { name: "更多操作", exact: true }).getByRole("button", { name, exact: true }).click();
}

// A recorded decision stays open for review; it cannot be submitted twice.
export async function recordIssueDecision(page: Page, decision: "保留原意" | "标记误报") {
  const drawer = page.getByRole("dialog", { name: "问题证据", exact: true });
  await drawer.getByRole("button", { name: decision, exact: true }).click();
  await expect(drawer.getByRole("status")).toContainText("决定已记录；此问题保留在列表中，便于后续追溯。");
  for (const name of ["前往修改", "保留原意", "标记误报"]) {
    await expect(drawer.getByRole("button", { name, exact: true })).toBeDisabled();
  }
  await drawer.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(drawer).toBeHidden();
}

// The seeded demo result is already complete and stays on screen until the
// POST returns, so "检查完成" alone can match it. Bind the wait to the new run.
export async function runCheckAndWait(page: Page) {
  const queued = page.waitForResponse((response) =>
    response.request().method() === "POST" && /\/api\/projects\/[^/]+\/checks$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", { name: "运行连续性检查", exact: true }).click();
  const response = await queued;
  expect(response.status()).toBe(202);
  const payload = await response.json() as { data: { run_id: string; status: string } };
  expect(payload.data.status).toBe("queued");
  await expect(page.locator(".run-lifecycle .run-facts")).toContainText(payload.data.run_id, { timeout: 15_000 });
  await expect(page.getByLabel("连续性检查运行状态", { exact: true })).toContainText("检查完成", { timeout: 15_000 });
  return payload.data.run_id;
}
