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
const agentProfile=(title,root='')=>({title,system_prompt:'',tool_ids:[],workspace:{root,write:'each',shell:false}});
const draftFixture={mode:'rules',template:'code',
 agents:[{key:'planner',profile:agentProfile('规划')},{key:'coder',profile:agentProfile('实现','demo')}],
 workflow:{title:'Synthetic draft',nodes:[{id:'input',type:'input'},{id:'plan',type:'agent',agent_id:'draft-planner',query:'拆解目标'},{id:'merge',type:'merge'}],
  edges:[['input','plan'],['plan','merge']],max_parallel:1,join_policy:'all_success'},mapping:{plan:'planner'}};
const revisedFixture={...draftFixture,workflow:{...draftFixture.workflow,title:'Synthetic draft v2',
 nodes:[...draftFixture.workflow.nodes,{id:'review',type:'approval',message:'确认上线'}],
 edges:[['input','plan'],['plan','merge'],['merge','review']]}};
const revisedChanges={title:{before:'Synthetic draft',after:'Synthetic draft v2'},nodes_added:['review'],
 nodes_removed:[],nodes_changed:[],edges_added:[['merge','review']],edges_removed:[],
 agents_added:[],agents_removed:[],agents_changed:['coder']};
const loopSummary={status:'success',rounds:2,reason:'',green_points:1,engine:'opencode',tier:'feature',duration_ms:50600,
 attempts:[{round:1,files:1,lines:2,passed:false,why:'FAILED tests/check.py::test_sum'},{round:2,files:2,lines:6,passed:true,why:'2 passed in 0.12s'}],
 diff:' mathx.py | 2 +-\n report.py | 4 +++-\n 2 files changed, 5 insertions(+), 1 deletion(-)'};
const loopRow={id:'run-loop',kind:'workflow_run',version:1,data:{kind:'loop',status:'completed',title:'自动编码：修复求和',started_at:'2026-11-10T03:00:00Z',input:{task:'修复求和',gate:'pytest -q'},summary:loopSummary}};
const queueJobs=[
 {id:'job-queued-0001',kind:'loop',status:'queued',priority:50,attempts:0,max_attempts:3,next_run_at:'2026-11-10T04:00:00Z',last_error:'',created_at:'2026-11-10T03:50:00Z',updated_at:'2026-11-10T03:50:00Z'},
 {id:'job-dead-0000002',kind:'loop',status:'dead',priority:50,attempts:3,max_attempts:3,next_run_at:'2026-11-10T04:10:00Z',last_error:'RuntimeError: gate exited 1',created_at:'2026-11-10T03:00:00Z',updated_at:'2026-11-10T03:40:00Z'}];
