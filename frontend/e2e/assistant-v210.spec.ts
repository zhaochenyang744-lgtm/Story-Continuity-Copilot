import type { Locator, Page, Route } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { api, createWorkByApi, expect, openTab, sampleWorkId, startVisitor, test } from "./support/app";
import { adoptRequest, askForFix, box, checkedWork, finished, findingsTab, openAssistantTab, proposal, REWRITTEN, send, SENTENCE, tasks, thread } from "./support/assistant";
import { ADD_ASK, changeItem, cardOf, confirmButton, confirmByApi, itemOf, ledgerOf, openLedger, proposeByApi, THREAD_ASK } from "./support/assistant-change";
import { theme } from "./support/pages";
import { beginCheck, draft, finishCheck, saveBody, setup } from "./support/writing";

// v2.1 (02): the change ledger also lists 采用改法 and pages; 看对话 finds a task older than the conversation the drawer holds; a sample work
// takes no characters; a visitor can change the materials of the sample work. Pictures are written only when SHOTS_V210_DIR names a folder.

const usageOf = async (page: Page) => api(page).get("/account/usage");
const adoptionOf = (page: Page) => ledgerOf(page).locator("[data-adoption]");
const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();

function adoption(over: Record<string, unknown> = {}) {
  return {
    entry: "adoption", id: "aprop-mock-1", label: "P1", task_id: "atask-mock-fix", kind: "edit_this", chapter_number: 11,
    before: "苏岑的外套内袋里装着父亲那枚带月牙裂纹的黄铜罗盘，而此刻同一枚罗盘仍握在温岚手中。",
    after: "苏岑的外套内袋里空着，父亲那枚带月牙裂纹的黄铜罗盘此刻仍握在温岚手中。",
    edited_by_author: false, status: "adopted", adopted_at: ago(300), undone_at: null, ...over,
  };
}
const change = (over: Record<string, unknown> = {}) => ({ entry: "change", ...changeItem({ status: "applied", applied_at: ago(900), decided_at: ago(900) }), ...over });

/** Serve the ledger as these pages, one by one: the page asks for the first, then for each `before` it was given. */
async function serveLedger(page: Page, pages: { changes: unknown[]; next: string | null }[], asked: string[] = []) {
  await page.route(/\/api\/projects\/[^/]+\/assistant\/changes(\?.*)?$/, async (route: Route) => {
    if (route.request().method() !== "GET") { await route.fallback(); return; }
    const url = new URL(route.request().url());
    asked.push(url.search);
    const before = url.searchParams.get("before");
    const index = before ? pages.findIndex((item, at) => at > 0 && pages[at - 1].next === before) : 0;
    await route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: pages[index], request_id: "mock" }) });
  });
}

