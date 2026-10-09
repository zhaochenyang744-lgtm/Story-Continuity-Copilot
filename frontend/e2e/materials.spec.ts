import { api, expect, openTab, registerAccount, setDraftBody, test } from "./support/app";
import { button, draft, failDraftSaves, saveBody } from "./support/writing";
import { cardWith, evidence, importBook, initialize, memories, pair, sample, startAnalysis, view } from "./support/pages";

test("08 资料五个视图：网址和刷新保持", async ({ page }) => {
  await sample(page, "memory");
  await pair(page, "materials-facts");
  for (const [label, key] of [["人物", "people"], ["设定", "settings"], ["伏笔", "threads"], ["问一问", "ask"], ["事实", "facts"]]) {
    await view(page, label, key);
    await page.reload();
    await expect(page.getByRole("navigation", { name: "资料分类", exact: true }).getByRole("button", { name: new RegExp(`^${label}(?:\\s|$)`) })).toHaveAttribute("aria-current", "page");
    expect(new URL(page.url()).searchParams.get("view")).toBe(key === "facts" ? null : key);
  }
});

test("08 事实筛选搜索：接口条数和出处焦点", async ({ page }) => {
  const id = await sample(page, "memory"), records = await memories(page, id);
  const list = page.getByRole("list", { name: "事实列表", exact: true });
  await expect(list.getByRole("listitem")).toHaveCount(records.length);
  const filters = page.getByRole("group", { name: "事实类型", exact: true });
  await filters.getByRole("button", { name: /^规则/ }).click();
  const rules = records.filter(r => r.memory_type === "static_canon");
  await expect(list.getByRole("listitem")).toHaveCount(rules.length);
  const keyword = rules[0].subject;
  await page.getByRole("textbox", { name: "搜索事实", exact: true }).fill(keyword);
  const matches = rules.filter(r => `${r.subject} ${r.value}`.includes(keyword));
  await expect(list.getByRole("listitem")).toHaveCount(matches.length);
  await page.getByRole("textbox", { name: "搜索事实", exact: true }).fill("不存在的测试词xyz08");
  await expect(page.getByText("没有符合条件的事实。", { exact: true })).toBeVisible();
  await page.getByRole("textbox", { name: "搜索事实", exact: true }).fill(keyword);
  const source = list.getByRole("button", { name: `看 ${matches[0].subject} 出自哪一章`, exact: true }).first();
  await source.click();
  const drawer = page.getByRole("dialog", { name: new RegExp(`^第 ${matches[0].source.chapter_number} 章 ·`) });
  await expect(drawer).toBeVisible();
  await expect(drawer).toContainText(matches[0].source.excerpt);
  await drawer.getByRole("button", { name: "关闭", exact: true }).click();
  await expect(source).toBeFocused();
});

test("08 人物别名：添加改名归档与刷新", async ({ page }) => {
  const id = await sample(page, "memory");
  await view(page, "人物", "people");
  const chars = (await api(page).get(`/projects/${id}/characters`)).characters;
  let selected = chars[0];
  for (const c of chars) {
    const aliases = await api(page).get(`/projects/${id}/characters/${c.id}/aliases?include_archived=true`);
    if (aliases.aliases.some((a: any) => a.status === "active")) { selected = c; break; }
  }
  const endpoint = `/projects/${id}/characters/${selected.id}/aliases?include_archived=true`;
  const aliases = (await api(page).get(endpoint)).aliases;
  expect(aliases.filter((a: any) => a.status === "active").length).toBeGreaterThan(0);
  const card = cardWith(page, selected.name);
  for (const a of aliases.filter((a: any) => a.status === "active")) await expect(card).toContainText(a.alias);
  await card.getByRole("button", { name: /^相关事实 / }).click();
  await card.getByRole("textbox", { name: "新别名", exact: true }).fill("测试引航员");
  await card.getByRole("button", { name: "添加", exact: true }).click();
  await expect(card.getByText("别名记下了。", { exact: true })).toBeVisible();
  const added = (await api(page).get(endpoint)).aliases.find((a: any) => a.alias === "测试引航员");
  expect(added.status).toBe("active");
  await page.reload();
  await expect(card).toContainText("测试引航员");
  await card.getByRole("button", { name: /^相关事实 / }).click();
  const row = card.getByRole("listitem").filter({ has: page.getByRole("textbox", { name: "别名 测试引航员", exact: true }) });
  await row.getByRole("textbox").fill("测试守灯人");
  await row.getByRole("button", { name: "保存", exact: true }).click();
  await expect(card.getByText("别名改好了。", { exact: true })).toBeVisible();
  expect((await api(page).get(endpoint)).aliases.find((a: any) => a.id === added.id).alias).toBe("测试守灯人");
  const updated = card.getByRole("listitem").filter({ has: page.getByRole("textbox", { name: "别名 测试守灯人", exact: true }) });
  await updated.getByRole("button", { name: "归档", exact: true }).click();
  await expect(card.getByText("别名已归档，记录仍保留。", { exact: true })).toBeVisible();
  expect((await api(page).get(endpoint)).aliases.find((a: any) => a.id === added.id).status).toBe("archived");
  await pair(page, "materials-people");
});

