import { mkdir } from "node:fs/promises";
import path from "node:path";
import type { Locator, Page } from "@playwright/test";
import { api, expect, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { box, chooseMode, send, thread, topbarAssistant } from "./support/assistant";
import { askView, serveTasks } from "./support/assistant-mock";
import { closeDrawer, openDrawer, openLedger, threadRecords, threadsView } from "./support/assistant-change";
import { theme } from "./support/pages";
import { ownWork } from "./support/writing";

// v2.1 B (task 19): the long task in the assistant. The test model (backend/tests/e2e_app.py) plans a thread audit over the whole work and, in each
// step, marks the first thread it is shown as resolved on the last chapter of the step. Markers in the sentence steer it:
//   E2E_LONG_NONE        a kind that cannot be done       E2E_LONG_CH6         chapters 6–10 from the start
//   E2E_LONG_ABANDON     the second thread of the first step is given up (a card of its own)
//   E2E_LONG_COSTLY      each step costs 0.6 yuan (with the ceiling at 0.5 the task stops and asks)
//   E2E_LONG_PLAN_SLOW   the plan takes 3 s    E2E_LONG_SLOW  each step takes 2.5 s    E2E_LONG_BAD  the report cannot validate (the task fails)
// The sample work has 10 chapters and three open threads (planted in 4, 5 and 7). Pictures for the delivery report are taken only when LONG_SHOTS_DIR is set.

const ASK = "那些还吊着的伏笔都替我过一遍";
const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();
const rect = (locator: Locator) => locator.evaluate((node) => { const box = node.getBoundingClientRect(); return { left: box.left, right: box.right, top: box.top, bottom: box.bottom, width: box.width, height: box.height }; });
const style = (locator: Locator, property: string) => locator.evaluate((node, name) => getComputedStyle(node).getPropertyValue(name), property);
const count = (value: number) => value.toLocaleString("en-US");
const BLUE = "rgb(31, 43, 255)";
const RED = "rgb(196, 42, 10)";

const long = (page: Page) => thread(page).locator('[data-kind="long"]').last();
const planCard = (page: Page) => thread(page).getByTestId("long-plan");
const question = (page: Page) => thread(page).getByTestId("long-question");
const groups = (page: Page) => thread(page).getByTestId("long-groups");
const group = (page: Page, name: string) => groups(page).getByRole("region", { name, exact: true });
const status = (page: Page, value: string, timeout = 40_000) => expect(long(page)).toHaveAttribute("data-status", value, { timeout });
const longRequest = (page: Page, tail: string) => page.waitForRequest((request) => request.method() === "POST" && new RegExp(`/assistant/long-tasks${tail}$`).test(request.url()));
const viewOf = async (page: Page, id: string) => {
  const tasks = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks as { id: string; kind: string }[];
  const task = tasks.filter((item) => item.kind === "long").at(-1)!;
  return api(page).get(`/projects/${id}/assistant/long-tasks/${task.id}`);
};

async function snap(page: Page, name: string) {
  const directory = process.env.LONG_SHOTS_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  await page.evaluate(async () => { await document.fonts.ready; });
  await page.screenshot({ path: path.join(directory, `${name}.png`), animations: "disabled" });
}
/** The same state at 1440 and 390, by day and by night. The drawer covers the theme switch: it is closed for the switch and opened again. */
async function photograph(page: Page, name: string, sizes: [number, number][] = [[1440, 1000], [390, 1500]], prepare?: () => Promise<void>) {
  if (!process.env.LONG_SHOTS_DIR) return;
  const top = long(page);
  const wanted = (await top.getAttribute("data-task"))!;
  for (const [width, height] of sizes) {
    for (const mode of ["day", "night"] as const) {
      await page.setViewportSize({ width, height });
      const drawer = page.getByRole("dialog", { name: "助手", exact: true });
      if (await drawer.count()) { await page.getByRole("button", { name: "关闭助手", exact: true }).click(); await expect(drawer).toHaveCount(0); }
      await theme(page, mode);
      await topbarAssistant(page).click();
      await expect(thread(page)).toBeVisible();
      // A state that lives in the card (an open form) is made again after the drawer has been shut and opened.
      await prepare?.();
      const task = thread(page).locator(`[data-task="${wanted}"]`);
      await task.scrollIntoViewIfNeeded();
      await snap(page, `${name}-${width}-${mode === "day" ? "浅色" : "深色"}`);
    }
  }
  // Back to day and the wide window (the drawer covers the theme switch, so it is shut for it and opened again).
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "关闭助手", exact: true }).click();
  await expect(page.getByRole("dialog", { name: "助手", exact: true })).toHaveCount(0);
  await theme(page, "day");
  await topbarAssistant(page).click();
  await expect(thread(page)).toBeVisible();
  await prepare?.();
}

