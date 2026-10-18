async(page)=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setViewportSize({width:1440,height:960});
 await page.goto('http://127.0.0.1:8771/#home');await page.evaluate(()=>localStorage.clear());await page.goto('http://127.0.0.1:8771/#module/planning/tasks');
 await page.getByRole('button',{name:'创建规划'}).click();
 const p=page.locator('.form-dialog[data-form="plan"]');
 await p.locator('[name=title]').fill('Demo 人生主线');
 await p.locator('[name=description]').fill('验证任务创建、优先级与依赖关系。');
 await p.getByRole('button',{name:'保存',exact:true}).click();
 await page.getByRole('heading',{name:'Demo 人生主线'}).waitFor();
 await page.getByRole('button',{name:'添加任务'}).click();
 const t=page.locator('.form-dialog[data-form="task"]');
 await t.locator('[name=title]').fill('完成第一步');
 await t.locator('[name=actTitle]').fill('准备阶段');
 await t.locator('[name=priority]').selectOption('p0');
 await t.getByRole('button',{name:'保存',exact:true}).click();
 await page.locator('.task-main').filter({hasText:'完成第一步'}).waitFor();
 const firstId=await page.locator('.task-main').first().getAttribute('data-id');
 await page.getByRole('button',{name:'添加任务'}).click();
 const t2=page.locator('.form-dialog[data-form="task"]');
 await t2.locator('[name=title]').fill('完成第二步');
 await t2.locator('[name=actTitle]').fill('执行阶段');
 await t2.locator('[name=priority]').selectOption('p1');
 await t2.locator('[name=requires]').selectOption(firstId);
 await t2.getByRole('button',{name:'保存',exact:true}).click();
 await page.locator('.task-main').filter({hasText:'完成第二步'}).waitFor();
 await page.locator('#task-filter').selectOption('locked');
 if(await page.locator('.task-card').count()!==1)throw Error('依赖状态筛选错误');
 await page.locator('#task-filter').selectOption('all');
 await page.locator('.task-main').filter({hasText:'完成第一步'}).waitFor();
 await page.locator('.task-check').first().click();
 await page.waitForFunction(()=>[...document.querySelectorAll('.task-card')].some(e=>e.innerText.includes('完成第二步')&&e.innerText.includes('可开始')));
 await page.getByRole('link',{name:'依赖关系',exact:true}).click();
 await page.locator('.graph-node').first().waitFor();
 if(await page.locator('.graph-node').count()!==2)throw Error('依赖图未显示两个独立任务');
 await page.locator('.graph-node').nth(1).click();
 await page.locator('#detail-dialog').waitFor({state:'visible'});
 await page.getByRole('button',{name:'关闭详情'}).click();await page.getByRole('button',{name:'返回上一页'}).click();
 await page.waitForURL('**/#module/planning/tasks');
 await page.goto('http://127.0.0.1:8771/#module/stages');
 await page.getByRole('button',{name:'记录新阶段'}).click();
 const st=page.locator('.form-dialog[data-form="stage"]');
 await st.locator('[name=title]').fill('Demo 阶段记录');
 await st.locator('[name=objective]').fill('检查记录与验证工作流');
 await st.getByRole('button',{name:'保存',exact:true}).click();
 await page.getByText('Demo 阶段记录').waitFor();
 await page.locator('.stage-list details').filter({hasText:'Demo 阶段记录'}).locator('summary').click();
 await page.getByRole('button',{name:'记录完成结果'}).click();
 const sf=page.locator('#finish-stage-form');
 await sf.locator('[name=completed]').fill('知识录入可保存\n任务依赖可验证');
 await sf.locator('[name=verification]').fill('隔离数据库浏览器流程通过');
 await sf.getByRole('button',{name:'保存阶段结果'}).click();
 await page.getByText('验证通过').first().waitFor();
 if(errors.length)throw Error(JSON.stringify(errors));
 return{status:'passed',plan:'PostgreSQL save',tasks:2,dependency:'derived and filtered',graph:2,stage:'created and finished',errors};
}



