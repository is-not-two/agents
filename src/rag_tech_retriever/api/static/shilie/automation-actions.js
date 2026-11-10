/* 配置与执行控制器；请求锁、输入草稿和运行状态独立于视图。 */
import { api, state, write, escapeHtml as esc } from "./data.js?v=130";
import { flow, LOOP_TIMEOUT_MS } from "./automation-views.js?v=130";
export function bindAutomation({ renderPage, refresh, toast }) {
  const dialog = (kind) => document.querySelector(`[data-auto-form="${kind}"]`);
  function openEditor(kind, row = null) {
    const d = dialog(kind),
      f = d.querySelector("form");
    f.reset();
    d.dataset.recordId = row?.id || "";
    d.dataset.version = row?.version || "";
    f.querySelector(".auto-form-error").hidden = true;
    if (kind === "workflow") {
      const select = f.elements.agent_id;
      select.replaceChildren(
        ...state.agents.map((a) => {
          const o = document.createElement("option");
          o.value = a.id;
          o.textContent = a.data.title;
          return o;
        }),
      );
      if (!select.options.length) {
        const o = document.createElement("option");
        o.value = "";
        o.textContent = "请先创建 Agent，或选择资料入库流程";
        select.append(o);
      }
    }
    const values =
      row?.data ||
      (kind === "agent"
        ? {
            title: "知识检索助手",
            system_prompt: "回答附带编号引用，没有依据时说明缺口。",
            scopes: ["personal", "docs", "planning"],
            mode: "text",
            result_limit: 5,
            generate: false,
            workspace: { root: "", write: "each", shell: false },
          }
        : {
            title: "新的检索流程",
            kind: "answer",
            agent_id: state.agents[0]?.id || "",
            chunk_size: 1500,
          });
    for (const [key, value] of Object.entries(values)) {
      if (key === "scopes") {
        f.querySelectorAll("[name=scopes]").forEach(
          (input) => (input.checked = value.includes(input.value)),
        );
        continue;
      }
      const input = f.elements.namedItem(key);
      if (!input) continue;
      if (input.type === "checkbox") input.checked = value;
      else input.value = value;
    }
    if (kind === "workflow") toggleKind(f);
    if (kind === "agent") {
      const ws = values.workspace || { root: "", write: "each", shell: false };
      /* 工作区是嵌套对象，不能走上面的平铺赋值。 */
      if (f.elements.workspace_root) f.elements.workspace_root.value = ws.root || "";
      if (f.elements.workspace_write) f.elements.workspace_write.value = ws.write || "each";
      if (f.elements.workspace_shell) f.elements.workspace_shell.checked = Boolean(ws.shell);
    }
    if (kind === "workflow" && values.kind === "graph") {
      f.elements.graph_json.value = JSON.stringify({
        agent_id: values.agent_id || "", nodes: values.nodes || [], edges: values.edges || [],
        max_parallel: values.max_parallel || 1, max_retries: values.max_retries ?? 1,
        node_timeout_seconds: values.node_timeout_seconds || 60,
      }, null, 2);
    }
    if (kind === "workflow" && values.kind === "graph") renderGraphRows(f);
    d.showModal();
    f.elements.title.focus();
  }
  const NODE_TYPES = ["input", "retrieve", "tool", "agent", "approval", "merge"];
  const graphRows = (form) => [...form.querySelectorAll("[data-graph-row]")];
  /* 一个节点可以有多个上游（并行汇合）；每行渲染 n 个上游选择器。 */
  const upstreamSelect = (ids, selected) =>
    `<select aria-label="上游节点" data-graph-upstream><option value="">无（起点）</option>${ids
      .map((id) => `<option value="${esc(id)}" ${id === selected ? "selected" : ""}>${esc(id)}</option>`)
      .join("")}</select>`;
  function renderGraphRows(form) {
    const holder = form.querySelector("[data-graph-rows]");
    if (!holder) return;
    let parsed = {};
    try { parsed = JSON.parse(form.elements.graph_json.value || "{}"); } catch { parsed = {}; }
    const nodes = Array.isArray(parsed.nodes) ? parsed.nodes : [
      { id: "input", type: "input" }, { id: "merge", type: "merge" },
    ];
    const edges = Array.isArray(parsed.edges) ? parsed.edges : [["input", "merge"]];
    const upstreams = new Map();
    for (const [from, to] of edges) {
      if (!upstreams.has(to)) upstreams.set(to, []);
      upstreams.get(to).push(from);
    }
    const ids = nodes.map((n) => n.id);
    holder.innerHTML = nodes.map((node) => {
      const chosen = upstreams.get(node.id) || [];
      // 没有上游时留一个空选择器作为起点，其余按实际边数展开。
      const slots = chosen.length ? chosen : [""];
      return `<div class="graph-editor__row" data-graph-row><input aria-label="节点 ID" data-graph-id value="${esc(node.id || "")}" maxlength="41"><select aria-label="节点类型" data-graph-type>${NODE_TYPES.map((t) => `<option value="${t}" ${t === node.type ? "selected" : ""}>${t}</option>`).join("")}</select><input aria-label="指令或查询" data-graph-query value="${esc(node.query || "")}" maxlength="1000" placeholder="query">${slots.map((from) => upstreamSelect(ids, from)).join("")}<button type="button" class="small-button" data-action="auto-graph-add-upstream" title="增加一个上游节点，用于并行汇合">+ 上游</button><button type="button" class="small-button" data-action="auto-graph-remove">删除</button></div>`;
    }).join("");
  }
  function syncGraphToJson(form) {
    const nodes = graphRows(form).map((row) => {
      const type = row.querySelector("[data-graph-type]").value;
      const query = row.querySelector("[data-graph-query]").value.trim();
      const node = { id: row.querySelector("[data-graph-id]").value.trim(), type };
      if (query && ["agent", "retrieve"].includes(type)) node.query = query;
      if (type === "merge") node.strategy = "concat";
      if (type === "approval") node.message = "请确认继续执行";
      if (type === "tool") node.tool_id = query;
      return node;
    });
    const seen = new Set();
    const edges = [];
    for (const row of graphRows(form)) {
      const to = row.querySelector("[data-graph-id]").value.trim();
      if (!to) continue;
      for (const select of row.querySelectorAll("[data-graph-upstream]")) {
        const from = select.value;
        if (!from || from === to) continue;
        const key = `${from}->${to}`;
        if (seen.has(key)) continue;
        seen.add(key);
        edges.push([from, to]);
      }
    }
    form.elements.graph_json.value = JSON.stringify({
      agent_id: "", nodes, edges, max_parallel: 1, max_retries: 1, node_timeout_seconds: 60,
    }, null, 2);
  }
  async function composeWorkflow(form) {
    if (state.autoBusy) return;
    const fd = new FormData(form);
    state.autoBusy = true;
    state.autoError = "";
    renderPage({ restore: true });
    try {
      const composed = await api("automation/compose", {
        goal: fd.get("goal"), mode: fd.get("mode"), template: fd.get("template"),
        confirmation: "生成工作流并直接运行",
      });
      await refresh();
      state.selectedFlow = composed.workflow_id;
      write("flow", composed.workflow_id);
      state.currentRun = await api(`workflows/${composed.workflow_id}/run`, {
        version: composed.version, input: { query: fd.get("goal") },
      });
      await refresh();
      toast(composed.mode === "model" ? "模型已生成并启动工作流" : "规则模式已生成并启动工作流");
    } catch (e) {
      state.autoError = e.message;
      toast(e.message, true);
    } finally {
      state.autoBusy = false;
      renderPage({ restore: true });
    }
  }
  async function draftWorkflow(form) {
    if (state.autoBusy) return;
    const fd = new FormData(form);
    state.autoBusy = true;
    state.autoError = "";
    renderPage({ restore: true });
    try {
      state.composeDraft = await api("automation/compose/draft", {
        goal: fd.get("goal"), mode: fd.get("mode"), template: fd.get("template"),
      });
      state.composeChanges = null;
      state.composeFeedback = "";
      toast("草稿已生成，先看结构再决定保存");
    } catch (e) {
      state.autoError = e.message;
      toast(e.message, true);
    } finally {
      state.autoBusy = false;
      renderPage({ restore: true });
    }
  }
  async function runTeam(form) {
    if (state.teamBusy) return;
    const data = new FormData(form);
    const agentIds = data.getAll("agent_ids");
    if (!agentIds.length) {
      toast("至少选一个成员", true);
      return;
    }
    state.teamBusy = true;
    renderPage({ restore: true });
    try {
      const result = await api("automation/teams/run", {
        agent_ids: agentIds,
        task: data.get("task"),
        mode: data.get("mode"),
        max_rounds: Number(data.get("max_rounds")),
        approved: data.has("approved"),
      });
      state.teamResult = result;
      toast(`团队完成：${result.turns.length} 段发言，${result.model_calls} 次模型调用`);
      await refresh();
    } catch (e) {
      toast(e.message, true);
    } finally {
      state.teamBusy = false;
      renderPage({ restore: true });
    }
  }
  async function runLoop(form) {
    if (state.loopBusy) return;
    const data = new FormData(form);
    const root = String(data.get("root") || "").trim();
    const task = String(data.get("task") || "").trim();
    const gate = String(data.get("gate") || "").trim();
    const engine = String(data.get("engine") || "opencode");
    const tier = String(data.get("tier") || "patch");
    /* 重绘会重建表单，输入留在 state 里回填。 */
    state.loopInput = { root, task, gate, engine, tier };
    if (!root || !task || !gate) {
      toast("代码仓库、改动目标和门禁命令都要填", true);
      return;
    }
    state.loopBusy = true;
    renderPage({ restore: true });
    try {
      /* 默认是 30 秒，loop 是同步长任务，必须按档位放宽。 */
      const result = await api(
        "automation/loop/run",
        { root, task, gate, engine, tier },
        "POST",
        LOOP_TIMEOUT_MS[tier] || LOOP_TIMEOUT_MS.patch,
      );
      state.loopResult = result;
      toast(result.status === "success"
        ? `自动编码通过：${result.rounds} 轮，${result.duration_ms} ms`
        : `自动编码结束（${result.status}）：${result.reason || "未通过门禁"}`);
      await refresh();
    } catch (e) {
      /* 页面停止等待不代表服务端失败，运行记录里仍会有结果。 */
      toast(e.code === "TIMEOUT"
        ? "页面已停止等待；服务端可能仍在运行，请到「运行记录」查看结果"
        : e.message, true);
    } finally {
      state.loopBusy = false;
      renderPage({ restore: true });
    }
  }
  /* ---------- 任务队列 ---------- */
  async function loadQueueJobs(status) {
    const query = status ? `?status=${encodeURIComponent(status)}&limit=30` : "?limit=30";
    const [jobs, stats] = await Promise.all([
      api("automation/queue" + query),
      api("automation/queue/stats").catch(() => ({})),
    ]);
    state.queueJobs = jobs || [];
    state.queueStats = stats || {};
    state.queueError = "";
  }
  async function enqueueJob(form) {
    if (state.queueBusy) return;
    const data = new FormData(form);
    const kind = String(data.get("kind") || "loop");
    const task = String(data.get("task") || "").trim();
    const maxAttempts = Number(data.get("max_attempts") || 3);
    if (!task) {
      toast("任务目标要填", true);
      return;
    }
    /* 载荷字段与服务端 queue_worker 的执行器约定一致，不要各写一套。 */
    const payload = { task };
    if (kind === "loop") {
      const root = String(data.get("root") || "").trim();
      const gate = String(data.get("gate") || "").trim();
      if (!root || !gate) {
        toast("代码仓库与门禁命令都要填", true);
        return;
      }
      payload.root = root;
      payload.gate = gate;
      payload.engine = String(data.get("engine") || "opencode");
      payload.tier = String(data.get("tier") || "patch");
    } else {
      payload.agent_ids = state.agents.map((a) => a.id);
      payload.mode = "group_chat";
      payload.max_rounds = 6;
      payload.approved = false;
    }
    state.queueInput = { ...state.queueInput, kind, task, max_attempts: maxAttempts };
    state.queueBusy = true;
    renderPage({ restore: true });
    try {
      const job = await api("automation/queue", {
        kind,
        payload,
        max_attempts: maxAttempts,
        priority: 50,
      });
      toast(`已入队：${job.id.slice(0, 8)}`);
      await loadQueueJobs(state.queueFilter);
    } catch (e) {
      toast(e.message, true);
    } finally {
      state.queueBusy = false;
      renderPage({ restore: true });
    }
  }
  async function queueAction(action, id) {
    if (!id) return;
    try {
      if (action === "queue-detail") {
        state.queueDetail = await api("automation/queue/" + id);
      } else if (action === "queue-cancel") {
        await api("automation/queue/" + id + "/cancel", {});
        toast("已取消");
      } else if (action === "queue-replay") {
        await api("automation/queue/" + id + "/replay", {});
        toast("已重新入队");
      }
      await loadQueueJobs(state.queueFilter);
      renderPage({ restore: true });
    } catch (e) {
      toast(e.message, true);
    }
  }
  async function reviseDraft() {
    if (state.autoBusy || !state.composeDraft) return;
    const field = document.getElementById("compose-feedback");
    const feedback = (field?.value || state.composeFeedback || "").trim();
    if (!feedback) {
      toast("先写清要改什么", true);
      return;
    }
    state.composeFeedback = feedback;
    state.autoBusy = true;
    renderPage({ restore: true });
    try {
      const result = await api("automation/compose/revise", {
        draft: state.composeDraft, feedback,
      });
      state.composeDraft = result.draft;
      state.composeChanges = result.changes;
      toast("已按意见修订，下方是结构差异");
    } catch (e) {
      toast(e.message, true);
    } finally {
      state.autoBusy = false;
      renderPage({ restore: true });
    }
  }
  async function saveDraft() {
    if (state.autoBusy || !state.composeDraft) return;
    state.autoBusy = true;
    renderPage({ restore: true });
    try {
      const saved = await api("automation/compose/save", { draft: state.composeDraft });
      state.composeDraft = null;
      state.composeChanges = null;
      state.composeFeedback = "";
      await refresh();
      state.selectedFlow = saved.workflow_id;
      write("flow", saved.workflow_id);
      toast(`已保存 ${saved.agents.length} 个 Agent 与流程`);
    } catch (e) {
      toast(e.message, true);
    } finally {
      state.autoBusy = false;
      renderPage({ restore: true });
    }
  }
  function toggleKind(form) {
    const kind = form.elements.kind.value, answer = kind === "answer", graph = kind === "graph";
    form.querySelector("[data-answer-config]").hidden = !answer;
    form.querySelector("[data-ingest-config]").hidden = answer || graph;
    form.querySelector("[data-graph-config]").hidden = !graph;
    form.elements.agent_id.required = answer;
    form.elements.chunk_size.required = !answer && !graph;
    form.elements.graph_json.required = graph;
    if (graph && !graphRows(form).length) renderGraphRows(form);
  }
  async function execute(form) {
    if (state.autoBusy) return;
    const w = flow();
    if (!w) return;
    const input = Object.fromEntries(new FormData(form));
    state.automationInput = { ...state.automationInput, ...input };
    state.autoBusy = true;
    state.autoError = "";
    renderPage({ restore: true });
    try {
      state.currentRun = await api(`workflows/${w.id}/run`, {
        version: w.version,
        input,
      });
      await refresh();
      toast(
        state.currentRun.data.status === "failed"
          ? "流程执行失败，请查看步骤记录"
          : state.currentRun.data.kind === "ingest"
            ? "资料已解析，等待你确认入库"
            : "流程执行完成",
      );
    } catch (e) {
      state.autoError = e.message;
      toast(e.message, true);
    } finally {
      state.autoBusy = false;
      renderPage({ restore: true });
    }
  }
  async function confirmRun(form) {
    if (state.autoBusy) return;
    const selected = new FormData(form).getAll("selected").map(Number);
    if (!selected.length) {
      toast("至少选择一个片段", true);
      return;
    }
    state.autoBusy = true;
    const submit = form.querySelector("[type=submit]");
    submit.disabled = true;
    submit.textContent = "正在保存…";
    try {
      const row = await api(`workflow-runs/${form.dataset.runId}/confirm`, {
        version: Number(form.dataset.version),
        selected,
      });
      state.currentRun = row;
      state.runDetail = row;
      await refresh();
      toast(`已保存 ${row.data.result.created_ids.length} 条知识`);
    } catch (e) {
      toast(e.message, true);
    } finally {
      state.autoBusy = false;
      if (form.isConnected) {
        submit.disabled = false;
        submit.textContent = "确认选中片段入库";
      } else renderPage({ restore: true });
    }
  }
  async function saveEditor(form) {
    if (form.dataset.saving === "true") return;
    const d = form.closest("dialog"),
      kind = d.dataset.autoForm,
      fd = new FormData(form),
      id = d.dataset.recordId,
      version = Number(d.dataset.version),
      button = form.querySelector("[type=submit]"),
      error = form.querySelector(".auto-form-error");
    let data;
    if (kind === "agent")
      data = {
        title: fd.get("title"),
        system_prompt: fd.get("system_prompt"),
        scopes: fd.getAll("scopes"),
        mode: fd.get("mode"),
        result_limit: Number(fd.get("result_limit")),
        generate: fd.has("generate"),
        workspace: {
          root: fd.get("workspace_root") || "",
          write: fd.get("workspace_write") || "each",
          shell: fd.has("workspace_shell"),
        },
      };
    else if (fd.get("kind") === "graph") {
      try {
        const parsed = JSON.parse(fd.get("graph_json") || "{}");
        if (!parsed || typeof parsed !== "object" || Array.isArray(parsed)) throw new Error("DAG 必须是 JSON 对象");
        data = { title: fd.get("title"), kind: "graph", ...parsed };
      } catch (parseError) {
        error.textContent = "DAG JSON 格式不正确：" + parseError.message;
        error.hidden = false;
        return;
      }
    } else
      data = {
        title: fd.get("title"),
        kind: fd.get("kind"),
        agent_id: fd.get("agent_id") || "",
        chunk_size: Number(fd.get("chunk_size")),
      };
    form.dataset.saving = "true";
    button.disabled = true;
    button.textContent = "保存中…";
    error.hidden = true;
    try {
      const path = kind === "agent" ? "agents" : "workflows";
      const row = await api(
        path + (id ? "/" + id : ""),
        { data, ...(id ? { version } : {}) },
        id ? "PUT" : "POST",
      );
      if (kind === "workflow") state.selectedFlow = row.id;
      await refresh();
      d.close();
      toast("配置已保存，历史版本已保留");
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    } finally {
      form.dataset.saving = "false";
      button.disabled = false;
      button.textContent = "保存配置";
    }
  }
  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const b = event.target.closest('[data-action^="auto-"]');
    if (!b) return;
    const action = b.dataset.action.slice(5),
      id = b.dataset.id;
    if (action === "graph-add") {
      const form = b.closest("form");
      if (!form) return;
      const holder = form.querySelector("[data-graph-rows]");
      const ids = graphRows(form).map((r) => r.querySelector("[data-graph-id]").value);
      const row = document.createElement("div");
      row.className = "graph-editor__row";
      row.setAttribute("data-graph-row", "");
      row.innerHTML = `<input aria-label="节点 ID" data-graph-id value="step${ids.length}" maxlength="41"><select aria-label="节点类型" data-graph-type>${NODE_TYPES.map((t) => `<option value="${t}">${t}</option>`).join("")}</select><input aria-label="指令或查询" data-graph-query maxlength="1000" placeholder="query">${upstreamSelect(ids, "")}<button type="button" class="small-button" data-action="auto-graph-add-upstream" title="增加一个上游节点，用于并行汇合">+ 上游</button><button type="button" class="small-button" data-action="auto-graph-remove">删除</button>`;
      holder.append(row);
      return;
    }
    if (action === "graph-add-upstream") {
      const row = b.closest("[data-graph-row]");
      const form = row?.closest("form");
      if (!row || !form) return;
      const ids = graphRows(form).map((r) => r.querySelector("[data-graph-id]").value);
      b.insertAdjacentHTML("beforebegin", upstreamSelect(ids, ""));
      return;
    }
    if (action === "graph-remove") {
      b.closest("[data-graph-row]")?.remove();
      return;
    }
    if (action === "graph-sync") {
      const form = b.closest("form");
      if (form) {
        syncGraphToJson(form);
        toast("已同步到 DAG JSON");
      }
      return;
    }
    if (action === "draft") {
      const form = b.closest("form") || document.getElementById("compose-form");
      if (form) await draftWorkflow(form);
      return;
    }
    if (action === "revise-draft") {
      await reviseDraft();
      return;
    }
    if (action === "save-draft") {
      await saveDraft();
      return;
    }
    if (action === "drop-draft") {
      state.composeDraft = null;
      state.composeChanges = null;
      state.composeFeedback = "";
      renderPage({ restore: true });
      return;
    }
    if (action === "new-agent") openEditor("agent");    if (action === "edit-agent")
      openEditor(
        "agent",
        state.agents.find((a) => a.id === id),
      );
    if (action === "new-workflow") openEditor("workflow");
    if (action === "edit-workflow")
      openEditor(
        "workflow",
        state.workflows.find((w) => w.id === id),
      );
    if (action === "select-flow" && !state.autoBusy) {
      state.selectedFlow = id;
      write("flow", id);
      state.autoError = "";
      renderPage({ restore: true });
    }
    if (action === "reload") await refresh();
    if (action === "setup" && !state.autoBusy) {
      state.autoBusy = true;
      renderPage({ restore: true });
      try {
        await api("automation/setup", {});
        await refresh();
        toast("基础配置已启用");
      } catch (e) {
        toast(e.message, true);
      } finally {
        state.autoBusy = false;
        renderPage({ restore: true });
      }
    }
    if (action === "confirm-graph") {
      const row = state.currentRun?.id === id ? state.currentRun : state.runDetail;
      if (!row || !window.confirm(b.dataset.approve === "true" ? "批准该节点继续执行？" : "拒绝并停止该工作流？")) return;
      b.disabled = true;
      try {
        const updated = await api(`workflow-runs/${id}/confirm`, { version: row.version, approve: b.dataset.approve === "true" });
        state.currentRun = updated; state.runDetail = updated; await refresh();
        toast(updated.data.status === "awaiting_confirmation" ? "仍有节点待确认" : "工作流已继续");
      } catch (e) { toast(e.message, true); }
      finally { b.disabled = false; }
      return;
    }
    if (action === "open-run") {
      b.disabled = true;
      try {
        state.runDetail = await api("workflow-runs/" + id);
        renderPage({ restore: true });
        document
          .querySelector(".run-result")
          ?.scrollIntoView({ behavior: "smooth", block: "start" });
      } catch (e) {
        toast(e.message, true);
      } finally {
        b.disabled = false;
      }
      return;
    }
    if (action.startsWith("queue-")) {
      await queueAction(action, id);
      return;
    }
  });
  document.addEventListener("submit", (event) => {
    if (event.target.id === "compose-form") {
      event.preventDefault();
      composeWorkflow(event.target);
      return;
    }
    if (event.target.id === "team-form") {
      event.preventDefault();
      runTeam(event.target);
      return;
    }
    if (event.target.id === "loop-form") {
      event.preventDefault();
      runLoop(event.target);
      return;
    }
    if (event.target.id === "queue-form") {
      event.preventDefault();
      enqueueJob(event.target);
      return;
    }
    if (event.target.matches(".automation-edit-form")) {
      event.preventDefault();
      saveEditor(event.target);
    }
    if (event.target.id === "workflow-execute-form") {
      event.preventDefault();
      execute(event.target);
    }
    if (event.target.id === "ingest-confirm-form") {
      event.preventDefault();
      confirmRun(event.target);
    }
  });
  document.addEventListener("input", (event) => {
    if (event.target.id === "compose-feedback")
      state.composeFeedback = event.target.value;
    if (event.target.closest("#workflow-execute-form") && event.target.name)
      state.automationInput[event.target.name] = event.target.value;
    if (event.target.closest("#loop-form") && event.target.name)
      state.loopInput[event.target.name] = event.target.value;
    if (event.target.closest("#queue-form") && event.target.name)
      state.queueInput[event.target.name] = event.target.value;
  });
  document.addEventListener("change", async (event) => {
    /* select 在部分浏览器只派发 change，这里补一次输入回填。 */
    if (event.target.closest("#loop-form") && event.target.name)
      state.loopInput[event.target.name] = event.target.value;
    if (event.target.closest("#queue-form") && event.target.name)
      state.queueInput[event.target.name] = event.target.value;
    /* 切换任务类型会改变表单结构（团队不需要仓库与门禁），要重绘。 */
    if (event.target.closest("#queue-form") && event.target.name === "kind") {
      renderPage({ restore: true });
      return;
    }
    if (event.target.matches("[data-queue-filter]")) {
      state.queueFilter = event.target.value;
      try {
        await loadQueueJobs(state.queueFilter);
      } catch (e) {
        toast(e.message, true);
      }
      renderPage({ restore: true });
      return;
    }
    if (
      event.target.name === "kind" &&
      event.target.closest(".automation-edit-form")
    )
      toggleKind(event.target.form);
    if (event.target.id === "workflow-file") {
      const file = event.target.files[0];
      if (!file) return;
      try {
        if (!/\.(md|txt)$/i.test(file.name) || file.size > 400000)
          throw Error("请选择 400 KB 以内的 Markdown 或 TXT 文件");
        const text = await file.text();
        if (text.length > 100000) throw Error("正文不能超过 10 万字");
        state.automationInput = {
          ...state.automationInput,
          title: file.name.replace(/\.(md|txt)$/i, ""),
          source: file.name,
          content: text,
        };
        renderPage({ restore: true });
        toast("已读取文件，点击解析查看入库预览");
      } catch (e) {
        toast(e.message, true);
      }
    }
  });
}
