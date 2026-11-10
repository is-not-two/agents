/* 求职板块（P0）：板块内 4 个并列页面（P1）。
   公司流水线按公司切换，只含意向 / 能力要求 / 能力缺口 / 面试复盘 4 个阶段；
   个人简历、AI 优化简历是独立于公司的个人资产页面，不挂在流水线里。
   数据全部来自现有 /api/jobs/* 端点，不新增记录类型、不调用模型。
   关联：job_lead.company ↔ company_capability.company，
        application.lead_id → job_lead，interview_report.application_id → application，
        application.resume_version_id → resume_version。 */
import { api, read, write, escapeHtml as escape } from "./data.js?v=129";

/* P1 页面：简历与 AI 优化不在流水线内部。 */
const PAGES = [
  ["pipeline", "公司流水线"],
  ["prep", "预面试"],
  ["resumes", "个人简历"],
  ["ai-resume", "AI 优化简历"],
  ["manage", "单表管理"],
];
const PAGE_IDS = PAGES.map(([id]) => id);
const PREP_MODES = [
  ["practice", "练习模式"],
  ["full", "完整问答"],
  ["voice", "模拟面试（语音）"],
];

/* 流水线阶段：4 个，不含简历。 */
const STAGES = [
  ["intent", "意向与投递"],
  ["required", "公司要什么能力"],
  ["gap", "我要补什么能力"],
  ["review", "面试复盘"],
];

const validPage = (value) =>
  PAGE_IDS.includes(value) ? value : PAGES[0][0];
const validStage = (value) =>
  STAGES.some(([id]) => id === value) ? value : STAGES[0][0];

const cache = {
  leads: [],
  applications: [],
  capabilities: [],
  reports: [],
  resumes: [],
  loaded: false,
  loading: false,
  busy: false,
  error: "",
  page: validPage(read("job-flow-page", "pipeline")),
  company: read("job-flow-company", ""),
  stage: validStage(read("job-flow-stage", "intent")),
  gap: null,
  gapLeadId: "",
  gapError: "",
  analysis: null,
  analysisKey: "",
  analysisError: "",
  templates: [],
  templatesLoaded: false,
  templatesLoading: false,
  templatesError: "",
  draft: null,
  optimizerError: "",
  optimizeSelection: {},
  prepMode: read("job-flow-prep-mode", "practice"),
  prepDraft: null,
  prepSessions: [],
  prepLoaded: false,
  prepLoading: false,
  prepError: "",
};

let _repaint = () => {};

async function load(force = false) {
  if (cache.loading) return;
  if (force) {
    cache.loaded = false;
    cache.error = "";
    cache.gap = null;
    cache.analysis = null;
  }
  cache.loading = true;
  cache.error = "";
  try {
    const [leads, applications, capabilities, reports, resumes] =
      await Promise.all([
        api("jobs/leads"),
        api("jobs/applications"),
        api("jobs/capabilities"),
        api("jobs/reports"),
        api("jobs/resumes"),
      ]);
    cache.leads = leads || [];
    cache.applications = applications || [];
    cache.capabilities = capabilities || [];
    cache.reports = reports || [];
    cache.resumes = resumes || [];
    cache.loaded = true;
  } catch (e) {
    cache.error = e.message;
  } finally {
    cache.loading = false;
    _repaint();
  }
}

async function loadTemplates() {
  if (cache.templatesLoading || cache.templatesLoaded || cache.templatesError) return;
  cache.templatesLoading = true;
  try {
    cache.templates = (await api("resume/templates")) || [];
    cache.templatesLoaded = true;
  } catch (e) {
    cache.templatesError = e.message;
  } finally {
    cache.templatesLoading = false;
    _repaint();
  }
}

const data = (r) => r.data || {};

function companies() {
  const names = new Set();
  for (const r of cache.leads) if (data(r).company) names.add(data(r).company);
  for (const r of cache.capabilities)
    if (data(r).company) names.add(data(r).company);
  return [...names].sort((a, b) => a.localeCompare(b, "zh"));
}

function currentCompany() {
  const list = companies();
  if (!list.length) return "";
  return list.includes(cache.company) ? cache.company : list[0];
}

