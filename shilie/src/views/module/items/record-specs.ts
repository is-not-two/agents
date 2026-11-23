export interface Field {
  key: string; label: string; type?: "text" | "url" | "long" | "lines" | "select" | "number";
  required?: boolean; max?: number; min?: number; options?: string[]; defaultValue?: string | number;
}
export interface RecordSpec {
  path: string; singular: string; fields: Field[];
}
export const specs: Record<string, RecordSpec> = {
  knowledge: { path: "knowledge", singular: "笔记", fields: [
    { key: "title", label: "标题", required: true, max: 160 },
    { key: "content", label: "正文", required: true, type: "long", max: 100000 },
    { key: "source", label: "来源", max: 1000 },
    { key: "tags", label: "标签（每行一个）", type: "lines" },
  ] },
  bookmarks: { path: "bookmarks", singular: "收藏", fields: [
    { key: "title", label: "标题", required: true, max: 160 },
    { key: "url", label: "网址", type: "url", required: true, max: 2000 },
    { key: "category", label: "分类", max: 24 },
    { key: "tags", label: "标签（每行一个）", type: "lines" },
    { key: "note", label: "备注", type: "long", max: 2000 },
  ] },
  lessons: { path: "lessons", singular: "教训", fields: [
    { key: "title", label: "标题", required: true, max: 160 },
    { key: "category", label: "分类", max: 20, required: true },
    { key: "content", label: "发生了什么", type: "long", max: 20000 },
    { key: "remedy", label: "以后如何避免", type: "long", max: 2000 },
  ] },
  "self-traits": { path: "traits", singular: "特质卡", fields: [
    { key: "title", label: "特点名称", required: true, max: 2000 },
    { key: "valence", label: "倾向", type: "select", options: ["待改进", "中性", "优势"], defaultValue: "待改进" },
    { key: "intensity", label: "强度", type: "number", min: 1, max: 5, defaultValue: 3, required: true },
    { key: "scene", label: "常见场景", type: "long", max: 4000 },
    { key: "note", label: "观察记录", type: "long", max: 20000 },
    { key: "status", label: "状态", type: "select", options: ["观察中", "已改善", "已归档"], defaultValue: "观察中" },
  ] },
  jobs: { path: "jobs/leads", singular: "岗位", fields: [
    { key: "company", label: "公司", required: true, max: 160 },
    { key: "title", label: "岗位名称", required: true, max: 160 },
    { key: "source_url", label: "招聘来源", type: "url", max: 2000 },
    { key: "jd_text", label: "招聘原文", type: "long", max: 50000 },
    { key: "notes", label: "备注", type: "long", max: 10000 },
  ] },
};
