/* 动效引擎：动效成体系、偏好可关闭（2026-10-24 深夜各轮的固化实现）。
   三律：①入场位移只用纵向；②私密页（滑块几何断言页）整体豁免；③装饰层全部
   fixed + pointer-events:none，且必须验证层叠可见性（极光/萤火虫 z=-1 画在
   html 底色之上、内容之下）。所有动效在 prefers-reduced-motion: reduce 下
   禁用：花瓣/萤火虫/辉光不创建，粒子零产生，倾斜/滚动/数字滚动全部短路。 */

const reduce = () => matchMedia("(prefers-reduced-motion: reduce)").matches;
const TILT_SELECTORS = ".portal-entry,.note-card,.lesson-row,.stat-block";
const RIPPLE_SELECTORS = ".primary-button,.portal-entry,.lesson-chip";

function spawnPetals() {
  if (document.querySelector(".petal")) return;
  for (let i = 0; i < 7; i++) {
    const petal = document.createElement("span");
    petal.className = "petal";
    petal.style.left = `${6 + i * 13 + (i % 3) * 3}%`;
    petal.style.animationDuration = `${12 + (i % 4) * 1.6}s`;
    petal.style.animationDelay = `${-i * 2.4}s`;
    document.body.append(petal);
  }
}

function spawnFireflies() {
  if (document.querySelector("#fireflies")) return;
  const box = document.createElement("div");
  box.id = "fireflies";
  box.setAttribute("aria-hidden", "true");
  for (let i = 0; i < 14; i++) {
    const fly = document.createElement("i");
    // 起点收在 10%-90%，配合 ±30px 漂移，任何视口宽度都不漂出画布（巡游曾抓到越界致断言失败）
    fly.style.setProperty("--fx", `${10 + ((i * 80) / 13) % 80}%`);
    fly.style.setProperty("--fy", `${12 + ((i * 37) % 76)}%`);
    fly.style.animationDuration = `${18 + ((i * 7) % 23)}s`;
    fly.style.animationDelay = `${-i * 1.9}s`;
    box.append(fly);
  }
  document.body.append(box);
}

function spawnGlow() {
  if (document.querySelector(".cursor-glow")) return;
  const glow = document.createElement("div");
  glow.className = "cursor-glow";
  glow.setAttribute("aria-hidden", "true");
  document.body.append(glow);
  let pending = null;
  document.addEventListener(
    "mousemove",
    (e) => {
      pending = e;
      if (pending._frame) return;
      pending._frame = requestAnimationFrame(() => {
        const event = pending;
        pending._frame = null;
        glow.style.transform = `translate(${event.clientX - 140}px, ${event.clientY - 140}px)`;
      });
    },
    { passive: true },
  );
}

function ambientLayers() {
  if (reduce()) return;
  spawnPetals();
  spawnFireflies();
  spawnGlow();
}

/* 点击粒子：10 粒金色碎片，620ms 自清；reduce 下零产生。 */
document.addEventListener(
  "pointerdown",
  (e) => {
    if (reduce()) return;
    for (let i = 0; i < 10; i++) {
      const p = document.createElement("span");
      p.className = "particle";
      const angle = (Math.PI * 2 * i) / 10 + Math.random() * 0.5;
      const dist = 42 + Math.random() * 52;
      p.style.left = `${e.clientX}px`;
      p.style.top = `${e.clientY}px`;
      p.style.setProperty("--px", `${Math.cos(angle) * dist}px`);
      p.style.setProperty("--py", `${Math.sin(angle) * dist + 26}px`);
      p.style.setProperty("--pr", `${Math.random() * 260 - 130}deg`);
      document.body.append(p);
      setTimeout(() => p.remove(), 640);
    }
  },
  { passive: true },
);

/* 涟漪 tap-wave：坐标定位点击点，500ms 扩散后自清。 */
document.addEventListener("pointerdown", (e) => {
  if (reduce()) return;
  const target =
    e.target instanceof Element && e.target.closest(RIPPLE_SELECTORS);
  if (!target) return;
  const rect = target.getBoundingClientRect();
  const wave = document.createElement("span");
  wave.className = "tap-wave";
  wave.style.left = `${e.clientX - rect.left}px`;
  wave.style.top = `${e.clientY - rect.top}px`;
  target.append(wave);
  setTimeout(() => wave.remove(), 520);
});

