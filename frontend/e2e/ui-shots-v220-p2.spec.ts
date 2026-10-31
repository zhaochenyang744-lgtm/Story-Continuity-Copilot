import { mkdir } from "node:fs/promises";
import type { Page } from "@playwright/test";
import { api, createWorkByApi, expect, newPage, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import { box, send, stopButton, thread, topbarAssistant } from "./support/assistant";
import { changeItem, changeView } from "./support/assistant-change";
import { askView, serveTasks } from "./support/assistant-mock";

// Pictures for the v2.2 UI delivery, phase two (task 19): the one assistant dock on the writing page, the materials and overview pages, its empty
// state, a question and its answer, the cards, a stop, the allowance used up; 1440 by day and by night, and 375 by day.
// Taken only when UI_SHOTS2_DIR names a folder (the ordinary run leaves no files).
const dir = process.env.UI_SHOTS2_DIR;
test.skip(!dir, "UI_SHOTS2_DIR is not set");
test.use({ actionTimeout: 15_000 });

const setMood = (page: Page, value: "day" | "night") => page.evaluate((v) => { document.documentElement.dataset.theme = v; }, value);
const hideDevBadge = (page: Page) => page.addStyleTag({ content: "nextjs-portal { display: none !important; }" });

async function take(page: Page, name: string, size: 1440 | 375, options: { fullPage?: boolean; before?: () => Promise<void> } = {}) {
  await mkdir(dir!, { recursive: true });
  await hideDevBadge(page);
  for (const tone of size === 1440 ? (["day", "night"] as const) : (["day"] as const)) {
    await setMood(page, tone);
    if (options.before) await options.before();
    await page.evaluate(async () => { await document.fonts.ready; });
    await page.waitForTimeout(500);
    await page.screenshot({ path: `${dir}/${name}-${size}-${tone === "day" ? "浅色" : "深色"}.png`, fullPage: options.fullPage ?? false, animations: "disabled" });
  }
  await setMood(page, "day");
}
const toEnd = (page: Page) => async () => { await thread(page).locator(".a-thread").evaluate((node) => { node.scrollTop = node.scrollHeight; }); };
const openDock = async (page: Page) => { if (!(await page.locator("#assistant-dock").isVisible())) await topbarAssistant(page).click(); await expect(thread(page)).toBeVisible(); await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur()); };
const closeDock = async (page: Page) => { if (await page.locator("#assistant-dock").isVisible()) await topbarAssistant(page).click(); await expect(page.locator("#assistant-dock")).toBeHidden(); };

const cardItems = () => [
  changeItem({ id: "achange-1", label: "C1", kind: "add_fact", title: "仓道里的旧潮位牌", before: "资料里没有", after: "背板至第 10 章尚未拆开（第 10 章）", editable: true, value: "背板至第 10 章尚未拆开",
    evidence: [{ chapter_number: 10, chapter_title: "第十章 五点四十分", start: 120, end: 150, text: "温岚把罗盘放进抽屉，锁上了。" }] }),
  changeItem({ id: "achange-2", label: "C2", kind: "resolve_thread", title: "廊桥钥匙的指向", before: "已埋设", after: "已回收（第 10 章）", editable: false, value: null }),
];
const decisionItem = () => changeItem({ id: "achange-d1", label: "C1", kind: "add_decision", target: { kind: "decision", id: "decision-mock" }, title: "记下决定·有意为之", before: "还没有这条决定", after: "第 10 章雾钟响一次是有意留下的谜团，之后再解释", editable: false, value: null, evidence: [], request_words: "雾钟那里是我有意留的谜团" });

