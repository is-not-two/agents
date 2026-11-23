export const isDemo = import.meta.env.MODE === "demo";

export interface Session {
  required: boolean;
  authenticated: boolean;
  account_login: boolean;
}

export async function request<T>(path: string, options: RequestInit = {}): Promise<T> {
  if (isDemo) {
    const { demoRequest } = await import("./demo-data");
    return await demoRequest(path, options) as T;
  }
  const headers = new Headers(options.headers);
  headers.set("Accept", "application/json");
  if (typeof options.body === "string" && !headers.has("Content-Type")) headers.set("Content-Type", "application/json");
  const response = await fetch("/api/" + path, {
    credentials: "same-origin",
    cache: "no-store",
    ...options,
    headers,
  });
  const body = await response.json().catch(() => null);
  if (!response.ok || body === null) {
    const detail = typeof body?.detail === "string" ? body.detail : "";
    throw new Error(detail || (response.ok ? "服务器没有返回有效数据" : "请求失败（" + response.status + "）"));
  }
  return body as T;
}

export function send<T>(path: string, data: unknown, method = "POST") {
  return request<T>(path, { method, body: JSON.stringify(data) });
}
export async function requestText(path: string): Promise<string> {
  if (isDemo) return request<string>(path);
  const response = await fetch("/api/" + path, { credentials: "same-origin", cache: "no-store" });
  const body = await response.text();
  if (!response.ok) {
    let detail: unknown;
    try { detail = JSON.parse(body)?.detail; } catch { /* upstream may not return JSON */ }
    throw new Error(typeof detail === "string" ? detail : "请求失败（" + response.status + "）");
  }
  return body;
}
export const messageOf = (error: unknown) => error instanceof Error ? error.message : "操作失败，请重试";
