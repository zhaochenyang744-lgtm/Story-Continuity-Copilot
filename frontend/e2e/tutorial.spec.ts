import type { Page } from "@playwright/test";
import { advanceTour, api, expect, openAccountMenu, openTab, registerAccount, sampleCheck, sampleWorkId, shot, test } from "./support/app";

const bar = (page: Page) => page.getByRole("region", { name: "导览", exact: true });
const findings = (page: Page) => page.getByRole("complementary", { name: "检查结果", exact: true });
const notice = (page: Page, text: string) => page.getByRole("status").filter({ hasText: text });
const progress = async (page: Page) => (await api(page).get("/onboarding")).progress as { current_step: number; completed_events: string[] };
const startTour = async (page: Page) => {
  await page.getByRole("button", { name: "开始导览", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  await expect(bar(page)).toContainText("导览 1 / 5");
};

test("走完导览：看事实出处 → 找检查结果 → 看依据 → 作决定 → 完成", async ({ page }) => {
  await registerAccount(page, "tour");
  const workId = await sampleWorkId(page);
  expect(await progress(page)).toMatchObject({ current_step: 1, completed_events: [] });

  // 第 1 步
  await startTour(page);
  await expect(page).toHaveURL(new RegExp(`/projects/${workId}/overview$`));
  await expect(bar(page).getByRole("list", { name: "五步导览" }).getByRole("listitem")).toHaveCount(5);
  await expect(bar(page)).toContainText("在资料里找到一条事实");
  await shot(page, "tutorial-step1");
  await bar(page).getByRole("button", { name: "去资料", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${workId}/memory$`));
  await expect(bar(page).getByRole("button", { name: "指给我看", exact: true })).toBeVisible();
  // Open where a fact comes from, then close it again.
  await page.getByRole("button", { name: /出自哪一章$/ }).first().click();
  const source = page.getByRole("dialog", { name: /^第 \d+ 章/ });
  await expect(source).toContainText("原文出处");
  await expect(source).toContainText("原文在这里只读，不会从这里修改。");
  await expect.poll(async () => (await progress(page)).completed_events).toEqual(["memory_source_opened"]);
  await source.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(source).toHaveCount(0);

  // 第 2 步: the check results
  await expect(bar(page)).toContainText("导览 2 / 5");
  await bar(page).getByRole("button", { name: "去写作页", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${workId}/workspace$`));
  await expect(findings(page).getByText("示例结果", { exact: false })).toBeVisible();
  // 第 3 步: open the first finding, then its full grounds.
  await findings(page).getByRole("button", { expanded: false }).first().click();
  await expect(bar(page)).toContainText("导览 3 / 5");
  await expect.poll(async () => (await progress(page)).current_step).toBe(3);
  await findings(page).getByRole("button", { name: "查看完整依据", exact: true }).click();
  await expect(bar(page)).toContainText("导览 4 / 5");
  expect(await progress(page)).toMatchObject({ current_step: 4, completed_events: ["memory_source_opened", "continuity_issue_located", "evidence_opened"] });

  // 第 4 步: decide.
  await expect(findings(page).getByRole("button", { name: "不是问题", exact: true })).toBeVisible();
  await expect(findings(page).getByRole("button", { name: "是有意的", exact: true })).toBeVisible();
  await shot(page, "tutorial-step4");
  await findings(page).getByRole("button", { name: "不是问题", exact: true }).click();
  await expect(notice(page, "记下了：这一条不是问题，不会写进资料。")).toBeVisible();

  // 第 5 步
  await expect(bar(page)).toContainText("导览 5 / 5");
  await expect(bar(page)).toContainText("决定记下了");
  const run = await sampleCheck(page, workId);
  expect(run.issues[0].decision).toMatchObject({ decision: "false_positive" });
  expect(await progress(page)).toMatchObject({ current_step: 5, completed_events: ["memory_source_opened", "continuity_issue_located", "evidence_opened", "author_decision_recorded"] });
  await bar(page).getByRole("button", { name: "完成导览", exact: true }).click();

  await expect(page).toHaveURL(/\/onboarding\/complete$/);
  await expect(page.getByRole("heading", { level: 1, name: "导览完成了", exact: true })).toBeVisible();
  await expect(page.getByText("导览 · 已完成", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "导入自己的作品", exact: true })).toBeVisible();
  await shot(page, "tutorial-complete");
  const onboarding = await api(page).get("/onboarding");
  expect(onboarding.status).toBe("completed");
  expect(onboarding.completed_at).toEqual(expect.any(String));
  // The decision made in the tour is a real one.
  expect((await sampleCheck(page, workId)).issues[0].decision).toMatchObject({ decision: "false_positive" });
});

test("跳过导览：回到首页并提示，完成页是「你跳过了导览」", async ({ page }) => {
  await registerAccount(page, "tourskip");
  await startTour(page);
  await bar(page).getByRole("button", { name: "跳过导览", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  await expect(notice(page, "已跳过导览。现在可以导入自己的作品。")).toBeVisible();
  expect((await api(page).get("/onboarding")).status).toBe("skipped");
  // Nothing of the tour is left to start; it can be taken again from the sample card.
  await expect(page.getByRole("button", { name: "开始导览", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: "重新看一遍导览", exact: true })).toBeVisible();

  await page.goto("/onboarding/complete");
  await expect(page.getByRole("heading", { level: 1, name: "你跳过了导览", exact: true })).toBeVisible();
  await expect(page.getByText("导览 · 已跳过", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "导入自己的作品", exact: true })).toBeVisible();
});

test("稍后再说：离开导览，刷新或再回来仍停在同一步", async ({ page }) => {
  await registerAccount(page, "tourlater");
  const workId = await sampleWorkId(page);
  await startTour(page);

  // 收起 / 展开 the explanation of the step.
  const more = bar(page).getByRole("button", { name: "这一步做什么", exact: true });
  await expect(more).toHaveAttribute("aria-expanded", "false");
  await more.click();
  await expect(bar(page)).toContainText("打开资料，找一条已经确认的事实，看它出自哪一章。");
  await bar(page).getByRole("button", { name: "收起", exact: true }).click();
  await expect(bar(page)).not.toContainText("打开资料，找一条已经确认的事实");

  // A refresh keeps the step the server has recorded.
  await advanceTour(page, workId, 2);
  await page.reload();
  await expect(bar(page)).toContainText("导览 2 / 5");
  await openTab(page, workId, "workspace");
  await expect(bar(page)).toContainText("导览 2 / 5");

  // 稍后再说 is offered on the last step: it leaves for the home page and keeps the tour where it was.
  await advanceTour(page, workId, 5);
  await page.reload();
  await expect(bar(page)).toContainText("导览 5 / 5");
  await bar(page).getByRole("button", { name: "稍后再说", exact: true }).click();
  await expect(page).toHaveURL(/\/$/);
  expect(await progress(page)).toMatchObject({ current_step: 5 });
  expect((await api(page).get("/onboarding")).status).toBe("active");
  await page.getByRole("button", { name: "开始导览", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${workId}/overview$`));
  await expect(bar(page)).toContainText("导览 5 / 5");
  await page.reload();
  await expect(bar(page)).toContainText("导览 5 / 5");
  await expect(bar(page).getByRole("button", { name: "完成导览", exact: true })).toBeVisible();
});

test("重新看一遍导览：回到第一步，之前的决定和草稿都不变", async ({ page }) => {
  await registerAccount(page, "tourrestart");
  const workId = await sampleWorkId(page);
  await advanceTour(page, workId, 5);
  await api(page).post("/onboarding/complete", { confirm: true });
  expect((await api(page).get("/onboarding")).status).toBe("completed");

  const project = await api(page).get(`/projects/${workId}`);
  const draftBefore = await api(page).get(`/projects/${workId}/drafts/${project.current_draft.id}`);
  const runBefore = await sampleCheck(page, workId);
  const chaptersBefore = (await api(page).get(`/projects/${workId}/chapters`)).chapters.length;
  expect(runBefore.issues[0].decision).toMatchObject({ decision: "keep_intentional" });

  await page.goto("/");
  await openAccountMenu(page);
  await page.getByRole("menuitem", { name: "重新看一遍导览", exact: true }).click();
  await expect(notice(page, "导览回到了第一步；正文、资料和处理记录都没有变。")).toBeVisible();
  await expect(page).toHaveURL(new RegExp(`/projects/${workId}/overview$`));
  await expect(bar(page)).toContainText("导览 1 / 5");

  const onboarding = await api(page).get("/onboarding");
  expect(onboarding.status).toBe("active");
  expect(onboarding.progress).toMatchObject({ current_step: 1, completed_events: [] });
  // Text, facts and the author's earlier decision are as they were.
  const draftAfter = await api(page).get(`/projects/${workId}/drafts/${project.current_draft.id}`);
  expect(draftAfter.body).toBe(draftBefore.body);
  expect(draftAfter.revision).toBe(draftBefore.revision);
  const runAfter = await sampleCheck(page, workId);
  expect(runAfter.run_id).toBe(runBefore.run_id);
  expect(runAfter.issues[0].decision).toMatchObject({ decision: "keep_intentional" });
  expect((await api(page).get(`/projects/${workId}/chapters`)).chapters).toHaveLength(chaptersBefore);
});

test("窄屏下的导览：第 4 步只能看依据，没有可点的决定按钮", async ({ page }) => {
  await registerAccount(page, "tournarrow");
  const workId = await sampleWorkId(page);
  await advanceTour(page, workId, 4);
  await page.setViewportSize({ width: 390, height: 844 });
  await openTab(page, workId, "workspace");
  await expect(bar(page)).toContainText("导览 4 / 5");
  await bar(page).getByRole("button", { name: "这一步做什么", exact: true }).click();
  await expect(bar(page)).toContainText("手机上可以浏览完整依据；请在电脑上作出决定。");
  await expect(page.getByRole("note").filter({ hasText: "手机上可以浏览完整依据；请在电脑上继续作出决定。" })).toBeVisible();

  // The grounds can be read ... (on a narrow screen the page shows one part at a time)
  await page.getByRole("navigation", { name: "切换内容", exact: true }).getByRole("button", { name: /^检查结果/ }).click();
  await findings(page).getByRole("button", { expanded: false }).first().click();
  await expect(findings(page).getByText("依据", { exact: true })).toBeVisible();
  await expect(findings(page).getByText("手机上可以浏览完整依据；请在电脑上继续作出决定。")).toBeVisible();
  // ... but nothing can be decided.
  for (const name of ["不是问题", "是有意的", "采用改法", "标为待修改", "改正文"]) {
    await expect(findings(page).getByRole("button", { name, exact: true }), name).toHaveCount(0);
  }
  expect((await sampleCheck(page, workId)).issues[0].decision).toBeNull();
  expect(await progress(page)).toMatchObject({ current_step: 4 });
});
