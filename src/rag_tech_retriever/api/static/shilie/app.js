import { bindCollaboration } from "./collaboration.js?v=119";
import { watchDraft, markDraftClean, allowDraftClose, allowDraftNavigation, setDraftSaving } from "./draft-guard.js?v=119";
import { bindAgentStudio } from "./agent-studio.js?v=119";
import { bindBackup } from "./backup.js?v=119";
import {
  bindPrivate,
  setPrivateRepaint,
  bindSlide,
} from "./private-view.js?v=119";
import { bindModelConnection } from "./model-connection.js?v=119";
import { bindTree } from "./tree-actions.js?v=119";
import { bindAutomation } from "./automation-actions.js?v=119";
import { bindLessons } from "./lessons.js?v=119";
import { bindJobs } from "./jobs.js?v=119";
import { bindCapabilities } from "./company-capabilities.js?v=119";
import { bindLearning } from "./learning.js?v=119";
import { bindJobInsights } from "./job-insights.js?v=119";
import { bindServerStatus } from "./server-status.js?v=119";
import { bindEvaluation } from "./evaluation.js?v=119";
import { startTour } from "./tour.js?v=119";
import { toggleDirector, directorActive } from "./director.js?v=119";
import { initMotion } from "./motion.js?v=119";
import { initOrbit } from "./orbit.js?v=119";
import { refreshTemporalCanvas } from "./temporal-webgl.js?v=119";
import {
  api,
  state,
  load,
  write,
  read,
  modules,
  groups,
  currentNote,
  escapeHtml,
} from "./data.js?v=119";
import {
  render,
  sidebar,
  dialogs,
  knowledgePanelHtml,
} from "./views.js?v=119";
const $ = (s) => document.querySelector(s),
  navigationStrip = $("#navigation-strip"),
  content = $("#content"),
  stack = [location.hash || "#home"],
  scrolls = new Map(
    Object.entries(state.visits).filter(
      ([, value]) => Number.isFinite(value) && value >= 0,
    ),
  ),
  toastBox = $("#toast");
document.querySelector(".skip-to-content")?.addEventListener("click", (event) => {
  event.preventDefault();
  content.focus();
});
toastBox.id = "toast";
toastBox.className = "toast";
toastBox.hidden = true;
toastBox.setAttribute("role", "status");
let modelConnectionController,
  backupController,
  lessonsController,
  jobsController,
  capabilitiesController,
  learningController,
  jobInsightsController,
  serverStatusController,
  evaluationController;
let toastTimer,
  detailTrigger = null,
  editingId = "",
  working = false,
  pendingBack = false,
  paintedRoute = location.hash || "#home";
