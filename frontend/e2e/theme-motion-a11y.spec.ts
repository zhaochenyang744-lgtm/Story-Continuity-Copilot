import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { api, createWorkByApi, expect, openAccountMenu, openTab, registerAccount, sampleWorkId, shot, test } from "./support/app";
import { button, finding, run, setup } from "./support/writing";
import { evidence, project, sample, theme, workMenu } from "./support/pages";

test("12 Q 夜间勾选栏禁用按钮透明底和弱描边", async ({ page }) => {
  await sample(page, "sources");
  await theme(page, "night");
  const control = button(page, "检查选中的章节");
  await expect(control).toBeDisabled();
  const expected = await control.evaluate(e => getComputedStyle(e).getPropertyValue("--c-on-inverse-3").trim());
  const actual = await control.evaluate(e => { const s = getComputedStyle(e); const probe = document.createElement("span"); probe.style.color = s.getPropertyValue("--c-on-inverse-3"); e.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return { background: s.backgroundColor, color: s.color, border: s.borderTopColor, width: s.borderTopWidth, expected: color }; });
  expect(expected).toBeTruthy();
  expect.soft(actual.background).toBe("rgba(0, 0, 0, 0)");
  expect.soft(actual.color).toBe(actual.expected);
  expect.soft(actual.border).toBe(actual.expected);
  await expect(control).toHaveCSS("box-shadow", `rgb(149, 155, 255) 0px 0px 0px 1px inset`);
  await shot(page, "12-Q-disabled-night", false);
});

test("08 夜间开关：系统默认和本机持久化", async ({ page }) => {
  for (const [scheme, value, background] of [["dark", "night", "rgb(17, 17, 17)"], ["light", "day", "rgb(244, 244, 241)"]] as const) {
    await page.emulateMedia({ colorScheme: scheme });
    await page.goto("/login");
    await expect(page.locator("html")).toHaveAttribute("data-theme", value);
    await expect(page.locator("body")).toHaveCSS("background-color", background);
    expect(await page.evaluate(() => localStorage.getItem("story-continuity:theme"))).toBeNull();
  }
  await registerAccount(page, "theme08");
  await button(page, "切换到夜间模式").click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  await expect(button(page, "切换到日间模式")).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("story-continuity:theme"))).toBe("night");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  await expect(page.locator("body")).toHaveCSS("background-color", "rgb(17, 17, 17)");
  await button(page, "切换到日间模式").click();
  await expect(button(page, "切换到夜间模式")).toBeVisible();
  expect(await page.evaluate(() => localStorage.getItem("story-continuity:theme"))).toBe("day");
});

test("08 夜间反色色块：深蓝底、浅色字，蓝色按钮有描边；日间不变", async ({ page }) => {
  await registerAccount(page, "inverse08");
  const id = await sampleWorkId(page);
  await createWorkByApi(page, { title: "夜间试验之书" });
  // Creating a real work completes onboarding, so explicitly restart the tour to inspect its band.
  await page.goto("/");
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "重新看一遍导览", exact: true }).click();
  await expect(page.getByRole("region", { name: "导览", exact: true })).toContainText("导览 1 / 5");
  const look = (target: Locator) => target.evaluate(e => ({ shadow: getComputedStyle(e).boxShadow }));
  const colours = { day: { background: "rgb(17, 17, 17)", color: "rgb(244, 244, 241)" }, night: { background: "rgb(29, 33, 85)", color: "rgb(244, 244, 241)" } };
  const places: [string, () => Promise<{ band: Locator; control: Locator }>][] = [
    ["night-tour", async () => {
      await openTab(page, id, "workspace");
      const band = page.getByRole("region", { name: "导览", exact: true });
      return { band, control: band.getByRole("button", { name: "去资料", exact: true }) };
    }],
    ["night-overview-band", async () => {
      await openTab(page, id, "overview");
      const band = page.getByRole("button", { name: /继续写 · 草稿/ });
      return { band, control: band.getByText("打开草稿", { exact: true }) };
    }],
    ["night-home-band", async () => {
      await page.goto("/");
      const band = page.getByRole("button", { name: /上次停在/ });
      return { band, control: band.getByText("继续写", { exact: true }) };
    }],
    ["night-chapters-bar", async () => {
      await openTab(page, id, "sources");
      for (const n of [1, 2]) await page.getByRole("checkbox", { name: `选择第 ${n} 章`, exact: true }).check();
      const band = page.getByTestId("chapter-selection");
      await band.scrollIntoViewIfNeeded();
      return { band, control: band.getByRole("button", { name: "检查选中的章节", exact: true }) };
    }],
  ];
  for (const [name, reach] of places) {
    await theme(page, "day");
    const { band, control } = await reach();
    await expect(band).toBeVisible();
    // The colours settle a frame after the switch, so each is read with a retrying assertion.
    for (const mode of ["day", "night"] as const) {
      await theme(page, mode);
      await expect(band, `${name}: ${mode}`).toHaveCSS("background-color", colours[mode].background);
      await expect(band, `${name}: ${mode}`).toHaveCSS("color", colours[mode].color);
      if (mode === "day") await expect(control, `${name}: no edge on the blue button by day`).toHaveCSS("box-shadow", "none");
      else await expect.poll(() => look(control).then(item => item.shadow), { message: `${name}: the blue button has an edge at night` }).not.toBe("none");
    }
    await shot(page, name, false);
  }
  await theme(page, "day");
});

