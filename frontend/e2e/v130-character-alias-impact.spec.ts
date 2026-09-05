import { expect, test, type APIResponse, type Page } from "@playwright/test";
import { randomUUID } from "node:crypto";
import path from "node:path";

const backendOrigin=process.env.E2E_BACKEND_ORIGIN;
if(!backendOrigin)throw new Error("E2E_BACKEND_ORIGIN is required");
const accountPrefix=process.env.E2E_ACCOUNT_PREFIX;
if(!accountPrefix)throw new Error("E2E_ACCOUNT_PREFIX is required");
type Envelope<T>={data:T};
async function data<T>(response:APIResponse){expect(response.ok(),await response.text()).toBe(true);return ((await response.json()) as Envelope<T>).data;}
async function register(page:Page){
  const account=`${accountPrefix}alias${Date.now()}${Math.floor(Math.random()*1000)}`.toLowerCase();
  await page.goto("/register");await page.getByLabel("账号").fill(account);await page.getByLabel("显示名称").fill("别名验收作者");await page.getByLabel("恢复邮箱").fill(`${account}@example.test`);await page.locator('input[name="password"]').fill(`safe-${randomUUID()}`);await page.getByRole("button",{name:"创建账号",exact:true}).click();
  await expect(page.getByRole("heading",{name:"继续你的故事",exact:true})).toBeVisible();
}
async function snap(page:Page,name:string){if(process.env.E2E_OUTPUT_DIR)await page.screenshot({path:path.join(process.env.E2E_OUTPUT_DIR,name),fullPage:true});}

