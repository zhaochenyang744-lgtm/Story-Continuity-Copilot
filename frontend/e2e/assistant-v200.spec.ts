import type { Locator, Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { api, expect, expectNoHorizontalOverflow, newPage, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { box, chooseMode, finished, menuNames, openAssistantTab, send, taskPost, tasks, thread, topbarAssistant } from "./support/assistant";
import { serveTasks } from "./support/assistant-mock";
import {
  ADD_ASK, ADDED_VALUE, afterOf, basisOf, cardOf, changeItem, changeView, closeDrawer, confirmButton, confirmByApi, confirmPost, editThread, factRecords, factRow, FACT_ASK, itemOf,
  lastChange, LAST_CHAPTER, ledgerButton, ledgerOf, MODEL_VALUE, openBasis, openCard, openDrawer, openLedger, proposeByApi, rejectByApi, THREAD_ASK, threadRow, threadsView,
  threadStatus, undoOf,
} from "./support/assistant-change";
import { theme } from "./support/pages";
import { setup } from "./support/writing";

// v2.0 (07): 改资料 in the assistant. The assistant proposes changes to the materials as a card (mark a thread resolved, change a fact,
// add a fact); the author confirms; the program writes; every item can be undone and applied again. The test model proposes by a marker in
// the sentence (see support/assistant-change.ts). Pictures are written only when SHOTS_V200_DIR names a folder (the runner passes the
// variable through); an ordinary run skips the last group.

const modeButton = (page: Page, label: string) => thread(page).getByRole("button", { name: `这次做什么：${label}` });
const routeUrl = /\/assistant\/route$/;
const routePost = (page: Page) => page.waitForRequest((request) => request.method() === "POST" && routeUrl.test(request.url()));
const stateOf = (item: Locator) => item.locator(".a-chg-state");

/** The card of the latest change task and its first item, with what a pending card shows. */
async function expectPending(card: Locator, title: string, kind: string) {
  await expect(card.locator(".a-chg-head")).toContainText("确认后才会执行，可以撤销");
  const item = itemOf(card);
  await expect(item).toHaveAttribute("data-status", "proposed");
  await expect(item).toHaveAttribute("data-kind", kind);
  await expect(item.locator(".a-chg-line strong")).toContainText(title);
  await expect(item.getByRole("checkbox")).toBeChecked();
  return item;
}

test.describe("改资料：用法和菜单", () => {
  test("模式菜单：写作页五项（自动、问作品、写前回顾、查前文矛盾、改资料），其他页三项，访客也有；自动模式下带 E2E_ROUTE_CHANGE 的句子建的是改资料任务", async ({ page, browser }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await modeButton(page, "自动").click();
    expect(await menuNames(thread(page))).toEqual(["自动", "问作品", "写前回顾", "查前文矛盾", "改资料", "长任务"]);
    await page.keyboard.press("Escape");
    await openTab(page, id, "sources");
    await topbarAssistant(page).click();
    await modeButton(page, "自动").click();
    expect(await menuNames(thread(page))).toEqual(["自动", "问作品", "改资料", "长任务"]);
    await page.keyboard.press("Escape");
    const visitor = await newPage(browser);
    await startVisitor(visitor);
    await openTab(visitor, await sampleWorkId(visitor), "workspace");
    await openAssistantTab(visitor);
    await modeButton(visitor, "自动").click();
    expect(await menuNames(thread(visitor))).toEqual(["自动", "问作品", "写前回顾", "改资料", "长任务"]);
    await visitor.close();

    // 自动: the sentence is judged, and what the judgement names is what is started.
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const sentence = `E2E_ROUTE_CHANGE ${THREAD_ASK}`;
    await box(page).fill(sentence);
    const asked = routePost(page);
    const created = taskPost(page);
    await send(page).click();
    expect((await asked).postDataJSON()).toMatchObject({ input: sentence });
    expect((await created).postDataJSON()).toEqual({ kind: "change", question: sentence, context: { page: "writing", chapter_number: expect.any(Number) },
      routed: true, route_source: "model", routed_input: sentence });
    await finished(page);
    await expect(modeButton(page, "自动")).toBeVisible();
    const line = tasks(page).last().getByTestId("process-line");
    await expect(line).toContainText("改资料");
    await line.locator("summary").click();
    await expect(line.getByRole("menuitem")).toContainText(["问作品"]);
    await expect(line.getByRole("menuitem", { name: "改资料" })).toHaveCount(0);
    // The use the box judged is not repeated on a line of its own.
    await expect(tasks(page).last().getByTestId("routed-line")).toHaveCount(0);
    await expect(tasks(page).last()).toHaveAttribute("data-kind", "change");
    await expect(cardOf(page)).toBeVisible();
  });

  test("手动选「改资料」：照选的发送，不问判断接口；没有改动时只有回答，没有卡片", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    let judged = 0;
    page.on("request", (request) => { if (request.method() === "POST" && routeUrl.test(request.url())) judged += 1; });
    await chooseMode(page, "改资料");
    await expect(box(page)).toHaveAttribute("placeholder", /记进事实/);
    await expect(send(page)).toBeDisabled();
    await box(page).fill("随便说说，没有要改的");
    const created = taskPost(page);
    await send(page).click();
    expect((await created).postDataJSON()).toEqual({ kind: "change", question: "随便说说，没有要改的", context: { page: "writing", chapter_number: expect.any(Number) } });
    await finished(page);
    expect(judged).toBe(0);
    const task = tasks(page).last();
    await expect(task.getByTestId("process-line")).toContainText("改资料");
    await expect(task.locator(".a-answer-note")).toContainText(`查过第 ${LAST_CHAPTER} 章正文，没有找到问题问到的内容。`);
    await expect(cardOf(page)).toHaveCount(0);
    await expect(modeButton(page, "自动")).toBeVisible();
  });
});

test.describe("改资料：标伏笔已回收", () => {
  test("卡片出现：条目、改前改后、依据都对，资料页的伏笔还是原状态；确认后伏笔变成已回收，列表和改动记录里都有；撤销、恢复", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await chooseMode(page, "改资料");
    await box(page).fill(THREAD_ASK);
    const created = taskPost(page);
    await send(page).click();
    expect((await created).postDataJSON()).toEqual({ kind: "change", question: THREAD_ASK, context: { page: "writing", chapter_number: expect.any(Number) } });
    await finished(page);
    const change = await lastChange(page, id);
    // The answer first, as for a question; then the card.
    await expect(tasks(page).last().locator(".a-answer")).toContainText("（示意回答）最后一章写到了这件事。");
    const card = cardOf(page);
    await expect(card.locator(".a-chg-head")).toContainText("资料改动 · 1 条");
    const item = await expectPending(card, change.title, "resolve_thread");
    await expect(item.locator(".a-chg-line strong")).toHaveText(change.title);
    await expect(item.locator(".a-chg-kind")).toHaveText("标伏笔已回收");
    // The words of the author's sentence the change answers to.
    expect(change.request_words).toBeTruthy();
    expect(THREAD_ASK.replace(/\s/g, "")).toContain(change.request_words!.replace(/\s/g, ""));
    await openBasis(item);
    await expect(item.locator(".a-chg-asked")).toHaveCount(0);  // the card's only item: the whole sentence is about it
    await expect(item.locator(".chg-before")).toContainText("已埋设");
    await expect(item.locator(".chg-after")).toContainText(`已回收（第 ${LAST_CHAPTER} 章）`);
    const evidence = item.getByRole("list", { name: "依据" });
    await expect(evidence.getByRole("listitem")).toHaveCount(1);
    await expect(evidence).toContainText(`第 ${LAST_CHAPTER} 章`);
    await expect(item.getByRole("button", { name: "改内容" })).toHaveCount(0);
    await expect(confirmButton(card)).toHaveText("确认 1 条");
    await expect(card.getByRole("button", { name: "不要", exact: true })).toBeVisible();
    // Nothing is written yet.
    expect(await threadStatus(page, id, change.target.id)).toBe("planted");
    await threadsView(page, id);
    await expect(threadRow(page, change.title)).toBeVisible();
    await expect(threadRow(page, change.title)).not.toContainText("助手按你的确认");

    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const posted = confirmPost(page);
    await confirmButton(cardOf(page)).click();
    expect((await posted).postDataJSON()).toEqual({ accepted: [expect.any(String)], edits: {} });
    const done = itemOf(cardOf(page));
    await expect(done).toHaveAttribute("data-status", "applied");
    await expect(stateOf(done)).toHaveText("已执行");
    await expect(confirmButton(cardOf(page))).toHaveCount(0);
    await expect(cardOf(page).getByTestId("change-written")).toContainText("已写入资料");
    await expect(undoOf(cardOf(page))).toBeVisible();
    expect(await threadStatus(page, id, change.target.id)).toBe("resolved");

    // The materials page: the thread is resolved, carries the assistant's tag, and the ledger has the item.
    await threadsView(page, id, true);
    await expect(threadRow(page, change.title)).toContainText("助手按你的确认修改");
    await expect(threadRow(page, change.title)).toContainText("已回收");
    const ledger = await openLedger(page);
    const row = ledger.locator("li").first();
    await expect(row).toContainText("标伏笔已回收");
    await expect(row).toContainText(change.title);
    await expect(row).toContainText("已埋设");
    await expect(row).toContainText(`已回收（第 ${LAST_CHAPTER} 章）`);
    await expect(row).toContainText("已执行");
    await expect(row.getByRole("button", { name: "撤销", exact: true })).toBeVisible();
    await expect(row.getByRole("button", { name: "看对话", exact: true })).toBeVisible();

    // Undo on the card puts the thread back; 恢复 writes it again.
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const again = itemOf(cardOf(page));
    await undoOf(cardOf(page)).click();
    await expect(again).toHaveAttribute("data-status", "undone");
    await expect(stateOf(again)).toHaveText("已撤销");
    expect(await threadStatus(page, id, change.target.id)).toBe("planted");
    await again.getByRole("button", { name: "恢复", exact: true }).click();
    await expect(again).toHaveAttribute("data-status", "applied");
    expect(await threadStatus(page, id, change.target.id)).toBe("resolved");
  });

  test("依据：点章节名打开那一章并把那一句找出来，和回答里的出处一样", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, THREAD_ASK);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await openBasis(itemOf(card));
    await itemOf(card).getByRole("list", { name: "依据" }).locator(".a-where").click();
    await itemOf(card).getByRole("list", { name: "依据" }).getByRole("button", { name: "去原文 →" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=${LAST_CHAPTER}$`));
    await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^第 ${LAST_CHAPTER} 章`) })).toBeAttached();
    const ring = page.locator("#chapter-body .mark-pulse");
    await expect(ring).toBeAttached({ timeout: 6_000 });
    await expect(ring.first()).toBeInViewport();
  });

  test("不要：整张卡片变成没有执行，资料不变；改动记录是空的；别处已经决定过的卡片再点确认，显示提示、卡片换成现在的样子、页面不崩", async ({ page }) => {
    const id = await setup(page);
    const { card, change } = await openCard(page, id, THREAD_ASK);
    await card.getByRole("button", { name: "不要", exact: true }).click();
    const item = itemOf(cardOf(page));
    await expect(item).toHaveAttribute("data-status", "rejected");
    await expect(stateOf(item)).toHaveText("没有执行");
    await expect(confirmButton(cardOf(page))).toHaveCount(0);
    expect(await threadStatus(page, id, change.target.id)).toBe("planted");
    // Deciding it again is refused by the server.
    const task = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks.at(-1);
    const again = await api(page).raw("POST", `/projects/${id}/assistant/tasks/${task.id}/changes/confirm`, { accepted: [task.changes[0].id], edits: {} });
    expect(again.status).toBe(409);
    expect(again.body.error.code).toBe("change_already_decided");
    await threadsView(page, id);
    await ledgerButton(page).click();
    await expect(ledgerOf(page)).toContainText("还没有助手改过的资料。");

    // Another window decided the card first; this one still shows it waiting.
    await openTab(page, id, "workspace");
    const second = await proposeByApi(page, id, THREAD_ASK);
    await page.reload();
    await openAssistantTab(page);
    await expect(confirmButton(cardOf(page))).toBeVisible();
    await rejectByApi(page, id, second);
    await confirmButton(cardOf(page)).click();
    await expect(cardOf(page)).toContainText("这张卡片已经确认或不要过了");
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "rejected");
    await expect(thread(page)).toBeVisible();
    expect(await threadStatus(page, id, change.target.id)).toBe("planted");
  });

  test("资料已变：确认前在资料页改了那条伏笔，点确认显示「资料已经变了（C1）」，什么都没写，条目标出并取消勾选", async ({ page }) => {
    const id = await setup(page);
    const { card, change } = await openCard(page, id, THREAD_ASK);
    await editThread(page, id, change.target.id, "developing");
    await confirmButton(card).click();
    await expect(cardOf(page)).toContainText("资料已经变了（C1），这张卡片不能再确认。可以再让助手看一次。");
    const item = itemOf(cardOf(page));
    await expect(item).toHaveAttribute("data-status", "proposed");
    await expect(item).toContainText("这条资料已经变了");
    await expect(item.getByRole("checkbox")).not.toBeChecked();
    await expect(confirmButton(cardOf(page))).toHaveText("确认 0 条");
    await expect(confirmButton(cardOf(page))).toBeDisabled();
    expect(await threadStatus(page, id, change.target.id)).toBe("developing");
    expect((await api(page).get(`/projects/${id}/assistant/changes`)).changes).toEqual([]);
  });

  test("撤销冲突：确认后在资料页改了那条伏笔，撤销时先问；算了不动，仍然撤销就退回原状态", async ({ page }) => {
    const id = await setup(page);
    const task = await proposeByApi(page, id, THREAD_ASK);
    const threadId = task.changes[0].target.id;
    await confirmByApi(page, id, task);
    await editThread(page, id, threadId, "developing");
    await page.reload();
    await openAssistantTab(page);
    const item = itemOf(cardOf(page));
    await expect(stateOf(item)).toHaveText("已执行");
    await undoOf(cardOf(page)).click();
    const prompt = item.getByRole("alert").filter({ hasText: "撤销会把这些后来的修改一起退回。" });
    await expect(prompt).toContainText("你后来也改过这条资料。");
    await expect(prompt).not.toContainText("这条后来又被改过：");
    expect(await threadStatus(page, id, threadId)).toBe("developing");
    await prompt.getByRole("button", { name: "算了", exact: true }).click();
    await expect(prompt).toHaveCount(0);
    await expect(item).toHaveAttribute("data-status", "applied");
    await undoOf(cardOf(page)).click();
    await prompt.getByRole("button", { name: "仍然撤销", exact: true }).click();
    await expect(item).toHaveAttribute("data-status", "undone");
    await expect(prompt).toHaveCount(0);
    expect(await threadStatus(page, id, threadId)).toBe("planted");
  });

  test("撤销冲突：后来又有一条改动也动了它，提示里列出那条，一起退回", async ({ page }) => {
    const id = await setup(page);
    const first = await proposeByApi(page, id, THREAD_ASK);
    const threadId = first.changes[0].target.id;
    await confirmByApi(page, id, first);
    await editThread(page, id, threadId, "developing");
    const second = await proposeByApi(page, id, THREAD_ASK);
    expect(second.changes[0].target.id).toBe(threadId);
    await confirmByApi(page, id, second);
    await page.reload();
    await openAssistantTab(page);
    const item = itemOf(tasks(page).first().getByRole("region", { name: "资料改动" }));
    await undoOf(tasks(page).first().getByRole("region", { name: "资料改动" })).click();
    const prompt = item.getByRole("alert").filter({ hasText: "撤销会把这些后来的修改一起退回。" });
    await expect(prompt).toContainText("这条后来又被改过：");
    await expect(prompt).toContainText(`${first.changes[0].title}：已回收（第 ${LAST_CHAPTER} 章）`);
    await expect(prompt).not.toContainText("你后来也改过这条资料。");
    await prompt.getByRole("button", { name: "仍然撤销", exact: true }).click();
    await expect(item).toHaveAttribute("data-status", "undone");
    await expect(itemOf(tasks(page).last().getByRole("region", { name: "资料改动" }))).toHaveAttribute("data-status", "undone");
    expect(await threadStatus(page, id, threadId)).toBe("planted");
  });

  test("资料页还有没确认的事实审阅：显示提示和去资料页的链接", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, FACT_ASK);
    await page.route(/\/changes\/confirm$/, async (route) => {
      if (route.request().method() !== "POST") { await route.fallback(); return; }
      await route.fulfill({ status: 409, contentType: "application/json", body: JSON.stringify({ error: { code: "change_memory_review_pending", message: "x", retryable: false, details: { review: "memory_delta" } } }) });
    });
    await confirmButton(card).click();
    await expect(cardOf(page)).toContainText("资料页还有没确认的事实变化，先处理完再确认事实。");
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "proposed");
    await cardOf(page).getByRole("button", { name: "去资料页", exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${id}/memory$`));
  });
});

test.describe("改资料：改事实和加事实", () => {
  test("改事实：改写内容再确认，写进去的是作者的文字，条目显示「你改过」；不能留空，最多 200 字", async ({ page }) => {
    const id = await setup(page);
    const { task, card } = await openCard(page, id, FACT_ASK);
    const item = await expectPending(card, "温岚·", "change_fact");
    await expect(item.locator(".a-chg-kind")).toHaveText("改事实");
    await expect.poll(() => afterOf(item)).toContain(`${MODEL_VALUE}（第 ${LAST_CHAPTER} 章）`);
    await item.getByRole("button", { name: "改内容", exact: true }).click();
    const field = item.getByRole("textbox", { name: /^改后的内容/ });
    await expect(field).toHaveValue(MODEL_VALUE);
    await expect(field).toHaveAttribute("maxlength", "200");
    await expect(item).not.toContainText("你改过");
    await field.fill("");
    await expect(item.getByRole("alert")).toContainText("改写的内容不能为空。");
    await expect(confirmButton(card)).toBeDisabled();
    await field.fill("作者自己的写法");
    await expect(item).toContainText("你改过");
    await expect.poll(() => afterOf(item)).toContain(`作者自己的写法（第 ${LAST_CHAPTER} 章）`);
    await item.getByRole("button", { name: "改好了", exact: true }).click();
    await expect(field).toHaveCount(0);
    await expect(item).toContainText("你改过");
    const posted = confirmPost(page);
    await confirmButton(card).click();
    expect((await posted).postDataJSON()).toEqual({ accepted: [task.changes[0].id], edits: { [task.changes[0].id]: "作者自己的写法" } });
    await expect(item).toHaveAttribute("data-status", "applied");
    await expect(item).toContainText("你改过");
    await expect.poll(async () => (await factRecords(page, id)).filter((fact) => fact.subject === "温岚" && fact.valid_to == null).map((fact) => fact.value)).toContain("作者自己的写法");
    expect((await factRecords(page, id)).map((fact) => fact.value)).not.toContain(MODEL_VALUE);

    await openTab(page, id, "memory");
    await expect(factRow(page, "作者自己的写法")).toContainText("助手按你的确认修改");
    // Undo puts the old wording back and the tag goes.
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await undoOf(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "undone");
    await expect.poll(async () => (await factRecords(page, id)).map((fact) => fact.value)).not.toContain("作者自己的写法");
    await openTab(page, id, "memory");
    await expect(factRow(page, "作者自己的写法")).toHaveCount(0);
  });

  test("加事实：确认后事实列表里有这条，带「助手按你的确认添加」；撤销后消失；恢复后又有", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, ADD_ASK);
    const item = await expectPending(card, "苏岑·", "add_fact");
    await expect(item.locator(".a-chg-kind")).toHaveText("加事实");
    await expect(item.locator(".chg-before")).toContainText("资料里没有");
    await expect(item.locator(".chg-after")).toContainText(`${ADDED_VALUE}（第 ${LAST_CHAPTER} 章）`);
    await expect(item.getByRole("button", { name: "改内容", exact: true })).toBeVisible();
    expect((await factRecords(page, id)).map((fact) => fact.value)).not.toContain(ADDED_VALUE);
    await confirmButton(card).click();
    await expect(item).toHaveAttribute("data-status", "applied");
    await openTab(page, id, "memory");
    await expect(factRow(page, ADDED_VALUE)).toContainText("助手按你的确认添加");
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await undoOf(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "undone");
    await openTab(page, id, "memory");
    await expect(factRow(page, ADDED_VALUE)).toHaveCount(0);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await itemOf(cardOf(page)).getByRole("button", { name: "恢复", exact: true }).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "applied");
    await openTab(page, id, "memory");
    await expect(factRow(page, ADDED_VALUE)).toContainText("助手按你的确认添加");
  });

  test("取消勾选的条目算「不要」：确认（0 条）不能点", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, ADD_ASK);
    const item = itemOf(card);
    await item.getByRole("checkbox").uncheck();
    await expect(confirmButton(card)).toHaveText("确认 0 条");
    await expect(confirmButton(card)).toBeDisabled();
    await item.getByRole("checkbox").check();
    await expect(confirmButton(card)).toBeEnabled();
  });
});

test.describe("改资料：资料页", () => {
  test("在资料页的抽屉里确认和撤销：事实列表和伏笔列表不用刷新就跟着变；改动记录按时间排，能撤销、恢复、看对话", async ({ page }) => {
    const id = await setup(page);
    await openTab(page, id, "memory");
    await openDrawer(page);
    await chooseMode(page, "改资料");
    await box(page).fill(ADD_ASK);
    await send(page).click();
    await finished(page);
    await confirmButton(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "applied");
    await closeDrawer(page);
    // The facts view is still the one on screen: its list moved without a reload.
    await expect(factRow(page, ADDED_VALUE)).toContainText("助手按你的确认添加");
    await openDrawer(page);
    await undoOf(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "undone");
    await closeDrawer(page);
    await expect(factRow(page, ADDED_VALUE)).toHaveCount(0);

    // A thread, on the threads view.
    await page.getByRole("navigation", { name: "资料分类" }).getByRole("button", { name: /^伏笔/ }).click();
    await expect(page.locator(".thread-list li").first()).toBeVisible();
    await openDrawer(page);
    await chooseMode(page, "改资料");
    await box(page).fill(THREAD_ASK);
    await send(page).click();
    await finished(page, 2);
    const change = await lastChange(page, id);
    await confirmButton(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "applied");
    await closeDrawer(page);
    await expect(threadRow(page, change.title)).toHaveCount(0);
    await page.getByRole("button", { name: /^已回收、放弃或归档的/ }).click();
    await expect(threadRow(page, change.title)).toContainText("助手按你的确认修改");

    // The ledger: the thread (latest) and the fact (undone), each with its buttons.
    const ledger = await openLedger(page);
    await expect(ledger.locator("li")).toHaveCount(2);
    await expect(ledger.locator("li").first()).toContainText(change.title);
    const threadItem = ledger.locator("li").filter({ hasText: change.title });
    const factItem = ledger.locator("li").filter({ hasText: ADDED_VALUE });
    await expect(threadItem).toContainText("已执行");
    await expect(factItem).toContainText("加事实");
    await expect(factItem).toContainText("资料里没有");
    await expect(factItem).toContainText("已撤销");
    await factItem.getByRole("button", { name: "恢复", exact: true }).click();
    await expect(factItem).toContainText("已执行");
    await page.getByRole("navigation", { name: "资料分类" }).getByRole("button", { name: /^事实/ }).click();
    await expect(factRow(page, ADDED_VALUE)).toContainText("助手按你的确认添加");
    await page.getByRole("navigation", { name: "资料分类" }).getByRole("button", { name: /^伏笔/ }).click();
    await page.getByRole("button", { name: /^已回收、放弃或归档的/ }).click();
    await expect(ledgerOf(page)).toBeVisible();
    await threadItem.getByRole("button", { name: "撤销", exact: true }).click();
    await expect(threadItem).toContainText("已撤销");
    expect(await threadStatus(page, id, change.target.id)).toBe("planted");
    await expect(threadRow(page, change.title)).toBeVisible();
    await expect(threadRow(page, change.title)).not.toContainText("助手按你的确认");

    // 看对话: the drawer opens on the conversation, at that task.
    await factItem.getByRole("button", { name: "看对话", exact: true }).click();
    await expect(thread(page)).toBeVisible();
    await expect(thread(page).locator('[data-kind="change"]').first()).toBeInViewport();
  });

  test("改动记录里撤销遇到冲突：和卡片里一样先问，仍然撤销后退回；没有记录时说没有", async ({ page }) => {
    const id = await setup(page);
    await openTab(page, id, "memory");
    await openLedger(page);
    await expect(ledgerOf(page)).toContainText("还没有助手改过的资料。");
    const task = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, task);
    await editThread(page, id, task.changes[0].target.id, "developing");
    await page.reload();
    const ledger = await openLedger(page);
    const row = ledger.locator("li").first();
    await row.getByRole("button", { name: "撤销", exact: true }).click();
    const prompt = row.getByRole("alert");
    await expect(prompt).toContainText("你后来也改过这条资料。");
    await expect(prompt).toContainText("撤销会把这些后来的修改一起退回。");
    await prompt.getByRole("button", { name: "仍然撤销", exact: true }).click();
    await expect(row).toContainText("已撤销");
    await expect(row.getByRole("button", { name: "恢复", exact: true })).toBeVisible();
    expect(await threadStatus(page, id, task.changes[0].target.id)).toBe("planted");
  });

  test("作者自己改过的资料不再带「助手按你的确认」的标签", async ({ page }) => {
    const id = await setup(page);
    const task = await proposeByApi(page, id, THREAD_ASK);
    const [change] = task.changes;
    await confirmByApi(page, id, task);
    await threadsView(page, id, true);
    await expect(threadRow(page, change.title)).toContainText("助手按你的确认修改");
    await editThread(page, id, change.target.id, "developing");
    await threadsView(page, id);
    await expect(threadRow(page, change.title)).toBeVisible();
    await expect(threadRow(page, change.title)).not.toContainText("助手按你的确认");
  });
});

// ── 夜间、375 宽和 1280 宽：卡片不溢出，没有横向滚动 ────────────────────────────────────────────────────────────────────
const LONG = "超长的内容".repeat(30) + "https://example.test/" + "a".repeat(80);
const factChange = (over: Record<string, unknown> = {}) => changeItem({ kind: "change_fact", target: { kind: "fact", id: "mem-1", record_id: "mem-1-v2" }, editable: true, ...over });
const crowded = () => changeView([
  changeItem({ id: "a-1", label: "C1" }),
  factChange({ id: "a-2", label: "C2", title: `${LONG.slice(0, 40)}·持有者`, before: LONG, after: `${LONG}（第 10 章）`, value: LONG }),
  factChange({ id: "a-3", label: "C3", kind: "add_fact", target: { kind: "fact", id: "mem-2", record_id: null }, title: "苏岑·状态", before: "资料里没有", after: "左腕受了伤（第 12 章）", value: "左腕受了伤", changed_since: true }),
]);

async function insideColumn(page: Page) {
  await expectNoHorizontalOverflow(page);
  const column = (await thread(page).boundingBox())!;
  const card = (await cardOf(page).boundingBox())!;
  expect(card.x + card.width, "the card ends inside the conversation").toBeLessThanOrEqual(column.x + column.width + 1);
  expect(await cardOf(page).evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
  expect(await thread(page).evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
}

test.describe("改资料：版面", () => {
  test("几条改动：每条只用一行短引文对应作者的话；依据相同的不再重列，写「依据同 C1」；值末尾不带句号再接章号", async ({ page }) => {
    await setup(page);
    await serveTasks(page, () => [changeView([
      changeItem({ id: "a-1", label: "C1" }),
      changeItem({ id: "a-2", label: "C2", kind: "change_fact", target: { kind: "fact", id: "mem-1", record_id: "mem-1-v1" }, title: "罗盘·持有者", editable: true,
        before: "由苏岑保管（第 1 章）", after: "由温岚保管（第 10 章）", value: "由温岚保管。", request_words: "罗盘现在在温岚手里" }),
      changeItem({ id: "a-3", label: "C3", kind: "add_fact", target: { kind: "fact", id: "mem-2", record_id: null }, title: "温岚·状态", editable: true,
        before: "资料里没有", after: "左腕受了伤（第 10 章）", value: "左腕受了伤", request_words: "她左腕受了伤",
        evidence: [{ chapter_number: 10, chapter_title: "第十章 五点四十分", start: 300, end: 330, text: "她左腕的绷带又渗出了一点血。" }] }),
    ])]);
    await page.reload();
    await openAssistantTab(page);
    const card = cardOf(page);
    // 依据 is one folded line for each item; opened, the words of the author's sentence it answers to, then its passages.
    for (const label of ["C1", "C2", "C3"]) await openBasis(itemOf(card, label));
    await expect(itemOf(card, "C1").locator(".a-chg-asked")).toHaveText("对应你说的「廊桥钥匙那条伏笔」");  // the prefix is for screen readers only
    await expect(itemOf(card, "C2").locator(".a-chg-asked")).toContainText("「罗盘现在在温岚手里」");
    await expect(itemOf(card, "C1").getByRole("list", { name: "依据" })).toHaveCount(1);
    await expect(itemOf(card, "C2").getByRole("list", { name: "依据" })).toHaveCount(0);
    await expect(basisOf(itemOf(card, "C2"))).toHaveText("依据同 C1");
    await expect(itemOf(card, "C3").getByRole("list", { name: "依据" })).toHaveCount(1);  // passages of its own
    await expect(basisOf(itemOf(card, "C3"))).not.toContainText("依据同");
    // A rewording keeps the server's form: no full stop before the chapter.
    const second = itemOf(card, "C2");
    await second.getByRole("button", { name: "改内容", exact: true }).click();
    await second.getByRole("textbox", { name: /^改后的内容/ }).fill("由温岚随身保管。");
    await expect.poll(() => afterOf(second)).toContain("由温岚随身保管（第 10 章）");
  });

  test("1280 宽，日间和夜间：卡片和改动记录不溢出", async ({ page }) => {
    const id = await setup(page);
    await serveTasks(page, () => [crowded()]);
    await page.reload();
    await openAssistantTab(page);
    for (const value of ["day", "night"] as const) {
      await theme(page, value);
      await expect(cardOf(page)).toBeVisible();
      await insideColumn(page);
    }
    await page.unrouteAll({ behavior: "ignoreErrors" });
    await confirmByApi(page, id, await proposeByApi(page, id, THREAD_ASK));
    await openTab(page, id, "memory");
    await openLedger(page);
    for (const value of ["night", "day"] as const) {
      await theme(page, value);
      await expectNoHorizontalOverflow(page);
    }
  });

  test("375 宽：写作页的助手窗格里卡片不溢出，资料页的改动记录不溢出", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "v200phone");
    const id = await sampleWorkId(phone);
    await serveTasks(phone, () => [crowded()]);
    await openTab(phone, id, "workspace");
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect(cardOf(phone)).toBeVisible();
    await insideColumn(phone);
    await itemOf(cardOf(phone), "C2").getByRole("button", { name: "改内容", exact: true }).tap();
    await expect(itemOf(cardOf(phone), "C2").getByRole("textbox", { name: /^改后的内容/ })).toBeVisible();
    await insideColumn(phone);
    await phone.unrouteAll({ behavior: "ignoreErrors" });
    await confirmByApi(phone, id, await proposeByApi(phone, id, THREAD_ASK));
    await openTab(phone, id, "memory");
    await openLedger(phone);
    await expectNoHorizontalOverflow(phone);
    await theme(phone, "night");
    await expectNoHorizontalOverflow(phone);
    await context.close();
  });
});

// ── 图 ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────
const shots = process.env.SHOTS_V200_DIR;
test.describe("改资料 截图", () => {
  test.skip(!shots, "SHOTS_V200_DIR is not set");
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
  const fact = (over: Record<string, unknown> = {}) => factChange({ title: "罗盘·持有者", before: "由苏岑保管（第 1 章）", after: "由温岚保管（第 10 章）", value: "由温岚保管", request_words: "罗盘现在在温岚手里", ...over });

  test("卡片：待确认、改内容展开、已执行和已撤销和没有执行", async ({ page }) => {
    await setup(page);
    let list: unknown[] = [changeView([
      changeItem({ id: "a-1", label: "C1" }),
      fact({ id: "a-2", label: "C2" }),
      fact({ id: "a-3", label: "C3", kind: "add_fact", target: { kind: "fact", id: "mem-2", record_id: null }, title: "温岚·状态", before: "资料里没有", after: "左腕受了伤（第 10 章）", value: "左腕受了伤", request_words: "她左腕受了伤", changed_since: true }),
    ])];
    await serveTasks(page, () => list);
    await page.reload();
    await openAssistantTab(page);
    await both(page, (value) => snap(thread(page), "01-待确认的卡片", value));
    const second = itemOf(cardOf(page), "C2");
    await second.getByRole("button", { name: "改内容", exact: true }).click();
    await second.getByRole("textbox", { name: /^改后的内容/ }).fill("由温岚随身保管。");
    await both(page, (value) => snap(thread(page), "02-改内容展开", value));
    const now = new Date().toISOString();
    list = [changeView([
      changeItem({ id: "a-1", label: "C1", status: "applied", applied_at: now, decided_at: now }),
      fact({ id: "a-2", label: "C2", after: "由温岚随身保管（第 10 章）", value: "由温岚随身保管", status: "undone", edited_by_author: true, undone_at: now }),
      fact({ id: "a-3", label: "C3", kind: "add_fact", target: { kind: "fact", id: "mem-2", record_id: null }, title: "温岚·状态", before: "资料里没有", after: "左腕受了伤（第 10 章）", value: "左腕受了伤", request_words: "她左腕受了伤", status: "rejected", changed_since: null }),
    ])];
    await page.reload();
    await openAssistantTab(page);
    await both(page, (value) => snap(thread(page), "03-已执行、已撤销、没有执行", value));
  });

  test("冲突提示、改动记录、资料页的标记", async ({ page }) => {
    const id = await setup(page);
    const first = await proposeByApi(page, id, THREAD_ASK);
    await confirmByApi(page, id, first);
    await editThread(page, id, first.changes[0].target.id, "developing");
    await confirmByApi(page, id, await proposeByApi(page, id, THREAD_ASK));
    await confirmByApi(page, id, await proposeByApi(page, id, ADD_ASK));
    const changed = await proposeByApi(page, id, FACT_ASK);
    await confirmByApi(page, id, changed, { [changed.changes[0].id]: "第 4 章上午就已经知道廊桥钥匙的含义。" });
    await page.reload();
    await openAssistantTab(page);
    const item = itemOf(tasks(page).first().getByRole("region", { name: "资料改动" }));
    await undoOf(tasks(page).first().getByRole("region", { name: "资料改动" })).click();
    await expect(item.locator(".a-chg-conflict")).toBeVisible();
    await both(page, (value) => snap(thread(page), "04-撤销冲突提示", value));
    await item.getByRole("button", { name: "算了", exact: true }).click();

    await openTab(page, id, "memory");
    await openLedger(page);
    await both(page, (value) => snap(page, "05-改动记录", value));
    await ledgerButton(page).click();
    await expect(page.getByRole("list", { name: "事实列表" })).toBeVisible();
    await both(page, (value) => snap(factRow(page, ADDED_VALUE), "06-资料页标记-加事实", value));
    await both(page, (value) => snap(factRow(page, "廊桥钥匙的含义"), "06-资料页标记-改事实", value));
    await threadsView(page, id, true);
    await both(page, (value) => snap(threadRow(page, first.changes[0].title), "06-资料页标记-伏笔", value));
  });

  test("375 宽：卡片、改动记录", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "v200shot");
    const id = await sampleWorkId(phone);
    await serveTasks(phone, () => [changeView([changeItem({ id: "a-1", label: "C1" }), fact({ id: "a-2", label: "C2" })])]);
    await openTab(phone, id, "workspace");
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect(cardOf(phone)).toBeVisible();
    await both(phone, (value) => snap(phone, "07-375宽-卡片", value));
    await phone.unrouteAll({ behavior: "ignoreErrors" });
    await confirmByApi(phone, id, await proposeByApi(phone, id, THREAD_ASK));
    await openTab(phone, id, "memory");
    await openLedger(phone);
    await both(phone, (value) => snap(phone, "07-375宽-改动记录", value));
    await context.close();
  });
});
