/* Corpus choices come from the server; never invent a namespace or file path. */
import { state, escapeHtml as esc } from "./data.js?v=102";
export function corpusSelect() {
  const options = state.corpusOptions;
  if (!options) return "";
  if (options.error) return `<span role="alert">${esc(options.error)}；语料选项未加载。</span>`;
  return `<label>技术语料域<select name="namespace" aria-label="技术语料域">${options.namespaces.map((item) => `<option value="${esc(item.id)}" ${state.namespace === item.id ? "selected" : ""}>${esc(item.label)}${item.installed ? "" : "（未安装）"}</option>`).join("")}</select></label>`;
}
