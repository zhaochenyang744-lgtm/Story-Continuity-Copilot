import { test, expect } from "@playwright/test";
import { randomUUID } from "node:crypto";
import { writeFile } from "node:fs/promises";

const frontend = "http://127.0.0.1:3238", backend = "http://127.0.0.1:8238";
const cases = [
  {name:"post-time", body:"CTRL_G02_TIME 昨日温岚尚未得知银钥匙的用途。今日她读完陈澈的信，才知道银钥匙能打开潮汐档案柜。", facts:["昨日温岚尚未得知银钥匙的用途", "今日她读完陈澈的信", "才知道银钥匙能打开潮汐档案柜"]},
  {name:"post-quotes", body:"CTRL_G02_QUOTES 陈澈说：‘温岚已经把潮汐表交给林默。’温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’", facts:["陈澈说：‘温岚已经把潮汐表交给林默。’", "温岚摇头说：‘我没有交出潮汐表，它仍在我的背包里。’"]},
];
for (const item of cases) test(`controller G02 ${item.name} preserves own citations and refresh`, async ({page}, info) => {
  expect(process.env.E2E_BASE_URL).toBe(frontend);
  expect(process.env.E2E_BACKEND_ORIGIN).toBe(backend);
  await page.setViewportSize({width:1440,height:960});
  const errors:string[]=[], external:string[]=[];
  page.on("pageerror", e=>errors.push(e.message));
  await page.context().route("**/*", async route=>{
    const url=new URL(route.request().url());
    if (["http:","https:"].includes(url.protocol) && ![frontend,backend].includes(url.origin)) {external.push(url.origin+url.pathname);await route.abort();}
    else await route.continue();
  });
  const account=`ctrlg02${Date.now()}${randomUUID().slice(0,5)}`;
  await page.goto("/register");
  await page.getByLabel("账号",{exact:true}).fill(account);
  await page.getByLabel("显示名称").fill("G02 独立验收");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);
  const registration=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith("/api/auth/register"));
  await page.getByRole("button",{name:"创建账号",exact:true}).click();
  const registered=await registration;expect(registered.ok()).toBe(true);
  const project=(await registered.json()).data.onboarding.tutorial.project_id;
  await expect(page.getByRole("heading",{name:"继续你的故事",exact:true})).toBeVisible();
  await page.goto(`/projects/${project}/workspace`);
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await page.locator("#draft-body").fill(item.body);
  await page.getByRole("button",{name:"保存草稿",exact:true}).click();
  await expect(page.getByRole("status").getByText(/草稿已保存于/)).toBeVisible();
  const created=page.waitForResponse(r=>r.request().method()==="POST"&&r.url().endsWith(`/api/projects/${project}/analyses`));
  await page.getByRole("button",{name:"生成章节简报",exact:true}).click();
  const response=await created;expect(response.status()).toBe(202);
  const id=(await response.json()).data.run_id;
  const read=async()=>{const r=await page.request.get(`${backend}/api/projects/${project}/analyses/${id}`);expect(r.ok()).toBe(true);return (await r.json()).data;};
  await expect.poll(async()=>(await read()).status).toBe("completed");
  const run=await read();
  expect(run.analysis.draft_coverage.status).toBe("covered");
  expect(run.analysis.draft_coverage.uncovered_source_ids).toEqual([]);
  const brief=page.locator('.writing-analysis-result[aria-label="章节简报结果"]');
  await expect(brief).toBeVisible();
  await expect(brief).not.toContainText("所有秘密已经公开");
  for (const fact of item.facts) {
    const supported=run.analysis.items.filter((x:any)=>x.text.includes(fact)&&x.sources.some((s:any)=>s.excerpt.includes(fact)));
    expect(supported.length, fact).toBeGreaterThan(0);
    await expect(brief).toContainText(fact);
  }
  for (const detail of await brief.locator("details").all()) {if(!await detail.getAttribute("open")) await detail.locator("summary").click();}
  for (const fact of item.facts) await expect(brief.locator("details").filter({hasText:fact}).first()).toBeVisible();
  await brief.scrollIntoViewIfNeeded();
  await brief.screenshot({path:info.outputPath(`${item.name}-expanded.png`),animations:"disabled"});
  await page.reload();
  await expect(brief).toBeVisible();
  const refreshed=await read();expect(refreshed.analysis).toEqual(run.analysis);
  for(const fact of item.facts) await expect(brief).toContainText(fact);
  await brief.screenshot({path:info.outputPath(`${item.name}-refreshed.png`),animations:"disabled"});
  const fixture=await (await page.request.get(`${backend}/api/test/g02-controller/calls`)).json();
  const matching=fixture.calls.filter((x:any)=>x.project_id===project);expect(matching).toHaveLength(1);
  expect(matching[0].request.layers.written.draft_claims).toHaveLength(2);
  if(item.name==="post-time") expect(run.analysis.summary).toContain("潮汐档案柜");
  expect(fixture.provider_http_calls).toBe(0);expect(errors).toEqual([]);expect(external).toEqual([]);
  await writeFile(info.outputPath("evidence.json"),JSON.stringify({case:item.name,body:item.body,run,refreshed,fixture:matching,errors,external},null,2));
});
