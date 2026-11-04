/* 求职闭环：真实记录优先，业务内容不写 localStorage。 */
import { api, escapeHtml as esc } from "./data.js?v=114";

const labels = { collected: "已收藏", applied: "已投递", following: "跟进中", interviewing: "面试中", offered: "已获 offer", rejected: "已结束" };
const paths = { job_lead: "leads", application: "applications", interview_report: "reports", resume_version: "resumes" };
const cache = { data: null, loading: false, busy: false, error: "", trash: false, selected: "", filter: "all", query: "", history: null, resumeDoc: null, diff: null };
let repaint = () => {};
const date = (value) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未设置";
const rows = () => cache.data ? Object.keys(paths).flatMap((kind) => cache.data[kind] || []) : [];
const selected = () => rows().find((row) => row.id === cache.selected);
const button = (text, action, row, extra = "") => `<button type="button" class="small-button" data-action="job-${action}" ${row ? `data-id="${esc(row.id)}"` : ""} ${extra}>${esc(text)}</button>`;
const options = (items, chosen) => items.map(([id, label]) => `<option value="${esc(id)}" ${id === chosen ? "selected" : ""}>${esc(label)}</option>`).join("");

async function load() {
  if (cache.loading) return;
  cache.loading = true;
  try {
    cache.data = await api(`jobs?trash=${cache.trash}`);
    cache.error = "";
  } catch (error) { cache.error = error.message; }
  finally { cache.loading = false; repaint(); }
}

function details(row) {
  if (!row) return '<section class="module-surface jobs-detail"><h2>选择一条岗位或投递</h2><p>先记录岗位，再添加投递和下一次跟进时间。面试后在同一处复盘。</p></section>';
  const data = row.data;
  const lead = row.kind === "job_lead" ? row : rows().find((r) => r.id === data.lead_id);
  const reports = (cache.data.interview_report || []).filter((r) => r.data.application_id === row.id);
  return `<section class="module-surface jobs-detail" aria-label="求职详情"><header><h2>${esc(data.title)}</h2><span>${row.kind === "application" ? esc(labels[data.status]) : row.kind === "interview_report" ? "面试复盘" : row.kind === "resume_version" ? "简历版本" : "岗位"}</span></header>
    <div class="jobs-actions">${cache.trash ? button("恢复记录", "restore", row) : button("编辑记录", "edit", row) + button("移入回收站", "archive", row)}${button("查看历史", "history", row)}
    ${!cache.trash && row.kind === "job_lead" ? button("添加投递", "application", row) : ""}${!cache.trash && row.kind === "application" ? button("记录面试复盘", "report", row) : ""}</div>
    ${lead ? `<p><a class="small-button" href="#module/job-insights/${encodeURIComponent(lead.id)}">查看岗位证据对照</a></p><p><strong>公司</strong> ${esc(lead.data.company)}</p>${lead.data.source_url ? `<a class="jobs-source" href="${esc(lead.data.source_url)}" target="_blank" rel="noopener noreferrer">打开岗位来源</a>` : ""}<details><summary>岗位原文</summary><pre class="jobs-prose">${esc(lead.data.jd_text || "尚未填写岗位原文")}</pre></details>` : ""}
    ${row.kind === "application" ? `<dl class="jobs-facts"><dt>投递渠道</dt><dd>${esc(data.channel || "未填写")}</dd><dt>投递时间</dt><dd>${esc(date(data.applied_at))}</dd><dt>下次跟进</dt><dd>${esc(date(data.follow_up_at))}</dd><dt>简历版本</dt><dd>${esc(rows().find((r) => r.id === data.resume_version_id)?.data.title || (data.resume_version_id ? "已归档版本" : "未关联"))}</dd></dl><h3>面试复盘</h3>${reports.length ? reports.map((r) => `<article class="jobs-report"><h4>${esc(r.data.title)}</h4>${reportBody(r.data, r)}${button("编辑复盘", "edit", r)}${button("复盘历史", "history", r)}${button("归档复盘", "archive", r)}</article>`).join("") : "<p>还没有面试复盘。推进到面试中后，可记录问题、卡壳点和下一步行动。</p>"}` : ""}
    ${row.kind === "interview_report" ? reportBody(data, row) : ""}${row.kind === "resume_version" ? `<p>文件：${esc(data.file_name || "仅登记元数据")} · ${data.size ? Math.round(data.size / 1024) + " KB" : "未上传"} · 解析：${esc(data.parse_status || "未解析")}</p><p>文件 SHA256：${esc(data.file_hash || "未登记")}</p><pre class="jobs-prose">${esc(data.highlights.join("\n"))}</pre>${data.document_id ? `<div class="jobs-actions">${button("查看解析", "resume-doc", row)}${cache.data.resume_version.some((r) => r.id !== row.id) ? button("对比上一版", "resume-diff", row) : ""}</div>` : "<p>仅保存版本元数据，可上传 PDF / DOCX / TXT 后自动解析。</p>"}${cache.resumeDoc?.record?.id === row.id ? `<h3>结构化段落</h3>${cache.resumeDoc.sections.map((section) => `<article class="jobs-report"><h4>${esc(section.title)}</h4><pre class="jobs-prose">${esc(section.content)}</pre></article>`).join("")}<p>技能命中：${esc((cache.resumeDoc.skills || []).join("、") || "未识别")}</p>` : ""}${cache.diff?.to === row.id ? `<h3>版本差异</h3><p>新增 ${cache.diff.added_lines} 行，删除 ${cache.diff.removed_lines} 行</p><pre class="jobs-prose">${esc(cache.diff.diff)}</pre>` : ""}` : ""}
    ${data.notes ? `<h3>备注</h3><pre class="jobs-prose">${esc(data.notes)}</pre>` : ""}
    ${cache.history?.id === row.id ? `<section class="jobs-history"><h3>版本历史</h3>${cache.history.rows.map((v) => `<p>v${v.version} ${esc(v.action)} ${esc(date(v.created_at))} ${button("恢复此版本", "restore", row, `data-target-version="${v.version}"`)}</p>`).join("")}</section>` : ""}</section>`;
}

