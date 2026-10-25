import type { Page } from "@playwright/test";
import { expect, shot, test } from "./support/app";
import { adoptRequest, ask, askForFix, checkedWork, finished, openAssistantTab, proposal, REWRITTEN, SENTENCE, tasks, thread } from "./support/assistant";
import { readDraftBody, setup } from "./support/writing";

// 07f, motion (chosen 2026-10-15): M1 the proofreading of an adopted change, M2 the counter that rolls when characters are spent, M3 the
// thread from a mark to its source, M4 the process folding by height, M5 the question rising into place. Each is checked at rest (the
// real state is right with or without the show), and with motion reduced nothing moves at all.

const motion = (page: Page) => page.emulateMedia({ reducedMotion: "no-preference" });
const occurrences = (text: string, part: string) => text.split(part).length - 1;
/** Count (from now on) every moment an element matching `selector` is in the page. */
const watch = (page: Page, selector: string, name: string) => page.evaluate(({ selector, name }) => {
  (window as any)[name] = 0;
  const look = () => { if (document.querySelector(selector)) (window as any)[name] += 1; };
  new MutationObserver(look).observe(document.body, { subtree: true, childList: true, attributes: true });
  look();
}, { selector, name });
const seen = (page: Page, name: string) => page.evaluate((key) => (window as any)[key] as number, name);

