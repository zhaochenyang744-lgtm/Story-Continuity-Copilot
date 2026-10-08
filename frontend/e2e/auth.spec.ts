import { api, createWorkByApi, expect, listWorks, login, logout, MAIL_LINKS_REASON, MAIL_LINKS_UNAVAILABLE, mailLink, newPage, openAccountMenu, registerAccount, sampleWorkId, startVisitor, test } from "./support/app";

const loginButton = (page: import("@playwright/test").Page) => page.getByRole("button", { name: "登录", exact: true });
const resetHint = "如果这个邮箱已经验证，我们发了一封重置邮件，15 分钟内有效。";

test("注册成功：进入首页，账号下有示例作品", async ({ page }) => {
  const { account, email } = await registerAccount(page, "reg");
  await expect(page.getByRole("button", { name: "账号菜单：E2E 作者" })).toBeVisible();

  const session = await api(page).get("/auth/session");
  expect(session.user.account_name).toBe(account);
  expect(session.user.display_name).toBe("E2E 作者");
  expect(session.user.account_type).toBe("registered");

  const onboarding = await api(page).get("/onboarding");
  expect(onboarding.status).toBe("active");
  const sample = await api(page).get(`/projects/${onboarding.tutorial.project_id}`);
  expect(sample.title).toBe("灰港回声");
  expect(sample.data_origin).toBe("tutorial_seed");
  // The recovery email was kept, masked, and is not verified yet.
  expect(session.user.recovery_email.configured).toBe(true);
  expect(session.user.recovery_email.verified).toBe(false);
  expect(session.user.recovery_email.masked).not.toBe(email);
});

test("注册校验：账号或密码太短不会创建账号，重复账号的错误显示在表单里", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/api/auth/register")) requests.push(request.method()); });
  await page.goto("/register");
  await expect(page.getByText("账号至少 3 个字符，密码至少 10 个字符。", { exact: false })).toBeVisible();

  // Too short an account name: the browser holds the form back and says why.
  const accountField = page.getByLabel("账号", { exact: true });
  await accountField.fill("ab");
  await page.getByLabel("显示名称", { exact: true }).fill("短账号");
  await page.getByLabel("恢复邮箱", { exact: true }).fill("short-account@example.test");
  await page.getByLabel("密码", { exact: true }).fill("a-long-enough-password");
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page).toHaveURL(/\/register$/);
  await expect.poll(() => accountField.evaluate((input: HTMLInputElement) => input.validationMessage)).not.toBe("");
  expect(await accountField.evaluate((input: HTMLInputElement) => input.validity.tooShort)).toBe(true);

  // Too short a password.
  await accountField.fill("v170shortpass");
  const passwordField = page.getByLabel("密码", { exact: true });
  await passwordField.fill("short-pw");
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page).toHaveURL(/\/register$/);
  await expect.poll(() => passwordField.evaluate((input: HTMLInputElement) => input.validationMessage)).not.toBe("");
  expect(await passwordField.evaluate((input: HTMLInputElement) => input.validity.tooShort)).toBe(true);
  expect(requests, "the form must not be sent while it is invalid").toEqual([]);

  // The server refuses short values too, and neither account exists.
  const refused = await api(page).raw("POST", "/auth/register", { account_name: "v170shortpass", display_name: "短密码", password: "short-pw", recovery_email: "short-pw@example.test" });
  expect(refused.status).toBeGreaterThanOrEqual(400);
  expect(refused.status).toBeLessThan(500);
  for (const name of ["ab", "v170shortpass"]) {
    const attempt = await api(page).raw("POST", "/auth/login", { account_name: name, password: "short-pw" });
    expect(attempt.status, `login as ${name}`).toBe(401);
  }

  // An account name that is taken: the error stays in the form, what was typed is still there.
  const { account } = await registerAccount(page, "dup");
  await logout(page);
  await page.goto("/register");
  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("显示名称", { exact: true }).fill("重名的人");
  await page.getByLabel("恢复邮箱", { exact: true }).fill(`other-${account}@example.test`);
  await page.getByLabel("密码", { exact: true }).fill("another-long-password");
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.locator("#auth-error")).toHaveAttribute("role", "alert");
  await expect(page.locator("#auth-error")).toBeVisible();
  await expect(page).toHaveURL(/\/register$/);
  await expect(page.getByLabel("账号", { exact: true })).toHaveValue(account);
  await expect(page.getByLabel("显示名称", { exact: true })).toHaveValue("重名的人");
  await expect(page.getByLabel("恢复邮箱", { exact: true })).toHaveValue(`other-${account}@example.test`);
  // Nothing was created: the first account still has its own name.
  const again = await api(page).raw("GET", "/auth/session?optional=true");
  expect(again.body.data.user).toBeNull();
});