function pipeline(company) {
  const leads = cache.leads.filter((r) => data(r).company === company);
  const leadIds = new Set(leads.map((r) => r.id));
  const apps = cache.applications.filter((r) => leadIds.has(data(r).lead_id));
  const appIds = new Set(apps.map((r) => r.id));
  const reports = cache.reports.filter((r) =>
    appIds.has(data(r).application_id),
  );
  const resumeIds = new Set(
    apps.map((r) => data(r).resume_version_id).filter(Boolean),
  );
  const resumes = cache.resumes.filter((r) => resumeIds.has(r.id));
  const caps = cache.capabilities.filter((r) => data(r).company === company);
  return { leads, apps, reports, resumes, caps };
}

function pageTabs() {
  return `<nav class="job-flow__pages" aria-label="求职板块页面">${PAGES.map(
    ([id, label]) =>
      `<button class="job-flow__page-tab" type="button" data-action="jobflow-page" data-page="${id}" aria-pressed="${id === cache.page}">${label}</button>`,
  ).join("")}</nav>`;
}

function companyBar() {
  const list = companies();
  const active = currentCompany();
  if (!list.length)
    return `<div class="job-flow__companies"><a class="small-button" href="#module/jobs">＋ 先登记一个公司 / 岗位意向</a></div>`;
  return `<nav class="job-flow__companies" aria-label="切换公司">${list
    .map(
      (name) =>
        `<button class="job-flow__company" type="button" data-action="jobflow-company" data-company="${escape(name)}" aria-pressed="${name === active}">${escape(name)}</button>`,
    )
    .join("")}<a class="small-button" href="#module/jobs">＋ 新增公司</a></nav>`;
}

function stageTabs() {
  return `<nav class="job-flow__stages" aria-label="求职阶段">${STAGES.map(
    ([id, label], i) =>
      `<button class="job-flow__stage-tab" type="button" data-action="jobflow-stage" data-stage="${id}" aria-pressed="${id === cache.stage}"><span>${i + 1}</span>${label}</button>`,
  ).join("")}</nav>`;
}

const card = (title, body, extra = "") =>
  `<article class="job-flow__card"><h3>${title}</h3>${body}${extra}</article>`;
const meta = (pairs) =>
  `<div class="job-flow__meta">${pairs
    .filter(([, v]) => v !== undefined && v !== null && v !== "")
    .map(([k, v]) => `<span>${escape(k)}：${escape(String(v))}</span>`)
    .join("")}</div>`;
const empty = (text, href, linkText) =>
  `<p class="empty-state">${escape(text)}${href ? ` <a href="${href}">${escape(linkText)}</a>` : ""}</p>`;

function resumeName(id) {
  if (!id) return "";
  return data(cache.resumes.find((r) => r.id === id) || {}).title || "";
}

function intentStage(p) {
  const leads = p.leads.map((r) => {
    const d = data(r);
    return card(
      escape(d.title || "未命名岗位"),
      meta([
        ["公司", d.company],
        ["JD 原文", d.jd_text ? "已录入" : "未录入"],
        ["备注", d.notes ? String(d.notes).slice(0, 80) : ""],
      ]),
    );
  });
  const apps = p.apps.map((r) => {
    const d = data(r);
    return card(
      escape(d.title || "投递记录"),
      meta([
        ["状态", d.status],
        ["渠道", d.channel],
        ["投递时间", d.applied_at],
        ["下次跟进", d.follow_up_at],
        ["使用简历", resumeName(d.resume_version_id)],
      ]),
    );
  });
  return `<h2 class="job-flow__heading">我选了这家公司的哪些岗位</h2><div class="job-flow__grid">${leads.join("") || empty("还没有岗位意向。", "#module/jobs", "去登记")}</div>
    <h2 class="job-flow__heading">投递进展</h2><div class="job-flow__grid">${apps.join("") || empty("还没有投递记录。", "#module/jobs", "去添加")}</div>`;
}

function requiredStage(p) {
  const items = p.caps.flatMap((r) =>
    (data(r).capabilities || []).map((c) => ({ ...c, _source: data(r).title })),
  );
  const must = items.filter((c) => c.requirement === "must");
  const nice = items.filter((c) => c.requirement !== "must");
  const render = (list) =>
    list
      .map((c) =>
        card(
          escape(c.name || "未命名能力"),
          meta([
            ["重要度", c.level],
            ["证据状态", c.status],
            ["证据", c.evidence ? String(c.evidence).slice(0, 100) : ""],
            ["来源", c._source],
          ]),
        ),
      )
      .join("");
  if (!items.length)
    return empty(
      "还没有登记这家公司需要什么能力。",
      "#module/company-capabilities",
      "去登记能力清单",
    );
  return `<h2 class="job-flow__heading">必须满足（${must.length}）</h2><div class="job-flow__grid">${render(must) || '<p class="empty-state">暂无</p>'}</div>
    <h2 class="job-flow__heading">加分项（${nice.length}）</h2><div class="job-flow__grid">${render(nice) || '<p class="empty-state">暂无</p>'}</div>`;
}

