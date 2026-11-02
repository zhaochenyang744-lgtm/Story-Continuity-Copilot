import { api, archiveWorkByApi, createWorkByApi, expect, keepDock, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { box, dock, topbarAssistant } from "./support/assistant";

// v2.2 phase three: the page fixes of the reviews (task 19).

test("作品卡的更多：重命名、归档，不用先进概览", async ({ page }) => {
  await registerAccount(page, "workmanage");
  await createWorkByApi(page, { title: "要改名的书" });
  await createWorkByApi(page, { title: "要归档的书" });
  await page.goto("/projects");
  const row = (title: string) => page.getByRole("main").getByRole("listitem").filter({ hasText: title });
  await row("要改名的书").getByLabel("更多：要改名的书", { exact: true }).click();
  await page.getByRole("menuitem", { name: "重命名", exact: true }).click();
  const rename = page.getByRole("dialog", { name: "重命名作品" });
  await rename.getByRole("textbox", { name: "书名" }).fill("改好名的书");
  await rename.getByRole("button", { name: "保存", exact: true }).click();
  await expect(rename).toHaveCount(0);
  await expect(row("改好名的书")).toBeVisible();
  await expect(row("要改名的书")).toHaveCount(0);
  await row("要归档的书").getByLabel("更多：要归档的书", { exact: true }).click();
  await page.getByRole("menuitem", { name: "归档作品", exact: true }).click();
  const confirm = page.getByRole("dialog", { name: "归档作品" });
  await expect(confirm.getByRole("button", { name: "归档", exact: true })).toHaveClass(/btn-destroy/);
  await confirm.getByRole("button", { name: "归档", exact: true }).click();
  await expect(row("要归档的书")).toHaveCount(0);
  expect((await api(page).get("/projects?status=archived")).projects.map((work: { title: string }) => work.title)).toContain("要归档的书");
});

test("助手面板开着还是关着，刷新后记得；不抢走光标", async ({ page }) => {
  await keepDock(page);
  await registerAccount(page, "dockkeep");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await expect(dock(page)).toBeHidden();
  await topbarAssistant(page).click();
  await expect(box(page)).toBeFocused();
  await page.reload();
  await expect(dock(page)).toBeVisible();
  await expect(topbarAssistant(page)).toHaveAttribute("aria-expanded", "true");
  // Open because the device remembered it: the cursor is not taken from the page.
  await expect(box(page)).not.toBeFocused();
  // Another page of the work: still open.
  await openTab(page, id, "memory");
  await expect(dock(page)).toBeVisible();
  // Shut it, and it stays shut.
  await topbarAssistant(page).click();
  await page.reload();
  await expect(topbarAssistant(page)).toHaveAttribute("aria-expanded", "false");
  await expect(dock(page)).toBeHidden();
});

test("记忆读不出来时面板就是关着的，也不报错", async ({ page }) => {
  await page.addInitScript(() => { Object.defineProperty(window, "localStorage", { get() { throw new Error("blocked"); } }); });
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await registerAccount(page, "dockblocked");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await expect(topbarAssistant(page)).toHaveAttribute("aria-expanded", "false");
  await topbarAssistant(page).click();
  await expect(dock(page)).toBeVisible();
  expect(errors).toEqual([]);
});

test("助手面板的收起提示：手机宽度不写快捷键", async ({ page }) => {
  await registerAccount(page, "dockkbd");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await expect(dock(page).locator("kbd")).toBeVisible();
  await page.setViewportSize({ width: 375, height: 812 });
  await expect(dock(page).locator("kbd")).toBeHidden();
  await expect(dock(page).getByRole("button", { name: "关闭助手", exact: true })).toContainText("收起");
});

test("顶栏「助手」打开时不是实心蓝：浅底加细框", async ({ page }) => {
  await registerAccount(page, "dockblue");
  const id = await sampleWorkId(page);
  await openTab(page, id, "workspace");
  const blue = await page.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-blue)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; });
  await topbarAssistant(page).click();
  await expect(topbarAssistant(page)).toHaveAttribute("aria-expanded", "true");
  expect(await topbarAssistant(page).evaluate((node) => getComputedStyle(node).backgroundColor)).not.toBe(blue);
  expect(await topbarAssistant(page).evaluate((node) => getComputedStyle(node).boxShadow)).not.toBe("none");
});

