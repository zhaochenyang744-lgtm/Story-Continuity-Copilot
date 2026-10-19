import { readFile } from "node:fs/promises";
import type { Page } from "@playwright/test";
import { accountMenuButton, api, createWorkByApi, expect, mailerCalls, mailLink, newPage, openAccountMenu, registerAccount, sampleWorkId, shot, startVisitor, test } from "./support/app";
import { theme } from "./support/pages";

/** Days are Beijing-time days (UTC+8), the same cut the server makes. */
const dayOf = (offsetDays = 0) => new Date(Date.now() + 8 * 3_600_000 + offsetDays * 86_400_000).toISOString().slice(0, 10);
const label = (day: string) => `${Number(day.slice(5, 7))} 月 ${Number(day.slice(8, 10))} 日`;
const topNav = (page: Page) => page.getByRole("navigation", { name: "全局", exact: true });
const settingsNav = (page: Page) => page.getByRole("navigation", { name: "设置", exact: true });
const group = (page: Page, name: string) => page.getByRole("group", { name, exact: true });

async function writeOn(page: Page, userId: string, projectId: string, day: string, chars: number, chapter = 1) {
  await api(page).post(`/test/v180/users/${userId}/writing-days`, { project_id: projectId, day, net_chars: chars, chapter_number: chapter });
}
async function saveDraft(page: Page, projectId: string, body: string, title = "桌上的留白") {
  const project = await api(page).get(`/projects/${projectId}`);
  const draft = await api(page).get(`/projects/${projectId}/drafts/${project.current_draft.id}`);
  await api(page).patch(`/projects/${projectId}/drafts/${draft.id}`, { base_revision: draft.revision, body, title });
}