function gapStage(p) {
  const items = p.caps.flatMap((r) =>
    (data(r).capabilities || []).filter(
      (c) => c.status === "missing" || c.status === "pending",
    ),
  );
  const missing = items
    .map((c) =>
      card(
        escape(c.name || "未命名能力"),
        meta([
          ["状态", c.status === "missing" ? "待补充" : "待核实"],
          ["重要度", c.level],
          ["证据", c.evidence],
        ]),
      ),
    )
    .join("");
  const leadOptions = p.leads
    .map(
      (r) =>
        `<option value="${escape(r.id)}" ${cache.gapLeadId === r.id ? "selected" : ""}>${escape(data(r).title || "岗位")}</option>`,
    )
    .join("");
  const gapPanel = `<div class="job-flow__analysis"><h2 class="job-flow__heading">JD 规则分析（只读，不调用模型）</h2>
    ${p.leads.length ? `<div class="job-flow__controls"><select id="job-flow-gap-lead" aria-label="选择岗位">${leadOptions}</select><button class="small-button" type="button" data-action="jobflow-gap-analyze">查看差距</button></div>` : empty("先登记岗位意向才能分析 JD。", "#module/jobs", "去登记")}
    ${cache.gapError ? `<p class="error-text">${escape(cache.gapError)}</p>` : ""}
    ${cache.gap ? renderAnalysis(cache.gap.analysis || {}) : ""}</div>`;
  return `<h2 class="job-flow__heading">能力清单里标为待补充 / 待核实的（${items.length}）</h2><div class="job-flow__grid">${missing || empty("没有待补充的能力，或还没登记能力清单。", "#module/company-capabilities", "去看能力清单")}</div>${gapPanel}`;
}

function renderAnalysis(analysis) {
  const requirements = Array.isArray(analysis.requirements)
    ? analysis.requirements
    : [];
  const notes = Array.isArray(analysis.notes) ? analysis.notes : [];
  return `<div class="job-flow__grid">${requirements
    .map((r) =>
      card(
        escape(r.name || "要求"),
        meta([
          ["优先级", r.priority],
          ["证据", Array.isArray(r.profile_facts) ? r.profile_facts.length : ""],
        ]),
      ),
    )
    .join("") || '<p class="empty-state">规则分析没有提取到要求，请结合完整 JD 阅读。</p>'}</div>
    ${notes.map((n) => `<p class="settings-hint">${escape(String(n))}</p>`).join("")}`;
}

function reviewStage(p) {
  const rows = p.reports
    .map((r) => {
      const d = data(r);
      const questions = Array.isArray(d.questions) ? d.questions : [];
      const weak = Array.isArray(d.weak_points) ? d.weak_points : [];
      const next = Array.isArray(d.next_actions) ? d.next_actions : [];
      return card(
        escape(d.title || `第 ${d.round || 1} 轮面试复盘`),
        meta([
          ["轮次", d.round],
          ["面试时间", d.interviewed_at],
          ["问题数", questions.length],
          ["薄弱点", weak.join("、")],
          ["下一步", next.join("、")],
        ]),
      );
    })
    .join("");
  return `<h2 class="job-flow__heading">面完之后的反省（${p.reports.length}）</h2><div class="job-flow__grid">${rows || empty("还没有面试复盘。面完记得把问题和自评写下来。", "#module/jobs", "去写复盘")}</div>`;
}

function stageContent(p) {
  if (cache.stage === "required") return requiredStage(p);
  if (cache.stage === "gap") return gapStage(p);
  if (cache.stage === "review") return reviewStage(p);
  return intentStage(p);
}

function pipelinePage() {
  const company = currentCompany();
  if (!company)
    return `${companyBar()}${empty("还没有公司。先登记一个岗位意向或能力清单。", "#module/jobs", "去登记")}`;
  return `${companyBar()}${stageTabs()}${stageContent(pipeline(company))}`;
}

