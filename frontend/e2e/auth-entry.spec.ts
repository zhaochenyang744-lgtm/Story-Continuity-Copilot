import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";

const apiFailure = (code: string, message = "认证请求未完成") => ({
  error: { code, message, retryable: code === "authentication_rate_limited" },
});

test("login and register keep distinct validation contracts and responsive entry layout", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto("/login");
  const loginAccount = page.getByLabel("账号");
  const loginPassword = page.getByLabel("密码");
  await expect(loginAccount).toBeFocused();
  expect(await loginAccount.evaluate((input) => (input as HTMLInputElement).minLength)).toBe(-1);
  expect(await loginPassword.evaluate((input) => (input as HTMLInputElement).minLength)).toBe(-1);
  await expect(page.getByText("账号至少 3 个字符，密码至少 10 个字符。", { exact: true })).toHaveCount(0);

  await page.goto("/register");
  const registerAccount = page.getByLabel("账号");
  const registerPassword = page.getByLabel("密码");
  expect(await registerAccount.evaluate((input) => (input as HTMLInputElement).minLength)).toBe(3);
  expect(await registerPassword.evaluate((input) => (input as HTMLInputElement).minLength)).toBe(10);
  await expect(page.getByText("账号至少 3 个字符，密码至少 10 个字符。", { exact: true })).toBeVisible();
  await expect(page.getByText("测试阶段暂不支持找回密码，请妥善保管。", { exact: true })).toBeVisible();

  await page.setViewportSize({ width: 390, height: 844 });
  await expect(registerAccount).toHaveCSS("font-size", "16px");
  const [primary, secondary] = await Promise.all([
    page.getByRole("button", { name: "创建本地账号", exact: true }).boundingBox(),
    page.getByRole("button", { name: "已有账号？返回登录", exact: true }).boundingBox(),
  ]);
  if (!primary || !secondary) throw new Error("认证操作按钮不可测量");
  expect(secondary.y).toBeGreaterThanOrEqual(primary.y + primary.height + 8);

  await page.goto("/login");
  await expect(page.getByLabel("账号")).not.toBeFocused();
});

test("credential errors are inline, accessible, replaceable, and keep the recovery actions stable", async ({ page }) => {
  let releaseRateLimit!: () => void;
  let loginCalls = 0;
  const rateLimitReady = new Promise<void>((resolve) => {
    releaseRateLimit = resolve;
  });
  await page.route("**/api/auth/login", async (route) => {
    loginCalls += 1;
    if (loginCalls === 1) {
      await route.fulfill({ status: 401, contentType: "application/json", body: JSON.stringify(apiFailure("invalid_credentials")) });
      return;
    }
    await rateLimitReady;
    await route.fulfill({ status: 429, contentType: "application/json", body: JSON.stringify(apiFailure("authentication_rate_limited")) });
  });
  await page.goto("/login");
  await page.getByLabel("账号").fill("valid-user");
  await page.getByLabel("密码").fill("valid-password");
  await page.getByRole("button", { name: "登录", exact: true }).click();

  const alert = page.locator("#auth-error");
  await expect(alert).toHaveText("账号或密码不正确。");
  for (const input of [page.getByLabel("账号"), page.getByLabel("密码")]) {
    await expect(input).toHaveAttribute("aria-invalid", "true");
    await expect(input).toHaveAttribute("aria-describedby", "auth-error");
  }
  await expect(page.getByLabel("账号")).toBeFocused();

  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(alert).toHaveCount(0);
  await expect(page.getByRole("button", { name: "登录", exact: true })).toHaveAttribute("aria-busy", "true");
  await expect(page.getByRole("button", { name: "还没有账号？创建本地账号", exact: true })).toBeDisabled();
  releaseRateLimit();
  await expect(alert).toHaveText("登录尝试过于频繁，请稍后再试。");
  await expect(page.getByText("已清除当前作品上下文", { exact: false })).toHaveCount(0);
});

test("password visibility toggles without changing the authentication flow", async ({ page }) => {
  await page.goto("/login");
  const password = page.getByLabel("密码");
  const toggle = page.getByRole("button", { name: "切换口令可见性", exact: true });
  await expect(toggle).toHaveAttribute("aria-pressed", "false");
  await toggle.click();
  await expect(password).toHaveAttribute("type", "text");
  await expect(toggle).toHaveAttribute("aria-pressed", "true");
});