document.body.insertAdjacentHTML("beforeend", dialogs());
function toast(message, error = false) {
  toastBox.textContent = message;
  toastBox.classList.toggle("error-text", error);
  toastBox.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => (toastBox.hidden = true), 4200);
}
window.addEventListener("shilie:entered-workspace", () => toast("已进入工作台"));
function persistRoute() {
  write("note", state.selectedNote);
  write("plan", state.selectedPlan);
  write("taskStatus", state.taskStatus);
  write("filter", state.filter);
  write("query", state.query);
  write("view", state.view);
  write("recent", state.recent);
  write("visits", state.visits);
}
function updatePosition() {
  const [kind, id] = location.hash.slice(1).split("/"),
    module = modules.find((m) => m.id === id),
    group = groups.find((g) => g.id === (module?.group || id)),
    nav = $("#position");
  nav.replaceChildren();
  const link = (label, href) => {
    const a = document.createElement("a");
    a.href = href;
    a.textContent = label;
    nav.append(a);
  };
  /* 首页分两层：开始页（环轨）与工作台。这里的 id 不能交给 groups 匹配，
     否则 `#home/workspace` 会被当成 `#category/workspace` 显示成两个“工作区”。 */
  if (kind === "home") {
    if (id === "workspace") {
      link("开始页", "#home");
      nav.append("›", "工作台");
    }
    return;
  }
  if (module) {
    link("工作区", "#home");
    nav.append("›");
    link(group.title, "#category/" + group.id);
    nav.append("›", module.title);
  } else if (group) {
    link("工作区", "#home");
    nav.append("›", group.title);
  }
}
function paintSidebar() {
  $("#sidebar").innerHTML = sidebar();
  /* 回收站入口在侧栏底部：展开后把入口对齐到侧栏顶部，
     让按钮和最新条目一起进入视口，而不是滚到列表最末端。 */
  if (state.trashOpen)
    requestAnimationFrame(() => {
      const bar = $("#sidebar"),
        section = bar?.querySelector(".sidebar-trash");
      if (bar && section)
        bar.scrollTop +=
          section.getBoundingClientRect().top - bar.getBoundingClientRect().top;
    });
}
function renderPage({ restore = false } = {}) {
  document.documentElement.dataset.layout = state.mode;
  document.documentElement.dataset.density =
    ["compact", "standard", "comfortable"][state.density] || "standard";
  document.documentElement.dataset.hero = state.compactHero
    ? "compact"
    : "full";
  document.body.dataset.layout = state.mode;
  const moduleId = location.hash.split("/")[1];
  content.dataset.module = location.hash.startsWith("#module/") ? moduleId : "";
  /* 首页两层：`#home` 开始页（环轨）、`#home/workspace` 工作台。
     只有真正跨层跳转时才播放入场过渡；同层刷新/重绘不闪。 */
  const route = location.hash || "#home";
  const homeLayer = route === "#home" || route === "#home/workspace";
  const enteringHomeLayer = route !== paintedRoute && homeLayer;
  const cameFromStart = paintedRoute === "#home" && route === "#home/workspace";
  paintedRoute = route;
  if (
    location.hash.startsWith("#module/") &&
    modules.some((m) => m.id === moduleId)
  )
    state.recent = [
      moduleId,
      ...state.recent.filter((id) => id !== moduleId),
    ].slice(0, 4);
  content.innerHTML = render();
  content.prepend(navigationStrip);
  if (moduleId === "documents" && state.searchResult?.hits?.length) {
    const list = content.querySelector(".result-list");
    if (list) {
      const visual = document.createElement("div");
      visual.className = "search-space";
      visual.setAttribute("aria-hidden", "true");
      visual.dataset.hits = String(state.searchResult.hits.length);
      list.before(visual);
    }
  }
  /* 首页环轨：内容已落地，交给 orbit.js 接管角度与交互（非首页时内部直接返回）。 */
  initOrbit();
  refreshTemporalCanvas();
  modelConnectionController?.ensure();
  backupController?.ensure();
  lessonsController?.ensure();
  jobsController?.ensure();
  capabilitiesController?.ensure();
  learningController?.ensure();
  jobInsightsController?.ensure();
  serverStatusController?.ensure();
  evaluationController?.ensure();
  bindSlide();
  navigationStrip.hidden = !location.hash || homeLayer;
  /* 移动端底部导航高亮：模块子页（如 #module/knowledge/notes）也算命中父模块。 */
  document.querySelectorAll(".mobile-nav a").forEach((a) => {
    const target = a.getAttribute("href");
    const current =
      location.hash === target ||
      (target.startsWith("#module/") && location.hash.startsWith(target + "/"));
    a.setAttribute("aria-current", current ? "page" : "false");
  });
  paintSidebar();
  document
    .querySelectorAll("button[data-mode]")
    .forEach((b) =>
      b.setAttribute("aria-pressed", String(b.dataset.mode === state.mode)),
    );
  document.title =
    route === "#home/workspace"
      ? "工作台 · 时列"
      : route === "#home"
        ? "开始 · 时列"
        : (modules.find((m) => m.id === moduleId)?.title || "工作区") +
          " · 时列";
  if (!restore) window.scrollTo(0, 0);
  if (enteringHomeLayer) {
    /* 跨层跳转：开始页 ↔ 工作台各给一次 260ms 入场，同层重绘不闪。 */
    content.classList.remove("page-enter");
    void content.offsetWidth;
    content.classList.add("page-enter");
  }
  if (cameFromStart)
    requestAnimationFrame(() => {
      document.querySelector("#home-main")?.focus({ preventScroll: true });
    });
  persistRoute();
}
let knowledgeTimer;
function scheduleKnowledgePanel() {
  clearTimeout(knowledgeTimer);
  knowledgeTimer = setTimeout(() => {
    write("query", state.query);
    const panel = $("#knowledge-panel");
    if (panel) panel.innerHTML = knowledgePanelHtml();
  }, 120);
}
function go(route) {
  if (!route.startsWith("#")) route = "#" + route;
  location.hash = route;
}
/* 路由回退表：特殊模块只在此登记，back() 里不再散落 if 特判。 */
const BACK_ROUTES = {
  "module/planning": "#category/workspace",
};
function back() {
  const [kind, id, sub] = location.hash.slice(1).split("/");
  if (kind === "module" && sub) {
    go(`#module/${id}`);
    return;
  }
  if (kind === "module") {
    const forced = BACK_ROUTES[`module/${id}`];
    if (forced) {
      go(forced);
      return;
    }
    const m = modules.find((x) => x.id === id);
    go(m ? `#category/${m.group}` : "#home");
    return;
  }
  go("#home");
}
function showDialog(kind, values = {}, id = "") {
  const d = document.querySelector(`.form-dialog[data-form="${kind}"]`);
  if (!d) {
    toast("找不到对应表单", true);
    return;
  }
  const form = d.querySelector("form");
  form.reset();
  editingId = id;
  d.dataset.recordId = id;
  for (const [key, value] of Object.entries(values)) {
    const field = form.elements.namedItem(key);
    if (!field) continue;
    if (field instanceof HTMLSelectElement && field.multiple) {
      [...field.options].forEach(
        (o) => (o.selected = (value || []).includes(o.value)),
      );
    } else field.value = value ?? "";
  }
  watchDraft(d);
  d.showModal();
  d.querySelector("input,textarea,select")?.focus();
}
function closeDialogs() {
  document.querySelectorAll("dialog[open]").forEach((d) => {
    if (allowDraftClose(d)) d.close();
  });
}
function showDetail(title, contentHtml, trigger = null) {
  const d = $("#detail-dialog");
  detailTrigger = trigger || document.activeElement;
  $("#detail-title").textContent = title;
  $("#detail-content").innerHTML = contentHtml;
  d.showModal();
  $("#detail-close").focus();
}
async function refresh(keepScroll = true) {
  const y = window.scrollY;
  try {
    await load();
    renderPage({ restore: true });
    if (keepScroll) window.scrollTo(0, y);
  } catch (e) {
    state.loading = false;
    state.error = e.message;
    renderPage();
  }
}
async function refreshKnowledge() {
  /* 知识写操作只刷新受影响集合与统计，不再重拉规划/求职/Agent 等 7 个接口。 */
  const y = window.scrollY;
  try {
    const [knowledge, status] = await Promise.all([
      api("knowledge"),
      api("status"),
    ]);
    Object.assign(state, { knowledge, status });
    renderPage({ restore: true });
    window.scrollTo(0, y);
  } catch (e) {
    state.loading = false;
    state.error = e.message;
    renderPage();
  }
}
async function refreshBookmarks() {
  /* 收藏写操作只重拉收藏集合，分类 chips 与列表按新数据重算。 */
  const y = window.scrollY;
  try {
    Object.assign(state, { bookmarks: await api("bookmarks") });
    renderPage({ restore: true });
    window.scrollTo(0, y);
  } catch (e) {
    toast(e.message, true);
  }
}
function restoreNote() {
  const row = currentNote();
  if (row)
    showDialog(
      "knowledge",
      {
        title: row.data.title,
        content: row.data.content,
        tags: (row.data.tags || []).join(", "),
        source: row.data.source || "",
      },
      row.id,
    );
}
function openHistory() {
  const row = currentNote();
  if (!row) return;
  api(`records/${row.id}/history`)
    .then((rows) => {
      const html = rows
        .map(
          (r) =>
            `<details class="history-entry"><summary>版本 ${r.version} · ${escapeHtml(r.action)} · ${escapeHtml(r.created_at)}</summary><h3>${escapeHtml(r.data.title)}</h3><p>${escapeHtml(r.data.content)}</p>${r.version !== row.version ? `<button class="small-button" data-action="restore-note" data-version="${r.version}">恢复此版本</button>` : ""}</details>`,
        )
        .join("");
      showDetail("笔记历史", html);
    })
    .catch((e) => toast(e.message, true));
}
function openStageFinish(id) {
  const rec = state.stages.find((s) => s.id === id);
  if (!rec) return;
  const d = $("#detail-dialog");
  detailTrigger = document.activeElement;
  $("#detail-title").textContent = "完成阶段记录";
  $("#detail-content").innerHTML =
    `<form id="finish-stage-form"><label class="form-field">完成内容<textarea name="completed" rows="5" placeholder="每行一项"></textarea></label><label class="form-field">问题与遗留<textarea name="issues" rows="4" placeholder="每行一项"></textarea></label><label class="form-field">验证记录<textarea name="verification" rows="4" placeholder="填写检查方式和结果；选择通过时必须填写"></textarea></label><label class="form-field">状态<select name="status"><option value="passed">验证通过</option><option value="attention">仍需处理</option></select></label><div class="form-actions"><button class="primary-button">保存阶段结果</button></div></form>`;
  d.dataset.finishId = id;
  d.showModal();
}
function listText(form, name) {
  return String(form.elements.namedItem(name).value || "")
    .split(/\n/)
    .map((x) => x.trim())
    .filter(Boolean);
}
function showFormError(form, message = "") {
  let node = form.querySelector(".form-error");
  if (!message) {
    node?.remove();
    return;
  }
  if (!node) {
    node = document.createElement("p");
    node.className = "form-error error-text";
    node.setAttribute("role", "alert");
    const actions = form.querySelector(".form-actions");
    if (actions) actions.before(node);
    else form.append(node);
  }
  node.textContent = message;
}
function showConflict(error) {
  showDetail(
    "保存冲突",
    `<p>${escapeHtml(error.message)}</p><p>你的输入没有被覆盖。加载最新版本后重新编辑，避免把旧内容写回去。</p><div class="form-actions"><button class="primary-button" data-action="reload-conflict">加载最新版本</button><button class="small-button" data-action="close-dialog">保留当前输入</button></div>`,
  );
}
async function saveForm(form) {
  if (working) return;
  working = true;
  setDraftSaving(form.closest("dialog"), true);
  showFormError(form);
  const submit = form.querySelector("[type=submit]");
  if (submit) {
    submit.disabled = true;
    submit.textContent = "保存中…";
  }
  try {
    const d = form.closest("dialog"),
      kind = d.dataset.form,
      fd = new FormData(form);
    const knowledgeOnly = kind === "knowledge";
    const bookmarkOnly = kind === "bookmark";
    if (knowledgeOnly) {
      const data = {
        title: fd.get("title"),
        content: fd.get("content"),
        tags: String(fd.get("tags"))
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        source: fd.get("source"),
      };
      const row = editingId
        ? state.knowledge.find((n) => n.id === editingId)
        : null;
      const saved = await api(
        editingId ? `knowledge/${editingId}` : "knowledge",
        { data, ...(row ? { version: row.version } : {}) },
        editingId ? "PUT" : "POST",
      );
      state.selectedNote = saved.id;
      state.filter = "all";
      state.query = "";
      toast("笔记已保存");
    } else if (bookmarkOnly) {
      const data = {
        title: fd.get("title"),
        url: fd.get("url"),
        category: fd.get("category"),
        tags: String(fd.get("tags"))
          .split(",")
          .map((x) => x.trim())
          .filter(Boolean),
        note: fd.get("note"),
      };
      const row = editingId
        ? state.bookmarks.find((b) => b.id === editingId)
        : null;
      await api(
        editingId ? `bookmarks/${editingId}` : "bookmarks",
        { data, ...(row ? { version: row.version } : {}) },
        editingId ? "PUT" : "POST",
      );
      toast("收藏已保存");
    } else if (kind === "stage") {
      const created = await api("stages", {
        title: fd.get("title"),
        objective: fd.get("objective"),
      });
      toast("阶段已创建，可以继续记录");
    }
    markDraftClean(d);
    setDraftSaving(d, false);
    if (knowledgeOnly) {
      await refreshKnowledge();
      document.dispatchEvent(new CustomEvent("shilie:semantic-effect", {
        detail: { name: "knowledge-saved", id: state.selectedNote },
      }));
    }
    else if (bookmarkOnly) await refreshBookmarks();
    else await refresh();
    closeDialogs();
  } catch (e) {
    if (e.code === "VERSION_CONFLICT") {
      showFormError(form, e.message);
      showConflict(e);
    } else {
      showFormError(form, e.message);
      toast(e.message, true);
    }
  } finally {
    working = false;
    setDraftSaving(form.closest("dialog"), false);
    if (submit) {
      submit.disabled = false;
      submit.textContent = "保存";
    }
  }
}
let searchRequestSequence = 0;
async function submitSearch(form) {
  if (state.searchBusy) return;
  const fd = new FormData(form),
    query = String(fd.get("query")),
    scope = String(fd.get("scope")),
    namespace = fd.get("namespace") || null,
    generate = fd.has("generate");
  if (!query.trim()) {
    Object.assign(state, {
      searchInput: query,
      scope,
      generate,
      searchError: "请输入查询内容",
    });
    renderPage({ restore: true });
    return;
  }
  Object.assign(state, {
    searchInput: query,
    scope,
    namespace,
    generate,
    searchBusy: true,
    searchError: "",
  });
  const requestId = ++searchRequestSequence;
  document.dispatchEvent(new CustomEvent("shilie:search-started", { detail: { requestId } }));
  let succeeded = false;
  try {
    renderPage({ restore: true });
    state.searchResult = await api("query", {
      query,
      scope,
      mode: "text",
      generate,
      namespace,
    });
    state.searchResultQuery = query;
    state.runs = [query, ...state.runs].slice(0, 10);
    succeeded = true;
  } catch (error) {
    state.searchError = error.message;
  } finally {
    state.searchBusy = false;
    if (location.hash.startsWith("#module/documents"))
      renderPage({ restore: true });
    document.dispatchEvent(new CustomEvent("shilie:search-finished", {
      detail: { requestId, ok: succeeded, error: state.searchError },
    }));
  }
}
/* 个人工作台提示词优化：只改写草稿，必须由用户点「应用」才写回输入框。 */
async function optimizePrompt() {
  const draft = $("#prompt-draft"),
    button = document.querySelector('[data-action="optimize-prompt"]'),
    status = $("#prompt-status"),
    result = $("#prompt-result"),
    optimized = $("#prompt-optimized");
  if (!draft || !button || !status || !result || !optimized) return;
  const text = draft.value.trim();
  if (!text) {
    toast("先写下需要优化的提示词", true);
    draft.focus();
    return;
  }
  button.disabled = true;
  status.textContent = "正在优化…";
  result.hidden = true;
  try {
    const data = await api("prompt/optimize", { text, target: "workspace" });
    optimized.value = data.optimized;
    result.hidden = false;
    status.textContent = data.usage?.total_tokens
      ? `已完成 · ${data.usage.total_tokens} tokens`
      : "已完成";
  } catch (error) {
    status.textContent = error.message;
    toast(error.message, true);
  } finally {
    button.disabled = false;
  }
}
function applyOptimizedPrompt() {
  const draft = $("#prompt-draft"),
    optimized = $("#prompt-optimized"),
    result = $("#prompt-result"),
    status = $("#prompt-status");
  if (!draft || !optimized || !result) return;
  draft.value = optimized.value.trim();
  result.hidden = true;
  if (status) status.textContent = "已应用到草稿";
  draft.focus();
}
function dismissOptimizedPrompt() {
  const result = $("#prompt-result"),
    status = $("#prompt-status");
  if (result) result.hidden = true;
  if (status) status.textContent = "";
}
async function finishStage(form) {
  if (form.dataset.saving === "true") return;
  const id = $("#detail-dialog").dataset.finishId,
    button = form.querySelector("button");
  const data = {
    completed: listText(form, "completed"),
    issues: listText(form, "issues"),
    verification: listText(form, "verification"),
    status: form.elements.status.value,
  };
  form.dataset.saving = "true";
  form.setAttribute("aria-busy", "true");
  button.disabled = true;
  button.textContent = "保存中…";
  try {
    await api(`stages/${id}/finish`, data);
    $("#detail-dialog").close();
    await refresh();
    toast("阶段结果已保存");
  } catch (error) {
    toast(error.message, true);
  } finally {
    form.dataset.saving = "false";
    form.setAttribute("aria-busy", "false");
    button.disabled = false;
    button.textContent = "保存阶段结果";
  }
}
async function restoreNoteVersion(version) {
  const row = currentNote();
  if (!row) return;
  try {
    await api(`records/${row.id}/restore`, {
      target_version: Number(version),
      current_version: row.version,
    });
    $("#detail-dialog").close();
    await refreshKnowledge();
    toast("已恢复此版本，旧历史已保留");
  } catch (e) {
    toast(e.message, true);
  }
}
function handleAction(button) {
  const owner = button.closest("[data-plan-id]");
  if (owner) state.selectedPlan = owner.dataset.planId;
  const { action, id, value } = button.dataset;
  switch (action) {
    case "back":
      back();
      break;
    case "new-note": {
      document.querySelector(
        '.form-dialog[data-form="knowledge"] h2',
      ).textContent = "新建笔记";
      editingId = "";
      showDialog("knowledge");
      break;
    }
    case "edit-note":
      document.querySelector(
        '.form-dialog[data-form="knowledge"] h2',
      ).textContent = "编辑笔记";
      restoreNote();
      break;
    case "select-note":
      state.selectedNote = id;
      renderPage({ restore: true });
      break;
    case "clear-search":
      state.query = "";
      renderPage({ restore: true });
      break;
    case "history-note":
      openHistory();
      break;
    case "delete-note": {
      const row = currentNote();
      if (row && confirm(`将“${row.data.title}”移入回收站？`))
        api(`records/${row.id}?version=${row.version}`, undefined, "DELETE")
          .then(async () => {
            state.selectedNote = "";
            await refreshKnowledge();
            toast("已移入回收站");
          })
          .catch((e) => toast(e.message, true));
      break;
    }
    case "new-bookmark":
      document.querySelector(
        '.form-dialog[data-form="bookmark"] h2',
      ).textContent = "新建收藏";
      editingId = "";
      showDialog("bookmark");
      break;
    case "edit-bookmark": {
      const row = state.bookmarks.find((b) => b.id === id);
      if (!row) break;
      document.querySelector(
        '.form-dialog[data-form="bookmark"] h2',
      ).textContent = "编辑收藏";
      showDialog(
        "bookmark",
        {
          title: row.data.title,
          url: row.data.url,
          category: row.data.category === "未分类" ? "" : row.data.category,
          tags: (row.data.tags || []).join(", "),
          note: row.data.note || "",
        },
        row.id,
      );
      break;
    }
    case "delete-bookmark": {
      const row = state.bookmarks.find((b) => b.id === id);
      if (row && confirm(`将“${row.data.title}”移入回收站？`))
        api(`records/${row.id}?version=${row.version}`, undefined, "DELETE")
          .then(async () => {
            await refreshBookmarks();
            toast("已移入回收站");
          })
          .catch((e) => toast(e.message, true));
      break;
    }
    case "bookmark-category":
      state.bookmarkFilter = value || "全部";
      write("bookmarkFilter", state.bookmarkFilter);
      renderPage({ restore: true });
      break;
    case "bookmark-trash":
      openBookmarkTrash();
      break;
    case "restore-bookmark-trash":
      restoreBookmarkTrash(id);
      break;
    case "filter":
      state.filter = value;
      renderPage({ restore: true });
      break;
    case "refresh":
      refresh();
      break;
    case "new-stage":
      document.querySelector('.form-dialog[data-form="stage"] h2').textContent =
        "记录新阶段";
      showDialog("stage");
      break;
    case "finish-stage":
      openStageFinish(id);
      break;
    case "close-dialog":
      if (allowDraftClose(button.closest("dialog"))) button.closest("dialog").close();
      break;
    case "reload-conflict":
      closeDialogs();
      refresh().then(() => toast("已加载最新版本，请重新编辑"));
      break;
    case "related-note":
      state.selectedNote = button.dataset.id;
      renderPage({ restore: true });
      break;
    case "retry":
      refresh(false);
      break;
    case "quick":
      openQuick();
      break;
    case "trash-notes":
      openTrash();
      break;
    case "trash-toggle":
      toggleTrash();
      break;
    case "trash-refresh":
      loadTrash();
      break;
    case "trash-restore":
      restoreSidebarTrash(id, Number(button.dataset.version || 0));
      break;
    case "optimize-prompt":
      optimizePrompt();
      break;
    case "apply-optimized":
      applyOptimizedPrompt();
      break;
    case "dismiss-optimized":
      dismissOptimizedPrompt();
      break;
    case "restore-trash":
      restoreTrash(id);
      break;
    case "stage-check":
      inspectStage(id);
      break;
    case "restore-stage-data":
      restoreStageData(id);
      break;
    case "restore-note":
      restoreNoteVersion(button.dataset.version);
      break;
    case "run-tour":
      startTour();
      break;
    case "toggle-director":
      toggleDirector();
      renderPage({ restore: true });
      break;
    case "server-status-export":
      serverStatusController?.download();
      break;
    case "server-status-reload":
      serverStatusController?.reload();
      break;
    case "eval-run":
      evaluationController?.run();
      break;
    case "login-mode": {
      /* 账号/令牌登录方式切换，偏好持久化到 localStorage */
      state.loginMode = state.loginMode === "token" ? "account" : "token";
      write("loginMode", state.loginMode);
      renderPage({ restore: true });
      break;
    }
    case "search-example": {
      state.searchInput = value || "";
      const input = $("#search-form input[name=query]");
      if (input) {
        input.value = state.searchInput;
        input.dispatchEvent(new Event("input", { bubbles: true }));
      }
      const form = $("#search-form");
      if (form) submitSearch(form);
      break;
    }
  }
}
document.addEventListener("click", (e) => {
  if (!(e.target instanceof Element)) return;
  const mode = e.target.closest("button[data-mode]");
  if (mode && ["portal", "sidebar"].includes(mode.dataset.mode)) {
    state.mode = mode.dataset.mode;
    write("mode", state.mode);
    const menu = mode.closest("details");
    if (menu) menu.open = false;
    renderPage({ restore: true });
    return;
  }
  if (e.target.closest("#quick-results a")) $("#quick-dialog").close();
  /* 评测题目展开/收起：结果区自管局部 DOM，不走 renderPage */
  const evalToggle = e.target.closest("[data-eval-toggle]");
  if (evalToggle) {
    evaluationController?.toggle(evalToggle.dataset.evalToggle);
    return;
  }
  const b = e.target.closest("[data-action]");
  if (b) {
    e.preventDefault();
    handleAction(b);
  }
});
document.addEventListener("input", (e) => {
  if (e.target.id === "density-range") {
    state.density = Number(e.target.value);
    write("density", state.density);
    document.documentElement.dataset.density = [
      "compact",
      "standard",
      "comfortable",
    ][state.density];
    $("#density-output").textContent = ["紧凑", "标准", "宽松"][state.density];
  }
  if (e.target.id === "knowledge-search") {
    state.query = e.target.value;
    scheduleKnowledgePanel();
  }
  if (e.target.name === "query") state.searchInput = e.target.value;
});
document.addEventListener("change", (e) => {
  /* 评测重排开关：只重置结果口径，不整页重绘 */
  if (e.target.matches("[data-eval-rerank]")) {
    evaluationController?.setRerank(e.target.checked);
    return;
  }
  if (e.target.closest("#search-form")) {
    if (e.target.name === "scope") state.scope = e.target.value;
    if (e.target.name === "namespace") state.namespace = e.target.value;
    if (e.target.name === "generate") state.generate = e.target.checked;
  }
  if (e.target.matches("[data-mode]") || e.target.id === "mode-select") {
    const nextMode = e.target.dataset.mode || e.target.value;
    if (!["portal", "sidebar"].includes(nextMode)) return;
    state.mode = nextMode;
    write("mode", state.mode);
    renderPage({ restore: true });
  }
  if (e.target.id === "density-select") {
    state.density = Number(e.target.value);
    write("density", state.density);
    renderPage({ restore: true });
  }
  if (e.target.id === "hero-size") {
    state.compactHero = e.target.value === "compact";
    write("hero", state.compactHero);
    renderPage({ restore: true });
  }
});
window.addEventListener("hashchange", () => {
  const route = location.hash || "#home",
    previous = stack.at(-1);
  if (!allowDraftNavigation()) {
    history.replaceState(null, "", previous || paintedRoute);
    pendingBack = false;
    return;
  }
  closeDialogs();
  scrolls.set(previous, window.scrollY);
  state.visits[previous] = window.scrollY;
  if (pendingBack) {
    if (stack.length > 1) stack.pop();
    pendingBack = false;
  } else if (stack.at(-1) !== route) stack.push(route);
  updatePosition();
  renderPage({ restore: scrolls.has(route) });
  if (scrolls.has(route))
    requestAnimationFrame(() => window.scrollTo(0, scrolls.get(route)));
});
window.addEventListener("popstate", () => {
  pendingBack = true;
});
window.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && $("#quick-dialog")?.open)
    $("#quick-dialog").close();
  if ((e.ctrlKey || e.metaKey) && e.key.toLowerCase() === "k") {
    e.preventDefault();
    openQuick();
  }
});
$("#quick-open").addEventListener("click", openQuick);
$("#quick-close").addEventListener("click", () => $("#quick-dialog").close());
$("#quick-query").addEventListener("input", populateQuick);

