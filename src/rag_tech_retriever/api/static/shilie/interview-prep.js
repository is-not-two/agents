/* 模拟面试：生成题目 → 逐题作答 → 确定性规则评分。
   数据只存 kind=interview_prep，绝不写入真实面试复盘 interview_report。
   语音模拟已冻结，不提供入口；模型生成需已配置连接，失败时保留错误提示。 */
import { api, escapeHtml as esc } from "./data.js?v=116";

const cache = {
  sessions: null,
  leads: null,
  resumes: null,
  draft: null,
  activeId: "",
  error: "",
  busy: false,
};

let _repaint = () => {};
let _toast = () => {};

const active = () => location.hash === "#module/interview-prep";

async function load(force = false) {
  if (cache.busy) return;
  if (!force && cache.sessions && cache.leads && cache.resumes) return;
  cache.busy = true;
  cache.error = "";
  try {
    const [sessions, leads, resumes] = await Promise.all([
      api("interview-prep"),
      api("jobs/leads"),
      api("jobs/resumes"),
    ]);
    cache.sessions = sessions || [];
    cache.leads = leads || [];
    cache.resumes = resumes || [];
  } catch (e) {
    cache.error = e.message;
  } finally {
    cache.busy = false;
    if (active()) _repaint();
  }
}

function current() {
  return (cache.sessions || []).find((row) => row.id === cache.activeId) || null;
}

function options(rows, chosen) {
  return (rows || [])
    .map(
      (row) =>
        `<option value="${esc(row.id)}"${row.id === chosen ? " selected" : ""}>${esc(
          row.data?.title || row.data?.company || row.id,
        )}</option>`,
    )
    .join("");
}

function turnsHtml(turns) {
  return (turns || [])
    .map(
      (turn, index) => `<article class="module-surface prep-turn">
      <h3>${index + 1}. ${esc(turn.q)}</h3>
      <label class="form-field">我的回答<textarea data-prep-answer="${index}" rows="4" maxlength="8000">${esc(
        turn.answer || "",
      )}</textarea></label>
      ${turn.suggestion ? `<p><small>优化建议：${esc(turn.suggestion)}</small></p>` : ""}
    </article>`,
    )
    .join("");
}

function evaluationHtml(evaluation) {
  if (!evaluation || !evaluation.source) return "";
  const dimensions = Object.entries(evaluation.dimensions || {})
    .map(([name, value]) => `<li>${esc(name)}：${esc(value)}</li>`)
    .join("");
  return `<section class="module-surface prep-score"><h2>规则评分 ${esc(
    evaluation.score,
  )}</h2><ul>${dimensions}</ul><p>${esc(evaluation.feedback)}</p><p><small>${esc(
    evaluation.notes,
  )}</small></p></section>`;
}

export function interviewPrepView() {
  if (cache.error)
    return `<section class="empty-panel"><h2>模拟面试暂不可用</h2><p>${esc(
      cache.error,
    )}</p><button class="primary-button" data-action="prep-reload">重试</button></section>`;
  if (!cache.sessions)
    return `<section class="loading-panel" role="status"><p>正在读取岗位、简历与会话…</p></section>`;
  const session = current();
  const draft = cache.draft;
  return `<section class="module-surface">
    <h2>生成一场模拟面试</h2>
    <p><small>题目来自岗位 JD 与简历正文；会话独立保存，不会写入真实面试复盘。语音模拟暂未开放。</small></p>
    <form id="prep-generate-form">
      <label class="form-field">岗位<select name="lead_id" required>${options(cache.leads, "")}</select></label>
      <label class="form-field">简历<select name="resume_id" required>${options(cache.resumes, "")}</select></label>
      <label class="form-field">模式<select name="mode">
        <option value="practice">练习（只给问题）</option>
        <option value="full">完整问答（含示范回答）</option>
      </select></label>
      <label class="form-check"><input type="checkbox" name="use_model"> 用模型生成（未配置连接会失败）</label>
      <button class="primary-button" type="submit"${cache.busy ? " disabled" : ""}>生成题目</button>
    </form>
  </section>
  ${
    draft
      ? `<section class="module-surface"><h2>草稿（尚未保存）</h2><p>${esc(
          draft.title,
        )}</p>${turnsHtml(draft.turns)}<button class="primary-button" data-action="prep-save">保存为会话</button><p><small>${esc(
          draft.notes,
        )}</small></p></section>`
      : ""
  }
  <section class="module-surface"><h2>已有会话</h2>
    ${
      cache.sessions.length
        ? `<ul>${cache.sessions
            .map(
              (row) =>
                `<li><button class="small-button" data-action="prep-select" data-id="${esc(
                  row.id,
                )}">${esc(row.data?.title || row.id)}</button></li>`,
            )
            .join("")}</ul>`
        : "<p>暂无会话。</p>"
    }
  </section>
  ${
    session
      ? `<section class="module-surface" id="prep-session"><h2>${esc(
          session.data?.title || "会话",
        )}</h2>${turnsHtml(session.data?.turns)}<div class="prep-actions"><button class="primary-button" data-action="prep-answers">提交作答</button><button class="small-button" data-action="prep-evaluate">规则评分</button></div><p><small>先提交作答再评分；评分只使用已保存的答案。</small></p>${evaluationHtml(
          session.data?.evaluation,
        )}</section>`
      : ""
  }`;
}

