import type { Locator, Page } from "@playwright/test";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { api, expect, expectNoHorizontalOverflow, openTab, registerAccount, sampleWorkId, test } from "./support/app";
import { box, chooseMode, finished, openAssistantTab, send, taskPost, thread } from "./support/assistant";
import { serveTasks } from "./support/assistant-mock";
import {
  ABANDON_THREAD_ASK, ADD_THREAD_ASK, ADDED_THREAD_NOTE, ADDED_THREAD_TITLE, cardOf, changeItem, changeView, confirmButton, confirmByApi, confirmPost, EDIT_THREAD_ASK,
  EDITED_NOTE, afterOf, basisOf, beforeOf, itemOf, lastChange, LAST_CHAPTER, openBasis, openCard, openLedger, proposeByApi, threadRecord, threadRecords, threadsView, threadsViewWith, undoOf,
} from "./support/assistant-change";
import { theme } from "./support/pages";
import { setup } from "./support/writing";

// v2.1 (08): the second batch of actions of 改资料 — 加伏笔, 改伏笔说明, 伏笔标放弃. Each goes: card → confirm → the tag on the materials page → undo → put
// back. The test model proposes by a marker in the sentence (see support/assistant-change.ts). Pictures are written only when SHOTS_V210_ACTIONS_DIR
// names a folder.

const stateOf = (item: Locator) => item.locator(".a-chg-state");
const STATUS_TEXT: Record<string, string> = { planned: "计划中", planted: "已埋设", developing: "推进中" };

