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
  // Before a file is chosen the one button says 选择文件; afterwards the drop zone's says 换一个文件.
  await page.getByRole("button", { name: /^(选择文件|换一个文件)$/ }).click();
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
  // Nothing is chosen yet: one focusable 选择文件 button (it only opens the picker). The drop zone is no second
  // button of that name and has nothing to focus; its own words are left out for screen readers.
  await expect(page.getByRole("button", { name: "选择文件" })).toHaveCount(1);
  const zone = page.getByTestId("import-dropzone");
  await expect(zone.getByRole("button")).toHaveCount(0);
  await expect(zone.locator("[tabindex], a, button, input")).toHaveCount(0);
  // Clicking the zone opens the picker too.
  const picker = page.waitForEvent("filechooser");
  await zone.click();
  await picker;
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
  await expect(alert("文件是空的，请换一个文件。")).toBeVisible();
  await expectStep(page, 1);
  await expect(page.getByRole("list", { name: "分章预览" })).toHaveCount(0);
  expect(await listWorks(page)).toEqual([]);
});

// Stored ZIP fixture generated with Node buffers; no additional package is needed.
function mixedHeadingDocx(): Buffer {
  const ns = 'xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"';
  const files: Record<string, string> = {
    "[Content_Types].xml": '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Default Extension="xml" ContentType="application/xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/><Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/></Types>',
    "_rels/.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>',
    "word/_rels/document.xml.rels": '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/></Relationships>',
    "word/styles.xml": '<w:styles ' + ns + '><w:style w:type="paragraph" w:styleId="1"><w:name w:val="heading 1"/></w:style></w:styles>',
    "word/document.xml": '<w:document ' + ns + '><w:body>' + ["第一章 雨夜", "第二章 回声", "第三章 空舱"].map((title, i) => '<w:p>' + (i < 2 ? '<w:pPr><w:pStyle w:val="1"/></w:pPr>' : '') + '<w:r>' + (i === 2 ? '<w:rPr><w:b/></w:rPr>' : '') + '<w:t>' + title + '</w:t></w:r></w:p><w:p><w:r><w:t>值班员走进第' + (i + 1) + '间船舱，记下窗边的水迹。</w:t></w:r></w:p>').join("") + '</w:body></w:document>',
  };
  const local: Buffer[] = [], central: Buffer[] = [];
  let offset = 0;
  for (const [name, value] of Object.entries(files)) {
    const filename = Buffer.from(name), data = Buffer.from(value);
    let crc = 0xffffffff;
    for (const byte of data) {
      crc ^= byte;
      for (let bit = 0; bit < 8; bit++) crc = (crc >>> 1) ^ ((crc & 1) ? 0xedb88320 : 0);
    }
    crc = (crc ^ 0xffffffff) >>> 0;
    const header = Buffer.alloc(30), entry = Buffer.alloc(46);
    header.writeUInt32LE(0x04034b50); header.writeUInt16LE(20, 4);
    header.writeUInt32LE(crc, 14); header.writeUInt32LE(data.length, 18); header.writeUInt32LE(data.length, 22); header.writeUInt16LE(filename.length, 26);
    entry.writeUInt32LE(0x02014b50); entry.writeUInt16LE(20, 4); entry.writeUInt16LE(20, 6);
    entry.writeUInt32LE(crc, 16); entry.writeUInt32LE(data.length, 20); entry.writeUInt32LE(data.length, 24); entry.writeUInt16LE(filename.length, 28); entry.writeUInt32LE(offset, 42);
    local.push(header, filename, data); central.push(entry, filename);
    offset += header.length + filename.length + data.length;
  }
  const directory = Buffer.concat(central), end = Buffer.alloc(22);
  end.writeUInt32LE(0x06054b50); end.writeUInt16LE(central.length / 2, 8); end.writeUInt16LE(central.length / 2, 10);
  end.writeUInt32LE(directory.length, 12); end.writeUInt32LE(offset, 16);
  return Buffer.concat([...local, directory, end]);
}

test("13 R Word 混用标题样式和加粗正文标题：预览和导入均为三章", async ({ page }) => {
  await registerAccount(page, "wordmixed");
  await toPreview(page, await tempFile("mixed-headings.docx", mixedHeadingDocx()));
  await expect(chapterRows(page)).toHaveCount(3);
  await expect(chapterRows(page)).toHaveText([/第一章 雨夜/, /第二章 回声/, /第三章 空舱/]);
  await shot(page, "13-R-word-preview-day", false);
  await finishImport(page, "混合样式的航海笔记");
  await page.getByRole("button", { name: "导入并创建作品", exact: true }).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const { chapters } = await importedWork(page, "混合样式的航海笔记");
  expect(chapters.map(c => c.title)).toEqual(["第一章 雨夜", "第二章 回声", "第三章 空舱"]);
  for (const [i, chapter] of chapters.entries()) expect(JSON.stringify(chapter)).toContain("第" + (i + 1) + "间船舱");
});
