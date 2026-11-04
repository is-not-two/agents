/* 模型连接表单：密钥仅随请求发送，不写浏览器偏好。 */
import { api, state } from "./data.js?v=110";
const escape = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const connection = {
  info: null,
  error: "",
  loading: false,
  busy: false,
  loaded: false,
};
export function modelConnectionView() {
  const info = connection.info;
  if (!info)
    return `<section class="module-surface"><p role="status">${connection.loading ? "正在读取模型连接…" : "尚未读取模型连接"}</p>${connection.error ? `<p role="alert" class="error-text">${escape(connection.error)}</p><button class="small-button" data-action="model-reload">重新加载</button>` : ""}</section>`;
  return `<section class="module-surface connection-settings"><header class="connection-heading"><div><h2>连接你的模型服务</h2><p>支持 OpenAI 兼容的聊天 API，保存后检索回答和 Agent 立即使用新连接。</p></div><span class="connection-state ${info.configured ? "ready" : ""}">${info.configured ? "已配置" : "待配置"}</span></header><form id="model-connection-form"><label class="form-field">API 地址<input name="base_url" type="url" required maxlength="2048" value="${escape(info.base_url)}" placeholder="https://api.example.com/v1" autocomplete="url"><small>填写服务商的 API 基础地址；也可粘贴完整的 chat/completions 地址。</small></label><label class="form-field">模型名称<input name="model" required maxlength="160" value="${escape(info.model)}" placeholder="填写服务商提供的模型 ID" autocomplete="off"></label><label class="form-field">API 密钥 <span>${info.has_api_key ? "已保存，留空则保持" : "尚未填写"}</span><div class="connection-secret"><input name="api_key" type="password" ${info.has_api_key ? "" : "required"} maxlength="8192" autocomplete="new-password" placeholder="${info.has_api_key ? "输入新密钥可替换原密钥" : "粘贴你的 API 密钥"}"><button type="button" class="small-button" data-action="model-reveal" aria-pressed="false">显示</button></div><small>密钥保存在本地服务器私有目录，不写入浏览器缓存或知识备份。</small></label><p class="connection-source">${info.source === "environment" ? "当前读取服务器环境配置；保存后优先使用本页配置。" : info.source === "web" ? "当前使用本页保存的连接，服务重启后仍保留。" : "测试连接不会保存；确认无误后点击保存。"}</p><div id="model-connection-feedback" role="status" aria-live="polite" hidden></div><div class="form-actions"><button type="button" class="small-button" data-action="model-reload">重新加载</button><button type="button" class="small-button" data-action="model-test">测试连接</button><button type="submit" class="primary-button">保存连接</button></div></form></section>`;
}
export function bindModelConnection({ renderPage, toast }) {
  const active = () => location.hash === "#module/connections";
  async function load() {
    if (connection.loading || connection.busy) return;
    const form = active()
      ? document.querySelector("#model-connection-form")
      : null;
    const buttons = form
      ? [...form.querySelectorAll("button")].map((button) => [
          button,
          button.disabled,
        ])
      : [];
    connection.loading = true;
    connection.error = "";
    if (form) {
      buttons.forEach(([button]) => (button.disabled = true));
      form.setAttribute("aria-busy", "true");
      feedback(form, "正在重新加载连接…");
    } else if (active()) renderPage({ restore: true });
    let loaded = false;
    try {
      connection.info = await api("model-connection");
      connection.loaded = true;
      loaded = true;
    } catch (e) {
      connection.error = e.message;
    } finally {
      connection.loading = false;
      buttons.forEach(([button, disabled]) => (button.disabled = disabled));
      if (form) form.setAttribute("aria-busy", "false");
      if (active()) {
        if (loaded || !document.querySelector("#model-connection-form"))
          renderPage({ restore: true });
        const current = document.querySelector("#model-connection-form");
        if (connection.error && current)
          feedback(current, connection.error, true);
      }
    }
  }
  function feedback(form, message, failed = false) {
    const box = form.querySelector("#model-connection-feedback");
    if (!box) return;
    box.hidden = false;
    box.textContent = message;
    box.className = failed
      ? "connection-feedback error-text"
      : "connection-feedback success";
    box.setAttribute("role", failed ? "alert" : "status");
  }
  async function submit(form, test) {
    if (connection.loading || connection.busy || !form.reportValidity()) return;
    connection.busy = true;
    const buttons = [...form.querySelectorAll("button")];
    buttons.forEach((b) => (b.disabled = true));
    form.setAttribute("aria-busy", "true");
    const button = test
        ? form.querySelector("[data-action=model-test]")
        : form.querySelector("[type=submit]"),
      label = button.textContent;
    button.textContent = test ? "正在测试…" : "正在保存…";
    feedback(form, test ? "正在请求模型服务，请稍候…" : "正在保存连接…");
    try {
      const data = Object.fromEntries(new FormData(form));
      data.revision = connection.info.revision;
      const result = await api(
        test ? "model-connection/test" : "model-connection",
        data,
        test ? "POST" : "PUT",
      );
      if (test) {
        feedback(form, result.message, !result.ok);
      } else {
        connection.info = result;
        state.status.llm_configured = result.configured;
        form.elements.api_key.value = "";
        if (active()) {
          renderPage({ restore: true });
          const current = document.querySelector("#model-connection-form");
          if (current) feedback(current, "连接已保存并立即生效。");
        }
        toast("模型连接已保存");
      }
    } catch (e) {
      feedback(form, e.message, true);
    } finally {
      connection.busy = false;
      form.setAttribute("aria-busy", "false");
      buttons.forEach((b) => (b.disabled = false));
      button.textContent = label;
    }
  }
  document.addEventListener("submit", (e) => {
    if (e.target.id === "model-connection-form") {
      e.preventDefault();
      submit(e.target, false);
    }
  });
  document.addEventListener("click", (e) => {
    if (!(e.target instanceof Element)) return;
    const b = e.target.closest('[data-action^="model-"]');
    if (!b) return;
    const action = b.dataset.action.slice(6);
    if (action === "reload") load();
    if (action === "test") submit(b.form, true);
    if (action === "reveal") {
      const input = b.form.elements.api_key,
        reveal = input.type === "password";
      input.type = reveal ? "text" : "password";
      b.textContent = reveal ? "隐藏" : "显示";
      b.setAttribute("aria-pressed", String(reveal));
    }
  });
  return {
    ensure() {
      if (
        active() &&
        !connection.loaded &&
        !connection.loading &&
        !connection.error
      )
        load();
    },
  };
}
