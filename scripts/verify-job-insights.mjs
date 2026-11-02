/* Real QA API/files/browser: no route mocks and no external provider calls. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./playwright-runtime.mjs";

const base = new URL(process.env.WEB_QA_URL || "http://invalid/");
const runId = process.env.WEB_QA_RUN_ID || "";
assert(base.protocol === "http:" && base.hostname === "127.0.0.1" && /^[a-f0-9]{12}$/.test(runId));
assert.deepEqual(await (await fetch(new URL("/__qa__/identity", base))).json(), { run_id: runId });
const output = process.env.WEB_QA_OUTPUT; assert(output);
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === "win32" ? { channel: "msedge" } : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const pageErrors = [], evidence = [];
page.on("pageerror", (error) => pageErrors.push(error.message));
page.on("dialog", (d) => d.accept());
const dialog = page.locator('dialog[data-form="job-profile"]');
const get = async (p) => (await page.request.get(new URL(p, base).href)).json();
const responseFor = (p, method) => { const pending = page.waitForResponse((r) => new URL(r.url()).pathname === p && r.request().method() === method); pending.catch(() => {}); return pending; };
const record = async (label, fn) => { await fn(); evidence.push({ label, passed: true }); console.log("PASS insights", label); };
async function clickResponse(button, p, method = "POST", expected = 200) {
  const [response] = await Promise.all([responseFor(p, method), button.click()]);
  assert.equal(response.status(), expected, await response.text());
  return response.json();
}
async function screenshot(name) {
  await page.emulateMedia({ reducedMotion: "reduce" });
  await page.waitForFunction(() => [...document.querySelectorAll("#content .module-surface")].every((el) => getComputedStyle(el).opacity === "1"));
  await page.screenshot({ path: path.join(output, name), fullPage: true });
  await page.emulateMedia({ reducedMotion: "no-preference" });
}
let job;
try {
  const seeded = await page.request.post(new URL("/api/jobs/leads", base).href, { data: { data: { title: `证据对照 QA ${runId}`, company: "合成岗位团队", jd_text: "本科及以上；熟悉 Python；PostgreSQL 优先；每周实习4天。<script>alert(1)</script>" } } });
  assert.equal(seeded.status(), 201); job = await seeded.json();
  await record("private evidence profile saved from UI, no silent external call", async () => {
    await page.goto(new URL(`/#module/job-insights/${job.id}`, base).href);
    await page.getByRole("button", { name: "编辑我的求职证据", exact: true }).click();
    await dialog.getByLabel("技能名称", { exact: true }).fill("Python");
    await dialog.getByLabel("实际做过什么", { exact: true }).fill("在合成 QA 项目中实现了接口；不冒充用户真实经历");
    await dialog.getByLabel("证据来源（仅作文字，不自动读取）").fill("QA README");
    await dialog.getByRole("button", { name: "添加个人事实", exact: true }).click();
    await dialog.getByLabel("事实类型", { exact: true }).selectOption("education");
    await dialog.getByLabel("个人事实（如学历/可到岗日期）").fill("合成学历事实：本科；不是用户信息");
    await dialog.getByLabel("事实依据", { exact: true }).fill("仅用于 QA，人工核实未完成");
    await clickResponse(dialog.getByRole("button", { name: "保存资料", exact: true }), "/api/jobs/profile", "PUT");
    await dialog.waitFor({ state: "hidden" });
    await page.getByText("已有自填证据，仍需核实", { exact: false }).waitFor();
    assert(await page.getByRole("button", { name: "模型补充分析（外发资料）", exact: true }).isDisabled());
  });
  await record("rules persist exact citations and separate hard conditions from skill proof", async () => {
    const result = await clickResponse(page.getByRole("button", { name: "保存离线规则分析", exact: true }), `/api/jobs/leads/${job.id}/analyze`);
    assert.equal(result.analysis.mode, "rules"); assert.equal(result.lead_version, job.version);
    for (const item of [...result.analysis.requirements, ...result.analysis.hard_conditions]) assert.equal(job.data.jd_text.slice(item.start, item.end), item.quote);
    assert.equal(result.analysis.requirements.find((item) => item.name === "Python").assessment, "evidence_supplied");
    assert.equal(result.analysis.requirements.find((item) => item.name === "PostgreSQL").assessment, "not_in_profile");
    await page.getByRole("heading", { name: "硬性条件，需逐条核对", exact: true }).waitFor();
    assert.equal(await page.locator("#content script").count(), 0);
  });
  await record("selected evidence gaps create confirmed cards without claiming inability", async () => {
    await page.locator('#gap-cards-form input[value="PostgreSQL"]').check();
    const result = await clickResponse(page.getByRole("button", { name: "确认把选中项建为复习卡", exact: true }), `/api/jobs/leads/${job.id}/learning-cards`);
    assert.equal(result.created.length, 1); assert.equal(result.created[0].data.source, "jd_gap");
    assert.equal(result.created[0].data.source_id, job.id);
  });
  await record("profile conflicts retain input; bound analysis becomes visibly stale", async () => {
    await page.getByRole("button", { name: "编辑我的求职证据", exact: true }).click();
    await dialog.getByLabel("资料名称", { exact: true }).fill("冲突时保留的本次输入");
    const current = await get("/api/jobs/profile");
    const changed = await page.request.put(new URL("/api/jobs/profile", base).href, { data: { revision: current.revision, data: { ...current.data, title: "另一个标签页已修改的资料" } } });
    assert.equal(changed.status(), 200);
    await clickResponse(dialog.getByRole("button", { name: "保存资料", exact: true }), "/api/jobs/profile", "PUT", 409);
    await page.locator("#profile-form-error").filter({ hasText: "当前输入已保留" }).waitFor();
    assert.equal(await dialog.getByLabel("资料名称", { exact: true }).inputValue(), "冲突时保留的本次输入");
    await dialog.getByRole("button", { name: "取消", exact: true }).click(); await dialog.waitFor({ state: "hidden" });
    await page.getByRole("button", { name: "刷新资料与分析", exact: true }).click();
    await page.getByText("这份冻结分析已过期", { exact: false }).waitFor();
  });
  await record("unknown lead route reports a recoverable error without refetch loop", async () => {
    let queries = 0; const count = (request) => { if (new URL(request.url()).pathname === "/api/jobs/leads") queries++; };
    page.on("request", count);
    await page.goto(new URL("/#module/job-insights/missing-qa-lead", base).href);
    await page.getByRole("alert").filter({ hasText: "指定岗位不存在或已归档" }).waitFor();
    await page.evaluate(() => new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve))));
    assert.equal(queries, 1); page.off("request", count);
    await page.goto(new URL(`/#module/job-insights/${job.id}`, base).href);
    await page.getByRole("heading", { name: "原文要求与个人证据", exact: true }).waitFor();
    await page.setViewportSize({ width: 390, height: 900 });
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await screenshot("job-insights-390.png");
  });
  await record("offline weekly statistics freeze, download and enqueue without duplicate sends", async () => {
    await page.goto(new URL("/#module/job-weekly", base).href);
    await page.getByRole("heading", { name: "当前管道分布（不是历史快照）", exact: true }).waitFor();
    assert(await page.getByRole("button", { name: "模型排序关注项（仅外发统计）", exact: true }).isDisabled());
    const result = await clickResponse(page.getByRole("button", { name: "生成并保存纯统计周报", exact: true }), "/api/jobs/report/weekly");
    const current = await get("/api/jobs/report/weekly");
    assert.deepEqual(result.metrics, current.current.metrics); assert.equal(result.mode, "statistics");
    const downloaded = page.waitForEvent("download");
    await page.getByRole("button", { name: "下载已保存周报", exact: true }).click();
    const file = await downloaded; await file.saveAs(path.join(output, "qa-weekly-report.md"));
    assert(fs.readFileSync(path.join(output, "qa-weekly-report.md"), "utf8").includes("统计口径"));
    for (let i = 0; i < 2; i++) {
      const notice = await clickResponse(page.getByRole("button", { name: "确认周报加入通知队列", exact: true }), "/api/jobs/report/weekly/notify");
      assert.equal(notice.reused, i === 1); assert.equal(notice.notification.data.status, "pending");
    }
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
    await screenshot("job-weekly-390.png");
    await page.reload(); await page.getByRole("heading", { name: "已保存周报", exact: true }).waitFor();
    assert((await get("/api/jobs/report/weekly")).saved);
    assert.equal(pageErrors.length, 0, JSON.stringify(pageErrors));
  });
  fs.writeFileSync(path.join(output, "job-insights-results.json"), JSON.stringify({ passed: true, real_browser: true, route_mocks: false, real_model_quality_verified: false, evidence, pageErrors }, null, 2));
} catch (error) {
  await page.screenshot({ path: path.join(output, "job-insights-failure.png"), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, "job-insights-results.json"), JSON.stringify({ passed: false, evidence, pageErrors, error: String(error) }, null, 2));
  throw error;
} finally { await browser.close(); }
