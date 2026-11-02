/* 检索质量评测：逐题跑评测集，看 top-k 召回率与重排前后名次变化。
   结果区内自行管理局部 DOM，不触发整页重绘——评测数据体积大，
   整页重建会丢掉滚动位置与展开状态。只读运行，不写业务数据。 */
import { api, escapeHtml as escape } from "./data.js?v=101";

const cache = {
  questions: null,
  result: null,
  error: "",
  loading: false,
  rerank: true,
  expanded: new Set(),
};

/* 视图在每次 renderPage 时重新生成，需要把已算好的结果回填进去，
   避免用户切走再切回就丢失评测结果。 */
function recallCell(entry) {
  const passed = entry.passed;
  const cls = passed === entry.total ? "eval-pass" : passed === 0 ? "eval-fail" : "eval-part";
  return `<td class="${cls}">${passed}/${entry.total} <small>${(entry.rate * 100).toFixed(0)}%</small></td>`;
}

function rankCell(rank) {
  return rank === null || rank === undefined ? '<span class="eval-none">—</span>' : "#" + escape(rank);
}

function moveCell(item) {
  const { vector_rank: before, final_rank: after } = item;
  if (before === null || after === null) return "";
  if (cache.rerank && before !== after) {
    const up = after < before;
    return `<span class="eval-move ${up ? "eval-move-up" : "eval-move-down"}" title="向量原始名次 → 重排后名次">${up ? "↑" : "↓"} ${escape(before)} → ${escape(after)}</span>`;
  }
  return "";
}

function failureTag(failure) {
  if (!failure) return '<span class="eval-ok">命中</span>';
  const cls = failure === "未召回" ? "eval-fail" : "eval-warn";
  return `<span class="${cls}">${escape(failure)}</span>`;
}

function hitsTable(item) {
  const rows = item.hits
    .map(
      (hit) => `<tr class="${hit.is_anchor ? "eval-anchor-row" : ""}">
        <td>#${escape(hit.rank)}</td>
        <td>${hit.is_anchor ? "★ " : ""}${escape(hit.title)}</td>
        <td><code>${escape(hit.id)}</code></td>
        <td>${escape(hit.status_marker)}</td>
        <td>${escape(hit.similarity)}</td>
        <td>${escape(hit.score)}</td>
      </tr>`,
    )
    .join("");
  return `<table class="eval-hits"><thead><tr><th>名次</th><th>标题</th><th>切片</th><th>状态</th><th>相似度</th><th>最终分</th></tr></thead><tbody>${rows}</tbody></table>`;
}

function questionRow(item) {
  const open = cache.expanded.has(item.qid);
  const anchors = item.anchors.map((a) => `<code>${escape(a)}</code>`).join(" ");
  return `<article class="eval-question${open ? " is-open" : ""}">
    <header data-eval-toggle="${escape(item.qid)}" role="button" tabindex="0" aria-expanded="${open}">
      <span class="eval-qid">${escape(item.qid)}</span>
      <span class="eval-qtext">${escape(item.question)}</span>
      <span class="eval-qmeta">${failureTag(item.failure)} ${moveCell(item)}</span>
    </header>
    <div class="eval-qbody">
      <p class="eval-anchors">金标：${anchors}</p>
      <p class="eval-ranks">向量原始名次 ${rankCell(item.vector_rank)} · 最终名次 ${rankCell(item.final_rank)} · 候选池 ${escape(item.pool_size)} 条</p>
      ${open ? hitsTable(item) : ""}
    </div>
  </article>`;
}

function summary(result) {
  if (!result) return "";
  const r = result.recall;
  const jumped = result.items.filter(
    (i) => cache.rerank && i.vector_rank && i.final_rank && i.final_rank < i.vector_rank,
  ).length;
  return `<div class="eval-summary">
    <table class="eval-recall"><thead><tr><th>口径</th><th>Top-1</th><th>Top-3</th><th>Top-5</th></tr></thead>
    <tbody><tr><td>${result.rerank ? "向量 + 重排" : "纯向量（不重排）"}</td>
      ${recallCell(r.top1)}${recallCell(r.top3)}${recallCell(r.top5)}
    </tr></tbody></table>
    <p class="eval-note">共 ${escape(result.total)} 题，失败 ${escape(result.failures)} 题${
      jumped ? `，重排上移 ${escape(jumped)} 题` : ""
    }。判定口径与 <code>scripts/v1_run_baseline.py</code> 一致：锚点任一进入 top-k 即命中。</p>
  </div>`;
}

export function evaluationView() {
  const q = cache.questions;
  const body = cache.loading
    ? '<p role="status">正在跑评测，向量检索需要加载模型与重排器，首次可能需要十几秒…</p>'
    : cache.error
      ? `<div class="eval-error" role="alert"><p>${escape(cache.error)}</p><button class="small-button" data-action="eval-run">重试</button></div>`
      : cache.result
        ? summary(cache.result) + `<div class="eval-questions">${cache.result.items.map(questionRow).join("")}</div>`
        : `<p class="eval-hint">尚未运行。题集 ${q ? escape(q.total) + " 道" : "读取中"}，点击「运行评测」开始。</p>`;

  return `<section class="module-surface eval-surface">
    <header class="eval-head">
      <div>
        <h2>检索质量评测</h2>
        <p>用固定题集复算检索准确率。金标锚点来自 <code>data/processed/eval_questions.json</code>，与 V1/V1.5 报告同一口径。</p>
      </div>
      <div class="eval-controls">
        <label class="eval-switch">
          <input type="checkbox" data-eval-rerank ${cache.rerank ? "checked" : ""} ${cache.loading ? "disabled" : ""}>
          <span>启用重排（bge-reranker-base）</span>
        </label>
        <button class="primary-button" data-action="eval-run" ${cache.loading ? "disabled" : ""}>${cache.loading ? "评测中…" : "运行评测"}</button>
      </div>
    </header>
    ${body}
  </section>`;
}

export function bindEvaluation({ renderPage }) {
  const active = () => location.hash === "#module/evaluation";
  const repaint = () => {
    const host = document.querySelector(".eval-surface");
    if (!host) return;
    const wrap = document.createElement("div");
    wrap.innerHTML = evaluationView();
    host.replaceWith(wrap.firstElementChild);
  };

  async function loadQuestions() {
    if (cache.questions || cache.loading) return;
    try {
      cache.questions = await api("eval/questions");
    } catch (error) {
      cache.error = error.message;
    }
    if (active()) repaint();
  }

  async function run() {
    if (cache.loading) return;
    cache.loading = true;
    cache.error = "";
    cache.result = null;
    cache.expanded.clear();
    if (active()) repaint();
    try {
      /* 评测要跑完 10 题 × 候选池重排，给足超时（默认 30s 不够） */
      cache.result = await api(`eval/run?rerank=${cache.rerank ? "true" : "false"}`, {}, "POST", 180000);
    } catch (error) {
      cache.error = error.message;
    } finally {
      cache.loading = false;
      if (active()) repaint();
    }
  }

  return {
    ensure() {
      if (!active()) return;
      loadQuestions();
    },
    run,
    setRerank(value) {
      cache.rerank = Boolean(value);
      /* 切换开关后旧结果口径已失效，清掉避免误读 */
      cache.result = null;
      cache.error = "";
      if (active()) repaint();
    },
    toggle(qid) {
      if (cache.expanded.has(qid)) cache.expanded.delete(qid);
      else cache.expanded.add(qid);
      if (active()) repaint();
    },
  };
}