const queueStats={queued:1,running:0,succeeded:2,dead:1,cancelled:0};
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
  if(n==='automation/code-roots')return send(res,200,[{name:'demo',title:'Synthetic repo',writable:true}]);
  if(n==='automation/compose/draft')return send(res,201,draftFixture);
  if(n==='automation/compose/revise')return send(res,200,{draft:revisedFixture,changes:revisedChanges});
  if(n==='automation/compose/save')return send(res,201,{mode:'rules',agent_ids:['a1','a2'],
   agents:[{key:'planner',id:'a1'},{key:'coder',id:'a2'}],workflow_id:'wf-draft',version:1,
   title:'Synthetic draft v2'});
  if(n==='automation/teams/run')return send(res,201,{id:'run-team',version:1,mode:'group_chat',
   model_calls:5,speakers:['Synthetic agent','Second agent'],final:'评估完成：缺口两项。',
   agents:[],turns:[{author:'Synthetic agent',text:'缺口：缺少实验设计经验。'},
   {author:'Second agent',text:'问题：如何设计一次对比实验？'}]});
  if(n==='workflow-runs')return send(res,200,[{id:'run-team',kind:'workflow_run',version:1,data:{kind:'team',status:'completed',title:'团队：评估候选人',started_at:'2026-11-10T02:30:00Z',mode:'group_chat',model_calls:3,approved:false,agents:[{id:'ux-agent',title:'Synthetic agent',tools:[]}],input:{task:'评估候选人'}}},loopRow]);
  if(n==='workflow-runs/run-loop')return send(res,200,loopRow);
  if(n==='automation/loop/run')return send(res,201,{id:'run-loop',version:1,task:body.task,gate:body.gate,...loopSummary});
  if(n==='automation/queue/stats')return send(res,200,queueStats);
  if(n==='automation/queue'&&req.method==='POST')return send(res,201,{id:'job-new-00000003',kind:body.kind,status:'queued',priority:body.priority,attempts:0,max_attempts:body.max_attempts,next_run_at:'2026-11-10T04:20:00Z',last_error:'',created_at:'2026-11-10T04:00:00Z',updated_at:'2026-11-10T04:00:00Z'});
  if(n==='automation/queue'&&req.method==='GET'){
   const status=u.searchParams.get('status');
   return send(res,200,status?queueJobs.filter(j=>j.status===status):queueJobs);
  }
  if(n==='automation/queue/job-queued-0001')return send(res,200,{...queueJobs[0],payload:{root:'demo',task:'修复求和',gate:'pytest -q'},checkpoint:{kind:'loop',round:1,files:1,lines:4},result:null});
  if(n==='automation/queue/job-dead-0000002')return send(res,200,{...queueJobs[1],payload:{root:'demo',task:'失败的改动'},checkpoint:{kind:'loop',round:2,files:0,lines:0},result:null});
  if(n.endsWith('/cancel'))return send(res,200,{id:'job-queued-0001',kind:'loop',status:'cancelled',priority:50,attempts:0,max_attempts:3,next_run_at:'',last_error:'',created_at:'2026-11-10T03:50:00Z',updated_at:'2026-11-10T04:05:00Z'});
  if(n.endsWith('/replay'))return send(res,200,{id:'job-dead-0000002',kind:'loop',status:'queued',priority:50,attempts:0,max_attempts:3,next_run_at:'2026-11-10T04:20:00Z',last_error:'',created_at:'2026-11-10T03:00:00Z',updated_at:'2026-11-10T04:10:00Z'});
  if(n==='workflow-runs/run-team')return send(res,200,{id:'run-team',kind:'workflow_run',version:1,data:{kind:'team',status:'completed',title:'团队：评估候选人',started_at:'2026-11-10T02:30:00Z',mode:'group_chat',model_calls:3,approved:false,agents:[{id:'ux-agent',title:'Synthetic agent',tools:[]}],input:{task:'评估候选人'},turns:[{author:'Synthetic agent',text:'缺口：缺少实验经验。'}],result:{answer:'终稿：缺口两项。'}}});
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
 const flowPage=await browser.newPage({viewport:{width:1440,height:960}});
 flowPage.on('pageerror',e=>report.errors.push('job-flow: '+e.message));
 flowPage.on('request',r=>{if(!r.url().startsWith(origin+'/'))report.external.push(r.url());});
 const fx=(rows)=>({status:200,contentType:'application/json',body:JSON.stringify(rows)});
 const flowLeads=[
  {id:'flow-lead-a',kind:'job_lead',version:1,data:{title:'产品经理',company:'甲公司',jd_text:'需要沟通能力'}},
  {id:'flow-lead-b',kind:'job_lead',version:1,data:{title:'全栈开发',company:'乙公司',jd_text:'需要 Python'}}];
 const flowApps=[{id:'flow-app-a',kind:'application',version:1,data:{title:'甲投递',lead_id:'flow-lead-a',resume_version_id:'flow-resume-1',status:'applied'}}];
 const flowCaps=[{id:'flow-cap-a',kind:'company_capability',version:1,data:{title:'甲能力',company:'甲公司',role:'产品经理',capabilities:[{name:'沟通能力',requirement:'must',level:5,status:'missing',evidence:''}]}}];
 const flowReports=[{id:'flow-report-a',kind:'interview_report',version:1,data:{title:'甲一面',application_id:'flow-app-a',round:1,questions:[{q:'问题',rating:2}],weak_points:['表达'],next_actions:['练习']}}];
 const flowResumes=[
  {id:'flow-resume-1',kind:'resume_version',version:1,data:{title:'简历 v1',file_name:'a.pdf',parse_status:'parsed',highlights:['Python']}},
  {id:'flow-resume-2',kind:'resume_version',version:1,data:{title:'简历 v2',file_name:'b.pdf',parse_status:'parsed',highlights:['沟通']}}];
 for(const [endpoint,rows] of [['jobs/leads',flowLeads],['jobs/applications',flowApps],['jobs/capabilities',flowCaps],['jobs/reports',flowReports],['jobs/resumes',flowResumes]])
  await flowPage.route('**/api/'+endpoint,route=>route.fulfill(fx(rows)));
 await flowPage.route('**/api/resume/templates',route=>route.fulfill(fx([
  {id:'product-manager',name:'AI 产品经理'},{id:'fullstack',name:'AI 全栈开发'},{id:'general',name:'通用结构优化'}])));
 await flowPage.goto(origin+'/#module/job-flow',{waitUntil:'networkidle'});
 await flowPage.waitForSelector('.job-flow__pages');
 const flowBody=async()=>await flowPage.locator('.job-flow__page').innerText();
 check('job-flow-five-p1-pages',await flowPage.locator('[data-action="jobflow-page"]').count()===5);
 check('job-flow-pipeline-four-stages',await flowPage.locator('[data-action="jobflow-stage"]').count()===4);
 check('job-flow-resume-not-a-pipeline-stage',await flowPage.locator('[data-stage="resume"]').count()===0);
 check('job-flow-two-companies',await flowPage.locator('.job-flow__company').count()===2);
 check('job-flow-default-company-shows-its-lead',(await flowBody()).includes('产品经理'));
 await flowPage.locator('[data-action="jobflow-company"][data-company="乙公司"]').click();
 check('job-flow-company-switch-changes-content',(await flowBody()).includes('全栈开发')&&!(await flowBody()).includes('产品经理'));
 await flowPage.locator('[data-action="jobflow-company"][data-company="甲公司"]').click();
 await flowPage.locator('[data-action="jobflow-stage"][data-stage="required"]').click();
 check('job-flow-required-stage-renders-capabilities',(await flowBody()).includes('沟通能力'));
 await flowPage.locator('[data-action="jobflow-stage"][data-stage="review"]').click();
 check('job-flow-review-stage-renders-report',(await flowBody()).includes('甲一面'));
 await flowPage.locator('[data-action="jobflow-page"][data-page="resumes"]').click();
 await flowPage.waitForSelector('.job-flow__page');
 check('job-flow-resumes-independent-of-company',await flowPage.locator('.job-flow__companies').count()===0);
 check('job-flow-resumes-lists-all-versions',await flowPage.locator('.job-flow__page .job-flow__card').count()>=2&&(await flowBody()).includes('简历 v2'));
 check('job-flow-resume-analysis-controls-present',await flowPage.locator('#job-flow-resume-id').count()===1&&await flowPage.locator('#job-flow-resume-lead').count()===1&&await flowPage.locator('[data-action="jobflow-resume-analyze"]').count()===1);
 await flowPage.reload({waitUntil:'networkidle'});
 await flowPage.waitForSelector('.job-flow__pages');
 check('job-flow-page-persists-after-reload',await flowPage.locator('[data-page="resumes"]').getAttribute('aria-pressed')==='true');
 await flowPage.locator('[data-action="jobflow-page"][data-page="ai-resume"]').click();
 const placeholder=await flowPage.locator('.job-flow__placeholder').innerText();
 check('job-flow-ai-resume-template-driven',placeholder.includes('模板驱动')&&placeholder.includes('不覆盖简历本体')&&await flowPage.locator('.job-flow__placeholder button').count()===0);
 check('job-flow-ai-resume-reports-template-status',(await flowPage.locator('.job-flow__page').innerText()).includes('模板状态'));
 await flowPage.waitForSelector('#resume-optimize-form',{timeout:8000});
 check('resume-optimizer-form-appears-with-templates',await flowPage.locator('#resume-optimize-form').count()===1&&await flowPage.locator('#resume-optimize-form [name="template_id"] option').count()===3);
 await flowPage.locator('[data-action="jobflow-page"][data-page="manage"]').click();
 check('job-flow-manage-keeps-four-legacy-links',await flowPage.locator('.job-flow__page a[href^="#module/"]').count()===4);
 const hiddenLinks=await flowPage.evaluate(()=>[...document.querySelectorAll('.job-flow__page a[href^="#module/"]')].map(a=>a.getAttribute('href').replace('#module/','')));
 const nav=await flowPage.evaluate(async()=>{
  const m=await import('/static/shilie/data.js');
  const ids=m.modules.map(x=>x.id),listed=m.navSections.flatMap(s=>s.modules),groups=new Set(m.groups.map(g=>g.id));
  return {modules:ids.length,missing:ids.filter(id=>!listed.includes(id)),unknown:listed.filter(id=>!ids.includes(id)),
   dupes:[...new Set(listed.filter((id,i)=>listed.indexOf(id)!==i))],orphans:[...new Set(m.modules.map(x=>x.group).filter(g=>!groups.has(g)))],sections:m.navSections.length};
 });
 check('nav-sections-cover-every-module',nav.missing.every(id=>hiddenLinks.includes(id))&&nav.unknown.length===0&&nav.dupes.length===0,{...nav,hiddenLinks});
 check('every-module-has-a-valid-group',nav.orphans.length===0,nav);
 const sidebar=await flowPage.evaluate(()=>{
  const secs=[...document.querySelectorAll('.sidebar .nav-section')],trash=document.querySelector('.sidebar .sidebar-trash');
  return {sections:secs.length,current:document.querySelectorAll('.sidebar [aria-current="page"]').length,
   trashAfter:!!(secs.length&&trash&&secs[secs.length-1].compareDocumentPosition(trash)&Node.DOCUMENT_POSITION_FOLLOWING),
   systemOpen:!!document.querySelector('.nav-section[data-section="system"] .nav-section__items')};
 });
 check('sidebar-five-sections-and-single-current',sidebar.sections===5&&sidebar.current===1,sidebar);
 check('sidebar-trash-after-sections-and-system-collapsed',sidebar.trashAfter&&!sidebar.systemOpen,sidebar);
 await flowPage.evaluate(()=>location.hash='#module/self-traits');
 await flowPage.waitForSelector('[data-action="trait-new"]');
 check('self-traits-page-reachable',await flowPage.locator('[data-action="trait-new"]').count()===1);
 check('job-flow-and-sidebar-checks-are-read-only',writes.every(x=>x.path==='knowledge'||x.path.startsWith('knowledge/')||x.path==='agents/ux-agent/run'));
 await flowPage.evaluate(()=>location.hash='#module/job-flow');
 await flowPage.waitForSelector('.job-flow__pages');
 await flowPage.locator('[data-action="jobflow-page"][data-page="resumes"]').click();
 await flowPage.locator('[data-action="jobflow-resume-analyze"]').click();
 await flowPage.waitForFunction(()=>document.querySelector('.job-flow__page')?.innerText.includes('比对结果'));
 const analyzeWrite=writes.find(x=>x.path==='jobs/resumes/flow-resume-1/analyze');
 check('job-flow-resume-analyze-request-contract',analyzeWrite?.method==='POST'&&analyzeWrite.body.lead_id==='flow-lead-a',{analyzeWrite});
 await flowPage.locator('[data-action="jobflow-page"][data-page="pipeline"]').click();
 await flowPage.locator('[data-action="jobflow-stage"][data-stage="gap"]').click();
 await flowPage.locator('[data-action="jobflow-gap-analyze"]').click();
 await flowPage.waitForFunction(()=>document.querySelector('.job-flow__page')?.innerText.includes('规则分析没有提取到要求'));
 check('job-flow-gap-analyze-tolerates-empty-result',await flowPage.locator('.job-flow__page').count()===1);
 check('only-one-controlled-write-from-flow-page',writes.filter(x=>x.path.startsWith('jobs/')).length===1);
 await flowPage.evaluate(()=>location.hash='#module/workflows');
 await flowPage.waitForSelector('#compose-form');
 check('compose-form-available',await flowPage.locator('#compose-form [name="goal"]').count()===1&&await flowPage.locator('#compose-form [name="mode"] option').count()===2);
 await flowPage.locator('[data-action="auto-new-workflow"]').click();
 await flowPage.locator('[data-auto-form="workflow"] [name="kind"]').selectOption('graph');
 await flowPage.waitForSelector('[data-auto-form="workflow"] [data-graph-row]');
 const graphBefore=await flowPage.locator('[data-auto-form="workflow"] [data-graph-row]').count();
 await flowPage.locator('[data-action="auto-graph-add"]').click();
 check('graph-editor-adds-node',await flowPage.locator('[data-auto-form="workflow"] [data-graph-row]').count()===graphBefore+1);
 await flowPage.locator('[data-action="auto-graph-sync"]').click();
 const graphJson=await flowPage.locator('[data-auto-form="workflow"] [name="graph_json"]').inputValue();
 check('graph-editor-syncs-json',JSON.parse(graphJson).nodes.length===graphBefore+1);
 const lastRow=flowPage.locator('[data-auto-form="workflow"] [data-graph-row]').last();
 await lastRow.locator('[data-action="auto-graph-add-upstream"]').click();
 check('graph-editor-supports-multiple-upstreams',await lastRow.locator('[data-graph-upstream]').count()===2);
 const newId=await lastRow.locator('[data-graph-id]').inputValue();
 await lastRow.locator('[data-graph-upstream]').nth(0).selectOption('input');
 await lastRow.locator('[data-graph-upstream]').nth(1).selectOption('merge');
 await flowPage.locator('[data-action="auto-graph-sync"]').click();
 const multiJson=JSON.parse(await flowPage.locator('[data-auto-form="workflow"] [name="graph_json"]').inputValue());
 const into=multiJson.edges.filter(([,to])=>to===newId).map(([from])=>from).sort();
 check('graph-editor-syncs-multi-upstream-edges',into.join(',')==='input,merge',{into});
 await flowPage.locator('[data-auto-form="workflow"] [data-action="close-dialog"]').first().click();
 await flowPage.evaluate(()=>location.hash='#module/agents');
 await flowPage.waitForSelector('[data-action="auto-new-agent"]');
 await flowPage.locator('[data-action="auto-new-agent"]').click();
 check('agent-dialog-has-workspace-binding',await flowPage.locator('[data-auto-form="agent"] [name="workspace_root"] option').count()===2&&await flowPage.locator('[data-auto-form="agent"] [name="workspace_write"] option').count()===2);
 await flowPage.locator('[data-auto-form="agent"] [data-action="close-dialog"]').first().click();
 await flowPage.evaluate(()=>location.hash='#module/workflows');
 await flowPage.waitForSelector('#compose-form');
 const compose=flowPage.locator('#compose-form');
 check('compose-template-options',await compose.locator('[name="template"] option').count()===2);
 await compose.locator('[name="goal"]').fill('给合成仓库加一个校验步骤');
 await compose.locator('[name="template"]').selectOption('code');
 await flowPage.locator('[data-action="auto-draft"]').click();
 await flowPage.waitForSelector('.draft-panel');
 const draftText=await flowPage.locator('.draft-panel').innerText();
 check('draft-panel-shows-agents-and-nodes',draftText.includes('planner')&&draftText.includes('demo')&&draftText.includes('Synthetic draft'));
 await flowPage.locator('#compose-feedback').fill('把审阅改成确认节点');
 await flowPage.locator('[data-action="auto-revise-draft"]').click();
 await flowPage.waitForSelector('.draft-diff');
 check('draft-revision-shows-structural-diff',(await flowPage.locator('.draft-diff').innerText()).includes('review'));
 await flowPage.locator('[data-action="auto-save-draft"]').click();
 await flowPage.waitForFunction(()=>!document.querySelector('.draft-panel'));
 check('confirm-saves-draft-once',writes.filter(x=>x.path==='automation/compose/save').length===1);
 const team=flowPage.locator('#team-form');
 check('team-form-available',await team.locator('[name="agent_ids"]').count()>=1&&await team.locator('[name="mode"] option').count()===2);
 await team.locator('[name="task"]').fill('评估候选人张三的能力缺口');
 await team.locator('[name="agent_ids"]').first().check();
 await team.locator('button[type="submit"]').click();
 await flowPage.waitForSelector('.team-turns');
 const teamText=await flowPage.locator('.team-turns').innerText();
 check('team-transcript-shows-turns',teamText.includes('缺口')&&teamText.includes('问题'));
 const teamCalls=writes.filter(x=>x.path==='automation/teams/run');
 check('team-run-sends-members-and-approval',teamCalls.length===1&&teamCalls[0].body.approved===false&&teamCalls[0].body.agent_ids.length===1);
 const loop=flowPage.locator('#loop-form');
 check('loop-form-fields',await loop.locator('[name="root"] option').count()>=1&&await loop.locator('[name="engine"] option').count()===3&&await loop.locator('[name="tier"] option').count()===3&&await loop.locator('[name="task"]').count()===1&&await loop.locator('[name="gate"]').count()===1);
 await loop.locator('[name="root"]').selectOption('demo');
 await loop.locator('[name="task"]').fill('修复求和函数对空列表的处理');
 await loop.locator('[name="gate"]').fill('python -m pytest tests/check.py -q');
 await loop.locator('[name="engine"]').selectOption('aider');
 await loop.locator('[name="tier"]').selectOption('feature');
 await loop.locator('button[type="submit"]').click();
 await flowPage.waitForSelector('.loop-result');
 const loopText=await flowPage.locator('.loop-result').innerText();
 check('loop-result-shows-rounds-and-diff',loopText.includes('第 2 轮')&&loopText.includes('git diff --stat')&&loopText.includes('50600'));
 const loopCalls=writes.filter(x=>x.path==='automation/loop/run');
 check('loop-run-sends-contract',loopCalls.length===1&&loopCalls[0].body.root==='demo'&&loopCalls[0].body.engine==='aider'&&loopCalls[0].body.tier==='feature'&&loopCalls[0].body.gate.includes('pytest'));
 const queue=flowPage.locator('#queue-form');
 check('queue-form-fields',await queue.locator('[name="kind"] option').count()===2&&await queue.locator('[name="root"] option').count()>=1&&await queue.locator('[name="task"]').count()===1&&await queue.locator('[name="gate"]').count()===1&&await queue.locator('[name="max_attempts"]').count()===1);
 check('queue-stats-render',(await flowPage.locator('.queue-stats').innerText()).includes('死信'));
 check('queue-list-renders-status-and-error',(await flowPage.locator('.queue-list').innerText()).includes('排队中')&&(await flowPage.locator('.queue-list').innerText()).includes('gate exited 1'));
 await queue.locator('[name="root"]').selectOption('demo');
 await queue.locator('[name="task"]').fill('把求和函数补上边界检查');
 await queue.locator('[name="gate"]').fill('python -m pytest tests/check.py -q');
 await queue.locator('[name="max_attempts"]').fill('2');
 await queue.locator('button[type="submit"]').click();
 await flowPage.waitForTimeout(150);
 const queueCalls=writes.filter(x=>x.path==='automation/queue');
 check('queue-enqueue-sends-contract',queueCalls.length===1&&queueCalls[0].body.kind==='loop'&&queueCalls[0].body.max_attempts===2&&queueCalls[0].body.payload.root==='demo'&&queueCalls[0].body.payload.gate.includes('pytest')&&queueCalls[0].body.payload.task.includes('边界检查'));
 await flowPage.locator('[data-action="auto-queue-detail"][data-id="job-queued-0001"]').click();
 await flowPage.waitForSelector('.queue-detail');
 const queueDetailText=await flowPage.locator('.queue-detail').innerText();
 check('queue-detail-shows-checkpoint',queueDetailText.includes('检查点')&&queueDetailText.includes('队列任务详情'));
 check('queue-detail-shows-payload',(await flowPage.locator('.queue-detail').textContent()).includes('修复求和'));
 await flowPage.locator('[data-action="auto-queue-cancel"][data-id="job-queued-0001"]').click();
 await flowPage.waitForTimeout(150);
 check('queue-cancel-calls-endpoint',writes.some(x=>x.path==='automation/queue/job-queued-0001/cancel'));
 await flowPage.locator('[data-action="auto-queue-replay"][data-id="job-dead-0000002"]').click();
 await flowPage.waitForTimeout(150);
 check('queue-replay-calls-endpoint',writes.some(x=>x.path==='automation/queue/job-dead-0000002/replay'));
 await flowPage.locator('[data-queue-filter]').selectOption('dead');
 await flowPage.waitForTimeout(150);
 check('queue-filter-narrows-list',(await flowPage.locator('.queue-job').count())===1&&(await flowPage.locator('.queue-list').innerText()).includes('gate exited 1'));
 await queue.locator('[name="kind"]').selectOption('team');
 await flowPage.waitForTimeout(120);
 check('queue-team-kind-hides-code-fields',await flowPage.locator('#queue-form [name="gate"]').count()===0&&await flowPage.locator('#queue-form [name="root"]').count()===0);
 await flowPage.evaluate(()=>location.hash='#module/runs');
 await flowPage.waitForSelector('.run-list [data-action="auto-open-run"]');
 await flowPage.locator('[data-action="auto-open-run"][data-id="run-team"]').click();
 await flowPage.waitForSelector('.team-turns');
 const teamDetail=await flowPage.locator('.run-result').innerText();
 check('team-run-detail-renders-turns',teamDetail.includes('团队运行')&&teamDetail.includes('缺口：缺少实验经验')&&teamDetail.includes('终稿'));
 await flowPage.locator('[data-action="auto-open-run"][data-id="run-loop"]').click();
 await flowPage.waitForSelector('.run-result .loop-attempts');
 const loopDetail=await flowPage.locator('.run-result').innerText();
 check('loop-run-detail-renders-summary',loopDetail.includes('自动编码')&&loopDetail.includes('第 2 轮')&&!loopDetail.includes('资料：undefined')&&await flowPage.locator('#ingest-confirm-form').count()===0);
 await flowPage.evaluate(()=>location.hash='#module/job-flow');
 await flowPage.waitForSelector('.job-flow__pages');
 await flowPage.locator('[data-action="jobflow-page"][data-page="prep"]').click();
 await flowPage.waitForSelector('#prep-generate-form');
 check('prep-page-has-three-modes',await flowPage.locator('[data-action="jobflow-prep-mode"]').count()===3);
 check('prep-practice-has-question-form-only',await flowPage.locator('.prep-turn').count()===0);
 await flowPage.locator('[data-action="jobflow-prep-mode"][data-mode="voice"]').click();
 const voiceText=await flowPage.locator('.job-flow__placeholder').innerText();
 check('prep-voice-mode-is-placeholder-only',voiceText.includes('等待接入')&&await flowPage.locator('#prep-generate-form').count()===0&&await flowPage.locator('.job-flow__placeholder button').count()===0);
 await flowPage.locator('[data-action="jobflow-prep-mode"][data-mode="practice"]').click();
 check('prep-returns-to-practice',await flowPage.locator('#prep-generate-form').count()===1);
 check('no-browser-page-errors',report.errors.length===0,{errors:report.errors});
 await flowPage.screenshot({path:path.join(out,'job-flow-desktop.png')});
 await flowPage.close();
 await page.close();
}catch(e){report.errors.push(e.stack||String(e));process.exitCode=1;}
finally{if(pending){try{pending();}catch{}}await browser.close();await new Promise(resolve=>server.close(resolve));fs.writeFileSync(path.join(out,'checks.json'),JSON.stringify(report,null,2)+'\n');}
for(const item of report.checks)console.log(item.name+': '+(item.ok?'PASS':'FAIL'));
console.log('DESKTOP_UX checks='+report.checks.length+' errors='+report.errors.length+' external='+report.external.length);
if(report.errors.length)console.error(report.errors.join('\n'));
if(report.external.length)process.exitCode=1;
