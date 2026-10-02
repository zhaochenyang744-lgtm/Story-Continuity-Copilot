// 历史独立验收记录（见 docs/legacy-gap-…），绑定当时的端口与账号；不随界面更新，不参加日常运行。
import { expect, test, type Page, type TestInfo } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

// Independent G04 acceptance: response fixtures supply a review suggestion only.
// Drafts, saves, decisions, Tiptap, Evidence and source evidence remain real.
// This spec is only for the second-round production artifact with a fresh isolated injected-stub backend.
const frontendOrigin = "http://127.0.0.1:3238";
const backendOrigin = "http://127.0.0.1:8238";
if (process.env.E2E_BASE_URL !== frontendOrigin || process.env.E2E_BACKEND_ORIGIN !== backendOrigin) {
  throw new Error("G04 independent acceptance requires isolated preview 3238/backend 8238");
}
if (!process.env.E2E_ACCOUNT_PREFIX?.startsWith("gapg04")) throw new Error("G04 requires a gapg04 account prefix");

type Draft = { id: string; revision: number; body: string; body_format: string };
type Case = { name: string; body: string; before: string; after: string; selector?: string };
type Evidence = { sufficiency: string };
type Issue = { id: string; evidence_status: string; evidence?: Evidence[]; [key: string]: unknown };
type Run = { run_id: string; status: string; issues?: Issue[]; [key: string]: unknown };
const target = "温岚仍握着黄铜罗盘";
const replacement = "温岚仍保管黄铜罗盘";

async function read<T>(page: Page, url: string): Promise<T> {
  const response = await page.request.get(url);
  expect(response.ok(), `${url}: ${await response.text()}`).toBe(true);
  return (await response.json()).data as T;
}
async function post<T>(page: Page, url: string, data: unknown): Promise<T> {
  const response = await page.request.post(url, { data, headers: { "Idempotency-Key": randomUUID() } });
  expect(response.ok(), `${url}: ${await response.text()}`).toBe(true);
  return (await response.json()).data as T;
}
async function stats(page: Page) {
  const response = await page.request.get(`${backendOrigin}/api/test/stage12/stats`);
  expect(response.ok()).toBe(true);
  const result = await response.json();
  expect(result.provider_mode).toBe("injected_stub");
  expect(result.external_provider_http_enabled).toBe(false);
  expect(result.provider_http_calls).toBe(0);
  return { provider_mode: result.provider_mode, provider_http_calls: result.provider_http_calls };
}
async function prepare(page: Page, item: Case) {
  const account = `${process.env.E2E_ACCOUNT_PREFIX}${Date.now()}${randomUUID().slice(0, 6)}`;
  const registered = await post<{ onboarding: { tutorial: { project_id: string } } }>(page, "/api/auth/register", {
    account_name: account, display_name: "G04 独立浏览器验收", password: `safe-${randomUUID()}`,
    recovery_email: `${account}@example.test`,
  });
  const projectId = registered.onboarding.tutorial.project_id;
  const base = `/api/projects/${projectId}`;
  const project = await read<{ current_draft: { id: string; revision: number } }>(page, base);
  const draftUrl = `${base}/drafts/${project.current_draft.id}`;
  const patched = await page.request.patch(draftUrl, {
    data: { base_revision: project.current_draft.revision, body: item.body, body_format: "markdown" },
    headers: { "Idempotency-Key": randomUUID() },
  });
  expect(patched.ok(), await patched.text()).toBe(true);
  const draft = await read<Draft>(page, draftUrl);
  const started = await post<Run>(page, `${base}/checks`, { draft_id: draft.id, draft_revision: draft.revision });
  const runUrl = `${base}/checks/${started.run_id}`;
  await expect.poll(async () => (await read<Run>(page, runUrl)).status, { timeout: 20_000 }).toBe("completed");
  const run = await read<Run>(page, `${runUrl}?include=issues,evidence,metrics`);
  const issue = run.issues?.find((entry) => entry.evidence_status === "sufficient" && entry.evidence?.some((source) => source.sufficiency === "sufficient"));
  expect(issue, "The real injected-stub run must have an issue with real resolvable sufficient evidence").toBeTruthy();
  const issueId = issue!.id;
  const marker = `G04 independent ${item.name}`;
  const matcher = (url: URL) => url.pathname === runUrl && url.searchParams.get("include")?.includes("issues") === true;
  await page.route(matcher, async (route) => {
    const response = await route.fetch();
    const envelope = await response.json();
    const selected = envelope.data.issues.find((entry: Issue) => entry.id === issueId);
    expect(selected).toBeTruthy();
    Object.assign(selected, {
      nature: "possible_conflict", explanation: marker, claim_text: `${marker}：${item.before}`,
      reasoning: "隔离验收建议夹具；只用于验证格式替换，不代表模型判断质量。",
      available_actions: ["edit", "apply_suggestion", "keep_intentional", "false_positive"],
      suggested_revision: { before: item.before, after: item.after },
    });
    await route.fulfill({ response, json: envelope });
  });
  for (const event of ["memory_source_opened", "continuity_issue_located", "evidence_opened"]) {
    await post(page, "/api/onboarding/progress", { tutorial_version: "1.2.0", project_id: projectId, event });
  }
  await page.goto(`/projects/${projectId}/workspace`);
  const editor = page.locator("#draft-body");
  await expect(editor).toBeVisible();
  await expect(editor).toHaveAttribute("data-body-format", "markdown");
  await expect(editor).toBeEditable();
  const open = async () => {
    await page.locator(".issue-row").filter({ hasText: marker }).click({ timeout: 10_000 });
    const drawer = page.getByRole("dialog", { name: "问题证据", exact: true });
    await expect(drawer).toBeVisible();
    return drawer;
  };
  return { account, base, projectId, draftUrl, draft, editor, marker, issueId, open, matcher };
}
async function capture(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true, animations: "disabled" });
}
async function observe(page: Page) {
  const browserErrors: string[] = [];
  const externalRequests: string[] = [];
  const uiMutations: { method: string; path: string }[] = [];
  page.on("pageerror", (error) => browserErrors.push(error.message));
  page.on("request", (request) => {
    const url = new URL(request.url());
    if (!["GET", "HEAD"].includes(request.method())) uiMutations.push({ method: request.method(), path: url.pathname });
  });
  await page.context().route("**/*", async (route) => {
    const url = new URL(route.request().url());
    if (["http:", "https:"].includes(url.protocol) && ![frontendOrigin, backendOrigin].includes(url.origin)) {
      externalRequests.push(`${url.origin}${url.pathname}`);
      return route.abort("blockedbyclient");
    }
    return route.continue();
  });
  return { browserErrors, externalRequests, uiMutations };
}