for (const size of [1440, 375] as const) {
  test(`ui screenshots 2: the assistant dock at ${size}`, async ({ page, browser }) => {
    test.setTimeout(900_000);
    const m = size === 375 ? "M" : "";
    await page.setViewportSize({ width: size, height: size === 375 ? 812 : 900 });
    await registerAccount(page, `dock${size}`);
    const id = await sampleWorkId(page);
    await api(page).post("/onboarding/skip", { confirm: true }).catch(() => undefined);
    let views: unknown[] = [];
    const unserve = await serveTasks(page, () => views);
    const draft = size === 375 ? page.locator("#draft-body") : page.getByRole("textbox", { name: "草稿正文", exact: true });

    // 写作: the dock closed, then open and empty.
    await openTab(page, id, "workspace");
    await expect(draft).toBeVisible();
    await take(page, `${m}01-写作-助手关`, size);
    await openDock(page);
    await take(page, `${m}02-写作-助手开-空状态`, size);

    // A question and its answer.
    views = [askView()];
    await page.reload();
    await expect(draft).toBeVisible();
    await openDock(page);
    await expect(thread(page).locator("[data-task]")).toHaveCount(1);
    await take(page, `${m}03-写作-助手开-一问一答`, size);

    // The findings column: only the check's results, each with 问助手 (at 375 it is the page's other pane).
    await closeDock(page);
    if (size === 375) await page.getByRole("navigation", { name: "切换内容" }).getByRole("button", { name: /^检查结果/ }).click();
    await page.getByTestId(/^finding-/).first().click();
    await page.locator(".finding").nth(1).scrollIntoViewIfNeeded();
    await take(page, `${m}04-写作-检查结果-问助手`, size);

    // The cards.
    views = [changeView(cardItems(), { context: { page: "writing", chapter_number: 11 } })];
    await page.reload();
    await expect(draft).toBeVisible();
    await openDock(page);
    await expect(thread(page).locator("[data-task]")).toHaveCount(1);
    await take(page, `${m}07-改资料卡片`, size, { before: toEnd(page) });
    views = [changeView([decisionItem()], { id: "atask-mock-decision", question: "雾钟那里是我有意留的谜团", answer: { status: "not_found", sentences: [], note: null }, sources: {}, coverage: null })];
    await page.reload();
    await openDock(page);
    await expect(thread(page).locator("[data-task]")).toHaveCount(1);
    await take(page, `${m}08-记下决定卡片`, size, { before: toEnd(page) });

    // 资料 and 概览 with the dock open.
    views = [askView()];
    await openTab(page, id, "memory");
    await openDock(page);
    await expect(thread(page).locator("[data-task]")).toHaveCount(1);
    await take(page, `${m}05-资料-助手开`, size);
    await openTab(page, id, "overview");
    await openDock(page);
    await take(page, `${m}06-概览-助手开`, size);

    // The allowance used up (a registered account with no characters left), the box gives way to one line.
    // (The sample work takes no characters, so this is a work of the author's own.)
    views = [];
    const own = await createWorkByApi(page, { title: "雾港旧事", genre: "悬疑", summary: "" });
    await page.route("**/api/account/usage", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({ response, json: { ...body, data: { ...body.data, check_chars_remaining: 0, check_chars_used: body.data.check_chars_limit } } });
    });
    await openTab(page, own, "overview");
    await openDock(page);
    await take(page, `${m}10-用完后-注册用户`, size);
    await page.unroute("**/api/account/usage");
    const guest = await newPage(browser);
    await guest.setViewportSize({ width: size, height: size === 375 ? 812 : 900 });
    await startVisitor(guest);
    const sample = await sampleWorkId(guest);
    await guest.route("**/api/account/usage", async (route) => {
      const response = await route.fetch();
      const body = await response.json();
      await route.fulfill({ response, json: { ...body, data: { ...body.data, assistant_tasks_remaining: 0 } } });
    });
    await openTab(guest, sample, "overview");
    await openDock(guest);
    await take(guest, `${m}10-用完后-访客`, size);
    await guest.context().close();

    // 停止: a question is asked and stopped while it runs (the test model waits seven seconds for this marker).
    await unserve();
    await openTab(page, id, "overview");
    await openDock(page);
    await box(page).fill("E2E_SLOWER 苏岑知道罗盘被调包了吗？");
    await send(page).click();
    await expect(stopButton(page)).toBeEnabled({ timeout: 10_000 });
    await stopButton(page).click();
    await expect(thread(page).getByText(/已停止/).first()).toBeVisible();
    await take(page, `${m}09-停止后`, size);

    // 1100: the dock lies over the page's right edge.
    if (size === 1440) {
      await page.setViewportSize({ width: 1100, height: 800 });
      await openTab(page, id, "workspace");
      await openDock(page);
      await take(page, "11-写作-1100-助手盖在右边", 1440);
    }
  });
}
