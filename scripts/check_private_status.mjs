/* Offline Edge/Chromium regression: real private-view.js and data.js, synthetic HTTP only.
   node scripts/check_private_status.mjs --report OUTPUT.json [--ui-dir PATH]
   Requires the existing Playwright runtime; never reads .env or a saved browser profile. */
import assert from 'node:assert/strict';
import fs from 'node:fs';
import http from 'node:http';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadPlaywright } from './playwright-runtime.mjs';

const args = process.argv.slice(2);
function option(name, fallback) {
  const i = args.indexOf(name);
  if (i < 0) return fallback;
  if (!args[i + 1] || args[i + 1].startsWith('--')) throw Error(`Missing value: ${name}`);
  return args[i + 1];
}
const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..');
const ui = path.resolve(option('--ui-dir', path.join(root, 'src/rag_tech_retriever/api/static/shilie')));
const moduleFile = path.resolve(option('--module-file', path.join(ui, 'private-view.js')));
const expected = option('--expect', 'fixed');
assert(['fixed', 'baseline'].includes(expected));
const output = path.resolve(option('--report', path.join(root, 'output/private-status-check.json')));
const report = {expected, moduleFile, checks: [], errors: [], externalRequests: [], writes: 0};
let scenario;
const errorText = '合成状态失败 <img src=x onerror="window.__xss=1">';
function send(res, status, value) {
  res.writeHead(status, {'Content-Type': 'application/json', 'Cache-Control': 'no-store'});
  res.end(JSON.stringify(value));
}
const server = http.createServer((req, res) => {
  const u = new URL(req.url, 'http://localhost');
  if (u.pathname === '/api/private/status' && req.method === 'GET') {
    scenario.requests++;
    if (scenario.requests <= 2) return send(res, 503, {detail: errorText, code: 'STORAGE_UNAVAILABLE'});
    scenario.pending = res;
    return;
  }
  if (u.pathname.startsWith('/api/')) {
    if (req.method !== 'GET') report.writes++;
    return send(res, 500, {detail: 'Unexpected API: ' + u.pathname});
  }
  if (u.pathname === '/') {
    res.writeHead(200, {'Content-Type': 'text/html; charset=utf-8'});
    res.end(`<!doctype html><html lang="zh"><meta charset="utf-8"><title>Isolated private status</title>
      <main id="test-root"></main><script type="module">
      import {privateView,setPrivateRepaint,bindPrivate} from '/private-view.js';
      const render=()=>{document.getElementById('test-root').innerHTML=privateView();};
      window.__render=render;setPrivateRepaint(render);bindPrivate();render();
      </script></html>`);
    return;
  }
  const file = u.pathname === '/private-view.js' ? moduleFile
    : u.pathname === '/data.js' ? path.join(ui, 'data.js') : null;
  if (!file) {res.writeHead(404);res.end();return;}
  res.writeHead(200, {'Content-Type': 'text/javascript; charset=utf-8'});
  res.end(fs.readFileSync(file));
});
await new Promise(resolve => server.listen(0, '127.0.0.1', resolve));
const origin = `http://127.0.0.1:${server.address().port}`;
let browser;
try {
  const {chromium} = await loadPlaywright();
  const edge = process.env.PLAYWRIGHT_EXECUTABLE_PATH || (process.platform === 'win32'
    ? 'C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe' : undefined);
  browser = await chromium.launch({headless: true, ...(edge ? {executablePath: edge} : {})});
  for (const configured of [true, false]) {
    scenario = {configured, requests: 0, pending: null};
    const page = await browser.newPage({viewport: {width: configured ? 1280 : 390, height: 844}});
    page.on('pageerror', error => report.errors.push(error.message));
    await page.route('**/*', route => {
      if (!route.request().url().startsWith(origin + '/')) {
        report.externalRequests.push(route.request().url());
        return route.abort();
      }
      return route.continue();
    });
    await page.goto(origin + '/#module/private', {waitUntil: 'networkidle'});
    const check = (name, ok) => {report.checks.push({name: `${configured ? 'configured' : 'new'}:${name}`, ok});assert(ok, name);};
    if (expected === 'baseline') {
      check('stuck-loading-reproduced', await page.locator('.private-loading').count() === 1);
      check('retry-missing', await page.locator('[data-private="retry-status"]').count() === 0);
      await page.evaluate(() => window.__render());
      await page.waitForTimeout(150);
      check('rerender-does-not-recover', scenario.requests === 1 && await page.locator('.private-loading').count() === 1);
    } else {
      const retry = page.getByRole('button', {name: '重试', exact: true});
      await retry.waitFor();
      check('first-503-shows-retry-not-setup', await page.locator('[role="alert"]').innerText() === errorText
        && await page.locator('#private-gate-form').count() === 0 && scenario.requests === 1);
      check('error-is-escaped', await page.locator('img').count() === 0 && !await page.evaluate(() => window.__xss));
      await page.evaluate(() => {window.__render();window.__render();});
      await page.waitForTimeout(150);
      check('no-render-retry-loop', scenario.requests === 1);
      await retry.click();
      await retry.waitFor();
      check('second-503-remains-retryable', scenario.requests === 2 && await page.locator('#private-gate-form').count() === 0);
      const request = page.waitForRequest(r => r.url() === origin + '/api/private/status');
      await page.evaluate(() => {const b=document.querySelector('[data-private="retry-status"]');b.click();b.click();});
      await request;
      await page.waitForTimeout(150);
      check('double-click-only-one-pending-probe', scenario.requests === 3 && !!scenario.pending);
      send(scenario.pending, 200, {configured, strong_crypto: true, requires_password: true});
      scenario.pending = null;
      await page.locator(configured ? '.slide-thumb' : '#private-gate-form').waitFor();
      check('recovery-selects-correct-gate', await page.locator('[role="alert"]').count() === 0
        && await page.locator('.private-loading').count() === 0
        && await page.locator(configured ? '#private-gate-form' : '.slide-thumb').count() === 0);
      await page.evaluate(() => window.__render());
      await page.waitForTimeout(150);
      check('settled-state-no-extra-probes', scenario.requests === 3);
    }
    await page.close();
  }
  assert(report.writes === 0 && !report.errors.length && !report.externalRequests.length);
} catch (error) {
  report.errors.push(error.stack || String(error));
  process.exitCode = 1;
} finally {
  if (scenario?.pending) {scenario.pending.destroy();scenario.pending = null;}
  if (browser) await browser.close();
  await new Promise(resolve => server.close(resolve));
  fs.mkdirSync(path.dirname(output), {recursive: true});
  fs.writeFileSync(output, JSON.stringify(report, null, 2) + '\n');
}
for (const check of report.checks) console.log(`${check.name}: ${check.ok ? 'PASS' : 'FAIL'}`);
console.log(`PRIVATE_STATUS_${expected.toUpperCase()} checks=${report.checks.length} errors=${report.errors.length} writes=${report.writes} external=${report.externalRequests.length}`);
if (report.errors.length) console.error(report.errors.join('\n'));