function replaceSession(row) {
  cache.sessions = (cache.sessions || []).map((item) =>
    item.id === row.id ? row : item,
  );
}

export function bindInterviewPrep({ renderPage, toast }) {
  _repaint = () => {
    if (active()) renderPage({ restore: true });
  };
  _toast = toast || (() => {});

  document.addEventListener("submit", async (e) => {
    if (!(e.target instanceof HTMLFormElement) || e.target.id !== "prep-generate-form") return;
    e.preventDefault();
    if (cache.busy) return;
    const form = e.target;
    cache.busy = true;
    try {
      cache.draft = await api("interview-prep/generate", {
        lead_id: form.elements.namedItem("lead_id").value,
        resume_id: form.elements.namedItem("resume_id").value,
        mode: form.elements.namedItem("mode").value,
        use_model: form.elements.namedItem("use_model").checked,
      });
      cache.error = "";
      _toast("题目已生成，确认后再保存会话");
    } catch (err) {
      cache.error = err.message;
      _toast(err.message);
    } finally {
      cache.busy = false;
      _repaint();
    }
  });

  document.addEventListener("click", async (e) => {
    if (!(e.target instanceof Element)) return;
    const button = e.target.closest("[data-action^='prep-']");
    if (!button || cache.busy) return;
    const action = button.dataset.action.slice(5);
    if (action === "reload") {
      cache.error = "";
      await load(true);
      return;
    }
    if (action === "select") {
      cache.activeId = button.dataset.id;
      cache.draft = null;
      _repaint();
      return;
    }
    const session = current();
    if (action === "save" && cache.draft) {
      cache.busy = true;
      try {
        const row = await api("interview-prep", { data: cache.draft });
        cache.sessions = [row, ...(cache.sessions || [])];
        cache.activeId = row.id;
        cache.draft = null;
        _toast("会话已保存，未写入面试复盘");
      } catch (err) {
        _toast(err.message);
      } finally {
        cache.busy = false;
        _repaint();
      }
      return;
    }
    if (action === "answers" && session) {
      const fields = [
        ...document.querySelectorAll("#prep-session [data-prep-answer]"),
      ];
      const answers = fields.map((field) => ({
        index: Number(field.dataset.prepAnswer),
        answer: field.value,
      }));
      if (!answers.length) return;
      cache.busy = true;
      try {
        const row = await api(`interview-prep/${session.id}/answers`, {
          version: session.version,
          answers,
        });
        replaceSession(row);
        _toast("作答已提交");
      } catch (err) {
        _toast(err.message);
      } finally {
        cache.busy = false;
        _repaint();
      }
      return;
    }
    if (action === "evaluate" && session) {
      cache.busy = true;
      try {
        const row = await api(`interview-prep/${session.id}/evaluate`, {
          version: session.version,
          source: "rules",
        });
        replaceSession(row);
        _toast("规则评分完成");
      } catch (err) {
        _toast(err.message);
      } finally {
        cache.busy = false;
        _repaint();
      }
    }
  });

  return {
    ensure() {
      if (active() && !cache.sessions && !cache.busy && !cache.error) load();
    },
  };
}
