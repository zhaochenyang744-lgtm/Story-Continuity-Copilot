import { mkdir } from "node:fs/promises";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { api, createWorkByApi, expect, fixturePath, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { theme } from "./support/pages";
import { button } from "./support/writing";

// v2.1 unified interface, the pages that have nothing to do with the assistant: the settings page, the writing calendar, the story
// route on a phone, the privacy page signed out, the category tabs, and the fields of the inner forms.

const dayOf = (offsetDays = 0) => new Date(Date.now() + 8 * 3_600_000 + offsetDays * 86_400_000).toISOString().slice(0, 10);
const rect = (locator: Locator) => locator.evaluate((node) => { const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height }; });
const cssColor = (page: Page, value: string) => page.evaluate((expression) => { const probe = document.createElement("i"); probe.style.color = expression; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; }, value);
const cssShadow = (page: Page, name: string) => page.evaluate((token) => { const probe = document.createElement("i"); probe.style.cssText = `box-shadow: var(${token}); transition: none`; document.body.append(probe); const value = getComputedStyle(probe).boxShadow; probe.remove(); return value; }, name);
const noSideScroll = (page: Page) => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);

/** Screenshots for the delivery report: only when PAGES_SHOTS_DIR is set, so the ordinary run leaves no files. */
async function snap(page: Page, name: string, fullPage = true) {
  const directory = process.env.PAGES_SHOTS_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await expect(page.getByText(/^正在(读取|载入|整理)/)).toHaveCount(0);
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(directory, `${name}.png`), fullPage });
}
/** The same page at 1440 and 390, by day and by night. `open` brings the page up at the width it is given. */
async function photograph(page: Page, name: string, open: () => Promise<void>, afterTheme?: () => Promise<void>, only1440 = false) {
  for (const [width, height] of only1440 ? [[1440, 960]] : [[1440, 960], [390, 844]]) {
    for (const mode of ["day", "night"] as const) {
      await page.setViewportSize({ width, height });
      await open();
      await theme(page, mode);
      // What has to come after the theme (a dialog covers the switch) is done last.
      await afterTheme?.();
      await snap(page, `${name}-${width}-${mode === "day" ? "浅色" : "深色"}`);
    }
    if (afterTheme) await page.keyboard.press("Escape");
    await theme(page, "day");
  }
}

async function writeOn(page: Page, userId: string, projectId: string, day: string, chars: number) {
  await api(page).post(`/test/v180/users/${userId}/writing-days`, { project_id: projectId, day, net_chars: chars, chapter_number: 1 });
}
async function withWriting(page: Page) {
  await registerAccount(page, "pagesv210");
  const me = (await api(page).get("/auth/session")).user;
  const work = await createWorkByApi(page, { title: "盐雾之下", genre: "近未来", summary: "港口封闭后的第七年。" });
  for (const [offset, chars] of [[-1, 1200], [-2, 300], [-3, 5200], [-30, 900], [-90, 2400], [-200, 700], [-300, 100]]) await writeOn(page, me.id, work, dayOf(offset), chars);
  return work;
}

test("17 设置页：内容区右端和顶栏右端对齐，说明和输入框各有最大宽度，左栏的线跟着内容到底", async ({ page }) => {
  await registerAccount(page, "setalign");
  await page.setViewportSize({ width: 1440, height: 960 });
  for (const item of ["general", "account", "usage", "data"]) {
    await page.goto(`/settings/${item}`);
    await expect(page.locator(".settings-pane .pane-head h2")).toBeVisible();
    const avatar = await rect(page.locator(".account-trigger"));
    const pane = await rect(page.locator(".settings-pane"));
    const group = await rect(page.locator(".settings .group").first());
    expect(Math.abs(pane.right - avatar.right), `${item}: the pane ends where the top bar ends`).toBeLessThanOrEqual(2);
    expect(Math.abs(group.right - avatar.right), `${item}: its first group ends there too`).toBeLessThanOrEqual(2);
    // The rule of the sub-navigation runs as far down as the content does.
    const settings = await rect(page.locator(".settings"));
    const nav = await rect(page.locator(".settings-nav"));
    expect(Math.abs(nav.bottom - settings.bottom)).toBeLessThanOrEqual(1);
    expect(nav.height).toBeGreaterThanOrEqual(pane.height - 1);
    // Words stop at 680px, a field at 480px.
    for (const width of await page.locator(".settings .row-text, .settings .pane-head .lede").evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().width))) expect(width).toBeLessThanOrEqual(681);
    for (const width of await page.locator(".settings input:not([type=checkbox]):not([type=radio]), .settings textarea").evaluateAll((nodes) => nodes.map((node) => node.getBoundingClientRect().width))) expect(width).toBeLessThanOrEqual(481);
  }
  await page.goto("/settings/general");
  expect(await page.locator(".settings-nav").evaluate((node) => getComputedStyle(node).borderRightWidth)).toBe("1px");
  expect(await page.locator(".settings").evaluate((node) => getComputedStyle(node).minHeight)).toBe("0px");
});

