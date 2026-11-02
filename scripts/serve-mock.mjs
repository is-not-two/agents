// 预览用静态服务器：API 全部 mock，页面与动画都是真实代码。
import http from "node:http";
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const ROOT = fileURLToPath(new URL("../", import.meta.url));
const STATIC = path.join(ROOT, "src", "rag_tech_retriever", "api", "static", "shilie");
const PORT = 8899;

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".css": "text/css; charset=utf-8",
  ".js": "text/javascript; charset=utf-8",
  ".mjs": "text/javascript; charset=utf-8",
  ".json": "application/json; charset=utf-8",
  ".svg": "image/svg+xml",
  ".png": "image/png",
  ".webp": "image/webp",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".woff2": "font/woff2",
};

const API = {
  session: { required: false, authenticated: true },
  knowledge: [
    { id: "n1", data: { title: "RAG 检索链路梳理", module: "knowledge" } },
    { id: "n2", data: { title: "bge 模型选型对比", module: "knowledge" } },
    { id: "n3", data: { title: "pgvector 索引实验", module: "knowledge" } },
  ],
  plans: [
    { id: "p1", title: "完成 V2 评测", plan: "本周" },
    { id: "p2", title: "整理面试材料", plan: "本月" },
  ],
  status: { ok: true },
  "stage-summary": { records: [{ id: "s1", name: "V1 基线", at: "2026-10-20" }], updated_at: "2026-10-20" },
  "query/options": { namespaces: [{ id: "aihuoke", name: "AIhuoke" }], default: "aihuoke" },
  agents: [],
  workflows: [],
  "workflow-runs": [],
  runs: [],
  lessons: [],
  jobs: [],
  notifications: [],
};

const server = http.createServer((req, res) => {
  const url = new URL(req.url, `http://127.0.0.1:${PORT}`);
  let p = url.pathname;

  if (p.startsWith("/api/")) {
    const key = p.replace("/api/", "").replace(/\/$/, "");
    const body = API[key] ?? API[key.split("/")[0]] ?? [];
    res.writeHead(200, { "content-type": "application/json; charset=utf-8" });
    res.end(JSON.stringify(body));
    return;
  }

  if (p === "/" || p === "/index.html") {
    const f = path.join(STATIC, "index.html");
    res.writeHead(200, { "content-type": MIME[".html"] });
    res.end(fs.readFileSync(f));
    return;
  }

  if (p.startsWith("/static/shilie/")) {
    const f = path.join(STATIC, p.replace("/static/shilie/", ""));
    if (fs.existsSync(f) && fs.statSync(f).isFile()) {
      res.writeHead(200, { "content-type": MIME[path.extname(f)] || "application/octet-stream" });
      res.end(fs.readFileSync(f));
      return;
    }
  }

  if (p.startsWith("/static/")) {
    const f = path.join(ROOT, "src", "rag_tech_retriever", "api", p.replace("/static/", "static/"));
    if (fs.existsSync(f) && fs.statSync(f).isFile()) {
      res.writeHead(200, { "content-type": MIME[path.extname(f)] || "application/octet-stream" });
      res.end(fs.readFileSync(f));
      return;
    }
  }

  res.writeHead(204);
  res.end();
});

server.listen(PORT, "127.0.0.1", () => {
  console.log(`preview on http://127.0.0.1:${PORT}`);
});
