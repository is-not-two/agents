/* Real desktop browser, actual source modules, synthetic HTTP only. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {loadPlaywright} from './playwright-runtime.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dir=path.resolve(process.env.SHILIE_UI_DIR||path.join(root,'src/rag_tech_retriever/api/static/shilie'));
const out=path.resolve(process.env.UX_CHECK_OUT||path.join(root,'output/desktop-ux-check'));
fs.mkdirSync(out,{recursive:true});
const notes=[],writes=[],agent={id:'ux-agent',version:1,data:{title:'Synthetic assistant',generate:true,scopes:['knowledge'],tool_ids:['knowledge_draft'],skill_ids:[],mcp_server_ids:[],model:{},budget:{},context:{max_messages:20},memory:{scope:'none'}}};
const leads=Array.from({length:20},(_,i)=>({id:'lead-'+i,kind:'job_lead',version:1,data:{title:'Synthetic job '+i,company:'Synthetic company',jd_text:'Fixture only',source_url:''}}));
const app={id:'application-0',kind:'application',version:1,data:{title:'Synthetic follow-up',lead_id:'lead-0',status:'following',follow_up_at:'2026-11-01T00:00:00Z'}};
let saveMode='fail',pending;
const report={checks:[],errors:[],external:[]};
const send=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname.startsWith('/api/')){
  let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):{};const n=u.pathname.slice(5);
  if(req.method!=='GET')writes.push({path:n,method:req.method,body});
  if(n==='session')return send(res,200,{required:false,authenticated:true,account_login:false});
  if(n==='knowledge'&&req.method==='POST'){
   if(saveMode==='pending'){pending=()=>send(res,503,{detail:'Synthetic save failure',code:'STORAGE_UNAVAILABLE'});return;}
   if(saveMode==='fail')return send(res,503,{detail:'Synthetic save failure',code:'STORAGE_UNAVAILABLE'});
   const row={id:'note-'+notes.length,kind:'knowledge',version:1,data:body.data};notes.push(row);return send(res,201,row);
  }
  if(n.startsWith('knowledge/')&&req.method==='PUT')return send(res,409,{detail:'Synthetic conflict',code:'VERSION_CONFLICT'});
  if(n==='knowledge')return send(res,200,notes);
  if(n==='status')return send(res,200,{});
  if(n==='stage-summary')return send(res,200,{records:[],updated_at:''});
  if(n==='query/options')return send(res,200,{namespaces:[],default:null});
  if(n==='jobs')return send(res,200,{job_lead:leads,application:[app],interview_report:[],resume_version:[],due_application_ids:[app.id],funnel:{stages:{collected:20,applied:1,interviewed:0,offered:0},rates:{applied_per_collected:.05,interviewed_per_applied:0,offered_per_interviewed:null},weekly:{applications:1,target:5,met:false}}});
  if(n==='agents')return send(res,200,[agent]);
  if(n==='model-connection')return send(res,200,{configured:true,has_api_key:true});
  if(n==='capabilities')return send(res,200,{builtin_tools:[],http_tools:[],web_search:{enabled:false}});
  if(n==='capabilities/tools')return send(res,200,{builtin:[{name:'knowledge_draft',description:'Fixture draft'}],http:[],mcp:[]});
  if(n==='agents/ux-agent/run')return send(res,503,{detail:'Synthetic provider unavailable',code:'TOOL_FAILURE'});
  return send(res,200,[]);
 }
 const rel=u.pathname==='/'?'index.html':u.pathname.replace(/^\/static\/shilie\//,'');const file=path.resolve(dir,rel);
 if(!file.startsWith(dir+path.sep)||!fs.existsSync(file)||!fs.statSync(file).isFile()){res.writeHead(404);res.end();return;}
 const mime={'.js':'text/javascript','.html':'text/html','.css':'text/css','.svg':'image/svg+xml','.png':'image/png','.webp':'image/webp','.mp4':'video/mp4'};
 res.writeHead(200,{'Content-Type':mime[path.extname(file)]||'application/octet-stream'});res.end(fs.readFileSync(file));
});
await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin=`http://127.0.0.1:${server.address().port}`;
const {chromium}=await loadPlaywright();
const executablePath=process.env.PLAYWRIGHT_EXECUTABLE_PATH||(process.platform==='win32'?'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe':undefined);
const browser=await chromium.launch({headless:true,...(executablePath?{executablePath}:{})});
const check=(name,ok,details)=>{report.checks.push({name,ok,...details});assert(ok,name);};
try{
 const page=await browser.newPage({viewport:{width:1440,height:960}});
 page.on('pageerror',e=>report.errors.push(e.message));page.on('request',r=>{if(!r.url().startsWith(origin+'/'))report.external.push(r.url());});
 let decision='dismiss',confirmCount=0;
 page.on('dialog',async d=>{confirmCount++;if(decision==='accept')await d.accept();else await d.dismiss();});
 await page.goto(origin+'/#module/knowledge',{waitUntil:'networkidle'});
 const dialog=page.locator('dialog[data-form="knowledge"]'),title=dialog.locator('[name="title"]');
 await page.locator('[data-action="new-note"]').first().click();await title.fill('SYNTHETIC-DRAFT');await dialog.locator('[name="content"]').fill('Draft body');
 await page.keyboard.press('Escape');check('escape-dismiss-keeps-input',await dialog.evaluate(e=>e.open)&&await title.inputValue()==='SYNTHETIC-DRAFT'&&confirmCount===1);
 await dialog.getByRole('button',{name:'取消',exact:true}).click();check('cancel-dismiss-keeps-input',await dialog.evaluate(e=>e.open)&&confirmCount===2);
 await page.evaluate(()=>location.hash='#module/jobs');await page.waitForTimeout(200);
 check('route-dismiss-keeps-hash-and-input',(await page.evaluate(()=>location.hash))==='#module/knowledge'&&await dialog.evaluate(e=>e.open)&&await title.inputValue()==='SYNTHETIC-DRAFT');
 const unload=await page.evaluate(()=>{const e=new Event('beforeunload',{cancelable:true});dispatchEvent(e);return e.defaultPrevented;});check('beforeunload-guard-installed',unload);
 check('draft-not-written-to-browser-storage',await page.evaluate(()=>![...Object.values(localStorage),...Object.values(sessionStorage)].some(v=>v.includes('SYNTHETIC-DRAFT')||v.includes('Draft body'))));
 saveMode='pending';await dialog.locator('button[type="submit"]').click();await page.waitForTimeout(100);const before=confirmCount;
 await page.keyboard.press('Escape');check('pending-save-cannot-be-discarded',await dialog.evaluate(e=>e.open)&&confirmCount===before&&writes.length===1);
 assert(pending);const finishPending=pending;pending=null;finishPending();await dialog.getByRole('alert').waitFor();
 check('failed-save-preserves-draft',await title.inputValue()==='SYNTHETIC-DRAFT');
 saveMode='success';await dialog.locator('button[type="submit"]').click();await page.waitForFunction(()=>!document.querySelector('dialog[data-form="knowledge"]').open);
 check('successful-save-no-discard-confirmation',notes.length===1&&confirmCount===before);
 await page.locator('[data-action="edit-note"]').click();await dialog.locator('[name="content"]').fill('Conflict draft');await dialog.locator('button[type="submit"]').click();await page.locator('#detail-dialog[open]').waitFor();
 check('conflict-retains-input',await dialog.locator('[name="content"]').inputValue()==='Conflict draft');
 await page.locator('#detail-dialog [data-action="close-dialog"]').click();decision='accept';await page.keyboard.press('Escape');
 await page.locator('[data-action="new-note"]').first().click();await title.fill('DISCARD-ME');await page.keyboard.press('Escape');
 await page.locator('[data-action="new-note"]').first().click();check('explicit-discard-clears-next-draft',await title.inputValue()==='');await page.keyboard.press('Escape');
 await page.evaluate(()=>location.hash='#module/jobs');await page.waitForSelector('.jobs-row');
 check('desktop-funnel-collapsed',await page.locator('[data-job-statistics]').count()===1&&!await page.locator('[data-job-statistics]').evaluate(e=>e.open));
 const list=await page.locator('.jobs-list').boundingBox();check('desktop-job-list-first-screen',list.y<650,{top:Math.round(list.y)});
 await page.locator('[data-action="job-select"]').first().click();await page.waitForSelector('.jobs-detail[aria-label="求职详情"]');
 const detail=await page.locator('.jobs-detail').boundingBox();check('desktop-job-detail-first-screen',detail.y<650,{top:Math.round(detail.y)});
 await page.locator('[data-action="job-due"]').click();check('due-shortcut-filters-existing-records',await page.locator('.jobs-row').count()===1&&await page.locator('#jobs-filter [name="filter"]').inputValue()==='due');
 await page.locator('[data-job-statistics] summary').click();await page.locator('[data-action="job-select"]').click();check('funnel-expanded-state-survives-selection',await page.locator('[data-job-statistics]').evaluate(e=>e.open));
 await page.screenshot({path:path.join(out,'jobs-desktop.png')});
 await page.evaluate(()=>location.hash='#module/agent-studio');await page.waitForSelector('[data-studio-form="start"]');
 const start=await page.locator('[data-studio-form="start"]').boundingBox();check('agent-question-first-screen',start.y<650,{top:Math.round(start.y)});
 check('agent-config-present-but-collapsed',await page.locator('[data-studio-form="config"]').count()===1&&!await page.locator('[data-studio-form="config"]').isVisible());
 await page.locator('[data-studio-advanced] summary').click();check('agent-advanced-settings-reachable',await page.locator('[data-studio-form="config"]').isVisible());
 await page.locator('[data-studio-advanced] summary').click();
 await page.locator('[data-studio-form="start"] [name="query"]').fill('Synthetic question');await page.locator('[data-studio-form="start"] button[type="submit"]').click();
 await page.locator('[data-studio-form="start"] [role="alert"]').filter({hasText:'Synthetic provider unavailable'}).waitFor();
 const request=writes.find(x=>x.path==='agents/ux-agent/run');check('agent-request-contract-unchanged',JSON.stringify(request.body)===JSON.stringify({version:1,query:'Synthetic question'}));
 check('agent-failure-preserves-question',await page.locator('[data-studio-form="start"] [name="query"]').inputValue()==='Synthetic question');
 await page.screenshot({path:path.join(out,'agent-desktop.png')});
 check('no-implicit-agent-config-or-permission-write',writes.every(x=>x.path==='knowledge'||x.path.startsWith('knowledge/')||x.path==='agents/ux-agent/run'));
 await page.close();
}catch(e){report.errors.push(e.stack||String(e));process.exitCode=1;}
finally{if(pending){try{pending();}catch{}}await browser.close();await new Promise(resolve=>server.close(resolve));fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify(report,null,2)+'\n');}
for(const item of report.checks)console.log(item.name+': '+(item.ok?'PASS':'FAIL'));
console.log('DESKTOP_UX checks='+report.checks.length+' errors='+report.errors.length+' external='+report.external.length);
if(report.errors.length)console.error(report.errors.join('\n'));
if(report.external.length)process.exitCode=1;
