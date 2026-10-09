import { createWorkByApi, expect, expectNoHorizontalOverflow, logout, openTab, registerAccount, sampleWorkId, shot, tabOrder, test } from "./support/app";
import { button, saveBody } from "./support/writing";
import { evidence, noWriteControls, view } from "./support/pages";

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