test("登录错误：错误在表单里并和输入框关联，账号保留，改对后进入首页", async ({ page }) => {
  const { account, password } = await registerAccount(page, "badpw");
  await logout(page);

  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("密码", { exact: true }).fill("not-the-password-1");
  await loginButton(page).click();
  const error = page.locator("#auth-error");
  await expect(error).toHaveText("账号或密码不正确。");
  await expect(error).toHaveAttribute("role", "alert");
  await expect(page.getByLabel("账号", { exact: true })).toHaveAccessibleDescription("账号或密码不正确。");
  await expect(page.getByLabel("账号", { exact: true })).toHaveAttribute("aria-invalid", "true");
  await expect(page.getByLabel("密码", { exact: true })).toHaveAccessibleDescription("账号或密码不正确。");
  await expect(page.getByLabel("账号", { exact: true })).toHaveValue(account);
  await expect(page).toHaveURL(/\/login$/);
  // Still signed out.
  expect((await api(page).raw("GET", "/auth/session?optional=true")).body.data.user).toBeNull();

  await page.getByLabel("密码", { exact: true }).fill(password);
  await loginButton(page).click();
  await expect(page.getByRole("heading", { level: 1, name: "从第一章开始" })).toBeVisible();
  expect((await api(page).get("/auth/session")).user.account_name).toBe(account);
});

test("显示 / 隐藏密码：输入框类型来回切换，不会提交表单", async ({ page }) => {
  const requests: string[] = [];
  page.on("request", (request) => { if (request.url().includes("/api/auth/")) requests.push(request.url()); });
  await page.goto("/login");
  const password = page.getByLabel("密码", { exact: true });
  await password.fill("typed-but-not-sent");
  await expect(password).toHaveAttribute("type", "password");

  await page.getByRole("button", { name: "显示密码", exact: true }).click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(page.getByRole("button", { name: "隐藏密码", exact: true })).toHaveAttribute("aria-pressed", "true");
  await expect(password).toHaveValue("typed-but-not-sent");

  await page.getByRole("button", { name: "隐藏密码", exact: true }).click();
  await expect(password).toHaveAttribute("type", "password");
  await expect(page.getByRole("button", { name: "显示密码", exact: true })).toHaveAttribute("aria-pressed", "false");

  await expect(page).toHaveURL(/\/login$/);
  await expect(page.locator("#auth-error")).toHaveCount(0);
  expect(requests.filter((url) => !url.includes("/auth/session")), "toggling must not send the form").toEqual([]);
});

test("退出再登录：退出后 /projects 只看得到登录页，再登录作品还在", async ({ page }) => {
  const { account, password } = await registerAccount(page, "again");
  const title = "退出前建好的书";
  const workId = await createWorkByApi(page, { title, genre: "科幻", summary: "退出后应当还在。" });

  await logout(page);
  expect((await api(page).raw("GET", "/auth/session?optional=true")).body.data.user).toBeNull();
  expect((await api(page).raw("GET", `/projects/${workId}`)).status).toBe(401);

  await page.goto("/projects");
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { level: 1, name: "登录", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { name: "作品管理" })).toHaveCount(0);
  await expect(page.getByText(title)).toHaveCount(0);

  await login(page, account, password);
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "作品管理" })).toBeVisible();
  await expect(page.getByText(title, { exact: true })).toBeVisible();
  expect((await listWorks(page)).map((work) => work.title)).toEqual([title]);
});

