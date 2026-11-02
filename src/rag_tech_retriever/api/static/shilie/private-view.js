/* 私密管理：愿望清单与私密日记。
   口令不存浏览器——每次访问都由后端校验，明文只在当前页面内存中存在。
   因此本模块不做路由级缓存，刷新即重新要求口令。 */
import { api, state } from "./data.js?v=101";

const esc = (x) =>
  String(x ?? "").replace(
    /[&<>"']/g,
    (c) =>
      ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[
        c
      ],
  );
const CATS = ["想拥有", "想去做"];
/* 首次设置时的口令暂存：只在页面内存里，刷新即失。滑块解锁不需要它。 */
const VAULT = { password: "" };

const v = {
  configured: null,
  strongCrypto: false,
  ticket: "",
  unlocked: false,
  busy: "",
  error: "",
  requiresPassword: false,
  loaded: false,
  tab: "wish",
  wishes: [],
  diaries: [],
  filter: "all",
  query: "",
  setupCode: "",
  probing: false,
  slide: 0,
};

async function status() {
  try {
    const s = await api("private/status");
    v.requiresPassword = !!s.requires_password;
    v.configured = s.configured;
    v.strongCrypto = s.strong_crypto || false;
  } catch (e) {
    v.error = e.message;
  }
  return v;
}
/* 滑块解锁：拖到底后调用本函数换取会话票据。
   票据只存在于服务端内存与当前页面，进程重启或离开页面即失效。 */
async function unlock() {
  v.busy = "unlock";
  v.error = "";
  try {
    const r = await api("private/session", { password: VAULT.password });
    v.ticket = r.ticket;
    v.unlocked = true;
    v.requiresPassword = false;
    VAULT.password = "";
    await load();
  } catch (e) {
    v.error = e.message;
    if (/口令|401/.test(e.message)) v.requiresPassword = true;
  } finally {
    v.busy = "";
  }
}
async function setup(password) {
  v.busy = "setup";
  v.error = "";
  try {
    const r = await api("private/setup", { password });
    v.setupCode = r.recovery_code;
    v.configured = true;
    const s = await api("private/session", { password });
    v.ticket = s.ticket;
    v.unlocked = true;
    await load();
  } catch (e) {
    v.error = e.message;
  } finally {
    v.busy = "";
  }
}
async function load() {
  // 未解锁时不发请求：否则会带空票据打后端，换来一条无意义的 401 报错
  if (!v.unlocked || !v.ticket) return;
  v.busy = "load";
  v.error = "";
  try {
    const [w, d] = await Promise.all([
      api("private/wish?ticket=" + encodeURIComponent(v.ticket)),
      api("private/diary?ticket=" + encodeURIComponent(v.ticket)),
    ]);
    v.wishes = w;
    v.diaries = d;
    v.loaded = true;
  } catch (e) {
    v.error = e.message;
    if (/票据|口令/.test(String(e.message))) {
      v.unlocked = false;
      v.ticket = "";
      v.requiresPassword = true;
    }
  } finally {
    v.busy = "";
    v.loaded = true;
  }
}
async function saveWish(form) {
  v.busy = "save";
  v.error = "";
  const fd = new FormData(form);
  try {
    const data = {
      title: String(fd.get("title") || "").trim(),
      note: String(fd.get("note") || "").trim(),
      category: String(fd.get("category") || CATS[0]),
      emoji: String(fd.get("emoji") || "✨"),
      price: String(fd.get("price") || "").trim(),
      done: fd.get("done") === "on",
    };
    if (!data.title) throw Error("请填写愿望名称");
    await api("private/wish", { ticket: v.ticket, data });
    await load();
    toast("愿望已保存");
    return true;
  } catch (e) {
    v.error = e.message;
    toast(e.message, true);
  } finally {
    v.busy = "";
    await repaint();
  }
}
async function toggleWish(id, done) {
  const row = v.wishes.find((w) => w.id === id);
  if (!row) return;
  v.busy = "save";
  v.error = "";
  try {
    await api(
      "private/wish/" + id,
      {
        ticket: v.ticket,
        version: row.version,
        data: { ...row.data, title: row.data.title, done: !done },
      },
      "PUT",
    );
    await load();
  } catch (e) {
    v.error = e.message;
    toast(e.message, true);
  } finally {
    v.busy = "";
    await repaint();
  }
}
async function removeWish(id) {
  const row = v.wishes.find((w) => w.id === id);
  if (!row) return;
  if (!confirm("删除「" + row.data.title + "」？此操作不可撤销。")) return;
  v.busy = "save";
  v.error = "";
  try {
    await api(
      "private/wish/" +
        id +
        "?version=" +
        row.version +
        "&ticket=" +
        encodeURIComponent(v.ticket),
      undefined,
      "DELETE",
    );
    await load();
    toast("已删除");
  } catch (e) {
    v.error = e.message;
    toast(e.message, true);
  } finally {
    v.busy = "";
    await repaint();
  }
}
async function saveDiary(form) {
  v.busy = "save";
  v.error = "";
  const fd = new FormData(form);
  try {
    const data = {
      title: String(fd.get("title") || "").trim(),
      content: String(fd.get("content") || "").trim(),
      date: String(fd.get("date") || new Date().toISOString().slice(0, 10)),
    };
    if (!data.title) throw Error("请填写标题");
    await api("private/diary", { ticket: v.ticket, data });
    await load();
    toast("日记已保存");
    return true;
  } catch (e) {
    v.error = e.message;
    toast(e.message, true);
  } finally {
    v.busy = "";
    await repaint();
  }
}
async function removeDiary(id) {
  const row = v.diaries.find((d) => d.id === id);
  if (!row) return;
  if (!confirm("删除「" + row.data.title + "」？此操作不可撤销。")) return;
  v.busy = "save";
  v.error = "";
  try {
    await api(
      "private/diary/" +
        id +
        "?version=" +
        row.version +
        "&ticket=" +
        encodeURIComponent(v.ticket),
      undefined,
      "DELETE",
    );
    await load();
    toast("已删除");
  } catch (e) {
    v.error = e.message;
    toast(e.message, true);
  } finally {
    v.busy = "";
    await repaint();
  }
}
const lock = () => {
  v.ticket = "";
  v.unlocked = false;
  v.wishes = [];
  v.diaries = [];
  v.slide = 0;
  v.loaded = false;
  VAULT.password = "";
};

function shell(inner) {
  return `<section class="private-studio">
    <header class="studio-heading"><div><p class="studio-caption">只有你能看到</p><h1>私密管理</h1></div>
      ${v.unlocked ? `<button class="tree-button" data-private="lock">锁定</button>` : ""}</header>
    ${v.error ? `<p class="connection-feedback error-text" role="alert">${esc(v.error)}</p>` : ""}
    ${inner}
  </section>`;
}

function gateView() {
  const setupMode = v.configured === false;
  if (setupMode) return setupView();
  return shell(`<div class="private-gate">
    <div class="lock-mark">🔒</div>
    <h2>拖动滑块进入</h2>
    <p>把下面的滑块拖到最右边，就能打开愿望清单和日记。</p>
    ${v.strongCrypto ? "" : '<p class="connection-feedback error-text">当前环境缺少加密库，数据没有加密保护。</p>'}
    ${v.requiresPassword ? '<label class="form-field">解锁口令<input id="private-unlock-password" type="password" autocomplete="current-password" placeholder="服务重启后需重新输入口令"></label>' : ""}
    <div class="slide-unlock" id="slide-unlock">
      <div class="slide-track"><div class="slide-fill" style="width:0%"></div></div>
      <button class="slide-thumb" type="button" aria-label="向右拖动解锁，按 End 键也可解锁"
        aria-valuenow="0" role="slider" aria-valuemin="0" aria-valuemax="100">›</button>
    </div>
    <p class="slide-hint" id="slide-hint">向右拖动</p>
  </div>`);
}

function setupView() {
  return shell(`<div class="private-gate">
    <div class="lock-mark">✦</div>
    <h2>第一次使用，设置口令</h2>
    <p>愿望清单和日记会用这个口令加密后再存入数据库。之后进页面只需拖动滑块，但解密仍需要它。</p>
    ${v.strongCrypto ? "" : '<p class="connection-feedback error-text">当前环境缺少加密库，无法提供加密保护，请先安装 cryptography。</p>'}
    <form id="private-gate-form" class="private-gate-form">
      <input name="password" type="password" required minlength="4" placeholder="设置口令（至少 4 位）" autocomplete="new-password">
      <button class="primary-button" ${v.busy ? "disabled" : ""}>${v.busy === "setup" ? "设置中…" : "设置并继续"}</button>
    </form>
    <small class="gate-hint">口令遗失将无法恢复内容。设置后会给你一串恢复码，请立刻保存。</small>
  </div>`);
}

function recoveryView() {
  return shell(`<div class="private-gate">
    <div class="lock-mark">✓</div>
    <h2>请立刻保存恢复码</h2>
    <p>这串码只在下面显示这一次。把它抄下来或存到安全的地方。</p>
    <code class="recovery-code">${esc(v.setupCode)}</code>
    <form id="private-recovery-form"><button class="primary-button">我已保存</button></form>
    <small class="gate-hint">口令遗失且没有这串码，内容将无法恢复。</small>
  </div>`);
}

function wishCard(w) {
  const d = w.data,
    done = !!d.done;
  return `<article class="wish-card${done ? " is-done" : ""}">
    ${done ? '<span class="wish-badge">✓</span>' : ""}
    <div class="wish-cover"${done ? ' style="filter:grayscale(.6);opacity:.6"' : ""}>${esc(d.emoji || "✨")}</div>
    <div class="wish-body">
      <div class="wish-title">${esc(d.title)}</div>
      ${d.note ? `<div class="wish-note">${esc(d.note)}</div>` : ""}
      <div class="wish-foot"><span class="wish-cat">${esc(d.category || "")}</span>
        ${d.price ? `<span class="wish-price">${esc(d.price)}</span>` : ""}</div>
    </div>
    <div class="wish-ops">
      <button class="wish-op" data-private="toggle-wish" data-id="${esc(w.id)}" title="${done ? "标记为未完成" : "标记完成"}">${done ? "↺" : "✓"}</button>
      <button class="wish-op" data-private="del-wish" data-id="${esc(w.id)}" title="删除">×</button>
    </div>
  </article>`;
}

function wishesView() {
  const q = v.query.trim().toLowerCase();
  const list = v.wishes
    .filter((w) => {
      if (v.filter === "已完成") return w.data.done;
      if (v.filter !== "all")
        return w.data.category === v.filter && !w.data.done;
      return true;
    })
    .filter(
      (w) =>
        !q ||
        String(w.data.title).toLowerCase().includes(q) ||
        String(w.data.note || "")
          .toLowerCase()
          .includes(q),
    );
  const doneCount = v.wishes.filter((w) => w.data.done).length;
  return shell(`<div class="private-tabs">
      <button data-private="tab" data-tab="wish" aria-pressed="${v.tab === "wish"}">愿望清单 ${v.wishes.length ? `（${doneCount}/${v.wishes.length}）` : ""}</button>
      <button data-private="tab" data-tab="diary" aria-pressed="${v.tab === "diary"}">私密日记${v.diaries.length ? `（${v.diaries.length}）` : ""}</button>
    </div>
    ${
      v.tab === "wish"
        ? `<div class="private-filters">
      <button class="chip" data-private="filter" data-c="all" aria-pressed="${v.filter === "all"}">全部</button>
      ${CATS.map((c) => `<button class="chip" data-private="filter" data-c="${esc(c)}" aria-pressed="${v.filter === c}">${esc(c)}</button>`).join("")}
      <button class="chip" data-private="filter" data-c="已完成" aria-pressed="${v.filter === "已完成"}">已完成</button>
      <input class="search-field" id="private-q" type="search" placeholder="搜索愿望…" value="${esc(v.query)}">
      <button class="primary-button" data-private="add-wish">＋ 添加愿望</button>
    </div>
    ${
      list.length
        ? `<div class="wish-wall">${list.map(wishCard).join("")}</div>`
        : `<div class="empty-panel"><h2>${q ? "没有匹配的愿望" : "还没有愿望"}</h2><p>${q ? "换个关键词试试。" : "写下想做的一件事，哪怕现在还做不到。"}</p>${q ? "" : '<button class="primary-button" data-private="add-wish">添加第一个愿望</button>'}</div>`
    }`
        : diaryViewInner()
    }`);
}

function diaryCard(d) {
  return `<article class="diary-card">
    <div class="diary-head"><span class="diary-date">${esc(d.data.date || "")}</span>
      <span class="diary-title">${esc(d.data.title)}</span>
      <span class="diary-lock">私密</span>
      <button class="wish-op" data-private="del-diary" data-id="${esc(d.id)}" title="删除">×</button></div>
    ${d.data.content ? `<p class="diary-body">${esc(d.data.content)}</p>` : ""}
  </article>`;
}
function diaryViewInner() {
  return `<div class="private-filters">
    <button class="primary-button" data-private="add-diary">＋ 写一篇</button>
  </div>
  ${
    v.diaries.length
      ? `<div class="diary-list">${v.diaries.map(diaryCard).join("")}</div>`
      : '<div class="empty-panel"><h2>还没有日记</h2><p>这里的内容同样加密保存。</p></div>'
  }`;
}

/* 同步渲染外壳，数据异步补齐。
   render() 是同步函数，不能返回 Promise，因此这里先出骨架，
   再由 ensurePrivate() 拉数据后重绘。 */
export function privateView() {
  if (v.configured === null) {
    // 首次渲染时配置未知，异步取回后再重绘
    if (!v.probing) {
      v.probing = true;
      status()
        .then(() => repaint())
        .catch(() => {});
    }
    return shell(
      '<p class="private-loading" role="status">正在检查私密状态…</p>',
    );
  }
  if (!v.configured) return gateView();
  if (!v.unlocked) return gateView();
  if (v.setupCode) return recoveryView();
  if (!v.loaded && v.busy === "") ensurePrivate();
  return wishesView();
}

/* 补齐数据后触发重绘；由 app.js 注入渲染函数，避免与 views.js 循环依赖。 */
let repaint = () => {};
export function setPrivateRepaint(fn) {
  repaint = async () => {
    await fn();
    bindSlide();
  };
}
export async function ensurePrivate() {
  if (v.busy) return;
  await load();
  await repaint();
}

/* 滑块拖动：就地更新样式，不触发整页重绘——
   否则松手前每次移动都会重建 DOM，指针捕获随之失效。 */
let dragging = false;
function slideTo(pct, wrap) {
  v.slide = Math.max(0, Math.min(100, pct));
  const fill = wrap.querySelector(".slide-fill");
  const thumb = wrap.querySelector(".slide-thumb");
  const hint = document.getElementById("slide-hint");
  const track = wrap.querySelector(".slide-track");
  // 与 onMove 的 travel 用同一公式，两者必须一致，否则 thumb 与填充会错位
  const thumbW = thumb ? thumb.getBoundingClientRect().width : 42;
  const travel = track
    ? Math.max(1, track.getBoundingClientRect().width - thumbW)
    : 1;
  if (fill) fill.style.width = v.slide + "%";
  if (thumb && v.slide < 100) {
    thumb.style.background = "";
    thumb.style.borderColor = "";
    thumb.style.color = "";
    thumb.textContent = "›";
  }
  if (thumb) {
    thumb.style.left = (travel * v.slide) / 100 + "px";
    thumb.setAttribute("aria-valuenow", String(Math.round(v.slide)));
  }
  if (hint) hint.textContent = v.slide >= 100 ? "正在打开…" : "向右拖动";
  if (thumb && v.slide >= 100) {
    thumb.style.background = "#4a8f5e";
    thumb.style.borderColor = "#4a8f5e";
    thumb.style.color = "#fff";
    thumb.textContent = "✓";
  }
}
async function finishSlide(wrap) {
  // 末端吸附：超过 88% 就补满，避免"差一点没解锁"的挫败感
  if (v.slide >= 88) slideTo(100, wrap);
  if (v.slide < 98) {
    slideTo(0, wrap);
    return;
  }
  if (v.busy) return;
  const password = document.getElementById("private-unlock-password");
  if (password) VAULT.password = password.value;
  if (v.requiresPassword && !VAULT.password) {
    v.error = "请输入解锁口令，再拖动滑块。";
    slideTo(0, wrap);
    await repaint();
    document.getElementById("private-unlock-password")?.focus();
    return;
  }
  await unlock();
  v.slide = 0;
  await repaint();
}
export function bindSlide() {
  const wrap = document.getElementById("slide-unlock");
  if (!wrap || wrap.dataset.bound) return;
  wrap.dataset.bound = "true";
  const thumb = wrap.querySelector(".slide-thumb");
  const track = wrap.querySelector(".slide-track");
  if (!thumb || !track) return;
  slideTo(0, wrap);
  // 只跟随水平位移：此前用绝对 clientX，垂直方向移动也会改位置，
  // 导致滑块能上下乱跑。
  // travel 用实测宽度减去滑块自身宽度，保证拖到最右正好是 100%
  let startX = 0,
    startPct = 0,
    travel = 1;
  const onMove = (e) => {
    if (dragging)
      slideTo(startPct + ((e.clientX - startX) / travel) * 100, wrap);
  };
  const onUp = (e) => {
    if (!dragging) return;
    dragging = false;
    document.removeEventListener("pointermove", onMove);
    document.removeEventListener("pointerup", onUp);
    document.removeEventListener("pointercancel", onUp);
    if (e.type === "pointercancel") {
      slideTo(0, wrap);
      return;
    }
    finishSlide(wrap);
  };
  thumb.addEventListener("pointerdown", (e) => {
    if (v.busy || e.button !== 0) return;
    dragging = true;
    // Re-measure: the viewport may have resized since this slider was bound.
    travel = Math.max(
      1,
      track.getBoundingClientRect().width - thumb.getBoundingClientRect().width,
    );
    startX = e.clientX;
    startPct = v.slide;
    // 用指针捕获而非 preventDefault：后者会抑制 pointermove，拖不动
    try {
      thumb.setPointerCapture(e.pointerId);
    } catch (_) {}
    document.addEventListener("pointermove", onMove);
    document.addEventListener("pointerup", onUp);
    document.addEventListener("pointercancel", onUp);
  });
  // 键盘可达：End 或长按方向键也可解锁
  thumb.addEventListener("keydown", (e) => {
    if (v.busy) return;
    if (e.key === "End" || e.key === "ArrowRight") {
      e.preventDefault();
      slideTo(100, wrap);
      finishSlide(wrap);
    }
    if (e.key === "Home") {
      e.preventDefault();
      slideTo(0, wrap);
    }
  });
}

function read(key, fallback) {
  try {
    return Number(sessionStorage.getItem("shilie-" + key)) || fallback;
  } catch {
    return fallback;
  }
}
function write(key, val) {
  try {
    sessionStorage.setItem("shilie-" + key, String(val));
  } catch {}
}

/* 离开私密管理即丢弃票据：票据只在当前页面有效，
   回到本模块需要重新拖动滑块。 */
function resetOnLeave() {
  if (!location.hash.includes("/private") && v.unlocked) {
    v.ticket = "";
    v.unlocked = false;
    v.wishes = [];
    v.diaries = [];
    v.slide = 0;
    v.loaded = false;
  }
}
window.addEventListener("hashchange", resetOnLeave);
// 每次进入私密管理都重新上锁：滑块是入口仪式，不该因为上一秒开过就跳过
let lastHash = "";
function relockOnEnter() {
  const cur = location.hash;
  if (cur === lastHash) return;
  lastHash = cur;
  if (cur.includes("/private") && v.unlocked) {
    v.ticket = "";
    v.unlocked = false;
    v.wishes = [];
    v.diaries = [];
    v.slide = 0;
    v.loaded = false;
    refreshPrivate();
  }
}
window.addEventListener("hashchange", relockOnEnter);

let toast = () => {};
export function bindPrivate(notify) {
  if (notify) toast = notify;
  document.addEventListener("click", async (e) => {
    if (!(e.target instanceof Element)) return;
    const b = e.target.closest("[data-private]");
    if (!b) return;
    e.preventDefault();
    e.stopPropagation();
    const act = b.dataset.private,
      id = b.dataset.id;
    if (act === "lock") return (lock(), refreshPrivate());
    if (act === "tab") {
      v.tab = b.dataset.tab;
      return refreshPrivate();
    }
    if (act === "filter") {
      v.filter = b.dataset.c;
      return refreshPrivate();
    }
    if (act === "toggle-wish")
      return toggleWish(id, v.wishes.find((w) => w.id === id)?.data.done);
    if (act === "del-wish") return removeWish(id);
    if (act === "del-diary") return removeDiary(id);
    if (act === "add-wish" || act === "add-diary") {
      const d = document.createElement("dialog");
      d.className = "form-dialog";
      const wish = act === "add-wish";
      d.innerHTML = `<form class="edit-form"><header class="drawer-header"><div><small>时列 · 私密管理</small>
        <h2>${wish ? "添加愿望" : "写日记"}</h2></div>
        <button type="button" class="icon-button" data-private="close" aria-label="关闭">×</button></header>
        <div class="drawer-content">
          <label class="form-field">${wish ? "想要什么" : "标题"}<input name="title" required maxlength="160" placeholder="${wish ? "例如：去一次北欧" : "例如：关于想做的事"}"></label>
          ${
            wish
              ? `<label class="form-field">分类<select name="category">${CATS.map((c) => `<option>${esc(c)}</option>`).join("")}</select></label>
          <label class="form-field">图标（可留空）<input name="emoji" maxlength="4" placeholder="🏔"></label>
          <label class="form-field">预算（选填）<input name="price" maxlength="40" placeholder="¥8,500"></label>
          <label class="form-field">备注（选填）<textarea name="note" rows="3" maxlength="2000" placeholder="想补充什么就写在这里"></textarea></label>`
              : `<label class="form-field">日期<input name="date" type="date"></label>
          <label class="form-field">正文<textarea name="content" rows="10" maxlength="20000"></textarea></label>`
          }
          <div class="form-actions"><button type="button" class="small-button" data-private="close">取消</button>
            <button class="primary-button">保存</button></div>
        </div></form>`;
      document.body.appendChild(d);
      d.addEventListener("click", (ev) => {
        if (ev.target.closest("[data-private=close]")) d.close();
      });
      d.querySelector("form").addEventListener("submit", async (ev) => {
        ev.preventDefault();
        const saved = wish
          ? await saveWish(ev.target)
          : await saveDiary(ev.target);
        if (saved) d.close();
      });
      d.addEventListener("close", () => d.remove(), { once: true });
      d.showModal();
    }
  });
  document.addEventListener("input", (e) => {
    if (e.target.id === "private-q") {
      v.query = e.target.value;
      const p = e.target.selectionStart;
      refreshPrivate().then(() => {
        const i = document.getElementById("private-q");
        if (i) {
          i.focus();
          i.setSelectionRange(p, p);
        }
      });
    }
  });
  document.addEventListener(
    "submit",
    async (e) => {
      if (e.target.id === "private-gate-form") {
        e.preventDefault();
        const pw = String(new FormData(e.target).get("password") || "");
        VAULT.password = pw;
        await setup(pw);
        await refreshPrivate();
      }
      if (e.target.id === "private-recovery-form") {
        e.preventDefault();
        v.setupCode = "";
        await refreshPrivate();
      }
    },
    true,
  );
}

function refreshPrivate() {
  return repaint();
}
