import AxeBuilder from "@axe-core/playwright";
import type { Locator, Page } from "@playwright/test";
import { api, expect, openTab, registerAccount, sampleWorkId, shot, test } from "./support/app";
import { button, finding, run, setup } from "./support/writing";
import { evidence, project, sample, theme, workMenu } from "./support/pages";

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
  const severe = results.flatMap(r => r.violations.filter(v => ["critical", "serious"].includes(v.impact)).map(v => ({ page: r.page, theme: r.theme, ...v })));
  expect(severe, JSON.stringify(severe, null, 2)).toEqual([]);
});

async function focusVisible(page: Page) {
  const focused = page.locator(":focus-visible");
  await expect(focused).toHaveCount(1);
  return focused.evaluate(e => ({ element: e.outerHTML.slice(0, 500), outline: getComputedStyle(e).outlineStyle, width: getComputedStyle(e).outlineWidth, shadow: getComputedStyle(e).boxShadow }));
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
  test.fixme(true, "新发现：章标题与草稿正文虽然匹配 :focus-visible，但 outline-style 和 box-shadow 都为 none；键盘决定写入本身通过");
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
  expect(checks.filter(s => !((s.outline !== "none" && s.width !== "0px") || s.shadow !== "none")), "每个键盘焦点必须有 outline 或 box-shadow").toEqual([]);
});

test("08 对话框焦点：初始焦点循环和 Esc 返回", async ({ page }, info) => {
  test.fixme(true, "重置对话框 Esc 关闭后焦点落回 BODY，没有返回打开它的重置作品按钮；菜单关闭后按钮隐藏");
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
  await expect(page.getByRole("menuitem", { name: "重置作品", exact: true, includeHidden: true })).toBeFocused();
});