test("17 写作日历：图和标题行、图例左右对齐，格子是正方形，1100 以下这一年挪到下面", async ({ page }) => {
  await withWriting(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/account");
  const body = page.locator(".heat-body");
  await expect(body).toBeVisible();
  const aligned = async (label: string) => {
    const head = await rect(page.locator("#author-calendar").locator(".."));
    const chart = await rect(body);
    const foot = await rect(page.locator(".heat-foot"));
    expect(Math.abs(chart.left - head.left), `${label}: left edge`).toBeLessThanOrEqual(2);
    expect(Math.abs(chart.right - head.right), `${label}: right edge`).toBeLessThanOrEqual(2);
    expect(Math.abs(chart.left - foot.left), `${label}: legend row left`).toBeLessThanOrEqual(2);
    expect(Math.abs(chart.right - foot.right), `${label}: legend row right`).toBeLessThanOrEqual(2);
    const cells = await page.locator(".heat-grid i").evaluateAll((nodes) => nodes.slice(0, 40).map((node) => { const box = node.getBoundingClientRect(); return [box.width, box.height]; }));
    for (const [width, height] of cells) { expect(Math.abs(width - height), `${label}: square cells`).toBeLessThanOrEqual(0.6); expect(width).toBeGreaterThanOrEqual(9.9); }
    return cells[0][0];
  };
  const wide = await aligned("1440");
  expect(wide, "cells grow with the column").toBeGreaterThan(12);
  // Next to the calendar at 1440, under it at 1100 and below.
  const side = await rect(page.locator(".author-stats"));
  expect(side.left).toBeGreaterThan((await rect(body)).right);
  // The last column is the newest day; the grid is as wide as the chart (no spill).
  const grid = await rect(page.locator(".heat-grid"));
  expect(grid.right).toBeLessThanOrEqual((await rect(body)).right + 0.5);
  await page.locator(".heat-grid i").last().hover();
  const tip = await rect(page.locator(".heat-grid .tip"));
  const last = await rect(page.locator(".heat-grid i").last());
  expect(Math.abs((tip.left + tip.right) / 2 - (last.left + last.right) / 2), "the tip sits over the cell it names").toBeLessThanOrEqual(1.5);
  expect(tip.bottom).toBeLessThanOrEqual(last.top + 1);

  for (const width of [1101, 1100, 900]) {
    await page.setViewportSize({ width, height: 900 });
    await aligned(String(width));
    const stats = await rect(page.locator(".author-stats"));
    const chart = await rect(page.locator(".heat-foot"));
    if (width <= 1100) expect(stats.top, `${width}: the year's figures are under the calendar`).toBeGreaterThanOrEqual(chart.bottom - 1);
    else expect(stats.left, `${width}: still beside it`).toBeGreaterThan(chart.right - 400);
  }

  // A phone: cells stay at their least size, the chart slides sideways and opens on the newest months.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/account");
  const scroller = page.locator(".heat-scroll");
  await expect(scroller).toBeVisible();
  expect(await scroller.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
  expect(await scroller.evaluate((node) => Math.round(node.scrollWidth - node.clientWidth - node.scrollLeft))).toBeLessThanOrEqual(1);
  const cell = await rect(page.locator(".heat-grid i").first());
  expect(Math.abs(cell.width - 10)).toBeLessThanOrEqual(0.6);
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
});

test("17 故事航线：手机上图里只有圆点和编号，名称在图下面的列表里；宽屏保持现状", async ({ page }) => {
  await registerAccount(page, "route17");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 1440, height: 960 });
  await openTab(page, id, "overview");
  const route = page.getByRole("region", { name: "故事航线", exact: true });
  await expect(route.getByTestId(/^route-thread-/).first()).toBeVisible();
  const lines = await route.getByTestId(/^route-thread-/).count();
  expect(lines).toBeGreaterThan(0);
  await expect(route.locator(".route-thread-label")).toHaveCount(lines);
  await expect(route.locator(".route-threads")).toHaveCount(0);

  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, id, "overview");
  await expect(route.getByTestId(/^route-thread-/)).toHaveCount(lines);
  await expect(route.locator(".route-thread-label")).toHaveCount(0);
  const items = route.locator(".route-threads li");
  await expect(items).toHaveCount(lines);
  for (let i = 0; i < lines; i += 1) await expect(items.nth(i)).toContainText(/第 \d+ 章埋下 · 已过 \d+ 章/);
  // The dots carry the numbers of the list.
  await expect(route.locator(".route-thread-no")).toHaveText(Array.from({ length: lines }, (_, i) => String(i + 1)));
  await expect(route.locator(".route-threads-no")).toHaveText(Array.from({ length: lines }, (_, i) => String(i + 1)));
  // No text of the chart is drawn beyond the chart's own edge.
  const outside = await route.locator("svg.route").evaluate((svg) => {
    const frame = svg.getBoundingClientRect();
    return Array.from(svg.querySelectorAll("text")).filter((text) => {
      const box = text.getBoundingClientRect();
      return box.width > 0 && (box.left < frame.left - 0.5 || box.right > frame.right + 0.5);
    }).map((text) => text.textContent);
  });
  expect(outside).toEqual([]);
  // Pointing at the last chapter writes its caption inside the chart too.
  await route.getByTestId(/^route-chapter-/).last().focus();
  await expect(route.getByText(/章时 · \d+ 条伏笔悬着$/)).toBeVisible();
  const caption = await route.locator("svg.route").evaluate((svg) => {
    const frame = svg.getBoundingClientRect();
    const box = svg.querySelector(".route-cursor text")!.getBoundingClientRect();
    return box.left >= frame.left - 0.5 && box.right <= frame.right + 0.5;
  });
  expect(caption).toBe(true);
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
  await page.setViewportSize({ width: 601, height: 844 });
  await expect(route.locator(".route-threads")).toHaveCount(0);
});

