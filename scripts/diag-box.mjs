import { loadPlaywright } from "./playwright-runtime.mjs";
const { chromium } = await loadPlaywright();
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const b = await chromium.launch({ executablePath: EDGE });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 } });
const p = await ctx.newPage();
await p.goto("http://127.0.0.1:8899/", { waitUntil: "networkidle" });
await p.waitForTimeout(1000);
const d = await p.evaluate(() => {
  const slot = document.querySelector(".sl-orbit__slot");
  const cs = getComputedStyle(slot);
  const probe = document.createElement("div");
  probe.style.cssText = "position:absolute;width:calc(170px * sin(30deg));height:calc(170px * cos(30deg));";
  document.body.appendChild(probe);
  const pr = probe.getBoundingClientRect();
  const out = {
    ua: navigator.userAgent.slice(0, 90),
    supportsSin: CSS.supports("width", "calc(10px * sin(30deg))"),
    probeW: Math.round(pr.width), probeH: Math.round(pr.height),
    slotTransform: cs.transform,
    slotTh: cs.getPropertyValue("--sl-th"),
    slotD: cs.getPropertyValue("--sl-d"),
    nodeScale: getComputedStyle(slot.querySelector(".sl-orbit__node")).scale,
    nodeOpacity: getComputedStyle(slot.querySelector(".sl-orbit__node")).opacity,
    nodeRect: (() => { const r = slot.querySelector(".sl-orbit__node").getBoundingClientRect(); return { x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width) }; })(),
  };
  probe.remove();
  return out;
});
console.log(JSON.stringify(d, null, 1));
await b.close();
