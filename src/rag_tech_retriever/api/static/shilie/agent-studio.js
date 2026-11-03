/* Explicit memory decisions and versioned sessions. Business data is never localStorage. */
import { api, escapeHtml as esc } from "./data.js?v=106";

const cache = { loaded: false, loading: false, busy: false, agents: [], memories: [], runs: [], selected: "", run: null, configured: false, error: "", caps: null, skills: [], servers: [], toolCatalog: null };
let generation = 0;
let paint = () => {};
function release(button) {
  cache.busy = false;
  if (button?.isConnected) button.disabled = false;
  const refresh = document.querySelector('.agent-studio [data-studio-action="refresh"]');
  if (refresh) refresh.disabled = cache.loading;
}
const owner = () => cache.agents.find((a) => a.id === cache.selected);
const input = (label, name, value = "", attrs = 'type="number" min="1"') => `<label class="form-field">${label}<input name="${name}" value="${esc(value ?? "")}" ${attrs}></label>`;
const stateNames = { pending: "待确认", confirmed: "已生效", rejected: "已拒绝", forgotten: "已遗忘" };

function capabilityBinding(d) {
  const catalog = cache.toolCatalog || {
    builtin: cache.caps?.builtin_tools || [], http: cache.caps?.http_tools || [], mcp: [],
  };
  const tools = new Set(d.tool_ids || []), skills = new Set(d.skill_ids || []), servers = new Set(d.mcp_server_ids || []);
  const web = cache.caps?.web_search;
  const box = (name, value, label, checked, disabled = false) =>
    `<label class="scope-checkboxes"><input type="checkbox" name="${name}" value="${esc(value)}" ${checked ? "checked" : ""} ${disabled ? "disabled" : ""}>${esc(label)}</label>`;
  return `<form data-studio-form="tools"><h3>能力绑定</h3>
    <p>联网搜索：${web?.enabled ? esc(web.provider) + (web.configured ? " 已配置" : " 未配置") : "未启用"}。工具权限只来自这里，模型和技能不能自行扩权。</p>
    <fieldset class="scope-checkboxes"><legend>内置工具</legend>${catalog.builtin.map((tool) => box("tool_ids", tool.name, `${tool.name} · ${tool.description}`, tools.has(tool.name))).join("")}</fieldset>
    ${catalog.http.length ? `<fieldset class="scope-checkboxes"><legend>管理员 HTTP 工具</legend>${catalog.http.map((tool) => box("tool_ids", tool.name, `${tool.name} · ${tool.description}`, tools.has(tool.name))).join("")}</fieldset>` : ""}
    ${catalog.mcp.length ? `<fieldset class="scope-checkboxes"><legend>MCP 工具（勾选即同时授权所属服务）</legend>${catalog.mcp.map((tool) => box("tool_ids", tool.name, `${tool.name} · ${tool.description}`, tools.has(tool.name))).join("")}</fieldset>` : ""}
    ${cache.servers.length ? `<fieldset class="scope-checkboxes"><legend>MCP 服务</legend>${cache.servers.map((server) => box("mcp_server_ids", server.id, `${server.id} · ${server.enabled && server.trusted ? "已信任" : "未启用/未信任"}`, servers.has(server.id))).join("")}</fieldset>` : ""}
    ${cache.skills.length ? `<fieldset class="scope-checkboxes"><legend>技能</legend>${cache.skills.map((skill) => box("skill_ids", skill.name, `${skill.name} · ${skill.description}`, skills.has(skill.name))).join("")}</fieldset>` : "<p>还没有技能；可在工作台技能目录中导入 SKILL.md。</p>"}
    <button type="submit">保存能力绑定</button><p class="studio-error error-text" role="alert"></p></form>`;
}

async function load() {
  const ticket = ++generation;
  cache.loading = true;
  paint();
  try {
    const agents = await api("agents");
    const selected = agents.some((a) => a.id === cache.selected) ? cache.selected : agents[0]?.id || "";
    const cfg = await api("model-connection");
    const [caps, skills, servers, toolCatalog] = await Promise.all([
      api("capabilities"), api("skills"), api("mcp/servers"), api("capabilities/tools").catch(() => null),
    ]);
    const memories = selected ? await api(`agents/${encodeURIComponent(selected)}/memory`) : [];
    const runs = (await api("agent-runs")).filter((r) => r.data.workflow_id === `agent:${selected}`);
    const id = runs.find((r) => r.id === cache.run?.id)?.id || runs[0]?.id;
    const run = id ? await api(`agent-runs/${encodeURIComponent(id)}`) : null;
    if (ticket !== generation) return;
    Object.assign(cache, { agents, selected, memories, runs, run, configured: cfg.configured,
      caps, skills, servers, toolCatalog, error: "" });
  } catch (error) { if (ticket === generation) cache.error = error.message; }
  finally { if (ticket === generation) { cache.loaded = true; cache.loading = false; paint(); } }
}