test("G04 real workbench rejects unsafe Markdown suggestions visibly without changing body or saving", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const observed = await observe(page);
  const beforeStats = await stats(page);
  const results: unknown[] = [];
  const cases: Case[] = [
    { name: "mixed-marks", body: "**温岚仍握着**黄铜罗盘。", before: target, after: replacement },
    { name: "after-newline", body: `**${target}**。`, before: target, after: "温岚仍保管\n黄铜罗盘" },
    { name: "cross-paragraph", body: "温岚仍握着\n\n黄铜罗盘。", before: "温岚仍握着\n黄铜罗盘", after: replacement },
    { name: "repeated-paragraph", body: `**${target}**。\n\n**${target}**。`, before: target, after: replacement },
  ];
  try {
    for (const item of cases) {
      const state = await prepare(page, item);
      const htmlBefore = await state.editor.innerHTML();
      const storedBefore = await read<Draft>(page, state.draftUrl);
      const writesBefore = observed.uiMutations.length;
      const drawer = await state.open();
      await drawer.getByRole("button", { name: "预览修改建议", exact: true }).click();
      await drawer.getByRole("button", { name: "应用到未保存草稿", exact: true }).click();
      await expect(drawer.getByRole("alert")).toContainText("正文未改变；请返回正文手动修改并检查格式。");
      await drawer.getByRole("alert").scrollIntoViewIfNeeded();
      await expect(drawer.getByRole("alert")).toBeInViewport();
      await expect(state.editor).toHaveJSProperty("innerHTML", htmlBefore);
      expect(await read<Draft>(page, state.draftUrl)).toEqual(storedBefore);
      expect(observed.uiMutations.slice(writesBefore).filter((entry) => entry.path.includes("/drafts/") || entry.path.includes("/decision"))).toEqual([]);
      await capture(page, testInfo, item.name);
      results.push({ case: item.name, account: state.account, project_id: state.projectId, real_evidence_issue_id: state.issueId,
        passed: true, body_and_format_unchanged: true, server_revision_unchanged: storedBefore.revision, production_alert_visible: true });
      await page.unroute(state.matcher);
    }
    expect(observed.externalRequests).toEqual([]);
  } finally {
    await writeFile(testInfo.outputPath("g04-rejection-evidence.json"), JSON.stringify({ beforeStats, afterStats: await stats(page), results, ...observed }, null, 2));
  }
});

