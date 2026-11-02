// 临时截图脚本（交付后删除）：离线 harness，mock /api/*，直接读磁盘静态资源。
import { loadPlaywright } from "./playwright-runtime.mjs";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await loadPlaywright();
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const ROOT = fileURLToPath(new URL("../", import.meta.url));
const STATIC = path.join(ROOT, "src", "rag_tech_retriever", "api", "static", "shilie");
const OUT = path.join(ROOT, "output", "web");
fs.mkdirSync(OUT, { recursive: true });

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".svg": "image/svg+xml",
  ".webp": "image/webp",
  ".png": "image/png",
};

const API = {
  session: { required: false, authenticated: true },
  knowledge: [],
  plans: [],
  status: {},
  "stage-summary": { records: [], updated_at: "" },
  "query/options": { namespaces: [], default: null },
  agents: [],
  workflows: [],
  "workflow-runs": [],
  runs: [],
  lessons: [],
  jobs: [],
  notifications: [],
};

const browser = await chromium.launch({ executablePath: EDGE });

async function shot(name, { width, height, run }) {
  const page = await browser.newPage({ viewport: { width, height } });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("console", (m) => m.type() === "error" && errors.push(m.text()));

  await page.route("**/*", async (route) => {
    const url = new URL(route.request().url());
    const p = url.pathname;
    if (p.startsWith("/api/")) {
      const key = p.replace("/api/", "").replace(/\/$/, "");
      const body = API[key] ?? API[key.split("/")[0]] ?? [];
      return route.fulfill({ status: 200, contentType: "application/json", body: JSON.stringify(body) });
    }
    if (p.startsWith("/static/shilie/")) {
      const file = path.join(STATIC, p.replace("/static/shilie/", ""));
      if (fs.existsSync(file)) {
        return route.fulfill({
          status: 200,
          contentType: MIME[path.extname(file)] || "application/octet-stream",
          body: fs.readFileSync(file),
        });
      }
    }
    if (p === "/" || p === "/index.html") {
      return route.fulfill({
        status: 200,
        contentType: MIME[".html"],
        body: fs.readFileSync(path.join(STATIC, "index.html")),
      });
    }
    return route.fulfill({ status: 204, body: "" });
  });

  await page.goto("http://orbit.local/", { waitUntil: "domcontentloaded" });
  await page.waitForSelector(width < 960 ? ".sl-orbit-list__item" : ".sl-orbit", {
    state: "attached",
    timeout: 15000,
  });
  if (width >= 960) {
    await page.waitForFunction(
      () => document.querySelector(".sl-orbit")?.classList.contains("is-lit"),
      null,
      { timeout: 15000 },
    );
  }
  await page.waitForTimeout(400);
  await page.mouse.move(0, 0);
  await page.waitForTimeout(200);

  if (run) {
    await page.click(".sl-orbit__hub");
    await page.waitForTimeout(1200);
    await page.mouse.move(0, 0);
    await page.waitForTimeout(300);
  }

  const info = await page.evaluate(() => {
    const st = document.querySelector(".sl-orbit");
    const nodes = [...document.querySelectorAll(".sl-orbit__node")];
    return {
      nodes: nodes.length,
      hubLabel: document.querySelector(".sl-orbit__hub-label")?.textContent,
      hubState: document.querySelector(".sl-orbit__hub-state")?.textContent,
      speed: st.dataset.orbitSpeed,
      aIn: getComputedStyle(st).getPropertyValue("--sl-a-in").trim(),
      stage: (() => { const r = st.getBoundingClientRect(); return { top: Math.round(r.top), h: Math.round(r.height) }; })(),
      clipped: nodes.filter((n) => { const l = n.querySelector(".sl-orbit__node-label"); return l && l.scrollHeight > l.clientHeight + 1; }).length,
      hScroll: document.documentElement.scrollWidth > innerWidth + 1,
      infiniteAnims: st.getAnimations({ subtree: true }).filter((a) => a.effect.getTiming().iterations === Infinity).length,
    };
  });

  await page.screenshot({ path: path.join(OUT, name), fullPage: false });
  console.log(name, JSON.stringify(info), "errors:", errors.length ? errors.slice(0, 3) : "0");
  await page.close();
}

await shot("orbit-1a-static.png", { width: 1440, height: 900, run: false });
await shot("orbit-1a-running.png", { width: 1440, height: 900, run: true });
await shot("orbit-1b-full.png", { width: 1440, height: 1080, run: true });
await shot("orbit-narrow.png", { width: 390, height: 780, run: false });

await browser.close();