document.addEventListener("submit", async (e) => {
  if (e.target.id === "login-form") {
    e.preventDefault();
    const form = e.target,
      button = form.querySelector("button[type=submit]"),
      error = $("#login-error");
    button.disabled = true;
    error.hidden = true;
    try {
      const fd = new FormData(form);
      const body =
        state.accountLogin && state.loginMode !== "token"
          ? {
              username: String(fd.get("username") || ""),
              password: String(fd.get("password") || ""),
              remember: fd.get("remember") === "on",
            }
          : { token: fd.get("token") };
      await api("session", body);
      await refresh(false);
    } catch (err) {
      error.textContent = err.message;
      error.hidden = false;
    } finally {
      button.disabled = false;
    }
    return;
  }
  if (e.target.matches(".edit-form") && e.target.closest("dialog[data-form]")) {
    const kind = e.target.closest("dialog[data-form]").dataset.form;
    if (["lesson", "jobs", "learning", "job-profile"].includes(kind)) return;
    /* 谨记表单由 lessons.js 自己接管（评审 F2：双重接管会抢先关弹窗吞校验错误） */ e.preventDefault();
    await saveForm(e.target);
  }
  if (e.target.id === "finish-stage-form") {
    e.preventDefault();
    await finishStage(e.target);
  }
  if (e.target.id === "search-form") {
    e.preventDefault();
    await submitSearch(e.target);
  }
});
$("#detail-close").addEventListener("click", () => $("#detail-dialog").close());
$("#detail-dialog").addEventListener("close", () => {
  if (detailTrigger?.isConnected) detailTrigger.focus({ preventScroll: true });
});
window.addEventListener("storage", (e) => {
  if (e.key === "shilie-mode") {
    state.mode = read("mode", "portal");
    renderPage({ restore: true });
  }
});
/* 会话过期（api() 收到 401）时回到登录面板；登录表单自身的 401 不触发（由表单内联报错）。 */
document.addEventListener("shilie:unauthorized", () => {
  if (state.authRequired) renderPage();
});

