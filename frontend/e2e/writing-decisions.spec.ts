import { api, beginCheck, button, countDraftWrites, decide, draft, expect, finding, findings, finishCheck, readDraftBody, reloadAcceptingUnload, run, saveBody, selectIssue, setDraftBody, setup, shot, test } from "./support/writing";

test("采用改法（示例结果）：正文与决定只保存一次", async ({ page }) => {
  const id = await setup(page), before = await draft(page, id), result = await run(page, id);
  const issue = result.issues.find((i: any) => i.suggested_revision);
  const writes = countDraftWrites(page);
  await selectIssue(page, issue);
  await button(page, "采用改法").click();
  await expect(button(page, "保存修改")).toBeVisible();
  expect(await readDraftBody(page)).toBe(before.body.replace(issue.suggested_revision.before, issue.suggested_revision.after));
  expect((await draft(page, id)).revision).toBe(before.revision);
  await shot(page, "writing-after-apply");
  await button(page, "保存修改").click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("accept_and_edit");
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await draft(page, id)).body).toContain(issue.suggested_revision.after);
  expect(writes).toHaveLength(1);
});

test("采用改法（新检查）：E2E_SUGGEST 合约与落库", async ({ page }) => {
  const id = await setup(page);
  const memories = (await api(page).get(`/projects/${id}/memory`)).records;
  expect(memories.some((m: any) => m.subject.includes("黄铜罗盘") && m.value.includes("温岚"))).toBe(true);
  await saveBody(page, id, "苏岑拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST。");
  const result = await finishCheck(page, id, await beginCheck(page, id));
  const issue = result.issues.find((i: any) => i.claim_text.includes("E2E_SUGGEST"));
  expect(issue).toMatchObject({ review_contract_version: "trustworthy_review_v1", nature: "possible_conflict", evidence_status: "sufficient" });
  expect(issue.suggested_revision.after).toContain("E2E_APPLIED");
  const before = await draft(page, id), writes = countDraftWrites(page);
  await selectIssue(page, issue);
  await expect(button(page, "采用改法")).toBeEnabled();
  await button(page, "采用改法").click();
  await button(page, "保存修改").click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("accept_and_edit");
  const after = await draft(page, id);
  expect(after.revision).toBe(before.revision + 1);
  expect(after.body).toContain("E2E_APPLIED");
  expect(after.body).not.toContain("E2E_SUGGEST");
  expect(writes).toHaveLength(1);
});

test("是有意的、不是问题：两种决定刷新保留", async ({ page }) => {
  const id = await setup(page), result = await run(page, id);
  const possible = result.issues.find((i: any) => i.nature === "possible_conflict");
  const conflict = result.issues.find((i: any) => i.nature === "confirmed_conflict");
  await decide(page, id, possible, "是有意的", "keep_intentional");
  await expect(page.getByRole("status").filter({ hasText: "记下了：保留原意" })).toBeVisible();
  await decide(page, id, conflict, "不是问题", "false_positive");
  await expect(page.getByRole("status").filter({ hasText: "记下了：这一条不是问题" })).toBeVisible();
  await page.reload();
  for (const issue of [possible, conflict]) await expect(finding(page, issue.id)).toContainText("已处理");
  expect((await run(page, id)).issues.filter((i: any) => i.decision)).toHaveLength(2);
});

test("标为待修改：可以取消、刷新保留且不算决定", async ({ page }) => {
  const id = await setup(page), issue = (await run(page, id)).issues[0];
  await selectIssue(page, issue);
  await button(page, "标为待修改").click();
  await expect(button(page, "取消待修改")).toBeVisible();
  await expect(finding(page, issue.id)).toContainText("待修改");
  let stored = (await run(page, id)).issues.find((i: any) => i.id === issue.id);
  expect(stored.to_revise).toBe(true); expect(stored.decision).toBeFalsy();
  await page.reload();
  await expect(finding(page, issue.id)).toContainText("待修改");
  await selectIssue(page, issue);
  await expect(button(page, "不是问题")).toBeEnabled();
  await button(page, "取消待修改").click();
  await expect(button(page, "标为待修改")).toBeVisible();
  stored = (await run(page, id)).issues.find((i: any) => i.id === issue.id);
  expect(stored.to_revise).toBe(false);
  await decide(page, id, issue, "不是问题", "false_positive");
});

test("证据不足的那条：只有待修改操作", async ({ page }) => {
  const id = await setup(page), issue = (await run(page, id)).issues.find((i: any) => i.nature === "insufficient_evidence");
  await selectIssue(page, issue);
  await expect(button(page, "标为待修改")).toBeEnabled();
  for (const name of ["是有意的", "不是问题", "采用改法", "改正文"]) await expect(button(page, name)).toHaveCount(0);
});

test("改正文：编辑焦点与受控保存", async ({ page }) => {
  const id = await setup(page), before = await draft(page, id);
  const issue = (await run(page, id)).issues.find((i: any) => i.nature === "confirmed_conflict"), writes = countDraftWrites(page);
  await selectIssue(page, issue);
  await button(page, "改正文").click();
  await expect(page.getByRole("textbox", { name: "草稿正文", exact: true })).toBeFocused();
  await expect(page.getByText("正在按选中的那一条改正文。保存时会一并记下你的处理。", { exact: true })).toBeVisible();
  const changed = before.body.replace(issue.claim_text, "温岚独自保管着黄铜罗盘。");
  await setDraftBody(page, changed);
  await button(page, "保存修改").click();
  await expect.poll(async () => (await run(page, id)).issues.find((i: any) => i.id === issue.id).decision?.decision).toBe("accept_and_edit");
  expect(await draft(page, id)).toMatchObject({ body: changed, revision: before.revision + 1 });
  expect(writes).toHaveLength(1);
});

