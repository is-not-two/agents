/* Real desktop browser, actual source modules, synthetic HTTP only. */
import fs from 'node:fs';
import path from 'node:path';
import http from 'node:http';
import {fileURLToPath} from 'node:url';
import {loadPlaywright} from './playwright-runtime.mjs';
const root=path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const dir=path.resolve(process.env.SHILIE_UI_DIR||path.join(root,'src/rag_tech_retriever/api/static/shilie'));
const out=path.resolve(process.env.UX_CHECK_OUT||path.join(root,'output/sidebar-navigation-check'));
fs.mkdirSync(out,{recursive:true});
const writes=[],agent={id:'ux-agent',version:1,data:{title:'Synthetic assistant',generate:true,scopes:['knowledge'],tool_ids:['knowledge_draft'],skill_ids:[],mcp_server_ids:[],model:{},budget:{},context:{max_messages:20},memory:{scope:'none'}}};
const leads=Array.from({length:20},(_,i)=>({id:'lead-'+i,kind:'job_lead',version:1,data:{title:'Synthetic job '+i,company:'Synthetic company',jd_text:'Fixture only',source_url:''}}));
const app={id:'application-0',kind:'application',version:1,data:{title:'Synthetic follow-up',lead_id:'lead-0',status:'following',follow_up_at:'2026-11-01T00:00:00Z'}};
const report={checks:[],errors:[],external:[]};
const send=(res,status,value)=>{res.writeHead(status,{'Content-Type':'application/json'});res.end(JSON.stringify(value));};
const server=http.createServer(async(req,res)=>{
 const u=new URL(req.url,'http://localhost');
 if(u.pathname.startsWith('/api/')){
  let raw='';for await(const chunk of req)raw+=chunk;const body=raw?JSON.parse(raw):{};const n=u.pathname.slice(5);
  if(req.method!=='GET')writes.push({path:n,method:req.method,body});
  if(n==='session')return send(res,200,{required:false,authenticated:true,account_login:false});
  if(n==='learning/cards')return send(res,200,{cards:[],due_ids:[]});
  if(n==='notifications')return send(res,200,{settings:{enabled:false,configured:false},notifications:[]});
  if(n==='notifications/daily-preview')return send(res,200,{body:'Synthetic preview'});
  if(n==='jobs/report/weekly')return send(res,503,{detail:'No weekly fixture'});
  if(n==='knowledge')return send(res,200,[]);
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
const check = (name, ok) => report.checks.push({name, ok: Boolean(ok)});
const openHash = async (page, hash) => {
  await page.evaluate(value => { location.hash = value; }, hash);
  await page.waitForFunction(value => location.hash === value, hash);
};
try {
  for (const oldMode of ['portal', 'sidebar']) {
    const page = await browser.newPage({viewport: {width: 1440, height: 960}});
    await page.addInitScript(mode => {
      localStorage.setItem('shilie-mode', JSON.stringify(mode));
    }, oldMode);
    page.on('pageerror', e => report.errors.push(e.stack || e.message));
    page.on('request', r => { if (!r.url().startsWith(origin+'/')) report.external.push(r.url()); });
    await page.goto(origin+'/#home', {waitUntil: 'domcontentloaded'});
    await page.locator('.sl-orbit__hub').waitFor({timeout: 12000});
    const start = await page.evaluate(() => ({
      layout: document.documentElement.dataset.layout,
      ringLinks: [...document.querySelectorAll('.sl-orbit__node')].map(a => [a.getAttribute('href'), a.getAttribute('aria-label')]),
      wall: Boolean(document.querySelector('#home-wallpaper video')),
    }));
    const sidebar = page.locator('#sidebar');
    check(oldMode+': start kept without sidebar', start.layout === 'portal' && start.ringLinks.length === 10 && start.wall && !await sidebar.isVisible());
    await page.locator('.sl-orbit__hub').click();
    await page.waitForFunction(() => location.hash === '#home/workspace');
    await page.locator('.home-main').waitFor();
    const workbenchSidebar = await sidebar.isVisible();
    check(oldMode+': workbench uses sidebar', workbenchSidebar);
    check(oldMode+': no header mode chooser', await page.locator('.layout-menu, button[data-mode]').count() === 0);
    report[oldMode] = {start, workbenchSidebar};
    if (oldMode === 'portal') {
      const entries = await sidebar.locator('a[href^="#module/"]').evaluateAll(links => links.map(a => a.getAttribute('href')));
      const {modules} = await page.evaluate(async () => {
        const moduleUrl = performance.getEntriesByType('resource').find(e => new URL(e.name).pathname.endsWith('/data.js'))?.name;
        return {modules: (await import(moduleUrl)).modules};
      });
      report.moduleCount = entries.length;
      report.parents = [];
      for (const href of entries) {
        const link = sidebar.locator(`a[href="${href}"]`);
        if (await link.isVisible()) await link.click(); else await openHash(page, href);
        await page.waitForFunction(value => location.hash === value && document.querySelector('#content')?.dataset.module === value.split('/')[1], href);
        const parent = '#category/' + modules.find(m => '#module/'+m.id === href).group;
        check(href+': sidebar stays visible', await sidebar.isVisible());
        await page.locator('#navigation-strip [data-action="back"]').click();
        await page.waitForFunction(value => location.hash === value, parent);
        await page.waitForFunction(() => document.querySelector('#content')?.dataset.module === '');
        report.parents.push([href, parent]);
        check(href+': valid parent with sidebar', await sidebar.isVisible());
      }
      await openHash(page, '#module/knowledge/notes');
      await page.locator('#navigation-strip [data-action="back"]').click();
      await page.waitForFunction(() => location.hash === '#module/knowledge');
      check('subpage returns to module', true);
      await openHash(page, '#category/workspace');
      await page.locator('#navigation-strip [data-action="back"]').click();
      await page.waitForFunction(() => ['#home', '#home/workspace'].includes(location.hash));
      check('category returns to workbench', await page.evaluate(() => location.hash) === '#home/workspace');
      await openHash(page, '#module/appearance');
      await page.locator('#density-range').waitFor();
      check('no settings mode chooser', await page.locator('#mode-select').count() === 0);
      check('sidebar home targets workbench', await sidebar.locator(':scope > a.nav-link').getAttribute('href') === '#home/workspace');
      check('breadcrumb targets workbench', await page.locator('#position a').first().getAttribute('href') === '#home/workspace');
      if (workbenchSidebar && await sidebar.locator(':scope > a.nav-link').getAttribute('href') === '#home/workspace') {
        await sidebar.locator(':scope > a.nav-link').click();
        await page.locator('.home-main').waitFor();
        await page.goBack();
        await page.locator('#density-range').waitFor();
        check('browser Back returns to appearance with sidebar', await sidebar.isVisible());
        await page.goForward();
        await page.locator('.home-main').waitFor();
        check('browser Forward returns to workbench with sidebar', await sidebar.isVisible());
        await openHash(page, '#module/appearance');
        await page.locator('#density-range').waitFor();
      }
      await page.locator('#navigation-strip a[href="#home"]').click();
      await page.locator('.sl-orbit__hub').waitFor();
      check('explicit start link still works', await page.evaluate(() => location.hash) === '#home');
    }
    await page.close();
  }

  const page = await browser.newPage({viewport: {width: 1440, height: 960}});
  page.on('pageerror', e => report.errors.push(e.stack || e.message));
  page.on('request', r => { if (!r.url().startsWith(origin+'/')) report.external.push(r.url()); });
  await page.goto(origin+'/#module/agents', {waitUntil: 'domcontentloaded'});
  await page.locator('#navigation-strip [data-action="back"]').waitFor();
  const sidebar = page.locator('#sidebar');
  const group = sidebar.locator('details[data-sidebar-group="automation"]');
  const workspace = sidebar.locator('details[data-sidebar-group="workspace"]');
  const settings = sidebar.locator('details[data-sidebar-group="settings"]');
  const branch = group.locator('a[href="#module/agents"]');
  const button = group.locator('summary');
  check('four categories expose disclosure controls', await sidebar.locator('details[data-sidebar-group] > summary').count() === 4);
  if (await button.count()) {
    const route = await page.evaluate(() => location.hash);
    await page.evaluate(() => { window.sameContent = document.querySelector('#content').lastElementChild; });
    const width = (await sidebar.boundingBox()).width;
    check('automation starts expanded', await branch.isVisible());
    await button.click();
    check('automation branches hide on click', !await branch.isVisible());
    check('other categories remain expanded', await workspace.locator('a[href="#module/knowledge"]').isVisible()
      && await settings.locator('a[href="#module/appearance"]').isVisible());
    check('collapse retains sidebar width, route and mounted content',
      (await sidebar.boundingBox()).width === width && await page.evaluate(hash =>
        location.hash === hash && window.sameContent === document.querySelector('#content').lastElementChild, route));
    await button.click();
    check('same header expands branches again', await branch.isVisible());
    await button.focus();
    await page.keyboard.press('Space');
    check('keyboard toggles category', !await branch.isVisible());
    await page.waitForFunction(() => JSON.parse(localStorage.getItem('shilie-closed-sidebar-groups') || '[]').includes('automation'));
    await page.reload({waitUntil:'domcontentloaded'});
    await button.waitFor();
    check('closed category persists across reload', !await branch.isVisible());
    check('other category remains open after reload', await workspace.locator('a[href="#module/knowledge"]').isVisible());
    await button.press('Enter');
    check('keyboard can reopen the category', await branch.isVisible());
    await group.locator('a[href="#module/workflows"]').click();
    await page.waitForFunction(() => location.hash === '#module/workflows');
    check('reopened branch navigates normally', await group.locator('a[href="#module/workflows"]').isVisible());
  }
  await page.close();
} catch (e) { report.errors.push(e.stack || String(e)); }
finally {
  await browser.close();
  await new Promise(resolve => server.close(resolve));
  report.writes = writes.length;
  fs.writeFileSync(path.join(out, 'sidebar-navigation.json'), JSON.stringify(report, null, 2)+'\n');
}
const failed = report.checks.filter(x => !x.ok);
console.log(JSON.stringify({checks: report.checks.length, failed: failed.length, examples: failed.slice(0, 4).map(x => x.name), modules: report.moduleCount, errors: report.errors, external: report.external.length, writes: writes.length}));
if (failed.length || report.errors.length || report.external.length || writes.length) process.exitCode = 1;
