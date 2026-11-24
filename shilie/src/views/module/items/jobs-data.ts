import type { Fields, Row } from "@/records";
import { request } from "@/api";
export type Lead = Row<Fields & { title: string; company: string; jd_text: string; source_url?: string; notes?: string }>;
export type Resume = Row<Fields & { title: string; document_id?: string; file_name?: string; parse_status?: string; highlights?: string[] }>;
export type Application = Row<Fields & { title: string; lead_id: string; resume_version_id: string; status: string; channel?: string; applied_at?: string; follow_up_at?: string; notes?: string }>;
export type Question = { q: string; answer_summary: string; rating: number };
export type Report = Row<Fields & { title: string; application_id: string; round: number; questions: Question[]; weak_points: string[]; next_actions: string[]; interviewed_at?: string; notes?: string }>;
export type Overview = { job_lead: Lead[]; application: Application[]; resume_version: Resume[]; interview_report: Report[]; due_application_ids: string[]; funnel: { stages: Record<string, number>; weekly?: { applications: number; target: number } } | null };
export const getJobs = () => request<Overview>("jobs");
export const labels: Record<string, string> = { collected: "已收藏", applied: "已投递", following: "跟进中", interviewing: "面试中", offered: "已获 Offer", rejected: "已结束" };
// Mirror the jobs API; the server remains authoritative for versions and transitions.
const transitions: Record<string, readonly string[]> = {
  collected: ["applied", "rejected"], applied: ["following", "interviewing", "rejected"],
  following: ["interviewing", "rejected"], interviewing: ["offered", "rejected"], offered: [], rejected: [],
};
export const applicationStatusChoices = (status = "collected") => [status, ...(transitions[status] || [])];
export const canRecordReport = (status: string) => ["interviewing", "offered", "rejected"].includes(status);
export const timeLocal = (stamp?: string) => {
  if (!stamp) return "";
  const time = new Date(stamp);
  return Number.isNaN(time.getTime()) ? "" : new Date(time.getTime() - time.getTimezoneOffset() * 60000).toISOString().slice(0, 16);
};
export const timeISO = (stamp: string) => stamp ? new Date(stamp).toISOString() : "";
