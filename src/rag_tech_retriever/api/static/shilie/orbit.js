/* 环轨引擎：全局单一角度源 + rAF 写 CSS 变量（首页「开始」环轨入口）。
   为什么不用 CSS animation 驱动公转：
   ①hover 要减速到额定 1/10、focus 要全停、用户暂停要全停，animation-play-state
     只能全停、不能分级；
   ②公转（环）与反向自转（节点）若用两套独立 animation，两者起始时刻与掉帧
     累积不同，会逐步产生相位差，节点看起来在"追赶"环轨。
   所以角度只在这一个地方累加，每帧往 .sl-orbit 上写一次 --sl-a-in / --sl-a-out，
   环上 10 个节点的"公转 + 自转抵消"都在同一条 transform 里用同一个变量算完，
   结构上不可能漂移。

   速度状态机归并为 stage.dataset.orbitSpeed 三个取值（running / slow / stopped，
   hover 改为「立即全停」后 slow 实际上不会再出现，保留枚举只为调试可读）。
   优先级：reduced-motion > 用户暂停 > 入口获得键盘焦点 > 指针停在某个入口上 > 无交互。
   页面隐藏时停 rAF，恢复时从当前角度继续（不回位）。 */

import { MOTION_CONFIG } from "./motion-config.js?v=121";

const NOMINAL_IN = 5; // 内环 °/s，顺时针
const NOMINAL_OUT = -3.75; // 外环 °/s，逆时针
const TAU = 0.2; // 速度插值的时间常数 200ms
/* 起转 600ms / 刹停 180ms 的不对称是刻意的，不要统一：
   起转慢，节点在环上"活"起来时有重量感；刹停快，悬停时靶子 180ms 内就钉死，
   否则用户正要点击那一刻目标还在动。 */
const RISE_SPAN = 0.6; // 0 → 额定：600ms
const FALL_SPAN = 0.18; // 额定 → 0：180ms
const DT_CAP = 0.25; // 单帧最大累加时长，防止切回标签页时角度瞬跳

let raf = 0;
let dispose = null;

const mod360 = (v) => ((v % 360) + 360) % 360;

