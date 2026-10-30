import type { Locator, Page, Route } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { api, createWorkByApi, expect, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { openAssistantTab, thread } from "./support/assistant";
import { serveTasks, askView } from "./support/assistant-mock";
import {
  cardOf, changeItem, confirmButton, confirmByApi, itemOf, ledgerButton, ledgerOf, openCard, openLedger, proposeByApi, THREAD_ASK, undoOf,
} from "./support/assistant-change";
import { theme } from "./support/pages";
import { button, finding, findings, run, selectIssue, setup } from "./support/writing";

// v2.2: 记住作者的决定 (front end). The 决定 tab of the materials page (read, reword, change what it covers, "still holds", delete), the
// add_decision item on the assistant's card (an ask can carry a card too), the sentence of why beside 是有意的 / 不是问题, the question
// after an undo ("要记下来吗"), and the two small words in the answer's sources and in a check's result. The records themselves are made on
// the cards, so what a test needs from the server it makes through the real undo -> remember -> confirm path; states a run cannot hold still
// (a decision that may be out of date, a decision that covers a finding, a note that comes back with a card) are served by hand.
// Pictures are written only when SHOTS_V220_DIR names a folder.

const envelope = (data: unknown, status = 200) => ({ status, contentType: "application/json", body: JSON.stringify({ data, request_id: "mock" }) });
const decisionsUrl = /\/api\/projects\/[^/]+\/decisions$/;
const decisionUrl = /\/api\/projects\/[^/]+\/decisions\/[^/]+$/;
type Decision = { id: string; kind: string; kind_label: string; statement: string; subjects: string[]; chapters: [number, number] | null; status: string; scope: string; quote: string; source: string; source_label: string; revision: number; basis_chapter: number | null };
const decisionsOf = async (page: Page, id: string) => (await api(page).get(`/projects/${id}/decisions`)).decisions as Decision[];
const rows = (page: Page) => page.getByRole("list", { name: "决定列表" }).locator("li");
const rowOf = (page: Page, text: string) => rows(page).filter({ hasText: text });
/** A row by its kind: stable while the row is being edited (its words then sit in fields, not in text). */
const kindRow = (page: Page, kind: string) => page.locator(`.decision-list li[data-kind="${kind}"]`);
const goDecisions = async (page: Page, id: string, query = "view=decisions") => {
  await page.goto(`/projects/${id}/memory?${query}`);
  await expect(page.getByTestId("decision-count")).toBeVisible();
};
const tabOf = (page: Page, name: string | RegExp) => page.getByRole("navigation", { name: "资料分类" }).getByRole("button", { name });
async function sampleWork(page: Page, prefix = "v220") {
  await registerAccount(page, prefix);
  return sampleWorkId(page);
}

/** The sample work with the tour finished, so no finding is decided yet and the tour does not hide the sentence of why. */
async function plainSample(page: Page) {
  const id = await sampleWork(page, "v220note");
  await api(page).post("/onboarding/complete", { confirm: true });
  await openTab(page, id, "workspace");
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
  return id;
}

/** An add_decision item of a card, as the server shows it. */
const decisionItem = (over: Record<string, unknown> = {}) => changeItem({
  id: "achange-mock-d1", label: "C1", task_id: "atask-mock-ask", kind: "add_decision", target: { kind: "decision", id: "decision-mock" }, title: "记下决定·有意为之",
  before: "资料里没有", after: "她第 7 章的年龄和第 3 章不同是有意的（管：苏岑；第 3–7 章）", editable: true, value: "她第 7 章的年龄和第 3 章不同是有意的",
  evidence: [], evidence_required: false, request_words: null, quote: "她年龄不统一是故意的", replaces: null, rememberable: false, ...over,
});
const askWithCard = (items: unknown[], over: Record<string, unknown> = {}) => askView({
  id: "atask-mock-ask", kind: "ask", question: "她年龄不统一是故意的，你看看第 9 章还有哪里提到", context: { page: "writing", chapter_number: 11 }, changes: items, ...over,
});

// ── 资料页「决定」一栏 ─────────────────────────────────────────────────────────────────────────────────────────────────────
test.describe("资料页：决定", () => {
  test("标签带条数，示例作品预置两条；每条有种类、内容、管哪些；从哪来展开看到原话；旧地址 ?tab= 也能打开", async ({ page }) => {
    const id = await sampleWork(page);
    const served = await decisionsOf(page, id);
    expect(served).toHaveLength(2);
    await openTab(page, id, "memory");
    await expect(tabOf(page, /^决定/)).toContainText("2");
    await tabOf(page, /^决定/).click();
    await expect(page).toHaveURL(/view=decisions/);
    await expect(page.getByTestId("decision-count")).toHaveText("已记 2 / 200 条");
    await expect(rows(page)).toHaveCount(2);
    const open = rowOf(page, "廊桥钥匙的指向");
    await expect(open).toContainText("先别收");
    await expect(open.locator(".decision-scope")).toContainText("管：廊桥钥匙的指向");
    await expect(open.getByText("廊桥钥匙那条先别收，后面还要写")).toHaveCount(0);
    await open.getByRole("button", { name: "从哪来", exact: true }).click();
    await expect(open.locator(".decision-source")).toContainText("你说的：「廊桥钥匙那条先别收，后面还要写」");
    await expect(open.locator(".decision-source")).toContainText("助手输入框");
    await expect(rowOf(page, "旧潮位牌")).toContainText("不用提醒");
    await page.reload();
    await expect(rows(page)).toHaveCount(2);
    await goDecisions(page, id, "tab=decisions");
    await expect(tabOf(page, /^决定/)).toHaveAttribute("aria-current", "page");
    await expect(rows(page)).toHaveCount(2);
  });

  test("没有决定的作品：说明这一栏是什么，已记 0 / 200 条", async ({ page }) => {
    await registerAccount(page, "v220empty");
    const id = await createWorkByApi(page, { title: "空决定" });
    await goDecisions(page, id);
    await expect(page.getByTestId("decision-count")).toHaveText("已记 0 / 200 条");
    await expect(page.locator(".empty")).toContainText("你在助手里说过的、以后也要照办的决定会记在这里");
    await expect(page.locator(".empty")).toContainText("每一条都要你确认才会记下");
    await expect(rows(page)).toHaveCount(0);
  });

  test("改：内容、管哪些、章节范围，保存后刷新还在；改回全书；填错的章节不能保存", async ({ page }) => {
    const id = await sampleWork(page);
    await goDecisions(page, id);
    const row = kindRow(page, "no_reminder");
    await row.getByRole("button", { name: "编辑", exact: true }).click();
    const form = row.getByRole("form", { name: "改这条决定" });
    await form.getByLabel("决定内容").fill("旧潮位牌的几种叫法一律不用提醒");
    await form.getByLabel("管哪些人或物").fill("旧潮位牌、潮位牌");
    await form.getByRole("radio", { name: "指定章节" }).check();
    await form.getByLabel("起始章").fill("7");
    await form.getByLabel("结束章").fill("3");
    await expect(form.getByRole("alert")).toContainText("起始章要在结束章之前");
    await expect(form.getByRole("button", { name: "保存", exact: true })).toBeDisabled();
    await form.getByLabel("起始章").fill("3");
    await form.getByLabel("结束章").fill("7");
    const patched = page.waitForRequest((request) => request.method() === "PATCH" && decisionUrl.test(request.url()));
    await form.getByRole("button", { name: "保存", exact: true }).click();
    expect((await patched).postDataJSON()).toEqual({ base_revision: 1, statement: "旧潮位牌的几种叫法一律不用提醒", subjects: ["旧潮位牌", "潮位牌"], chapters: [3, 7] });
    await expect(page.getByRole("status").filter({ hasText: "这条决定改好了。" })).toBeVisible();
    const changed = (await decisionsOf(page, id)).find((item) => item.kind === "no_reminder")!;
    expect(changed).toMatchObject({ statement: "旧潮位牌的几种叫法一律不用提醒", subjects: ["旧潮位牌", "潮位牌"], chapters: [3, 7], revision: 2 });
    await page.reload();
    await expect(rowOf(page, "一律不用提醒").locator(".decision-scope")).toHaveText("管：旧潮位牌、潮位牌；第 3–7 章");
    await rowOf(page, "一律不用提醒").getByRole("button", { name: "编辑", exact: true }).click();
    await expect(page.getByLabel("起始章")).toHaveValue("3");
    await page.getByRole("radio", { name: "全书" }).check();
    const again = page.waitForRequest((request) => request.method() === "PATCH" && decisionUrl.test(request.url()));
    await page.getByRole("button", { name: "保存", exact: true }).click();
    expect((await again).postDataJSON()).toMatchObject({ base_revision: 2, whole_work: true });
    await expect(rowOf(page, "一律不用提醒").locator(".decision-scope")).toHaveText("管：旧潮位牌、潮位牌；全书");
    expect((await decisionsOf(page, id)).find((item) => item.kind === "no_reminder")!.chapters).toBeNull();
  });

  test("取消编辑不改任何东西；在别处改过以后保存：提示载入最新版本，输入的内容还在", async ({ page }) => {
    const id = await sampleWork(page);
    await goDecisions(page, id);
    const row = kindRow(page, "no_reminder");
    await row.getByRole("button", { name: "编辑", exact: true }).click();
    await row.getByLabel("决定内容").fill("改了一半");
    await row.getByRole("button", { name: "取消", exact: true }).click();
    await expect(row.locator(".decision-statement")).toContainText("旧潮位牌前后几种叫法");
    await row.getByRole("button", { name: "编辑", exact: true }).click();
    await expect(row.getByLabel("决定内容")).toHaveValue(/旧潮位牌前后几种叫法/);
    await row.getByLabel("决定内容").fill("我在这个窗口里改的");
    // Another window changes it first.
    const other = (await decisionsOf(page, id)).find((item) => item.kind === "no_reminder")!;
    await api(page).patch(`/projects/${id}/decisions/${other.id}`, { base_revision: other.revision, statement: "另一个窗口改的" });
    await row.getByRole("button", { name: "保存", exact: true }).click();
    const warn = row.getByRole("alert").filter({ hasText: "这条决定在别处改过" });
    await expect(warn).toBeVisible();
    await expect(row.getByLabel("决定内容")).toHaveValue("我在这个窗口里改的");
    await warn.getByRole("button", { name: "载入最新版本", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "载入了最新版本" })).toBeVisible();
    await expect(row.getByLabel("决定内容")).toHaveValue("我在这个窗口里改的");
    await row.getByRole("button", { name: "保存", exact: true }).click();
    await expect(page.getByRole("status").filter({ hasText: "这条决定改好了。" })).toBeVisible();
    expect((await decisionsOf(page, id)).find((item) => item.kind === "no_reminder")).toMatchObject({ statement: "我在这个窗口里改的", revision: 3 });
  });

  test("删：先问一次；取消不删；确认后消失，条数减一，服务器上也没了", async ({ page }) => {
    const id = await sampleWork(page);
    await goDecisions(page, id);
    const row = rowOf(page, "旧潮位牌");
    await row.getByRole("button", { name: "删除", exact: true }).click();
    await expect(row.getByRole("alert")).toContainText("删除后助手不再照这条办。确定删除？");
    await row.getByRole("button", { name: "取消", exact: true }).click();
    await expect(rows(page)).toHaveCount(2);
    expect(await decisionsOf(page, id)).toHaveLength(2);
    await row.getByRole("button", { name: "删除", exact: true }).click();
    const posted = page.waitForRequest((request) => request.method() === "POST" && /\/decisions\/[^/]+\/delete$/.test(request.url()));
    await row.getByRole("button", { name: "确认删除", exact: true }).click();
    expect((await posted).postDataJSON()).toEqual({ base_revision: 1 });
    await expect(rows(page)).toHaveCount(1);
    await expect(page.getByTestId("decision-count")).toHaveText("已记 1 / 200 条");
    await expect(tabOf(page, /^决定/)).toContainText("1");
    expect((await decisionsOf(page, id)).map((item) => item.kind)).toEqual(["keep_open"]);
  });

  test("可能过时：排在前面带标记，「仍然有效」只发 still_holds；已取代：有标记、不能编辑", async ({ page }) => {
    const id = await sampleWork(page);
    const real = await decisionsOf(page, id);
    const state: Decision[] = [
      { ...real[0], status: "stale", basis_chapter: 7, revision: 4 },
      { ...real[1], status: "active" },
      { ...real[1], id: "decision-old", statement: "旧潮位牌以前的叫法随意", status: "superseded", kind: "prefer", kind_label: "以哪处为准", scope: "管：旧潮位牌；全书" },
    ];
    await page.route(decisionsUrl, (route) => (route.request().method() === "GET" ? route.fulfill(envelope({ decisions: state, limit: 200, kinds: {} })) : route.fallback()));
    let held: unknown = null;
    await page.route(decisionUrl, async (route: Route) => {
      if (route.request().method() !== "PATCH") { await route.fallback(); return; }
      held = route.request().postDataJSON();
      state[0] = { ...state[0], status: "active", revision: 5 };
      await route.fulfill(envelope({ decision: state[0] }));
    });
    await goDecisions(page, id);
    await expect(rows(page).first()).toHaveAttribute("data-status", "stale");
    const stale = rows(page).first();
    await expect(stale.getByTestId("decision-stale")).toContainText("可能过时");
    await expect(stale.getByTestId("decision-stale")).toContainText("第 7 章后来改过");
    const gone = rowOf(page, "旧潮位牌以前的叫法随意");
    await expect(gone.getByTestId("decision-superseded")).toContainText("已取代");
    await expect(gone.getByRole("button", { name: "编辑", exact: true })).toHaveCount(0);
    await expect(gone.getByRole("button", { name: "删除", exact: true })).toBeVisible();
    await expect(page.getByTestId("decision-count")).toHaveText("已记 3 / 200 条");
    await shot(page, "02-可能过时和已取代", "stale");
    await stale.getByRole("button", { name: "仍然有效", exact: true }).click();
    await expect.poll(() => held).toEqual({ base_revision: 4, still_holds: true });
    await expect(rows(page).first().getByTestId("decision-stale")).toHaveCount(0);
    await expect(page.getByRole("status").filter({ hasText: "这条决定仍然有效" })).toBeVisible();
  });
});

