import { request, send } from "@/api";

export type Fields = Record<string, unknown>;
export interface Row<T extends Fields = Fields> {
  id: string;
  kind: string;
  version: number;
  data: T;
  updated_at?: string;
  deleted?: boolean;
}
export const segment = encodeURIComponent;
export const saveRecord = <T extends Fields>(path: string, data: T, row?: Row) =>
  row ? send<Row<T>>(path + "/" + segment(row.id), { data, version: row.version }, "PUT")
    : send<Row<T>>(path, { data });
export const archiveRecord = (row: Row) =>
  request<Row>("records/" + segment(row.id) + "?version=" + row.version, { method: "DELETE" });
export const getHistory = (row: Row) => request<Row[]>("records/" + segment(row.id) + "/history");
export const restoreRecord = (row: Row, target: number) =>
  send<Row>("records/" + segment(row.id) + "/restore", { current_version: row.version, target_version: target });
export const lines = (value: string) => value.split(/\r?\n/).map(item => item.trim()).filter(Boolean);
export const dateText = (value: unknown) => typeof value === "string" && value
  ? new Date(value).toLocaleString("zh-CN", { hour12: false }) : "—";
export function publicLink(value: unknown) {
  try {
    const url = new URL(String(value || ""));
    return ["http:", "https:"].includes(url.protocol) && !url.username && !url.password ? url.href : "";
  } catch { return ""; }
}
