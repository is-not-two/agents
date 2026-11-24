<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import { useRoute } from "vue-router";
import { childModules, findModule } from "@/views/category/categories.config";
import EmptyState from "@/components/EmptyState.vue";
import { specs } from "./items/record-specs";

const route = useRoute();
const found = computed(() => findModule(String(route.params.moduleId)));
const children = computed(() => childModules(found.value?.module.id || ""));
const JobFlow = defineAsyncComponent(() => import("./items/JobFlowView.vue"));
const Records = defineAsyncComponent(() => import("./items/RecordCollection.vue"));
const Documents = defineAsyncComponent(() => import("./items/DocumentsSearchView.vue"));
const Jobs = defineAsyncComponent(() => import("./items/JobsListView.vue"));
const Capabilities = defineAsyncComponent(() => import("./items/CompanyCapabilitiesView.vue"));
const Planning = defineAsyncComponent(() => import("./items/PlanningView.vue"));
const Connection = defineAsyncComponent(() => import("./items/ConnectionView.vue"));
const Appearance = defineAsyncComponent(() => import("./items/AppearanceView.vue"));
const Weekly = defineAsyncComponent(() => import("./items/WeeklyView.vue"));
const Notifications = defineAsyncComponent(() => import("./items/NotificationsView.vue"));
const Stages = defineAsyncComponent(() => import("./items/StagesView.vue"));
const Insights = defineAsyncComponent(() => import("./items/JobInsightsView.vue"));
const AgentStudio = defineAsyncComponent(() => import("./items/AgentStudioView.vue"));
const Resumes = defineAsyncComponent(() => import("./items/ResumePanel.vue"));
const Backup = defineAsyncComponent(() => import("./items/BackupView.vue"));
const Learning = defineAsyncComponent(() => import("./items/LearningView.vue"));
const Evaluation = defineAsyncComponent(() => import("./items/EvaluationView.vue"));
const Private = defineAsyncComponent(() => import("./items/PrivateView.vue"));
const TaskQueue = defineAsyncComponent(() => import("./items/TaskQueueView.vue"));
const RunHistory = defineAsyncComponent(() => import("./items/RunHistoryView.vue"));
const Collaboration = defineAsyncComponent(() => import("./items/CollaborationView.vue"));
const AgentMemory = defineAsyncComponent(() => import("./items/AgentMemoryView.vue"));
const AgentCapabilities = defineAsyncComponent(() => import("./items/AgentCapabilitiesView.vue"));
const MarkdownImport = defineAsyncComponent(() => import("./items/MarkdownImport.vue"));
const Diagnostics = defineAsyncComponent(() => import("./items/DiagnosticsView.vue"));
const JobPreparation = defineAsyncComponent(() => import("./items/JobPreparationView.vue"));
const jobTables = ["jobs", "resumes", "company-capabilities", "job-insights", "job-weekly"].map(id => findModule(id)!.module);
</script>

<template>
  <div class="page-frame">
    <template v-if="found">
      <header class="page-heading glass" :data-tint="found.category.tint">
        <p class="page-parent">{{ found.category.name }}</p>
        <h1>{{ found.module.name }}</h1><p v-if="found.module.desc">{{ found.module.desc }}</p>
      </header>
      <nav v-if="children.length && found.module.id !== 'job-flow'" class="business-actions" :aria-label="found.module.name + '内功能'">
        <RouterLink v-for="child in children" :key="child.id" class="secondary" :to="'/module/' + child.id">{{ child.name }}</RouterLink>
        <RouterLink v-if="found.module.id === 'agent-studio'" class="secondary" to="/module/task-queue?launch=now">即时运行</RouterLink>
      </nav>
      <JobFlow v-if="found.module.id === 'job-flow'" />
      <Documents v-else-if="found.module.id === 'documents'" />
      <Jobs v-else-if="found.module.id === 'jobs'" />
      <Capabilities v-else-if="found.module.id === 'company-capabilities'" />
      <Planning v-else-if="found.module.id === 'planning'" />
      <Connection v-else-if="found.module.id === 'connections'" />
      <Appearance v-else-if="found.module.id === 'appearance'" />
      <Weekly v-else-if="found.module.id === 'job-weekly'" />
      <Notifications v-else-if="found.module.id === 'notifications'" />
      <Stages v-else-if="found.module.id === 'stages'" />
      <Insights v-else-if="found.module.id === 'job-insights'" />
      <AgentStudio v-else-if="found.module.id === 'agent-studio'" />
      <Resumes v-else-if="found.module.id === 'resumes'" :key="route.fullPath"
        :initial-resume="typeof route.query.resume === 'string' ? route.query.resume : undefined" />
      <JobPreparation v-else-if="found.module.id === 'job-prep' || found.module.id === 'job-resume-ai'" :key="route.fullPath"
        :initial-lead="typeof route.query.lead === 'string' ? route.query.lead : undefined" :optimize-only="found.module.id === 'job-resume-ai'" />
      <nav v-else-if="found.module.id === 'job-tables'" class="business-actions" aria-label="求职单表入口">
        <RouterLink v-for="entry in jobTables" :key="entry.id" class="secondary" :to="'/module/' + entry.id">{{ entry.name }}</RouterLink>
      </nav>
      <Backup v-else-if="found.module.id === 'backup'" />
      <Learning v-else-if="found.module.id === 'learning'" />
      <Evaluation v-else-if="found.module.id === 'evaluation'" />
      <Private v-else-if="found.module.id === 'private'" />
      <TaskQueue v-else-if="found.module.id === 'task-queue'" />
      <RunHistory v-else-if="found.module.id === 'runs'" />
      <Collaboration v-else-if="found.module.id === 'collaboration'" />
      <AgentMemory v-else-if="found.module.id === 'agent-memory'" />
      <AgentCapabilities v-else-if="found.module.id === 'agent-capabilities'" />
      <Diagnostics v-else-if="found.module.id === 'diagnostics'" />
      <template v-else-if="specs[found.module.id]">
        <MarkdownImport v-if="found.module.id === 'knowledge'" />
        <Records :module-id="found.module.id" :spec="specs[found.module.id]" />
      </template>
      <EmptyState v-else title="业务功能尚未接入" description="这个模块的入口已就绪。本阶段只验证导航，不展示虚假的业务操作。" />
    </template>
    <EmptyState v-else title="找不到这个模块" description="可以返回工作台重新选择。"><RouterLink to="/workspace">回到工作台</RouterLink></EmptyState>
  </div>
</template>
