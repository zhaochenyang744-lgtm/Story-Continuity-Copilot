import type { Page } from "@playwright/test";
import { api, expect, fixturePath, listWorks, pickGenre, registerAccount, shot, tempFile, test } from "./support/app";

// Chapters written for these tests; no real work is quoted.
const txtBook = [
  "第一章 退潮", "灰色的潮线退到了堤坝外面。阿棠把渔网收起来，听见远处有人敲钟。", "",
  "第二章 来信", "信封上没有署名，只有一枚被海水泡软的邮戳。", "",
  "第三章 夜航", "夜里的渡船没有点灯，船夫一句话也不说。", "",
  "第四章 回港", "天亮以前，船靠了岸，岸上的人都已经走光了。", "",
].join("\n");
const markdownBook = (chapters: number) => Array.from({ length: chapters }, (_, index) => `# 第${index + 1}章 第${index + 1}站\n\n这是第 ${index + 1} 站的开头，一句话就够了。\n`).join("\n");

const chooseFile = async (page: Page, file: string) => {
  const chooser = page.waitForEvent("filechooser");
  // Before a file is chosen the button says 选择文件; afterwards 换一个文件.
  await page.getByTestId("import-dropzone").getByRole("button", { name: /^(选择文件|换一个文件)$/ }).click();
  await (await chooser).setFiles(file);
  await expect(page.getByTestId("import-dropzone")).toContainText("已选择");
};
const expectStep = async (page: Page, step: 1 | 2 | 3) =>
  expect(page.getByRole("list", { name: "导入步骤" }).getByRole("listitem").nth(step - 1)).toHaveAttribute("aria-current", "step");
const chapterRows = (page: Page) => page.getByRole("list", { name: "分章预览" }).getByRole("listitem");
const toPreview = async (page: Page, file: string) => {
  await page.goto("/projects/import");
  await expect(page.getByRole("heading", { level: 1, name: "导入作品", exact: true })).toBeVisible();
  await expectStep(page, 1);
  await chooseFile(page, file);
  await page.getByRole("button", { name: "下一步：检查分章", exact: true }).click();
  await expectStep(page, 2);
};
const finishImport = async (page: Page, title: string, genre = "", summary = "") => {
  await page.getByRole("button", { name: "分章没问题，下一步", exact: true }).click();
  await expectStep(page, 3);
  await page.getByRole("textbox", { name: /^书名/ }).fill(title);
  if (genre) await page.getByRole("textbox", { name: "类型", exact: true }).fill(genre);
  if (summary) await page.getByRole("textbox", { name: "简介", exact: true }).fill(summary);
};
const importedWork = async (page: Page, title: string) => {
  const work = (await listWorks(page)).find((item) => item.title === title);
  expect(work, `a work called ${title}`).toBeTruthy();
  const project = await api(page).get(`/projects/${work!.id}`);
  const chapters = (await api(page).get(`/projects/${work!.id}/chapters?include=excerpt`)).chapters as { number: number; title: string; source_spans?: { text_excerpt: string }[] }[];
  return { id: work!.id, project, chapters };
};

