/* Real browser + owned QA PostgreSQL. No route mocks, production URL or paid model. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./playwright-runtime.mjs";

const base = new URL(process.env.WEB_QA_URL || "http://invalid/");
const runId = process.env.WEB_QA_RUN_ID || "";
assert(base.protocol === "http:" && base.hostname === "127.0.0.1" && /^[a-f0-9]{12}$/.test(runId), "Requires owned disposable QA identity");
assert.deepEqual(await (await fetch(new URL("/__qa__/identity", base))).json(), { run_id: runId });
const output = process.env.WEB_QA_OUTPUT;
assert(output, "Explicit artifact directory required");
fs.mkdirSync(output, { recursive: true });
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === "win32" ? { channel: "msedge" } : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [], evidence = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("dialog", (dialog) => dialog.accept());
const dialog = page.locator('dialog[data-form="jobs"]');
const record = async (label, body) => { await body(); evidence.push({ label, passed: true }); console.log("PASS jobs", label); };
async function save(endpoint, status = 201) {
  const pending = page.waitForResponse((r) => new URL(r.url()).pathname === endpoint && ["POST", "PUT"].includes(r.request().method()));
  await dialog.getByRole("button", { name: "保存", exact: true }).click();
  const response = await pending;
  assert.equal(response.status(), status, await response.text());
  const row = await response.json();
  await page.waitForFunction(() => !document.querySelector('#jobs-form [type="submit"]').disabled);
  if (status < 400) await dialog.waitFor({ state: "hidden" });
  return row;
}
async function archive(button) {
  const response = page.waitForResponse((r) => new URL(r.url()).pathname.startsWith("/api/records/") && r.request().method() === "DELETE");
  await button.click();
  assert.equal((await response).status(), 200);
  await page.waitForResponse((r) => new URL(r.url()).pathname === "/api/jobs");
}
async function restore() {
  const pending = page.waitForResponse((r) => new URL(r.url()).pathname.endsWith("/restore") && r.request().method() === "POST");
  await page.getByRole("button", { name: "恢复记录", exact: true }).click();
  assert.equal((await pending).status(), 200);
  await page.waitForResponse((r) => new URL(r.url()).pathname === "/api/jobs");
}
let lead, app;
const name = `Python 实习 ${runId} <img src=x onerror=alert(1)>`;
try {
  await record("create real lead, preserve source and escape user HTML", async () => {
    await page.goto(new URL("/#module/jobs", base).href);
    await page.getByRole("button", { name: "添加岗位", exact: true }).click();
    await dialog.getByLabel("公司", { exact: true }).fill("示例招聘团队");
    await dialog.getByLabel("岗位名称", { exact: true }).fill(name);
    await dialog.getByLabel("来源链接（选填）").fill("https://example.com/jobs");
    await dialog.getByLabel("岗位原文（选填）").fill("需要 Python、FastAPI、PostgreSQL；此为隔离合成岗位。");
    lead = await save("/api/jobs/leads");
    await page.getByRole("button", { name: "添加投递", exact: true }).waitFor();
    assert.equal(await page.locator(".jobs-detail img").count(), 0);
  });
  await record("application and due-followup use real saved state", async () => {
    await page.getByRole("button", { name: "添加投递", exact: true }).click();
    await dialog.getByLabel("状态", { exact: true }).selectOption("applied");
    await dialog.getByLabel("投递渠道（选填）").fill("官网");
    await dialog.getByLabel("下次跟进时间（选填）").fill("2020-01-01T09:00");
    app = await save("/api/jobs/applications");
    await page.locator(`.jobs-row[data-id="${app.id}"]`).waitFor();
    assert(app.data.applied_at);
    assert((await page.locator(".jobs-caption").first().textContent()).includes("1 条已到跟进时间"));
  });
  await record("409 keeps dialog and unsaved input intact", async () => {
    await page.getByRole("button", { name: "编辑记录", exact: true }).click();
    await dialog.getByLabel("备注（选填）").fill("冲突时必须保留的本次输入");
    const changed = await page.request.patch(new URL(`/api/jobs/applications/${app.id}`, base).href, { data: { version: app.version, data: { channel: "另一个标签页修改" } } });
    assert.equal(changed.status(), 200);
    await save(`/api/jobs/applications/${app.id}`, 409);
    assert(await dialog.isVisible());
    assert.equal(await dialog.getByLabel("备注（选填）").inputValue(), "冲突时必须保留的本次输入");
    assert((await page.locator("#jobs-form-error").textContent()).includes("当前输入已保留"));
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
    const refreshed = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/jobs");
    await page.getByRole("button", { name: "刷新", exact: true }).click(); await refreshed;
  });
  await record("advance to interview and record actual questions without implicit cards", async () => {
    await page.getByRole("button", { name: "编辑记录", exact: true }).click();
    await dialog.getByLabel("状态", { exact: true }).selectOption("interviewing");
    app = await save(`/api/jobs/applications/${app.id}`, 200);
    await page.getByRole("button", { name: "记录面试复盘", exact: true }).click();
    await dialog.getByLabel("问题", { exact: true }).fill("接口重试如何避免重复写入？");
    await dialog.getByLabel("当时回答与卡壳点").fill("说到了幂等键，没有说明执行后记账前崩溃窗口。");
    await dialog.getByLabel("自评", { exact: true }).selectOption("2");
    await dialog.getByLabel("薄弱点（每行一项，保存不会自动建卡）").fill("外部副作用的未知状态");
    await dialog.getByLabel("下一步行动（每行一项）").fill("补一组崩溃恢复反例");
    await save("/api/jobs/reports");
    await page.getByRole("heading", { name: "薄弱点（待确认复习候选）", exact: true }).waitFor();
    assert((await page.locator(".jobs-detail").textContent()).includes("外部副作用的未知状态"));
  });
  await record("desktop and 390px layouts do not overflow", async () => {
    await page.locator(".jobs-row").filter({ hasText: name }).click();
    for (const width of [1440, 390]) {
      await page.setViewportSize({ width, height: 960 });
      assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
      await page.screenshot({ path: path.join(output, `jobs-${width}.png`), fullPage: true });
    }
    await page.getByRole("button", { name: "编辑记录", exact: true }).click();
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await page.screenshot({ path: path.join(output, "jobs-form-390.png"), fullPage: true });
    await dialog.getByRole("button", { name: "取消", exact: true }).click();
  });
  await record("archive and restore app and report through the UI", async () => {
    await archive(page.getByRole("button", { name: "归档复盘", exact: true }));
    await archive(page.getByRole("button", { name: "移入回收站", exact: true }));
    await page.getByRole("button", { name: "回收站", exact: true }).click();
    await page.locator(".jobs-row").filter({ hasText: name }).filter({ hasNotText: "轮复盘" }).click();
    await restore();
    await page.locator(".jobs-row").filter({ hasText: "轮复盘" }).click();
    await restore();
    await page.getByRole("button", { name: "返回有效记录", exact: true }).click();
    await page.locator(".jobs-row").filter({ hasText: name }).click();
    await page.getByRole("heading", { name: "接口重试如何避免重复写入？", exact: true }).waitFor();
    await page.reload();
    await page.locator(".jobs-row").filter({ hasText: name }).click();
    await page.getByRole("heading", { name: "接口重试如何避免重复写入？", exact: true }).waitFor();
    assert.equal(pageErrors.length, 0, JSON.stringify(pageErrors));
  });
  fs.writeFileSync(path.join(output, "jobs-results.json"), JSON.stringify({ passed: true, database: "owned disposable PostgreSQL", real_browser: true, route_mocks: false, evidence, pageErrors, lead: lead.id, application: app.id }, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(output, "jobs-failure.png"), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, "jobs-results.json"), JSON.stringify({ passed: false, evidence, pageErrors, error: String(error) }, null, 2));
  throw error;
} finally { await browser.close(); }
