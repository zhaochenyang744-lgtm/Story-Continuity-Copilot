import { api, button, expect, findings, saveBody, setup, shot, test } from "./support/writing";
import { pair } from "./support/pages";
import type { Page } from "@playwright/test";

/** The right column's tabs; each one is picked by its name (the findings tab carries a count). */
const tab = (page: Page, name: string | RegExp) => findings(page).getByRole("tab", { name, exact: typeof name === "string" });
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
  // The result is in the right column, which has switched to it; nothing is added below the draft.
  await expect(tab(page, "写前回顾")).toHaveAttribute("aria-selected", "true");
  await expect(page.getByRole("region", { name: "写前回顾与计划对照" })).toHaveCount(0);
  const region = findings(page).getByRole("region", { name: "写前回顾", exact: true });
  await expect(region).toBeVisible();
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
  await pair(page, "writing-brief");
});
test("对照计划：逐条结果与后端一致", async ({ page }) => {
  const id = await setup(page), result = await analysis(page, id, "对照计划", "plan_alignment");
  await expect(tab(page, "对照计划")).toHaveAttribute("aria-selected", "true");
  const region = findings(page).getByRole("region", { name: "对照计划", exact: true });
  await expect(region).toBeVisible();
  await expect(region).toContainText(result.analysis.summary);
  expect(result.analysis.items.length).toBeGreaterThan(0);
  for (const item of result.analysis.items) await expect(region.getByText(item.story_plan_title, { exact: true })).toBeVisible();
  await shot(page, "writing-plan-alignment-day", false);
});
test("没有计划时：不显示对照计划入口", async ({ page }) => {
  const id = await setup(page, false), plans = await api(page).get(`/projects/${id}/author-intent?include_archived=true`);
  expect(plans.story_plans).toHaveLength(0);
  await expect(button(page, "对照计划")).toHaveCount(0);
  // Without a plan there is no such tab either: the findings tab stands alone.
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/]);
  await expect(tab(page, "对照计划")).toHaveCount(0);
});

test("右栏的切换：页头按钮开始分析并切到对应一项；方向键、Home、End 在三项之间移动，Tab 进入面板", async ({ page }) => {
  const id = await setup(page);
  await expect(findings(page).getByRole("tablist", { name: "右栏内容", exact: true })).toBeVisible();
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/]);
  await expect(tab(page, /^检查结果/)).toHaveAttribute("aria-selected", "true");
  await analysis(page, id, "写前回顾", "context_brief");
  await expect(tab(page, "写前回顾")).toHaveAttribute("aria-selected", "true");
  await analysis(page, id, "对照计划", "plan_alignment");
  await expect(tab(page, "对照计划")).toHaveAttribute("aria-selected", "true");
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/, "写前回顾", "对照计划"]);
  // Only the chosen tab is in the tab order; the arrow keys move and choose.
  await expect(tab(page, "写前回顾")).toHaveAttribute("tabindex", "-1");
  await tab(page, "对照计划").focus();
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, /^检查结果/)).toBeFocused();
  await expect(tab(page, /^检查结果/)).toHaveAttribute("aria-selected", "true");
  await expect(findings(page).getByRole("tabpanel")).toHaveCount(1);
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, "写前回顾")).toBeFocused();
  await expect(findings(page).getByRole("region", { name: "写前回顾", exact: true })).toBeVisible();
  await page.keyboard.press("End");
  await expect(tab(page, "对照计划")).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tab(page, /^检查结果/)).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(tab(page, "对照计划")).toBeFocused();
  await expect(findings(page).getByRole("region", { name: "对照计划", exact: true })).toBeVisible();
  // Tab leaves the strip for the chosen panel's content.
  await page.keyboard.press("Tab");
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest("[role=tabpanel]")))).toBe(true);
});

test("右栏的切换：右栏不在视口里时，点页头按钮会滚到它", async ({ page }) => {
  const id = await setup(page);
  await page.setViewportSize({ width: 1440, height: 400 });
  const side = page.getByRole("complementary", { name: "检查与回顾", exact: true });
  await expect(side).not.toBeInViewport({ ratio: 0.2 });
  await analysis(page, id, "写前回顾", "context_brief");
  await expect(side).toBeInViewport({ ratio: 0.2 });
  await expect(findings(page).getByRole("region", { name: "写前回顾", exact: true })).toBeInViewport();
});
test("分析失败后重试：写前回顾", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚仍保管黄铜罗盘，E2E_ANALYSIS_FAIL_ONCE。");
  const first = await analysis(page, id, "写前回顾", "context_brief", "failed");
  const region = findings(page).getByRole("region", { name: "写前回顾", exact: true });
  await expect(region).toContainText("没有保存部分结果。");
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/analyses/${first.run_id}/retry`));
  await region.getByRole("button", { name: "重试", exact: true }).click();
  const rid = (await (await response).json()).data.run.run_id;
  expect(rid).not.toBe(first.run_id);
  await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${rid}`)).status).toBe("completed");
  const second = await api(page).get(`/projects/${id}/analyses/${rid}`);
  await expect(region).toContainText(second.analysis.summary);
});
