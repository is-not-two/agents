import { collaborationView } from "./collaboration.js?v=110";
import { corpusSelect } from "./public-corpus.js?v=110";
import { agentStudioView } from "./agent-studio.js?v=110";
import { backupView } from "./backup.js?v=110";
import { privateView } from "./private-view.js?v=110";
import { modelConnectionView } from "./model-connection.js?v=110";
import { treeView, treeDialog } from "./tree.js?v=110";
import {
  agentsPage,
  workflowsPage,
  runsPage,
  automationDialogs,
} from "./automation-views.js?v=110";
import { lessonsView, lessonsDialog } from "./lessons.js?v=110";
import { jobsView, jobsDialog } from "./jobs.js?v=110";
import {
  capabilitiesView,
  capabilitiesDialog,
} from "./company-capabilities.js?v=110";
import { learningView, notificationsView, learningDialogs } from "./learning.js?v=110";
import { jobInsightsView, jobWeeklyView, jobProfileDialog } from "./job-insights.js?v=110";
import { serverStatusView } from "./server-status.js?v=110";
import { evaluationView } from "./evaluation.js?v=110";
import { directorActive } from "./director.js?v=110";
import { icon, orbitIcon } from "./icons.js?v=110";
import {
  escapeHtml as esc,
  groups,
  modules,
  state,
  currentNote,
} from "./data.js?v=110";
function highlight(value, query) {
  const text = String(value ?? ""),
    term = String(query || "").trim();
  if (!term) return esc(text);
  let from = 0,
    html = "",
    index;
  const lower = text.toLowerCase(),
    needle = term.toLowerCase();
  while ((index = lower.indexOf(needle, from)) !== -1) {
    html +=
      esc(text.slice(from, index)) +
      "<mark>" +
      esc(text.slice(index, index + term.length)) +
      "</mark>";
    from = index + term.length;
  }
  return html + esc(text.slice(from));
}
const arrow =
  '<svg class="icon" viewBox="0 0 20 20" aria-hidden="true"><path d="m7 4 6 6-6 6"/></svg>';
const btn = (label, action, cls = "small-button", attrs = "") =>
  `<button class="${cls}" data-action="${action}" ${attrs}>${label}</button>`;
const back = () => "";
function frame(title, body, planned = false) {
  return `${back()}<div class="page-head"><h1>${esc(title)}</h1>${planned ? '<span class="planned-label">最小 Demo</span>' : ""}</div>${body}`;
}
function dialog(kind, title, body) {
  return `<dialog class="form-dialog" data-form="${kind}"><form class="edit-form"><header class="drawer-header"><div><small>时列 · 工作区</small><h2>${title}</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content">${body}</div></form></dialog>`;
}
function field(label, name, value = "", type = "text", help = "") {
  return `<label class="form-field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${name === "title" ? 'required maxlength="160"' : ""}>${help ? `<small>${help}</small>` : ""}</label>`;
}
function textarea(label, name, value = "", rows = 9) {
  return `<label class="form-field">${label}<textarea name="${name}" rows="${rows}" ${name === "content" ? "required" : ""}>${esc(value)}</textarea></label>`;
}
function actions() {
  return `<div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button class="primary-button" type="submit">保存</button></div>`;
}
/* 首页 v3：190px 信息横幅（品牌+时段问候+日期+快速打开）+ 今日概览（统计块/今日到期/最近笔记）
   + 中心「开始」按钮与两圈反向旋转的环轨入口（2026-10-30 起替换原 2×2 入口卡）。 */
function localToday() {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
}
function greet() {
  const h = new Date().getHours();
  return h < 5
    ? "夜深了"
    : h < 11
      ? "早上好"
      : h < 13
        ? "中午好"
        : h < 18
          ? "下午好"
          : "晚上好";
}
function homeStats() {
  const nodes = (state.plans || []).flatMap((p) => {
    try {
      return (p.data.acts || []).flatMap((a) => a.nodes || []);
    } catch {
      return [];
    }
  });
  const done = nodes.filter((n) => n.done).length;
  return [
    {
      label: "知识条目",
      value: (state.knowledge || []).length,
      href: "#module/knowledge",
    },
    {
      label: "任务完成",
      value: done,
      total: nodes.length,
      href: "#module/planning",
    },
    {
      label: "谨记名单",
      value: state.status?.lessons_count ?? 0,
      href: "#module/lessons",
    },
    {
      label: "阶段记录",
      value: (state.stages || []).length,
      href: "#module/stages",
    },
  ];
}
/* 首页环轨入口：中心「开始」按钮 + 内 6 / 外 4 两圈反向旋转（2026-10-30 首页 v3 轮）。
   入口是写死白名单，不按 data.js 的声明顺序机械取：模块表里挤着 3 个求职子页
   （岗位证据对照 / 求职周报 / 到期复习），机械取会把常用入口顶掉。
   内环 = 模块（#module/*），外环 = 分组（#category/*）。 */