test("新建作品：书名必填，选「其他」出现类型输入框，创建后后端数据对得上", async ({ page }) => {
  await registerAccount(page, "newwork");
  await page.goto("/projects/new");
  await expect(page.getByRole("heading", { level: 1, name: "新建作品", exact: true })).toBeVisible();

  // Without a title nothing is sent.
  const created: string[] = [];
  page.on("request", (request) => { if (request.method() === "POST" && new URL(request.url()).pathname === "/api/projects") created.push(request.url()); });
  const title = page.getByRole("textbox", { name: /^书名/ });
  await page.getByRole("button", { name: "创建并开始写第一章", exact: true }).click();
  await expect.poll(() => title.evaluate((input: HTMLInputElement) => input.validity.valueMissing)).toBe(true);
  await expect(page).toHaveURL(/\/projects\/new$/);
  expect(created).toEqual([]);
  expect(await listWorks(page)).toEqual([]);

  // 其他 opens a field for the type's own name; the other types do not.
  await expect(page.getByRole("textbox", { name: "其他类型", exact: true })).toHaveCount(0);
  await pickGenre(page, "悬疑");
  await expect(page.getByRole("textbox", { name: "其他类型", exact: true })).toHaveCount(0);
  await pickGenre(page, "其他");
  await expect(page.getByRole("textbox", { name: "其他类型", exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "其他类型", exact: true }).fill("海洋志怪");
  await title.fill("潮汐之后的信");
  const summary = "一封迟到十年的信，把退休的引航员叫回了雾港。";
  await page.getByRole("textbox", { name: /^简介/ }).fill(summary);
  await expect(page.getByText(`${Array.from(summary).length} / 500`, { exact: true })).toBeVisible();
  await shot(page, "new-work");

  await page.getByRole("button", { name: "创建并开始写第一章", exact: true }).click();
  // The page for the first chapter opens.
  await expect(page).toHaveURL(/\/projects\/[^/]+\/workspace$/);
  const id = new URL(page.url()).pathname.split("/")[2];
  await expect(page.getByRole("navigation", { name: "作品" }).getByRole("button", { name: "写作", exact: true })).toHaveAttribute("aria-current", "page");
  const work = await api(page).get(`/projects/${id}`);
  expect(work.title).toBe("潮汐之后的信");
  expect(work.genre).toBe("海洋志怪");
  expect(work.summary).toBe(summary);
  expect(work.status).toBe("active");
  expect(work.current_draft).toBeTruthy();
  expect((await listWorks(page)).map((item) => item.title)).toEqual(["潮汐之后的信"]);
});

test("新建时取消：回到作品管理，作品数不变", async ({ page }) => {
  await registerAccount(page, "newcancel");
  await page.goto("/projects/new");
  await page.getByRole("textbox", { name: /^书名/ }).fill("不会被创建的书");
  await pickGenre(page, "科幻");
  await page.getByRole("button", { name: "取消", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  expect(await listWorks(page)).toEqual([]);
  await expect(page.getByText("不会被创建的书")).toHaveCount(0);
});

test("导入 Markdown：选文件、检查分章、填书名，作品和章节落到后端", async ({ page }) => {
  await registerAccount(page, "importmd");
  await page.goto("/projects/import");
  await expect(page.getByRole("heading", { level: 1, name: "导入作品", exact: true })).toBeVisible();
  await expectStep(page, 1);
  // Nothing is chosen yet: the main button only opens the file picker.
  await expect(page.getByRole("button", { name: "选择文件" })).toHaveCount(2);
  await shot(page, "import-step1");
  await chooseFile(page, fixturePath("stage9-mist-harbor.md"));
  await expect(page.getByTestId("import-dropzone")).toContainText("stage9-mist-harbor.md");
  const previewed = page.waitForResponse((response) => response.url().endsWith("/api/imports/preview") && response.ok());
  await page.getByRole("button", { name: "下一步：检查分章", exact: true }).click();
  const preview = (await (await previewed).json()).data;
  await expectStep(page, 2);

  // The preview: three chapters, each starting where the file says.
  await expect(chapterRows(page)).toHaveCount(3);
  await expect(chapterRows(page)).toHaveText([/雾港初章[\s\S]*钟声响起后，所有船只必须停泊在雾港。/, /北堤钥匙[\s\S]*林默一直保管银钥匙。/, /清晨门扉[\s\S]*林默知道北堤门只在清晨开启。/]);
  await expect(page.getByText("按 Markdown 标题分章", { exact: false })).toBeVisible();
  await expect(page.getByText("原文全部保留，顺序不变，没有重复或遗漏。")).toBeVisible();
  expect(preview.detected.chapter_count).toBe(3);
  // Only 3 chapters: no pager.
  await expect(page.getByRole("navigation", { name: "分章预览翻页" })).toHaveCount(0);
  // The preview creates nothing yet.
  expect(await listWorks(page)).toEqual([]);
  await shot(page, "import-step2");

  await finishImport(page, "雾港旧事（导入）", "悬疑", "用来试导入的小稿。");
  await expect(page.getByText("将把 stage9-mist-harbor.md 的 3 章创建为一部新作品。", { exact: true })).toBeVisible();
  await shot(page, "import-step3");
  await page.getByRole("button", { name: "导入并创建作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);

  const { project, chapters } = await importedWork(page, "雾港旧事（导入）");
  expect(project.data_origin).toBe("user_import");
  expect(project.genre).toBe("悬疑");
  expect(project.summary).toBe("用来试导入的小稿。");
  expect(chapters.map((chapter) => chapter.title)).toEqual(["雾港初章", "北堤钥匙", "清晨门扉"]);
  expect(chapters.map((chapter) => chapter.number)).toEqual([1, 2, 3]);
  expect(JSON.stringify(chapters[0])).toContain("钟声响起后，所有船只必须停泊在雾港。");
  expect(await listWorks(page)).toHaveLength(1);
});

test("导入 Markdown：章数多时分章预览可以翻页", async ({ page }) => {
  await registerAccount(page, "importpage");
  await toPreview(page, await tempFile("ten-stops.md", markdownBook(10)));
  const pager = page.getByRole("navigation", { name: "分章预览翻页" });
  await expect(chapterRows(page)).toHaveCount(8);
  await expect(pager).toContainText("1 / 2");
  await expect(pager.getByRole("button", { name: "上一页", exact: true })).toBeDisabled();
  await pager.getByRole("button", { name: "下一页", exact: true }).click();
  await expect(pager).toContainText("2 / 2");
  await expect(chapterRows(page)).toHaveCount(2);
  await expect(chapterRows(page)).toHaveText([/第9站[\s\S]*这是第 9 站的开头/, /第10站[\s\S]*这是第 10 站的开头/]);
  await expect(pager.getByRole("button", { name: "下一页", exact: true })).toBeDisabled();
  await pager.getByRole("button", { name: "上一页", exact: true }).click();
  await expect(chapterRows(page).first()).toContainText("第1站");

  await finishImport(page, "十个站的小说");
  await page.getByRole("button", { name: "导入并创建作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const { chapters } = await importedWork(page, "十个站的小说");
  expect(chapters).toHaveLength(10);
});

test("导入 TXT：按章节标记分章，章数对得上", async ({ page }) => {
  await registerAccount(page, "importtxt");
  await toPreview(page, await tempFile("tide-letters.txt", txtBook));
  await expect(page.getByText("按章节标记分章", { exact: false })).toBeVisible();
  await expect(chapterRows(page)).toHaveCount(4);
  await expect(chapterRows(page)).toHaveText([/退潮/, /来信/, /夜航/, /回港/]);
  // The file name is the suggested title.
  await page.getByRole("button", { name: "分章没问题，下一步", exact: true }).click();
  await expectStep(page, 3);
  await expect(page.getByRole("textbox", { name: /^书名/ })).toHaveValue("tide-letters");
  await page.getByRole("textbox", { name: /^书名/ }).fill("退潮来信");
  await page.getByRole("button", { name: "导入并创建作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const { project, chapters } = await importedWork(page, "退潮来信");
  expect(project.data_origin).toBe("user_import");
  expect(chapters.map((chapter) => chapter.title)).toEqual(["退潮", "来信", "夜航", "回港"]);
  expect(JSON.stringify(chapters[0])).toContain("灰色的潮线退到了堤坝外面");
});

test("取消导入：作品数不变，已取消的预览不能再提交，重新导入能完成", async ({ page }) => {
  await registerAccount(page, "importcancel");
  const file = fixturePath("stage9-mist-harbor.md");
  await page.goto("/projects/import");
  await chooseFile(page, file);
  const previewed = page.waitForResponse((response) => response.url().endsWith("/api/imports/preview") && response.ok());
  await page.getByRole("button", { name: "下一步：检查分章", exact: true }).click();
  const preview = (await (await previewed).json()).data;
  await expectStep(page, 2);
  await expect(chapterRows(page)).toHaveCount(3);

  await page.getByRole("button", { name: "取消导入", exact: true }).click();
  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole("heading", { level: 1, name: "作品管理", exact: true })).toBeVisible();
  expect(await listWorks(page)).toEqual([]);
  // The cancelled preview is gone for good.
  const late = await api(page).raw("POST", `/imports/${preview.import_id}/commit`, {
    confirm: true, title: "迟到的提交", genre: "", summary: "", chapter_preview_ids: preview.detected.chapters.map((chapter: { preview_id: string }) => chapter.preview_id),
  });
  expect(late.status).toBeGreaterThanOrEqual(400);
  expect(await listWorks(page)).toEqual([]);

  // A fresh import still works.
  await toPreview(page, file);
  await expect(chapterRows(page)).toHaveCount(3);
  await finishImport(page, "取消之后重新导入");
  await page.getByRole("button", { name: "导入并创建作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  expect((await listWorks(page)).map((work) => work.title)).toEqual(["取消之后重新导入"]);
});

test("不支持的文件：错误留在第一步，不会进入预览", async ({ page }) => {
  await registerAccount(page, "importbad");
  await page.goto("/projects/import");
  const send = () => page.getByRole("button", { name: "下一步：检查分章", exact: true }).click();
  // The page's own message box (the framework's route announcer is also an alert, and is empty).
  const alert = (text: string) => page.getByRole("alert").filter({ has: page.getByRole("button", { name: "关闭提示", exact: true }) }).filter({ hasText: text });

  // A format the importer does not read.
  await chooseFile(page, await tempFile("notes.pdf", "%PDF-1.4 not a book"));
  await send();
  await expect(alert("文件格式不支持：请使用 Word（.docx），或 UTF-8 编码的 .md / .txt。")).toBeVisible();
  await expectStep(page, 1);
  await expect(page.getByRole("list", { name: "分章预览" })).toHaveCount(0);
  await expect(page.getByTestId("import-dropzone")).toContainText("notes.pdf");

  // An empty file with a good name.
  await chooseFile(page, await tempFile("empty.txt", ""));
  await send();
  await expect(alert("")).toBeVisible();
  await expectStep(page, 1);
  await expect(page.getByRole("list", { name: "分章预览" })).toHaveCount(0);
  expect(await listWorks(page)).toEqual([]);
});