test.describe("改资料：加伏笔", () => {
  test("在输入框里提出：卡片写明改前改后和依据；确认后伏笔列表里有这条并带「助手按你的确认添加」；撤销后从列表消失（已归档）；恢复后又在", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await chooseMode(page, "改资料");
    await box(page).fill(ADD_THREAD_ASK);
    const created = taskPost(page);
    await send(page).click();
    expect((await created).postDataJSON()).toEqual({ kind: "change", question: ADD_THREAD_ASK, context: { page: "writing", chapter_number: expect.any(Number) } });
    await finished(page);
    const change = await lastChange(page, id);
    const card = cardOf(page);
    await expect(card.locator(".a-chg-head")).toContainText("资料改动 · 1 条");
    const item = itemOf(card);
    await expect(item).toHaveAttribute("data-kind", "add_thread");
    await expect(item).toHaveAttribute("data-status", "proposed");
    await expect(item.locator(".a-chg-line strong")).toHaveText(ADDED_THREAD_TITLE);
    await expect(item.locator(".a-chg-kind")).toHaveText("加伏笔");
    await expect(item.locator(".chg-before")).toContainText("资料里没有");
    await expect(item.locator(".chg-after")).toContainText(`已埋设（第 ${LAST_CHAPTER} 章）：${ADDED_THREAD_NOTE}`);
    await openBasis(item);
    await expect(item.getByRole("list", { name: "依据" }).getByRole("listitem")).toHaveCount(1);
    await expect(item.getByRole("button", { name: "改内容", exact: true })).toBeVisible();
    expect((await threadRecords(page, id)).map((record) => record.title)).not.toContain(ADDED_THREAD_TITLE);

    await confirmButton(card).click();
    await expect(item).toHaveAttribute("data-status", "applied");
    await expect(stateOf(item)).toHaveText("已写入");
    const written = await threadRecord(page, id, change.target.id);
    expect([written.title, written.status, written.description, written.archived_at]).toEqual([ADDED_THREAD_TITLE, "planted", ADDED_THREAD_NOTE, null]);
    await expect(await threadsViewWith(page, id, ADDED_THREAD_TITLE)).toContainText("助手按你的确认添加");
    const ledger = await openLedger(page);
    await expect(ledger.locator("li").first()).toContainText("加伏笔");
    await expect(ledger.locator("li").first()).toContainText(ADDED_THREAD_TITLE);

    // Undo: the thread is archived, and leaves the list of open threads.
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await undoOf(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "undone");
    expect((await threadRecord(page, id, change.target.id)).archived_at).not.toBeNull();
    await threadsView(page, id);
    await expect(page.locator(".thread-list li").first()).toBeVisible();
    await expect(page.locator(".thread-list li").filter({ hasText: ADDED_THREAD_TITLE })).toHaveCount(0);

    // 恢复: it is out of the archive again, with its tag.
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await itemOf(cardOf(page)).getByRole("button", { name: "恢复", exact: true }).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "applied");
    expect((await threadRecord(page, id, change.target.id)).archived_at).toBeNull();
    await expect(await threadsViewWith(page, id, ADDED_THREAD_TITLE)).toContainText("助手按你的确认添加");
  });

  test("作者改写说明再确认：写进去的是作者的文字；标题不能改", async ({ page }) => {
    const id = await setup(page);
    const { task, card, change } = await openCard(page, id, ADD_THREAD_ASK);
    const item = itemOf(card);
    await item.getByRole("button", { name: "改内容", exact: true }).click();
    const field = item.getByRole("textbox", { name: /^改后的内容/ });
    await expect(field).toHaveValue(ADDED_THREAD_NOTE);
    await expect(field).toHaveAttribute("maxlength", "200");
    await field.fill("作者自己的说明");
    await expect(item.locator(".chg-after")).toContainText(`已埋设（第 ${LAST_CHAPTER} 章）：作者自己的说明`);
    await expect(item.locator(".a-chg-line strong")).toHaveText(ADDED_THREAD_TITLE);
    await expect(item.getByRole("textbox")).toHaveCount(1);  // the title has no field
    const posted = confirmPost(page);
    await confirmButton(card).click();
    expect((await posted).postDataJSON()).toEqual({ accepted: [task.changes[0].id], edits: { [task.changes[0].id]: "作者自己的说明" } });
    await expect(item).toHaveAttribute("data-status", "applied");
    expect((await threadRecord(page, id, change.target.id)).description).toBe("作者自己的说明");
  });

  test("确认前作者在资料页加了同名伏笔：点确认显示「资料已经变了（C1）」，什么都没写", async ({ page }) => {
    const id = await setup(page);
    const { card } = await openCard(page, id, ADD_THREAD_ASK);
    const before = (await threadRecords(page, id)).length;
    const version = (await api(page).get(`/projects/${id}/foreshadows`)).foreshadow_version;
    await api(page).post(`/projects/${id}/foreshadows`, { base_foreshadow_version: version, title: ADDED_THREAD_TITLE, description: "作者自己先加的", status: "planted" });
    await confirmButton(card).click();
    await expect(cardOf(page)).toContainText("资料已经变了（C1），这张卡片不能再确认。可以再让助手看一次。");
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "proposed");
    await expect(itemOf(cardOf(page))).toContainText("这条资料已经变了");
    expect((await threadRecords(page, id)).length).toBe(before + 1);  // only the author's
  });
});

