import { layoutStory, geometry } from "./story-layout.js?v=109";
import { branchNotice, branchDialog } from "./branch-actions.js?v=109";
/* 主线向右分叉，支线向下展开；显示状态与服务端记录分离。 */
import { state, read, write } from "./data.js?v=109";
export const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
export const treeState = {
  kind: read("tree-kind", "main"),
  planId: "",
  selected: "",
  folded: read("tree-folded", []),
  busy: false,
  auto: read("story-auto", true),
  zoom: 1,
};
if (!["main", "side"].includes(treeState.kind)) treeState.kind = "main";
if (!Array.isArray(treeState.folded)) treeState.folded = [];
const action = (label, name, extra = "", cls = "tree-button") =>
  `<button class="${cls}" data-action="tree-${name}" ${extra}>${label}</button>`;
const status = (n) =>
  n.done ? "已完成" : n.state === "locked" ? "等待前置" : "可开始";
export const treePlan = () =>
  state.plans.find(
    (p) => p.id === treeState.planId && p.data.kind === treeState.kind,
  ) || state.plans.find((p) => p.data.kind === treeState.kind);
export const treeNodes = () =>
  treePlan()?.data.acts.flatMap((a) => a.nodes) || [];
export const rootId = () => {
  let id = "@root:" + treePlan()?.id;
  const ids = new Set(treeNodes().map((n) => n.id));
  while (ids.has(id)) id += "@";
  return id;
};

/* 展开/收起状态持久化，刷新后保留。返回切换后的折叠状态。 */
export const isFolded = (id) => treeState.folded.includes(id);
export function setFolded(id, folded) {
  if (folded === undefined) {
    folded = !treeState.folded.includes(id);
  }
  treeState.folded = folded
    ? [...new Set([...treeState.folded, id])]
    : treeState.folded.filter((v) => v !== id);
  write("tree-folded", treeState.folded);
  return folded;
}

/* 节点完成状态：节点自身done，或其子树全部完成——方向行据此显示汇总进度 */
const nodeDone = (n) => !!n.done;
export function subtree(nodes, id) {
  return nodes.filter((n) => n.parent_id === id);
}
export function progressOf(nodes) {
  const done = nodes.filter(nodeDone).length;
  return {
    done,
    total: nodes.length,
    percent: nodes.length ? Math.round((done / nodes.length) * 100) : 0,
  };
}

export function cardProgress(n, nodes) {
  const ids = new Set(n.root ? nodes.map((x) => x.id) : [n.id]);
  if (!n.root) {
    let size;
    do {
      size = ids.size;
      for (const item of nodes) if (ids.has(item.parent_id)) ids.add(item.id);
    } while (ids.size !== size);
  }
  const members = nodes.filter((x) => ids.has(x.id));
  if (n.root) members.push(n);
  return progressOf(members);
}