// ── 卡片 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
test.describe("卡片：记下决定", () => {
  test("问作品的回答下面也有卡片：种类、原话、取代、改字限 80 字；确认和不要用同一套接口", async ({ page }) => {
    const id = await sampleWork(page, "v220card");
    let view = askWithCard([decisionItem({ id: "d-1", label: "C1", replaces: "她的年龄以第三章为准" })]);
    await serveTasks(page, () => [view]);
    const confirms: unknown[] = [];
    await page.route(/\/assistant\/tasks\/atask-mock-ask\/changes\/(confirm|reject)$/, async (route) => {
      confirms.push({ path: new URL(route.request().url()).pathname.split("/").at(-1), body: route.request().postDataJSON() });
      const now = new Date().toISOString();
      view = askWithCard([decisionItem({ id: "d-1", status: route.request().url().endsWith("confirm") ? "applied" : "rejected", applied_at: now, decided_at: now, edited_by_author: true })]);
      await route.fulfill(envelope(view));
    });
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const card = cardOf(page);
    await expect(card).toBeVisible();
    await expect(thread(page).locator('[data-task]').last()).toContainText("等你确认");
    const item = itemOf(card, "C1");
    await expect(item).toHaveAttribute("data-kind", "add_decision");
    await expect(item.locator(".a-chg-kind")).toHaveText("记下决定");
    await expect(item.locator(".a-chg-line strong")).toHaveText("有意为之");
    await expect(item.locator(".chg-before")).toContainText("资料里没有");
    await expect(item.locator(".chg-after")).toContainText("她第 7 章的年龄和第 3 章不同是有意的（管：苏岑；第 3–7 章）");
    await expect(item.getByTestId("decision-quote")).toHaveText("依据你说的：「她年龄不统一是故意的」");
    await expect(item.getByTestId("decision-replaces")).toHaveText("取代：她的年龄以第三章为准");
    await expect(item.getByTestId("change-basis")).toHaveCount(0);
    await shot(card, "03-记下决定的卡片", "card");
    await item.getByRole("button", { name: "改内容", exact: true }).click();
    const box = item.getByRole("textbox", { name: /^改后的内容/ });
    await expect(box).toHaveAttribute("maxlength", "80");
    await box.fill("她的年龄前后不同是有意的");
    await expect(item.locator(".chg-after")).toContainText("她的年龄前后不同是有意的（管：苏岑；第 3–7 章）");
    await confirmButton(card).click();
    await expect.poll(() => confirms.length).toBe(1);
    expect(confirms[0]).toEqual({ path: "confirm", body: { accepted: ["d-1"], edits: { "d-1": "她的年龄前后不同是有意的" } } });
    await expect(card.getByTestId("change-written")).toBeVisible();
    await expect(undoOf(card)).toBeVisible();
  });

  test("不要：整张卡片没要，不写任何东西", async ({ page }) => {
    const id = await sampleWork(page, "v220no");
    let view = askWithCard([decisionItem({ id: "d-1" })]);
    await serveTasks(page, () => [view]);
    await page.route(/\/changes\/reject$/, async (route) => {
      view = askWithCard([decisionItem({ id: "d-1", status: "rejected", decided_at: new Date().toISOString() })]);
      await route.fulfill(envelope(view));
    });
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await cardOf(page).getByRole("button", { name: "不要", exact: true }).click();
    await expect(itemOf(cardOf(page), "C1").locator(".a-chg-state")).toHaveText("没要");
    expect(await decisionsOf(page, id)).toHaveLength(2);
  });

  test("真实流程：确认标已回收 → 撤销 → 问「要记下来吗」→ 记下来 → 同一张卡片多一条「先别收」→ 确认 → 资料页「决定」里有它", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, THREAD_ASK);
    await confirmButton(card).click();
    await expect(card.getByTestId("change-written")).toBeVisible();
    await expect(card.getByTestId("remember-ask")).toHaveCount(0);
    await undoOf(card).click();
    const first = itemOf(card, "C1");
    await expect(first).toHaveAttribute("data-status", "undone");
    const ask = card.getByTestId("remember-ask");
    await expect(ask).toContainText("要记下来，以后别再提出这一条吗？");
    await expect(ask.getByRole("button", { name: "记下来", exact: true })).toBeVisible();
    await expect(ask.getByRole("button", { name: "不用", exact: true })).toBeVisible();
    await shot(card, "04-撤销后问要不要记下来", "remember");
    const remembered = page.waitForRequest((request) => request.method() === "POST" && /\/assistant\/changes\/[^/]+\/remember$/.test(request.url()));
    await ask.getByRole("button", { name: "记下来", exact: true }).click();
    expect((await remembered).postDataJSON()).toEqual({});
    await expect(card.getByTestId("remember-made")).toContainText("已生成一张记录卡片");
    const second = itemOf(card, "C2");
    await expect(second).toHaveAttribute("data-kind", "add_decision");
    await expect(second).toHaveAttribute("data-status", "proposed");
    await expect(second.locator(".a-chg-line strong")).toHaveText("先别收");
    await expect(second.getByTestId("decision-quote")).toContainText("撤销了标成已回收");
    await shot(card, "05-记下来之后同一张卡片多一条", "remember");
    await confirmButton(card).click();
    await expect(second).toHaveAttribute("data-status", "applied");
    // Only asked once: after a reload the question is not asked again.
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).getByTestId("remember-ask")).toHaveCount(0);
    const made = (await decisionsOf(page, id)).filter((item) => item.source === "undo");
    expect(made).toHaveLength(1);
    expect(made[0]).toMatchObject({ kind: "keep_open", source_label: "撤销时记下" });
    await goDecisions(page, id);
    await expect(tabOf(page, /^决定/)).toContainText("2");
    const row = rowOf(page, made[0].statement);
    await row.getByRole("button", { name: "从哪来", exact: true }).click();
    await expect(row.locator(".decision-source")).toContainText("撤销时记下");
  });

  test("不用：问题消失，刷新后也不再问；没有记下任何决定", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, THREAD_ASK);
    await confirmButton(card).click();
    await undoOf(card).click();
    await card.getByTestId("remember-ask").getByRole("button", { name: "不用", exact: true }).click();
    await expect(card.getByTestId("remember-ask")).toHaveCount(0);
    await expect(card.getByTestId("remember-made")).toHaveCount(0);
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).getByTestId("remember-ask")).toHaveCount(0);
    // The sample's own 先别收 was let go for the proposal (see releaseKeptOpen); nothing was added.
    expect(await decisionsOf(page, id)).toHaveLength(1);
  });

  test("改动记录里也问一次：记下来 → 打开那个任务；之后不再问", async ({ page }) => {
    const id = await sampleWork(page, "v220led");
    const task = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, task);
    await api(page).post(`/projects/${id}/assistant/changes/${task.changes[0].id}/undo`, { confirm: false });
    await openTab(page, id, "memory");
    const ledger = await openLedger(page);
    const ask = ledger.getByTestId("remember-ask");
    await expect(ask).toContainText("要记下来，以后别再提出这一条吗？");
    await shot(ledger, "06-改动记录里问要不要记下来", "ledger");
    await ask.getByRole("button", { name: "记下来", exact: true }).click();
    await expect(ledger.getByTestId("remember-made")).toBeVisible();
    await expect(thread(page)).toBeVisible();
    await expect(cardOf(page).locator('[data-kind="add_decision"]')).toHaveCount(1);
    await page.reload();
    await openLedger(page);
    await expect(ledgerOf(page).getByTestId("remember-ask")).toHaveCount(0);
    await expect(ledgerButton(page)).toBeVisible();
  });

  test("资料页「决定」里的「看对话」打开它出自的那个任务", async ({ page }) => {
    const id = await sampleWork(page, "v220talk");
    const real = await decisionsOf(page, id);
    const state = [{ ...real[0], source: "box", source_label: "助手输入框", source_ref: "atask-mock-ask" }];
    await page.route(decisionsUrl, (route) => (route.request().method() === "GET" ? route.fulfill(envelope({ decisions: state, limit: 200, kinds: {} })) : route.fallback()));
    await serveTasks(page, () => [askWithCard([decisionItem({ status: "applied", applied_at: new Date().toISOString() })])]);
    await goDecisions(page, id);
    const row = rows(page).first();
    await row.getByRole("button", { name: "从哪来", exact: true }).click();
    await row.getByRole("button", { name: "看对话", exact: true }).click();
    await expect(thread(page)).toBeVisible();
    await expect(thread(page).locator('[data-task="atask-mock-ask"]')).toBeVisible();
  });
});