async function pendingDecision(page: import("@playwright/test").Page, reload: boolean) {
  const id = await setup(page), before = await draft(page, id);
  const issue = (await run(page, id)).issues.find((i: any) => i.suggested_revision), writes = countDraftWrites(page);
  const pattern = "**/api/projects/*/issues/*/decision";
  let attempts = 0;
  await page.route(pattern, async route => { attempts++; await route.abort("failed"); });
  await selectIssue(page, issue);
  await button(page, "采用改法").click();
  await button(page, "保存修改").click();
  await expect(button(page, "重试记录决定")).toBeVisible();
  expect(attempts).toBe(1);
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).decision).toBeFalsy();
  if (reload) await reloadAcceptingUnload(page);
  await expect(page.getByText(/正文已经保存，编辑暂时锁定/)).toBeVisible();
  if (!reload) await shot(page, "writing-pending-decision");
  await page.unroute(pattern);
  await button(page, "重试记录决定").click();
  await expect.poll(async () => (await run(page, id)).issues.filter((i: any) => i.decision)).toHaveLength(1);
  expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).decision.decision).toBe("accept_and_edit");
  expect((await draft(page, id)).revision).toBe(before.revision + 1);
  expect(writes).toHaveLength(1);
}
test("正文存上了、决定没记下：只补记决定", async ({ page }) => { await pendingDecision(page, false); });
test("待补记的决定经得起刷新", async ({ page }) => { await pendingDecision(page, true); });

test("全部处理完，审阅事实变化", async ({ page }) => {
  const id = await setup(page), result = await run(page, id), before = await api(page).get(`/projects/${id}`);
  // Only the sample's state update comes with a proposed fact change.
  expect(result.issues.filter((i: any) => i.has_memory_proposal).map((i: any) => i.nature)).toEqual(["state_change"]);
  for (const issue of result.issues) {
    await selectIssue(page, issue);
    if (issue.nature === "insufficient_evidence") {
      await button(page, "标为待修改").click();
      expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).to_revise).toBe(true);
    } else await decide(page, id, issue, issue.nature === "state_change" ? "保留这个变化" : "是有意的", "keep_intentional");
  }
  await expect(findings(page)).toContainText("都处理完了。最后确认哪些事实有变化，再记进资料。");
  await expect(findings(page).getByText("这次没有要记进资料的变化。", { exact: true })).toHaveCount(0);
  const response = page.waitForResponse(r => r.request().method() === "POST" && r.url().endsWith("/memory/change-sets"));
  await button(page, "审阅事实变化").click();
  const res = await response;
  expect(res.ok(), await res.text()).toBe(true);
  const changes = (await res.json()).data.change_set;
  expect(changes.items).toHaveLength(1);
  expect(changes.items[0]).toMatchObject({ operation: "replace", after: { subject: "黄铜罗盘", value: "放在档案室的桌上" } });
  const form = page.getByRole("form", { name: "审阅事实变化", exact: true });
  await expect(form).toContainText("截至第10章末仍握在温岚手中");
  await expect(form).toContainText("放在档案室的桌上");
  await expect(form.getByRole("radio", { name: "记下", exact: true })).toBeChecked();
  await form.scrollIntoViewIfNeeded();
  await shot(page, "writing-fact-review", false);
  await button(page, "确认并更新资料").click();
  await expect.poll(async () => (await api(page).get(`/projects/${id}`)).current_memory_version).toBe(before.current_memory_version + 1);
  const records = (await api(page).get(`/projects/${id}/memory`)).records;
  expect(records.some((m: any) => m.subject === "黄铜罗盘" && m.predicate === "holder_at_ch10_end" && m.value === "放在档案室的桌上")).toBe(true);
  expect(records.some((m: any) => m.subject === "黄铜罗盘" && m.value.includes("截至第10章末仍握在温岚手中"))).toBe(false);
  await expect(form).toHaveCount(0);
});

test("没有要记进资料的变化：不给审阅入口", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "苏岑拿着黄铜罗盘，温岚的手中已经空了，E2E_SUGGEST。");
  const result = await finishCheck(page, id, await beginCheck(page, id));
  expect(result.issues.map((i: any) => i.has_memory_proposal)).toEqual([false]);
  const issue = result.issues[0];
  await decide(page, id, issue, "不是问题", "false_positive");
  await expect(findings(page).getByText("这次没有要记进资料的变化。", { exact: true })).toBeVisible();
  await expect(button(page, "审阅事实变化")).toHaveCount(0);
  await shot(page, "writing-no-fact-changes", false);
  const attempt = await api(page).raw("POST", `/projects/${id}/memory/change-sets`, { run_id: result.run_id, source_run_revision: result.source_revision, resolved_revision: result.current_revision });
  expect([attempt.status, attempt.body.error.code]).toEqual([422, "no_reviewable_changes"]);
});

test("自动沿用之前的判断：只改无关句子", async ({ page }) => {
  const id = await setup(page);
  await saveBody(page, id, "温岚握着黄铜罗盘。窗外停着一辆蓝色小车。");
  const first = await finishCheck(page, id, await beginCheck(page, id));
  const issue = first.issues.find((i: any) => i.claim_text.includes("罗盘"));
  await decide(page, id, issue, "不是问题", "false_positive");
  expect((await run(page, id)).issues.find((i: any) => i.id === issue.id).reuse_policy.enabled).toBe(true);
  await saveBody(page, id, "温岚握着黄铜罗盘。窗外停着一辆白色小车。");
  const second = await finishCheck(page, id, await beginCheck(page, id));
  const reused = second.issues.find((i: any) => i.claim_text === issue.claim_text);
  expect(reused.reused_decision).toBeTruthy();
  await expect(finding(page, reused.id)).toContainText("沿用之前的判断");
});
