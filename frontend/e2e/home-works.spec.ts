import type { Page } from "@playwright/test";
import { api, archiveWorkByApi, createWorkByApi, expect, listWorks, registerAccount, sampleWorkId, shot, startVisitor, test } from "./support/app";

const count = (value: number) => value.toLocaleString("en-US");
const worksPage = async (page: Page) => {
  await page.goto("/projects");
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
};
const rows = (page: Page) => page.getByRole("main").getByRole("listitem");
const rowOf = (page: Page, title: string) => rows(page).filter({ hasText: title });
const titlesFromApi = async (page: Page, query: string) => (await api(page).get(`/projects?${query}`)).projects.map((work: { title: string }) => work.title);

test("新用户首页：示例作品卡片、空的「你的作品」、检查额度", async ({ page }) => {
  await registerAccount(page, "homenew");
  const sample = await api(page).get(`/projects/${await sampleWorkId(page)}`);
  expect(sample.chapter_count).toBe(10);

  await expect(page.getByRole("heading", { level: 1, name: "从第一章开始", exact: true })).toBeVisible();
  await expect(page.getByText("你好", { exact: true })).toBeVisible();
  await expect(page.getByRole("banner").getByRole("button", { name: "新建作品", exact: true })).toBeVisible();

  // 示例作品
  const samples = page.getByRole("region", { name: "示例作品" });
  await expect(samples.getByRole("heading", { name: "示例作品", exact: true })).toBeVisible();
  const card = samples.getByRole("button", { name: /灰港回声/ });
  await expect(card).toContainText("10 章");
  // The card counts the written chapters only (the same figure as the overview's 正文), not the draft.
  expect(sample.chapter_word_count).toBeLessThan(sample.word_count);
  await expect(card).toContainText(`${count(sample.chapter_word_count)} 字`);
  await expect(samples.getByRole("button", { name: "开始导览", exact: true })).toBeVisible();
  await expect(samples.getByText("示例作品不占你的作品数，也不计入额度。", { exact: true })).toBeVisible();

  // 你的作品: empty, with both ways in.
  const mine = page.getByRole("region", { name: "你的作品" });
  await expect(mine.getByText("还没有自己的作品。把写好的稿子导进来，或者从第一章开始。", { exact: true })).toBeVisible();
  await expect(mine.getByRole("button", { name: /导入已有作品/ })).toBeVisible();
  await expect(mine.getByRole("button", { name: /从空白开始/ })).toBeVisible();
  expect(await listWorks(page)).toEqual([]);

  // 检查额度 shows what the server says.
  const usage = await api(page).get("/account/usage");
  expect(usage.account_type).toBe("registered");
  const quota = page.getByRole("region", { name: "检查额度" });
  await expect(quota).toContainText(`${count(usage.check_chars_remaining)} / ${count(usage.check_chars_limit)} 字`);
  await expect(quota).toContainText("24 小时内还可检查");
  await expect(quota).toContainText(`现在还能检查约 ${Math.floor(usage.check_chars_remaining / 2500)} 章`);
  await shot(page, "home-new-user");

  // The two entries lead where they say.
  await mine.getByRole("button", { name: /导入已有作品/ }).click();
  await expect(page).toHaveURL(/\/projects\/import$/);
  await page.goBack();
  await mine.getByRole("button", { name: /从空白开始/ }).click();
  await expect(page).toHaveURL(/\/projects\/new$/);
});