// ── 检查结果：说一句为什么 ─────────────────────────────────────────────────────────────────────────────────────────────
test.describe("检查结果：说一句为什么", () => {
  const noteBox = (page: Page) => findings(page).getByPlaceholder("说一句为什么（可选，写了以后可以记成一条决定）");
  const decisionPost = (page: Page) => page.waitForRequest((request) => request.method() === "POST" && /\/issues\/[^/]+\/decision$/.test(request.url()));

  test("不写：请求里没有 note，行为和以前一样；写了：note 跟着提交，输入框只在没处理时出现", async ({ page }) => {
    const id = await plainSample(page);
    const result = await run(page, id);
    const [plain, noted] = [result.issues.find((issue: any) => issue.nature === "possible_conflict"), result.issues.find((issue: any) => issue.nature === "confirmed_conflict")];
    await selectIssue(page, plain);
    await expect(noteBox(page)).toBeVisible();
    const first = decisionPost(page);
    await button(page, "是有意的").click();
    const body = (await first).postDataJSON();
    expect(body).not.toHaveProperty("note");
    expect(body).toMatchObject({ decision: "keep_intentional" });
    await expect(finding(page, plain.id)).toContainText("已处理");
    await expect(noteBox(page)).toHaveCount(0);
    await selectIssue(page, noted);
    await noteBox(page).fill("  这个人物就是这样说话的  ");
    await shot(findings(page), "07-说一句为什么", "note");
    const second = decisionPost(page);
    await button(page, "不是问题").click();
    expect((await second).postDataJSON()).toMatchObject({ decision: "false_positive", note: "这个人物就是这样说话的" });
    await expect(finding(page, noted.id)).toContainText("已处理");
    await expect(page.getByTestId("memory-card-made")).toHaveCount(0);
  });

  test("返回里带 memory_card：提示已生成一张记录卡片，一点打开助手里的那个任务", async ({ page }) => {
    const id = await plainSample(page);
    const issue = (await run(page, id)).issues.find((item: any) => item.nature === "possible_conflict");
    await serveTasks(page, () => [askWithCard([decisionItem({ quote: "这是故意写的" })])]);
    await page.route(/\/issues\/[^/]+\/decision$/, async (route) => {
      const real = await route.fetch();
      const payload = await real.json();
      await route.fulfill({ status: real.status(), contentType: "application/json", body: JSON.stringify({ ...payload, data: { ...payload.data, memory_card: { task_id: "atask-mock-ask" } } }) });
    });
    await page.reload();
    await selectIssue(page, issue);
    await noteBox(page).fill("这是故意写的");
    const posted = decisionPost(page);
    await button(page, "是有意的").click();
    expect((await posted).postDataJSON()).toMatchObject({ note: "这是故意写的" });
    const made = page.getByTestId("memory-card-made");
    await expect(made).toContainText("已生成一张记录卡片");
    await shot(findings(page), "08-已生成一张记录卡片", "note");
    await made.getByRole("button", { name: "打开卡片", exact: true }).click();
    await expect(thread(page)).toBeVisible();
    await expect(thread(page).locator('[data-task="atask-mock-ask"]')).toBeVisible();
    await expect(cardOf(page).locator('[data-kind="add_decision"]')).toBeVisible();
  });

  test("被作者记下的决定盖住的结果：「按你记下的决定略过」，链接去决定一栏，不说沿用之前的判断", async ({ page }) => {
    const id = await plainSample(page);
    const covered = (await run(page, id)).issues.find((item: any) => item.nature === "possible_conflict");
    const real = await decisionsOf(page, id);
    await page.route(/\/api\/projects\/[^/]+\/checks\/[^/?]+\?/, async (route) => {
      const response = await route.fetch();
      const payload = await response.json();
      const issues = (payload.data.issues ?? []).map((issue: any) => (issue.id === covered.id
        ? { ...issue, decision: null, reused_decision: { decision: "author_decision", status: "author_decision", decision_id: real[0].id, statement: real[0].statement, source_issue_id: null, review_path: `/projects/${id}/materials?tab=decisions`, requires_new_decision: false } }
        : issue));
      await route.fulfill({ status: response.status(), contentType: "application/json", body: JSON.stringify({ ...payload, data: { ...payload.data, issues } }) });
    });
    await page.reload();
    const row = finding(page, covered.id);
    await expect(row).toContainText("按你记下的决定略过");
    await expect(row).not.toContainText("沿用之前的判断");
    await selectIssue(page, covered);
    const line = findings(page).getByTestId("author-decision-cover");
    await expect(line).toContainText(`按你记下的决定略过：「${real[0].statement}」`);
    await expect(line).not.toContainText("沿用你之前对同一句的判断");
    await shot(findings(page), "09-按决定略过", "cover");
    await line.getByRole("link", { name: "查看这条决定", exact: true }).click();
    await expect(page).toHaveURL(/\/memory\?view=decisions/);
    await expect(rows(page)).toHaveCount(2);
  });
});

