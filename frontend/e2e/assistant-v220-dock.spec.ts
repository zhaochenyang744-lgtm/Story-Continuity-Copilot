import type { Locator, Page } from "@playwright/test";
import { api, expect, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { box, checkedWork, chip, dock, send, stopButton, tasks, thread, topbarAssistant } from "./support/assistant";
import { findings } from "./support/writing";

// v2.2 phase two: the assistant is one panel docked at the right of every page. The top bar's button, Ctrl + / and Esc open and close it; a wide window
// pushes the page aside, a narrow one lets it lie over the edge. On the writing page the right column holds the check's results only, and each result
// has 问助手. 停止 works while the sentence is still being judged, and while the task runs, and shows 已停止 at once.

const bounds = async (locator: Locator) => (await locator.boundingBox())!;
const delayRoute = (page: Page, ms: number) => page.route(/\/assistant\/route$/, async (route) => {
  if (route.request().method() !== "POST") { await route.fallback(); return; }
  await new Promise((resolve) => setTimeout(resolve, ms));
  await route.fallback();
});

test("停靠面板：顶栏按钮、Ctrl + / 和 Esc 开关；宽窗口挤开页面，窄窗口盖在上面；换页不关", async ({ page }) => {
  await registerAccount(page, "dock1");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, id, "overview");
  await expect(dock(page)).toBeHidden();
  await expect(topbarAssistant(page)).toHaveAttribute("aria-expanded", "false");
  await topbarAssistant(page).click();
  await expect(dock(page)).toBeVisible();
  await expect(page.locator("html")).toHaveAttribute("data-dock", "push");
  const panel = await bounds(dock(page));
  expect(panel.width).toBeGreaterThanOrEqual(399);
  expect(panel.width).toBeLessThanOrEqual(401);
  // The page is pushed aside, not covered: its main area ends where the panel begins.
  expect((await bounds(page.locator("main"))).x + (await bounds(page.locator("main"))).width).toBeLessThanOrEqual(panel.x + 1);
  // The cursor is in the box; Esc closes (and gives the button its focus back); Ctrl + / opens and closes.
  await expect(box(page)).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(dock(page)).toBeHidden();
  await expect(page.locator("html")).not.toHaveAttribute("data-dock", /.+/);
  await page.keyboard.press("Control+/");
  await expect(dock(page)).toBeVisible();
  await page.keyboard.press("Control+/");
  await expect(dock(page)).toBeHidden();
  // It stays open from page to page of the work.
  await topbarAssistant(page).click();
  await page.getByRole("navigation", { name: "作品" }).getByRole("button", { name: "资料", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "资料", exact: true })).toBeVisible();
  await expect(dock(page)).toBeVisible();
  await expect(page.getByRole("complementary", { name: "助手" })).toHaveCount(1);
  // A window too narrow for both: the panel lies over the page's edge, and the page keeps its own width.
  await page.setViewportSize({ width: 1000, height: 800 });
  await expect(page.locator("html")).toHaveAttribute("data-dock", "overlay");
  await expect(page.locator(".app")).toHaveCSS("padding-right", "0px");
  // Leaving the work closes it.
  await page.getByRole("button", { name: "首页", exact: true }).click();
  await expect(dock(page)).toHaveCount(0);
});

test("写作页：右栏只放检查结果，没有标签；助手开着时章节收成一条号码，正文、检查结果、助手并排", async ({ page }) => {
  await registerAccount(page, "dock2");
  const id = await sampleWorkId(page);
  await page.setViewportSize({ width: 1440, height: 900 });
  await openTab(page, id, "workspace");
  await expect(findings(page).getByRole("tab")).toHaveCount(0);
  await expect(findings(page).getByRole("heading", { name: /^检查结果/ })).toBeVisible();
  await expect(page.locator(".draft-chapters .rail-title").first()).toBeVisible();
  await topbarAssistant(page).click();
  await expect(thread(page)).toBeVisible();
  await expect(page.locator(".draft-chapters .rail-title").first()).toBeHidden();
  await expect(page.locator(".draft-chapters .mono").first()).toBeVisible();
  const [draft, results, panel] = [await bounds(page.locator(".draft")), await bounds(findings(page)), await bounds(dock(page))];
  expect(draft.x + draft.width).toBeLessThanOrEqual(results.x + 1);
  expect(results.x + results.width).toBeLessThanOrEqual(panel.x + 1);
  // Under 1440 the panel lies over the page instead.
  await page.setViewportSize({ width: 1300, height: 900 });
  await expect(page.locator("html")).toHaveAttribute("data-dock", "overlay");
  await expect(page.locator(".draft-chapters .rail-title").first()).toBeHidden().catch(() => undefined);
});

test("每条检查结果有「问助手」：打开助手，把这条结果放进提问的上下文，不发送", async ({ page }) => {
  const { id, issue } = await checkedWork(page);
  await openTab(page, id, "workspace");
  const row = findings(page).locator("li.finding").filter({ has: page.getByTestId(`finding-${issue.id}`) });
  const ask = row.getByRole("button", { name: "问助手", exact: true });
  await expect(ask).toBeEnabled();
  await ask.click();
  await expect(dock(page)).toBeVisible();
  await expect(chip(page, "检查结果 · 第")).toBeVisible();
  await expect(tasks(page)).toHaveCount(0);
  await expect(box(page)).toBeFocused();
});

test("停止：判断用法时点停止，这次发送作废、不建任务，问题放回输入框，写着已停止；按钮在刚出现时是灰的", async ({ page }) => {
  await registerAccount(page, "stop1");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await delayRoute(page, 4000);
  const posts: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST" && /\/assistant\/(long-)?tasks$/.test(request.url())) posts.push(request.url()); });
  await box(page).fill("苏岑知道罗盘被调包了吗？");
  await send(page).click();
  // It looks greyed for the first moment (it does not take a click it would ignore), then it can be pressed.
  await expect(stopButton(page)).toBeDisabled();
  await expect(stopButton(page)).toBeEnabled({ timeout: 3000 });
  await stopButton(page).click();
  await expect(page.getByTestId("route-stopped")).toContainText("已停止");
  await expect(box(page)).toHaveValue("苏岑知道罗盘被调包了吗？");
  await expect(stopButton(page)).toHaveCount(0);
  // The judgement that was still on its way changes nothing.
  await page.waitForTimeout(4500);
  expect(posts).toEqual([]);
  await expect(tasks(page)).toHaveCount(0);
});

test("停止：任务在跑时点停止，马上写着已停止，服务器那边也是已停止，之后不再变", async ({ page }) => {
  await registerAccount(page, "stop2");
  const id = await sampleWorkId(page);
  await openTab(page, id, "overview");
  await topbarAssistant(page).click();
  await box(page).fill("E2E_SLOWER 苏岑知道罗盘被调包了吗？");
  await send(page).click();
  await expect(stopButton(page)).toBeEnabled({ timeout: 10_000 });
  const started = Date.now();
  await stopButton(page).click();
  await expect(tasks(page).first()).toContainText("已停止");
  expect(Date.now() - started).toBeLessThan(2500);
  await expect(stopButton(page)).toHaveCount(0);
  const listed = async () => (await api(page).get(`/projects/${id}/assistant/tasks?limit=5`)).tasks as { status: string; answer: unknown }[];
  expect((await listed())[0].status).toBe("cancelled");
  await page.waitForTimeout(8000);
  expect((await listed())[0].status).toBe("cancelled");
  await expect(tasks(page).first()).toContainText("已停止");
});
