/* 证据对照不等于能力评分；规则/统计永远可独立于模型使用。 */
import { api, escapeHtml as esc } from "./data.js?v=115";

const cache = { leads: null, profile: null, gap: null, lead: "", routeLoaded: "", weekly: null, day: "", loaded: false, weeklyLoaded: false, busy: false, error: "", weeklyError: "", model: false, chosen: new Set() };
let paint = () => {};
const priorities = { not_required: "原文明确不要求", preferred: "原文提及优先/加分", required: "原文要求", mentioned: "原文提及，需核对" };
const assessments = { evidence_supplied: "已有自填证据，仍需核实", declared_only: "已声明，但没有证据", not_in_profile: "资料未提供，不代表不会" };
const categories = { education: "学历", experience: "经验/年限", availability: "到岗/出勤", language: "语言", other: "其他" };
const button = (label, action, disabled = false) => `<button class="small-button" type="button" data-action="insight-${action}" ${cache.busy || disabled ? "disabled" : ""}>${esc(label)}</button>`;
const activeLead = () => cache.leads?.find((row) => row.id === cache.lead);
const routeLead = () => { const value = location.hash.split("/")[2] || ""; try { return decodeURIComponent(value); } catch { return value; } };

async function loadAnalysis() {
  if (cache.busy) return;
  cache.busy = true;
  const requested = routeLead();
  try {
    const [leads, profile, connection] = await Promise.all([api("jobs/leads"), api("jobs/profile"), api("model-connection").catch(() => ({ configured: false }))]);
    cache.leads = leads; cache.profile = profile; cache.model = connection.configured;
    const wanted = requested || cache.lead;
    if (requested && !leads.some((lead) => lead.id === requested)) throw new Error("指定岗位不存在或已归档，请回求职记录选择有效岗位。");
    cache.lead = leads.some((lead) => lead.id === wanted) ? wanted : leads[0]?.id || "";
    cache.gap = activeLead()?.data.jd_text ? await api(`jobs/leads/${cache.lead}/gap`) : null;
    cache.error = "";
  } catch (error) { cache.error = error.message; }
  finally { cache.busy = false; cache.loaded = true; cache.routeLoaded = requested; paint(); }
}
async function loadWeekly() {
  if (cache.busy) return;
  cache.busy = true;
  try {
    const [result, connection] = await Promise.all([api("jobs/report/weekly" + (cache.day ? "?day=" + encodeURIComponent(cache.day) : "")), api("model-connection").catch(() => ({ configured: false }))]);
    cache.weekly = result; cache.model = connection.configured; cache.weeklyError = "";
  } catch (error) { cache.weeklyError = error.message; }
  finally { cache.busy = false; cache.weeklyLoaded = true; paint(); }
}

