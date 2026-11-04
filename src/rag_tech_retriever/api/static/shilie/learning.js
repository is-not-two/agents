/* 到期复习与通知：确认、评分、队列状态均以服务端返回为准。 */
import { api, escapeHtml as esc } from "./data.js?v=109";

const cache = { cards: null, notifications: null, preview: null, error: "", noticeError: "", loading: false, noticeLoading: false, busy: false, trash: false, filter: "due", selected: "", revealed: new Set(), reviews: null, requests: new Map() };
let paint = () => {};
const grades = ["忘了", "困难", "记得", "熟练"];
const states = { pending: "等待发送", sending: "发送中", sent: "SMTP 已接受", failed: "失败", unknown: "结果未知", cancelled: "已取消" };
const date = (value) => value ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "未设置";
const button = (label, action, id = "", extra = "") => `<button type="button" class="small-button" data-action="learn-${action}" data-id="${esc(id)}" ${cache.busy ? "disabled" : ""} ${extra}>${esc(label)}</button>`;
const cardById = (id) => cache.cards?.cards.find((row) => row.id === id);
const local = (value) => { const d = new Date(value); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };

async function loadCards() {
  if (cache.loading) return;
  cache.loading = true;
  try {
    cache.cards = await api(`learning/cards?trash=${cache.trash}`); cache.error = "";
    for (const [id, request] of cache.requests) if (cardById(id)?.version !== request.version) cache.requests.delete(id);
  } catch (error) { cache.error = error.message; }
  finally { cache.loading = false; paint(); }
}
async function loadNotices() {
  if (cache.noticeLoading) return;
  cache.noticeLoading = true;
  try {
    [cache.notifications, cache.preview] = await Promise.all([api("notifications"), api("notifications/daily-preview")]); cache.noticeError = "";
  } catch (error) { cache.noticeError = error.message; }
  finally { cache.noticeLoading = false; paint(); }
}

export function learningView() {
  const head = `<div class="page-head"><h1>到期复习</h1></div><div class="jobs-toolbar">${button("添加复习卡", "new")}${button(cache.filter === "due" ? "查看全部卡片" : "只看到期卡片", "filter")}${button(cache.trash ? "返回有效卡片" : "卡片回收站", "trash")}${button("刷新", "reload")}<a class="small-button" href="#module/notifications">通知中心</a></div>`;
  if (!cache.cards) return `${head}<p role="${cache.error ? "alert" : "status"}">${esc(cache.error || "正在读取复习卡…")}</p>`;
  const cards = cache.cards.cards.filter((row) => cache.trash || cache.filter === "all" || cache.cards.due_ids.includes(row.id));
  const selected = cards.find((row) => row.id === cache.selected) || cards[0];
  const revealed = selected && cache.revealed.has(selected.id);
  const due = selected && cache.cards.due_ids.includes(selected.id) && !cache.trash;
  return `${head}${cache.error ? `<p class="error-text" role="alert">${esc(cache.error)}</p>` : ""}<p class="jobs-caption">${cache.cards.due_ids.length} 张到期，${cache.cards.cards.length} 张${cache.trash ? "已归档" : "有效"}卡片。先回忆，再显示答案并自评；漏答不会清零。</p><div class="jobs-layout learning-layout" aria-busy="${cache.busy || cache.loading}"><section class="module-surface jobs-list" aria-label="复习卡列表">${cards.length ? cards.map((row) => `<button type="button" class="jobs-row" data-action="learn-select" data-id="${esc(row.id)}" aria-pressed="${row.id === selected?.id}"><strong>${esc(row.data.title)}</strong><small>${row.data.paused ? "已暂停" : "下次复习：" + esc(date(row.data.due_at))}</small></button>`).join("") : `<p>${cache.trash ? "卡片回收站为空。" : "没有到期卡片。可以查看全部卡片，或从面试复盘勾选薄弱点并确认建卡。"}</p>`}</section>
    ${selected ? `<section class="module-surface jobs-detail learning-card" aria-label="当前复习卡"><p>${{ manual: "手工卡片", interview: "来自已确认的面试薄弱点", jd_gap: "来自已确认的 JD 缺口" }[selected.data.source]}</p><h2>${esc(selected.data.title)}</h2><p>下次复习 ${esc(date(selected.data.due_at))}；已掌握轮次 ${selected.data.repetitions}，当前间隔 ${selected.data.interval_days} 天。</p>
    ${cache.trash ? button("恢复卡片", "restore", selected.id) : `${button(revealed ? "收起答案" : "显示答案 / 资料引用", "reveal", selected.id)}${revealed ? `<pre class="jobs-prose learning-answer">${esc(selected.data.answer_ref || "尚未填写答案或资料引用，可先编辑补齐。")}</pre>` : ""}<div class="learning-grades" aria-label="复习自评">${grades.map((label, rating) => button(label, "grade", selected.id, `data-rating="${rating}" ${!revealed || !due || cache.busy ? "disabled" : ""}`)).join("")}</div>${!due ? "<p>此卡片尚未到期或已暂停，不会重复记录评分。</p>" : ""}<div class="jobs-actions">${button("编辑卡片", "edit", selected.id)}${button("归档卡片", "archive", selected.id)}</div>`}
    ${button("查看复习记录", "history", selected.id)}${cache.reviews?.id === selected.id ? `<section class="learning-history"><h3>复习记录</h3>${cache.reviews.rows.length ? cache.reviews.rows.map((row) => `<p>${esc(date(row.data.reviewed_at))}：${grades[row.data.rating]}；下次 ${esc(date(row.data.next_due_at))}</p>`).join("") : "<p>尚无复习记录。</p>"}</section>` : ""}</section>` : ""}</div>`;
}

