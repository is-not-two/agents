/* 人物：一张卡记一个可修订的自我观察。事实源在 PostgreSQL（kind=self_trait），
   修改轨迹由通用 /api/records/{id}/history 提供，前端不另存一份。 */
import { api, read, write, escapeHtml as escape } from "./data.js?v=129";

const VALENCES = ["待改进", "中性", "优势"];
const STATUSES = ["观察中", "已改善", "已归档"];

const cache = {
  rows: null,
  trash: null,
  showTrash: false,
  filter: read("trait-filter", "all"),
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
    const [rows, trash] = await Promise.all([
      api("traits"),
      api("traits?trash=true"),
    ]);
    cache.rows = rows;
    cache.trash = trash;
  } catch (e) {
    cache.error = e.message;
  } finally {
    cache.loading = false;
    _repaint();
  }
}

const sourceRows = () => (cache.showTrash ? cache.trash : cache.rows) || [];

function visibleRows() {
  if (cache.filter === "all") return sourceRows();
  return sourceRows().filter(
    (r) => r.data.valence === cache.filter || r.data.status === cache.filter,
  );
}

function chips() {
  const counts = { all: sourceRows().length };
  for (const r of sourceRows()) {
    for (const key of [r.data.valence, r.data.status]) {
      if (key) counts[key] = (counts[key] || 0) + 1;
    }
  }
  const keys = ["all", ...VALENCES, ...STATUSES];
  return `<nav class="lesson-chips" aria-label="筛选人物记录">${keys
    .map(
      (k) =>
        `<button class="lesson-chip" data-action="trait-filter" data-value="${escape(k)}" aria-pressed="${cache.filter === k}">${k === "all" ? "全部" : escape(k)} ${counts[k] ?? 0}</button>`,
    )
    .join("")}</nav>`;
}

function meter(value) {
  const n = Math.min(5, Math.max(1, Number(value) || 3));
  return `<span aria-label="强度 ${n}/5">${"●".repeat(n)}${"○".repeat(5 - n)}</span>`;
}

function card(r) {
  const d = r.data || {};
  const ops = cache.showTrash
    ? `<button class="small-button" data-action="trait-restore" data-id="${escape(r.id)}" data-version="${r.version}">恢复</button>`
    : `<button class="small-button" data-action="trait-edit" data-id="${escape(r.id)}">修改</button><button class="small-button" data-action="trait-history" data-id="${escape(r.id)}">修改记录</button><button class="small-button" data-action="trait-delete" data-id="${escape(r.id)}" data-version="${r.version}">归档</button>`;
  return `<article class="trait-card${d.status === "已归档" ? " is-archived" : ""}" data-valence="${escape(d.valence || "")}">
    <h3>${escape(d.title)}</h3>
    <div class="trait-meta"><span>${escape(d.valence || "")}</span>${meter(d.intensity)}<span>${escape(d.status || "")}</span>${d.scene ? `<span>· ${escape(d.scene)}</span>` : ""}</div>
    ${d.note ? `<p class="trait-note">${escape(d.note)}</p>` : ""}
    <footer class="trait-ops">${ops}</footer>
  </article>`;
}

export function selfTraitsView() {
  if (!cache.rows && !cache.error && !cache.loading) load();
  const head = `<div class="lesson-toolbar"><button class="primary-button" data-action="trait-new">＋ 记一个特点</button><button class="small-button" data-action="trait-trash" aria-pressed="${cache.showTrash}">${cache.showTrash ? "返回列表" : `已归档（${cache.trash ? cache.trash.length : 0}）`}</button><button class="small-button" data-action="trait-reload">刷新</button></div>`;
  if (cache.loading && !cache.rows)
    return `${head}<section class="module-surface trait-list"><p>正在读取…</p></section>`;
  if (cache.error)
    return `${head}<section class="module-surface trait-list"><p class="error-text" role="alert">${escape(cache.error)}</p></section>`;
  const rows = visibleRows();
  if (!rows.length)
    return `${head}${chips()}<section class="module-surface trait-list"><p class="empty-state">${cache.showTrash ? "没有已归档的记录。" : "还没有记录。写下你观察到的一个特点，之后随时可以改。"}</p></section>`;
  return `${head}${chips()}<section class="module-surface trait-list" aria-busy="${cache.busy}">${rows.map(card).join("")}</section>`;
}

const option = (v, selected = false) =>
  `<option value="${v}" ${selected ? "selected" : ""}>${v}</option>`;

export function selfTraitsDialog() {
  const intensity = [1, 2, 3, 4, 5]
    .map((n) => option(String(n), n === 3))
    .join("");
  const body = `<label class="form-field">特点名称<input name="title" required maxlength="60" placeholder="例如：自制力差" autocomplete="off"></label>
  <label class="form-field">倾向<select name="valence">${VALENCES.map((v) => option(v)).join("")}</select></label>
  <label class="form-field">强度（1 最轻，5 最明显）<select name="intensity">${intensity}</select></label>
  <label class="form-field">常见场景（选填）<input name="scene" maxlength="200" placeholder="例如：晚上刷手机"></label>
  <label class="form-field">观察到的具体事情（选填）<textarea name="note" rows="5" maxlength="4000" placeholder="今天发生了什么；以后想怎么调整"></textarea></label>
  <label class="form-field">状态<select name="status">${STATUSES.map((s) => option(s)).join("")}</select></label>
  <p class="trait-form-error error-text" role="alert" hidden></p>
  <div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button class="primary-button" type="submit">保存</button></div>`;
  return `<dialog class="form-dialog" data-form="trait"><form class="edit-form" id="trait-edit-form"><header class="drawer-header"><div><small>时列 · 人物</small><h2 id="trait-dialog-title">记一个特点</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭">×</button></header><div class="drawer-content">${body}</div></form></dialog>
  <dialog class="form-dialog" data-form="trait-history"><div class="drawer-content" id="trait-history-body"><p>正在读取…</p></div></dialog>`;
}