/* 3D 倾斜：鼠标位置驱动 perspective 800px rotateX/Y ±7-9°，同步光斑 --mx/--my。 */
document.addEventListener(
  "mousemove",
  (e) => {
    if (reduce()) return;
    const card =
      e.target instanceof Element && e.target.closest(TILT_SELECTORS);
    document.querySelectorAll(TILT_SELECTORS).forEach((el) => {
      if (el !== card && el.dataset.tilted) {
        el.dataset.tilted = "";
        el.style.transform = "";
      }
    });
    if (!card) return;
    const rect = card.getBoundingClientRect();
    const px = (e.clientX - rect.left) / rect.width;
    const py = (e.clientY - rect.top) / rect.height;
    card.dataset.tilted = "1";
    card.style.setProperty("--mx", `${Math.round(px * 100)}%`);
    card.style.setProperty("--my", `${Math.round(py * 100)}%`);
    card.style.transform = `perspective(800px) rotateX(${(0.5 - py) * 15}deg) rotateY(${(px - 0.5) * 18}deg) translateZ(6px)`;
  },
  { passive: true },
);

/* 首页插画鼠标视差：±12px，rAF 节流。 */
function bindParallax() {
  const hero = document.querySelector(".home-hero picture");
  if (!hero || hero.dataset.parallax) return;
  hero.dataset.parallax = "1";
  const img = hero.querySelector("img");
  if (!img) return;
  document.addEventListener(
    "mousemove",
    (e) => {
      if (reduce() || !img.isConnected) return;
      const dx = (e.clientX / window.innerWidth - 0.5) * 24;
      const dy = (e.clientY / window.innerHeight - 0.5) * 18;
      img.style.translate = `${dx.toFixed(1)}px ${dy.toFixed(1)}px`;
    },
    { passive: true },
  );
}

/* 统计数字滚动：纯整数 0→目标 620ms ease-out cubic；比率值直接显示。 */
function rollNumbers(root) {
  if (reduce()) return;
  root.querySelectorAll("[data-count]").forEach((el) => {
    if (el.dataset.rolled) return;
    el.dataset.rolled = "1";
    const target = Number(el.dataset.count);
    if (!Number.isFinite(target) || target <= 0) return;
    const started = performance.now();
    const tick = (now) => {
      const t = Math.min(1, (now - started) / 620);
      const eased = 1 - Math.pow(1 - t, 3);
      el.firstChild &&
        (el.firstChild.nodeValue = String(Math.round(target * eased)));
      if (t < 1) requestAnimationFrame(tick);
      else el.firstChild && (el.firstChild.nodeValue = String(target));
    };
    requestAnimationFrame(tick);
  });
}

/* 滚动渐显 + 页面内容入场：私密页整体豁免（滑块几何历史修过三轮）。 */
let revealObserver = null;
function observeReveals() {
  if (reduce() || !("IntersectionObserver" in window)) return;
  revealObserver =
    revealObserver ||
    new IntersectionObserver(
      (entries) => {
        entries.forEach((entry) => {
          if (entry.isIntersecting) {
            entry.target.classList.add("revealed");
            revealObserver.unobserve(entry.target);
          }
        });
      },
      { threshold: 0.08 },
    );
  const scope = document.getElementById("content");
  if (!scope) return;
  if (location.hash.includes("private")) return;
  scope
    .querySelectorAll(
      ".module-surface,.fold-section,.today-overview,.result-card",
    )
    .forEach((el) => {
      if (!el.classList.contains("revealed")) {
        el.classList.add("reveal");
        revealObserver.observe(el);
      }
    });
}

export function initMotion({ content }) {
  ambientLayers();
  /* 页面转场：hash 切换后 260ms 纵向滑入（横向位移会造成视口溢出，禁用）。 */
  window.addEventListener("hashchange", () => {
    if (reduce()) return;
    content.classList.remove("page-enter");
    void content.offsetWidth; // 重启动画
    content.classList.add("page-enter");
    observeReveals();
  });
  /* 重绘后重挂渐显/数字滚动/视差。 */
  new MutationObserver(() => {
    rollNumbers(content);
    observeReveals();
    bindParallax();
  }).observe(content, { childList: true, subtree: false });
  rollNumbers(content);
  observeReveals();
  bindParallax();
}