test.describe("07f 动效", () => {
  test("M1 采用改法的校对：文字先真正换掉；旧字红色划掉折起，新字逐字落下由绿转正文色，整句闪一下，之后临时装饰全部移除；撤销不播放", async ({ page }) => {
    test.setTimeout(150_000);
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    await motion(page);
    const edit = proposal(task, "edit_this");
    await watch(page, "#draft-body .proof-del", "dels");
    await watch(page, "#draft-body .proof-ins", "inses");
    await watch(page, "#draft-body .mark-pulse", "pulses");
    const adopt = adoptRequest(page, "adopt");
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    // The document holds the new sentence at once; the show is only on top of it.
    await expect.poll(() => readDraftBody(page)).toBe(REWRITTEN);
    const old = page.locator("#draft-body .proof-del");
    await expect(old).toHaveText("苏");
    expect(await old.evaluate((node) => getComputedStyle(node).color)).toBe(await page.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-red-text)"; document.body.append(probe); const value = getComputedStyle(probe).color; probe.remove(); return value; }));
    const dropping = page.locator("#draft-body .proof-ins");
    await expect(dropping.first()).toBeAttached();
    // One character at a time, 45 ms apart, once the struck words have folded away.
    const delays = await dropping.evaluateAll((nodes) => nodes.map((node) => parseFloat((node as HTMLElement).style.animationDelay)));
    expect(delays).toEqual([540, 585, 630, 675, 720, 765]);
    expect(await dropping.evaluateAll((nodes) => nodes.map((node) => node.textContent).join(""))).toBe("（示意改法）");
    expect(await dropping.first().evaluate((node) => getComputedStyle(node).animationName)).toBe("proof-drop, proof-settle");
    await shot(page, "07f-M1-proof", false);
    await adopt;
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    // Gone by themselves, after the whole sentence has been ringed once.
    await expect(page.locator("#draft-body .proof-ins, #draft-body .proof-del")).toHaveCount(0, { timeout: 4_000 });
    expect(await seen(page, "pulses")).toBeGreaterThan(0);
    await expect(page.locator("#draft-body .mark-pulse")).toHaveCount(0, { timeout: 4_000 });
    const body = await readDraftBody(page);
    expect(occurrences(body, REWRITTEN)).toBe(1);
    expect(occurrences(body, SENTENCE)).toBe(0);
    // Undo: the old sentence is back at once, with no show.
    const dels = await seen(page, "dels");
    const undo = adoptRequest(page, "undo");
    await edit.getByRole("button", { name: "已采用 · 撤销", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(SENTENCE);
    await undo;
    expect(await seen(page, "dels")).toBe(dels);
    expect(id).toBeTruthy();
  });

  test("M1b 动画进行中按键或点击：装饰立刻移除，文字已经是最终结果、只换了一次", async ({ page }) => {
    test.setTimeout(150_000);
    const { issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    await motion(page);
    const edit = proposal(task, "edit_this");
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect(page.locator("#draft-body .proof-ins").first()).toBeAttached();
    await page.keyboard.press("ArrowLeft");
    await expect(page.locator("#draft-body .proof-ins, #draft-body .proof-del")).toHaveCount(0);
    const body = await readDraftBody(page);
    expect(occurrences(body, REWRITTEN)).toBe(1);
    expect(occurrences(body, SENTENCE)).toBe(0);
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    await expect(page.locator("#draft-body .mark-pulse")).toHaveCount(0);
    // A click elsewhere on the page ends it the same way.
    await edit.getByRole("button", { name: "已采用 · 撤销", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(SENTENCE);
    await edit.getByRole("button", { name: "采用", exact: true }).click({ timeout: 30_000 });
    await expect(page.locator("#draft-body .proof-ins").first()).toBeAttached();
    await page.getByRole("heading", { level: 1 }).click({ force: true });
    await expect(page.locator("#draft-body .proof-ins, #draft-body .proof-del")).toHaveCount(0);
    expect(occurrences(await readDraftBody(page), REWRITTEN)).toBe(1);
  });

  test("M1c 减少动态效果：采用时没有任何临时装饰，文字直接是新句", async ({ page }) => {
    test.setTimeout(150_000);
    const { issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    await watch(page, "#draft-body .proof-del, #draft-body .proof-ins, #draft-body .mark-pulse, #draft-body .rewrite-fresh", "marks");
    const edit = proposal(task, "edit_this");
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(REWRITTEN);
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    expect(await seen(page, "marks")).toBe(0);
  });

  test("M2 扣字数的数字滚动：任务结束计了字，顶栏「可检查 N 字」只滚动变了的位，回答底部的「计 500 字」随后淡入；失败退字也滚动；减少动态效果时直接是新值", async ({ page }) => {
    await setup(page, true, true);
    await openAssistantTab(page);
    const figure = page.locator(".topbar-quota .odo");
    const value = async () => Number((await figure.getAttribute("aria-label"))!.replace(/\D/g, ""));
    const start = await value();
    // Reduced motion (the default here): the new value, nothing rolling.
    await watch(page, ".topbar-quota .odo-col.roll", "rolls");
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    await expect.poll(value).toBe(start - 500);
    expect(await seen(page, "rolls")).toBe(0);
    // With motion: the digits that changed roll, and the cost line comes in after.
    await motion(page);
    await watch(page, ".topbar-quota .odo-col.roll", "rolls2");
    await ask(page, "E2E_TWO 温岚是谁？");
    await finished(page, 2);
    await expect.poll(value).toBe(start - 1000);
    expect(await seen(page, "rolls2")).toBeGreaterThan(0);
    await expect(page.locator(".topbar-quota .odo-col.roll")).toHaveCount(0, { timeout: 3_000 });
    const rest = tasks(page).nth(1).locator(".a-rest.a-fade");
    expect(await rest.locator(".a-cost-line").evaluate((node) => getComputedStyle(node).animationName)).toBe("fade-in");
    await expect(tasks(page).nth(1).locator(".a-cost-line")).toHaveText("计 500 字");
    // A task that fails gives the characters back: the figure is where it was (it is read again only when the task is over, so nothing
    // was taken from it on the way and there is nothing to roll back).
    await ask(page, "E2E_FAIL 苏岑是谁？");
    await finished(page, 1, "failed");
    await expect.poll(value).toBe(start - 1000);
  });

  test("M3 鼠标悬停或聚焦角标：下面出处列表里对应那一条的引文画出蓝色下划线（从左到右），离开时收回", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await motion(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    await task.getByRole("button", { name: /^出处 \d+ 处/ }).click();
    const line = task.locator(".a-sources .a-source").first();
    // A source is one line until it is opened to its words; the underline is drawn under those.
    await line.locator(".a-where").click();
    const quote = line.locator(".q");
    const size = () => quote.evaluate((node) => getComputedStyle(node).backgroundSize);
    expect(await size()).toBe("0% 1.5px");
    expect(await quote.evaluate((node) => getComputedStyle(node).transitionDuration)).toBe("0.28s");
    await task.locator(".a-cite button").first().hover();
    await expect(line).toHaveClass(/lit/);
    await expect.poll(size).toBe("100% 1.5px");
    await page.mouse.move(2, 2);
    await expect.poll(size, { timeout: 3_000 }).toBe("0% 1.5px");
    await expect(line).not.toHaveClass(/lit/);
    // The keyboard does the same.
    await task.locator(".a-cite button").first().focus();
    await expect.poll(size).toBe("100% 1.5px");
    await shot(page, "07f-M3-thread", false);
    await page.keyboard.press("Escape");
    await expect.poll(size).toBe("0% 1.5px");
  });

  test("M4 过程收起：跑完自动折叠时按高度收起并淡出，「查了 N 处 · M 秒」的两个数字依次落位；手动展开 / 收起也按高度，数字不再重播", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await motion(page);
    await watch(page, ".a-proc-wrap.folding", "folds");
    await ask(page, "E2E_SLOW 苏岑知道罗盘被调包了吗？");
    await expect(tasks(page).first().locator(".a-proc-wrap")).toBeVisible();
    await finished(page);
    const task = tasks(page).first();
    expect(await seen(page, "folds")).toBeGreaterThan(0);
    await expect(task.locator(".a-proc-wrap")).toHaveCount(0, { timeout: 3_000 });
    const figures = task.locator(".a-fold .a-drop");
    await expect(figures).toHaveCount(2);
    expect(await figures.evaluateAll((nodes) => nodes.map((node) => getComputedStyle(node).animationDelay))).toEqual(["0s", "0.08s"]);
    expect(await figures.first().evaluate((node) => getComputedStyle(node).animationName)).toBe("a-drop-in");
    await expect(task.getByRole("button", { name: /查了 \d+ 处 · \d+ 秒/ })).toBeVisible();
    // Opening and closing by hand: the same height change, and the figures stay as they are.
    await task.getByRole("button", { name: /查了 \d+ 处/ }).click();
    await expect(task.locator(".a-proc-wrap")).toBeVisible();
    await expect(task.locator(".a-proc-wrap")).toHaveClass(/unfolding/);
    await expect(task.locator(".a-fold .a-drop")).toHaveCount(0);
    await watch(page, ".a-proc-wrap.folding", "folds2");
    await task.getByRole("button", { name: /查了 \d+ 处/ }).click();
    await expect(task.locator(".a-proc-wrap")).toHaveCount(0, { timeout: 3_000 });
    expect(await seen(page, "folds2")).toBeGreaterThan(0);
    // A conversation read from the server again is simply folded, with nothing to settle.
    await page.reload();
    await openAssistantTab(page);
    await expect(tasks(page).first().locator(".a-fold")).toBeVisible();
    await expect(tasks(page).first().locator(".a-drop, .a-proc-wrap")).toHaveCount(0);
  });

  test("M5 问题发出去：作者的问题气泡从下方升起并淡入（0.34 秒），输入框同时清空；点建议问题、改问题重发同样；刷新后读出来的旧问题不动", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await motion(page);
    await box_(page).fill("苏岑知道罗盘被调包了吗？");
    const asking = page.waitForRequest((r) => r.method() === "POST" && /\/assistant\/tasks$/.test(r.url()));
    await thread(page).getByRole("button", { name: "发送", exact: true }).click();
    await asking;
    await expect(box_(page)).toHaveValue("");
    const bubble = tasks(page).first().locator(".a-ask.rise");
    await expect(bubble).toHaveCount(1);
    expect(await bubble.evaluate((node) => getComputedStyle(node).animationName)).toBe("a-rise");
    expect(await bubble.evaluate((node) => getComputedStyle(node).animationDuration)).toBe("0.34s");
    await finished(page);
    await expect(tasks(page).first().locator(".a-ask")).toContainText("苏岑知道罗盘被调包了吗？");
    // Reworded and sent again: the new question rises too.
    const first = tasks(page).first();
    await first.locator(".a-ask").hover();
    await first.getByRole("button", { name: "修改这个问题" }).click();
    await first.getByRole("textbox", { name: "修改问题" }).fill("苏岑后来知道了吗？");
    await first.getByRole("button", { name: /^重新发送/ }).click();
    await finished(page, 2);
    await expect(tasks(page).last().locator(".a-ask.rise")).toHaveCount(1);
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).locator(".a-ask.rise")).toHaveCount(0);
    // Reduced motion: no animation at all.
    await page.emulateMedia({ reducedMotion: "reduce" });
    await ask(page, "温岚是谁？");
    expect(await tasks(page).last().locator(".a-ask.rise").evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
  });
});

const box_ = (page: Page) => thread(page).getByRole("textbox", { name: "向助手提问", exact: true });
