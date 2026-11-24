<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { archiveRecord, dateText, getHistory, lines, segment } from "@/records";
import type { Lead, Resume } from "./jobs-data";
const props = defineProps<{ leads?: Lead[]; initialResume?: string }>();
const emit = defineEmits<{ uploaded: [row: Resume]; changed: [] }>();
const rows = ref<Resume[]>([]), file = ref<File>(), title = ref(""), input = ref<HTMLInputElement>();
const workspaceLeads = ref<Lead[]>([]);
const leads = computed(() => props.leads ?? workspaceLeads.value);
const selected = ref(""), comparison = ref(""), leadId = ref("");
const content = ref(""), analysis = ref<string[]>([]), analysisReady = ref(false), error = ref(""), note = ref(""), busy = ref(false);
const chosen = computed(() => rows.value.find(row => row.id === selected.value));
const editing = ref(false), metadata = ref({ title: "", highlights: "" }), versions = ref<Awaited<ReturnType<typeof getHistory>>>();
function resetSelection() {
  editing.value = false; versions.value = undefined; content.value = ""; analysisReady.value = false; comparison.value = "";
}
function editVersion(row: Resume) {
  metadata.value = { title: row.data.title, highlights: (row.data.highlights || []).join("\n") };
  editing.value = true;
}
function saveVersion() { return run(async () => {
  const row = chosen.value;
  if (!row) return;
  const saved = await send<Resume>("jobs/resumes/" + segment(row.id),
    { version: row.version, data: { title: metadata.value.title.trim(), highlights: lines(metadata.value.highlights) } }, "PATCH");
  rows.value = rows.value.map(item => item.id === saved.id ? saved : item);
  editing.value = false; versions.value = undefined; note.value = "已保存版本资料，原文件未改动。"; emit("changed");
}); }
function showVersions(row: Resume) { return run(async () => { versions.value = await getHistory(row); }); }
function archiveVersion(row: Resume) {
  if (busy.value || !confirm("归档该简历版本？有关联投递时后端会拒绝。可在回收站恢复。")) return;
  return run(async () => {
    await archiveRecord(row);
    rows.value = rows.value.filter(item => item.id !== row.id); selected.value = rows.value[0]?.id || "";
    resetSelection(); note.value = "简历版本已归档。"; emit("changed");
  });
}
async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await action(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function upload() {
  const chosenFile = file.value;
  if (!chosenFile) return;
  await run(async () => {
    if (chosenFile.size > 10 * 1024 * 1024) throw new Error("简历不得超过 10 MB。");
    const body = new FormData(); body.set("file", chosenFile); body.set("title", title.value.trim());
    const row = await request<Resume>("jobs/resumes/upload", { method: "POST", body });
    rows.value = [row, ...rows.value]; selected.value = row.id; resetSelection();
    note.value = "简历已上传。"; file.value = undefined; title.value = ""; content.value = "";
    if (input.value) input.value.value = "";
    emit("uploaded", row);
  });
}
function preview() { return run(async () => {
  content.value = (await request<{ text: string }>("jobs/resumes/" + segment(selected.value) + "/document")).text;
}); }
function diff() { return run(async () => {
  content.value = (await request<{ diff: string }>("jobs/resumes/" + segment(selected.value) + "/diff?against=" + segment(comparison.value))).diff;
}); }
function analyze() { return run(async () => {
  const result = await send<{ matched_skills?: string[] }>("jobs/resumes/" + segment(selected.value) + "/analyze", { lead_id: leadId.value });
  analysis.value = result.matched_skills || []; analysisReady.value = true;
}); }
onMounted(() => run(async () => {
  rows.value = await request<Resume[]>("jobs/resumes");
  const target = props.initialResume ? rows.value.find(row => row.id === props.initialResume) : rows.value[0];
  selected.value = target?.id ?? "";
  if (props.initialResume) {
    if (!target) note.value = "旧链接里的简历不存在或已归档，请重新选择。";
    else if (target.data.document_id) content.value = (await request<{ text: string }>("jobs/resumes/" + segment(target.id) + "/document")).text;
  }
  if (!props.leads && !isDemo) workspaceLeads.value = await request<Lead[]>("jobs/leads");
}));
</script>

<template>
  <section class="business-panel glass">
    <h2>简历版本与上传</h2>
    <p class="muted">{{ isDemo ? "演示只读取 TXT / Markdown，不上传到服务器。" : "支持 PDF、DOCX、TXT、Markdown 和常见图片，最大 10 MB。" }}</p>
    <form class="business-form resume-inline" @submit.prevent="upload">
      <div class="business-columns">
        <label>简历文件<input ref="input" type="file" :accept="isDemo ? '.txt,.md' : '.pdf,.docx,.txt,.md,.png,.jpg,.jpeg'"
          required @change="file = ($event.target as HTMLInputElement).files?.[0]" /></label>
        <label>版本名称（选填）<input v-model="title" maxlength="160" /></label>
      </div>
      <button type="submit" class="primary" :disabled="busy">上传并解析</button>
    </form>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
    <div v-if="rows.length" class="business-form resume-inline">
      <label>简历版本<select v-model="selected" :disabled="busy" @change="resetSelection">
        <option value="" disabled>请选择</option><option v-for="row in rows" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
      <p v-if="chosen">{{ chosen.data.file_name || '仅登记版本' }} · {{ chosen.data.document_id ? '有解析正文' : '无解析正文' }}</p>
      <div class="business-actions"><button type="button" class="secondary" :disabled="busy || !chosen?.data.document_id" @click="preview">查看解析正文</button>
        <template v-if="chosen">
          <button type="button" class="secondary" :disabled="busy" @click="editVersion(chosen)">编辑版本资料</button>
          <button type="button" class="secondary" :disabled="busy" @click="showVersions(chosen)">版本历史</button>
          <button type="button" class="secondary" :disabled="busy" @click="archiveVersion(chosen)">归档简历版本</button>
        </template>
      </div>
      <template v-if="!isDemo && rows.filter(row => row.data.document_id).length > 1 && chosen?.data.document_id">
        <label>对比版本<select v-model="comparison"><option value="">选择其他版本</option><option v-for="row in rows.filter(r => r.id !== selected && r.data.document_id)" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
        <button class="secondary" :disabled="busy || !comparison" type="button" @click="diff">对比正文</button>
      </template>
      <template v-if="!isDemo && leads.some(row => row.data.jd_text?.trim())">
        <label>比对岗位<select v-model="leadId"><option value="">选择岗位</option><option v-for="lead in leads.filter(r => r.data.jd_text?.trim())" :key="lead.id" :value="lead.id">{{ lead.data.company }} · {{ lead.data.title }}</option></select></label>
        <button class="secondary" :disabled="busy || !leadId || !chosen?.data.document_id" type="button" @click="analyze">比对岗位要求</button>
        <p v-if="analysisReady" role="status">命中技能：{{ analysis.join("、") || "未命中" }}</p>
      </template>
    </div>
    <p v-else-if="!busy">还没有简历版本。</p>
    <form v-if="editing && chosen" class="business-form resume-inline" @submit.prevent="saveVersion">
      <label>简历名称<input v-model="metadata.title" required maxlength="160" /></label>
      <label>简历亮点（每行一条）<textarea v-model="metadata.highlights" rows="3" /></label>
      <div class="business-actions"><button class="primary" :disabled="busy">保存版本资料</button>
        <button type="button" class="secondary" :disabled="busy" @click="editing = false">取消</button></div>
    </form>
    <section v-if="versions" aria-label="简历版本历史">
      <h3>版本历史</h3><p v-if="!versions.length">暂无历史。</p>
      <ul v-else><li v-for="version in versions" :key="version.version">第 {{ version.version }} 版 · {{ version.data.title }}
        · {{ dateText(version.updated_at) }}<span v-if="version.deleted"> · 已归档</span></li></ul>
    </section>
    <p v-if="content" class="preserve">{{ content }}</p>
  </section>
</template>
