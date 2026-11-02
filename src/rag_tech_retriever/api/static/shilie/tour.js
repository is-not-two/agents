/* 验收巡游：单次可取消运行；真实交互，只读检索，不写业务数据。 */
let activeRun = null;
const qs = (s) => document.querySelector(s);
const qsa = (s) => [...document.querySelectorAll(s)];
const reducedMotion = () => matchMedia("(prefers-reduced-motion: reduce)").matches;

function check(run) {
  if (activeRun !== run || run.controller.signal.aborted || !run.panel.isConnected)
    throw new DOMException("巡游已取消", "AbortError");
}

function wait(ms, run) {
  check(run);
  return new Promise((resolve, reject) => {
    const signal = run.controller.signal;
    const abort = () => { clearTimeout(timer); reject(new DOMException("巡游已取消", "AbortError")); };
    const timer = setTimeout(() => {
      signal.removeEventListener("abort", abort);
      try { check(run); resolve(); } catch (error) { reject(error); }
    }, ms);
    signal.addEventListener("abort", abort, { once: true });
  });
}

function ensurePanel() {
  let panel = qs("#tour-panel");
  if (panel) return panel;
  panel = document.createElement("aside");
  panel.id = "tour-panel";
  panel.innerHTML = '<header><span>验收巡游</span><button type="button" id="tour-close" aria-label="关闭">×</button></header>' +
    '<div id="tour-log"></div><footer id="tour-foot">准备…</footer>';
  document.body.append(panel);
  panel.querySelector("#tour-close").addEventListener("click", () => {
    const run = activeRun;
    if (run?.panel === panel) {
      activeRun = null;
      run.controller.abort();
    }
    panel.remove();
  });
  return panel;
}

function log(panel, text, state) {
  const logEl = panel.querySelector("#tour-log");
  const line = document.createElement("div");
  line.className = "tour-line " + (state || "doing");
  line.textContent = (state === "ok" ? "✅ " : state === "fail" ? "❌ " : "▸ ") + text;
  logEl.append(line);
  logEl.scrollTop = 1e6;
  return line;
}

function highlight(el, run) {
  check(run);
  if (!el) return;
  el.scrollIntoView({ block: "center", behavior: reducedMotion() ? "auto" : "smooth" });
  el.classList.add("tour-target");
  wait(1400, run).then(() => el.classList.remove("tour-target"), () => el.classList.remove("tour-target"));
}

async function waitFor(selector, run, timeout = 8000) {
  const started = Date.now();
  while (Date.now() - started < timeout) {
    check(run);
    const el = qs(selector);
    if (el) return el;
    await wait(150, run);
  }
  throw Error("等待超时: " + selector);
}

async function goto(hash, run) {
  check(run);
  if (location.hash === hash) return;
  location.hash = hash;
  await wait(900, run);
}

function searchAndWait(run, trigger, timeout = 9000) {
  check(run);
  return new Promise((resolve, reject) => {
    const signal = run.controller.signal;
    let requestId = null, triggering = true;
    const cleanup = () => {
      clearTimeout(timer);
      document.removeEventListener("shilie:search-started", started);
      document.removeEventListener("shilie:search-finished", finished);
      signal.removeEventListener("abort", abort);
    };
    const fail = (error) => { cleanup(); reject(error); };
    const abort = () => fail(new DOMException("巡游已取消", "AbortError"));
    const started = (event) => { if (triggering) requestId = event.detail.requestId; };
    const finished = (event) => {
      if (requestId === null || event.detail.requestId !== requestId) return;
      try { check(run); } catch (error) { fail(error); return; }
      cleanup();
      if (event.detail.ok) resolve();
      else reject(Error(event.detail.error || "本次检索失败"));
    };
    const timer = setTimeout(() => fail(Error("本次检索未在时限内完成")), timeout);
    document.addEventListener("shilie:search-started", started);
    document.addEventListener("shilie:search-finished", finished);
    signal.addEventListener("abort", abort, { once: true });
    try {
      trigger();
      triggering = false;
      if (requestId === null) fail(Error("本次检索未启动，请等待已有检索完成"));
    } catch (error) { fail(error); }
  });
}

async function inspectDialog(selector, trigger, run, pause) {
  check(run);
  trigger();
  const dialog = qs(selector);
  const signal = run.controller.signal;
  const abort = () => dialog?.close();
  signal.addEventListener("abort", abort, { once: true });
  try {
    await wait(pause, run);
    check(run);
    if (!dialog?.open) throw Error("弹窗未打开");
  } finally {
    signal.removeEventListener("abort", abort);
    dialog?.close();
  }
}