test("作者主页：名字、简介、四个数字、写作日历、这一年、正在写、全部作品、最近动态", async ({ page }) => {
  const { account } = await registerAccount(page, "home");
  const me = (await api(page).get("/auth/session")).user;
  await api(page).patch("/auth/profile", { base_profile_revision: me.profile_revision, display_name: "林栖", avatar_preset: "archive_blue", bio: "写近未来的港口城市，和住在里面的人。" });
  const first = await createWorkByApi(page, { title: "盐雾之下", genre: "近未来", summary: "港口封闭后的第七年，档案员在一份回执里发现了父亲的签名。" });
  const second = await createWorkByApi(page, { title: "纸灯", genre: "短篇集" });
  await saveDraft(page, first, "雾从港口的方向漫上来。苏岑把回执摊在桌上。".repeat(30));
  await saveDraft(page, second, "纸灯点亮的那一夜，没有人说话。".repeat(10), "纸灯一");
  // The past: writing on each of the last four days, and a long gap before.
  for (const [offset, chars] of [[-1, 1200], [-2, 300], [-3, 5200], [-4, 90], [-9, 700]]) await writeOn(page, me.id, first, dayOf(offset), chars);

  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "作者主页", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("heading", { level: 1, name: "林栖", exact: true })).toBeVisible();
  await expect(page.getByText(`@${account} · `)).toContainText(/\d{4} 年 \d{1,2} 月加入/);
  await expect(page.getByText("写近未来的港口城市，和住在里面的人。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "写一句介绍自己" })).toHaveCount(0);

  // The four figures: works, chapters, characters (chapters and draft, spaces left out), the streak in blue.
  const figures = page.locator(".author-figs");
  const works = (await api(page).get("/projects?q=&sort=updated_desc")).projects.filter((item: { data_origin: string }) => item.data_origin === "user_created");
  const chars = works.reduce((sum: number, item: { word_count: number }) => sum + item.word_count, 0);
  await expect(figures.locator(".v").nth(0)).toHaveText("2");
  await expect(figures.locator(".v").nth(1)).toHaveText("0");
  await expect(figures.locator(".v").nth(2)).toHaveText(chars.toLocaleString("en-US"));
  const streak = figures.locator(".v.blue");
  await expect(streak).toHaveText("5");
  await expect(figures.getByText("天连续在写", { exact: true })).toBeVisible();
  expect(await streak.evaluate((node) => getComputedStyle(node).color)).toBe(await page.evaluate(() => { const probe = document.createElement("i"); probe.style.color = "var(--c-blue-text)"; document.body.append(probe); const color = getComputedStyle(probe).color; probe.remove(); return color; }));

  // 写作日历: focusable, a day is read on hover and with the arrow keys, each month's total is there for a screen reader.
  const calendar = group(page, "写作日历，过去 12 个月，方向键可以逐日查看");
  await expect(calendar).toBeVisible();
  const cells = page.locator(".heat-grid i");
  await expect(cells).toHaveCount(365);
  await cells.nth(365 - 2).hover();
  await expect(page.locator(".heat-grid .tip")).toHaveText(`${label(dayOf(-1))} · 1,200 字`);
  await cells.nth(365 - 6).hover();
  await expect(page.locator(".heat-grid .tip")).toHaveText(`${label(dayOf(-5))} · 没有写`);
  await page.mouse.move(0, 0);
  await calendar.focus();
  await expect(page.getByRole("status").filter({ hasText: label(dayOf()) })).toContainText("字");
  await page.keyboard.press("ArrowDown");
  await expect(page.getByRole("status").filter({ hasText: " · " }).last()).toContainText(label(dayOf()));
  await page.keyboard.press("ArrowLeft");
  await expect(page.getByRole("status").filter({ hasText: " · " }).last()).toContainText(label(dayOf(-7)));
  expect(await calendar.getAttribute("aria-describedby")).toBeTruthy();
  const monthly = await page.locator(`[id="${await calendar.getAttribute("aria-describedby")}"]`).textContent();
  expect(monthly).toMatch(/每月写作字数：.*\d{4} 年 \d{1,2} 月 [\d,]+ 字/);
  const shades = await cells.evaluateAll((nodes) => nodes.map((node) => node.getAttribute("data-l")));
  expect(shades.filter((level) => level === "0").length).toBeGreaterThan(300);
  expect(shades[364]).not.toBe("0");
  expect(new Set(shades.filter((level) => level !== "0")).size).toBeGreaterThanOrEqual(3);

  // 这一年
  const year = page.getByRole("region", { name: "这一年" });
  await expect(year.getByText("写作的天数", { exact: true }).locator("xpath=following-sibling::dd")).toHaveText("6 天");
  await expect(year.getByText("最多的一天", { exact: true }).locator("xpath=following-sibling::dd")).toHaveText("5,200 字");
  await expect(year.getByText("最长连续", { exact: true }).locator("xpath=following-sibling::dd")).toHaveText("5 天");
  await expect(year.getByText("检查过的章节", { exact: true }).locator("xpath=following-sibling::dd")).toHaveText("0 章");

  // 正在写: the work whose draft was saved last.
  const current = page.getByRole("region", { name: "正在写" });
  await expect(current).toContainText("《纸灯》 · 第 1 章");
  await expect(current.getByRole("heading", { level: 3, name: "纸灯一", exact: true })).toBeVisible();
  await expect(current).toContainText("草稿 150 字");
  await expect(current).toContainText("本章还没检查");
  // 全部作品: every work, then the way to a new one.
  const all = page.getByRole("region", { name: /^全部作品/ });
  await expect(all.locator(".work")).toHaveCount(3);
  await expect(all.getByRole("button", { name: /盐雾之下/ })).toContainText("近未来");
  await expect(all.getByRole("button", { name: /盐雾之下/ })).toContainText("港口封闭后的第七年");
  await expect(all.getByRole("button", { name: "＋ 新建一部作品", exact: true })).toBeVisible();
  await expect(all.getByRole("button", { name: "导入已有的稿子", exact: true })).toBeVisible();
  // 最近动态: what was done, never what was written.
  const feed = page.getByRole("complementary", { name: "最近动态" });
  await expect(feed).toContainText("保存了第 1 章草稿");
  await expect(feed).toContainText("新建了作品");
  await expect(feed.getByText("雾从港口的方向")).toHaveCount(0);
  await expect(feed.getByText("纸灯点亮")).toHaveCount(0);
  await shot(page, "author-home");

  // The way on.
  await current.getByRole("button", { name: "继续写 →", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${second}/workspace$`));
  await page.goBack();
  await page.getByRole("button", { name: "编辑资料", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/profile$/);
  await page.goto("/account");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
});

test("作者主页：没有草稿时没有「正在写」；没写简介时是一个去设置的链接；还没写过就是 0", async ({ page }) => {
  await registerAccount(page, "empty");
  await page.goto("/account");
  await expect(page.getByRole("heading", { level: 1, name: "E2E 作者", exact: true })).toBeVisible();
  await expect(page.getByRole("region", { name: "正在写" })).toHaveCount(0);
  await expect(page.getByRole("heading", { name: "正在写" })).toHaveCount(0);
  await expect(page.locator(".author-figs .v.blue")).toHaveText("0");
  await expect(page.getByText("还没有动态", { exact: false })).toBeVisible();
  await page.getByRole("button", { name: "写一句介绍自己", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/profile$/);
  // A work with an empty draft is not being written either.
  await createWorkByApi(page, { title: "空白的书" });
  await page.goto("/account");
  await expect(page.getByRole("region", { name: /^全部作品/ }).locator(".work:not(.work-new)")).toHaveCount(1);
  await expect(page.getByRole("region", { name: "正在写" })).toHaveCount(0);
});

test("作者主页：今天还没写、昨天写了，显示「昨天以前连续」", async ({ page }) => {
  await registerAccount(page, "yesterday");
  const me = (await api(page).get("/auth/session")).user;
  const work = await createWorkByApi(page, { title: "昨日之书" });
  for (const offset of [-1, -2, -3]) await writeOn(page, me.id, work, dayOf(offset), 400);
  await page.goto("/account");
  await expect(page.locator(".author-figs .v.blue")).toHaveText("3");
  await expect(page.locator(".author-figs").getByText("天 · 昨天以前连续", { exact: true })).toBeVisible();
  await expect(page.locator(".author-figs").getByText("昨天以前连续 3 天", { exact: true })).toHaveCount(1);
});

test("访客的作者主页：最上面一条横幅，没有简介可写，不能编辑资料", async ({ page }) => {
  await startVisitor(page);
  await page.goto("/account");
  const banner = page.getByRole("note").filter({ hasText: "这是访客空间" });
  await expect(banner).toBeVisible();
  await expect(banner).toContainText(/还剩 \d+ (天|小时)/);
  await expect(banner).toContainText("作品、写作日历和动态都会清除");
  await expect(page.getByText("注册后可以写一句介绍自己。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "编辑资料", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "写一句介绍自己", exact: true })).toHaveCount(0);
  await shot(page, "author-home-visitor");
  // 注册个人账号 asks first, then leaves the visitor space for the registration page.
  await banner.getByRole("button", { name: "注册个人账号", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "先退出访客空间", exact: true });
  await expect(dialog).toContainText("不会带到新账号");
  await dialog.getByRole("button", { name: "留在这里", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await banner.getByRole("button", { name: "注册个人账号", exact: true }).click();
  await dialog.getByRole("button", { name: "退出并去注册", exact: true }).click();
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByRole("heading", { level: 1, name: "创建账号", exact: true })).toBeVisible();
});

test("旧地址：/account/profile 去作者主页，/account/security 去设置的账号与安全", async ({ page }) => {
  await registerAccount(page, "legacy");
  await page.goto("/account/profile");
  await expect(page).toHaveURL(/\/account$/);
  await expect(page.getByRole("heading", { level: 1, name: "E2E 作者", exact: true })).toBeVisible();
  await page.goto("/account/security");
  await expect(page).toHaveURL(/\/settings\/security$/);
  await expect(page.getByRole("heading", { level: 2, name: "账号与安全", exact: true })).toBeVisible();
  // The old address is replaced, not stacked: back leaves for the page before it.
  await page.goBack();
  await expect(page).not.toHaveURL(/\/account\/security$/);
});

test("头像菜单：作者主页、设置、退出登录三项，访客也一样", async ({ page, browser }) => {
  await registerAccount(page, "menu");
  await openAccountMenu(page);
  await expect(page.getByRole("menuitem")).toHaveText(["作者主页", "设置", "退出登录"]);
  await page.getByRole("menuitem", { name: "设置", exact: true }).click();
  await expect(page).toHaveURL(/\/settings$/);
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "作者主页", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  const visitor = await newPage(browser);
  await startVisitor(visitor);
  await openAccountMenu(visitor);
  await expect(visitor.getByRole("menuitem")).toHaveText(["作者主页", "设置", "退出登录"]);
  await visitor.context().close();
});

test("设置：五项各有自己的地址，/settings 是个人资料，刷新后停在原来那一项", async ({ page }) => {
  await registerAccount(page, "nav");
  await page.goto("/settings");
  const nav = settingsNav(page);
  await expect(nav.getByRole("button", { name: "个人资料", exact: true })).toHaveAttribute("aria-current", "page");
  for (const [name, path, heading] of [["账号与安全", "security", "账号与安全"], ["用量", "usage", "用量"], ["偏好", "preferences", "偏好"], ["数据", "data", "数据"], ["个人资料", "profile", "个人资料"]] as const) {
    await nav.getByRole("button", { name, exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/settings/${path}$`));
    await page.reload();
    await expect(page.getByRole("heading", { level: 2, name: heading, exact: true })).toBeVisible();
    await expect(nav.getByRole("button", { name, exact: true })).toHaveAttribute("aria-current", "page");
  }
  await nav.getByRole("button", { name: "← 回到作者主页", exact: true }).click();
  await expect(page).toHaveURL(/\/account$/);
  await page.goto("/settings/nothing");
  await expect(page.getByRole("heading", { level: 1, name: /找不到|404/ })).toBeVisible();
});

