/* 谨记名单：记录犯过的错误，按类型分类（技术/操作/判断/习惯/其他，可自定义）。
   事实源在 PostgreSQL（kind=lesson）；分类筛选是浏览器显示偏好。 */
import { api, read, write, escapeHtml as escape } from "./data.js?v=119";

const CATEGORIES = ["技术", "操作", "判断", "习惯", "其他"];

const cache = {
  rows: null,
  trash: null,
  showTrash: false,
  filter: read("lesson-filter", "all"),
  error: "",
  loading: false,
  busy: false,
};

let _repaint = () => {};

async function load(force = false) {
  if (cache.loading) return;
  if (force) {
    cache.rows = null;
    cache.trash = null;
    cache.error = "";
  }
  cache.loading = true;
  cache.error = "";
  try {
    cache.rows = await api("lessons");
    cache.trash = await api("lessons?trash=true");
  } catch (e) {
    cache.error = e.message;
  } finally {
    cache.loading = false;
    _repaint();
  }
}

function rows() {
  const source = cache.showTrash ? cache.trash : cache.rows;
  if (!source) return [];
  return cache.filter === "all"
    ? source
    : source.filter((r) => r.data.category === cache.filter);
}

function categoryChips(counts) {
  // 预设类型 + 实际出现的自定义类型（含计数），保证自定义谨记也有筛选入口
  const custom = Object.keys(counts).filter(
    (k) => k !== "all" && !CATEGORIES.includes(k),
  );
  const keys = ["all", ...CATEGORIES, ...custom];
  const items = keys.map((k) => [
    k,
    `${k === "all" ? "全部" : k} ${counts[k] ?? 0}`.trim(),
  ]);
  return `<nav class="lesson-chips" aria-label="按类型筛选">${items
    .map(
      ([key, label]) =>
        `<button class="lesson-chip" data-action="lesson-filter" data-value="${escape(
          key,
        )}" aria-pressed="${cache.filter === key}">${escape(label)}</button>`,
    )
    .join("")}</nav>`;
}

export function lessonsView() {
  if (!cache.rows && !cache.error && !cache.loading) load();
  const head = `<div class="lesson-toolbar"><button class="primary-button" data-action="lesson-new">＋ 记一条</button><button class="small-button" data-action="lesson-trash" aria-pressed="${cache.showTrash}">${cache.showTrash ? "返回列表" : `回收站（${cache.trash ? cache.trash.length : 0}）`}</button></div>`;
  if (cache.loading && !cache.rows)
    return `<section class="module-surface lesson-list"><p>正在读取…</p></section>`;
  if (cache.error)
    return `<section class="module-surface lesson-list"><p class="error-text" role="alert">${escape(
      cache.error,
    )}</p><button class="small-button" data-action="lesson-reload">重新读取</button></section>`;
  const source = cache.showTrash ? cache.trash : cache.rows;
  const counts = { all: source ? source.length : 0 };
  for (const r of source || [])
    counts[r.data.category] = (counts[r.data.category] || 0) + 1;
  if (!source || source.length === 0)
    return `${head}${categoryChips(counts)}<section class="module-surface lesson-list"><p class="empty-state">${
      cache.showTrash
        ? "回收站为空。"
        : "还没有记录。犯过的错写下来，下次绕开它。"
    }</p></section>`;
  const list = rows()
    .map(
      (r) => `<article class="lesson-row">
  <header><span class="lesson-cat" data-cat="${escape(r.data.category)}">${escape(
    r.data.category,
  )}</span><h3>${escape(r.data.title)}</h3><time>${escape(
    r.created_at || "",
  )}</time></header>
  ${r.data.content ? `<p>${escape(r.data.content)}</p>` : ""}
  ${r.data.remedy ? `<p class="lesson-remedy"><span>对策</span>${escape(r.data.remedy)}</p>` : ""}
  <footer>${
    cache.showTrash
      ? `<button class="small-button" data-action="lesson-restore" data-id="${escape(r.id)}" data-version="${r.version}">恢复</button>`
      : `<button class="small-button" data-action="lesson-edit" data-id="${escape(r.id)}">编辑</button><button class="small-button" data-action="lesson-delete" data-id="${escape(r.id)}" data-version="${r.version}">移入回收站</button>`
  }</footer>
