import { isDemo } from "@/api";

export interface SampleItem {
  id: string;
  title: string;
  subtitle: string;
  description: string;
  roles: { title: string; status: string; note: string }[];
}
const SAMPLE: Record<string, SampleItem[]> = isDemo ? {
  "job-flow": [
    { id: "pine-lab", title: "松屿实验室", subtitle: "2 个岗位 · 1 条跟进",
      description: "一个用来展示公司详情层级的虚构团队。这里只显示松屿实验室的资料。",
      roles: [
        { title: "AI 应用开发实习生", status: "已收藏", note: "关注工作流编排、知识检索与模型评测。" },
        { title: "平台研发实习生", status: "待跟进", note: "关注工具集成和内部工作台体验。" },
      ] },
    { id: "tidal-studio", title: "潮间工作室", subtitle: "1 个岗位 · 暂无跟进",
      description: "演示用的另一家公司，用来验证不同公司不会出现在同一详情页。",
      roles: [{ title: "产品工程师", status: "已收藏", note: "关注小团队工作效率与交互设计。" }] },
  ],
} : {};
export const samplesFor = (id: string) => SAMPLE[id] ?? [];
export const findSample = (moduleId: string, itemId: string) => samplesFor(moduleId).find((item) => item.id === itemId);