function runView() {
  const run = cache.run; if (!run) return '<p>尚无此 Agent 的工具型运行。</p>';
  const data = run.data;
  const canContinue = run.kind === "agent_session" && !data.closed && data.mode === "model" && ["completed", "fallback"].includes(data.status);
  return `<h3>运行详情：${esc(data.status)}</h3><p>配置版本 ${esc(data.agent?.version)}；累计模型调用 ${esc(data.model_steps)}；工具调用 ${esc(data.calls_used)}；会话轮次 ${esc(data.turns || 1)}</p>
    <p>意图提示 ${esc(data.intent?.intent || "unknown")}，不构成授权。${data.closed ? "此会话已结束，不再续聊。" : ""}</p>
    ${run.kind === "agent_session" && !data.closed && ["completed", "fallback", "failed"].includes(data.status) ? '<button type="button" data-studio-action="close-session">结束会话（不再续聊）</button>' : ""}
    <div class="preserve-lines">${esc(data.result?.answer || "没有生成回答")}</div>
    ${(data.result?.notes || []).map((note) => `<p class="error-text">${esc(note)}</p>`).join("")}
    <details><summary>输入与回答记录</summary>${(data.messages || []).filter((m) => m.role === "user" || (m.role === "assistant" && !m.tool_calls)).map((m) => `<p><strong>${esc(m.role)}</strong></p><div class="preserve-lines">${esc(m.content || "")}</div>`).join("")}</details>
    <details><summary>工具步骤与模型追踪</summary>${(data.steps || []).map((s) => `<p>${esc(s.title)} · ${esc(s.status)} · ${esc(s.duration_ms)} ms</p>`).join("")}<pre class="preserve-lines">${esc(JSON.stringify(data.trace || [], null, 2))}</pre></details>
    ${data.status === "awaiting_confirmation" ? `<h4>待确认工具（每次只批准第一项）</h4><pre class="preserve-lines">${esc(JSON.stringify(data.pending_calls || [], null, 2))}</pre><button type="button" data-studio-action="approve">批准当前操作</button> <button type="button" data-studio-action="reject-run">拒绝当前操作</button>` : ""}
    ${canContinue ? `<form data-studio-form="continue">${input("继续提问", "query", "", 'required maxlength="4000" type="text"')}<p>会复用服务器历史和累计预算；不会自动重试失败运行。</p><button type="submit" ${!cache.configured ? "disabled" : ""}>继续此会话（调用模型）</button><p class="studio-error error-text" role="alert"></p></form>` : '<p>此运行不可续聊；待确认先处理，失败不自动重试，手动试运行不调用模型。</p>'}`;
}

