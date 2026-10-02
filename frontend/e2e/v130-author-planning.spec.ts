import { expect, test, type APIResponse, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin = process.env.E2E_BACKEND_ORIGIN;
if (!backendOrigin) throw new Error("E2E_BACKEND_ORIGIN is required");
const accountPrefix = process.env.E2E_ACCOUNT_PREFIX;
if (!accountPrefix) throw new Error("E2E_ACCOUNT_PREFIX is required");

type ApiEnvelope<T> = { data: T };
type AuthorSnapshot = {
  author_context_version: number;
  story_plans: { id: string; title: string; archived: boolean }[];
  character_plans: { id: string; name: string; archived: boolean }[];
  world_plans: { id: string; name: string; archived: boolean }[];
};

async function data<T>(response: APIResponse): Promise<T> {
  expect(response.ok(), await response.text()).toBe(true);
  return ((await response.json()) as ApiEnvelope<T>).data;
}

async function register(page: Page, displayName = "v1.3.0 作者") {
  const account = `${accountPrefix}plan${Date.now()}${Math.floor(Math.random() * 1000)}`.toLowerCase();
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill(displayName);
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
}

async function createProject(page: Page, title: string) {
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "新建作品", exact: true }).first().click();
  await page.getByRole("textbox", { name: /作品名称/ }).fill(title);
  await page.getByRole("textbox", { name: /简介/ }).fill("验证作者规划与正文档案严格分离。");
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  return page.url().match(/\/projects\/([^/]+)\//)?.[1] ?? "";
}

async function saveStory(page: Page, values: { title: string; summary: string; goal: string; target: string }) {
  const dialog = page.getByRole("dialog", { name: "新建故事规划" });
  await dialog.getByRole("textbox", { name: "标题", exact: true }).fill(values.title);
  await dialog.getByRole("textbox", { name: "摘要", exact: true }).fill(values.summary);
  await dialog.getByRole("textbox", { name: "创作目标", exact: true }).fill(values.goal);
  await dialog.getByRole("spinbutton", { name: "目标章节", exact: true }).fill(values.target);
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

async function saveCharacter(page: Page, name: string) {
  const dialog = page.getByRole("dialog", { name: "新建角色规划" });
  await dialog.getByRole("textbox", { name: "姓名", exact: true }).fill(name);
  await dialog.getByRole("combobox", { name: "角色类型", exact: true }).selectOption("ally");
  await dialog.getByRole("textbox", { name: "角色目标", exact: true }).fill("找回失踪的航海日志");
  await dialog.getByRole("textbox", { name: "计划状态", exact: true }).fill("暂时隐瞒潮汐密码");
  await dialog.getByRole("textbox", { name: "备注", exact: true }).fill("不要提前揭示身份");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

async function saveWorld(page: Page, name: string) {
  const dialog = page.getByRole("dialog", { name: "新建设定规划" });
  await dialog.getByRole("textbox", { name: "名称", exact: true }).fill(name);
  await dialog.getByRole("combobox", { name: "分类", exact: true }).selectOption("rule");
  await dialog.getByRole("textbox", { name: "描述", exact: true }).fill("只有第三次雾钟响起后才会开启。");
  await dialog.getByRole("textbox", { name: "备注", exact: true }).fill("后续章节使用，尚未成为正文事实");
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(dialog).toHaveCount(0);
}

async function screenshot(page: Page, name: string) {
  if (!process.env.E2E_OUTPUT_DIR) return;
  await page.screenshot({ path: path.join(process.env.E2E_OUTPUT_DIR, name), fullPage: true });
}

async function expectNoOverflow(page: Page) {
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.getBoundingClientRect().width)).toBe(true);
}