export function treeView() {
  const p = treePlan(),
    plans = state.plans.filter((x) => x.data.kind === treeState.kind);
  if (p) treeState.planId = p.id;
  const root = p
    ? {
        id: rootId(),
        title: p.data.title,
        kind: p.data.kind,
        done: !!p.data.done,
        root: true,
      }
    : null;
  const graph = root ? layoutStory(root, treeNodes(), treeState.folded) : null;
  const cards =
    graph?.cards
      .map((n) => {
        const kids = n.root
          ? treeNodes().filter((k) => !k.parent_id)
          : subtree(treeNodes(), n.id);
        const main = n.kind === "main",
          folded = isFolded(n.id),
          progress = cardProgress(n, treeNodes());
        return `<article class="story-card ${main ? "story-main" : "story-side"} ${treeState.selected === n.id ? "selected" : ""}" data-story-id="${esc(n.id)}" style="left:${n.x}px;top:${n.y}px">
   <button class="story-title" title="单击展开或收起，双击编辑详情；按 F2 编辑" data-action="tree-fold" data-id="${esc(n.id)}" aria-expanded="${!folded}"><small>${main ? "主线" : "支线"}</small><strong>${esc(n.title)}</strong><span>${kids.length ? `${folded ? "▸" : "▾"} ${kids.length} 个分支` : "暂无分支"}${n.done ? " · 已完成" : ""}</span></button>
   ${action("×", "delete", `data-id="${esc(n.id)}" aria-label="删除 ${esc(n.title)}" title="删除"`, "story-delete")}
   <div class="story-progress"><button data-action="tree-toggle" data-id="${esc(n.id)}" aria-label="${n.done ? "撤销完成" : "完成"} ${esc(n.title)}" aria-pressed="${!!n.done}" ${treeState.busy || (n.state === "locked" && !n.done) ? "disabled" : ""}>${n.done ? "✓ 已完成" : "○ 完成本项"}</button><span title="包含本项及下级任务">${progress.done}/${progress.total} · ${progress.percent}%</span><div class="story-progress-track" role="progressbar" aria-label="${esc(n.title)} 完成进度" aria-valuemin="0" aria-valuemax="100" aria-valuenow="${progress.percent}"><i style="width:${progress.percent}%"></i></div></div>

   ${main ? action("＋", "add", `data-parent="${n.root ? "" : esc(n.id)}" data-kind="main" aria-label="在 ${esc(n.title)} 后添加主线" title="添加后续主线（可添加多个）"`, "story-add story-add-main") : ""}
   ${action("＋", "add", `data-parent="${n.root ? "" : esc(n.id)}" data-kind="side" aria-label="在 ${esc(n.title)} 下添加支线" title="添加支线（可添加多个）"`, "story-add story-add-side")}

  </article>`;
      })
      .join("") || "";
  const paths =
    graph?.edges
      .map((e) => {
        const a = e.from,
          b = e.to,
          g = geometry;
        const d =
          e.kind === "main"
            ? `M${a.x + g.width} ${a.y + 48} H${b.x - 36} V${b.y + 48} H${b.x}`
            : `M${a.x + 12} ${a.y + g.height} V${b.y + 40} H${b.x}`;
        return `<path class="${e.kind}" d="${d}"/>`;
      })
      .join("") || "";
  return `<section class="planning-studio"><header class="studio-heading"><div><h1>人生规划</h1><p>主线向右延伸，支线向下展开</p></div>${action("＋ 新建主线", "new-plan", "", "primary-button")}</header>${branchNotice(p)}
 <div class="studio-toolbar"><nav class="tree-kind-switch">${["main", "side"].map((k) => action(k === "main" ? "主线规划" : "独立支线", "kind", `data-kind="${k}" aria-pressed="${treeState.kind === k}"`)).join("")}</nav>
 ${plans.length ? `<select id="tree-plan-picker" aria-label="切换规划">${plans.map((row) => `<option value="${row.id}" ${row.id === p?.id ? "selected" : ""}>${esc(row.data.title)}</option>`).join("")}</select>` : ""}
 ${action("全部展开", "expand-all")}${action("全部收起", "fold-all")}
 <label class="story-auto"><input type="checkbox" id="story-auto" ${treeState.auto ? "checked" : ""}> 自动居中</label>${action("居中当前", "center")}${action("查看全图", "fit")}</div>
 ${graph ? `<div class="story-viewport" tabindex="0" aria-label="规划画布，可拖动空白区域"><div class="story-space" style="width:${graph.width * treeState.zoom}px;height:${graph.height * treeState.zoom}px"><div class="story-canvas" style="width:${graph.width}px;height:${graph.height}px;transform:scale(${treeState.zoom})"><svg width="${graph.width}" height="${graph.height}" aria-hidden="true">${paths}</svg>${cards}</div></div></div><footer class="story-footer"><span>单击展开 · 双击编辑 · 拖动空白处移动视角</span><label>缩放 <input id="story-zoom" type="range" min="40" max="140" step="5" value="${treeState.zoom * 100}"><output>${Math.round(treeState.zoom * 100)}%</output></label></footer>` : `<div class="story-empty"><h2>从第一条主线开始</h2><p>添加主线后，可以向右分叉、向下添加支线。</p>${action("＋ 新建规划", "new-plan", "", "primary-button")}</div>`}</section>`;
}

export function treeDialog() {
  return (
    branchDialog() +
    `<dialog id="tree-editor" class="form-dialog" aria-labelledby="tree-editor-title"><form id="tree-edit-form"><header class="drawer-header"><div><small>时列 · 人生规划</small><h2 id="tree-editor-title">添加下一步</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭编辑">×</button></header><div class="drawer-content"><p id="tree-add-context" class="tree-add-context"></p><label class="form-field">你想做什么？<input name="title" required maxlength="160" placeholder="例如：读完一本书" autocomplete="off"></label><p class="entry-hint">只填这一项就能保存，其余可以以后再补。</p><label hidden>添加位置<select name="parent_id"></select></label><label hidden data-root-field>类型<select name="kind"><option value="main">主线</option><option value="side">支线</option></select></label><details class="tree-optional"><summary>补充信息 <span>可不填</span></summary><label class="form-field">说明（选填）<textarea name="description" rows="3" maxlength="20000" placeholder="想补充什么，就写在这里"></textarea></label><div data-node-fields><label class="form-field">计划日期（选填）<div class="optional-date"><input name="due_date" type="date" aria-describedby="date-hint"><button type="button" data-action="tree-clear-date" class="tree-button">清除日期</button></div><small id="date-hint">不确定时间就留空，不影响添加和完成。</small></label><label class="form-field">优先级（可不选）<select name="priority">${["p0", "p1", "p2", "p3", "p4"].map((p, i) => `<option value="${p}">${["P0 · 最重要", "P1 · 优先做", "P2 · 常规（默认）", "P3 · 稍后做", "P4 · 有空再做"][i]}</option>`).join("")}</select></label><label class="form-field">需要先完成哪些任务？（选填）<select name="requires" multiple></select><small>没有要求就留空，按 Ctrl 可选多个。</small></label></div></details><p class="tree-form-error error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存</button></div></div></form></dialog>`
  );
}
