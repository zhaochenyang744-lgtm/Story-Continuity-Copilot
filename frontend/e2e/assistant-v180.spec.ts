import type { Page } from "@playwright/test";
import { api, expect, newPage, openTab, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";
import {
  adoptRequest, allowance, ask, askForFix, box, checkedWork, chip, chooseMode, finished, openAssistantTab, openPlus, proposal, REWRITTEN, select, selectedWords,
  send, SENTENCE, stopButton, taskPost, tasks, thread, toolbar, topbarAssistant,
} from "./support/assistant";
import { askView, fixView, proposalView, runningView, serveTasks } from "./support/assistant-mock";
import { findings, readDraftBody, setup } from "./support/writing";

// The assistant's second round (v1.8.0, 07c): how it tells what it does, the answer's card and row of actions, a change as words,
// the box the author writes in, asking again, and the switch that decides who sees any of it. States a real run cannot hold
// still (a step in progress, a task cut short) are served by hand; everything the page sends goes to the real test server.

const bodyOf = (request: { postDataJSON: () => any }) => request.postDataJSON();
const putFeedback = (page: Page) => page.waitForRequest((request) => request.method() === "PUT" && /\/feedback$/.test(request.url()));
const deleteFeedback = (page: Page) => page.waitForRequest((request) => request.method() === "DELETE" && /\/feedback$/.test(request.url()));
const setRollout = (page: Page, mode: string) => api(page).post(`/test/v180/assistant-rollout/${mode}`);
const column = (page: Page) => thread(page).locator(".a-thread");

test.describe("助手：过程", () => {
  test("说明句和动作合成一行；没有「第几轮」；跑完折成「查了 N 处 · M 秒」，点开看到每一步和找到的片段", async ({ page }) => {
    await setup(page);
    await serveTasks(page, () => [askView()]);
    await page.reload();
    await openAssistantTab(page);
    const task = tasks(page).first();
    // Folded: how many places, how long (completed_at − started_at), and the first line it said.
    const fold = task.getByRole("button", { name: /^查了 6 处 · 14 秒/ });
    await expect(fold).toHaveAttribute("aria-expanded", "false");
    await expect(fold).toContainText("先查苏岑和罗盘的已确认事实");
    await expect(task.locator(".a-say")).toHaveCount(0);
    await fold.click();
    await expect(fold).toHaveAttribute("aria-expanded", "true");
    // The model's lines read as ordinary sentences; the actions of one kind under a line are one row, worded here from the tool and the count.
    await expect(task.locator(".a-say")).toHaveText(["先查苏岑和罗盘的已确认事实。", "再看罗盘在第 9、10 章经过了谁的手。", "最后对一下草稿里写的。"]);
    await expect(task.locator(".a-act")).toHaveText([/^查了 2 条事实：苏岑、黄铜罗盘/, /^搜了 2 处正文.*3 段$/, /^读了第 10 章$/, /^读了本章草稿$/]);
    await expect(task.locator(".a-steps")).not.toContainText(/第 \d+ 轮|共 \d+ 轮|\d+ 步/);
    // A row with passages opens: where each comes from and what it says; the ones the answer did not use are marked and fainter.
    await task.getByRole("button", { name: /^搜了 2 处正文/ }).click();
    const found = task.locator(".a-found p");
    await expect(found).toHaveCount(3);
    await expect(found.nth(0)).toContainText("第 9 章 · 仓道的高台");
    await expect(found.nth(0)).toContainText("苏岑把罗盘交给温岚");
    await expect(found.nth(0)).not.toContainText("没有引用");
    await expect(found.nth(2)).toContainText("没有引用");
    await expect(found.nth(2)).toHaveClass(/unused/);
    expect(await found.nth(2).evaluate((node) => getComputedStyle(node).color)).not.toBe(await found.nth(0).evaluate((node) => getComputedStyle(node).color));
  });

  test("失败的步骤单独一行（✕ 和原因），修正显示成一句话，协议提醒不显示", async ({ page }) => {
    await setup(page);
    const step = (over: Record<string, unknown>) => ({ round: 1, kind: "tool", tool: "propose_edit", summary: "提出改法", result_count: null, group: "g1-propose_edit", refs: [], error_code: null, error_text: null, ...over });
    await serveTasks(page, () => [askView({
      steps: [
        step({ kind: "say", tool: null, summary: "按第 10 章的写法给两种改法。", group: null }),
        step({ error_code: "proposal_before_not_unique", error_text: "原句在草稿里出现了不止一次" }),
        step({ round: 2, group: "g2-propose_edit" }),
        step({ round: 2, group: "g2-propose_edit" }),
        step({ round: 3, kind: "repair", tool: null, summary: "回答的引用有误，让助手重新回答", group: null, error_code: "citation_validation_failed", error_text: "引用没对上，重新整理回答" }),
        step({ round: 3, kind: "protocol_error", tool: null, summary: "助手没有调用工具，已提醒它查询或回答", group: null, error_code: "assistant_protocol_error", error_text: "这一步没成功" }),
      ],
    })]);
    await page.reload();
    await openAssistantTab(page);
    const task = tasks(page).first();
    await task.getByRole("button", { name: /^查了 2 处/ }).click();
    await expect(task.locator(".a-act.bad")).toHaveText("提出改法没通过：原句在草稿里出现了不止一次");
    expect(await task.locator(".a-act.bad .mk").evaluate((node) => getComputedStyle(node, "::before").content)).toBe('"✕"');
    await expect(task.locator(".a-act.ok")).toHaveText(["提出了 2 个改法", "引用没对上，重新整理回答"]);
    expect(await task.locator(".a-act.ok .mk").first().evaluate((node) => getComputedStyle(node, "::before").content)).toBe('"✓"');
    await expect(task.locator(".a-steps")).not.toContainText(/没有调用工具|这一步没成功/);
  });

  test("真实的运行：读不到的章、重新整理回答、查到上限都如实写出", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    // A chapter that is not there: its step fails on its own line with the reason, beside the one that went through.
    await ask(page, "E2E_BADREAD 苏岑是谁？");
    await finished(page);
    let task = tasks(page).first();
    await task.getByRole("button", { name: /^查了 \d+ 处/ }).click();
    await expect(task.locator(".a-act.bad")).toHaveText("读第 999 章没通过：这一章不在可查范围内");
    await expect(task.locator(".a-act.ok").first()).toContainText("查了 1 条事实：苏岑");
    // An answer whose citation did not match is written again: one line says so, and the answer that follows is fine.
    await ask(page, "E2E_REPAIR 温岚是谁？");
    await finished(page, 2);
    task = tasks(page).last();
    await task.getByRole("button", { name: /^查了 \d+ 处/ }).click();
    await expect(task.locator(".a-act.ok").filter({ hasText: "引用没对上，重新整理回答" })).toHaveCount(1);
    await expect(task.getByText("（示意回答）前文写过这件事。")).toBeVisible();
    // Cut short by the limit: a line above the answer says so, and 查过 / 没查 does not repeat it.
    await ask(page, "E2E_LIMIT 黎舟是谁？");
    await finished(page, 3);
    task = tasks(page).last();
    await expect(task.getByText("查到上限了，先按已找到的回答。", { exact: true })).toBeVisible();
    const [limit, answer] = [await task.locator(".a-limit").boundingBox(), await task.locator(".a-answer").boundingBox()];
    expect(limit!.y).toBeLessThan(answer!.y);
    await expect(task).not.toContainText("步数或预算已到");
  });

  test("进行中：照 phase 写正在做的事，满 3 秒才显示秒数，前面是三格动画；已完成的行是 ✓", async ({ page }) => {
    await setup(page);
    // The step began a moment from now, so the seconds count from zero and show once they reach three.
    const began = Date.now() + 1500;
    await serveTasks(page, () => [runningView("tool", { phase_started_at: new Date(began).toISOString() })]);
    await page.reload();
    await openAssistantTab(page);
    const task = tasks(page).first();
    const now = task.locator(".a-act.now");
    await expect(now).toContainText("正在读第 10 章");
    await expect(now.locator(".secs")).toHaveText("");
    await expect(now.locator(".secs")).toHaveText(/^[3-9] 秒$/, { timeout: 12_000 });
    // The done line is a ✓ line; the line in progress carries three squares that step along (still when motion is reduced).
    await expect(task.locator(".a-say")).toHaveText("先查苏岑和罗盘的已确认事实。");
    expect(await task.locator(".a-act.ok .mk").first().evaluate((node) => getComputedStyle(node, "::before").content)).toBe('"✓"');
    await expect(now.locator(".a-three i")).toHaveCount(3);
    expect(await now.locator(".a-three i").first().evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
    await page.emulateMedia({ reducedMotion: "no-preference" });
    expect(await now.locator(".a-three i").first().evaluate((node) => getComputedStyle(node).animationName)).toBe("a-step");
    expect(await now.locator(".a-three i").nth(2).evaluate((node) => getComputedStyle(node).animationDelay)).toBe("0.7s");
  });

  test("等模型回复时写「正在想下一步」；作者打开过的折叠保持打开", async ({ page }) => {
    await setup(page);
    const unserve = await serveTasks(page, () => [runningView("thinking")]);
    await page.reload();
    await openAssistantTab(page);
    await expect(tasks(page).first().locator(".a-act.now")).toContainText("正在想下一步");
    await unserve();
    await page.reload();
    await openAssistantTab(page);
    // A real one: after it ends the process folds; once the author opens it, it stays open while another question runs.
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const first = tasks(page).first();
    const fold = first.getByRole("button", { name: /^查了 \d+ 处/ });
    await expect(fold).toHaveAttribute("aria-expanded", "false");
    await fold.click();
    await ask(page, "E2E_SLOW 温岚是谁？");
    await expect(tasks(page).nth(1)).toHaveAttribute("data-status", /^(queued|running)$/);
    await expect(fold).toHaveAttribute("aria-expanded", "true");
    await finished(page, 2);
    await expect(fold).toHaveAttribute("aria-expanded", "true");
  });
});

test.describe("助手：回答", () => {
  test("校验通过后逐句淡入（句间隔 0.12 秒）；减少动态效果时直接显示；刷新后读出来的旧回答不再淡入", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await ask(page, "E2E_TWO 苏岑知道罗盘被调包了吗？");
    await finished(page);
    const sentences = tasks(page).first().locator(".a-answer.a-fade .a-s");
    await expect(sentences).toHaveCount(2);
    expect(await sentences.nth(0).evaluate((node) => getComputedStyle(node).animationName)).toBe("a-appear");
    expect(await sentences.nth(0).evaluate((node) => getComputedStyle(node).animationDelay)).toBe("0s");
    expect(await sentences.nth(1).evaluate((node) => getComputedStyle(node).animationDelay)).toBe("0.12s");
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await sentences.nth(1).evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
    await page.reload();
    await openAssistantTab(page);
    await expect(tasks(page).first().locator(".a-answer .a-s")).toHaveCount(2);
    await expect(tasks(page).first().locator(".a-answer.a-fade")).toHaveCount(0);
  });

  test("引用角标：悬停或聚焦弹出章节名、引文和「去原文」；离开 300 毫秒后收起；Esc 收起", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const cite = task.locator(".a-cite button").first();
    const card = task.locator(".a-pop");
    await expect(card).toHaveCount(0);
    await cite.hover();
    await expect(card).toBeVisible();
    await expect(cite).toHaveAttribute("aria-expanded", "true");
    await expect(card.locator(".w")).toHaveText(/^(事实摘要 · )?第 \d+ 章/);
    await expect(card.locator("q")).not.toHaveText("");
    await expect(card.getByRole("button", { name: "去原文 →" })).toBeVisible();
    // It does not go the moment the pointer leaves (so the pointer can get into it), and it goes soon after.
    await page.mouse.move(2, 2);
    await expect(card).toBeVisible();
    await expect(card).toHaveCount(0, { timeout: 3_000 });
    // The pointer can move into the card and stay.
    await cite.hover();
    await card.hover();
    await page.waitForTimeout(700);
    await expect(card).toBeVisible();
    await page.mouse.move(2, 2);
    await expect(card).toHaveCount(0, { timeout: 3_000 });
    // The keyboard: focus opens it, Escape closes it and leaves focus on the mark.
    await cite.focus();
    await expect(card).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(card).toHaveCount(0);
    await expect(cite).toBeFocused();
    await expect(thread(page)).toBeVisible();
  });

  test("手机上点按角标弹出卡片，再点一下收起；点卡片里的「去原文」", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "touch");
    const id = await sampleWorkId(phone);
    await openTab(phone, id, "workspace");
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await ask(phone, "E2E_PASSAGE 苏岑知道罗盘被调包了吗？");
    await finished(phone);
    const task = tasks(phone).first();
    const cite = task.locator(".a-cite button").first();
    const card = task.locator(".a-pop");
    await cite.tap();
    await expect(card).toBeVisible();
    // The browser's mouse-over / mouse-out after a tap must not shut it again (it did, after about a third of a second).
    await phone.waitForTimeout(1000);
    await expect(card).toBeVisible();
    await expect(card.getByRole("button", { name: "去原文 →" })).toBeVisible();
    await cite.tap();
    await expect(card).toHaveCount(0);
    await cite.tap();
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "去原文 →" }).tap();
    await expect(phone).toHaveURL(/\/workspace\?chapter=\d+$/);
    await context.close();
  });

  test("去原文：打开那一章，把那一句找出来，闪一下蓝色", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await page.emulateMedia({ reducedMotion: "no-preference" });
    await ask(page, "E2E_PASSAGE 苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const cite = task.locator(".a-cite button").first();
    const number = Number((await cite.getAttribute("aria-label"))!.match(/第 (\d+) 章/)![1]);
    await cite.hover();
    await task.getByRole("button", { name: "去原文 →" }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=${number}$`));
    await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^第 ${number} 章`) })).toBeAttached();
    const ring = page.locator("#chapter-body .mark-pulse");
    await expect(ring).toBeAttached({ timeout: 6_000 });
    await expect(ring.first()).toBeInViewport();
  });

  test("复制：默认带出处，按住 Shift 只复制正文，复制后显示「已复制」；剪贴板不能用时选中文字", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const sentence = "（示意回答）前文写过这件事。";
    const where = (await task.locator(".a-source .a-where").first().innerText()).trim();
    const copy = task.locator(".a-foot > .a-link").first();
    await copy.click();
    await expect(copy).toHaveText("已复制");
    expect((await page.evaluate(() => navigator.clipboard.readText())).replace(/\r\n/g, "\n")).toBe(`${sentence}[1]\n\n[1] ${where}`);
    await expect(copy).toHaveText("复制", { timeout: 4_000 });
    await copy.click({ modifiers: ["Shift"] });
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(sentence);
    // No clipboard: the answer is left selected, and the button says so.
    await page.evaluate(() => { Object.defineProperty(navigator.clipboard, "writeText", { configurable: true, value: () => Promise.reject(new Error("blocked")) }); });
    await page.evaluate(() => window.getSelection()?.removeAllRanges());
    await expect(copy).toHaveText("复制", { timeout: 4_000 });
    await copy.click();
    await expect(copy).toHaveText("已选中，按 Ctrl+C 复制");
    expect(await selectedWords(page)).toContain(sentence);
  });

  test("重新回答：只对已完成的问答，标「约 500 字」；新回答放在原位，旧的折进「之前的回答」", async ({ page }) => {
    const id = await setup(page, true, true);
    await openAssistantTab(page);
    const before = await allowance(page);
    await ask(page, "E2E_FAIL 苏岑是谁？");
    await finished(page, 1, "failed");
    await expect(tasks(page).first().getByRole("button", { name: "重新回答" })).toHaveCount(0);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const first = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[1];
    const task = tasks(page).last();
    const again = task.getByRole("button", { name: "重新回答", exact: true });
    await expect(again).toBeVisible();
    await expect(task.locator(".a-regen .a-hint")).toHaveText("约 500 字");
    const response = page.waitForRequest((request) => request.method() === "POST" && new RegExp(`/assistant/tasks/${first.id}/regenerate$`).test(request.url()));
    await again.click();
    await response;
    await expect.poll(async () => (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks.length).toBe(3);
    // Two entries still (the failed one and this question); the new answer is where the old one was, the old one is folded.
    const saved = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks;
    expect(saved[2].regenerated_from).toBe(first.id);
    const entry = tasks(page).last();
    await expect(entry).toHaveAttribute("data-task", saved[2].id);
    await expect(entry).toHaveAttribute("data-status", "completed", { timeout: 20_000 });
    await expect(tasks(page)).toHaveCount(2);
    await expect(entry.locator("details.a-older > summary")).toHaveText("之前的回答 · 1");
    expect(await entry.locator("details.a-older").evaluate((node: HTMLDetailsElement) => node.open)).toBe(false);
    await entry.locator("details.a-older > summary").click();
    await expect(entry.locator("details.a-older").getByText("（示意回答）前文写过这件事。")).toBeVisible();
    // Charged like a new question each time (the failed one was handed back).
    await expect.poll(() => allowance(page)).toBe(before - 1000);
  });

  test("有用 / 没用：小图标、没用时选原因、选完一秒后收起并显示「已记下」、再点一次撤回", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const up = task.getByRole("button", { name: "有用", exact: true });
    const down = task.getByRole("button", { name: "没用", exact: true });
    await expect(up).toHaveAttribute("aria-pressed", "false");
    let request = putFeedback(page);
    await up.click();
    expect(bodyOf(await request)).toEqual({ verdict: "up" });
    await expect(up).toHaveAttribute("aria-pressed", "true");
    // Pressing it again takes it back.
    const gone = deleteFeedback(page);
    await up.click();
    await gone;
    await expect(up).toHaveAttribute("aria-pressed", "false");
    expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].feedback).toBeNull();
    // 没用: four reasons, any of them; a second after the last choice they fold away and 「已记下」 shows.
    request = putFeedback(page);
    await down.click();
    expect(bodyOf(await request)).toEqual({ verdict: "down", reasons: [] });
    const reasons = task.getByRole("group", { name: "哪里不好" });
    await expect(reasons.getByRole("button")).toHaveText(["不对", "啰嗦", "没找到", "出处不准"]);
    const saved = putFeedback(page);
    await reasons.getByRole("button", { name: "啰嗦", exact: true }).click();
    await reasons.getByRole("button", { name: "出处不准", exact: true }).click();
    await expect(reasons.getByRole("button", { name: "出处不准", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(bodyOf(await saved)).toEqual({ verdict: "down", reasons: ["verbose", "bad_source"] });
    await expect(reasons).toHaveCount(0);
    await expect(task.getByText("已记下，谢谢。")).toBeVisible();
    expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].feedback).toEqual({ verdict: "down", reasons: ["verbose", "bad_source"] });
    // It is still there after a reload, and can be withdrawn.
    await page.reload();
    await openAssistantTab(page);
    await expect(tasks(page).first().getByRole("button", { name: "没用", exact: true })).toHaveAttribute("aria-pressed", "true");
    const withdrawn = deleteFeedback(page);
    await tasks(page).first().getByRole("button", { name: "没用", exact: true }).click();
    await withdrawn;
    await expect(tasks(page).first().getByRole("button", { name: "没用", exact: true })).toHaveAttribute("aria-pressed", "false");
  });

  test("作品以外：浅底的固定文案，不显示出处和「接着问」，计费同找不到", async ({ page }) => {
    await setup(page, true, true);
    await openAssistantTab(page);
    const before = await allowance(page);
    await ask(page, "E2E_OFF 帮我写一首关于海港的诗");
    await finished(page);
    const task = tasks(page).first();
    await expect(task.getByText("我只能查这部作品里写过的内容，可以换个关于作品的问题。", { exact: true })).toBeVisible();
    await expect(task.locator(".a-fixed")).toBeVisible();
    await expect(task.locator(".a-cite, .a-sources, .a-cover, .a-answer-note")).toHaveCount(0);
    await expect(task.getByRole("button", { name: "接着问", exact: true })).toHaveCount(0);
    // The reply would be the same fixed words again: asking again is not offered.
    await expect(task.getByRole("button", { name: "重新回答", exact: true })).toHaveCount(0);
    await expect(task).toContainText("计 500 字");
    await expect.poll(() => allowance(page)).toBe(before - 500);
    expect(await task.locator(".a-fixed").evaluate((node) => getComputedStyle(node).backgroundColor)).not.toBe("rgba(0, 0, 0, 0)");
  });
});

