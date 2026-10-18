async (page) => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.goto('http://127.0.0.1:8773/#module/planning/story');await page.reload();
 const existing=await page.request.get('http://127.0.0.1:8773/api/plans');for(const row of await existing.json())await page.request.delete(`http://127.0.0.1:8773/api/records/${row.id}?version=${row.version}`);await page.reload();
 await page.getByRole('button',{name:'创建规划',exact:true}).click();
 let d=page.locator('.form-dialog[open]');
 await d.locator('[name=title]').fill('职业成长主线');await d.locator('[name=description]').fill('从基础到交付');await d.getByRole('button',{name:'保存',exact:true}).click();await d.waitFor({state:'hidden'});
 await page.locator('.storyline [data-action=new-act]').click();d=page.locator('.form-dialog[open]');await d.locator('[name=title]').fill('基础篇');await d.locator('[name=description]').fill('完成基础训练');await d.getByRole('button',{name:'保存',exact:true}).click();await d.waitFor({state:'hidden'});
 if(!await page.locator('.story-chapter').innerText().then(t=>t.includes('待编排')))throw Error('empty chapter state');
 await page.locator('[data-action=new-task-act]').click();d=page.locator('.form-dialog[open]');await d.locator('[name=title]').fill('学习 Python');await d.locator('[name=description]').fill('记录学习要点');await d.locator('[name=due_date]').fill('2026-11-01');await d.getByRole('button',{name:'保存',exact:true}).click();await d.waitFor({state:'hidden'});
 await page.locator('[data-action=new-task-act]').click();d=page.locator('.form-dialog[open]');await d.locator('[name=title]').fill('交付检索项目');await d.locator('[name=requires]').selectOption({label:'学习 Python'});await d.getByRole('button',{name:'保存',exact:true}).click();await d.waitFor({state:'hidden'});
 const second=page.locator('.story-task').filter({hasText:'交付检索项目'});await second.locator('summary').click();if(!await second.locator('[data-action=toggle-task]').isDisabled())throw Error('locked can complete');
 const first=page.locator('.story-task').filter({hasText:'学习 Python'}).first();await first.locator('summary').click();await first.locator('[data-action=toggle-task]').click();await page.waitForFunction(()=>document.querySelector('.story-task.done')&&!document.querySelector('.story-task-actions button[disabled][data-action=toggle-task]')); 
 if(await page.locator('.story-task').filter({hasText:'交付检索项目'}).locator('[data-action=toggle-task]').isDisabled())throw Error('not unlocked');
 const chapter=page.locator('.story-chapter');await chapter.locator(':scope>summary').click();await page.reload();await page.waitForSelector('.story-chapter');if(await page.locator('.story-chapter').getAttribute('open')!==null)throw Error('collapse not persisted');
 await page.locator('.story-chapter>summary').click();await page.locator('[data-action=edit-act]').click();d=page.locator('.form-dialog[open]');await d.locator('[name=description]').fill('阶段目标已更新');await d.getByRole('button',{name:'保存',exact:true}).click();await d.waitFor({state:'hidden'});
 if(!await page.locator('.chapter-description').innerText().then(t=>t==='阶段目标已更新'))throw Error('chapter edit');
 const layout=[];for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});const ok=await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth);if(!ok)throw Error('overflow '+width);layout.push(width);}
 await page.setViewportSize({width:1440,height:1000});await page.evaluate(()=>scrollTo(0,0));await page.screenshot({path:'output/web/story-desktop.png',fullPage:true});
 await page.evaluate(value=>localStorage.setItem('qa-story-report',JSON.stringify(value)),{hierarchy:true,emptyChapter:true,chapterEdit:true,dependencyUnlock:true,collapseReload:true,dueDate:true,widths:layout,errors});if(errors.length)throw Error('script errors');
}