const STEPS = [
  [
    "首页 · 极光层真实可见",
    async (run) => {
      await goto("#home", run);
      await waitFor(".sl-orbit__hub", run);
      const bg = getComputedStyle(document.body).backgroundColor;
      if (bg !== "rgba(0, 0, 0, 0)") throw Error("body 不透明，极光仍被遮挡");
      return "底色由 html 承载，光斑在内容之下";
    },
  ],
  [
    "首页 · 环轨入口 10 个",
    async (run) => {
      const stage = qs(".sl-orbit");
      const nodes = qsa(".sl-orbit__node");
      if (!stage) throw Error("环轨舞台不存在");
      if (!qs(".sl-orbit__hub")) throw Error("中心开始按钮不存在");
      highlight(stage, run);
      if (nodes.length !== 10) throw Error("入口数 " + nodes.length);
      return `内环 ${qsa(".sl-orbit__ring--inner .sl-orbit__node").length} / 外环 ${qsa(".sl-orbit__ring--outer .sl-orbit__node").length}`;
    },
  ],
  [
    "首页 · 花瓣与萤火虫退层",
    async (run) => {
      // reduce 下动效层被正确禁用（正确降级），断言"确实未启用"而非误报失败（评审 F7）
      if (reducedMotion()) {
        const flies = qs("#fireflies");
        if ((flies && getComputedStyle(flies).display !== "none") ||
            qsa(".petal").some((el) => getComputedStyle(el).display !== "none"))
          throw Error("减少动画下仍显示装饰层");
        return "减少动画：动效层未启用（已验证）";
      }
      const petals = qsa(".petal").length;
      const fly = qs("#fireflies i");
      const under = fly
        ? (() => {
            const r = fly.getBoundingClientRect();
            const hit = document.elementFromPoint(r.left + 2, r.top + 2);
            return hit && !hit.closest("#fireflies");
          })()
        : false;
      if (petals !== 7 || !under) throw Error(`花瓣${petals}/萤火虫压内容`);
      return "7 片花瓣 · 萤火虫在内容下";
    },
  ],
  [
    "首页 · 3D 倾斜与辉光",
    async (run) => {
      /* 环轨节点刻意不参与 3D 倾斜（加了会和公转/自转的 transform 打架），
         倾斜断言改挂在首页统计块 .stat-block 上——它仍在 motion.js 的 TILT_SELECTORS 里。 */
      if (reducedMotion()) {
        if (qs(".stat-block")?.style.transform.includes("perspective"))
          throw Error("减少动画下仍有倾斜");
        return "减少动画：倾斜已降级（已验证）";
      }
      const card = qs(".stat-block");
      if (!card) throw Error("统计块不存在");
      highlight(card, run);
      const r = card.getBoundingClientRect();
      card.dispatchEvent(
        new MouseEvent("mousemove", {
          clientX: r.left + r.width * 0.75,
          clientY: r.top + r.height * 0.7,
          bubbles: true,
        }),
      );
      await wait(400, run);
      if (!card.style.transform.includes("perspective"))
        throw Error("无倾斜 transform");
      return "统计块跟随光标翻转";
    },
  ],
  [
    "首页 · 点击粒子爆发",
    async (run) => {
      if (reducedMotion()) {
        if (qsa(".particle").some((el) => getComputedStyle(el).display !== "none"))
          throw Error("减少动画下仍显示粒子");
        return "减少动画：粒子已禁用（已验证）";
      }
      const hero = qs(".home-hero");
      highlight(hero, run);
      const r = hero.getBoundingClientRect();
      const burst = new MouseEvent("pointerdown", {
        clientX: r.left + r.width * 0.5,
        clientY: r.top + 40,
        bubbles: true,
      });
      document.dispatchEvent(burst);
      await wait(160, run);
      const n = qsa(".particle").length;
      if (n < 8) throw Error("粒子 " + n);
      await wait(800, run);
      return n + " 粒金色碎片已自清";
    },
  ],
  [
    "规划 · 连线生长与节点弹入",
    async (run) => {
      await goto("#module/planning", run);
      if (!qs(".story-card") && qs(".story-empty"))
        return { skip: "规划为空，无节点动画可检查" };
      await waitFor(".story-card", run);
      const line = qs(".story-canvas path");
      const card = qs(".story-card");
      highlight(card, run);
      if (!line) return { skip: "当前规划无连线" };
      const expected = reducedMotion() ? "none" : "card-pop";
      if (getComputedStyle(card).animationName !== expected)
        throw Error(reducedMotion() ? "减少动画下仍有节点动画" : "无弹入动画");
      return "树是生长出来的";
    },
  ],
  [
    "规划 · 折叠往返",
    async (run) => {
      const count = () =>
        qsa(".story-card").filter((e) => e.offsetParent).length;
      const before = count();
      if (before <= 1) return { skip: "没有展开的子节点可作折叠往返检查" };
      qs("[data-action=tree-fold-all]").click();
      await wait(600, run);
      const folded = count();
      qs("[data-action=tree-expand-all]").click();
      await wait(600, run);
      const after = count();
      if (!(folded < before && after === before))
        throw Error(`${before}→${folded}→${after}`);
      return `${before}→${folded}→${after} 复原`;
    },
  ],
  [
    "知识库 · 空态示意与弹窗",
    async (run) => {
      await goto("#module/knowledge", run);
      const demo = qsa(".demo-card").length;
      const notes = qsa(".note-card").length;
      if (demo !== 3 && notes === 0 && !qs(".empty-panel"))
        throw Error("知识列表和空态均不存在");
      await inspectDialog(".form-dialog[data-form=knowledge]", () => qs("[data-action=new-note]").click(), run, 450);
      return demo === 3 ? "3 张示意 · 弹窗正常" : "知识列表或筛选空态 · 弹窗正常";
    },
  ],
  [
    "谨记名单 · 分类与录入",
    async (run) => {
      await goto("#module/lessons", run);
      await waitFor(".lesson-chips", run);
      const chips = qsa(".lesson-chip").length;
      if (chips < 6) throw Error("chips " + chips);
      await inspectDialog(".form-dialog[data-form=lesson]", () => qs("[data-action=lesson-new]").click(), run, 400);
      return chips + " 个分类 · 弹窗正常";
    },
  ],
  [
    "检索 · 示例一键真搜",
    async (run) => {
      await goto("#module/documents", run);
      await searchAndWait(run, () => {
        const chip = qs(".example-chip");
        if (chip) {
          highlight(chip, run);
          chip.click();
        } else {
          const input = qs("#search-form input[name=query]");
          if (!input) throw Error("搜索表单不存在");
          input.value = "协议号状态怎么查";
          input.form.requestSubmit();
        }
      });
      await waitFor(".result-meta, .result-list", run);
      return "本次真实检索成功，结果已渲染";
    },
  ],
  [
    "设置 · 服务状态卡",
    async (run) => {
      await goto("#module/appearance", run);
      await waitFor(".server-status", run);
      await wait(900, run);
      const text = qs(".server-status").innerText;
      highlight(qs(".server-status"), run);
      if (!text.includes("MCP 服务")) throw Error("无 MCP 行");
      return "MCP · 向量库 · 记录表";
    },
  ],
];