export function initOrbit() {
  /* 幂等：先取消上一轮 rAF、解绑旧监听，再重绑（每次 renderPage 都会调用）。 */
  if (raf) cancelAnimationFrame(raf);
  raf = 0;
  dispose?.();
  dispose = null;

  const stage = document.querySelector(".sl-orbit");
  if (!stage) return; // 非首页：环轨不存在，直接返回

  const hub = stage.querySelector(".sl-orbit__hub");
  const hubLabel = stage.querySelector(".sl-orbit__hub-label");
  const hubState = stage.querySelector(".sl-orbit__hub-state");
  const statusBox = stage.querySelector("#sl-orbit-status");
  const mq = matchMedia("(prefers-reduced-motion: reduce)");

  let angleIn = 0;
  let angleOut = 0;
  let factor = 0; // 当前速度系数 0..1（内外环共用，保证同步）
  let target = 0;
  let last = 0;
  /* 首页是"开始页"：进页即转，不需要先点一下 —— 动起来本身就是欢迎。
     仍保留暂停能力：点中心按钮可停，点入口时自动让路，减少动画下不启动。 */
  let mode = "running"; // idle | running | paused
  let onNode = false; // 指针真的停在某个入口上（空白区不算，见 onNodeEnter 注释）
  let entryFocus = false;
  let visible = document.visibilityState !== "hidden";
  let litTimer = 0;
  let enterTimer = 0;

  /* ---- 状态推导 ---- */

  function computeTarget() {
    if (mq.matches) return 0; // 优先级 1：减少动画
    if (document.documentElement.dataset.motion === "off") return 0;
    if (mode !== "running") return 0; // 优先级 2：用户暂停 / 从未启动
    if (entryFocus) return 0; // 优先级 3：键盘聚焦到任一入口
    /* 优先级 4：指针停在入口上 → 完全静止。不是"降速"，是 0：
       用户悬停的意图就是"我要点这一颗"，靶子还在爬就等于点不中。
       缓降交给 FALL_SPAN=180ms，累计位移约 0.45°（170px 半径上 1.3px），看不出来。 */
    if (onNode) return 0;
    return 1; // 优先级 5：无交互
  }

  function speedName(value) {
    if (value >= 1) return "running";
    return value > 0 ? "slow" : "stopped";
  }

  function syncSpeed() {
    const name = speedName(target);
    if (stage.dataset.orbitSpeed !== name) stage.dataset.orbitSpeed = name;
  }

  function syncHub() {
    /* 开始页语义：中心按钮是"进入工作台"，不是播放控制。
       环轨一进页就在转，暂停交给"指针停到入口上"。 */
    if (hubLabel) hubLabel.textContent = "进入工作台";
    if (hubState) hubState.textContent = target === 0 ? "环轨已静止" : "环轨运行中";
    if (hub) hub.setAttribute("aria-label", "进入工作台");
  }
  function announce(text) {
    if (statusBox) statusBox.textContent = text;
  }

  /* ---- 角度写入 ---- */

  function write() {
    stage.style.setProperty("--sl-a-in", angleIn.toFixed(3) + "deg");
    stage.style.setProperty("--sl-a-out", angleOut.toFixed(3) + "deg");
  }

  function clearAngles() {
    stage.style.removeProperty("--sl-a-in");
    stage.style.removeProperty("--sl-a-out");
  }

  /* ---- 主循环 ---- */

  function tick(now) {
    raf = 0;
    if (!stage.isConnected) return; // 页面已被替换，静默退出
    const dt = Math.min(DT_CAP, Math.max(0, (now - last) / 1000));
    last = now;

    const next = computeTarget();
    if (next !== target) {
      target = next;
      syncSpeed();
    }

    /* 平滑插值，两条约束同时成立：
       ①「剩余量 / 跨度」线性斜坡 —— 速度变化没有任何瞬间跳变，且 0→额定
         恰好 600ms、额定→0 恰好 180ms 落地到 0（不会留尾巴）；
       ②指数项（τ=200ms）只在单帧 dt 极小、或落差本来就极小时提供更软的起步。
       为什么不用纯指数：τ=200ms 的指数衰减要 3τ≈600ms 才走到 95%，实测点暂停后
       环还会继续爬 0.84°、890ms 才完全停住——既不满足「刹停 180ms 上限」，
       也不满足验收要求的「200ms 内角速度归零」。 */
    const gap = target - factor;
    const span = gap > 0 ? RISE_SPAN : FALL_SPAN;
    const eased = Math.abs(gap) * (1 - Math.exp(-dt / TAU));
    const step = gap === 0 ? 0 : Math.max(eased, dt / span);
    if (Math.abs(gap) <= step) factor = target;
    else factor += Math.sign(gap) * step;

    if (factor !== 0) {
      angleIn = mod360(angleIn + NOMINAL_IN * factor * dt);
      angleOut = mod360(angleOut + NOMINAL_OUT * factor * dt);
      write();
    }

    if (factor !== 0 || target !== 0) raf = requestAnimationFrame(tick);
  }

  function kick() {
    if (raf || !visible) return;
    if (factor === 0 && target === 0) return; // 本来就完全静止，不必空转
    last = performance.now();
    raf = requestAnimationFrame(tick);
  }

  function recompute() {
    target = computeTarget();
    syncSpeed();
    syncHub();
    kick();
  }

  /* ---- 事件 ---- */

  /* 每秒都要判的只有节点，空白区不构成"要看清楚"的意图：
     舞台 576×576 里 10 个节点只占约 12% 面积，另外 88% 是空白；
     若把整个舞台算进去，用户点完「开始」鼠标恰好停在按钮旁边几像素处，
     环会在缓起阶段被立刻判停 —— 「点了开始却什么都没转」。
     所以逐节点绑定：只有指针真的压在某个入口上才让路。
     只绑 pointerenter/pointerleave（它忽略元素内部子元素之间的移动），
     不要再叠 pointerover/pointerout：节点里有 icon 和 label 三层，
     over/out 每划过图标就产生一对假事件，会把刚停下的环又恢复一次。 */
  const nodes = [...stage.querySelectorAll(".sl-orbit__node")];
  const onNodeEnter = (event) => {
    if (event.pointerType === "touch") return; // 触屏的合成 hover 会粘住，不参与
    onNode = true;
    recompute();
  };
  const onNodeLeave = () => {
    onNode = false;
    recompute();
  };
  const onFocusIn = (event) => {
    entryFocus = !hub.contains(event.target);
    recompute();
  };
  const onFocusOut = (event) => {
    const next = event.relatedTarget;
    entryFocus = !!(next && stage.contains(next) && !hub.contains(next));
    recompute();
  };
  /* 首页是"开始页"：中心按钮进入独立的工作台视图，而不是在同一页往下滚。
     路由变化由 app.js 的 hashchange 接管，环轨随之卸载。 */
  const onHubClick = (event) => {
    event.preventDefault();
    if (location.hash === "#home/workspace") return;
    announce("进入工作台");
    if (enterTimer) return;
    const finish = () => {
      enterTimer = 0;
      if (!stage.isConnected) return;
      location.hash = "#home/workspace";
      window.dispatchEvent(new Event("shilie:entered-workspace"));
    };
    if (mq.matches || document.documentElement.dataset.motion === "off") return finish();
    stage.classList.add("is-entering");
    window.dispatchEvent(new Event("shilie:entering-workspace"));
    enterTimer = setTimeout(finish, MOTION_CONFIG.enterMilliseconds);
  };
  const onVisibility = () => {
    if (document.visibilityState === "hidden") {
      visible = false;
      if (raf) cancelAnimationFrame(raf);
      raf = 0;
    } else {
      visible = true;
      /* 从当前角度继续，不回位：angleIn / angleOut 一直保留。 */
      kick();
    }
  };
  const onReduceChange = () => {
    if (mq.matches) clearAngles(); // 让 CSS 里的 --sl-a-in:0deg 生效
    recompute();
  };

  nodes.forEach((node) => {
    node.addEventListener("pointerenter", onNodeEnter);
    node.addEventListener("pointerleave", onNodeLeave);
  });
  stage.addEventListener("focusin", onFocusIn);
  stage.addEventListener("focusout", onFocusOut);
  hub.addEventListener("click", onHubClick);
  document.addEventListener("visibilitychange", onVisibility);
  mq.addEventListener("change", onReduceChange);
  window.addEventListener("shilie:motionchange", recompute);

  dispose = () => {
    nodes.forEach((node) => {
      node.removeEventListener("pointerenter", onNodeEnter);
      node.removeEventListener("pointerleave", onNodeLeave);
    });
    stage.removeEventListener("focusin", onFocusIn);
    stage.removeEventListener("focusout", onFocusOut);
    hub.removeEventListener("click", onHubClick);
    document.removeEventListener("visibilitychange", onVisibility);
    mq.removeEventListener("change", onReduceChange);
    window.removeEventListener("shilie:motionchange", recompute);
    clearTimeout(litTimer);
    clearTimeout(enterTimer);
  };

  /* ---- 首帧 ---- */

  target = computeTarget();
  syncSpeed();
  syncHub();

  if (mq.matches) {
    /* 减少动画：不启动 rAF，角度恒 0（CSS 里已声明），入场位移直接取消。 */
    stage.classList.add("is-lit");
    return;
  }

  /* 入场：先落一次未点亮状态，再点亮，保证 transition 真的跑起来；
     800ms 兜底，避免首帧回调被浏览器丢弃时节点一直不可见。
     不用 IntersectionObserver：默认静止下入场只承担"成形"，不承担"证明会动"，
     折叠线下播完不影响信息传达。 */
  requestAnimationFrame(() => {
    if (!stage.isConnected) return;
    void stage.offsetWidth;
    stage.classList.add("is-lit");
  });
  litTimer = setTimeout(() => {
    if (stage.isConnected) stage.classList.add("is-lit");
  }, 800);

  /* 默认运行：入场成形之后立即起转。factor 从 0 出发，
     所以前 600ms 是"缓缓转起来"而不是突兀地全速，起转与入场同时完成。 */
  if (mode === "running") {
    recompute();
    kick();
  }
}
