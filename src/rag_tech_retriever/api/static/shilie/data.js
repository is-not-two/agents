/* 网络与偏好；内容只写 PostgreSQL，浏览器仅保存阅读位置和显示偏好。 */

/* 错误码 → 默认文案（服务端返回 detail 时优先用服务端文案；字段集中一处）。 */
export const ERROR_TEXT = {
  VALIDATION_ERROR: "提交内容不符合要求，请检查输入",
  NOT_FOUND: "内容不存在或已被删除",
  VERSION_CONFLICT: "记录已被其他操作更新，请刷新后重试",
  PAYLOAD_TOO_LARGE: "提交内容超过大小限制",
  UNAUTHORIZED: "请先登录",
  FORBIDDEN: "操作被拒绝",
  RATE_LIMITED: "请求过于频繁，请稍后再试",
  STORAGE_UNAVAILABLE: "存储暂时不可用，请稍后重试",
  TOOL_FAILURE: "工具调用失败，请稍后重试",
  INTERNAL: "服务器内部错误，请稍后重试",
  NETWORK: "网络连接失败，请检查网络后重试",
  TIMEOUT: "请求超时，请稍后重试",
};
function codeFromStatus(status) {
  if (status === 400 || status === 422) return "VALIDATION_ERROR";
  if (status === 401) return "UNAUTHORIZED";
  if (status === 403) return "FORBIDDEN";
  if (status === 404) return "NOT_FOUND";
  if (status === 409) return "VERSION_CONFLICT";
  if (status === 413) return "PAYLOAD_TOO_LARGE";
  if (status === 429) return "RATE_LIMITED";
  if (status === 503) return "STORAGE_UNAVAILABLE";
  return "INTERNAL";
}
export async function api(path, body, method = body ? "POST" : "GET", timeoutMs = 30000) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  let response;
  try {
    response = await fetch("/api/" + path, {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal: controller.signal,
    });
  } catch (networkError) {
    const timedOut = networkError?.name === "AbortError";
    const error = new Error(timedOut ? ERROR_TEXT.TIMEOUT : ERROR_TEXT.NETWORK);
    error.code = timedOut ? "TIMEOUT" : "NETWORK";
    throw error;
  } finally {
    clearTimeout(timer);
  }
  let result = null;
  try {
    result = await response.json();
  } catch {
    /* 非 JSON 响应（网关错误页等）走统一文案，不把解析异常抛给用户 */
    result = null;
  }
  if (!response.ok) {
    const code = (typeof result?.code === "string" && result.code) || codeFromStatus(response.status);
    const error = new Error(
      typeof result?.detail === "string" && result.detail
        ? result.detail
        : ERROR_TEXT[code] || ERROR_TEXT.INTERNAL,
    );
    error.status = response.status;
    error.code = code;
    error.requestId = result?.request_id || response.headers.get("X-Request-ID") || "";
    if (code === "UNAUTHORIZED" && path !== "session") {
      state.authRequired = true;
      document.dispatchEvent(new CustomEvent("shilie:unauthorized"));
    }
    throw error;
  }
  return result;
}
export function read(key, fallback) {
  try {
    return JSON.parse(localStorage.getItem("shilie-" + key)) ?? fallback;
  } catch {
    return fallback;
  }
}
export function write(key, value) {
  try {
    localStorage.setItem("shilie-" + key, JSON.stringify(value));
  } catch {
    /* 偏好存储不可用不影响业务保存 */
  }
}
/* 全站唯一 HTML 转义出口（评审 F13）：用户内容一律经此转义后再进 innerHTML。 */
export function escapeHtml(x) {
  return String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
}
export const groups = [
  { id: "workspace", title: "个人工作台", caption: "知识、计划与复盘" },
  { id: "automation", title: "自动化中心", caption: "检索与助手" },
  { id: "settings", title: "系统设置", caption: "连接、数据与界面" },
  { id: "private", title: "私密空间", caption: "愿望清单与私密日记" },
];
/* 侧栏专用分组：只决定导航的显示顺序与折叠，不改变 groups 的业务归属。
   面包屑、首页环轨与 #category/* 仍按 groups 解析，避免改侧栏牵动四处。
   后续新增模块只需把 id 加到对应 section 的 modules 里。 */
