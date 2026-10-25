import type { Locator, Page } from "@playwright/test";
import { expect } from "./app";
import { beginCheck, findings, finishCheck, saveBody, selectIssue, setup } from "./writing";

// What the assistant specs share: where things are in the column, and the small moves everyone makes.

export const thread = (page: Page) => page.getByTestId("assistant-thread");
/** Every entry of the conversation (a question with its answers, a 写前回顾, a 帮我改这一处). */
export const tasks = (page: Page) => thread(page).locator("[data-task]");
export const box = (page: Page) => thread(page).getByRole("textbox", { name: "向助手提问", exact: true });
export const send = (page: Page) => thread(page).getByRole("button", { name: "发送", exact: true });
export const stopButton = (page: Page) => thread(page).locator(".cx-send.stop");
export const sideTab = (page: Page) => findings(page).getByRole("tab", { name: /^助手/ });
export const topbarAssistant = (page: Page) => page.locator("#assistant-open");
// The figure rolls like a counter when it changes (a digit is in the page twice while it does), so it is read from its label.
export const allowance = async (page: Page) => Number(((await page.locator(".topbar-quota .odo").getAttribute("aria-label")) ?? "").replace(/\D/g, ""));
export const taskPost = (page: Page) => page.waitForRequest((request) => request.method() === "POST" && /\/assistant\/tasks$/.test(request.url()));
/** A context tag inside the box (its text is followed by the × that takes it off). */
export const chip = (page: Page, text: string) => thread(page).locator(".a-chip").filter({ hasText: text });
export const toolbar = (page: Page) => page.getByRole("toolbar", { name: "对选中的文字提问", exact: true });
/** The uses the mode menu offers, by their names (each entry also carries a line saying what it does). */
export const menuNames = (root: Locator) => root.getByRole("menuitemradio").evaluateAll((nodes) => nodes.map((node) => node.getAttribute("aria-label")));
export const composeNote = "回答由 AI 生成，可能出错，请点出处核对。";

export async function openAssistantTab(page: Page) {
  await sideTab(page).click();
  await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
  await expect(thread(page)).toBeVisible();
  // Switching to the tab puts the cursor in the box, where the key hint stands in the cost line's place; most checks read the line at rest.
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
}
export async function ask(page: Page, question: string) {
  await box(page).fill(question);
  await send(page).click();
}
export async function finished(page: Page, count = 1, status = "completed") {
  await expect(thread(page).locator(`[data-task][data-status="${status}"]`)).toHaveCount(count, { timeout: 20_000 });
}
/** A real text selection inside an element, made the way the browser would: the first `length` characters of its first long text node. */
export async function select(page: Page, selector: string, length = 12) {
  await page.evaluate(({ selector, length }) => {
    const root = document.querySelector(selector)!;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    let node = walker.nextNode();
    while (node && (node.textContent ?? "").trim().length < length + 2) node = walker.nextNode();
    const range = document.createRange();
    range.setStart(node!, 0);
    range.setEnd(node!, length);
    const selection = window.getSelection()!;
    selection.removeAllRanges();
    selection.addRange(range);
  }, { selector, length });
}
export const selectedWords = (page: Page) => page.evaluate(() => window.getSelection()!.toString());
/** The 「＋」 menu, opened. */
export async function openPlus(page: Page) {
  await thread(page).getByRole("button", { name: "添加上下文", exact: true }).click();
  await expect(thread(page).getByRole("menu", { name: "加进这次提问" })).toBeVisible();
}
/** Choose what the box does (问作品 / 写前回顾 / 查前文矛盾). */
export async function chooseMode(page: Page, label: string) {
  await thread(page).getByRole("button", { name: /^这次做什么：/ }).click();
  await thread(page).getByRole("menuitemradio", { name: label, exact: true }).click();
  await expect(thread(page).getByRole("button", { name: `这次做什么：${label}` })).toBeVisible();
}
export const proposal = (task: Locator, kind: string) => task.locator(`[data-proposal][data-kind="${kind}"]`);

// ── 05b: 写前回顾, 帮我改这一处, 查前文矛盾 ──────────────────────────────────────────────────────────────
// The test model's scripts for these (backend/tests/e2e_app.py): a recap cites the first number of each candidate group;
// a fix proposes an edit (the sentence with its first character replaced by 「（示意改法）」), and an intentional
// way out (E2E_SETUP in the sentence adds a setup for chapter 1); a check of a passage checks it once and cites its first source.
export const SENTENCE = "苏岑拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST。";
export const REWRITTEN = `（示意改法）${SENTENCE.slice(1)}`;
export const chars = (text: string) => text.replace(/\s+/g, "").length;
export const findingsTab = (page: Page) => findings(page).getByRole("tab", { name: /^检查结果/ });
export const adoptRequest = (page: Page, action: string) => page.waitForRequest((request) => request.method() === "POST" && new RegExp(`/proposals/[^/]+/${action}$`).test(request.url()));

/** A work whose latest check is a real one, with one finding on `body` (a sentence with E2E_SUGGEST in it). */
export async function checkedWork(page: Page, body = SENTENCE, charged = false) {
  const id = await setup(page, true, charged);
  await saveBody(page, id, body);
  const result = await finishCheck(page, id, await beginCheck(page, id));
  const issue = result.issues.find((item: any) => item.claim_text.includes("E2E_SUGGEST"));
  expect(issue, JSON.stringify(result.issues)).toBeTruthy();
  return { id, issue };
}
/** Open the finding and hand it to the assistant; resolves with the finished task. */
export async function askForFix(page: Page, issue: { id: string }, label = "让助手给改法") {
  await selectIssue(page, issue);
  const request = taskPost(page);
  await findings(page).getByRole("button", { name: label, exact: true }).click();
  await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
  const body = (await request).postDataJSON();
  await finished(page);
  return { body, task: tasks(page).last() };
}