test.describe("改动记录：采用改法", () => {
  test("采用后进改动记录，撤销采用后条目还在、写明已撤销采用，正文不动；再采用一次，条目回到已采用", async ({ page }) => {
    test.setTimeout(150_000);
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    const adopted = adoptRequest(page, "adopt");
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await adopted;
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    // The sample work takes no characters, and the day's count stands.
    expect((await usageOf(page)).check_chars_used).toBe(0);
    const saved = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((item: { kind: string }) => item.kind === "edit_this");

    await openTab(page, id, "memory");
    await openLedger(page);
    const row = adoptionOf(page).first();
    await expect(row).toHaveAttribute("data-status", "adopted");
    await expect(row).toHaveAttribute("data-kind", "edit_this");
    await expect(row).toContainText("采用改法");
    await expect(row).toContainText(`第 ${saved.chapter_number} 章`);
    await expect(row.locator(".chg-before")).toContainText(SENTENCE.slice(0, 10));
    await expect(row.locator(".chg-after")).toContainText(REWRITTEN.slice(0, 12));
    await expect(row.locator(".ledger-state")).toHaveText("已采用");
    await expect(row.getByText("你改过")).toHaveCount(0);
    await expect(row.getByText("只记为撤销，不改你的正文。")).toBeVisible();
    await expect(row.getByRole("button", { name: "看对话", exact: true })).toBeVisible();

    const body = (await draft(page, id)).body;
    await row.getByRole("button", { name: "撤销采用", exact: true }).click();
    await expect(row).toHaveAttribute("data-status", "undone");
    await expect(row.locator(".ledger-state")).toHaveText("已撤销采用");
    await expect(row.getByRole("button", { name: "撤销采用", exact: true })).toHaveCount(0);
    await expect(row.getByRole("button", { name: "看对话", exact: true })).toBeVisible();
    expect((await draft(page, id)).body).toBe(body);  // 撤销采用 never touches the draft
    // Still there after a reload, from the server.
    await page.reload();
    await openLedger(page);
    await expect(adoptionOf(page).first()).toHaveAttribute("data-status", "undone");
    const after = (await api(page).get(`/projects/${id}/assistant/changes`)).changes[0];
    expect(after).toMatchObject({ entry: "adoption", status: "undone", id: saved.id });
    expect(after.undone_at).toBeTruthy();

    // The card in the writing page has gone back to a proposal. The draft still holds the adopted sentence (the undo did not touch it),
    // so the card cannot adopt until the author has put the old sentence back; then adopting empties the mark.
    await openTab(page, id, "workspace");
    await saveBody(page, id, SENTENCE);
    await page.reload();
    await openAssistantTab(page);
    const again = proposal(tasks(page).last(), "edit_this");
    await expect(again.getByRole("button", { name: "采用", exact: true })).toBeEnabled({ timeout: 8_000 });
    await again.getByRole("button", { name: "采用", exact: true }).click();
    await expect(again.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    const last = (await api(page).get(`/projects/${id}/assistant/changes`)).changes;
    expect(last.map((item: { id: string; status: string; undone_at: string | null }) => [item.id, item.status, item.undone_at])).toEqual([[saved.id, "adopted", null]]);
  });

  test("作者改写过的句子：条目写改写后的，标「你改过」，撤销采用后还是这句", async ({ page }) => {
    test.setTimeout(150_000);
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    const edited = `（改了）${SENTENCE.slice(1)}`;
    await edit.getByRole("button", { name: "改一改", exact: true }).click();
    await edit.getByRole("textbox", { name: "改后的句子" }).fill(edited);
    await edit.getByRole("button", { name: "改好了", exact: true }).click();
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    await openTab(page, id, "memory");
    await openLedger(page);
    const row = adoptionOf(page).first();
    await expect(row.locator(".chg-after")).toContainText("（改了）");
    await expect(row.getByText("你改过")).toBeVisible();
    await row.getByRole("button", { name: "撤销采用", exact: true }).click();
    await expect(row).toHaveAttribute("data-status", "undone");
    await expect(row.locator(".chg-after")).toContainText("（改了）");
    await expect(row.getByText("你改过")).toBeVisible();
  });

  test("撤销采用遇到状态已变：写出人话，列表重新读取", async ({ page }) => {
    const id = await setup(page);
    await serveLedger(page, [{ changes: [adoption()], next: null }]);
    await page.route("**/proposals/*/undo", (route) => route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "proposal_state_invalid", message: "x", retryable: false } }) }));
    await openTab(page, id, "memory");
    await openLedger(page);
    const row = adoptionOf(page).first();
    await row.getByRole("button", { name: "撤销采用", exact: true }).click();
    await expect(row.getByRole("alert")).toContainText("这条改法的状态已经变了");
  });
});

test.describe("改动记录：翻页", () => {
  test("有更早的才显示「再看更早的」；点了带着上一页给的位置去取下一页并接在后面，取完按钮消失", async ({ page }) => {
    const id = await setup(page);
    const asked: string[] = [];
    await serveLedger(page, [
      { changes: [adoption({ id: "p-1" }), change({ id: "c-1", label: "C1" }), adoption({ id: "p-2", status: "undone", adopted_at: null, undone_at: ago(100), kind: "add_setup", before: "" })], next: "cursor-one" },
      { changes: [change({ id: "c-2", label: "C2", title: "第二页的伏笔" }), adoption({ id: "p-3", chapter_number: 4 })], next: null },
    ], asked);
    await openTab(page, id, "memory");
    await openLedger(page);
    await expect(ledgerOf(page).locator("ol > li")).toHaveCount(3);
    const more = ledgerOf(page).getByRole("button", { name: "再看更早的", exact: true });
    await expect(more).toBeVisible();
    await more.click();
    await expect(ledgerOf(page).locator("ol > li")).toHaveCount(5);
    await expect(ledgerOf(page).locator("ol > li").nth(3)).toContainText("第二页的伏笔");
    await expect(more).toHaveCount(0);
    expect(asked.map((search) => new URLSearchParams(search).get("before"))).toEqual([null, "cursor-one"]);
  });

  test("没有更早的：不显示按钮", async ({ page }) => {
    const id = await setup(page);
    await serveLedger(page, [{ changes: [adoption()], next: null }]);
    await openTab(page, id, "memory");
    await openLedger(page);
    await expect(adoptionOf(page)).toHaveCount(1);
    await expect(ledgerOf(page).getByRole("button", { name: "再看更早的", exact: true })).toHaveCount(0);
  });

  test("真实服务器：用位置翻页，中间有撤销也不重复", async ({ page }) => {
    const id = await setup(page);
    const first = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, first);
    const page1 = await api(page).get(`/projects/${id}/assistant/changes?limit=1`);
    expect(page1.changes).toHaveLength(1);
    expect(page1.next).toBeNull();
    const again = await proposeByApi(page, id, "E2E_ADD_FACT 苏岑左腕受伤的事记进事实");
    await confirmByApi(page, id, again);
    const one = await api(page).get(`/projects/${id}/assistant/changes?limit=1`);
    expect(one.next).toEqual(expect.any(String));
    const two = await api(page).get(`/projects/${id}/assistant/changes?limit=1&before=${encodeURIComponent(one.next)}`);
    expect(two.next).toBeNull();
    expect(two.changes[0].id).not.toBe(one.changes[0].id);
    expect((await api(page).raw("GET", `/projects/${id}/assistant/changes?before=nonsense`)).status).toBe(400);
  });
});

