/* Real API/browser boundary: explicit memory decisions, no route mocks/provider use. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./playwright-runtime.mjs";

const base = new URL(process.env.WEB_QA_URL || "http://invalid/");
const runId = process.env.WEB_QA_RUN_ID || "", output = process.env.WEB_QA_OUTPUT;
assert(base.hostname === "127.0.0.1" && base.protocol === "http:" && /^[a-f0-9]{12}$/.test(runId) && output);
assert.deepEqual(await (await fetch(new URL("/__qa__/identity", base))).json(), { run_id: runId });
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === "win32" ? { channel: "msedge" } : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
const errors = [], evidence = [];
page.on("pageerror", (e) => errors.push(e.message)); page.on("dialog", (d) => d.accept());
const studio = page.locator(".agent-studio");
async function record(label, fn) { await fn(); evidence.push({ label, passed: true }); console.log("PASS studio", label); }
async function clickResponse(button, route, method = "POST", status = 200) {
  const pending = page.waitForResponse((r) => new URL(r.url()).pathname === route && r.request().method() === method); pending.catch(() => {});
  const [response] = await Promise.all([pending, button.click()]); assert.equal(response.status(), status, await response.text()); return response.json();
}
const fact = `合成偏好 QA ${runId} <img src=x onerror=alert(1)>`;
let owner, memory;
try {
  const response = await page.request.post(new URL("/api/agents", base).href, { data: { data: { title: `工作室 QA ${runId}`, generate: false, scopes: ["personal"], tool_ids: ["knowledge_draft"] } } });
  assert.equal(response.status(), 201); owner = await response.json();
  await page.goto(new URL("/#module/agent-studio", base).href);
  await studio.getByLabel("选择 Agent", { exact: true }).selectOption(owner.id);
  await page.locator(`.agent-studio[data-owner="${owner.id}"]`).waitFor();
  await studio.getByText("配置版本 1。", { exact: false }).waitFor();
  await record("default memory disabled, model requests disabled and budget settings persist", async () => {
    assert.equal(await studio.getByLabel("记忆范围", { exact: true }).inputValue(), "none");
    assert(await studio.getByRole("button", { name: "开始新运行（调用模型）", exact: true }).isDisabled());
    assert(await studio.getByRole("button", { name: "提出记忆候选（未生效）", exact: true }).isDisabled());
    await studio.getByLabel("累计模型轮数（可空）", { exact: true }).fill("3");
    await studio.getByLabel("上下文策略", { exact: true }).selectOption("verbatim_window");
    await studio.getByLabel("记忆范围", { exact: true }).selectOption("persistent");
    owner = await clickResponse(studio.getByRole("button", { name: "保存可靠性设置", exact: true }), `/api/agents/${owner.id}`, "PUT");
    await studio.getByText("配置版本 2。", { exact: false }).waitFor();
    assert.equal(owner.data.budget.max_rounds, 3);
    assert.equal(owner.data.context.strategy, "verbatim_window");
  });
  await record("plain text candidate is pending, explicit confirmation is required and XSS does not execute", async () => {
    await studio.getByLabel("拟记住的内容", { exact: true }).fill(fact);
    memory = await clickResponse(studio.getByRole("button", { name: "提出记忆候选（未生效）", exact: true }), `/api/agents/${owner.id}/memory`, "POST", 201);
    assert.equal(memory.data.state, "pending"); await studio.getByText("待确认", { exact: true }).waitFor();
    assert.equal(await studio.locator("[data-studio-memory] img").count(), 0);
    const confirmed = await clickResponse(studio.getByRole("button", { name: "确认保存长期记忆", exact: true }), `/api/agents/${owner.id}/memory/${memory.id}/decide`);
    assert.equal(confirmed.data.state, "confirmed"); memory = confirmed; await studio.getByText("已生效", { exact: true }).waitFor();
    const exported = await (await page.request.get(new URL("/api/export?format=json", base).href)).text();
    assert(!exported.includes(fact) && !exported.includes(memory.id));
  });
  await record("409 leaves reliability form input intact rather than silently overwriting", async () => {
    const external = await page.request.put(new URL(`/api/agents/${owner.id}`, base).href, { data: { version: owner.version, data: { title: owner.data.title + " changed" } } });
    assert.equal(external.status(), 200); owner = await external.json();
    await studio.getByLabel("温度（可空）", { exact: true }).fill("0.7");
    await clickResponse(studio.getByRole("button", { name: "保存可靠性设置", exact: true }), `/api/agents/${owner.id}`, "PUT", 409);
    assert.equal(await studio.getByLabel("温度（可空）", { exact: true }).inputValue(), "0.7");
    await studio.getByText("输入已保留", { exact: false }).waitFor();
    await studio.getByRole("button", { name: "刷新 Agent 工作室", exact: true }).click();
    await studio.getByText("配置版本 3。", { exact: false }).waitFor();
  });
  await record("forget stops active use, keeps an explicit audit state and cannot be generic-restored", async () => {
    const result = await clickResponse(studio.getByRole("button", { name: "确认遗忘", exact: true }), `/api/agents/${owner.id}/memory/${memory.id}/decide`);
    assert.equal(result.data.state, "forgotten"); memory = result; await studio.getByText("已遗忘", { exact: true }).waitFor();
    const restored = await page.request.post(new URL(`/api/records/${memory.id}/restore`, base).href, { data: { current_version: memory.version, target_version: 2 } }); assert.equal(restored.status(), 409);
  });
  await record("manual private run exposes audit without pretending model use; mobile and reload persist", async () => {
    const run = await clickResponse(studio.getByRole("button", { name: "只读草稿试运行（不调用模型）", exact: true }), `/api/agents/${owner.id}/tools/call`);
    assert.equal(run.kind, "agent_session"); assert.equal(run.data.mode, "manual"); assert.equal(run.data.model_steps, 0);
    await studio.getByText("运行详情：completed", { exact: true }).waitFor();
    await clickResponse(studio.getByRole("button", { name: "结束会话（不再续聊）", exact: true }), `/api/agent-runs/${run.id}/close`);
    await studio.getByText("此会话已结束，不再续聊。", { exact: false }).waitFor();
    assert.equal(await studio.getByRole("button", { name: "继续此会话（调用模型）", exact: true }).count(), 0);
    const exported = await (await page.request.get(new URL("/api/export?format=json", base).href)).text(); assert(!exported.includes(run.id));
    await page.setViewportSize({ width: 390, height: 844 });
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(() => [...document.querySelectorAll("#content .module-surface")].every((el) => getComputedStyle(el).opacity === "1"));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({ path: path.join(output, "agent-studio-390.png"), fullPage: true });
    await page.reload();
    await studio.getByLabel("选择 Agent", { exact: true }).selectOption(owner.id);
    await studio.getByText("已遗忘", { exact: true }).waitFor();
    await studio.getByText("运行详情：completed", { exact: true }).waitFor();
    assert(await studio.getByRole("button", { name: "开始新运行（调用模型）", exact: true }).isDisabled());
  });
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: path.join(output, "agent-studio-failure.png"), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, "agent-studio-failure.html"), await page.content());
  throw error;
} finally {
  fs.writeFileSync(path.join(output, "agent-studio-results.json"), JSON.stringify({ evidence, errors }, null, 2));
  await browser.close();
}
