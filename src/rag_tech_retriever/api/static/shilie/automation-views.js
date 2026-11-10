/* 自动化纯视图：配置、实际运行与人工确认各自呈现。 */
import { state } from "./data.js?v=129";
export const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const flow = () =>
  state.workflows.find((w) => w.id === state.selectedFlow) ||
  state.workflows[0];
const labels = {
  running: "执行中",
  completed: "已完成",
  fallback: "已降级",
  failed: "执行失败",
  skipped: "已跳过",
  awaiting_confirmation: "待确认入库",
  confirmed: "已入库",
};
const scopes = { personal: "个人知识", docs: "技术文档", planning: "人生规划" };
const workspaceOptions = (selected = "") =>
  `<option value="">不绑定（只能检索与通用工具）</option>` +
  (state.codeRoots.length
    ? state.codeRoots
        .map(
          (root) =>
            `<option value="${esc(root.name)}" ${root.name === selected ? "selected" : ""}>${esc(root.title)}${root.writable ? "" : "（只读）"}</option>`,
        )
        .join("")
    : '<option value="" disabled>管理员尚未登记代码工作区</option>');
function workspacePanel() {
  return `<fieldset class="scope-checkboxes"><legend>代码工作区</legend><label class="form-field">绑定目录<select name="workspace_root">${workspaceOptions()}</select></label><label class="form-field">写入确认<select name="workspace_write"><option value="each">每次写入都要确认</option><option value="run">本轮首次确认后不再逐条确认</option></select></label><label><input type="checkbox" name="workspace_shell">允许执行管理员白名单命令（默认关闭）</label><small>代码工具由绑定自动授予：读、搜、改、写都会记入步骤，写入先备份再原子替换。</small></fieldset>`;
}
function draftPanel() {
  const draft = state.composeDraft;
  if (!draft) return "";
  const changes = state.composeChanges;
  const changeLine = (label, items) =>
    items && items.length ? `<li>${label}：${esc(items.map((item) => (Array.isArray(item) ? item.join(" → ") : item)).join("、"))}</li>` : "";
  const diff = changes
    ? `<ul class="draft-diff">${changeLine("新增节点", changes.nodes_added)}${changeLine("删除节点", changes.nodes_removed)}${changeLine("改动节点", changes.nodes_changed)}${changeLine("新增连线", changes.edges_added)}${changeLine("删除连线", changes.edges_removed)}${changeLine("新增 Agent", changes.agents_added)}${changeLine("删除 Agent", changes.agents_removed)}${changeLine("改动 Agent", changes.agents_changed)}</ul>`
    : "";
  return `<section class="draft-panel"><header class="workflow-heading"><h2>草稿：${esc(draft.workflow.title)}</h2><small>${draft.mode === "model" ? "模型生成" : "规则生成"} · ${draft.agents.length} 个 Agent · ${draft.workflow.nodes.length} 个节点 · 尚未保存</small></header><div class="draft-columns"><div><h3>Agent</h3><ul>${draft.agents.map((item) => `<li><strong>${esc(item.key)}</strong> ${esc(item.profile.title)}<small>${item.profile.workspace.root ? "工作区 " + esc(item.profile.workspace.root) : "无代码工作区"}${item.profile.tool_ids.length ? " · " + esc(item.profile.tool_ids.join("、")) : ""}</small></li>`).join("")}</ul></div><div><h3>节点</h3><ol>${draft.workflow.nodes.map((node) => `<li><strong>${esc(node.id)}</strong> ${esc(node.type)}${node.query ? "：" + esc(node.query.slice(0, 60)) : ""}</li>`).join("")}</ol></div></div>${diff}<label class="form-field">修改意见<textarea id="compose-feedback" rows="3" maxlength="2000" placeholder="例如：把审阅拆成两个人并行，最后加一个上线确认">${esc(state.composeFeedback || "")}</textarea></label><div class="form-actions"><button class="small-button" data-action="auto-revise-draft" ${state.autoBusy ? "disabled" : ""}>按意见修订</button><button class="primary-button" data-action="auto-save-draft" ${state.autoBusy ? "disabled" : ""}>确认并保存</button><button class="small-button" data-action="auto-drop-draft">放弃草稿</button></div></section>`;
}
function teamPanel() {
  const agents = state.agents || [];
  if (!agents.length) return "";
  const members = agents
    .map(
      (a) =>
        `<label class="team-member"><input type="checkbox" name="agent_ids" value="${a.id}"> <span>${esc(a.data.title)}</span><small>${esc((a.data.tool_ids || []).join("、") || "无额外工具")}</small></label>`,
    )
    .join("");
  const result = state.teamResult;
  const transcript = result
    ? `<section class="draft-panel"><header class="workflow-heading"><h2>团队发言（${result.turns.length} 段）</h2><small>${result.mode === "magentic" ? "磁石模式" : "群聊模式"} · ${result.model_calls} 次模型调用 · 记录 ${esc(result.id)}</small></header><ol class="team-turns">${result.turns.map((t) => `<li><strong>${esc(t.author)}</strong><p>${esc(t.text)}</p></li>`).join("")}</ol><p class="workflow-agent">终稿：${esc(result.final)}</p></section>`
    : "";
  return `<form id="team-form" class="compose-form"><h2>多 Agent 团队</h2><fieldset class="scope-checkboxes team-members"><legend>成员（1-4 个）</legend>${members}</fieldset><label class="form-field">团队目标<textarea name="task" rows="3" required maxlength="2000" placeholder="例如：给这家公司做能力缺口评估，并针对缺口出一道面试题"></textarea></label><div class="draft-columns"><label class="form-field">协作方式<select name="mode"><option value="group_chat">群聊：轮流发言，互相看结论</option><option value="magentic">磁石：自动规划、派活、按进度重规划</option></select></label><label class="form-field">最多轮次<input type="number" name="max_rounds" min="1" max="12" value="6"></label></div><label class="scope-checkboxes"><input type="checkbox" name="approved">允许本次执行写操作（改文件、外部动作）</label><div class="form-actions"><button class="primary-button" type="submit" ${state.teamBusy ? "disabled" : ""}>${state.teamBusy ? "团队运行中…" : "组建团队并运行"}</button></div><small>成员使用各自已授予的工具；写操作默认不执行，只把「需批准」回给团队。</small></form>${transcript}`;
}