test("17 隐私页：没登录时手机上左右有 16px 留白，和登录后一样；登录页本身不变", async ({ page, browser }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/privacy");
  await expect(page.getByRole("heading", { level: 1, name: "隐私说明", exact: true })).toBeVisible();
  const gutters = async (target: Page) => target.evaluate(() => {
    const box = document.querySelector(".article")!.getBoundingClientRect();
    return { left: box.left, right: document.documentElement.clientWidth - box.right };
  });
  const signedOut = await gutters(page);
  expect(Math.abs(signedOut.left - 16)).toBeLessThanOrEqual(1);
  expect(signedOut.right).toBeGreaterThanOrEqual(15);
  expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
  // The wide window: the same centred column as before.
  await page.setViewportSize({ width: 1440, height: 900 });
  const wide = await rect(page.locator(".article"));
  expect(Math.abs((wide.left + wide.right) / 2 - (await page.evaluate(() => document.documentElement.clientWidth)) / 2)).toBeLessThanOrEqual(1);
  expect(wide.width).toBeLessThanOrEqual(681);

  // Signed in the page has the same gutter.
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 390, height: 844 } });
  const other = await context.newPage();
  await other.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await registerAccount(other, "priv17");
  await other.goto("/privacy");
  await expect(other.getByRole("heading", { level: 1, name: "隐私说明", exact: true })).toBeVisible();
  const signedIn = await gutters(other);
  expect(Math.abs(signedIn.left - signedOut.left)).toBeLessThanOrEqual(1);
  await context.close();

  // The sign-in page keeps its own layout: its main area has no padding.
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1, name: "欢迎回来", exact: true })).toBeVisible();
  expect(await page.locator("main").evaluate((node) => { const style = getComputedStyle(node); return [style.paddingLeft, style.paddingRight]; })).toEqual(["0px", "0px"]);
});

