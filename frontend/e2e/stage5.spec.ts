import AxeBuilder from "@axe-core/playwright";
import { expect, Page, test } from "@playwright/test";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";
import { randomUUID } from "node:crypto";

const shots = process.env.E2E_SCREENSHOTS_DIR
  ? path.resolve(process.env.E2E_SCREENSHOTS_DIR)
  : path.resolve(process.cwd(), "../artifacts/stage5-screenshots");
const account = (prefix: string) => `${prefix}${Date.now()}${Math.random().toString(16).slice(2, 8)}`;
const apiCorpus = { response_count: 0, endpoint_templates: {} as Record<string, Record<string, number>>, parse_failures: {} as Record<string, number>, parse_failure_kinds: {} as Record<string, number>, categories: { private_key: 0, api_key: 0, session_token: 0, password: 0, import_body: 0, raw_provider_body: 0, chain_of_thought: 0, absolute_path: 0, protected_poc_path: 0 }, unresolved: 0 };
const apiCorpusPending = new Set<Promise<void>>();
type ApiBodySession = { send(method: string, params?: { requestId: string }): Promise<unknown>; detach(): Promise<void> };
type PendingApiBody = { key: string; status: number };
const apiCorpusContexts = new Set<{ session: ApiBodySession; pendingBodies: Map<string, PendingApiBody> }>();
const templateEndpoint = (pathname: string) => pathname.replace(/\b[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}\b/gi, ":id").replace(/\b(?:prj|run|draft|issue|change|import)-[a-z0-9-]+\b/gi, ":id");
const sensitivePatterns: Record<keyof typeof apiCorpus.categories, RegExp> = { private_key: /-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----/, api_key: /api[_-]?key|authorization\s*:\s*bearer/i, session_token: /scc_local_session|session[_-]?token/i, password: /"password"\s*:/i, import_body: /海雾遮住钟楼|潮声越过钟楼/, raw_provider_body: /provider[_-]?body/i, chain_of_thought: /chain[_-]?of[_-]?thought|reasoning_content/i, absolute_path: /[A-Za-z]:\\Users\\/, protected_poc_path: /story-continuity-poc|held-out|golden/i };
const scanFailureKind = (error: unknown) => {
  const message = error instanceof Error ? error.message : "";
  if (message.includes("Response body is unavailable")) return "body_unavailable";
  if (message.includes("Protocol error")) return "protocol_error";
  return error instanceof Error ? error.name : "UnknownError";
};
const scanApiBody = async (session: ApiBodySession, requestId: string, pending: PendingApiBody) => {
  if (pending.status === 204) return;
  try {
    let result: { body: string; base64Encoded: boolean } | undefined;
    let lastError: unknown;
    for (let attempt = 0; attempt < 5 && !result; attempt++) {
      try {
        result = await session.send("Network.getResponseBody", { requestId }) as { body: string; base64Encoded: boolean };
      } catch (error) {
        lastError = error;
        await new Promise((resolve) => setTimeout(resolve, 100));
      }
    }
    if (!result) throw lastError;
    const body = result.base64Encoded ? Buffer.from(result.body, "base64").toString("utf8") : result.body;
    for (const [category, pattern] of Object.entries(sensitivePatterns)) if (pattern.test(body)) apiCorpus.categories[category as keyof typeof apiCorpus.categories]++;
  } catch (error) {
    apiCorpus.unresolved++;
    const parseKey = `${pending.key} ${pending.status}`;
    apiCorpus.parse_failures[parseKey] = (apiCorpus.parse_failures[parseKey] ?? 0) + 1;
    const kind = scanFailureKind(error);
    apiCorpus.parse_failure_kinds[kind] = (apiCorpus.parse_failure_kinds[kind] ?? 0) + 1;
  }
};
test.beforeEach(async ({ page }) => {
  const cdp = await page.context().newCDPSession(page);
  const pendingBodies = new Map<string, PendingApiBody>();
  const requestMethods = new Map<string, string>();
  apiCorpusContexts.add({ session: cdp, pendingBodies });
  await cdp.send("Network.enable");
  cdp.on("Network.requestWillBeSent", (event) => requestMethods.set(event.requestId, event.request.method));
  cdp.on("Network.responseReceived", (event) => {
    const url = new URL(event.response.url);
    if (!url.pathname.startsWith("/api/")) return;
    const key = `${event.requestId}`;
    const endpoint = `${requestMethods.get(event.requestId) ?? "UNKNOWN"} ${templateEndpoint(url.pathname)}`;
    pendingBodies.set(key, { key: endpoint, status: event.response.status });
    apiCorpus.response_count++;
    const bucket = apiCorpus.endpoint_templates[endpoint] ??= {};
    bucket[String(event.response.status)] = (bucket[String(event.response.status)] ?? 0) + 1;
  });
  cdp.on("Network.loadingFinished", (event) => {
    const pending = pendingBodies.get(event.requestId);
    if (!pending) return;
    pendingBodies.delete(event.requestId);
    const scan = scanApiBody(cdp, event.requestId, pending);
    apiCorpusPending.add(scan);
    void scan.finally(() => apiCorpusPending.delete(scan));
  });
});
test.afterEach(async () => {
  await new Promise((resolve) => setTimeout(resolve, 500));
  for (const context of apiCorpusContexts) {
    for (const [requestId, pending] of context.pendingBodies) {
      context.pendingBodies.delete(requestId);
      const scan = scanApiBody(context.session, requestId, pending);
      apiCorpusPending.add(scan);
      void scan.finally(() => apiCorpusPending.delete(scan));
    }
  }
  await Promise.all([...apiCorpusPending]);
  for (const context of apiCorpusContexts) {
    await context.session.detach();
    apiCorpusContexts.delete(context);
  }
});
test.afterAll(async () => {
  if (!process.env.STAGE6_API_CORPUS_PATH) return;
  await Promise.all([...apiCorpusPending]);
  for (const context of apiCorpusContexts) await context.session.detach();
  await writeFile(process.env.STAGE6_API_CORPUS_PATH, JSON.stringify({ scanned: apiCorpus.unresolved === 0, response_count: apiCorpus.response_count, endpoint_templates: apiCorpus.endpoint_templates, parse_failures: apiCorpus.parse_failures, parse_failure_kinds: apiCorpus.parse_failure_kinds, categories: apiCorpus.categories, unresolved: apiCorpus.unresolved }, null, 2));
  if (!apiCorpus.response_count || apiCorpus.unresolved) throw new Error("API corpus scanner did not complete");
});

