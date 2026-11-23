/* 只读检查：8771 上的「求职板块」与「Agent 与工作流」两个模块。
   通过 SSH 本地转发 127.0.0.1:18771 访问，令牌由环境变量传入，不落盘、不打印。 */
const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");

const BASE = "https://127.0.0.1:18771";
const OUT = __dirname;

async function main() {
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const context = await browser.newContext({
    ignoreHTTPSErrors: true,
    viewport: { width: 1280, height: 900 },
  });
  const errors = [];
  const login = await context.request.post(BASE + "/api/session", {
    data: { token: process.env.SHILIE_TOKEN },
  });
  if (!login.ok()) throw new Error("login failed: " + login.status());

  const page = await context.newPage();
  page.on("console", (m) => {
    if (m.type() === "error") errors.push(m.text());
  });
  page.on("pageerror", (e) => errors.push("pageerror: " + e.message));

  const report = {};

  // ---------- 求职板块 ----------
  await page.goto(BASE + "/#module/job-flow", { waitUntil: "networkidle" });
  await page.waitForTimeout(1500);
  report.jobflow = await page.evaluate(() => {
    const text = (el) => (el ? el.textContent.trim() : "");
    return {
      title: text(document.querySelector(".page-head h1")),
      pages: [...document.querySelectorAll(".job-flow__page-tab")].map((b) => ({
        label: b.textContent.trim(),
        pressed: b.getAttribute("aria-pressed"),
      })),
      companies: [...document.querySelectorAll(".job-flow__company")].map((b) => b.textContent.trim()),
      stages: [...document.querySelectorAll(".job-flow__stage-tab")].map((b) => b.textContent.trim()),
      headings: [...document.querySelectorAll(".job-flow__heading")].map(text),
      cards: document.querySelectorAll(".job-flow__card").length,
      empties: [...document.querySelectorAll(".empty-state")].map(text),
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    };
  });
  await page.screenshot({ path: path.join(OUT, "jobflow-pipeline-1280.png"), fullPage: true });

  // 切 4 个阶段
  report.stages = {};
  const stageIds = ["intent", "required", "gap", "review"];
  for (const id of stageIds) {
    const btn = page.locator(`[data-action="jobflow-stage"][data-stage="${id}"]`);
    if (await btn.count()) {
      await btn.first().click();
      await page.waitForTimeout(400);
      report.stages[id] = await page.evaluate(() => ({
        headings: [...document.querySelectorAll(".job-flow__heading")].map((e) => e.textContent.trim()),
        cards: document.querySelectorAll(".job-flow__card").length,
        empties: [...document.querySelectorAll(".empty-state")].map((e) => e.textContent.trim()),
      }));
    }
  }
  await page.screenshot({ path: path.join(OUT, "jobflow-stage-review-1280.png"), fullPage: true });

  // 切 4 个页面
  report.pages = {};
  const pageIds = ["pipeline", "prep", "resumes", "ai-resume", "manage"];
  for (const id of pageIds) {
    const btn = page.locator(`[data-action="jobflow-page"][data-page="${id}"]`);
    if (!(await btn.count())) continue;
    await btn.first().click();
    await page.waitForTimeout(900);
    report.pages[id] = await page.evaluate(() => ({
      cards: document.querySelectorAll(".job-flow__card").length,
      headings: [...document.querySelectorAll(".job-flow__heading")].map((e) => e.textContent.trim()),
      empties: [...document.querySelectorAll(".empty-state, .job-flow__placeholder")].map((e) => e.textContent.trim().slice(0, 80)),
      buttons: [...document.querySelectorAll("[data-action^='jobflow-'], .job-flow__page button, .job-flow__page .primary-button")].map((b) => b.textContent.trim()).filter(Boolean).slice(0, 12),
    }));
    await page.screenshot({ path: path.join(OUT, `jobflow-page-${id}-1280.png`), fullPage: true });
  }

  // ---------- Agent 与工作流 ----------
  report.automation = {};
  for (const [route, shot] of [
    ["#module/agents", "automation-agents-1280.png"],
    ["#module/workflows", "automation-workflows-1280.png"],
    ["#module/runs", "automation-runs-1280.png"],
  ]) {
    await page.goto(BASE + "/" + route, { waitUntil: "networkidle" });
    await page.waitForTimeout(1200);
    report.automation[route.slice(9)] = await page.evaluate(() => ({
      h1: (document.querySelector(".page-head h1") || {}).textContent || "",
      h2: [...document.querySelectorAll("h2, h3")].map((e) => e.textContent.trim()).slice(0, 20),
      forms: [...document.querySelectorAll("form")].map((f) => f.id || f.getAttribute("data-studio-form") || ""),
      buttons: [...document.querySelectorAll("button, a.small-button")].map((b) => b.textContent.trim()).filter(Boolean).slice(0, 25),
      rows: document.querySelectorAll(".run-row, .queue-row, .record-row").length,
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    await page.screenshot({ path: path.join(OUT, shot), fullPage: true });
  }

  // ---------- 窄屏 ----------
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto(BASE + "/#module/job-flow", { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  report.narrow = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  await page.screenshot({ path: path.join(OUT, "jobflow-390.png"), fullPage: true });
  await page.goto(BASE + "/#module/workflows", { waitUntil: "networkidle" });
  await page.waitForTimeout(1000);
  report.narrowWorkflows = await page.evaluate(() => ({
    scrollWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
  }));
  await page.screenshot({ path: path.join(OUT, "workflows-390.png"), fullPage: true });

  report.errors = errors;
  fs.writeFileSync(path.join(OUT, "report.json"), JSON.stringify(report, null, 2));
  console.log(JSON.stringify(report, null, 2));
  await browser.close();
}

main().catch((e) => {
  console.error("CHECK_FAILED", e);
  process.exit(1);
});