/* 客户端等待上限：与 platform/coding_loop.py 的 TIERS 分钟预算对齐，留约 10% 余量。
   里程碑续期会再拉长服务端预算，届时页面可能先停止等待，结果以运行记录为准。 */
export const LOOP_TIMEOUT_MS = {
  patch: 11 * 60 * 1000,
  feature: 44 * 60 * 1000,
  epic: 198 * 60 * 1000,
};
const loopStates = { success: "通过门禁", failed: "未通过", stuck: "卡住", stopped: "已停止" };
function loopMetrics(r) {
  return `<div class="loop-metrics"><span>状态：${esc(loopStates[r.status] || r.status || "—")}</span><span>轮次：${r.rounds ?? "—"}</span><span>绿点：${r.green_points ?? "—"}</span><span>耗时：${r.duration_ms ?? "—"} ms</span><span>执行器：${esc(r.engine || "—")}</span><span>档位：${esc(r.tier || "—")}</span></div>`;
}
function loopAttempts(rows) {
  if (!Array.isArray(rows) || !rows.length)
    return '<p class="result-notice">没有产生改动尝试。</p>';
  return `<ol class="loop-attempts">${rows.map((a) => `<li><strong>第 ${esc(a.round)} 轮</strong> · ${a.passed ? "门禁通过" : "门禁未通过"} · ${esc(a.files)} 文件 / ${esc(a.lines)} 行<small>${esc(a.why || "无门禁输出")}</small></li>`).join("")}</ol>`;
}
function loopDiff(r) {
  /* 服务端给的是 git diff --stat（截 2000 字），不是完整补丁，文案必须如实。 */
  return r.diff
    ? `<details class="run-context" open><summary>改动摘要（git diff --stat）</summary><pre class="loop-diff preserve-lines">${esc(r.diff)}</pre></details>`
    : '<p class="result-notice">本次没有绿点改动摘要。</p>';
}
function loopResultPanel() {
  const r = state.loopResult;
  if (!r) return "";
  return `<section class="draft-panel loop-result"><header class="workflow-heading"><h2>自动编码结果</h2><small>记录 ${esc(r.id)}</small></header>${loopMetrics(r)}<p class="run-input-label">目标：${esc(r.task || "")}</p><p class="run-input-label">门禁：${esc(r.gate || "")}</p>${r.reason ? `<p class="result-notice">${esc(r.reason)}</p>` : ""}${loopAttempts(r.attempts)}${loopDiff(r)}</section>`;
}
function loopPanel() {
  const roots = (state.codeRoots || []).filter((root) => root.writable);
  const input = state.loopInput || {};
  const options = roots.length
    ? roots
        .map(
          (root) =>
            `<option value="${esc(root.name)}" ${root.name === input.root ? "selected" : ""}>${esc(root.title)}</option>`,
        )
        .join("")
    : '<option value="">没有可写的代码仓库</option>';
  const disabled = state.loopBusy || !roots.length;
  const engines = [
    ["opencode", "opencode（独立服务，多文件强）"],
    ["aider", "aider（Python 包，单轮较慢）"],
    ["model", "模型直写整文件（无外部依赖）"],
  ]
    .map(
      ([value, label]) =>
        `<option value="${value}" ${(input.engine || "opencode") === value ? "selected" : ""}>${label}</option>`,
    )
    .join("");
  const tiers = [
    ["patch", "patch：6 轮 / 3 文件 / 80 行 / 10 分钟"],
    ["feature", "feature：20 轮 / 10 文件 / 600 行 / 40 分钟"],
    ["epic", "epic：60 轮 / 30 文件 / 3000 行 / 180 分钟"],
  ]
    .map(
      ([value, label]) =>
        `<option value="${value}" ${(input.tier || "patch") === value ? "selected" : ""}>${label}</option>`,
    )
    .join("");
  return `<form id="loop-form" class="compose-form loop-form"><h2 class="loop-wide">自动编码</h2><label class="form-field">代码仓库<select name="root" required ${disabled ? "disabled" : ""}>${options}</select></label><label class="form-field">执行器<select name="engine" ${disabled ? "disabled" : ""}>${engines}</select></label><label class="form-field">预算档位<select name="tier" ${disabled ? "disabled" : ""}>${tiers}</select></label><label class="form-field loop-wide">改动目标<textarea name="task" rows="2" required maxlength="2000" placeholder="例如：修复空列表时的除零错误">${esc(input.task || "")}</textarea></label><label class="form-field loop-wide">门禁命令（退出码决定是否通过）<input name="gate" required maxlength="1000" value="${esc(input.gate || "")}" placeholder="例如：python -m pytest tests/test_x.py -q"></label><div class="form-actions loop-wide"><button class="primary-button" type="submit" ${disabled ? "disabled" : ""}>${state.loopBusy ? "编码中…" : "开始自动编码"}</button></div><small class="loop-wide">模型只负责改代码，通过与否由门禁退出码决定；改动只发生在隔离副本，主仓库不受影响。接口同步执行，页面最多等待约 ${Math.round((LOOP_TIMEOUT_MS[input.tier] || LOOP_TIMEOUT_MS.patch) / 60000)} 分钟；若页面先停止等待，服务端仍可能继续，结果以「运行记录」为准。展示的是改动摘要，不是完整补丁。</small></form>`;
}
const button = (label, action, cls = "small-button", attrs = "") =>  `<button class="${cls}" data-action="auto-${action}" ${attrs}>${label}</button>`;
function unavailable() {
  return state.automationError
    ? `<p class="error-text" role="alert">${esc(state.automationError)}</p>${button("重新加载", "reload")}`
    : "";
}
function empty() {
  return `<section class="empty-panel"><h2>启用你的第一组流程</h2><p>创建一个可编辑的知识助手，以及检索回答、资料入库两条流程。</p>${button(state.autoBusy ? "创建中…" : "启用基础流程", "setup", "primary-button", state.autoBusy ? "disabled" : "")}</section>`;
}
export function agentsPage() {
  return `${unavailable()}<div class="module-toolbar"><p>配置助手的指令、检索范围与回答方式。</p>${button("新建 Agent", "new-agent", "primary-button")}</div>${state.agents.length ? `<div class="agent-grid">${state.agents.map((a) => `<article class="agent-config"><header><span class="agent-monogram">${esc(a.data.title.slice(0, 1))}</span><div><h2>${esc(a.data.title)}</h2><small>配置版本 ${a.version}</small></div>${button("编辑", "edit-agent", "small-button", `data-id="${a.id}"`)}</header><p class="agent-instruction preserve-lines">${esc(a.data.system_prompt || "使用系统默认指令")}</p><div class="inline-tags">${a.data.scopes.map((s) => `<span>${scopes[s]}</span>`).join("")}</div><footer><span>${a.data.mode === "vector" ? "技术文档向量＋重排" : "全文匹配"} · ${a.data.result_limit} 条引用</span><span>${a.data.generate ? "生成 AI 回答" : "仅检索引用"}</span></footer></article>`).join("")}</div>` : empty()}`;
}
function graphResult(row) {
  const d = row.data, res = d.result || {};
  const pending = d.status === "awaiting_confirmation";
  const parallel = d.workflow?.data?.max_parallel || 1;
  const waiting = (d.pending_children || []).map((item) => item.node);
  return `<section class="run-result" data-run-id="${row.id}"><div class="run-result-head"><div><small>DAG 运行 · ${esc(row.id.slice(0, 8))} · 并行度 ${parallel}</small><h2>${esc(d.title)}</h2></div><span class="run-badge ${d.status}">${labels[d.status] || d.status}</span></div>
    <p class="run-input-label">输入：${esc(JSON.stringify(d.input || {}))}</p>
    <ol class="run-steps">${(d.steps || []).map((s) => `<li><span class="step-indicator ${s.status}">${s.status === "completed" ? "✓" : "!"}</span><div><strong>${esc(s.title)}</strong><p>${esc(s.detail)}</p></div><small>${s.duration_ms} ms</small></li>`).join("")}</ol>
    <details class="run-context" open><summary>节点状态</summary><pre class="preserve-lines">${esc(JSON.stringify(d.node_status || {}, null, 2))}</pre></details>
    ${res.answer ? `<article class="answer-card preserve-lines">${esc(res.answer)}</article>` : ""}
    ${(res.notes || []).map((note) => `<p class="error-text">${esc(note)}</p>`).join("")}
    ${pending ? `<p class="result-notice">等待确认节点：${esc(d.pending_node)}（${esc(d.pending_kind)}）${waiting.length > 1 ? `，同批 ${waiting.length} 个：${esc(waiting.join("、"))}` : ""}。批准后继续执行后续节点。</p><div class="form-actions"><button class="primary-button" data-action="auto-confirm-graph" data-id="${row.id}" data-approve="true">批准继续</button><button class="small-button" data-action="auto-confirm-graph" data-id="${row.id}" data-approve="false">拒绝并停止</button></div>` : ""}</section>`;
}
function teamRun(row) {
  const d = row.data,
    res = d.result || {};
  const members = (d.agents || []).map((a) => a.title).join("、");
  return `<section class="run-result" data-run-id="${row.id}"><div class="run-result-head"><div><small>团队运行 · ${esc(row.id.slice(0, 8))} · ${d.mode === "magentic" ? "磁石模式" : "群聊模式"} · ${d.model_calls || 0} 次模型调用</small><h2>${esc(d.title)}</h2></div><span class="run-badge ${d.status}">${labels[d.status] || d.status}</span></div><p class="run-input-label">目标：${esc(d.input?.task || "")}</p><p class="result-notice">成员：${esc(members || "—")}${d.approved ? " · 本轮允许写操作" : " · 本轮不允许写操作"}</p><ol class="team-turns">${(d.turns || []).map((t) => `<li><strong>${esc(t.author)}</strong><p>${esc(t.text)}</p></li>`).join("") || "<li>没有发言记录</li>"}</ol>${res.answer ? `<article class="answer-card preserve-lines">${esc(res.answer)}</article>` : ""}</section>`;
}
/* loop 记录结构与 answer/ingest 完全不同，必须单独渲染，
   否则会落到通用分支显示「资料：undefined」和入库确认表单。 */