test("08 改动影响：分析附依据而不改人物", async ({ page }, info) => {
  const id = await sample(page, "memory");
  const before = await api(page).get(`/projects/${id}/characters`);
  await view(page, "人物", "people");
  const c = before.characters[0], card = cardWith(page, c.name);
  await card.getByRole("button", { name: /^相关事实 / }).click();
  await card.getByLabel("打算怎么改", { exact: true }).fill(`把${c.name}的身份改成港务调查员。`);
  const result = await startAnalysis(page, id, () => card.getByRole("button", { name: "看会影响什么", exact: true }).click());
  await evidence(info, "change-impact", result);
  expect(result.status, JSON.stringify(result)).toBe("completed");
  expect(result.analysis_type).toBe("change_impact");
  await expect(card).toContainText("改动影响 · 只分析，不修改");
  await expect(card).toContainText(result.analysis.summary);
  expect(result.analysis.items.length).toBeGreaterThan(0);
  for (const item of result.analysis.items) {
    expect(item.evidence.length).toBeGreaterThan(0);
    await expect(card).toContainText(item.impact);
  }
  expect(await api(page).get(`/projects/${id}/characters`)).toEqual(before);
});

test("08 自定义设定分类：分配改名删除保留设定", async ({ page }) => {
  const id = await sample(page, "memory"), endpoint = `/projects/${id}/setting-categories`;
  const original = await api(page).get(`/projects/${id}/world`);
  const entry = original.entries[0];
  await view(page, "设定", "settings");
  await button(page, "管理分类").click();
  const manager = page.getByRole("region", { name: "管理分类", exact: true });
  await manager.getByLabel("新分类名称", { exact: true }).fill("功法");
  await manager.getByRole("button", { name: "新建", exact: true }).click();
  await expect(manager.getByLabel("功法 的名称", { exact: true })).toBeVisible();
  const category = (await api(page).get(endpoint)).categories.find((c: any) => c.name === "功法");
  expect(category.builtin).toBe(false);
  await page.getByRole("button", { name: new RegExp(`^${entry.name}`) }).click();
  await page.getByRole("combobox", { name: "放在", exact: true }).selectOption(category.key);
  await expect.poll(async () => (await api(page).get(endpoint)).membership[entry.id]).toBe(category.key);
  const builtin = (await api(page).get(endpoint)).categories.find((c: any) => c.builtin && c.key !== "other");
  const builtRow = manager.getByRole("listitem").filter({ has: page.getByLabel(`${builtin.name} 的名称`, { exact: true }) });
  await builtRow.getByRole("textbox").fill("测试分类名");
  await builtRow.getByRole("button", { name: "改名", exact: true }).click();
  await expect.poll(async () => (await api(page).get(endpoint)).categories.find((c: any) => c.key === builtin.key).name).toBe("测试分类名");
  await manager.getByRole("listitem").filter({ has: page.getByLabel("功法 的名称", { exact: true }) }).getByRole("button", { name: "删除", exact: true }).click();
  await expect.poll(async () => (await api(page).get(endpoint)).categories.some((c: any) => c.key === category.key)).toBe(false);
  expect((await api(page).get(endpoint)).membership[entry.id]).toBe(entry.entry_type);
  expect(await api(page).get(`/projects/${id}/world`)).toEqual(original);
  await button(page, "完成").click();
  await pair(page, "materials-settings");
});

