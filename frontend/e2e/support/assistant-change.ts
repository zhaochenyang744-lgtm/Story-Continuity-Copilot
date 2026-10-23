import type { Locator, Page } from "@playwright/test";
import { api, expect } from "./app";
import { openAssistantTab, thread, topbarAssistant } from "./assistant";
import { askView } from "./assistant-mock";

// What the 改资料 specs share (v2.0). The test model (backend/tests/e2e_app.py) proposes by a marker in the sentence:
//   E2E_CHANGE_THREAD  marks the first thread that is not resolved as resolved, on a passage of the last written chapter (10); which thread
//                      that is depends on the order the sample work's threads were stored in, so a test reads it from the card;
//   E2E_CHANGE_FACT    changes the first fact it is shown about 温岚 to "（示意改后）正文最新的写法";
//   E2E_ADD_FACT       adds the fact 苏岑 · 状态：（示意）左腕受了伤;
//   none of them       proposes nothing and ends in "not found".

export const THREAD_ASK = "E2E_CHANGE_THREAD 那条还没收的伏笔最后一章已经收了";
export const FACT_ASK = "E2E_CHANGE_FACT 温岚那条事实过时了，按最后一章改一下";
export const ADD_ASK = "E2E_ADD_FACT 苏岑左腕受伤的事记进事实";
export const ADDED_VALUE = "（示意）左腕受了伤";
export const MODEL_VALUE = "（示意改后）正文最新的写法";
export const LAST_CHAPTER = 10;

export type Change = { id: string; label: string; status: string; title: string; request_words: string | null; target: { kind: string; id: string; record_id?: string | null } };
export type ChangeTask = { id: string; status: string; changes: Change[] };

/** A change task started through the API and waited for: the same task the box would start, without the box. */
export async function proposeByApi(page: Page, id: string, question: string): Promise<ChangeTask> {
  const created = await api(page).post(`/projects/${id}/assistant/tasks`, { kind: "change", question, context: { page: "materials" } });
  await expect.poll(async () => (await api(page).get(`/projects/${id}/assistant/tasks/${created.id}`)).status, { timeout: 30_000 }).toBe("completed");
  return api(page).get(`/projects/${id}/assistant/tasks/${created.id}`);
}
export const confirmByApi = (page: Page, id: string, task: ChangeTask, edits: Record<string, string> = {}) =>
  api(page).post(`/projects/${id}/assistant/tasks/${task.id}/changes/confirm`, { accepted: task.changes.map((item) => item.id), edits });
export const rejectByApi = (page: Page, id: string, task: ChangeTask) => api(page).post(`/projects/${id}/assistant/tasks/${task.id}/changes/reject`, {});
/** The first item of the newest change task of the conversation (read from the server: the thread a run chose is not known beforehand). */
export async function lastChange(page: Page, id: string): Promise<Change> {
  const task = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks.filter((item: { kind: string }) => item.kind === "change").at(-1) as ChangeTask;
  expect(task?.changes?.length, "the newest change task has a card").toBeGreaterThan(0);
  return task.changes[0];
}

/** A thread as the materials hold it. */
export async function threadRecord(page: Page, id: string, threadId: string) {
  const records = (await api(page).get(`/projects/${id}/foreshadows?include_archived=true`)).records as { id: string; title: string; status: string; version: number }[];
  const found = records.find((record) => record.id === threadId);
  expect(found, `the thread ${threadId}`).toBeTruthy();
  return found!;
}
export const threadStatus = async (page: Page, id: string, threadId: string) => (await threadRecord(page, id, threadId)).status;
/** The author edits that thread on their own (the page's own edit): it leaves the state a change expects. */
export async function editThread(page: Page, id: string, threadId: string, status: string) {
  const record = await threadRecord(page, id, threadId);
  await api(page).patch(`/projects/${id}/foreshadows/${record.id}`, { base_version: record.version, status, resolved_chapter_id: null });
}
/** The confirmed facts of the current version. */
export const factRecords = async (page: Page, id: string) => (await api(page).get(`/projects/${id}/memory`)).records as { id: string; subject: string; predicate: string; value: string; valid_to: number | null }[];

