import { spawn } from 'node:child_process';
import { cp, mkdir, mkdtemp, readFile, writeFile } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import path from 'node:path';
import net from 'node:net';

const evidence=import.meta.dirname;
const repo=path.resolve(evidence,'../../..');
const front=path.join(repo,'frontend');
const distName='.next-gap-final-accept';
const dist=path.join(front,distName);
const root=await mkdtemp(path.join(tmpdir(),'story-v130-rc-independent-r2-'));
const artifact=path.join(root,'standalone');
const output=path.join(evidence,`attempt-${Date.now()}`);
await mkdir(output,{recursive:true});
const frontendOrigin='http://127.0.0.1:3238', backendOrigin='http://127.0.0.1:8238';
const children=[];
function env(extra={}){
  const result={...process.env};
  for(const key of Object.keys(result))if(/^(?:CONTINUITY_|SMTP_|RECOVERY_HASH_SECRET$|PUBLIC_RESET_BASE_URL$)/.test(key)||/(?:API_KEY|PASSWORD|TOKEN|SECRET)$/i.test(key))delete result[key];
  return {...result,BACKEND_ORIGIN:backendOrigin,PUBLIC_APP_MODE:'0',PUBLIC_BASE_URL:frontendOrigin,NEXT_DIST_DIR:distName,E2E_BASE_URL:frontendOrigin,E2E_BACKEND_ORIGIN:backendOrigin,E2E_ACCOUNT_PREFIX:`gapg04r2${process.pid}`,E2E_TEST_ROOT:root,E2E_OUTPUT_DIR:output,SCC_DISABLE_DEFAULT_APP:'1',...extra};
}
async function free(port){await new Promise((resolve,reject)=>{const server=net.createServer();server.once('error',reject);server.listen(port,'127.0.0.1',()=>server.close(resolve));});}
function start(command,args,cwd,name,extra={}){
  const child=spawn(command,args,{cwd,env:env(extra),windowsHide:true,stdio:['ignore','pipe','pipe']});
  const record={child,name,output:'',done:null};
  record.done=new Promise(resolve=>{child.once('error',error=>{record.output+=String(error);resolve(-1);});child.once('exit',resolve);});
  child.stdout.on('data',chunk=>record.output+=chunk);child.stderr.on('data',chunk=>record.output+=chunk);
  children.push(record);return record;
}
async function ready(url){const deadline=Date.now()+60000;let last='';while(Date.now()<deadline){try{const r=await fetch(url);if(r.status===200)return r;last=String(r.status);}catch(e){last=e.message;}await new Promise(r=>setTimeout(r,250));}throw Error(`Not ready ${url}: ${last}`);}
const result={started_at:new Date().toISOString(),status:'failed',root,artifact,output,frontendOrigin,backendOrigin,build_id:(await readFile(path.join(dist,'BUILD_ID'),'utf8')).trim()};
try{
  await Promise.all([free(3238),free(8238)]);
  await cp(path.join(dist,'standalone'),artifact,{recursive:true,errorOnExist:true});
  await cp(path.join(front,'public'),path.join(artifact,'public'),{recursive:true,errorOnExist:true});
  await cp(path.join(dist,'static'),path.join(artifact,distName,'static'),{recursive:true,errorOnExist:true});
  start(path.join(repo,'.venv','Scripts','python.exe'),['-m','uvicorn','tests.e2e_app:app','--host','127.0.0.1','--port','8238'],path.join(repo,'backend'),'backend.log',{TRUSTED_HOSTS:'127.0.0.1:8238',TRUSTED_ORIGINS:frontendOrigin});
  await ready(`${backendOrigin}/health`);
  start(process.execPath,[path.join(artifact,'server.js')],artifact,'frontend.log',{HOSTNAME:'127.0.0.1',PORT:'3238',NODE_ENV:'production'});
  const html=await(await ready(frontendOrigin)).text();
  const assets=[...new Set(html.match(/\/_next\/static\/[^"']+\.(?:js|css)(?:\?[^"']*)?/g)??[])];
  if(!assets.length)throw Error('No bootstrap assets');
  result.assets=[];for(const asset of assets){const r=await fetch(frontendOrigin+asset);result.assets.push({asset,status:r.status});if(r.status!==200)throw Error('Asset failed '+asset);}
  const session=await fetch(`${frontendOrigin}/api/auth/session?optional=true`);result.session_status=session.status;if(session.status!==200)throw Error('Session bootstrap failed');
  const testRoute=await fetch(`${frontendOrigin}/test-writing-tools`);result.test_route_http_status=testRoute.status;result.test_route_has_harness=(await testRoute.text()).includes('rich-suggestion-harness');
  const browser=start(process.execPath,[path.join(front,'node_modules','@playwright','test','cli.js'),'test','--config','playwright.config.ts','e2e/v130-writing-analysis.spec.ts','e2e/v140-frontend.spec.ts','e2e/legacy-gap-independent-round2.spec.ts','--grep','writing analysis closes brief|trustworthy review separates|G04 real workbench','--output',path.join(output,'results'),'--reporter','line'],front,'playwright.log');
  result.test_exit=await browser.done;
  process.stdout.write(browser.output);
  result.provider=await(await fetch(`${backendOrigin}/api/test/stage12/stats`)).json();
  if(result.provider.provider_http_calls!==0||result.provider.external_provider_http_enabled!==false)throw Error('Unexpected real provider activity');
  if(result.test_exit!==0)throw Error('Playwright failed');
  result.status='passed';
}catch(error){result.failure={name:error.name,message:error.message};process.exitCode=1;}
finally{
  for(const r of [...children].reverse()){if(r.child.exitCode===null)r.child.kill('SIGTERM');await r.done;await writeFile(path.join(output,r.name),r.output,'utf8');}
  result.completed_at=new Date().toISOString();await writeFile(path.join(output,'result.json'),JSON.stringify(result,null,2)+'\n','utf8');
  process.stdout.write(JSON.stringify(result,null,2)+'\n');
}