test("v1.3.0 character aliases and change impact stay explicit, traceable, and mobile read-only",async({page})=>{
  await page.setViewportSize({width:1440,height:960});
  const statsBefore=await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json() as {provider_http_calls:number};
  await register(page);
  const onboarding=await data<{tutorial:{project_id:string}}>(await page.request.get(`${backendOrigin}/api/onboarding`));
  const projectId=onboarding.tutorial.project_id;
  await page.request.post(`${backendOrigin}/api/test/v130/projects/${projectId}/characters`);
  const project=await data<{source_revision:number;current_memory_version:number;author_context_version:number;current_draft:{id:string;revision:number}}>(await page.request.get(`${backendOrigin}/api/projects/${projectId}`));
  const characters=await data<{characters:{id:string;name:string}[]}>(await page.request.get(`${backendOrigin}/api/projects/${projectId}/characters`));
  const character=characters.characters[0];
  const otherCharacter=characters.characters[1];
  expect(otherCharacter).toBeTruthy();
  const before=await Promise.all([
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/author-intent?include_archived=true`)),
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/memory`)),
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/drafts/${project.current_draft.id}`)),
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/chapters?include=excerpt`)),
  ]);
  await page.goto(`/projects/${projectId}/characters`);
  await expect(page.locator(".character-detail > header h2")).toHaveText(character.name);
  await expect(page.getByRole("heading",{name:"角色别名",exact:true})).toBeVisible();
  await page.getByPlaceholder("添加作者确认的别名").fill("小岚");
  await page.getByRole("button",{name:"添加别名",exact:true}).click();
  await expect(page.getByText("别名已保存为独立角色资料。",{exact:true})).toBeVisible();
  await expect(page.locator(".version-chip")).toHaveText("v1");
  const aliasInput=page.getByLabel("小岚 别名");
  await aliasInput.fill("档案员岚");await page.getByRole("button",{name:"保存",exact:true}).click();
  await expect(page.locator(".version-chip")).toHaveText("v2");
  await page.request.get(`${backendOrigin}/api/test/stage12/reset`);
  const proposal=`把“${character.name}”的公开身份改为港务调查员 E2E_CHANGE_IMPACT_BLOCK`;
  await page.getByPlaceholder(/例如：把/).fill(proposal);
  await page.getByRole("button",{name:"分析影响",exact:true}).click();
  await expect.poll(async()=>((await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json()) as {blocked:boolean}).blocked).toBe(true);
  await expect(page.getByRole("button",{name:"分析影响",exact:true})).toBeDisabled();
  await expect(page.locator(".impact-context")).toContainText(`角色 · ${character.name}`);
  await expect(page.locator(".impact-context")).toContainText(proposal);
  await page.locator(".archive-index").getByRole("button",{name:new RegExp(otherCharacter.name)}).click();
  await expect(page.locator(".character-detail > header h2")).toHaveText(otherCharacter.name);
  await expect(page.locator(".impact-context")).toHaveCount(0);
  await expect(page.getByText(new RegExp(`${character.name}.*影响分析正在`))).toBeVisible();
  await expect(page.getByRole("button",{name:"分析影响",exact:true})).toBeDisabled();
  await page.locator(".archive-index").getByRole("button",{name:new RegExp(character.name)}).click();
  await page.request.get(`${backendOrigin}/api/test/stage12/release`);
  await expect(page.getByText("该修改会影响角色身份识别与相关资料核对。",{exact:true})).toBeVisible();
  const bindings=page.locator(".impact-context small");
  await expect(bindings).toContainText(`草稿 r${project.current_draft.revision}`);
  await expect(bindings).toContainText(`来源 r${project.source_revision}`);
  await expect(bindings).toContainText(`Story Memory V${project.current_memory_version}`);
  await expect(bindings).toContainText(`Author Context V${project.author_context_version}`);
  await expect(bindings).toContainText("别名 V2");
  await expect(bindings).toContainText("检索 writing-analysis-lexical-v1");
  const characterEvidence=page.getByRole("link",{name:new RegExp("character_record")});
  const aliasEvidence=page.getByRole("link",{name:new RegExp("character_alias")});
  await expect(characterEvidence).toBeVisible();await expect(aliasEvidence).toBeVisible();
  await expect(page.getByText("分析版本（1）",{exact:true})).toBeVisible();
  await page.getByText("分析版本（1）",{exact:true}).click();
  await expect(page.locator(".impact-history")).toContainText(character.name);
  await expect(page.locator(".impact-history")).toContainText(character.id);
  await expect(page.locator(".impact-history")).toContainText(proposal);
  await snap(page,"character-alias-impact-01-desktop.png");
  const after=await Promise.all([
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/author-intent?include_archived=true`)),
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/memory`)),
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/drafts/${project.current_draft.id}`)),
    data(await page.request.get(`${backendOrigin}/api/projects/${projectId}/chapters?include=excerpt`)),
  ]);
  expect(after).toEqual(before);
  const aliasHref=await aliasEvidence.getAttribute("href");
  expect(aliasHref).toMatch(new RegExp(`/projects/${projectId}/characters\\?character=${character.id}#alias-`));
  const aliasTarget=new URL(aliasHref!,page.url()).hash.slice(1);
  await aliasEvidence.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/characters\\?character=${character.id}#alias-`));
  await expect(page.locator(".character-detail > header h2")).toHaveText(character.name);
  const aliasAnchor=page.locator(`[id="${aliasTarget}"]`);
  await expect(aliasAnchor).toBeVisible();
  expect(await aliasAnchor.evaluate((node)=>{const box=node.getBoundingClientRect();return box.top<window.innerHeight&&box.bottom>0;})).toBe(true);
  await expect(page.getByLabel("档案员岚 别名")).toBeVisible();
  const refreshedCharacterEvidence=page.getByRole("link",{name:new RegExp("character_record")});
  await refreshedCharacterEvidence.click();
  await expect(page).toHaveURL(new RegExp(`/projects/${projectId}/characters\\?character=${character.id}#character-${character.id}$`));
  const characterAnchor=page.locator(`[id="character-${character.id}"]`);
  await expect(characterAnchor).toBeVisible();
  expect(await characterAnchor.evaluate((node)=>{const box=node.getBoundingClientRect();return box.top<window.innerHeight&&box.bottom>0;})).toBe(true);
  await page.getByLabel("档案员岚 别名").fill("新档案员岚");await page.getByRole("button",{name:"保存",exact:true}).click();
  await page.reload();
  await expect(page.locator(".change-impact-panel .run-state")).toHaveText("依据已变化");
  await expect(page.locator(".impact-context small")).toContainText("别名 V2");
  await page.setViewportSize({width:390,height:844});
  await expect(page.getByRole("heading",{name:"角色别名",exact:true})).toBeVisible();
  await expect(page.getByPlaceholder("添加作者确认的别名")).toHaveCount(0);
  await expect(page.getByPlaceholder(/例如：把/)).toHaveCount(0);
  await expect(page.getByRole("button",{name:/添加别名|分析影响|保存|归档|重试|取消/})).toHaveCount(0);
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=window.innerWidth)).toBe(true);
  await snap(page,"character-alias-impact-02-mobile-390.png");
  const statsAfter=await (await page.request.get(`${backendOrigin}/api/test/stage12/stats`)).json() as {provider_http_calls:number};
  expect(statsAfter.provider_http_calls).toBe(statsBefore.provider_http_calls);expect(statsAfter.provider_http_calls).toBe(0);
});
