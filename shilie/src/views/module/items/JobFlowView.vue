<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import {
  ArrowRight, BriefcaseBusiness, Building2, CheckCircle2, ChevronRight,
  FileText, GitBranch, Lightbulb, Plus, Send, Sparkles, Target, Trophy, X,
} from "lucide-vue-next";
import { messageOf, request } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import RecordEditor from "./RecordEditor.vue";
import { specs } from "./record-specs";
import type { Overview, Lead } from "./jobs-data";
import type { Row } from "@/records";

const router = useRouter();
const data = ref<Overview | null>(null);
const error = ref("");
const busy = ref(true);
const creating = ref(false);
const activeNode = ref<string | null>(null);

async function load() {
  busy.value = true; error.value = "";
  try { data.value = await request<Overview>("jobs"); }
  catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function created(row: Row) {
  creating.value = false;
  if (data.value) data.value = { ...data.value, job_lead: [row as Lead, ...data.value.job_lead] };
  activeNode.value = null;
}
onMounted(load);

const leads = computed(() => data.value?.job_lead ?? []);
const apps = computed(() => data.value?.application ?? []);
const resumes = computed(() => data.value?.resume_version ?? []);
const reports = computed(() => data.value?.interview_report ?? []);
const capabilities = computed(() => (data.value as unknown as { company_capability?: Row[] })?.company_capability ?? []);
const companies = computed(() => new Set(leads.value.map(l => l.data.company)).size);

type Stage = { id: string; label: string; sub: string; count: number; icon: typeof BriefcaseBusiness; tone: string };
const stages = computed<Stage[]>(() => [
  { id: "collected", label: "收集岗位", sub: `${companies.value} 家公司 · ${leads.value.length} 个岗位`, count: leads.value.length, icon: Target, tone: "rose" },
  { id: "applied", label: "投递", sub: `${apps.value.length} 份投递记录`, count: apps.value.length, icon: Send, tone: "amber" },
  { id: "interviewed", label: "面试", sub: `${reports.value.length} 场复盘`, count: reports.value.length, icon: BriefcaseBusiness, tone: "violet" },
  { id: "offered", label: "Offer", sub: "待解锁", count: 0, icon: Trophy, tone: "green" },
]);

const links = computed(() => [
  { id: "company-capability", label: "公司能力清单", sub: `${capabilities.value.length} 条`, icon: Building2, to: "/module/company-capabilities", tone: "rose" },
  { id: "job-insights", label: "岗位证据对照", sub: "经历 × 要求", icon: GitBranch, to: "/module/job-insights", tone: "violet" },
  { id: "resumes", label: "简历版本", sub: `${resumes.value.length} 份`, icon: FileText, to: "/module/resumes", tone: "amber" },
  { id: "job-prep", label: "面试准备", sub: "模拟练习", icon: Sparkles, to: "/module/job-prep", tone: "green" },
  { id: "ai-resume", label: "AI 改简历", sub: "针对岗位起草", icon: Lightbulb, to: "/module/job-resume-ai", tone: "rose" },
  { id: "job-weekly", label: "求职周报", sub: "每周回看", icon: CheckCircle2, to: "/module/job-weekly", tone: "violet" },
]);

const detail = computed(() => {
  const id = activeNode.value;
  if (!id) return null;
  const stage = stages.value.find(s => s.id === id);
  if (stage) {
    if (id === "collected") return { title: stage.label, rows: leads.value, moduleId: "job-flow", kind: "岗位意向" };
    if (id === "applied") return { title: stage.label, rows: apps.value, moduleId: "jobs", kind: "投递记录" };
    if (id === "interviewed") return { title: stage.label, rows: reports.value, moduleId: "job-prep", kind: "面试复盘" };
    return { title: stage.label, rows: [], moduleId: "jobs", kind: "Offer 记录" };
  }
  const link = links.value.find(l => l.id === id);
  if (link) return { title: link.label, rows: [], moduleId: link.to.replace("/module/", ""), kind: "关联模块", to: link.to };
  return null;
});

function rowTitle(row: Row): string {
  const d = row.data as Record<string, unknown>;
  return String(d.title || d.company || d.name || "未命名");
}
function rowSub(row: Row): string {
  const d = row.data as Record<string, unknown>;
  return String(d.company || d.status || "");
}
function openDetail(id: string) { activeNode.value = activeNode.value === id ? null : id; }
function goModule(id: string) { router.push("/module/" + id); activeNode.value = null; }
</script>

<template>
  <section class="business-stack job-pipeline">
    <nav class="business-actions" aria-label="流水线内功能">
      <RouterLink v-for="section in [
        { id: 'jobs', name: '投递记录' }, { id: 'resumes', name: '个人简历' },
        { id: 'company-capabilities', name: '公司能力' }, { id: 'job-insights', name: '证据对照' },
        { id: 'job-weekly', name: '求职周报' }, { id: 'job-prep', name: '预面试' }]"
        :key="section.id" class="secondary" :to="'/module/' + section.id">{{ section.name }}</RouterLink>
    </nav>

    <div class="pipeline-toolbar">
      <div>
        <h2 class="pipeline-title">求职流水线</h2>
        <p class="pipeline-sub">从心仪岗位到每一次面试，点击节点查看详情</p>
      </div>
      <button class="primary" type="button" @click="creating = !creating"><Plus :size="15" />添加公司和岗位</button>
    </div>
    <RecordEditor v-if="creating" :spec="specs.jobs" @saved="created" @cancel="creating = false" />

    <p v-if="busy" role="status">正在读取流水线…</p>
    <div v-else-if="error"><p class="form-error" role="alert">{{ error }}</p><button class="secondary" @click="load">重试</button></div>

    <template v-else>
      <div class="pipeline-canvas glass">
        <div class="pipeline-heading"><span class="pipeline-kicker">主流程</span><span class="pipeline-hint">实线表示阶段流转</span></div>

        <div class="stage-track">
          <template v-for="(stage, i) in stages" :key="stage.id">
            <button class="stage-node" :class="['tone-' + stage.tone, { active: activeNode === stage.id, empty: stage.count === 0 }]"
              type="button" :aria-expanded="activeNode === stage.id" @click="openDetail(stage.id)">
              <span class="node-icon"><component :is="stage.icon" :size="21" aria-hidden="true" /></span>
              <span class="node-body"><strong>{{ stage.label }}</strong><small>{{ stage.sub }}</small></span>
              <span class="node-count">{{ stage.count }}</span>
            </button>
            <svg v-if="i < stages.length - 1" class="stage-arrow" viewBox="0 0 46 20" aria-hidden="true" preserveAspectRatio="none">
              <path d="M1 10 H38 M32 5 L38 10 L32 15" fill="none" stroke="currentColor" stroke-width="1.8"
                stroke-linecap="round" stroke-linejoin="round" />
            </svg>
          </template>
        </div>

        <div class="pipeline-divider"><span>关联模块</span></div>
        <p class="pipeline-hint link-hint">虚线表示阶段关联的资源与工具</p>

        <div class="link-grid">
          <button v-for="link in links" :key="link.id" class="link-node"
            :class="['tone-' + link.tone, { active: activeNode === link.id }]" type="button"
            :aria-expanded="activeNode === link.id" @click="openDetail(link.id)">
            <span class="link-icon"><component :is="link.icon" :size="17" aria-hidden="true" /></span>
            <span class="link-text"><strong>{{ link.label }}</strong><small>{{ link.sub }}</small></span>
            <ChevronRight :size="15" class="link-chevron" aria-hidden="true" />
          </button>
        </div>
      </div>

      <aside v-if="detail" class="pipeline-detail glass" :aria-label="detail.title + '详情'">
        <header class="detail-head">
          <div><p class="detail-kicker">{{ detail.kind }}</p><h3>{{ detail.title }}</h3></div>
          <button class="icon-button" type="button" aria-label="关闭详情" @click="activeNode = null"><X :size="17" /></button>
        </header>

        <template v-if="detail.rows.length">
          <ul class="detail-list">
            <li v-for="row in detail.rows" :key="row.id">
              <div><strong>{{ rowTitle(row) }}</strong><small v-if="rowSub(row)">{{ rowSub(row) }}</small></div>
              <span class="row-version">v{{ row.version }}</span>
            </li>
          </ul>
        </template>
        <EmptyState v-else-if="detail.to" :title="detail.title" description="点击进入这个模块查看详情与创建记录。">
          <button class="primary" type="button" @click="goModule(detail.moduleId)">打开模块 <ArrowRight :size="14" /></button>
        </EmptyState>
        <EmptyState v-else :title="`还没有${detail.kind}`" description="从上方流水线节点或关联模块开始创建。">
          <button class="primary" type="button" @click="goModule(detail.moduleId)">去创建 <ArrowRight :size="14" /></button>
        </EmptyState>
      </aside>

      <p v-if="!leads.length && !apps.length" role="status" class="pipeline-empty-hint">
        流水线还是空的。点击「添加公司和岗位」开始，或点击任意节点了解它的用途。
      </p>
    </template>
  </section>
</template>
