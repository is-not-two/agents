<script setup lang="ts">
import { onMounted, ref } from "vue";
import { messageOf, request } from "@/api";
import { dateText, getHistory, restoreRecord } from "@/records";
type Entry = { id: string; kind: string; version: number; title: string; subtitle: string; updated_at: string };
const data = ref<{ total: number; truncated: boolean; items: Entry[] }>();
const busy = ref(false), error = ref(""), notice = ref("");
const labels: Record<string, string> = { knowledge: "笔记", bookmark: "收藏", plan: "规划", lesson: "谨记", learning_card: "复习卡",
  job_lead: "岗位", application: "投递", interview_report: "面试复盘", resume_version: "简历版本", company_capability: "公司能力" };
async function action(entry?: Entry) {
  if (busy.value || (entry && !confirm("将「" + entry.title + "」恢复为最新版本？"))) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    if (entry) {
      const row = { ...entry, data: {} };
      const latest = (await getHistory(row)).filter(item => !item.deleted).sort((a, b) => b.version - a.version)[0];
      if (!latest) throw new Error("没有可恢复的版本。");
      await restoreRecord(row, latest.version); notice.value = "已恢复「" + entry.title + "」。";
    }
    data.value = await request("trash");
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
onMounted(() => action());
</script>
<template>
  <div class="page-frame business-stack">
    <header class="page-heading glass"><h1>回收站</h1><p>恢复工作区已归档的内容。私密条目与运行审计不在这里展示。</p></header>
    <div class="business-actions"><p v-if="data">共 {{ data.total }} 条<span v-if="data.truncated">，这里只显示最近记录</span></p>
      <button class="secondary" type="button" :disabled="busy" @click="action()">刷新回收站</button></div>
    <p v-if="busy" role="status">正在处理…</p><p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <p v-if="data && !data.items.length">回收站为空。</p>
    <article v-for="row in data?.items" :key="row.id" class="business-panel glass">
      <h2>{{ row.title }}</h2><p>{{ labels[row.kind] || row.kind }} · {{ dateText(row.updated_at) }}</p>
      <p v-if="row.subtitle">{{ row.subtitle }}</p>
      <button class="secondary" type="button" :disabled="busy" @click="action(row)">恢复</button>
    </article>
  </div>
</template>
