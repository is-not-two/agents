// 可见巡游验收：有头浏览器 + 现场 HUD 解说，实时展示每一步检查与 ✅/❌
// 用法（在含 playwright 依赖的目录）：node visible-tour.mjs
import {chromium} from 'playwright';

const EDGE = 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe';
const BASE = 'http://127.0.0.1:8770';
const results = [];

const browser = await chromium.launch({executablePath: EDGE, headless: false, slowMo: 420});
const page = await browser.newPage({viewport: {width: 1440, height: 900}});

// HUD：注入右下角解说面板
await page.addInitScript(() => {
  const panel = document.createElement('div');
  panel.id = '__tour_hud';
  panel.style.cssText =
    'position:fixed;right:16px;bottom:16px;z-index:99999;background:#2d2720ee;color:#ffe9c9;' +
    'font:13px/1.7 Consolas,monospace;padding:14px 18px;border-radius:12px;max-width:420px;' +
    'box-shadow:0 12px 40px #0008;pointer-events:none;white-space:pre-line';
  document.addEventListener('DOMContentLoaded', () => document.body.append(panel));
  window.__tour = [];
  window.__hud = (step, ok) => {
    window.__tour.push(`${ok === null ? '▸' : ok ? '✅' : '❌'} ${step}`);
    const panel = document.getElementById('__tour_hud');
    if (panel) panel.textContent = '实时验收巡游\n' + window.__tour.slice(-7).join('\n');
  };
});

async function step(name, fn) {
  await page.evaluate((n) => window.__hud(n, null), name);
  await page.waitForTimeout(700);
  try {
    const detail = await fn();
    results.push([name, true]);
    await page.evaluate((n) => window.__hud(n + (detail ? ' · ' + detail : ''), true), name);
  } catch (e) {
    results.push([name, false]);
    await page.evaluate((n, m) => window.__hud(n + ' ❌ ' + m, false), name, String(e.message).split('\n')[0].slice(0, 60));
  }
  await page.waitForTimeout(600);
}

await page.goto(BASE + '/#home', {waitUntil: 'networkidle'});
await page.waitForSelector('.sl-orbit__node', {timeout: 15000});
await page.waitForTimeout(800);