test("17 资料页、计划页的分类导航：窄屏一行横向滑动，选中的页签滑进可见区", async ({ page }) => {
  await registerAccount(page, "tabs17");
  const id = await sampleWorkId(page);
  for (const [tab, label] of [["memory", "资料分类"], ["plan", "计划分类"]] as const) {
    for (const width of [390, 320]) {
      await page.setViewportSize({ width, height: 844 });
      await openTab(page, id, tab);
      const nav = page.getByRole("navigation", { name: label, exact: true });
      await expect(nav).toBeVisible();
      const tops = await nav.getByRole("button").evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().top)));
      expect(new Set(tops).size, `${tab} at ${width}: one row`).toBe(1);
      expect(await nav.evaluate((node) => getComputedStyle(node).flexWrap)).toBe("nowrap");
      expect(await nav.evaluate((node) => getComputedStyle(node).overflowX)).toBe("auto");
      expect(await noSideScroll(page)).toBeLessThanOrEqual(0);
      // Choose the last tab: it ends up inside the row's visible part.
      const tabs = nav.getByRole("button");
      await tabs.last().click();
      await expect(tabs.last()).toHaveAttribute("aria-current", "page");
      await expect.poll(async () => nav.evaluate((row) => {
        const chosen = row.querySelector('[aria-current="page"]')!.getBoundingClientRect();
        const frame = row.getBoundingClientRect();
        return chosen.left >= frame.left - 0.5 && chosen.right <= frame.right + 0.5;
      })).toBe(true);
    }
  }
  // A wide window keeps the tabs as they were.
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, id, "memory");
  expect(await page.getByRole("navigation", { name: "资料分类", exact: true }).evaluate((node) => getComputedStyle(node).overflowX)).toBe("visible");
});

test("17 内部表单的输入框：白底、没有边框、小圆角、一圈细环加淡影；悬停和聚焦各深一档，不变蓝；浅色和深色；登录页和写作页不受影响", async ({ page }) => {
  await registerAccount(page, "fields17");
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/settings/general");
  const name = page.getByRole("textbox", { name: "显示名称", exact: true });
  const look = (field: Locator) => field.evaluate((node) => { const style = getComputedStyle(node); return { background: style.backgroundColor, width: style.borderTopWidth, style: style.borderTopStyle, color: style.borderTopColor, radius: style.borderTopLeftRadius, shadow: style.boxShadow }; });
  for (const mode of ["day", "night"] as const) {
    await theme(page, mode);
    await page.mouse.move(0, 0);
    const surface = await cssColor(page, "var(--c-surface)");
    const blue = await cssColor(page, "var(--c-blue)");
    const [rest, hover, focus] = [await cssShadow(page, "--ring-rest"), await cssShadow(page, "--ring-hover"), await cssShadow(page, "--ring-focus")];
    await expect.poll(async () => (await look(name)).shadow, { message: `${mode}: resting` }).toBe(rest);
    const resting = await look(name);
    expect(resting, `${mode}: resting`).toMatchObject({ background: surface, width: "0px", radius: "6px" });
    await name.hover();
    await expect.poll(async () => (await look(name)).shadow, { message: `${mode}: hover` }).toBe(hover);
    await page.mouse.move(0, 0);
    await name.focus();
    await expect.poll(async () => (await look(name)).shadow, { message: `${mode}: focus` }).toBe(focus);
    const focused = await look(name);
    expect(focused.background).toBe(surface);
    expect(focused.shadow).not.toContain(blue);
    await name.blur();
  }
  await theme(page, "day");
  // The area for the introduction and the select-like controls share the box.
  const bio = await look(page.getByRole("textbox", { name: "简介", exact: true }));
  expect(bio).toMatchObject({ width: "0px", radius: "6px" });

  // New work and the import form.
  await page.goto("/projects/new");
  const title = page.getByRole("textbox", { name: /^书名/ });
  expect(await look(title)).toMatchObject({ width: "0px", radius: "6px" });
  expect(await look(page.getByRole("textbox", { name: /^简介/ }))).toMatchObject({ width: "0px", radius: "6px" });

  // An error keeps its red, now a ring; a disabled field its quiet look.
  await page.getByRole("button", { name: "创建并开始写第一章", exact: true }).click();
  await title.evaluate((node: HTMLInputElement) => node.setAttribute("aria-invalid", "true"));
  await expect.poll(async () => (await look(title)).shadow).toContain(await cssColor(page, "var(--c-red-text)"));
  await title.evaluate((node: HTMLInputElement) => node.removeAttribute("aria-invalid"));

  // Writing page: the chapter title and the body keep their own looks (no box).
  const work = await createWorkByApi(page, { title: "框线之书" });
  await page.goto(`/projects/${work}/workspace`);
  const heading = page.locator(".draft-title textarea");
  await expect(heading).toBeVisible();
  expect(await look(heading)).toMatchObject({ width: "0px", background: "rgba(0, 0, 0, 0)" });
  const editor = page.getByRole("textbox", { name: "草稿正文", exact: true });
  await expect(editor).toBeVisible();
  expect(await editor.evaluate((node) => getComputedStyle(node).borderTopWidth)).toBe("0px");

  // The sign-in pages keep their underline fields.
  await page.context().clearCookies();
  await page.goto("/login");
  const account = page.getByLabel("账号", { exact: true });
  await expect(account).toBeVisible();
  await account.blur();
  expect(await account.evaluate((node) => { const style = getComputedStyle(node); return { top: style.borderTopWidth, bottom: style.borderBottomWidth, radius: style.borderTopLeftRadius, background: style.backgroundColor }; })).toEqual({ top: "0px", bottom: "1px", radius: "0px", background: "rgba(0, 0, 0, 0)" });
  await account.focus();
  expect(await account.evaluate((node) => { const style = getComputedStyle(node); return { bottom: style.borderBottomWidth, shadow: style.boxShadow, top: style.borderTopWidth }; })).toEqual({ bottom: "2px", shadow: "none", top: "0px" });
});