/* 个人简历：全量版本，不按公司过滤；规则比对可跨公司挑岗位。 */
function resumesPage() {
  const rows = cache.resumes
    .map((r) => {
      const d = data(r);
      const highlights = Array.isArray(d.highlights) ? d.highlights : [];
      const usedBy = cache.applications
        .filter((a) => data(a).resume_version_id === r.id)
        .map((a) => data(a).title || "投递记录");
      return card(
        escape(d.title || "简历版本"),
        meta([
          ["文件", d.file_name],
          ["解析状态", d.parse_status],
          ["亮点", highlights.join("、")],
          ["用于投递", usedBy.join("、")],
        ]),
      );
    })
    .join("");
  const leadOptions = cache.leads
    .map((r) => {
      const d = data(r);
      const label = `${d.company ? d.company + " · " : ""}${d.title || "岗位"}`;
      return `<option value="${escape(r.id)}">${escape(label)}</option>`;
    })
    .join("");
  const resumeOptions = cache.resumes
    .map(
      (r) =>
        `<option value="${escape(r.id)}">${escape(data(r).title || "简历")}</option>`,
    )
    .join("");
  const canAnalyze = cache.leads.length && cache.resumes.length;
  const controls = canAnalyze
    ? `<div class="job-flow__controls"><select id="job-flow-resume-id" aria-label="选择简历">${resumeOptions}</select><select id="job-flow-resume-lead" aria-label="选择岗位">${leadOptions}</select><button class="small-button" type="button" data-action="jobflow-resume-analyze">运行规则比对</button></div>`
    : empty("需要至少一个岗位（含 JD 原文）和一个简历版本才能比对。", "#module/jobs", "去准备");
  const result = cache.analysis
    ? `<h2 class="job-flow__heading">比对结果</h2><div class="job-flow__grid">${card(
        "简历命中",
        meta([
          ["命中能力", (cache.analysis.matched_skills || []).join("、")],
          ["质量已验证", cache.analysis.quality_verified ? "是" : "否"],
        ]),
      )}</div>${renderAnalysis(cache.analysis.analysis || {})}`
    : "";
  return `<h2 class="job-flow__heading">全部简历版本（${cache.resumes.length}）</h2><div class="job-flow__grid">${rows || empty("还没有简历版本。", "#module/jobs", "去上传简历")}</div>
    <h2 class="job-flow__heading">规则比对：JD 要求 × 简历文本（只读，不调用模型）</h2>${controls}
    ${cache.analysisError ? `<p class="error-text">${escape(cache.analysisError)}</p>` : ""}${result}
    <p class="settings-hint">简历是个人资产，不随公司切换。命中只表示词出现在简历里，不代表能力已验证。</p>`;
}