test("G04 real workbench retains uniform marks and nested containers through explicit save and refresh", async ({ page }, testInfo) => {
  test.setTimeout(240_000);
  await page.setViewportSize({ width: 1440, height: 900 });
  const observed = await observe(page);
  const beforeStats = await stats(page);
  const results: unknown[] = [];
  const cases: Case[] = [
    { name: "uniform-bold", body: `**${target}**。`, before: target, after: replacement, selector: "strong" },
    { name: "nested-list-quote", body: `- \n  > ***${target}***。`, before: target, after: replacement, selector: "li blockquote strong em, li blockquote em strong" },
  ];
  try {
    for (const item of cases) {
      const state = await prepare(page, item);
      await expect(state.editor.locator(item.selector!)).toContainText(target);
      const storedBefore = await read<Draft>(page, state.draftUrl);
      const writesBefore = observed.uiMutations.length;
      const drawer = await state.open();
      await drawer.getByRole("button", { name: "预览修改建议", exact: true }).click();
      await drawer.getByRole("button", { name: "应用到未保存草稿", exact: true }).click();
      await expect(drawer).toHaveCount(0);
      await expect(state.editor.locator(item.selector!)).toContainText(replacement);
      await expect(page.locator(".workspace-save-summary")).toContainText("未保存");
      expect(await read<Draft>(page, state.draftUrl)).toEqual(storedBefore);
      expect(observed.uiMutations.slice(writesBefore).filter((entry) => entry.path.includes("/drafts/") || entry.path.includes("/decision"))).toEqual([]);
      await capture(page, testInfo, `${item.name}-unsaved`);
      const oldDrawer = await state.open();
      await expect(oldDrawer.getByRole("button", { name: "预览修改建议", exact: true })).toBeDisabled();
      await expect(oldDrawer).toContainText("这条检查针对先前正文");
      await page.keyboard.press("Escape");
      await expect(oldDrawer).toHaveCount(0);
      await page.getByRole("button", { name: "保存受控修订", exact: true }).click();
      await expect(page.locator(".workspace-save-summary")).toContainText("已保存");
      await expect.poll(async () => (await read<Draft>(page, state.draftUrl)).revision).toBe(storedBefore.revision + 1);
      const saved = await read<Draft>(page, state.draftUrl);
      expect(saved.body_format).toBe("markdown");
      expect(saved.body).toContain(`**${replacement}**`);
      expect(saved.body).not.toContain(target);
      await page.reload();
      await expect(state.editor).toHaveAttribute("data-body-format", "markdown");
      await expect(state.editor.locator(item.selector!)).toContainText(replacement);
      expect(await read<Draft>(page, state.draftUrl)).toEqual(saved);
      await capture(page, testInfo, `${item.name}-saved-reloaded`);
      results.push({ case: item.name, account: state.account, project_id: state.projectId, real_evidence_issue_id: state.issueId,
        passed: true, unsaved_before_author_action: true, stale_suggestion_disabled: true,
        saved_revision: saved.revision, saved_body_format: saved.body_format, saved_body: saved.body, dom_selector_preserved: item.selector });
      await page.unroute(state.matcher);
    }
    expect(observed.externalRequests).toEqual([]);
  } finally {
    await writeFile(testInfo.outputPath("g04-save-evidence.json"), JSON.stringify({ beforeStats, afterStats: await stats(page), results, ...observed }, null, 2));
  }
});