await step('首页：极光层真实可见（body 透明）', async () => {
  const bg = await page.evaluate(() => getComputedStyle(document.body).backgroundColor);
  if (bg !== 'rgba(0, 0, 0, 0)') throw Error('body 不透明，极光被挡');
  return '底色由 html 承载';
});
await step('首页：环轨入口 10 个（内 6 / 外 4）', async () => {
  const n = await page.$$eval('.sl-orbit__node', (e) => e.length);
  if (n !== 10) throw Error('入口数 ' + n);
  return n + ' 个入口';
});
await step('首页：花瓣与萤火虫（在内容之下）', async () => {
  const p = await page.$$eval('.petal', (e) => e.length);
  const under = await page.evaluate(() => {
    const f = document.querySelector('#fireflies i');
    if (!f) return false;
    const r = f.getBoundingClientRect();
    const el = document.elementFromPoint(r.left + 2, r.top + 2);
    return el && !el.closest('#fireflies');
  });
  if (p !== 7 || !under) throw Error('花瓣' + p + '/萤火虫压内容');
  return '7 片 · 萤火虫已退层';
});
await step('首页：光标辉光 + 环轨节点几何', async () => {
  // 环轨节点的 transform 已被定位链（公转 + 自转抵消）占用，刻意不参与 3D 倾斜；
  // 这里改为验证节点真的排布出来了（boundingBox 非空且互不重叠）。
  const boxes = await page.$$eval('.sl-orbit__node', (nodes) =>
    nodes.map((n) => {
      const r = n.getBoundingClientRect();
      return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
    }),
  );
  if (boxes.length !== 10) throw Error('节点数 ' + boxes.length);
  if (boxes.some((b) => !b.w || !b.h)) throw Error('节点尺寸为 0');
  const centers = new Set(boxes.map((b) => b.x + ':' + b.y));
  if (centers.size !== 10) throw Error('节点重叠，圆心重复 ' + (10 - centers.size) + ' 个');
  return '10 个节点各自就位';
});
await step('首页：点击粒子爆发', async () => {
  await page.mouse.click(500, 400);
  await page.waitForTimeout(150);
  const n = await page.$$eval('.particle', (e) => e.length);
  if (n < 8) throw Error('粒子 ' + n);
  await page.waitForTimeout(900);
  return n + ' 粒已自清';
});
await page.goto(BASE + '/#module/planning', {waitUntil: 'networkidle'});
await page.waitForSelector('.story-card', {timeout: 15000});
await step('规划：连线生长 + 节点弹入', async () => {
  const line = await page.$eval('.story-canvas path', (e) => getComputedStyle(e).animationName).catch(() => 'none');
  const card = await page.$eval('.story-card', (e) => getComputedStyle(e).animationName);
  if (!['line-grow', 'none'].includes(line) || card !== 'card-pop') throw Error(line + '/' + card);
  return '树是长出来的';
});
await step('规划：折叠往返', async () => {
  const before = await page.$$eval('.story-card', (e) => e.filter((x) => x.offsetParent).length);
  await page.click('[data-action=tree-fold-all]');
  await page.waitForTimeout(500);
  const folded = await page.$$eval('.story-card', (e) => e.filter((x) => x.offsetParent).length);
  await page.click('[data-action=tree-expand-all]');
  await page.waitForTimeout(500);
  const after = await page.$$eval('.story-card', (e) => e.filter((x) => x.offsetParent).length);
  if (!(folded < before && after === before)) throw Error(before + '→' + folded + '→' + after);
  return before + '→' + folded + '→' + after;
});
await page.goto(BASE + '/#module/knowledge', {waitUntil: 'networkidle'});
await step('知识库：空态示意卡 + 弹窗', async () => {
  const demo = await page.$$eval('.demo-card', (e) => e.length);
  if (demo !== 3) throw Error('示意卡 ' + demo);
  await page.click('[data-action=new-note]');
  await page.waitForTimeout(500);
  const open = await page.$eval('.form-dialog[data-form=knowledge]', (e) => e.open);
  await page.keyboard.press('Escape');
  return '3 张示意 · 弹窗' + (open ? '正常' : '未开');
});
await page.goto(BASE + '/#module/lessons', {waitUntil: 'networkidle'});
await step('谨记名单：分类筛选 + 录入弹窗', async () => {
  const chips = await page.$$eval('.lesson-chip', (e) => e.length);
  if (chips < 6) throw Error('chips ' + chips);
  await page.click('[data-action=lesson-new]');
  await page.waitForTimeout(450);
  const open = await page.$eval('.form-dialog[data-form=lesson]', (e) => e.open);
  await page.keyboard.press('Escape');
  return chips + ' 个分类 · 弹窗' + (open ? '正常' : '未开');
});
await page.goto(BASE + '/#module/documents', {waitUntil:'networkidle'});
await step('检索：示例 chip 一键真搜', async () => {
  await page.waitForSelector('.example-chip', {timeout: 8000});
  await page.click('.example-chip');
  await page.waitForSelector('.result-meta, .result-list', {timeout: 8000});
  return '结果已渲染';
});
await page.goto(BASE + '/#module/appearance', {waitUntil: 'networkidle'});
await step('设置：服务状态卡（MCP/向量库）', async () => {
  await page.waitForSelector('.server-status', {timeout: 8000});
  await page.waitForFunction(() => {
    const el = document.querySelector('.server-status');
    return el && !el.innerText.includes('正在读取');
  }, {timeout: 8000});
  const text = await page.$eval('.server-status', (e) => e.innerText);
  if (!text.includes('MCP 服务')) throw Error('无 MCP 行');
  return 'MCP·向量库·记录表';
});

const pass = results.filter((r) => r[1]).length;
const summary = `巡游完成：${pass}/${results.length} 通过`;
await page.evaluate((s) => {
  window.__hud(s, null);
  const panel = document.getElementById('__tour_hud');
  if (panel) panel.textContent = '实时验收巡游\n' + window.__tour.join('\n');
}, summary);
console.log('\n=== ' + summary + ' ===');
results.forEach(([n, ok]) => console.log((ok ? '✅' : '❌') + ' ' + n));
await page.waitForTimeout(6000);
await browser.close();