/* AI 优化简历：模板由用户配置；未配置模板/模型时明确报缺，不放假功能。 */
function aiResumePage() {
  if (!cache.templatesLoaded && !cache.templatesError && !cache.templatesLoading)
    loadTemplates();
  const templates = cache.templates || [];
  const picked = cache.optimizeSelection || {};
  const option = (value, label, selected) =>
    `<option value="${escape(value)}" ${selected === value ? "selected" : ""}>${escape(label)}</option>`;
  const templateOptions = templates
    .map((t) => option(t.id, t.name, picked.template_id))
    .join("");
  const resumeOptions = cache.resumes
    .map((r) => option(r.id, data(r).title || "简历", picked.resume_id))
    .join("");
  const leadOptions = cache.leads
    .map((r) => {
      const d = data(r);
      return option(r.id, `${d.company ? d.company + " · " : ""}${d.title || "岗位"}`, picked.lead_id);
    })
    .join("");
  const ready = templates.length && cache.leads.length && cache.resumes.length;
  const form = ready
    ? `<form id="resume-optimize-form" class="resume-optimizer"><div class="job-flow__controls"><select name="template_id" aria-label="优化模板">${templateOptions}</select><select name="resume_id" aria-label="简历版本">${resumeOptions}</select><select name="lead_id" aria-label="目标岗位">${leadOptions}</select><button class="primary-button" type="submit">生成草稿</button></div><small>生成会调用服务器配置的模型；未配置时明确报错，不返回伪造结果。</small></form>`
    : empty(
        "尚未配置优化模板，或还缺少简历 / 岗位。模板写在服务器 config/resume_templates.yaml。",
        "#module/jobs",
        "去准备资料",
      );
  const draft = cache.draft
    ? `<div class="resume-optimizer__draft"><h2 class="job-flow__heading">优化草稿（尚未写库）</h2><pre class="preserve-lines">${escape(cache.draft.draft)}</pre><p class="settings-hint">${escape(cache.draft.note || "")}</p><div class="trait-ops"><button class="small-button" type="button" data-action="jobflow-apply">确认另存留痕</button></div></div>`
    : "";
  return `<div class="job-flow__placeholder"><h3>AI 优化简历 · 模板驱动</h3><p>模板内容由你提供。草稿<strong>不覆盖简历本体</strong>；只有你点「确认另存」才写成一条独立知识记录并保留版本历史。模板或模型连接未配置时接口明确报错，不生成伪造改写。</p></div>
    <div class="job-flow__grid">${card(
      "模板状态",
      meta([
        ["已配置模板", templates.length],
        ["简历版本", cache.resumes.length],
        ["岗位", cache.leads.length],
        ["草稿写库", "仅人工确认后"],
      ]),
    )}${card(
      "边界",
      meta([
        ["工具", "不新增、不改配置"],
        ["模型", "未配置则不请求"],
        ["留痕", "另存为知识记录"],
      ]),
    )}</div>
    ${cache.templatesError ? `<p class="error-text">${escape(cache.templatesError)}</p>` : ""}
    ${cache.optimizerError ? `<p class="error-text">${escape(cache.optimizerError)}</p>` : ""}
    ${form}${draft}`;
}

/* 预面试：三种模式共用 turns[]；语音模式只留接口，不实现音频。 */
async function loadPrepSessions() {
  if (cache.prepLoading || cache.prepLoaded || cache.prepError) return;
  cache.prepLoading = true;
  try {
    cache.prepSessions = (await api("interview-prep")) || [];
    cache.prepLoaded = true;
  } catch (e) {
    cache.prepError = e.message;
  } finally {
    cache.prepLoading = false;
    _repaint();
  }
}

function prepSessionsCard() {
  const rows = (cache.prepSessions || []).map((r) =>
    card(
      escape(data(r).title || "预面试会话"),
      meta([
        ["公司", data(r).company],
        ["模式", data(r).mode],
        ["回合", (data(r).turns || []).length],
      ]),
    ),
  );
  return `<h2 class="job-flow__heading">已保存的会话（${rows.length}）</h2><div class="job-flow__grid">${rows.join("") || '<p class="empty-state">还没有保存过预面试会话。</p>'}</div>`;
}

function prepPage() {
  if (!cache.prepLoaded && !cache.prepError && !cache.prepLoading) loadPrepSessions();
  const mode = PREP_MODES.some(([id]) => id === cache.prepMode)
    ? cache.prepMode
    : "practice";
  const tabs = `<nav class="job-flow__stages" aria-label="预面试模式">${PREP_MODES.map(
    ([id, label]) =>
      `<button class="job-flow__stage-tab" type="button" data-action="jobflow-prep-mode" data-mode="${id}" aria-pressed="${id === mode}">${label}</button>`,
  ).join("")}</nav>`;
  if (mode === "voice")
    return `${tabs}<div class="job-flow__placeholder"><h3>模拟面试（语音）· 等待接入</h3><p>后续接入模拟人声：按 turns[] 逐轮播放问题、采集你的回答并给出建议。数据模型已预留 audio 字段与回合结构；本轮<strong>不实现音频生成或识别，也不放假按钮</strong>。</p></div>${prepSessionsCard()}`;
  const leadOptions = cache.leads
    .map((r) => {
      const d = data(r);
      return `<option value="${escape(r.id)}">${escape(`${d.company ? d.company + " · " : ""}${d.title || "岗位"}`)}</option>`;
    })
    .join("");
  const resumeOptions = cache.resumes
    .map((r) => `<option value="${escape(r.id)}">${escape(data(r).title || "简历")}</option>`)
    .join("");
  const ready = cache.leads.length && cache.resumes.length;
  const controls = ready
    ? `<form id="prep-generate-form" class="job-flow__controls"><select name="lead_id" aria-label="目标岗位">${leadOptions}</select><select name="resume_id" aria-label="简历版本">${resumeOptions}</select><label class="scope-checkboxes"><input type="checkbox" name="use_model">用模型生成（需配置连接）</label><button class="primary-button" type="submit">生成问答</button></form><p class="settings-hint">${mode === "practice" ? "练习模式只出问题，你可以自己答；规则模式是模板题，不代表真实面试官的问题。" : "完整问答给出示范回答与优化建议，需人工核对，不添加简历里没有的事实。"}</p>`
    : empty("需要至少一个岗位（含 JD 原文）和一个简历版本。", "#module/jobs", "去准备");
  const turns = cache.prepDraft
    ? cache.prepDraft.turns
        .map((t, i) => {
          const body =
            mode === "full"
              ? `<p class="trait-note">${escape(t.answer || "（无示范回答）")}</p><p class="settings-hint">建议：${escape(t.suggestion || "暂无")}</p>`
              : `<label class="form-field">我来答<textarea data-prep-answer="${i}" rows="3" maxlength="8000" placeholder="写下你的回答，保存时会一起留痕"></textarea></label>`;
          return `<article class="prep-turn"><h3>Q${i + 1} · ${escape(t.q)}</h3>${body}</article>`;
        })
        .join("")
    : "";
  const save = cache.prepDraft
    ? `<div class="trait-ops"><button class="small-button" type="button" data-action="jobflow-prep-save">保存会话</button></div>`
    : "";
  return `${tabs}${controls}${cache.prepError ? `<p class="error-text">${escape(cache.prepError)}</p>` : ""}${turns ? `<div class="job-flow__grid">${turns}</div>${save}` : ""}${prepSessionsCard()}`;
}