function reportBody(data, row) {
  return `<time>${esc(date(data.interviewed_at))}</time>${data.questions.map((q) => `<h4>${esc(q.q)}</h4><p class="jobs-prose">${esc(q.answer_summary || "未填写回答复盘")}</p><small>自评 ${q.rating}/3</small>`).join("")}<h4>薄弱点（待确认复习候选）</h4><ul>${data.weak_points.map((s) => `<li>${esc(s)}</li>`).join("")}</ul><h4>下一步行动</h4><ul>${data.next_actions.map((s) => `<li>${esc(s)}</li>`).join("")}</ul>${row && data.weak_points.length ? `<button type="button" class="small-button" data-action="learn-candidate" data-id="${esc(row.id)}">选点创建复习卡</button>` : ""}<p class="jobs-caption">勾选薄弱点并确认后才会创建复习卡；通知发送需独立启用。</p>`;
}

const percent = (value) => (Number.isFinite(value) ? `${Math.round(value * 1000) / 10}%` : "暂不计算");

function funnel(f) {
  if (!f) return "";
  const s = f.stages, r = f.rates;
  return `<section class="module-surface jobs-funnel" aria-label="求职漏斗"><header><h2>求职漏斗</h2><span>当前有效记录</span></header><ol class="funnel-steps">
    <li><strong>收藏</strong><b>${s.collected}</b><small>基准</small></li>
    <li><strong>投递</strong><b>${s.applied}</b><small>收藏→投递 ${percent(r.applied_per_collected)}</small></li>
    <li><strong>进面</strong><b>${s.interviewed}</b><small>投递→进面 ${percent(r.interviewed_per_applied)}</small></li>
    <li><strong>Offer</strong><b>${s.offered}</b><small>进面→offer ${percent(r.offered_per_interviewed)}</small></li></ol>
    <p class="jobs-caption">本周投递 ${f.weekly.applications} / 目标 ${f.weekly.target}${f.weekly.met ? "，已达标" : ""}。进面按已登记面试复盘计，offer 按当前状态计，两者不保证严格嵌套。</p></section>`;
}

