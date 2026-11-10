/* 目标公司能力清单：记录公司要什么，不自动判定个人是否具备。 */
import { api, escapeHtml as esc } from "./data.js?v=116";

const requirementLabels = { must: "硬性要求", nice: "加分项" };
const statusLabels = { evidence: "有证据", pending: "待补证据", missing: "未提供" };
const cache = { data: null, loading: false, busy: false, error: "", trash: false, selected: "", history: null };
let repaint = () => {};
const date = (value) => (value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未设置");
const rows = () => cache.data || [];
const selected = () => rows().find((row) => row.id === cache.selected);
const button = (text, action, row, extra = "") => `<button type="button" class="small-button" data-action="cap-${action}" ${row ? `data-id="${esc(row.id)}"` : ""} ${extra}>${esc(text)}</button>`;
const options = (items, chosen) => items.map(([id, label]) => `<option value="${esc(id)}" ${String(id) === String(chosen) ? "selected" : ""}>${esc(label)}</option>`).join("");

async function load() {
  if (cache.loading) return;
  cache.loading = true;
  try {
    cache.data = await api(`jobs/capabilities?trash=${cache.trash}`);
    cache.error = "";
  } catch (error) { cache.error = error.message; }
  finally { cache.loading = false; repaint(); }
}

function source(value) {
  if (!value) return "";
  return /^https?:\/\//i.test(value)
    ? `<a class="jobs-source" href="${esc(value)}" target="_blank" rel="noopener noreferrer">打开能力来源</a>`
    : `<p class="jobs-caption">来源：${esc(value)}</p>`;
}

function capabilityItem(item) {
  return `<article class="capability-item"><header><h4>${esc(item.name)}</h4><span>${esc(requirementLabels[item.requirement] || item.requirement)} · 重要度 ${item.level}/5</span></header><p class="jobs-caption">证据状态：${esc(statusLabels[item.status] || item.status)}</p>${item.evidence ? `<p class="jobs-prose">${esc(item.evidence)}</p>` : ""}</article>`;
}

function details(row) {
  if (!row) return '<section class="module-surface jobs-detail"><h2>选择一家目标公司</h2><p>先记录公司与岗位，再填写原文要求的能力、重要度和自己的证据状态；没有证据不代表不会。</p></section>';
  const data = row.data;
  return `<section class="module-surface jobs-detail" aria-label="目标公司能力详情"><header><h2>${esc(data.title)}</h2><span>${data.capabilities.length} 项能力</span></header>
    <div class="jobs-actions">${cache.trash ? button("恢复记录", "restore", row) : button("编辑记录", "edit", row) + button("移入回收站", "archive", row)}${button("查看历史", "history", row)}</div>
    ${source(data.source)}
    <ul class="capability-list">${data.capabilities.map(capabilityItem).join("")}</ul>
    ${data.notes ? `<h3>备注</h3><pre class="jobs-prose">${esc(data.notes)}</pre>` : ""}
    ${cache.history?.id === row.id ? `<section class="jobs-history"><h3>版本历史</h3>${cache.history.rows.map((v) => `<p>v${v.version} ${esc(v.action)} ${esc(date(v.created_at))} ${button("恢复此版本", "restore", row, `data-target-version="${v.version}"`)}</p>`).join("")}</section>` : ""}</section>`;
}

export function capabilitiesView() {
  const head = `<div class="page-head"><h1>目标公司能力</h1></div><div class="jobs-toolbar">${button("添加目标公司", "new")}${button(cache.trash ? "返回有效记录" : "回收站", "trash")}${button("刷新", "reload")}<a class="small-button" href="#module/jobs">求职记录</a></div>`;
  if (!cache.data) return `${head}<section class="module-surface"><p role="${cache.error ? "alert" : "status"}">${esc(cache.error || "正在读取目标公司能力…")}</p></section>`;
  const chosen = selected();
  return `${head}${cache.error ? `<p class="error-text" role="alert">${esc(cache.error)}</p>` : ""}<p class="jobs-caption">共 ${rows().length} 家目标公司。能力清单来自 JD 原文或人工整理，页面不给出“已具备/不满足”的自动结论。</p>
    <div class="jobs-layout" aria-busy="${cache.loading || cache.busy}"><section class="module-surface jobs-list" aria-label="目标公司列表">${rows().length ? rows().map((r) => `<button type="button" class="jobs-row" data-action="cap-select" data-id="${esc(r.id)}" aria-pressed="${r.id === chosen?.id}"><strong>${esc(r.data.title)}</strong><span>${r.data.capabilities.length} 项能力</span><small>${esc(r.data.capabilities.filter((c) => c.status === "missing").length)} 项未提供证据</small></button>`).join("") : `<p>${cache.trash ? "回收站为空。" : "暂无目标公司。添加后可逐条记录能力要求与证据状态。"}</p>`}</section>${details(chosen)}</div>`;
}

export function capabilitiesDialog() {
  return '<dialog class="form-dialog jobs-dialog" data-form="capability" aria-labelledby="capability-dialog-title"><form class="edit-form" id="capability-form"><header class="drawer-header"><h2 id="capability-dialog-title">目标公司能力</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content" id="capability-form-body"></div></form></dialog>';
}

const input = (label, name, value = "", maximum = 160, required = false) => `<label class="form-field">${esc(label)}<input name="${name}" value="${esc(value)}" maxlength="${maximum}" ${required ? "required" : ""}></label>`;
const area = (label, name, value = "", maximum = 1000) => `<label class="form-field">${esc(label)}<textarea name="${name}" rows="2" maxlength="${maximum}">${esc(value)}</textarea></label>`;
function capabilityRow(item = {}) {
  return `<fieldset class="capability-row" data-capability><legend>能力</legend>${input("能力名称", "cap_name", item.name, 120, true)}<label class="form-field">要求<select name="cap_requirement" aria-label="要求">${options(Object.entries(requirementLabels), item.requirement || "must")}</select></label><label class="form-field">重要度<select name="cap_level" aria-label="重要度">${options([[1, "1 提及"], [2, "2 一般"], [3, "3 重要"], [4, "4 很重视"], [5, "5 核心"]], item.level || 3)}</select></label><label class="form-field">证据状态<select name="cap_status" aria-label="证据状态">${options(Object.entries(statusLabels), item.status || "pending")}</select></label>${area("证据说明（如实填写，不自动采信）", "cap_evidence", item.evidence)}${button("移除此能力", "remove-row")}</fieldset>`;
}

export function bindCapabilities({ renderPage, toast }) {
  repaint = () => { if (location.hash === "#module/company-capabilities") renderPage({ restore: true }); };
  const dialog = () => document.querySelector('dialog[data-form="capability"]');
  function open(row = null) {
    const d = dialog(), value = row?.data || {};
    d.dataset.recordId = row?.id || ""; d.dataset.version = row?.version || "";
    document.getElementById("capability-dialog-title").textContent = row ? "编辑目标公司能力" : "添加目标公司能力";
    document.getElementById("capability-form-body").innerHTML = `${input("公司", "company", value.company, 160, true)}${input("岗位（选填）", "role", value.role, 160)}${input("来源（JD 链接或平台说明，选填）", "source", value.source, 2000)}<div id="capability-rows">${(value.capabilities?.length ? value.capabilities : [{}]).map(capabilityRow).join("")}</div>${button("添加一项能力", "add-row")}${area("备注（选填）", "notes", value.notes, 10000)}<p id="capability-form-error" class="error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存</button></div>`;
    d.showModal();
    d.querySelector('input[name="company"]')?.focus();
  }
  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const b = event.target.closest('[data-action^="cap-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(4);
    const row = rows().find((r) => r.id === b.dataset.id);
    if (action === "new") return open();
    if (action === "edit" && row) return open(row);
    if (action === "add-row") return document.getElementById("capability-rows").insertAdjacentHTML("beforeend", capabilityRow());
    if (action === "remove-row") return b.closest("fieldset").remove();
    if (action === "select") { cache.selected = b.dataset.id; cache.history = null; repaint(); return; }
    if (action === "trash") { cache.trash = !cache.trash; cache.data = null; cache.selected = ""; cache.history = null; await load(); return; }
    if (action === "reload") return load();
    if (!row) return;
    cache.busy = true;
    try {
      if (action === "history") cache.history = { id: row.id, rows: await api(`records/${row.id}/history`) };
      if (action === "archive" && confirm("移入回收站？可从回收站恢复，不会连带删除关联内容。")) {
        await api(`records/${row.id}?version=${row.version}`, undefined, "DELETE"); cache.history = null; await load(); toast("已移入回收站");
      }
      if (action === "restore" && confirm("将此历史内容恢复为一个新版本？当前内容仍保留在历史中。")) {
        const history = await api(`records/${row.id}/history`);
        const target = b.dataset.targetVersion ? Number(b.dataset.targetVersion) : history.find((v) => !v.deleted)?.version;
        if (!target) throw new Error("没有可恢复的有效版本");
        await api(`records/${row.id}/restore`, { target_version: target, current_version: row.version }); cache.history = null; await load(); toast("已恢复为新版本");
      }
    } catch (error) { toast(error.message, true); }
    finally { cache.busy = false; repaint(); }
  });
  document.addEventListener("submit", async (event) => {
    if (event.target.id !== "capability-form") return;
    event.preventDefault();
    if (cache.busy) return;
    const form = event.target, d = dialog(), errorBox = form.querySelector("#capability-form-error"), submit = form.querySelector('[type="submit"]');
    const data = {
      company: form.querySelector('[name="company"]').value,
      role: form.querySelector('[name="role"]').value,
      source: form.querySelector('[name="source"]').value,
      notes: form.querySelector('[name="notes"]').value,
      capabilities: [...form.querySelectorAll("[data-capability]")].map((field) => ({
        name: field.querySelector('[name="cap_name"]').value,
        requirement: field.querySelector('[name="cap_requirement"]').value,
        level: Number(field.querySelector('[name="cap_level"]').value),
        status: field.querySelector('[name="cap_status"]').value,
        evidence: field.querySelector('[name="cap_evidence"]').value,
      })),
    };
    cache.busy = true; submit.disabled = true; submit.textContent = "保存中…"; errorBox.hidden = true;
    try {
      const id = d.dataset.recordId;
      const row = await api(`jobs/capabilities${id ? "/" + id : ""}`, { data, ...(id ? { version: Number(d.dataset.version) } : {}) }, id ? "PUT" : "POST");
      cache.selected = row.id; cache.history = null; d.close(); await load(); toast(cache.error ? "已保存，但列表读取失败，请刷新列表，不要重复提交" : "已保存");
    } catch (error) { errorBox.textContent = error.message + (error.status === 409 ? "。当前输入已保留，请复制需要的内容后取消并重新打开最新记录。" : ""); errorBox.hidden = false; }
    finally { cache.busy = false; submit.disabled = false; submit.textContent = "保存"; repaint(); }
  });
  return { ensure() { if (location.hash === "#module/company-capabilities" && !cache.data && !cache.loading && !cache.error) load(); } };
}