export function jobInsightsView() {
  const head = '<div class="page-head"><h1>岗位证据对照</h1></div>';
  if (!cache.loaded || (routeLead() && routeLead() !== cache.routeLoaded)) return head + '<p role="status">正在读取岗位与私密证据资料…</p>';
  const toolbar = `<div class="jobs-toolbar">${button("编辑我的求职证据", "profile")}${button("刷新资料与分析", "reload")}<a class="small-button" href="#module/jobs">求职记录</a><a class="small-button" href="#module/job-weekly">求职周报</a></div>`;
  if (cache.error) return `${head}${toolbar}<p class="error-text" role="alert">${esc(cache.error)}</p>`;
  const lead = activeLead(), result = cache.gap?.analysis;
  return `${head}${toolbar}<p class="jobs-caption">资料保存在服务器 data/local 私密文件，不进入公共工作区备份，也不自动发送给模型。请另行保护个人资料。</p><label class="form-field">选择岗位<select id="insight-lead" aria-label="选择岗位">${(cache.leads || []).map((row) => `<option value="${esc(row.id)}" ${row.id === cache.lead ? "selected" : ""}>${esc(row.data.company)} / ${esc(row.data.title)}</option>`).join("")}</select></label>
    ${!lead ? '<section class="module-surface jobs-detail"><p>还没有岗位。先在求职记录中添加公司、岗位和 JD 原文。</p></section>' : `<section class="module-surface jobs-detail"><h2>${esc(lead.data.company)} / ${esc(lead.data.title)}</h2><p>岗位版本 v${lead.version}；自填技能 ${cache.profile.data.skills.length} 条，个人事实 ${cache.profile.data.facts.length} 条。</p><div class="jobs-actions">${button("保存离线规则分析", "rules", !lead.data.jd_text)}${button("模型补充分析（外发资料）", "model", !cache.model || !lead.data.jd_text)}${button("重新调用模型（可能收费）", "model-again", !cache.model || !lead.data.jd_text)}</div>${!lead.data.jd_text ? "<p>请先编辑岗位，粘贴完整 JD 原文。没有原文不会编造分析。</p>" : `<details><summary>完整 JD 原文</summary><pre class="jobs-prose">${esc(lead.data.jd_text)}</pre></details>`}</section>`}
    ${result ? `<section class="module-surface jobs-detail insight-analysis"><h2>原文要求与个人证据</h2><p>${cache.gap.stale ? '<strong class="error-text">岗位或资料已变化，这份冻结分析已过期，请重新分析。</strong>' : "该对照绑定当前岗位与资料版本。"} ${cache.gap.persisted ? "已留档" : "只读规则预览，尚未留档"}；${esc(cache.gap.status)}。</p>${cache.gap.status === "running" ? '<p class="error-text">上一次模型请求未完成记账，结果未知；不会自动重复调用。若核对后重试，请明确选择重新调用。</p>' : ""}<p>真实 JD 人工质量验收尚未完成；不提供录用概率或自动资格认定。</p><form id="gap-cards-form">${result.requirements.length ? result.requirements.map((item) => `<article class="insight-requirement"><h3>${esc(item.name)}</h3><p>${esc(priorities[item.priority])}；${esc(assessments[item.assessment])}</p><blockquote>${esc(item.quote)}</blockquote><small>原文字符区间 ${item.start}–${item.end}</small>${item.evidence.length ? `<ul>${item.evidence.map((e) => `<li>${esc(e.evidence || "尚未填写证据说明")}<br><small>${esc(e.reference || "尚未填写来源")}</small></li>`).join("")}</ul>` : ""}${item.assessment !== "evidence_supplied" && item.priority !== "not_required" ? `<label><input type="checkbox" name="candidate" value="${esc(item.name)}" ${cache.chosen.has(item.name) ? "checked" : ""} ${cache.gap.stale ? "disabled" : ""}>作为我选择的复习候选</label>` : ""}</article>`).join("") : "<p>规则词表没有提取到技术要求，请阅读完整 JD 或在确认后使用模型补充，不代表岗位没有要求。</p>"}<button class="small-button" type="submit" ${cache.busy || cache.gap.stale ? "disabled" : ""}>确认把选中项建为复习卡</button></form></section><section class="module-surface jobs-detail"><h2>硬性条件，需逐条核对</h2>${result.hard_conditions.length ? result.hard_conditions.map((item) => `<article class="insight-requirement"><h3>${esc(categories[item.category])}</h3><blockquote>${esc(item.quote)}</blockquote><p>${esc(priorities[item.priority])}；不自动判断是否满足。</p>${item.profile_facts.length ? `<ul>${item.profile_facts.map((fact) => `<li>${esc(fact.value)}<br><small>${esc(fact.evidence || "未填事实依据")}</small></li>`).join("")}</ul>` : "<p>当前没有对应个人事实，请人工补充核对。</p>"}</article>`).join("") : "<p>未提取到硬条件不代表没有限制，请核对完整原文。</p>"}<ul>${result.notes.map((note) => `<li>${esc(note)}</li>`).join("")}</ul></section>` : ""}`;
}

