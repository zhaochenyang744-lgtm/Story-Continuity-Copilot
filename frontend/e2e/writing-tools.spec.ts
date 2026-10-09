import { api, button, expect, saveBody, setup, shot, test } from "./support/writing";
import type { Page } from "@playwright/test";
async function analysis(page: Page, id: string, label: string, type: string, expected = "completed") {
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/analyses"));
  await button(page, label).click();
  const res = await response;
  expect(res.ok()).toBe(true);
  const rid = (await res.json()).data.run_id;
  await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${rid}`)).status).toBe(expected);
  const record = await api(page).get(`/projects/${id}/analyses/${rid}`);
  expect(record.analysis_type).toBe(type);
  return record;
}
test("写前回顾：分析记录与出处原文", async ({ page }) => {
  const id = await setup(page), result = await analysis(page, id, "写前回顾", "context_brief");
  const region = page.getByRole("region", { name: "写前回顾", exact: true });
  await expect(region).toContainText(result.analysis.summary);
  expect(result.analysis.items.length).toBeGreaterThan(0);
  for (const item of result.analysis.items) {
    expect(item.sources.length).toBeGreaterThan(0);
    await expect(region.getByText(item.text, { exact: true })).toBeVisible();
  }
  // Native details summaries expose the sources inline.
  const item = result.analysis.items[0];
  const row = region.getByRole("listitem").filter({ has: page.getByText(item.text, { exact: true }) });
  await row.getByText(/^出处 \d+$/).click();
  await expect(row.getByText(item.sources[0].excerpt, { exact: true })).toBeVisible();
  await shot(page, "writing-brief");
});
test("对照计划：逐条结果与后端一致", async ({ page }) => {
  const id = await setup(page), result = await analysis(page, id, "对照计划", "plan_alignment");
  const region = page.getByRole("region", { name: "对照计划", exact: true });
  await expect(region).toContainText(result.analysis.summary);
  expect(result.analysis.items.length).toBeGreaterThan(0);
  for (const item of result.analysis.items) await expect(region.getByText(item.story_plan_title, { exact: true })).toBeVisible();
  await shot(page, "writing-plan-alignment");
});
test("没有计划时：不显示对照计划入口", async ({ page }) => {
  const id = await setup(page, false), plans = await api(page).get(`/projects/${id}/author-intent?include_archived=true`);
  expect(plans.story_plans).toHaveLength(0);
  await expect(button(page, "对照计划")).toHaveCount(0);
});
test("分析失败后重试：写前回顾", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚仍保管黄铜罗盘，E2E_ANALYSIS_FAIL_ONCE。");
  const first = await analysis(page, id, "写前回顾", "context_brief", "failed");
  const region = page.getByRole("region", { name: "写前回顾", exact: true });
  await expect(region).toContainText("没有保存部分结果。");
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/analyses/${first.run_id}/retry`));
  await region.getByRole("button", { name: "重试", exact: true }).click();
  const rid = (await (await response).json()).data.run.run_id;
  expect(rid).not.toBe(first.run_id);
  await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${rid}`)).status).toBe("completed");
  const second = await api(page).get(`/projects/${id}/analyses/${rid}`);
  await expect(region).toContainText(second.analysis.summary);
});
