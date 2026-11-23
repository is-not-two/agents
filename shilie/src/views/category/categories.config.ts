import { BriefcaseBusiness, BookOpen, Map, Bot, Settings } from "lucide-vue-next";
import type { Component } from "vue";

export interface ModuleInfo { id: string; name: string; desc?: string; parentModuleId?: string }
export interface Category { id: string; name: string; caption: string; icon: Component; tint: string; modules: ModuleInfo[] }

export const CATEGORIES: Category[] = [
  { id: "jobs", name: "求职", icon: BriefcaseBusiness, tint: "rose", caption: "从心仪岗位，到每一次面试。", modules: [
    { id: "job-flow", name: "求职流水线", desc: "按公司看岗位、面试与复盘" },
    { id: "jobs", name: "投递记录", desc: "按岗位跟进投递进度", parentModuleId: "job-flow" },
    { id: "resumes", name: "个人简历", desc: "上传简历、管理版本与查看正文", parentModuleId: "job-flow" },
    { id: "company-capabilities", name: "目标公司能力", desc: "整理招聘要求里的能力清单", parentModuleId: "job-flow" },
    { id: "job-insights", name: "岗位证据对照", desc: "对照已有经历和岗位要求", parentModuleId: "job-flow" },
    { id: "job-weekly", name: "求职周报", desc: "回看一周的投递与进展", parentModuleId: "job-flow" },
    { id: "job-prep", name: "预面试", desc: "选岗位和简历后开始练习", parentModuleId: "job-flow" },
    { id: "job-resume-ai", name: "AI 改简历", desc: "生成针对岗位的草稿，不覆盖原简历", parentModuleId: "job-flow" },
    { id: "job-tables", name: "单表管理", desc: "按记录类型管理求职资料", parentModuleId: "job-flow" },
  ] },
  { id: "knowledge", name: "知识", icon: BookOpen, tint: "apricot", caption: "保存读过、学过和想再找回的内容。", modules: [
    { id: "knowledge", name: "个人知识库", desc: "笔记、摘录和错题" },
    { id: "bookmarks", name: "网页收藏", desc: "文档、教程和待读网页" },
    { id: "documents", name: "技术文档检索", desc: "从技术资料里找答案" },
    { id: "learning", name: "到期复习", desc: "从复习卡回顾自己的薄弱点" },
    { id: "evaluation", name: "检索评测", desc: "向量基线与重排对照", parentModuleId: "documents" },
  ] },
  { id: "planning", name: "规划", icon: Map, tint: "mauve", caption: "把长期方向拆成眼前能做的事。", modules: [
    { id: "planning", name: "人生规划", desc: "安排主线和支线" },
    { id: "stages", name: "阶段记录", desc: "回看当前阶段的进展" },
    { id: "lessons", name: "谨记名单", desc: "记录踩过的坑" },
    { id: "self-traits", name: "人物特质", desc: "记录和修订自我观察", parentModuleId: "planning" },
    { id: "private", name: "私密区", desc: "加密愿望与日记", parentModuleId: "planning" },
  ] },
  { id: "agent", name: "助手", icon: Bot, tint: "peach", caption: "把重复的工作交给自己的 Agent。", modules: [
    { id: "agent-studio", name: "Agent 工作室", desc: "配置并运行助手" },
    { id: "task-queue", name: "任务队列", desc: "入队、跟进和处理失败的任务", parentModuleId: "agent-studio" },
    { id: "runs", name: "运行记录与审批", desc: "回看产物、核对待确认操作", parentModuleId: "agent-studio" },
    { id: "collaboration", name: "Agent 协作", desc: "交接白名单、计划和逐步审批", parentModuleId: "agent-studio" },
    { id: "agent-memory", name: "Agent 记忆", desc: "按 Agent 管理与确认记忆", parentModuleId: "agent-studio" },
    { id: "agent-capabilities", name: "技能与工具权限", desc: "管理技能、MCP 及工具授权", parentModuleId: "agent-studio" },
  ] },
  { id: "settings", name: "系统", icon: Settings, tint: "lilac", caption: "管理连接、数据和界面偏好。", modules: [
    { id: "notifications", name: "通知中心" },
    { id: "connections", name: "模型连接" },
    { id: "backup", name: "数据与备份" },
    { id: "appearance", name: "界面偏好" },
    { id: "diagnostics", name: "服务状态与诊断", parentModuleId: "connections" },
  ] },
];

export const findCategory = (id: string) => CATEGORIES.find((category) => category.id === id);
export const topLevelModules = (category: Category) => category.modules.filter(module => !module.parentModuleId);
export const childModules = (parentId: string) => CATEGORIES.flatMap(category =>
  category.modules.filter(module => module.parentModuleId === parentId));
export function findModule(id: string) {
  for (const category of CATEGORIES) {
    const module = category.modules.find((entry) => entry.id === id);
    if (module) return { category, module };
  }
}
