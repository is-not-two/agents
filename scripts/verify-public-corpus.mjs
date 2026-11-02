/* Genuine isolated API/files/browser, no route mocks or semantic-quality claim. */
import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import { loadPlaywright } from "./playwright-runtime.mjs";
const base = new URL(process.env.WEB_QA_URL || "http://invalid/"), id = process.env.WEB_QA_RUN_ID || "", output = process.env.WEB_QA_OUTPUT;
assert(base.hostname === "127.0.0.1" && base.protocol === "http:" && /^[a-f0-9]{12}$/.test(id) && output);
assert.deepEqual(await (await fetch(new URL("/__qa__/identity", base))).json(), { run_id: id });
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : process.platform === "win32" ? { channel: "msedge" } : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } }), evidence = [], errors = [];
page.on("pageerror", (e) => errors.push(e.message)); page.on("dialog", (d) => { errors.push("Unexpected dialog: " + d.message()); d.dismiss(); });
async function record(label, fn) { await fn(); evidence.push({ label, passed: true }); console.log("PASS public-corpus", label); }
async function search(query, namespace) {
  const form = page.locator("#search-form");
  await form.locator('select[name="scope"]').selectOption("docs"); await form.getByLabel("技术语料域", { exact: true }).selectOption(namespace);
  await form.locator('input[name="query"]').fill(query);
  const wait = page.waitForResponse((r) => new URL(r.url()).pathname === "/api/query" && r.request().method() === "POST"); wait.catch(() => {});
  const [r] = await Promise.all([wait, form.getByRole("button", { name: "搜索", exact: true }).click()]); assert.equal(r.status(), 200, await r.text());
  const data = await r.json(); await page.waitForFunction(() => !document.querySelector('#search-form[aria-busy="true"]')); return data;
}
try {
  await page.goto(new URL("/#module/documents", base).href);
  await record("server-owned corpus options and explicit public search use real file data", async () => {
    const data = await search("PUBLIC_ONLY", "public_docs"); assert.equal(data.namespace, "public_docs"); assert(data.hits.length);
    assert(data.hits.every((h) => h.namespace === "public_docs")); assert(!JSON.stringify(data).includes("PRIVATE_ONLY"));
    await page.locator(".result-meta").filter({ hasText: "public_docs" }).waitFor();
    assert.equal(await page.locator(".result-list img").count(), 0);
  });
  await record("same query and shared IDs cannot cross the selected corpus boundary", async () => {
    assert.equal((await search("PRIVATE_ONLY", "public_docs")).hits.length, 0);
    const privateResult = await search("PRIVATE_ONLY", "tech_doc"); assert(privateResult.hits.length); assert.equal(privateResult.namespace, "tech_doc");
    assert.equal((await search("PRIVATE_ONLY", "public_docs")).hits.length, 0);
  });
  await record("unapproved namespace and caller-supplied table are rejected without model use", async () => {
    const bad = await page.request.post(new URL("/api/query", base).href, { data: { query: "PRIVATE_ONLY", scope: "docs", namespace: "public_docs; DROP TABLE x" } }); assert.equal(bad.status(), 400);
    const extra = await page.request.post(new URL("/api/query", base).href, { data: { query: "PRIVATE_ONLY", scope: "docs", namespace: "public_docs", table_name: "rag_chunks" } }); assert([400, 422].includes(extra.status()));
  });
  await record("390px and reload expose actual server default, never mislabel old results", async () => {
    await search("PUBLIC_ONLY", "public_docs"); await page.setViewportSize({ width: 390, height: 844 }); await page.emulateMedia({ reducedMotion: "reduce" });
    await page.waitForFunction(() => [...document.querySelectorAll("#content .module-surface")].every((e) => getComputedStyle(e).opacity === "1"));
    assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth + 1));
    await page.screenshot({ path: path.join(output, "public-corpus-390.png"), fullPage: true });
    await page.reload(); await page.locator('#search-form select[name="namespace"]').waitFor();
    assert.equal(await page.locator('#search-form select[name="namespace"]').inputValue(), "tech_doc");
    assert.equal(await page.locator(".result-card").count(), 0);
  });
  assert.deepEqual(errors, []);
} catch (error) {
  await page.screenshot({ path: path.join(output, "public-corpus-failure.png"), fullPage: true }).catch(() => {});
  fs.writeFileSync(path.join(output, "public-corpus-failure.html"), await page.content()); throw error;
} finally {
  fs.writeFileSync(path.join(output, "public-corpus-results.json"), JSON.stringify({ evidence, errors }, null, 2)); await browser.close();
}
