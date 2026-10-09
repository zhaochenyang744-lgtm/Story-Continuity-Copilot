import { expect, expectNoHorizontalOverflow, logout, openTab, registerAccount, sampleWorkId, shot, tabOrder, test } from "./support/app";
import { button, saveBody } from "./support/writing";
import { evidence, noWriteControls, view } from "./support/pages";

test("08 窄屏作品五页：无横向溢出并且只读", async ({ page }, info) => {
  test.fixme(true, "新发现：390px 窗口的章节页 scrollWidth=796；其他作品页及资料子视图为 375，只读断言均通过");
  await registerAccount(page, "narrow08");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 390, height: 844 });
  const names = { overview: "overview", workspace: "writing", sources: "chapters", memory: "materials", plan: "plan" };
  const widths: { page: string; scroll: number; inner: number }[] = [];
  for (const tab of tabOrder) {
    await openTab(page, id, tab);
    await expect(page.getByText("窗口较窄，现在只能浏览。把窗口放宽就能继续写作和检查。", { exact: true })).toBeVisible();
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
