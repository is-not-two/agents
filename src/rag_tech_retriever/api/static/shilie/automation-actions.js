/* 配置与执行控制器；请求锁、输入草稿和运行状态独立于视图。 */
import { api, state, write } from "./data.js?v=116";
import { flow } from "./automation-views.js?v=116";
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
    if (kind === "workflow" && values.kind === "graph") {
      f.elements.graph_json.value = JSON.stringify({
        agent_id: values.agent_id || "", nodes: values.nodes || [], edges: values.edges || [],
        max_parallel: values.max_parallel || 1, max_retries: values.max_retries ?? 1,
        node_timeout_seconds: values.node_timeout_seconds || 60,
      }, null, 2);
    }
    d.showModal();
    f.elements.title.focus();
  }
  function toggleKind(form) {
    const kind = form.elements.kind.value, answer = kind === "answer", graph = kind === "graph";
    form.querySelector("[data-answer-config]").hidden = !answer;
    form.querySelector("[data-ingest-config]").hidden = answer || graph;
    form.querySelector("[data-graph-config]").hidden = !graph;
    form.elements.agent_id.required = answer;
    form.elements.chunk_size.required = !answer && !graph;
    form.elements.graph_json.required = graph;
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
    if (action === "new-agent") openEditor("agent");
    if (action === "edit-agent")
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
    }
  });
  document.addEventListener("submit", (event) => {
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
    if (event.target.closest("#workflow-execute-form") && event.target.name)
      state.automationInput[event.target.name] = event.target.value;
  });
  document.addEventListener("change", async (event) => {
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
