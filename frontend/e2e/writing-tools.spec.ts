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
test("对照计划：结果是检查结果顶部的一块，逐条结果与后端一致，「×」只收起", async ({ page }) => {
  const id = await setup(page), result = await analysis(page, id, "对照计划", "plan_alignment");
  // The result is not a tab of its own: it is the top block of the findings column (the assistant has its own panel).
  await expect(findings(page).getByRole("tab")).toHaveCount(0);
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
  // Without a plan there is no comparison block either.
  await expect(findings(page).getByRole("tab")).toHaveCount(0);
  await expect(findings(page).getByTestId("plan-block")).toHaveCount(0);
});

test("右栏只有检查结果：一个标题，没有标签；对照计划的结果在它上面", async ({ page }) => {
  const id = await setup(page);
  await expect(findings(page).getByRole("tablist")).toHaveCount(0);
  await expect(findings(page).getByRole("heading", { name: /^检查结果/ })).toBeVisible();
  await analysis(page, id, "对照计划", "plan_alignment");
  await expect(findings(page).getByTestId("plan-block")).toBeVisible();
  await expect(findings(page).getByRole("tab")).toHaveCount(0);
});

test("右栏的切换：右栏不在视口里时（窄窗口里它在正文下面），点页头按钮会滚到它", async ({ page }) => {
  const id = await setup(page);
  // (A wide window keeps the column on screen from the top bar down; in a narrower one it is a pane under the draft.)
  await page.setViewportSize({ width: 900, height: 600 });
  const side = page.getByRole("complementary", { name: "检查与助手", exact: true });
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
