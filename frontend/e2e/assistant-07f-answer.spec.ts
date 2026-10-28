import type { Page } from "@playwright/test";
import { api, expect, openTab, registerAccount, sampleWorkId, shot, test } from "./support/app";
import { ask, finished, openAssistantTab, tasks, thread } from "./support/assistant";
import { askView, serveTasks } from "./support/assistant-mock";
import { setup } from "./support/writing";

// 07f, the answer and what sits under it: a tap on a mark on a phone (02), what a search turned up (04), the sources coming in after
// the sentences (08), the row of actions that does not jump (09), the ring after the scroll (12), earlier answers (17), the size of
// a mark's target (20), what asking again costs (22), a stopped task (24), thanks (25), a fact's card and its way to the words (33),
// and who has seen the privacy note (27).

const hours = (page: Page) => page.emulateMedia({ reducedMotion: "no-preference" });
const colourOf = (page: Page, value: string) => page.evaluate((expression) => {
  const probe = document.createElement("i");
  probe.style.color = expression;
  document.body.append(probe);
  const colour = getComputedStyle(probe).color;
  probe.remove();
  return colour;
}, value);
/** The chapters of the work with their text, as the reading page shows them. */
const chaptersOf = async (page: Page, id: string) => (await api(page).get(`/projects/${id}/long-term-review`)).chapters as { number: number; title: string; body: string }[];
/** The mock answer: one sentence citing the given source. */
const citing = (ref: string, sources: Record<string, unknown>, over: Record<string, unknown> = {}) =>
  askView({ sources, answer: { status: "answered", sentences: [{ text: "前文写过这件事。", refs: [ref] }], note: null }, steps: [], ...over });