test.describe("助手：改法", () => {
  test("只标出改的字：连续的改动合成一段；改动过半时退回整句对照", async ({ page }) => {
    await setup(page);
    await serveTasks(page, () => [fixView([
      proposalView(),
      proposalView({ id: "aprop-mock-2", proposal: "P2", before: "甲乙丙丁戊己庚辛壬癸。", after: "完全不同的另一句话。" }),
      proposalView({ id: "aprop-mock-3", proposal: "P3", before: "她把温水递给了他。", after: "她把冰水递给了他。" }),
    ])]);
    await page.reload();
    await openAssistantTab(page);
    const [long, whole, small] = ["P1", "P2", "P3"].map((name) => tasks(page).first().locator(`[data-proposal="${name}"]`));
    // The design's own sentence: three stretches go (装, ，而, 同一枚罗盘), two come (空, ，); everything else is left alone.
    await expect(long.locator("del")).toHaveText(["删去：装", "删去：，而", "删去：同一枚罗盘"]);
    await expect(long.locator("ins")).toHaveText(["改为：空", "改为：，"]);
    await expect(long.locator(".a-diff")).not.toHaveClass(/whole/);
    await expect(small.locator("del")).toHaveText("删去：温");
    await expect(small.locator("ins")).toHaveText("改为：冰");
    // Most of it changed: the whole old sentence struck and the whole new one added, instead of confetti.
    await expect(whole.locator(".a-diff")).toHaveClass(/whole/);
    await expect(whole.locator("del")).toHaveText("删去：甲乙丙丁戊己庚辛壬癸。");
    await expect(whole.locator("ins")).toHaveText("改为：完全不同的另一句话。");
    // The two whole sentences are in a fold.
    await expect(long.locator(".a-whole-body")).toHaveCount(0);
    await long.getByRole("button", { name: /^整句对照/ }).click();
    await expect(long.locator(".a-whole-body .b")).toContainText("而此刻同一枚罗盘仍握在温岚手中");
    await expect(long.locator(".a-whole-body .f")).toContainText("此刻仍握在温岚手中");
  });

  test("改一改：新句变成可编辑的框，边改边重算差异，标「已手改」；采用时把作者的句子传给 adopt，撤销换回原句", async ({ page }) => {
    test.setTimeout(150_000);
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    const edited = `（改了）${SENTENCE.slice(1)}`;
    await expect(edit.locator(".a-edited")).toHaveCount(0);
    await edit.getByRole("button", { name: "改一改", exact: true }).click();
    const area = edit.getByRole("textbox", { name: "改后的句子" });
    await expect(area).toHaveValue(REWRITTEN);
    await area.fill(edited);
    // The difference is worked out again as the words change; the sentence is marked as reworded.
    await expect(edit.locator("ins")).toHaveText("改为：（改了）");
    await expect(edit.locator(".a-edited")).toHaveText("已手改");
    await expect(edit.getByRole("button", { name: "改好了", exact: true })).toBeVisible();
    await edit.getByRole("button", { name: "改好了", exact: true }).click();
    await expect(area).toHaveCount(0);
    await expect(edit.locator("ins")).toHaveText("改为：（改了）");
    // Adopting puts the author's sentence in the draft and sends it to the server as `after`.
    const adopt = adoptRequest(page, "adopt");
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(edited);
    const sent = await adopt;
    expect(bodyOf(sent)).toMatchObject({ after: edited });
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    const saved = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((p: any) => p.kind === "edit_this");
    expect(saved).toMatchObject({ status: "adopted", after: REWRITTEN, after_edited: edited, edited_by_author: true });
    await expect(edit.locator(".a-edited")).toHaveText("已手改");
    // Undo swaps the author's sentence, not the assistant's, back for the old one.
    const undo = adoptRequest(page, "undo");
    await edit.getByRole("button", { name: "已采用 · 撤销", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(SENTENCE);
    await undo;
    await expect(edit.getByRole("button", { name: "采用", exact: true })).toBeEnabled({ timeout: 30_000 });
    const after = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((p: any) => p.kind === "edit_this");
    expect(after).toMatchObject({ status: "proposed", after_edited: null, edited_by_author: false });
  });

  test("改后的句子不合格：采用前就说明；服务器拒绝时就地写出人话，作者改的字还在，可以把原句改回草稿", async ({ page }) => {
    test.setTimeout(150_000);
    const { issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    await edit.getByRole("button", { name: "改一改", exact: true }).click();
    const area = edit.getByRole("textbox", { name: "改后的句子" });
    // Still holding the old sentence: refused before it touches the draft.
    await area.fill(`先说一句，${SENTENCE}`);
    await expect(edit.getByRole("alert")).toHaveText("改后的句子里原样留着原句，请把原句改掉。");
    await expect(edit.getByRole("button", { name: "采用", exact: true })).toBeDisabled();
    await area.fill("");
    await expect(edit.getByRole("alert")).toHaveText("改后的句子不能为空。");
    await area.fill(SENTENCE);
    await expect(edit.getByRole("alert")).toHaveText("和原句一样，还没有改动。");
    expect(await readDraftBody(page)).toBe(SENTENCE);
    // The server may still refuse one (a sentence it will not keep). Its code becomes words, the box keeps what was typed, and the draft can be put back.
    const mine = `（再改）${SENTENCE.slice(1)}`;
    await area.fill(mine);
    await page.route("**/proposals/*/adopt", (route) => route.fulfill({ status: 422, contentType: "application/json", body: JSON.stringify({ error: { code: "proposal_text_internal_id", message: "x", retryable: false } }) }));
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect(edit.getByRole("alert")).toContainText("改后的句子里有不能出现的内部编号，请删掉。");
    await expect(area).toHaveValue(mine);
    await expect(edit.locator("ins")).toHaveText("改为：（再改）");
    await edit.getByRole("button", { name: "把原句改回草稿", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(SENTENCE);
    await expect(area).toHaveValue(mine);
  });

  test("补前文：可以先改一改再复制；复制的是作者改过的句子", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const { issue } = await checkedWork(page, `${SENTENCE.replace("。", "，")}E2E_SETUP。`);
    const { task } = await askForFix(page, issue);
    const setupWay = proposal(task, "add_setup");
    await setupWay.getByRole("button", { name: "改一改", exact: true }).click();
    await setupWay.getByRole("textbox", { name: "改后的句子" }).fill("（我改的）前文补这一句。");
    await expect(setupWay.locator("ins")).toContainText("（我改的）前文补这一句。");
    await expect(setupWay.locator(".a-edited")).toHaveText("已手改");
    await setupWay.getByRole("button", { name: "复制这句，去第 1 章", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("（我改的）前文补这一句。");
    await expect(page).toHaveURL(/\/workspace\?chapter=1$/);
  });
});

test.describe("助手：输入框", () => {
  test("标签在框内顶部、各自可去掉、选中的原文用宋体；文字区两行高、最多六行；框下固定一行小字", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await select(page, "#draft-body", 14);
    await toolbar(page).getByRole("button", { name: /^问助手/ }).click();
    const frame = thread(page).locator("form.cx");
    const picked = frame.locator(".a-chip.quote");
    await expect(picked).toBeVisible();
    const [chipBox, areaBox] = [await picked.boundingBox(), await box(page).boundingBox()];
    expect(chipBox!.y).toBeLessThan(areaBox!.y);
    expect(await picked.evaluate((node) => getComputedStyle(node).fontFamily)).toContain("Noto Serif");
    // Two lines high when empty; it grows with what is written to six lines, and then scrolls inside.
    expect(areaBox!.height).toBeGreaterThanOrEqual(42);
    expect(areaBox!.height).toBeLessThanOrEqual(50);
    await box(page).fill(Array.from({ length: 12 }, (_, index) => `第${index + 1}行`).join("\n"));
    const tall = await box(page).evaluate((node) => ({ height: node.getBoundingClientRect().height, scrolls: node.scrollHeight > node.clientHeight }));
    expect(tall.height).toBeGreaterThan(120);
    expect(tall.height).toBeLessThanOrEqual(140);
    expect(tall.scrolls).toBe(true);
    await picked.getByRole("button", { name: /^去掉：选中：/ }).click();
    await expect(picked).toHaveCount(0);
    await expect(thread(page).getByText("回答由 AI 生成，可能出错，请点出处核对。", { exact: true })).toBeVisible();
  });

  test("「＋」菜单：某一章、某个人物、某条检查结果、在正文里选一段；选中后变成标签，进请求", async ({ page }) => {
    const { id, issue } = await checkedWork(page);
    const [character] = (await api(page).get(`/projects/${id}/characters`)).characters;
    await openAssistantTab(page);
    await openPlus(page);
    const menu = thread(page).getByRole("menu", { name: "加进这次提问" });
    await expect(menu.getByRole("menuitem")).toHaveText([/^某一章/, /^某个人物/, /^某条检查结果/, /^在正文里选一段/]);
    // 某一章 → the chapters → a tag.
    await menu.getByRole("menuitem", { name: /^某一章/ }).click();
    await menu.getByRole("menuitem", { name: /^第 3 章/ }).click();
    await expect(chip(page, "第 3 章")).toBeVisible();
    // 某个人物.
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^某个人物/ }).click();
    await thread(page).getByRole("menuitem", { name: character.name, exact: true }).click();
    await expect(chip(page, `人物 · ${character.name}`)).toBeVisible();
    // 在正文里选一段: only a hint, no tag.
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^在正文里选一段/ }).click();
    await expect(thread(page).getByText(/在正文里选中一段文字，再点浮出来的「问助手」/)).toBeVisible();
    await expect(thread(page).locator(".a-chip")).toHaveCount(2);
    const request = taskPost(page);
    await ask(page, "她手里还有别的东西吗？");
    expect(bodyOf(await request).context).toMatchObject({ page: "writing", chapter_number: 3, character_id: character.id });
    await finished(page);
    // The tags went with the question; what stands in the box now is the answer just given, which the next question follows.
    await expect(thread(page).locator(".a-chip")).toHaveText("接着上一问 · 第 1 次追问，还能再问 1 次");
    // 某条检查结果 → a tag 「第 1 处」, and the question goes as a request for a change to that finding (the box's 自动 judges it).
    await openPlus(page);
    await thread(page).getByRole("menuitem", { name: /^某条检查结果/ }).click();
    await thread(page).getByRole("menuitem", { name: new RegExp(`^1`) }).click();
    await expect(chip(page, "第 1 处")).toBeVisible();
    const fix = taskPost(page);
    await ask(page, "保留苏岑的视角");
    expect(bodyOf(await fix)).toEqual({ kind: "fix_issue", question: "保留苏岑的视角", context: { page: "writing", issue_id: issue.id }, routed: true, route_source: "model", routed_input: "保留苏岑的视角" });
  });

  test("没有现成的检查结果时，菜单里的「某条检查结果」不可用或不出现", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await openPlus(page);
    // The sample's own result cannot be handed over: the entry is there but says why it is off.
    const entry = thread(page).getByRole("menuitem", { name: /^某条检查结果/ });
    await expect(entry).toBeDisabled();
    await expect(entry).toHaveAttribute("title", "示例结果不能交给助手，先再检查一次");
  });

  test("模式：自动 / 问作品 / 写前回顾 / 查前文矛盾；写前回顾可以不写字；查前文矛盾要先选中一段", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    const mode = thread(page).getByRole("button", { name: /^这次做什么：/ });
    await mode.click();
    await expect(thread(page).getByRole("menuitemradio")).toHaveText(["自动", "问作品", "写前回顾", "查前文矛盾", "改资料"]);
    await page.keyboard.press("Escape");
    // 写前回顾: nothing to write; the placeholder and the cost line follow; sending starts one.
    await chooseMode(page, "写前回顾");
    await expect(box(page)).toHaveAttribute("placeholder", /不用写字，直接发送/);
    await expect(send(page)).toBeEnabled();
    let request = taskPost(page);
    await send(page).click();
    expect(bodyOf(await request)).toEqual({ kind: "recap", context: { page: "writing" } });
    await finished(page);
    await expect(thread(page).getByRole("button", { name: "这次做什么：自动" })).toBeVisible();
    // 查前文矛盾: no picked passage, no sending; with one, it can go.
    await chooseMode(page, "查前文矛盾");
    await page.evaluate(() => window.scrollTo(0, 0));
    await expect(box(page)).toHaveAttribute("placeholder", "在正文里选中要查的一段");
    await expect(send(page)).toBeDisabled();
    await expect(thread(page).locator(".cx-note")).toHaveText("约 500 字");
    await select(page, "#draft-body", 14);
    const picked = (await selectedWords(page)).trim();
    // The picked words become the tag on their own in this mode; the bar's own button is another way to the same thing.
    await expect(send(page)).toBeEnabled();
    await expect(thread(page).locator(".cx-note")).toHaveText(/^约 \d+ 字$/);
    request = taskPost(page);
    await send(page).click();
    expect(bodyOf(await request)).toMatchObject({ kind: "ask", question: "这段和前文有没有矛盾？", context: { page: "writing", selection: picked, intent: "check_selection" } });
    await finished(page, 2);
    await expect(thread(page).getByRole("button", { name: "这次做什么：自动" })).toBeVisible();
  });

  test("其他页的抽屉只有「自动」和「问作品」；访客在写作页没有「查前文矛盾」", async ({ page, browser }) => {
    const id = await setup(page);
    await openTab(page, id, "sources");
    await topbarAssistant(page).click();
    await expect(thread(page).getByRole("button", { name: "这次做什么：自动" })).toBeEnabled();
    await thread(page).getByRole("button", { name: /^这次做什么：/ }).click();
    await expect(thread(page).getByRole("menuitemradio")).toHaveText(["自动", "问作品", "改资料"]);
    await page.keyboard.press("Escape");
    const visitor = await newPage(browser);
    await startVisitor(visitor);
    const sample = await sampleWorkId(visitor);
    await openTab(visitor, sample, "workspace");
    await openAssistantTab(visitor);
    await thread(visitor).getByRole("button", { name: /^这次做什么：/ }).click();
    await expect(thread(visitor).getByRole("menuitemradio")).toHaveText(["自动", "问作品", "写前回顾", "改资料"]);
    await visitor.close();
  });

  test("发送键：没写字时灰、能发时蓝、助手在查时是黑底停止键；聚焦时先写「Enter 发送」，超过 250 字换成字数", async ({ page }) => {
    await setup(page, true, true);
    await openAssistantTab(page);
    const square = thread(page).locator(".cx-send");
    const size = await square.boundingBox();
    expect([Math.round(size!.width), Math.round(size!.height)]).toEqual([32, 32]);
    await expect(square).toBeDisabled();
    const grey = await square.evaluate((node) => getComputedStyle(node).backgroundColor);
    await box(page).fill("苏岑是谁？");
    await expect(square).toBeEnabled();
    const blue = await square.evaluate((node) => getComputedStyle(node).backgroundColor);
    expect(blue).toBe("rgb(31, 43, 255)");
    expect(blue).not.toBe(grey);
    // The hint: Enter first when the box has focus; the count from 250; red at 300.
    await box(page).focus();
    await box(page).fill("");
    await expect(thread(page).locator(".cx-keys")).toHaveText("Enter 发送");
    await box(page).fill("字".repeat(268));
    await expect(thread(page).locator(".cx-note")).toHaveText("268 / 300");
    await box(page).fill("字".repeat(300));
    await expect(thread(page).locator(".cx-note")).toHaveText("300 / 300");
    await expect(thread(page).locator(".cx-note")).toHaveClass(/warn/);
    await box(page).fill("E2E_SLOW 苏岑现在在哪？");
    await square.click();
    // While it works: a black stop key; the next question can be written but not sent.
    const stop = stopButton(page);
    await expect(stop).toBeVisible();
    // Black at rest, a shade lighter under the pointer (which is where 发送 was clicked): the judgement that now precedes a task gives
    // the browser time to notice the key under it, so the shade is read either way.
    expect(["rgb(17, 17, 17)", "rgb(51, 51, 51)"]).toContain(await stop.evaluate((node) => getComputedStyle(node).backgroundColor));
    await box(page).fill("再问一个");
    await expect(thread(page).locator(".cx-note")).toHaveText("上一个问题还在查");
    await box(page).press("Enter");
    await expect(tasks(page)).toHaveCount(1);
    // The stop key ignores clicks for 700 ms after it appears (a double click on 发送 must not stop the new task).
    await page.waitForTimeout(800);
    await stop.click();
    await expect(tasks(page).first()).toHaveAttribute("data-status", "cancelled");
    await expect(send(page)).toBeEnabled();
  });

  test("输入框和全站的输入框是同一套：浅底、悬停出细边、聚焦变白加蓝边和淡蓝外光", async ({ page, browser }) => {
    await setup(page);
    await openAssistantTab(page);
    const frame = thread(page).locator("form.cx");
    // The fields ease between their states; what is read here is the state they arrive at.
    await page.addStyleTag({ content: "*, *::before, *::after { transition: none !important; }" });
    const read = (node: Element) => { const style = getComputedStyle(node); return { background: style.backgroundColor, border: style.borderTopColor, shadow: style.boxShadow, radius: style.borderTopLeftRadius }; };
    const quiet = await frame.evaluate(read);
    await page.mouse.move(2, 2);
    await frame.hover();
    const hovered = await frame.evaluate(read);
    await box(page).focus();
    const focused = await frame.evaluate(read);
    const tokens = await page.evaluate(() => { const root = getComputedStyle(document.documentElement); const colour = (name: string) => { const probe = document.createElement("i"); probe.style.cssText = `color: var(${name}); transition: none`; document.body.append(probe); const value = getComputedStyle(probe).color; probe.remove(); return value; }; return { sunken: colour("--c-sunken"), line: colour("--c-line"), surface: colour("--c-surface"), blue: colour("--c-blue"), tint: colour("--c-blue-tint"), md: root.getPropertyValue("--r-md").trim() }; });
    expect(quiet.background).toBe(tokens.sunken);
    expect(quiet.border).toBe("rgba(0, 0, 0, 0)");
    expect(hovered.border).toBe(tokens.line);
    expect(focused.background).toBe(tokens.surface);
    expect(focused.border).toBe(tokens.blue);
    expect(focused.shadow).toContain(tokens.tint);
    expect(focused.radius).toBe(tokens.md);
    // The same on a field of another page (the sign-in page): soft fill, white and blue when focused, 6px corners.
    const other = await browser.newPage({ baseURL: process.env.E2E_BASE_URL });
    await other.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await other.goto("/register");
    await other.addStyleTag({ content: "*, *::before, *::after { transition: none !important; }" });
    const field = other.getByLabel("账号", { exact: true });
    // (The page puts the cursor in this field when it opens; take it out to see the field at rest.)
    await field.evaluate((node) => (node as HTMLInputElement).blur());
    const before = await field.evaluate(read);
    await field.focus();
    const after = await field.evaluate(read);
    expect(before.background).toBe(tokens.sunken);
    expect(before.radius).toBe("6px");
    expect(after.background).toBe(tokens.surface);
    expect(after.border).toBe(tokens.blue);
    expect(after.shadow).toContain(tokens.tint);
    await other.close();
  });
});

