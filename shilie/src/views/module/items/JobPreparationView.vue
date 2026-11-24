<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { messageOf } from "@/api";
import InterviewPanel from "./InterviewPanel.vue";
import { getJobs, type Lead, type Resume } from "./jobs-data";
const props = defineProps<{ initialLead?: string; optimizeOnly?: boolean }>();
const leads = ref<Lead[]>([]), resumes = ref<Resume[]>([]), busy = ref(false), error = ref(""), loaded = ref(false);
const invalidLead = computed(() => loaded.value && props.initialLead && !leads.value.some(row => row.id === props.initialLead));
async function load() {
  busy.value = true; error.value = "";
  try { const data = await getJobs(); leads.value = data.job_lead; resumes.value = data.resume_version; loaded.value = true; }
  catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function uploaded(row: Resume) { resumes.value = [row, ...resumes.value.filter(item => item.id !== row.id)]; }
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <p v-if="busy" role="status">正在读取岗位与简历…</p>
    <div v-else-if="error" class="business-panel glass"><p class="form-error" role="alert">{{ error }}</p><button type="button" class="secondary" @click="load">重试</button></div>
    <p v-else-if="!leads.length">还没有岗位。<RouterLink to="/module/job-flow">去流水线添加岗位</RouterLink></p>
    <template v-else>
      <p v-if="invalidLead" role="status">旧链接里的岗位不存在或已归档，请重新选择。没有自动改用其他岗位。</p>
      <InterviewPanel :leads="leads" :resumes="resumes" :initial-lead="invalidLead ? '' : (initialLead || '')"
        :optimize-only="optimizeOnly" @uploaded="uploaded" />
    </template>
  </section>
</template>
