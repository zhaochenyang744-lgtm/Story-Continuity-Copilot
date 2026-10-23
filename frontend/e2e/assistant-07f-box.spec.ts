import type { Page } from "@playwright/test";
import { expect, openTab, registerAccount, sampleWorkId, shot, test } from "./support/app";
import { allowance, ask, askForFix, box, checkedWork, chip, chooseMode, finished, openAssistantTab, openPlus, select, selectedWords, send, stopButton, tasks, thread, toolbar, topbarAssistant } from "./support/assistant";
import { runningView, serveTasks } from "./support/assistant-mock";
import { setup } from "./support/writing";

// 07f, the box the author writes in: the bar keeps its shape when the box has focus (01), the cost never loses a digit (11), a fix for one
// finding reads only that finding (05), 查前文矛盾 takes the selected words by itself (03), the stop key stays dark under the pointer (10),
// the menus keep their focus ring and light one entry at a time (16), and open in the direction that has room (32).

const colourOf = (page: Page, value: string) => page.evaluate((expression) => {
  const probe = document.createElement("i");
  probe.style.color = expression;
  document.body.append(probe);
  const colour = getComputedStyle(probe).color;
  probe.remove();
  return colour;
}, value);

/** Where the parts of the bar are and how big, for comparing the box with and without focus. */
const bar = (page: Page) => thread(page).evaluate((root) => {
  // Measured from the box's own corner, so that the page scrolling a little when the box takes focus does not count as the bar moving.
  const origin = root.querySelector("form.cx")!.getBoundingClientRect();
  const rect = (selector: string) => { const box = root.querySelector(selector)?.getBoundingClientRect(); return box ? { x: Math.round(box.x - origin.x), y: Math.round(box.y - origin.y), width: Math.round(box.width), height: Math.round(box.height) } : null; };
  return { plus: rect(".cx-plus"), mode: rect(".cx-mode"), caret: rect(".cx-mode .caret"), send: rect(".cx-send"), note: rect(".cx-note"), noteText: root.querySelector(".cx-note")?.textContent ?? "" };
});

async function expectBarSteady(page: Page) {
  await box(page).focus();
  const focused = await bar(page);
  await box(page).blur();
  const resting = await bar(page);
  // 「＋」 and the send key keep their size, the mode keeps its arrow, and the slot that holds the key hint / the cost does not move at all.
  expect(focused.plus).toEqual({ ...focused.plus!, width: 28, height: 28 });
  expect(focused.send).toEqual({ ...focused.send!, width: 32, height: 32 });
  expect(focused.plus).toEqual(resting.plus);
  expect(focused.mode).toEqual(resting.mode);
  expect(focused.send).toEqual(resting.send);
  expect(focused.note).toEqual(resting.note);
  expect(focused.noteText).toContain("Enter 发送");
  expect(resting.noteText).not.toContain("Enter 发送");
  if (focused.caret) expect(focused.caret.width).toBeGreaterThan(4);
}

