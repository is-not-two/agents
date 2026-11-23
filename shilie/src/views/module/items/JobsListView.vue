<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { messageOf } from "@/api";
import { dateText } from "@/records";
import { getJobs, labels, type Overview } from "./jobs-data";
import RecordCollection from "./RecordCollection.vue";
import { specs } from "./record-specs";
const info = ref<Overview>(), status = ref("all"), query = ref(""), error = ref(""), manage = ref(false), busy = ref(true);
const leads = computed(() => new Map((info.value?.job_lead || []).map(row => [row.id, row])));
const rows = computed(() => (info.value?.application || []).filter(row => {
  const hit = leads.value.get(row.data.lead_id)?.data;
  const matches = [row.data.title, hit?.company, hit?.title].join(" ").toLowerCase().includes(query.value.trim().toLowerCase());
  return matches && (status.value === "all" || (status.value === "due" ? info.value?.due_application_ids.includes(row.id) : row.data.status === status.value));
}));
async function load() { busy.value = true; error.value = "";
  try { info.value = await getJobs(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <div class="business-actions"><button class="secondary" type="button" @click="manage = !manage">{{ manage ? "收起岗位管理" : "岗位管理与回收站" }}</button>
      <RouterLink class="secondary" to="/module/job-flow">按公司进入流水线</RouterLink></div>
    <RecordCollection v-if="manage" module-id="jobs" :spec="specs.jobs" />
    <div v-if="info?.funnel" class="business-panel glass"><h2>求职漏斗</h2>
      <div class="business-actions"><span>收藏 {{ info.funnel.stages.collected }}</span><span>投递 {{ info.funnel.stages.applied }}</span>
        <span>进面 {{ info.funnel.stages.interviewed }}</span><span>Offer {{ info.funnel.stages.offered }}</span></div></div>
    <div class="business-form glass business-columns"><label>搜索公司或岗位<input v-model="query" type="search" /></label>
      <label>投递状态<select v-model="status"><option value="all">全部</option><option value="due">待跟进</option>
        <option v-for="[key,label] in Object.entries(labels)" :key="key" :value="key">{{ label }}</option></select></label></div>
    <p v-if="busy" role="status">正在读取投递…</p><p v-else-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-else-if="!rows.length">没有符合条件的投递记录。可在公司流水线选择岗位并记录投递。</p>
    <article v-for="row in rows" :key="row.id" class="business-panel glass">
      <h3>{{ row.data.title || leads.get(row.data.lead_id)?.data.title || '投递' }}</h3>
      <p>{{ leads.get(row.data.lead_id)?.data.company }} · {{ labels[row.data.status] || row.data.status }}</p>
      <p>下次跟进：{{ dateText(row.data.follow_up_at) }}</p>
      <RouterLink v-if="leads.get(row.data.lead_id)" class="secondary"
        :to="{ name: 'item-detail', params: { moduleId: 'job-flow', itemId: leads.get(row.data.lead_id)!.data.company }, query: { lead: row.data.lead_id } }">进入岗位处理投递</RouterLink>
    </article>
  </section>
</template>