test("08 减少动态效果：直接最终值与正常计数采样", async ({ page }, info) => {
  await registerAccount(page, "motion08");
  const id = await sampleWorkId(page), expected = (await project(page, id)).chapter_word_count;
  await page.addInitScript(() => {
    const samples: number[] = [];
    Object.assign(window, { __countSamples: samples });
    const read = () => {
      const node = document.querySelector('[data-testid="overview-word-count"] [data-testid="count-live"]');
      if (node?.textContent?.trim()) samples.push(Number(node.textContent.replaceAll(",", "")));
    };
    new MutationObserver(read).observe(document, { subtree: true, childList: true, characterData: true });
  });
  const samples = () => page.evaluate(() => (window as typeof window & { __countSamples: number[] }).__countSamples);
  await page.emulateMedia({ reducedMotion: "reduce" });
  await openTab(page, id, "overview");
  await expect.poll(samples).not.toEqual([]);
  const reduced = await samples();
  expect(reduced.every(n => n === expected)).toBe(true);
  const svg = page.getByRole("img", { name: /^故事航线：/ });
  await expect(svg).toBeVisible();
  const route = await svg.evaluate(e => ({ clip: getComputedStyle(e).clipPath, animations: e.getAnimations({ subtree: true }).map(a => ({ state: a.playState, duration: a.effect?.getComputedTiming().duration })) }));
  expect(route.clip).toBe("none");
  expect(route.animations.every(a => a.state !== "running" || Number(a.duration) <= .01)).toBe(true);
  await page.emulateMedia({ reducedMotion: "no-preference" });
  await openTab(page, id, "overview");
  await expect.poll(async () => (await samples()).some(n => n < expected), { message: "observe at least one real intermediate CountUp value" }).toBe(true);
  await expect(page.getByTestId("overview-word-count").getByTestId("count-live")).toHaveText(expected.toLocaleString("en-US"));
  await evidence(info, "motion-samples", { expected, reduced, route, normal: await samples() });
});

test("08 axe 扫描：十个页面的日间和夜间", async ({ page }, info) => {
  const results: { page: string; theme: string; violations: any[] }[] = [];
  const scan = async (name: string) => {
    await expect(page.getByText(/^正在(读取|载入)/)).toHaveCount(0);
    await page.evaluate(() => document.fonts.ready);
    for (const value of ["day", "night"] as const) {
      await theme(page, value);
      // Colours ease over to the other theme; the scan starts once they have arrived, not halfway.
      await expect.poll(() => page.evaluate(() => document.getAnimations().filter(animation => animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity).length), { message: "the theme's colour transition has finished" }).toBe(0);
      const result = await new AxeBuilder({ page }).analyze();
      results.push({ page: name, theme: value, violations: result.violations.map(v => ({ id: v.id, impact: v.impact, description: v.description, help: v.help, helpUrl: v.helpUrl, nodes: v.nodes.map(n => ({ target: n.target, html: n.html, failureSummary: n.failureSummary })) })) });
      const capture: Record<string, string> = { "登录": "login", "首页新用户": "home", "作品管理": "works", "写作": "writing", "个人信息": "profile" };
      if (capture[name]) await shot(page, `${capture[name]}-${value}`, false);
    }
  };
  await page.goto("/login");
  await expect(page.getByRole("heading", { level: 1, name: "登录", exact: true })).toBeVisible();
  await scan("登录");
  await registerAccount(page, "axe08");
  await scan("首页新用户");
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  await scan("作品管理");
  const id = await sampleWorkId(page);
  for (const [label, tab] of [["概览", "overview"], ["写作", "workspace"], ["章节", "sources"], ["资料事实", "memory"], ["计划", "plan"]] as const) {
    await openTab(page, id, tab);
    if (tab === "overview") await expect(page.getByRole("img", { name: /^故事航线：/ })).toBeVisible();
    if (tab === "sources") await expect(page.getByRole("table", { name: "全部章节", exact: true }).getByRole("rowgroup")).toHaveCount(11);
    await scan(label);
  }
  await page.goto(`/projects/${id}/memory?view=people`);
  await expect(page.getByRole("article").first()).toBeVisible();
  await scan("资料人物");
  await page.goto("/account/profile");
  await expect(page.getByRole("heading", { level: 1, name: "E2E 作者", exact: true })).toBeVisible();
  await scan("个人信息");
  await evidence(info, "axe-results", results);
  // The writing page has its one h1 (unseen), so axe no longer asks for one.
  expect(results.flatMap(r => r.violations.map(v => `${r.page}/${r.theme}: ${v.id}`)).filter(item => item.endsWith("page-has-heading-one"))).toEqual([]);
  const severe = results.flatMap(r => r.violations.filter(v => ["critical", "serious"].includes(v.impact)).map(v => ({ page: r.page, theme: r.theme, ...v })));
  expect(severe, JSON.stringify(severe, null, 2)).toEqual([]);
});