test.describe("07f 输入框", () => {
  test("01 聚焦时「＋」不被挤窄、模式的箭头还在：右栏、抽屉、手机；「Enter 发送」换掉花费提示，这一行不动", async ({ page, browser }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await expectBarSteady(page);
    await shot(page, "07f-01-box-column", false);
    // The drawer on another page (400 wide).
    await openTab(page, id, "overview");
    await topbarAssistant(page).click();
    await expect(thread(page)).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 900 });
    expect((await thread(page).boundingBox())!.width).toBeLessThanOrEqual(400);
    await expectBarSteady(page);
    // A phone.
    const phone = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const small = await phone.newPage();
    await registerAccount(small, "bar");
    const sample = await sampleWorkId(small);
    await openTab(small, sample, "workspace");
    await small.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect(thread(small)).toBeVisible();
    await expectBarSteady(small);
    await phone.close();
  });

  test("11 花费提示放不下时整段去掉「今天还剩…」，只留「约 500 字」，不截断数字；余量在 title 里", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    const note = thread(page).locator(".cx-note");
    await expect(note).toContainText("约 500 字");
    const width = (await note.boundingBox())!.width;
    const more = note.locator(".more");
    const left = await allowance(page);
    await expect(note).toHaveAttribute("title", new RegExp(`今天还剩 ${left.toLocaleString("en-US")} 字`));
    // Never half a figure: either all of it shows, or none of it.
    const fits = await note.evaluate((node) => node.scrollWidth <= node.clientWidth);
    expect(fits).toBe(true);
    if (width < 190) {
      await expect(more).toBeHidden();
      expect((await note.innerText()).trim()).toBe("约 500 字");
    } else {
      await expect(more).toBeVisible();
      await expect(more).toContainText(`今天还剩 ${left.toLocaleString("en-US")} 字`);
    }
    // A narrower box (a drawer on a phone is full width, the column on a tablet is wide): the rule holds at every width.
    for (const size of [{ width: 1100, height: 900 }, { width: 1440, height: 900 }]) {
      await page.setViewportSize(size);
      const now = note.locator(".more");
      const room = (await note.boundingBox())!.width;
      if (room < 190) await expect(now).toBeHidden(); else await expect(now).toBeVisible();
      expect(await note.evaluate((node) => node.scrollWidth <= node.clientWidth)).toBe(true);
    }
  });

  test("05 选了「某条检查结果」：模式变成「帮我改这一处」，标签写「检查结果 · 第 1 处」，章节和人物标签变灰、加删除线、不随提问发出", async ({ page }) => {
    const { id, issue } = await checkedWork(page);
    await askForFix(page, issue);
    const task = tasks(page).last();
    await task.getByRole("button", { name: "按要求重新给改法", exact: true }).click();
    const mode = thread(page).getByRole("button", { name: /^这次做什么：/ });
    await expect(mode).toHaveText("帮我改这一处");
    await expect(mode).toBeDisabled();
    await expect(chip(page, "检查结果 · 第 1 处")).toBeVisible();
    // The chapter and a person are added by the 「＋」 menu; beside a fix they are shown but are not part of the question.
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^某一章/ }).click();
    await thread(page).locator(".cx-menu .scroll [role=menuitem]").first().click();
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^某个人物/ }).click();
    await thread(page).locator(".cx-menu .scroll [role=menuitem]").nth(1).click();
    const chapter = thread(page).locator(".a-chip.muted").filter({ hasText: /^第 \d+ 章/ });
    const person = thread(page).locator(".a-chip.muted").filter({ hasText: /^人物 · / });
    await expect(chapter).toBeVisible();
    await expect(person).toBeVisible();
    await expect(chapter).toContainText("改法只看这一处");
    expect(await chapter.locator(".label").evaluate((node) => getComputedStyle(node).textDecorationLine)).toBe("line-through");
    expect(await chip(page, "检查结果 · 第 1 处").evaluate((node) => node.classList.contains("muted"))).toBe(false);
    await box(page).fill("保留苏岑的视角");
    const request = page.waitForRequest((r) => r.method() === "POST" && /\/assistant\/tasks$/.test(r.url()));
    await send(page).click();
    expect((await request).postDataJSON()).toEqual({ kind: "fix_issue", question: "保留苏岑的视角", context: { page: "writing", issue_id: issue.id } });
    await finished(page, 2);
    // Sent, the box is empty and the mode is 自动 again.
    await expect(mode).toContainText("自动");
    await tasks(page).last().getByRole("button", { name: "按要求重新给改法", exact: true }).click();
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^某一章/ }).click();
    await thread(page).locator(".cx-menu .scroll [role=menuitem]").first().click();
    await expect(thread(page).locator(".a-chip.muted")).toHaveCount(1);
    await thread(page).getByRole("button", { name: "去掉：检查结果 · 第 1 处" }).click();
    await expect(mode).toContainText("自动");
    await expect(mode).toBeEnabled();
    await expect(thread(page).locator(".a-chip.muted")).toHaveCount(0);
    await expect(thread(page).locator(".a-chip").first()).toContainText("第");
    // 帮我改这一处 is not in the mode menu.
    await mode.click();
    await expect(thread(page).getByRole("menuitemradio")).toHaveText(["自动", "问作品", "写前回顾", "查前文矛盾", "改资料"]);
    await page.keyboard.press("Escape");
    await shot(page, "07f-05-fix-chips", false);
    expect(id).toBeTruthy();
  });

  test("03 查前文矛盾：占位写「在正文里选中要查的一段」，选中的文字自动成为标签、发送键随之可用；清空选区不去标签；浮条不压工具栏", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await chooseMode(page, "查前文矛盾");
    await expect(box(page)).toHaveAttribute("placeholder", "在正文里选中要查的一段");
    // The bottom right says only what it costs.
    await expect(thread(page).locator(".cx-note")).toContainText("约 500 字");
    await expect(thread(page).locator(".cx-note")).not.toContainText("选中");
    await expect(send(page)).toBeDisabled();
    await select(page, "#draft-body", 14);
    const picked = (await selectedWords(page)).trim();
    await expect(chip(page, "选中：「")).toBeVisible();
    await expect(send(page)).toBeEnabled();
    await expect(thread(page).locator(".cx-note")).toContainText(`约 ${500 + picked.replace(/\s+/g, "").length} 字`);
    // The bar over the words is clear of the editor's own tool row.
    await expect(toolbar(page)).toBeVisible();
    const [bar_, tools] = [await toolbar(page).boundingBox(), await page.locator(".draft-tools").boundingBox()];
    const overlap = bar_!.y < tools!.y + tools!.height && bar_!.y + bar_!.height > tools!.y && bar_!.x < tools!.x + tools!.width && bar_!.x + bar_!.width > tools!.x;
    expect(overlap).toBe(false);
    await shot(page, "07f-03-check-mode", false);
    // Emptying the selection leaves the tag where it is; the author takes it off by hand, and it stays off.
    await page.evaluate(() => window.getSelection()?.removeAllRanges());
    await page.waitForTimeout(300);
    await expect(chip(page, "选中：「")).toBeVisible();
    await expect(send(page)).toBeEnabled();
    await thread(page).getByRole("button", { name: /^去掉：选中/ }).click();
    await expect(chip(page, "选中：「")).toHaveCount(0);
    await expect(send(page)).toBeDisabled();
    await page.waitForTimeout(300);
    await expect(chip(page, "选中：「")).toHaveCount(0);
    // A new selection becomes the tag again, and sends as a check of exactly those words.
    await select(page, "#draft-body", 16);
    const again = (await selectedWords(page)).trim();
    await expect(chip(page, "选中：「")).toBeVisible();
    const request = page.waitForRequest((r) => r.method() === "POST" && /\/assistant\/tasks$/.test(r.url()));
    await send(page).click();
    expect((await request).postDataJSON()).toMatchObject({ kind: "ask", context: { page: "writing", selection: again, intent: "check_selection" } });
    await finished(page);
    await expect(thread(page).getByRole("button", { name: "这次做什么：自动" })).toBeVisible();
  });

  test("03b 先选中文字、再把模式换成「查前文矛盾」：选中的文字直接成为标签；选中靠近页面顶端时浮条放在选区下方", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await select(page, "#draft-body", 14);
    await expect(toolbar(page)).toBeVisible();
    // The first words of the draft sit right under the tool row: the bar goes below them.
    const [selection, bar_] = [await page.evaluate(() => window.getSelection()!.getRangeAt(0).getBoundingClientRect().bottom), await toolbar(page).boundingBox()];
    expect(bar_!.y).toBeGreaterThanOrEqual(selection - 1);
    await chooseMode(page, "查前文矛盾");
    await expect(chip(page, "选中：「")).toBeVisible();
    await expect(send(page)).toBeEnabled();
  });

  test("10 停止键：助手在查时是黑底，鼠标移上去仍是深色（不变成发送的蓝色）", async ({ page }) => {
    await setup(page);
    await serveTasks(page, () => [runningView("thinking")]);
    await page.reload();
    await openAssistantTab(page);
    const stop = stopButton(page);
    await expect(stop).toBeVisible();
    const [ink, ink2, blue] = [await colourOf(page, "var(--c-ink)"), await colourOf(page, "var(--c-ink-2)"), await colourOf(page, "var(--c-blue)")];
    await expect.poll(() => stop.evaluate((node) => getComputedStyle(node).backgroundColor)).toBe(ink);
    await stop.hover();
    await expect.poll(() => stop.evaluate((node) => getComputedStyle(node).backgroundColor)).toBe(ink2);
    expect(ink2).not.toBe(blue);
    await shot(page, "07f-10-stop-hover", false);
  });
});