test.describe("助手：提问和空对话", () => {
  test("改问题重发：鼠标移上去出现「改」，改了重发带 edited_from，原问题和回答折叠为「已改问」", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const first = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0];
    const bubble = tasks(page).first().locator(".a-ask").first();
    const edit = bubble.getByRole("button", { name: "修改这个问题", exact: true });
    await expect(edit).toHaveCSS("opacity", "0");
    await bubble.hover();
    await expect(edit).toHaveCSS("opacity", "1");
    await edit.click();
    const area = thread(page).getByRole("textbox", { name: "修改问题", exact: true });
    await expect(area).toHaveValue("苏岑知道罗盘被调包了吗？");
    // Cancelling puts the question back as it was.
    await thread(page).getByRole("button", { name: "取消", exact: true }).click();
    await expect(area).toHaveCount(0);
    await bubble.hover();
    await edit.click();
    const resend = thread(page).getByRole("button", { name: "重新发送 · 约 500 字", exact: true });
    await expect(resend).toBeDisabled();
    await area.fill("苏岑知道罗盘被谁调包了吗？");
    const request = taskPost(page);
    await resend.click();
    expect(bodyOf(await request)).toMatchObject({ kind: "ask", question: "苏岑知道罗盘被谁调包了吗？", edited_from: first.id });
    await finished(page, 2);
    await expect(tasks(page)).toHaveCount(2);
    const old = tasks(page).first();
    await expect(old.locator("summary").first()).toHaveText("已改问 · 苏岑知道罗盘被调包了吗？");
    expect(await old.evaluate((node: HTMLDetailsElement) => node.open)).toBe(false);
    await expect(tasks(page).last()).toContainText("苏岑知道罗盘被谁调包了吗？");
    const saved = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks;
    expect(saved[1].edited_from).toBe(first.id);
  });

  test("输入框为空时按 ↑ 调出上一问；已有字时不动", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    await ask(page, "温岚现在在哪？");
    await finished(page, 2);
    await box(page).focus();
    await expect(box(page)).toHaveValue("");
    await page.keyboard.press("ArrowUp");
    await expect(box(page)).toHaveValue("温岚现在在哪？");
    await box(page).fill("先写点别的");
    await page.keyboard.press("ArrowUp");
    await expect(box(page)).toHaveValue("先写点别的");
  });

  test("空对话：四条按模板生成的建议问题（最后一条请助手出主意），点一下就问；有了对话就不再出现；写前回顾按钮在下面", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    const list = thread(page).getByRole("list", { name: "可以先问这些" });
    await expect(list.getByRole("listitem")).toHaveCount(4);
    await expect(list.getByRole("listitem").nth(0)).toContainText("第 10 章结尾写到哪了？");
    await expect(list.getByRole("listitem").nth(0)).toContainText("接着写之前");
    await expect(list.getByRole("listitem").nth(1)).toContainText(/现在知道些什么？/);
    await expect(list.getByRole("listitem").nth(1)).toContainText(/草稿里出现 \d+ 次/);
    await expect(list.getByRole("listitem").nth(2)).toContainText(/上一次出场在做什么？/);
    await expect(list.getByRole("listitem").nth(3)).toContainText("有哪些伏笔还没收？");
    // Most often first: the counts go down.
    const counts = (await list.getByRole("listitem").allInnerTexts()).slice(1, 3).map((text) => Number(text.match(/出现 (\d+) 次/)![1]));
    expect(counts[0]).toBeGreaterThanOrEqual(counts[1]);
    await expect(thread(page).getByRole("button", { name: "写前回顾", exact: true })).toBeVisible();
    const request = taskPost(page);
    await list.getByRole("button", { name: /^第 10 章结尾写到哪了/ }).click();
    expect(bodyOf(await request)).toMatchObject({ kind: "ask", question: "第 10 章结尾写到哪了？", context: { page: "writing" } });
    await finished(page);
    await expect(list).toHaveCount(0);
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).getByRole("list", { name: "可以先问这些" })).toHaveCount(0);
    expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks).toHaveLength(1);
  });

  test("空对话的写前回顾按钮发起写前回顾；访客看到固定的三条", async ({ page, browser }) => {
    await setup(page);
    await openAssistantTab(page);
    const request = taskPost(page);
    await thread(page).getByRole("button", { name: "写前回顾", exact: true }).click();
    expect(bodyOf(await request)).toEqual({ kind: "recap", context: { page: "writing" } });
    await finished(page);
    const visitor = await newPage(browser);
    await startVisitor(visitor);
    const sample = await sampleWorkId(visitor);
    await openTab(visitor, sample, "workspace");
    await openAssistantTab(visitor);
    const list = thread(visitor).getByRole("list", { name: "可以先问这些" });
    // The same three as an author's own, counted in the sample's draft.
    await expect(list.getByRole("listitem")).toHaveText([/^第 10 章结尾写到哪了？/, /现在知道些什么？.*草稿里出现 \d+ 次/, /上一次出场在做什么？.*草稿里出现 \d+ 次/, /^有哪些伏笔还没收？/]);
    await visitor.close();
  });

  test("往上翻、又有新内容进来时，右下角出现「新回答 ↓」，点了回到底部并消失", async ({ page }) => {
    await setup(page);
    const finishedAsk = (index: number) => askView({ id: `atask-mock-${index}`, question: `第 ${index} 个问题`, created_at: new Date(Date.now() - (9 - index) * 60_000).toISOString() });
    let last: Record<string, unknown> = runningView("thinking", { id: "atask-mock-9", question: "第 9 个问题" });
    await serveTasks(page, () => [...[1, 2, 3, 4, 5, 6].map(finishedAsk), last]);
    await page.reload();
    await openAssistantTab(page);
    const scroller = column(page);
    await expect.poll(() => scroller.evaluate((node) => node.scrollHeight > node.clientHeight + 200)).toBe(true);
    await expect.poll(() => scroller.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight < 80)).toBe(true);
    // Reading further up; then the running question ends and its answer comes in.
    await page.waitForTimeout(400);
    await scroller.evaluate((node) => { node.scrollTop = 0; });
    await expect(thread(page).getByRole("button", { name: /^新回答/ })).toHaveCount(0);
    last = finishedAsk(9);
    const jump = thread(page).getByRole("button", { name: /^新回答/ });
    await expect(jump).toBeVisible({ timeout: 8_000 });
    await jump.click();
    await expect(jump).toHaveCount(0);
    await expect.poll(() => scroller.evaluate((node) => node.scrollHeight - node.scrollTop - node.clientHeight < 80)).toBe(true);
    // The button does not come while the author is at the bottom.
    expect(await scroller.evaluate((node) => node.scrollTop)).toBeGreaterThan(100);
  });
});

