import { expect, test } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { readFile } from "node:fs/promises";
import path from "node:path";

const fixture = path.resolve(process.cwd(), "e2e/fixtures/stage9-mist-harbor.md");

async function api(page: import("@playwright/test").Page, path: string) {
  return page.evaluate(async (url) => (await fetch(url)).json(), path);
}

async function readyForDelta(page: import("@playwright/test").Page) {
  await page.goto("/register");
  await page.getByLabel("账号").fill(`stage11k${Date.now()}`); await page.getByLabel("显示名称").fill("11K 作者"); await page.getByLabel("密码").fill(`safe-${randomUUID()}`); await page.getByRole("button",{name:"创建本地账号"}).click();
  await page.getByRole("button",{name:"作品管理",exact:true}).click(); await page.getByRole("button",{name:"导入作品",exact:true}).click();
  await page.locator('input[name="file"]').setInputFiles({name:"base.md",mimeType:"text/markdown",buffer:await readFile(fixture)}); await page.getByRole("button",{name:"解析并预览章节"}).click(); await page.getByRole("button",{name:"继续确认"}).click(); await page.getByLabel("作品名").fill("11K 增量作品"); await page.getByRole("button",{name:"确认导入"}).click();
  await page.getByRole("button",{name:"初始化 Story Memory"}).click(); await page.getByRole("button",{name:"审核候选与 Evidence"}).click(); const init=page.getByRole("form",{name:"Story Memory 初始化审核"}); const core=init.locator("article.memory-init-candidate").filter({hasText:"核心候选（必须决定）"}); await core.getByLabel("接受（写入 V1）").check(); await init.getByRole("button",{name:"确认核心审核并建立 Memory V1"}).click(); await expect(init.getByText("已安全建立部分 Memory",{exact:true})).toBeVisible();
  const id=new URL(page.url()).pathname.split("/")[2]; await page.goto(`/projects/${id}/sources`); await page.getByLabel("章节正文").fill("# 增量章节\n林默将银钥匙交给守塔人。"); const preview=page.waitForResponse((r)=>r.url().includes("source-change-sets/preview")&&r.request().method()==="POST"); await page.getByRole("button",{name:"预览追加"}).click(); expect((await preview).status()).toBe(201); const commit=page.waitForResponse((r)=>/source-change-sets\/.+\/commit/.test(r.url())&&r.request().method()==="POST"); await page.getByRole("button",{name:"确认追加并创建下一章草稿"}).click(); expect((await commit).status()).toBe(200); return id;
}

async function start(page: import("@playwright/test").Page,id: string) {
  await page.goto(`/projects/${id}/workspace`); const started=page.waitForResponse((r)=>r.url().endsWith("/incremental-reviews")&&r.request().method()==="POST"); await page.locator(".warning").filter({hasText:"Source r2"}).getByRole("button",{name:"运行增量检查"}).click(); const response=await started; expect(response.status()).toBe(202); return (await response.json()).data;
}

test("desktop separates Issues and Memory Delta, shows current-project Evidence, then edited core creates V2",async({page})=>{
  const id=await readyForDelta(page); const started=await start(page,id);
  await expect(page.getByRole("heading",{name:/Issues/})).toBeVisible(); await expect(page.getByRole("heading",{name:"Memory Delta"})).toBeVisible();
  expect(started).toMatchObject({continuity_run_id:expect.any(String),memory_delta_run_id:expect.any(String)}); expect(started.continuity_run_id).not.toBe(started.memory_delta_run_id);
  const continuity=await api(page,`/api/projects/${id}/checks/${started.continuity_run_id}?include=issues,evidence,metrics`); const deltaRun=await api(page,`/api/projects/${id}/checks/${started.memory_delta_run_id}?include=metrics`);
  expect(continuity.data).toMatchObject({run_type:"continuity",source_revision:2,is_stale:false,lineage_status:"incremental_source_revision"}); expect(deltaRun.data).toMatchObject({run_type:"memory_delta",source_revision:2,is_stale:false,lineage_status:"incremental_source_revision"});
  await page.locator(".issue-list button").first().click(); const drawer=page.getByRole("dialog",{name:"问题证据"}); await expect(drawer).toBeVisible(); await expect(drawer.getByText("Evidence",{exact:true})).toBeVisible(); await expect(drawer.locator(`a[href="/projects/${id}/sources#span-${(await continuity.data.issues[0].evidence[0].span_id)}"]`)).toBeVisible(); await page.keyboard.press("Escape");
  await page.getByRole("button",{name:"打开 Delta 审核与 Evidence"}).click(); const review=page.getByRole("form",{name:"Memory Delta 审核"}); const core=review.locator("article.memory-init-candidate").filter({hasText:"核心候选（必须决定）"}); await core.getByRole("radio",{name:"编辑后接受"}).check(); await core.getByLabel("事实内容").fill("编辑后交给守塔人");
  const committed=page.waitForResponse((r)=>/\/memory\/deltas\/[^/]+\/commit$/.test(new URL(r.url()).pathname)&&r.request().method()==="POST"); await review.getByRole("button",{name:"提交已决定的核心候选"}).click(); expect((await committed).status()).toBe(200);
  const coverage=await api(page,`/api/projects/${id}/memory/coverage`); expect(coverage.data).toMatchObject({status:"ready_partial",source_revision:2,counts:{core_pending:0,pending_canon_count:0}}); const memory=await api(page,`/api/projects/${id}/memory`); expect(memory.data.memory_version).toBe(2); expect(memory.data.records.map((x:{value:string})=>x.value)).toContain("编辑后交给守塔人");
});

test("all delta core rejected keeps Memory V1 and exposes readable source coverage audit",async({page})=>{
  const id=await readyForDelta(page); await start(page,id); await page.getByRole("button",{name:"打开 Delta 审核与 Evidence"}).click(); const review=page.getByRole("form",{name:"Memory Delta 审核"}); const core=review.locator("article.memory-init-candidate").filter({hasText:"核心候选（必须决定）"}); await core.getByRole("radio",{name:"拒绝",exact:true}).check(); await review.getByRole("button",{name:"提交已决定的核心候选"}).click();
  await expect(page.getByLabel("增量来源覆盖审计")).toContainText("covered_without_memory_change"); const delta=await api(page,`/api/projects/${id}/memory/delta`); expect(delta.data).toMatchObject({status:"covered",coverage:{status:"ready_partial"},coverage_audit:{status:"covered_without_memory_change"}}); expect(delta.data.coverage_audit.details.decisions[0]).toMatchObject({decision:"rejected",evidence_span_id:expect.any(String)}); const audit=await api(page,`/api/projects/${id}/source-coverage-audits/${delta.data.coverage_audit.id}`); expect(audit.data.audit.id).toBe(delta.data.coverage_audit.id); const memory=await api(page,`/api/projects/${id}/memory`); expect(memory.data.memory_version).toBe(1);
});

test("390 remains browse-only for delta decisions and commit",async({page})=>{
  await page.setViewportSize({width:1440,height:900}); const id=await readyForDelta(page); await start(page,id); await page.getByRole("button",{name:"打开 Delta 审核与 Evidence"}).click(); await page.setViewportSize({width:390,height:844}); const review=page.getByRole("form",{name:"Memory Delta 审核"}); await expect(review).toBeVisible(); for(const input of await review.locator("input, select, textarea").all()) await expect(input).toBeDisabled(); await expect(review.getByRole("button",{name:"提交已决定的核心候选"})).toBeDisabled();
});