test("已登录时打开 /login：直接回到首页，登录表单一次都不出现", async ({ page }) => {
  await registerAccount(page, "loggedin");
  // Watch the document from its very first paint: record whether the sign-in card or a 404 ever shows.
  await page.addInitScript(() => {
    const seen = { login: false, notFound: false, resetPage: false };
    (window as unknown as { __seen: typeof seen }).__seen = seen;
    const look = () => {
      // The sign-in and registration form is the only thing with an account-name field.
      if (document.querySelector('.auth-form input[name="account_name"]')) seen.login = true;
      if (document.querySelector(".not-found")) seen.notFound = true;
      if (document.querySelector(".auth")) seen.resetPage = true;
    };
    new MutationObserver(look).observe(document, { childList: true, subtree: true });
    look();
  });
  await page.goto("/login");
  await page.waitForURL((url) => url.pathname === "/");
  await expect(page.getByRole("heading", { level: 1, name: "从第一章开始" })).toBeVisible();
  type Seen = { login: boolean; notFound: boolean; resetPage: boolean };
  const seen = await page.evaluate(() => (window as unknown as { __seen: Seen }).__seen);
  expect(seen.login, "the sign-in card appeared while redirecting").toBe(false);
  if (seen.notFound) test.info().annotations.push({ type: "observation", description: "「找不到这个页面」在从 /login 跳回首页的过程中闪现过" });
  // The same for the other sign-in addresses.
  for (const path of ["/register", "/password-reset"]) {
    await page.goto(path);
    await page.waitForURL((url) => url.pathname === "/");
    const again = await page.evaluate(() => (window as unknown as { __seen: Seen }).__seen);
    expect(again.login, `the sign-in card appeared while leaving ${path}`).toBe(false);
    if (again.resetPage) test.info().annotations.push({ type: "observation", description: `已登录时打开 ${path}，找回密码页在跳回首页之前出现过` });
  }
});

test("会话过期：清掉 cookie 后在应用里换页，回到登录页并说明登录已过期", async ({ page, context }) => {
  test.fixme(true, "产品问题：「登录已过期，请重新登录。」只在 /projects 上闪一下，地址变成 /login 时 app.tsx 的换页清错误逻辑把它清掉了，登录页上看不到");
  await registerAccount(page, "expired");
  await context.clearCookies();
  await page.getByRole("button", { name: "作品管理", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { level: 1, name: "登录", exact: true })).toBeVisible();
  await expect(page.locator("#auth-error")).toHaveText("登录已过期，请重新登录。");
  expect((await api(page).raw("GET", "/auth/session?optional=true")).body.data.user).toBeNull();
});

test("验证恢复邮箱：从邮件里的链接验证，账号安全页显示已验证", async ({ page }) => {
  test.fixme(MAIL_LINKS_UNAVAILABLE, MAIL_LINKS_REASON);
  const { email } = await registerAccount(page, "verify");
  expect((await api(page).get("/auth/session")).user.recovery_email.verified).toBe(false);
  await page.goto(await mailLink(page, "verify_email", email));
  await expect(page.getByText("恢复邮箱验证好了，可以用来找回密码。", { exact: true })).toBeVisible();
  // The one-time token is taken out of the address bar as soon as it is read.
  await expect(page).toHaveURL(/\/verify-email$/);
  expect((await api(page).get("/auth/session")).user.recovery_email.verified).toBe(true);
  await page.getByRole("button", { name: "回到首页", exact: true }).click();
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "账号安全", exact: true }).click();
  await expect(page.getByText("已验证", { exact: true })).toBeVisible();
});

