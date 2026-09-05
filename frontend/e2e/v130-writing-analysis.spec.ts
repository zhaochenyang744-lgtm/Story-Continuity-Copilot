import { expect, test, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin=process.env.E2E_BACKEND_ORIGIN;
if(!backendOrigin)throw new Error("E2E_BACKEND_ORIGIN is required");
const accountPrefix=process.env.E2E_ACCOUNT_PREFIX;
if(!accountPrefix)throw new Error("E2E_ACCOUNT_PREFIX is required");

async function register(page:Page){
  const account=`${accountPrefix}analysis${Date.now()}${Math.floor(Math.random()*1000)}`.toLowerCase();
  await page.goto("/register");
  await page.getByLabel("账号").fill(account);
  await page.getByLabel("显示名称").fill("分析验收作者");
  await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);
  await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);
  await page.getByRole("button",{name:"创建账号",exact:true}).click();
  await expect(page.getByRole("heading",{name:"继续你的故事",exact:true})).toBeVisible();
}

async function createProject(page:Page){
  await page.getByRole("button",{name:"作品管理",exact:true}).click();
  await page.getByRole("button",{name:"新建作品",exact:true}).click();
  await page.getByLabel("作品名称",{exact:true}).fill("雾钟返航闭环");
  await page.getByRole("button",{name:"创建并进入作品",exact:true}).click();
  await expect(page).toHaveURL(/\/projects\/[^/]+\/overview$/);
  const match=page.url().match(/\/projects\/([^/]+)\//);
  if(!match)throw new Error("project id missing");
  return match[1];
}

async function saveDraft(page:Page,body:string){
  const editor=page.locator("#draft-body");
  await editor.fill(body);
  await page.getByRole("button",{name:"保存草稿",exact:true}).click();
  await expect(page.getByText(/草稿已保存为 revision/)).toBeVisible();
}

async function snap(page:Page,name:string){
  if(process.env.E2E_OUTPUT_DIR)await page.screenshot({path:path.join(process.env.E2E_OUTPUT_DIR,name),fullPage:true});
}

test("v1.3.0 writing analysis closes brief, alignment, retry, stale, and mobile read-only flows",async({page})=>{
  await page.setViewportSize({width:1440,height:960});
  const statsBefore=await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json() as {provider_http_calls:number};
  await register(page);
  const projectId=await createProject(page);
  const plan=await page.request.post(`${backendOrigin}/api/projects/${projectId}/author-intent/story-plans`,{headers:{"Idempotency-Key":randomUUID()},data:{base_author_context_version:0,title:"林默带着潮汐表返回雾港",summary:"返航后调查雾钟。",goal:"让返航动作进入正文。",status:"planned",target_chapter_number:1}});
  expect(plan.status(),await plan.text()).toBe(201);
  await page.getByRole("button",{name:"写作与检查",exact:true}).click();
  await expect(page.locator(".workspace-grid")).toBeVisible();
  await saveDraft(page,"林默带着潮汐表返回雾港。她在北门外听见第三次雾钟。" );

  await page.getByRole("button",{name:"生成章节简报",exact:true}).click();
  const brief=page.locator('.writing-analysis-result[aria-label="章节简报结果"]');
  await expect(brief.getByText("写作前先守住返航目标、角色当前状态与雾港规则。",{exact:true})).toBeVisible();
  await brief.getByText(/查看来源/).first().click();
  await expect(brief.getByText(/author_context/).first()).toBeVisible();

  await page.getByRole("button",{name:"检查计划偏离",exact:true}).click();
  const alignment=page.locator('.writing-analysis-result[aria-label="计划偏离结果"]');
  await expect(alignment.getByText("已覆盖",{exact:true})).toBeVisible();
  await alignment.getByText(/查看来源/).click();
  await expect(alignment.getByText(/draft_claim/)).toBeVisible();
  await snap(page,"writing-analysis-01-desktop.png");

  await saveDraft(page,"E2E_ANALYSIS_FAIL_ONCE 林默再次返回雾港。" );
  await page.getByRole("button",{name:"生成章节简报",exact:true}).click();
  await expect(brief.getByText(/结果未通过结构校验/)).toBeVisible();
  await brief.getByRole("button",{name:"重试",exact:true}).click();
  await expect(brief.getByText("写作前先守住返航目标、角色当前状态与雾港规则。",{exact:true})).toBeVisible();

  await saveDraft(page,"林默改写了返航后的第一段。" );
  await expect(brief.getByText("依据已变化",{exact:true})).toBeVisible();
  await expect(alignment.getByText("依据已变化",{exact:true})).toBeVisible();

  await page.setViewportSize({width:390,height:844});
  await expect(brief).toBeVisible();
  await expect(alignment).toBeVisible();
  await expect(page.getByRole("button",{name:"生成章节简报",exact:true})).toHaveCount(0);
  await expect(page.getByRole("button",{name:"检查计划偏离",exact:true})).toHaveCount(0);
  await expect(brief.getByRole("button",{name:/重试|取消/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await snap(page,"writing-analysis-02-mobile-390.png");
  const statsAfter=await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json() as {provider_http_calls:number};
  expect(statsAfter.provider_http_calls).toBe(statsBefore.provider_http_calls);
  expect(statsAfter.provider_http_calls).toBe(0);
});