export function jobsView() {
  const head = `<div class="page-head"><h1>求职记录</h1></div><div class="jobs-toolbar">${button("添加岗位", "new")}${button("登记简历版本", "resume")}${button("上传简历", "resume-upload")}${button(cache.trash ? "返回有效记录" : "回收站", "trash")}${button("刷新", "reload")}<a class="small-button" href="#module/company-capabilities">目标公司能力</a></div>`;
  if (!cache.data) return `${head}<section class="module-surface"><p role="${cache.error ? "alert" : "status"}">${esc(cache.error || "正在读取求职记录…")}</p></section>`;
  const all = rows();
  const applications = cache.data.application;
  const list = cache.trash ? all : [...applications, ...cache.data.job_lead.filter((lead) => !applications.some((app) => app.data.lead_id === lead.id))];
  const filtered = list.filter((r) => (cache.filter === "all" || (cache.filter === "due" ? cache.data.due_application_ids.includes(r.id) : r.data.status === cache.filter)) && `${r.data.title} ${r.data.company || ""}`.toLowerCase().includes(cache.query.toLowerCase()));
  const chosen = selected();
  return `${head}${cache.error ? `<p class="error-text" role="alert">${esc(cache.error)}</p>` : ""}<p class="jobs-caption">${applications.length} 条投递，${cache.data.due_application_ids.length} 条已到跟进时间。可从复盘选点建卡，在到期复习页自评；通知摘要需在通知中心明确确认。</p>
    ${cache.trash ? "" : funnel(cache.data.funnel)}
    <form id="jobs-filter" class="jobs-filter" role="search"><label>查找公司或岗位<input name="query" value="${esc(cache.query)}" maxlength="160" placeholder="输入公司或岗位"></label><label>投递状态<select name="filter">${options([["all", "全部"], ["due", "待跟进"], ...Object.entries(labels)], cache.filter)}</select></label><button class="small-button" type="submit">筛选</button></form>
    <div class="jobs-layout" aria-busy="${cache.loading || cache.busy}"><section class="module-surface jobs-list" aria-label="岗位与投递列表">${filtered.length ? filtered.map((r) => `<button type="button" class="jobs-row" data-action="job-select" data-id="${esc(r.id)}" aria-pressed="${r.id === chosen?.id}"><strong>${esc(r.data.title)}</strong><span>${esc(labels[r.data.status] || (r.kind === "resume_version" ? "简历版本" : r.kind === "interview_report" ? "复盘" : r.data.company))}</span>${r.data.follow_up_at ? `<small>${cache.data.due_application_ids.includes(r.id) ? "待跟进：" : "下次跟进："}${esc(date(r.data.follow_up_at))}</small>` : ""}</button>`).join("") : `<p>${cache.trash ? "回收站为空。" : "暂无符合条件的记录。可添加岗位，或调整筛选。"}</p>`}</section>${details(chosen)}</div>
    ${!cache.trash && cache.data.resume_version.length ? `<section class="jobs-resumes"><h2>简历版本</h2>${cache.data.resume_version.map((r) => button(r.data.title, "select", r)).join("")}</section>` : ""}`;
}

export function jobsDialog() {
  return '<dialog class="form-dialog jobs-dialog" data-form="jobs" aria-labelledby="jobs-dialog-title"><form class="edit-form" id="jobs-form"><header class="drawer-header"><h2 id="jobs-dialog-title">求职记录</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content" id="jobs-form-body"></div></form></dialog>'
    + '<dialog class="form-dialog jobs-dialog" data-form="resume-upload" aria-labelledby="resume-upload-title"><form class="edit-form" id="resume-upload-form"><header class="drawer-header"><h2 id="resume-upload-title">上传简历</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content"><label class="form-field">简历文件<input name="file" type="file" accept=".pdf,.docx,.txt,.md,.png,.jpg,.jpeg" required></label><label class="form-field">版本名称（选填）<input name="title" maxlength="160" placeholder="例如：AI 应用工程师 v2"></label><p>支持 PDF / DOCX / TXT / Markdown / PNG / JPEG，最大 10MB。扫描件与图片会尝试 OCR；原文件不进入公共备份，解析文本加密保存在服务器私密目录。</p><p id="resume-upload-error" class="error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">上传并解析</button></div></div></form></dialog>';
}