const ORBIT_INNER = [
  ["knowledge", "个人知识库", "knowledge"],
  ["documents", "技术文档|检索", "search"],
  ["planning", "人生规划", "planning"],
  ["jobs", "求职记录", "task"],
  ["stages", "阶段记录", "stages"],
  ["agent-studio", "Agent|工作室", "agent"],
];
const ORBIT_OUTER = [
  ["workspace", "个人|工作台", "home"],
  ["automation", "自动化|中心", "workflow"],
  ["settings", "系统设置", "settings"],
  ["private", "私密空间", "lock"],
];
/* 标题里的 | 是人工断行点。中文没有空格、也没有词边界信息，浏览器的自动断行
   只按"填满行宽"贪心：6 字的「技术文档检索」会被断成「技术文档检/索」，
   5 字的「个人工作台」断成「个人工作/台」。
   注意必须用 <br>（强制断行）而不是 <wbr>：<wbr> 只是"可选断点"，浏览器在
   一行放得下时不会用它，实测两种写法只有 <br> 能稳定落在词边界上。
   aria-label 与降级列表仍用去掉 | 的纯文本。 */
const plainTitle = (t) => esc(t.replace(/\|/g, ""));
const wrappedTitle = (t) => esc(t).replace(/\|/g, "<br>");
function orbitSlot([id, title, iconName], kind, index) {
  /* 私密空间要按"可能被旁人看见"来设计，单独一个修饰类挂虚线描边（见 CSS）。 */
  const modifier = id === "private" ? " sl-orbit__node--private" : "";
  /* 节点已改为"纯图标"：文字用 sr-only 保留给读屏与键盘用户（视觉隐藏），
     aria-label 仍是完整名称，所以去掉视觉文字不损失可访问性。 */
  return `<div class="sl-orbit__slot" style="--sl-i:${index}"><a class="sl-orbit__node${modifier}" href="#${kind}/${id}" aria-label="${plainTitle(title)}"><span class="sl-orbit__node-icon">${orbitIcon(iconName)}</span><span class="sl-orbit__node-label">${wrappedTitle(title)}</span></a></div>`;
}
function orbitListItem([id, title, iconName], kind) {
  return `<a class="sl-orbit-list__item" href="#${kind}/${id}">${icon(iconName)}<span>${plainTitle(title)}</span>${arrow}</a>`;
}
/* 环轨与扁平列表同时渲染，靠 CSS 容器查询切换显隐（内容区窄于 610px 时只有列表）；
   10 个入口的 DOM 成本可忽略，换来的是不用在 resize 时重绘。
   外面这层 .home-orbit-wrap 是容器查询的基准：显隐按「内容区宽度」判，
   不按视口宽度——portal / sidebar 两套布局同视口下内容区差约 260px。 */