load()
  .then(() => {
    if (!state.selectedPlan && state.plans.length)
      state.selectedPlan = state.plans[0].id;
    const route = location.hash.slice(1);
    if (!route) history.replaceState(null, "", "#home");
    updatePosition();
    renderPage({ restore: scrolls.has(location.hash) });
    if (scrolls.has(location.hash))
      requestAnimationFrame(() =>
        window.scrollTo(0, scrolls.get(location.hash)),
      );
  })
  .catch((e) => {
    state.loading = false;
    state.error = e.message;
    renderPage();
  });

function populateQuick() {
  const query = $("#quick-query").value.toLowerCase();
  $("#quick-results").innerHTML =
    modules
      .filter((m) => `${m.title} ${m.group}`.toLowerCase().includes(query))
      .map(
        (m) =>
          `<a class="module-option" href="#module/${m.id}">${escapeHtml(m.title)}</a>`,
      )
      .join("") || "<p>没有匹配模块</p>";
}
function openQuick() {
  $("#quick-query").value = "";
  populateQuick();
  if (!$("#quick-dialog").open) $("#quick-dialog").showModal();
  $("#quick-query").focus();
}
$("#quick-dialog").addEventListener("keydown", (event) => {
  const links = [...$("#quick-results").querySelectorAll("a")],
    index = links.indexOf(document.activeElement);
  if (event.key === "ArrowDown" || event.key === "ArrowUp") {
    event.preventDefault();
    links[
      event.key === "ArrowDown"
        ? Math.min(index + 1, links.length - 1)
        : Math.max(index - 1, 0)
    ]?.focus();
  }
  if (event.key === "Enter" && event.target.id === "quick-query") {
    event.preventDefault();
    links[0]?.click();
  }
});
let scrollTimer;
window.addEventListener(
  "scroll",
  () => {
    clearTimeout(scrollTimer);
    scrollTimer = setTimeout(() => {
      const route = location.hash || "#home";
      state.visits[route] = window.scrollY;
      scrolls.set(route, window.scrollY);
      write("visits", state.visits);
    }, 150);
  },
  { passive: true },
);
let trashRows = [];
async function openTrash() {
  try {
    trashRows = await api("knowledge?trash=true");
    showDetail(
      "知识回收站",
      trashRows.length
        ? trashRows
            .map(
              (row) =>
                `<section class="trash-entry"><h3>${escapeHtml(row.data.title)}</h3><p>${escapeHtml(row.data.content.slice(0, 120))}</p><button class="small-button" data-action="restore-trash" data-id="${escapeHtml(row.id)}">恢复笔记</button></section>`,
            )
            .join("")
        : "<p>回收站为空。</p>",
    );
  } catch (error) {
    toast(error.message, true);
  }
}
async function restoreTrash(id) {
  const row = trashRows.find((item) => item.id === id);
  if (!row) return;
  try {
    const history = await api(`records/${id}/history`),
      target = history.find((version) => !version.deleted);
    if (!target) throw Error("没有可恢复的历史版本");
    await api(`records/${id}/restore`, {
      target_version: target.version,
      current_version: row.version,
    });
    state.selectedNote = id;
    closeDialogs();
    await refreshKnowledge();
    toast("笔记已恢复，历史仍保留");
  } catch (error) {
    toast(error.message, true);
  }
}
/* 侧栏回收站：一次汇总所有公开工作区类型的已删除记录。 */
async function toggleTrash() {
  state.trashOpen = !state.trashOpen;
  if (state.trashOpen && !state.trashData && !state.trashLoading) {
    await loadTrash();
    return;
  }
  paintSidebar();
}
async function loadTrash() {
  if (state.trashLoading) return;
  state.trashLoading = true;
  state.trashError = "";
  paintSidebar();
  try {
    state.trashData = await api("trash");
  } catch (error) {
    state.trashError = error.message;
  } finally {
    state.trashLoading = false;
    paintSidebar();
  }
}
async function restoreSidebarTrash(id, version) {
  const row = (state.trashData?.items || []).find((item) => item.id === id);
  if (!row) return;
  try {
    const history = await api(`records/${id}/history`),
      target = history.find((item) => !item.deleted);
    if (!target) throw Error("没有可恢复的历史版本");
    await api(`records/${id}/restore`, {
      target_version: target.version,
      current_version: version || row.version,
    });
    toast(`已恢复「${row.title}」`);
    await refresh();
    await loadTrash();
  } catch (error) {
    toast(error.message, true);
  }
}
let bookmarkTrashRows = [];
async function openBookmarkTrash() {
  try {
    bookmarkTrashRows = await api("bookmarks?trash=true");
    showDetail(
      "收藏回收站",
      bookmarkTrashRows.length
        ? bookmarkTrashRows
            .map(
              (row) =>
                `<section class="trash-entry"><h3>${escapeHtml(row.data.title)}</h3><p>${escapeHtml(row.data.url)}</p><button class="small-button" data-action="restore-bookmark-trash" data-id="${escapeHtml(row.id)}">恢复收藏</button></section>`,
            )
            .join("")
        : "<p>回收站为空。</p>",
    );
  } catch (error) {
    toast(error.message, true);
  }
}
async function restoreBookmarkTrash(id) {
  const row = bookmarkTrashRows.find((item) => item.id === id);
  if (!row) return;
  try {
    const history = await api(`records/${id}/history`),
      target = history.find((version) => !version.deleted);
    if (!target) throw Error("没有可恢复的历史版本");
    await api(`records/${id}/restore`, {
      target_version: target.version,
      current_version: row.version,
    });
    closeDialogs();
    await refreshBookmarks();
    toast("收藏已恢复");
  } catch (error) {
    toast(error.message, true);
  }
}
async function inspectStage(id) {
  try {
    const result = await api(`stages/${id}/rollback-check`);
    showDetail(
      "源码回滚预检",
      `<p>${result.can_apply ? "当前源码与阶段结束时一致，可以在停止应用后执行回滚。" : "检测到后续改动或备份问题，当前不能覆盖恢复。"}</p><p>${result.changes.length} 项文件改动</p>${result.conflicts.length ? `<ul>${result.conflicts.map((item) => `<li>${escapeHtml(item)}</li>`).join("")}</ul>` : ""}<p>在项目目录执行：</p><pre><code>${escapeHtml("python scripts/stage_checkpoint.py rollback --id " + id)}</code></pre><p>检查通过后，再使用 --apply。数据库恢复另行处理。</p>`,
    );
  } catch (error) {
    toast(error.message, true);
  }
}
async function restoreStageData(id) {
  if (
    prompt(
      "恢复该阶段开始时的知识和规划。当前内容会先保存保护快照。请输入“恢复数据”：",
    ) !== "恢复数据"
  )
    return;
  try {
    const result = await api(`stages/${id}/restore-data`, {
      confirmation: "恢复数据",
    });
    closeDialogs();
    await refresh();
    toast(`已恢复 ${result.restored_records} 条记录，保护快照已保存`);
  } catch (error) {
    toast(error.message, true);
  }
}

bindAutomation({ renderPage, refresh, toast });
bindTree({ renderPage, refresh, toast });
modelConnectionController = bindModelConnection({ renderPage, toast });

backupController = bindBackup({ renderPage, refresh, toast });
setPrivateRepaint(() => renderPage({ restore: true }));
bindPrivate(toast);
lessonsController = bindLessons({ renderPage, toast });
jobsController = bindJobs({ renderPage, toast });
capabilitiesController = bindCapabilities({ renderPage, toast });
learningController = bindLearning({ renderPage, toast });
jobInsightsController = bindJobInsights({ renderPage, toast });
bindAgentStudio({ renderPage, toast });
bindCollaboration({ renderPage, toast });
serverStatusController = bindServerStatus({ renderPage });
evaluationController = bindEvaluation({ renderPage });
initMotion({ content, renderPage });
