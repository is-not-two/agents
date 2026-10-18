// 时列前端浏览器验证：默认使用本机 Edge。
// 用法：node verify-ui.mjs <场景名>
// 场景：home | tree | interact | responsive | all
import {chromium} from 'playwright';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const BASE = 'http://127.0.0.1:8766/?v=25';
const OUT = 'E:/project/agents/rag-tech-doc-retriever/output/web';

// 拦截 plans API 注入示例数据，验证渲染而不写数据库。
const mockPlan = {
  id: 'p1', version: 1,
  data: {
    title: '学习与生活', kind: 'main', description: '',
    progress: {done: 0, total: 2, percent: 0},
    acts: [{id: 'a1', title: '第一阶段', nodes: [
      {id: 'n1', title: '读完一本书', description: '', parent_id: '', priority: 'p2', due_date: '', requires: [], done: false, state: 'available'},
      {id: 'n2', title: '写读书摘要', description: '', parent_id: 'n1', priority: 'p2', due_date: '', requires: [], done: false, state: 'available'}
    ]}]
  }
};

const log = (...a) => console.log(...a);
const ok = c => c ? '✓' : '✗';

async function withPage(fn, {width = 1440, height = 900} = {}) {
  const errors = [];
  const browser = await chromium.launch({executablePath: EDGE});
  const page = await browser.newPage({viewport: {width, height}});
  page.on('console', m => { if (m.type() === 'error') errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  try {
    await fn(page, errors);
  } finally {
    await browser.close();
  }
  return errors;
}

async function mockPlans(page) {
  await page.route('**/api/plans', r => r.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify([mockPlan])}));
  await page.route('**/api/plans/**', r => r.fulfill({status: 200, contentType: 'application/json', body: JSON.stringify(mockPlan)}));
}

const scenes = {
  async home(page, errors) {
    await page.goto(BASE + '#home', {waitUntil: 'networkidle'});
    await page.waitForSelector('.portal-entry', {timeout: 20000});
    log('标题      :', await page.title());
    log('入口卡片  :', JSON.stringify(await page.$$eval('.portal-entry h2', e => e.map(x => x.textContent))));
    log('顶栏背景  :', await page.$eval('.topbar', e => getComputedStyle(e).backgroundColor));
    log('返回按钮  :', await page.$$eval('[data-action=back]', e => e.length), '个');
    await page.screenshot({path: `${OUT}/edge-home.png`});
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  async tree(page, errors) {
    await mockPlans(page);
    await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
    await page.waitForSelector('.tree-viewport', {timeout: 20000});
    await page.waitForTimeout(600);
    const nodes = await page.$$eval('.tree-item', els => els.map(e => {
      const r = e.getBoundingClientRect();
      return {title: e.querySelector('strong').textContent, x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width)};
    }));
    log('=== 节点实测（Edge）===');
    nodes.forEach(n => log(`  ${n.title.padEnd(12)} x=${String(n.x).padStart(4)} y=${String(n.y).padStart(4)} 宽=${n.w}`));
    if (nodes.length >= 3) log(`父子缩进  : ${nodes[1].x - nodes[0].x}px`);
    const lines = await page.$$eval('.tree-lines path', els => els.map(e => e.getAttribute('d')));
    log('连线      :', lines.length, '条 →', lines.join(' | '));
    await page.screenshot({path: `${OUT}/edge-tree.png`});
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  async interact(page, errors) {
    await mockPlans(page);
    await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
    await page.waitForSelector('.tree-viewport', {timeout: 20000});
    await page.waitForTimeout(500);
    await page.click('.tree-item .tree-add');
    await page.waitForTimeout(500);
    log('＋弹窗    :', ok(await page.$eval('#tree-editor', e => e.open)), await page.$eval('#tree-editor-title', e => e.textContent));
    log('上下文    :', await page.$eval('#tree-add-context', e => e.textContent));
    log('父节点隐藏:', ok(await page.$eval('#tree-editor [name=parent_id]', e => e.closest('label').hidden)));
    log('必填数量  :', await page.$$eval('#tree-edit-form [required]', e => e.length), '（应为1）');
    await page.click('#tree-editor [data-action=close-dialog]');
    await page.waitForTimeout(300);
    await page.click('.tree-item:nth-child(2) .tree-node-select');
    await page.waitForTimeout(500);
    log('详情面板  :', ok(await page.$$eval('.tree-inspector', e => e.length)));
    await page.$eval('#tree-zoom', el => {el.value = 80; el.dispatchEvent(new Event('input', {bubbles: true}));});
    await page.waitForTimeout(400);
    log('缩放      :', await page.$eval('#tree-zoom-output', e => e.textContent));
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
      await page.screenshot({path: `${OUT}/edge-tree-${w}.png`});
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
  try {
    await withPage(scenes[s], s === 'responsive' ? {} : {});
  } catch (e) {
    bad++;
    log('  失败:', e.message.split('\n')[0]);
  }
}
log(bad ? `\n${bad} 个场景失败` : '\n全部通过');