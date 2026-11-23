<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { messageOf, request, send } from "@/api";
import { segment } from "@/records";
import type { Lead } from "./jobs-data";
type Skill = { name: string; evidence: string; reference: string };
type Fact = { category: string; value: string; evidence: string };
type Profile = { revision: string; data: { title: string; skills: Skill[]; facts: Fact[] } };
type Requirement = { name: string; priority: string; assessment: string; quote: string; start: number; end: number; evidence: Skill[] };
type Gap = { stale: boolean; persisted: boolean; reused?: boolean; lead_version: number; profile_revision: string; status: string;
  analysis?: { requirements: Requirement[]; hard_conditions: { category: string; priority: string; quote: string; profile_facts: Fact[] }[]; notes: string[] } };
const priorities: Record<string, string> = { required: "要求", preferred: "优先", mentioned: "原文提及", not_required: "明确不要求" };
const assessments: Record<string, string> = { evidence_supplied: "已有自填证据，需核对", declared_only: "有声明、无证据", not_in_profile: "资料未提供，不代表不会" };
const categories: Record<string, string> = { education: "学历", experience: "经验或年限", availability: "到岗或出勤", language: "语言", other: "其他" };
const route = useRoute(), router = useRouter();
const leads = ref<Lead[]>([]), active = ref(""), profile = ref<Profile>(), edit = ref<Profile["data"]>(), gap = ref<Gap>();
const chosen = ref<string[]>([]), error = ref(""), note = ref(""), busy = ref(false), configured = ref(false);
const lead = computed(() => leads.value.find(row => row.id === active.value));
const path = () => "jobs/leads/" + segment(active.value);
async function loadGap() {
  chosen.value = []; gap.value = undefined;
  if (lead.value?.data.jd_text?.trim()) gap.value = await request(path() + "/gap");
}
async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await action(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function load() { return run(async () => {
  const [rows, data, connection] = await Promise.all([request<Lead[]>("jobs/leads"), request<Profile>("jobs/profile"),
    request<{ configured: boolean }>("model-connection").catch(() => ({ configured: false }))]);
  leads.value = rows; profile.value = data; configured.value = connection.configured; edit.value = undefined;
  const selected = typeof route.query.lead === "string" ? route.query.lead : "";
  active.value = rows.some(row => row.id === selected) ? selected : rows[0]?.id || "";
  await loadGap();
}); }
function pick(event: Event) { return run(async () => {
  active.value = (event.target as HTMLSelectElement).value;
  await router.replace({ query: { ...route.query, lead: active.value } });
  await loadGap();
}); }
function startEditing() { if (profile.value) edit.value = JSON.parse(JSON.stringify(profile.value.data)); }
function saveProfile() { return run(async () => {
  if (!edit.value || !profile.value) return;
  const data = { title: edit.value.title, skills: edit.value.skills.filter(item => item.name.trim()), facts: edit.value.facts.filter(item => item.value.trim()) };
  profile.value = await send<Profile>("jobs/profile", { revision: profile.value.revision, data }, "PUT");
  edit.value = undefined; await loadGap(); note.value = "已保存求职证据。";
}); }
function analyze(mode: "rules" | "model" | "repeat") {
  if (mode !== "rules" && !confirm(mode === "repeat" ? "重新发送岗位与个人证据给模型？可能重复计费。" : "确认把完整岗位原文与个人证据发送给已配置的模型？")) return;
  return run(async () => {
    if (!lead.value || !profile.value) return;
    gap.value = await send<Gap>(path() + "/analyze", { version: lead.value.version, profile_revision: profile.value.revision,
      mode: mode === "rules" ? "rules" : "model", confirmation: mode === "rules" ? "" : "发送岗位与资料进行分析",
      request_id: mode === "repeat" ? crypto.randomUUID() : "" });
    chosen.value = []; note.value = gap.value.reused ? "已复用已有分析。" : "分析请求已完成，请核对证据。";
  });
}
function cards() {
  if (!gap.value || gap.value.stale || !chosen.value.length || !confirm("只为勾选的要求创建复习卡？")) return;
  return run(async () => {
    if (!gap.value) return;
    const result = await send<{ created: unknown[]; reused: unknown[] }>(path() + "/learning-cards", { version: gap.value.lead_version,
      profile_revision: gap.value.profile_revision, names: [...chosen.value], confirmation: "确认创建复习卡" });
    chosen.value = []; note.value = "新增 " + result.created.length + " 张，复用 " + result.reused.length + " 张。";
  });
}
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
    <div class="business-actions"><button type="button" class="secondary" :disabled="busy || !profile" @click="startEditing">编辑我的求职证据</button>
      <button type="button" class="secondary" :disabled="busy" @click="load">刷新资料与分析</button>
      <RouterLink class="secondary" to="/module/job-flow">求职流水线</RouterLink></div>
    <form v-if="edit" class="business-form glass" @submit.prevent="saveProfile">
      <h2>我的求职证据</h2><p>只保存自填资料；不自动提交给模型。</p>
      <label>资料名称<input v-model="edit.title" maxlength="160" required /></label>
      <fieldset v-for="(item,i) in edit.skills" :key="'skill-' + i" class="business-form">
        <legend>技能 {{ i + 1 }}</legend><label>技能名称<input v-model="item.name" maxlength="80" required /></label>
        <label>实际做过什么<input v-model="item.evidence" maxlength="1000" /></label><label>证据来源<input v-model="item.reference" maxlength="500" /></label>
        <button type="button" class="secondary" @click="edit.skills.splice(i, 1)">移除技能</button></fieldset>
      <fieldset v-for="(item,i) in edit.facts" :key="'fact-' + i" class="business-form">
        <legend>个人事实 {{ i + 1 }}</legend><label>事实类型<select v-model="item.category"><option v-for="(name,key) in categories" :key="key" :value="key">{{ name }}</option></select></label>
        <label>事实<input v-model="item.value" required maxlength="1000" /></label><label>事实依据<input v-model="item.evidence" maxlength="1000" /></label>
        <button type="button" class="secondary" @click="edit.facts.splice(i, 1)">移除事实</button></fieldset>
      <div class="business-actions"><button type="button" class="secondary" :disabled="edit.skills.length >= 50" @click="edit.skills.push({ name: '', evidence: '', reference: '' })">添加技能</button>
        <button type="button" class="secondary" :disabled="edit.facts.length >= 20" @click="edit.facts.push({ category: 'other', value: '', evidence: '' })">添加事实</button>
        <button class="primary" :disabled="busy">保存证据</button><button type="button" class="secondary" @click="edit = undefined">取消</button></div>
    </form>
    <div v-if="leads.length" class="business-form glass">
      <label>选择岗位<select :value="active" :disabled="busy" @change="pick"><option v-for="row in leads" :key="row.id" :value="row.id">{{ row.data.company }} / {{ row.data.title }}</option></select></label>
      <details v-if="lead?.data.jd_text"><summary>完整招聘原文</summary><p class="preserve">{{ lead.data.jd_text }}</p></details>
      <p v-else>请先在公司流水线为岗位填写招聘原文。</p>
      <div class="business-actions"><button class="primary" type="button" :disabled="busy || !lead?.data.jd_text" @click="analyze('rules')">保存离线规则分析</button>
        <button class="secondary" type="button" :disabled="busy || !configured || !lead?.data.jd_text" @click="analyze('model')">模型补充分析</button>
        <button v-if="configured && gap?.status === 'running'" class="secondary" type="button" :disabled="busy" @click="analyze('repeat')">核对后重新调用模型</button></div>
    </div>
    <p v-else-if="!busy && !error">还没有岗位，请先添加公司和岗位。</p>
    <div v-if="gap?.analysis" class="business-panel glass">
      <h2>原文要求与个人证据</h2><p>{{ gap.stale ? '岗位或证据已变化，建议重新分析。' : gap.persisted ? '分析已留档。' : '规则预览，未留档。' }} 不判断录用概率。</p>
      <p v-if="!gap.analysis.requirements.length">未提取到要求，不代表岗位没有要求。</p>
      <article v-for="item in gap.analysis.requirements" :key="item.name + item.start"><h3>{{ item.name }}</h3>
        <p>{{ priorities[item.priority] }} · {{ assessments[item.assessment] }}</p><blockquote>{{ item.quote }}</blockquote>
        <ul><li v-for="(entry, i) in item.evidence" :key="i">{{ entry.evidence }} {{ entry.reference }}</li></ul>
        <label v-if="item.assessment !== 'evidence_supplied' && item.priority !== 'not_required'" class="check-line">
          <input type="checkbox" v-model="chosen" :value="item.name" :disabled="gap.stale || busy" /> 创建「{{ item.name }}」复习卡
        </label>
      </article>
      <button class="secondary" type="button" :disabled="busy || gap.stale || !chosen.length" @click="cards">为选中项建复习卡</button>
      <h2>硬性条件</h2><article v-for="(item,i) in gap.analysis.hard_conditions" :key="i"><h3>{{ categories[item.category] }}</h3>
        <blockquote>{{ item.quote }}</blockquote><p>请人工确认是否满足。</p>
        <ul><li v-for="(fact,j) in item.profile_facts" :key="j">{{ fact.value }} {{ fact.evidence }}</li></ul></article>
      <ul><li v-for="item in gap.analysis.notes" :key="item">{{ item }}</li></ul>
    </div>
  </section>
</template>
