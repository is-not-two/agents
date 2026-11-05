/* 自动化纯视图：配置、实际运行与人工确认各自呈现。 */
import { state } from "./data.js?v=119";
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
const button = (label, action, cls = "small-button", attrs = "") =>
  `<button class="${cls}" data-action="auto-${action}" ${attrs}>${label}</button>`;
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
function result(row, confirmation = false) {
  if (!row) return "";
  if (row.data.kind === "graph") return graphResult(row);
  const r = row.data,
    res = r.result || {};
  return `<section class="run-result" data-run-id="${row.id}"><div class="run-result-head"><div><small>运行结果 · ${esc(row.id.slice(0, 8))}</small><h2>${esc(r.title)}</h2></div><span class="run-badge ${r.status}">${labels[r.status] || r.status}</span></div>${row.kind === "agent_session" ? '<p class="result-notice">此运行含会话或长期记忆配置，不进入公共工作区备份；未做应用层加密。</p>' : ""}<p class="run-input-label">${r.kind === "answer" ? "问题：" + esc(r.input.query) : "资料：" + esc(r.input.title)}</p><ol class="run-steps">${r.steps.map((s) => `<li><span class="step-indicator ${s.status}">${s.status === "completed" ? "✓" : s.status === "skipped" ? "−" : "!"}</span><div><strong>${esc(s.title)}</strong><p>${esc(s.detail)}</p></div><small>${s.duration_ms} ms</small></li>`).join("")}</ol><details class="run-context"><summary>输入与配置版本</summary><p>流程 v${r.workflow?.version || "—"}${r.agent ? " · " + esc(r.agent.data.title) + " v" + r.agent.version : ""}</p><pre>${esc(r.input.query || r.input.content || "")}</pre></details>${r.trace?.length ? `<details class="run-context"><summary>模型预算与调用追踪</summary><pre class="preserve-lines">${esc(JSON.stringify({ limits: r.effective_limits, trace: r.trace }, null, 2))}</pre></details>` : ""}${r.kind === "answer" ? `${res.notes?.length ? `<p class="result-notice">${esc(res.notes.join("；"))}</p>` : ""}${res.answer ? `<article class="answer-card preserve-lines">${esc(res.answer)}</article>` : ""}<div class="run-citations">${(res.hits || []).map((h, i) => `<details><summary><span>[${i + 1}] ${esc(h.title)}</span><small>${scopes[h.category] || h.category}</small></summary><p class="preserve-lines">${esc(h.content)}</p><small>${esc(h.source)}</small></details>`).join("") || "<p>没有找到相关依据。</p>"}</div>` : `${r.status === "awaiting_confirmation" ? '<p class="result-notice">片段尚未写入知识库，选择并确认后才会保存。</p>' : ""}<form id="ingest-confirm-form" data-run-id="${row.id}" data-version="${row.version}"><div class="ingest-chunks">${(res.chunks || []).map((c, i) => `<details class="ingest-chunk" open><summary>${r.status === "awaiting_confirmation" ? `<input type="checkbox" name="selected" value="${i}" checked aria-label="选择片段 ${i + 1}">` : ""}<strong>${esc(c.title)}</strong><small>${c.content.length} 字</small></summary><p class="preserve-lines">${esc(c.content)}</p></details>`).join("")}</div>${r.status === "awaiting_confirmation" ? `<div class="form-actions"><button type="submit" class="primary-button" ${state.autoBusy ? "disabled" : ""}>${state.autoBusy ? "正在保存…" : "确认选中片段入库"}</button></div>` : ""}${r.status === "confirmed" ? `<p>已保存 ${res.created_ids.length} 条知识。<a class="small-button" href="#module/knowledge">前往知识库</a></p>` : ""}</form>`}</section>`;
}
export function workflowsPage() {
  const w = flow();
  const input = state.automationInput;
  return `${unavailable()}<div class="module-toolbar"><p>选择流程，输入内容并执行。</p>${button("新建流程", "new-workflow", "primary-button")}</div>${w ? `<div class="automation-layout"><nav class="workflow-list" aria-label="已保存流程">${state.workflows.map((r) => `<button data-action="auto-select-flow" data-id="${r.id}" aria-pressed="${r.id === w.id}" ${state.autoBusy ? "disabled" : ""}><small>${r.data.kind === "answer" ? "检索与回答" : r.data.kind === "graph" ? "通用 DAG" : "知识处理"}</small><strong>${esc(r.data.title)}</strong><span>v${r.version}</span></button>`).join("")}</nav><section class="workflow-workspace"><header class="workflow-heading"><h2>${esc(w.data.title)}</h2>${button("编辑流程", "edit-workflow", "small-button", `data-id="${w.id}"`)}</header><ol class="pipeline-rail">${(w.data.kind === "graph" ? w.data.nodes.map((node) => node.id) : w.data.kind === "answer" ? ["接收问题", "检索依据", "可选 AI 回答"] : ["接收资料", "标题与字数切片", "人工确认入库"]).map((s, i) => `<li><span>0${i + 1}</span>${s}</li>`).join("")}</ol><form id="workflow-execute-form" data-workflow-id="${w.id}" aria-busy="${state.autoBusy}">${w.data.kind === "answer" || w.data.kind === "graph" ? `<p class="workflow-agent">${w.data.kind === "graph" ? "通用 DAG 流程，按节点顺序协调工具与 Agent" : "使用 " + esc(state.agents.find((a) => a.id === w.data.agent_id)?.data.title || "Agent 已不可用，请重新选择")}</p><label class="form-field">问题<input name="query" required maxlength="1000" value="${esc(input.query)}" placeholder="想从知识库或 Agent 中查找什么？"></label>` : `<div class="ingest-input-head"><label class="form-field">资料名称<input name="title" required maxlength="160" value="${esc(input.title)}"></label><label class="file-import small-button">读取 Markdown / TXT<input id="workflow-file" type="file" accept=".md,.txt,text/plain,text/markdown"></label></div><label class="form-field">来源（可选）<input name="source" maxlength="1000" value="${esc(input.source)}"></label><label class="form-field">资料正文<textarea name="content" rows="8" required maxlength="100000" placeholder="粘贴资料，或从本机读取文件">${esc(input.content)}</textarea></label><small>按标题和 ${w.data.chunk_size} 字切片，下一步由你确认。</small>`}<div class="form-actions"><button type="submit" class="primary-button" ${state.autoBusy ? "disabled" : ""}>${state.autoBusy ? "执行中…" : w.data.kind === "answer" ? "执行检索流程" : w.data.kind === "graph" ? "运行 DAG" : "解析并预览"}</button></div>${state.autoError ? `<p class="error-text" role="alert">${esc(state.autoError)}</p>` : ""}</form>${state.currentRun?.data.workflow_id === w.id ? result(state.currentRun, true) : ""}</section></div>` : empty()}`;
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
        )}</fieldset><label class="form-field">检索方式<select name="mode"><option value="text">全文匹配</option><option value="vector">技术文档向量＋重排</option></select><small>个人知识与规划使用全文；向量不可用时自动回退。</small></label>${field("最多引用条数", "result_limit", "number", 'min="1" max="10" required')}<label class="scope-checkboxes"><input type="checkbox" name="generate">尝试生成 AI 回答</label><p>模型不可用时仍显示引用。前往「模型连接」页面填写并保存 API 配置。</p>`,
    ) +
    dialog(
      "workflow",
      "工作流配置",
      `${field("名称", "title", "text", 'required maxlength="160"')}<label class="form-field">流程类型<select name="kind"><option value="answer">检索与回答</option><option value="ingest">资料处理与入库</option><option value="graph">通用 DAG（JSON）</option></select></label><label class="form-field" data-answer-config>使用 Agent<select name="agent_id"></select></label><div data-ingest-config>${field("每段最多字数", "chunk_size", "number", 'min="200" max="6000" required')}</div><div data-graph-config hidden><label class="form-field">DAG 定义<textarea name="graph_json" rows="10" placeholder='{"nodes":[{"id":"input","type":"input"},{"id":"merge","type":"merge"}],"edges":[["input","merge"]]}'></textarea></label><small>节点类型 input / retrieve / tool / agent / approval / merge；保存时会校验环、重复 ID、不可达节点与模板路径。</small></div>`,
    )
  );
}