export function jobWeeklyView() {
  const head = '<div class="page-head"><h1>求职周报</h1></div>';
  const toolbar = `<form id="weekly-date-form" class="jobs-filter"><label>本周任意日期<input type="date" name="day" aria-label="本周任意日期" value="${esc(cache.day || cache.weekly?.current.week_start || "")}" required></label><button class="small-button" type="submit">查看这一周</button></form><div class="jobs-toolbar">${button("生成并保存纯统计周报", "weekly-save")}${button("模型排序关注项（仅外发统计）", "weekly-model", !cache.model)}${button("重新调用模型排序（可能收费）", "weekly-model-again", !cache.model)}${button("确认周报加入通知队列", "weekly-notify")}${button("下载已保存周报", "weekly-download", !cache.weekly?.saved)}${button("刷新统计", "weekly-reload")}</div>`;
  if (!cache.weekly) return `${head}${toolbar}<p role="${cache.weeklyError ? "alert" : "status"}">${esc(cache.weeklyError || "正在读取周统计…")}</p>`;
  const current = cache.weekly.current, metrics = current.metrics;
  const fields = [["applications_submitted", "本周投递"], ["interviews_recorded", "本周面试复盘"], ["cohort_interviewed", "投递组已记录面试"], ["reviews_recorded", "本周复习"], ["knowledge_added", "本周新增知识"], ["plan_completion_events", "规划完成事件"], ["followups_due", "当前待跟进"], ["reviews_due", "当前待复习"]];
  return `${head}${toolbar}${cache.weeklyError ? `<p class="error-text" role="alert">${esc(cache.weeklyError)}</p>` : ""}<section class="module-surface jobs-detail"><h2>${esc(current.week_start)} 起的一周</h2><p>统计截止 ${esc(current.as_of)}；无模型也可用，不自动外发。</p><dl class="jobs-facts">${fields.map(([key, label]) => `<dt>${label}</dt><dd data-metric="${key}">${metrics[key]}</dd>`).join("")}<dt>投递组累计进面率</dt><dd>${metrics.cohort_interview_rate === null ? "无分母，暂不计算" : Math.round(metrics.cohort_interview_rate * 10000) / 100 + "%"}</dd></dl><h3>当前管道分布（不是历史快照）</h3><pre class="jobs-prose">${esc(JSON.stringify(current.pipeline_current, null, 2))}</pre><h3>高频追问</h3><ul>${current.top_questions.map((item) => `<li>${esc(item.question)}（${item.count} 次复盘）</li>`).join("") || "<li>本周尚无已记录的问题。</li>"}</ul><h3>薄弱点</h3><ul>${current.top_weak_points.map((item) => `<li>${esc(item.point)}（${item.count} 次）</li>`).join("") || "<li>本周尚无薄弱点记录。</li>"}</ul><ul>${current.notes.map((note) => `<li>${esc(note)}</li>`).join("")}</ul></section>
    <section class="module-surface jobs-detail"><h2>已保存周报</h2>${cache.weekly.saved ? `<p>${cache.weekly.stale ? "当前数据已变化，下面是留档快照，不会静默覆盖。" : "快照对应当前数据版本。"} 方式：${esc(cache.weekly.saved.mode)}</p>${cache.weekly.saved.status === "running" ? '<p class="error-text">上次模型结果尚未记账，先使用统计，不会自动重发；需核对后明确重新调用。</p>' : ""}<pre class="jobs-prose">${esc(cache.weekly.saved.markdown)}</pre>` : "<p>尚未保存。查看统计是只读的，点击生成后才会留档。</p>"}</section>`;
}

export function jobProfileDialog() {
  return '<dialog class="form-dialog" data-form="job-profile" aria-labelledby="job-profile-title"><form id="job-profile-form" class="edit-form"><header class="drawer-header"><h2 id="job-profile-title">我的求职证据</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div id="job-profile-fields" class="drawer-content"></div></form></dialog>';
}
const input = (label, name, value, max = 1000) => `<label class="form-field">${label}<input name="${name}" value="${esc(value || "")}" maxlength="${max}"></label>`;
function skillRow(skill = {}) {
  return `<fieldset class="profile-skill"><legend>技能与实际证据</legend>${input("技能名称", "skill_name", skill.name, 80)}${input("实际做过什么", "skill_evidence", skill.evidence)}${input("证据来源（仅作文字，不自动读取）", "skill_reference", skill.reference, 500)}${button("移除此技能", "remove-skill")}</fieldset>`;
}
function factRow(fact = {}) {
  return `<fieldset class="profile-fact"><legend>需要核对的个人事实</legend><label class="form-field">类型<select name="fact_category" aria-label="事实类型">${Object.entries(categories).map(([key, label]) => `<option value="${key}" ${key === fact.category ? "selected" : ""}>${label}</option>`).join("")}</select></label>${input("个人事实（如学历/可到岗日期）", "fact_value", fact.value)}${input("事实依据", "fact_evidence", fact.evidence)}${button("移除此事实", "remove-fact")}</fieldset>`;
}

