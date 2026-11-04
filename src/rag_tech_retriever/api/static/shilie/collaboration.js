/* Experimental collaboration: no paid dispatch without server opt-in and confirmation. */
import { api, escapeHtml as esc } from "./data.js?v=112";
const c = { loaded: false, loading: false, busy: false, agents: [], runs: [], selected: "", run: null, status: {}, configured: false, error: "", draft: { query: "", steps: [] } };
let paint = () => {}, generation = 0;
const owner = () => c.agents.find((a) => a.id === c.selected);
const peers = () => c.agents.filter((a) => owner()?.data.handoffs?.allowed?.includes(a.id));
const route = (id) => `collaborations/${encodeURIComponent(id)}`;
const names = { running: "运行中，勿重复提交", awaiting_confirmation: "等待单独确认", confirmed: "计划已确认，尚未派发", completed: "全部计划已有产物", fallback: "未全部完成，查看已有产物", failed: "已停止" };
function release(button) { c.busy = false; if (button?.isConnected) button.disabled = false; const refresh = document.querySelector('[data-collab-action="refresh"]'); if (refresh) refresh.disabled = c.loading; }
async function load() {
  const ticket = ++generation; c.loading = true; paint();
  try {
    const agents = await api("agents"), status = await api("collaborations/status"), cfg = await api("model-connection");
    const selected = agents.some((a) => a.id === c.selected) ? c.selected : agents[0]?.id || "";
    const runs = (await api("collaborations")).filter((r) => r.data.workflow_id === `agent:${selected}`);
    const id = runs.find((r) => r.id === c.run?.id)?.id || runs[0]?.id;
    const run = id ? await api(route(id)) : null;
    if (ticket !== generation) return;
    Object.assign(c, { agents, status, selected, runs, run, configured: cfg.configured, error: "" });
  } catch (error) { if (ticket === generation) c.error = error.message; }
  finally { if (ticket === generation) { c.loaded = true; c.loading = false; paint(); } }
}
function planView(run) {
  let plan = run.data.shared_state.plan || [];
  if (!plan.length) {
    try { plan = JSON.parse(run.data.pending_calls?.[0]?.function?.arguments || "{}").plan || []; }
    catch { return '<p class="error-text">计划格式错误，请拒绝或终止，不会自动执行。</p>'; }
  }
  if (!Array.isArray(plan) || plan.some((item) => !item || typeof item !== "object" || Array.isArray(item))) return '<p class="error-text">计划结构无效，请拒绝或终止。</p>';
  return plan.map((step, i) => `<article class="record-detail"><h4>步骤 ${i + 1} · ${esc(c.agents.find((a) => a.id === step.assignee)?.data.title || step.assignee)}</h4><p class="preserve-lines">${esc(step.input)}</p><p>预期：${esc(step.expected)}</p></article>`).join("");
}
function resultView() {
  if (!c.run) return '<p>尚无本Supervisor的协作记录。</p>';
  const run = c.run, d = run.data, s = d.shared_state, child = run.pending_child_run;
  const finished = ["completed", "fallback", "failed"].includes(d.status);
  return `<section data-collab-result><h3>${names[d.status] || esc(d.status)}</h3><p>运行 v${run.version}；阶段 ${esc(s.phase)}；模型尝试 ${s.budget.model_used}/${s.budget.model_limit}；工具尝试 ${s.budget.tool_used}/${s.budget.tool_limit}。未知token/费用不算零。</p>
    ${planView(run)}<p>计划批准不等于Worker写操作批准；三方结果和提示都不能改变权限。</p>
    ${d.status === "awaiting_confirmation" && !child ? `<button type="button" data-collab-action="approve">${d.mode === "manual" ? "确认人工计划（不派发）" : "批准计划并继续协作（可能计费）"}</button> <button type="button" data-collab-action="reject">拒绝计划</button>` : ""}
    ${d.status === "confirmed" ? `<p>人工计划仅被确认，尚未调用Worker。</p><button type="button" data-collab-action="execute" ${!c.status.enabled || !c.configured ? "disabled" : ""}>执行已确认计划（可能计费）</button>` : ""}
    ${child ? `<h4>Worker写操作等待单独确认</h4><p>${esc(child.data.title)} · v${child.version}</p><pre>${esc(JSON.stringify(child.data.pending_calls || [], null, 2))}</pre><button type="button" data-collab-action="approve-child">批准当前Worker操作</button> <button type="button" data-collab-action="reject-child">拒绝当前Worker操作</button>` : ""}
    ${!finished ? '<button type="button" data-collab-action="abort">核对后终止，不重试</button>' : ""}
    <h4>实际黑板产物</h4>${s.board.map((item) => `<article class="record-detail"><p>步骤 ${item.step + 1} · ${esc(item.status)} · 子运行 ${esc(item.child_id)}</p><div class="preserve-lines">${esc(item.content)}</div></article>`).join("") || '<p>还没有已取得的Worker产物。</p>'}
    ${(d.result.notes || []).map((note) => `<p class="error-text">${esc(note)}</p>`).join("")}
    <div class="preserve-lines">${esc(d.result.answer || "尚未生成汇总")}</div>
    <details><summary>权限快照、派发与预算审计</summary><pre>${esc(JSON.stringify({ directory: s.directory, sources: s.sources, dispatches: s.dispatches, budget: s.budget, trace: d.trace }, null, 2))}</pre></details></section>`;
}
export function collaborationView() {
  if (!c.loaded && !c.loading) { c.loading = true; queueMicrotask(load); }
  if (c.loading) return '<section class="module-surface collaboration-page"><p>正在读取协作计划…</p></section>';
  if (c.error) return `<section class="module-surface collaboration-page"><p class="error-text" role="alert">${esc(c.error)}</p><button data-collab-action="refresh">重读协作记录</button></section>`;
  const a = owner(), allowed = peers();
  return `<section class="module-surface collaboration-page" data-owner="${esc(c.selected)}"><div class="module-toolbar"><p>实验性Worker-as-Tool，顺序执行，不是DAG引擎。</p><button type="button" data-collab-action="refresh" ${c.busy ? "disabled" : ""}>刷新协作记录</button></div>
    <p>${c.status.enabled ? "管理员已启用模型协作。每次仍需人工确认，可能计费。" : "模型协作默认关闭；人工计划预览与确认不调用模型。"} 模拟回归不代表真实收益，不建议仅因角色更多就启用。</p>
    <p>协作及子运行不进入公共备份；数据库记录未做应用层加密。失联请先查记录，勿重复生成计划；终止不能撤回已发出的外部操作。</p>
    <label class="form-field">Supervisor<select data-collab-owner aria-label="Supervisor">${c.agents.map((item) => `<option value="${esc(item.id)}" ${item.id === c.selected ? "selected" : ""}>${esc(item.data.title)}</option>`).join("")}</select></label>
    ${!a ? '<p>先在Agent设置创建独立的Supervisor和Worker配置。</p><a href="#module/agents">前往Agent设置</a>' : `
    <form data-collab-form="members"><h3>交接白名单（Supervisor v${a.version}）</h3>${c.agents.filter((item) => item.id !== a.id).map((item) => `<label class="form-field"><span><input type="checkbox" name="worker" value="${esc(item.id)}" ${a.data.handoffs?.allowed?.includes(item.id) ? "checked" : ""}>${esc(item.data.title)} · v${item.version}</span><small>范围 ${esc(item.data.scopes.join("/"))}；记忆 ${esc(item.data.memory?.scope || "none")}；工具 ${esc((item.data.tool_ids || []).join(",") || "无")}；生成 ${item.data.generate ? "开启" : "关闭"}</small></label>`).join("")}
      <button type="submit">保存交接白名单</button><p class="collab-error error-text" role="alert"></p></form>
    <form data-collab-form="plan"><h3>人工协作计划（零模型调用）</h3><label class="form-field">协作任务<textarea name="query" rows="3" required maxlength="4000">${esc(c.draft.query)}</textarea></label>
      ${c.draft.steps.map((step, i) => `<fieldset><legend>步骤 ${i + 1}</legend><label class="form-field">Worker<select name="assignee-${i}" aria-label="步骤 ${i + 1} Worker">${allowed.map((peer) => `<option value="${esc(peer.id)}" ${peer.id === step.assignee ? "selected" : ""}>${esc(peer.data.title)}</option>`).join("")}</select></label><label class="form-field">Worker输入<textarea name="input-${i}" rows="2" required maxlength="4000">${esc(step.input)}</textarea></label><label class="form-field">预期产物<input name="expected-${i}" required maxlength="1000" value="${esc(step.expected)}"></label><button type="button" data-collab-action="remove-step" data-index="${i}">移除此步骤</button></fieldset>`).join("")}
      <button type="button" data-collab-action="add-step" ${!allowed.length || c.draft.steps.length >= c.status.max_plan_steps ? "disabled" : ""}>添加步骤</button> <button type="submit" ${!allowed.length || !c.draft.steps.length ? "disabled" : ""}>创建人工计划（不执行）</button><p class="collab-error error-text" role="alert"></p></form>
    <button type="button" data-collab-action="auto-plan" ${!c.status.enabled || !c.configured || !a.data.generate || !allowed.length ? "disabled" : ""}>让Supervisor生成新计划（可能计费）</button>
    <p>实际执行前，所有参与Agent必须已开启生成且版本未变。默认共享总调用额度较小，预算不足会停止，不冒称完成。</p>
    <label class="form-field">选择协作记录<select data-collab-run aria-label="选择协作记录">${c.runs.map((item) => `<option value="${esc(item.id)}" ${item.id === c.run?.id ? "selected" : ""}>${esc(item.data.title)} · ${esc(item.data.status)} · ${esc(item.data.started_at)}</option>`).join("")}</select></label>${resultView()}`}</section>`;
}
export function bindCollaboration({ renderPage, toast }) {
  paint = () => { if (location.hash === "#module/collaboration") renderPage(); };
  document.addEventListener("input", (event) => {
    if (!event.target.closest('[data-collab-form="plan"]')) return;
    const form = event.target.form, fd = new FormData(form); c.draft.query = fd.get("query");
    c.draft.steps.forEach((step, i) => { step.assignee = fd.get(`assignee-${i}`); step.input = fd.get(`input-${i}`); step.expected = fd.get(`expected-${i}`); });
  });
  document.addEventListener("change", async (event) => {
    try {
      if (event.target.matches("[data-collab-owner]") && event.target.value !== c.selected) { c.selected = event.target.value; c.run = null; c.draft = { query: "", steps: [] }; await load(); }
      if (event.target.matches("[data-collab-run]")) { c.run = await api(route(event.target.value)); paint(); }
    } catch (error) { toast(error.message, true); }
  });
  document.addEventListener("submit", async (event) => {
    const form = event.target; if (!form.matches("[data-collab-form]")) return;
    event.preventDefault(); if (c.busy) return; c.busy = true;
    const b = form.querySelector('[type="submit"]'); b.disabled = true;
    try {
      const fd = new FormData(form), a = owner();
      if (form.dataset.collabForm === "members") {
        await api(`agents/${encodeURIComponent(a.id)}`, { version: a.version, data: { handoffs: { allowed: fd.getAll("worker") } } }, "PUT");
        c.draft.steps = [];
      } else {
        const plan = c.draft.steps.map((_, i) => ({ step: i, assignee: fd.get(`assignee-${i}`), input: fd.get(`input-${i}`), expected: fd.get(`expected-${i}`) }));
        c.run = await api("collaborations", { agent_id: a.id, version: a.version, query: fd.get("query"), plan, confirmation: "仅创建人工计划" });
      }
      await load(); toast("已保存；未因此批准Worker写操作");
    } catch (error) { form.querySelector(".collab-error").textContent = error.message + (error.status === 409 ? "；输入保留，请核对版本。" : ""); }
    finally { release(b); }
  });
  document.addEventListener("click", async (event) => {
    const b = event.target.closest("[data-collab-action]"); if (!b || c.busy) return;
    const action = b.dataset.collabAction;
    if (action === "add-step") { c.draft.steps.push({ assignee: peers()[0]?.id, input: "", expected: "" }); paint(); return; }
    if (action === "remove-step") { c.draft.steps.splice(Number(b.dataset.index), 1); paint(); return; }
    c.busy = true; b.disabled = true;
    try {
      const run = c.run, a = owner();
      if (action === "auto-plan") {
        if (!c.draft.query.trim()) throw new Error("先输入协作任务");
        if (!window.confirm("生成新计划会调用模型并可能计费；确认前不会派发Worker。失联先查记录，不自动重试。")) return;
        c.run = await api("collaborations", { agent_id: a.id, version: a.version, query: c.draft.query, confirmation: "生成协作计划（可能计费）" });
      }
      if (["approve", "reject"].includes(action)) {
        const approve = action === "approve";
        if (!window.confirm(approve ? "已逐条核对Worker、权限和输入；批准计划不等于批准Worker写操作。" : "拒绝此计划，不派发Worker？")) return;
        c.run = await api(route(run.id) + "/confirm", { version: run.version, approve, confirmation: approve ? "批准计划，不批准Worker写操作" : "拒绝计划" });
      }
      if (action === "execute") {
        if (!window.confirm("按已确认计划调用模型，可能计费。任何Worker写操作仍会暂停。")) return;
        c.run = await api(route(run.id) + "/execute", { version: run.version, confirmation: "执行协作计划（可能计费）" });
      }
      if (["approve-child", "reject-child"].includes(action)) {
        const approve = action === "approve-child";
        if (!window.confirm("已核对当前Worker的具体工具与参数？这不是计划审批。")) return;
        c.run = await api(route(run.id) + "/child-confirm", { version: run.version, child_version: run.pending_child_run.version, approve, confirmation: approve ? "批准当前Worker操作" : "拒绝当前Worker操作" });
      }
      if (action === "abort") {
        if (!window.confirm("已核对在途请求，终止协作且不重试？已经发出的请求不能撤回。")) return;
        c.run = await api(route(run.id) + "/abort", { version: run.version, confirmation: "已核对在途请求，终止协作且不重试" });
      }
      await load();
    } catch (error) { toast(error.message, true); }
    finally { release(b); }
  });
}