test.describe("助手：开关、测试版、隐私", () => {
  test("开关关闭时所有助手入口都不显示；已有对话的作品不报错", async ({ page }) => {
    test.setTimeout(150_000);
    const errors: string[] = [];
    page.on("pageerror", (error) => errors.push(error.message));
    const { id, issue } = await checkedWork(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    try {
      await setRollout(page, "off");
      expect((await api(page).get("/auth/session")).user.assistant).toEqual({ available: false, beta: false });
      await page.reload();
      await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
      // The column's own tabs: only the findings. No tab, no thread, no 写前回顾 in the page's head, nothing after picking words.
      await expect(findings(page).getByRole("tab")).toHaveCount(0);
      await expect(findings(page).getByRole("heading", { name: /^检查结果/ })).toBeVisible();
      await expect(thread(page)).toHaveCount(0);
      await expect(page.locator(".draft-head-actions").getByRole("button", { name: "写前回顾", exact: true })).toHaveCount(0);
      await select(page, "#draft-body", 14);
      await page.waitForTimeout(500);
      await expect(toolbar(page)).toHaveCount(0);
      await expect(page.locator(".mobile-panes button")).toHaveText(["正文", /^检查结果/]);
      // A finding has no 让助手给改法.
      await page.evaluate(() => window.getSelection()?.removeAllRanges());
      await expect(findings(page).getByRole("button", { name: /让助手/ })).toHaveCount(0);
      await page.locator(`[data-testid="finding-${issue.id}"]`).click();
      await expect(page.locator(".finding-detail")).toBeVisible();
      await expect(findings(page).getByRole("button", { name: /让助手/ })).toHaveCount(0);
      // Other pages: no 助手 button in the top bar, no bar over picked words.
      await openTab(page, id, "sources");
      await expect(page.getByRole("navigation", { name: "作品" })).toBeVisible();
      await expect(topbarAssistant(page)).toHaveCount(0);
      await page.locator("#chapter-2").getByRole("button", { name: /^段落/ }).click();
      await select(page, ".chapter-passages", 14);
      await page.waitForTimeout(500);
      await expect(toolbar(page)).toHaveCount(0);
      // The conversation is still on the server, and comes back with the switch.
      expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks).toHaveLength(1);
      await setRollout(page, "all");
      await openTab(page, id, "workspace");
      await openAssistantTab(page);
      await expect(tasks(page)).toHaveCount(1);
    } finally { await setRollout(page, "all"); }
    expect(errors).toEqual([]);
  });

  test("注册用户阶段：「助手」标签旁有「测试版」小标签（3 像素圆角），抽屉标题也有", async ({ page }) => {
    const id = await setup(page);
    try {
      await setRollout(page, "registered");
      expect((await api(page).get("/auth/session")).user.assistant).toEqual({ available: true, beta: true });
      await page.reload();
      const tab = findings(page).getByRole("tab", { name: /^助手/ });
      await expect(tab.locator(".a-beta")).toHaveText("测试版");
      expect(await tab.locator(".a-beta").evaluate((node) => getComputedStyle(node).borderTopLeftRadius)).toBe("3px");
      await openTab(page, id, "sources");
      await topbarAssistant(page).click();
      await expect(page.getByRole("dialog", { name: "助手", exact: true }).locator(".a-beta")).toHaveText("测试版");
      // Not in the other stages.
      await setRollout(page, "all");
      await page.reload();
      await expect(page.locator(".a-beta")).toHaveCount(0);
    } finally { await setRollout(page, "all"); }
  });

  test("隐私说明页：不登录也能打开，正文是定稿的，外链在新标签页打开；页脚、注册页有链接", async ({ page, browser }) => {
    const other = await browser.newPage({ baseURL: process.env.E2E_BASE_URL });
    await other.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await other.goto("/privacy");
    await expect(other.getByRole("heading", { level: 1, name: "隐私说明" })).toBeVisible();
    await expect(other).toHaveURL(/\/privacy$/);
    await expect(other.getByText("最近更新：2026 年 10 月 24 日")).toBeVisible();
    await expect(other.getByRole("heading", { level: 2 })).toHaveText(["我们收集什么", "怎么用", "交给谁处理", "保存多久", "你可以做什么", "关于 AI 生成的内容", "联系我们", "这份说明的变更"]);
    await expect(other.getByText("我们不会公开、出售你的作品，也不会用你的作品训练任何模型。")).toBeVisible();
    await expect(other.getByText("这些片段会被发送到 DeepSeek 在中国大陆的服务器上处理。", { exact: false })).toBeVisible();
    const policy = other.getByRole("link", { name: "隐私政策", exact: true });
    await expect(policy).toHaveAttribute("href", "https://cdn.deepseek.com/policies/zh-CN/deepseek-privacy-policy.html");
    await expect(policy).toHaveAttribute("target", "_blank");
    await expect(policy).toHaveAttribute("rel", /noopener/);
    await expect(other.getByRole("link", { name: "zcy4711@gmail.com" })).toHaveAttribute("href", "mailto:zcy4711@gmail.com");
    // The page is an article: a narrow column, not the width of the app.
    expect((await other.locator("article.privacy").boundingBox())!.width).toBeLessThanOrEqual(700);
    await other.getByRole("contentinfo").getByRole("link", { name: "隐私说明", exact: true }).waitFor();
    // The register page links to it.
    await other.goto("/register");
    await other.getByRole("link", { name: "隐私说明", exact: true }).click();
    await expect(other).toHaveURL(/\/privacy$/);
    await other.close();
    // Signed in: the foot of the page links to it.
    await setup(page);
    await page.getByRole("contentinfo").getByRole("link", { name: "隐私说明", exact: true }).click();
    await expect(page).toHaveURL(/\/privacy$/);
    await expect(page.getByRole("heading", { level: 1, name: "隐私说明" })).toBeVisible();
  });

  test("第一次打开助手：说明文字下有一句「会把相关片段发给 DeepSeek」和隐私说明的链接；本机记住以后不再显示", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    const line = thread(page).getByText(/^使用助手会把相关片段发给 DeepSeek 处理，详见隐私说明。/);
    await expect(line).toBeVisible();
    const link = line.getByRole("link", { name: "隐私说明", exact: true });
    await expect(link).toHaveAttribute("href", "/privacy");
    await expect(link).toHaveAttribute("target", "_blank");
    // Only a first question counts as having read it.
    expect(await page.evaluate(() => window.localStorage.getItem("story-continuity:assistant-privacy-seen"))).toBeNull();
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    await expect.poll(() => page.evaluate(() => window.localStorage.getItem("story-continuity:assistant-privacy-seen"))).toBe("1");
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).getByText(/使用助手会把相关片段发给 DeepSeek/)).toHaveCount(0);
  });

  test("检查结果也标明 AI 生成：写作页右栏列表底部、章节页的检查结果区域，各一行浅色小字", async ({ page }) => {
    const { id } = await checkedWork(page);
    const note = "检查结果由 AI 生成，可能有错漏，请对照原文判断。";
    const onWriting = findings(page).getByTestId("ai-note");
    await expect(onWriting).toHaveText(note);
    // After the last finding, and small and light like the line under the assistant's box.
    const [last, line] = [await findings(page).getByTestId(/^finding-/).last().boundingBox(), await onWriting.boundingBox()];
    expect(line!.y).toBeGreaterThan(last!.y);
    const compose = thread(page).locator(".a-ai-note");
    await openAssistantTab(page);
    const same = await Promise.all([onWriting, compose].map((locator) => locator.evaluate((node) => { const style = getComputedStyle(node); return [style.fontSize, style.color]; })));
    expect(same[0]).toEqual(same[1]);
    // The chapters page shows a result too: the sample's own multi-chapter result is there from the start.
    await openTab(page, id, "sources");
    await expect(page.locator("section.latest").getByText(note, { exact: true })).toBeVisible();
  });
});