</article>`,
    )
    .join("");
  const filtered = rows().length;
  return `${head}${categoryChips(counts)}<section class="module-surface lesson-list" aria-busy="${cache.busy}">${
    filtered === 0 ? '<p class="empty-state">该类型暂无记录。</p>' : list
  }</section>`;
}

export function lessonsDialog() {
  const options = CATEGORIES.map((c) => `<option value="${c}">`).join("");
  return `<dialog class="form-dialog" data-form="lesson"><form class="edit-form" id="lesson-edit-form"><header class="drawer-header"><div><small>时列 · 谨记名单</small><h2 id="lesson-dialog-title">记一条谨记</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content">
  <label class="form-field">错误类型<input name="category" list="lesson-categories" value="技术" maxlength="20" required><datalist id="lesson-categories">${options}</datalist></label>
  <label class="form-field">犯了什么错？<input name="title" required maxlength="160" placeholder="一句话说清错误本身" autocomplete="off"></label>
  <label class="form-field">经过与原因（选填）<textarea name="content" rows="4" maxlength="20000" placeholder="当时怎么发生的，为什么会这样"></textarea></label>
  <label class="form-field">对策（选填）<textarea name="remedy" rows="2" maxlength="2000" placeholder="下次遇到同样情况怎么做"></textarea></label>
  <p class="lesson-form-error error-text" role="alert" hidden></p>
  <div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存</button></div>
</div></form></dialog>`;
}

export function bindLessons({ renderPage, toast }) {
  const active = () => location.hash === "#module/lessons";
  _repaint = () => {
    if (active()) renderPage({ restore: true });
  };
  const form = () =>
    document.querySelector('.form-dialog[data-form="lesson"] form');

  function open(values = {}, id = "") {
    const dialogEl = document.querySelector('.form-dialog[data-form="lesson"]');
    if (!dialogEl) return;
    const f = form();
    f.reset();
    dialogEl.dataset.recordId = id;
    for (const [key, value] of Object.entries(values)) {
      if (f.elements.namedItem(key))
        f.elements.namedItem(key).value = value ?? "";
    }
    document.getElementById("lesson-dialog-title").textContent = id
      ? "编辑谨记"
      : "记一条谨记";
    dialogEl.showModal();
    f.querySelector("input[name=title]").focus();
  }

  document.addEventListener("click", async (e) => {
    if (!(e.target instanceof Element)) return; // 合成事件 target 可能为 document（评审 F9）
    const b = e.target.closest('[data-action^="lesson-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(7);
    if (action === "new") {
      cache.showTrash = false;
      open({});
    } else if (action === "filter") {
      cache.filter = b.dataset.value;
      write("lesson-filter", cache.filter);
      _repaint();
    } else if (action === "trash") {
      cache.showTrash = !cache.showTrash;
      _repaint();
    } else if (action === "reload") {
      load(true);
    } else if (action === "edit") {
      const row = (cache.rows || []).find((r) => r.id === b.dataset.id);
      if (row)
        open(
          {
            category: row.data.category,
            title: row.data.title,
            content: row.data.content,
            remedy: row.data.remedy,
          },
          row.id,
        );
    } else if (action === "delete") {
      if (!confirm("把这条谨记移入回收站？")) return;
      cache.busy = true;
      _repaint();
      try {
        await api(
          `records/${b.dataset.id}?version=${b.dataset.version}`,
          undefined,
          "DELETE",
        );
        toast("已移入回收站");
        await load(true);
      } catch (err) {
        toast(err.message, true);
      } finally {
        // 成功与失败都必须复位，否则整页按钮永久锁死（评审 F1）
        cache.busy = false;
        _repaint();
      }
      return;
    } else if (action === "restore") {
      cache.busy = true;
      _repaint();
      try {
        const history = await api(`records/${b.dataset.id}/history`);
        const target = history.find((v) => !v.deleted);
        if (!target) throw Error("没有可恢复的历史版本");
        await api(`records/${b.dataset.id}/restore`, {
          target_version: target.version,
          current_version: Number(b.dataset.version),
        });
        toast("已恢复");
        await load(true);
      } catch (err) {
        toast(err.message, true);
      } finally {
        cache.busy = false;
        _repaint();
      }
      return;
    }
  });

  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "lesson-edit-form") return;
    e.preventDefault();
    if (cache.busy) return;
    const dialogEl = e.target.closest("dialog");
    const submit = e.target.querySelector("[type=submit]");
    const errEl = e.target.querySelector(".lesson-form-error");
    cache.busy = true;
    submit.disabled = true;
    submit.textContent = "保存中…";
    errEl.hidden = true;
    const fd = new FormData(e.target);
    const data = {
      category: fd.get("category"),
      title: fd.get("title"),
      content: fd.get("content"),
      remedy: fd.get("remedy"),
    };
    try {
      const id = dialogEl.dataset.recordId;
      const current = id ? (cache.rows || []).find((r) => r.id === id) : null;
      const saved = await api(
        id ? `lessons/${id}` : "lessons",
        { data, ...(current ? { version: current.version } : {}) },
        id ? "PUT" : "POST",
      );
      toast(id ? "谨记已更新" : "已记下");
      dialogEl.close();
      await load(true);
    } catch (err) {
      errEl.textContent = err.message;
      errEl.hidden = false;
    } finally {
      cache.busy = false;
      submit.disabled = false;
      submit.textContent = "保存";
    }
  });

  return {
    ensure() {
      if (active() && !cache.rows && !cache.error && !cache.loading) load();
    },
  };
}
