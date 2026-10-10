import { advanceTour, api, createWorkByApi, expect, expectNoHorizontalOverflow, logout, openTab, registerAccount, sampleWorkId, shot, tabOrder, test } from "./support/app";
import { beginCheck, button, findings, finishCheck, run, saveBody, selectIssue } from "./support/writing";
import { evidence, noWriteControls, pair, view } from "./support/pages";

for (const width of [390, 1024, 1280]) test(`12 O ${width} 五页顶栏单行、标签没有滚动条`, async ({ page }, info) => {
  await registerAccount(page, `o${width}`);
  const id = await createWorkByApi(page, { title: "这是一部名字特别特别长的长篇小说，用来检查中等宽度的作品顶栏" });
  await page.setViewportSize({ width, height: width === 390 ? 844 : 960 });
  for (const tab of tabOrder) {
    await openTab(page, id, tab);
    const banner = page.getByRole("banner");
    const controls = [banner.getByRole("button", { name: "首页", exact: true }), banner.getByRole("button", { name: /^更换当前作品：/ }), banner.getByRole("button", { name: /^切换到/ }), banner.getByRole("button", { name: /^账号菜单：/ })];
    const boxes = await Promise.all(controls.map(c => c.boundingBox()));
    const centres = boxes.map(b => b!.y + b!.height / 2);
    const tabs = await page.getByRole("navigation", { name: "作品", exact: true }).evaluate(e => ({ scroll: e.scrollWidth, client: e.clientWidth, top: e.getBoundingClientRect().top }));
    await evidence(info, `${width}-${tab}`, { boxes, tabs });
    expect.soft(Math.max(...centres) - Math.min(...centres)).toBeLessThan(20);
    expect.soft(tabs.scroll).toBeLessThanOrEqual(tabs.client);
    if (width >= 1024) expect.soft(tabs.top).toBeLessThan(boxes[0]!.y + boxes[0]!.height);
    await shot(page, `12-O-${tab}-${width}-day`, false);
  }
});

test("08 窄屏作品五页：无横向溢出并且只读", async ({ page }, info) => {
  await registerAccount(page, "narrow08");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const names = { overview: "overview", workspace: "writing", sources: "chapters", memory: "materials", plan: "plan" };
  const widths: { page: string; scroll: number; inner: number }[] = [];
  for (const tab of tabOrder) {
    await openTab(page, id, tab);
    await expect(page.getByText("窗口较窄，现在只能浏览。把窗口放宽就能继续写作和检查。", { exact: true })).toBeVisible();
    await expectOneLineTopBar(page);
    await shot(page, `${names[tab]}-390`, false);
    widths.push({ page: tab, ...await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: innerWidth })) });
    await expectNoHorizontalOverflow(page, true);
    if (tab === "workspace") {
      await expect(page.getByRole("textbox", { name: "草稿正文（只读）", exact: true })).toHaveAttribute("contenteditable", "false");
      await expect(page.getByRole("textbox", { name: "草稿正文（只读）", exact: true })).toHaveAttribute("aria-readonly", "true");
    }
    if (tab === "plan") for (const card of await page.getByRole("article").all()) await card.getByRole("button").first().click();
    await noWriteControls(page, /^(保存|检查这一章|再检查一次|不是问题|保留原意|保留变化|采用改法|新建计划|编辑|归档|记下|确认|检查选中的章节)$/);
    if (tab === "memory") for (const [name, value] of [["人物", "people"], ["设定", "settings"], ["伏笔", "threads"], ["问一问", "ask"]]) {
      await view(page, name, value);
      const expand = page.getByRole("button", { name: /^相关事实 / });
      const count = await expand.count();
      for (let i = 0; i < count; i++) await expand.first().click();
      await noWriteControls(page, /^(添加|保存|归档|管理分类|从正文里找伏笔|记一条伏笔|记下|编辑|看会影响什么|问)$/);
      widths.push({ page: `memory:${value}`, ...await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: innerWidth })) });
      await expectNoHorizontalOverflow(page, true);
    }
  }
  await evidence(info, "narrow-widths", widths);
});

test("08 窄屏公共页面：首页作品管理登录", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await registerAccount(page, "public390");
  await expectNoHorizontalOverflow(page);
  await shot(page, "home-390", false);
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  await expectNoHorizontalOverflow(page);
  await shot(page, "works-390", false);
  await logout(page);
  await expectNoHorizontalOverflow(page);
  await shot(page, "login-390", false);
});

test("08 从窄变宽：不刷新恢复写作和检查", async ({ page }) => {
  await registerAccount(page, "resize08");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, id, "workspace");
  const editor = page.getByRole("textbox", { name: "草稿正文", exact: true });
  await expect(page.getByRole("textbox", { name: "草稿正文（只读）", exact: true })).toHaveAttribute("contenteditable", "false");
  let navigations = 0;
  page.on("framenavigated", frame => { if (frame === page.mainFrame()) navigations++; });
  await page.setViewportSize({ width: 1440, height: 960 });
  await expect(editor).toHaveAttribute("contenteditable", "true");
  await expect(button(page, "再检查一次")).toBeEnabled();
  await saveBody(page, id, "温岚保管黄铜罗盘。放宽窗口后继续写作。");
  expect(navigations).toBe(0);
});