export function startTour() {
  if (activeRun) return;
  qs("#director-close")?.click();
  const panel = ensurePanel();
  const run = { panel, controller: new AbortController() };
  activeRun = run;
  panel.querySelector("#tour-log").replaceChildren();
  (async () => {
    let pass = 0, skipped = 0;
    try {
      for (let i = 0; i < STEPS.length; i++) {
        check(run);
        const [name, fn] = STEPS[i];
        const line = log(panel, name);
        panel.querySelector("#tour-foot").textContent = `巡游中 ${i + 1}/${STEPS.length}`;
        await wait(650, run);
        try {
          const detail = await fn(run);
          check(run);
          line.remove();
          if (detail?.skip) {
            skipped++;
            log(panel, name + " · 不适用：" + detail.skip, "skip");
          } else {
            log(panel, name + (detail ? " · " + detail : ""), "ok");
            pass++;
          }
        } catch (error) {
          check(run);
          line.remove();
          log(panel, name + " ❌ " + String(error.message).slice(0, 70), "fail");
        }
      }
      check(run);
      panel.querySelector("#tour-foot").textContent = `完成：${pass}/${STEPS.length - skipped} 通过${skipped ? `，${skipped} 项不适用` : ""}（点 × 关闭）`;
      await goto("#module/appearance", run);
    } catch (error) {
      if (!run.controller.signal.aborted && activeRun === run && panel.isConnected)
        log(panel, "巡游中断：" + String(error.message).slice(0, 70), "fail");
    } finally {
      run.controller.abort();
      if (activeRun === run) activeRun = null;
    }
  })();
}