export function bindJobInsights({ renderPage, toast }) {
  paint = () => { if (location.hash.startsWith("#module/job-insights") || location.hash === "#module/job-weekly") renderPage({ restore: true }); };
  const dialog = () => document.querySelector('dialog[data-form="job-profile"]');
  document.addEventListener("change", (event) => {
    if (!(event.target instanceof Element)) return;
    if (event.target.id === "insight-lead") { cache.chosen.clear(); location.hash = "#module/job-insights/" + encodeURIComponent(event.target.value); }
    if (event.target.matches('#gap-cards-form [name="candidate"]')) event.target.checked ? cache.chosen.add(event.target.value) : cache.chosen.delete(event.target.value);
  });
  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const b = event.target.closest('[data-action^="insight-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(8);
    if (action === "remove-skill") return b.closest("fieldset").remove();
    if (action === "remove-fact") return b.closest("fieldset").remove();
    if (action === "add-skill") return document.getElementById("profile-skills").insertAdjacentHTML("beforeend", skillRow());
    if (action === "add-fact") return document.getElementById("profile-facts").insertAdjacentHTML("beforeend", factRow());
    if (action === "profile") {
      if (!cache.profile) { await loadAnalysis(); if (!cache.profile) return; }
      const data = cache.profile.data;
      dialog().dataset.revision = cache.profile.revision;
      document.getElementById("job-profile-fields").innerHTML = `${input("资料名称", "title", data.title, 160)}<p>只填写真实技能与可核对的事实，不填密码、令牌。资料不进入公共备份。</p><div id="profile-skills">${(data.skills.length ? data.skills : [{}]).map(skillRow).join("")}</div>${button("添加技能证据", "add-skill")}<div id="profile-facts">${data.facts.map(factRow).join("")}</div>${button("添加个人事实", "add-fact")}<p id="profile-form-error" class="error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存资料</button></div>`;
      dialog().showModal(); return;
    }
    if (action === "reload") return loadAnalysis();
    if (action === "weekly-reload") return loadWeekly();
    if (action === "weekly-download" && cache.weekly?.saved) {
      const url = URL.createObjectURL(new Blob([cache.weekly.saved.markdown], { type: "text/markdown;charset=utf-8" }));
      const link = document.createElement("a"); link.href = url; link.download = `shilie-week-${cache.weekly.saved.week_start}.md`; link.click(); setTimeout(() => URL.revokeObjectURL(url), 1000); return;
    }
    cache.busy = true; paint();
    try {
      if (["rules", "model", "model-again"].includes(action)) {
        const model = action !== "rules";
        if (model && !confirm("将完整岗位原文与自填证据资料发送给已配置模型？可能产生供应商费用；本次失败不会自动重试。")) return;
        if (action === "model-again" && !confirm("请先核对上次调用。重新调用可能重复付费；确定明确发起新的分析？")) return;
        cache.gap = await api(`jobs/leads/${cache.lead}/analyze`, { version: activeLead().version, profile_revision: cache.profile.revision, mode: model ? "model" : "rules", confirmation: model ? "发送岗位与资料进行分析" : "", request_id: action === "model-again" ? crypto.randomUUID() : "" });
        cache.chosen.clear(); toast(cache.gap.reused ? "已复用绑定相同资料的分析，未重复调用" : "分析已留档，请核对引用与硬条件");
      }
      if (["weekly-save", "weekly-model", "weekly-model-again", "weekly-notify"].includes(action)) {
        const model = ["weekly-model", "weekly-model-again"].includes(action);
        if (model && !confirm("只发送周报统计指标给已配置模型排序关注项？可能产生费用，不发送个人技能资料或面试原文。")) return;
        if (action === "weekly-model-again" && !confirm("核对上次模型调用后，明确发起新请求？可能重复产生费用。")) return;
        if (action === "weekly-notify" && !confirm("把纯统计周报加入本周通知队列？不会立即发送；重复操作复用原消息。")) return;
        await api("jobs/report/weekly" + (action === "weekly-notify" ? "/notify" : ""), { day: cache.day, mode: model ? "model" : "statistics", request_id: action === "weekly-model-again" ? crypto.randomUUID() : "", confirmation: action === "weekly-notify" ? "加入周报通知队列" : model ? "发送统计进行周报增强" : "生成并保存周报" });
        cache.weekly = await api("jobs/report/weekly" + (cache.day ? "?day=" + encodeURIComponent(cache.day) : "")); toast(action === "weekly-notify" ? "周报已入队，不代表已发送" : "周报已保存，统计口径已附在正文");
      }
    } catch (error) { toast(error.message, true); }
    finally { cache.busy = false; paint(); }
  });
  document.addEventListener("submit", async (event) => {
    if (!["job-profile-form", "gap-cards-form", "weekly-date-form"].includes(event.target.id)) return;
    event.preventDefault();
    if (cache.busy) return;
    const form = event.target;
    if (form.id === "weekly-date-form") { cache.day = new FormData(form).get("day"); return loadWeekly(); }
    if (form.id === "gap-cards-form") {
      const names = new FormData(form).getAll("candidate");
      if (!names.length) return toast("请勾选要复习的缺证据项；没有证据不等于不会。", true);
      if (!confirm(`确认把选中的 ${names.length} 项创建为复习卡？不会自动认定你不具备这些技能。`)) return;
      cache.busy = true; paint();
      try { const result = await api(`jobs/leads/${cache.lead}/learning-cards`, { version: cache.gap.lead_version, profile_revision: cache.gap.profile_revision, names, confirmation: "确认创建复习卡" }); toast(`新增 ${result.created.length} 张，复用 ${result.reused.length} 张`); }
      catch (error) { toast(error.message, true); }
      finally { cache.busy = false; paint(); }
      return;
    }
    const submit = form.querySelector('[type="submit"]'), errorBox = form.querySelector("#profile-form-error");
    cache.busy = true; submit.disabled = true; errorBox.hidden = true;
    try {
      const data = { title: form.querySelector('[name="title"]').value, skills: [], facts: [] };
      for (const row of form.querySelectorAll(".profile-skill")) {
        const item = { name: row.querySelector('[name="skill_name"]').value, evidence: row.querySelector('[name="skill_evidence"]').value, reference: row.querySelector('[name="skill_reference"]').value };
        if (Object.values(item).some((s) => s.trim())) data.skills.push(item);
      }
      for (const row of form.querySelectorAll(".profile-fact")) {
        const item = { category: row.querySelector('[name="fact_category"]').value, value: row.querySelector('[name="fact_value"]').value, evidence: row.querySelector('[name="fact_evidence"]').value };
        if (item.value.trim() || item.evidence.trim()) data.facts.push(item);
      }
      cache.profile = await api("jobs/profile", { revision: dialog().dataset.revision, data }, "PUT"); dialog().close(); cache.chosen.clear();
      cache.gap = activeLead()?.data.jd_text ? await api(`jobs/leads/${cache.lead}/gap`) : null; toast("资料已保存；已有分析的版本状态已重新核对");
    } catch (error) { errorBox.textContent = error.message + (error.status === 409 ? "；当前输入已保留，请核对最新资料。" : ""); errorBox.hidden = false; }
    finally { cache.busy = false; submit.disabled = false; paint(); }
  });
  return { ensure() { if (location.hash.startsWith("#module/job-insights") && (!cache.loaded || (routeLead() && routeLead() !== cache.routeLoaded)) && !cache.busy) loadAnalysis(); if (location.hash === "#module/job-weekly" && !cache.weeklyLoaded && !cache.busy) loadWeekly(); } };
}
