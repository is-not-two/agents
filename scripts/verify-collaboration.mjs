/* Real browser/API, no route mocks or paid providers; default-off manual path. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./playwright-runtime.mjs";
const base = new URL(process.env.WEB_QA_URL || "http://invalid/"), id = process.env.WEB_QA_RUN_ID || "", output = process.env.WEB_QA_OUTPUT;
assert(base.hostname === "127.0.0.1" && base.protocol === "http:" && /^[a-f0-9]{12}$/.test(id) && output);
assert.deepEqual(await (await fetch(new URL("/__qa__/identity", base))).json(), { run_id: id });
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === "win32" ? { channel: "msedge" } : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const root = page.locator(".collaboration-page"), evidence = [], errors = [];
page.on("pageerror", (e) => errors.push(e.message)); page.on("dialog", (d) => d.accept());
async function record(label, fn) { await fn(); evidence.push({ label, passed: true }); console.log("PASS collaboration", label); }
async function clickResponse(button, route, method = "POST", status = 200) {
  const wait = page.waitForResponse((r) => new URL(r.url()).pathname === route && r.request().method() === method); wait.catch(() => {});
  const [response] = await Promise.all([wait, button.click()]); assert.equal(response.status(), status, await response.text()); return response.json();
}
async function create(title) { const r = await page.request.post(new URL("/api/agents", base).href, { data: { data: { title, generate: false } } }); assert.equal(r.status(), 201); return r.json(); }
let owner, workers, run;
const query = `人工私有计划 ${id} <img src=x onerror=alert(1)>`;
try {
  workers = [await create(`Draft QA ${id}`), await create(`Review QA ${id}`)]; owner = await create(`Supervisor QA ${id}`);
  await page.goto(new URL("/#module/collaboration", base).href);
  await root.getByLabel("Supervisor", { exact: true }).selectOption(owner.id);
  await page.locator(`.collaboration-page[data-owner="${owner.id}"]`).waitFor();
  await record("default-off feature exposes no paid action; allowlist saved without model use", async () => {
    assert(await root.getByRole("button", { name: "让Supervisor生成新计划（可能计费）", exact: true }).isDisabled());
    for (const worker of workers) await root.locator(`input[name="worker"][value="${worker.id}"]`).check();
    owner = await clickResponse(root.getByRole("button", { name: "保存交接白名单", exact: true }), `/api/agents/${owner.id}`, "PUT");
    await root.getByText("Supervisor v2", { exact: false }).waitFor();
    assert.deepEqual(new Set(owner.data.handoffs.allowed), new Set(workers.map((w) => w.id)));
  });
  await record("manual plan and actual frozen worker versions require a separate confirmation", async () => {
    await root.getByLabel("协作任务", { exact: true }).fill(query);
    for (let i = 0; i < 2; i++) {
      await root.getByRole("button", { name: "添加步骤", exact: true }).click();
      const step = root.locator('form[data-collab-form="plan"] fieldset').nth(i);
      await step.getByLabel(`步骤 ${i + 1} Worker`, { exact: true }).selectOption(workers[i].id);
      await step.getByLabel("Worker输入", { exact: true }).fill(`只读步骤 ${i} ${query}`);
      await step.getByLabel("预期产物", { exact: true }).fill("引用与缺口，不执行外发");
    }
    run = await clickResponse(root.getByRole("button", { name: "创建人工计划（不执行）", exact: true }), "/api/collaborations", "POST", 201);
    assert.equal(run.data.status, "awaiting_confirmation"); assert.equal(run.data.shared_state.budget.model_used, 0);
    await root.getByRole("button", { name: "确认人工计划（不派发）", exact: true }).waitFor();
    assert.equal(await root.locator('[data-collab-result] img').count(), 0);
    run = await clickResponse(root.getByRole("button", { name: "确认人工计划（不派发）", exact: true }), `/api/collaborations/${run.id}/confirm`);
    assert.equal(run.data.status, "confirmed"); assert.equal(run.data.shared_state.board.length, 0);
    assert.deepEqual(run.data.shared_state.plan.map((s) => s.version), [1, 1]);
    await root.getByRole("heading", { name: "计划已确认，尚未派发", exact: true }).waitFor();
    assert(await root.getByRole("button", { name: "执行已确认计划（可能计费）", exact: true }).isDisabled());
  });
  await record("private collaboration is absent from public backup and cannot use ordinary confirmation", async () => {
    const exported = await (await page.request.get(new URL("/api/export", base).href)).text();
    assert(!exported.includes(run.id) && !exported.includes(query));
    assert.equal((await page.request.post(new URL(`/api/agent-runs/${run.id}/confirm`, base).href, { data: { version: run.version, approve: true } })).status(), 404);
    const stopped = await clickResponse(root.getByRole("button", { name: "核对后终止，不重试", exact: true }), `/api/collaborations/${run.id}/abort`);
    assert.equal(stopped.data.status, "failed"); run = stopped;
    await root.getByRole("heading", { name: "已停止", exact: true }).waitFor();
  });
  await record("peer version conflict retains unsaved checkboxes; desktop/mobile/reload remain usable", async () => {
    const changed = await page.request.put(new URL(`/api/agents/${owner.id}`, base).href, { data: { version: owner.version, data: { title: owner.data.title + " changed" } } }); assert.equal(changed.status(), 200);
    await root.locator(`input[name="worker"][value="${workers[1].id}"]`).uncheck();
    await clickResponse(root.getByRole("button", { name: "保存交接白名单", exact: true }), `/api/agents/${owner.id}`, "PUT", 409);
    assert(!(await root.locator(`input[name="worker"][value="${workers[1].id}"]`).isChecked()));
    await root.getByText("输入保留", { exact: false }).waitFor();
    await root.getByRole("button", { name: "刷新协作记录", exact: true }).click();
    await root.getByText("Supervisor v3", { exact: false }).waitFor();
    await page.setViewportSize({ width: 390, height: 844 }); await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(() => [...document.querySelectorAll("#content .module-surface")].every((e) => getComputedStyle(e).opacity === "1"));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    assert((await root.locator('input[name="worker"]').first().boundingBox()).width < 25, "Native checkboxes must not inherit full-width text-input styling");
    await page.screenshot({ path: path.join(output, "collaboration-390.png"), fullPage: true });
    await page.reload(); await root.getByLabel("Supervisor", { exact: true }).selectOption(owner.id);
    await root.getByRole("heading", { name: "已停止", exact: true }).waitFor();
    assert(await root.getByRole("button", { name: "让Supervisor生成新计划（可能计费）", exact: true }).isDisabled());
  });
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: path.join(output, "collaboration-failure.png"), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, "collaboration-failure.html"), await page.content()); throw error;
} finally {
  fs.writeFileSync(path.join(output, "collaboration-results.json"), JSON.stringify({ evidence, errors }, null, 2)); await browser.close();
}