test.describe("改资料：改伏笔说明", () => {
  test("卡片写明改前改后的说明全文，依据位置是作者的话；展开改写；确认后资料页有标记；撤销后说明回到原样、标记没了", async ({ page }) => {
    const id = await setup(page);
    const { task, card, change } = await openCard(page, id, EDIT_THREAD_ASK);
    const original = (await threadRecord(page, id, change.target.id)).description;
    const item = itemOf(card);
    await expect(item).toHaveAttribute("data-kind", "edit_thread");
    await expect(item.locator(".a-chg-line strong")).toHaveText(change.title);
    await expect(item.locator(".a-chg-kind")).toHaveText("改伏笔说明");
    // A long note is one text with the difference marked: what stays and what is added make the new note, what stays and what goes make the old one.
    await expect(item.locator(".a-chg-diff")).toBeVisible();
    await expect.poll(() => beforeOf(item)).toBe(original.trim());
    await expect.poll(() => afterOf(item)).toBe(EDITED_NOTE);
    await expect(basisOf(item)).toHaveText("依据：你的话");
    await openBasis(item);
    await expect(item.locator(".a-chg-asked")).toHaveText(`你说的「${change.request_words}」`);
    expect(EDIT_THREAD_ASK.replace(/\s/g, "")).toContain(change.request_words!);
    await expect(item.getByRole("list", { name: "依据" })).toHaveCount(0);
    await expect(item.getByRole("textbox")).toHaveCount(0);

    await item.getByRole("button", { name: "改内容", exact: true }).click();
    const field = item.getByRole("textbox", { name: /^改后的内容/ });
    await expect(field).toHaveValue(EDITED_NOTE);
    await field.fill("");
    await expect(item.getByRole("alert")).toContainText("改写的内容不能为空。");
    await expect(confirmButton(card)).toBeDisabled();
    await field.fill("作者自己的新说明");
    await expect(item).toContainText("你改过");
    await expect.poll(() => afterOf(item)).toBe("作者自己的新说明");
    await item.getByRole("button", { name: "改好了", exact: true }).click();
    expect((await threadRecord(page, id, change.target.id)).description).toBe(original);  // nothing is written yet

    const posted = confirmPost(page);
    await confirmButton(card).click();
    expect((await posted).postDataJSON()).toEqual({ accepted: [task.changes[0].id], edits: { [task.changes[0].id]: "作者自己的新说明" } });
    await expect(item).toHaveAttribute("data-status", "applied");
    const written = await threadRecord(page, id, change.target.id);
    expect(written.description).toBe("作者自己的新说明");
    await expect(await threadsViewWith(page, id, change.title)).toContainText("助手按你的确认修改");
    const ledger = await openLedger(page);
    await expect(ledger.locator("li").first()).toContainText("改伏笔说明");
    await expect(ledger.locator("li").first()).toContainText("作者自己的新说明");

    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await undoOf(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "undone");
    const back = await threadRecord(page, id, change.target.id);
    expect([back.description, back.status]).toEqual([original, written.status]);
    await expect(await threadsViewWith(page, id, change.title)).not.toContainText("助手按你的确认");
  });

  test("确认前作者在资料页改了那条说明：点确认显示「资料已经变了（C1）」，条目取消勾选", async ({ page }) => {
    const id = await setup(page);
    const { card, change } = await openCard(page, id, EDIT_THREAD_ASK);
    const record = await threadRecord(page, id, change.target.id);
    await api(page).patch(`/projects/${id}/foreshadows/${record.id}`, { base_version: record.version, description: "作者先改的说明" });
    await confirmButton(card).click();
    await expect(cardOf(page)).toContainText("资料已经变了（C1），这张卡片不能再确认。可以再让助手看一次。");
    await expect(itemOf(cardOf(page)).getByRole("checkbox")).not.toBeChecked();
    expect((await threadRecord(page, id, change.target.id)).description).toBe("作者先改的说明");
  });
});

