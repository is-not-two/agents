/* 剧情层级视图；阶段和任务状态来自 API，折叠只是显示偏好。 */
import { state, priorities, priorityNames } from "./data.js?v=106";
const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const status = {
  draft: "待编排",
  done: "已完成",
  available: "可开始",
  locked: "等待前置",
};
const open = (key, fallback = false) =>
  (state.storyOpen[key] ?? fallback) ? "open" : "";
const match = (t) =>
  (state.priority === "all" || t.priority === state.priority) &&
  (state.taskStatus === "all" || t.state === state.taskStatus);
function taskNode(t, p, act) {
  const byId = Object.fromEntries(
    p.data.acts.flatMap((a) => a.nodes).map((n) => [n.id, n]),
  );
  return `<details class="story-task ${t.state}" data-story-key="node:${t.id}" ${open("node:" + t.id)}><summary><span class="story-status-dot"></span><span><strong>${esc(t.title)}</strong><small>${t.priority.toUpperCase()} · ${status[t.state]}${t.due_date ? " · " + esc(t.due_date) : ""}</small></span><span class="fold-chevron">⌄</span></summary><div class="story-task-body"><p class="preserve-lines">${esc(t.description || "还没有任务说明。")}</p><div class="prerequisite-list"><small>解锁条件</small>${t.requires.length ? t.requires.map((id) => `<span class="${byId[id]?.done ? "met" : "waiting"}">${byId[id]?.done ? "✓" : "○"} ${esc(byId[id]?.title || id)}</span>`).join("") : "<span>无前置任务，可以直接开始</span>"}</div><div class="story-task-actions"><button class="primary-button" data-action="toggle-task" data-id="${esc(t.id)}" ${state.pendingTaskId || (!t.done && t.state === "locked") ? "disabled" : ""}>${state.pendingTaskId === t.id ? "保存中…" : t.done ? "撤销完成" : "完成任务"}</button><button class="small-button" data-action="edit-task" data-id="${esc(t.id)}" ${state.pendingTaskId ? "disabled" : ""}>编辑任务</button><button class="text-button" data-action="delete-task" data-id="${esc(t.id)}" ${state.pendingTaskId ? "disabled" : ""}>移除</button></div></div></details>`;
}
function chapter(a, index, p) {
  const nodes = a.nodes.filter(match),
    pr = a.progress || { done: 0, total: a.nodes.length };
  return `<details class="story-chapter" data-story-key="act:${a.id}" ${open("act:" + a.id, index === 0)}><summary><span class="chapter-index">${String(index + 1).padStart(2, "0")}</span><span class="chapter-label"><small>第 ${index + 1} 章 · ${status[a.state] || "待编排"}</small><strong>${esc(a.title)}</strong></span><span class="chapter-progress">${pr.done}/${pr.total}</span><span class="fold-chevron">⌄</span></summary><div class="chapter-body">${a.description ? `<p class="chapter-description preserve-lines">${esc(a.description)}</p>` : ""}<div class="chapter-tools"><button class="small-button" data-action="new-task-act" data-id="${esc(a.id)}">添加任务</button><button class="text-button" data-action="edit-act" data-id="${esc(a.id)}">编辑章节</button>${!a.nodes.length ? `<button class="text-button" data-action="delete-act" data-id="${esc(a.id)}">删除空章节</button>` : ""}</div>${nodes.length ? nodes.map((t) => taskNode(t, p, a)).join("") : `<p class="empty-state">${a.nodes.length ? "当前筛选条件下没有任务。" : "这一章还没有任务，可以先写阶段目标，再添加任务。"}</p>`}</div></details>`;
}
export function storyBoard() {
  return `<div class="story-board">${["main", "side"]
    .map((kind) => {
      const rows = state.plans.filter((p) => p.data.kind === kind);
      return rows.length
        ? `<section class="story-group"><h3>${kind === "main" ? "主线剧情" : "支线探索"}<small>${rows.length} 条规划</small></h3>${rows.map((p) => `<details class="storyline" data-plan-id="${esc(p.id)}" data-story-key="plan:${p.id}" ${open("plan:" + p.id, true)}><summary><span class="storyline-mark ${kind}">${kind === "main" ? "主" : "支"}</span><span class="storyline-title"><strong>${esc(p.data.title)}</strong><small>${p.data.acts.length} 个章节 · 完成 ${p.data.progress.done}/${p.data.progress.total}</small></span><span class="fold-chevron">⌄</span></summary><div class="storyline-body">${p.data.description ? `<p class="story-description preserve-lines">${esc(p.data.description)}</p>` : ""}<div class="chapter-tools"><button class="small-button" data-action="new-act">新增章节</button><button class="text-button" data-action="edit-plan">编辑规划</button></div><div class="chapter-timeline">${p.data.acts.map((a, i) => chapter(a, i, p)).join("") || '<p class="empty-state">添加第一章，开始编排这条规划。</p>'}</div></div></details>`).join("")}</section>`
        : "";
    })
    .join("")}</div>`;
}
