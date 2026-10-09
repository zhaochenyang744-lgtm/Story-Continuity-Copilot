import { randomUUID } from "node:crypto";
import { labelError, labelRunFailure } from "../app/api";
import { api, createWorkByApi, expect, openTab, registerAccount, sampleWorkId, shot, tabLabels, tabOrder, test } from "./support/app";

const workTabs = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "作品", exact: true });
const globalTabs = (page: import("@playwright/test").Page) => page.getByRole("navigation", { name: "全局", exact: true });

test("顶栏：首页和作品管理标出当前页；作品内五个标签依次排列，点哪个到哪个", async ({ page }) => {
  await registerAccount(page, "topbar");
  const workId = await createWorkByApi(page, { title: "顶栏试验之书" });

  // 全局: 首页 / 作品管理
  await expect(globalTabs(page).getByRole("button", { name: "首页", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(globalTabs(page).getByRole("button", { name: "作品管理", exact: true })).not.toHaveAttribute("aria-current", "page");
  await globalTabs(page).getByRole("button", { name: "作品管理", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(globalTabs(page).getByRole("button", { name: "作品管理", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(globalTabs(page).getByRole("button", { name: "首页", exact: true })).not.toHaveAttribute("aria-current", "page");
  await globalTabs(page).getByRole("button", { name: "首页", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(globalTabs(page).getByRole("button", { name: "首页", exact: true })).toHaveAttribute("aria-current", "page");

  // 作品内: 概览 写作 章节 资料 计划
  await openTab(page, workId, "overview");
  await expect(globalTabs(page)).toHaveCount(0);
  const buttons = workTabs(page).getByRole("button");
  await expect(buttons).toHaveCount(5);
  for (const [index, tab] of tabOrder.entries()) await expect(buttons.nth(index)).toHaveAccessibleName(tabLabels[tab]);
  expect(tabOrder.map((tab) => tabLabels[tab])).toEqual(["概览", "写作", "章节", "资料", "计划"]);
  await shot(page, "shell-overview");

  for (const tab of [...tabOrder, "overview" as const]) {
    await workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${workId}/${tab}$`));
    await expect(workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true })).toHaveAttribute("aria-current", "page");
    // Only the current one is marked.
    await expect(workTabs(page).locator("[aria-current='page']")).toHaveCount(1);
  }
});

test("切换标签不重读作品：作品详情接口的请求数不增加，页面也没有重新加载", async ({ page }) => {
  await registerAccount(page, "tabsame");
  const workId = await createWorkByApi(page, { title: "切换标签之书" });
  const detail = new URL(`/api/projects/${workId}`, "http://x").pathname;
  let reads = 0;
  page.on("request", (request) => { if (request.method() === "GET" && new URL(request.url()).pathname === detail) reads += 1; });

  await openTab(page, workId, "overview");
  await expect(page.getByRole("heading", { level: 1, name: "切换标签之书", exact: true })).toBeVisible();
  await page.waitForLoadState("networkidle");
  expect(reads, "the work is read when it is opened").toBeGreaterThanOrEqual(1);
  const afterOpen = reads;
  // A marker that only a full page load would wipe.
  await page.evaluate(() => { (window as unknown as { __kept: boolean }).__kept = true; });

  for (const tab of [...tabOrder, "memory", "overview"] as const) {
    await workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true }).click();
    await expect(page).toHaveURL(new RegExp(`/projects/${workId}/${tab}$`));
    await expect(workTabs(page).getByRole("button", { name: tabLabels[tab], exact: true })).toHaveAttribute("aria-current", "page");
  }
  await page.waitForLoadState("networkidle");
  expect(reads, "switching tabs must not read the work again").toBe(afterOpen);
  expect(await page.evaluate(() => (window as unknown as { __kept?: boolean }).__kept)).toBe(true);
  // A different work does read its own record.
  const other = await createWorkByApi(page, { title: "另一部" });
  await page.goto(`/projects/${other}/overview`);
  await expect(page.getByRole("heading", { level: 1, name: "另一部", exact: true })).toBeVisible();
});

test("切换作品：用顶栏的「更换当前作品」换到另一部，网址和标题都跟着换", async ({ page }) => {
  await registerAccount(page, "switchwork");
  const first = await createWorkByApi(page, { title: "第一部书" });
  const second = await createWorkByApi(page, { title: "第二部书" });
  await openTab(page, first, "overview");
  await expect(page.getByRole("heading", { level: 1, name: "第一部书", exact: true })).toBeVisible();

  await page.getByRole("button", { name: "更换当前作品：第一部书", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await page.getByRole("main").getByRole("button", { name: /第二部书/ }).first().click();
  await expect(page).toHaveURL(new RegExp(`/projects/${second}/overview$`));
  await expect(page.getByRole("heading", { level: 1, name: "第二部书", exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "更换当前作品：第二部书", exact: true })).toBeVisible();
  await expect(page.getByText("第一部书")).toHaveCount(0);
  // The sample work can be switched to as well.
  const sample = await sampleWorkId(page);
  await page.goto(`/projects/${sample}/overview`);
  await expect(page.getByRole("button", { name: "更换当前作品：灰港回声", exact: true })).toBeVisible();
});

test("找不到页面：未知网址和不存在的作品都有自己的说明", async ({ page }) => {
  await registerAccount(page, "notfound");
  await page.goto("/不存在的路径");
  await expect(page.getByRole("heading", { level: 1, name: "找不到这个页面", exact: true })).toBeVisible();
  await expect(page.getByText("网址可能输错了，或者这个页面已经不在了。", { exact: true })).toBeVisible();
  // Its content starts at the page's left margin, like every other page.
  const edge = await page.evaluate(() => {
    const main = document.getElementById("main")!;
    return { heading: document.querySelector("h1")!.getBoundingClientRect().left, margin: main.getBoundingClientRect().left + parseFloat(getComputedStyle(main).paddingLeft) };
  });
  expect(edge.heading).toBeCloseTo(edge.margin, 0);
  await shot(page, "not-found");
  await page.getByRole("button", { name: "回到首页", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);

  const missing = `prj-${randomUUID()}`;
  expect((await api(page).raw("GET", `/projects/${missing}`)).status).toBe(404);
  await page.goto(`/projects/${missing}/overview`);
  await expect(page.getByRole("heading", { level: 1, name: "找不到这部作品", exact: true })).toBeVisible();
  await expect(page.getByText("它可能已经删除，或者不属于当前账号。其他作品不受影响。", { exact: true })).toBeVisible();
  await shot(page, "work-not-found");
  await page.getByRole("button", { name: "作品管理", exact: true }).last().click();
  await expect(page).toHaveURL(/\/projects$/);
});

test("跳到主要内容：第一次按 Tab 落在跳转链接上，回车后焦点就在主要内容区上，再按 Tab 进入它里面的第一个控件", async ({ page }) => {
  await registerAccount(page, "skiplink");
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "从第一章开始", exact: true })).toBeVisible();
  await page.evaluate(() => (document.activeElement as HTMLElement | null)?.blur());
  await page.keyboard.press("Tab");
  const skip = page.getByRole("link", { name: "跳到主要内容", exact: true });
  await expect(skip).toBeFocused();
  await expect(skip).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(/#main$/);
  // Focus is on the main area itself, and takes no frame (the whole area would be boxed in).
  const main = page.getByRole("main");
  await expect(main).toBeFocused();
  await expect(main).toHaveCSS("outline-style", "none");
  // The next Tab lands on the first control inside it, not back in the top bar.
  const first = await page.evaluate(() => {
    const selector = 'a[href], button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), summary, [tabindex]:not([tabindex="-1"])';
    const element = Array.from(document.getElementById("main")!.querySelectorAll<HTMLElement>(selector)).find(item => item.getClientRects().length > 0);
    return element ? element.outerHTML.slice(0, 160) : null;
  });
  expect(first, "主要内容区里有可以聚焦的控件").not.toBeNull();
  await page.keyboard.press("Tab");
  await expect.poll(() => page.evaluate(() => document.activeElement === document.getElementById("main"))).toBe(false);
  await expect.poll(() => page.evaluate(() => document.activeElement?.outerHTML.slice(0, 160))).toBe(first);
});

test("错误文案：补齐的错误码一一对应，失败的检查和分析用平常的话，不出现技术词", async () => {
  const conflict = "内容在别处更新过。已经载入最新版本，请确认后再试。";
  const expected: Record<string, string> = {
    base_version_changed: conflict, metadata_revision_conflict: conflict, author_context_version_conflict: conflict,
    draft_revision_not_current: "草稿在别处更新过，请刷新后再试。",
    run_basis_changed: "作品内容变了，这次检查的结果已经过期，请再检查一次。",
    run_cancelled: "这次检查已经取消。",
    already_decided: "这一条已经处理过了。",
    idempotency_conflict: "这个操作刚刚已经提交过，请刷新看看结果。",
    import_expired: "导入预览已经过期，请重新选择文件。",
    source_too_large: "文件太大，超过了单次导入的上限。",
    chapter_revision_empty: "章节正文不能为空。",
    chapter_revision_unchanged: "正文和标题都没变，不用提交。",
    setting_category_name_invalid: "分类名称不能为空，最多 20 个字。",
    export_too_large: "资料包太大，请先单独导出 TXT 或 Markdown 正文。",
  };
  for (const [code, text] of Object.entries(expected)) expect(labelError({ code }), code).toBe(text);
  // The export panel's own words for the same refusal are the same sentence.
  expect(labelError({ code: "export_too_large" })).toBe("资料包太大，请先单独导出 TXT 或 Markdown 正文。");

  expect(labelRunFailure("invalid_json")).toBe("这次检查没有完成，没有留下任何结果。");
  expect(labelRunFailure("schema_invalid", "回顾")).toBe("这次回顾没有完成，没有留下任何结果。");
  expect(labelRunFailure(null)).toBe("这次检查没有完成，没有留下任何结果。");
  expect(labelRunFailure("no_such_error", "对照")).toBe("这次对照没有完成，没有留下任何结果。");
  const technical = /结构|校验|写入|[Pp]rovider|token|schema/;
  for (const code of ["invalid_json", "schema_invalid", "output_truncated", "provider_unavailable", "provider_timeout", "internal_run_error", "budget_guard_exceeded", "author_cancelled", "evidence_unresolvable", "review_contract_unresolvable", "suggested_revision_unresolvable", "candidate_fields_invalid", "change_kind_invalid", "affected_memory_invalid", "duplicate_candidate", "invalidation_reason_invalid", "provider_attempt_quota_exceeded", "analysis_input_invalid", "analysis_draft_empty", "run_basis_changed", "budget_paused"]) {
    for (const what of ["检查", "回顾", "对照", "事实整理"]) {
      const text = labelRunFailure(code, what);
      expect(text, `${code} / ${what}`).not.toMatch(technical);
      expect(text, `${code} / ${what}`).toContain("没有留下");
    }
    expect(labelError({ code }), code).not.toMatch(technical);
  }
});