function managePage() {
  const links = [
    ["#module/jobs", "求职记录 / 简历上传", "岗位意向、投递、面试复盘、简历上传"],
    ["#module/company-capabilities", "能力清单", "按公司登记 must / nice 能力与证据"],
    ["#module/job-insights", "证据对照", "我的求职证据与 JD 分析"],
    ["#module/job-weekly", "求职周报", "按周统计与汇总"],
  ];
  return `<p class="settings-hint">这四张单表是原来的页面，数据一条没动，仍可直接打开。板块只把它们收进来，不替换。</p><div class="job-flow__grid">${links
    .map(
      ([href, label, note]) =>
        `<article class="job-flow__card"><h3>${escape(label)}</h3><p class="settings-hint">${escape(note)}</p><div class="trait-ops"><a class="small-button" href="${href}">打开页面</a></div></article>`,
    )
    .join("")}</div>`;
}

function pageContent() {
  if (cache.page === "prep") return prepPage();
  if (cache.page === "resumes") return resumesPage();
  if (cache.page === "ai-resume") return aiResumePage();
  if (cache.page === "manage") return managePage();
  return pipelinePage();
}

export function jobFlowView() {
  if (!cache.loaded && !cache.error && !cache.loading) load();
  const head = `<div class="page-head"><h1>求职板块</h1><p class="settings-hint">公司的事按公司看，简历的事单独看。流水线只覆盖从选岗位到面试复盘，简历与 AI 优化是并列页面。</p></div>`;
  if (cache.loading && !cache.loaded)
    return `${head}<section class="module-surface job-flow__page"><p>正在读取求职资料…</p></section>`;
  if (cache.error)
    return `${head}<section class="module-surface job-flow__page"><p class="error-text" role="alert">${escape(cache.error)}</p><button class="small-button" type="button" data-action="jobflow-reload">重新读取</button></section>`;
  return `${head}${pageTabs()}<section class="module-surface job-flow__page" aria-busy="${cache.busy}">${pageContent()}</section>`;
}