export function agentStudioView() {
  if (!cache.loaded && !cache.loading) { cache.loading = true; queueMicrotask(load); }
  if (cache.loading) return '<section class="module-surface agent-studio" aria-busy="true"><p>正在读取 Agent 工作室，请稍候…</p></section>';
  if (cache.error) return `<section class="module-surface agent-studio"><p class="error-text" role="alert">${esc(cache.error)}</p><button type="button" data-studio-action="refresh">重新读取工作室</button></section>`;
  const a = owner(), d = a?.data;
  return `<section class="module-surface agent-studio" data-owner="${esc(cache.selected)}"><div class="module-toolbar"><p>配置预算、审阅长期记忆、查看工具运行和会话追踪。</p><button data-studio-action="refresh" type="button" ${cache.loading || cache.busy ? "disabled" : ""}>刷新 Agent 工作室</button></div>
    ${cache.error ? `<p class="error-text" role="alert">${esc(cache.error)}</p>` : ""}
    <label class="form-field">选择 Agent<select data-studio-owner aria-label="选择 Agent">${cache.agents.map((item) => `<option value="${esc(item.id)}" ${item.id === cache.selected ? "selected" : ""}>${esc(item.data.title)}</option>`).join("")}</select></label>
    ${!a ? '<p>先到 Agent 设置新建一个助手。</p><a href="#module/agents">前往 Agent 设置</a>' : `
    <form data-studio-form="config"><h3>模型、预算与记忆</h3><p>配置版本 ${a.version}。空值继承管理员限制，不能提高全局上限；模型与预算也用于固定检索工作流；固定流程每次独立运行，不跨运行续聊。</p>
      ${input("模型别名（管理员登记）", "alias", d.model?.alias || "", 'type="text" maxlength="64"')}
      ${input("温度（可空）", "temperature", d.model?.temperature, 'type="number" min="0" max="2" step="0.1"')}
      ${input("最大输出 token（可空）", "max_tokens", d.model?.max_tokens)}
      ${input("累计模型轮数（可空）", "max_rounds", d.budget?.max_rounds)}
      ${input("累计工具次数（可空）", "max_tool_calls", d.budget?.max_tool_calls)}
      ${input("请求字符上限（可空）", "max_context_chars", d.budget?.max_context_chars)}
      ${input("上下文消息上限", "max_messages", d.context?.max_messages || 20, 'type="number" required min="2" max="1000"')}
      <label class="form-field">上下文策略<select name="context_strategy" aria-label="上下文策略"><option value="window" ${(d.context?.strategy || "window") === "window" ? "selected" : ""}>完整工具轮窗口</option><option value="verbatim_window" ${d.context?.strategy === "verbatim_window" ? "selected" : ""}>逐字折叠旧用户消息</option></select></label>
      ${input("逐字保留最近用户消息数", "keep_recent_users", d.context?.keep_recent_users || 2, 'type="number" required min="1" max="20"')}
      <p>逐字折叠保留用户原文、减少消息数，不是语义摘要；旧回答/工具结果可能被移除，依赖旧回答时会提示重述。仍超字符预算就停止，不自动额外付费。</p>
      <label class="form-field">记忆范围<select name="scope" aria-label="记忆范围">${[["none", "不复用记忆（默认）"], ["session", "仅此会话"], ["persistent", "此会话＋已确认长期记忆"]].map(([v, label]) => `<option value="${v}" ${v === (d.memory?.scope || "none") ? "selected" : ""}>${label}</option>`).join("")}</select></label>
      <p>会话与长期记忆保存在服务器数据库，未做应用层加密；不进入公共工作区备份。不要填写密码、令牌或私密日记，需由数据库备份保护。</p><button type="submit">保存可靠性设置</button><p class="studio-error error-text" role="alert"></p></form>
    ${capabilityBinding(d)}
    <h3>长期记忆候选与决定</h3><p>新候选不会自动生效。确认后仅供本 Agent 参考，不改变工具权限。遗忘停止未来使用，但审计正文不物理擦除；记忆改变后须新建会话。</p>
    <form data-studio-form="memory"><label class="form-field">拟记住的内容<textarea name="content" required maxlength="2000" rows="3"></textarea></label><button type="submit" ${d.memory?.scope !== "persistent" ? "disabled" : ""}>提出记忆候选（未生效）</button><p class="studio-error error-text" role="alert"></p></form>
    <div data-studio-memory>${cache.memories.map((m) => `<article class="record-detail"><p><strong>${stateNames[m.data.state] || esc(m.data.state)}</strong> · v${m.version}</p><div class="preserve-lines">${esc(m.data.content)}</div>${m.data.state === "pending" ? `<button type="button" data-studio-action="confirm" data-id="${esc(m.id)}" ${d.memory?.scope !== "persistent" ? "disabled" : ""}>确认保存长期记忆</button> <button type="button" data-studio-action="reject" data-id="${esc(m.id)}">拒绝记忆</button>` : m.data.state === "confirmed" ? `<button type="button" data-studio-action="forget" data-id="${esc(m.id)}">确认遗忘</button>` : ""}</article>`).join("") || '<p>没有记忆条目。</p>'}</div>
    <h3>工具型运行与会话</h3><p>${cache.configured ? "已配置模型。主动提交会调用供应商并可能计费。" : "模型未配置；不会发起模型请求。可使用获准的只读草稿试运行。"}</p>
    <form data-studio-form="start">${input("新运行的问题", "query", "", 'type="text" required maxlength="4000"')}<button type="submit" ${!cache.configured || !d.generate ? "disabled" : ""}>开始新运行（调用模型）</button><p class="studio-error error-text" role="alert"></p></form>
    ${d.tool_ids?.includes("knowledge_draft") ? '<button type="button" data-studio-action="manual">只读草稿试运行（不调用模型）</button>' : ""}
    <label class="form-field">选择运行<select data-studio-run aria-label="选择运行">${cache.runs.map((r) => `<option value="${esc(r.id)}" ${r.id === cache.run?.id ? "selected" : ""}>${esc(r.data.title)} · ${esc(r.data.status)} · ${esc(r.data.started_at)}</option>`).join("")}</select></label>${runView()}`}
    </section>`;
}