/** The top bar (with the dot on its 助手 button), by day and by night, at 1440 and 390. */
async function photographBar(page: Page, name: string) {
  const directory = process.env.LONG_SHOTS_DIR;
  if (!directory) return;
  await mkdir(directory, { recursive: true });
  for (const width of [1440, 390]) {
    await page.setViewportSize({ width, height: 900 });
    for (const mode of ["day", "night"] as const) {
      await theme(page, mode);
      await page.getByRole("banner").screenshot({ path: path.join(directory, `${name}-${width}-${mode === "day" ? "浅色" : "深色"}.png`), animations: "disabled" });
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await theme(page, "day");
}

/** A registered author on the sample work's overview page with the assistant open. `own` makes the sample an ordinary work (it then takes characters). */
async function open(page: Page, own = false) {
  await registerAccount(page, "l19");
  const id = await sampleWorkId(page);
  if (own) await ownWork(page, id);
  await openTab(page, id, "overview");
  await openDrawer(page);
  return id;
}
/** Say it to the box in 长任务 mode and send. */
async function sendLong(page: Page, text: string) {
  await chooseMode(page, "长任务");
  await box(page).fill(text);
  const request = longRequest(page, "");
  await send(page).click();
  return request;
}
/** A plan card on screen for `text`. */
async function planned(page: Page, text: string) {
  await sendLong(page, text);
  await expect(planCard(page)).toBeVisible({ timeout: 20_000 });
}
async function adjust(page: Page, values: { from?: number; to?: number; cap?: number }) {
  const plan = planCard(page);
  if (!(await plan.getByRole("form", { name: "调整计划" }).count())) await plan.getByRole("button", { name: "调整", exact: true }).click();
  const form = plan.getByRole("form", { name: "调整计划" });
  if (values.from !== undefined) await form.getByRole("spinbutton", { name: "起始章" }).fill(String(values.from));
  if (values.to !== undefined) await form.getByRole("spinbutton", { name: "结束章" }).fill(String(values.to));
  if (values.cap !== undefined) await form.getByRole("spinbutton", { name: "费用上限" }).fill(String(values.cap));
  await form.getByRole("button", { name: "保存修改", exact: true }).click();
}
const start = (page: Page) => planCard(page).getByRole("button", { name: "开始", exact: true }).click();

/** A long task view made by hand, for the states that cannot be held still on a real server. */
function longView(over: Record<string, unknown> = {}) {
  const steps = [
    { kind: "read", chapters: [1, 5], look_for: "还没收的伏笔在这几章里收了没有、是不是写明不追了", produces: ["resolve_thread", "abandon_thread"], chars: 5385 },
    { kind: "read", chapters: [6, 10], look_for: "还没收的伏笔在这几章里收了没有、是不是写明不追了", produces: ["resolve_thread", "abandon_thread"], chars: 5249 },
    { kind: "report", produces: [] },
  ];
  const body = { type: "thread_audit", target: null, output: "list", chapters: [1, 10], steps, est_chars: 10634, est_cny: 0.08, open_threads: 3, produces: ["abandon_thread", "resolve_thread"] };
  return {
    ...askView({ id: "atask-long-mock", kind: "long", status: "long_running", question: ASK, context: { page: "overview" }, steps: [], answer: null, sources: {}, coverage: null,
      usage: { steps: 0, chars_charged: 500 }, created_at: ago(100), started_at: ago(70), completed_at: null }),
    plan: { proposed: body, approved: body, cap_cny: 2, est_chars: 10634, est_cny: 0.08, chars_read: 5385, stop_requested: false },
    long_steps: [
      { ordinal: 1, spec: steps[0], status: "done", attempt: 1, found: 3, cost_cny: 0.03 },
      { ordinal: 2, spec: steps[1], status: "running", attempt: 1, found: 0, cost_cny: 0 },
      { ordinal: 3, spec: steps[2], status: "pending", attempt: 0, found: 0, cost_cny: 0 },
    ],
    progress: { done: 1, total: 3, cost_cny: 0.31, cap_cny: 2 }, questions: [], changes: [],
    ...over,
  };
}
/** Make the page read this long task (in the conversation's list and at its own address) as given. */
async function serveLong(page: Page, view: () => Record<string, unknown>) {
  await serveTasks(page, () => [view()]);
  await page.route(/\/assistant\/long-tasks\/[^/]+$/, async (route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: view(), request_id: "mock" }) });
  });
}