/** Logo, work switch, theme switch and avatar share the first line; the five tabs sit on the line below. */
async function expectOneLineTopBar(page: import("@playwright/test").Page) {
  const boxes = await Promise.all([
    page.getByRole("button", { name: "首页", exact: true }),
    page.getByRole("button", { name: /^更换当前作品：/ }),
    page.getByRole("button", { name: /^切换到(夜间|日间)模式$/ }),
    page.getByRole("button", { name: /^账号菜单：/ }),
  ].map(item => item.boundingBox()));
  const tabs = await page.getByRole("navigation", { name: "作品", exact: true }).boundingBox();
  expect(tabs).not.toBeNull();
  const centres = boxes.map(box => box!.y + box!.height / 2);
  expect(Math.max(...centres) - Math.min(...centres), "logo、作品、主题开关、头像在同一行").toBeLessThan(20);
  expect(Math.max(...boxes.map(box => box!.y + box!.height)), "第一行在标签行上方").toBeLessThanOrEqual(tabs!.y + 1);
  expect(boxes[3]!.x + boxes[3]!.width, "头像在窗口内").toBeLessThanOrEqual(390);
}

test("08 窄屏顶栏：作品名很长时截断，不换行", async ({ page }) => {
  await registerAccount(page, "topbar390");
  const id = await createWorkByApi(page, { title: "这是一部名字特别特别长的长篇小说，用来检查窄屏顶栏" });
  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, id, "overview");
  await expectOneLineTopBar(page);
  const label = page.getByRole("button", { name: /^更换当前作品：/ }).locator("span");
  expect(await label.evaluate(e => e.scrollWidth > e.clientWidth), "作品名被截断（带省略号）").toBe(true);
  await expectNoHorizontalOverflow(page);
});

test("13 S 900 宽可写作保存检查决定、勾选章节、新建伏笔与计划", async ({ page }) => {
  await registerAccount(page, "medium13");
  const id = await sampleWorkId(page);
  await advanceTour(page, id, 4);
  await page.setViewportSize({ width: 900, height: 900 });
  await openTab(page, id, "workspace");
  await expect(page.getByText("窗口较窄，现在只能浏览。把窗口放宽就能继续写作和检查。", { exact: true })).toHaveCount(0);
  await saveBody(page, id, "温岚把黄铜罗盘放在窗边。E2E_SUGGEST。");
  const runId = await beginCheck(page, id);
  await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: /^检查结果/ }).click();
  const result = await finishCheck(page, id, runId);
  expect(result.issues.length).toBeGreaterThan(0);
  await selectIssue(page, result.issues[0]);
  await findings(page).getByRole("button", { name: "不是问题", exact: true }).click();
  await expect.poll(async () => (await run(page, id, runId)).issues[0].decision?.decision).toBe("false_positive");
  await expectNoHorizontalOverflow(page);
  await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "正文", exact: true }).click();
  await pair(page, "13-S-writing-900");

  await openTab(page, id, "sources");
  await page.getByRole("checkbox", { name: "选择第 1 章", exact: true }).check();
  await expect(page.getByTestId("chapter-selection")).toContainText("1 / 8 章");
  await expect(button(page, "检查选中的章节")).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  await pair(page, "13-S-chapters-900");

  await openTab(page, id, "memory");
  await view(page, "伏笔", "threads");
  await button(page, "记一条伏笔").click();
  await page.getByRole("textbox", { name: "标题", exact: true }).fill("窄窗里的纸船");
  await page.getByRole("textbox", { name: "说明", exact: true }).fill("值班员在窗台留下一只蓝色纸船。");
  await expectNoHorizontalOverflow(page);
  await button(page, "记下").click();
  await expect(page.getByText("伏笔记下了。", { exact: true })).toBeVisible();
  expect((await api(page).get("/projects/" + id + "/foreshadows?include_archived=true")).records.some((r: {title: string}) => r.title === "窄窗里的纸船")).toBe(true);
  await expectNoHorizontalOverflow(page);
  await pair(page, "13-S-materials-900");

  await openTab(page, id, "plan");
  await expect(button(page, "新建计划")).toBeEnabled();
  await expectNoHorizontalOverflow(page);
  await button(page, "新建计划").click();
  const planDialog = page.getByRole("dialog", { name: "新建计划", exact: true });
  await planDialog.getByRole("textbox", { name: "标题", exact: true }).fill("窗前的新航线");
  await planDialog.getByRole("textbox", { name: "写什么", exact: true }).fill("值班员带着纸船走向码头。");
  await expectNoHorizontalOverflow(page);
  await planDialog.getByRole("button", { name: "保存", exact: true }).click();
  await expect(planDialog).toHaveCount(0);
  expect((await api(page).get("/projects/" + id + "/author-intent?include_archived=true")).story_plans.some((p: {title: string}) => p.title === "窗前的新航线")).toBe(true);
  await pair(page, "13-S-plan-900");
});

test("13 S 768 可写、767 只读；1023 保留正文和检查结果切换", async ({ page }) => {
  await registerAccount(page, "boundary13");
  const id = await sampleWorkId(page);
  await openTab(page, id, "workspace");
  for (const width of [768, 767, 1023]) {
    await page.setViewportSize({ width, height: 900 });
    const readOnly = width < 768;
    await expect(page.getByRole("textbox", { name: readOnly ? "草稿正文（只读）" : "草稿正文", exact: true })).toHaveAttribute("contenteditable", String(!readOnly));
    await expect(page.getByText("窗口较窄，现在只能浏览。把窗口放宽就能继续写作和检查。", { exact: true })).toHaveCount(readOnly ? 1 : 0);
    await expect(page.getByRole("navigation", { name: "切换内容", exact: true })).toBeVisible();
    await expectNoHorizontalOverflow(page);
  }
  await advanceTour(page, id, 4);
  await page.reload();
  for (const width of [768, 767]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.getByRole("note").filter({ hasText: "手机上可以浏览完整依据；请在电脑上继续作出决定。" })).toHaveCount(width < 768 ? 1 : 0);
  }
});