test("v1.3.0 author planning keeps future plans editable and written records read-only", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const statsBefore = (await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json()) as { provider_calls: number; provider_http_calls: number };
  await register(page);
  const projectId = await createProject(page, "潮汐之后");
  expect(projectId).not.toBe("");

  const [outlineBefore, charactersBefore, worldBefore] = await Promise.all([
    data<Record<string, unknown>>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/outline`)),
    data<Record<string, unknown>>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/characters`)),
    data<Record<string, unknown>>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/world`)),
  ]);

  await page.getByRole("button", { name: "大纲", exact: true }).click();
  await expect(page.getByRole("button", { name: "创作规划", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(page.getByText("还没有创作规划。这里记录作者对后续故事的安排，不会自动成为正文事实。", { exact: true })).toBeVisible();
  await expect(page.getByText("尚无规划版本", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "新建规划", exact: true }).click();
  await saveStory(page, { title: "第一幕回港", summary: "船员重返灰港。", goal: "找出雾钟来源。", target: "12" });
  await expect(page.getByText("规划第 1 版", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建规划", exact: true }).click();
  await saveStory(page, { title: "第二幕潮门", summary: "潮门在午夜打开。", goal: "让两条线索交汇。", target: "14" });
  await expect(page.getByText("规划第 2 版", { exact: true })).toBeVisible();

  await page.getByRole("button", { name: "编辑 第一幕回港", exact: true }).click();
  const storyEdit = page.locator('.author-plan-dialog[aria-label="编辑故事规划"]');
  await expect(storyEdit).toBeVisible();
  await storyEdit.getByRole("textbox", { name: "摘要", exact: true }).fill("船员带着破损罗盘重返灰港。");
  await storyEdit.getByRole("button", { name: "保存", exact: true }).click();
  await expect(storyEdit).toHaveCount(0);
  await expect(page.getByText("规划第 3 版", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "上移 第二幕潮门", exact: true }).click();
  await expect(page.getByText("规划第 4 版", { exact: true })).toBeVisible();
  await expect(page.locator(".author-plan-list h2").first()).toHaveText("第二幕潮门");
  await screenshot(page, "author-planning-story-desktop.png");

  await page.getByRole("button", { name: "归档 第一幕回港", exact: true }).click();
  const archiveStory = page.getByRole("dialog", { name: "归档 第一幕回港" });
  await archiveStory.getByRole("button", { name: "确认归档", exact: true }).click();
  await expect(archiveStory).toHaveCount(0);
  await expect(page.getByText("规划第 5 版", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "第一幕回港", exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "查看已归档", exact: true }).click();
  await expect(page.getByRole("heading", { name: "第一幕回港", exact: true })).toBeVisible();
  await expect(page.locator('[data-author-plan-id]').filter({ hasText: "第一幕回港" })).toContainText("已归档");
  await page.getByRole("button", { name: "隐藏已归档", exact: true }).click();

  const snapshotAtFive = await data<AuthorSnapshot>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/author-intent?include_archived=true`));
  const secondStory = snapshotAtFive.story_plans.find((item) => item.title === "第二幕潮门");
  if (!secondStory) throw new Error("second story plan missing");
  await page.getByRole("button", { name: "编辑 第二幕潮门", exact: true }).click();
  const conflictDialog = page.locator('.author-plan-dialog[aria-label="编辑故事规划"]');
  await expect(conflictDialog).toBeVisible();
  await conflictDialog.getByRole("textbox", { name: "标题", exact: true }).fill("未提交输入保留");
  const externalWrite = await page.request.patch(`${backendOrigin}/api/projects/${projectId}/author-intent/story-plans/${secondStory.id}`, {
    headers: { "Idempotency-Key": randomUUID() },
    data: { base_author_context_version: 5, title: "另一窗口版本" },
  });
  expect(externalWrite.status()).toBe(200);
  await conflictDialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(conflictDialog.getByRole("alert")).toHaveText("内容已在其他窗口更新，已载入最新版本，请确认后重试。");
  await expect(conflictDialog.getByRole("textbox", { name: "标题", exact: true })).toHaveValue("未提交输入保留");
  await expect(page.getByText("规划第 6 版", { exact: true })).toBeVisible();
  const afterConflict = await data<AuthorSnapshot>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/author-intent?include_archived=true`));
  expect(afterConflict.story_plans.find((item) => item.id === secondStory.id)?.title).toBe("另一窗口版本");
  expect(afterConflict.author_context_version).toBe(6);
  await conflictDialog.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page.getByRole("heading", { name: "另一窗口版本", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "已写章节", exact: true }).click();
  await expect(page.locator('.author-reference-pane[aria-label="已写章节"]')).toBeVisible();
  await expect(page.getByText("此作品还没有大纲节点。", { exact: true })).toBeVisible();
  await expect(page.getByText("另一窗口版本", { exact: true })).toHaveCount(0);
  await page.getByRole("button", { name: "创作规划", exact: true }).click();

  await page.getByRole("button", { name: "角色库", exact: true }).click();
  await expect(page.getByText("还没有角色规划。可以先记录角色接下来要追求的目标与计划状态。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建角色规划", exact: true }).click();
  await saveCharacter(page, "温岚");
  await expect(page.getByText("规划第 7 版", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "编辑 温岚", exact: true }).click();
  const characterEdit = page.locator('.author-plan-dialog[aria-label="编辑角色规划"]');
  await expect(characterEdit).toBeVisible();
  await characterEdit.getByRole("textbox", { name: "备注", exact: true }).fill("已交出罗盘，但仍保留密码");
  await characterEdit.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("规划第 8 版", { exact: true })).toBeVisible();
  await screenshot(page, "author-planning-character-desktop.png");
  await page.getByRole("button", { name: "归档 温岚", exact: true }).click();
  await page.getByRole("dialog", { name: "归档 温岚" }).getByRole("button", { name: "确认归档", exact: true }).click();
  await expect(page.getByText("规划第 9 版", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "正文档案", exact: true }).click();
  await expect(page.locator(".character-page")).toBeVisible();
  await expect(page.getByText("温岚", { exact: true })).toHaveCount(0);

  await page.getByRole("button", { name: "世界观", exact: true }).click();
  await expect(page.getByText("还没有设定规划。可以先记录后续创作准备使用的世界设定。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "新建设定规划", exact: true }).click();
  await saveWorld(page, "北潮门");
  await expect(page.getByText("规划第 10 版", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "编辑 北潮门", exact: true }).click();
  const worldEdit = page.locator('.author-plan-dialog[aria-label="编辑设定规划"]');
  await expect(worldEdit).toBeVisible();
  await worldEdit.getByRole("textbox", { name: "备注", exact: true }).fill("第十四章后才可写入正文");
  await worldEdit.getByRole("button", { name: "保存", exact: true }).click();
  await expect(page.getByText("规划第 11 版", { exact: true })).toBeVisible();
  await screenshot(page, "author-planning-world-desktop.png");
  await page.getByRole("button", { name: "归档 北潮门", exact: true }).click();
  await page.getByRole("dialog", { name: "归档 北潮门" }).getByRole("button", { name: "确认归档", exact: true }).click();
  await expect(page.getByText("规划第 12 版", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "正文资料", exact: true }).click();
  await expect(page.locator(".world-page")).toBeVisible();
  await expect(page.getByText("北潮门", { exact: true })).toHaveCount(0);

  const [outlineAfter, charactersAfter, worldAfter] = await Promise.all([
    data<Record<string, unknown>>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/outline`)),
    data<Record<string, unknown>>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/characters`)),
    data<Record<string, unknown>>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/world`)),
  ]);
  expect(outlineAfter).toEqual(outlineBefore);
  expect(charactersAfter).toEqual(charactersBefore);
  expect(worldAfter).toEqual(worldBefore);
  expect(JSON.stringify({ outlineAfter, charactersAfter, worldAfter })).not.toContain("另一窗口版本");
  expect(JSON.stringify({ outlineAfter, charactersAfter, worldAfter })).not.toContain("温岚");
  expect(JSON.stringify({ outlineAfter, charactersAfter, worldAfter })).not.toContain("北潮门");

  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "大纲", exact: true }).click();
  await expect(page.getByRole("heading", { name: "另一窗口版本", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "新建规划", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /^(编辑|上移|下移|归档) / })).toHaveCount(0);
  await expect(page.getByText("移动端可以浏览作者规划；请在桌面端创建、编辑、排序或归档。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "已写章节", exact: true }).click();
  await expect(page.locator('.author-reference-pane[aria-label="已写章节"]')).toBeVisible();
  await expect(page.getByText("此作品还没有大纲节点。", { exact: true })).toBeVisible();
  await expectNoOverflow(page);
  await screenshot(page, "author-planning-mobile-390.png");

  const tutorialResponse = await page.request.get(`${backendOrigin}/api/onboarding`);
  const tutorial = await data<{ tutorial: { project_id: string } }>(tutorialResponse);
  const tutorialAuthor = await data<AuthorSnapshot>(await page.request.get(`${backendOrigin}/api/projects/${tutorial.tutorial.project_id}/author-intent`));
  expect(tutorialAuthor.story_plans).toEqual([]);
  expect(tutorialAuthor.character_plans).toEqual([]);
  expect(tutorialAuthor.world_plans).toEqual([]);

  const statsAfter = (await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json()) as { provider_calls: number; provider_http_calls: number };
  expect(statsAfter).toMatchObject({ provider_calls: statsBefore.provider_calls, provider_http_calls: 0 });
});