export function notificationsView() {
  const head = `<div class="page-head"><h1>通知中心</h1></div><div class="jobs-toolbar">${button("刷新摘要与队列", "notice-reload")}<a class="small-button" href="#module/learning">回到复习</a></div>`;
  if (!cache.notifications || !cache.preview) return `${head}<p role="${cache.noticeError ? "alert" : "status"}">${esc(cache.noticeError || "正在读取通知状态…")}</p>`;
  const settings = cache.notifications.settings;
  return `${head}${cache.noticeError ? `<p class="error-text" role="alert">${esc(cache.noticeError)}</p>` : ""}<section class="module-surface jobs-detail"><h2>今日摘要预览</h2><pre class="jobs-prose">${esc(cache.preview.body)}</pre><p>${settings.enabled ? "通知外发已启用。" : "通知外发未启用，入队不会自动发送。"}${settings.configured ? "SMTP 配置字段已齐备，实际连接结果以发送记录为准。" : "尚未配置完整 SMTP。由部署人员设置环境变量，不在聊天或页面提交密码。"}</p><p>${esc(settings.delivery_semantics)}</p><div class="jobs-actions">${button("确认加入今日通知队列", "enqueue")}${button("确认发送待处理队列", "dispatch", "", !settings.enabled || !settings.configured || cache.busy ? "disabled" : "")}</div></section>
    <section class="module-surface jobs-detail"><h2>通知队列</h2>${cache.notifications.notifications.length ? cache.notifications.notifications.map((row) => `<article class="notice-row" data-notice-id="${esc(row.id)}"><h3>${esc(row.data.title)}</h3><p><strong>${row.data.status === "sent" && !row.data.smtp_accepted ? "人工核对已收到" : esc(states[row.data.status] || row.data.status)}</strong>；尝试 ${row.data.attempts} 次</p><p class="${row.data.status === "unknown" || row.data.status === "failed" ? "error-text" : ""}">${esc(row.data.last_error || row.data.resolution || "")}</p><details><summary>查看冻结的消息正文</summary><pre class="jobs-prose">${esc(row.data.body)}</pre></details><div class="jobs-actions">${["failed", "unknown"].includes(row.data.status) ? button("核对未发送后重试", "resolve", row.id, 'data-decision="retry"') : ""}${row.data.status === "unknown" ? button("人工核对已收到", "resolve", row.id, 'data-decision="received"') : ""}${["pending", "failed"].includes(row.data.status) ? button("取消待发通知", "resolve", row.id, 'data-decision="cancel"') : ""}</div></article>`).join("") : "<p>队列为空。预览是只读的，只有明确确认才会加入队列。</p>"}</section>`;
}