async function register(page: Page, name: string) {
  await page.goto("/register");
  await page.getByLabel("账号").fill(name);
  await page.getByLabel("显示名称").fill("本地作者");
  await page.getByLabel("密码").fill(`test-${randomUUID()}`);
  await page.getByRole("button", { name: "创建本地账号" }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
}
const globalNavButton = (page: Page, name: "首页" | "作品管理") =>
  page.locator(".global-nav").getByRole("button", { name, exact: true });
const projectNavButton = (page: Page, name: string) =>
  page.locator(".project-nav").getByRole("button", { name, exact: true });
const openProject = (page: Page, title: string) =>
  page.locator(".project-rows li").filter({ hasText: title }).getByRole("button", { name: "打开", exact: true });
const runStatus = (page: Page) => page.getByLabel("连续性检查运行状态", { exact: true });
const openUserMenu = async (page: Page) => {
  await page.getByRole("button", { name: "用户菜单", exact: true }).click();
  return page.getByRole("menu", { name: "用户菜单", exact: true });
};
const expectCenteredAuthCard = async (page: Page) => {
  const box = await page.locator(".auth").boundingBox();
  const viewport = page.viewportSize();
  if (!box || !viewport) throw new Error("认证卡片或视口不可用");
  expect(Math.abs(box.x + box.width / 2 - viewport.width / 2)).toBeLessThanOrEqual(2);
};
const expectActiveProjectNavVisible = async (page: Page, name: string) => {
  const nav = page.locator(".project-nav nav");
  const active = projectNavButton(page, name);
  await expect(active).toHaveAttribute("aria-current", "page");
  const [navBox, activeBox] = await Promise.all([nav.boundingBox(), active.boundingBox()]);
  if (!navBox || !activeBox) throw new Error("项目导航或当前模块不可用");
  expect(activeBox.x).toBeGreaterThanOrEqual(navBox.x - 1);
  expect(activeBox.x + activeBox.width).toBeLessThanOrEqual(navBox.x + navBox.width + 1);
};
const expectButtonTextHorizontallyCentered = async (page: Page, name: string) => {
  const offset = await page.getByRole("button", { name, exact: true }).evaluate((button) => {
    const buttonBox = button.getBoundingClientRect();
    const range = document.createRange();
    range.selectNodeContents(button);
    const textBox = range.getBoundingClientRect();
    return Math.abs(
      buttonBox.left + buttonBox.width / 2 - (textBox.left + textBox.width / 2),
    );
  });
  expect(offset).toBeLessThanOrEqual(1);
};

test("logout then login with the same local credentials restores work", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  const name = account("stagefivelogin");
  const secret = `test-${randomUUID()}`;
  await page.goto("/register");
  await page.getByLabel("账号").fill(name);
  await page.getByLabel("显示名称").fill("本地作者");
  await page.getByLabel("密码").fill(secret);
  await page.getByRole("button", { name: "创建本地账号" }).click();
  const logoutMenu = await openUserMenu(page);
  await logoutMenu.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await page.getByLabel("账号").fill(name);
  await page.getByLabel("密码").fill(secret);
  await page.getByRole("button", { name: "登录" }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("capture production visual states from the real local workflow", async ({ page }) => {
  const errors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") errors.push(message.text());
  });
  page.on("pageerror", (error) => errors.push(error.message));
  await mkdir(shots, { recursive: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await page.goto("/login");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "1440-login.png"), fullPage: true });
  await page.goto("/register");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "1440-register.png"), fullPage: true });
  await page.setViewportSize({ width: 1024, height: 900 });
  await page.goto("/login");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "1024-login.png"), fullPage: true });
  await page.goto("/register");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "1024-register.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("/login");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "390-login.png"), fullPage: true });
  await page.goto("/register");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "390-register.png"), fullPage: true });
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto("/login");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "320-login.png"), fullPage: true });
  await page.goto("/register");
  await expectCenteredAuthCard(page);
  await page.screenshot({ path: path.join(shots, "320-register.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 960 });
  await register(page, account("stagefivevisual"));
  await page.screenshot({ path: path.join(shots, "1440-home.png"), fullPage: true });
  await globalNavButton(page, "作品管理").click();
  await expect(page.getByRole("heading", { name: "作品管理" })).toBeVisible();
  const globalRail = await page.locator(".global-nav").boundingBox();
  expect(globalRail?.x).toBe(0);
  expect(globalRail?.width).toBe(200);
  await page.screenshot({ path: path.join(shots, "1440-projects.png"), fullPage: true });
  await openProject(page, "灰港回声").click();
  await expect(page.getByRole("heading", { name: "灰港回声" })).toBeVisible();
  await expectButtonTextHorizontallyCentered(page, "查看大纲");
  await expectButtonTextHorizontallyCentered(page, "查看角色库");
  await page.screenshot({ path: path.join(shots, "1440-project-overview.png"), fullPage: true });
  await projectNavButton(page, "写作与检查").click();
  await expect(page.getByLabel("草稿正文")).toBeVisible();
  await page.screenshot({ path: path.join(shots, "1440-workspace.png"), fullPage: true });
  await page.setViewportSize({ width: 1024, height: 900 });
  await expectActiveProjectNavVisible(page, "写作与检查");
  await page.screenshot({ path: path.join(shots, "1024-workspace.png"), fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  await expect(page.getByText("浏览只读", { exact: false })).toBeVisible();
  await expectActiveProjectNavVisible(page, "写作与检查");
  await expect(page.locator(".global-nav .brand > span").last()).toHaveAttribute("aria-label", "Story Continuity");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(shots, "390-workspace-browse-only.png"), fullPage: true });
  await page.setViewportSize({ width: 320, height: 700 });
  await projectNavButton(page, "大纲").click();
  await projectNavButton(page, "写作与检查").click();
  await expectActiveProjectNavVisible(page, "写作与检查");
  await expect(page.locator(".global-nav .brand > span").last()).toHaveAttribute("aria-label", "Story Continuity");
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
  await page.screenshot({ path: path.join(shots, "320-workspace-browse-only.png"), fullPage: true });
  expect(errors).toEqual([]);
});

test.describe.serial("Stage 5 real local workflow", () => {
  test.beforeAll(async () => { await mkdir(shots, { recursive: true }); });

  test("registration, cookie session recovery, logout and expired session recovery are real", async ({
    page,
    context,
  }) => {
    const expired: number[] = [];
    page.on("response", (response) => {
      if (new URL(response.url()).pathname === "/api/auth/session")
        expired.push(response.status());
    });
    await register(page, account("stagefiveauth"));
    await page.reload();
    await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
    const logoutMenu = await openUserMenu(page);
    await logoutMenu.getByRole("menuitem", { name: "退出登录", exact: true }).click();
    await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
    await context.clearCookies();
    await page.goto("/projects");
    await expect(page.getByRole("heading", { name: "登录" })).toBeVisible();
    expect(expired).toContain(401);
  });

  test("two browser sessions keep project data isolated", async ({ browser }) => {
    const first = await browser.newContext();
    const second = await browser.newContext();
    try {
      const a = await first.newPage();
      const b = await second.newPage();
      const privateTitle = `账户隔离作品-${Date.now()}`;
      await register(a, account("stagefiveisoa"));
      await globalNavButton(a, "作品管理").click();
      await a.getByRole("button", { name: "新建作品" }).click();
      await a.locator('input[name="title"]').fill(privateTitle);
      await a.getByRole("button", { name: "创建并进入作品" }).click();
      await expect(a.getByRole("heading", { name: privateTitle })).toBeVisible();
      await register(b, account("stagefiveisob"));
      await globalNavButton(b, "作品管理").click();
      await expect(b.getByText(privateTitle)).toHaveCount(0);
      await expect(b.locator(".project-rows li")).toHaveCount(3);
    } finally {
      await first.close();
      await second.close();
    }
  });

  test("project search, filters and sorting use the API, and every seed keeps four independent data views", async ({ page }) => {
    const errors: string[] = [];
    const projectRequests: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));
    page.on("request", (request) => {
      const url = new URL(request.url());
      if (url.pathname === "/api/projects") projectRequests.push(url.search);
    });
    await register(page, account("stagefivecatalog"));
    await expect(page.locator(".home-continue")).toContainText("灰港回声");
    await globalNavButton(page, "作品管理").click();
    await expect(page.locator(".project-rows li")).toHaveCount(3);
    await expect(page.locator(".project-rows li").first()).toContainText("灰港回声");
    await page.getByLabel("搜索").fill("纸月档案");
    await page.getByLabel("状态").selectOption("active");
    await page.getByLabel("排序").selectOption("title_asc");
    await page.getByRole("button", { name: "应用条件" }).click();
    await expect(page.locator(".project-rows li")).toHaveCount(1);
    await expect(page.locator(".project-rows li")).toContainText("纸月档案");
    expect(projectRequests.some((query) => query.includes("q=%E7%BA%B8%E6%9C%88%E6%A1%A3%E6%A1%88") && query.includes("status=active") && query.includes("sort=title_asc"))).toBe(true);
    await page.getByRole("button", { name: "清除条件" }).click();
    await expect(page.locator(".project-rows li")).toHaveCount(3);

    const seeds = [
      { title: "灰港回声", outline: "雾钟", character: "温岚", world: "灰港", memory: "灰港雾钟" },
      { title: "纸月档案", outline: "封蜡的月历", character: "陆栖", world: "旧印刷厂", memory: "封蜡的月历" },
      { title: "零点花园", outline: "玻璃温室", character: "程末", world: "玻璃温室", memory: "玻璃温室" },
    ];
    const snapshots: string[] = [];
    for (const seed of seeds) {
      await page.locator(".project-rows li").filter({ hasText: seed.title }).getByRole("button", { name: "打开" }).click();
      await expect(page.getByRole("heading", { name: seed.title })).toBeVisible();
      for (const [tab, text] of [["大纲", seed.outline], ["角色库", seed.character], ["世界观", seed.world], ["Story Memory", seed.memory]] as const) {
        await projectNavButton(page, tab).click();
        await expect(page.getByRole("heading", { name: tab })).toBeVisible();
        await expect(page.locator(".read-list")).toContainText(text);
        snapshots.push(`${seed.title}/${tab}:${await page.locator(".read-list").innerText()}`);
      }
      await globalNavButton(page, "作品管理").click();
    }
    expect(new Set(snapshots).size).toBe(12);
    expect(errors).toEqual([]);
  });

  test("desktop remains actionable while narrow and reduced-motion views are browse-only", async ({
    browser,
  }) => {
    const context = await browser.newContext({
      viewport: { width: 1024, height: 900 },
      reducedMotion: "reduce",
    });
    try {
      const page = await context.newPage();
      await register(page, account("stagefiveresponsive"));
      await globalNavButton(page, "作品管理").click();
      await page.locator(".project-rows li").first().getByRole("button", { name: "打开" }).click();
      await projectNavButton(page, "写作与检查").click();
      await expect(page.getByRole("button", { name: "运行连续性检查" })).toBeEnabled();
      await expect(page.locator("body")).toHaveCSS("scroll-behavior", "auto");
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
      await page.screenshot({ path: path.join(shots, "1024-reduced-motion.png"), fullPage: true });
      for (const width of [1440, 1280]) {
        await page.setViewportSize({ width, height: 900 });
        await expect(page.getByRole("button", { name: "运行连续性检查" })).toBeEnabled();
      }
      const cdp = await context.newCDPSession(page);
      await page.setViewportSize({ width: 1440, height: 900 });
      await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 2 });
      try {
        const runButton = page.getByRole("button", { name: "运行连续性检查" });
        await expect(runButton).toBeVisible();
        expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
        const bounds = await runButton.boundingBox();
        expect(bounds && bounds.x >= 0 && bounds.y >= 0 && bounds.x + bounds.width <= 1440 && bounds.y + bounds.height <= 900).toBe(true);
        await page.screenshot({ path: path.join(shots, "1440-zoom-200.png"), fullPage: true });
      } finally {
        await cdp.send("Emulation.setPageScaleFactor", { pageScaleFactor: 1 });
      }
      await page.setViewportSize({ width: 390, height: 844 });
      await page.reload();
      await expect(page.getByText("浏览只读", { exact: false })).toBeVisible();
      await expect(page.getByRole("button", { name: "运行连续性检查" })).toBeDisabled();
      await expect(page.getByText("请求超时", { exact: false })).toHaveCount(0);
      const mobileNav = page.locator(".global-nav");
      expect((await mobileNav.boundingBox())?.height).toBeLessThanOrEqual(68);
      for (const name of ["首页", "作品管理"] as const) {
        const button = globalNavButton(page, name);
        expect(await button.evaluate((element) => element.getBoundingClientRect().height)).toBeGreaterThanOrEqual(44);
        await expect(button).toHaveCSS("white-space", "nowrap");
      }
      const userMenu = await openUserMenu(page);
      await expect(userMenu.locator("p")).toContainText("本地作者");
      await page.keyboard.press("Escape");
      await expect(userMenu).toBeHidden();
      await expect(page.getByRole("button", { name: "用户菜单", exact: true })).toBeFocused();
      await page.setViewportSize({ width: 320, height: 700 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    } finally {
      await context.close();
    }
  });

  test("dirty project navigation asks whether to save, discard, or cancel", async ({ page }) => {
    await register(page, account("stagefivedirty"));
    await globalNavButton(page, "作品管理").click();
    await page.locator(".project-rows li").first().getByRole("button", { name: "打开" }).click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByLabel("草稿正文").fill("未保存的切换测试");
    await globalNavButton(page, "作品管理").click();
    const dialog = page.getByRole("dialog", { name: "未保存草稿" });
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "取消" }).click();
    await expect(dialog).toBeHidden();
    await globalNavButton(page, "首页").click();
    await page.getByRole("button", { name: "放弃修改" }).click();
    await expect(page.getByRole("heading", { name: "继续你的故事" })).toBeVisible();
  });

  test("a delayed project A response cannot overwrite project B", async ({ page }) => {
    await register(page, account("stagefivelate"));
    await globalNavButton(page, "作品管理").click();
    let releaseA: (() => void) | undefined;
    let heldOnce = false;
    const held = new Promise<void>((resolve) => { releaseA = resolve; });
    await page.route(/\/api\/projects\/[^/]+\/memory$/, async (route) => {
      if (!heldOnce) { heldOnce = true; await held; }
      await route.continue();
    });
    await page.locator(".project-rows li").filter({ hasText: "灰港回声" }).getByRole("button", { name: "打开" }).click();
    await globalNavButton(page, "作品管理").click();
    await page.locator(".project-rows li").filter({ hasText: "纸月档案" }).getByRole("button", { name: "打开" }).click();
    await expect(page.getByRole("heading", { name: "纸月档案" })).toBeVisible();
    releaseA?.();
    await page.waitForTimeout(250);
    await expect(page.getByRole("heading", { name: "纸月档案" })).toBeVisible();
    expect(page.url()).toContain("/overview");
    await expect(page.locator(".project-nav")).toContainText("纸月档案");
    await expect(page.getByText("请求超时", { exact: false })).toHaveCount(0);
  });

  test("metadata CAS succeeds, stale revision conflicts, and archive restores writable access", async ({ page }) => {
    await register(page, account("stagefivemetadata"));
    await globalNavButton(page, "作品管理").click();
    await page.locator(".project-rows li").first().getByRole("button", { name: "打开" }).click();
    await page.getByRole("button", { name: "编辑作品信息" }).click();
    await page.getByLabel("说明").fill("CAS 成功后的作品说明");
    await page.getByRole("button", { name: "保存元数据" }).click();
    await expect(page.getByText("作品信息已更新")).toBeVisible();
    const staleStatus = await page.evaluate(async () => {
      const id = location.pathname.split("/")[2];
      const response = await fetch(`/api/projects/${id}`, {
        method: "PATCH",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "Idempotency-Key": crypto.randomUUID() },
        body: JSON.stringify({ base_metadata_revision: 1, summary: "stale" }),
      });
      return response.status;
    });
    expect(staleStatus).toBe(409);
    await page.getByRole("button", { name: "归档作品" }).click();
    await page.getByRole("button", { name: "确认归档" }).click();
    await expect(page.getByText("作品已归档：仅可浏览", { exact: false })).toBeVisible();
    await projectNavButton(page, "写作与检查").click();
    await expect(page.getByRole("button", { name: "运行连续性检查" })).toBeDisabled();
    await page.screenshot({ path: path.join(shots, "1440-archived-read-only.png"), fullPage: true });
    await projectNavButton(page, "项目概览").click();
    await page.getByRole("button", { name: "恢复作品" }).click();
    await page.getByRole("button", { name: "恢复作品" }).last().click();
    await expect(page.getByText("作品信息已更新")).toBeVisible();
    await projectNavButton(page, "写作与检查").click();
    await expect(page.getByRole("button", { name: "运行连续性检查" })).toBeEnabled();
    await page.screenshot({ path: path.join(shots, "1440-restored-workspace.png"), fullPage: true });
  });

  test("Accept and edit creates the controlled N plus 1 revision", async ({ page }) => {
    await register(page, account("stagefiveaccept"));
    await globalNavButton(page, "作品管理").click();
    await openProject(page, "灰港回声").click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(runStatus(page)).toContainText("检查完成", { timeout: 15000 });
    await page.locator(".issue-list button").first().click();
    await page.getByRole("button", { name: "Accept & edit" }).click();
    await page.getByLabel("草稿正文").fill("受控 N+1 编辑");
    await page.getByRole("button", { name: "保存受控修订" }).click();
    await expect(page.getByLabel("草稿修订", { exact: true })).toContainText("revision 2");
    await expect(page.getByText("已按受控谱系保存", { exact: false })).toBeVisible();
  });

  test("False positive records a real author decision", async ({ page }) => {
    await register(page, account("stagefivefalse"));
    await globalNavButton(page, "作品管理").click();
    await openProject(page, "灰港回声").click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(runStatus(page)).toContainText("检查完成", { timeout: 15000 });
    await page.locator(".issue-list button").first().click();
    await page.getByRole("button", { name: "Mark false positive" }).click();
    await expect(page.getByText("已标记为误报", { exact: false })).toBeVisible();
  });

  test("Reset restores the current project after confirmation", async ({ page }) => {
    await register(page, account("stagefivereset"));
    await globalNavButton(page, "作品管理").click();
    await openProject(page, "灰港回声").click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "Reset 当前作品" }).click();
    await page.screenshot({ path: path.join(shots, "1440-reset-confirmation.png"), fullPage: true });
    await page.getByRole("button", { name: "确认恢复" }).click();
    await expect(page.getByText("当前作品已按其数据来源恢复", { exact: false })).toBeVisible();
    await expect(page.getByLabel("草稿修订", { exact: true })).toContainText("revision 1");
  });

  test("empty project check fails closed with insufficient context", async ({ page }) => {
    await register(page, account("stagefiveempty"));
    await globalNavButton(page, "作品管理").click();
    await page.getByRole("button", { name: "新建作品" }).click();
    await page.locator('input[name="title"]').fill("空上下文作品");
    await page.getByRole("button", { name: "创建并进入作品" }).click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(page.getByText("Story Memory 尚待初始化", { exact: false })).toBeVisible();
  });

  test("imported project check also fails closed before Memory initialization", async ({ page }) => {
    await register(page, account("stagefiveimportcontext"));
    await globalNavButton(page, "作品管理").click();
    await page.getByRole("button", { name: "导入作品" }).click();
    await page.setInputFiles('input[name="file"]', { name: "context.txt", mimeType: "text/plain", buffer: Buffer.from("第一章\n海雾遮住钟楼。", "utf8") });
    await page.getByRole("button", { name: "解析并预览章节" }).click();
    await page.getByRole("button", { name: "继续确认" }).click();
    await page.locator('input[name="title"]').fill("导入空上下文");
    await page.getByRole("button", { name: "确认导入" }).click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(page.getByText("Story Memory 尚待初始化", { exact: false })).toBeVisible();
  });

  test("cancelling an import preview creates no project and a later preview can commit", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (message) => {
      if (message.type() === "error") errors.push(message.text());
    });
    page.on("pageerror", (error) => errors.push(error.message));
    const importFile = {
      name: "tide.md",
      mimeType: "text/markdown",
      buffer: Buffer.from("# 第一章\n潮声越过钟楼。\n# 第二章\n她收起航图。", "utf8"),
    };
    await page.setViewportSize({ width: 1440, height: 960 });
    await register(page, account("stagefivecancelimport"));
    await globalNavButton(page, "作品管理").click();
    await expect(page.locator(".project-rows li")).toHaveCount(3);
    await page.getByRole("button", { name: "导入作品" }).click();
    await expect(page.getByRole("heading", { name: "导入已有作品" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "选择要导入的文件" })).toBeVisible();
    await expect(page.locator("body")).not.toContainText("Choose File");
    await expect(page.locator("body")).not.toContainText("No file chosen");
    await page.getByRole("button", { name: "选择本地文件" }).focus();
    await expect(page.locator(":focus")).toHaveCSS("outline-style", "solid");
    await page.screenshot({ path: path.join(shots, "1440-import-step-1.png"), fullPage: true });
    await page.getByTestId("import-dropzone").evaluate((zone) => {
      const transfer = new DataTransfer();
      transfer.items.add(new File(["# 第一章\n潮声越过钟楼。\n# 第二章\n她收起航图。"], "tide.md", { type: "text/markdown" }));
      zone.dispatchEvent(new DragEvent("drop", { bubbles: true, cancelable: true, dataTransfer: transfer }));
    });
    await expect(page.getByText("tide.md", { exact: false })).toBeVisible();
    await page.getByRole("button", { name: "解析并预览章节" }).click();
    await expect(page.getByRole("heading", { name: "章节预览" })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "1440-import-step-2-preview.png"), fullPage: true });
    await page.getByRole("button", { name: "返回重新选择" }).click();
    await expect(page.getByRole("heading", { name: "选择要导入的文件" })).toBeVisible();
    await page.setInputFiles('input[name="file"]', importFile);
    await page.getByRole("button", { name: "解析并预览章节" }).click();
    await page.getByRole("button", { name: "继续确认" }).click();
    await expect(page.getByRole("heading", { name: "确认导入" })).toBeVisible();
    await page.getByRole("button", { name: "返回章节预览" }).click();
    await expect(page.getByRole("heading", { name: "章节预览" })).toBeVisible();
    await page.getByRole("button", { name: "继续确认" }).click();
    await page.locator('input[name="title"]').fill("未提交的潮汐档案");
    await page.screenshot({ path: path.join(shots, "1440-import-step-3-confirmation.png"), fullPage: true });
    await page.getByRole("button", { name: "取消导入" }).click();
    await expect(page.getByRole("heading", { name: "选择要导入的文件" })).toBeVisible();
    await globalNavButton(page, "作品管理").click();
    await expect(page.locator(".project-rows li")).toHaveCount(3);
    await page.getByRole("button", { name: "导入作品" }).click();
    await expect(page.getByRole("heading", { name: "导入已有作品" })).toBeVisible();
    await page.setInputFiles('input[name="file"]', importFile);
    await page.getByRole("button", { name: "解析并预览章节" }).click();
    await page.getByRole("button", { name: "继续确认" }).click();
    await expect(page.getByRole("heading", { name: "确认导入" })).toBeVisible();
    await page.locator('input[name="title"]').fill("潮汐档案");
    await page.getByRole("button", { name: "确认导入" }).click();
    await expect(page.getByRole("heading", { name: "潮汐档案" })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "1440-import-submitted-overview.png"), fullPage: true });
    expect(errors).toEqual([]);
  });

  test("keyboard focus is visible and primary controls meet the 44 pixel target", async ({ page }) => {
    await page.goto("/login");
    await page.keyboard.press("Tab");
    await expect(page.locator(":focus")).toHaveCSS("outline-style", "solid");
    const height = await page.getByRole("button", { name: "登录" }).evaluate((el) => el.getBoundingClientRect().height);
    expect(height).toBeGreaterThanOrEqual(44);
  });

  test("Memory Review can reject every item without creating a new version", async ({ page }) => {
    let commitPayload: { accepted_item_ids: string[]; rejected_item_ids: string[] } | null = null;
    page.on("request", (request) => {
      if (request.method() === "POST" && /\/memory\/change-sets\/[^/]+\/commit$/.test(new URL(request.url()).pathname))
        commitPayload = request.postDataJSON() as { accepted_item_ids: string[]; rejected_item_ids: string[] };
    });
    await register(page, account("stagefiveallreject"));
    await globalNavButton(page, "作品管理").click();
    await openProject(page, "灰港回声").click();
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(runStatus(page)).toContainText("检查完成", { timeout: 15000 });
    const reviewDrawer = page.getByRole("dialog", { name: "问题证据" });
    for (let i = 0; i < 2; i++) { await page.locator(".issue-list li").filter({ hasNotText: "已决策" }).getByRole("button").first().click(); await reviewDrawer.getByRole("button", { name: "Keep intentional" }).click(); await expect(reviewDrawer).toBeHidden(); }
    await page.getByRole("button", { name: "审阅 Memory 变更" }).click();
    const rejects = page.getByLabel("拒绝（不写入）");
    await expect(rejects).toHaveCount(2);
    for (const item of await rejects.all()) {
      await item.check();
      await expect(item).toBeChecked();
    }
    await page.waitForTimeout(100);
    await page.getByRole("button", { name: "确认并提交审核结果" }).click();
    const captured = commitPayload as { accepted_item_ids: string[]; rejected_item_ids: string[] } | null;
    expect(captured?.accepted_item_ids).toEqual([]);
    expect(captured?.rejected_item_ids).toHaveLength(2);
    await expect(page.getByText("全部项目已拒绝，Story Memory 版本未变")).toBeVisible();
  });

  test("real session, projects, new and import context are API-backed", async ({ page }) => {
    const errors: string[] = [], network: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    page.on("request", (r) => { const u = new URL(r.url()); if (u.pathname.startsWith("/api/")) network.push(`${r.method()} ${u.pathname}`); });
    await register(page, account("stagefivea"));
    await globalNavButton(page, "作品管理").click();
    await expect(page.getByRole("heading", { name: "作品管理" })).toBeVisible();
    await expect(page.locator(".project-rows li")).toHaveCount(3);
    await page.getByRole("button", { name: "新建作品" }).click();
    await expect(page.getByRole("heading", { name: "新建作品" })).toBeVisible();
    await page.locator('.form-panel input[name="title"]').fill("空白试作");
    await page.locator('.form-panel input[name="genre"]').fill("测试");
    await page.getByRole("button", { name: "创建并进入作品" }).click();
    await expect(page.locator(".memory-panel").getByRole("heading", { name: "Memory V1", exact: true })).toBeVisible();
    await globalNavButton(page, "作品管理").click();
    await page.getByRole("button", { name: "导入作品" }).click();
    await page.setInputFiles('input[name="file"]', { name: "chapter.md", mimeType: "text/markdown", buffer: Buffer.from("# 第一章\n海雾遮住钟楼。\n# 第二章\n她记录了潮声。", "utf8") });
    await page.getByRole("button", { name: "解析并预览章节" }).click();
    await expect(page.getByRole("heading", { name: "章节预览" })).toBeVisible();
    await expect(page.getByText("SHA-256")).toBeVisible();
    await page.getByRole("button", { name: "继续确认" }).click();
    await page.locator('.form-panel input[name="title"]').fill("潮汐档案");
    await page.getByRole("button", { name: "确认导入" }).click();
    await expect(page.getByText("导入作品尚待作者确认", { exact: false })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "stage5-import-empty.png"), fullPage: true });
    expect(errors).toEqual([]);
    expect(network.length).toBeGreaterThan(8);
    expect(network.every((x) => /^((GET|POST|PATCH) )\/api\//.test(x))).toBe(true);
  });

  test("grey harbor uses queued run, evidence, author decisions and Memory Review", async ({ page }) => {
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(m.text()));
    page.on("pageerror", (e) => errors.push(e.message));
    await register(page, account("stagefiveb"));
    await globalNavButton(page, "作品管理").click();
    const grey = page.locator(".project-rows li").filter({ hasText: "灰港回声" });
    await grey.getByRole("button", { name: "打开" }).click();
    await expect(page.getByRole("heading", { name: "灰港回声" })).toBeVisible();
    for (const name of ["大纲", "角色库", "世界观", "Story Memory"]) {
      await projectNavButton(page, name).click();
      await expect(page.getByRole("heading", { name })).toBeVisible();
    }
    await projectNavButton(page, "写作与检查").click();
    await page.getByRole("button", { name: "Reset 当前作品" }).click();
    await page.getByRole("button", { name: "确认恢复" }).click();
    await expect(page.getByLabel("草稿修订", { exact: true })).toContainText("revision 1");
    const editor = page.getByLabel("草稿正文");
    await expect(editor).toBeEditable();
    await editor.fill(`${await editor.inputValue()}\n阶段五真实保存。`);
    await page.getByRole("button", { name: "保存草稿" }).click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(runStatus(page)).toContainText("检查完成", { timeout: 15_000 });
    await page.screenshot({ path: path.join(shots, "1440-grey-harbor-run-complete.png"), fullPage: true });
    const firstIssue = page.locator(".issue-list button").first();
    await firstIssue.click();
    const drawer = page.getByRole("dialog", { name: "问题证据" });
    await expect(drawer.getByRole("heading", { name: "Evidence" })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "1440-evidence-drawer.png"), fullPage: true });
    await drawer.getByRole("button", { name: "Keep intentional" }).click();
    await expect(drawer).toBeHidden();
    await page
      .locator(".issue-list li")
      .filter({ hasNotText: "已决策" })
      .getByRole("button")
      .click();
    await expect(drawer).toBeVisible();
    await drawer.getByRole("button", { name: "Keep intentional" }).click();
    await expect(drawer).toBeHidden();
    await expect(
      page.locator(".issue-list li").filter({ hasNotText: "已决策" }),
    ).toHaveCount(0);
    await page.getByRole("button", { name: "审阅 Memory 变更" }).click();
    await expect(page.getByRole("heading", { name: "Memory Update Review" })).toBeVisible();
    await page.screenshot({ path: path.join(shots, "1440-memory-update-review.png"), fullPage: true });
    await page.getByLabel("拒绝").first().check();
    await page.getByRole("button", { name: "确认并提交审核结果" }).click();
    await expect(page.getByText("MemoryVersion", { exact: false })).toBeVisible();
    const axe = await new AxeBuilder({ page }).analyze();
    expect(axe.violations, JSON.stringify(axe.violations, null, 2)).toEqual([]);
    await page.screenshot({ path: path.join(shots, "stage5-grey-harbor-workspace.png"), fullPage: true });
    expect(errors).toEqual([]);
  });

  test("five reset-to-review runs are deterministic", async ({ page }) => {
    const records: Array<Record<string, unknown>> = [];
    const consoleErrors: string[] = [], pageErrors: string[] = [], failedRequests: string[] = [];
    page.on("console", (m) => m.type() === "error" && consoleErrors.push(m.text()));
    page.on("pageerror", (e) => pageErrors.push(e.message));
    page.on("response", (r) => {
      const url = new URL(r.url());
      if (url.pathname.startsWith("/api/") && r.status() >= 400 && !(url.pathname === "/api/auth/session" && r.status() === 401)) failedRequests.push(`${r.request().method()} ${url.pathname} ${r.status()}`);
    });
    await register(page, account("stage6demo"));
    await globalNavButton(page, "作品管理").click();
    await openProject(page, "灰港回声").click();
    await projectNavButton(page, "写作与检查").click();
    for (let index = 1; index <= 5; index++) {
      const started = Date.now();
      await page.getByRole("button", { name: "Reset 当前作品" }).click();
      await page.getByRole("button", { name: "确认恢复" }).click();
      await expect(page.getByText("Memory V4", { exact: false })).toBeVisible();
      await expect(page.getByLabel("草稿修订", { exact: true })).toContainText("revision 1");
      const editor = page.getByLabel("草稿正文");
      await editor.fill(`${await editor.inputValue()}\n第${index}轮作者确认草稿。`);
      await page.getByRole("button", { name: "保存草稿" }).click();
      const queued = page.waitForResponse((r) => r.request().method() === "POST" && /\/api\/projects\/[^/]+\/checks$/.test(new URL(r.url()).pathname));
      await page.getByRole("button", { name: "运行连续性检查" }).click();
      const response = await queued;
      const queuedPayload = await response.json() as { data: { run_id: string; status: string } };
      expect(response.status()).toBe(202);
      expect(queuedPayload.data.status).toBe("queued");
      await expect(runStatus(page)).toContainText("检查完成", { timeout: 15_000 });
      const drawer = page.getByRole("dialog", { name: "问题证据" });
      for (let issue = 0; issue < 2; issue++) {
        await page.locator(".issue-list li").filter({ hasNotText: "已决策" }).getByRole("button").first().click();
        await drawer.getByRole("button", { name: "Keep intentional" }).click();
        await expect(drawer).toBeHidden();
      }
      await page.getByRole("button", { name: "审阅 Memory 变更" }).click();
      await expect(page.getByRole("heading", { name: "Memory Update Review" })).toBeVisible();
      await page.getByLabel("拒绝（不写入）").first().check();
      await page.getByRole("button", { name: "确认并提交审核结果" }).click();
      await expect(page.getByText("MemoryVersion", { exact: false })).toBeVisible();
      records.push({ round: index, run_id: queuedPayload.data.run_id, queued_before_completion: true, result: "completed_and_reviewed", duration_ms: Date.now() - started, recovery: "project_reset_to_memory_v4_draft_revision_1", manual_intervention: 0 });
    }
    expect(consoleErrors).toEqual([]);
    expect(pageErrors).toEqual([]);
    expect(failedRequests).toEqual([]);
    if (process.env.STAGE6_DEMO_RECORD_PATH) await writeFile(process.env.STAGE6_DEMO_RECORD_PATH, JSON.stringify({ runs: records, console_errors: consoleErrors, page_errors: pageErrors, unexpected_failed_requests: failedRequests }, null, 2));
  });

  test("long project title and long draft stay usable without horizontal overflow", async ({ page }) => {
    await register(page, account("stage6long"));
    await globalNavButton(page, "作品管理").click();
    await page.getByRole("button", { name: "新建作品" }).click();
    const title = "潮汐记录".repeat(19).slice(0, 80);
    await page.locator('input[name="title"]').fill(title);
    await page.getByRole("button", { name: "创建并进入作品" }).click();
    await expect(page.getByRole("heading", { name: title })).toBeVisible();
    for (const width of [1440, 1280, 1024, 390, 320]) {
      await page.setViewportSize({ width, height: 900 });
      expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    }
    await page.setViewportSize({ width: 1024, height: 900 });
    await projectNavButton(page, "写作与检查").click();
    const editor = page.getByLabel("草稿正文");
    await editor.fill("可保存的长正文。".repeat(1200));
    expect(await editor.evaluate((el) => el.scrollHeight > el.clientHeight)).toBe(true);
    await page.getByRole("button", { name: "保存草稿" }).click();
    await expect(editor).toHaveValue(/可保存的长正文/);
    await page.screenshot({ path: path.join(shots, "1024-long-title-long-draft.png"), fullPage: true });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(page.getByText("浏览只读", { exact: false })).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: path.join(shots, "390-long-title-browse-only.png"), fullPage: true });
  });

  test("extreme legal issues retain evidence, scrolling and focus restore", async ({ page }) => {
    await register(page, account("stage6issues"));
    await globalNavButton(page, "作品管理").click();
    await openProject(page, "灰港回声").click();
    await projectNavButton(page, "写作与检查").click();
    const editor = page.getByLabel("草稿正文");
    await editor.fill(`EXTREME_ISSUES\n${Array.from({ length: 20 }, (_, i) => `第${i + 1}项审阅草稿与既有事实发生差异。`).join("\n")}`);
    await page.getByRole("button", { name: "保存草稿" }).click();
    await page.getByRole("button", { name: "运行连续性检查" }).click();
    await expect(runStatus(page)).toContainText("检查完成", { timeout: 15_000 });
    const items = page.locator(".issue-list li");
    await expect(items).toHaveCount(20);
    await expect(page.getByText("高风险", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("中风险", { exact: false }).first()).toBeVisible();
    await page.setViewportSize({ width: 1440, height: 960 });
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await items.last().scrollIntoViewIfNeeded();
    await expect(items.last()).toBeVisible();
    await page.screenshot({ path: path.join(shots, "1440-extreme-issues.png"), fullPage: true });
    const first = items.first().getByRole("button");
    await first.click();
    const drawer = page.getByRole("dialog", { name: "问题证据" });
    await expect(drawer).toBeVisible();
    await page.screenshot({ path: path.join(shots, "1440-extreme-evidence-drawer.png"), fullPage: true });
    await page.keyboard.press("Escape");
    await expect(drawer).toBeHidden();
    await expect(first).toBeFocused();
    await page.setViewportSize({ width: 390, height: 844 });
    await page.reload();
    await expect(page.getByText("浏览只读", { exact: false })).toBeVisible();
    await expect(items).toHaveCount(20);
    await expect(page.getByText("高风险", { exact: false }).first()).toBeVisible();
    await expect(page.getByText("中风险", { exact: false }).first()).toBeVisible();
    await items.last().scrollIntoViewIfNeeded();
    await expect(items.last()).toBeVisible();
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true);
    await page.screenshot({ path: path.join(shots, "390-extreme-issues-browse-only.png"), fullPage: true });
  });
});