function input(label, name, value = "", type = "text", maximum = 160, required = false) {
  return `<label class="form-field">${esc(label)}<input name="${name}" type="${type}" value="${esc(value)}" maxlength="${maximum}" ${required ? "required" : ""}></label>`;
}
const area = (label, name, value = "", maximum = 10000) => `<label class="form-field">${esc(label)}<textarea name="${name}" rows="4" maxlength="${maximum}">${esc(value)}</textarea></label>`;
const localTime = (value) => {
  if (!value) return "";
  const d = new Date(value);
  return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
function questionField(question = { q: "", answer_summary: "", rating: 0 }) {
  return `<fieldset data-job-question><legend>实际面试问题</legend>${input("问题", "q", question.q, "text", 2000, true)}${area("当时回答与卡壳点", "answer_summary", question.answer_summary, 4000)}<label class="form-field">自评<select name="rating" aria-label="自评">${options([["0", "未自评"], ["1", "不会"], ["2", "部分掌握"], ["3", "能讲清楚"]], String(question.rating))}</select></label>${button("移除此问题", "remove-question")}</fieldset>`;
}

export function bindJobs({ renderPage, toast }) {
  repaint = () => { if (location.hash === "#module/jobs") renderPage({ restore: true }); };
  const dialog = () => document.querySelector('dialog[data-form="jobs"]');
  function open(kind, row = null, related = "") {
    const d = dialog();
    const value = row?.data || {};
    d.dataset.kind = kind; d.dataset.recordId = row?.id || ""; d.dataset.version = row?.version || "";
    document.getElementById("jobs-dialog-title").textContent = `${row ? "编辑" : "添加"}${{ job_lead: "岗位", application: "投递", interview_report: "面试复盘", resume_version: "简历版本" }[kind]}`;
    let fields = "";
    if (kind === "job_lead") fields = input("公司", "company", value.company, "text", 160, true) + input("岗位名称", "title", value.title, "text", 160, true) + input("来源链接（选填）", "source_url", value.source_url, "url", 2000) + area("岗位原文（选填）", "jd_text", value.jd_text, 50000);
    if (kind === "resume_version") fields = input("简历版本名称", "title", value.title, "text", 160, true) + input("文件 SHA256（选填）", "file_hash", value.file_hash, "text", 64) + area("亮点（每行一项）", "highlights", (value.highlights || []).join("\n"));
    if (kind === "application") fields = `<input name="lead_id" type="hidden" value="${esc(value.lead_id || related)}"><label class="form-field">状态<select name="status" aria-label="状态">${options(Object.entries(labels), value.status || "collected")}</select></label>${input("投递渠道（选填）", "channel", value.channel, "text", 80)}<label class="form-field">所用简历版本<select name="resume_version_id" aria-label="所用简历版本">${options([["", "暂不关联"], ...cache.data.resume_version.map((r) => [r.id, r.data.title])], value.resume_version_id || "")}</select></label>${input("投递时间（留空时首次投递自动记录）", "applied_at", localTime(value.applied_at), "datetime-local")}${input("下次跟进时间（选填）", "follow_up_at", localTime(value.follow_up_at), "datetime-local")}`;
    if (kind === "interview_report") fields = `<input name="application_id" type="hidden" value="${esc(value.application_id || related)}">${input("面试轮次", "round", value.round || 1, "number", 2, true)}${input("面试时间（留空使用当前时间）", "interviewed_at", localTime(value.interviewed_at), "datetime-local")}<div id="jobs-questions">${(value.questions || [{}]).map(questionField).join("")}</div>${button("添加一个问题", "add-question")}${area("薄弱点（每行一项，保存不会自动建卡）", "weak_points", (value.weak_points || []).join("\n"))}${area("下一步行动（每行一项）", "next_actions", (value.next_actions || []).join("\n"))}`;
    if (kind !== "resume_version") fields += area("备注（选填）", "notes", value.notes, kind === "application" ? 20000 : 10000);
    document.getElementById("jobs-form-body").innerHTML = `${fields}<p id="jobs-form-error" class="error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存</button></div>`;
    d.showModal();
    d.querySelector('input:not([type="hidden"]), select')?.focus();
  }
  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const b = event.target.closest('[data-action^="job-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(4);
    const row = rows().find((r) => r.id === b.dataset.id);
    if (action === "new") return open("job_lead");
    if (action === "resume") return open("resume_version");
    if (action === "edit" && row) return open(row.kind, row);
    if (action === "application" && row) return open("application", null, row.id);
    if (action === "report" && row) return open("interview_report", null, row.id);
    if (action === "add-question") { document.getElementById("jobs-questions").insertAdjacentHTML("beforeend", questionField()); return; }
    if (action === "remove-question") { b.closest("fieldset").remove(); return; }
    if (action === "select") { cache.selected = b.dataset.id; cache.history = null; cache.resumeDoc = null; cache.diff = null; repaint(); return; }
    if (action === "resume-upload") { document.querySelector('dialog[data-form="resume-upload"]').showModal(); return; }
    if (action === "trash") { cache.trash = !cache.trash; cache.data = null; cache.selected = ""; cache.history = null; await load(); return; }
    if (action === "reload") { await load(); return; }
    if (!row) return;
    cache.busy = true;
    try {
      if (action === "resume-doc") { cache.resumeDoc = await api(`jobs/resumes/${row.id}/document`); cache.diff = null; cache.selected = row.id; }
      if (action === "resume-diff") {
        const other = cache.data.resume_version.find((r) => r.id !== row.id);
        if (!other) throw new Error("没有可对比的其他简历版本");
        cache.diff = await api(`jobs/resumes/${row.id}/diff?against=${encodeURIComponent(other.id)}`); cache.resumeDoc = null; cache.selected = row.id;
      }
      if (action === "history") cache.history = { id: row.id, rows: await api(`records/${row.id}/history`) };
      if (action === "archive" && confirm("移入回收站？有关联记录时会阻止归档，不会连带删除。")) {
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
    if (event.target.id === "resume-upload-form") {
      event.preventDefault();
      if (cache.busy) return;
      const form = event.target, button = form.querySelector('[type="submit"]'), errorBox = form.querySelector("#resume-upload-error");
      cache.busy = true; button.disabled = true; button.textContent = "上传解析中…"; errorBox.hidden = true;
      try {
        const response = await fetch("/api/jobs/resumes/upload", { method: "POST", body: new FormData(form), cache: "no-store" });
        let value = null; try { value = await response.json(); } catch { value = null; }
        if (!response.ok) throw new Error(value?.detail || "上传失败");
        form.closest("dialog").close(); await load(); toast(value?.ocr_used ? "简历已上传并通过 OCR 解析" : "简历已上传并解析");
      } catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; }
      finally { cache.busy = false; button.disabled = false; button.textContent = "上传并解析"; }
      return;
    }
    if (event.target.id === "jobs-filter") {
      event.preventDefault(); const data = new FormData(event.target); cache.query = String(data.get("query")); cache.filter = String(data.get("filter")); repaint(); return;
    }
    if (event.target.id !== "jobs-form") return;
    event.preventDefault();
    if (cache.busy) return;
    const form = event.target, d = dialog(), kind = d.dataset.kind, errorBox = form.querySelector("#jobs-form-error"), submit = form.querySelector('[type="submit"]');
    const data = Object.fromEntries(new FormData(form));
    for (const key of ["applied_at", "follow_up_at", "interviewed_at"]) if (key in data) data[key] = data[key] ? new Date(data[key]).toISOString() : "";
    for (const key of ["weak_points", "next_actions", "highlights"]) if (key in data) data[key] = data[key].split("\n").map((s) => s.trim()).filter(Boolean);
    if (kind === "interview_report") {
      data.round = Number(data.round);
      data.questions = [...form.querySelectorAll("[data-job-question]")].map((f) => ({ q: f.querySelector('[name="q"]').value, answer_summary: f.querySelector('[name="answer_summary"]').value, rating: Number(f.querySelector('[name="rating"]').value) }));
      for (const key of ["q", "answer_summary", "rating"]) delete data[key];
    }
    cache.busy = true; submit.disabled = true; submit.textContent = "保存中…"; errorBox.hidden = true;
    try {
      const id = d.dataset.recordId;
      const row = await api(`jobs/${paths[kind]}${id ? "/" + id : ""}`, { data, ...(id ? { version: Number(d.dataset.version) } : {}) }, id ? "PUT" : "POST");
      cache.selected = row.id; cache.history = null; d.close(); await load(); toast(cache.error ? "已保存，但列表读取失败，请刷新列表，不要重复提交" : "已保存");
    } catch (error) { errorBox.textContent = error.message + (error.status === 409 ? "。当前输入已保留，请复制需要的内容后取消并重新打开最新记录。" : ""); errorBox.hidden = false; }
    finally { cache.busy = false; submit.disabled = false; submit.textContent = "保存"; repaint(); }
  });
  return { ensure() { if (location.hash === "#module/jobs" && !cache.data && !cache.loading && !cache.error) load(); } };
}
