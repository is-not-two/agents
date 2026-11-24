<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ArrowUpRight, Building2 } from "lucide-vue-next";
import { isDemo, messageOf, request } from "@/api";
import EmptyState from "@/components/EmptyState.vue";
import RecordEditor from "./RecordEditor.vue";
import { childModules } from "@/views/category/categories.config";
import { specs } from "./record-specs";
import type { Lead } from "./jobs-data";
import type { Row } from "@/records";
const rows = ref<Lead[]>([]), error = ref(""), busy = ref(true), creating = ref(false);
const sections = childModules("job-flow");
const query = ref("");
const companies = computed(() => {
  const groups = new Map<string, number>();
  for (const row of rows.value) groups.set(row.data.company, (groups.get(row.data.company) || 0) + 1);
  return [...groups].filter(([name]) => name.toLowerCase().includes(query.value.trim().toLowerCase()));
});
async function load() {
  busy.value = true; error.value = "";
  try { rows.value = await request<Lead[]>("jobs/leads"); }
  catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function created(row: Row) { creating.value = false; rows.value = [row as Lead, ...rows.value]; }
onMounted(load);
</script>

<template>
  <section class="business-stack">
    <nav class="business-actions" aria-label="流水线内功能">
      <RouterLink v-for="section in sections" :key="section.id" class="secondary" :to="'/module/' + section.id">{{ section.name }}</RouterLink>
    </nav>
    <div class="business-toolbar"><label>查找公司<input v-model="query" type="search" placeholder="输入公司名称" /></label>
      <button class="primary" type="button" @click="creating = !creating">添加公司和岗位</button></div>
    <RecordEditor v-if="creating" :spec="specs.jobs" @saved="created" @cancel="creating = false" />
    <p v-if="busy" role="status">正在读取公司…</p>
    <div v-else-if="error"><p class="form-error" role="alert">{{ error }}</p><button class="secondary" @click="load">重试</button></div>
    <template v-else-if="companies.length">
      <div class="section-line"><h2>公司列表</h2><span v-if="isDemo">演示数据，刷新后恢复初始状态</span></div>
      <div class="module-grid">
        <RouterLink v-for="[name, count] in companies" :key="name" class="module-card glass company-card"
          :to="{ name: 'item-detail', params: { moduleId: 'job-flow', itemId: name } }">
          <Building2 :size="23" aria-hidden="true" /><div><h3>{{ name }}</h3><p>{{ count }} 个岗位</p></div><ArrowUpRight :size="18" aria-hidden="true" />
        </RouterLink>
      </div>
    </template>
    <EmptyState v-else :title="query ? '没有匹配的公司' : '还没有公司'"
      description="可以新建一个岗位，公司会自动出现在这里。" />
  </section>
</template>
