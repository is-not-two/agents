import assert from "node:assert/strict";
import { join } from "node:path";
import { gzipSync } from "node:zlib";
import { readdir, readFile, stat } from "node:fs/promises";
import { pathToFileURL } from "node:url";
import { loadPlaywright } from "../../scripts/playwright-runtime.mjs";

const base = process.env.SHILIE_DEMO_URL || "http://127.0.0.1:5174";
const out = process.env.SHILIE_DEMO_SCREENSHOTS;
const dist = process.env.SHILIE_BUILD_DIR ? pathToFileURL(join(process.env.SHILIE_BUILD_DIR, "/")) : new URL("../dist/", import.meta.url);
const { chromium } = await loadPlaywright();
const browser = await chromium.launch(process.env.BROWSER_EXECUTABLE
  ? { executablePath: process.env.BROWSER_EXECUTABLE }
  : process.platform === "win32" ? { executablePath: "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe" }
  : { channel: process.env.BROWSER_CHANNEL || "chrome" });
const capture = async (page, file) => {
  if (out) await page.screenshot({ path: join(out, file), fullPage: true, animations: "disabled" });
};
try {
  const page = await browser.newPage({ viewport: { width: 1440, height: 900 } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  await page.goto(base + "/#/");
  await page.getByRole("heading", { name: "进入时列" }).waitFor();
  await capture(page, "01-login.png");
  await page.getByRole("button", { name: "进入演示" }).click();
  const start = page.getByRole("link", { name: "开始", exact: true });
  await start.waitFor();
  assert.equal(await page.locator(".workspace-sidebar,.topbar").count(), 0);
  assert.equal(await page.locator(".start-trail").first().evaluate(e => getComputedStyle(e).animationName), "start-draw");
  await capture(page, "00-start.png");
  await start.click();
  await page.locator(".category-card").last().waitFor();
  await page.locator(".workspace-sidebar").waitFor();
  assert(page.url().endsWith("#/workspace"));
  const sidebar = page.locator(".workspace-sidebar");
  const jobsGroup = sidebar.getByRole("button", { name: "求职", exact: true });
  await jobsGroup.click();
  assert.equal(await jobsGroup.getAttribute("aria-expanded"), "true");
  const jobsLinks = jobsGroup.locator("..").locator(".workspace-modules a");
  const flowLink = sidebar.getByRole("link", { name: "求职流水线", exact: true });
  assert.deepEqual(await jobsLinks.allTextContents(), ["求职流水线"]);
  assert.equal(await flowLink.isVisible(), true);
  await jobsGroup.click();
  assert.equal(await jobsGroup.getAttribute("aria-expanded"), "false");
  assert.equal(await flowLink.isVisible(), false);
  assert(page.url().endsWith("#/workspace"));
  await jobsGroup.click();
  assert.equal(await page.locator(".category-card").count(), 5);
  assert.equal(await page.locator(".category-card:nth-child(5)").evaluate(e => getComputedStyle(e).animationDelay), "0.32s");
  await page.locator(".stat-card b").last().filter({ hasText: /^13$/ }).waitFor();
  await capture(page, "02-home.png");
  await page.locator(".category-card").filter({ has: page.getByRole("heading", { name: "求职", exact: true }) }).click();
  await page.getByRole("navigation", { name: "求职模块列表" }).waitFor();
  assert.equal(await page.locator(".module-card").count(), 1);
  await capture(page, "03-category.png");
  await page.getByRole("navigation", { name: "求职模块列表" }).getByRole("link", { name: /求职流水线/ }).click();
  const flowSections = page.getByRole("navigation", { name: "流水线内功能" });
  await flowSections.waitFor();
  assert.deepEqual(await flowSections.getByRole("link").allTextContents(),
    ["投递记录", "个人简历", "目标公司能力", "岗位证据对照", "求职周报", "预面试", "AI 改简历", "单表管理"]);
  await page.getByRole("link", { name: /松屿实验室/ }).click();
  await page.getByRole("heading", { name: "松屿实验室", exact: true, level: 1 }).waitFor();
  assert.equal(await page.getByText("潮间工作室", { exact: true }).count(), 0);
  assert.equal(await page.locator(".breadcrumbs a").count(), 3);
  assert.equal(await page.locator(".workspace-sidebar").getByRole("link", { name: "求职流水线", exact: true }).getAttribute("aria-current"), "page");
  await jobsGroup.click();
  assert.equal(await jobsGroup.getAttribute("aria-expanded"), "false");
  await page.reload();
  await page.getByRole("heading", { name: "松屿实验室", exact: true, level: 1 }).waitFor();
  assert.equal(await jobsGroup.getAttribute("aria-expanded"), "false");
  await jobsGroup.click();
  assert.equal(await sidebar.getByRole("link", { name: "求职流水线", exact: true }).getAttribute("aria-current"), "page");
  await capture(page, "04-company.png");
  await page.goBack();
  await page.getByRole("heading", { name: "公司列表", exact: true }).waitFor();
  await page.keyboard.press("Control+k");
  await page.getByRole("dialog", { name: "快速打开模块" }).waitFor();
  await page.getByRole("textbox", { name: "搜索模块" }).fill("个人知识库");
  await capture(page, "05-command.png");
  await page.keyboard.press("Enter");
  await page.getByRole("heading", { name: "个人知识库", exact: true }).waitFor();
  await page.getByRole("heading", { name: "检索实验笔记" }).waitFor();
  await page.getByRole("button", { name: "新建笔记" }).click();
  await page.getByLabel("标题", { exact: true }).fill("迁移验收笔记");
  await page.getByLabel("正文", { exact: true }).fill("用于验证版本恢复的合成内容。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("link", { name: /迁移验收笔记/ }).click();
  await page.getByRole("button", { name: "编辑", exact: true }).click();
  await page.getByLabel("正文", { exact: true }).fill("改后的测试内容。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("改后的测试内容。", { exact: true }).waitFor();
  page.on("dialog", dialog => dialog.accept());
  await page.getByRole("button", { name: "移入回收站" }).click();
  await page.getByRole("button", { name: "回收站", exact: true }).click();
  await page.getByRole("link", { name: /迁移验收笔记/ }).click();
  await page.getByRole("button", { name: "查看版本历史" }).click();
  await page.getByRole("listitem").filter({ hasText: /第 1 版/ }).getByRole("button", { name: "恢复此版本" }).click();
  await page.locator("dd").getByText("用于验证版本恢复的合成内容。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "移入回收站" }).click();
  await sidebar.getByRole("link", { name: "回收站" }).click();
  await page.getByRole("article").filter({ hasText: "迁移验收笔记" }).getByRole("button", { name: "恢复" }).click();
  await page.getByText("回收站为空。", { exact: true }).waitFor();

  await page.getByRole("link", { name: "求职流水线", exact: true }).click();
  await page.getByRole("link", { name: /松屿实验室/ }).click();
  await page.getByRole("button", { name: "添加岗位" }).click();
  await page.getByLabel("岗位名称").fill("迁移验收工程师");
  await page.getByLabel("招聘原文").fill("负责可靠性测试与知识检索。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("heading", { name: "迁移验收工程师", exact: true }).waitFor();
  await page.getByRole("button", { name: "记录投递" }).click();
  await page.getByLabel("投递渠道").fill("本地验收");
  const statusChoices = page.locator("form").getByRole("combobox").filter({ has: page.getByRole("option", { name: "已投递", exact: true }) });
  assert.equal(await statusChoices.locator('option[value="interviewing"]').count(), 0);
  await statusChoices.selectOption("applied");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("渠道：本地验收").waitFor();
  assert.equal(await page.getByRole("button", { name: "记录复盘" }).isDisabled(), true);
  await page.getByRole("button", { name: "编辑投递" }).click();
  await statusChoices.selectOption("interviewing");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByRole("button", { name: "记录复盘" }).click();
  await page.getByLabel("问题", { exact: true }).fill("如何验证检索？");
  await page.getByLabel("回答复盘").fill("先建立基线。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("第 1 轮面试复盘").click();
  await page.getByText(/如何验证检索？：先建立基线。/).waitFor();
  await page.getByRole("button", { name: "编辑复盘", exact: true }).click();
  await page.getByLabel("回答复盘").fill("更新后的复盘。");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  const summary = page.getByText("第 1 轮面试复盘", { exact: true });
  const reportDetail = summary.locator("..");
  if (await reportDetail.getAttribute("open") === null) await summary.click();
  await page.getByText(/如何验证检索？：更新后的复盘。/).waitFor();
  await page.getByRole("button", { name: "复盘历史", exact: true }).click();
  const reviewHistory = page.getByRole("region", { name: "复盘版本历史" });
  await reviewHistory.getByText(/第 1 版/).click();
  await reviewHistory.getByText(/如何验证检索？：先建立基线。/).waitFor();
  await page.getByRole("button", { name: "归档复盘", exact: true }).click();
  await summary.waitFor({ state: "detached" });
  await page.getByRole("button", { name: "预面试", exact: true }).click();
  await page.getByRole("button", { name: "上传简历" }).click();
  await page.getByLabel("简历文件").setInputFiles({ name: "fixture.txt", mimeType: "text/plain", buffer: Buffer.from("合成简历，演示测试。") });
  await page.getByRole("button", { name: "上传并解析" }).click();
  const practice = page.getByRole("button", { name: "生成练习" });
  await practice.click();
  await page.getByLabel("回答", { exact: true }).fill("先对照基线，再验证改动。");
  await page.getByRole("button", { name: "保存练习" }).click();
  await page.getByText("预面试 · 迁移验收工程师", { exact: true }).click();
  await page.getByText(/先对照基线，再验证改动。/).waitFor();
  await page.getByRole("button", { name: "能力要求", exact: true }).click();
  await page.getByRole("button", { name: "添加能力清单", exact: true }).click();
  assert.equal(await page.getByLabel("公司", { exact: true }).inputValue(), "松屿实验室");
  assert.equal(await page.getByLabel("公司", { exact: true }).isEditable(), false);
  await page.getByLabel("名称", { exact: true }).fill("合成检索能力");
  await page.getByRole("button", { name: "保存", exact: true }).click();
  await page.getByText("合成检索能力", { exact: true }).waitFor();
  await page.getByRole("button", { name: "能力差距", exact: true }).click();
  await page.getByText("合成检索能力", { exact: true }).waitFor();
  assert.deepEqual(await jobsLinks.allTextContents(), ["求职流水线"]);
  await flowLink.click();
  await flowSections.getByRole("link", { name: "个人简历", exact: true }).click();
  await page.getByRole("heading", { name: "个人简历", exact: true, level: 1 }).waitFor();
  assert.equal(await flowLink.getAttribute("aria-current"), "page");
  assert.equal(await page.locator(".breadcrumbs").getByRole("link", { name: "求职流水线" }).isVisible(), true);
  await page.getByRole("button", { name: "查看解析正文" }).click();
  await page.getByText("合成简历，演示测试。", { exact: true }).waitFor();
  const resumeId = await page.getByLabel(/^简历版本/).inputValue();
  assert(resumeId);
  await page.goto(base + "/#module/job-flow/resumes/" + encodeURIComponent(resumeId));
  await page.waitForURL(/#\/module\/resumes\?resume=/);
  await page.getByText("合成简历，演示测试。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "编辑版本资料" }).click();
  await page.getByLabel("简历名称", { exact: true }).fill("迁移验收简历新版");
  await page.getByLabel(/简历亮点/).fill("验证发布流程");
  await page.getByRole("button", { name: "保存版本资料" }).click();
  await page.getByText("已保存版本资料，原文件未改动。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "版本历史", exact: true }).click();
  await page.getByRole("region", { name: "简历版本历史" }).getByText(/第 1 版/).waitFor();
  await page.getByRole("button", { name: "查看解析正文" }).click();
  await page.getByText("合成简历，演示测试。", { exact: true }).waitFor();
  await page.getByRole("button", { name: "归档简历版本" }).click();
  await page.getByText("简历版本已归档。", { exact: true }).waitFor();
  await sidebar.getByRole("link", { name: "回收站" }).click();
  await page.getByRole("heading", { name: "迁移验收简历新版", exact: true }).waitFor();
  for (const [old, target, heading] of [
    ["prep/lead-1", "/module/job-prep?lead=lead-1", "预面试"],
    ["ai-resume/lead-2", "/module/job-resume-ai?lead=lead-2", "AI 改简历"],
    ["manage", "/module/job-tables", "单表管理"],
    ["tables", "/module/job-tables", "单表管理"],
  ]) {
    await page.goto(base + "/#module/job-flow/" + old);
    await page.waitForURL(url => url.hash === "#" + target);
    await page.getByRole("heading", { name: heading, exact: true, level: 1 }).waitFor();
    if (old.includes("lead-")) assert.equal(await page.getByLabel(/^目标岗位/).inputValue(), old.split("/")[1]);
    if (old === "manage") {
      await page.reload();
      await page.getByRole("heading", { name: heading, exact: true, level: 1 }).waitFor();
      assert.equal(new URL(page.url()).hash, "#" + target);
    }
  }
  await page.goto(base + "/#module/job-flow/prep/no-such-lead");
  await page.getByText(/旧链接里的岗位不存在/).waitFor();
  assert.equal(await page.getByLabel(/^目标岗位/).inputValue(), "");
  assert.equal(await page.getByRole("button", { name: "生成练习" }).isDisabled(), true);
  await page.goto(base + "/#/module/job-flow/item/missing");
  await page.getByRole("heading", { name: "找不到这个条目" }).waitFor();
  await page.locator(".workspace-sidebar").getByRole("link", { name: "返回开始页" }).click();
  await start.waitFor();
  assert.equal(await page.locator(".workspace-sidebar").count(), 0);
  assert.deepEqual(errors, []);
  await page.goto(base + "/#module/job-flow/company/" + encodeURIComponent("潮间工作室") + "/gap");
  await page.getByRole("heading", { name: "潮间工作室", exact: true, level: 1 }).waitFor();
  assert.equal(await page.getByRole("button", { name: "能力差距", exact: true }).getAttribute("aria-pressed"), "true");

  const mobile = await browser.newPage({ viewport: { width: 390, height: 844 }, reducedMotion: "reduce" });
  await mobile.goto(base + "/#/");
  await mobile.getByRole("button", { name: "进入演示" }).click();
  await mobile.getByRole("link", { name: "开始", exact: true }).waitFor();
  assert.equal(await mobile.locator(".start-trail").first().evaluate(e => getComputedStyle(e).animationName), "none");
  assert.equal(await mobile.locator(".workspace-drawer").count(), 0);
  await mobile.getByRole("link", { name: "开始", exact: true }).click();
  await mobile.locator(".category-card").last().waitFor();
  assert.equal(await mobile.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  assert.equal(await mobile.locator("html").getAttribute("data-motion"), "off");
  await mobile.getByRole("button", { name: "模块导航" }).click();
  const drawer = mobile.getByRole("dialog", { name: "模块导航" });
  await drawer.waitFor();
  const mobileJobs = drawer.getByRole("button", { name: "求职", exact: true });
  await mobileJobs.click();
  assert.equal(await mobileJobs.getAttribute("aria-expanded"), "true");
  await mobileJobs.click();
  assert.equal(await mobileJobs.getAttribute("aria-expanded"), "false");
  await mobileJobs.click();
  assert.deepEqual(await mobileJobs.locator("..").locator(".workspace-modules a").allTextContents(), ["求职流水线"]);
  await drawer.getByRole("link", { name: "求职流水线", exact: true }).click();
  await mobile.getByRole("heading", { name: "求职流水线", exact: true, level: 1 }).waitFor();
  assert.equal(await drawer.isVisible(), false);
  await mobile.getByRole("button", { name: "快速打开" }).click();
  await mobile.getByRole("dialog", { name: "快速打开模块" }).waitFor();
  await mobile.keyboard.press("Escape");
  await capture(mobile, "06-mobile.png");

  const production = await browser.newPage();
  let signedIn = false;
  let accountLogin = true;
  let posted = 0;
  let stageFinished = false;
  let weeklySaved = false;
  let queued = false;
  const prodErrors = [];
  production.on("pageerror", error => prodErrors.push(error.message));
  production.on("dialog", dialog => dialog.accept());
  const stage = { id: "stage-fixture", title: "Vue 验收", status: "running", objective: "验证阶段记录",
    created_at: "2026-11-11T00:00:00Z", completed: [], issues: [], verification: [], changes: [], data_snapshot_available: false };
  const week = { week_start: "2026-11-09", metrics: { applications_submitted: 3 }, pipeline_current: {},
    top_questions: [], top_weak_points: [], notes: [] };
  const profiles = [];
  const memories = [];
  const mockPreview = { summary: "退款模拟预览", columns: ["订单"], rows: [["模拟订单 01"]], roles: ["财务", "仓库"],
    initial: "待退款", actions: [{ label: "批准退款", roles: ["财务"], before: "待退款", after: "已批准" }] };
  const reviewProject = { id: "draft-review", version: 1, data: { title: "模拟退款后台", status: "completed", active: "", error: "", history: [],
    stages: [{ id: "refund", title: "退款", task: "验证审批角色", depends: [], gate: "", approved: false, draft: mockPreview }] } };
  const stageIds = ["input", "material", "resume_draft", "first_question", "first_answer", "followup_question", "followup_answer", "boss_review"];
  const interviewFlow = { id: "fixture-interview", version: 4, kind: "workflow", data: { title: "合成三角色流程", kind: "graph",
    nodes: [{ id: "input", type: "input" }, { id: "material", type: "tool", tool_id: "interview_context" },
      ...stageIds.slice(2).map(id => ({ id, type: "agent", query: "[INTERVIEW_EVIDENCE_V1]" }))],
    edges: stageIds.slice(1).map((id,i) => [stageIds[i], id]) } };
  const flows = [interviewFlow];
  const lead = { id: "fixture-lead", version: 1, kind: "job_lead", data: { company: "合成公司", title: "合成工程师", jd_text: "核对证据。" } };
  const resume = { id: "fixture-resume", version: 1, kind: "resume_version", data: { title: "合成简历", document_id: "fixture" } };
  const now = new Date();
  const today = [now.getFullYear(), now.getMonth() + 1, now.getDate()].map(part => String(part).padStart(2, "0")).join("-");
  const planTask = { id: "due-fixture", title: "今日合成任务", due_date: today, done: false, priority: "p2", requires: [] };
  const planFixture = { id: "fixture-plan", kind: "plan", version: 1, data: { title: "合成规划", kind: "main",
    acts: [{ id: "act", nodes: [planTask, { ...planTask, id: "done-fixture", title: "已完成合成任务", done: true }] }] } };
  const noteFixture = { id: "fixture-note", kind: "knowledge", version: 1, data: { title: "最近合成笔记", content: "合成笔记正文" } };
  const interviewRun = { id: "fixture-interview-run", version: 1, kind: "workflow_run", data: {
    status: "completed", private_interview: true, interview_lead_id: lead.id, node_outputs: {
      resume_draft: { answer: "合成简历草稿" }, first_question: { answer: "合成面试官首问" }, first_answer: { answer: "合成候选人首答" },
      followup_question: { answer: "合成面试官追问" }, followup_answer: { answer: "合成候选人追答" },
      boss_review: { answer: "合成用人主管复盘", evidence: { facts: ["不建卡的材料原句"], pending: ["补充吞吐量证据"], suggestions: ["练习解释失败复盘"] } },
    },
  } };
  let interviewRuns = 0;
  let simulationCards = 0;
  const snapshot = { format_version: 1, records: [] };
  const snapshotHash = "a".repeat(64), revision = "b".repeat(64);
  let restores = 0;
  let reviewSent = false;
  let workflowApproved = false;
  let savedGraph;
  let queuedJob;
  let teamCalls = 0, loopCalls = 0;
  const turns = [{ author: "合成成员", text: "合成团队发言" }];
  const loopSummary = { status: "success", reason: "合成门禁结果", diff: "fixture.txt | 1 +", attempts: [{ round: 1, passed: true }] };
  let collabRun;
  const privateTicket = "test-private-ticket";
  const learningCard = { id: "card-1", version: 1, kind: "learning_card", data: { title: "如何核对来源？",
    answer_ref: "先核对原文。", due_at: "2026-11-10T00:00:00Z", paused: false, source: "manual" } };
  const graphRun = { id: "graph-1", version: 5, kind: "workflow_run", data: { kind: "graph", title: "验收图运行",
    status: "awaiting_confirmation", pending_kind: "approval", pending_node: "gate", workflow: { data: { nodes: [
      { id: "gate", type: "approval", message: "确认合成输出" }] } } } };
  const draft = { mode: "rules", template: "generic", workflow: { title: "测试草稿", kind: "graph", nodes: [{ id: "input", type: "input" }], edges: [] },
    agents: [{ key: "worker", profile: { title: "草稿 Agent", system_prompt: "使用测试资料", mode: "text", scopes: ["docs"], generate: false, tool_ids: [] } }] };
  await production.route("http://127.0.0.1:31744/**", async (route) => {
    const req = route.request();
    const path = new URL(req.url()).pathname;
    if (path === "/api/session") {
      if (req.method() === "POST") {
        assert.deepEqual(req.postDataJSON(), accountLogin
          ? { username: "fixture-user", password: "fixture-password", remember: false }
          : { token: "fixture-token" });
        posted += 1;
        signedIn = true;
        return route.fulfill({ json: { authenticated: true } });
      }
      if (req.method() === "DELETE") { signedIn = false; return route.fulfill({ json: { authenticated: false } }); }
      return route.fulfill({ json: { required: true, authenticated: signedIn, account_login: accountLogin } });
    }
    if (path === "/api/trash") return route.fulfill({ json: { total: 0, truncated: false, items: [] } });
    if (path === "/api/jobs") return route.fulfill({ json: { job_lead: [lead], resume_version: [resume], application: [], due_application_ids: [] } });
    if (path === "/api/plans") return route.fulfill({ json: [planFixture] });
    if (path === "/api/knowledge") {
      if (req.method() === "POST") return route.fulfill({ status: 409, json: { detail: "<b>模拟版本冲突</b>" } });
      return route.fulfill({ json: [noteFixture] });
    }
    if (path === "/api/workflows/fixture-interview/run") {
      assert.deepEqual(req.postDataJSON(), { version: 4, input: { lead_id: lead.id, resume_id: resume.id, knowledge_id: "" } });
      interviewRuns += 1;
      return route.fulfill({ json: interviewRun });
    }
    if (path === "/api/workflow-runs/fixture-interview-run") return route.fulfill({ json: interviewRun });
    if (path === "/api/learning/from-simulation/fixture-interview-run") {
      assert.deepEqual(req.postDataJSON(), { version: 1, points: ["练习解释失败复盘"], confirmation: "确认创建复习卡" });
      simulationCards++;
      return route.fulfill({ json: { created: [{}], reused: [] } });
    }
    if (path === "/api/learning/cards") return route.fulfill({ json: {
      cards: [learningCard], due_ids: reviewSent ? [] : [learningCard.id] } });
    if (path === "/api/learning/cards/card-1/review") {
      const body = req.postDataJSON();
      assert.equal(body.rating, 2);
      assert.equal(body.version, 1);
      assert.match(body.request_id, /^[a-z0-9-]{16,100}$/);
      reviewSent = true;
      return route.fulfill({ json: { card: { ...learningCard, version: 2 } } });
    }
    if (path === "/api/private/status") return route.fulfill({ json: { configured: true, strong_crypto: true } });
    if (path === "/api/private/session") {
      assert.deepEqual(req.postDataJSON(), { password: "synthetic-password" });
      return route.fulfill({ json: { ticket: privateTicket } });
    }
    if (path === "/api/private/wish") {
      assert.equal(new URL(req.url()).search, "");
      assert.equal((await req.allHeaders())["x-private-ticket"], privateTicket);
      return route.fulfill({ json: [{ id: "wish", version: 1, kind: "wish", data: { title: "合成私密愿望" } }] });
    }
    if (path === "/api/agent-runs") return route.fulfill({ json: [] });
    if (path === "/api/workflow-runs" || path === "/api/workflow-runs/graph-1") {
      const record = workflowApproved ? { ...graphRun, version: 6, data: { ...graphRun.data, status: "completed", result: { answer: "仅合成运行" } } } : graphRun;
      return route.fulfill({ json: path.endsWith("/graph-1") ? record : [record, ...(interviewRuns ? [interviewRun] : [])] });
    }
    if (path === "/api/workflow-runs/graph-1/confirm") {
      assert.deepEqual(req.postDataJSON(), { version: 5, approve: true });
      workflowApproved = true;
      return route.fulfill({ json: {} });
    }
    if (path === "/api/automation/code-roots") return route.fulfill({ json: [{ name: "writable", writable: true }, { name: "readonly", writable: false }] });
    if (path === "/api/automation/teams/run") {
      assert.equal(req.method(), "POST");
      assert.deepEqual(req.postDataJSON(), { agent_ids: ["agent-manual"], task: "仅验收即时团队", mode: "group_chat", max_rounds: 6, approved: false });
      teamCalls += 1;
      return route.fulfill({ json: { id: "team-test", final: "合成团队终稿", turns } });
    }
    if (path === "/api/automation/loop/run") {
      assert.equal(req.method(), "POST");
      assert.deepEqual(req.postDataJSON(), { root: "writable", task: "仅验收即时编码表单", gate: "fixture-only", engine: "opencode", tier: "patch" });
      loopCalls += 1;
      return route.fulfill({ json: { id: "loop-test", ...loopSummary } });
    }
    if (path === "/api/workflow-runs/loop-test") return route.fulfill({ json: { id: "loop-test", version: 1, kind: "workflow_run",
      data: { kind: "loop", title: "合成编码历史", status: "completed", summary: loopSummary } } });
    if (path === "/api/automation/queue/stats") return route.fulfill({ json: { queued: Number(!!queuedJob) } });
    if (path === "/api/automation/queue") {
      if (req.method() === "POST") {
        const { idempotency_key, ...body } = req.postDataJSON();
        assert.match(idempotency_key, /^[a-z0-9-]{16,100}$/);
        assert.deepEqual(body, { kind: "team", payload: { agent_ids: ["agent-manual"], task: "仅验收入队", mode: "group_chat", max_rounds: 6, approved: false },
          max_attempts: 3, priority: 50 });
        queuedJob = { id: "test-job", kind: "team", status: "queued", attempts: 0, max_attempts: 3 };
        return route.fulfill({ json: queuedJob });
      }
      return route.fulfill({ json: queuedJob ? [queuedJob] : [] });
    }
    if (path === "/api/collaborations/status") return route.fulfill({ json: { enabled: false, max_plan_steps: 4 } });
    if (path === "/api/model-connection") return route.fulfill({ json: { configured: false } });
    if (path === "/api/collaborations") {
      if (req.method() === "POST") {
        const input = req.postDataJSON();
        assert.deepEqual(input, { agent_id: "agent-manual", version: 2, query: "编排验收",
          plan: [{ step: 0, assignee: "agent-draft", input: "核对测试输出", expected: "核对结论" }], confirmation: "仅创建人工计划" });
        collabRun = { id: "collab-test", version: 1, kind: "agent_session", data: { title: "合成协作计划", status: "awaiting_confirmation",
          workflow_id: "agent:agent-manual", mode: "manual", shared_state: { phase: "plan", plan: input.plan, board: [] } } };
        return route.fulfill({ json: collabRun });
      }
      return route.fulfill({ json: collabRun ? [collabRun] : [] });
    }
    if (path === "/api/collaborations/collab-test") return route.fulfill({ json: collabRun });
    if (path === "/api/collaborations/collab-test/confirm") {
      assert.deepEqual(req.postDataJSON(), { version: 1, approve: true, confirmation: "批准计划，不批准Worker写操作" });
      collabRun = { ...collabRun, version: 2, data: { ...collabRun.data, status: "confirmed" } };
      return route.fulfill({ json: collabRun });
    }
    if (path === "/api/collaborations/collab-test/execute") throw new Error("未启用模型协作不得自动执行");
    if (path === "/api/stages") return route.fulfill({ json: [{ ...stage, ...(stageFinished ? { status: "passed", verification: ["测试证据"] } : {}) }] });
    if (path === "/api/stages/stage-fixture/finish") {
      assert.equal(req.method(), "POST");
      assert.deepEqual(req.postDataJSON(), { completed: [], issues: [], verification: ["测试证据"], status: "passed" });
      stageFinished = true; return route.fulfill({ json: stage });
    }
    if (path === "/api/stages/stage-fixture/diff") return route.fulfill({ body: "差异文本样例", contentType: "text/plain; charset=utf-8" });
    if (path === "/api/jobs/report/weekly") {
      if (req.method() === "POST") {
        assert.deepEqual(req.postDataJSON(), { day: "2026-11-09", mode: "statistics", confirmation: "生成并保存周报", request_id: "" });
        weeklySaved = true; return route.fulfill({ json: week });
      }
      return route.fulfill({ json: { current: week, saved: weeklySaved ? { ...week, markdown: "冻结周报样例" } : null, stale: false } });
    }
    if (path === "/api/notifications") return route.fulfill({ json: { settings: { enabled: false, configured: false },
      notifications: queued ? [{ id: "notice", version: 1, data: { title: "今日测试摘要", status: "pending", body: "测试内容", attempts: 0 } }] : [] } });
    if (path === "/api/notifications/daily-preview") return route.fulfill({ json: { body: "待跟进 3 条。" } });
    if (path === "/api/notifications/daily") {
      assert.equal(req.method(), "POST");
      assert.deepEqual(req.postDataJSON(), { confirmation: "加入通知队列" });
      queued = true; return route.fulfill({ json: { reused: false } });
    }
    if (path === "/api/notifications/dispatch") throw new Error("未配置 SMTP 不得触发发送");
    if (path === "/api/import/options") return route.fulfill({ json: { max_file_bytes: 4_096 } });
    if (path === "/api/import/preview") {
      assert.deepEqual(req.postDataJSON(), { snapshot });
      return route.fulfill({ json: { snapshot, snapshot_hash: snapshotHash, revision, change_count: 1,
        counts: { added: 0, updated: 0, removed: 1, unchanged: 0 }, changes: [{ id: "old", kind: "knowledge", title: "合成旧笔记", action: "removed" }] } });
    }
    if (path === "/api/import") {
      assert.deepEqual(req.postDataJSON(), { snapshot, snapshot_hash: snapshotHash, expected_revision: revision, confirmation: "恢复数据" });
      restores += 1;
      return route.fulfill({ json: { restored_records: 1, warning: "" } });
    }
    if (path === "/api/agents") {
      if (req.method() === "POST") {
        assert.deepEqual(req.postDataJSON(), { data: { title: "手动测试 Agent", system_prompt: "只处理测试资料", mode: "text", scopes: ["docs"], generate: false, tool_ids: [], memory: { scope: "persistent" } } });
        profiles.push({ id: "agent-manual", version: 1, kind: "agent_profile", ...req.postDataJSON() });
        return route.fulfill({ json: profiles.at(-1) });
      }
      return route.fulfill({ json: profiles });
    }
    if (path === "/api/agents/agent-manual/memory") {
      if (req.method() === "POST") {
        const body = req.postDataJSON();
        assert.equal(body.project, "合成项目 A"); assert.equal(body.source_title, "项目.md");
        assert.equal(body.content, "# 合成资料\n只保留这个段落");
        memories.push({ id: "note-1", version: 1, data: { ...body, state: "pending" } });
        return route.fulfill({ json: memories[0] });
      }
      return route.fulfill({ json: memories.filter(row => row.data.project === new URL(req.url()).searchParams.get("project")) });
    }
    if (path === "/api/agents/agent-manual/memory/note-1/decide") {
      const body = req.postDataJSON();
      assert.equal(body.project, "合成项目 A");
      assert.equal(body.version, memories[0].version);
      memories[0].version += 1; memories[0].data.state = body.action === "confirm" ? "confirmed" : "forgotten";
      return route.fulfill({ json: memories[0] });
    }
    if (path === "/api/capabilities") return route.fulfill({ json: { builtin_tools: [] } });
    if (path === "/api/draft-projects") return route.fulfill({ json: [reviewProject] });
    if (path === "/api/draft-projects/draft-review") return route.fulfill({ json: reviewProject });
    if (path === "/api/draft-projects/draft-review/action") {
      const body = req.postDataJSON(), d = reviewProject.data, stage = d.stages[0];
      assert.equal(body.version, reviewProject.version);
      assert.equal(body.node, "refund");
      if (body.action === "choices") return route.fulfill({ json: { options: ["改为主管审批", "保持财务审批"] } });
      if (body.action === "gate") {
        assert.equal(body.value, "只有财务可以批准"); stage.gate = body.value; d.status = "awaiting_review";
      } else if (body.action === "approve") {
        stage.approved = true; d.status = "completed";
      } else {
        assert.equal(body.action, "revise"); assert.equal(body.value, "改为主管审批");
        d.history.push({ id: stage.id, title: stage.title, version: reviewProject.version, draft: stage.draft });
        stage.draft = null; stage.approved = false; d.status = "paused";
      }
      reviewProject.version += 1;
      return route.fulfill({ json: reviewProject });
    }
    if (path === "/api/agents/agent-manual" && req.method() === "PUT") {
      assert.deepEqual(req.postDataJSON(), { version: 1, data: { handoffs: { allowed: ["agent-draft"] } } });
      const row = profiles[0];
      row.data.handoffs = { allowed: ["agent-draft"] };
      row.version += 1;
      return route.fulfill({ json: row });
    }
    if (path === "/api/workflows") {
      if (req.method() === "POST") {
        savedGraph = req.postDataJSON().data;
        flows.push({ id: "flow-manual", version: 1, kind: "workflow", data: savedGraph });
        return route.fulfill({ json: flows.at(-1) });
      }
      return route.fulfill({ json: flows });
    }
    if (path === "/api/automation/compose/draft") {
      assert.deepEqual(req.postDataJSON(), { goal: "整理一份测试周报", mode: "rules", template: "generic" });
      return route.fulfill({ json: draft });
    }
    if (path === "/api/automation/compose/save") {
      assert.deepEqual(req.postDataJSON(), { draft });
      profiles.push({ id: "agent-draft", version: 1, kind: "agent_profile", data: draft.agents[0].profile });
      flows.push({ id: "flow-draft", version: 1, kind: "workflow", data: draft.workflow });
      return route.fulfill({ json: { workflow_id: "flow-draft", agent_ids: ["agent-draft"], version: 1 } });
    }
    if (path.startsWith("/api/")) return route.fulfill({ json: [] });
    const name = path === "/" ? "index.html" : path.slice(1);
    assert(!name.includes(".."));
    const kind = name.endsWith(".js") ? "text/javascript" : name.endsWith(".css") ? "text/css" : name.endsWith(".webp") ? "image/webp" : "text/html";
    try { return await route.fulfill({ body: await readFile(new URL(name, dist)), contentType: kind + (kind.startsWith("text/") ? "; charset=utf-8" : "") }); }
    catch { return route.fulfill({ status: 404 }); }
  });
  await production.goto("http://127.0.0.1:31744/#/module/jobs");
  await production.getByRole("textbox", { name: "账号" }).fill("fixture-user");
  await production.locator("[name=password]").fill("fixture-password");
  await production.getByRole("button", { name: "登录", exact: true }).click();
  await production.getByRole("heading", { name: "投递记录", exact: true }).waitFor();
  assert.equal(posted, 1);
  await production.goto("http://127.0.0.1:31744/#/workspace");
  const todayPanel = production.getByRole("region", { name: "今日工作区" });
  await todayPanel.getByRole("link", { name: "今日合成任务" }).waitFor();
  assert.equal(await todayPanel.getByText("已完成合成任务").count(), 0);
  await todayPanel.getByRole("link", { name: "今日合成任务" }).click();
  await production.locator("#plan-task-due-fixture:focus").waitFor();
  await production.goBack();
  await todayPanel.getByRole("link", { name: "最近合成笔记" }).click();
  await production.getByText("合成笔记正文", { exact: true }).waitFor();
  await production.goto("http://127.0.0.1:31744/#/module/knowledge");
  await production.getByRole("button", { name: "新建笔记", exact: true }).click();
  const draftForm = production.locator("form").filter({ has: production.getByLabel("正文", { exact: true }) });
  await draftForm.getByLabel("标题", { exact: true }).fill("保留中的草稿");
  await draftForm.getByLabel("正文", { exact: true }).fill("失败不应清掉输入");
  await draftForm.getByRole("button", { name: "保存", exact: true }).click();
  const draftError = draftForm.getByRole("alert");
  await draftError.getByText("<b>模拟版本冲突</b>", { exact: true }).waitFor();
  assert.equal(await draftError.locator("b").count(), 0);
  assert.equal(await draftForm.getByLabel("正文", { exact: true }).inputValue(), "失败不应清掉输入");
  await draftForm.getByRole("button", { name: "取消", exact: true }).click();
  await production.goto("http://127.0.0.1:31744/#/module/job-flow/item/" + encodeURIComponent(lead.data.company));
  await production.getByRole("link", { name: "准备这场面试", exact: true }).click();
  await production.getByRole("heading", { name: "准备这场面试", exact: true }).waitFor();
  await production.getByText("目标岗位：合成工程师", { exact: true }).waitFor();
  assert.equal(interviewRuns, 0);
  await production.getByRole("button", { name: "生成草稿并模拟", exact: true }).click();
  await production.getByText("合成用人主管复盘", { exact: true }).waitFor();
  assert.equal(simulationCards, 0);
  assert.equal(await production.getByRole("checkbox", { name: "不建卡的材料原句" }).count(), 0);
  await production.getByRole("checkbox", { name: "练习解释失败复盘" }).check();
  await production.getByRole("button", { name: "确认创建复习卡", exact: true }).click();
  await production.getByText("新增 1 张复习卡，复用 0 张。", { exact: true }).waitFor();
  await production.reload();
  await production.getByRole("button", { name: /^回看模拟/ }).click();
  await production.getByText("合成面试官追问", { exact: true }).waitFor();
  assert.equal(interviewRuns, 1, "回看不能重新执行模型工作流");
  assert.equal(simulationCards, 1, "回看不能自动建卡");
  await production.goto("http://127.0.0.1:31744/#/module/stages");
  await production.getByRole("button", { name: "结束阶段" }).click();
  await production.getByLabel("结果", { exact: true }).selectOption("passed");
  assert.equal(await production.getByLabel("验证证据（每行一项）").getAttribute("required"), "");
  await production.getByLabel("验证证据（每行一项）").fill("测试证据");
  await production.getByRole("button", { name: "保存阶段结果" }).click();
  await production.getByRole("button", { name: "查看文本差异" }).click();
  await production.getByText("差异文本样例", { exact: true }).waitFor();
  await production.goto("http://127.0.0.1:31744/#/module/job-weekly");
  await production.getByRole("button", { name: "保存纯统计周报" }).click();
  await production.getByText("冻结周报样例", { exact: true }).waitFor();
  await production.goto("http://127.0.0.1:31744/#/module/notifications");
  await production.getByText("待跟进 3 条。", { exact: true }).waitFor();
  assert.equal(await production.getByRole("button", { name: "发送队列" }).isDisabled(), true);
  await production.getByRole("button", { name: "加入通知队列" }).click();
  await production.getByRole("heading", { name: "今日测试摘要" }).waitFor();
  await production.goto("http://127.0.0.1:31744/#/module/agent-studio");
  await production.getByRole("button", { name: "新建 Agent", exact: true }).click();
  await production.getByLabel("名称", { exact: true }).fill("手动测试 Agent");
  await production.getByLabel("角色指令", { exact: true }).fill("只处理测试资料");
  await production.getByLabel("记忆", { exact: true }).selectOption("persistent");
  await production.getByRole("button", { name: "保存 Agent", exact: true }).click();
  await production.getByText("Agent 已保存。", { exact: true }).waitFor();
  const memory = production.getByRole("region", { name: "项目记忆与笔记" });
  await memory.getByLabel("记忆项目").fill("合成项目 A");
  await memory.getByText("新增记忆或导入 Obsidian 笔记", { exact: true }).click();
  await memory.getByLabel(/选择 Markdown/).setInputFiles({ name: "项目.md", mimeType: "text/markdown", buffer: Buffer.from("# 合成资料\n原笔记全文") });
  await memory.getByLabel(/笔记摘录/).fill("# 合成资料\n只保留这个段落");
  assert.equal(memories.length, 0);
  await memory.getByRole("button", { name: "保存为待确认条目" }).click();
  await memory.getByText("项目.md · 待确认", { exact: true }).click();
  await memory.getByRole("button", { name: "确认用于此范围" }).click();
  await memory.getByText("项目.md · 已生效", { exact: true }).waitFor();
  await memory.getByLabel("记忆项目").fill("合成项目 B");
  await memory.getByRole("button", { name: "查看此范围的记忆" }).click();
  await memory.getByText("此范围没有记忆。", { exact: true }).waitFor();
  await memory.getByLabel("记忆项目").fill("合成项目 A");
  await memory.getByRole("button", { name: "查看此范围的记忆" }).click();
  await memory.getByText("项目.md · 已生效", { exact: true }).click();
  await memory.getByRole("button", { name: "遗忘此条目" }).click();
  await memory.getByText("项目.md · 已遗忘", { exact: true }).waitFor();
  await production.getByRole("button", { name: "草稿项目", exact: true }).click();
  await production.getByLabel("已有草稿项目").selectOption("draft-review");
  const draftProject = production.getByRole("region", { name: "草稿项目", exact: true });
  await draftProject.getByLabel("体验角色").selectOption("仓库");
  assert.equal(await draftProject.getByRole("button", { name: "批准退款", exact: true }).isDisabled(), true);
  await draftProject.getByLabel("体验角色").selectOption("财务");
  await draftProject.getByRole("button", { name: "批准退款", exact: true }).click();
  await draftProject.getByText("当前模拟状态：已批准", { exact: true }).waitFor();
  await draftProject.getByLabel("验收标准（可选）").fill("只有财务可以批准");
  await draftProject.getByRole("button", { name: "设置验收点", exact: true }).click();
  await draftProject.getByRole("button", { name: "验收通过这版", exact: true }).click();
  await draftProject.getByText("草稿已完成", { exact: true }).waitFor();
  await draftProject.getByRole("button", { name: "回到这一步修改", exact: true }).click();
  await draftProject.getByRole("button", { name: "让 AI 给几个改法", exact: true }).click();
  await draftProject.getByRole("button", { name: "改为主管审批", exact: true }).click();
  await draftProject.getByRole("button", { name: "暂停并退回这一步", exact: true }).click();
  await draftProject.getByText("已暂停", { exact: true }).waitFor();
  await draftProject.getByLabel("比较版本").selectOption({ index: 1 });
  await draftProject.getByText("模拟数据 · 历史草稿，只读", { exact: true }).waitFor();
  await production.getByRole("button", { name: "用目标起草" }).click();
  await production.getByLabel("任务目标").fill("整理一份测试周报");
  await production.getByRole("button", { name: "生成草稿", exact: true }).click();
  await production.getByRole("heading", { name: "测试草稿" }).waitFor();
  assert.equal(profiles.length, 1, "生成草稿不能先写入配置");
  await production.getByRole("button", { name: "确认并保存草稿" }).click();
  await production.getByText("已保存至同一套 Agent 与工作流。", { exact: true }).waitFor();
  await production.getByRole("button", { name: "我的 Agent" }).click();
  assert.deepEqual(await production.getByRole("combobox").locator("option").allTextContents(), ["未选择", "手动测试 Agent", "草稿 Agent"]);
  await production.getByRole("button", { name: "已保存流程" }).click();
  await production.getByRole("button", { name: "手动新建工作流" }).click();
  await production.getByLabel("流程名称", { exact: true }).fill("手动编排验收");
  await production.getByLabel(/^默认 Agent/).selectOption("agent-manual");
  await production.getByLabel("新节点 ID").fill("gate");
  await production.getByLabel(/新节点类型/).selectOption("approval");
  await production.getByRole("button", { name: "添加节点", exact: true }).click();
  await production.getByLabel("需要确认的内容").fill("确认合成结果");
  await production.getByLabel(/起点/).selectOption("answer");
  await production.getByLabel(/终点/).selectOption("gate");
  await production.getByRole("button", { name: "添加连线" }).click();
  await production.getByRole("button", { name: "保存工作流", exact: true }).click();
  await production.getByText("工作流已保存，未运行。", { exact: true }).waitFor();
  assert.deepEqual(savedGraph.edges, [["input", "answer"], ["answer", "gate"]]);
  assert.deepEqual(savedGraph.nodes.at(-1), { id: "gate", type: "approval", message: "确认合成结果" });
  await production.goto("http://127.0.0.1:31744/#/module/runs?run=graph-1&kind=graph");
  await production.getByText("确认合成输出", { exact: true }).waitFor();
  assert.equal(workflowApproved, false);
  await production.getByRole("button", { name: "批准本次操作" }).click();
  await production.getByText("仅合成运行", { exact: true }).waitFor();
  assert.equal(workflowApproved, true);
  await production.goto("http://127.0.0.1:31744/#/module/learning");
  await production.getByRole("heading", { name: "如何核对来源？" }).waitFor();
  assert.equal(await production.getByRole("button", { name: "记得", exact: true }).count(), 0);
  await production.getByRole("button", { name: "显示答案" }).click();
  await production.getByText("先核对原文。", { exact: true }).waitFor();
  await production.getByRole("button", { name: "记得", exact: true }).click();
  await production.getByText("没有符合条件的复习卡。", { exact: true }).waitFor();
  assert.equal(reviewSent, true);
  await production.goto("http://127.0.0.1:31744/#/module/private");
  await production.getByLabel("私密口令", { exact: true }).fill("synthetic-password");
  await production.getByRole("button", { name: "解锁", exact: true }).click();
  await production.getByRole("heading", { name: "合成私密愿望" }).waitFor();
  await production.getByRole("button", { name: "锁定此页面" }).click();
  await production.getByRole("heading", { name: "解锁愿望与日记" }).waitFor();
  assert.equal(await production.getByRole("heading", { name: "合成私密愿望" }).count(), 0);
  await production.goto("http://127.0.0.1:31744/#module/workflows");
  await production.getByRole("heading", { name: "Agent 工作室", exact: true }).waitFor();
  await production.getByRole("link", { name: "任务队列", exact: true }).click();
  await production.getByRole("button", { name: "新建队列任务" }).click();
  await production.getByLabel("手动测试 Agent", { exact: true }).check();
  await production.getByLabel("团队目标").fill("仅验收入队");
  await production.getByRole("button", { name: "确认入队" }).click();
  await production.getByRole("heading", { name: "团队协作 · 排队中" }).waitFor();
  await production.getByRole("link", { name: "即时运行", exact: true }).click();
  await production.getByLabel("团队目标").fill("仅验收即时团队");
  assert.equal(teamCalls, 0);
  await production.getByRole("button", { name: "确认立即运行" }).click();
  await production.getByText("合成团队发言", { exact: true }).waitFor();
  await production.getByLabel("类型").selectOption("loop");
  assert.equal(await production.getByLabel("代码工作区").locator('option[value="readonly"]').count(), 0);
  await production.getByLabel("代码工作区").selectOption("writable");
  await production.getByLabel("改动目标").fill("仅验收即时编码表单");
  await production.getByLabel("验收门禁命令").fill("fixture-only");
  assert.equal(loopCalls, 0);
  await production.getByRole("button", { name: "确认立即运行" }).click();
  await production.getByText("通过门禁 · 合成门禁结果", { exact: true }).waitFor();
  await production.getByRole("link", { name: "回看本次运行" }).click();
  await production.getByRole("heading", { name: "合成编码历史" }).waitFor();
  await production.reload();
  await production.getByRole("heading", { name: "合成编码历史" }).waitFor();
  assert.equal(teamCalls, 1);
  assert.equal(loopCalls, 1);
  await production.goto("http://127.0.0.1:31744/#/module/collaboration");
  await production.getByRole("heading", { name: "交接白名单" }).waitFor();
  await production.getByRole("checkbox", { name: /草稿 Agent/ }).check();
  await production.getByRole("button", { name: "保存交接白名单" }).click();
  await production.getByText("交接白名单已保存，不会执行任务。", { exact: true }).waitFor();
  await production.getByLabel("协作任务").fill("编排验收");
  await production.getByRole("button", { name: "添加步骤" }).click();
  await production.getByLabel("输入", { exact: true }).fill("核对测试输出");
  await production.getByLabel("预期产物").fill("核对结论");
  await production.getByRole("button", { name: "创建人工计划（不执行）" }).click();
  await production.getByRole("heading", { name: "合成协作计划" }).waitFor();
  await production.getByRole("button", { name: "批准计划", exact: true }).click();
  const executePlan = production.getByRole("button", { name: "执行已确认计划", exact: true });
  await executePlan.waitFor();
  assert.equal(await executePlan.isDisabled(), true);
  await production.goto("http://127.0.0.1:31744/#/module/backup");
  await production.getByLabel("备份文件").setInputFiles({ name: "fixture.json", mimeType: "application/json", buffer: Buffer.from(JSON.stringify(snapshot)) });
  await production.getByRole("button", { name: "预览恢复内容" }).click();
  await production.getByText("移入回收站 · 合成旧笔记", { exact: true }).waitFor();
  assert.equal(restores, 0);
  assert.equal(await production.getByRole("button", { name: "确认恢复" }).isDisabled(), true);
  await production.getByLabel("核对预览后输入「恢复数据」").fill("恢复数据");
  await production.getByRole("button", { name: "确认恢复" }).click();
  await production.getByText("已处理 1 条记录。", { exact: true }).waitFor();
  assert.equal(restores, 1);
  await production.getByRole("button", { name: "退出登录" }).click();
  await production.getByRole("heading", { name: "进入时列" }).waitFor();
  accountLogin = false;
  await production.goto("http://127.0.0.1:31744/#/trash");
  await production.reload();
  await production.locator("input[name=token]").fill("fixture-token");
  assert.equal(await production.locator("input[name=username]").count(), 0);
  await production.getByRole("button", { name: "登录", exact: true }).click();
  await production.getByRole("heading", { name: "回收站", exact: true }).waitFor();
  await production.getByText("回收站为空。", { exact: true }).waitFor();
  assert.equal(posted, 2);
  assert.deepEqual(prodErrors, []);
  const files = await readdir(new URL("assets/", dist));
  const gzipBytes = (await Promise.all(files.filter(n => n.endsWith(".js"))
    .map(async n => gzipSync(await readFile(new URL("assets/" + n, dist))).length))).reduce((a, b) => a + b, 0);
  const wallpaperBytes = (await stat(new URL("wallpaper/shilie-spring.webp", dist))).size;
  assert(gzipBytes < 150_000);
  assert(wallpaperBytes < 200_000);
  console.log(JSON.stringify({ ok: true, gzipBytes, wallpaperBytes, checks: "两级导航/公司隔离/旧深链/投递状态/复盘版本/简历编辑与归档（本地演示）；生产登录/今日工作区/三角色运行与刷新回看/阶段周报/通知与任务入队/Agent 和手动 DAG/审批/人工协作/复习评分/私密锁定/备份确认（模拟接口）" }));
} finally {
  await browser.close();
}