test.describe("全站：圆角和输入框", () => {
  test("圆角按大小分级：标签 3、按钮和输入框 6、菜单和助手的框 10、大卡片 / 对话框 / 抽屉 14；分隔线、表格、页头保持直线", async ({ page }) => {
    const id = await setup(page);
    const radius = (selector: string) => page.locator(selector).first().evaluate((node) => getComputedStyle(node).borderTopLeftRadius);
    expect(await page.evaluate(() => ["--r-xs", "--r-sm", "--r-md", "--r-lg"].map((name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim()))).toEqual(["3px", "6px", "10px", "14px"]);
    // The writing page: tags and badges 3; buttons 6; the sample's tour band 14; the page's own rules and head are straight.
    expect(await radius(".finding .tag")).toBe("3px");
    expect(await radius(".draft-head-meta .badge")).toBe("3px");
    expect(await radius(".draft-head .btn-primary")).toBe("6px");
    expect(await radius(".tour")).toBe("14px");
    expect(await radius(".topbar")).toBe("0px");
    expect(await radius(".draft-head")).toBe("0px");
    expect(await radius(".finding")).toBe("0px");
    // A menu 10 (and the button that opens it 6); the dialog it leads to 14.
    await page.locator(".draft-head-actions details.menu > summary").click();
    expect(await radius(".draft-head-actions .menu > summary")).toBe("6px");
    expect(await radius(".draft-head-actions .menu-list")).toBe("10px");
    await page.getByRole("menuitem", { name: "重置作品", exact: true }).click();
    await expect(page.getByRole("dialog")).toBeVisible();
    expect(await radius(".dialog")).toBe("14px");
    await page.keyboard.press("Escape");
    // The assistant's box 10, its tag 3, its send square 6, the question bubble 10; the drawer 14 on the side that faces the page.
    await openAssistantTab(page);
    expect(await radius(".assistant .cx")).toBe("10px");
    expect(await radius(".assistant .cx-send")).toBe("6px");
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    expect(await radius(".assistant .a-ask")).toBe("10px");
    expect(await radius(".assistant .a-cite button")).toBe("3px");
    await openTab(page, id, "sources");
    expect(await radius(".chapter-row")).toBe("0px");
    expect(await radius(".chapter-item")).toBe("0px");
    await topbarAssistant(page).click();
    expect(await page.locator(".drawer").evaluate((node) => getComputedStyle(node).borderRadius)).toBe("14px 0px 0px 14px");
    await page.keyboard.press("Escape");
    // Fields everywhere are 6.
    await openTab(page, id, "memory");
    expect(await radius(".search input")).toBe("6px");
    expect(await radius(".chip")).toBe("6px");
  });
});
