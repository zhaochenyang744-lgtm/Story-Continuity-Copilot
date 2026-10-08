import { accountMenuButton, api, expect, MAIL_LINKS_REASON, MAIL_LINKS_UNAVAILABLE, mailerCalls, mailLink, openAccountMenu, registerAccount, shot, startVisitor, test } from "./support/app";

const profile = (page: import("@playwright/test").Page) => page.getByRole("region", { name: "个人信息", exact: true });

test("个人信息：查看模式 → 编辑改名 → 保存，顶栏跟着变，登录账号不变，刷新后还在", async ({ page }) => {
  const { account } = await registerAccount(page, "profile");
  await openAccountMenu(page);
  await expect(page.getByRole("menu", { name: "账号菜单" })).toContainText(`@${account}`);
  await page.getByRole("menuitem", { name: "个人信息", exact: true }).click();
  await expect(page).toHaveURL(/\/account\/profile$/);

  // 查看: the name is shown as text, nothing to type into.
  await expect(page.getByRole("heading", { level: 1, name: "E2E 作者", exact: true })).toBeVisible();
  await expect(profile(page).getByText("登录账号", { exact: true })).toBeVisible();
  await expect(profile(page).getByText(account, { exact: true })).toBeVisible();
  await expect(profile(page).getByText("个人账号", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "显示名称", exact: true })).toHaveCount(0);
  await shot(page, "profile-view");

  // 编辑
  const before = (await api(page).get("/auth/session")).user;
  await profile(page).getByRole("button", { name: "编辑", exact: true }).click();
  const name = page.getByRole("textbox", { name: "显示名称", exact: true });
  await expect(name).toHaveValue("E2E 作者");
  const save = page.getByRole("button", { name: "保存", exact: true });
  await expect(save).toBeDisabled();
  await name.fill("夜航的笔名");
  await expect(save).toBeEnabled();
  await shot(page, "profile-edit");
  await save.click();

  await expect(page.getByText("已保存。", { exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "夜航的笔名", exact: true })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "显示名称", exact: true })).toHaveCount(0);
  await expect(accountMenuButton(page)).toHaveAccessibleName("账号菜单：夜航的笔名");
  await openAccountMenu(page);
  await expect(page.getByRole("menu", { name: "账号菜单" })).toContainText(`@${account}`);
  await page.keyboard.press("Escape");

  const after = (await api(page).get("/auth/session")).user;
  expect(after.display_name).toBe("夜航的笔名");
  expect(after.account_name).toBe(account);
  expect(after.profile_revision).toBe(before.profile_revision + 1);

  await page.reload();
  await expect(page.getByRole("heading", { level: 1, name: "夜航的笔名", exact: true })).toBeVisible();
  await expect(accountMenuButton(page)).toHaveAccessibleName("账号菜单：夜航的笔名");
});

test("编辑时取消：名称恢复，后端没有变化", async ({ page }) => {
  const { account } = await registerAccount(page, "profilecancel");
  await page.goto("/account/profile");
  const before = (await api(page).get("/auth/session")).user;
  await profile(page).getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByRole("textbox", { name: "显示名称", exact: true }).fill("不想保存的名字");
  await page.getByRole("button", { name: "取消", exact: true }).click();

  await expect(page.getByRole("textbox", { name: "显示名称", exact: true })).toHaveCount(0);
  await expect(page.getByRole("heading", { level: 1, name: "E2E 作者", exact: true })).toBeVisible();
  await expect(page.getByText("不想保存的名字")).toHaveCount(0);
  await expect(page.getByText("已保存。")).toHaveCount(0);
  const after = (await api(page).get("/auth/session")).user;
  expect(after.display_name).toBe("E2E 作者");
  expect(after.account_name).toBe(account);
  expect(after.profile_revision).toBe(before.profile_revision);
  // Editing again starts from the saved name, not from the abandoned one.
  await profile(page).getByRole("button", { name: "编辑", exact: true }).click();
  await expect(page.getByRole("textbox", { name: "显示名称", exact: true })).toHaveValue("E2E 作者");
});

test("账号安全：当前恢复邮箱和状态，更换邮箱后变成未验证并收到新的验证邮件，可以重新发送", async ({ page }) => {
  test.fixme(MAIL_LINKS_UNAVAILABLE, MAIL_LINKS_REASON);
  const { email } = await registerAccount(page, "security");
  await page.goto("/account/security");
  await expect(page.getByRole("heading", { level: 1, name: "账号安全", exact: true })).toBeVisible();
  const first = (await api(page).get("/auth/session")).user.recovery_email;
  expect(first).toMatchObject({ configured: true, verified: false });
  await expect(page.getByText(first.masked, { exact: true })).toBeVisible();
  await expect(page.getByText("未验证", { exact: true })).toBeVisible();

  // Verify it, so that the change below visibly takes the verification away.
  await page.goto(await mailLink(page, "verify_email", email));
  await expect(page.getByText("恢复邮箱验证好了，可以用来找回密码。", { exact: true })).toBeVisible();
  await page.goto("/account/security");
  await expect(page.getByText("已验证", { exact: true })).toBeVisible();
  expect((await api(page).get("/auth/session")).user.recovery_email.verified).toBe(true);

  // 换一个邮箱
  const mails = await mailerCalls(page);
  const newEmail = `moved-${email}`;
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
  await shot(page, "security");

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
  await page.goto("/account/security");
  await expect(page.getByText("已验证", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "重新发送验证", exact: true })).toHaveCount(0);
});

test("访客的个人中心：账号类型是访客空间，不能绑定恢复邮箱", async ({ page }) => {
  await startVisitor(page);
  await openAccountMenu(page);
  // A visitor's menu has only the way out.
  await expect(page.getByRole("menuitem")).toHaveText(["退出登录"]);
  await page.keyboard.press("Escape");

  await page.goto("/account/profile");
  await expect(page.getByRole("heading", { level: 1, name: "访客", exact: true })).toBeVisible();
  await expect(page.getByText("访客空间", { exact: true })).toBeVisible();
  await expect(profile(page).getByText("访客空间（注册后可以长期保存）", { exact: true })).toBeVisible();
  await expect(profile(page).getByRole("button", { name: "编辑", exact: true })).toHaveCount(0);
  await expect(profile(page).getByText("登录账号", { exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "账号安全 · 恢复邮箱", exact: true })).toHaveCount(0);

  await page.goto("/account/security");
  await expect(page.getByRole("heading", { level: 1, name: "账号安全", exact: true })).toBeVisible();
  await expect(page.getByText("访客空间不能绑定恢复邮箱。注册个人账号后就可以绑定。", { exact: true })).toBeVisible();
  await expect(page.getByText("还没绑定", { exact: true })).toBeVisible();
  await expect(page.getByRole("textbox")).toHaveCount(0);
  await expect(page.getByRole("button", { name: /绑定并发送验证|更换并发送验证/ })).toHaveCount(0);

  // The server agrees.
  const user = (await api(page).get("/auth/session")).user;
  expect(user.account_type).toBe("visitor");
  const edit = await api(page).raw("PATCH", "/auth/profile", { base_profile_revision: user.profile_revision, display_name: "想改名的访客", avatar_preset: "continuity_violet" });
  expect(edit.status).toBe(403);
  const bind = await api(page).raw("POST", "/auth/recovery-email", { recovery_email: "visitor@example.test" });
  expect(bind.status).toBe(403);
  expect((await api(page).get("/auth/session")).user.display_name).toBe(user.display_name);
});