test.describe("改资料：伏笔标放弃", () => {
  test("卡片只在标签旁多一行小字，没有依据列表，依据位置是作者的话；确认后伏笔放弃了、资料页有标记；撤销后状态回到原样、标记没了", async ({ page }) => {
    const id = await setup(page);
    const { card, change } = await openCard(page, id, ABANDON_THREAD_ASK);
    const original = await threadRecord(page, id, change.target.id);
    const item = itemOf(card);
    await expect(item).toHaveAttribute("data-kind", "abandon_thread");
    await expect(item.locator(".a-chg-line strong")).toHaveText(change.title);
    await expect(item.locator(".a-chg-kind")).toHaveText("伏笔标放弃");
    await expect(item.locator(".a-chg-note")).toHaveText("作者确认后这条伏笔不再提醒");
    await expect(item.locator(".chg-before")).toContainText(STATUS_TEXT[original.status]);
    await expect(item.locator(".chg-after")).toContainText("已放弃");
    await expect(basisOf(item)).toHaveText("依据：你的话");
    await openBasis(item);
    await expect(item.locator(".a-chg-asked")).toHaveText(`你说的「${change.request_words}」`);
    expect(ABANDON_THREAD_ASK.replace(/\s/g, "")).toContain(change.request_words!);
    await expect(item.getByRole("list", { name: "依据" })).toHaveCount(0);
    await expect(item.getByRole("button", { name: "改内容", exact: true })).toHaveCount(0);
    await expect(confirmButton(card)).toHaveText("确认 1 条");
    expect((await threadRecord(page, id, change.target.id)).status).toBe(original.status);

    await confirmButton(card).click();
    await expect(item).toHaveAttribute("data-status", "applied");
    await expect(item.locator(".a-chg-note")).toHaveCount(0);  // the line is for the card that waits
    const written = await threadRecord(page, id, change.target.id);
    expect([written.status, written.resolved]).toEqual(["abandoned", null]);
    const row = await threadsViewWith(page, id, change.title);
    await expect(row).toContainText("助手按你的确认修改");
    await expect(row).toContainText("放弃了");
    const ledger = await openLedger(page);
    await expect(ledger.locator("li").first()).toContainText("伏笔标放弃");
    await expect(ledger.locator("li").first()).toContainText("已放弃");

    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await undoOf(cardOf(page)).click();
    await expect(itemOf(cardOf(page))).toHaveAttribute("data-status", "undone");
    expect((await threadRecord(page, id, change.target.id)).status).toBe(original.status);
    await threadsView(page, id);
    await expect(threadRow(page, change.title)).toBeVisible();
    await expect(threadRow(page, change.title)).not.toContainText("助手按你的确认");
  });
});

// ── 夜间、375 宽：卡片不溢出；图 ───────────────────────────────────────────────────────────────────────────────────────
const threadRow = (page: Page, title: string) => page.locator(".thread-list li").filter({ hasText: title });
const NOTE = "钥匙被温岚放回了廊桥的石缝，去向已经明了。";
const items = () => [
  changeItem({ id: "a-1", label: "C1", kind: "add_thread", target: { kind: "foreshadow", id: "fs-new" }, title: ADDED_THREAD_TITLE, before: "资料里没有",
    after: `已埋设（第 ${LAST_CHAPTER} 章）：${ADDED_THREAD_NOTE}`, editable: true, value: ADDED_THREAD_NOTE, request_words: "最后一章埋了个悬念" }),
  changeItem({ id: "a-2", label: "C2", kind: "edit_thread", title: "廊桥钥匙的指向", before: "廊桥钥匙还没有交代去向。", after: NOTE, editable: true, value: NOTE, evidence: [],
    evidence_required: false, request_words: "廊桥钥匙那条伏笔的说明" }),
  changeItem({ id: "a-3", label: "C3", kind: "abandon_thread", title: "罗盘下落", before: "已埋设", after: "已放弃", evidence: [], evidence_required: false, risk: "high",
    request_words: "罗盘那条线不追了" }),
];
const view = () => changeView(items(), { question: "最后一章埋了个悬念，加一条伏笔；廊桥钥匙那条伏笔的说明改一改；罗盘那条线不追了" });

async function insideColumn(page: Page) {
  await expectNoHorizontalOverflow(page);
  const column = (await thread(page).boundingBox())!;
  const card = (await cardOf(page).boundingBox())!;
  expect(card.x + card.width, "the card ends inside the conversation").toBeLessThanOrEqual(column.x + column.width + 1);
  expect(await cardOf(page).evaluate((node) => node.scrollWidth <= node.clientWidth + 1)).toBe(true);
}