test.describe("长任务：入口和计划", () => {
  test("模式菜单里有「长任务」和它的说明；选它发送走 POST /long-tasks；计划卡的步骤、字数、费用和接口一致", async ({ page }) => {
    const id = await open(page);
    await thread(page).getByRole("button", { name: /^这次做什么：/ }).click();
    const menu = thread(page).getByRole("menu", { name: "这次让助手做什么" });
    await expect(menu.getByRole("menuitemradio", { name: "长任务", exact: true })).toContainText("先列计划，你点头后在后台做");
    await expect(menu.getByRole("menuitemradio", { name: "长任务", exact: true })).not.toHaveAttribute("aria-disabled", "true");
    await menu.getByRole("menuitemradio", { name: "长任务", exact: true }).click();
    await box(page).fill(`E2E_LONG_PLAN_SLOW ${ASK}`);
    const request = longRequest(page, "");
    await send(page).click();
    const body = (await request);
    expect(body.postDataJSON()).toEqual({ question: `E2E_LONG_PLAN_SLOW ${ASK}`, context: { page: "overview" }, origin: "mode" });
    expect(body.headers()["idempotency-key"]).toBeTruthy();
    // The box is empty and back on 自动 at once; the conversation says the plan is being made.
    await expect(box(page)).toHaveValue("");
    await expect(thread(page).getByRole("button", { name: "这次做什么：自动", exact: true })).toBeVisible();
    await expect(long(page).locator(".a-ask")).toContainText(ASK);
    await expect(thread(page).getByTestId("long-planning")).toContainText("长任务 · 正在列计划…");
    await photograph(page, "01-列计划中");
    await expect(planCard(page)).toBeVisible({ timeout: 20_000 });
    await expect(thread(page).getByTestId("long-planning")).toHaveCount(0);

    const view = await viewOf(page, id);
    const proposed = view.plan.proposed;
    expect(view.status).toBe("awaiting_plan");
    const plan = planCard(page);
    await expect(plan.locator(".a-card-head")).toContainText("长任务 · 计划");
    await expect(plan.locator(".a-card-head")).toContainText("点「开始」才读正文");
    const steps = plan.locator(".a-long-steps li");
    await expect(steps).toHaveCount(proposed.steps.length);
    for (const [index, step] of proposed.steps.entries()) {
      if (step.kind === "read") {
        await expect(steps.nth(index)).toContainText(`第 ${step.chapters[0]}–${step.chapters[1]} 章`);
        await expect(steps.nth(index)).toContainText(step.look_for);
      } else await expect(steps.nth(index)).toContainText("汇总");
    }
    await expect(steps.nth(0).locator(".n")).toHaveText("1");
    await expect(plan.getByTestId("long-estimate")).toContainText(`约读 ${count(proposed.est_chars)} 字 · 预计 ¥${proposed.est_cny.toFixed(2)} · 上限 ¥2`);
    await expect(plan.getByTestId("long-quota")).toContainText("示例作品不计字数");
    for (const name of ["开始", "改范围", "不做", "调整"]) await expect(plan.getByRole("button", { name, exact: true })).toBeVisible();
    expect(await style(plan.getByRole("button", { name: "开始", exact: true }), "background-color")).toBe(BLUE);
    await photograph(page, "02-计划卡");
  });

  test("改范围：表单里改起止章和上限，提交后步骤变成一步，字数和上限跟着变；范围不对时说明原因", async ({ page }) => {
    const id = await open(page);
    await planned(page, ASK);
    const before = (await viewOf(page, id)).plan;
    await planCard(page).getByRole("button", { name: "改范围", exact: true }).click();
    const form = planCard(page).getByRole("form", { name: "调整计划" });
    await expect(form).toBeVisible();
    await expect(form.getByRole("spinbutton", { name: "起始章" })).toHaveValue("1");
    await expect(form.getByRole("spinbutton", { name: "结束章" })).toHaveValue("10");
    await expect(form.getByRole("spinbutton", { name: "费用上限" })).toHaveValue("2");
    await photograph(page, "03-改范围表单", undefined, async () => { await planCard(page).getByRole("button", { name: "改范围", exact: true }).click(); await expect(planCard(page).getByRole("form", { name: "调整计划" })).toBeVisible(); });
    // A range the work does not have is refused where it is typed, nothing is sent.
    await form.getByRole("spinbutton", { name: "起始章" }).fill("8");
    await form.getByRole("spinbutton", { name: "结束章" }).fill("3");
    await form.getByRole("button", { name: "保存修改", exact: true }).click();
    await expect(planCard(page).getByRole("alert")).toContainText("章节范围不对");
    await adjust(page, { from: 6, to: 10, cap: 1.5 });
    await expect(planCard(page).getByRole("form", { name: "调整计划" })).toHaveCount(0);
    const after = (await viewOf(page, id)).plan;
    expect(after.proposed.steps.map((step: { chapters?: number[] }) => step.chapters ?? null)).toEqual([[6, 10], null]);
    expect(after.cap_cny).toBe(1.5);
    expect(after.est_chars).toBeLessThan(before.est_chars);
    const steps = planCard(page).locator(".a-long-steps li");
    await expect(steps).toHaveCount(2);
    await expect(steps.nth(0)).toContainText("第 6–10 章");
    await expect(steps.nth(1)).toContainText("汇总");
    await expect(planCard(page).getByTestId("long-estimate")).toContainText(`约读 ${count(after.est_chars)} 字 · 预计 ¥${after.proposed.est_cny.toFixed(2)} · 上限 ¥1.5`);
  });

  test("不做：计划卡收起，留一行「没有开始就停下了」，字数没有动，可以再开新的", async ({ page }) => {
    const id = await open(page, true);
    const usage = await api(page).get("/account/usage");
    await planned(page, ASK);
    const stopped = longRequest(page, "/[^/]+/stop");
    await planCard(page).getByRole("button", { name: "不做", exact: true }).click();
    await stopped;
    await expect(planCard(page)).toHaveCount(0);
    await status(page, "stopped");
    await expect(long(page).getByTestId("long-note")).toHaveText("没有开始就停下了。");
    expect((await viewOf(page, id)).status).toBe("stopped");
    // Only the plan was charged (a question's worth); nothing was read.
    expect((await api(page).get("/account/usage")).check_chars_used - usage.check_chars_used).toBe(500);
    await planned(page, ASK);
    await expect(thread(page).locator('[data-kind="long"]')).toHaveCount(2);
  });

  test("这类长任务做不了：不出计划卡，一行说明", async ({ page }) => {
    await open(page);
    await sendLong(page, `E2E_LONG_NONE 帮我把第三卷重写一遍`);
    await status(page, "completed");
    await expect(planCard(page)).toHaveCount(0);
    await expect(long(page).getByTestId("long-note")).toContainText("这类长任务现在还做不了");
  });

  test("自动判断出「长任务」时也走 POST /long-tasks；访客的同一句按问题处理", async ({ page, browser }) => {
    const answer = { data: { route: "long_task", source: "model", unsure: false }, request_id: "mock" };
    const id = await open(page);
    await page.route(/\/assistant\/route$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(answer) }));
    await box(page).fill(ASK);
    const created = longRequest(page, "");
    await send(page).click();
    expect((await created).postDataJSON()).toEqual({ question: ASK, context: { page: "overview" }, origin: "route" });
    await expect(planCard(page)).toBeVisible({ timeout: 20_000 });
    expect((await viewOf(page, id)).kind).toBe("long");

    const guest = await (await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 1440, height: 960 } })).newPage();
    await guest.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await startVisitor(guest);
    await openTab(guest, await sampleWorkId(guest), "overview");
    await openDrawer(guest);
    await guest.route(/\/assistant\/route$/, (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(answer) }));
    await box(guest).fill(ASK);
    const asked = guest.waitForRequest((request) => request.method() === "POST" && /\/assistant\/tasks$/.test(request.url()));
    await send(guest).click();
    expect((await asked).postDataJSON().kind).toBe("ask");
    await guest.context().close();
  });

  test("访客：模式菜单里的「长任务」置灰，指上去写「注册后可以用」，点了不会换模式", async ({ page }) => {
    await startVisitor(page);
    await openTab(page, await sampleWorkId(page), "overview");
    await openDrawer(page);
    await thread(page).getByRole("button", { name: /^这次做什么：/ }).click();
    const item = thread(page).getByRole("menuitemradio", { name: "长任务", exact: true });
    await expect(item).toBeVisible();
    await expect(item).toHaveAttribute("aria-disabled", "true");
    await expect(item).toHaveAttribute("title", "注册后可以用");
    expect(await style(item, "cursor")).toBe("not-allowed");
    // aria-disabled keeps it reachable (so the reason can be read); Playwright would wait for it to become enabled, so the click is forced.
    await item.click({ force: true });
    await expect(thread(page).getByRole("button", { name: "这次做什么：自动", exact: true })).toBeVisible();
  });
});