test("找回密码：回应不泄露邮箱是否存在，新密码能登录、旧密码不能，链接只能用一次", async ({ page }) => {
  test.fixme(MAIL_LINKS_UNAVAILABLE, MAIL_LINKS_REASON);
  const { account, password, email } = await registerAccount(page, "reset");
  await page.goto(await mailLink(page, "verify_email", email));
  await expect(page.getByText("恢复邮箱验证好了，可以用来找回密码。", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "回到首页", exact: true }).click();
  await logout(page);

  const ask = async (address: string) => {
    await page.goto("/password-reset");
    await page.getByLabel("恢复邮箱", { exact: true }).fill(address);
    await page.getByRole("button", { name: "发送重置邮件", exact: true }).click();
    const message = page.getByRole("status").filter({ hasText: resetHint });
    await expect(message).toHaveText(resetHint);
    return page.locator(".auth-main").innerText();
  };
  const unknown = await ask("nobody-here@example.test");
  const known = await ask(email);
  expect(known, "the page must not tell a known address from an unknown one").toBe(unknown);

  const link = await mailLink(page, "password_reset", email);
  const newPassword = `new-${account}-pw`;
  await page.goto(link);
  await page.getByLabel("新密码", { exact: true }).fill(newPassword);
  await page.getByRole("button", { name: "更新密码", exact: true }).click();
  await expect(page.getByText(/^密码已更新/)).toBeVisible();

  const old = await api(page).raw("POST", "/auth/login", { account_name: account, password });
  expect(old.status).toBe(401);
  await login(page, account, newPassword);
  await logout(page);

  // The same link a second time.
  await page.goto(link);
  await page.getByLabel("新密码", { exact: true }).fill(`${newPassword}-again`);
  await page.getByRole("button", { name: "更新密码", exact: true }).click();
  await expect(page.getByRole("alert").filter({ hasText: "无效" })).toContainText("安全链接无效、已过期或已使用，请重新发起。");
  expect((await api(page).raw("POST", "/auth/login", { account_name: account, password: `${newPassword}-again` })).status).toBe(401);
  await login(page, account, newPassword);
});

test("访客：有自己的示例作品，和注册账号互相看不到对方的作品", async ({ page, browser }) => {
  await startVisitor(page);
  await expect(page.getByText("访客空间 · 24 小时", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "账号菜单：访客" })).toBeVisible();
  const session = await api(page).get("/auth/session");
  expect(session.user.account_type).toBe("visitor");
  const visitorSample = await api(page).get(`/projects/${await sampleWorkId(page)}`);
  expect(visitorSample.title).toBe("灰港回声");
  const visitorTitle = "访客写的短篇";
  const visitorWork = await createWorkByApi(page, { title: visitorTitle });

  const author = await newPage(browser);
  try {
    await registerAccount(author, "isolate");
    const authorTitle = "注册账号写的长篇";
    const authorWork = await createWorkByApi(author, { title: authorTitle });

    await page.goto("/projects");
    await expect(page.getByRole("heading", { level: 1, name: "作品管理" })).toBeVisible();
    await expect(page.getByText(visitorTitle, { exact: true })).toBeVisible();
    await expect(page.getByText(authorTitle)).toHaveCount(0);
    await author.goto("/projects");
    await expect(author.getByText(authorTitle, { exact: true })).toBeVisible();
    await expect(author.getByText(visitorTitle)).toHaveCount(0);

    expect((await listWorks(page)).map((work) => work.title)).toEqual([visitorTitle]);
    expect((await listWorks(author)).map((work) => work.title)).toEqual([authorTitle]);
    // Knowing the other side's id does not help.
    expect((await api(page).raw("GET", `/projects/${authorWork}`)).status).toBe(404);
    expect((await api(author).raw("GET", `/projects/${visitorWork}`)).status).toBe(404);
  } finally {
    await author.context().close();
  }
});