function orbitStage() {
  const outer = ORBIT_OUTER.map((n, i) => orbitSlot(n, "category", i)).join("");
  const inner = ORBIT_INNER.map((n, i) => orbitSlot(n, "module", i)).join("");
  const list = [
    ...ORBIT_OUTER.map((n) => orbitListItem(n, "category")),
    ...ORBIT_INNER.map((n) => orbitListItem(n, "module")),
  ].join("");
  return `<div class="home-orbit-wrap"><nav class="sl-orbit" aria-label="工作区入口环轨" data-orbit-speed="running"><div class="sl-orbit__halo" aria-hidden="true"></div><div class="sl-orbit__track sl-orbit__track--inner" aria-hidden="true"></div><div class="sl-orbit__track sl-orbit__track--outer" aria-hidden="true"></div><div class="sl-orbit__spokes" aria-hidden="true"></div><div class="sl-orbit__ring sl-orbit__ring--inner">${inner}</div><div class="sl-orbit__ring sl-orbit__ring--outer">${outer}</div><button class="sl-orbit__hub" type="button" aria-label="进入工作台" aria-describedby="sl-orbit-hint"><span class="sl-orbit__hub-label">进入</span><span class="sl-orbit__hub-state">环轨运行中</span></button><p id="sl-orbit-hint" class="sl-sr-only">环轨上的入口正在自动旋转。按此键进入下方工作台；也可以直接用键盘聚焦到某个入口。</p><p id="sl-orbit-status" role="status" class="sl-sr-only"></p></nav><nav class="sl-orbit-list" aria-label="工作区入口">${list}</nav></div>`;
}
function workspacePage() {
  const stats = homeStats();
  const today = localToday();
  const due = (state.plans || [])
    .flatMap((p) => {
      try {
        return (p.data.acts || []).flatMap((a) =>
          (a.nodes || [])
            .filter((n) => n.due_date === today && !n.done)
            .map((n) => ({ title: n.title, plan: p.data.title })),
        );
      } catch {
        return [];
      }
    })
    .slice(0, 5);
  const recentNotes = (state.knowledge || []).slice(0, 3);
  const picture = `<picture><source media="(max-width: 700px)" srcset="/static/shilie/landscape-800.webp"><img src="/static/shilie/landscape-1600.webp" alt="花树掩映的临水书阁，远山与云海" fetchpriority="high"></picture>`;
  return `<section class="home-main" id="home-main" tabindex="-1" aria-label="时列工作台"><section class="home-hero" aria-label="时列工作区">${picture}<div class="home-heading"><span class="home-brand">时列</span><p class="home-greet">${greet()}，${today}</p><button class="small-button home-quick" data-action="quick">快速打开搜索 <kbd>Ctrl K</kbd></button><a class="small-button home-back-start" href="#home">回到开始页</a></div></section><section class="today-overview" aria-label="今日概览"><nav class="stat-grid">${stats.map((s) => `<a class="stat-block" href="${s.href}"><b ${typeof s.value === "number" ? 'data-count="' + s.value + '"' : ""}>${s.value}${s.total !== undefined ? "<small> / " + s.total + "</small>" : ""}</b><span>${s.label}</span></a>`).join("")}</nav>${due.length ? `<div class="due-panel"><h2>今日到期</h2><ul>${due.map((d) => `<li><strong>${esc(d.title)}</strong><small>${esc(d.plan || "")}</small></li>`).join("")}</ul></div>` : ""}${recentNotes.length ? `<div class="recent-notes"><h2>最近笔记</h2><nav>${recentNotes.map((n) => `<a href="#module/knowledge" data-action="select-note" data-id="${esc(n.id)}">${esc(n.data.title)}</a>`).join("")}</nav></div>` : ""}</section>${
    state.recent.length
      ? `<section class="recent-section"><h2>继续上次工作</h2><nav class="recent-links">${state.recent
          .map((id) => modules.find((m) => m.id === id))
          .filter(Boolean)
          .map((m) => `<a href="#module/${m.id}">${icon(m.icon)}${m.title}</a>`)
          .join("")}</nav></section>`
      : ""
  }</section>`;
}
function startPage() {
  return `<section class="home-start" aria-label="时列开始页">${orbitStage()}</section>`;
}
/* 兼容旧调用：没有指定视图时默认落在开始页。 */
function home() {
  return startPage();
}
function category(id) {
  const group = groups.find((g) => g.id === id);
  if (!group) return home();
  return frame(
    group.title,
    `<p class="lede">${group.caption}</p><nav class="module-options">${modules
      .filter((m) => m.group === id)
      .map(
        (m) =>
          `<a class="module-option" href="#module/${m.id}"><span class="module-icon">${icon(m.icon)}</span><span><h3>${m.title}</h3><p>${m.id === "knowledge" ? "记录、检索和整理个人知识" : m.id === "jobs" ? "岗位、投递、跟进与面试复盘" : m.id === "company-capabilities" ? "目标公司需要的技能、重要度与证据状态" : m.id === "lessons" ? "记录犯过的错误，按类型归档，下次绕开" : m.id === "planning" ? "目标、阶段、优先级和依赖" : m.id === "stages" ? "成果、问题、改动和验证" : m.id === "workflows" ? "知识处理、检索与回答流程" : m.id === "documents" ? "搜索个人内容并查看引用" : "查看和管理工作区设置"}</p></span>${arrow}</a>`,
      )
      .join("")}</nav>`,
  );
}
function tabs(module, choices, selected) {
  return `<nav class="segmented local-tabs" aria-label="${module}视图">${choices.map(([id, label]) => `<a href="#module/${module}/${id}" aria-current="${id === selected ? "page" : "false"}">${label}</a>`).join("")}</nav>`;
}
function noteCard(n) {
  return `<button class="note-card ${state.selectedNote === n.id ? "active" : ""}" data-action="select-note" data-id="${n.id}"><strong>${highlight(n.data.title, state.query)}</strong><small>${esc((n.data.tags || []).join(" · ") || "未分类")}</small><span>${highlight(n.data.content.slice(0, 86), state.query)}</span></button>`;
}
/* 知识页空态：三张虚线示意卡展示条目形态，替代无意义的空面板（2026-10-24 首页 v2 轮）。 */
function knowledgeEmpty(term) {
  if (term)
    return `<section class="empty-panel"><h2>没有匹配的知识条目</h2><p>换个关键词，或清除搜索条件。</p>${btn("清除搜索", "clear-search")}</section>`;
  const demos = [
    ["排查记录", "现象 → 原因 → 处置，下次直接搜到"],
    ["读书摘录", "来源页码 + 原文 + 自己的一句话"],
    ["面试错题", "题目、当时答错点、正确口径"],
  ];
  return `<nav class="demo-grid" aria-label="条目形态示意">${demos.map(([t, d]) => `<article class="demo-card"><h3>${t}</h3><p>${d}</p></article>`).join("")}</nav><section class="empty-panel"><h2>这里还没有知识条目</h2><p>写下第一条经验、想法或资料，保存后会进入个人知识库。</p>${btn("创建第一条笔记", "new-note", "primary-button")}</section>`;
}
function relatedNotes(target) {
  const tags = new Set((target.data.tags || []).map((tag) => tag.toLowerCase()));
  const titleTerms = new Set(
    (target.data.title || "")
      .toLowerCase()
      .match(/[a-z0-9]{2,}|[\u4e00-\u9fa5]{2,}/g) || [],
  );
  return state.knowledge
    .filter((note) => note.id !== target.id)
    .map((note) => {
      const otherTags = (note.data.tags || []).map((tag) => tag.toLowerCase());
      const tagHits = otherTags.filter((tag) => tags.has(tag)).length;
      const titleHits = Array.from(titleTerms).filter((term) =>
        (note.data.title || "").toLowerCase().includes(term),
      ).length;
      return { note, score: tagHits * 3 + titleHits * 2, tagHits, titleHits };
    })
    .filter((item) => item.score > 0)
    .sort((a, b) => b.score - a.score || a.note.id.localeCompare(b.note.id))
    .slice(0, 5);
}
function knowledgeSelection() {
  const term = state.query.trim().toLowerCase();
  const filtered = state.knowledge.filter(
    (n) =>
      state.filter === "all" ||
      (state.filter === "notes" ? !n.data.source : n.data.source),
  );
  const rows = filtered.filter((n) => {
    const d = n.data;
    return (
      !term ||
      [d.title, d.content, ...(d.tags || [])]
        .join(" ")
        .toLowerCase()
        .includes(term)
    );
  });
  const selected = rows.find((n) => n.id === state.selectedNote) || rows[0];
  if (selected) state.selectedNote = selected.id;
  return { term, rows, selected };
}
export function knowledgePanelHtml() {
  const { term, rows, selected } = knowledgeSelection();
  if (!rows.length) return knowledgeEmpty(term);
  const related = relatedNotes(selected);
  return `<div class="knowledge-grid"><nav class="knowledge-list" aria-label="知识列表">${rows.map(noteCard).join("")}</nav><article class="document"><div class="document-toolbar"><span>${esc(selected.data.source || (selected.data.tags || []).join(" · ") || "个人知识")} · v${selected.version}</span><div>${btn("历史", "history-note")}${btn("编辑", "edit-note")}${btn("删除", "delete-note", "text-button")}</div></div><h2>${highlight(selected.data.title, state.query)}</h2><div class="document-content">${selected.data.content
    .split(/\n{2,}/)
    .map(
      (part) =>
        `<p>${highlight(part, state.query).replace(/\n/g, "<br>")}</p>`,
    )
    .join(
      "",
    )}</div>${(selected.data.tags || []).length ? `<div class="inline-tags">${selected.data.tags.map((t) => `<span>${esc(t)}</span>`).join("")}</div>` : ""}${related.length ? `<section class="related-notes"><h3>相关笔记</h3><div>${related.map(({ note, tagHits, titleHits }) => `<button class="related-note" data-action="related-note" data-id="${note.id}"><strong>${esc(note.data.title)}</strong><span>${tagHits ? `标签重合 ${tagHits}` : `标题相关 ${titleHits}`}</span></button>`).join("")}</div></section>` : ""}</article></div>`;
}
function knowledge() {
  const hasAny = (state.knowledge || []).length > 0;
  return frame(
    "个人知识库",
    `${
      hasAny
        ? tabs(
            "knowledge",
            [
              ["all", "全部"],
              ["notes", "笔记"],
              ["resources", "资料"],
            ],
            state.filter,
          )
        : ""
    }<div class="module-toolbar">${hasAny ? `<label class="search-field">${icon("search")}<input id="knowledge-search" type="search" placeholder="搜索标题、正文或标签" value="${esc(state.query)}"></label>` : ""}<div class="toolbar-actions">${btn("回收站", "trash-notes")}${btn("新建笔记", "new-note", "primary-button")}</div></div><div id="knowledge-panel">${knowledgePanelHtml()}</div>`,
  );
}
/* 网页收藏：分类 chips + 外链卡片；标题本身就是链接，点击直达原网页（新标签页、noopener）。 */
function bookmarkCategories() {
  return [
    "全部",
    ...new Set((state.bookmarks || []).map((b) => b.data.category || "未分类")),
  ];
}
function bookmarkHost(url) {
  try {
    return new URL(url).hostname.replace(/^www\./, "");
  } catch {
    return "";
  }
}
function bookmarksEmpty() {
  const demos = [
    ["文档与教程", "官方文档、规范与参考手册"],
    ["待读文章", "先存下来，读完再挪分类"],
    ["工具与服务", "常用平台入口，一键直达"],
  ];
  return `<nav class="demo-grid" aria-label="收藏分类示意">${demos.map(([t, d]) => `<article class="demo-card"><h3>${t}</h3><p>${d}</p></article>`).join("")}</nav><section class="empty-panel"><h2>还没有网页收藏</h2><p>保存常用网址并按分类整理，点击标题即可跳转。</p>${btn("新建收藏", "new-bookmark", "primary-button")}</section>`;
}
export function bookmarksPanelHtml() {
  const rows = (state.bookmarks || []).filter(
    (b) =>
      state.bookmarkFilter === "全部" ||
      (b.data.category || "未分类") === state.bookmarkFilter,
  );
  if (!(state.bookmarks || []).length) return bookmarksEmpty();
  if (!rows.length)
    return `<section class="empty-panel"><h2>该分类下暂无收藏</h2><p>换个分类，或把新网址保存到这个分类。</p><button class="small-button" data-action="bookmark-category" data-value="全部">查看全部</button></section>`;
  return `<div class="bookmark-grid">${rows
    .map((b) => {
      const tags = (b.data.tags || [])
        .map((t) => `<span>${esc(t)}</span>`)
        .join("");
      return `<article class="bookmark-card"><header><a class="bookmark-title" href="${esc(b.data.url)}" target="_blank" rel="noopener noreferrer" title="${esc(b.data.url)}">${esc(b.data.title)}${icon("link")}</a><span class="bookmark-domain">${esc(bookmarkHost(b.data.url))}</span></header>${b.data.note ? `<p class="bookmark-note">${esc(b.data.note)}</p>` : ""}<footer><span class="bookmark-category">${esc(b.data.category)}</span>${tags ? `<span class="bookmark-tags">${tags}</span>` : ""}<span class="bookmark-actions">${btn("编辑", "edit-bookmark", "small-button", `data-id="${esc(b.id)}"`)}${btn("删除", "delete-bookmark", "text-button", `data-id="${esc(b.id)}"`)}</span></footer></article>`;
    })
    .join("")}</div>`;
}
function bookmarksView() {
  const cats = bookmarkCategories();
  /* 分类被删空或改名后，旧筛选回落到「全部」，避免停在不可见的空分类上。 */
  if (!cats.includes(state.bookmarkFilter)) state.bookmarkFilter = "全部";
  return frame(
    "网页收藏",
    `<div class="module-toolbar"><nav class="category-chips" aria-label="收藏分类">${cats
      .map(
        (c) =>
          `<button class="category-chip" type="button" data-action="bookmark-category" data-value="${esc(c)}" aria-pressed="${c === state.bookmarkFilter}">${esc(c)}</button>`,
      )
      .join("")}</nav><div class="toolbar-actions">${btn("回收站", "bookmark-trash")}${btn("新建收藏", "new-bookmark", "primary-button")}</div></div><div id="bookmark-panel">${bookmarksPanelHtml()}</div>`,
  );
}
function stagePage() {
  if (state.stageError)
    return frame(
      "阶段记录",
      `<section class="empty-panel"><h2>阶段记录暂不可用</h2><p>${esc(state.stageError)}</p>${btn("重试", "refresh", "primary-button")}</section>`,
    );
  return frame(
    "阶段记录",
    `<div class="module-toolbar"><div><p>实时读取阶段账本，展示完成项、问题、验证和文件改动。</p><small>最近更新：${esc(state.stageTime)}</small></div><div>${btn("刷新", "refresh")}${btn("记录新阶段", "new-stage", "primary-button")}</div></div>${state.stages.length ? `<div class="stage-list">${state.stages.map((s) => `<details class="fold-section"><summary><span><strong>${esc(s.title)}</strong><small>${esc(s.completed_at || s.created_at)} · ${s.status === "passed" ? "验证通过" : s.status === "running" ? "进行中" : "待关注"}</small></span><b>${s.changes?.length || 0} 项改动</b></summary><div class="fold-body">${s.status === "running" ? `<button class="primary-button" data-action="finish-stage" data-id="${esc(s.id)}">记录完成结果</button>` : ""}${s.status !== "running" && s.id.startsWith("20") ? `<div class="stage-actions"><button class="small-button" data-action="stage-check" data-id="${esc(s.id)}">回滚预检</button><a class="small-button" href="/api/stages/${esc(s.id)}/diff" target="_blank" rel="noopener">查看差异</a>${s.data_snapshot_available ? `<button class="small-button" data-action="restore-stage-data" data-id="${esc(s.id)}">恢复阶段数据</button>` : ""}</div>` : ""}<section><h3>完成</h3><ul>${(s.completed || []).map((i) => `<li>${esc(i)}</li>`).join("") || "<li>尚未记录</li>"}</ul></section>${s.issues?.length ? `<section><h3>问题与遗留</h3><ul>${s.issues.map((i) => `<li>${esc(i)}</li>`).join("")}</ul></section>` : ""}<section><h3>验证</h3><ul>${(s.verification || []).map((i) => `<li>${esc(i)}</li>`).join("") || "<li>尚未记录</li>"}</ul></section><section><h3>改动文件 · ${s.changes?.length || 0}</h3><ul>${(s.changes || []).map((c) => `<li><code>${esc(c.path)}</code><small>${esc(c.scope || c.kind || "改动")}</small></li>`).join("") || "<li>无文件变更</li>"}</ul></section><p>${esc(s.recovery || "源码快照支持预检回滚")}</p></div></details>`).join("")}</div>` : '<section class="empty-panel"><h2>还没有阶段记录</h2><p>开始一个阶段后，完成项、问题和验证结果都会记录下来。</p></section>'}`,
  );
}
/* 检索页 hero：初始态居中大标题+大搜索框+示例 chips（点击真搜）+最近搜索；有结果后收为紧凑表单。 */
const SEARCH_EXAMPLES = [
  "RPA 主动加好友命令 wechat.add_friend 的命令号是多少？",
  "composer.lock 锁定的 topthink/framework 版本是多少？",
  "pathlib 的 glob 模式里 ** 匹配什么？",
  "pgvector 默认执行什么搜索？",
];
function searchForm(compact) {
  return `<form id="search-form" class="${compact ? "search-panel" : "search-hero-form"}" aria-busy="${state.searchBusy}"><label class="${compact ? "" : "hero-search-label"}">${compact ? "问题或关键词" : ""}<input name="query" value="${esc(state.searchInput)}" placeholder="例如：连接超时如何排查？" ${compact ? "" : 'class="hero-search-input"'} required></label><div class="search-options"><label>检索范围<select name="scope">${[
    ["all", "全部内容"],
    ["personal", "个人知识"],
    ["docs", "技术文档"],
    ["planning", "人生规划"],
  ]
    .map(
      ([v, t]) =>
        `<option value="${v}" ${state.scope === v ? "selected" : ""}>${t}</option>`,
    )
    .join(
      "",
    )}</select></label>${corpusSelect()}<label><input type="checkbox" name="generate" ${state.generate ? "checked" : ""}> 尝试生成 AI 回答</label><button type="submit" class="primary-button" ${state.searchBusy ? "disabled" : ""}>${state.searchBusy ? "搜索中…" : "搜索"}</button></div></form>`;
}
function searchPage() {
  const initial =
    !state.searchResult && !state.searchBusy && !state.searchError;
  const hero = `<section class="search-hero" aria-label="技术文档检索"><h1>技术文档检索</h1><p class="search-hero-sub">内部生产文档与公开技术文档，同一套向量检索与重排</p>${searchForm(false)}<nav class="example-chips" aria-label="示例查询">${SEARCH_EXAMPLES.map((q) => `<button type="button" class="example-chip" data-action="search-example" data-value="${esc(q)}">${esc(q)}</button>`).join("")}</nav>${
    state.runs.length
      ? `<nav class="recent-search-chips" aria-label="最近搜索">${state.runs
          .slice(0, 6)
          .map(
            (q) =>
              `<button type="button" class="example-chip recent" data-action="search-example" data-value="${esc(q)}">${esc(q)}</button>`,
          )
          .join("")}</nav>`
      : ""
  }</section>`;
  if (initial) return hero;
  return `${state.searchBusy ? hero : ""}<form id="search-form" class="search-panel" aria-busy="${state.searchBusy}"><label>问题或关键词<input name="query" value="${esc(state.searchInput)}" placeholder="例如：连接超时如何排查？" required></label><div class="search-options"><label>检索范围<select name="scope">${[
    ["all", "全部内容"],
    ["personal", "个人知识"],
    ["docs", "技术文档"],
    ["planning", "人生规划"],
  ]
    .map(
      ([v, t]) =>
        `<option value="${v}" ${state.scope === v ? "selected" : ""}>${t}</option>`,
    )
    .join(
      "",
    )}</select></label>${corpusSelect()}<label><input type="checkbox" name="generate" ${state.generate ? "checked" : ""}> 尝试生成 AI 回答</label><button type="submit" class="primary-button" ${state.searchBusy ? "disabled" : ""}>${state.searchBusy ? "搜索中…" : "搜索"}</button></div>${state.searchBusy ? '<p role="status">正在检索，请稍候…</p>' : ""}${state.searchError ? `<p class="error-text" role="alert">${esc(state.searchError)}</p>` : ""}${state.searchResult ? `<p class="result-meta">“${esc(state.searchResultQuery)}”的结果 · ${esc(state.searchResult.engine)}${state.searchResult.namespace ? " / " + esc(state.searchResult.namespace) : ""}${state.searchResult.notes?.length ? " · " + esc(state.searchResult.notes.join("；")) : ""}</p>${state.searchResult.answer ? `<article class="answer-card">${esc(state.searchResult.answer)}</article>` : ""}<div class="result-list">${state.searchResult.hits.map((h) => `<article class="result-card"><small>${esc(h.category)} · ${esc(h.source || "个人内容")}${h.status_marker && h.status_marker !== "UNKNOWN" ? " · " + esc(h.status_marker) : ""}</small><h3>${highlight(h.title || h.data?.title, state.searchResultQuery)}</h3><p>${highlight(h.content || h.data?.content, state.searchResultQuery)}</p></article>`).join("") || "<p>没有找到相关内容。</p>"}</div>` : ""}</form>`;
}
function simple(id) {
  const title = modules.find((m) => m.id === id)?.title || "工作区";
  if (id === "agents") return frame(title, agentsPage());
  if (id === "connections") return frame(title, modelConnectionView());
  if (id === "backup") return frame(title, backupView());
  if (id === "runs") return frame(title, runsPage());
  if (id === "workflows") return frame("工作流", workflowsPage());
  return frame(
    title,
    '<section class="empty-panel"><h2>开始搜索工作区</h2><a class="primary-button" href="#module/documents">前往检索</a></section>',
  );
}
function appearance() {
  return frame(
    "界面偏好",
    `<section class="module-surface settings-surface"><label class="settings-row">导航模式<select id="mode-select"><option value="portal" ${state.mode === "portal" ? "selected" : ""}>入口模式</option><option value="sidebar" ${state.mode === "sidebar" ? "selected" : ""}>侧栏模式</option></select></label><label class="settings-row"><span>页面密度</span><span class="density-control"><output id="density-output" for="density-range">${["紧凑", "标准", "宽松"][state.density]}</output><input id="density-range" class="density-slider" type="range" min="0" max="2" step="1" value="${state.density}" aria-label="页面密度"><span class="density-labels"><span>紧凑</span><span>标准</span><span>宽松</span></span></span></label><label class="settings-row"><span>首页插画尺寸</span><select id="hero-size"><option value="full" ${!state.compactHero ? "selected" : ""}>完整</option><option value="compact" ${state.compactHero ? "selected" : ""}>紧凑</option></select></label></section><section class="module-surface settings-surface"><h2>验收与观测</h2><div class="observability-actions"><button class="primary-button" data-action="run-tour">▶ 运行验收巡游</button><button class="small-button" data-action="toggle-director" aria-pressed="${directorActive()}">◉ ${directorActive() ? "关闭事件直播" : "开启事件直播"}</button></div><p class="settings-hint">巡游对页面做只读自检；事件直播把页面里的导航、点击与报错实时列在右侧面板。</p></section>${serverStatusView()}`,
  );
}
export function render() {
  if (state.authRequired) {
    /* 账号密码登录（服务器配置 WORKSPACE_USER/PASSWORD_HASH 后启用），令牌登录保留为备用 */
    const account = state.accountLogin && state.loginMode !== "token";
    return `<form id="login-form" class="module-surface login-panel"><h1>进入时列工作区</h1>${
      account
        ? `<p>使用账号登录。</p>
        <label class="form-field">账号<input name="username" type="text" autocomplete="username" required maxlength="64"></label>
        <label class="form-field">密码<input name="password" type="password" autocomplete="current-password" required maxlength="256"></label>
        <label class="form-check"><input type="checkbox" name="remember"> 记住此账号 30 天</label>`
        : `<p>输入服务器设置的访问令牌。</p>
        <label class="form-field">访问令牌<input name="token" type="password" autocomplete="current-password" required></label>`
    }<p id="login-error" class="error-text" role="alert" hidden></p><button class="primary-button" type="submit">进入工作区</button>${
      state.accountLogin
        ? `<button type="button" class="small-button login-switch" data-action="login-mode">${account ? "改用访问令牌登录" : "改用账号登录"}</button>`
        : ""
    }</form>`;
  }
  if (state.loading)
    return `<section class="loading-panel" role="status" aria-live="polite"><p>正在连接工作区…</p>${Array.from({ length: 3 }, () => '<div class="skeleton-row" aria-hidden="true"></div>').join("")}</section>`;
  if (state.error)
    return `<section class="empty-panel"><h2>工作区暂不可用</h2><p>${esc(state.error)}</p><button class="primary-button" data-action="retry">重试</button></section>`;
  const [kind, id, tab] = location.hash.slice(1).split("/");
  if (kind === "home" && id === "workspace") return workspacePage();
  if (kind === "category") return category(id);
  if (kind !== "module" || !modules.some((m) => m.id === id)) return startPage();
  if (id === "knowledge") {
    if (["all", "notes", "resources"].includes(tab)) state.filter = tab;
    return knowledge();
  }
  if (id === "bookmarks") return bookmarksView();
  if (id === "planning") {
    if (["story", "tasks", "relations"].includes(tab)) state.view = tab;
    return treeView();
  }
  if (id === "stages") return stagePage();
  if (id === "lessons") return lessonsView();
  if (id === "jobs") return jobsView();
  if (id === "company-capabilities") return capabilitiesView();
  if (id === "collaboration") return collaborationView();
  if (id === "agent-studio") return agentStudioView();
  if (id === "job-insights") return jobInsightsView();
  if (id === "job-weekly") return jobWeeklyView();
  if (id === "learning") return learningView();
  if (id === "notifications") return notificationsView();
  if (id === "workflows") return frame("工作流", workflowsPage());
  if (id === "documents") return searchPage();
  if (id === "evaluation") return evaluationView();
  if (id === "private") return privateView();
  if (id === "appearance") return appearance();
  return simple(id);
}
export function sidebar() {
  return `<a class="nav-link" href="#home">${icon("home")}工作区首页</a>${groups
    .map(
      (g) =>
        `<section><h2>${g.title}</h2>${modules
          .filter((m) => m.group === g.id)
          .map(
            (m) =>
              `<a class="nav-link" href="#module/${m.id}" ${location.hash.includes(m.id) ? 'aria-current="page"' : ""}>${icon(m.icon)}${m.title}</a>`,
          )
          .join("")}</section>`,
    )
    .join("")}`;
}
export function dialogs() {
  return (
    treeDialog() +
    automationDialogs() +
    lessonsDialog() +
    jobsDialog() +
    capabilitiesDialog() +
    learningDialogs() +
    jobProfileDialog() +
    `${dialog("knowledge", "笔记", `${field("标题", "title")}${textarea("正文", "content")}<label class="form-field">标签（用逗号分隔）<input name="tags"></label>${field("来源", "source")}${actions()}`)}${dialog("bookmark", "网页收藏", `${field("标题", "title")}<label class="form-field">网址<input name="url" type="url" inputmode="url" required maxlength="2048" placeholder="https://example.com"><small>只接受完整的 http/https 链接</small></label><label class="form-field">分类（留空为未分类）<input name="category" maxlength="24" placeholder="例如：文档与教程"></label><label class="form-field">标签（用逗号分隔）<input name="tags"></label>${textarea("备注", "note", "", 5)}${actions()}`)}${dialog("stage", "阶段记录", `${field("阶段名称", "title")}${textarea("目标", "objective", "", 4)}${actions()}`)}`
  );
}
export function detail(title, html) {
  return `<h2>${esc(title)}</h2>${html}`;
}