test.describe("07f 回答", () => {
  test("02 手机上点按角标：卡片不会自己收起（等 1 秒仍在），再点一次才收起，点别处也收起", async ({ browser }) => {
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 }, hasTouch: true, isMobile: true });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "tap");
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
    // The browser sends a mouse-over and a mouse-out after a tap; they must not shut the card.
    await phone.waitForTimeout(1000);
    await expect(card).toBeVisible();
    await expect(cite).toHaveAttribute("aria-expanded", "true");
    await cite.tap();
    await expect(card).toHaveCount(0);
    await phone.waitForTimeout(600);
    await expect(card).toHaveCount(0);
    await cite.tap();
    await expect(card).toBeVisible();
    await task.locator(".a-answer").tap({ position: { x: 4, y: 4 } });
    await expect(card).toHaveCount(0, { timeout: 2_000 });
    await context.close();
  });

  test("20 引用角标的可点区域至少 24×24，角标本身和行高不变", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const cite = tasks(page).first().locator(".a-cite button").first();
    const [visible, target] = await cite.evaluate((node) => {
      const after = getComputedStyle(node, "::after");
      return [node.getBoundingClientRect().height, [parseFloat(after.width), parseFloat(after.height)]] as const;
    });
    expect(visible).toBeLessThan(16);
    expect(target[0]).toBeGreaterThanOrEqual(24);
    expect(target[1]).toBeGreaterThanOrEqual(24);
  });

  test("04 展开「搜了 N 处正文」：每个片段一行半左右（命中词前后各约 18 字，没有命中词取开头 42 字），后面跟章节名，点章节名去原文", async ({ page }) => {
    await setup(page);
    const long = `${"他走进仓道，雨水顺着帽檐往下淌。".repeat(8)}那枚罗盘静静地躺在抽屉里。${"窗外的潮声一阵接着一阵，没有停的意思。".repeat(8)}`;
    const plain = "老周站在高台上看着远处的灯，".repeat(20);
    const view = askView();
    await serveTasks(page, () => [askView({ sources: { ...view.sources, R2: { ...(view.sources as any).R2, text: long }, R4: { ...(view.sources as any).R4, text: plain } } })]);
    await page.reload();
    await openAssistantTab(page);
    const task = tasks(page).first();
    await task.getByRole("button", { name: "怎么查的" }).click();
    await task.getByRole("button", { name: /^搜了 2 处正文/ }).click();
    const found = task.locator(".a-found p");
    const around = found.nth(0).locator(".snip");
    const text = (await around.innerText()).trim();
    expect(text.startsWith("…")).toBe(true);
    expect(text.endsWith("…")).toBe(true);
    expect(text).toContain("罗盘");
    expect(Array.from(text).length).toBeLessThanOrEqual(18 + 2 + 18 + 2 + 2);
    expect(Array.from(text).length).toBeLessThan(Array.from(long).length / 2);
    // No searched word in it (the third one is for 抽屉 and says nothing of it): the opening, 42 characters.
    const opening = (await found.nth(2).locator(".snip").innerText()).trim();
    expect(Array.from(opening).length).toBeLessThanOrEqual(43);
    expect(opening.endsWith("…")).toBe(true);
    expect(plain.startsWith(opening.replace(/…$/, ""))).toBe(true);
    // The chapter comes after the words, and takes the author to the original.
    await expect(found.nth(0).locator(".a-from").first()).toContainText("第 9 章");
    expect(await found.nth(0).evaluate((node) => node.getBoundingClientRect().height)).toBeLessThan(120);
    await shot(page, "07f-04-found", false);
    await found.nth(0).getByRole("button", { name: /第 9 章/ }).click();
    await expect(page).toHaveURL(/\/workspace\?chapter=9$/);
  });

  test("08 回答新出现时，出处列表、「查过 / 没查」和操作行在最后一句开始淡入后再一起淡入；减少动态效果时直接显示", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await hours(page);
    await ask(page, "E2E_TWO 苏岑知道罗盘被调包了吗？");
    await finished(page);
    const rest = tasks(page).first().locator(".a-rest.a-fade");
    await expect(rest).toHaveCount(1);
    expect(await rest.evaluate((node) => getComputedStyle(node).animationName)).toBe("a-appear");
    expect(await rest.evaluate((node) => getComputedStyle(node).animationDelay)).toBe("0.24s");
    await expect(rest.locator(".a-sources-wrap")).toBeAttached();
    await expect(rest.locator(".a-foot")).toBeAttached();
    await page.emulateMedia({ reducedMotion: "reduce" });
    expect(await rest.evaluate((node) => getComputedStyle(node).animationName)).toBe("none");
    await page.reload();
    await openAssistantTab(page);
    await expect(tasks(page).first().locator(".a-rest")).toHaveCount(1);
    await expect(tasks(page).first().locator(".a-rest.a-fade")).toHaveCount(0);
  });

  test("09 「已复制」不让整行跳：计字和按钮不动；点「没用」时原因出现在操作行下方", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const foot = tasks(page).first().locator(".a-foot");
    const places = () => foot.evaluate((node) => Array.from(node.querySelectorAll<HTMLElement>(":scope > .a-link, :scope > .a-regen, :scope > .a-thumbs, :scope > .a-cost-line")).map((item) => { const box = item.getBoundingClientRect(); return [Math.round(box.x), Math.round(box.y)]; }));
    const before = await places();
    await foot.getByRole("button", { name: "复制", exact: true }).click();
    await expect(foot.getByRole("button", { name: "已复制", exact: true })).toBeVisible();
    expect(await places()).toEqual(before);
    await expect(foot.getByRole("button", { name: "复制", exact: true })).toBeVisible({ timeout: 4_000 });
    await foot.getByRole("button", { name: "没用", exact: true }).click();
    const reasons = foot.getByRole("group", { name: "哪里不好" });
    await expect(reasons).toBeVisible();
    expect(await places()).toEqual(before);
    const [row, why] = [await foot.locator(".a-thumbs").boundingBox(), await reasons.boundingBox()];
    expect(why!.y).toBeGreaterThan(row!.y + row!.height - 1);
  });

  test("12 去原文：等页面滚完再闪（闪的时候位置已经不动）", async ({ page }) => {
    const id = await setup(page);
    await openAssistantTab(page);
    await hours(page);
    await ask(page, "E2E_PASSAGE 苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const cite = task.locator(".a-cite button").first();
    await cite.hover();
    await task.getByRole("button", { name: "去原文 →" }).click();
    const ring = page.locator("#chapter-body .mark-pulse");
    await expect(ring).toBeAttached({ timeout: 6_000 });
    const [first, later] = [await page.evaluate(() => window.scrollY), await page.evaluate(() => new Promise<number>((resolve) => window.setTimeout(() => resolve(window.scrollY), 250)))];
    expect(later).toBe(first);
    await expect(ring.first()).toBeInViewport();
    expect(id).toBeTruthy();
  });

  test("17 旧回答和当前回答分得清：折叠行有 ›（展开变 ⌃），展开后缩进加细线、颜色降一级；「已改问」同样、不再变淡", async ({ page }) => {
    await setup(page);
    const old = askView({ id: "atask-old" });
    const current = askView({ id: "atask-new", regenerated_from: "atask-old" });
    const first = askView({ id: "atask-q1", question: "旧的问法", created_at: new Date(Date.now() - 600_000).toISOString() });
    const second = askView({ id: "atask-q2", question: "新的问法", edited_from: "atask-q1" });
    await serveTasks(page, () => [first, old, current, second]);
    await page.reload();
    await openAssistantTab(page);
    const entry = tasks(page).filter({ has: page.locator("details.a-older") }).first();
    const summary = entry.locator("details.a-older > summary");
    await expect(summary).toHaveText("之前的回答 · 1");
    const mark = (node: Element) => getComputedStyle(node, "::after").content;
    expect(await summary.evaluate(mark)).toBe('" ›"');
    await summary.click();
    expect(await summary.evaluate(mark)).toBe('" ⌃"');
    const body = entry.locator("details.a-older > .a-fold-body");
    const style = await body.evaluate((node) => { const css = getComputedStyle(node); return { left: css.marginLeft, rule: css.borderLeftWidth, colour: css.borderLeftColor }; });
    expect(style.left).toBe("10px");
    expect(style.rule).toBe("2px");
    expect(style.colour).toBe(await colourOf(page, "var(--c-line)"));
    const [older, newer] = [await body.locator(".a-answer").first().evaluate((node) => getComputedStyle(node).color), await entry.locator(":scope > .a-task .a-answer").first().evaluate((node) => getComputedStyle(node).color)];
    expect(older).toBe(await colourOf(page, "var(--c-ink-2)"));
    expect(older).not.toBe(newer);
    await shot(page, "07f-17-older", false);
    // A reworded question folds the same way, and is no longer faded.
    const reworded = tasks(page).filter({ has: page.locator("summary", { hasText: /^已改问/ }) }).first();
    const fold = reworded.locator(":scope > summary");
    expect(await fold.evaluate(mark)).toBe('" ›"');
    expect(await reworded.evaluate((node) => getComputedStyle(node).opacity)).toBe("1");
    await fold.click();
    expect(await fold.evaluate(mark)).toBe('" ⌃"');
    await expect(reworded.locator(":scope > .a-fold-body")).toBeVisible();
  });

  test("22 重新回答的估价按原任务：查前文矛盾按它的字数；24 停止后正文写计了多少字；21 作品以外不再给「重新回答」", async ({ page }) => {
    await setup(page);
    const selection = "甲乙丙丁戊己庚辛壬癸";
    await serveTasks(page, () => [
      askView({ id: "atask-check", context: { page: "writing", chapter_number: 11, selection, intent: "check_selection" } }),
      askView({ id: "atask-stop1", status: "cancelled", answer: null, coverage: null, sources: {}, usage: { steps: 1, chars_charged: 515 }, question: "停在中途的问题" }),
      askView({ id: "atask-stop2", status: "cancelled", answer: null, coverage: null, sources: {}, usage: { steps: 0, chars_charged: 0 }, question: "还没开始就停了" }),
      askView({ id: "atask-off", question: "写一首诗", answer: { status: "out_of_scope", sentences: [], note: null }, sources: {}, steps: [], coverage: null }),
    ]);
    await page.reload();
    await openAssistantTab(page);
    await expect(tasks(page).nth(0).locator(".a-regen .a-hint")).toHaveText("约 510 字");
    // 24: one line, once.
    const [stopped, free] = [tasks(page).nth(1), tasks(page).nth(2)];
    await expect(stopped.getByText("已停止，计 515 字", { exact: true })).toBeVisible();
    await expect(free.getByText("已停止，没有计字数", { exact: true })).toBeVisible();
    await expect(stopped.getByText("已停止。", { exact: true })).toHaveCount(0);
    // 21.
    await expect(tasks(page).nth(3).getByRole("button", { name: "重新回答", exact: true })).toHaveCount(0);
    await expect(tasks(page).nth(3).locator(".a-fixed")).toBeVisible();
  });

  test("25 有用 / 没用：图标有 title；点「有用」出现短暂的「谢谢」；「谢谢」和「已记下，谢谢。」都是灰字，不是链接蓝", async ({ page }) => {
    await setup(page);
    await openAssistantTab(page);
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    const task = tasks(page).first();
    const up = task.getByRole("button", { name: "有用", exact: true });
    const down = task.getByRole("button", { name: "没用", exact: true });
    await expect(up).toHaveAttribute("title", "有用");
    await expect(down).toHaveAttribute("title", "没用");
    const muted = await colourOf(page, "var(--c-muted)");
    await up.click();
    const thanks = task.locator(".a-noted", { hasText: /^谢谢$/ });
    await expect(thanks).toBeVisible();
    expect(await thanks.evaluate((node) => getComputedStyle(node).color)).toBe(muted);
    await expect(thanks).toHaveCount(0, { timeout: 5_000 });
    await expect(up).toHaveAttribute("aria-pressed", "true");
    await down.click();
    await task.getByRole("group", { name: "哪里不好" }).getByRole("button", { name: "啰嗦", exact: true }).click();
    const noted = task.locator(".a-noted", { hasText: "已记下，谢谢。" });
    await expect(noted).toBeVisible({ timeout: 4_000 });
    expect(await noted.evaluate((node) => getComputedStyle(node).color)).toBe(muted);
  });
});

