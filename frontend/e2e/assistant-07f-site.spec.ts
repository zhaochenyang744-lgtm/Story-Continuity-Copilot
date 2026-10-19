import type { Page } from "@playwright/test";
import { accountMenuButton, api, expect, openAccountMenu, openTab, registerAccount, sampleWorkId, shot, startVisitor, test } from "./support/app";
import { ask, box, finished, openAssistantTab, sideTab, tasks, thread, topbarAssistant } from "./support/assistant";
import { fixView, proposalView, serveTasks } from "./support/assistant-mock";
import { theme } from "./support/pages";
import { findings, setup } from "./support/writing";

// 07f, the rest: a change that asks for an earlier chapter (13) and the words of a refused sentence (14), the keyboard's way to the box
// (19), what the sample's results do not claim (18), the empty conversation (15, 23), the page around it (06, 07, 26, 29, 30, 34, 35),
// and the assistant on a phone (31).

const setRollout = (page: Page, mode: string) => api(page).post(`/test/v180/assistant-rollout/${mode}`);
const motion = (page: Page) => page.emulateMedia({ reducedMotion: "no-preference" });
const colourOf = (page: Page, value: string) => page.evaluate((expression) => {
  const probe = document.createElement("i");
  probe.style.color = expression;
  document.body.append(probe);
  const colour = getComputedStyle(probe).color;
  probe.remove();
  return colour;
}, value);
const chaptersOf = async (page: Page, id: string) => (await api(page).get(`/projects/${id}/long-term-review`)).chapters as { number: number; title: string; body: string }[];

test.describe("07f 改法", () => {
  test("13 补铺垫：显示位置句（没有时写放在第 N 章合适的位置）；「复制这句，去第 N 章」后滚到那一句并闪一下，提示条说粘到哪里；有「不用」", async ({ page, context }) => {
    await context.grantPermissions(["clipboard-read", "clipboard-write"]);
    const id = await setup(page);
    const first = (await chaptersOf(page, id)).find((item) => item.number === 1)!;
    const anchor = first.body.split(/\n+/).map((line) => line.trim()).find((line) => line.length > 12)!.split("。")[0] + "。";
    const added = "（示意）前文补这一句。";
    let proposals = [proposalView({ id: "aprop-setup", proposal: "P2", kind: "add_setup", chapter_number: 1, before: anchor, after: added })];
    await serveTasks(page, () => [fixView(proposals)]);
    await page.route("**/proposals/aprop-setup/dismiss", (route) => route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify({ data: proposalView({ id: "aprop-setup", proposal: "P2", kind: "add_setup", chapter_number: 1, before: anchor, after: added, status: "dismissed" }), request_id: "mock" }) }));
    await page.reload();
    await openAssistantTab(page);
    await motion(page);
    const option = tasks(page).first().locator('[data-kind="add_setup"]');
    await expect(option.locator(".a-setup-at")).toContainText(anchor);
    await expect(option.locator("ins")).toContainText(added);
    await expect(option.getByText("前面已完成的章节不能一键改，请手动粘贴。", { exact: true })).toBeVisible();
    await expect(option.getByText("前面的章节这一阶段不能一键改。")).toHaveCount(0);
    await expect(option.getByRole("button", { name: "不用", exact: true })).toBeVisible();
    await shot(page, "07f-13-setup", false);
    await option.getByRole("button", { name: "复制这句，去第 1 章", exact: true }).click();
    expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(added);
    await expect(page).toHaveURL(/\/workspace\?chapter=1$/);
    await expect(page.locator(".feedback")).toContainText("已复制，粘到这一句后面", { timeout: 6_000 });
    await expect(page.locator("#chapter-body .mark-pulse")).toBeAttached({ timeout: 6_000 });
    await shot(page, "07f-13-after", false);
    // No sentence to point at: the card says where, and so does the message on the chapter.
    proposals = [proposalView({ id: "aprop-setup", proposal: "P2", kind: "add_setup", chapter_number: 1, before: "", after: added })];
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const bare = tasks(page).first().locator('[data-kind="add_setup"]');
    await expect(bare.locator(".a-setup-at")).toHaveText("放在第 1 章合适的位置");
    await bare.getByRole("button", { name: "复制这句，去第 1 章", exact: true }).click();
    await expect(page.locator(".feedback")).toContainText("已复制，请粘到第 1 章合适的位置", { timeout: 6_000 });
    // 不用 puts the proposal away through the existing dismiss call.
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const request = page.waitForRequest((r) => r.method() === "POST" && /\/proposals\/aprop-setup\/dismiss$/.test(r.url()));
    await tasks(page).first().locator('[data-kind="add_setup"]').getByRole("button", { name: "不用", exact: true }).click();
    await request;
    await expect(tasks(page).first().locator('[data-kind="add_setup"]')).toHaveClass(/dismissed/);
  });

  test("14 改一改不合格：一种情况一句话（和原句一样 / 原样留着原句 / 太长写出最多几个字 / 为空）；和原句相同时不显示「已手改」", async ({ page }) => {
    await setup(page);
    const view = proposalView();
    await serveTasks(page, () => [fixView([view])]);
    await page.reload();
    await openAssistantTab(page);
    const option = tasks(page).first().locator('[data-kind="edit_this"]');
    await option.getByRole("button", { name: "改一改", exact: true }).click();
    const editBox = option.getByRole("textbox", { name: "改后的句子", exact: true });
    const before = view.before as string;
    const problem = option.locator(".a-why.a-warn");
    await editBox.fill(before);
    await expect(problem).toHaveText("和原句一样，还没有改动。");
    await expect(option.locator(".a-edited")).toHaveCount(0);
    await editBox.fill(`${before}再补一句。`);
    await expect(problem).toHaveText("改后的句子里原样留着原句，请把原句改掉。");
    const most = Array.from(before).length * 2 + 60;
    await editBox.fill("字".repeat(most + 1));
    await expect(problem).toHaveText(`比原句长太多，最多 ${most} 字。`);
    await editBox.fill("字".repeat(most));
    await expect(problem).toHaveCount(0);
    await editBox.fill("");
    await expect(problem).toHaveText("改后的句子不能为空。");
    await shot(page, "07f-14-problem", false);
  });

  test("18 示例作品预先放好的检查结果：底部不写「检查结果由 AI 生成」", async ({ page }) => {
    await setup(page);
    await expect(findings(page).getByText("示例结果", { exact: true })).toBeVisible();
    await expect(page.getByTestId("ai-note")).toHaveCount(0);
  });
});

