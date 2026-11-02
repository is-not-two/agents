/* Test-only runtime lookup; no frontend dependency or build step is introduced. */
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import { pathToFileURL } from "node:url";

export async function loadPlaywright() {
  if (process.env.PLAYWRIGHT_MODULE) return import(pathToFileURL(path.resolve(process.env.PLAYWRIGHT_MODULE)).href);
  try { return await import("playwright"); } catch (error) {
    if (error.code !== "ERR_MODULE_NOT_FOUND") throw error;
  }
  const cache = process.platform === "win32" ? path.join(process.env.LOCALAPPDATA || os.homedir(), "npm-cache", "_npx") : path.join(os.homedir(), ".npm", "_npx");
  if (fs.existsSync(cache)) {
    for (const name of fs.readdirSync(cache).sort().slice(0, 32)) {
      const entry = path.join(cache, name, "node_modules", "playwright", "index.mjs");
      if (fs.existsSync(entry)) return import(pathToFileURL(entry).href);
    }
  }
  throw Error("Playwright test runtime missing; set PLAYWRIGHT_MODULE or cache @playwright/cli@0.1.22");
}