export const navSections = [
  {
    id: "library",
    title: "知识与检索",
    icon: "knowledge",
    modules: ["knowledge", "bookmarks", "documents"],
  },
  {
    id: "career",
    title: "求职板块",
    icon: "briefcase",
    /* 侧栏只留一个 P0 入口；板块内 4 个并列 P1 页面，简历不随公司切换。 */
    modules: ["job-flow"],
  },
  {
    id: "review",
    title: "学习与复盘",
    icon: "clock",
    modules: ["learning", "lessons"],
  },
  {
    id: "self",
    title: "自我与人生",
    icon: "user",
    modules: ["planning", "stages", "self-traits", "private"],
  },
  {
    id: "system",
    title: "系统",
    icon: "settings",
    modules: [
      "notifications", "connections", "backup", "appearance", "workflows",
      "agents", "agent-studio", "collaboration", "runs", "evaluation",
    ],
  },
];
export const modules = [
  ["knowledge", "个人知识库", "workspace", "knowledge"],
  ["bookmarks", "网页收藏", "workspace", "link"],
  ["job-flow", "求职板块", "workspace", "briefcase"],
  ["jobs", "求职记录", "workspace", "briefcase"],
  ["company-capabilities", "目标公司能力", "workspace", "target"],
  ["job-insights", "岗位证据对照", "workspace", "clipboard"],
  ["job-weekly", "求职周报", "workspace", "chart"],
  ["learning", "到期复习", "workspace", "clock"],
  ["notifications", "通知中心", "settings", "bell"],
  ["lessons", "谨记名单", "workspace", "list"],
  ["documents", "技术文档检索", "workspace", "search"],
  ["evaluation", "检索质量评测", "automation", "gauge"],
  ["planning", "人生规划", "workspace", "planning"],
  ["stages", "阶段记录", "workspace", "stages"],
  ["self-traits", "人物", "workspace", "user"],
  ["workflows", "工作流", "automation", "workflow"],
  ["agents", "Agent 设置", "automation", "agent"],
  ["agent-studio", "Agent 工作室", "automation", "sparkle"],
  ["collaboration", "实验协作", "automation", "users"],
  ["runs", "运行记录", "automation", "history"],
  ["connections", "模型连接", "settings", "connection"],
  ["backup", "数据与备份", "settings", "backup"],
  ["appearance", "界面偏好", "settings", "palette"],
  ["private", "私密管理", "private", "lock"],
].map(([id, title, group, icon]) => ({ id, title, group, icon }));
export const state = {
  knowledge: [],
  bookmarks: [],
  bookmarkFilter: read("bookmarkFilter", "全部"),
  /* 侧栏分组折叠状态：默认只收起系统组，避免长列表把常用入口挤出首屏。 */
  navCollapsed: { system: true, ...(read("nav-collapsed", {}) || {}) },
  /* 侧栏回收站：展开状态只存在内存，数据由 /api/trash 一次汇总。 */
  trashOpen: false,
  trashLoading: false,
  trashError: "",
  trashData: null,
  plans: [],
  stages: [],
  stageTime: "",
  stageError: "",
  authRequired: false,
  accountLogin: false,
  loginMode: "token",
  status: {},
  mode: read("mode", "portal"),
  density: read("density", 1),
  compactHero: read("hero", false),
  selectedNote: read("note", ""),
  selectedPlan: read("plan", ""),
  filter: read("filter", "all"),
  taskStatus: read("taskStatus", "all"),
  query: read("query", ""),
  view: read("view", "story"),
  storyOpen: read("storyOpen", {}),
  recent: read("recent", []),
  visits: read("visits", {}),
  runs: [],
  agents: [],
  workflows: [],
  workflowRuns: [],
  automationError: "",
  selectedFlow: read("flow", ""),
  autoBusy: false,
  autoError: "",
  teamBusy: false,
  teamResult: null,
  /* 自动编码：输入与结果只留内存，刷新即重置，不写 localStorage。 */
  loopBusy: false,
  loopResult: null,
  loopInput: { root: "", task: "", gate: "", engine: "opencode", tier: "patch" },
  /* 任务队列：异步执行的入口。队列是服务端状态，页面只做展示与操作。 */
  queueJobs: [],
  queueStats: {},
  queueDetail: null,
  queueBusy: false,
  queueError: "",
  queueFilter: "",
  queueInput: { kind: "loop", root: "", task: "", gate: "", engine: "opencode", tier: "patch", max_attempts: 3 },
  automationInput: { query: "", title: "", source: "", content: "" },
  currentRun: null,
  runDetail: null,
  codeRoots: [],
  composeDraft: null,
  composeChanges: null,
  pendingTaskId: "",
  searchBusy: false,
  searchError: "",
  searchResultQuery: "",
  generate: false,
  searchResult: null,
  searchInput: "",
  scope: "all",
  namespace: null,
  corpusOptions: null,
  graphSelection: "",
  loading: true,
  error: "",
};
state.mode = ["portal", "sidebar"].includes(state.mode) ? state.mode : "portal";
state.density = [0, 1, 2].includes(state.density) ? state.density : 1;
state.taskStatus = ["all", "available", "locked", "done"].includes(
  state.taskStatus,
)
  ? state.taskStatus
  : "all";