test.describe("长任务：做、问、报告、确认", () => {
  test("开始：进度行和细进度条，到「第 k/n 步」；做完后一行「做完了」，报告按小节排，标签加粗，每条一个出处标记，末尾有覆盖说明", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page);
    await planned(page, `E2E_LONG_SLOW ${ASK}`);
    const started = longRequest(page, "/[^/]+/start");
    await start(page);
    expect((await started).postDataJSON()).toEqual({});
    const progress = thread(page).getByTestId("long-progress");
    await expect(progress).toBeVisible();
    await expect(progress).toContainText(/第 [1-3]\/3 步 · 已用 (¥\d\.\d\d|不到 ¥0\.01) · 用时 不到 1 分钟/);
    await expect(progress.getByRole("progressbar", { name: "长任务进度" })).toHaveAttribute("aria-valuemax", "3");
    await expect(progress.getByRole("button", { name: "停止", exact: true })).toBeVisible();
    expect(await rect(progress.locator(".a-long-bar"))).toMatchObject({ height: 3 });
    // The step goes on while the conversation is polled every 2 seconds; the line moves to a later step.
    await expect(progress).toContainText(/第 [23]\/3 步/, { timeout: 15_000 });
    await status(page, "completed");
    await expect(progress).toHaveCount(0);

    const view = await viewOf(page, id);
    const end = thread(page).getByTestId("long-end");
    await expect(end).toHaveText(/^做完了 · 不到 1 分钟 · (¥\d\.\d\d|不到 ¥0\.01)$/);
    expect(await style(end, "font-size")).toBe("11px");
    const report = thread(page).getByTestId("long-report");
    const sections = Object.entries(view.answer.sections) as [string, { label: string; refs: string[] }[]][];
    const total = sections.reduce((sum, [, items]) => sum + items.length, 0);
    await expect(report.locator("h4")).toHaveText(sections.map(([title]) => title));
    expect(await style(report.locator("h4").first(), "font-size")).toBe("13px");
    expect(await style(report.locator("h4").first(), "font-weight")).toBe("700");
    await expect(report.getByTestId("long-count")).toContainText(`共 ${total} 条：${sections.map(([title, items]) => `${title} ${items.length} 条`).join("，")}`);
    const items = report.locator(".a-points li");
    await expect(items).toHaveCount(total);
    expect(await report.locator(".a-points b").allTextContents()).toEqual(sections.flatMap(([, entries]) => entries.map((entry) => entry.label)));
    expect(await style(report.locator(".a-points b").first(), "font-weight")).toBe("700");
    for (let index = 0; index < total; index += 1) await expect(items.nth(index).locator(".a-cite")).toHaveCount(1);
    await expect(report.getByTestId("long-cover")).toContainText("查过第 1–10 章正文、伏笔记录；没查：本章草稿");
    expect(await style(report.getByTestId("long-cover").locator("strong"), "font-weight")).toBe("700");
    await expect(report.getByRole("button", { name: /^出处 \d+ 处/ })).toBeVisible();
    // Two cards of one kind: 标已回收, 2 条; nothing is written before the author says so.
    await expect(group(page, "标已回收")).toContainText("标已回收 · 2 条");
    await expect(group(page, "标已回收")).toContainText("整组确认");
    await expect(group(page, "标已回收").getByRole("button", { name: "确认 2 条", exact: true })).toBeVisible();
    expect((await threadRecords(page, id)).filter((item) => item.status === "resolved")).toHaveLength(0);
    await photograph(page, "06-报告和分组卡片");
  });

  test("按组确认：只写下这一组（within 是这一组，accepted 是勾上的），另一组还在；标放弃单独一张、红边、不能整批确认；撤销后和任务 18 的卡片一样", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page);
    await planned(page, `E2E_LONG_ABANDON ${ASK}`);
    await start(page);
    await status(page, "completed");
    const view = await viewOf(page, id);
    const resolve = view.changes.filter((item: { kind: string }) => item.kind === "resolve_thread");
    const abandon = view.changes.filter((item: { kind: string }) => item.kind === "abandon_thread");
    expect([resolve.length, abandon.length]).toEqual([2, 1]);

    // The give-up is a card of its own with a red edge, no tick box, and its own button.
    const risky = group(page, "标放弃");
    await expect(risky).toHaveCount(1);
    await expect(risky).toContainText("标放弃 · 1 条");
    await expect(risky).toContainText("要一条条确认");
    expect(await style(risky, "box-shadow")).toContain(RED);
    await expect(risky.getByRole("checkbox")).toHaveCount(0);
    await expect(risky.getByRole("button", { name: "确认这一条", exact: true })).toBeVisible();
    await expect(risky.getByRole("button", { name: "不要", exact: true })).toHaveCount(0);
    const plain = group(page, "标已回收");
    await expect(plain.getByRole("checkbox")).toHaveCount(2);
    expect(await style(plain, "box-shadow")).not.toContain(RED);
    // The server refuses the two groups together.
    const everything = view.changes.map((item: { id: string }) => item.id);
    const refused = await api(page).raw("POST", `/projects/${id}/assistant/long-tasks/${view.id}/changes/confirm`, { accepted: everything, within: everything });
    expect(refused.status).toBe(422);
    expect(refused.body.error.code).toBe("assistant_long_confirm_alone");

    // One item of the group is left unticked: the ticked one is written, the unticked one still waits; 不要 turns it down.
    await plain.getByRole("checkbox").nth(1).uncheck();
    const confirm = longRequest(page, "/[^/]+/changes/confirm");
    await plain.getByRole("button", { name: "确认 1 条", exact: true }).click();
    const sent = (await confirm).postDataJSON();
    expect(sent.within).toEqual(resolve.map((item: { id: string }) => item.id));
    expect(sent.accepted).toEqual([resolve[0].id]);
    await expect(plain.getByTestId("change-written")).toContainText("已写入资料 · 1 条");
    await expect(plain.locator(`[data-change="${resolve[0].id}"]`)).toHaveAttribute("data-status", "applied");
    await expect(plain.locator(`[data-change="${resolve[1].id}"]`)).toHaveAttribute("data-status", "proposed");
    await expect(plain.getByRole("button", { name: "确认选中的", exact: true })).toBeVisible();
    const turnedDown = longRequest(page, "/[^/]+/changes/reject");
    await plain.getByRole("button", { name: "不要", exact: true }).click();
    await turnedDown;
    await expect(plain.locator(`[data-change="${resolve[1].id}"]`)).toHaveAttribute("data-status", "rejected");
    await expect(plain.locator(`[data-change="${resolve[1].id}"]`)).toContainText("没要");
    // The other group has not moved.
    await expect(risky.getByRole("button", { name: "确认这一条", exact: true })).toBeVisible();
    const records = await threadRecords(page, id);
    expect(records.find((item) => item.id === resolve[0].target.id)?.status).toBe("resolved");
    expect(records.find((item) => item.id === resolve[1].target.id)?.status).toBe("planted");
    expect(records.find((item) => item.id === abandon[0].target.id)?.status).toBe("planted");
    await photograph(page, "07-确认一组以后");

    // Taking it back: the same button as in the ledger; the item is quiet again and the thread is open.
    await plain.getByTestId("change-written").getByRole("button", { name: "撤销", exact: true }).click();
    await expect(plain.locator(`[data-change="${resolve[0].id}"]`)).toHaveAttribute("data-status", "undone");
    expect((await threadRecords(page, id)).find((item) => item.id === resolve[0].target.id)?.status).toBe("planted");

    // The give-up is confirmed by itself.
    const alone = longRequest(page, "/[^/]+/changes/confirm");
    await risky.getByRole("button", { name: "确认这一条", exact: true }).click();
    expect((await alone).postDataJSON()).toEqual({ accepted: [abandon[0].id], within: [abandon[0].id] });
    await expect(risky.locator(`[data-change="${abandon[0].id}"]`)).toHaveAttribute("data-status", "applied");
    expect((await threadRecords(page, id)).find((item) => item.id === abandon[0].target.id)?.status).toBe("abandoned");

    // 改动记录: the written items are in the ledger of the materials page, and 看对话 comes back to the long task.
    await closeDrawer(page);
    await threadsView(page, id, true);
    const ledger = await openLedger(page);
    const row = ledger.locator("li").filter({ hasText: abandon[0].title });
    await expect(row).toContainText("已写入");
    await row.getByRole("button", { name: "看对话", exact: true }).click();
    await expect(thread(page)).toBeVisible();
    await expect(long(page)).toBeInViewport();
    await expect(long(page).getByTestId("long-report")).toBeVisible();
  });

  test("到上限停下来问：提问卡左边一条蓝边；「提高上限到 ¥… 接着做」后做完，报告里记着问过一次", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page);
    await planned(page, `E2E_LONG_COSTLY ${ASK}`);
    await adjust(page, { cap: 0.5 });
    await expect(planCard(page).getByTestId("long-estimate")).toContainText("上限 ¥0.5");
    await start(page);
    await status(page, "waiting_author");
    const card = question(page);
    await expect(card).toBeVisible();
    await expect(card).toHaveAttribute("data-kind", "budget");
    await expect(card).toContainText("已经用了");
    await expect(card).toContainText("提高上限接着做，还是把已经做完的交给你");
    expect(await style(card, "box-shadow")).toContain(BLUE);
    await expect(thread(page).getByTestId("long-progress")).toContainText("等你回答");
    const view = await viewOf(page, id);
    expect(view.questions).toHaveLength(1);
    // A ceiling to raise it to is chosen next to the button, and the button says it.
    const raise = card.getByRole("button", { name: /^提高上限到 ¥[\d.]+ 接着做$/ });
    await expect(raise).toBeVisible();
    await expect(card.getByRole("button", { name: "到此为止", exact: true })).toBeVisible();
    await photograph(page, "05-提问卡-上限");
    await card.getByRole("combobox", { name: "新的上限" }).selectOption("2.5");
    await expect(card.getByRole("button", { name: "提高上限到 ¥2.5 接着做", exact: true })).toBeVisible();
    const answered = longRequest(page, "/[^/]+/answer");
    await card.getByRole("button", { name: "提高上限到 ¥2.5 接着做", exact: true }).click();
    expect((await answered).postDataJSON()).toEqual({ question_id: view.questions[0].id, choice: "continue", cap_cny: 2.5 });
    await status(page, "completed");
    await expect(question(page)).toHaveCount(0);
    expect((await viewOf(page, id)).plan.cap_cny).toBe(2.5);
    await expect(thread(page).getByTestId("long-asked")).toContainText("提高上限到 ¥2.5 接着做了");
    await expect(thread(page).getByTestId("long-end")).toContainText("做完了");
  });

  test("到上限时选「到此为止」：交出已经做完的，报告末尾写「中途停下了」，覆盖说明写明没读的章节", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page, true);
    await planned(page, `E2E_LONG_COSTLY ${ASK}`);
    await adjust(page, { cap: 0.5 });
    await start(page);
    await status(page, "waiting_author");
    const answered = longRequest(page, "/[^/]+/answer");
    await question(page).getByRole("button", { name: "到此为止", exact: true }).click();
    expect((await answered).postDataJSON().choice).toBe("stop");
    await status(page, "stopped");
    const view = await viewOf(page, id);
    expect(view.status).toBe("stopped");
    await expect(thread(page).getByTestId("long-end")).toHaveText(/^停下了 · 不到 1 分钟 · ¥\d\.\d\d$/);
    await expect(thread(page).getByTestId("long-note")).toContainText("中途停下了");
    await expect(thread(page).getByTestId("long-cover")).toContainText("查过第 1–5 章正文、伏笔记录；没查：第 6–10 章、本章草稿");
    // What the first step found is still on cards.
    await expect(group(page, "标已回收")).toContainText("标已回收 · 1 条");
    // What was not read is given back: the author paid for the plan and the first step's chapters only.
    expect(view.plan.chars_read).toBeLessThan(view.plan.est_chars);
    await photograph(page, "08-停下了");
  });

  test("失败：一行红色系提示，写明任务停了、字数已退回；字数真的退了", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page, true);
    const before = await api(page).get("/account/usage");
    await planned(page, `E2E_LONG_BAD ${ASK}`);
    await start(page);
    await status(page, "failed");
    const failed = thread(page).getByTestId("long-failed");
    await expect(failed).toHaveText("这一步的结果核对不过，任务停了，字数已退回。");
    expect(await style(failed, "color")).toBe(RED);
    expect(await style(failed, "border-top-color")).toBe(RED);
    expect((await viewOf(page, id)).error_code).toBe("assistant_long_report_invalid");
    await expect(failed.locator("xpath=..").locator(".a-long-report")).toHaveCount(0);
    expect((await api(page).get("/account/usage")).check_chars_used).toBe(before.check_chars_used);
    await photograph(page, "09-失败");
  });

  test("额度不够：计划卡先写清要读多少、今天还剩多少；开始被拒时说明并留在计划卡上，缩小范围后能开始", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page, true);
    await planned(page, ASK);
    const plan = (await viewOf(page, id)).plan;
    const quota = planCard(page).getByTestId("long-quota");
    const usage = await api(page).get("/account/usage");
    await expect(quota).toContainText(`要读约 ${count(plan.est_chars)} 字，你今天还剩 ${count(usage.check_chars_remaining)} 字`);
    expect(await style(quota, "color")).not.toBe(RED);
    // The day's allowance has less than the plan reads: the card says so beforehand, and the server refuses to start.
    const session = await api(page).get("/auth/session");
    await api(page).post(`/test/v180/users/${session.user.id}/spend-characters/${usage.check_chars_remaining - (plan.est_chars - 100)}`);
    await page.reload();
    await openDrawer(page);
    await expect(planCard(page)).toBeVisible();
    await expect(quota).toContainText(`你今天只剩 ${count(plan.est_chars - 100)} 字，不够读完。缩小章节范围再开始`);
    expect(await style(quota, "color")).toBe(RED);
    await start(page);
    await expect(planCard(page).getByRole("alert")).toContainText(`今天的可检查字数不够（要读约 ${count(plan.est_chars)} 字，还剩 ${count(plan.est_chars - 100)} 字）。缩小章节范围再开始。`);
    await expect(planCard(page)).toBeVisible();
    expect((await viewOf(page, id)).status).toBe("awaiting_plan");
    await adjust(page, { from: 6, to: 10 });
    await start(page);
    await status(page, "completed");
  });
});

