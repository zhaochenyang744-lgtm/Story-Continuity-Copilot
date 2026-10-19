import { api, button, expect, findings, saveBody, setup, shot, test } from "./support/writing";
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
test("对照计划：结果是助手标签顶部的一块，逐条结果与后端一致，「×」只收起", async ({ page }) => {
  const id = await setup(page), result = await analysis(page, id, "对照计划", "plan_alignment");
  // The result is not a tab of its own any more: the column switches to the assistant and shows it at the top.
  await expect(tab(page, "助手")).toHaveAttribute("aria-selected", "true");
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/, "助手"]);
  const block = findings(page).getByTestId("plan-block");
  await expect(block).toBeVisible();
  await expect(block.getByText(/^对照计划 · \d{1,2}:\d{2}$/)).toBeVisible();
  const region = block.getByRole("region", { name: "对照计划", exact: true });
  await expect(region).toBeVisible();
  await expect(region).toContainText(result.analysis.summary);
  expect(result.analysis.items.length).toBeGreaterThan(0);
  for (const item of result.analysis.items) await expect(region.getByText(item.story_plan_title, { exact: true })).toBeVisible();
  await shot(page, "writing-plan-alignment-day", false);
  // 「×」 only folds the block away; the result stays and 展开 brings it back.
  await block.getByRole("button", { name: "收起对照计划", exact: true }).click();
  await expect(region).toBeHidden();
  await expect(block.getByText(/^对照计划 · /)).toBeVisible();
  await block.getByRole("button", { name: "展开", exact: true }).click();
  await expect(region).toBeVisible();
  await expect(region).toContainText(result.analysis.summary);
  // A draft changed after the comparison makes it say so, as before.
  await saveBody(page, id, "温岚仍保管黄铜罗盘，改过的草稿。");
  await expect(region).toContainText("草稿改过，结果可能过时");
});
test("没有计划时：不显示对照计划入口", async ({ page }) => {
  const id = await setup(page, false), plans = await api(page).get(`/projects/${id}/author-intent?include_archived=true`);
  expect(plans.story_plans).toHaveLength(0);
  await expect(button(page, "对照计划")).toHaveCount(0);
  // Without a plan there is no such tab either: the findings tab stands alone.
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/, "助手"]);
  await expect(tab(page, "对照计划")).toHaveCount(0);
});

test("右栏的切换：只有「检查结果」「助手」两项；方向键、Home、End 在两项之间移动，Tab 进入面板", async ({ page }) => {
  const id = await setup(page);
  await expect(findings(page).getByRole("tablist", { name: "右栏内容", exact: true })).toBeVisible();
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/, "助手"]);
  await expect(tab(page, /^检查结果/)).toHaveAttribute("aria-selected", "true");
  // 写前回顾 and 对照计划 start in the assistant; the strip stays at two.
  await analysis(page, id, "对照计划", "plan_alignment");
  await expect(tab(page, "助手")).toHaveAttribute("aria-selected", "true");
  await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/, "助手"]);
  await expect(tab(page, "助手")).toHaveAttribute("tabindex", "0");
  await expect(tab(page, /^检查结果/)).toHaveAttribute("tabindex", "-1");
  // Only the chosen tab is in the tab order; the arrow keys move and choose, and wrap round.
  await tab(page, "助手").focus();
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, /^检查结果/)).toBeFocused();
  await expect(tab(page, /^检查结果/)).toHaveAttribute("aria-selected", "true");
  await expect(findings(page).getByRole("tabpanel")).toHaveCount(1);
  await page.keyboard.press("ArrowRight");
  await expect(tab(page, "助手")).toBeFocused();
  await expect(tab(page, "助手")).toHaveAttribute("aria-selected", "true");
  await expect(findings(page).getByTestId("plan-block")).toBeVisible();
  await page.keyboard.press("ArrowLeft");
  await expect(tab(page, /^检查结果/)).toBeFocused();
  await page.keyboard.press("End");
  await expect(tab(page, "助手")).toBeFocused();
  await page.keyboard.press("Home");
  await expect(tab(page, /^检查结果/)).toBeFocused();
  await page.keyboard.press("ArrowLeft");
  await expect(tab(page, "助手")).toBeFocused();
  // Tab leaves the strip for the chosen panel's content.
  await page.keyboard.press("Tab");
  await expect.poll(() => page.evaluate(() => Boolean(document.activeElement?.closest("[role=tabpanel]")))).toBe(true);
});

test("右栏的切换：右栏不在视口里时，点页头按钮会滚到它", async ({ page }) => {
  const id = await setup(page);
  await page.setViewportSize({ width: 1440, height: 400 });
  const side = page.getByRole("complementary", { name: "检查与回顾", exact: true });
  await expect(side).not.toBeInViewport({ ratio: 0.2 });
  await analysis(page, id, "对照计划", "plan_alignment");
  await expect(side).toBeInViewport({ ratio: 0.2 });
  await expect(findings(page).getByRole("region", { name: "对照计划", exact: true })).toBeInViewport();
});
test("分析失败后重试：对照计划", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚仍保管黄铜罗盘，E2E_ANALYSIS_FAIL_ONCE。");
  const first = await analysis(page, id, "对照计划", "plan_alignment", "failed");
  const region = findings(page).getByRole("region", { name: "对照计划", exact: true });
  await expect(region).toContainText("这次对照没有完成，没有留下任何结果。");
  await expect(region).not.toContainText(/结构|校验|写入|[Pp]rovider/);
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith(`/analyses/${first.run_id}/retry`));
  await region.getByRole("button", { name: "重试", exact: true }).click();
  const rid = (await (await response).json()).data.run.run_id;
  expect(rid).not.toBe(first.run_id);
  await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${rid}`)).status).toBe("completed");
  const second = await api(page).get(`/projects/${id}/analyses/${rid}`);
  await expect(region).toContainText(second.analysis.summary);
});