async function showHistory(row) {
  const d = document.querySelector('.form-dialog[data-form="trait-history"]');
  const body = document.getElementById("trait-history-body");
  if (!d || !body) return;
  body.innerHTML = "<p>正在读取…</p>";
  d.showModal();
  try {
    const versions = await api(`records/${row.id}/history`);
    const items = (versions || [])
      .slice()
      .reverse()
      .map((v) => {
        const data = v.data || {};
        return `<li><strong>v${v.version}</strong> · ${escape(data.title || "")} · ${escape(data.valence || "")} ${escape(String(data.intensity ?? ""))}/5 · ${escape(data.status || "")}<small>${escape(v.created_at || v.updated_at || "")}</small></li>`;
      })
      .join("");
    body.innerHTML = `<h2>修改记录</h2><p class="settings-hint">每次保存都会留下一版，能看到自己什么时候改了看法。</p><ul class="trash-panel">${items || "<li>暂无历史版本</li>"}</ul><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">关闭</button></div>`;
  } catch (err) {
    body.innerHTML = `<p class="error-text">${escape(err.message)}</p>`;
  }
}

export function bindSelfTraits({ renderPage, toast }) {
  const active = () => location.hash === "#module/self-traits";
  _repaint = () => {
    if (active()) renderPage({ restore: true });
  };

  function open(values = {}, id = "") {
    const d = document.querySelector('.form-dialog[data-form="trait"]');
    const f = document.getElementById("trait-edit-form");
    if (!d || !f) return;
    f.reset();
    d.dataset.recordId = id;
    for (const [key, value] of Object.entries(values)) {
      const el = f.elements.namedItem(key);
      if (el) el.value = value ?? "";
    }
    document.getElementById("trait-dialog-title").textContent = id
      ? "修改这条观察"
      : "记一个特点";
    d.showModal();
    f.querySelector("input[name=title]").focus();
  }

  document.addEventListener("click", async (e) => {
    if (!(e.target instanceof Element)) return;
    const b = e.target.closest('[data-action^="trait-"]');
    if (!b || cache.busy) return;
    const action = b.dataset.action.slice(6);
    const row = sourceRows().find((r) => r.id === b.dataset.id);
    if (action === "new") {
      cache.showTrash = false;
      open({});
    } else if (action === "filter") {
      cache.filter = b.dataset.value;
      write("trait-filter", cache.filter);
      _repaint();
    } else if (action === "trash") {
      cache.showTrash = !cache.showTrash;
      _repaint();
    } else if (action === "reload") {
      load(true);
    } else if (action === "edit" && row) {
      open({ ...row.data, intensity: String(row.data.intensity ?? 3) }, row.id);
    } else if (action === "history" && row) {
      await showHistory(row);
    } else if (action === "delete" && row) {
      if (!confirm(`把「${row.data.title}」归档？可在「已归档」里恢复。`)) return;
      cache.busy = true;
      _repaint();
      try {
        await api(`records/${row.id}?version=${row.version}`, undefined, "DELETE");
        toast("已归档");
        await load(true);
      } catch (err) {
        toast(err.message, true);
      } finally {
        cache.busy = false;
        _repaint();
      }
    } else if (action === "restore" && row) {
      cache.busy = true;
      _repaint();
      try {
        const history = await api(`records/${row.id}/history`);
        const target = history.find((v) => !v.deleted);
        if (!target) throw Error("没有可恢复的历史版本");
        await api(`records/${row.id}/restore`, {
          target_version: target.version,
          current_version: Number(row.version),
        });
        toast("已恢复");
        await load(true);
      } catch (err) {
        toast(err.message, true);
      } finally {
        cache.busy = false;
        _repaint();
      }
    }
  });

  document.addEventListener("submit", async (e) => {
    if (e.target.id !== "trait-edit-form") return;
    e.preventDefault();
    if (cache.busy) return;
    const f = e.target;
    const d = f.closest("dialog");
    const submit = f.querySelector("[type=submit]");
    const errEl = f.querySelector(".trait-form-error");
    const fd = new FormData(f);
    const data = {
      title: fd.get("title"),
      valence: fd.get("valence"),
      intensity: Number(fd.get("intensity")),
      scene: fd.get("scene"),
      note: fd.get("note"),
      status: fd.get("status"),
    };
    cache.busy = true;
    submit.disabled = true;
    submit.textContent = "保存中…";
    errEl.hidden = true;
    try {
      const id = d.dataset.recordId;
      const current = id ? (cache.rows || []).find((r) => r.id === id) : null;
      await api(
        id ? `traits/${id}` : "traits",
        { data, ...(current ? { version: current.version } : {}) },
        id ? "PUT" : "POST",
      );
      toast(id ? "已更新，修改记录会保留上一版" : "已记下");
      d.close();
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