test.describe("长任务：离开和回来", () => {
  test("顶栏的「助手」按钮：长任务做完时出一个小圆点，打开助手后消失，刷新后也不再出现", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page);
    await planned(page, `E2E_LONG_SLOW ${ASK}`);
    await start(page);
    await expect(thread(page).getByTestId("long-progress")).toBeVisible();
    await closeDrawer(page);
    const dot = page.getByTestId("assistant-dot");
    await expect(dot).toHaveCount(0);
    // The top bar follows the task by itself while the assistant is closed.
    await expect(dot).toBeVisible({ timeout: 40_000 });
    expect((await viewOf(page, id)).status).toBe("completed");
    await expect(topbarAssistant(page)).toContainText("长任务有新进展");
    await photographBar(page, "10-顶栏小圆点");
    await topbarAssistant(page).click();
    await expect(thread(page)).toBeVisible();
    await expect(dot).toHaveCount(0);
    await expect(long(page)).toHaveAttribute("data-status", "completed");
    await closeDrawer(page);
    await page.reload();
    await expect(topbarAssistant(page)).toBeVisible();
    await expect(page.getByTestId("assistant-dot")).toHaveCount(0);
  });

  test("等回答时也出小圆点；回来答完以后，圆点不会再出现", async ({ page }) => {
    test.setTimeout(120_000);
    await open(page);
    await planned(page, `E2E_LONG_COSTLY ${ASK}`);
    await adjust(page, { cap: 0.5 });
    await start(page);
    await closeDrawer(page);
    await expect(page.getByTestId("assistant-dot")).toBeVisible({ timeout: 40_000 });
    await openDrawer(page);
    await expect(page.getByTestId("assistant-dot")).toHaveCount(0);
    await expect(question(page)).toBeVisible();
    await question(page).getByRole("button", { name: "到此为止", exact: true }).click();
    await status(page, "stopped");
    await closeDrawer(page);
    // The author was looking when it ended: nothing new to point at.
    await expect(page.getByTestId("assistant-dot")).toHaveCount(0);
  });

  test("刷新页面后，对话里读回长任务的计划、问题和卡片（对话列表里的是简版，长任务自己的地址补全）", async ({ page }) => {
    test.setTimeout(120_000);
    const id = await open(page);
    await planned(page, ASK);
    await page.reload();
    await openDrawer(page);
    await expect(planCard(page)).toBeVisible();
    await start(page);
    await status(page, "completed");
    await page.reload();
    await openDrawer(page);
    await expect(thread(page).getByTestId("long-report")).toBeVisible();
    await expect(group(page, "标已回收")).toBeVisible();
    expect((await viewOf(page, id)).status).toBe("completed");
  });
});

