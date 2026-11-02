/* 导演模式：右侧实时事件流面板——记录页面上发生的导航/点击/检索/表单/报错，
   让任何自动化操作（agent 或巡游）都可被用户旁观。纯观察者，不改变任何行为。 */
let directorOn = false;
let detach = () => {};
const qs = (s) => document.querySelector(s);

const DIR_STYLES = {
  nav: ["#8fd0ff", "→"],
  click: ["#ffd9a0", "◉"],
  form: ["#c9e6b8", "✎"],
  search: ["#e6c9ff", "🔍"],
  error: ["#ffb3a7", "✖"],
  info: ["#d8c3a4", "·"],
};

function fmtTime() {
  const d = new Date();
  return `${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}:${String(d.getSeconds()).padStart(2, "0")}`;
}

function short(text, n = 60) {
  return String(text ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, n);
}

const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );

function push(panel, type, text) {
  const log = panel.querySelector("#director-log");
  if (!log) return;
  const [color, icon] = DIR_STYLES[type] || DIR_STYLES.info;
  const line = document.createElement("div");
  line.className = "director-line";
  // 事件文本含用户数据（标题原文、hash），必须转义后才能进 innerHTML（评审 F3）
  line.innerHTML = `<time>${fmtTime()}</time><span style="color:${color}">${icon}</span><em>${esc(
    short(text),
  )}</em>`;
  log.append(line);
  while (log.children.length > 120) log.firstChild.remove();
  log.scrollTop = 1e6;
}

function describe(el) {
  if (!el || el === document) return "document";
  if (el.id) return "#" + el.id;
  const title = el.querySelector?.("h1,h2,h3,strong")?.textContent;
  if (title) return short(title, 30);
  return (
    el.tagName.toLowerCase() +
    (el.className && typeof el.className === "string"
      ? "." + el.className.split(" ")[0]
      : "")
  );
}

function attachObservers(panel) {
  const onClick = (e) => {
    if (e.target.closest?.("#director-panel")) return;
    const el = e.target instanceof Element ? e.target : null;
    const button = el?.closest?.("button,a,[data-action]");
    push(
      panel,
      "click",
      button ? `点击 ${describe(button)}` : `点击 ${describe(el)}`,
    );
  };
  const onSubmit = (e) => {
    if (e.target.closest?.("#director-panel")) return;
    push(panel, "form", `提交表单 ${describe(e.target)}`);
  };
  const onHash = () => push(panel, "nav", `导航 → ${location.hash || "#home"}`);
  const origFetch = window.fetch;
  window.fetch = function (input, init) {
    const url = typeof input === "string" ? input : input?.url || "";
    const method = (init?.method || "GET").toUpperCase();
    if (url.includes("/api/")) {
      const kind =
        url.includes("query") || url.includes("search") ? "search" : "info";
      push(
        panel,
        kind === "search" ? "search" : "info",
        `${method} ${url.replace("/api/", "")}`,
      );
    }
    return origFetch.apply(this, arguments);
  };
  const onError = (e) => push(panel, "error", e.message || "未知错误");
  // 具名处理函数：detach 时必须成对移除，否则反复开关无限累积（评审 F4）
  const onRejection = (e) =>
    push(panel, "error", short(String(e.reason?.message || e.reason), 70));
  window.addEventListener("click", onClick, true);
  document.addEventListener("submit", onSubmit, true);
  window.addEventListener("hashchange", onHash);
  window.addEventListener("error", onError);
  window.addEventListener("unhandledrejection", onRejection);
  detach = () => {
    window.removeEventListener("click", onClick, true);
    document.removeEventListener("submit", onSubmit, true);
    window.removeEventListener("hashchange", onHash);
    window.removeEventListener("error", onError);
    window.removeEventListener("unhandledrejection", onRejection);
    window.fetch = origFetch;
    detach = () => {};
  };
}

function ensurePanel() {
  let panel = qs("#director-panel");
  if (panel) return panel;
  panel = document.createElement("aside");
  panel.id = "director-panel";
  panel.innerHTML =
    '<header><span>导演模式 · 事件直播</span><button type="button" id="director-close" aria-label="关闭">×</button></header>' +
    '<div id="director-log"></div>' +
    '<footer><button type="button" id="director-replay" class="replay-btn">⏵ 慢动作重演巡游</button><small>所有页面事件实时记录于此</small></footer>';
  document.body.append(panel);
  qs("#director-close").addEventListener("click", () => {
    panel.remove();
    directorOn = false;
    detach();
  });
  qs("#director-replay").addEventListener("click", () => slowTour());
  attachObservers(panel);
  push(panel, "info", "导演模式已开启，等待页面事件…");
  return panel;
}

async function slowTour() {
  const panel = qs("#director-panel");
  if (!panel) return;
  const btn = panel.querySelector("#director-replay");
  btn.disabled = true;
  btn.textContent = "⏸ 重演中（3× 慢放）";
  push(panel, "info", "开始慢动作重演：每步间隔约 2.4 秒");
  // 复用巡游步骤但拉长节奏；复用 startTour 的 STEPS 不可行（模块私有），此处以轻量方式重演核心动作
  const steps = [
    ["#home", "首页 · 看极光与花瓣"],
    ["#module/planning", "规划 · 看连线生长"],
    ["#module/knowledge", "知识库 · 看空态与示意"],
    ["#module/lessons", "谨记名单 · 看分类"],
    ["#module/documents", "检索 · 看示例搜索"],
    ["#module/appearance", "设置 · 看服务状态卡"],
  ];
  for (const [hash, label] of steps) {
    if (!panel.isConnected) return; // 面板已关：立即停止，不再劫持导航（评审 F5）
    push(panel, "nav", "重演 " + label);
    location.hash = hash;
    await new Promise((r) => setTimeout(r, 2400));
  }
  const live = qs("#director-panel");
  if (!live) return;
  const resetBtn = live.querySelector("#director-replay");
  if (resetBtn) {
    resetBtn.disabled = false;
    resetBtn.textContent = "⏵ 慢动作重演巡游";
  }
  push(
    live,
    "info",
    "重演完成——要跑完整 11 步验收，用设置页的「运行验收巡游」",
  );
}

export function directorActive() {
  return directorOn;
}

export function toggleDirector(force) {
  directorOn = force !== undefined ? force : !directorOn;
  if (directorOn) {
    // 面板互斥：巡游面板同位叠放会完全盖住导演面板（评审 F8），经其关闭按钮走清理路径
    qs("#tour-close")?.click();
    ensurePanel();
  } else {
    qs("#director-panel")?.remove();
    detach();
  }
  return directorOn;
}