test.describe("07f 键盘", () => {
  test("19 点「助手」标签把光标放进输入框（方向键切换不抢焦点）；对话区最前面有只在键盘聚焦时出现的「跳到输入框」；关着的引用卡片里没有「去原文」", async ({ page }) => {
    await setup(page);
    await sideTab(page).click();
    await expect(box(page)).toBeFocused();
    await ask(page, "苏岑知道罗盘被调包了吗？");
    await finished(page);
    // The arrow keys move between the tabs without pulling the cursor away from them.
    await sideTab(page).focus();
    await page.keyboard.press("ArrowLeft");
    await expect(findings(page).getByRole("tab", { name: /^检查结果/ })).toBeFocused();
    await page.keyboard.press("ArrowRight");
    await expect(sideTab(page)).toBeFocused();
    // From the 更多 menu, one Tab reaches the link that jumps to the box; it can be seen only then.
    const skip = thread(page).getByRole("button", { name: "跳到输入框", exact: true });
    await expect(skip).toBeAttached();
    expect((await skip.boundingBox())!.width).toBeLessThanOrEqual(1);
    await thread(page).locator(".a-bar summary").focus();
    await page.keyboard.press("Tab");
    await expect(skip).toBeFocused();
    expect((await skip.boundingBox())!.width).toBeGreaterThan(40);
    await page.keyboard.press("Enter");
    await expect(box(page)).toBeFocused();
    // The card's way to the original is in the page only while the card is open.
    const task = tasks(page).first();
    await expect(task.getByRole("button", { name: "去原文 →" })).toHaveCount(0);
    await task.locator(".a-cite button").first().focus();
    await expect(task.getByRole("button", { name: "去原文 →" })).toHaveCount(1);
    await page.keyboard.press("Escape");
    await expect(task.getByRole("button", { name: "去原文 →" })).toHaveCount(0);
  });

  test("19b 其他页的抽屉打开时光标在输入框里", async ({ page }) => {
    const id = await setup(page);
    await openTab(page, id, "overview");
    await topbarAssistant(page).click();
    await expect(box(page)).toBeFocused();
  });
});