test.describe("07f 事实的出处", () => {
  test("33 事实类出处标「事实摘要 · 第 N 章」；去原文用来源段落定位并闪一下；找不到时说明；底部出处列表的章名同样去阅读页并定位", async ({ page }) => {
    const id = await setup(page);
    const chapter = (await chaptersOf(page, id)).find((item) => item.number === 9)!;
    const lines = chapter.body.split(/\n+/).map((line) => line.trim()).filter((line) => line.length > 20);
    const fact = (anchor: unknown) => ({
      R1: { kind: "fact", chapter_number: 9, chapter_title: chapter.title, start: null, end: null, text: "苏岑：把罗盘交给温岚保管", cited: true, anchor },
      R2: { kind: "passage", chapter_number: 9, chapter_title: chapter.title, start: 0, end: 30, text: lines[1].slice(0, 40), cited: true },
    });
    let current: unknown = { text: lines[0].slice(0, 60), chapter_number: 9 };
    await serveTasks(page, () => [citing("R1", fact(current))]);
    await page.reload();
    await openAssistantTab(page);
    await hours(page);
    const task = tasks(page).first();
    const cite = task.locator(".a-cite button").first();
    await cite.hover();
    await expect(task.locator(".a-pop .w")).toHaveText("事实摘要 · 第 9 章");
    await shot(page, "07f-33-fact-card", false);
    await task.getByRole("button", { name: "去原文 →" }).click();
    await expect(page).toHaveURL(/\/workspace\?chapter=9$/);
    await expect(page.locator("#chapter-body .mark-pulse")).toBeAttached({ timeout: 6_000 });
    await expect(page.locator(".feedback")).toHaveCount(0);
    // The words are not in the chapter (or the fact has no source passage): the chapter opens and the page says so.
    for (const anchor of [{ text: "这句话在第九章里根本没有出现过。", chapter_number: 9 }, null]) {
      current = anchor;
      await openTab(page, id, "workspace");
      await openAssistantTab(page);
      await tasks(page).first().locator(".a-cite button").first().hover();
      await tasks(page).first().getByRole("button", { name: "去原文 →" }).click();
      await expect(page).toHaveURL(/\/workspace\?chapter=9$/);
      await expect(page.locator(".feedback")).toContainText("没在第 9 章找到对应的原句，已打开这一章", { timeout: 6_000 });
      await expect(page.locator("#chapter-body .mark-pulse")).toHaveCount(0);
      if (anchor) await shot(page, "07f-33-not-found", false);
    }
    // The chapter name under the answer: the reading page, with the passage rung (not the chapter list).
    current = { text: lines[0].slice(0, 60), chapter_number: 9 };
    await serveTasks(page, () => [citing("R2", fact(current))]);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    // The list of sources is folded to one line; each source is one line that opens to its words and the way to the original.
    await tasks(page).first().getByRole("button", { name: /^出处 \d+ 处/ }).click();
    await tasks(page).first().locator(".a-sources .a-where").first().click();
    await tasks(page).first().locator(".a-sources").getByRole("button", { name: "去原文 →" }).first().click();
    await expect(page).toHaveURL(/\/workspace\?chapter=9$/);
    await expect(page.locator("#chapter-body .mark-pulse")).toBeAttached({ timeout: 6_000 });
  });
});

test.describe("07f 隐私说明", () => {
  test("27 首次提示等作者发出第一问之后才记为已看过；登录页的访客入口有「隐私说明」链接", async ({ page, browser }) => {
    await setup(page);
    await openAssistantTab(page);
    const key = "story-continuity:assistant-privacy-seen";
    await expect(thread(page).locator(".a-privacy")).toBeVisible();
    // Looking at the panel is not enough: it is still unseen after a reload.
    expect(await page.evaluate((name) => localStorage.getItem(name), key)).toBeNull();
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).locator(".a-privacy")).toBeVisible();
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    expect(await page.evaluate((name) => localStorage.getItem(name), key)).toBe("1");
    await page.reload();
    await openAssistantTab(page);
    await expect(thread(page).locator(".a-privacy")).toHaveCount(0);
    // The login page: the visitor's way in names the privacy page.
    const guest = await browser.newContext({ baseURL: process.env.E2E_BASE_URL });
    const login = await guest.newPage();
    await login.goto("/login");
    const link = login.locator(".auth-visitor").getByRole("link", { name: "隐私说明" });
    await expect(link).toHaveAttribute("href", "/privacy");
    await shot(login, "07f-27-login", false);
    await guest.close();
  });
});