function loopRun(row) {
  const d = row.data, s = d.summary || {};
  return `<section class="run-result" data-run-id="${esc(row.id)}"><div class="run-result-head"><div><small>自动编码 · ${esc(row.id.slice(0, 8))} · ${esc(s.engine || "—")} / ${esc(s.tier || "—")}</small><h2>${esc(d.title)}</h2></div><span class="run-badge ${esc(d.status)}">${labels[d.status] || esc(d.status)}</span></div>${loopMetrics(s)}<p class="run-input-label">目标：${esc(d.input?.task || s.task || "")}</p><p class="run-input-label">门禁：${esc(d.input?.gate || s.gate || "")}</p>${s.reason ? `<p class="result-notice">${esc(s.reason)}</p>` : ""}${loopAttempts(s.attempts)}${loopDiff(s)}</section>`;
}
function result(row, confirmation = false) {
  if (!row) return "";
  if (row.data.kind === "graph") return graphResult(row);
  if (row.data.kind === "team") return teamRun(row);
  if (row.data.kind === "loop") return loopRun(row);
  const r = row.data,
    res = r.result || {};
  return `<section class="run-result" data-run-id="${row.id}"><div class="run-result-head"><div><small>运行结果 · ${esc(row.id.slice(0, 8))}</small><h2>${esc(r.title)}</h2></div><span class="run-badge ${r.status}">${labels[r.status] || r.status}</span></div>${row.kind === "agent_session" ? '<p class="result-notice">此运行含会话或长期记忆配置，不进入公共工作区备份；未做应用层加密。</p>' : ""}<p class="run-input-label">${r.kind === "answer" ? "问题：" + esc(r.input.query) : "资料：" + esc(r.input.title)}</p><ol class="run-steps">${(r.steps || []).map((s) => `<li><span class="step-indicator ${s.status}">${s.status === "completed" ? "✓" : s.status === "skipped" ? "−" : "!"}</span><div><strong>${esc(s.title)}</strong><p>${esc(s.detail)}</p></div><small>${s.duration_ms} ms</small></li>`).join("")}</ol><details class="run-context"><summary>输入与配置版本</summary><p>流程 v${r.workflow?.version || "—"}${r.agent ? " · " + esc(r.agent.data.title) + " v" + r.agent.version : ""}</p><pre>${esc(r.input.query || r.input.content || "")}</pre></details>${r.trace?.length ? `<details class="run-context"><summary>模型预算与调用追踪</summary><pre class="preserve-lines">${esc(JSON.stringify({ limits: r.effective_limits, trace: r.trace }, null, 2))}</pre></details>` : ""}${r.kind === "answer" ? `${res.notes?.length ? `<p class="result-notice">${esc(res.notes.join("；"))}</p>` : ""}${res.answer ? `<article class="answer-card preserve-lines">${esc(res.answer)}</article>` : ""}<div class="run-citations">${(res.hits || []).map((h, i) => `<details><summary><span>[${i + 1}] ${esc(h.title)}</span><small>${scopes[h.category] || h.category}</small></summary><p class="preserve-lines">${esc(h.content)}</p><small>${esc(h.source)}</small></details>`).join("") || "<p>没有找到相关依据。</p>"}</div>` : `${r.status === "awaiting_confirmation" ? '<p class="result-notice">片段尚未写入知识库，选择并确认后才会保存。</p>' : ""}<form id="ingest-confirm-form" data-run-id="${row.id}" data-version="${row.version}"><div class="ingest-chunks">${(res.chunks || []).map((c, i) => `<details class="ingest-chunk" open><summary>${r.status === "awaiting_confirmation" ? `<input type="checkbox" name="selected" value="${i}" checked aria-label="选择片段 ${i + 1}">` : ""}<strong>${esc(c.title)}</strong><small>${c.content.length} 字</small></summary><p class="preserve-lines">${esc(c.content)}</p></details>`).join("")}</div>${r.status === "awaiting_confirmation" ? `<div class="form-actions"><button type="submit" class="primary-button" ${state.autoBusy ? "disabled" : ""}>${state.autoBusy ? "正在保存…" : "确认选中片段入库"}</button></div>` : ""}${r.status === "confirmed" ? `<p>已保存 ${res.created_ids.length} 条知识。<a class="small-button" href="#module/knowledge">前往知识库</a></p>` : ""}</form>`}</section>`;
}
export function workflowsPage() {
  const w = flow();
  const input = state.automationInput;
  return `${unavailable()}<div class="module-toolbar"><p>选择流程，输入内容并执行。</p>${button("新建流程", "new-workflow", "primary-button")}</div><form id="compose-form" class="compose-form"><label class="form-field">一句话目标<input name="goal" required maxlength="1000" placeholder="例如：把这份 JD 拆成能力清单并给出学习计划"></label><label class="form-field">生成方式<select name="mode"><option value="rules">规则模式（本地可验证，不调用模型）</option><option value="model">模型模式（需服务器配置模型连接）</option></select></label><label class="form-field">任务类型<select name="template"><option value="generic">通用任务（规划 → 产出）</option><option value="code">代码改动（规划 → 实现 → 审查）</option></select></label><div class="form-actions"><button class="small-button" type="button" data-action="auto-draft" ${state.autoBusy ? "disabled" : ""}>先出草稿审一遍</button><button class="primary-button" type="submit" ${state.autoBusy ? "disabled" : ""}>AI 生成并运行</button></div><small>「先出草稿」不写库：可以先提意见让它改，看到结构差异后再保存。直接生成会立刻建 Agent 与流程并运行，写库节点仍需人工批准。</small></form>${draftPanel()}${teamPanel()}${loopPanel()}${loopResultPanel()}${w ? `<div class="automation-layout"><nav class="workflow-list" aria-label="已保存流程">${state.workflows.map((r) => `<button data-action="auto-select-flow" data-id="${r.id}" aria-pressed="${r.id === w.id}" ${state.autoBusy ? "disabled" : ""}><small>${r.data.kind === "answer" ? "检索与回答" : r.data.kind === "graph" ? "通用 DAG" : "知识处理"}</small><strong>${esc(r.data.title)}</strong><span>v${r.version}</span></button>`).join("")}</nav><section class="workflow-workspace"><header class="workflow-heading"><h2>${esc(w.data.title)}</h2>${button("编辑流程", "edit-workflow", "small-button", `data-id="${w.id}"`)}</header><ol class="pipeline-rail">${(w.data.kind === "graph" ? w.data.nodes.map((node) => node.id) : w.data.kind === "answer" ? ["接收问题", "检索依据", "可选 AI 回答"] : ["接收资料", "标题与字数切片", "人工确认入库"]).map((s, i) => `<li><span>0${i + 1}</span>${s}</li>`).join("")}</ol><form id="workflow-execute-form" data-workflow-id="${w.id}" aria-busy="${state.autoBusy}">${w.data.kind === "answer" || w.data.kind === "graph" ? `<p class="workflow-agent">${w.data.kind === "graph" ? "通用 DAG 流程，按节点顺序协调工具与 Agent" : "使用 " + esc(state.agents.find((a) => a.id === w.data.agent_id)?.data.title || "Agent 已不可用，请重新选择")}</p><label class="form-field">问题<input name="query" required maxlength="1000" value="${esc(input.query)}" placeholder="想从知识库或 Agent 中查找什么？"></label>` : `<div class="ingest-input-head"><label class="form-field">资料名称<input name="title" required maxlength="160" value="${esc(input.title)}"></label><label class="file-import small-button">读取 Markdown / TXT<input id="workflow-file" type="file" accept=".md,.txt,text/plain,text/markdown"></label></div><label class="form-field">来源（可选）<input name="source" maxlength="1000" value="${esc(input.source)}"></label><label class="form-field">资料正文<textarea name="content" rows="8" required maxlength="100000" placeholder="粘贴资料，或从本机读取文件">${esc(input.content)}</textarea></label><small>按标题和 ${w.data.chunk_size} 字切片，下一步由你确认。</small>`}<div class="form-actions"><button type="submit" class="primary-button" ${state.autoBusy ? "disabled" : ""}>${state.autoBusy ? "执行中…" : w.data.kind === "answer" ? "执行检索流程" : w.data.kind === "graph" ? "运行 DAG" : "解析并预览"}</button></div>${state.autoError ? `<p class="error-text" role="alert">${esc(state.autoError)}</p>` : ""}</form>${state.currentRun?.data.workflow_id === w.id ? result(state.currentRun, true) : ""}</section></div>` : empty()}`;
}
export function runsPage() {
  return `${unavailable()}<div class="module-toolbar"><p>保存最近执行的输入、配置版本、步骤和结果。列表显示最近 100 次。</p>${button("刷新记录", "reload")}</div>${state.workflowRuns.length ? `<div class="run-list">${state.workflowRuns.map((r) => `<button data-action="auto-open-run" data-id="${r.id}"><span class="run-badge ${r.data.status}">${labels[r.data.status]}</span><span><strong>${esc(r.data.title)}</strong><small>${new Date(r.data.started_at).toLocaleString()}</small></span><span>查看 →</span></button>`).join("")}</div>` : '<section class="empty-panel"><h2>还没有执行记录</h2><a href="#module/workflows" class="primary-button">执行第一条流程</a></section>'}${state.runDetail ? result(state.runDetail) : ""}`;
}
const field = (label, name, type = "text", attrs = "") =>
  `<label class="form-field">${label}<input name="${name}" type="${type}" ${attrs}></label>`;
