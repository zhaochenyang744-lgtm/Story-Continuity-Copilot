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
