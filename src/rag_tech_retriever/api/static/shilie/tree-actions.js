import { bindBranch } from "./branch-actions.js?v=112";
import { api, state, write } from "./data.js?v=112";
import {
  treeState as s,
  treePlan,
  treeNodes,
  rootId,
  esc,
  isFolded,
  setFolded,
} from "./tree.js?v=112";

export function bindTree({ renderPage, refresh, toast }) {
  const $ = (q) => document.querySelector(q),
    dialog = $("#tree-editor"),
    form = $("#tree-edit-form");
  let editing = null,
    saving = false,
    foldTimer = null;

  // 重绘但保留页面滚动位置，避免折叠时页面跳回顶部
  function padding(v, c, x, y) {
    c.style.left = x + "px";
    c.style.top = y + "px";
    const space = c.parentElement;
    space.style.width = c.offsetWidth * s.zoom + 2 * x + "px";
    space.style.height = c.offsetHeight * s.zoom + 2 * y + "px";
  }
  const redraw = () => {
    const v = $(".story-viewport"),
      c = $(".story-canvas"),
      pos = v ? { left: v.scrollLeft, top: v.scrollTop } : null,
      px = parseFloat(c?.style.left) || 0,
      py = parseFloat(c?.style.top) || 0;
    renderPage({ restore: true });
    if (pos)
      requestAnimationFrame(() => {
        const next = $(".story-viewport"),
          canvas = $(".story-canvas");
        if (next && canvas) {
          padding(next, canvas, px, py);
          next.scrollTo(pos);
        }
      });
  };
  function center(fit = false) {
    requestAnimationFrame(() => {
      const v = $(".story-viewport"),
        canvas = $(".story-canvas");
      if (!v || !canvas) return;
      if (fit) {
        s.zoom = Math.max(
          0.4,
          Math.min(
            1,
            (v.clientWidth - 32) / canvas.offsetWidth,
            (v.clientHeight - 32) / canvas.offsetHeight,
          ),
        );
        redraw();
        requestAnimationFrame(() => {
          const view = $(".story-viewport"),
            c = $(".story-canvas");
          if (view && c) {
            padding(view, c, 0, 0);
            view.scrollTo({
              left: (view.scrollWidth - view.clientWidth) / 2,
              top: (view.scrollHeight - view.clientHeight) / 2,
            });
          }
        });
        return;
      }
      const card = [...document.querySelectorAll("[data-story-id]")].find(
        (c) => c.dataset.storyId === (s.selected || rootId()),
      );
      if (card) {
        padding(v, canvas, v.clientWidth / 2, v.clientHeight / 2);
        const z = s.zoom;
        v.scrollTo({
          left: (card.offsetLeft + card.offsetWidth / 2) * z,
          top: (card.offsetTop + card.offsetHeight / 2) * z,
          behavior: matchMedia("(prefers-reduced-motion: reduce)").matches
            ? "instant"
            : "smooth",
        });
      }
    });
  }

  const branch = bindBranch({
    getPlan: treePlan,
    refresh,
    redraw,
    toast,
    setBusy: (value) => (s.busy = value),
    clearSelection: () => (s.selected = ""),
  });
  const descendants = (id) => {
    const ids = new Set([id]);
    let size;
    do {
      size = ids.size;
      treeNodes().forEach((n) => {
        if (ids.has(n.parent_id)) ids.add(n.id);
      });
    } while (size !== ids.size);
    return ids;
  };
  // 全部有子节点的 id，用于展开/收起全部
  const expandableIds = () =>
    new Set([rootId(), ...treeNodes().map((n) => n.id)]);

  function open(mode, id = "", parent = "", kind = "side") {
    const p = treePlan(),
      root = mode === "new-plan" || id === rootId(),
      node = treeNodes().find((n) => n.id === id);
    editing = {
      mode,
      id,
      kind: node?.kind || kind,
      plan: p ? structuredClone(p) : null,
    };
    form.reset();
    $(".tree-form-error").hidden = true;
    $("[data-root-field]").hidden = true;
    $("[data-node-fields]").hidden = root;
    $("#tree-editor-title").textContent =
      mode === "new-plan"
        ? "创建" + (s.kind === "main" ? "主线" : "支线")
        : root
          ? "编辑方向"
          : mode === "add"
            ? kind === "main"
              ? "添加后续主线"
              : "添加支线"
            : "编辑这一步";
    $("#tree-add-context").textContent = root
      ? "写下你想实现的目标。"
      : mode === "add"
        ? "添加到「" +
          (treeNodes().find((n) => n.id === parent)?.title || p.data.title) +
          "」下面"
        : "修改这一步的内容。";
    form.querySelectorAll("details").forEach((d) => (d.open = mode === "edit"));
    const value =
      root && mode !== "new-plan"
        ? p.data
        : node || {
            title: "",
            description: "",
            parent_id: parent,
            priority: "p2",
          };
    const excluded = node ? descendants(id) : new Set();
    form.elements.parent_id.innerHTML =
      `<option value="">方向根节点</option>` +
      treeNodes()
        .filter((n) => !excluded.has(n.id))
        .map((n) => `<option value="${esc(n.id)}">${esc(n.title)}</option>`)
        .join("");
    form.elements.requires.innerHTML = treeNodes()
      .filter((n) => n.id !== id)
      .map((n) => `<option value="${esc(n.id)}">${esc(n.title)}</option>`)
      .join("");
    for (const key of [
      "title",
      "description",
      "parent_id",
      "priority",
      "due_date",
    ])
      form.elements[key].value = value[key] || "";
    form.elements.kind.value = value.kind || s.kind;
    [...form.elements.requires.options].forEach(
      (o) => (o.selected = (value.requires || []).includes(o.value)),
    );
    dialog.showModal();
    form.elements.title.focus();
  }

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    if (saving) return;
    saving = true;
    const button = form.querySelector("[type=submit]"),
      error = $(".tree-form-error");
    button.disabled = true;
    button.textContent = "保存中…";
    error.hidden = true;
    try {
      const { mode, id, plan: p } = editing,
        fd = new FormData(form),
        root = mode === "new-plan" || id === rootId();
      let data = { title: fd.get("title"), description: fd.get("description") },
        row;
      if (root) {
        data = {
          ...(p && mode !== "new-plan" ? p.data : { acts: [] }),
          ...data,
          kind: fd.get("kind"),
        };
        row = await api(
          mode === "new-plan" ? "plans" : `plans/${p.id}`,
          { data, ...(mode === "new-plan" ? {} : { version: p.version }) },
          mode === "new-plan" ? "POST" : "PUT",
        );
        s.kind = row.data.kind;
        write("tree-kind", s.kind);
      } else {
        data = {
          ...data,
          kind: editing.kind,
          parent_id: fd.get("parent_id"),
          priority: fd.get("priority"),
          due_date: fd.get("due_date"),
          requires: [...form.elements.requires.selectedOptions].map(
            (o) => o.value,
          ),
        };
        row = await api(
          `plans/${p.id}/nodes${mode === "add" ? "" : "/" + id}`,
          { data, version: p.version },
          mode === "add" ? "POST" : "PUT",
        );
        if (mode === "add") {
          // 新增后把父链展开，用户能立刻看到刚加的项
          const byId = new Map(treeNodes().map((n) => [n.id, n]));
          const chain = new Set();
          let pid = data.parent_id;
          while (pid) {
            chain.add(pid);
            pid = byId.get(pid)?.parent_id || "";
          }
          chain.add(rootId());
          s.folded = s.folded.filter((v) => !chain.has(v));
          write("tree-folded", s.folded);
        }
      }
      s.planId = row.id;
      const oldIds = new Set(
        p?.data.acts.flatMap((a) => a.nodes).map((n) => n.id) || [],
      );
      s.selected =
        mode === "add"
          ? row.data.acts.flatMap((a) => a.nodes).find((n) => !oldIds.has(n.id))
              ?.id
          : id;
      await refresh();
      dialog.close();
      if (s.auto) center();
      toast("已保存到工作区");
    } catch (e) {
      error.textContent = e.message;
      error.hidden = false;
    } finally {
      saving = false;
      button.disabled = false;
      button.textContent = "保存";
    }
  });

  // 在捕获阶段处理，并阻断冒泡：app.js 对所有 [data-action] 会preventDefault
  // 并进入 handleAction，若它先执行并重绘 DOM，本处理器后续拿到的按钮引用即失效，
  // aria-expanded 读不到真实状态，折叠表现为"点了没反应"。
  document.addEventListener(
    "click",
    async (e) => {
      if (!(e.target instanceof Element)) return; // 合成事件 target 可能为 document（防 TypeError）
      const b = e.target.closest('[data-action^="tree-"]');
      if (!b || s.busy) return;
      e.preventDefault();
      e.stopPropagation();
      const action = b.dataset.action.slice(5),
        id = b.dataset.id,
        p = treePlan();

      if (action !== "fold") {
        clearTimeout(foldTimer);
        foldTimer = null;
      }
      if (action === "delete") return branch.preview(id, id === rootId());
      if (action === "clear-date") {
        form.elements.due_date.value = "";
        form.elements.due_date.focus();
        return;
      }
      if (action === "new-plan") {
        return open(action);
      }
      if (action === "kind") {
        s.kind = b.dataset.kind;
        s.planId = "";
        s.selected = "";
        write("tree-kind", s.kind);
        return redraw();
      }
      if (action === "add")
        return open("add", "", b.dataset.parent, b.dataset.kind);
      if (action === "edit") return open("edit", id);

      if (action === "center") return center();
      if (action === "fit") return center(true);
      if (action === "fold") {
        if (!id) return;
        clearTimeout(foldTimer);
        if (e.detail > 1) {
          open("edit", id);
          return;
        }
        const planId = p?.id;
        foldTimer = setTimeout(() => {
          if (
            treePlan()?.id !== planId ||
            !document.querySelector(".story-viewport") ||
            dialog.open
          )
            return;
          s.selected = id;
          setFolded(id, !isFolded(id));
          redraw();
          if (s.auto) center();
        }, 350);
        return;
      }
      if (action === "expand-all") {
        const ids = expandableIds();
        s.folded = s.folded.filter((v) => !ids.has(v));
        write("tree-folded", s.folded);
        return redraw();
      }
      if (action === "fold-all") {
        const ids = expandableIds();
        s.folded = [...new Set([...s.folded, ...ids])];
        write("tree-folded", s.folded);
        return redraw();
      }

      if (!p) return;
      // 行首圆圈：切换完成，服务端仍做前置校验
      if (action === "toggle") {
        const root = id === rootId(),
          node = root ? p.data : treeNodes().find((n) => n.id === id);
        if (!node) return;
        s.busy = true;
        redraw();
        try {
          await api(
            root ? `plans/${p.id}` : `plans/${p.id}/nodes/${id}`,
            {
              data: root
                ? { ...p.data, done: !node.done }
                : { done: !node.done },
              version: p.version,
            },
            "PUT",
          );
          await refresh();
          toast(node.done ? "已恢复为未完成" : "已完成");
        } catch (error) {
          toast(error.message, true);
        } finally {
          s.busy = false;
          redraw();
        }
      }
    },
    true,
  );

  document.addEventListener("keydown", (e) => {
    const b = e.target instanceof Element && e.target.closest(".story-title");
    if (b && e.key === "F2") {
      e.preventDefault();
      clearTimeout(foldTimer);
      open("edit", b.dataset.id);
    }
  });
  let drag = null;
  document.addEventListener("pointerdown", (e) => {
    if (!(e.target instanceof Element)) return; // 合成事件 target 可能为 document（防 TypeError）
    const v = e.target.closest(".story-viewport");
    if (
      !v ||
      e.target.closest("button,input,select,.story-card") ||
      e.button !== 0
    )
      return;
    drag = {
      v,
      x: e.clientX,
      y: e.clientY,
      left: v.scrollLeft,
      top: v.scrollTop,
    };
    v.setPointerCapture(e.pointerId);
  });
  document.addEventListener("pointermove", (e) => {
    if (drag) {
      drag.v.scrollLeft = drag.left + drag.x - e.clientX;
      drag.v.scrollTop = drag.top + drag.y - e.clientY;
    }
  });
  document.addEventListener("pointerup", () => (drag = null));
  document.addEventListener("pointercancel", () => (drag = null));
  document.addEventListener("change", (e) => {
    if (e.target.id === "story-auto") {
      s.auto = e.target.checked;
      write("story-auto", s.auto);
      if (s.auto) center();
    }
    if (e.target.id === "story-zoom") {
      s.zoom = Number(e.target.value) / 100;
      redraw();
      center();
    }
    if (e.target.id === "tree-plan-picker") {
      s.planId = e.target.value;
      s.selected = "";
      redraw();
      if (s.auto) center();
    }
  });
}