test("访客次数用完：输入框换成一行说明和「注册」，点它去注册页", async ({ page }) => {
  await startVisitor(page);
  const id = await sampleWorkId(page);
  await page.route("**/api/account/usage", async (route) => {
    const response = await route.fetch();
    const body = await response.json();
    await route.fulfill({ response, json: { ...body, data: { ...body.data, assistant_tasks_remaining: 0 } } });
  });
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  const used = dock(page).locator(".a-used");
  await expect(used).toContainText("访客可以在示例作品上问 3 次，24 小时内已经用完。");
  await expect(box(page)).toHaveCount(0);
  await expect(dock(page).locator(".a-starters button").first()).toBeDisabled();
  await used.getByRole("button", { name: "注册", exact: true }).click();
  await expect(page).toHaveURL(/\/register$/);
});

test("后端连不上：写「暂时连不上服务」和重试，不退回登录页；恢复后重试就回来", async ({ page }) => {
  await registerAccount(page, "offline");
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  await page.route("**/api/auth/session**", (route) => route.abort());
  await page.reload();
  const note = page.getByTestId("service-unreachable");
  await expect(note).toContainText("暂时连不上服务");
  await expect(page).toHaveURL(/\/projects$/);
  await page.unroute("**/api/auth/session**");
  await note.getByRole("button", { name: "重试", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  await expect(note).toHaveCount(0);
});

test("资料的事实行：分类标签挨着名字，不甩到行尾", async ({ page }) => {
  await registerAccount(page, "factrow");
  const id = await sampleWorkId(page);
  await openTab(page, id, "memory");
  const item = page.getByRole("list", { name: "事实列表" }).locator("li").first();
  const name = await item.locator(".fact-head strong").boundingBox();
  const tag = await item.locator(".fact-head .tag").boundingBox();
  const row = await item.boundingBox();
  expect(tag!.x - (name!.x + name!.width)).toBeLessThan(40);
  expect(row!.x + row!.width - (tag!.x + tag!.width)).toBeGreaterThan(200);
});

test("资料的设定：按内容排列，不强行等宽三列", async ({ page }) => {
  await registerAccount(page, "settings3");
  const id = await sampleWorkId(page);
  await openTab(page, id, "memory");
  await page.getByRole("button", { name: /^设定/ }).first().click();
  const groups = page.locator(".setting-group");
  await expect(groups.first()).toBeVisible();
  expect(await page.locator(".setting-grid").evaluate((node) => getComputedStyle(node).columnWidth)).toBe("300px");
});

test("归档的计划：列表里能展开看内容，也能用它的内容新建一条", async ({ page }) => {
  await registerAccount(page, "planarchive");
  const id = await createWorkByApi(page, { title: "计划归档之书" });
  const version = async () => (await api(page).get(`/projects/${id}/author-intent`)).author_context_version as number;
  await api(page).post(`/projects/${id}/author-intent/story-plans`, { base_author_context_version: await version(), title: "旧潮位牌的下落", summary: "拆开背板，看见里面的东西。", goal: "让读者知道牌是被人动过的", status: "planned" });
  const plan = (await api(page).get(`/projects/${id}/author-intent`)).story_plans.find((item: { title: string }) => item.title === "旧潮位牌的下落");
  await api(page).post(`/projects/${id}/author-intent/story-plans/${plan.id}/archive`, { base_author_context_version: await version(), confirm: true });
  await openTab(page, id, "plan");
  await page.getByRole("button", { name: /^已归档 1 条/ }).click();
  const entry = page.locator(".plan-archived").getByRole("button", { name: /旧潮位牌的下落/ });
  await entry.click();
  await expect(page.locator(".plan-archived")).toContainText("拆开背板，看见里面的东西。");
  await expect(page.locator(".plan-archived")).toContainText("让读者知道牌是被人动过的");
  await page.locator(".plan-archived").getByRole("button", { name: "用这条的内容新建计划", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "新建计划" });
  await expect(dialog.getByRole("textbox", { name: "标题" })).toHaveValue("旧潮位牌的下落");
});

test("作品归档只读：概览、章节、计划里不再催着去写、去检查", async ({ page }) => {
  await registerAccount(page, "readonlywords");
  const id = await createWorkByApi(page, { title: "归档只读之书" });
  await archiveWorkByApi(page, id);
  await openTab(page, id, "overview");
  await expect(page.getByRole("button", { name: "去写作页处理", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "去写作页查看", exact: true })).toBeVisible();
  await expect(page.getByText("这一章没有检查结果。", { exact: true })).toBeVisible();
  await expect(page.getByText("没有写下的计划。", { exact: true })).toBeVisible();
  await expect(page.getByText(/在写作页点「检查这一章」/)).toHaveCount(0);
  await openTab(page, id, "sources");
  await expect(page.getByText("这部作品已归档，只能浏览，不能检查。", { exact: true })).toBeVisible();
  await expect(page.getByText(/勾选最多 8 章/)).toHaveCount(0);
  await openTab(page, id, "plan");
  await expect(page.getByText("没有计划。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "写下第一条计划", exact: true })).toHaveCount(0);
});