test("个人资料：直接是表单，有改动才能保存，简介 60 字，保存后主页和顶栏跟着变", async ({ page }) => {
  const { account } = await registerAccount(page, "profile");
  await page.goto("/settings/profile");
  const name = page.getByRole("textbox", { name: "显示名称", exact: true });
  const bio = page.getByRole("textbox", { name: "简介", exact: true });
  const save = page.getByRole("button", { name: "保存", exact: true });
  await expect(name).toHaveValue("E2E 作者");
  await expect(bio).toHaveValue("");
  await expect(page.getByText(/^0\s*\/ 60$/)).toBeVisible();
  await expect(save).toBeDisabled();
  await shot(page, "settings-profile");

  const before = (await api(page).get("/auth/session")).user;
  await name.fill("夜航的笔名");
  await bio.fill("写近未来的港口城市，和住在里面的人。");
  await expect(page.getByText(/^18\s*\/ 60$/)).toBeVisible();
  await expect(save).toBeEnabled();
  await page.getByRole("radio", { name: "书页玫" }).check({ force: true });
  await save.click();
  await expect(page.getByText("已保存。", { exact: true })).toBeVisible();
  await expect(save).toBeDisabled();
  await expect(accountMenuButton(page)).toHaveAccessibleName("账号菜单：夜航的笔名");
  const after = (await api(page).get("/auth/session")).user;
  expect(after).toMatchObject({ display_name: "夜航的笔名", bio: "写近未来的港口城市，和住在里面的人。", avatar_preset: "folio_rose", account_name: account });
  expect(after.profile_revision).toBe(before.profile_revision + 1);
  await page.goto("/account");
  await expect(page.getByRole("heading", { level: 1, name: "夜航的笔名", exact: true })).toBeVisible();
  await expect(page.getByText("写近未来的港口城市，和住在里面的人。", { exact: true })).toBeVisible();

  // A bio of 61 characters cannot be saved; the counter says so.
  await page.goto("/settings/profile");
  await bio.fill("写".repeat(61));
  await expect(page.getByText(/^61\s*\/ 60$/)).toBeVisible();
  await expect(save).toBeDisabled();
  // Cancel puts back what is saved.
  await name.fill("不想保存的名字");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(name).toHaveValue("夜航的笔名");
  await expect(bio).toHaveValue("写近未来的港口城市，和住在里面的人。");
  expect((await api(page).get("/auth/session")).user.profile_revision).toBe(after.profile_revision);
});

