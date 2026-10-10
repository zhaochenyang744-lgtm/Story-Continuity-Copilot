import { expect, test as base, type Browser, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { mkdir, writeFile } from "node:fs/promises";
import path from "node:path";

export { expect };

/** The five tabs of an open work, by the id used in the address. */
export type Tab = "overview" | "workspace" | "sources" | "memory" | "plan";
export const tabLabels: Record<Tab, string> = { overview: "概览", workspace: "写作", sources: "章节", memory: "资料", plan: "计划" };
export const tabOrder: Tab[] = ["overview", "workspace", "sources", "memory", "plan"];

/**
 * Every test gets a day-themed page with reduced motion, so numbers and transitions are in their final
 * state when they are read or photographed. Tests that need another setting call page.emulateMedia again.
 */
export const test = base.extend({
  page: async ({ page }, provide) => {
    await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
    await provide(page);
  },
});

/** A new page in its own browser context (its own cookies), with the same media settings as `test`'s page. */
export async function newPage(browser: Browser): Promise<Page> {
  const context = await browser.newContext({ baseURL: process.env.E2E_BASE_URL, viewport: { width: 1440, height: 960 } });
  const page = await context.newPage();
  await page.emulateMedia({ reducedMotion: "reduce", colorScheme: "light" });
  return page;
}

const origin = () => new URL(process.env.E2E_BASE_URL ?? "http://127.0.0.1:3000").origin;

/** The answers of the backend, already unwrapped from `{ data }`. Writes carry the headers the server requires. */
export function api(page: Page) {
  const headers = () => ({ "Idempotency-Key": randomUUID(), Origin: origin() });
  const read = async (response: Awaited<ReturnType<Page["request"]["get"]>>, what: string) => {
    expect(response.ok(), `${what} -> ${response.status()} ${await response.text()}`).toBe(true);
    return response.status() === 204 ? undefined : (await response.json()).data;
  };
  return {
    get: async <T = any>(url: string): Promise<T> => read(await page.request.get(`/api${url}`), `GET ${url}`),
    post: async <T = any>(url: string, data?: unknown): Promise<T> => read(await page.request.post(`/api${url}`, { headers: headers(), data }), `POST ${url}`),
    patch: async <T = any>(url: string, data?: unknown): Promise<T> => read(await page.request.patch(`/api${url}`, { headers: headers(), data }), `PATCH ${url}`),
    /** The status code only, for calls that are expected to be refused. */
    status: async (url: string) => (await page.request.get(`/api${url}`)).status(),
    /** Any call, answered as { status, body } without asserting success (for refusals). */
    raw: async (method: "GET" | "POST" | "PATCH", url: string, data?: unknown) => {
      const response = await page.request.fetch(`/api${url}`, { method, headers: method === "GET" ? {} : headers(), data });
      return { status: response.status(), body: await response.json().catch(() => null) };
    },
  };
}

const homeHeading =/^(从第一章开始|继续你的故事)$/;

/** Register a unique author through the registration form. Done once the home page is showing. */
export async function registerAccount(page: Page, prefix: string, displayName = "E2E 作者") {
  const stem = prefix.toLowerCase().replace(/[^a-z0-9_.-]/g, "").slice(0, 16);
  if (!stem) throw new Error("An ASCII account prefix is required");
  const account = `${process.env.E2E_ACCOUNT_PREFIX ?? "v170e2e"}${stem}${randomUUID().replaceAll("-", "").slice(0, 12)}`;
  const password = `safe-${randomUUID()}`;
  const email = `${account}@example.test`;
  await page.goto("/register");
  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("显示名称", { exact: true }).fill(displayName);
  await page.getByLabel("恢复邮箱", { exact: true }).fill(email);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "创建账号", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: homeHeading })).toBeVisible();
  await expect(page).toHaveURL(/\/$/);
  return { account, password, email };
}

/** Sign in through the login form. Done once the home page is showing. */
export async function login(page: Page, account: string, password: string) {
  await page.goto("/login");
  await page.getByLabel("账号", { exact: true }).fill(account);
  await page.getByLabel("密码", { exact: true }).fill(password);
  await page.getByRole("button", { name: "登录", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: homeHeading })).toBeVisible();
}

export const accountMenuButton = (page: Page) => page.getByRole("button", { name: /^账号菜单：/ });

export async function openAccountMenu(page: Page) {
  await accountMenuButton(page).click();
  await expect(page.getByRole("menu", { name: "账号菜单" })).toBeVisible();
}

/** Sign out through the account menu. Done once the login page is showing. */
export async function logout(page: Page) {
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "退出登录", exact: true }).click();
  await expect(page).toHaveURL(/\/login$/);
  await expect(page.getByRole("heading", { level: 1, name: "登录", exact: true })).toBeVisible();
}

/** Enter as a visitor from the login page. Done once the home page is showing. */
export async function startVisitor(page: Page) {
  await page.goto("/login");
  await page.getByRole("button", { name: "以访客身份进入", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: homeHeading })).toBeVisible();
}

