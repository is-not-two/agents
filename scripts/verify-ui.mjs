// 时列前端浏览器验证：默认使用本机 Edge。
// 用法：node verify-ui.mjs <场景名>
// 场景：home | tree | interact | responsive | all
import {chromium} from 'playwright';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const BASE = 'http://127.0.0.1:8766/?v=34';
const OUT = 'E:/project/agents/rag-tech-doc-retriever/output/web';

const mockPlan = {
  id: 'p1', version: 1,
  data: {
    title: '学习与生活', kind: 'main', description: '今年的主线',
    progress: {done: 1, total: 4, percent: 25},
    acts: [{id: 'a1', title: '第一阶段', nodes: [
      {id: 'n1', title: '读完《置身事内》', description: '', parent_id: '', priority: 'p1', due_date: '2026-10-20', requires: [], done: false, state: 'available'},
      {id: 'n1a', title: '每周读一章', description: '', parent_id: 'n1', priority: 'p2', due_date: '', requires: [], done: false, state: 'available'},
      {id: 'n2', title: '每周跑步三次', description: '', parent_id: '', priority: 'p2', due_date: '', requires: [], done: false, state: 'available'},
      {id: 'n3', title: '整理书桌', description: '', parent_id: '', priority: 'p3', due_date: '', requires: [], done: true, state: 'available'}
    ]}]
  }
};

const log = (...a) => console.log(...a);
const ok = c => c ? '✓' : '✗';

async function withPage(fn, {width = 1440, height = 900} = {}) {
  const errors = [];
  const browser = await chromium.launch({executablePath: EDGE});
  const page = await browser.newPage({viewport: {width, height}});
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('404')) errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  try { await fn(page, errors); } finally { await browser.close(); }
  return errors;
}

async function mockPlans(page) {
  await page.route('**/api/plans', r => r.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([mockPlan])}));
  await page.route('**/api/plans/**', r => r.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(mockPlan)}));
  await page.route('**/api/plans/p1/nodes/*', r => r.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(mockPlan)}));
}

const scenes = {
  async home(page, errors) {
    await page.goto(BASE + '#home', {waitUntil: 'networkidle'});
    await page.waitForSelector('.portal-entry', {timeout: 20000});
    log('标题      :', await page.title());
    log('入口卡片  :', JSON.stringify(await page.$$eval('.portal-entry h2', e => e.map(x => x.textContent))));
    log('顶栏背景  :', await page.$eval('.topbar', e => getComputedStyle(e).backgroundColor));
    await page.screenshot({path: `${OUT}/edge-home.png`});
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  // 人生规划：同页展开列表
  async tree(page, errors) {
    await mockPlans(page);
    await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
    await page.waitForSelector('.dir-card', {timeout: 20000});
    await page.waitForTimeout(600);
    log('方向      :', await page.$eval('.dir-title', e => e.textContent.trim()));
    log('进度      :', await page.$eval('.dir-count', e => e.textContent));
    log('画布残留  :', await page.$$eval('.tree-viewport,.tree-zoom,.tree-item', e => e.length), '（应为0）');

    // 往返折叠
    const vis = () => page.$$eval('.node-row', e => e.filter(x => x.offsetParent !== null).length);
    const n0 = await vis();
    await page.click('.dir-tw'); await page.waitForTimeout(400);
    const n1 = await vis();
    await page.click('.dir-tw'); await page.waitForTimeout(400);
    const n2 = await vis();
    log('折叠往返  :', `${n0} → ${n1} → ${n2}`, ok(n1 === 0 && n2 === n0) ? '✓' : '✗');

    // 层级缩进
    await page.click('[data-action=tree-expand-all]'); await page.waitForTimeout(400);
    const rows = await page.$$eval('.node-row', e => e.filter(x => x.offsetParent !== null).map(x => ({
      t: x.querySelector('.node-title').textContent.trim(),
      d: (x.className.match(/depth-\d/) || ['?'])[0],
      pad: getComputedStyle(x).paddingLeft
    })));
    log('全部展开  :', rows.length, '条');
    log('层级      :', JSON.stringify(rows.reduce((a, x) => { a[x.d] = (a[x.d] || 0) + 1; return a; }, {})));
    log('缩进      :', [...new Set(rows.map(x => x.pad))].join(' → '));
    rows.forEach(x => log(`  [${x.d}] ${x.t}`));
    await page.screenshot({path: `${OUT}/edge-tree.png`, fullPage: true});

    await page.click('[data-action=tree-fold-all]'); await page.waitForTimeout(400);
    log('全部收起  :', await vis(), '条');
    await page.click('[data-action=tree-expand-all]'); await page.waitForTimeout(400);
    log('再展开    :', await vis(), '条');
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  async interact(page, errors) {
    await mockPlans(page);
    await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
    await page.waitForSelector('.dir-card', {timeout: 20000});
    await page.waitForTimeout(500);

    // 添加表单：只填名称即可，父节点隐藏
    await page.click('.node-row [data-action=tree-add]');
    await page.waitForTimeout(500);
    log('＋弹窗    :', ok(await page.$eval('#tree-editor', e => e.open)), await page.$eval('#tree-editor-title', e => e.textContent));
    log('上下文    :', await page.$eval('#tree-add-context', e => e.textContent));
    log('父节点隐藏:', ok(await page.$eval('#tree-editor [name=parent_id]', e => e.closest('label').hidden)));
    log('必填数量  :', await page.$$eval('#tree-edit-form [required]', e => e.length), '（应为1）');
    await page.click('#tree-editor [data-action=close-dialog]');
    await page.waitForTimeout(300);

    // 行首圆圈切换完成
    const before = await page.$$eval('.node-row.is-done', e => e.length);
    await page.click('.node-row:not(.is-done) .node-tick');
    await page.waitForTimeout(900);
    const after = await page.$$eval('.node-row.is-done', e => e.length);
    log('勾选切换  :', `${before} → ${after}`, ok(after !== before) ? '✓' : '✗');
    log('toast     :', await page.$eval('#toast', e => e.hidden ? '(隐藏)' : e.textContent));
    await page.screenshot({path: `${OUT}/edge-tree.png`, fullPage: true});
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  async responsive(page, errors) {
    for (const [w, h] of [[1440, 900], [1024, 768], [390, 844]]) {
      await page.setViewportSize({width: w, height: h});
      await mockPlans(page);
      await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
      await page.waitForTimeout(700);
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth > window.innerWidth + 1);
      log(`${w}×${h} 横向溢出:`, ok(!overflow), overflow ? '存在' : '无');
      await page.screenshot({path: `${OUT}/edge-tree-${w}.png`, fullPage: true});
    }
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  }
};

const which = process.argv[2] || 'all';
const list = which === 'all' ? Object.keys(scenes) : [which];
let bad = 0;
for (const s of list) {
  if (!scenes[s]) { log('未知场景:', s); continue; }
  log(`\n=== ${s} ===`);
  try { await withPage(scenes[s]); }
  catch (e) { bad++; log('  失败:', e.message.split('\n')[0]); }
}
log(bad ? `\n${bad} 个场景失败` : '\n全部通过');