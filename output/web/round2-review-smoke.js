async page=>{
 await page.goto('http://127.0.0.1:8770/?v=17#module/stages');await page.locator('[data-action=new-stage]').click();await page.locator('dialog[data-form=stage]').waitFor();await page.keyboard.press('Escape');if(await page.locator('dialog[data-form=stage]').isVisible())throw Error('阶段对话框Esc失败');
 await page.goto('http://127.0.0.1:8770/?v=17#module/knowledge');await page.locator('[data-action=new-note]').first().click();await page.locator('dialog[data-form=knowledge]').waitFor();await page.keyboard.press('Escape');if(await page.locator('dialog[data-form=knowledge]').isVisible())throw Error('知识对话框Esc失败');
 if(await page.locator('dialog[data-form=act],dialog[data-form=task],dialog[data-form=plan]').count())throw Error('旧表单残留');
 await page.emulateMedia({reducedMotion:'reduce'});await page.goto('http://127.0.0.1:8770/?v=17#module/planning');await page.locator('.studio-heading').waitFor();const transition=await page.locator('.tree-node-select').first().evaluate(e=>getComputedStyle(e).transitionDuration);if(transition!=='0s')throw Error('减少动画未生效');await page.emulateMedia({reducedMotion:'no-preference'});
 return {stageDialog:true,knowledgeDialog:true,escape:true,legacyDialogsAbsent:true,reducedMotion:true,readOnly:true};
}