export function bindJobFlow({ renderPage, toast }) {
  _repaint = () => {
    if (location.hash === "#module/job-flow") renderPage({ restore: true });
  };

  document.addEventListener("click", async (e) => {
    if (!(e.target instanceof Element)) return;
    const b = e.target.closest('[data-action^="jobflow-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(8);
    if (action === "page") {
      cache.page = validPage(b.dataset.page);
      write("job-flow-page", cache.page);
      _repaint();
    } else if (action === "company") {
      cache.company = b.dataset.company || "";
      cache.gap = null;
      write("job-flow-company", cache.company);
      _repaint();
    } else if (action === "stage") {
      cache.stage = validStage(b.dataset.stage);
      write("job-flow-stage", cache.stage);
      _repaint();
    } else if (action === "reload") {
      load(true);
    } else if (action === "gap-analyze") {
      const leadId = document.getElementById("job-flow-gap-lead")?.value;
      if (!leadId) return;
      cache.busy = true;
      cache.gapError = "";
      _repaint();
      try {
        cache.gapLeadId = leadId;
        cache.gap = await api(`jobs/leads/${leadId}/gap`);
      } catch (err) {
        cache.gapError = err.message;
      } finally {
        cache.busy = false;
        _repaint();
      }
    } else if (action === "resume-analyze") {
      const resumeId = document.getElementById("job-flow-resume-id")?.value;
      const leadId = document.getElementById("job-flow-resume-lead")?.value;
      if (!resumeId || !leadId) return;
      cache.busy = true;
      cache.analysisError = "";
      _repaint();
      try {
        cache.analysisKey = `${resumeId}:${leadId}`;
        cache.analysis = await api(
          `jobs/resumes/${resumeId}/analyze`,
          { lead_id: leadId },
          "POST",
        );
        toast("规则比对完成，命中只代表文本出现，不代表能力已验证");
      } catch (err) {
        cache.analysisError = err.message;
      } finally {
        cache.busy = false;
        _repaint();
      }
    } else if (action === "prep-mode") {
      cache.prepMode = b.dataset.mode || "practice";
      cache.prepDraft = null;
      cache.prepError = "";
      write("job-flow-prep-mode", cache.prepMode);
      _repaint();
    } else if (action === "prep-save") {
      if (!cache.prepDraft) return;
      const answers = [...document.querySelectorAll("[data-prep-answer]")].map(
        (el) => el.value,
      );
      const draft = {
        ...cache.prepDraft,
        turns: cache.prepDraft.turns.map((t, i) => ({
          ...t,
          answer: cache.prepMode === "practice" ? answers[i] || "" : t.answer,
        })),
      };
      cache.busy = true;
      _repaint();
      try {
        await api("interview-prep", { data: draft });
        toast("预面试会话已保存，未写入面试复盘");
        cache.prepLoaded = false;
        cache.prepError = "";
        await loadPrepSessions();
      } catch (err) {
        cache.prepError = err.message;
      } finally {
        cache.busy = false;
        _repaint();
      }
    } else if (action === "apply") {
      if (!cache.draft) return;
      cache.busy = true;
      _repaint();
      try {
        await api("resume/apply", {
          title: `简历优化 · ${cache.draft.template}`,
          draft: cache.draft.draft,
          confirmation: "确认另存优化草稿",
        });
        toast("已另存为知识记录，简历本体未改动");
        cache.draft = null;
        cache.optimizerError = "";
      } catch (err) {
        cache.optimizerError = err.message;
      } finally {
        cache.busy = false;
        _repaint();
      }
    }
  });

  document.addEventListener("submit", async (e) => {
    if (e.target.id === "prep-generate-form") {
      e.preventDefault();
      if (cache.busy) return;
      const fd = new FormData(e.target);
      cache.busy = true;
      cache.prepError = "";
      _repaint();
      try {
        cache.prepDraft = await api("interview-prep/generate", {
          lead_id: fd.get("lead_id"),
          resume_id: fd.get("resume_id"),
          mode: cache.prepMode,
          use_model: fd.has("use_model"),
        });
        toast("预面试问答已生成，尚未保存");
      } catch (err) {
        cache.prepError = err.message;
      } finally {
        cache.busy = false;
        _repaint();
      }
      return;
    }
    if (e.target.id !== "resume-optimize-form") return;
    e.preventDefault();
    if (cache.busy) return;
    const fd = new FormData(e.target);
    cache.optimizeSelection = {
      template_id: fd.get("template_id"),
      resume_id: fd.get("resume_id"),
      lead_id: fd.get("lead_id"),
    };
    cache.busy = true;
    cache.optimizerError = "";
    _repaint();
    try {
      cache.draft = await api("resume/optimize", cache.optimizeSelection);
      toast("草稿已生成，尚未写库");
    } catch (err) {
      cache.optimizerError = err.message;
    } finally {
      cache.busy = false;
      _repaint();
    }
  });

  return {
    ensure() {
      if (location.hash === "#module/job-flow" && !cache.loaded && !cache.loading)
        load();
    },
  };
}
