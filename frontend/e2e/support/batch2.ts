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
