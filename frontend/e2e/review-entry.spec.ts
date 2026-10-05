import AxeBuilder from "@axe-core/playwright";
import { expect, test } from "@playwright/test";

test("review entry opens after actionable decisions while insufficient evidence stays read-only", async ({ page }, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  const pageErrors: string[] = [];
  const consoleErrors: string[] = [];
  const failedApiResponses: string[] = [];
  const checkPosts: string[] = [];
  page.on("pageerror", (error) => pageErrors.push(error.message));
  page.on("request", (request) => {
    if (request.method() === "POST" && /\/api\/projects\/[^/]+\/checks$/.test(new URL(request.url()).pathname)) {
      checkPosts.push(request.url());
    }
  });

  await page.goto("/login");
  await page.getByRole("button", { name: "访客体验 24 小时", exact: true }).click();
  await expect(page.getByRole("heading", { name: "继续你的故事", exact: true })).toBeVisible();
  // Observe the authenticated review flow; the initial anonymous session probe is an expected 401.
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("response", (response) => {
    const pathname = new URL(response.url()).pathname;
    if (pathname.startsWith("/api/") && response.status() >= 400) {
      failedApiResponses.push(`${response.request().method()} ${pathname} ${response.status()}`);
    }
  });

  await page.locator(".global-nav").getByRole("button", { name: "作品管理", exact: true }).click();
  await page.locator(".project-rows li").filter({ hasText: "灰港回声" }).getByRole("button", { name: "打开", exact: true }).click();
  await page.locator(".project-nav").getByRole("button", { name: "写作与检查", exact: true }).click();
  await expect(page.getByText("示例检查结果", { exact: true })).toBeVisible();
  const issues = page.locator(".issue-list").getByRole("button");
  await expect(issues).toHaveCount(4);
  await expect(issues.filter({ hasText: "证据不足" })).toHaveCount(1);
  const drawer = page.getByRole("dialog", { name: "问题证据", exact: true });
  const insufficient = issues.filter({ hasText: "黎舟已经告诉苏岑‘廊桥钥匙’的含义。" });
  const expectInsufficientReadOnly = async () => {
    await insufficient.click();
    await expect(drawer.getByText("证据尚不充分", { exact: false })).toBeVisible();
    await expect(drawer.getByText("服务端未开放可提交操作", { exact: false })).toBeVisible();
    for (const name of ["前往修改", "预览修改建议", "保留原意", "标记误报"]) {
      await expect(drawer.getByRole("button", { name, exact: true })).toHaveCount(0);
    }
    await expect(drawer.getByRole("status")).toHaveCount(0);
    await drawer.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(drawer).toBeHidden();
  };
  await expectInsufficientReadOnly();

  const reviewEntry = page.getByRole("button", { name: "审阅事实变化", exact: true });
  const claims = [
    "温岚仍握着黄铜罗盘；与此同时，黄铜罗盘也在苏岑的外套内袋。",
    "随后，温岚把罗盘放在潮汐档案室的桌上。",
    "苏岑决定先核对那声不该响起的雾钟。",
  ];
  for (const [index, claim] of claims.entries()) {
    await expect(reviewEntry).toHaveCount(0);
    await expect(page.getByRole("heading", { name: `待处理提示 ${3 - index}`, exact: true })).toBeVisible();
    await issues.filter({ hasText: claim }).click();
    await drawer.getByRole("button", { name: "保留原意", exact: true }).click();
    await expect(drawer.getByRole("status")).toContainText("决定已记录；此问题保留在列表中，便于后续追溯。");
    await expect(drawer.getByRole("button", { name: "保留原意", exact: true })).toBeDisabled();
    await drawer.getByRole("button", { name: "关闭", exact: true }).click();
    await expect(drawer).toBeHidden();
    const notice = page.getByRole("status").filter({ hasText: "决定已记录：" });
    await expect(notice).toBeVisible();
    await expect(notice).toContainText(index < 2
      ? "决定已记录：保留作者意图；请继续处理其余需要决定的问题。"
      : "决定已记录：保留作者意图；可继续审阅后续的事实变化。");
  }

  await expect(page.getByRole("heading", { name: "待处理提示 0", exact: true })).toBeVisible();
  await expect(issues.filter({ hasText: "决定已记录" })).toHaveCount(3);
  await expect(reviewEntry).toBeVisible();
  await expect(reviewEntry).toBeEnabled();
  // Check the entire writing page with resolved impact labels and both
  // named details groups present, including the primary button's hover state.
  const colors = () => page.locator("button.primary:not(:disabled), .issue-row.resolved .risk, .issue-row.resolved .issue-claim").evaluateAll((elements) =>
    elements.map((element) => {
      const style = getComputedStyle(element);
      return { text: element.textContent, color: style.color, background: style.backgroundColor,
        opacity: style.opacity, rowOpacity: element.closest(".issue-row") ? getComputedStyle(element.closest(".issue-row")!).opacity : null };
    }),
  );
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  const defaultColors = await colors();
  await page.screenshot({ path: testInfo.outputPath("writing-1440.png"), fullPage: true });
  await reviewEntry.hover();
  expect((await new AxeBuilder({ page }).analyze()).violations).toEqual([]);
  await testInfo.attach("contrast-samples", { body: JSON.stringify({ default: defaultColors, hover: await colors() }, null, 2), contentType: "application/json" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("navigation", { name: "手机浏览内容" }).getByRole("button", { name: "问题 4", exact: true }).click();
  await expect(issues.filter({ hasText: "决定已记录" })).toHaveCount(3);
  await page.screenshot({ path: testInfo.outputPath("writing-390.png"), fullPage: true });
  await page.setViewportSize({ width: 1440, height: 900 });
  // Refresh verifies persisted decisions, independently of the local resolved-ID fallback.
  await page.reload();
  await expect(reviewEntry).toBeEnabled();
  await expect(page.getByRole("heading", { name: "待处理提示 0", exact: true })).toBeVisible();
  const changesetResponse = page.waitForResponse((response) =>
    response.request().method() === "POST" && /\/api\/projects\/[^/]+\/memory\/change-sets$/.test(new URL(response.url()).pathname),
  );
  await reviewEntry.click();
  expect((await changesetResponse).status()).toBe(201);
  const review = page.getByRole("form", { name: "事实库更新审阅", exact: true });
  await expect(review).toBeVisible();
  await expect(review.getByRole("heading", { name: "事实变化审阅", exact: true })).toBeVisible();
  await expect(review.locator("article.diff")).toHaveCount(3);
  await expectInsufficientReadOnly();
  await expect(insufficient).not.toContainText("决定已记录");
  await expect(page.getByRole("alert")).toBeEmpty();
  expect(checkPosts).toEqual([]);
  expect(failedApiResponses).toEqual([]);
  expect(consoleErrors).toEqual([]);
  expect(pageErrors).toEqual([]);
});