// ── 出处 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
test("回答的出处里有「作者的决定」：标签是作者的决定，点开是决定内容，没有「去原文」", async ({ page }) => {
  const id = await sampleWork(page, "v220src");
  const view = askView({
    id: "atask-mock-ask", question: "苏岑的年龄要不要统一？",
    answer: { status: "answered", sentences: [{ text: "作者定过她前后的年龄不同是有意的，不用统一。", refs: ["R9"] }], note: null },
    sources: { R9: { kind: "decision", chapter_number: null, chapter_title: null, start: null, end: null, text: "她第 7 章的年龄和第 3 章不同是有意的（管：苏岑；第 3–7 章）", cited: true } },
  });
  await serveTasks(page, () => [view]);
  await openTab(page, id, "workspace");
  await openAssistantTab(page);
  await thread(page).getByRole("button", { name: /^出处 1 处/ }).click();
  const source = thread(page).getByRole("list", { name: "出处" }).locator("li").first();
  await expect(source).toContainText("作者的决定");
  await source.getByRole("button", { name: /作者的决定/ }).click();
  await expect(source).toContainText("她第 7 章的年龄和第 3 章不同是有意的");
  await expect(source.getByRole("button", { name: /去原文/ })).toHaveCount(0);
  await shot(thread(page), "10-出处：作者的决定", "source");
  // The citation card above the sentence names it the same way.
  await thread(page).getByRole("button", { name: /^出处 1：/ }).hover();
  await expect(page.getByRole("group", { name: "出处 1" })).toContainText("作者的决定");
  await expect(page.getByRole("group", { name: "出处 1" }).getByRole("button", { name: /去原文/ })).toHaveCount(0);
});