test("client-side navigation after login keeps the bootstrapped session and never re-shows the bootstrap screen", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const sessionRequests: string[] = [];
  page.on("request", (request) => {
    if (new URL(request.url()).pathname === "/api/auth/session") sessionRequests.push(request.url());
  });
  await page.goto("/register");
  await page.getByLabel("账号").fill(`authnav${Date.now()}`);
  await page.getByLabel("显示名称").fill("认证导航测试");
  await page.getByLabel("密码").fill(`safe-${randomUUID()}`);
  await page.getByRole("button", { name: "创建本地账号", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  expect(sessionRequests.length).toBeGreaterThan(0);
  sessionRequests.length = 0;

  const homeNav = page.locator(".global-nav").getByRole("button", { name: "首页", exact: true });
  const projectsNav = page.locator(".global-nav").getByRole("button", { name: "作品管理", exact: true });
  const navMetrics = async (button: import("@playwright/test").Locator) =>
    button.evaluate((element) => {
      const buttonBox = element.getBoundingClientRect();
      const iconBox = element.querySelector("svg")?.getBoundingClientRect();
      const text = Array.from(element.childNodes).find((node) => node.nodeType === Node.TEXT_NODE && node.textContent?.trim());
      const range = document.createRange();
      if (text) range.selectNodeContents(text);
      const textBox = range.getBoundingClientRect();
      return {
        width: buttonBox.width,
        justifyContent: getComputedStyle(element).justifyContent,
        iconLeft: iconBox ? iconBox.left - buttonBox.left : -1,
        textLeft: textBox.left - buttonBox.left,
      };
    });
  const [homeBefore, projectsBefore] = await Promise.all([navMetrics(homeNav), navMetrics(projectsNav)]);
  expect(homeBefore.justifyContent).toBe("flex-start");
  expect(projectsBefore.justifyContent).toBe("flex-start");
  expect(homeBefore.width).toBe(projectsBefore.width);
  expect(homeBefore.iconLeft).toBe(projectsBefore.iconLeft);
  expect(homeBefore.textLeft).toBe(projectsBefore.textLeft);

  const homeHead = page.locator(".home-section-head");
  const issueHead = page.locator(".home-issues-section > h2");
  await expect(homeHead).toHaveCSS("min-height", "40px");
  await expect(issueHead).toHaveCSS("min-height", "40px");
  const [homeHeadBox, homeButtonBox, issueHeadBox] = await Promise.all([
    homeHead.boundingBox(),
    homeHead.getByRole("button", { name: "查看全部作品", exact: true }).boundingBox(),
    issueHead.boundingBox(),
  ]);
  if (!homeHeadBox || !homeButtonBox || !issueHeadBox) throw new Error("首页标题行不可测量");
  expect(Math.abs(homeHeadBox.y + homeHeadBox.height / 2 - (homeButtonBox.y + homeButtonBox.height / 2))).toBeLessThanOrEqual(1);
  expect(homeHeadBox.height).toBe(issueHeadBox.height);

  await projectsNav.click();
  await expect(page.getByRole("heading", { name: "作品管理" })).toBeVisible();
  const [homeActive, projectsActive] = await Promise.all([navMetrics(homeNav), navMetrics(projectsNav)]);
  expect(homeActive.iconLeft).toBe(homeBefore.iconLeft);
  expect(homeActive.textLeft).toBe(homeBefore.textLeft);
  expect(projectsActive.iconLeft).toBe(projectsBefore.iconLeft);
  expect(projectsActive.textLeft).toBe(projectsBefore.textLeft);
  await homeNav.click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  expect(sessionRequests).toEqual([]);
  await expect(page.getByText("正在恢复本地会话…", { exact: true })).toHaveCount(0);
  await page.setViewportSize({ width: 390, height: 844 });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
});

test("an existing session entering /login waits for the session check and replaces the route without an auth-card flash", async ({ page }) => {
  const account = `authredirect${Date.now()}`;
  const password = `safe-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("认证重定向测试");
  await page.getByLabel("密码").fill(password);
  await page.getByRole("button", { name: "创建本地账号", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);

  let release!: () => void;
  let intercepted!: () => void;
  const delayed = new Promise<void>((resolve) => { release = resolve; });
  const interceptedRequest = new Promise<void>((resolve) => { intercepted = resolve; });
  await page.route(/\/api\/auth\/session(?:\?optional=true)?$/, async (route) => {
    const response = await route.fetch();
    intercepted();
    await delayed;
    await route.fulfill({ response });
  });
  await page.goto("/login");
  await interceptedRequest;
  await expect(page.locator(".auth")).toHaveCount(0);
  release();
  await expect(page).toHaveURL(/\/$/);
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
});