test.describe("07f 菜单", () => {
  test("16 菜单的键盘焦点是内描边，没被圆角裁掉；用键盘移动时鼠标停着的那一项不再亮：＋菜单、模式菜单、账号菜单、更多菜单", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    const ring = (locatorPage: Page) => locatorPage.evaluate(() => {
      const style = getComputedStyle(document.activeElement as Element);
      return { shadow: style.boxShadow, outline: style.outlineStyle };
    });
    // 「＋」 → 某一章 → the chapters: the mouse rests on the third entry while the arrow keys move.
    await openPlus(page);
    const menu = thread(page).getByRole("menu", { name: "加进这次提问" });
    await menu.getByRole("menuitem", { name: /^某一章/ }).click();
    const entries = menu.getByRole("menuitem");
    expect(await entries.count()).toBeGreaterThan(3);
    const third = (await entries.nth(3).boundingBox())!;
    await page.mouse.move(third.x + third.width / 2, third.y + third.height / 2);
    await expect.poll(() => entries.nth(3).evaluate((node) => getComputedStyle(node).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
    await page.keyboard.press("ArrowDown");
    await expect(menu).toHaveAttribute("data-keyboard", "");
    const focused = await ring(page);
    expect(focused.shadow).toContain("inset");
    expect(focused.outline).toBe("none");
    // Only one entry is lit: the one with the focus; the one under the resting mouse is not.
    await expect.poll(() => entries.nth(3).evaluate((node) => getComputedStyle(node).backgroundColor)).toBe("rgba(0, 0, 0, 0)");
    await shot(page, "07f-16-menu-focus", false);
    await page.mouse.move(third.x + third.width / 2 + 4, third.y + third.height / 2 + 1);
    await expect(menu).not.toHaveAttribute("data-keyboard", "");
    await expect.poll(() => entries.nth(3).evaluate((node) => getComputedStyle(node).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
    await page.keyboard.press("Escape");
    // 模式菜单.
    await thread(page).getByRole("button", { name: /^这次做什么：/ }).click();
    await page.keyboard.press("ArrowDown");
    expect((await ring(page)).shadow).toContain("inset");
    await page.keyboard.press("Escape");
    // 更多.
    await page.getByLabel("更多：完成本章、技术详情、重置", { exact: true }).click();
    await page.keyboard.press("Tab");
    expect((await ring(page)).shadow).toContain("inset");
    await page.keyboard.press("Escape");
    // 账号菜单.
    await page.getByRole("button", { name: /^账号菜单：/ }).click();
    await page.keyboard.press("ArrowDown");
    expect((await ring(page)).shadow).toContain("inset");
    await page.keyboard.press("Escape");
  });

  for (const size of [{ width: 1440, height: 400 }, { width: 1024, height: 400 }]) {
    test(`32 矮窗口 ${size.width}×${size.height}：向上弹出的菜单放不下就向下，两边都放不下就限高、里面滚动；每一项都点得到`, async ({ page }) => {
      await setup(page);
      await openAssistantTab(page);
      await ask(page, "苏岑知道罗盘被调包了吗？");
      await finished(page);
      await page.setViewportSize(size);
      await box(page).scrollIntoViewIfNeeded();
      const topbar = (await page.locator(".topbar").boundingBox())!;
      await openPlus(page);
      const menu = thread(page).getByRole("menu", { name: "加进这次提问" });
      const top = (await menu.boundingBox())!;
      // Clear of the fixed top bar, and every entry takes a click (the check does not click, it asks the browser who would get it).
      expect(top.y).toBeGreaterThanOrEqual(topbar.y + topbar.height - 1);
      for (const entry of await menu.getByRole("menuitem").all()) if (await entry.isEnabled()) await entry.click({ trial: true });
      await shot(page, `07f-32-plus-${size.width}x${size.height}`, false);
      await menu.getByRole("menuitem", { name: /^某一章/ }).click();
      expect((await menu.boundingBox())!.y).toBeGreaterThanOrEqual(topbar.y + topbar.height - 1);
      for (const entry of await menu.getByRole("menuitem").all()) if (await entry.isEnabled()) await entry.click({ trial: true });
      await page.keyboard.press("Escape");
      await thread(page).getByRole("button", { name: /^这次做什么：/ }).click();
      const mode = thread(page).getByRole("menu", { name: "这次让助手做什么" });
      expect((await mode.boundingBox())!.y).toBeGreaterThanOrEqual(topbar.y + topbar.height - 1);
      for (const entry of await mode.getByRole("menuitemradio").all()) await entry.click({ trial: true });
    });
  }
});
