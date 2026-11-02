import { loadPlaywright } from "./playwright-runtime.mjs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const { chromium } = await loadPlaywright();
const EDGE = "C:/Program Files (x86)/Microsoft/Edge/Application/msedge.exe";
const ROOT = fileURLToPath(new URL("../", import.meta.url));
const PAGE = path.join(ROOT, "output", "web", "node-apple-variants.html");
const OUT = path.join(ROOT, "output", "web", "node-apple-variants.png");

const browser = await chromium.launch({ executablePath: EDGE });
const page = await browser.newPage({
  viewport: { width: 1180, height: 1200 },
  deviceScaleFactor: 2,
});
const errors = [];
page.on("pageerror", (e) => errors.push(e.message));

await page.goto("file:///" + PAGE.replace(/\\/g, "/"), { waitUntil: "networkidle" });
await page.waitForTimeout(400);

const info = await page.evaluate(() => {
  const rows = [...document.querySelectorAll(".row")];
  return {
    rows: rows.length,
    heights: rows.map((r) => Math.round(r.getBoundingClientRect().height)),
    nodes: document.querySelectorAll(".node").length,
    docH: Math.round(document.documentElement.scrollHeight),
  };
});

await page.screenshot({ path: OUT, fullPage: true });
console.log(JSON.stringify(info), "errors:", errors.length ? errors : 0);
await browser.close();
