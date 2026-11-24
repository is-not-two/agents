<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { dateText, segment, type Fields, type Row } from "@/records";
import ResumePanel from "./ResumePanel.vue";
import type { Lead, Resume } from "./jobs-data";
const props = defineProps<{ leads: Lead[]; resumes: Resume[]; initialLead: string; optimizeOnly?: boolean; preparation?: boolean }>();
const emit = defineEmits<{ uploaded: [row: Resume] }>();
type Turn = { q: string; answer: string; suggestion: string };
type Draft = Fields & { title: string; turns: Turn[]; lead_id: string; notes: string };
type Workflow = Row<Fields & { title: string; edges?: string[][]; nodes?: { id: string; type?: string; tool_id?: string; query?: string }[] }>;
type Output = { answer?: string; evidence?: { facts: string[]; pending: string[]; suggestions: string[] } };
type Run = Row<Fields & { status: string; interview_lead_id?: string; private_interview?: boolean; started_at?: string;
  node_outputs?: Record<string, Output>; result?: { notes: string[] }; node_status?: Record<string, string> }>;
const stages: [string, string][] = [["resume_draft","简历草稿"],["first_question","首问"],["first_answer","首答"],
  ["followup_question","追问"],["followup_answer","追答"],["boss_review","用人主管复盘"]];