test("v1.3.0 wide operational pages expand and center while bounded forms stay centered", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 900 });
  await register(page, "宽屏作者");
  const homeGeometry = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>("main")?.getBoundingClientRect();
    const content = document.querySelector<HTMLElement>(".home-page")?.getBoundingClientRect();
    if (!main || !content) throw new Error("home geometry missing");
    return { left: content.left, width: content.width, centerDelta: Math.abs((content.left + content.right) / 2 - (main.left + main.right) / 2) };
  });
  // visual-system.css: --global-page-max is 1210px, with a 1px geometry tolerance.
  expect(homeGeometry.width).toBeGreaterThanOrEqual(1209);
  expect(homeGeometry.width).toBeLessThanOrEqual(1211);
  expect(homeGeometry.centerDelta).toBeLessThanOrEqual(1);
  await expectNoOverflow(page);
  await screenshot(page, "wide-01-home-1920.png");

  await page.setViewportSize({ width: 2560, height: 900 });
  const homeLeftAt2560 = await page.locator(".home-page").evaluate((node) => node.getBoundingClientRect().left);
  expect(homeLeftAt2560).toBeGreaterThan(homeGeometry.left + 250);
  await expectNoOverflow(page);

  await page.setViewportSize({ width: 1920, height: 900 });
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await page.getByRole("button", { name: "新建作品", exact: true }).first().click();
  const centeredForm = await page.getByRole("region", { name: "新建作品表单", exact: true }).evaluate((node) => {
    const box = node.getBoundingClientRect();
    const main = node.closest("main")?.getBoundingClientRect();
    if (!main) throw new Error("main geometry missing");
    return { centerDelta: Math.abs((box.left + box.right) / 2 - (main.left + main.right) / 2), width: box.width };
  });
  expect(centeredForm.centerDelta).toBeLessThanOrEqual(1);
  expect(centeredForm.width).toBeLessThanOrEqual(1211);
  expect(centeredForm.width).toBeGreaterThanOrEqual(1209);
  await expectNoOverflow(page);
  await page.getByRole("textbox", { name: /作品名称/ }).fill("宽屏锚点验证");
  await page.getByRole("button", { name: "创建并进入作品", exact: true }).click();
  await expect(page).toHaveURL(/\/overview$/);
  await expect(page.locator(".project-page")).toBeVisible();

  const projectGeometry = await page.evaluate(() => {
    const main = document.querySelector<HTMLElement>("main")?.getBoundingClientRect();
    const content = document.querySelector<HTMLElement>(".project-page")?.getBoundingClientRect();
    if (!main || !content) throw new Error("project geometry missing");
    return { left: content.left, width: content.width, centerDelta: Math.abs((content.left + content.right) / 2 - (main.left + main.right) / 2) };
  });
  expect(projectGeometry.width).toBeGreaterThan(1200);
  expect(projectGeometry.width).toBeLessThanOrEqual(1441);
  expect(projectGeometry.centerDelta).toBeLessThanOrEqual(1);
  await expectNoOverflow(page);
  await screenshot(page, "wide-02-project-overview-1920.png");

  await page.getByRole("button", { name: "大纲", exact: true }).click();
  await expect(page.getByRole("button", { name: "创作规划", exact: true })).toHaveAttribute("aria-pressed", "true");
  const outlineLeft = await page.locator(".project-page").evaluate((node) => node.getBoundingClientRect().left);
  expect(Math.abs(outlineLeft - projectGeometry.left)).toBeLessThanOrEqual(1);
  await expectNoOverflow(page);
  await screenshot(page, "wide-03-outline-planning-1920.png");

  await page.setViewportSize({ width: 2560, height: 900 });
  const projectAt2560 = await page.locator(".project-page").evaluate((node) => ({ left: node.getBoundingClientRect().left, width: node.getBoundingClientRect().width }));
  expect(projectAt2560.left).toBeGreaterThan(projectGeometry.left + 250);
  expect(projectAt2560.width).toBeLessThanOrEqual(1441);
  await expectNoOverflow(page);
});