/** After the work's writing page has been opened: the change task made through the API is in the assistant column. */
export async function openCard(page: Page, id: string, question: string) {
  const task = await proposeByApi(page, id, question);
  await page.reload();
  await openAssistantTab(page);
  return { task, change: task.changes[0], card: cardOf(page) };
}
export const cardOf = (page: Page) => thread(page).getByRole("region", { name: "资料改动" }).last();
export const itemOf = (card: Locator, label = "C1") => card.locator(`[data-label="${label}"]`);
export const confirmButton = (card: Locator) => card.getByRole("button", { name: /^确认（\d+ 条）$/ });
export const confirmPost = (page: Page) => page.waitForRequest((request) => request.method() === "POST" && /\/changes\/confirm$/.test(request.url()));

/** The materials page's threads view, with the closed ones shown. */
export async function threadsView(page: Page, id: string, showClosed = false) {
  await page.goto(`/projects/${id}/memory?view=threads`);
  await expect(page.locator(".materials-view.threads")).toBeVisible();
  await expect(page.getByText("正在读取…")).toHaveCount(0);
  if (showClosed) await page.getByRole("button", { name: /^已回收、放弃或归档的/ }).click();
}
export const threadRow = (page: Page, title: string) => page.locator(".thread-list li").filter({ hasText: title });
export const factRow = (page: Page, text: string) => page.getByRole("list", { name: "事实列表" }).locator("li").filter({ hasText: text });
export const ledgerButton = (page: Page) => page.getByRole("button", { name: "助手改动记录", exact: true });
export const ledgerOf = (page: Page) => page.getByRole("region", { name: "助手改动记录" });
export async function openLedger(page: Page) {
  await ledgerButton(page).click();
  await expect(ledgerOf(page)).toBeVisible();
  return ledgerOf(page);
}
/** The assistant drawer of a page that has no column of its own. */
export async function openDrawer(page: Page) {
  await topbarAssistant(page).click();
  await expect(thread(page)).toBeVisible();
}
export async function closeDrawer(page: Page) {
  await page.getByRole("button", { name: "关闭助手", exact: true }).click();
  await expect(thread(page)).toHaveCount(0);
}

// ── Task views made by hand (for the pictures: a card of several items in states one run cannot hold still) ─────────────────
const ago = (seconds: number) => new Date(Date.now() - seconds * 1000).toISOString();
export function changeItem(over: Record<string, unknown> = {}) {
  return {
    id: "achange-mock-1", label: "C1", task_id: "atask-mock-change", kind: "resolve_thread", target: { kind: "foreshadow", id: "fs-mock" },
    title: "廊桥钥匙的指向", before: "已埋设", after: "已回收（第 10 章）", editable: false, value: null,
    evidence: [{ chapter_number: 10, chapter_title: "第十章 五点四十分", start: 120, end: 150, text: "温岚把那把铜钥匙放回了廊桥的石缝里，转身下了台阶。" }],
    request_words: "廊桥钥匙那条伏笔", status: "proposed", edited_by_author: false, changed_since: false, created_at: ago(60), decided_at: null, applied_at: null, undone_at: null, ...over,
  };
}
export function changeView(items: unknown[], over: Record<string, unknown> = {}) {
  return askView({
    id: "atask-mock-change", kind: "change", question: "廊桥钥匙那条伏笔收了，罗盘现在在温岚手里，她左腕受了伤，一并改一下", context: { page: "materials" },
    answer: { status: "answered", sentences: [{ text: "第 10 章写到温岚把钥匙放回了廊桥，罗盘由她保管，左腕的伤也在这一章出现。", refs: ["R3"] }], note: null },
    changes: items, ...over,
  });
}
