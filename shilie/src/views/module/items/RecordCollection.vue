<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { ArrowUpRight, Plus } from "lucide-vue-next";
import { messageOf, request } from "@/api";
import { dateText, type Row } from "@/records";
import EmptyState from "@/components/EmptyState.vue";
import RecordEditor from "./RecordEditor.vue";
import type { RecordSpec } from "./record-specs";

const props = defineProps<{ moduleId: string; spec: RecordSpec }>();
const rows = ref<Row[]>([]), query = ref(""), loading = ref(true), error = ref("");
const trash = ref(false), creating = ref(false);
const filtered = computed(() => rows.value.filter(row =>
  [row.data.title, row.data.company, row.data.category, row.data.tags].join(" ").toLowerCase().includes(query.value.trim().toLowerCase())));
async function load() {
  loading.value = true; error.value = "";
  try { rows.value = await request<Row[]>(props.spec.path + "?trash=" + trash.value); }
  catch (reason) { error.value = messageOf(reason); }
  finally { loading.value = false; }
}
function created(row: Row) { rows.value = [row, ...rows.value]; creating.value = false; }
onMounted(load);
</script>

<template>
  <section class="business-stack">
    <div class="business-toolbar">
      <label>查找{{ spec.singular }}<input type="search" v-model="query" placeholder="输入关键词" /></label>
      <div class="business-actions">
        <button v-if="!trash" class="primary" type="button" @click="creating = !creating"><Plus :size="16" /> 新建{{ spec.singular }}</button>
        <button class="secondary" type="button" @click="trash = !trash; creating = false; load()">{{ trash ? "返回有效记录" : "回收站" }}</button>
      </div>
    </div>
    <RecordEditor v-if="creating" :spec="spec" @saved="created" @cancel="creating = false" />
    <p v-if="loading" role="status">正在读取…</p>
    <div v-else-if="error" class="business-panel glass"><p class="form-error" role="alert">{{ error }}</p><button class="secondary" @click="load">重试</button></div>
    <div v-else-if="filtered.length" class="module-grid">
      <RouterLink v-for="row in filtered" :key="row.id" class="module-card glass"
        :to="{ name: 'item-detail', params: { moduleId, itemId: row.id }, query: trash ? { trash: '1' } : {} }">
        <div><h3>{{ row.data.title || spec.singular }}</h3><p>{{ row.data.company || row.data.category || dateText(row.updated_at) }}</p></div>
        <ArrowUpRight :size="18" aria-hidden="true" />
      </RouterLink>
    </div>
    <EmptyState v-else :title="query ? '没有匹配的记录' : trash ? '回收站为空' : '还没有' + spec.singular"
      :description="query ? '换个关键词试试。' : trash ? '归档的记录会在这里显示。' : '点上方新建按钮添加第一条。'" />
  </section>
</template>
