import { api, createWorkByApi, expect, expectNoHorizontalOverflow, openTab, registerAccount, sampleCheck, sampleWorkId, shot, tempFile, test } from "./support/app";
import { draft, button } from "./support/writing";
import { evidence, importBook, intent, pair, project, sample } from "./support/pages";

test("08 概览：示例数字与接口一致", async ({ page }) => {
  const id = await sample(page), work = await project(page, id), saved = await draft(page, id), check = await sampleCheck(page, id);
  const timeline = (await api(page).get(`/projects/${id}/chapter-timeline`)).chapters;
  const figures = page.getByTestId("overview-figures");
  const values = figures.getByTestId("count-live");
  await expect(values).toHaveText(["10", String(check.issues.filter((i: any) => !i.decision && !i.reused_decision).length), work.chapter_word_count.toLocaleString("en-US")]);
  await expect(figures).toContainText(`已检查 ${timeline.filter((c: any) => !c.draft && c.status === "checked").length}`);
  await expect(figures).toContainText(`另有草稿 ${saved.body.replace(/\s+/g, "").length.toLocaleString("en-US")} 字`);
  await pair(page, "overview");
});

test("08 故事航线：章节、伏笔和考虑中计划", async ({ page }) => {
  const id = await sample(page);
  const route = page.getByRole("region", { name: "故事航线", exact: true });
  await expect(route.getByTestId(/^route-chapter-/)).toHaveCount(11);
  await expect(route.getByRole("button", { name: /^第 11 章 · / })).toHaveAttribute("title", /^第 11 章草稿 · /);
  const threads = (await api(page).get(`/projects/${id}/foreshadows`)).records.filter((r: any) => !r.archived_at && r.planted && ["planted", "developing"].includes(r.status));
  expect(threads.length).toBeGreaterThan(0);
  await expect(route.getByTestId(/^route-thread-/)).toHaveCount(Math.min(6, threads.filter((r: any) => r.planted.chapter_number < 11).length));
  await expect(route.getByText("接下来", { exact: true })).toBeVisible();
  await expect(route.getByText("考虑中", { exact: true })).toBeVisible();
  const plans = await intent(page, id);
  expect(plans.story_plans.some((p: any) => !p.archived && p.target_chapter_number > 11)).toBe(true);
  await route.scrollIntoViewIfNeeded();
  await shot(page, "overview-route", false);
  // A written chapter opens in the writing page by its number; the draft's point opens the draft.
  await route.getByRole("button", { name: /^第 3 章 · / }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=3$`));
  await openTab(page, id, "overview");
  await route.getByRole("button", { name: /^第 11 章 · / }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace$`));
});

test("08 故事航线：键盘可以到达每个章节点，聚焦时和悬停一样高亮，回车打开", async ({ page }) => {
  const id = await sample(page);
  const route = page.getByRole("region", { name: "故事航线", exact: true });
  const points = route.getByRole("button", { name: /^第 \d+ 章/ });
  await expect(points).toHaveCount(11);
  await points.nth(4).focus();
  await expect(points.nth(4)).toBeFocused();
  await expect(route.getByText(/^第 5 章时 · \d+ 条伏笔悬着$/)).toBeVisible();
  await page.keyboard.press("Tab");
  await expect(points.nth(5)).toBeFocused();
  await expect(route.getByText(/^第 6 章时 · \d+ 条伏笔悬着$/)).toBeVisible();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace\\?chapter=6$`));
  await openTab(page, id, "overview");
  await points.nth(10).focus();
  await page.keyboard.press("Enter");
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace$`));
});

test("08 草稿里待看：条数与写作入口", async ({ page }) => {
  const id = await sample(page), check = await sampleCheck(page, id);
  const region = page.getByRole("region", { name: "草稿里待看", exact: true });
  await expect(region.getByRole("listitem")).toHaveCount(check.issues.filter((i: any) => !i.decision && !i.reused_decision).length);
  await region.getByRole("button", { name: "去写作页处理", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace$`));
});

test("08 接下来：计划入口与空作品提示", async ({ page }) => {
  const id = await sample(page), plans = await intent(page, id);
  const region = page.getByRole("region", { name: "接下来", exact: true });
  await expect(region.getByRole("listitem")).toHaveCount(Math.min(5, plans.story_plans.filter((p: any) => !p.archived && p.status !== "completed").length));
  await button(page, "全部计划").click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/plan$`));
  const empty = await createWorkByApi(page, { title: "空的航线" });
  await openTab(page, empty, "overview");
  await expect(page.getByText(/^还没写下接下来的打算。/)).toBeVisible();
});

test("08 空作品概览：空状态与页面宽度", async ({ page }) => {
  await registerAccount(page, "empty08");
  const id = await createWorkByApi(page, { title: "尚未启航" });
  const errors: string[] = [];
  page.on("pageerror", e => errors.push(e.message));
  await openTab(page, id, "overview");
  await expect(page.getByText("还没有已写的章节", { exact: true })).toBeVisible();
  await expect(page.getByTestId("overview-figures").getByTestId("count-live")).toHaveText(["0", "0", "0"]);
  // Next's empty route-announcer has role=alert; application errors live in main.
  await expect(page.getByRole("main").getByRole("alert")).toHaveCount(0);
  await expectNoHorizontalOverflow(page);
  expect(errors).toEqual([]);
  await pair(page, "overview-empty");
});

test("08 大数字不溢出：十万字正文", async ({ page }, info) => {
  await registerAccount(page, "large08");
  const text = Array.from({ length: 30 }, (_, i) => `第${i + 1}章 测试航程\n\n${"风吹过空旷的码头，值班员把当天的水位记在本子上。".repeat(160)}\n`).join("\n");
  const id = await importBook(page, await tempFile("large-book.txt", text), "十万字测试航程");
  expect((await project(page, id)).chapter_word_count).toBeGreaterThan(100_000);
  await expect(page.getByTestId("overview-word-count").getByTestId("count-live")).toHaveText((await project(page, id)).chapter_word_count.toLocaleString("en-US"));
  const measurements = { size: parseFloat(await page.getByTestId("overview-word-count").getByTestId("count-live").evaluate(e => getComputedStyle(e).fontSize)), block: await page.getByTestId("overview-word-count").evaluate(e => e.getBoundingClientRect().toJSON()), number: await page.getByTestId("overview-word-count").getByTestId("count-live").evaluate(e => e.getBoundingClientRect().toJSON()), content: await page.getByTestId("overview-page").evaluate(e => e.getBoundingClientRect().toJSON()) };
  await evidence(info, "overview-large", measurements);
  await shot(page, "overview-large-day", false);
  expect(measurements.block.right, "数字区不超出概览内容区").toBeLessThanOrEqual(measurements.content.right);
  expect(measurements.number.right, "数字文本也不超出内容区").toBeLessThanOrEqual(measurements.content.right);
  // Numbers that fit keep the full size (the example's chapter count); the six-digit one is smaller because it did not fit.
  await openTab(page, await sampleWorkId(page), "overview");
  const sizes = await page.getByTestId("overview-figures").getByTestId("count-live").evaluateAll(nodes => nodes.map(node => parseFloat(getComputedStyle(node).fontSize)));
  expect(sizes[0], "放得下的数字保持最大字号").toBe(72);
  expect(measurements.size, "十万字的数字放不下，缩小了").toBeLessThan(72);
});