test.describe("07f 空对话和全站", () => {
  test("15 访客的建议问题按示例草稿实际计次，算法和注册用户相同；23 空对话的说明不再重复「只提建议」", async ({ page }) => {
    await startVisitor(page);
    const id = await sampleWorkId(page);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    const items = thread(page).getByRole("list", { name: "可以先问这些" }).locator("li");
    const texts = await items.allInnerTexts();
    const project = await api(page).get(`/projects/${id}`);
    const current = await api(page).get(`/projects/${id}/drafts/${project.current_draft.id}`);
    const people = (await api(page).get(`/projects/${id}/characters`)).characters as { name: string }[];
    const counted = people.map((person) => ({ name: person.name, count: current.body.split(person.name).length - 1 })).filter((person) => person.count > 0).sort((a, b) => b.count - a.count).slice(0, 2);
    expect(counted.length).toBe(2);
    for (const person of counted) expect(texts.join("\n")).toContain(`${person.name}`);
    for (const person of counted) expect(texts.some((text) => text.includes(`草稿里出现 ${person.count} 次`))).toBe(true);
    expect(texts.join("\n")).not.toMatch(/草稿里出现 (9|7) 次/);
    await expect(thread(page).locator(".a-intro")).not.toContainText("不会改你的正文");
    await expect(thread(page).locator(".a-intro")).toContainText("每句回答都带着出处");
  });

  test("29 助手关闭时右栏只有「检查结果」：普通小标题，不是标签页", async ({ page }) => {
    await setup(page);
    try {
      await setRollout(page, "off");
      await page.reload();
      await expect(findings(page).getByRole("heading", { name: /^检查结果/ })).toBeVisible();
      await expect(findings(page).getByRole("tab")).toHaveCount(0);
      await expect(findings(page).getByRole("tablist")).toHaveCount(0);
      await expect(findings(page).locator('[role="tabpanel"]')).toHaveCount(0);
    } finally { await setRollout(page, "all"); }
  });

  test("06 提示条和提示框的左色条是一块直的竖条（贴内侧、上下留 8、宽 4、圆角 2），外框保持圆角：蓝、红、黄", async ({ page }) => {
    await setup(page);
    const seen = await page.evaluate(() => {
      const make = (className: string) => {
        const item = document.createElement("div");
        item.className = className;
        item.textContent = "x";
        item.style.position = "relative";
        item.style.animation = "none";
        document.body.append(item);
        const style = getComputedStyle(item);
        const bar = getComputedStyle(item, "::before");
        const result = { left: style.borderLeftWidth, radius: style.borderTopLeftRadius, top: bar.top, bottom: bar.bottom, width: bar.width, barRadius: bar.borderTopLeftRadius, colour: bar.backgroundColor };
        item.remove();
        return result;
      };
      return { info: make("note note-info"), warn: make("note note-warn"), error: make("note note-error"), toast: make("feedback"), toastError: make("feedback error") };
    });
    const [blue, yellow, red] = [await colourOf(page, "var(--c-blue)"), await colourOf(page, "var(--c-yellow)"), await colourOf(page, "var(--c-red)")];
    for (const [name, colour] of [["info", blue], ["warn", yellow], ["error", red], ["toast", blue], ["toastError", red]] as const) {
      const item = seen[name];
      expect(item.left, name).toBe("1px");
      expect(item.radius, name).toBe("10px");
      expect(item.width, name).toBe("4px");
      expect(item.barRadius, name).toBe("2px");
      expect(item.top, name).toBe("8px");
      expect(item.bottom, name).toBe("8px");
      expect(item.colour, name).toBe(colour);
    }
  });

  test("07 概览页横幅里的「打开草稿」是 6 像素圆角；实心按钮都有圆角", async ({ page }) => {
    const id = await setup(page);
    await openTab(page, id, "overview");
    const go = page.locator(".band-go");
    await expect(go).toBeVisible();
    expect(await go.evaluate((node) => getComputedStyle(node).borderTopLeftRadius)).toBe("6px");
    for (const selector of [".btn-primary", ".select-go", ".skip"]) {
      for (const node of await page.locator(selector).all()) expect(await node.evaluate((item) => getComputedStyle(item).borderTopLeftRadius)).not.toBe("0px");
    }
    await shot(page, "07f-07-band", false);
  });

  test("26 页脚的分隔线和内容栏同宽", async ({ page }) => {
    await registerAccount(page, "foot");
    for (const width of [1440, 1100, 375]) {
      await page.setViewportSize({ width, height: 900 });
      await page.goto("/projects");
      await expect(page.locator(".site-foot")).toBeVisible();
      await expect(page.locator(".topbar-inner")).toBeVisible();
      const [foot, column] = await page.evaluate(() => {
        // The column of the page's content: inside the top bar's own padding, the same on every page.
        const main = document.querySelector(".topbar-inner")!;
        const style = getComputedStyle(main);
        const box = main.getBoundingClientRect();
        const left = box.left + parseFloat(style.paddingLeft);
        const foot = document.querySelector(".site-foot")!.getBoundingClientRect();
        return [[Math.round(foot.left), Math.round(foot.right)], [Math.round(left), Math.round(box.right - parseFloat(style.paddingRight))]];
      });
      expect(foot, `${width}`).toEqual(column);
    }
  });

  test("30 对话框的阴影和菜单、卡片是同一个柔和阴影", async ({ page }) => {
    await setup(page);
    await page.getByLabel("更多：完成本章、技术详情、重置", { exact: true }).click();
    await page.getByRole("menuitem", { name: "重置作品", exact: true }).click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const shadow = await dialog.evaluate((node) => getComputedStyle(node).boxShadow);
    const probe = await page.evaluate(() => { const item = document.createElement("i"); item.style.boxShadow = "var(--elev-pop)"; document.body.append(item); const value = getComputedStyle(item).boxShadow; item.remove(); return value; });
    expect(shadow).toBe(probe);
    expect(shadow).not.toMatch(/\b0px 0px\b.*8px 8px/);
    expect(shadow).toContain("36px");
  });

  test("34 输入框的占位文字：日夜都和底色至少 4.5:1，已输入的文字更深；35 个人信息页的大头像是 14 像素圆角，顶栏的小头像仍是圆形", async ({ page }) => {
    await registerAccount(page, "hint");
    await page.goto("/projects/new");
    const field = page.locator("textarea[name=summary]");
    await expect(field).toBeVisible();
    const ratio = () => field.evaluate((node) => {
      const parse = (value: string) => (value.match(/[\d.]+/g) ?? []).slice(0, 3).map(Number);
      const light = (rgb: number[]) => { const [r, g, b] = rgb.map((v) => { const c = v / 255; return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4; }); return 0.2126 * r + 0.7152 * g + 0.0722 * b; };
      const [a, b] = [light(parse(getComputedStyle(node, "::placeholder").color)), light(parse(getComputedStyle(node).backgroundColor))];
      return (Math.max(a, b) + 0.05) / (Math.min(a, b) + 0.05);
    });
    await expect.poll(ratio).toBeGreaterThanOrEqual(4.5);
    await theme(page, "night");
    // The colours ease from one theme to the other; the ratio is read where they have arrived.
    await expect.poll(ratio).toBeGreaterThanOrEqual(4.5);
    await theme(page, "day");
    await expect.poll(() => field.evaluate((node) => getComputedStyle(node, "::placeholder").color)).toBe(await colourOf(page, "var(--c-muted)"));
    expect(await field.evaluate((node) => getComputedStyle(node, "::placeholder").color)).toBe(await colourOf(page, "var(--c-muted)"));
    expect(await field.evaluate((node) => getComputedStyle(node).color)).toBe(await colourOf(page, "var(--c-ink)"));
    // 35.
    await openAccountMenu(page);
    await page.getByRole("menuitem", { name: "作者主页", exact: true }).click();
    const large = page.locator(".avatar-xl");
    await expect(large).toBeVisible();
    const style = await large.evaluate((node) => { const css = getComputedStyle(node); return { radius: css.borderTopLeftRadius, overflow: css.overflow }; });
    expect(style).toEqual({ radius: "14px", overflow: "hidden" });
    expect(await accountMenuButton(page).locator(".avatar").evaluate((node) => getComputedStyle(node).borderTopLeftRadius)).toBe("50%");
  });
});

