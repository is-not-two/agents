// 时列前端浏览器验证：默认使用本机 Edge。
// 用法：node verify-ui.mjs <场景名>
// 场景：home | tree | interact | responsive | all
import {loadPlaywright} from "./playwright-runtime.mjs";
import fs from "node:fs";
import {fileURLToPath} from "node:url";
const {chromium} = await loadPlaywright();

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const BASE = process.env.WEB_QA_URL || 'http://127.0.0.1:8770/';
const OUT = process.env.WEB_QA_OUTPUT || fileURLToPath(new URL('../output/web', import.meta.url));
fs.mkdirSync(OUT, {recursive: true});

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
  const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? {executablePath: process.env.BROWSER_EXECUTABLE} : process.platform === "win32" ? {executablePath: EDGE} : {channel: process.env.BROWSER_CHANNEL || "chrome"});
  const page = await browser.newPage({viewport: {width, height}});
  page.on('console', m => { if (m.type() === 'error' && !m.text().includes('404')) errors.push(m.text()); });
  page.on('pageerror', e => errors.push('PAGEERROR: ' + e.message));
  try { await fn(page, errors); if(errors.length) throw Error(JSON.stringify(errors)); } finally { await browser.close(); }
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
    await page.waitForSelector('.sl-orbit', {timeout: 20000});
    log('标题      :', await page.title());
    log('环轨入口  :', JSON.stringify(await page.$$eval('.sl-orbit__node-label', e => e.map(x => x.textContent))));
    log('顶栏背景  :', await page.$eval('.topbar', e => getComputedStyle(e).backgroundColor));
    await page.screenshot({path: `${OUT}/edge-home.png`});
    log('错误      :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  // 人生规划：主线分叉画布（2026-10-19 起的 .story-* DOM）
  async tree(page, errors) {
    await mockPlans(page);
    await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
    await page.waitForSelector('.story-card', {timeout: 20000});
    await page.waitForTimeout(600);
    const cards = () => page.$$eval('.story-card', e => e.filter(x => x.offsetParent !== null).length);
    log('方向根节点:', await page.$eval('.story-card .story-title strong', e => e.textContent.trim()));
    log('根进度   :', JSON.stringify(await page.$$eval('.story-progress span', e => e.slice(0, 1).map(x => x.textContent.trim()))));
    log('连线     :', await page.$$eval('.story-canvas svg path', e => e.length), '条');
    const c0 = await cards();
    await page.click('[data-action=tree-fold-all]'); await page.waitForTimeout(400);
    const c1 = await cards();
    await page.click('[data-action=tree-expand-all]'); await page.waitForTimeout(400);
    const c2 = await cards();
    log('收起展开 :', `${c0} → ${c1} → ${c2}`, ok(c1 < c0 && c2 === c0) ? '✓' : '✗');
    log('节点标题 :', JSON.stringify(await page.$$eval('.story-card .story-title strong', e => e.map(x => x.textContent.trim()))));
    await page.screenshot({path: `${OUT}/edge-tree.png`, fullPage: true});
    log('错误     :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
  },

  async interact(page, errors) {
    // 有状态 mock：PUT 完成后，后续 GET 返回已完成版本，模拟真实持久化
    const planDone = JSON.parse(JSON.stringify(mockPlan));
    planDone.data.acts[0].nodes.find(n => n.id === 'n2').done = true;
    planDone.data.progress = {done: 2, total: 4, percent: 50};
    let doneState = false;
    await page.route('**/api/plans', r => r.fulfill({status: 200, contentType: 'application/json',
      body: JSON.stringify(doneState ? [planDone] : [mockPlan])}));
    await page.route('**/api/plans/**', r => {
      if (r.request().method() === 'PUT') doneState = true;
      return r.fulfill({status: 200, contentType: 'application/json',
        body: JSON.stringify(doneState ? planDone : mockPlan)});
    });
    await page.goto(BASE + '#module/planning', {waitUntil: 'networkidle'});
    await page.waitForSelector('.story-card', {timeout: 20000});
    await page.waitForTimeout(500);

    // 添加表单：只填名称即可，父节点隐藏
    await page.click('.story-add-side');
    await page.waitForTimeout(500);
    log('＋弹窗    :', ok(await page.$eval('#tree-editor', e => e.open)), await page.$eval('#tree-editor-title', e => e.textContent));
    log('上下文    :', await page.$eval('#tree-add-context', e => e.textContent));
    log('父节点隐藏:', ok(await page.$eval('#tree-editor [name=parent_id]', e => e.closest('label').hidden)));
    log('必填数量  :', await page.$$eval('#tree-edit-form [required]', e => e.length), '（应为1）');
    await page.click('#tree-editor [data-action=close-dialog]');
    await page.waitForTimeout(300);

    // 完成切换（PUT → 状态化 GET）
    const target = '.story-card:has-text("每周跑步三次") [data-action=tree-toggle]';
    const before = await page.$eval(target, e => e.getAttribute('aria-pressed'));
    await page.click(target);
    await page.waitForTimeout(900);
    const after = await page.$eval('.story-card:has-text("每周跑步三次") [data-action=tree-toggle]', e => e.getAttribute('aria-pressed'));
    log('完成切换  :', `${before} → ${after}`, ok(before !== after) ? '✓' : '✗');
    log('toast     :', await page.$eval('#toast', e => e.hidden ? '(隐藏)' : e.textContent));

    // 缩放滑块（应用绑定在 change：松手生效）
    await page.$eval('#story-zoom', e => { e.value = '80'; e.dispatchEvent(new Event('change', {bubbles: true})); });
    await page.waitForTimeout(300);
    const scale = await page.$eval('.story-canvas', e => e.style.transform);
    log('缩放      :', scale, scale.includes('scale(0.8') ? '✓' : '✗');
    await page.screenshot({path: `${OUT}/edge-interact.png`, fullPage: true});
    log('错误     :', errors.length ? JSON.stringify(errors.slice(0, 5)) : '无');
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
  },

  /* 检索质量评测页：题集加载 → 跑评测 → 重排开关 → 逐题展开。
     真实调用 /api/eval（要加载嵌入与重排模型，给足等待时间）。 */
  async evaluation(page, errors) {
    await page.setViewportSize({width: 1440, height: 1000});
    await page.goto(BASE + '#module/evaluation', {waitUntil: 'networkidle'});
    await page.waitForSelector('.eval-surface', {timeout: 15000});
    log('页面渲染  :', ok(true));

    const switchPresent = await page.locator('[data-eval-rerank]').count();
    log('重排开关  :', ok(switchPresent === 1));

    const hintBefore = await page.locator('.eval-hint').count();
    log('初始提示  :', ok(hintBefore === 1));

    /* 触发真实评测（首次加载模型，最多等 4 分钟） */
    await page.locator('[data-action="eval-run"]').click();
    await page.waitForSelector('.eval-summary, .eval-error', {timeout: 240000});

    const hasError = await page.locator('.eval-error').count();
    if (hasError) {
      const msg = await page.locator('.eval-error p').first().innerText();
      log('评测      :', '✗ 返回错误', msg.slice(0, 120));
      throw Error('评测接口报错：' + msg.slice(0, 120));
    }

    const recallCells = await page.locator('.eval-recall td').allInnerTexts();
    log('召回率    :', recallCells.slice(1).map(t => t.replace(/\s+/g, ' ').trim()).join(' | '));

    const qCount = await page.locator('.eval-question').count();
    log('题目数    :', ok(qCount === 10), qCount);

    const moves = await page.locator('.eval-move').count();
    log('重排名次变化:', moves > 0 ? `✓ ${moves} 条` : '✗ 无');

    /* 展开第一题，验证明细表真实出现 */
    await page.locator('.eval-question > header').first().click();
    await page.waitForTimeout(300);
    const hitRows = await page.locator('.eval-hits tbody tr').count();
    log('命中明细行:', ok(hitRows > 0), hitRows);
    await page.screenshot({path: `${OUT}/edge-evaluation.png`, fullPage: true});

    /* 关掉重排，确认结果被清空（口径切换后不展示旧数） */
    await page.locator('[data-eval-rerank]').uncheck();
    await page.waitForTimeout(400);
    const afterToggle = await page.locator('.eval-hint').count();
    log('关闭重排后重置:', ok(afterToggle === 1));

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
if (bad) process.exitCode = 1;