state.filter = ["all", "notes", "resources"].includes(state.filter)
  ? state.filter
  : "all";
state.query = typeof state.query === "string" ? state.query : "";
state.bookmarkFilter =
  typeof state.bookmarkFilter === "string" ? state.bookmarkFilter : "全部";
state.view = ["story", "tasks", "relations"].includes(state.view)
  ? state.view
  : "story";
state.storyOpen =
  state.storyOpen &&
  typeof state.storyOpen === "object" &&
  !Array.isArray(state.storyOpen)
    ? state.storyOpen
    : {};
state.recent = Array.isArray(state.recent)
  ? state.recent.filter((id) => modules.some((m) => m.id === id)).slice(0, 4)
  : [];
state.visits =
  state.visits &&
  typeof state.visits === "object" &&
  !Array.isArray(state.visits)
    ? state.visits
    : {};
export function plan() {
  return state.plans.find((p) => p.id === state.selectedPlan) || state.plans[0];
}
export function currentNote() {
  return (
    state.knowledge.find((n) => n.id === state.selectedNote) ||
    state.knowledge[0]
  );
}
export async function load() {
  const session = await api("session");
  state.authRequired = session.required && !session.authenticated;
  /* 服务器启用账号登录时默认账号方式；未启用则强制令牌方式 */
  state.accountLogin = Boolean(session.account_login);
  if (state.accountLogin) {
    state.loginMode = read("loginMode", "account") === "token" ? "token" : "account";
  } else {
    state.loginMode = "token";
  }
  if (state.authRequired) {
    Object.assign(state, { loading: false, error: "" });
    return;
  }
  const [knowledge, bookmarks, plans, status, summary, corpusOptions] = await Promise.all([
    api("knowledge"),
    /* 收藏为独立集合，接口异常时不阻塞知识/规划等主视图。 */
    api("bookmarks").catch(() => []),
    api("plans"),
    api("status"),
    api("stage-summary").catch((error) => ({
      records: [],
      updated_at: "",
      error: error.message,
    })),
    api("query/options").catch((error) => ({ error: error.message })),
  ]);
  const automation = await Promise.all([
    api("agents"),
    api("workflows"),
    api("workflow-runs"),
    api("automation/code-roots").catch(() => []),
  ])
    .then(([agents, workflows, workflowRuns, codeRoots]) => ({
      agents,
      workflows,
      workflowRuns,
      codeRoots,
      automationError: "",
    }))
    .catch((e) => ({ automationError: e.message }));
  /* 队列是可选能力：队列表尚未初始化时不让整个工作台报错，只提示不可用。 */
  const queue = await Promise.all([
    api("automation/queue?limit=30").catch((e) => ({ __error: e.message })),
    api("automation/queue/stats").catch((e) => ({ __error: e.message })),
  ]).then(([jobs, stats]) => {
    if (jobs?.__error) return { queueJobs: [], queueStats: {}, queueError: jobs.__error };
    return { queueJobs: jobs || [], queueStats: stats || {}, queueError: "" };
  });
  Object.assign(state, automation, queue, {
    knowledge,
    bookmarks,
    plans,
    status,
    corpusOptions,
    namespace: corpusOptions.namespaces?.some((item) => item.id === state.namespace) ? state.namespace : corpusOptions.default || null,
    stages: summary.records,
    stageTime: summary.updated_at,
    stageError: summary.error || "",
    loading: false,
    error: "",
  });
}