test.describe("07f 手机", () => {
  test("31 手机上写作页的助手窗格是固定高度的滚动区：对话单独滚动，输入框在窗格底部，翻上去后有新回答出现「新回答 ↓」", async ({ browser }) => {
    test.setTimeout(150_000);
    const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 375, height: 812 } });
    const phone = await context.newPage();
    await phone.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await registerAccount(phone, "pane");
    const id = await sampleWorkId(phone);
    await openTab(phone, id, "workspace");
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    const questions = ["苏岑是谁？", "温岚是谁？", "罗盘在谁手里？", "老周是谁？", "第 9 章发生了什么？", "黎舟是谁？"];
    for (const [index, question] of questions.entries()) {
      await ask(phone, question);
      await finished(phone, index + 1);
    }
    const geometry = async () => phone.evaluate(() => {
      const pane = document.getElementById("side-panel-assistant")!.getBoundingClientRect();
      const log = document.querySelector<HTMLElement>(".a-thread")!;
      const field = document.querySelector('[aria-label="向助手提问"]')!.getBoundingClientRect();
      return { pane: [Math.round(pane.top), Math.round(pane.height)], log: [log.scrollHeight, log.clientHeight], field: Math.round(field.bottom), page: document.documentElement.scrollHeight, height: window.innerHeight };
    });
    await phone.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: "助手", exact: true }).click();
    await expect.poll(async () => (await geometry()).pane[0]).toBeLessThan(200);
    const now = await geometry();
    // The conversation is longer than the pane and scrolls inside it; the box is at the pane's foot and in the window.
    expect(now.log[0]).toBeGreaterThan(now.log[1]);
    expect(now.pane[1]).toBeLessThanOrEqual(now.height);
    expect(now.field).toBeLessThanOrEqual(now.height);
    expect(now.page).toBeLessThan(now.height * 3);
    // The pane switch sits just under the top bar (whose real height on a phone is taller than --topbar-h), not under it.
    const cover = await phone.evaluate(() => ({ bar: document.querySelector(".topbar")!.getBoundingClientRect().bottom, panes: document.querySelector(".mobile-panes")!.getBoundingClientRect().top }));
    expect(cover.panes).toBeGreaterThanOrEqual(cover.bar - 1);
    // The page itself is held still: a pull outside the conversation does not move it, so the box stays on the screen.
    const before = await phone.evaluate(() => window.scrollY);
    await phone.locator(".mobile-panes").hover();
    await phone.mouse.wheel(0, -3000);
    await phone.waitForTimeout(300);
    expect(await phone.evaluate(() => window.scrollY)).toBe(before);
    expect(Math.round(await phone.locator('#side-panel-assistant textarea[aria-label="向助手提问"]').evaluate((field) => field.getBoundingClientRect().bottom))).toBeLessThanOrEqual(now.height);
    await shot(phone, "07f-31-phone-pane", false);
    // Scrolled up in the conversation while an answer is on its way, 「新回答 ↓」 shows and takes the author to the end.
    await ask(phone, "E2E_SLOW 老周后来去了哪里？");
    await expect(tasks(phone)).toHaveCount(questions.length + 1);
    await phone.locator(".a-thread").hover();
    await phone.mouse.wheel(0, -4000);
    await finished(phone, questions.length + 1);
    const jump = phone.getByRole("button", { name: "新回答 ↓", exact: true });
    await expect(jump).toBeVisible({ timeout: 20_000 });
    await jump.click();
    await expect(jump).toHaveCount(0);
    expect(await phone.evaluate(() => { const log = document.querySelector<HTMLElement>(".a-thread")!; return log.scrollHeight - log.scrollTop - log.clientHeight; })).toBeLessThan(80);
    await context.close();
  });
});

test.describe("07g 复查后的修正", () => {
  test("双击发送不会停掉刚发出的任务：停止键出现后的片刻内不接受点击", async ({ page }) => {
    test.setTimeout(90_000);
    await registerAccount(page, "dblsend");
    const id = await sampleWorkId(page);
    await openTab(page, id, "workspace");
    await openAssistantTab(page);
    await box(page).fill("E2E_SLOWER 苏岑是谁？");
    await thread(page).getByRole("button", { name: "发送", exact: true }).dblclick();
    await finished(page, 1, "completed");
    await expect(thread(page).locator('[data-task][data-status="cancelled"]')).toHaveCount(0);
  });
});
