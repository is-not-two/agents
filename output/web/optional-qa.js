async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 let nodes=[],saves=[];
 const row=()=>({id:'optional-fixture',version:1,data:{title:'学习与生活',kind:'main',description:'',progress:{done:0,total:nodes.length,percent:0},acts:[{id:'act',title:'任务',nodes}]}});
 await page.route('**/api/plans',r=>r.fulfill({json:[row()]}));
 await page.route('**/api/plans/optional-fixture/nodes**',async r=>{const data=r.request().postDataJSON().data;saves.push(data);if(r.request().method()==='POST')nodes.push({...data,id:'test-node',done:false,state:'available'});else Object.assign(nodes[0],data);await r.fulfill({status:200,json:row()});});
 await page.goto('http://127.0.0.1:8770/?v=15#module/planning');await page.reload();await page.locator('.tree-root').waitFor();
 await page.getByRole('button',{name:'在 学习与生活 下添加节点',exact:true}).click();const f=page.locator('#tree-edit-form');
 if(await f.locator('[name=due_date]').isVisible())throw Error('日期默认占用表单');
 if(await f.locator('[required]').count()!==1)throw Error('额外必填项');
 await f.locator('[name=title]').fill('读完一本书');await page.screenshot({path:'output/web/optional-entry.png',fullPage:true});
 await f.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#tree-editor').waitFor({state:'hidden'});if(saves[0].due_date!=='')throw Error('空日期保存失败');
 await page.getByRole('button',{name:'编辑节点',exact:true}).click();await f.locator('summary').click();await f.locator('[name=due_date]').fill('2027-01-01');await f.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#tree-editor').waitFor({state:'hidden'});
 await page.getByRole('button',{name:'编辑节点',exact:true}).click();await f.locator('summary').click();if(await f.locator('[name=due_date]').inputValue()!=='2027-01-01')throw Error('编辑丢日期');
 await f.getByRole('button',{name:'清除日期',exact:true}).click();await f.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#tree-editor').waitFor({state:'hidden'});if(saves.at(-1).due_date!=='')throw Error('清除失败');
 await page.reload();await page.locator('.tree-root').waitFor();await page.getByRole('button',{name:'查看节点：读完一本书',exact:true}).click();if(await page.locator('.tree-inspector').textContent().then(t=>t.includes('未设置')))throw Error('冗余提示');
 await page.setViewportSize({width:1366,height:1000});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'output/web/optional-layout.png',fullPage:true});
 await page.unroute('**/api/plans');await page.unroute('**/api/plans/optional-fixture/nodes**');await page.reload();
 if(errors.length)throw Error(errors.join(';'));return {titleOnly:true,optionalCollapsed:true,addDate:true,clearDate:true,reload:true,errors};
}