export function bindAgentStudio({ renderPage, toast }) {
  paint = () => { if (location.hash === "#module/agent-studio") renderPage(); };
  document.addEventListener("change", async (event) => {
    try {
      if (event.target.matches("[data-studio-owner]") && event.target.value !== cache.selected) { cache.selected = event.target.value; cache.run = null; await load(); }
      if (event.target.matches("[data-studio-run]")) { cache.run = await api(`agent-runs/${encodeURIComponent(event.target.value)}`); paint(); }
    } catch (error) { toast(error.message, true); }
  });
  document.addEventListener("submit", async (event) => {
    const form = event.target; if (!form.matches("[data-studio-form]")) return;
    event.preventDefault(); if (cache.busy) return;
    cache.busy = true; const button = form.querySelector('[type="submit"]'); button.disabled = true;
    const fd = new FormData(form), a = owner(), kind = form.dataset.studioForm, errorBox = form.querySelector(".studio-error");
    const number = (name) => fd.get(name) === "" ? null : Number(fd.get(name));
    try {
      if (kind === "config") await api(`agents/${encodeURIComponent(a.id)}`, { version: a.version, data: {
        model: { alias: fd.get("alias"), temperature: number("temperature"), max_tokens: number("max_tokens") },
        budget: { max_rounds: number("max_rounds"), max_tool_calls: number("max_tool_calls"), max_context_chars: number("max_context_chars") },
        context: { strategy: fd.get("context_strategy"), max_messages: number("max_messages"), keep_recent_users: number("keep_recent_users") }, memory: { scope: fd.get("scope") } } }, "PUT");
      if (kind === "tools") {
        const toolIds = fd.getAll("tool_ids"), serverIds = new Set(fd.getAll("mcp_server_ids"));
        for (const name of toolIds) {
          const tool = (cache.toolCatalog?.mcp || []).find((item) => item.name === name);
          if (tool) serverIds.add(tool.server_id);
        }
        await api(`agents/${encodeURIComponent(a.id)}`, { version: a.version, data: {
          tool_ids: toolIds, skill_ids: fd.getAll("skill_ids"), mcp_server_ids: [...serverIds] } }, "PUT");
      }
      if (kind === "memory") await api(`agents/${encodeURIComponent(a.id)}/memory`, { agent_version: a.version, content: fd.get("content"), request_id: form.dataset.requestId ||= crypto.randomUUID() });
      if (kind === "start") cache.run = await api(`agents/${encodeURIComponent(a.id)}/run`, { version: a.version, query: fd.get("query") });
      if (kind === "continue") cache.run = await api(`agent-runs/${encodeURIComponent(cache.run.id)}/continue`, { version: cache.run.version, query: fd.get("query") });
      toast(kind === "memory" ? "候选已保存，尚未生效，请逐条确认" : "已保存结果"); await load();
    } catch (error) { errorBox.textContent = error.message + (error.status === 409 ? "；输入已保留，请刷新并核对版本。" : ""); }
    finally { release(button); }
  });
  document.addEventListener("click", async (event) => {
    const b = event.target.closest("[data-studio-action]"); if (!b || cache.busy) return;
    cache.busy = true; b.disabled = true;
    try {
      const action = b.dataset.studioAction, a = owner();
      if (action === "manual") cache.run = await api(`agents/${encodeURIComponent(a.id)}/tools/call`, { version: a.version, name: "knowledge_draft", arguments: { title: "只读试运行", content: "仅生成草稿，不自动保存知识，不调用模型。" } });
      if (action === "close-session") cache.run = await api(`agent-runs/${encodeURIComponent(cache.run.id)}/close`, { version: cache.run.version });
      if (["confirm", "reject", "forget"].includes(action)) {
        const item = cache.memories.find((m) => m.id === b.dataset.id);
        const words = { confirm: "确认保存长期记忆", reject: "拒绝记忆", forget: "确认遗忘" };
        if (!window.confirm(`${words[action]}？\n${item.data.content}\n此决定不会调用模型。`)) return;
        await api(`agents/${encodeURIComponent(a.id)}/memory/${encodeURIComponent(item.id)}/decide`, { version: item.version, agent_version: a.version, action, confirmation: words[action] });
      }
      if (["approve", "reject-run"].includes(action)) {
        if (!window.confirm(action === "approve" ? "已核对当前工具及参数，批准第一项操作？" : "拒绝待确认操作？")) return;
        cache.run = await api(`agent-runs/${encodeURIComponent(cache.run.id)}/confirm`, { version: cache.run.version, approve: action === "approve" });
      }
      await load();
    } catch (error) { toast(error.message, true); }
    finally { release(b); }
  });
}