test("隐私说明里写了记下的决定随作品保存、导出、删除", async ({ page }) => {
  await page.goto("/privacy");
  await expect(page.getByText("你确认记下的决定随作品保存，导出作品时一起导出，删除作品时一起删除。")).toBeVisible();
});

// ── 图 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
const shots = process.env.SHOTS_V220_DIR;
async function shot(target: Page | Locator, name: string, _group: string) {
  if (!shots) return;
  await mkdir(shots, { recursive: true });
  const page = "goto" in target ? (target as Page) : (target as Locator).page();
  await page.evaluate(async () => { await document.fonts.ready; });
  await target.screenshot({ path: path.join(shots, `${name}.png`), animations: "disabled" });
}

test.describe("决定 截图", () => {
  test.skip(!shots, "SHOTS_V220_DIR is not set");
  test("资料页：列表、编辑、删除确认；日间和夜间；375 宽", async ({ page, browser }) => {
    const id = await sampleWork(page, "v220shot");
    await goDecisions(page, id);
    for (const value of ["day", "night"] as const) { await theme(page, value); await shot(page, `01-决定列表-${value === "day" ? "日间" : "夜间"}`, "list"); }
    await theme(page, "day");
    const row = kindRow(page, "no_reminder");
    await row.getByRole("button", { name: "从哪来", exact: true }).click();
    await shot(page, "01b-从哪来展开", "list");
    await row.getByRole("button", { name: "编辑", exact: true }).click();
    await row.getByRole("radio", { name: "指定章节" }).check();
    await shot(page, "11-编辑", "edit");
    await row.getByRole("button", { name: "取消", exact: true }).click();
    await row.getByRole("button", { name: "删除", exact: true }).click();
    await shot(page, "12-删除确认", "delete");
    const phone = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const small = await phone.newPage();
    await small.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(small, "v220phone");
    const smallId = await sampleWorkId(small);
    await goDecisions(small, smallId);
    await shot(small, "13-375宽-决定列表", "phone");
    await phone.close();
  });
});
