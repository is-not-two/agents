/* 运行诊断：分区读取，失败与旧数据显式区分；诊断不执行发布命令。 */
import { api, escapeHtml as escape } from "./data.js?v=101";
const cache = { data: null, mcp: null, diagnostics: null, errors: {}, loaded: false, loading: false, checkedAt: "" };
let repaint = () => {};

async function load() {
  if (cache.loading) return;
  cache.loading = true;
  repaint();
  const keys = ["data", "mcp", "diagnostics"];
  const paths = ["admin/stats", "mcp/status", "admin/diagnostics"];
  try {
    const results = await Promise.allSettled(paths.map((path) => api(path)));
    cache.errors = {};
    results.forEach((result, i) => {
      if (result.status === "fulfilled") cache[keys[i]] = result.value;
      else {
        cache[keys[i]] = null;
        cache.errors[keys[i]] = result.reason?.message || "读取失败";
      }
    });
    cache.checkedAt = new Date().toISOString();
  } finally {
    cache.loading = false;
    cache.loaded = true;
    repaint();
  }
}

function diagnosticsView() {
  const d = cache.diagnostics;
  if (!d || !Array.isArray(d.checks)) return "";
  return `<h3>运行诊断：${d.passed ? "通过" : "存在待处理项"}</h3><p>模式 ${escape(d.profile)} · 请求 ${escape(d.request_id || "")}</p><ul class="status-tools diagnostic-checks">${d.checks.map((c) => `<li><span>${escape(c.id)}</span><small class="${c.status === "fail" ? "error-text" : ""}">${escape(c.status)} · ${escape(c.message)}</small></li>`).join("")}</ul>`;
}

export function serverStatusView() {
  if (!cache.loaded && !cache.loading) load();
  const s = cache.data, m = cache.mcp;
  const kinds = s ? Object.entries(s.kinds || {}).map(([kind, n]) => `<tr><td>${escape(kind)}</td><td>${escape(n.active)}</td><td>${escape(n.trash)}</td></tr>`).join("") : "";
  const v = s?.vector;
  const vectors = v ? (v.available ? `<p>向量库：可用 · tech_doc ${escape(v.counts?.tech_doc ?? "?")} 条</p>` : `<p class="error-text">向量库不可用：${escape(v.reason || "未知原因")}</p>`) : "";
  const tools = m && Array.isArray(m.tools) ? m.tools.map((t) => `<li><span>${escape(t.name)}</span><small>${t.enabled ? "已启用" : "已关闭"} · ${escape(t.permission)}</small></li>`).join("") : "";
  const labels = { data: "统计摘要", mcp: "MCP 服务", diagnostics: "运行诊断" };
  const errors = Object.entries(cache.errors).map(([key, message]) => `<p class="error-text" role="alert">${escape(labels[key] || key)}：${escape(message)}</p>`).join("");
  return `<section class="module-surface server-status" aria-busy="${cache.loading}"><h2>服务状态与运行诊断</h2><p role="status">${cache.loading ? "正在读取…" : "最近检查 " + escape(new Date(cache.checkedAt).toLocaleString("zh-CN", { hour12: false }))}</p><div class="toolbar-actions"><button class="small-button" data-action="server-status-reload" ${cache.loading ? "disabled" : ""}>刷新诊断</button><button class="small-button" data-action="server-status-export" ${!cache.diagnostics || cache.loading ? "disabled" : ""}>下载诊断报告</button></div>${errors}${s ? `<p>存储 ${escape(s.storage)} · 阶段 ${escape(s.stages_count)} · 限流 ${escape(s.rate_limit_per_minute)}/分钟 · 模型${s.llm_configured ? "已配置" : "未配置"} · 鉴权${s.auth_enabled ? "已开启" : "未开启"}</p><table class="status-table"><thead><tr><th>记录类型</th><th>有效</th><th>回收站</th></tr></thead><tbody>${kinds}</tbody></table>` : ""}${vectors}${m ? `<p>MCP 服务：${escape(m.server)} · ${escape(m.transport)} · 端点 ${escape(m.mount)}</p><ul class="status-tools">${tools}</ul>` : ""}${diagnosticsView()}</section>`;
}

export function bindServerStatus({ renderPage }) {
  const active = () => location.hash === "#module/appearance";
  repaint = () => { if (active()) renderPage({ restore: true }); };
  return {
    ensure() { if (active() && !cache.loaded && !cache.loading) load(); },
    reload() { load(); },
    download() {
      if (!cache.diagnostics || cache.loading) return;
      const blob = new Blob([JSON.stringify({ checkedAt: cache.checkedAt, ...cache.diagnostics }, null, 2)], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = "shilie-diagnostics.json";
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
    },
  };
}
