async page=>{
 const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.setViewportSize({width:1440,height:1000});await page.reload();await page.locator('.studio-heading').waitFor();await page.evaluate(()=>document.fonts.ready);await page.locator('.studio-heading').screenshot({path:'output/web/round4-webp.png'});await page.screenshot({path:'output/web/round4-live.png',fullPage:true});
 const resources=await page.evaluate(()=>performance.getEntriesByType('resource').filter(r=>r.name.includes('planning-mist')).map(r=>({url:r.name,bytes:r.encodedBodySize})));
 await page.route('**/planning-mist.webp',async r=>{const image=await page.request.get('http://127.0.0.1:8770/static/shilie/planning-mist.png');await r.fulfill({body:await image.body(),contentType:'image/png'});});await page.reload();await page.locator('.studio-heading').waitFor();await page.locator('.studio-heading').screenshot({path:'output/web/round4-png-reference.png'});
 await page.unroute('**/planning-mist.webp');await page.reload();await page.locator('.studio-heading').waitFor();return {resources,errors,readOnly:true};
}