test("访客首页：访客标题区和访客版额度", async ({ page }) => {
  await startVisitor(page);
  await expect(page.getByText("访客空间 · 24 小时", { exact: true })).toBeVisible();
  // The sample work is not the visitor's own work: nothing to continue, the page starts from chapter one,
  // and the sample only appears in its own column.
  expect((await api(page).get("/home")).continue_work).toBeNull();
  await expect(page.getByRole("heading", { level: 1, name: "从第一章开始", exact: true })).toBeVisible();
  await expect(page.getByRole("heading", { level: 1, name: "继续你的故事", exact: true })).toHaveCount(0);
  await expect(page.getByRole("button", { name: /上次停在/ })).toHaveCount(0);
  const mine = page.getByRole("region", { name: "你的作品" });
  await expect(mine.getByText("还没有自己的作品。把写好的稿子导进来，或者从第一章开始。", { exact: true })).toBeVisible();
  await expect(mine.getByText("灰港回声")).toHaveCount(0);
  const usage = await api(page).get("/account/usage");
  expect(usage.account_type).toBe("visitor");
  const quota = page.getByRole("region", { name: "检查额度" });
  await expect(quota).toContainText(`${usage.checks_remaining} / ${usage.checks_limit} 次`);
  await expect(quota).toContainText("访客 · 24 小时内还可检查");
  await expect(quota).toContainText(`每次最多 ${count(usage.check_chars_per_check)} 字`);
  await expect(quota).toContainText("注册后可以检查更长的章节");
  // The sample work is there; a visitor has no tour to restart.
  const sample = await api(page).get(`/projects/${await sampleWorkId(page)}`);
  const card = page.getByRole("region", { name: "示例作品" }).getByRole("button", { name: /灰港回声/ });
  await expect(card).toBeVisible();
  await expect(card).toContainText(`${count(sample.chapter_word_count)} 字`);
  await shot(page, "home-visitor");
});

test("作品管理列表：搜索、状态筛选、排序", async ({ page }) => {
  await registerAccount(page, "worklist");
  // 北堤旧事 (paused) is older than 潮声之后, so "recently changed" and "by title" disagree; 雾港来信 is archived.
  const north = await createWorkByApi(page, { title: "北堤旧事", genre: "历史", summary: "北堤上的旧案。" });
  const northWork = await api(page).get(`/projects/${north}`);
  await api(page).patch(`/projects/${north}`, { base_metadata_revision: northWork.metadata_revision, status: "paused" });
  await createWorkByApi(page, { title: "潮声之后", genre: "悬疑", summary: "潮退之后留下的东西。" });
  const fog = await createWorkByApi(page, { title: "雾港来信", genre: "现实", summary: "一封迟到的信。" });
  await archiveWorkByApi(page, fog);

  await worksPage(page);
  // The page has its own 新建作品; the top bar does not repeat it here (it does on the home page).
  await expect(page.getByRole("banner").getByRole("button", { name: "新建作品", exact: true })).toHaveCount(0);
  await expect(page.getByRole("main").getByRole("button", { name: "新建作品", exact: true })).toBeVisible();
  // The filter chip and the row label say the same word.
  await expect(page.getByRole("group", { name: "作品状态", exact: true }).getByRole("button", { name: "已暂停", exact: true })).toBeVisible();
  // No sample work in this list.
  await expect(page.getByText("灰港回声")).toHaveCount(0);
  const byUpdate = await titlesFromApi(page, "q=&sort=updated_desc");
  expect(byUpdate).toEqual(["潮声之后", "北堤旧事"]);
  await expect(rows(page)).toHaveCount(2);
  await expect(rows(page)).toHaveText([/潮声之后/, /北堤旧事/]);
  await expect(rowOf(page, "北堤旧事")).toContainText("暂停");
  await expect(page.getByText("雾港来信")).toHaveCount(0);
  // "N 部作品" counts what the list shows by default: the archived one is left out.
  await expect(page.getByText("部作品", { exact: true }).locator("xpath=..")).toHaveText(/^作品2+部作品$/);
  await shot(page, "works-list");

  // Search by title.
  const search = page.getByRole("textbox", { name: "搜索作品", exact: true });
  await search.fill("潮声");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("潮声之后");
  expect(await titlesFromApi(page, "q=%E6%BD%AE%E5%A3%B0&sort=updated_desc")).toEqual(["潮声之后"]);
  // Search by summary too.
  await search.fill("旧案");
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("北堤旧事");
  // A word nothing matches.
  await search.fill("根本没有这个词");
  await expect(page.getByText("没有符合条件的作品。换个条件试试。", { exact: true })).toBeVisible();
  await expect(rows(page)).toHaveCount(0);
  await search.fill("");
  await expect(rows(page)).toHaveCount(2);

  // Status: 未归档 hides the archived one, 已归档 shows it.
  const statuses = page.getByRole("group", { name: "作品状态", exact: true });
  await expect(statuses.getByRole("button", { name: "未归档", exact: true })).toHaveAttribute("aria-pressed", "true");
  await statuses.getByRole("button", { name: "已归档", exact: true }).click();
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("雾港来信");
  await expect(rows(page).first()).toContainText("已归档");
  expect(await titlesFromApi(page, "q=&status=archived&sort=updated_desc")).toEqual(["雾港来信"]);
  await statuses.getByRole("button", { name: "已暂停", exact: true }).click();
  await expect(rows(page)).toHaveCount(1);
  await expect(rows(page).first()).toContainText("北堤旧事");
  await statuses.getByRole("button", { name: "未归档", exact: true }).click();
  await expect(rows(page)).toHaveCount(2);
  await expect(page.getByText("雾港来信")).toHaveCount(0);

  // Order: 最近修改 ⇄ 书名.
  const sort = page.getByRole("combobox", { name: "排序", exact: true });
  await sort.selectOption({ label: "书名" });
  const byTitle = await titlesFromApi(page, "q=&sort=title_asc");
  expect(byTitle).toEqual(["北堤旧事", "潮声之后"]);
  expect(byTitle).not.toEqual(byUpdate);
  await expect(rows(page)).toHaveText([/北堤旧事/, /潮声之后/]);
  await sort.selectOption({ label: "最近修改" });
  await expect(rows(page)).toHaveText([/潮声之后/, /北堤旧事/]);
});