function hasVisibleFocus(s: { outline: string; width: string; color: string; shadow: string }) {
  const nonTransparent = (color: string) => color.startsWith("rgb(") || (color.startsWith("rgba(") && Number(color.slice(5, -1).split(",").at(-1)) > 0);
  return (s.outline !== "none" && s.width !== "0px" && nonTransparent(s.color))
    || (s.shadow.match(/rgba?\([^)]*\)/g) ?? []).some(nonTransparent);
}

test("12 Q 焦点判据拒绝透明描边和阴影", () => {
  expect(hasVisibleFocus({ outline: "solid", width: "3px", color: "rgba(0, 0, 0, 0)", shadow: "rgba(0, 0, 0, 0) 0px 0px 3px" })).toBe(false);
  expect(hasVisibleFocus({ outline: "none", width: "0px", color: "rgb(0, 0, 0)", shadow: "rgba(0, 0, 0, 0) 0px 0px 3px, rgb(40, 40, 255) 0px 0px 2px" })).toBe(true);
});

async function focusVisible(page: Page) {
  const focused = page.locator(":focus-visible");
  await expect(focused).toHaveCount(1);
  const read = () => focused.evaluate(e => ({ element: e.outerHTML.slice(0, 500), outline: getComputedStyle(e).outlineStyle, width: getComputedStyle(e).outlineWidth, color: getComputedStyle(e).outlineColor, shadow: getComputedStyle(e).boxShadow }));
  // Focus shadows transition from transparent; require a visible colour before moving on.
  await expect.poll(async () => hasVisibleFocus(await read())).toBe(true);
  return read();
}
async function tabTo(page: Page, target: Locator, checks: Awaited<ReturnType<typeof focusVisible>>[]) {
  for (let i = 0; i < 160; i++) {
    await page.keyboard.press("Tab");
    checks.push(await focusVisible(page));
    if (await target.evaluate(e => e === document.activeElement)) return;
  }
  throw new Error("160 次 Tab 后仍无法聚焦目标控件");
}

test("08 键盘决定：焦点框与不是问题写入", async ({ page }, info) => {
  const id = await setup(page), before = await run(page, id), issue = before.issues[0];
  const checks: Awaited<ReturnType<typeof focusVisible>>[] = [];
  await tabTo(page, finding(page, issue.id), checks);
  await page.keyboard.press("Enter");
  await expect(finding(page, issue.id)).toHaveAttribute("aria-expanded", "true");
  await tabTo(page, button(page, "不是问题"), checks);
  await page.keyboard.press("Enter");
  await expect.poll(async () => (await run(page, id, before.run_id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("false_positive");
  await evidence(info, "keyboard-focus", checks);
  await shot(page, "keyboard-decision-day", false);
  expect(checks.filter(s => !hasVisibleFocus(s)), "每个键盘焦点必须有不透明的 outline 或 box-shadow").toEqual([]);
});

test("08 对话框焦点：初始焦点循环和 Esc 返回", async ({ page }, info) => {
  await sample(page);
  await workMenu(page, "重置作品");
  const d = page.getByRole("dialog", { name: "重置作品", exact: true });
  await expect.poll(() => d.evaluate(e => e.contains(document.activeElement))).toBe(true);
  for (let i = 0; i < 8; i++) {
    await page.keyboard.press(i < 4 ? "Tab" : "Shift+Tab");
    await expect.poll(() => d.evaluate(e => e.contains(document.activeElement))).toBe(true);
  }
  await page.keyboard.press("Escape");
  await expect(d).toHaveCount(0);
  await evidence(info, "dialog-return-focus", await page.evaluate(() => ({ activeTag: document.activeElement?.tagName, activeText: document.activeElement?.textContent?.slice(0, 120) })));
  // The menu item went away with the menu, so focus goes to the button that opened the menu.
  await expect(page.getByLabel("更多：导出、编辑信息、归档", { exact: true })).toBeFocused();
});

test("08 抽屉焦点：原文出处关闭后回到打开它的那一条依据", async ({ page }) => {
  const id = await setup(page), issue = (await run(page, id)).issues[0];
  await finding(page, issue.id).click();
  const evidence = page.getByRole("complementary", { name: "检查与回顾", exact: true }).getByRole("button", { name: /^第 \d+ 章/ }).first();
  await evidence.click();
  const drawer = page.getByRole("dialog", { name: /^第 \d+ 章/ });
  await expect(drawer).toBeVisible();
  await expect.poll(() => drawer.evaluate(e => e.contains(document.activeElement))).toBe(true);
  await page.keyboard.press("Escape");
  await expect(drawer).toHaveCount(0);
  await expect(evidence).toBeFocused();
});