test("个人资料：有没保存的改动时，换设置项、去别的页、退出和刷新都会提醒", async ({ page }) => {
  await registerAccount(page, "guard");
  await page.goto("/settings/profile");
  const name = page.getByRole("textbox", { name: "显示名称", exact: true });
  await name.fill("还没存的名字");
  const dialog = page.getByRole("dialog", { name: "资料还没保存", exact: true });
  // Another item of the settings.
  await settingsNav(page).getByRole("button", { name: "偏好", exact: true }).click();
  await expect(dialog).toBeVisible();
  await shot(page, "settings-leave-dialog");
  await dialog.getByRole("button", { name: "留在这里", exact: true }).click();
  await expect(dialog).toHaveCount(0);
  await expect(page).toHaveURL(/\/settings\/profile$/);
  await expect(name).toHaveValue("还没存的名字");
  // Another page.
  await topNav(page).getByRole("button", { name: "首页", exact: true }).click();
  await expect(dialog).toBeVisible();
  await page.keyboard.press("Escape");
  await expect(dialog).toHaveCount(0);
  // Signing out.
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(dialog).toBeVisible();
  await dialog.getByRole("button", { name: "留在这里", exact: true }).click();
  // Closing or reloading the tab.
  const warned = new Promise<boolean>((resolve) => { page.once("dialog", (prompt) => { void prompt.dismiss(); resolve(prompt.type() === "beforeunload"); }); });
  await page.evaluate(() => { window.location.reload(); });
  expect(await warned).toBe(true);
  // Leaving is a choice: 放弃修改并离开.
  await settingsNav(page).getByRole("button", { name: "偏好", exact: true }).click();
  await dialog.getByRole("button", { name: "放弃修改并离开", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/preferences$/);
  expect((await api(page).get("/auth/session")).user.display_name).toBe("E2E 作者");
  // Nothing is asked once the form is clean again.
  await topNav(page).getByRole("button", { name: "首页", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(dialog).toHaveCount(0);
});

test("个人资料：访客不能改，只有一段说明", async ({ page }) => {
  await startVisitor(page);
  await page.goto("/settings/profile");
  await expect(page.getByText("访客空间不能修改个人资料", { exact: false })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  const user = (await api(page).get("/auth/session")).user;
  const edit = await api(page).raw("PATCH", "/auth/profile", { base_profile_revision: user.profile_revision, display_name: "想改名的访客", avatar_preset: "continuity_violet", bio: "我" });
  expect(edit.status).toBe(403);
});

test("账号与安全：修改密码，旧密码错、两次不一致、不合规都挡住，成功后当前会话不退出", async ({ page }) => {
  const { account, password } = await registerAccount(page, "password");
  await page.goto("/settings/security");
  const row = page.locator(".row").filter({ hasText: "密码" }).first();
  await expect(row).toContainText("注册时设置");
  await expect(page.getByText("只在一处保持登录")).toBeVisible();
  await expect(page.getByText("在别的设备登录后，这里会自动退出", { exact: true })).toBeVisible();
  await expect(page.getByText(account, { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "修改密码", exact: true }).click();
  const old = page.getByLabel("旧密码", { exact: true });
  const next = page.getByLabel("新密码", { exact: true });
  const again = page.getByLabel("再输一次新密码", { exact: true });
  const submit = page.getByRole("button", { name: "修改密码", exact: true }).last();
  await shot(page, "settings-password");

  await old.fill("not-the-password");
  await next.fill("a-brand-new-password-1");
  await again.fill("a-brand-new-password-1");
  await submit.click();
  await expect(page.locator("p.inline-error")).toContainText("旧密码不对");
  expect((await api(page).raw("GET", "/auth/session")).status).toBe(200);
  await old.fill(password);
  await again.fill("something-else-entirely");
  await submit.click();
  await expect(page.locator("p.inline-error")).toContainText("两次输入的新密码不一致");
  // Too short: the browser itself holds the form back, nothing is sent.
  await next.fill("short");
  await again.fill("short");
  await submit.click();
  expect(await next.evaluate((node) => (node as HTMLInputElement).validity.tooShort)).toBe(true);
  await expect(page.locator("p.inline-error")).toContainText("两次输入的新密码不一致");
  await next.fill("aaaaaaaaaaaa");
  await again.fill("aaaaaaaaaaaa");
  await submit.click();
  await expect(page.locator("p.inline-error")).toContainText("密码至少 10 个字符");
  await expect(page.getByRole("button", { name: "退出登录并找回密码", exact: true })).toBeVisible();

  await next.fill("a-brand-new-password-1");
  await again.fill("a-brand-new-password-1");
  await submit.click();
  await expect(page.getByText("密码已修改", { exact: true })).toBeVisible();
  await expect(page.getByLabel("旧密码", { exact: true })).toHaveCount(0);
  expect((await api(page).raw("GET", "/auth/session")).status).toBe(200);
  const stamp = (await api(page).get("/auth/session")).user.password_changed_at;
  expect(stamp).toEqual(expect.any(String));
  await expect(row).toContainText(`上次修改：${label(dayOf())}`);
  await page.reload();
  await expect(page.locator(".row").filter({ hasText: "密码" }).first()).toContainText(`上次修改：${label(dayOf())}`);

  // The new password signs in, the old one does not.
  const other = await newPage(page.context().browser()!);
  await other.goto("/login");
  await other.getByLabel("账号", { exact: true }).fill(account);
  await other.getByLabel("密码", { exact: true }).fill(password);
  await other.getByRole("button", { name: "登录", exact: true }).click();
  await expect(other.getByRole("alert").filter({ hasText: "账号或密码不正确" })).toBeVisible();
  await other.getByLabel("密码", { exact: true }).fill("a-brand-new-password-1");
  await other.getByRole("button", { name: "登录", exact: true }).click();
  await expect(other).toHaveURL(/\/$/);
  await other.context().close();
});

test("账号与安全：忘了旧密码的链接去邮箱找回", async ({ page }) => {
  await registerAccount(page, "forgot");
  await page.goto("/settings/security");
  await page.getByRole("button", { name: "修改密码", exact: true }).click();
  await page.getByRole("button", { name: "退出登录并找回密码", exact: true }).click();
  await expect(page).toHaveURL(/\/password-reset$/);
  await expect(page.getByRole("heading", { level: 1, name: "找回密码", exact: true })).toBeVisible();
  expect((await api(page).raw("GET", "/auth/session")).status).toBe(401);
});

test("账号与安全：当前恢复邮箱和状态，更换邮箱后变成未验证并收到新的验证邮件，可以重新发送", async ({ page }) => {
  const { email } = await registerAccount(page, "security");
  await page.goto("/settings/security");
  await expect(page.getByRole("heading", { level: 2, name: "账号与安全", exact: true })).toBeVisible();
  const first = (await api(page).get("/auth/session")).user.recovery_email;
  expect(first).toMatchObject({ configured: true, verified: false });
  await expect(page.getByText(first.masked, { exact: true })).toBeVisible();
  await expect(page.getByText("未验证", { exact: true })).toBeVisible();

  // Verify it, so that the change below visibly takes the verification away.
  await page.goto(await mailLink(page, "verify_email", email));
  await expect(page.getByText("恢复邮箱验证好了，可以用来找回密码。", { exact: true })).toBeVisible();
  await page.goto("/settings/security");
  await expect(page.getByText("已验证", { exact: true })).toBeVisible();
  expect((await api(page).get("/auth/session")).user.recovery_email.verified).toBe(true);

  // 换一个邮箱
  const mails = await mailerCalls(page);
  const newEmail = `moved-${email}`;
  await page.getByRole("button", { name: "更换", exact: true }).click();
  await page.getByRole("textbox", { name: "换一个邮箱", exact: true }).fill(newEmail);
  await page.getByRole("button", { name: "更换并发送验证", exact: true }).click();
  await expect(page.getByText("恢复邮箱已绑定，验证邮件已发送。", { exact: true })).toBeVisible();
  await expect(page.getByText("未验证", { exact: true })).toBeVisible();
  const moved = (await api(page).get("/auth/session")).user.recovery_email;
  expect(moved).toMatchObject({ configured: true, verified: false });
  expect(moved.masked).not.toBe(first.masked);
  await expect(page.getByText(moved.masked, { exact: true })).toBeVisible();
  expect(await mailerCalls(page)).toBe(mails + 1);
  await mailLink(page, "verify_email", newEmail);
  await shot(page, "settings-security");

  // 重新发送验证: the server holds back a second mail to the same address within a minute, on purpose.
  const resend = page.getByRole("button", { name: "重新发送验证", exact: true });
  const sent = page.getByText("验证邮件重新发送了。", { exact: true });
  const held = page.getByRole("alert").filter({ hasText: "安全请求过于频繁，请稍后再试。" });
  await resend.click();
  await expect(held).toBeVisible();
  expect(await mailerCalls(page)).toBe(mails + 1);
  // Once the cool-down is over, the same button sends again.
  test.setTimeout(180_000);
  await expect.poll(async () => {
    await resend.click();
    await expect(sent.or(held)).toBeVisible();
    return sent.isVisible();
  }, { message: "the resend goes out after the one-minute cool-down", timeout: 120_000, intervals: [5_000] }).toBe(true);
  expect(await mailerCalls(page)).toBe(mails + 2);
  // The newest link verifies the new address and takes the resend button away.
  await page.goto(await mailLink(page, "verify_email", newEmail));
  await expect(page.getByText("恢复邮箱验证好了，可以用来找回密码。", { exact: true })).toBeVisible();
  expect((await api(page).get("/auth/session")).user.recovery_email.verified).toBe(true);
  await page.goto("/settings/security");
  await expect(page.getByText("已验证", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "更换", exact: true }).click();
  await expect(page.getByRole("button", { name: "重新发送验证", exact: true })).toHaveCount(0);
});

test("访客的账号与安全：不能绑定恢复邮箱，没有密码", async ({ page }) => {
  await startVisitor(page);
  await page.goto("/settings/security");
  await expect(page.getByRole("heading", { level: 2, name: "账号与安全", exact: true })).toBeVisible();
  await expect(page.getByText("访客空间不能绑定恢复邮箱，也没有密码。注册个人账号后就可以绑定。", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /修改密码|更换|绑定/ })).toHaveCount(0);
  const bind = await api(page).raw("POST", "/auth/recovery-email", { recovery_email: "visitor@example.test" });
  expect(bind.status).toBe(403);
  const change = await api(page).raw("POST", "/auth/password", { current_password: "x", new_password: "another-password-1" });
  expect(change.status).toBe(403);
  expect(change.body.error.code).toBe("password_change_not_allowed");
});

test("用量：近 24 小时还能检查多少字、恢复时间、近 7 天两色柱子，鼠标移上去看两个数", async ({ page }) => {
  await registerAccount(page, "usage");
  const me = (await api(page).get("/auth/session")).user;
  await api(page).post(`/test/v180/users/${me.id}/usage`, { kind: "continuity", chars: 3200, hours_ago: 20 });
  await api(page).post(`/test/v180/users/${me.id}/usage`, { kind: "assistant_task", chars: 500, hours_ago: 0.1 });
  await api(page).post(`/test/v180/users/${me.id}/usage`, { kind: "continuity", chars: 800, hours_ago: 0.05 });
  await page.goto("/settings/usage");
  await expect(page.getByText("近 24 小时还能检查", { exact: true })).toBeVisible();
  const usage = await api(page).get("/account/usage");
  expect(usage.check_chars_used).toBe(4500);
  await expect(page.getByTestId("usage-remaining")).toContainText(usage.check_chars_remaining.toLocaleString("en-US"));
  await expect(page.getByTestId("usage-remaining")).toContainText("/ 60,000 字");
  await expect(page.getByText("已用 4,500 字", { exact: true })).toBeVisible();
  await expect(page.getByText(/^最早的一笔在 3 小时 \d+ 分钟后恢复$|^最早的一笔在 4 小时后恢复$/)).toBeVisible();
  await expect(page.getByText(/助手每问一次算 500 字/)).toBeVisible();
  await expect(page.getByText(/不是每天 0 点恢复/)).toBeVisible();
  const week = page.getByRole("list", { name: "近 7 天每天用掉的字数" });
  const columns = week.getByRole("listitem");
  await expect(columns).toHaveCount(7);
  await expect(page.getByText("检查", { exact: true }).first()).toBeVisible();
  await expect(page.getByText("助手", { exact: true }).first()).toBeVisible();
  // Today is the last column: both colours are there, and the hover reads both numbers.
  const daily = await api(page).get("/account/usage/daily?days=7");
  expect(daily.days).toHaveLength(7);
  const today = daily.days[6];
  expect(today.assistant_chars).toBe(500);
  await columns.last().hover();
  await expect(page.locator(".settings .week-wrap .tip")).toHaveText(`${label(today.day)} · 检查 ${today.check_chars.toLocaleString("en-US")} 字 · 助手 500 字`);
  await expect(columns.last()).toHaveAccessibleName(`${label(today.day)} · 检查 ${today.check_chars.toLocaleString("en-US")} 字 · 助手 500 字`);
  await expect(columns.last().locator("i.a")).toBeVisible();
  await expect(columns.last().locator("i.c")).toBeVisible();
  await shot(page, "settings-usage");
});

test("用量：访客看到的是访客的次数额度", async ({ page }) => {
  await startVisitor(page);
  await page.goto("/settings/usage");
  const usage = await api(page).get("/account/usage");
  await expect(page.getByText("访客 · 24 小时内还可检查", { exact: true })).toBeVisible();
  await expect(page.getByText(`/ ${usage.checks_limit} 次`, { exact: true })).toBeVisible();
  await expect(page.getByText(`每次最多 ${usage.check_chars_per_check.toLocaleString("en-US")} 字`)).toBeVisible();
  await expect(page.getByRole("list", { name: "近 7 天每天用掉的字数" })).toHaveCount(0);
});

test("偏好：主题三态，顶栏按钮和设置同步，跟随系统时系统一变就跟着变", async ({ page }) => {
  await registerAccount(page, "theme");
  await page.goto("/settings/preferences");
  const themes = group(page, "主题");
  const html = page.locator("html");
  const stored = () => page.evaluate(() => localStorage.getItem("story-continuity:theme"));
  await page.emulateMedia({ colorScheme: "light" });
  await expect(themes.getByRole("button", { name: "跟随系统", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(html).toHaveAttribute("data-theme", "day");

  await themes.getByRole("button", { name: "深色", exact: true }).click();
  await expect(html).toHaveAttribute("data-theme", "night");
  await expect(themes.getByRole("button", { name: "深色", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await stored()).toBe("night");
  await expect(page.getByRole("button", { name: "切换到日间模式", exact: true })).toBeVisible();
  // The top bar's button moves the setting here too.
  await page.getByRole("button", { name: "切换到日间模式", exact: true }).click();
  await expect(html).toHaveAttribute("data-theme", "day");
  await expect(themes.getByRole("button", { name: "浅色", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await stored()).toBe("day");
  // A fixed theme does not follow the system.
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveAttribute("data-theme", "day");

  // 跟随系统 follows it as it changes.
  await themes.getByRole("button", { name: "跟随系统", exact: true }).click();
  expect(await stored()).toBeNull();
  await expect(html).toHaveAttribute("data-theme", "night");
  await page.emulateMedia({ colorScheme: "light" });
  await expect(html).toHaveAttribute("data-theme", "day");
  await page.emulateMedia({ colorScheme: "dark" });
  await expect(html).toHaveAttribute("data-theme", "night");
  await page.reload();
  await expect(html).toHaveAttribute("data-theme", "night");
  await expect(themes.getByRole("button", { name: "跟随系统", exact: true })).toHaveAttribute("aria-pressed", "true");
  // The top bar's button, while following the system, makes the opposite theme fixed.
  await page.getByRole("button", { name: "切换到日间模式", exact: true }).click();
  await expect(html).toHaveAttribute("data-theme", "day");
  await expect(themes.getByRole("button", { name: "浅色", exact: true })).toHaveAttribute("aria-pressed", "true");
  expect(await stored()).toBe("day");
  await page.emulateMedia({ colorScheme: "light" });
  await shot(page, "settings-preferences");
  await expect(page.getByText("跟随系统设置", { exact: true })).toBeVisible();
});

test("偏好：访客也能用，设置存在本机，localStorage 不可用时也不出错", async ({ page }) => {
  await startVisitor(page);
  await page.goto("/settings/preferences");
  await group(page, "主题").getByRole("button", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "night");
  await group(page, "正文字号").getByRole("button", { name: "大", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-font-size", "large");
  expect(await page.evaluate(() => localStorage.getItem("story-continuity:font-size"))).toBe("large");
  // With storage blocked the buttons still work for this visit.
  const blocked = await newPage(page.context().browser()!);
  await blocked.addInitScript(() => {
    Object.defineProperty(window, "localStorage", { get() { throw new DOMException("blocked", "SecurityError"); } });
  });
  const errors: string[] = [];
  blocked.on("pageerror", (error) => errors.push(error.message));
  await startVisitor(blocked);
  await blocked.goto("/settings/preferences");
  await group(blocked, "主题").getByRole("button", { name: "深色", exact: true }).click();
  await expect(blocked.locator("html")).toHaveAttribute("data-theme", "night");
  await group(blocked, "正文字号").getByRole("button", { name: "小", exact: true }).click();
  await expect(blocked.locator("html")).toHaveAttribute("data-font-size", "small");
  expect(errors).toEqual([]);
  await blocked.context().close();
});

test("偏好：正文字号小、中、大改变写作页的字，中就是原来的字号", async ({ page }) => {
  await registerAccount(page, "size");
  const work = await createWorkByApi(page, { title: "字号试验" });
  const sizeOfEditor = async () => parseFloat(await page.getByRole("textbox", { name: "草稿正文", exact: true }).evaluate((node) => getComputedStyle(node).fontSize));
  await page.goto("/settings/preferences");
  const sizes = group(page, "正文字号");
  await expect(sizes.getByRole("button", { name: "中", exact: true })).toHaveAttribute("aria-pressed", "true");
  const read = async (choice: string, expected: number) => {
    await page.goto("/settings/preferences");
    await sizes.getByRole("button", { name: choice, exact: true }).click();
    await page.goto(`/projects/${work}/workspace`);
    await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
    expect(await sizeOfEditor()).toBeCloseTo(expected, 0);
  };
  await read("中", 19);
  await read("大", 21);
  await read("小", 17);
  // It is remembered on this device, and takes hold before the page is drawn.
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-font-size", "small");
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeVisible();
  expect(await sizeOfEditor()).toBeCloseTo(17, 0);
  // Back to 中: the attribute stays out of the way and the size is the old one.
  await page.goto("/settings/preferences");
  await sizes.getByRole("button", { name: "中", exact: true }).click();
  expect(await page.evaluate(() => localStorage.getItem("story-continuity:font-size"))).toBeNull();
});

test("数据：导出全部作品下载一个 zip，不含示例作品；删除账号暂不提供", async ({ page }) => {
  await registerAccount(page, "export");
  const first = await createWorkByApi(page, { title: "盐雾之下" });
  await createWorkByApi(page, { title: "纸灯" });
  await saveDraft(page, first, "还没入库的草稿EXPORT-ME。");
  await page.goto("/settings/data");
  await expect(page.getByText("单部作品仍可在作品的“更多”里导出", { exact: true })).toBeVisible();
  await expect(page.getByText("暂不提供", { exact: true })).toBeVisible();
  await expect(page.getByText("删除账号", { exact: true })).toBeVisible();
  await shot(page, "settings-data");
  const download = page.waitForEvent("download");
  await page.getByRole("button", { name: "导出", exact: true }).click();
  const file = await download;
  expect(file.suggestedFilename()).toBe(`story-continuity-全部作品-${dayOf().replaceAll("-", "")}.zip`);
  const bytes = await readFile(await file.path());
  expect(bytes.subarray(0, 2).toString("latin1")).toBe("PK");
  const text = bytes.toString("latin1");
  for (const name of ["index.json", "README.txt", "manuscript.txt", "snapshot.json", "checksums.json"]) expect(text).toContain(name);
  await expect(page.getByText("文件已生成，看一下浏览器的下载列表。", { exact: true })).toBeVisible();
  // The server's own answer: two works, the sample left out.
  const response = await page.request.get("/api/account/export");
  expect(response.status()).toBe(200);
  expect(response.headers()["content-type"]).toBe("application/zip");
  const entries = (await response.body()).toString("utf8");
  expect(entries).toContain("盐雾之下");
  expect(entries).toContain("纸灯");
});

test("数据：访客的导出按钮不可用并说明原因", async ({ page }) => {
  await startVisitor(page);
  await page.goto("/settings/data");
  await expect(page.getByRole("button", { name: "导出", exact: true })).toBeDisabled();
  await expect(page.getByText("访客空间不能导出全部作品；注册个人账号后可以使用。", { exact: true })).toBeVisible();
  const refused = await api(page).raw("GET", "/account/export");
  expect(refused.status).toBe(403);
});

test("窄屏 375：作者主页单列，设置的左栏变成一行能横向滚动的导航", async ({ page }) => {
  await registerAccount(page, "narrow");
  const work = await createWorkByApi(page, { title: "窄屏之书" });
  await saveDraft(page, work, "窄屏上写的字。".repeat(20));
  await page.setViewportSize({ width: 375, height: 800 });
  await page.goto("/account");
  await expect(page.getByRole("heading", { level: 1, name: "E2E 作者", exact: true })).toBeVisible();
  const overflow = () => page.evaluate(() => document.documentElement.scrollWidth - document.documentElement.clientWidth);
  expect(await overflow()).toBeLessThanOrEqual(0);
  const hero = await page.locator(".author-hero").boundingBox();
  const avatar = await page.locator(".avatar-xl").boundingBox();
  const name = await page.locator(".author-name").boundingBox();
  expect(name!.y).toBeGreaterThanOrEqual(avatar!.y + avatar!.height - 1);
  expect(hero!.width).toBeLessThanOrEqual(375);
  const calendar = page.locator(".heat-scroll");
  expect(await calendar.evaluate((node) => node.scrollWidth > node.clientWidth)).toBe(true);
  expect(await calendar.evaluate((node) => node.scrollLeft)).toBeGreaterThan(0);
  const works = await page.locator(".author ul.works > li").evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().left)));
  expect(new Set(works).size).toBe(1);
  await shot(page, "author-home-narrow");

  await page.goto("/settings/profile");
  expect(await overflow()).toBeLessThanOrEqual(0);
  const links = page.locator(".settings-links");
  const box = await links.boundingBox();
  const title = await page.getByRole("heading", { level: 1, name: "设置", exact: true }).boundingBox();
  expect(box!.y).toBeGreaterThan(title!.y);
  const buttons = await links.getByRole("button").evaluateAll((nodes) => nodes.map((node) => Math.round(node.getBoundingClientRect().top)));
  expect(new Set(buttons).size).toBe(1);
  expect(await links.evaluate((node) => getComputedStyle(node).overflowX)).toBe("auto");
  await links.getByRole("button", { name: "数据", exact: true }).click();
  await expect(page).toHaveURL(/\/settings\/data$/);
  await shot(page, "settings-narrow");
});

test("夜间：作者主页和设置在夜间主题下都读得清", async ({ page }) => {
  await registerAccount(page, "night");
  const me = (await api(page).get("/auth/session")).user;
  const work = await createWorkByApi(page, { title: "夜间之书" });
  for (const offset of [-1, -2, -3]) await writeOn(page, me.id, work, dayOf(offset), 900 * -offset);
  await page.goto("/account");
  await theme(page, "night");
  const shades = await page.locator(".heat-grid i").evaluateAll((nodes) => [...new Set(nodes.map((node) => getComputedStyle(node).backgroundColor))]);
  expect(shades.length).toBeGreaterThanOrEqual(3);
  await shot(page, "author-home-night");
  await page.goto("/settings/usage");
  await shot(page, "settings-usage-night");
});

test("sample 工作的写作不进写作日历", async ({ page }) => {
  await registerAccount(page, "sample");
  const sample = await sampleWorkId(page);
  await saveDraft(page, sample, "示例作品里随手改的字。".repeat(10));
  await page.goto("/account");
  await expect(page.locator(".author-figs .v").nth(0)).toHaveText("0");
  await expect(page.locator(".author-figs .v.blue")).toHaveText("0");
  await expect(page.getByText("还没有动态", { exact: false })).toBeVisible();
});
