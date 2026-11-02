/* Confirmed cards, real review persistence and visible outbox failure on owned QA. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./playwright-runtime.mjs";

const base = new URL(process.env.WEB_QA_URL || "http://invalid/");
const runId = process.env.WEB_QA_RUN_ID || "";
assert(base.protocol === "http:" && base.hostname === "127.0.0.1" && /^[a-f0-9]{12}$/.test(runId));
assert.deepEqual(await (await fetch(new URL("/__qa__/identity", base))).json(), { run_id: runId });
const output = process.env.WEB_QA_OUTPUT;
assert(output);
fs.mkdirSync(output, { recursive: true });
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === "win32" ? { channel: "msedge" } : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [], evidence = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("dialog", (d) => d.type() === "prompt" ? d.accept("已核对通知结果") : d.accept());
const dialog = page.locator('dialog[data-form="learning"]');
const get = async (pathname) => (await page.request.get(new URL(pathname, base).href)).json();
const record = async (label, fn) => { await fn(); evidence.push({ label, passed: true }); console.log("PASS learning", label); };
const responseFor = (pathname, method = "POST") => {
  const pending = page.waitForResponse((r) => new URL(r.url()).pathname === pathname && r.request().method() === method);
  // Install a rejection handler immediately; a slower click must not turn an
  // observation timeout into an unhandled rejection that discards artifacts.
  pending.catch(() => {});
  return pending;
};
async function save(pathname, name, method = "POST") {
  const pending = responseFor(pathname, method);
  await dialog.getByRole("button", { name, exact: true }).click();
  const response = await pending; assert.equal(response.status(), method === "POST" && pathname === "/api/learning/cards" ? 201 : 200, await response.text());
  await page.waitForFunction(() => !document.querySelector('#learning-form [type="submit"]').disabled);
  await dialog.waitFor({ state: "hidden" });
  return response.json();
}
let card, manual, source;
async function showAllCards() {
  await page.getByRole("heading", { name: "到期复习", exact: true }).waitFor();
  const toggle = page.getByRole("button", { name: "查看全部卡片", exact: true });
  if (await toggle.count()) await toggle.click();
  await page.getByRole("button", { name: "只看到期卡片", exact: true }).waitFor();
}
async function stableScreenshot(name) {
  // Full-page capture does not scroll reveal observers into view. Use the
  // product's actual reduced-motion preference for readable static evidence,
  // not forced opacity or edits to the product's DOM/content.
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForFunction(() => [...document.querySelectorAll("#content .module-surface")].every((el) => getComputedStyle(el).opacity === "1"));
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  await page.emulateMedia({ reducedMotion: "no-preference" });
}
try {
  const jobs = await get("/api/jobs");
  const application = jobs.application.find((row) => row.data.title.includes(runId));
  source = jobs.interview_report.find((row) => row.data.application_id === application?.id);
  assert(source && source.data.weak_points.length);
  await record("unchecked candidates cannot silently create cards; explicit confirmation deduplicates", async () => {
    await page.goto(new URL("/#module/jobs", base).href);
    await page.locator(`.jobs-row[data-id="${application.id}"]`).click();
    await page.getByRole("button", { name: "选点创建复习卡", exact: true }).click();
    await dialog.getByRole("button", { name: "确认创建复习卡", exact: true }).click();
    await page.locator("#learning-form-error").filter({ hasText: "请勾选" }).waitFor();
    assert.equal((await get("/api/learning/cards")).cards.length, 0);
    await dialog.getByRole("checkbox").first().check();
    const result = await save(`/api/learning/from-interview/${source.id}`, "确认创建复习卡");
    card = result.created[0]; assert(card && card.data.source_id === source.id);
    await page.getByRole("button", { name: "选点创建复习卡", exact: true }).click();
    await dialog.getByRole("checkbox").first().check();
    const repeated = await save(`/api/learning/from-interview/${source.id}`, "确认创建复习卡");
    assert.equal(repeated.created.length, 0); assert.equal(repeated.reused[0].id, card.id);
  });
  await record("recall then self-grade changes due time once and persists review evidence", async () => {
    await page.goto(new URL("/#module/learning", base).href);
    const layout = await page.evaluate(() => document.documentElement.dataset.layout);
    await page.evaluate(() => {
      const wrapper = document.createElement("div"); wrapper.dataset.mode = "foreign-dialog-mode"; wrapper.id = "qa-mode-collision";
      const child = document.createElement("button"); child.textContent = "QA foreign container"; wrapper.append(child); document.body.append(wrapper);
    });
    await page.locator("#qa-mode-collision button").click();
    assert.equal(await page.evaluate(() => document.documentElement.dataset.layout), layout);
    await page.evaluate(() => document.getElementById("qa-mode-collision").remove());
    await page.getByRole("heading", { name: card.data.title, exact: true }).waitFor();
    assert(await page.getByRole("button", { name: "记得", exact: true }).isDisabled());
    await page.getByRole("button", { name: "显示答案 / 资料引用", exact: true }).click();
    const pending = responseFor(`/api/learning/cards/${card.id}/review`);
    await page.getByRole("button", { name: "记得", exact: true }).click();
    assert.equal((await pending).status(), 200);
    await page.getByText("没有到期卡片。", { exact: false }).waitFor();
    const result = await get("/api/learning/cards");
    assert.equal(result.due_ids.length, 0); assert.equal(result.cards[0].version, 2);
    await showAllCards();
    await page.getByRole("button", { name: "查看复习记录", exact: true }).click();
    await page.locator(".learning-history").filter({ hasText: "记得" }).waitFor();
    assert.equal((await get(`/api/learning/cards/${card.id}/reviews`)).length, 1);
  });
  await record("manual cards, pause, 409 input preservation, archive and restore", async () => {
    await page.getByRole("button", { name: "添加复习卡", exact: true }).click();
    await dialog.getByLabel("复习问题", { exact: true }).fill("手工复习 <script>alert(1)</script>");
    await dialog.getByLabel("答案或资料引用", { exact: true }).fill("不应进入通知正文的私人答案 QA_SECRET_ANSWER");
    await dialog.getByLabel("复习时间", { exact: true }).fill("2020-01-01T09:00");
    manual = await save("/api/learning/cards", "保存");
    await page.locator(`.jobs-row[data-id="${manual.id}"]`).click();
    await page.getByRole("button", { name: "编辑卡片", exact: true }).click();
    await dialog.getByLabel("复习问题", { exact: true }).fill("冲突也保留的输入");
    const updated = await page.request.put(new URL(`/api/learning/cards/${manual.id}`, base).href, { data: { version: manual.version, data: { paused: true } } });
    assert.equal(updated.status(), 200);
    const conflict = responseFor(`/api/learning/cards/${manual.id}`, "PUT");
    await dialog.getByRole("button", { name: "保存", exact: true }).click(); assert.equal((await conflict).status(), 409);
    await page.locator("#learning-form-error").filter({ hasText: "当前输入已保留" }).waitFor();
    assert.equal(await dialog.getByLabel("复习问题", { exact: true }).inputValue(), "冲突也保留的输入");
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    await dialog.waitFor({ state: "hidden" });
    assert(["portal", "sidebar"].includes(await page.evaluate(() => document.documentElement.dataset.layout)));
    const refreshed = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/learning/cards");
    await Promise.all([refreshed, page.getByRole("button", { name: "刷新", exact: true }).click()]);
    await page.locator(`.jobs-row[data-id="${manual.id}"]`).click();
    const archived = page.waitForResponse((r) => r.request().method() === "DELETE");
    const [archiveResponse] = await Promise.all([archived, page.getByRole("button", { name: "归档卡片", exact: true }).click()]); assert.equal(archiveResponse.status(), 200);
    await page.getByRole("button", { name: "卡片回收站", exact: true }).click();
    await page.locator(`.jobs-row[data-id="${manual.id}"]`).click();
    const restored = responseFor(`/api/records/${manual.id}/restore`);
    await page.getByRole("button", { name: "恢复卡片", exact: true }).click(); assert.equal((await restored).status(), 200);
    await page.getByRole("button", { name: "返回有效卡片", exact: true }).click();
    await page.locator(`.jobs-row[data-id="${manual.id}"]`).click();
    assert.equal(await page.locator(".learning-card script").count(), 0);
  });
  await record("preview is readonly, notification disabled by default, same-day queue is stable", async () => {
    await page.goto(new URL("/#module/notifications", base).href);
    await page.getByRole("heading", { name: "今日摘要预览", exact: true }).waitFor();
    assert(await page.getByRole("button", { name: "确认发送待处理队列", exact: true }).isDisabled());
    assert.equal((await get("/api/notifications")).notifications.length, 0);
    for (let i = 0; i < 2; i++) {
      const pending = responseFor("/api/notifications/daily");
      await page.getByRole("button", { name: "确认加入今日通知队列", exact: true }).click();
      const row = await pending; assert.equal(row.status(), 200);
      assert.equal((await row.json()).reused, i === 1);
      await page.locator(".notice-row").waitFor();
    }
    assert.equal((await get("/api/notifications")).notifications.length, 1);
    assert(!(await get("/api/notifications/daily-preview")).body.includes("QA_SECRET_ANSWER"));
  });
  await record("real local SMTP greeting disconnect yields visible failed state, explicit retry and cancel", async () => {
    const failure = await page.request.post(new URL("/__qa__/notifications/fail-before-data", base).href);
    assert.equal(failure.status(), 200, await failure.text());
    assert.equal((await failure.json()).processed[0].data.status, "failed");
    const refreshed = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/notifications");
    await Promise.all([refreshed, page.getByRole("button", { name: "刷新摘要与队列", exact: true }).click()]);
    await page.locator(".notice-row").filter({ hasText: "SMTP 连接或握手失败" }).waitFor();
    const row = (await get("/api/notifications")).notifications[0];
    let pending = responseFor(`/api/notifications/${row.id}/resolve`);
    await page.getByRole("button", { name: "核对未发送后重试", exact: true }).click(); assert.equal((await pending).status(), 200);
    pending = responseFor(`/api/notifications/${row.id}/resolve`);
    await page.getByRole("button", { name: "取消待发通知", exact: true }).click(); assert.equal((await pending).status(), 200);
    await page.locator(".notice-row").filter({ hasText: "已取消" }).waitFor();
  });
  await record("mobile layout, page reload and review evidence survive without route mocks", async () => {
    await page.setViewportSize({ width: 390, height: 900 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await stableScreenshot("notifications-390.png");
    await page.goto(new URL("/#module/learning", base).href);
    await showAllCards();
    await page.locator(`.jobs-row[data-id="${card.id}"]`).click();
    await page.getByRole("button", { name: "查看复习记录", exact: true }).click();
    await page.locator(".learning-history").waitFor();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await stableScreenshot("learning-390.png");
    await page.reload(); await showAllCards();
    await page.locator(`.jobs-row[data-id="${card.id}"]`).click();
    assert.equal((await get(`/api/learning/cards/${card.id}/reviews`)).length, 1);
    assert.equal(pageErrors.length, 0, JSON.stringify(pageErrors));
  });
  fs.writeFileSync(path.join(output, "learning-results.json"), JSON.stringify({ passed: true, real_browser: true, route_mocks: false, evidence, pageErrors }, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(output, "learning-failure.png"), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, "learning-results.json"), JSON.stringify({ passed: false, evidence, pageErrors, error: String(error) }, null, 2));
  throw error;
} finally { await browser.close(); }
