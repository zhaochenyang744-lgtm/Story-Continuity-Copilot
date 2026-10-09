import type { Page } from "@playwright/test";
import { api, createWorkByApi, expect, openTab, registerAccount, test } from "./support/app";
import { button, saveBody } from "./support/writing";
import { cardWith, intent, pair, sample, startAnalysis } from "./support/pages";
const plan = (page: Page, title: string) => cardWith(page, title);
async function empty(page: Page) {
  await registerAccount(page, "plan08");
  const id = await createWorkByApi(page, { title: "计划测试" });
  await openTab(page, id, "plan");
  return id;
}
async function addStory(page: Page, title: string) {
  await button(page, "新建计划").click();
  const dialog = page.getByRole("dialog", { name: "新建计划", exact: true });
  await dialog.getByRole("textbox", { name: "标题", exact: true }).fill(title);
  await dialog.getByRole("textbox", { name: "写什么", exact: true }).fill("值班员返回码头。 ");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page.getByText("计划记下了。", { exact: true })).toBeVisible();
}

test("08 示例计划：状态与三类筛选", async ({ page }) => {
  const id = await sample(page, "plan"), context = await intent(page, id);
  await expect(page.getByRole("article").filter({ hasText: "已定" }).first()).toBeVisible();
  await expect(page.getByRole("article").filter({ hasText: "考虑中" }).first()).toBeVisible();
  await pair(page, "plan");
  for (const [label, kind, key] of [["情节", "story", "story_plans"], ["人物", "character", "character_plans"], ["设定", "world", "world_plans"]]) {
    await page.getByRole("navigation", { name: "计划分类", exact: true }).getByRole("button", { name: new RegExp(`^${label}`) }).click();
    expect(new URL(page.url()).searchParams.get("kind")).toBe(kind);
    const expected = context[key].filter((p: any) => !p.archived);
    await expect(page.getByRole("article")).toHaveCount(expected.length);
    for (const row of expected) await expect(plan(page, row.title ?? row.name)).toBeVisible();
  }
});

test("08 新建计划：三种类型的特有字段", async ({ page }) => {
  const id = await empty(page);
  for (const label of ["情节", "人物", "设定"]) {
    await button(page, "新建计划").click();
    const d = page.getByRole("dialog", { name: "新建计划", exact: true });
    await d.getByRole("radio", { name: label, exact: true }).click();
    if (label === "情节") {
      await d.getByLabel("标题", { exact: true }).fill("回到码头");
      await d.getByLabel("写什么", { exact: true }).fill("值班员返回码头。");
      await d.getByLabel("写在第几章", { exact: true }).fill("2");
      await d.getByRole("combobox", { name: "进度", exact: true }).selectOption("in_progress");
    } else if (label === "人物") {
      await d.getByLabel("人物", { exact: true }).fill("值班员");
      await d.getByRole("combobox", { name: "角色", exact: true }).selectOption("ally");
      await d.getByLabel("接下来会怎样变化", { exact: true }).fill("开始帮助船长。");
    } else {
      await d.getByLabel("名称", { exact: true }).fill("航道规则");
      await d.getByRole("combobox", { name: "类别", exact: true }).selectOption("rule");
      await d.getByLabel("内容", { exact: true }).fill("夜间必须点灯。");
    }
    await d.getByRole("button", { name: "保存", exact: true }).click();
    await expect(d).toHaveCount(0);
    await expect(page.getByText("计划记下了。", { exact: true })).toBeVisible();
    const c = await intent(page, id);
    if (label === "情节") expect(c.story_plans).toEqual([expect.objectContaining({ title: "回到码头", summary: "值班员返回码头。", target_chapter_number: 2, status: "in_progress" })]);
    else if (label === "人物") expect(c.character_plans).toEqual([expect.objectContaining({ name: "值班员", role_type: "ally", planned_state: "开始帮助船长。" })]);
    else expect(c.world_plans).toEqual([expect.objectContaining({ name: "航道规则", category: "rule", description: "夜间必须点灯。" })]);
  }
});

