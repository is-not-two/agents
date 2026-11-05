import { loadPlaywright } from "./playwright-runtime.mjs";
import fs from "node:fs"; import path from "node:path";
const { chromium } = await loadPlaywright();
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const STATIC = "E:/project/agents/rag-tech-doc-retriever/src/rag_tech_retriever/api/static/shilie";
const API = {session:{required:false,authenticated:true},knowledge:[],plans:[],status:{},"stage-summary":{records:[],updated_at:""},"query/options":{namespaces:[],default:null},agents:[],workflows:[],"workflow-runs":[]};
const b = await chromium.launch({ executablePath: EDGE });
const ctx = await b.newContext({ viewport: { width: 1440, height: 900 }, bypassCSP: true });
const p = await ctx.newPage();
await p.route("**/*", async r => {
  const u = new URL(r.request().url()); const pt = u.pathname;
  if (pt.startsWith("/api/")) { const k = pt.replace("/api/",""); return r.fulfill({status:200,contentType:"application/json",body:JSON.stringify(API[k]??[])}); }
  if (pt.startsWith("/static/shilie/")) { const f = path.join(STATIC, pt.replace("/static/shilie/","")); if (fs.existsSync(f)) { const m={".js":"text/javascript; charset=utf-8",".css":"text/css; charset=utf-8",".html":"text/html; charset=utf-8",".svg":"image/svg+xml",".webp":"image/webp",".png":"image/png"}; return r.fulfill({status:200,contentType:m[path.extname(f)]||"application/octet-stream",body:fs.readFileSync(f)}); } }
  if (pt==="/") return r.fulfill({status:200,contentType:"text/html; charset=utf-8",body:fs.readFileSync(path.join(STATIC,"index.html"))});
  return r.fulfill({ status: 204, body: "" });
});
await p.goto("http://127.0.0.1:8899/", { waitUntil: "networkidle" });
await p.waitForTimeout(1500);
const d = await p.evaluate(() => {
  const q = s => document.querySelector(s);
  const rect = e => e ? { w: Math.round(e.getBoundingClientRect().width), h: Math.round(e.getBoundingClientRect().height) } : null;
  const orbit = q(".sl-orbit");
  const wrap = q(".home-orbit-wrap");
  const start = q(".home-start");
  return {
    hasStart: !!start, startRect: rect(start),
    wrapRect: rect(wrap), wrapType: wrap ? getComputedStyle(wrap).containerType : null,
    orbitDisplay: orbit ? getComputedStyle(orbit).display : null, orbitRect: rect(orbit),
    hubLabel: q(".sl-orbit__hub-label")?.textContent,
    listDisplay: q(".sl-orbit-list") ? getComputedStyle(q(".sl-orbit-list")).display : null,
    v: q('script[src*="views.js"]')?.getAttribute('src'),
  };
});
console.log(JSON.stringify(d, null, 1));
await b.close();