export function learningDialogs() {
  return '<dialog class="form-dialog" data-form="learning" aria-labelledby="learning-dialog-title"><form class="edit-form" id="learning-form"><header class="drawer-header"><h2 id="learning-dialog-title">复习卡</h2><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content" id="learning-form-body"></div></form></dialog>';
}

export function bindLearning({ renderPage, toast }) {
  paint = () => { if (["#module/learning", "#module/notifications"].includes(location.hash)) renderPage({ restore: true }); };
  const dialog = () => document.querySelector('dialog[data-form="learning"]');
  function openCard(row = null) {
    const d = dialog(), data = row?.data || {};
    d.dataset.learningMode = "card"; d.dataset.recordId = row?.id || ""; d.dataset.version = row?.version || "";
    document.getElementById("learning-dialog-title").textContent = row ? "编辑复习卡" : "添加复习卡";
    document.getElementById("learning-form-body").innerHTML = `<label class="form-field">复习问题<input name="title" required maxlength="1000" value="${esc(data.title)}"></label><label class="form-field">答案或资料引用<textarea name="answer_ref" rows="5" maxlength="10000">${esc(data.answer_ref)}</textarea></label><label class="form-field">复习时间<input name="due_at" type="datetime-local" required value="${local(data.due_at || new Date().toISOString())}"></label><label><input name="paused" type="checkbox" ${data.paused ? "checked" : ""}>暂停此卡片</label>${formEnd("保存")}`;
    d.showModal(); d.querySelector('[name="title"]').focus();
  }
  function formEnd(text) { return `<p id="learning-form-error" class="error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button class="primary-button" type="submit">${text}</button></div>`; }
  async function openCandidate(id) {
    const source = await api(`jobs/reports/${id}`);
    const d = dialog();
    d.dataset.learningMode = "candidate"; d.dataset.recordId = id; d.dataset.version = source.version;
    document.getElementById("learning-dialog-title").textContent = "选择并确认创建复习卡";
    document.getElementById("learning-form-body").innerHTML = `<p>${esc(source.data.title)}，来源版本 v${source.version}。只有勾选并确认的薄弱点会保存为卡片。</p><div class="learning-candidates">${source.data.weak_points.map((point) => `<label><input type="checkbox" name="point" value="${esc(point)}">${esc(point)}</label>`).join("")}</div><p>不会把全部复盘或私密内容自动记入长期记忆。</p>${formEnd("确认创建复习卡")}`;
    d.showModal();
  }
  document.addEventListener("click", async (event) => {
    if (!(event.target instanceof Element)) return;
    const b = event.target.closest('[data-action^="learn-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(6), row = cardById(b.dataset.id);
    if (action === "new") return openCard();
    if (action === "edit" && row) return openCard(row);
    if (action === "select" && row) { cache.selected = row.id; cache.reviews = null; paint(); return; }
    if (action === "reveal" && row) { cache.revealed.has(row.id) ? cache.revealed.delete(row.id) : cache.revealed.add(row.id); paint(); return; }
    if (action === "filter") { cache.filter = cache.filter === "due" ? "all" : "due"; paint(); return; }
    cache.busy = true; paint();
    try {
      if (action === "candidate") await openCandidate(b.dataset.id);
      if (action === "trash") { cache.trash = !cache.trash; cache.selected = ""; cache.reviews = null; await loadCards(); }
      if (action === "reload") await loadCards();
      if (action === "notice-reload") await loadNotices();
      if (action === "history" && row) cache.reviews = { id: row.id, rows: await api(`learning/cards/${row.id}/reviews`) };
      if (action === "grade" && row) {
        const rating = Number(b.dataset.rating);
        let request = cache.requests.get(row.id);
        if (request && request.rating !== rating) throw new Error("上一评分结果尚未确认，请先刷新核对，不能改评分盲目重发。");
        request ||= { version: row.version, rating, request_id: crypto.randomUUID() };
        cache.requests.set(row.id, request);
        const result = await api(`learning/cards/${row.id}/review`, request);
        cache.requests.delete(row.id); cache.revealed.delete(row.id); cache.reviews = null;
        await loadCards(); toast(`已记录复习，下次 ${date(result.card.data.due_at)}`);
      }
      if (action === "archive" && row && confirm("归档此卡片？复习记录仍会保留。")) { await api(`records/${row.id}?version=${row.version}`, undefined, "DELETE"); await loadCards(); }
      if (action === "restore" && row && confirm("将卡片历史恢复为新版本？")) {
        const history = await api(`records/${row.id}/history`), target = history.find((v) => !v.deleted);
        if (!target) throw new Error("没有有效历史可恢复");
        await api(`records/${row.id}/restore`, { target_version: target.version, current_version: row.version }); await loadCards();
      }
      if (action === "enqueue" && confirm("将当前摘要加入今日通知队列？这不会立即发送，同日重复操作会复用原记录。")) {
        const result = await api("notifications/daily", { confirmation: "加入通知队列" }); await loadNotices(); toast(result.reused ? "已复用今日通知，没有重复入队" : "已入队，尚未发送");
      }
      if (action === "dispatch" && confirm("向已配置的私人收件箱发送待处理队列？SMTP 接受不代表手机已收到。")) { await api("notifications/dispatch", { confirmation: "发送通知" }); await loadNotices(); toast("本批发送已处理，请核对每条状态"); }
      if (action === "resolve") {
        const notice = cache.notifications.notifications.find((n) => n.id === b.dataset.id);
        const confirmation = prompt("请先核对真实发送结果。若未发送可重试；未知结果重试可能重复通知。请输入：已核对通知结果");
        if (confirmation !== "已核对通知结果") return;
        await api(`notifications/${notice.id}/resolve`, { version: notice.version, action: b.dataset.decision, confirmation }); await loadNotices();
      }
    } catch (error) { toast(error.message, true); }
    finally { cache.busy = false; paint(); }
  });
  document.addEventListener("submit", async (event) => {
    if (event.target.id !== "learning-form") return;
    event.preventDefault();
    if (cache.busy) return;
    const form = event.target, d = dialog(), submit = form.querySelector('[type="submit"]'), errorBox = form.querySelector("#learning-form-error");
    cache.busy = true; submit.disabled = true; errorBox.hidden = true;
    try {
      if (d.dataset.learningMode === "candidate") {
        const points = new FormData(form).getAll("point");
        if (!points.length) throw new Error("请勾选至少一条薄弱点，再确认创建。");
        const result = await api(`learning/from-interview/${d.dataset.recordId}`, { version: Number(d.dataset.version), points, confirmation: "确认创建复习卡" });
        d.close(); cache.cards = null; cache.error = ""; toast(`新增 ${result.created.length} 张，复用 ${result.reused.length} 张；可到复习页查看`);
      } else {
        const raw = new FormData(form), id = d.dataset.recordId;
        const data = { title: raw.get("title"), answer_ref: raw.get("answer_ref"), due_at: new Date(raw.get("due_at")).toISOString(), paused: raw.has("paused") };
        const row = await api(`learning/cards${id ? "/" + id : ""}`, { data, ...(id ? { version: Number(d.dataset.version) } : {}) }, id ? "PUT" : "POST");
        cache.selected = row.id; d.close(); await loadCards(); toast("复习卡已保存");
      }
    } catch (error) { errorBox.textContent = error.message + (error.status === 409 ? "；当前输入已保留，请核对最新版本。" : ""); errorBox.hidden = false; }
    finally { cache.busy = false; submit.disabled = false; paint(); }
  });
  return { ensure() { if (location.hash === "#module/learning" && !cache.cards && !cache.loading && !cache.error) loadCards(); if (location.hash === "#module/notifications" && !cache.notifications && !cache.noticeLoading && !cache.noticeError) loadNotices(); } };
}