test("17 截图（只在设置了 PAGES_SHOTS_DIR 时拍）", async ({ page, browser }) => {
  test.skip(!process.env.PAGES_SHOTS_DIR, "screenshots are taken only for the delivery report");
  test.setTimeout(240_000);
  const work = await withWriting(page);
  const sample = await sampleWorkId(page);

  await photograph(page, "01-设置页", async () => { await page.goto("/settings/general"); await expect(page.locator(".settings-pane .pane-head h2")).toBeVisible(); });
  await photograph(page, "01b-设置页-用量", async () => { await page.goto("/settings/usage"); await expect(page.locator(".settings-pane .pane-head h2")).toBeVisible(); });
  await photograph(page, "02-写作日历", async () => { await page.goto("/account"); await expect(page.locator(".heat-body")).toBeVisible(); });
  await page.setViewportSize({ width: 1000, height: 900 });
  await page.goto("/account");
  await snap(page, "02b-写作日历-1000-浅色");
  await photograph(page, "03-故事航线", async () => { await openTab(page, sample, "overview"); await expect(page.getByTestId(/^route-thread-/).first()).toBeVisible(); await page.getByRole("region", { name: "故事航线", exact: true }).scrollIntoViewIfNeeded(); });
  await photograph(page, "05-资料页分类导航", async () => { await openTab(page, sample, "memory"); });
  await photograph(page, "05b-计划页分类导航", async () => { await openTab(page, sample, "plan"); });
  await photograph(page, "06-新建作品表单", async () => { await page.goto("/projects/new"); await page.getByRole("textbox", { name: /^书名/ }).fill("潮汐之后"); await page.getByRole("textbox", { name: /^简介/ }).focus(); });
  await photograph(page, "06b-设置-账号表单", async () => { await page.goto("/settings/account"); await expect(page.locator(".settings-pane .pane-head h2")).toBeVisible(); }, async () => { await button(page, "修改密码").click(); await expect(page.getByLabel("旧密码", { exact: true })).toBeVisible(); });
  await photograph(page, "06c-导入表单", async () => {
    await page.goto("/projects/import");
    const chooser = page.waitForEvent("filechooser");
    await page.getByRole("button", { name: "选择文件", exact: true }).click();
    await (await chooser).setFiles(fixturePath("stage9-mist-harbor.md"));
    await button(page, "下一步：检查分章").click();
    await button(page, "分章没问题，下一步").click();
    await page.getByRole("textbox", { name: /^书名/ }).fill("测试雾港");
  });
  await photograph(page, "06d-计划弹窗", async () => {
    await openTab(page, work, "plan");
  }, async () => {
    await button(page, "新建计划").click();
    await page.getByRole("dialog", { name: "新建计划", exact: true }).getByRole("textbox", { name: "标题", exact: true }).fill("值班员回到码头");
  }, true);
  await photograph(page, "06e-资料页表单", async () => {
    await openTab(page, work, "memory");
  }, async () => {
    await page.getByRole("navigation", { name: "资料分类", exact: true }).getByRole("button", { name: /^伏笔/ }).click();
    await button(page, "记一条伏笔").click();
    await page.getByRole("textbox", { name: "标题", exact: true }).fill("廊桥钥匙");
  }, true);

  // The privacy page, signed out.
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 1440, height: 960 } });
  const visitor = await context.newPage();
  await visitor.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  await photograph(visitor, "04-隐私页-未登录", async () => { await visitor.goto("/privacy"); await expect(visitor.getByRole("heading", { level: 1, name: "隐私说明", exact: true })).toBeVisible(); });
  await visitor.setViewportSize({ width: 390, height: 844 });
  await visitor.goto("/login");
  await snap(visitor, "04b-登录页-390-浅色");
  await visitor.setViewportSize({ width: 1440, height: 960 });
  await visitor.goto("/login");
  await snap(visitor, "04b-登录页-1440-浅色");
  await context.close();
});
