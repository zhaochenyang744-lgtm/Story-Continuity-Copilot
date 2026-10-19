import AxeBuilder from "@axe-core/playwright";
import type { Page } from "@playwright/test";
import { api, expect, openTab, sampleWorkId, shot, startVisitor, test } from "./support/app";
import { adoptRequest, allowance, ask, askForFix, box, checkedWork, chip, chars, finished, findingsTab, openAssistantTab, proposal, REWRITTEN, select, selectedWords, send, SENTENCE, sideTab, stopButton, taskPost, tasks, thread, toolbar, topbarAssistant } from "./support/assistant";
import { evidence, theme } from "./support/pages";
import { beginCheck, button, draft, finding, findings, finishCheck, readDraftBody, run, saveBody, selectIssue, setDraftBody, setup } from "./support/writing";

// The built-in assistant (v1.8.0). The backend's test provider answers from a fixed two-round script
// (look up a name and search the text, then answer with the first source), so every answer here is
// predictable; E2E_SLOW, E2E_FAIL and E2E_NOT_FOUND in a question pick the other endings.

test.describe("助手", () => {
  test("写作页：提问得到带出处的回答，步骤折叠，扣 500 字，刷新后对话还在", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await expect(thread(page).getByRole("textbox", { name: "向助手提问" })).toHaveAttribute("placeholder", "问这部作品里的人、事、物……");
    await expect(thread(page)).toContainText(/约 500 字 · 今天还剩 [\d,]+ 字/);
    const before = await allowance(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    await expect(task).toContainText("苏岑知道罗盘被调包了吗？");
    await expect(task.getByText("问作品", { exact: true })).toBeVisible();
    await expect(task.getByText("有答案", { exact: true })).toBeVisible();
    // The steps are folded into one line; opening it lists what was looked up.
    const fold = task.getByRole("button", { name: /^查了 \d+ 处/ });
    await expect(fold).toHaveAttribute("aria-expanded", "false");
    await expect(task.getByText("查了 1 条事实：苏岑")).toHaveCount(0);
    await fold.click();
    await expect(task.getByText("先查苏岑的已确认事实，再在正文里搜一搜。")).toBeVisible();
    await expect(task.getByText("查了 1 条事实：苏岑")).toBeVisible();
    await expect(task.getByText("搜了 1 处正文")).toBeVisible();
    // The answer carries numbered sources (1, 2, 3 …, never the raw R number).
    await expect(task.getByText("（示意回答）前文写过这件事。")).toBeVisible();
    await expect(task.locator(".a-cite button")).toHaveText(["1"]);
    await expect(task.getByRole("button", { name: /^出处 1：第 \d+ 章/ })).toBeVisible();
    await expect(task.getByRole("list", { name: "出处" }).getByRole("listitem")).toHaveCount(1);
    await expect(task).not.toContainText(/\bR\d+\b/);
    await expect(task).toContainText(/查过：.*已确认事实：苏岑/);
    await expect(task).toContainText(/没查：/);
    // Under the answer only what it cost: no count of steps, and no round.
    await expect(task).toContainText("计 500 字");
    await expect(task).not.toContainText(/\d+ 步|第 \d+ 轮/);
    await expect.poll(() => allowance(page)).toBe(before - 500);
    await expect(thread(page)).toContainText(`今天还剩 ${(before - 500).toLocaleString("en-US")} 字`);
    await page.evaluate(() => window.scrollTo(0, 340));
    await shot(page, "assistant-writing-day", false);
    // The conversation is on the server, and the author's last tab is remembered on this device.
    await page.reload();
    await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
    await expect(tasks(page)).toHaveCount(1);
    await expect(tasks(page).first()).toContainText("（示意回答）前文写过这件事。");
  });

  test("点出处的章名：打开写作页的阅读页并定位到那一段，同卡片里的「去原文」", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const item = task.getByRole("list", { name: "出处" }).getByRole("listitem").first();
    const chapter = item.getByRole("button", { name: /^第 \d+ 章/ });
    const number = Number((await chapter.innerText()).match(/^第 (\d+) 章/)![1]);
    await chapter.click();
    await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=${number}$`));
    await expect(page.getByRole("heading", { level: 1, name: new RegExp(`^第 ${number} 章`) })).toBeAttached();
  });

  test("接着问：带上「接着问」标签，请求体含 follow_up_of", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const first = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0];
    await tasks(page).first().getByRole("button", { name: "接着问", exact: true }).click();
    await expect(chip(page, "接着问：苏岑知道罗盘被调包了吗？")).toBeVisible();
    await expect(box(page)).toBeFocused();
    const request = taskPost(page);
    await ask(page, "她是什么时候知道的？");
    const body = (await request).postDataJSON();
    expect(body.follow_up_of).toBe(first.id);
    expect(body.kind).toBe("ask");
    await finished(page, 2);
    // The tag goes with the question that used it.
    await expect(thread(page).locator(".a-chip")).toHaveCount(0);
    const saved = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks;
    expect(saved[1].follow_up_of).toBe(first.id);
  });

  test("运行中：步骤和停止按钮，停止后显示已停止", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "E2E_SLOW 苏岑现在在哪？");
    const task = tasks(page).first();
    await expect(task).toHaveAttribute("data-status", /^(queued|running)$/);
    await expect(task.getByText("正在查", { exact: true })).toBeVisible();
    await expect(thread(page).getByRole("status").first()).toBeVisible();
    // While it works the send square is a stop button, and the next question can be typed but not sent.
    await expect(send(page)).toHaveCount(0);
    await expect(stopButton(page)).toBeVisible();
    await expect(thread(page).getByText("上一个问题还在查", { exact: true })).toBeVisible();
    await task.getByRole("button", { name: "停止", exact: true }).click();
    await expect(task).toHaveAttribute("data-status", "cancelled");
    await expect(task.getByText(/^已停止，计 \d+ 字$/)).toBeVisible();
    await expect(task.getByText(/没有计字数/)).toHaveCount(0);
    await box(page).fill("再问一个");
    await expect(send(page)).toBeEnabled();
  });

  test("模型没有回应：失败文案、没有计字数、字数没减少，可以重试", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    const before = await allowance(page);
    await ask(page, "E2E_FAIL 苏岑是谁？");
    await finished(page, 1, "failed");
    const task = tasks(page).first();
    await expect(task).toContainText("模型这次没有回应，没有计字数。可以重试；正文和资料都没有改动。");
    await expect(task).not.toContainText(/provider_|timeout/i);
    await expect.poll(() => allowance(page)).toBe(before);
    const request = taskPost(page);
    await task.getByRole("button", { name: "重试", exact: true }).click();
    expect((await request).postDataJSON().question).toBe("E2E_FAIL 苏岑是谁？");
    await finished(page, 2, "failed");
    await expect.poll(() => allowance(page)).toBe(before);
  });

  test("正文里找不到：灰字状态和说明", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "E2E_NOT_FOUND 苏岑的生日是哪天？");
    await finished(page);
    const task = tasks(page).first();
    await expect(task.getByText("正文里找不到", { exact: true })).toBeVisible();
    await expect(task.getByText("（示意）查过前文，没有找到相关的写法。", { exact: true })).toBeVisible();
    await expect(task.locator(".a-cite")).toHaveCount(0);
  });

  test("选中草稿里的文字：工具条「问助手」带入上下文，「前面怎么写的」直接发起", async ({ page }) => {
    await setup(page);
    await expect(toolbar(page)).toHaveCount(0);
    await select(page, "#draft-body", 3);
    await expect(toolbar(page)).toHaveCount(0);
    await select(page, "#draft-body", 12);
    await expect(toolbar(page)).toBeVisible();
    const picked = (await selectedWords(page)).trim();
    await shot(page, "assistant-selection-toolbar", false);
    // The bar's buttons are real buttons with names, and Escape puts the bar away.
    await expect(toolbar(page).getByRole("button", { name: /^问助手/ })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(toolbar(page)).toHaveCount(0);
    await select(page, "#draft-body", 12);
    await toolbar(page).getByRole("button", { name: /^问助手/ }).click();
    await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
    await expect(chip(page, `选中：「${picked}」`)).toBeVisible();
    await expect(box(page)).toBeFocused();
    await expect(toolbar(page)).toHaveCount(0);
    // Asking with it puts the passage in the request, and the tag goes.
    const typed = taskPost(page);
    await ask(page, "这句话是谁说的？");
    const typedBody = (await typed).postDataJSON();
    expect(typedBody.context).toMatchObject({ page: "writing", selection: picked });
    await finished(page);
    await expect(tasks(page).first().locator(".a-quote")).toContainText(picked.slice(0, 8));
    await expect(thread(page).locator(".a-chip")).toHaveCount(0);
    // 前面怎么写的 asks at once.
    await select(page, "#draft-body", 12);
    const quick = taskPost(page);
    await toolbar(page).getByRole("button", { name: /^前面怎么写的/ }).click();
    const quickBody = (await quick).postDataJSON();
    expect(quickBody.question).toBe("这段前面怎么写的？");
    expect(quickBody.context.selection).toBe(picked);
    await finished(page, 2);
  });

  test("章节页：顶栏「助手」打开抽屉，上下文是打开的那一章；Esc 关闭，焦点回到按钮", async ({ page }) => {
    const id = await setup(page);
    await openTab(page, id, "sources");
    await expect(topbarAssistant(page)).toBeVisible();
    await expect(topbarAssistant(page)).toHaveText("助手");
    await page.locator("#chapter-2").getByRole("button", { name: /^段落/ }).click();
    await topbarAssistant(page).click();
    const drawer = page.getByRole("dialog", { name: "助手", exact: true });
    await expect(drawer).toBeVisible();
    await expect(box(page)).toBeFocused();
    await expect(chip(page, "第 2 章")).toBeVisible();
    const request = taskPost(page);
    await ask(page, "苏岑第一次出现是在哪里？");
    expect((await request).postDataJSON().context).toMatchObject({ page: "chapters", chapter_number: 2 });
    await finished(page);
    await shot(page, "assistant-drawer", false);
    // Focus stays inside the drawer, then Escape closes it and the button gets focus back.
    for (let i = 0; i < 25; i++) {
      await page.keyboard.press("Tab");
      expect(await page.evaluate(() => Boolean(document.activeElement?.closest('[role="dialog"]')))).toBe(true);
    }
    await page.keyboard.press("Escape");
    // Tabbing may have opened a citation card (focus does); the first Escape then only puts that card away.
    if (await drawer.count()) await page.keyboard.press("Escape");
    await expect(drawer).toHaveCount(0);
    await expect(topbarAssistant(page)).toBeFocused();
    // The writing page's own right column has the assistant, so its top bar has no such button.
    await openTab(page, id, "workspace");
    await expect(topbarAssistant(page)).toHaveCount(0);
  });

  test("资料页人物卡：抽屉里的上下文标签是「人物 · 某某」，请求体带 character_id", async ({ page }) => {
    const id = await setup(page);
    const [character] = (await api(page).get(`/projects/${id}/characters`)).characters;
    await page.goto(`/projects/${id}/memory?view=people&character=${character.id}`);
    await expect(page.locator(`#character-${character.id}`)).toBeVisible();
    await topbarAssistant(page).click();
    await expect(chip(page, `人物 · ${character.name}`)).toBeVisible();
    const request = taskPost(page);
    await ask(page, `${character.name}是谁？`);
    expect((await request).postDataJSON().context).toMatchObject({ page: "materials", character_id: character.id });
    await finished(page);
    // The tag can be taken off.
    await thread(page).getByRole("button", { name: `去掉：人物 · ${character.name}` }).click();
    await expect(chip(page, `人物 · ${character.name}`)).toHaveCount(0);
  });

  test("资料页没有「问一问」标签，旧地址落到事实；旧问答记录在助手里只读显示", async ({ page }) => {
    const id = await setup(page);
    const saved = await api(page).get(`/projects/${id}`);
    const current = await api(page).get(`/projects/${id}/drafts/${saved.current_draft.id}`);
    const old = await api(page).post<{ run_id: string }>(`/projects/${id}/analyses`, { analysis_type: "story_qa", draft_id: current.id, draft_revision: current.revision, question: "罗盘现在在哪里？", scope: ["confirmed", "written", "planned"] });
    await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${old.run_id}`)).status).toBe("completed");
    await page.goto(`/projects/${id}/memory?view=ask`);
    const tabs = page.getByRole("navigation", { name: "资料分类", exact: true });
    await expect(tabs.getByRole("button")).toHaveText([/^事实/, /^人物/, /^设定/, /^伏笔/]);
    await expect(tabs.getByRole("button", { name: /^事实/ })).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("button", { name: "问一问" })).toHaveCount(0);
    // The history is in the assistant, folded, read only.
    await topbarAssistant(page).click();
    const legacy = thread(page).locator("details.a-legacy");
    await expect(legacy.getByText("以前在资料页问过的问题（只读）", { exact: true })).toBeVisible();
    await expect(legacy.getByText("罗盘现在在哪里？")).toBeHidden();
    await legacy.getByText("以前在资料页问过的问题（只读）", { exact: true }).click();
    await expect(legacy.getByText("罗盘现在在哪里？")).toBeVisible();
    await expect(legacy.getByRole("button")).toHaveCount(0);
    await expect(legacy.getByRole("textbox")).toHaveCount(0);
  });

  test("清空对话：确认后列表为空，刷新后也是空的", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    await thread(page).locator("details.menu > summary").click();
    await thread(page).getByRole("menuitem", { name: "清空对话", exact: true }).click();
    const confirm = thread(page).getByRole("alertdialog");
    await expect(confirm).toContainText("清空后这部作品的对话不再显示。已用的字数不退。");
    // Cancelling leaves everything as it was.
    await confirm.getByRole("button", { name: "取消", exact: true }).click();
    await expect(confirm).toHaveCount(0);
    await expect(tasks(page)).toHaveCount(1);
    await thread(page).locator("details.menu > summary").click();
    await thread(page).getByRole("menuitem", { name: "清空对话", exact: true }).click();
    await thread(page).getByRole("alertdialog").getByRole("button", { name: "清空", exact: true }).click();
    await expect(tasks(page)).toHaveCount(0);
    await expect(thread(page).getByText(/^问这部作品里的人、事、物。/)).toBeVisible();
    await page.reload();
    await expect(thread(page).getByText(/^问这部作品里的人、事、物。/)).toBeVisible();
    await expect(tasks(page)).toHaveCount(0);
  });

  test("字数不够：框变成虚线，直接写明原因和恢复时间，发送键不可点", async ({ page }) => {
    const id = await setup(page);
    const session = await api(page).get("/auth/session");
    const usage = await api(page).get("/account/usage");
    await api(page).post(`/test/v180/users/${session.user.id}/spend-characters/${usage.check_chars_remaining - 300}`);
    await page.reload();
    await openAssistantTab(page);
    // The reason is written in the box itself (not on a red line under it), and the box has no fill.
    const frame = thread(page).locator("form.cx");
    await expect(frame).toHaveClass(/\boff\b/);
    await expect(frame.getByText("今天的可检查字数不够这次提问（约 500 字，还剩 300 字）。用掉的额度 24 小时后陆续返还。", { exact: true })).toBeVisible();
    await expect(box(page)).toHaveCount(0);
    await expect(send(page)).toBeDisabled();
    expect(await frame.evaluate((node) => ({ style: getComputedStyle(node).borderStyle, fill: getComputedStyle(node).backgroundColor }))).toEqual({ style: "dashed", fill: "rgba(0, 0, 0, 0)" });
    await expect(thread(page).locator(".a-block")).toHaveCount(0);
    // The server refuses it too, with the code the page turns into those words.
    const refused = await api(page).raw("POST", `/projects/${id}/assistant/tasks`, { kind: "ask", question: "苏岑是谁？", context: { page: "writing" } });
    expect(refused.status).toBe(429);
    expect(refused.body.error.code).toBe("character_quota_exceeded");
  });

  test("访客：示例作品上能问，显示还剩几次；不是示例作品时的拒绝有中文说明", async ({ page }) => {
    await startVisitor(page);
    const id = await sampleWorkId(page);
    await openTab(page, id, "workspace");
    await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
    await openAssistantTab(page);
    await expect(thread(page)).toContainText("今天还可以问 3 次");
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    // (The cursor is in the box after sending, and the key hint stands where the count is; leave the box to read it.)
    await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
    await expect(thread(page)).toContainText("今天还可以问 2 次");
    await expect(tasks(page).first()).not.toContainText("计 500 字");
    // A visitor has no other work; the refusal is simulated once.
    await page.route("**/assistant/tasks", (route) => route.request().method() === "POST"
      ? route.fulfill({ status: 403, contentType: "application/json", body: JSON.stringify({ error: { code: "assistant_visitor_sample_only", message: "x", retryable: false } }) })
      : route.fallback());
    await ask(page, "再问一个");
    await expect(thread(page).getByText("访客只能在示例作品上使用助手。", { exact: true })).toBeVisible();
  });

  test("手机宽度：写作页第三个窗格「助手」可用，其他页的抽屉全屏", async ({ page }) => {
    const id = await setup(page);
    await page.setViewportSize({ width: 375, height: 812 });
    await openTab(page, id, "workspace");
    const panes = page.getByRole("navigation", { name: "切换内容", exact: true });
    await expect(panes.getByRole("button")).toHaveText(["正文", /^检查结果/, "助手"]);
    await panes.getByRole("button", { name: "助手", exact: true }).click();
    await expect(panes.getByRole("button", { name: "助手", exact: true })).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeHidden();
    await expect(thread(page)).toBeVisible();
    // The pane switch already names the assistant; the side tabs would only repeat it.
    await expect(page.getByRole("tablist", { name: "右栏内容", exact: true })).toBeHidden();
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    await expect(tasks(page).first().getByText("（示意回答）前文写过这件事。")).toBeVisible();
    await shot(page, "assistant-phone-pane", false);
    await panes.getByRole("button", { name: /^检查结果/ }).click();
    await expect(thread(page)).toBeHidden();
    // Another page: the drawer fills the screen.
    await openTab(page, id, "sources");
    await topbarAssistant(page).click();
    const drawer = page.getByRole("dialog", { name: "助手", exact: true });
    await expect(drawer).toBeVisible();
    const size = await drawer.boundingBox();
    expect(size!.width).toBeGreaterThanOrEqual(374);
    expect(size!.height).toBeGreaterThanOrEqual(800);
    await expect(thread(page).getByRole("textbox", { name: "向助手提问" })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await shot(page, "assistant-phone-drawer", false);
  });

  test("夜间主题：写作页助手标签截图（只做人工核对）", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    await tasks(page).first().getByRole("button", { name: /^查了 \d+ 处/ }).click();
    await theme(page, "night");
    await page.evaluate(() => window.scrollTo(0, 340));
    await shot(page, "assistant-writing-night", false);
    await button(page, "切换到日间模式").click();
  });

});

// ── 05b: 写前回顾, 帮我改这一处, 查前文矛盾 ──────────────────────────────────────────────────────────────
// The test model's scripts for these (backend/tests/e2e_app.py): a recap cites the first number of each candidate group;
// a fix proposes an edit (the sentence with its first character replaced by 「（示意改法）」), and an intentional
// way out (E2E_SETUP in the sentence adds a setup for chapter 1); a check of a passage checks it once and cites its first source.
test.describe("助手：写前回顾、帮我改这一处、查前文矛盾", () => {
  test("写前回顾：按钮发起 recap 并切到助手；四栏有概括、原文和出处；扣 500 字；可以重新回顾", async ({ page }) => {
    await setup(page);
    const before = await allowance(page);
    const request = taskPost(page);
    await button(page, "写前回顾").click();
    expect((await request).postDataJSON()).toEqual({ kind: "recap", context: { page: "writing" } });
    await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
    await finished(page);
    const task = tasks(page).first();
    await expect(task.getByText("写前回顾 · 第 11 章", { exact: true })).toBeVisible();
    await expect(task.getByText("只看第 1–10 章", { exact: true })).toBeVisible();
    // The four columns that have anything in them; every item is a sentence with its passage and where it is from.
    const ending = task.getByRole("region", { name: "上一章停在哪", exact: true });
    await expect(ending.getByText("（示意）上一章停在这里。", { exact: true })).toBeVisible();
    await expect(ending.locator(".a-ri-src .a-text")).toHaveCount(1);
    await expect(ending.locator(".a-ri-src .a-text")).not.toHaveText("");
    await expect(ending.locator(".a-from")).toHaveText("第 10 章");
    const people = task.getByRole("region", { name: "出场人物的最新状态", exact: true });
    await expect(people.locator(".a-ri").first()).toContainText("（示意）");
    for (const item of await people.locator(".a-ri").all()) {
      await expect(item.locator(".a-text").first()).not.toHaveText("");
      await expect(item.locator(".a-from").first()).toHaveText(/^(已确认事实 · )?第 \d+ 章$/);
    }
    // An empty column is not shown (the test model leaves 还没收的线 empty).
    await expect(task.getByRole("region", { name: "还没收的线", exact: true })).toHaveCount(0);
    await expect(task).not.toContainText(/\bR\d+\b/);
    await expect(task).toContainText("查过：第 1–10 章正文、截至第 11 章的事实、伏笔记录、本章计划。");
    await expect(task).toContainText("没查：本章草稿（写前回顾不看草稿）。");
    await expect(task).toContainText("计 500 字");
    await expect.poll(() => allowance(page)).toBe(before - 500);
    await shot(page, "assistant-recap-day", false);
    // 重新回顾 asks again, the same way.
    const again = taskPost(page);
    await task.getByRole("button", { name: "重新回顾", exact: true }).click();
    expect((await again).postDataJSON()).toEqual({ kind: "recap", context: { page: "writing" } });
    await finished(page, 2);
  });

  test("写前回顾按钮：草稿是第 1 章时禁用并说明原因", async ({ page }) => {
    await setup(page, false);
    const recap = button(page, "写前回顾");
    await expect(recap).toBeDisabled();
    await expect(recap).toHaveAttribute("title", "第一章前面没有内容可以回顾");
    // The server says the same, and charges nothing.
    const id = new URL(page.url()).pathname.split("/")[2];
    const before = await allowance(page);
    const refused = await api(page).raw("POST", `/projects/${id}/assistant/tasks`, { kind: "recap", context: { page: "writing" } });
    expect(refused.status).toBe(422);
    expect(refused.body.error.code).toBe("recap_nothing_before");
    await page.reload();
    expect(await allowance(page)).toBe(before);
  });

  test("写前回顾按钮：草稿没保存、有任务在运行时禁用并说明原因", async ({ page }) => {
    await setup(page);
    await expect(button(page, "写前回顾")).toBeEnabled();
    await setDraftBody(page, "温岚把黄铜罗盘放在窗边。");
    await expect(button(page, "写前回顾")).toBeDisabled();
    await expect(button(page, "写前回顾")).toHaveAttribute("title", "等草稿保存后再回顾");
    await button(page, "保存").click();
    await expect(button(page, "写前回顾")).toBeEnabled();
    await openAssistantTab(page);
    // (The empty conversation has a 写前回顾 button of its own; this is the one in the page's head.)
    const head = page.locator(".draft-head-actions").getByRole("button", { name: "写前回顾", exact: true });
    await ask(page, "E2E_SLOW 苏岑现在在哪？");
    await expect(head).toBeDisabled();
    await expect(head).toHaveAttribute("title", "上一个问题还在查");
    await finished(page);
    await expect(head).toBeEnabled();
  });

  test("对照计划的结果在助手标签顶部，可以收起；右栏只有两个标签", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const response = page.waitForResponse((r) => r.request().method() === "POST" && r.url().endsWith("/analyses"));
    await button(page, "对照计划").click();
    const rid = (await (await response).json()).data.run_id;
    await expect.poll(async () => (await api(page).get(`/projects/${id}/analyses/${rid}`)).status).toBe("completed");
    await expect(findings(page).getByRole("tab")).toHaveText([/^检查结果/, "助手"]);
    await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
    const block = thread(page).getByTestId("plan-block");
    await expect(block).toBeVisible();
    // It sits above the conversation, not under it.
    const [blockBox, taskBox] = [await block.boundingBox(), await tasks(page).first().boundingBox()];
    expect(blockBox!.y).toBeLessThan(taskBox!.y);
    await expect(block.getByRole("region", { name: "对照计划", exact: true })).toBeVisible();
    await block.getByRole("button", { name: "收起对照计划", exact: true }).click();
    await expect(block.getByRole("region", { name: "对照计划", exact: true })).toBeHidden();
    await expect(block.getByRole("button", { name: "展开", exact: true })).toBeVisible();
  });

  test("让助手给改法：请求不带 question；助手里是这一条和它的改法；没有改正文", async ({ page }) => {
    const { id, issue } = await checkedWork(page);
    const original = await readDraftBody(page);
    const { body, task } = await askForFix(page, issue);
    expect(body).toEqual({ kind: "fix_issue", context: { page: "writing", issue_id: issue.id } });
    // The finding on top: its number, its kind and its sentence.
    const head = task.locator(".a-issue");
    await expect(head.locator(".a-issue-num")).toHaveText("1");
    await expect(head.locator(".tag")).toBeVisible();
    await expect(head).toContainText(issue.explanation.split(/(?<=[。！？])/)[0]);
    await expect(task.getByText("（示意回答）检查结果指出这一句和前文对不上。")).toBeVisible();
    await expect(task.locator(".a-cite button")).toHaveCount(1);
    // Two ways out, each in its own block: the change and 这是有意的.
    await expect(task.locator("[data-proposal]")).toHaveCount(2);
    const edit = proposal(task, "edit_this");
    await expect(edit.getByText("改法 · 改本章这句", { exact: true })).toBeVisible();
    // Only the words that change are marked: the first character goes, six come in its place; the whole sentences are in the fold.
    await expect(edit.locator("del")).toHaveText("删去：苏");
    await expect(edit.locator("ins")).toHaveText("改为：（示意改法）");
    await edit.getByRole("button", { name: /^整句对照/ }).click();
    await expect(edit.locator(".a-whole-body .b")).toContainText(SENTENCE);
    await expect(edit.locator(".a-whole-body .f")).toContainText(REWRITTEN);
    await expect(edit.getByRole("button", { name: "采用", exact: true })).toBeEnabled();
    await expect(edit.getByRole("button", { name: "不用", exact: true })).toBeEnabled();
    await expect(proposal(task, "intentional").getByText("改法 · 这是有意的", { exact: true })).toBeVisible();
    await expect(proposal(task, "intentional").getByRole("button", { name: "标为有意为之", exact: true })).toBeEnabled();
    await expect(task).toContainText("计 500 字");
    expect(await readDraftBody(page)).toBe(original);
    expect((await draft(page, id)).body).toBe(original);
    await shot(page, "assistant-fix-before", false);
  });

  test("采用：编辑器里换成改后的句子，立即保存，再记为已采用；检查结果里出现小标签；撤销把原句换回来", async ({ page }) => {
    test.setTimeout(150_000);
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    const adopt = adoptRequest(page, "adopt");
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(REWRITTEN);
    // Adopting saves straight away instead of waiting for the idle autosave (5–30 s), and is recorded only after
    // that save: the request carries the saved revision, checked below.
    const adopted = await adopt;
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    const saved = await draft(page, id);
    expect(saved.body).toBe(REWRITTEN);
    expect(adopted.postDataJSON()).toEqual({ draft_revision: saved.revision });
    expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((p: any) => p.kind === "edit_this")).toMatchObject({ status: "adopted", adopted_draft_revision: saved.revision });
    // The findings list says so, and adopting is not the author's decision on the finding.
    await findingsTab(page).click();
    await expect(finding(page, issue.id)).toContainText("已采用助手改法");
    expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).decision).toBeFalsy();
    await sideTab(page).click();
    await shot(page, "assistant-fix-adopted", false);
    // 撤销 puts the old sentence back in the editor; once that is saved it is recorded.
    const undo = adoptRequest(page, "undo");
    await edit.getByRole("button", { name: "已采用 · 撤销", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(SENTENCE);
    await undo;
    await expect(edit.getByRole("button", { name: "采用", exact: true })).toBeEnabled({ timeout: 30_000 });
    expect((await draft(page, id)).body).toBe(SENTENCE);
    expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((p: any) => p.kind === "edit_this").status).toBe("proposed");
    await findingsTab(page).click();
    await expect(finding(page, issue.id)).not.toContainText("已采用助手改法");
  });

  test("采用前原句已经被改掉：采用按钮禁用并说明原因；可以按要求重新给改法", async ({ page }) => {
    const { issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    await setDraftBody(page, "完全不同的一句话。");
    const edit = proposal(task, "edit_this");
    await expect(edit.getByRole("button", { name: "采用", exact: true })).toBeDisabled();
    await expect(edit.getByText("原句已经改过，可以按要求重新给改法。", { exact: true })).toBeVisible();
    // 按要求重新给改法: a tag 「第 1 处」, another placeholder, and a question in the request.
    await task.getByRole("button", { name: "按要求重新给改法", exact: true }).click();
    await expect(chip(page, "第 1 处")).toBeVisible();
    await expect(box(page)).toHaveAttribute("placeholder", "对改法有什么要求？比如：保留苏岑的视角");
    const request = taskPost(page);
    await ask(page, "保留苏岑的视角");
    expect((await request).postDataJSON()).toEqual({ kind: "fix_issue", question: "保留苏岑的视角", context: { page: "writing", issue_id: issue.id } });
    await finished(page, 2);
    await expect(thread(page).locator(".a-chip")).toHaveCount(0);
    await expect(box(page)).toHaveAttribute("placeholder", "问这部作品里的人、事、物……");
    await expect(tasks(page).last()).toContainText("保留苏岑的视角");
  });

  test("不用：这条改法变灰并标「不用」，正文没动", async ({ page }) => {
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    await edit.getByRole("button", { name: "不用", exact: true }).click();
    await expect(edit).toHaveAttribute("data-status", "dismissed");
    await expect(edit.getByText("不用", { exact: true })).toBeVisible();
    await expect(edit.getByRole("button", { name: "采用", exact: true })).toHaveCount(0);
    expect((await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((p: any) => p.kind === "edit_this").status).toBe("dismissed");
    expect(await readDraftBody(page)).toBe(SENTENCE);
    // The other way out is still there.
    await expect(proposal(task, "intentional").getByRole("button", { name: "标为有意为之", exact: true })).toBeEnabled();
  });

  test("标为有意为之：检查结果里这一条记为「是有意的」", async ({ page }) => {
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    await proposal(task, "intentional").getByRole("button", { name: "标为有意为之", exact: true }).click();
    await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("keep_intentional");
    await expect(proposal(task, "intentional").getByText("已标为有意为之。", { exact: true })).toBeVisible();
    await findingsTab(page).click();
    await expect(finding(page, issue.id)).toContainText("已处理");
  });

  test("补前文：「去第 N 章 · 复制这句」复制并打开那一章", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const { issue } = await checkedWork(page, "苏岑拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST，E2E_SETUP。");
    const { task } = await askForFix(page, issue);
    const setup_ = proposal(task, "add_setup");
    await expect(setup_.getByText("改法 · 补第 1 章", { exact: true })).toBeVisible();
    await expect(setup_.locator("ins")).toContainText("（示意）前文补这一句。");
    await expect(setup_.getByText("前面已完成的章节不能一键改，请手动粘贴。", { exact: true })).toBeVisible();
    await expect(setup_.getByRole("button", { name: /^采用/ })).toHaveCount(0);
    await setup_.getByRole("button", { name: "复制这句，去第 1 章", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe("（示意）前文补这一句。");
    await expect(page).toHaveURL(/\/workspace\?chapter=1$/);
    await expect(page.getByRole("heading", { level: 1, name: /^第 1 章/ })).toBeAttached();
  });

  test("复查这一句：按 after 的字数计，显示复查结果；复查不改变检查结果的状态", async ({ page }) => {
    test.setTimeout(150_000);
    const { id, issue } = await checkedWork(page);
    const { task } = await askForFix(page, issue);
    const edit = proposal(task, "edit_this");
    // Not before the change is adopted.
    await expect(edit.getByRole("button", { name: /^复查这一句/ })).toHaveCount(0);
    await edit.getByRole("button", { name: "采用", exact: true }).click();
    await expect.poll(() => readDraftBody(page)).toBe(REWRITTEN);
    await expect(edit.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible({ timeout: 8_000 });
    const count = chars(REWRITTEN);
    const recheck = edit.getByRole("button", { name: `复查这一句 · 约 ${count} 字`, exact: true });
    await expect(recheck).toBeVisible();
    const before = await allowance(page);
    const request = adoptRequest(page, "recheck");
    await recheck.click();
    await request;
    // One of the two answers, with the finding's kind, explanation and the passage it rests on when there is a problem.
    const result = edit.locator(".a-recheck");
    await expect(result).toContainText(/复查没有发现问题|复查发现 \d+ 处问题/, { timeout: 30_000 });
    await expect.poll(() => allowance(page)).toBe(before - count);
    const saved = (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0].proposals.find((p: any) => p.kind === "edit_this");
    expect(["clean", "issues"]).toContain(saved.recheck.status);
    if (saved.recheck.status === "issues") {
      await expect(result.locator(".tag").first()).toBeVisible();
      await expect(result.locator(".a-evidence li").first()).toContainText(/第 \d+ 章/);
    }
    await shot(page, "assistant-recheck", false);
    // Not the author's decision: the finding keeps the state it had.
    expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).decision).toBeFalsy();
  });

  test("访客：看不到「复查这一句」和「查前文矛盾」", async ({ page }) => {
    await startVisitor(page);
    const id = await sampleWorkId(page);
    // The sample's own finding gets a fix by the API; the visitor adopts it the way the page would (edit, save, record).
    const target = (await run(page, id)).issues.find((item: any) => item.suggested_revision);
    const created = await api(page).post(`/projects/${id}/assistant/tasks`, { kind: "fix_issue", context: { page: "writing", issue_id: target.id } });
    await expect.poll(async () => (await api(page).get(`/projects/${id}/assistant/tasks/${created.id}`)).status).toBe("completed");
    const fix = await api(page).get(`/projects/${id}/assistant/tasks/${created.id}`);
    const edit = fix.proposals.find((item: any) => item.kind === "edit_this");
    const current = await draft(page, id);
    await api(page).patch(`/projects/${id}/drafts/${current.id}`, { base_revision: current.revision, title: current.title, body: current.body.replace(edit.before, edit.after), body_format: current.body_format });
    await api(page).post(`/projects/${id}/assistant/tasks/${created.id}/proposals/${edit.id}/adopt`, { draft_revision: current.revision + 1 });
    await openTab(page, id, "workspace");
    await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
    await openAssistantTab(page);
    const adopted = proposal(tasks(page).first(), "edit_this");
    await expect(adopted.getByRole("button", { name: "已采用 · 撤销", exact: true })).toBeVisible();
    await expect(adopted.getByRole("button", { name: /^复查这一句/ })).toHaveCount(0);
    // The server says no to the visitor as well.
    const refused = await api(page).raw("POST", `/projects/${id}/assistant/tasks/${created.id}/proposals/${edit.id}/recheck`, {});
    expect(refused.status).toBe(403);
    expect(refused.body.error.code).toBe("assistant_check_visitor_forbidden");
    // The bar over picked words has no third button.
    await select(page, "#draft-body", 12);
    await expect(toolbar(page)).toBeVisible();
    await expect(toolbar(page).getByRole("button")).toHaveCount(2);
    await expect(toolbar(page).getByRole("button", { name: /^查前文矛盾/ })).toHaveCount(0);
  });

  test("状态变化的条目：按钮叫「让助手解释」，结果里没有改法", async ({ page }) => {
    const id = await setup(page);
    await saveBody(page, id, "温岚把黄铜罗盘放在档案室的桌上，E2E_STATE。");
    const result = await finishCheck(page, id, await beginCheck(page, id));
    const issue = result.issues.find((item: any) => item.nature === "state_change");
    expect(issue, JSON.stringify(result.issues)).toBeTruthy();
    await selectIssue(page, issue);
    await expect(findings(page).getByRole("button", { name: "让助手给改法", exact: true })).toHaveCount(0);
    const request = taskPost(page);
    await findings(page).getByRole("button", { name: "让助手解释", exact: true }).click();
    expect((await request).postDataJSON()).toEqual({ kind: "fix_issue", context: { page: "writing", issue_id: issue.id } });
    await finished(page);
    const task = tasks(page).last();
    await expect(task.getByText("解释这一处", { exact: true })).toBeVisible();
    await expect(task.getByText("（示意）这是状态变化，不是错误。")).toBeVisible();
    await expect(task.locator("[data-proposal]")).toHaveCount(0);
  });

  test("草稿在检查之后改过：「让助手给改法」禁用并说明原因；示例结果也不能交给助手", async ({ page }) => {
    const { issue } = await checkedWork(page);
    await setDraftBody(page, "检查之后改过的草稿。");
    await selectIssue(page, issue);
    const give = findings(page).getByRole("button", { name: "让助手给改法", exact: true });
    await expect(give).toBeDisabled();
    await expect(give).toHaveAttribute("title", "草稿在检查之后改过，再检查一次后再让助手给改法");
    await expect(findings(page).getByText(/草稿在检查之后改过，这一条针对的是先前的正文/)).toBeVisible();
  });

  test("示例结果不能交给助手：按钮禁用并说明原因", async ({ page }) => {
    const id = await setup(page);
    const issue = (await run(page, id)).issues[0];
    await selectIssue(page, issue);
    const give = findings(page).getByRole("button", { name: "让助手给改法", exact: true });
    await expect(give).toBeDisabled();
    await expect(give).toHaveAttribute("title", "示例结果不能交给助手，先再检查一次");
    await expect(findings(page).getByText("示例结果不能交给助手，先再检查一次。", { exact: true })).toBeVisible();
  });

  test("选中草稿里的文字：「查前文矛盾 · 约 N 字」发起检查，请求体带 intent；步骤里有定点检查", async ({ page }) => {
    await setup(page);
    await select(page, "#draft-body", 12);
    const picked = (await selectedWords(page)).trim();
    const check = toolbar(page).getByRole("button", { name: /^查前文矛盾/ });
    await expect(check).toBeVisible();
    await expect(check).toHaveText(`查前文矛盾 · 约 ${500 + chars(picked)} 字`);
    const before = await allowance(page);
    const request = taskPost(page);
    await check.click();
    const body = (await request).postDataJSON();
    expect(body).toMatchObject({ kind: "ask", question: "这段和前文有没有矛盾？", context: { page: "writing", selection: picked, intent: "check_selection" } });
    await expect(sideTab(page)).toHaveAttribute("aria-selected", "true");
    await finished(page);
    const task = tasks(page).first();
    await expect(task.getByText("查前文矛盾", { exact: true })).toBeVisible();
    await task.getByRole("button", { name: /^查了 \d+ 处/ }).click();
    await expect(task.getByText("定点检查了这一段")).toBeVisible();
    // The sentence is in the answer: either the first source of the check, or that it found nothing.
    await expect(task).toContainText(/（示意回答）选中的这段和前文有对不上的地方。|（示意）检查了选中的这段，没有发现和前文矛盾的地方。/);
    await expect(task).toContainText(/计 \d+ 字/);
    await expect.poll(() => allowance(page)).toBe(before - 500 - chars(picked));
  });

  test("窄屏：检查结果窗格和助手窗格都没有内层标签，Tab 不会落到看不见的元素上", async ({ page }) => {
    await checkedWork(page);
    await page.setViewportSize({ width: 375, height: 812 });
    const panes = page.getByRole("navigation", { name: "切换内容", exact: true });
    for (const name of [/^检查结果/, "助手"]) {
      await panes.getByRole("button", { name }).click();
      await expect(page.locator(".side-tabs")).toBeHidden();
      await expect(findings(page).getByRole("tab")).toHaveCount(0);
      await page.locator("body").click({ position: { x: 1, y: 1 } });
      for (let i = 0; i < 40; i++) {
        await page.keyboard.press("Tab");
        const state = await page.evaluate(() => {
          const element = document.activeElement as HTMLElement | null;
          return { inStrip: Boolean(element?.closest(".side-tabs")), shown: !element || element === document.body || element.getClientRects().length > 0 };
        });
        expect(state).toEqual({ inStrip: false, shown: true });
      }
    }
  });

  test("手机宽度：助手窗格里的改法", async ({ page }) => {
    const { id, issue } = await checkedWork(page);
    await api(page).post(`/projects/${id}/assistant/tasks`, { kind: "fix_issue", context: { page: "writing", issue_id: issue.id } });
    await expect.poll(async () => (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0]?.status).toBe("completed");
    await page.setViewportSize({ width: 375, height: 812 });
    await openTab(page, id, "workspace");
    await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    const task = tasks(page).first();
    await expect(proposal(task, "edit_this")).toBeVisible();
    // A phone cannot change the draft: the adopt button says why.
    await expect(proposal(task, "edit_this").getByRole("button", { name: "采用", exact: true })).toBeDisabled();
    await expect(proposal(task, "edit_this")).toContainText("这个屏幕太窄，不能改正文");
    expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBeLessThanOrEqual(375);
    await proposal(task, "edit_this").scrollIntoViewIfNeeded();
    await shot(page, "assistant-phone-fix", false);
  });

  test("axe：带写前回顾结果和带改法的助手标签，日夜各扫一次", async ({ page }, info) => {
    const { id, issue } = await checkedWork(page);
    await api(page).post(`/projects/${id}/assistant/tasks`, { kind: "recap", context: { page: "writing" } });
    await expect.poll(async () => (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[0]?.status).toBe("completed");
    await api(page).post(`/projects/${id}/assistant/tasks`, { kind: "fix_issue", context: { page: "writing", issue_id: issue.id } });
    await expect.poll(async () => (await api(page).get(`/projects/${id}/assistant/tasks`)).tasks[1]?.status).toBe("completed");
    const results: { theme: string; violations: unknown[] }[] = [];
    for (const value of ["day", "night"] as const) {
      await openTab(page, id, "workspace");
      await theme(page, value);
      await openAssistantTab(page);
      await finished(page, 2);
      await expect.poll(() => page.evaluate(() => document.getAnimations().filter((a) => a.playState === "running" && a.effect?.getComputedTiming().iterations !== Infinity).length)).toBe(0);
      const found = await new AxeBuilder({ page }).analyze();
      results.push({ theme: value, violations: found.violations.filter((v) => ["critical", "serious"].includes(v.impact ?? "")).map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.map((n) => ({ target: n.target, summary: n.failureSummary })) })) });
      await tasks(page).first().scrollIntoViewIfNeeded();
      await shot(page, `assistant-recap-${value}`, false);
      await tasks(page).last().scrollIntoViewIfNeeded();
      await shot(page, `assistant-fix-${value}`, false);
    }
    await evidence(info, "assistant-05b-axe-results", results);
    expect(results.filter((r) => r.violations.length), JSON.stringify(results, null, 2)).toEqual([]);
  });
});