test.describe("改资料：新动作的版面", () => {
  test("三种新动作在一张卡片里：标签、放弃的小字、依据位置的作者的话；日间夜间不溢出", async ({ page }) => {
    await setup(page);
    await serveTasks(page, () => [view()]);
    await page.reload();
    await openAssistantTab(page);
    const card = cardOf(page);
    await expect(itemOf(card, "C1").locator(".a-chg-kind")).toHaveText("加伏笔");
    await expect(itemOf(card, "C2").locator(".a-chg-kind")).toHaveText("改伏笔说明");
    await expect(itemOf(card, "C3").locator(".a-chg-kind")).toHaveText("伏笔标放弃");
    await expect(itemOf(card, "C3").locator(".a-chg-note")).toHaveText("作者确认后这条伏笔不再提醒");
    await expect(itemOf(card, "C1").locator(".a-chg-note")).toHaveCount(0);
    for (const label of ["C1", "C2", "C3"]) await openBasis(itemOf(card, label));
    await expect(itemOf(card, "C2").locator(".a-chg-asked")).toHaveText("你说的「廊桥钥匙那条伏笔的说明」");
    await expect(itemOf(card, "C3").locator(".a-chg-asked")).toHaveText("你说的「罗盘那条线不追了」");
    await expect(itemOf(card, "C1").locator(".a-chg-asked")).toContainText("「最后一章埋了个悬念」");
    for (const value of ["day", "night"] as const) {
      await theme(page, value);
      await expect(card).toBeVisible();
      await insideColumn(page);
    }
  });

  test("375 宽：卡片不溢出，改说明的框展开也不溢出", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "v210act");
    const id = await sampleWorkId(phone);
    await serveTasks(phone, () => [view()]);
    await openTab(phone, id, "workspace");
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect(cardOf(phone)).toBeVisible();
    await insideColumn(phone);
    await itemOf(cardOf(phone), "C2").getByRole("button", { name: "改内容", exact: true }).tap();
    await expect(itemOf(cardOf(phone), "C2").getByRole("textbox", { name: /^改后的内容/ })).toBeVisible();
    await insideColumn(phone);
    await theme(phone, "night");
    await insideColumn(phone);
    await context.close();
  });
});

const shots = process.env.SHOTS_V210_ACTIONS_DIR;
test.describe("v2.1 第二批动作 截图", () => {
  test.skip(!shots, "SHOTS_V210_ACTIONS_DIR is not set");
  const snap = async (target: Page | Locator, name: string) => {
    await mkdir(shots!, { recursive: true });
    const page = "goto" in target ? (target as Page) : (target as Locator).page();
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.waitForTimeout(500);
    await target.screenshot({ path: path.join(shots!, `${name}.png`), animations: "disabled" });
  };

  test("卡片：日间、夜间", async ({ page }) => {
    await setup(page);
    await serveTasks(page, () => [view()]);
    await page.reload();
    await openAssistantTab(page);
    await itemOf(cardOf(page), "C2").getByRole("button", { name: "改内容", exact: true }).click();
    await theme(page, "day");
    await snap(cardOf(page), "01-三种新动作的卡片-日间");
    await theme(page, "night");
    await snap(cardOf(page), "02-三种新动作的卡片-夜间");
    await theme(page, "day");
  });

  test("375 宽：卡片", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "v210actshot");
    const id = await sampleWorkId(phone);
    await serveTasks(phone, () => [view()]);
    await openTab(phone, id, "workspace");
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect(cardOf(phone)).toBeVisible();
    await snap(cardOf(phone), "03-375宽-卡片-日间");
    await theme(phone, "night");
    await snap(cardOf(phone), "04-375宽-卡片-夜间");
    await context.close();
  });

  test("资料页的标记：加伏笔、改说明、标放弃", async ({ page }) => {
    const id = await setup(page);
    const added = await proposeByApi(page, id, ADD_THREAD_ASK);
    await confirmByApi(page, id, added);
    const abandoned = await proposeByApi(page, id, ABANDON_THREAD_ASK);
    await confirmByApi(page, id, abandoned);
    await threadsView(page, id);
    await expect(threadRow(page, ADDED_THREAD_TITLE)).toContainText("助手按你的确认添加");
    await snap(threadRow(page, ADDED_THREAD_TITLE), "05-资料页标记-加伏笔");
    await openLedger(page);
    await snap(page, "06-改动记录-加伏笔和标放弃");
  });
});