test("作品管理为空：没有作品时给出两个入口", async ({ page }) => {
  await registerAccount(page, "workempty");
  await worksPage(page);
  await expect(page.getByText("导入写好的稿子，或者从空白开始。", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: /导入已有作品/ })).toBeVisible();
  await expect(page.getByRole("button", { name: /从空白开始/ })).toBeVisible();
  await expect(page.getByRole("textbox", { name: "搜索作品" })).toHaveCount(0);
  await shot(page, "works-empty");
});

test("作品卡片上的入口：继续写、打开概览、追加章节", async ({ page }) => {
  await registerAccount(page, "workrow");
  const id = await createWorkByApi(page, { title: "入口测试之书" });
  const archivedId = await createWorkByApi(page, { title: "已经归档的书" });
  await archiveWorkByApi(page, archivedId);

  await worksPage(page);
  const row = rowOf(page, "入口测试之书");
  await row.getByRole("button", { name: "继续写", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/workspace$`));

  await worksPage(page);
  await rowOf(page, "入口测试之书").getByLabel("更多：入口测试之书", { exact: true }).click();
  await page.getByRole("menuitem", { name: "打开概览", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/overview$`));

  await worksPage(page);
  await rowOf(page, "入口测试之书").getByLabel("更多：入口测试之书", { exact: true }).click();
  await page.getByRole("menuitem", { name: "追加章节", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${id}/sources#append$`));
  await expect(page.getByRole("navigation", { name: "作品" }).getByRole("button", { name: "章节", exact: true })).toHaveAttribute("aria-current", "page");
  await expect(page.locator("#append")).toBeVisible();

  // An archived work is only for looking at.
  await worksPage(page);
  await page.getByRole("group", { name: "作品状态", exact: true }).getByRole("button", { name: "已归档", exact: true }).click();
  const archived = rowOf(page, "已经归档的书");
  await expect(archived.getByLabel("更多：已经归档的书")).toHaveCount(0);
  await archived.getByRole("button", { name: "查看", exact: true }).click();
  await expect(page).toHaveURL(new RegExp(`/projects/${archivedId}/overview$`));
});

test("首页「继续写」：进入最近在写的那部作品的写作页", async ({ page }) => {
  await registerAccount(page, "homecont");
  await createWorkByApi(page, { title: "先建的书" });
  const latest = await createWorkByApi(page, { title: "后建的书" });
  await page.goto("/");
  await expect(page.getByRole("heading", { level: 1, name: "继续你的故事", exact: true })).toBeVisible();
  const band = page.getByRole("button", { name: /上次停在 · 《后建的书》/ });
  await expect(band).toContainText("继续写");
  await band.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${latest}/workspace$`));
});