const mode = ref<"agent" | "practice" | "full">(isDemo ? "practice" : "agent"), leadId = ref(props.initialLead);
const resumeId = ref(""), knowledgeId = ref(""), model = ref(false), uploading = ref(false);
const showOptimize = ref(false), templateId = ref(""), optimized = ref(""), optimizationTitle = ref("");
const templates = ref<{ id: string; name: string }[]>([]), knowledge = ref<Row[]>([]), runs = ref<Run[]>([]);
const draft = ref<Draft>(), activeRun = ref<Run>(), sessions = ref<Row<Draft>[]>([]);
const selectedPoints = ref<string[]>([]);
const error = ref(""), note = ref(""), busy = ref(false);
const eligible = computed(() => props.resumes.filter(row => row.data.document_id));
const history = computed(() => runs.value.filter(row => row.data.private_interview && row.data.interview_lead_id === leadId.value));
const ready = computed(() => eligible.value.some(row => row.id === resumeId.value) && props.leads.some(row => row.id === leadId.value && row.data.jd_text?.trim()));
const points = computed(() => {
  const data = activeRun.value?.data;
  const evidence = data?.node_outputs?.boss_review?.evidence;
  return data?.status === "completed" && evidence
    ? [...new Set([...(evidence.pending || []), ...(evidence.suggestions || [])])].filter(point => point.length <= 1000)
    : [];
});
const runStatus = computed(() => {
  const value = activeRun.value?.data;
  if (!value) return "";
  if (value.status === "completed") return "模拟已完成";
  const fail = stages.find(([id]) => value.node_status?.[id] === "failed");
  return fail ? "停在：" + fail[1] : "模拟状态：" + value.status;
});
watch(eligible, rows => {
  if (!rows.some(row => row.id === resumeId.value)) resumeId.value = props.preparation && rows.length !== 1 ? "" : rows[0]?.id ?? "";
}, { immediate: true });
watch(leadId, () => { draft.value = undefined; activeRun.value = undefined; optimized.value = ""; note.value = ""; });
watch([resumeId, knowledgeId], () => { optimized.value = ""; activeRun.value = undefined; });
watch(activeRun, () => { selectedPoints.value = []; });
async function run(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await action(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function upload(row: Resume) { emit("uploaded", row); resumeId.value = row.id; uploading.value = false; }
function validFlow(row: Workflow) {
  const nodes = row.data.nodes || [];
  if (props.preparation) {
    const ids = ["input", "material", ...stages.map(([id]) => id)];
    const edges = row.data.edges || [];
    if (nodes.length !== ids.length || edges.length !== ids.length - 1 ||
        !ids.every((id, i) => nodes.some(node => node.id === id &&
          (i === 0 ? node.type === "input" : i === 1 ? node.type === "tool" && node.tool_id === "interview_context" : node.type === "agent")) &&
          (!i || edges.some(([from, to]) => from === ids[i - 1] && to === id)))) return false;
  }
  return nodes.some(node => node.tool_id === "interview_context") &&
    ["resume_draft","first_answer","followup_answer","boss_review"].every(id =>
      nodes.some(node => node.id === id && node.query?.includes("[INTERVIEW_EVIDENCE_V1]")));
}
async function generate() {
  if (!ready.value) return;
  if ((mode.value === "agent" || model.value) && !confirm("确认把所选岗位、简历和允许的资料发给已配置的模型？")) return;
  await run(async () => {
    draft.value = undefined; activeRun.value = undefined;
    const input = { lead_id: leadId.value, resume_id: resumeId.value };
    if (mode.value !== "agent") {
      draft.value = await send<Draft>("interview-prep/generate", { ...input, mode: mode.value, use_model: model.value });
      return;
    }
    const workflows = await request<Workflow[]>("workflows");
    let flow: { id: string; version: number } | undefined = workflows.find(validFlow);
    if (!flow) {
      const proposal = await send<Fields>("automation/compose/draft", { goal: "三角色文字模拟面试", template: "interview" });
      const saved = await send<{ workflow_id: string; version: number }>("automation/compose/save", { draft: proposal });
      flow = { id: saved.workflow_id, version: saved.version };
    }
    activeRun.value = await send<Run>("workflows/" + segment(flow.id) + "/run", { version: flow.version,
      input: { ...input, knowledge_id: knowledgeId.value } });
    runs.value = [activeRun.value, ...runs.value.filter(row => row.id !== activeRun.value?.id)];
  });
}
function saveSession() { return run(async () => {
  if (!draft.value) return;
  const saved = await send<Row<Draft>>("interview-prep", { data: draft.value });
  sessions.value = [saved, ...sessions.value]; draft.value = undefined; note.value = "已保存练习会话。";
}); }
function saveCards() {
  const source = activeRun.value;
  if (!source || !selectedPoints.value.length) return;
  return run(async () => {
    const result = await send<{ created: unknown[]; reused: unknown[] }>("learning/from-simulation/" + segment(source.id),
      { version: source.version, points: selectedPoints.value, confirmation: "确认创建复习卡" });
    selectedPoints.value = [];
    note.value = "新增 " + result.created.length + " 张复习卡，复用 " + result.reused.length + " 张。";
  });
}
function optimize() {
  if (!ready.value || !templateId.value || !confirm("确认将所选简历与岗位原文发给模型生成草稿？")) return;
  return run(async () => {
    const data = await send<{ draft: string; template: string }>("resume/optimize", { template_id: templateId.value, resume_id: resumeId.value, lead_id: leadId.value });
    optimized.value = data.draft; optimizationTitle.value = "简历草稿 · " + data.template;
  });
}
function saveOptimized() {
  if (!optimized.value.trim() || !confirm("另存为知识记录？不会覆盖原简历。")) return;
  return run(async () => { await send("resume/apply", { draft: optimized.value, title: optimizationTitle.value, confirmation: "确认另存优化草稿" }); note.value = "已另存为知识记录。"; });
}
onMounted(() => run(async () => {
  if (!props.optimizeOnly) {
    const [previous, saved] = await Promise.all([request<Run[]>("workflow-runs"), request<Row<Draft>[]>("interview-prep")]);
    runs.value = previous; sessions.value = saved;
  }
  if (!isDemo) {
    templates.value = await request("resume/templates");
    if (!props.optimizeOnly) knowledge.value = await request("knowledge");
    templateId.value = templates.value[0]?.id ?? "";
  }
}));
</script>

<template>
  <section class="business-stack">
    <section class="business-panel glass"><h2>{{ preparation ? '准备这场面试' : optimizeOnly ? '选择改稿材料' : '预面试' }}</h2>
      <p class="muted">{{ preparation ? '一次选择材料，得到简历草稿、三角色模拟和练习建议；不改原简历。' : optimizeOnly ? '草稿不会覆盖原简历。' : '练习与真实面试复盘分开保存。' }}</p>
      <div class="business-actions">
        <button class="secondary" type="button" :disabled="busy" @click="uploading = !uploading">上传简历</button>
        <button v-if="!isDemo && !optimizeOnly && !preparation" class="secondary" type="button" @click="showOptimize = !showOptimize">定向改稿</button>
      </div>
    </section>
    <ResumePanel v-if="uploading" :leads="leads" @uploaded="upload" />
    <form class="business-form glass" @submit.prevent="generate">
      <div class="business-columns">
        <p v-if="preparation">目标岗位：{{ leads.find(row => row.id === leadId)?.data.title }}</p>
        <label v-else>目标岗位<select v-model="leadId" :disabled="busy"><option value="" disabled>请选择岗位</option>
          <option v-for="row in leads" :key="row.id" :value="row.id">{{ row.data.company }} · {{ row.data.title }}</option></select></label>
        <label>简历版本<select v-model="resumeId" :disabled="busy"><option value="">{{ eligible.length ? '请选择' : '尚无可用简历' }}</option><option v-for="row in eligible" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
      </div>
      <template v-if="!optimizeOnly">
        <label v-if="!preparation">练习方式<select v-model="mode" :disabled="busy"><option v-if="!isDemo" value="agent">三角色文字模拟</option><option value="practice">自己作答</option><option value="full">参考问答</option></select></label>
        <label v-if="mode === 'agent'">知识授权<select v-model="knowledgeId" :disabled="busy"><option value="">不使用知识库</option><option v-for="row in knowledge" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
        <label v-else-if="!isDemo" class="check-line"><input type="checkbox" v-model="model" :disabled="busy" /> 使用 AI 出题</label>
        <button type="submit" class="primary" :disabled="busy || !ready">{{ busy ? "处理中…" : preparation ? "生成草稿并模拟" : mode === 'agent' ? "运行模拟" : "生成练习" }}</button>
      </template>
      <p v-if="!ready" class="muted">需要有正文的简历和填写了招聘原文的岗位。</p>
    </form>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
    <p v-if="optimizeOnly && isDemo">演示不调用模型生成简历草稿。</p>
    <section v-if="(optimizeOnly || showOptimize) && !isDemo" class="business-form glass"><h2>定向改稿</h2>
      <label>优化模板<select v-model="templateId"><option value="">没有可用模板</option><option v-for="template in templates" :key="template.id" :value="template.id">{{ template.name }}</option></select></label>
      <button class="primary" type="button" :disabled="busy || !ready || !templateId" @click="optimize">生成改稿</button>
      <template v-if="optimized"><label>草稿正文<textarea v-model="optimized" rows="10" maxlength="50000" /></label>
        <button class="secondary" type="button" :disabled="busy" @click="saveOptimized">另存为知识记录</button></template>
    </section>
    <section v-if="draft" class="business-form glass"><h2>{{ draft.title }}</h2><p v-if="draft.notes">{{ draft.notes }}</p>
      <article v-for="(turn, index) in draft.turns" :key="index"><h3>{{ index + 1 }}. {{ turn.q }}</h3>
        <label>回答<textarea v-model="turn.answer" rows="3" maxlength="8000" /></label><p v-if="turn.suggestion">{{ turn.suggestion }}</p></article>
      <button class="primary" type="button" :disabled="busy" @click="saveSession">保存练习</button>
    </section>
    <section v-if="activeRun" class="business-stack" aria-label="模拟结果">
      <h2>{{ runStatus }}</h2><p v-for="(text, i) in activeRun.data.result?.notes" :key="i" class="form-error">{{ text }}</p>
      <article v-for="[key, label] in stages.filter(([id]) => activeRun?.data.node_outputs?.[id]?.answer)" :key="key" class="business-panel glass">
        <h3>{{ label }}</h3><p class="preserve">{{ activeRun.data.node_outputs?.[key]?.answer }}</p></article>
      <form v-if="points.length" class="business-form glass" @submit.prevent="saveCards">
        <h3>选择练习点</h3><p>勾选内容会作为普通复习卡进入工作区备份；请不要选敏感内容。</p>
        <label v-for="point in points" :key="point" class="check-line">
          <input v-model="selectedPoints" type="checkbox" :value="point" :disabled="busy" /> {{ point }}</label>
        <button class="primary" :disabled="busy || !selectedPoints.length">确认创建复习卡</button>
        <RouterLink to="/module/learning">去复习</RouterLink>
      </form>
    </section>
    <section v-if="!optimizeOnly" class="business-panel glass"><h2>练习与模拟历史</h2>
      <p v-if="!history.length && !sessions.some(row => row.data.lead_id === leadId)">这个岗位还没有记录。</p>
      <ul class="simple-list"><li v-for="row in history" :key="row.id"><button class="secondary" type="button" :disabled="busy"
        @click="run(async () => { activeRun = await request<Run>('workflow-runs/' + segment(row.id)); })">回看模拟 · {{ dateText(row.data.started_at) }}</button></li>
      <li v-for="row in sessions.filter(r => r.data.lead_id === leadId)" :key="row.id"><details><summary>{{ row.data.title }}</summary>
        <p v-for="(turn, i) in row.data.turns" :key="i" class="preserve">{{ turn.q }}：{{ turn.answer || "未作答" }}</p></details></li></ul>
    </section>
  </section>
</template>
