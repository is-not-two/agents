async page => {
 const layouts=[],errors=[];page.on('pageerror',e=>errors.push(e.message));
 for(const mode of ['portal','sidebar']){
  await page.goto('http://127.0.0.1:8773/');await page.evaluate(mode=>localStorage.setItem('shilie-mode',JSON.stringify(mode)),mode);await page.reload();
  for(const route of ['planning/story','planning/tasks','planning/relations','workflows','agents','runs']){
   await page.goto('http://127.0.0.1:8773/#module/'+route);await page.waitForSelector('#content .back-button');
   for(const width of [1440,390,320]){await page.setViewportSize({width,height:1000});if(!await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth))throw Error('overflow '+mode+' '+route+' '+width);layouts.push({mode,route,width});}
  }
 }
 await page.setViewportSize({width:1440,height:1000});await page.goto('http://127.0.0.1:8770/?v=12#module/planning/story');await page.waitForSelector('#content .back-button');
 const before=await (await page.request.get('http://127.0.0.1:8770/api/status')).json();
 for(const route of ['planning/story','workflows','agents','runs','stages']){await page.goto('http://127.0.0.1:8770/?v=12#module/'+route);await page.waitForSelector('#content .back-button');if(await page.locator('#content .error-text').count())throw Error('live error '+route);}
 const assets=await page.evaluate(()=>[...document.querySelectorAll('script[src],link[rel=stylesheet]')].map(e=>e.src||e.href));if(!assets.every(a=>a.includes('v=12')))throw Error('old assets');
 const after=await (await page.request.get('http://127.0.0.1:8770/api/status')).json();if(before.knowledge_count!==after.knowledge_count||before.plan_count!==after.plan_count)throw Error('readonly changed content');
 await page.evaluate(report=>localStorage.setItem('qa-final-report',JSON.stringify(report)),{layouts,liveRoutes:5,assets,counts:{knowledge:after.knowledge_count,plans:after.plan_count},llmConfigured:after.llm_configured,errors});
 if(errors.length)throw Error('script errors');
}