test.describe("长任务：手机宽度", () => {
  test("390 宽：计划卡、提问卡、分组卡片不溢出，按钮和输入框的点按区域不小于 40px", async ({ page }) => {
    test.setTimeout(150_000);
    await page.setViewportSize({ width: 390, height: 1100 });
    await open(page);
    const noOverflow = async (target: Locator, label: string) => {
      const box = await rect(target);
      expect(box.left, `${label} left`).toBeGreaterThanOrEqual(0);
      expect(box.right, `${label} right`).toBeLessThanOrEqual(390);
      expect(await target.evaluate((node) => node.scrollWidth <= node.clientWidth + 1), `${label} scrollWidth`).toBe(true);
    };
    const fingers = async (buttons: Locator) => {
      for (const button of await buttons.all()) {
        const box = await rect(button);
        const name = (await button.getAttribute("aria-label")) ?? (await button.innerText());
        expect(box.height, `${name} height`).toBeGreaterThanOrEqual(40);
        expect(box.width, `${name} width`).toBeGreaterThanOrEqual(40);
      }
    };
    await planned(page, `E2E_LONG_COSTLY E2E_LONG_ABANDON ${ASK}`);
    const plan = planCard(page);
    await noOverflow(plan, "计划卡");
    await fingers(plan.locator(".a-card-foot button, .a-long-est button"));
    await plan.getByRole("button", { name: "改范围", exact: true }).click();
    const form = plan.getByRole("form", { name: "调整计划" });
    await noOverflow(form, "调整表单");
    await fingers(form.locator("button, input"));
    await adjust(page, { cap: 0.5 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await start(page);
    await status(page, "waiting_author");
    await noOverflow(question(page), "提问卡");
    await fingers(question(page).locator("button, select"));
    await photograph(page, "05b-提问卡-手机", [[390, 1500]]);
    await page.setViewportSize({ width: 390, height: 1100 });
    await question(page).getByRole("button", { name: /^提高上限到 / }).click();
    await status(page, "completed");
    await noOverflow(groups(page), "分组卡片");
    for (const card of await groups(page).locator(".a-chg-card").all()) {
      await noOverflow(card, "分组卡片");
      await fingers(card.locator(".a-chg-foot button"));
    }
    await group(page, "标已回收").getByRole("button", { name: /^确认 \d+ 条$/ }).click();
    await fingers(group(page, "标已回收").getByTestId("change-written").locator("button"));
    await noOverflow(thread(page).getByTestId("long-report"), "报告");
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  });
});

test.describe("长任务：做好的图（手造的状态）", () => {
  test("进度和「两个选项」的提问卡：手造的任务视图，按样稿画出来", async ({ page }) => {
    await open(page);
    let view = longView();
    await serveLong(page, () => view);
    await page.reload();
    await openDrawer(page);
    await expect(thread(page).getByTestId("long-progress")).toContainText("第 2/3 步 · 已用 ¥0.31 · 用时 1 分钟");
    await expect(thread(page).getByTestId("long-progress").getByRole("progressbar")).toHaveAttribute("aria-valuenow", "1");
    await photograph(page, "04-进度");

    view = longView({
      status: "waiting_author",
      questions: [{
        id: "alq-mock", kind: "decision", step: 2, text: "两处写法不同，以哪处为准？", choices: ["a", "b", "both", "you_decide"],
        options: [
          { key: "a", label: "第 4 章：钥匙交给了守桥人", chapter: 4, quote: "……把钥匙递给了老守桥人" },
          { key: "b", label: "第 9 章：钥匙一直在苏岑身上", chapter: 9, quote: "……钥匙还在她外套内袋里" },
        ],
        answer: null,
      }],
    });
    await expect(question(page)).toBeVisible({ timeout: 10_000 });
    await expect(question(page)).toHaveAttribute("data-kind", "decision");
    const options = question(page).locator(".a-long-option");
    await expect(options).toHaveCount(4);
    await expect(options.nth(0)).toContainText("第 4 章：钥匙交给了守桥人");
    await expect(options.nth(0)).toContainText("「……把钥匙递给了老守桥人」");
    await expect(options.nth(2)).toHaveText("两处都保留（是有意的）");
    await expect(options.nth(3)).toHaveText("你定（按最新一章）");
    expect(await style(question(page), "box-shadow")).toContain(BLUE);
    const answered = longRequest(page, "/[^/]+/answer");
    await page.route(/\/assistant\/long-tasks\/[^/]+\/answer$/, (route) => route.fulfill({ status: 202, contentType: "application/json", body: JSON.stringify({ data: longView(), request_id: "mock" }) }));
    await options.nth(1).click();
    expect((await answered).postDataJSON()).toEqual({ question_id: "alq-mock", choice: "b" });
    view = longView({ status: "waiting_author", questions: [{ ...(view.questions as object[])[0], answer: null }] });
    await photograph(page, "05c-提问卡-选哪一处");
  });
});
