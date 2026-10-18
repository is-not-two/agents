async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const titles=['完成个人知识库与人生规划的第一版网页体验','梳理知识录入到检索回答的完整流程','检查多层任务展开、长标题与键盘操作','整理操作问题并完成一次可回滚的改版','提交截图与验证记录供下一轮交叉评审'];
 const nodes=titles.map((title,i)=>({id:'n'+i,title,parent_id:i?'n'+(i-1):'',done:false,priority:'p2',due_date:'',description:'',requires:[],state:'available'}));nodes.push({...nodes[0],id:'sibling',parent_id:'n1',title:'另一条分支：核对任务保存和刷新后的结果'});
 await page.route('**/api/plans',r=>r.fulfill({json:[{id:'experiment',version:1,data:{title:'把想法变成可以使用的作品',kind:'main',description:'',acts:[{id:'a',title:'任务',nodes}],progress:{done:0,total:6,percent:0}}}]}));
 const results=[];
 for(const variant of [{name:'baseline',indent:42,width:320},{name:'compact',indent:32,width:280}]){
  await page.route('**/tree.js?v=15',async route=>{const response=await route.fetch();let body=await response.text();body=body.replace('depth*42',`depth*${variant.indent}`).replace('n.x+380',`n.x+${variant.width+60}`);await route.fulfill({response,body});});
  for(const width of [1280,1440])for(const zoom of [80,100]){
   await page.setViewportSize({width,height:1050});await page.evaluate(z=>{localStorage.setItem('shilie-tree-folded','[]');localStorage.setItem('shilie-tree-zoom',JSON.stringify(z));localStorage.setItem('shilie-tree-kind','"main"');},zoom);await page.reload();await page.locator('.tree-root').waitFor();await page.addStyleTag({content:`.tree-item,.tree-node-select{width:${variant.width}px}`});
   const metrics=await page.evaluate(()=>{const v=document.querySelector('.tree-viewport');return {pageOverflow:document.documentElement.scrollWidth>innerWidth,canvasOverflow:v.scrollWidth-v.clientWidth,titles:[...document.querySelectorAll('.tree-node-select strong')].map(n=>({title:n.textContent,clipped:n.scrollHeight>n.clientHeight+1})),indent:document.querySelectorAll('.tree-item')[1].offsetLeft-document.querySelectorAll('.tree-item')[0].offsetLeft};});
   results.push({variant:variant.name,width,zoom,...metrics});if(width===1440&&zoom===100){await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:`output/web/round2-fixed-${variant.name}.png`,fullPage:true});}
  }
  await page.unroute('**/tree.js?v=15');
 }
 await page.getByRole('button',{name:'在 把想法变成可以使用的作品 下添加节点',exact:true}).click();await page.locator('#tree-editor').waitFor();await page.keyboard.press('Escape');await page.waitForTimeout(150);const escapeCloses=!await page.locator('#tree-editor').isVisible();
 await page.unroute('**/api/plans');await page.reload();await page.locator('.studio-heading').waitFor();
 const report={results,escapeCloses,errors,fixtureOnly:true};await page.evaluate(r=>localStorage.setItem('round2-fixed-results',JSON.stringify(r)),report);return report;
}