const actions =
  '<div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存配置</button></div><p class="auto-form-error error-text" role="alert" hidden></p>';
function dialog(kind, title, body) {
  return `<dialog class="form-dialog auto-dialog" data-auto-form="${kind}"><form class="automation-edit-form"><header class="drawer-header"><h2>${title}</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content">${body}${actions}</div></form></dialog>`;
}
export function automationDialogs() {
  return (
    dialog(
      "agent",
      "Agent 设置",
      `${field("名称", "title", "text", 'required maxlength="160"')}<label class="form-field">角色指令<textarea name="system_prompt" rows="6" maxlength="10000" placeholder="例如：用简洁的语言回答，并指出需要补充的资料。"></textarea></label><fieldset class="scope-checkboxes"><legend>允许检索的范围</legend>${Object.entries(
        scopes,
      )
        .map(
          ([s, l]) =>
            `<label><input type="checkbox" name="scopes" value="${s}">${l}</label>`,
        )
        .join(
          "",
        )}</fieldset><label class="form-field">检索方式<select name="mode"><option value="text">全文匹配</option><option value="vector">技术文档向量＋重排</option></select><small>个人知识与规划使用全文；向量不可用时自动回退。</small></label>${field("最多引用条数", "result_limit", "number", 'min="1" max="10" required')}<label class="scope-checkboxes"><input type="checkbox" name="generate">尝试生成 AI 回答</label>${workspacePanel()}<p>模型不可用时仍显示引用。前往「模型连接」页面填写并保存 API 配置。</p>`,
    ) +
    dialog(
      "workflow",
      "工作流配置",
      `${field("名称", "title", "text", 'required maxlength="160"')}<label class="form-field">流程类型<select name="kind"><option value="answer">检索与回答</option><option value="ingest">资料处理与入库</option><option value="graph">通用 DAG（JSON）</option></select></label><label class="form-field" data-answer-config>使用 Agent<select name="agent_id"></select></label><div data-ingest-config>${field("每段最多字数", "chunk_size", "number", 'min="200" max="6000" required')}</div><div data-graph-config hidden><div class="graph-editor" data-graph-editor><div class="graph-editor__head"><strong>节点编排</strong><button type="button" class="small-button" data-action="auto-graph-add">＋ 添加节点</button><button type="button" class="small-button" data-action="auto-graph-sync">同步到 JSON</button></div><div data-graph-rows></div><small>每行的「上游」决定依赖边；input 节点无上游。同步后仍可手工修改 JSON。</small></div><label class="form-field">DAG 定义（JSON）<textarea name="graph_json" rows="10" placeholder='{"nodes":[{"id":"input","type":"input"},{"id":"merge","type":"merge"}],"edges":[["input","merge"]]}'></textarea></label><small>节点类型 input / retrieve / tool / agent / approval / merge；保存时会校验环、重复 ID、不可达节点与模板路径。</small></div>`,
    )
  );
}