test.describe("看对话：找到更早的任务", () => {
  /** The conversation the drawer reads is cut to the latest 30; here it leaves out one task, as if it were older than them. */
  async function withoutFromList(page: Page, taskId: string) {
    await page.route(/\/assistant\/tasks\?limit=30$/, async (route: Route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data.tasks = body.data.tasks.filter((item: { id: string }) => item.id !== taskId);
      await route.fulfill({ response, json: body });
    });
  }
  const visibleIn = async (thread: Locator, target: Locator) => {
    const box = await thread.boundingBox();
    const at = await target.boundingBox();
    expect(box && at, "both are on the page").toBeTruthy();
    expect(at!.y).toBeGreaterThanOrEqual(box!.y - 2);
    expect(at!.y).toBeLessThan(box!.y + box!.height);
  };

  test("任务不在已加载的列表里：单独取回、放进对话并滚到那里", async ({ page }) => {
    const id = await setup(page);
    const old = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, old);
    for (const question of [ADD_ASK, THREAD_ASK]) await confirmByApi(page, id, await proposeByApi(page, id, question));
    await withoutFromList(page, old.id);
    const fetched: string[] = [];
    page.on("request", (request) => { if (request.method() === "GET" && /\/assistant\/tasks\//.test(request.url())) fetched.push(request.url()); });
    await openTab(page, id, "memory");
    await openLedger(page);
    const row = ledgerOf(page).locator(`li[data-change]`).filter({ has: page.locator("button", { hasText: "看对话" }) }).last();
    await row.getByRole("button", { name: "看对话", exact: true }).click();
    await expect(thread(page)).toBeVisible();
    const target = thread(page).locator(`[data-task="${old.id}"]`);
    await expect(target).toBeVisible();
    await visibleIn(thread(page), target);
    await expect(thread(page).getByTestId("assistant-cleared")).toHaveCount(0);
    expect(fetched.some((url) => url.includes(`/assistant/tasks/${old.id}?chain=1`))).toBe(true);
    // The list asked for was not made longer to find it.
    expect(fetched.every((url) => !/limit=(?!30\b)\d+/.test(url))).toBe(true);
    // It sits before the tasks of the list, in the order they were asked.
    const order = await thread(page).locator("[data-task]").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-task")));
    expect(order[0]).toBe(old.id);
  });

  test("被清空的对话：写一行「这次对话已经清除」，不报错，改动记录还在", async ({ page }) => {
    const id = await setup(page);
    const task = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, task);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await thread(page).locator(".a-bar details.menu > summary").click();
    await thread(page).getByRole("menuitem", { name: "清空对话", exact: true }).click();
    await thread(page).getByRole("alertdialog").getByRole("button", { name: "清空", exact: true }).click();
    await expect(tasks(page)).toHaveCount(0);
    await openTab(page, id, "memory");
    await openLedger(page);
    await expect(ledgerOf(page).locator("li[data-change]")).toHaveCount(1);
    await ledgerOf(page).getByRole("button", { name: "看对话", exact: true }).click();
    await expect(thread(page).getByTestId("assistant-cleared")).toHaveText("这次对话已经清除。");
    await expect(thread(page).getByRole("alert")).toHaveCount(0);
    await expect(tasks(page)).toHaveCount(0);
    // The ledger still lets the author undo what the cleared conversation did.
    await expect(ledgerOf(page).getByRole("button", { name: "撤销", exact: true })).toBeVisible();
  });
});

test.describe("示例作品不计字数", () => {
  test("额度用完以后，示例作品上助手和检查照样可用，用量不变；自己的作品上被挡住", async ({ page }) => {
    test.setTimeout(150_000);
    const id = await setup(page);
    const session = await api(page).get("/auth/session");
    const usage = await usageOf(page);
    await api(page).post(`/test/v180/users/${session.user.id}/spend-characters/${usage.check_chars_remaining - 300}`);
    const spent = (await usageOf(page)).check_chars_used;
    expect((await usageOf(page)).check_chars_remaining).toBe(300);
    await page.reload();
    await openAssistantTab(page);
    // The box is open, says the work costs nothing, and a question goes through without a character spent.
    await expect(thread(page).locator("form.cx")).not.toHaveClass(/\boff\b/);
    await expect(thread(page)).toContainText("示例作品不计字数");
    await box(page).fill("苏岑知道罗盘被调包了吗？");
    await send(page).click();
    await finished(page);
    const task = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks.at(-1);
    expect(task.usage.chars_charged).toBe(0);
    expect((await usageOf(page)).check_chars_used).toBe(spent);
    // The page's own check is not held back for the allowance either.
    await expect(page.locator(".draft-head-allowance")).toContainText("示例作品不计字数");
    await expect(page.locator(".draft-head-allowance")).not.toHaveClass(/\bover\b/);
    await findingsTab(page).click();
    await finishCheck(page, id, await beginCheck(page, id));
    expect((await usageOf(page)).check_chars_used).toBe(spent);
    // The chapters page.
    await openTab(page, id, "sources");
    await page.getByRole("checkbox", { name: /^选择第 \d+ 章$/ }).first().check();
    await expect(page.getByTestId("chapter-selection")).toContainText("示例作品不计字数");
    await expect(page.getByTestId("chapter-selection")).not.toContainText("额度不够");
    await expect(page.getByRole("button", { name: "检查选中的章节", exact: true })).toBeEnabled();
    // Another work of the same author is held back as before.
    const own = await createWorkByApi(page, { title: "自己的作品" });
    await openTab(page, own, "workspace");
    await openAssistantTab(page);
    await expect(thread(page).locator("form.cx")).toHaveClass(/\boff\b/);
    await expect(thread(page)).toContainText("今天的可检查字数不够这次提问");
  });
});

test.describe("访客改资料", () => {
  test("访客在示例作品上建改资料任务、确认、撤销、恢复，都正常，不扣字数", async ({ page }) => {
    test.setTimeout(150_000);
    await startVisitor(page);
    const id = await sampleWorkId(page);
    const before = await usageOf(page);
    expect(before.account_type).toBe("visitor");
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const sentence = `E2E_ROUTE_CHANGE ${THREAD_ASK}`;
    await box(page).fill(sentence);
    await send(page).click();
    await finished(page);
    await expect(tasks(page).last()).toHaveAttribute("data-kind", "change");
    const task = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks.at(-1);
    expect(task.usage.chars_charged).toBe(0);
    expect(task.changes.length).toBeGreaterThan(0);
    const card = cardOf(page);
    await expect(card).toBeVisible();
    await confirmButton(card).click();
    const item = itemOf(cardOf(page));
    await expect(item).toHaveAttribute("data-status", "applied");
    await item.getByRole("button", { name: "撤销", exact: true }).click();
    await expect(item).toHaveAttribute("data-status", "undone");
    await item.getByRole("button", { name: "恢复", exact: true }).click();
    await expect(item).toHaveAttribute("data-status", "applied");
    // The ledger of the demo work shows it, and the visitor's characters were never touched (a visitor has none; only the task counts).
    await openTab(page, id, "memory");
    await openLedger(page);
    await expect(ledgerOf(page).locator("li[data-change]").first()).toContainText("已执行");
    const after = await usageOf(page);
    expect(after.assistant_tasks_remaining).toBe(before.assistant_tasks_remaining - 1);
    expect(after.checks_remaining).toBe(before.checks_remaining);
  });
});

// ── 图 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
const shots = process.env.SHOTS_V210_DIR;
test.describe("v2.1 截图", () => {
  test.skip(!shots, "SHOTS_V210_DIR is not set");
  const snap = async (target: Page | Locator, name: string, value?: "day" | "night") => {
    await mkdir(shots!, { recursive: true });
    const page = "goto" in target ? (target as Page) : (target as Locator).page();
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.waitForTimeout(500);
    await target.screenshot({ path: path.join(shots!, `${name}${value ? (value === "day" ? "-日间" : "-夜间") : ""}.png`), animations: "disabled" });
  };
  const both = async (page: Page, take: (value: "day" | "night") => Promise<void>) => {
    for (const value of ["day", "night"] as const) { await theme(page, value); await take(value); }
    await theme(page, "day");
  };

  test("改动记录：采用改法（已采用、已撤销采用、你改过），翻页按钮", async ({ page }) => {
    const id = await setup(page);
    await serveLedger(page, [{
      changes: [
        adoption({ id: "p-1" }),
        adoption({ id: "p-2", status: "undone", adopted_at: null, undone_at: ago(120), after: "苏岑摸了摸空着的内袋，罗盘仍在温岚手里。", edited_by_author: true, chapter_number: 11 }),
        change({ id: "c-1", label: "C1" }),
        adoption({ id: "p-3", kind: "add_setup", before: "", after: "老周早就在码头见过那枚罗盘。", chapter_number: 4, adopted_at: ago(2400) }),
      ],
      next: null,
    }]);
    await openTab(page, id, "memory");
    await openLedger(page);
    await both(page, (value) => snap(ledgerOf(page), "01-改动记录-采用改法", value));
  });

  test("翻页：「再看更早的」，点了以后接在后面、按钮消失", async ({ page }) => {
    const id = await setup(page);
    await serveLedger(page, [
      { changes: [adoption({ id: "p-1" }), change({ id: "c-1", label: "C1" })], next: "cursor-one" },
      { changes: [adoption({ id: "p-2", status: "undone", adopted_at: null, undone_at: ago(2000), kind: "add_setup", before: "", after: "老周早就在码头见过那枚罗盘。", chapter_number: 4 }),
        change({ id: "c-2", label: "C2", title: "白色渡船与失去的署名", applied_at: ago(3000) })], next: null },
    ]);
    await openTab(page, id, "memory");
    await openLedger(page);
    await both(page, (value) => snap(ledgerOf(page), "02-翻页-点之前", value));
    await ledgerOf(page).getByRole("button", { name: "再看更早的", exact: true }).click();
    await expect(ledgerOf(page).locator("ol > li")).toHaveCount(4);
    await both(page, (value) => snap(ledgerOf(page), "02-翻页-点之后", value));
  });

  test("看对话：定位到较早的任务", async ({ page }) => {
    const id = await setup(page);
    const old = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, old);
    for (const question of [ADD_ASK, THREAD_ASK]) await confirmByApi(page, id, await proposeByApi(page, id, question));
    await page.route(/\/assistant\/tasks\?limit=30$/, async (route: Route) => {
      const response = await route.fetch();
      const body = await response.json();
      body.data.tasks = body.data.tasks.filter((item: { id: string }) => item.id !== old.id);
      await route.fulfill({ response, json: body });
    });
    await openTab(page, id, "memory");
    await openLedger(page);
    await ledgerOf(page).locator("li[data-change]").last().getByRole("button", { name: "看对话", exact: true }).click();
    await expect(thread(page).locator(`[data-task="${old.id}"]`)).toBeVisible();
    // The drawer covers the theme switch, so the theme is set on the page itself.
    for (const value of ["day", "night"] as const) {
      await page.evaluate((next) => document.documentElement.setAttribute("data-theme", next), value);
      await snap(page, "03-看对话-定位到较早的任务", value);
    }
  });

  test("示例作品额度用完：助手和检查仍可用，自己的作品被挡住", async ({ page }) => {
    const id = await setup(page);
    const session = await api(page).get("/auth/session");
    const usage = await usageOf(page);
    await api(page).post(`/test/v180/users/${session.user.id}/spend-characters/${usage.check_chars_remaining - 300}`);
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page)).toContainText("示例作品不计字数");
    await both(page, (value) => snap(page, "04-示例作品额度用完-写作页", value));
    await openTab(page, id, "sources");
    await page.getByRole("checkbox", { name: /^选择第 \d+ 章$/ }).first().check();
    await expect(page.getByTestId("chapter-selection")).toContainText("示例作品不计字数");
    await both(page, (value) => snap(page.getByTestId("chapter-selection"), "04-示例作品额度用完-章节页", value));
    const own = await createWorkByApi(page, { title: "自己的作品" });
    await openTab(page, own, "workspace");
    await openAssistantTab(page);
    await expect(thread(page).locator("form.cx")).toHaveClass(/\boff\b/);
    await both(page, (value) => snap(thread(page), "04-对照-自己的作品额度不够", value));
  });
});