test("08 编辑计划：标题内容写入", async ({ page }) => {
  const id = await empty(page);
  await addStory(page, "旧计划");
  const original = (await intent(page, id)).story_plans[0];
  await plan(page, "旧计划").getByRole("button").click();
  await plan(page, "旧计划").getByRole("button", { name: "编辑", exact: true }).click();
  const d = page.getByRole("dialog", { name: "编辑计划", exact: true });
  await d.getByLabel("标题", { exact: true }).fill("新的计划");
  await d.getByRole("textbox", { name: "写什么", exact: true }).fill("船长留在岸上。");
  await d.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("计划改好了。", { exact: true })).toBeVisible();
  expect((await intent(page, id)).story_plans).toEqual([expect.objectContaining({ id: original.id, title: "新的计划", summary: "船长留在岸上。" })]);
});

test("08 已定和考虑中：互转与禁用对照", async ({ page }) => {
  const id = await empty(page);
  await addStory(page, "唯一的计划");
  const pid = (await intent(page, id)).story_plans[0].id;
  const card = plan(page, "唯一的计划");
  await card.getByRole("button").click();
  for (const considering of [true, false, true]) {
    await card.getByRole("button", { name: considering ? "放到考虑中" : "定下来", exact: true }).click();
    await expect.poll(async () => (await api(page).get(`/projects/${id}/plan-states`)).considering.some((p: any) => p.plan_id === pid)).toBe(considering);
    await expect(card.getByText(considering ? "考虑中" : "已定", { exact: true })).toBeVisible();
  }
  await expect(button(page, "对照正文")).toBeDisabled();
  await expect(button(page, "对照正文")).toHaveAttribute("title", "还没有已定的计划；「考虑中」的不参与对照");
});

test("08 计划上移下移：接口与页面顺序", async ({ page }) => {
  const id = await empty(page);
  for (const title of ["第一项", "第二项", "第三项"]) await addStory(page, title);
  const titles = async () => (await intent(page, id)).story_plans.map((p: any) => p.title);
  const card = plan(page, "第二项");
  await card.getByRole("button").click();
  await card.getByRole("button", { name: "上移", exact: true }).click();
  await expect.poll(titles).toEqual(["第二项", "第一项", "第三项"]);
  await expect(page.getByRole("article").nth(0)).toContainText("第二项");
  await card.getByRole("button", { name: "下移", exact: true }).click();
  await expect.poll(titles).toEqual(["第一项", "第二项", "第三项"]);
  await expect(page.getByRole("article").nth(1)).toContainText("第二项");
});

test("08 归档计划：确认与保留记录", async ({ page }) => {
  const id = await empty(page);
  await addStory(page, "暂不采用");
  const pid = (await intent(page, id)).story_plans[0].id;
  const card = plan(page, "暂不采用");
  await card.getByRole("button").click();
  await card.getByRole("button", { name: "归档", exact: true }).click();
  const d = page.getByRole("dialog", { name: "归档「暂不采用」？", exact: true });
  await expect(d).toBeVisible();
  expect((await intent(page, id)).story_plans[0].archived_at).toBeNull();
  await d.getByRole("button", { name: "归档", exact: true }).click();
  await expect(card).toHaveCount(0);
  expect((await intent(page, id)).story_plans.find((p: any) => p.id === pid).archived_at).toEqual(expect.any(String));
});

test("08 新作品对照正文：跳转和分析结果", async ({ page }) => {
  const id = await empty(page);
  await openTab(page, id, "workspace");
  await saveBody(page, id, "值班员返回码头。他把船灯点亮。");
  await openTab(page, id, "plan");
  await addStory(page, "返回码头");
  const result = await startAnalysis(page, id, () => button(page, "对照正文").click());
  expect(result.status, JSON.stringify(result)).toBe("completed");
  expect(result.analysis_type).toBe("plan_alignment");
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace$`));
  const region = page.getByRole("region", { name: "对照计划", exact: true });
  await expect(region).toContainText(result.analysis.summary);
  expect(result.analysis.items).toHaveLength(1);
  await expect(region).toContainText("返回码头");
});
