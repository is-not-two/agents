import type { Fields, Row } from "@/records";
import { applicationStatusChoices, canRecordReport } from "@/views/module/items/jobs-data";

// Never loaded by the production build. Reload discards simulated changes.
const leads: Row[] = [
  { id: "lead-1", kind: "job_lead", version: 1, data: { company: "松屿实验室", title: "AI 应用开发实习生", jd_text: "工作流编排、知识检索与模型评测。" } },
  { id: "lead-2", kind: "job_lead", version: 1, data: { company: "潮间工作室", title: "产品工程师", jd_text: "关注小团队工作效率与交互设计。" } },
];
const groups: Record<string, { kind: string; rows: Row[] }> = {
  "jobs/leads": { kind: "job_lead", rows: leads },
  "jobs/applications": { kind: "application", rows: [] },
  "jobs/reports": { kind: "interview_report", rows: [] },
  "jobs/resumes": { kind: "resume_version", rows: [] },
  "jobs/capabilities": { kind: "company_capability", rows: [] },
  "interview-prep": { kind: "interview_prep", rows: [] },
  plans: { kind: "plan", rows: [] },
  knowledge: { kind: "knowledge", rows: [{ id: "note-1", kind: "knowledge", version: 1,
    data: { title: "检索实验笔记", content: "先测干净基线，再单独比较一个变量。", tags: ["检索"] } }] },
  bookmarks: { kind: "bookmark", rows: [] }, lessons: { kind: "lesson", rows: [] },
};
const history = new Map<string, Row[]>();
const clone = <T>(value: T) => structuredClone(value);
function create(group: { kind: string; rows: Row[] }, data: Fields) {
  const row: Row = { id: crypto.randomUUID(), kind: group.kind, version: 1, data, updated_at: new Date().toISOString() };
  group.rows.unshift(row);
  history.set(row.id, [clone(row)]);
  return clone(row);
}
function update(row: Row, data: Fields, deleted = false) {
  const entries = history.get(row.id) || [clone(row)];
  row.version += 1; row.data = data; row.deleted = deleted; row.updated_at = new Date().toISOString();
  entries.unshift(clone(row)); history.set(row.id, entries);
  return clone(row);
}
const all = () => Object.values(groups).flatMap(group => group.rows);
const files = new Map<string, string>();
export async function demoRequest(path: string, options: RequestInit): Promise<unknown> {
  const url = new URL(path, "http://demo.invalid/");
  const key = url.pathname.slice(1), verb = options.method || "GET";
  const body = typeof options.body === "string" ? JSON.parse(options.body) : {};
  if (key === "trash") {
    const items = all().filter(row => row.deleted).map(row => ({ id: row.id, kind: row.kind, version: row.version,
      updated_at: row.updated_at, title: row.data.title || row.data.company || row.kind, subtitle: "" }));
    return { total: items.length, items, truncated: false };
  }
  if (key === "query/options") return { namespaces: [] };
  if (key === "query" && verb === "POST") {
    const hits = groups.knowledge.rows.filter(row => !row.deleted &&
      [row.data.title, row.data.content].join(" ").includes(body.query)).map(row => ({ title: row.data.title, content: row.data.content, source: "演示知识" }));
    return { hits, engine: "demo", answer: "", notes: ["只在本页模拟检索，不调用真实模型。"] };
  }
  if (key === "jobs/resumes/upload" && options.body instanceof FormData) {
    const file = options.body.get("file");
    if (!(file instanceof File) || !/\.(md|txt)$/i.test(file.name)) throw new Error("演示只读取 TXT/Markdown；正式接口支持 PDF/DOCX 等格式。");
    const row = create(groups["jobs/resumes"], { title: String(options.body.get("title") || file.name),
      file_name: file.name, document_id: "demo", parse_status: "parsed" });
    files.set(row.id, await file.text());
    return row;
  }
  const document = key.match(/^jobs\/resumes\/([^/]+)\/document$/);
  if (document) return { text: files.get(decodeURIComponent(document[1])) || "" };
  if (key === "jobs" && verb === "GET") return { counts: {}, funnel: null, due_application_ids: [],
    ...Object.fromEntries(Object.values(groups).filter(group => group.kind.startsWith("job_") || ["application", "resume_version", "interview_report", "company_capability"].includes(group.kind))
      .map(group => [group.kind, clone(group.rows.filter(row => !row.deleted))])) };
  const reportRoute = key.match(/^jobs\/applications\/([^/]+)\/reports$/);
  if (reportRoute && verb === "POST") {
    const app = groups["jobs/applications"].rows.find(row => row.id === reportRoute[1] && !row.deleted);
    if (!app || !canRecordReport(String(app.data.status))) throw new Error("请先将投递推进到面试中。");
    return create(groups["jobs/reports"], { ...body.data, application_id: reportRoute[1] });
  }
  if (key === "resume/templates") return [];
  if (key === "interview-prep/generate") {
    const lead = leads.find(row => row.id === body.lead_id);
    const resume = groups["jobs/resumes"].rows.find(row => row.id === body.resume_id);
    if (!lead || !resume) throw new Error("请选择岗位与简历。");
    return { title: "预面试 · " + lead.data.title, company: lead.data.company, role: lead.data.title,
      lead_id: lead.id, resume_id: resume.id, mode: body.mode, audio: {}, notes: "本地演示模板题，未调用模型。",
      turns: [{ q: "请用一个项目说明你如何验证工作结果。", answer: "", suggestion: "" }] };
  }
  if (["workflow-runs", "workflows"].includes(key)) return [];
  if (key.startsWith("records/")) {
    const [, id, action] = key.split("/");
    const row = all().find(item => item.id === decodeURIComponent(id));
    if (!row) throw new Error("演示记录不存在。");
    if (action === "history") return clone(history.get(row.id) || [row]);
    if (action === "restore") {
      const old = (history.get(row.id) || []).find(entry => entry.version === body.target_version && !entry.deleted);
      if (body.current_version !== row.version || !old) throw new Error("版本已变化或不存在。");
      return update(row, clone(old.data));
    }
    if (verb === "DELETE") {
      if (Number(url.searchParams.get("version")) !== row.version) throw new Error("版本已变化。");
      return update(row, row.data, true);
    }
  }
  const group = groups[key];
  if (group) {
    if (verb === "POST") {
      if (group.kind === "application" && !applicationStatusChoices().includes(body.data.status)) throw new Error("不支持此状态跳转。");
      return create(group, body.data);
    }
    return clone(group.rows.filter(row => Boolean(row.deleted) === (url.searchParams.get("trash") === "true")));
  }
  const [parent, id] = [key.slice(0, key.lastIndexOf("/")), key.slice(key.lastIndexOf("/") + 1)];
  const row = groups[parent]?.rows.find(item => item.id === decodeURIComponent(id) && !item.deleted);
  if (row) {
    if (verb === "PUT" || verb === "PATCH") {
      if (body.version !== row.version) throw new Error("版本已变化。");
      const data = verb === "PATCH" ? { ...row.data, ...body.data } : body.data;
      if (row.kind === "application" && !applicationStatusChoices(String(row.data.status)).includes(data.status))
        throw new Error("不支持此状态跳转。");
      return update(row, data);
    }
    return clone(row);
  }
  throw new Error("演示不调用真实服务器；这项操作需要连接单用户后端。");
}