test("08 伏笔：手动记录回收与扫描逐条决定", async ({ page }, info) => {
  const id = await sample(page, "workspace");
  await saveBody(page, id, "温岚把黄铜罗盘放在桌上。北门雾钟响了，潮汐表上仍有一个缺口。");
  await openTab(page, id, "memory");
  await view(page, "伏笔", "threads");
  const endpoint = `/projects/${id}/foreshadows?include_archived=true`;
  const before = (await api(page).get(endpoint)).records;
  await button(page, "记一条伏笔").click();
  await page.getByRole("textbox", { name: "标题", exact: true }).fill("测试灯塔的记号");
  await page.getByRole("textbox", { name: "说明", exact: true }).fill("值班员在门边留下三个蓝点。");
  await page.getByRole("combobox", { name: "状态", exact: true }).selectOption("planted");
  const chapters = (await api(page).get(`/projects/${id}/chapters?include=excerpt`)).chapters;
  await page.getByRole("combobox", { name: "埋在", exact: true }).selectOption(`${chapters[0].id}|`);
  await button(page, "记下").click();
  await expect(page.getByText("伏笔记下了。", { exact: true })).toBeVisible();
  const manual = (await api(page).get(endpoint)).records.find((r: any) => r.title === "测试灯塔的记号");
  expect(manual).toMatchObject({ description: "值班员在门边留下三个蓝点。", status: "planted", planted: { chapter_number: 1 } });
  const row = page.getByRole("listitem").filter({ has: page.getByText(manual.title, { exact: true }) });
  await row.getByRole("button", { name: "标为已回收", exact: true }).click();
  await page.getByRole("combobox", { name: "回收于", exact: true }).selectOption(`${chapters[1].id}|`);
  await button(page, "保存").click();
  await expect(row).toHaveCount(0);
  expect((await api(page).get(endpoint)).records.find((r: any) => r.id === manual.id).status).toBe("resolved");
  const result = await startAnalysis(page, id, () => button(page, "从正文里找伏笔").click());
  await evidence(info, "foreshadow-scan", result);
  expect(result.status, JSON.stringify(result)).toBe("completed");
  expect(result.analysis.candidates).toHaveLength(2);
  const candidates = page.getByRole("region", { name: "扫描找到的伏笔", exact: true });
  const [accepted, rejected] = result.analysis.candidates;
  await candidates.getByRole("article").filter({ hasText: accepted.title }).getByRole("button", { name: "记下", exact: true }).click();
  await expect(page.getByText("记下了。", { exact: true })).toBeVisible();
  await candidates.getByRole("article").filter({ hasText: rejected.title }).getByRole("button", { name: "不记", exact: true }).click();
  await expect(candidates).toHaveCount(0);
  const after = (await api(page).get(endpoint)).records;
  expect(after).toHaveLength(before.length + 2);
  expect(after.some((r: any) => r.title === accepted.title)).toBe(true);
  expect(after.filter((r: any) => !before.some((b: any) => b.id === r.id)).some((r: any) => r.title === rejected.title)).toBe(false);
  const reviewed = await api(page).get(`/projects/${id}/analyses/${result.run_id}`);
  expect(reviewed.analysis.candidates.map((c: any) => c.decision_status)).toEqual(["accepted", "rejected"]);
  await pair(page, "materials-foreshadow");
});

test("08 问一问：回答依据与未保存提示", async ({ page }, info) => {
  const id = await sample(page, "memory");
  await view(page, "问一问", "ask");
  await page.getByLabel("问一个关于正文的问题", { exact: true }).fill("罗盘现在在哪里？");
  const result = await startAnalysis(page, id, () => button(page, "问").click());
  await evidence(info, "story-qa", result);
  expect(result.status, JSON.stringify(result)).toBe("completed");
  expect(result.analysis_type).toBe("story_qa");
  await expect(page.getByText(result.analysis.answer, { exact: true })).toBeVisible();
  expect(result.analysis.findings.length).toBeGreaterThan(0);
  for (const item of result.analysis.findings) for (const source of item.evidence) await expect(page.getByText(source.excerpt, { exact: true })).toBeVisible();
  await expect(page.getByText(/^只根据已保存的内容回答/)).toBeVisible();
  await pair(page, "materials-ask");
  await openTab(page, id, "workspace");
  const saved = await draft(page, id);
  const unblock = await failDraftSaves(page);
  await setDraftBody(page, `${saved.body}\n测试尚未保存的补充。`);
  await page.getByRole("navigation", { name: "作品", exact: true }).getByRole("button", { name: "资料", exact: true }).click();
  await view(page, "问一问", "ask");
  // Suggested questions exercise the dirty guard; the main submit is disabled while dirty.
  const chars = (await api(page).get(`/projects/${id}/characters`)).characters;
  await button(page, `${chars[0].name}现在在哪里？`).click();
  await expect(page.getByText("先保存草稿；问一问只看已保存的版本。", { exact: true })).toBeVisible();
  expect((await draft(page, id)).body).toBe(saved.body);
  expect((await api(page).get(`/projects/${id}/analyses?analysis_type=story_qa&limit=20`)).runs).toHaveLength(1);
  await unblock();
});

test("08 导入整理事实：三种决定建立第一版", async ({ page }) => {
  await registerAccount(page, "init08");
  const id = await importBook(page);
  expect((await memories(page, id))).toHaveLength(0);
  await initialize(page, id, true);
});
