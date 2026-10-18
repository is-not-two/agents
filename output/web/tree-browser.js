async page => {
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 await page.setViewportSize({width:1440,height:1050});
 await page.getByRole('button',{name:'创建第一条主线',exact:true}).click();
 const form=page.locator('#tree-edit-form');
 await form.locator('[name=title]').fill('成为独立 AI 应用开发者');
 await form.locator('[name=description]').fill('从学习到交付，让每个目标都能拆成下一步。');
 await form.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#tree-editor').waitFor({state:'hidden'});
 async function add(parent,title){await page.getByRole('button',{name:`在 ${parent} 下添加节点`,exact:true}).click();await form.locator('[name=title]').fill(title);await form.getByRole('button',{name:'保存',exact:true}).click();await page.locator('#tree-editor').waitFor({state:'hidden'});}
 await add('成为独立 AI 应用开发者','夯实技术基础');await add('夯实技术基础','完成 Python 项目');await add('夯实技术基础','整理知识笔记');await add('成为独立 AI 应用开发者','交付一个完整作品');await add('交付一个完整作品','实现知识检索工作流');
 const before=await page.locator('.tree-item').count();
 await page.getByRole('button',{name:'收起 夯实技术基础',exact:true}).click();if(await page.locator('.tree-item').count()!==before-2)throw Error('折叠失败');
 await page.getByRole('button',{name:'展开 夯实技术基础',exact:true}).click();
 await page.getByRole('slider',{name:'画布缩放'}).fill('80');
 await page.getByRole('button',{name:'定位根节点',exact:true}).click();
 await page.reload();await page.locator('.tree-item').first().waitFor();
 if(await page.locator('.tree-item').count()!==6)throw Error('刷新数据丢失');
 if(await page.locator('#tree-zoom').inputValue()!=='80')throw Error('缩放未保持');
 await page.getByRole('button',{name:'查看节点：完成 Python 项目',exact:true}).click();
 await page.getByRole('button',{name:'标记完成',exact:true}).click();await page.waitForFunction(()=>document.querySelector('.tree-inspector')?.textContent.includes('撤销完成'));
 await page.evaluate(()=>window.scrollTo(0,0));await page.screenshot({path:'output/web/tree-desktop.png',fullPage:true});
 const result={nodes:6,fold:true,persist:true,zoom:80,complete:true,errors};
 await page.evaluate(r=>localStorage.setItem('tree-qa-result',JSON.stringify(r)),result);
 return result;
}