/** The id of this account's sample work (the one the tour runs on). */
export async function sampleWorkId(page: Page): Promise<string> {
  const onboarding = await api(page).get("/onboarding");
  // Visitors have no tour record; the home page then takes the sample from the list of works.
  const id = onboarding?.tutorial?.project_id
    ?? (await api(page).get("/projects?q=&sort=updated_desc")).projects.find((item: { data_origin: string }) => item.data_origin === "demo_seed" || item.data_origin === "tutorial_seed")?.id;
  expect(id, "the account's sample work (GET /api/onboarding, else GET /api/projects)").toEqual(expect.any(String));
  return id;
}

/** Choose one of the type chips on the new-work page the way a reader does: by clicking its label. */
export async function pickGenre(page: Page, genre: string) {
  await page.getByRole("radiogroup", { name: "类型", exact: true }).getByText(genre, { exact: true }).click();
  await expect(page.getByRole("radio", { name: genre, exact: true })).toBeChecked();
}

type WorkInput = { title: string; genre?: string; summary?: string };

/** Create a work through the new-work page and return its id (taken from the address it lands on). */
export async function createWork(page: Page, { title, genre, summary }: WorkInput): Promise<string> {
  await page.goto("/projects/new");
  await page.getByRole("textbox", { name: /^书名/ }).fill(title);
  if (genre) {
    const known = ["悬疑", "奇幻", "科幻", "言情", "历史", "现实", "其他"];
    await pickGenre(page, known.includes(genre) ? genre : "其他");
    if (!known.includes(genre)) await page.getByRole("textbox", { name: "其他类型", exact: true }).fill(genre);
  }
  if (summary) await page.getByRole("textbox", { name: /^简介/ }).fill(summary);
  await page.getByRole("button", { name: "创建并开始写第一章", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/workspace(?:[?#].*)?$/);
  return new URL(page.url()).pathname.split("/")[2];
}

/** Create a work straight through the API, for tests that only need it to exist. */
export async function createWorkByApi(page: Page, { title, genre = "悬疑", summary = "" }: WorkInput): Promise<string> {
  const created = await api(page).post("/projects", { title, genre, summary });
  return created.project.id;
}

/** Archive a work through the API (the way the archive dialog does). */
export async function archiveWorkByApi(page: Page, workId: string) {
  const work = await api(page).get(`/projects/${workId}`);
  await api(page).patch(`/projects/${workId}`, { base_metadata_revision: work.metadata_revision, status: "archived", confirm_archive: true });
}

/** Every work of the account except the sample work, archived ones included. */
export async function listWorks(page: Page): Promise<{ id: string; title: string; genre: string; summary: string; status: string; chapter_count: number; updated_at: string }[]> {
  const [current, archived] = await Promise.all([api(page).get("/projects?q=&sort=updated_desc"), api(page).get("/projects?q=&status=archived&sort=updated_desc")]);
  return [...current.projects, ...archived.projects].filter((item) => item.data_origin !== "tutorial_seed" && item.data_origin !== "demo_seed");
}

/** Open one tab of a work and wait until the top bar marks it as the current page. */
export async function openTab(page: Page, workId: string, tab: Tab) {
  await page.goto(`/projects/${workId}/${tab}`);
  await expect(page.getByRole("navigation", { name: "作品" }).getByRole("button", { name: tabLabels[tab], exact: true })).toHaveAttribute("aria-current", "page");
}

const draftEditor = (page: Page) => page.getByRole("textbox", { name: "草稿正文", exact: true });

/** Enter paragraphs with real browser input events, including empty paragraphs. */
export async function setDraftBody(page: Page, text: string) {
  const editor = draftEditor(page);
  await expect(editor).toHaveAttribute("contenteditable", "true");
  await editor.fill("");
  const lines = text.replaceAll("\r\n", "\n").split("\n");
  for (const [index, line] of lines.entries()) {
    if (index) await editor.press("Enter");
    if (line) await page.keyboard.insertText(line);
  }
  await expect.poll(() => readDraftBody(page)).toBe(lines.join("\n"));
}

/** Join the rendered paragraphs with newlines. */
export async function readDraftBody(page: Page) {
  const editor = draftEditor(page);
  await expect(editor).toBeVisible();
  return editor.evaluate((element) => {
    const text = (node: Node): string => {
      // Tiptap's non-editable finding badges decorate the text; they are not draft content.
      if (node instanceof HTMLElement && node.getAttribute("contenteditable") === "false") return "";
      if (node.nodeType === Node.TEXT_NODE) return node.textContent ?? "";
      if (node instanceof HTMLBRElement) return node.classList.contains("ProseMirror-trailingBreak") ? "" : "\n";
      return Array.from(node.childNodes).map(text).join("");
    };
    return Array.from(element.children).map(text).join("\n");
  });
}

/** Resolve a fixture relative to this support file, independent of shell cwd. */
export function fixturePath(name: string): string {
  const root = path.resolve(__dirname, "..", "fixtures");
  const resolved = path.resolve(root, name);
  const relative = path.relative(root, resolved);
  if (!relative || relative.startsWith("..") || path.isAbsolute(relative)) throw new Error("Fixture must be inside e2e/fixtures");
  return resolved;
}

/** Write a throwaway file under the run's output folder and return its path (for upload tests). */
export async function tempFile(name: string, content: string | Buffer): Promise<string> {
  // Each file gets its own folder so that the name stays exactly as given.
  const directory = path.join(process.env.E2E_OUTPUT_DIR ?? path.resolve(__dirname, "..", "..", "test-results"), "files", randomUUID().slice(0, 8));
  await mkdir(directory, { recursive: true });
  const file = path.join(directory, name);
  await writeFile(file, content);
  return file;
}

/**
 * The newest captured security mail of a purpose ("verify_email" | "password_reset") as a path that
 * can be opened (the token travels in the #fragment). With `recipient`, waits for a mail to that address.
 */
export async function mailLink(page: Page, purpose: "verify_email" | "password_reset", recipient?: string): Promise<string> {
  let link = "";
  await expect.poll(async () => {
    const response = await page.request.get(`/api/test/mail/${purpose}`);
    if (response.status() !== 200) return "none";
    const mail = await response.json();
    if (recipient && mail.recipient !== recipient) return "other recipient";
    const url = new URL(mail.action_url);
    link = `${url.pathname}${url.search}${url.hash}`;
    return "found";
  }, { message: `a ${purpose} mail${recipient ? ` to ${recipient}` : ""}` }).toBe("found");
  return link;
}

/** How many security mails the test backend has captured so far. */
export async function mailerCalls(page: Page): Promise<number> {
  const response = await page.request.get("/api/test/stage12/stats");
  expect(response.ok()).toBe(true);
  return (await response.json()).mailer_calls;
}

/** Wait for layout/animations, then capture the whole page (legacy default) or the current viewport. */
export async function shot(page: Page, name: string, fullPage = true) {
  const directory = process.env.E2E_SCREENSHOTS_DIR;
  if (!directory) throw new Error("E2E_SCREENSHOTS_DIR is required");
  await expect(page.getByText(/^正在(读取|载入)/)).toHaveCount(0);
  await page.evaluate(async (wholePage) => {
    await document.fonts.ready;
    if (wholePage) await Promise.all(document.getAnimations().filter((animation) => animation.effect?.getComputedTiming().iterations !== Infinity).map((animation) => animation.finished.catch(() => undefined)));
  }, fullPage);
  if (!fullPage) await expect.poll(() => page.evaluate(() => document.getAnimations().filter(animation => animation.playState === "running" && animation.effect?.getComputedTiming().iterations !== Infinity).length), { message: "viewport screenshot waits for running finite animations" }).toBe(0);
  await mkdir(directory, { recursive: true });
  await page.screenshot({ path: path.join(directory, `${name}.png`), fullPage });
}

/** Assert no sideways scrolling; soft mode keeps collecting evidence without hiding failures. */
export async function expectNoHorizontalOverflow(page: Page, soft = false) {
  const overflow = await page.evaluate(() => ({ scroll: document.documentElement.scrollWidth, inner: window.innerWidth }));
  (soft ? expect.soft : expect)(overflow.scroll, `page is ${overflow.scroll}px wide in a ${overflow.inner}px window`).toBeLessThanOrEqual(overflow.inner);
}

const tourEvents = ["memory_source_opened", "continuity_issue_located", "evidence_opened", "author_decision_recorded"] as const;

/** The sample work's latest check, with its findings. */
export async function sampleCheck(page: Page, workId: string) {
  const project = await api(page).get(`/projects/${workId}`);
  return api(page).get(`/projects/${workId}/checks/${project.latest_run.run_id}?include=issues,evidence,metrics`);
}

/** Record the author's decision on the sample check's first finding, as the decision buttons do. */
export async function decideFirstFinding(page: Page, workId: string, decision: "keep_intentional" | "false_positive") {
  const run = await sampleCheck(page, workId);
  const issue = run.issues[0];
  await api(page).post(`/projects/${workId}/issues/${issue.id}/decision`, { run_id: run.run_id, source_revision: run.source_revision, decision });
  return { runId: run.run_id as string, issueId: issue.id as string };
}

/** Move the tour forward through the progress API (a tour step is done when its event is recorded). */
export async function advanceTour(page: Page, workId: string, toStep: 2 | 3 | 4 | 5) {
  for (const event of tourEvents.slice(0, toStep - 1)) {
    if (event === "author_decision_recorded") await decideFirstFinding(page, workId, "keep_intentional");
    await api(page).post("/onboarding/progress", { tutorial_version: "1.2.0", project_id: workId, event });
  }
}
