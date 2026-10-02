import { expect, type Locator, type Page } from "@playwright/test";

export const continuityLifecycle = (page: Page) =>
  page.getByRole("region", { name: "连续性检查进度", exact: true });

export async function openRunDetails(card: Locator) {
  const details = card.getByRole("group").filter({ has: card.page().getByText("技术详情", { exact: true }) });
  if (await details.getAttribute("open") === null) {
    await card.getByText("技术详情", { exact: true }).click();
  }
  await expect(card.locator(".run-facts")).toBeVisible();
}

// A demo's previous completed result can remain visible until POST returns.
// Bind every lifecycle observation to the newly created run, including errors.
export async function bindRun(card: Locator, runId: string) {
  expect(runId).toEqual(expect.any(String));
  expect(runId.length).toBeGreaterThan(0);
  await openRunDetails(card);
  await expect(card.locator(".run-facts")).toContainText(runId);
}

export async function startLifecycleRun(page: Page) {
  const queued = page.waitForResponse((response) =>
    response.request().method() === "POST" &&
    /\/api\/projects\/[^/]+\/checks$/.test(new URL(response.url()).pathname));
  await page.getByRole("button", { name: "运行连续性检查", exact: true }).click();
  const response = await queued;
  expect(response.status()).toBe(202);
  const { data } = await response.json() as { data: { run_id: string; status: string } };
  expect(data.status).toBe("queued");
  await bindRun(continuityLifecycle(page), data.run_id);
  return data.run_id;
}

export async function readLifecycleRun(page: Page, runId: string) {
  const projectId = new URL(page.url()).pathname.split("/")[2];
  const response = await page.request.get(`/api/projects/${projectId}/checks/${runId}?include=issues,evidence,metrics`);
  expect(response.status()).toBe(200);
  const { data } = await response.json();
  expect(data.run_id).toBe(runId);
  return data;
}
