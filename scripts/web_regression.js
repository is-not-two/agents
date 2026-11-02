/* Executed by playwright-cli against a UUID-verified disposable test server. */
async page=>{
 const base=__BASE_URL__,runId=__RUN_ID__,phase=__PHASE__;
 const check=(ok,message)=>{if(!ok)throw Error(message);};
 page.setDefaultTimeout(12000);
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const api=async(path,method='GET',body)=>page.evaluate(async({path,method,body})=>{
  const r=await fetch(path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined});
  const data=await r.json();if(!r.ok)throw Error(`${r.status}: ${data.detail}`);return data;
 },{path,method,body});
 // Every phase verifies identity before taking any action; never accept an arbitrary URL.
 if(!page.url().startsWith(base+'/'))await page.goto(base+'/#module/knowledge');
 check((await api('/__qa__/identity')).run_id===runId,'Unexpected server: abort regression');
 const go=async route=>{await page.goto(base+'/#'+route);};
 const editor=page.locator('dialog[data-form=knowledge]');
 const saveNote=()=>editor.getByRole('button',{name:'保存',exact:true}).click();

 if(phase==='core'){
  await page.setViewportSize({width:1440,height:1000});
  // Native confirmation is accepted inside the test page to avoid CLI modal handoff races.
  // The destructive API effects are separately asserted below.
  await page.addInitScript(()=>{window.confirm=()=>true;});
  await page.evaluate(()=>{window.confirm=()=>true;});
  await page.getByRole('button',{name:'新建笔记',exact:true}).click();
  await editor.locator('[name=title]').fill('回归笔记');
  await editor.locator('[name=content]').fill('验证创建、修改、刷新和历史版本。');
  await editor.locator('[name=tags]').fill('regression,test');
  await saveNote();await editor.waitFor({state:'hidden'});
  await page.getByRole('button',{name:'编辑',exact:true}).click();
  await editor.locator('[name=content]').fill('版本二：重启后仍然存在。');
  await saveNote();await editor.waitFor({state:'hidden'});await page.reload();
  await page.locator('.document').getByText('版本二：重启后仍然存在。',{exact:true}).waitFor();
  const notes=await api('/api/knowledge');
  const note=notes.find(n=>n.data.title==='回归笔记');
  check(note.version===2,'Knowledge version did not increase');
  check((await api(`/api/records/${note.id}/history`)).length===2,'Missing knowledge history');

  await go('module/planning');
  await page.getByRole('button',{name:'＋ 新建主线',exact:true}).click();
  const tree=page.locator('#tree-editor');await tree.locator('[name=title]').fill('主线一');
  await tree.locator('[type=submit]').click();await tree.waitFor({state:'hidden'});
  const card=title=>page.locator('.story-card').filter({has:page.locator('strong',{hasText:new RegExp('^'+title+'$')})});
  async function add(parent,title,kind){
   await card(parent).getByRole('button',{name:`在 ${parent} ${kind==='main'?'后添加主线':'下添加支线'}`,exact:true}).click();
   await tree.locator('[name=title]').fill(title);await tree.locator('[type=submit]').click();
   await tree.waitFor({state:'hidden'});await card(title).waitFor();
  }
  await add('主线一','主线二','main');await add('主线二','主线三','main');
  await add('主线二','主线四','main');await add('主线三','主线五','main');
  await add('主线二','支线一','side');await add('主线二','支线二','side');
  await card('主线二').locator('.story-title').dblclick();await tree.waitFor({state:'visible'});
  check(await page.locator('.story-card').count()===7,'Double click collapsed tree');
  await tree.getByRole('button',{name:'取消',exact:true}).click();
  await card('主线二').locator('.story-title').click();await card('主线三').waitFor({state:'detached'});
  await card('主线二').locator('.story-title').click();await card('主线三').waitFor();
  await page.getByRole('button',{name:'完成 主线一',exact:true}).click();
  await page.getByRole('button',{name:'撤销完成 主线一',exact:true}).waitFor();
  check(await page.getByRole('progressbar',{name:'主线一 完成进度',exact:true}).getAttribute('aria-valuenow')==='14','Wrong aggregate progress');
  await page.getByRole('button',{name:'删除 主线四',exact:true}).click();
  await page.getByRole('button',{name:'确认删除',exact:true}).click();
  await card('主线四').waitFor({state:'detached'});
  await page.getByRole('button',{name:'撤销删除',exact:true}).click();await card('主线四').waitFor();
  await page.locator('#story-auto').check();await page.locator('#story-zoom').fill('140');
  await page.locator('#story-zoom').dispatchEvent('change');
  await card('主线三').locator('.story-title').click();
  await page.waitForFunction(()=>{
   const a=document.querySelector('.story-viewport').getBoundingClientRect(),b=document.querySelector('.story-card.selected')?.getBoundingClientRect();
   return b&&Math.abs(b.x+b.width/2-a.x-a.width/2)<2&&Math.abs(b.y+b.height/2-a.y-a.height/2)<2;
  });
  await page.reload();await card('主线一').waitFor();check(await page.locator('.story-card').count()===6,'Fold preference was not preserved');

  // MODEL_RELOAD_REGRESSION_START
  await go('module/connections');
  const modelForm=page.locator('#model-connection-form');await modelForm.waitFor();
  await modelForm.locator('[name=base_url]').fill('https://fixture.invalid/v1');
  await modelForm.locator('[name=model]').fill('regression-unsaved-model');
  await modelForm.locator('[name=api_key]').fill('fixture-reload-draft-key');
  const rejectModelReload=async route=>{
   if(route.request().method()==='GET')await route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'Regression reload unavailable'})});
   else await route.continue();
  };
  await page.route('**/api/model-connection',rejectModelReload,{times:1});
  try{
   const modelReloadResponse=page.waitForResponse(r=>r.url().endsWith('/api/model-connection')&&r.request().method()==='GET');
   await modelForm.getByRole('button',{name:'重新加载',exact:true}).click();
   check((await modelReloadResponse).status()===503,'Model reload fault did not reach browser');
   await page.waitForFunction(()=>document.querySelector('#model-connection-feedback')?.textContent.includes('Regression reload unavailable'));
   check(await modelForm.locator('[name=base_url]').inputValue()==='https://fixture.invalid/v1','Failed reload lost draft API URL');
   check(await modelForm.locator('[name=model]').inputValue()==='regression-unsaved-model','Failed reload lost draft model');
   check(await modelForm.locator('[name=api_key]').inputValue()==='fixture-reload-draft-key','Failed reload lost draft key');
   check(await modelForm.locator('#model-connection-feedback').isVisible(),'Failed reload hid error');
   check(!await modelForm.getByRole('button',{name:'保存连接',exact:true}).isDisabled(),'Failed reload did not restore save button');
   check(await modelForm.getAttribute('aria-busy')==='false','Failed reload left form busy');
   check(!await page.evaluate(()=>JSON.stringify({...localStorage,...sessionStorage}).includes('fixture-reload-draft-key')),'Model key leaked into browser storage');
  }finally{await page.unroute('**/api/model-connection',rejectModelReload);}
  // MODEL_RELOAD_REGRESSION_END

  await go('module/workflows');await page.getByRole('button',{name:/启用基础流程/}).click();
  await page.locator('.workflow-list button').filter({has:page.locator('small',{hasText:'知识处理'})}).click();
  const flow=page.locator('#workflow-execute-form');await flow.locator('[name=title]').fill('回归资料');
  await flow.locator('[name=content]').fill('# 标题\n\n确认后才写入知识库。');
  await page.getByRole('button',{name:'解析并预览',exact:true}).click();
  await page.getByRole('button',{name:'确认选中片段入库',exact:true}).click();
  await page.getByText('已保存 1 条知识。',{exact:false}).first().waitFor();
  // REGRESSION: failed confirmation must not reselect unchecked chunks.
  const knowledgeBeforeRetry=(await api('/api/knowledge')).length;
  await flow.locator('[name=title]').fill('失败重试隔离资料');
  await flow.locator('[name=content]').fill('# 不应入库\n未选中的合成片段。\n# 应当入库\n用户选中的合成片段。');
  await page.getByRole('button',{name:'解析并预览',exact:true}).click();
  await page.locator('#ingest-confirm-form [name=selected]').first().uncheck();
  await page.route('**/api/workflow-runs/*/confirm',route=>route.fulfill({status:503,contentType:'application/json',body:JSON.stringify({detail:'回归演练：确认暂不可用'})}),{times:1});
  await page.getByRole('button',{name:'确认选中片段入库',exact:true}).click();
  await page.getByRole('status').filter({hasText:'回归演练：确认暂不可用'}).waitFor();
  check(!await page.locator('#ingest-confirm-form [name=selected]').first().isChecked(),'Failed confirmation reselected an unchecked chunk');
  check(await page.locator('#ingest-confirm-form [name=selected]').last().isChecked(),'Failed confirmation lost a checked chunk');
  check(!await page.getByRole('button',{name:'确认选中片段入库',exact:true}).isDisabled(),'Failed confirmation cannot be retried');
  check((await api('/api/knowledge')).length===knowledgeBeforeRetry,'Failed confirmation wrote knowledge');
  await page.getByRole('button',{name:'确认选中片段入库',exact:true}).click();
  await page.locator('.run-badge.confirmed').waitFor();
  const knowledgeAfterRetry=await api('/api/knowledge');
  check(knowledgeAfterRetry.length===knowledgeBeforeRetry+1&&knowledgeAfterRetry.some(r=>r.data.title==='应当入库')&&!knowledgeAfterRetry.some(r=>r.data.title==='不应入库'),'Retry saved the wrong selection');
  // END confirmation retry regression.
  await page.locator('.workflow-list button').filter({has:page.locator('small',{hasText:'检索与回答'})}).click();
  await page.locator('#workflow-execute-form [name=query]').fill('重启');
  await page.getByRole('button',{name:'执行检索流程',exact:true}).click();
  await page.locator('.run-citations details').first().waitFor();

  await go('module/private');await page.locator('#private-gate-form [name=password]').fill('regression-only-password');
  await page.locator('#private-gate-form button').click();await page.getByRole('button',{name:'我已保存',exact:true}).click();
  await page.getByRole('button',{name:'＋ 添加愿望',exact:true}).click();
  let d=page.locator('dialog[open]').filter({has:page.locator('[name=category]')});
  await d.locator('[name=title]').fill('回归愿望');await d.getByRole('button',{name:'保存',exact:true}).click();
  await d.waitFor({state:'detached'});await page.getByTitle('标记完成',{exact:true}).click();
  await page.locator('.wish-card.is-done').waitFor();
  await page.getByRole('button',{name:'私密日记',exact:true}).click();
  await page.getByRole('button',{name:'＋ 写一篇',exact:true}).click();
  d=page.locator('dialog[open]').filter({has:page.locator('[name=content]')});
  await d.locator('[name=title]').fill('回归日记');await d.locator('[name=content]').fill('隔离内容');
  await d.getByRole('button',{name:'保存',exact:true}).click();await d.waitFor({state:'detached'});
  await page.getByTitle('删除',{exact:true}).click();await page.locator('.diary-card').waitFor({state:'detached'});
  await page.getByRole('button',{name:'锁定',exact:true}).click();
  // Resize an already-bound slider; a fresh mobile page would miss stale travel geometry.
  await page.setViewportSize({width:390,height:844});
  const thumb=await page.locator('.slide-thumb').boundingBox(),track=await page.locator('.slide-track').boundingBox();
  async function drag(fraction){await page.mouse.move(thumb.x+thumb.width/2,thumb.y+thumb.height/2);await page.mouse.down();
   await page.mouse.move(thumb.x+thumb.width/2+(track.width-thumb.width)*fraction,thumb.y+thumb.height/2,{steps:10});
   const after=await page.locator('.slide-thumb').boundingBox();check(Math.abs(after.y-thumb.y)<1,'Slider moved vertically while pressed');await page.mouse.up();}
  await drag(.4);await page.waitForFunction(()=>document.querySelector('.slide-thumb')?.getAttribute('aria-valuenow')==='0');
  await drag(1);await page.locator('.private-tabs').waitFor();
  await page.setViewportSize({width:1440,height:1000});

  // Keep a private wish present while testing public backup round-tripping.
  const snapshot=await api('/api/export?format=json');
  check(snapshot.records.every(r=>!['wish','diary'].includes(r.kind)),'Public backup contains private records');
  await api('/api/knowledge','POST',{data:{title:'备份后的新条目',content:'恢复时移入回收站'}});
  await go('module/backup');
  await page.locator('.backup-file-limit').filter({hasText:'文件大小上限'}).waitFor();
  await page.locator('#backup-file').setInputFiles({name:'regression.json',mimeType:'application/json',buffer:Buffer.from(JSON.stringify(snapshot))});
  await page.locator('.backup-file-name').filter({hasText:'regression.json'}).waitFor();
  await page.getByRole('button',{name:'预览恢复内容',exact:true}).click();
  const restore=page.locator('#backup-restore-form');await restore.waitFor();
  check(!await restore.locator('[name=confirmed]').isChecked(),'Restore confirmation unexpectedly checked');
  await restore.locator('[name=confirmed]').check();await restore.getByRole('button',{name:'确认恢复',exact:true}).click();
  await page.locator('.backup-result').waitFor();
  check(!(await api('/api/knowledge')).some(n=>n.data.title==='备份后的新条目'),'Backup restore did not remove extra note');
  await go('module/private');await page.locator('.slide-thumb').waitFor();
  await page.locator('.slide-thumb').press('End');await page.locator('.private-tabs').waitFor();
  await page.getByRole('button',{name:/愿望清单/}).click();await page.locator('.wish-card').waitFor();
  check(await page.locator('.wish-card').count()===1,'Public restore changed private wish');
  await page.setViewportSize({width:390,height:844});await go('module/knowledge');
  check(await page.evaluate(()=>document.documentElement.scrollWidth)<=390,'Page overflows mobile viewport');
 }

 if(phase==='prepare-failure'){
  await go('module/knowledge');await page.reload();await page.getByRole('button',{name:'新建笔记',exact:true}).click();
  await editor.locator('[name=title]').fill('断连时保留输入');await editor.locator('[name=content]').fill('数据库恢复后保存这份草稿。');
 }
 if(phase==='database-offline'){
  await saveNote();await page.getByRole('status').filter({hasText:'数据库暂不可用'}).waitFor();
  check(await editor.isVisible(),'Failed save dismissed draft');
  check(await editor.locator('[name=title]').inputValue()==='断连时保留输入','Failed save lost input');
  const health=await page.evaluate(async()=>{const r=await fetch('/health');const d=await r.json();return {status:r.status,detail:d.detail};});
  check(health.status===503&&!health.detail.includes('password'),'DB outage was not sanitized 503');
 }
 if(phase==='database-recovered'){
  await saveNote();await editor.waitFor({state:'hidden'});
  await page.locator('.document h2').filter({hasText:'断连时保留输入'}).waitFor();
  check((await api('/api/knowledge')).filter(n=>n.data.title==='断连时保留输入').length===1,'Retry duplicated draft');
 }
 if(phase==='application-restarted'){
  await page.reload();await page.locator('.document').waitFor();
  check((await api('/api/knowledge')).some(n=>n.data.title==='断连时保留输入'),'Application restart lost note');
  await go('module/private');await page.locator('#private-unlock-password').waitFor();
  await page.locator('#private-unlock-password').fill('regression-only-password');
  await page.locator('.slide-thumb').press('End');await page.locator('.private-tabs').waitFor();
  await page.getByRole('button',{name:/愿望清单/}).click();await page.locator('.wish-card').waitFor();
 }
 check(errors.length===0,'Browser error: '+errors.join('; '));
 return {passed:true,phase};
}
