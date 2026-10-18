async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:1366,height:1000});
 await page.locator('#content>#navigation-strip').waitFor();
 const backCount=await page.locator('[data-action="back"]').count();if(backCount!==1)throw Error('重复返回');
 const black=await page.locator('.topbar').evaluate(e=>getComputedStyle(e).backgroundColor);if(black!=='rgb(0, 0, 0)')throw Error('顶栏非黑色');
 await page.locator('.global-back').click();await page.waitForFunction(()=>location.hash==='#category/automation');
 let nodes=[{id:'main',title:'学习 Python',parent_id:'',priority:'p2',requires:[],description:'',due_date:'',done:false,state:'available'},{id:'child',title:'做一个小项目',parent_id:'main',priority:'p2',requires:[],description:'',due_date:'',done:false,state:'available'}];
 const row=()=>({id:'ui-fixture',version:1,data:{title:'今年的目标',kind:'main',description:'',progress:{done:0,total:nodes.length,percent:0},acts:[{id:'act',title:'任务',nodes}]}});
 let saved=null;
 await page.route('**/api/plans',r=>r.fulfill({json:[row()]}));
 await page.route('**/api/plans/ui-fixture/nodes',async r=>{saved=r.request().postDataJSON().data;nodes.push({...saved,id:'new-child',done:false,state:'available'});await r.fulfill({status:201,json:row()});});
 await page.goto('http://127.0.0.1:8770/?v=14#module/planning');await page.reload();await page.locator('.tree-item').first().waitFor();
 const main=page.getByRole('button',{name:'查看节点：学习 Python',exact:true}),child=page.getByRole('button',{name:'查看节点：做一个小项目',exact:true});
 const a=await main.boundingBox(),b=await child.boundingBox();if(b.y<=a.y)throw Error('子节点未在下方');
 await main.click();if(await child.count())throw Error('点击未收起');await main.click();await child.waitFor();
 await page.getByRole('button',{name:'在 学习 Python 下添加节点',exact:true}).click();
 const f=page.locator('#tree-edit-form');if(await f.locator('[name=parent_id]').isVisible())throw Error('仍显示父节点');
 if(!await page.locator('#tree-add-context').textContent().then(t=>t.includes('学习 Python')))throw Error('添加位置不清楚');
 await f.locator('[name=title]').fill('写一份练习');await f.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#tree-editor').waitFor({state:'hidden'});if(saved.parent_id!=='main')throw Error('添加归属错误');
 await page.getByRole('button',{name:'回到开头',exact:true}).click();await page.screenshot({path:'output/web/simple-planning.png',fullPage:true});
 await page.unroute('**/api/plans');await page.unroute('**/api/plans/ui-fixture/nodes');await page.reload();await page.locator('.studio-heading').waitFor();
 if(errors.length)throw Error(errors.join(';'));
 return {backCount,backNavigation:true,black,childBelow:true,clickExpandCollapse:true,automaticParent:true,errors,scope:'Browser fixtures only; no personal records written'};
}
