<script setup lang="ts">
import { computed, defineAsyncComponent } from "vue";
import { useRoute } from "vue-router";
import { ArrowLeft } from "lucide-vue-next";
import EmptyState from "@/components/EmptyState.vue";
import { specs } from "./items/record-specs";
const route = useRoute();
const parent = computed(() => "/module/" + encodeURIComponent(String(route.params.moduleId)));
const moduleId = computed(() => String(route.params.moduleId));
const Records = defineAsyncComponent(() => import("./items/RecordDetail.vue"));
const Company = defineAsyncComponent(() => import("./items/CompanyWorkspace.vue"));
</script>

<template>
  <div class="page-frame">
    <RouterLink class="back-link" :to="parent"><ArrowLeft :size="17" /> 返回模块列表</RouterLink>
    <Records v-if="specs[moduleId]" :key="route.fullPath" :module-id="moduleId" :id="String(route.params.itemId)"
      :spec="specs[moduleId]" :trash="route.query.trash === '1'" />
    <Company v-else-if="moduleId === 'job-flow'" :key="route.fullPath" :company="String(route.params.itemId)"
      :initial-lead="String(route.query.lead || '')" :initial-section="String(route.query.section || '')" />
    <EmptyState v-else title="找不到这个条目" description="此条目不存在，或这个模块尚未接入业务数据。" />
  </div>
</template>
