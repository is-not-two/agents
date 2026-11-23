<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { dateText, segment, type Row } from "@/records";
type Agent = Row<{ title: string; generate: boolean; scopes: string[]; tool_ids: string[]; handoffs?: { allowed: string[] } }>;
type Step = { assignee: string; input: string; expected: string };
type Call = { function?: { arguments?: string } };
type Child = Row<{ title: string; pending_calls?: Call[] }>;
type Run = Row<{ title: string; workflow_id: string; mode: string; status: string; started_at?: string; pending_calls?: Call[];
  shared_state: { phase: string; plan?: Step[]; board?: { step: number; status: string; child_id: string; content: string }[]; budget?: unknown };
  result?: { answer?: string; notes?: string[] }; trace?: unknown }> & { pending_child_run?: Child | null };
const profile = ref<Agent[]>([]), runs = ref<Run[]>([]), current = ref<Run>(), owner = ref(""), workers = ref<string[]>([]);
const setup = ref<{ enabled: boolean; max_plan_steps: number }>(), model = ref(false), target = ref(""), steps = ref<Step[]>([]);
const busy = ref(false), error = ref(""), note = ref("");
const leader = computed(() => profile.value.find(row => row.id === owner.value));
const peers = computed(() => profile.value.filter(row => row.id !== owner.value && leader.value?.data.handoffs?.allowed.includes(row.id)));
const histories = computed(() => runs.value.filter(row => row.data.workflow_id === "agent:" + owner.value));
const terminal = computed(() => ["completed","fallback","failed"].includes(current.value?.data.status || ""));
const plan = computed<Step[]>(() => {
  const row = current.value;
  if (!row) return [];
  let candidate: unknown = row.data.shared_state.plan;
  if (!Array.isArray(candidate) || !candidate.length) {
    try { candidate = JSON.parse(row.data.pending_calls?.[0]?.function?.arguments || "{}").plan; } catch { return []; }
  }
  return Array.isArray(candidate) && candidate.every(step => typeof step?.assignee === "string" && typeof step?.input === "string" &&
    typeof step?.expected === "string") ? candidate : [];
});
const endpoint = (id: string) => "collaborations/" + segment(id);
async function action(fn: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function fetchRuns(id?: string) {
  runs.value = await request("collaborations");
  const key = id || histories.value[0]?.id;
  current.value = key ? await request(endpoint(key)) : undefined;
}
function sync() {
  workers.value = [...(leader.value?.data.handoffs?.allowed || [])]; steps.value = [];
}
function load() { return action(async () => {
  const [agents, settings, connection] = await Promise.all([request<Agent[]>("agents"),
    request<typeof setup.value>("collaborations/status"), request<{ configured: boolean }>("model-connection").catch(() => ({ configured: false }))]);
  profile.value = agents; setup.value = settings; model.value = connection.configured;
  if (!leader.value) { owner.value = agents[0]?.id || ""; sync(); }
  else workers.value = [...(leader.value.data.handoffs?.allowed || [])];
  await fetchRuns(current.value?.id);
}); }
function pick(event: Event) { return action(async () => {
  owner.value = (event.target as HTMLSelectElement).value; target.value = ""; current.value = undefined; sync(); await fetchRuns();
}); }
function open(event: Event) { return action(async () => {
  const id = (event.target as HTMLSelectElement).value;
  current.value = id ? await request(endpoint(id)) : undefined;
}); }
function saveWorkers() { return action(async () => {
  const row = leader.value;
  if (!row) return;
  const saved = await send<Agent>("agents/" + segment(row.id), { version: row.version, data: { handoffs: { allowed: [...workers.value] } } }, "PUT");
  profile.value = profile.value.map(item => item.id === saved.id ? saved : item); sync();
  note.value = "交接白名单已保存，不会执行任务。";
}); }
function create(useModel: boolean) {
  const row = leader.value;
  if (!row || !target.value.trim() || !peers.value.length) return;
  if (useModel && (!setup.value?.enabled || !model.value || !row.data.generate || !confirm("用模型生成计划？可能计费，不会直接批准 Worker 写操作。"))) return;
  if (!useModel && (!steps.value.length || steps.value.some(step => !step.input.trim() || !step.expected.trim()))) return;
  return action(async () => {
    const saved = await send<Run>("collaborations", { agent_id: row.id, version: row.version, query: target.value.trim(),
      ...(useModel ? {} : { plan: steps.value.map((step,i) => ({ step: i, ...step })) }),
      confirmation: useModel ? "生成协作计划（可能计费）" : "仅创建人工计划" });
    await fetchRuns(saved.id); note.value = "计划已生成，请核对后再决定。";
  });
}
function decide(kind: "plan" | "child" | "execute" | "abort", approve?: boolean) {
  const row = current.value;
  if (!row || terminal.value) return;
  const child = row.pending_child_run;
  if (kind === "plan" && (child || row.data.status !== "awaiting_confirmation" || (approve && !plan.value.length))) return;
  if (kind === "child" && (!child || !child.data.pending_calls?.length)) return;
  if (kind === "execute" && (row.data.status !== "confirmed" || !setup.value?.enabled || !model.value)) return;
  const detail = { plan: approve ? "批准计划，不批准Worker写操作" : "拒绝计划",
    child: approve ? "批准当前Worker操作" : "拒绝当前Worker操作",
    execute: "执行协作计划（可能计费）", abort: "已核对在途请求，终止协作且不重试" }[kind];
  if (!confirm(detail + "？")) return;
  return action(async () => {
    await send(endpoint(row.id) + "/" + (kind === "plan" ? "confirm" : kind === "child" ? "child-confirm" : kind),
      { version: row.version, confirmation: detail,
        ...(kind === "plan" || kind === "child" ? { approve } : {}),
        ...(kind === "child" ? { child_version: child?.version } : {}) });
    await fetchRuns(row.id); note.value = "协作状态已更新。";
  });
}
function addStep() {
  if (!peers.value.length || steps.value.length >= (setup.value?.max_plan_steps || 0)) return;
  steps.value.push({ assignee: peers.value[0].id, input: "", expected: "" });
}
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不会调用模型或派发协作任务。</p>
    <template v-else>
      <div class="business-actions"><button class="secondary" type="button" :disabled="busy" @click="load">刷新协作记录</button></div>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
      <div class="business-form glass"><label>负责人<select :value="owner" :disabled="busy" @change="pick">
        <option v-for="agent in profile" :key="agent.id" :value="agent.id">{{ agent.data.title }}</option></select></label>
        <p>批准计划不等于批准 Worker 写操作。失联后先刷新，不要盲目重发。</p>
        <p v-if="!setup?.enabled">模型协作未启用；人工建计划和批准不调用模型。</p>
      </div>
      <template v-if="leader">
        <form class="business-form glass" @submit.prevent="saveWorkers">
          <h2>交接白名单</h2>
          <label v-for="agent in profile.filter(item => item.id !== owner)" :key="agent.id" class="check-line">
            <input type="checkbox" v-model="workers" :value="agent.id" :disabled="busy" /> {{ agent.data.title }} · {{ agent.data.scopes.join('/') }} · 工具：{{ agent.data.tool_ids.join('、') || '无' }}</label>
          <button class="secondary" :disabled="busy">保存交接白名单</button>
        </form>
        <form class="business-form glass" @submit.prevent="create(false)">
          <h2>新建协作计划</h2><label>协作任务<textarea v-model="target" rows="3" maxlength="4000" required /></label>
          <fieldset v-for="(step,index) in steps" :key="index" class="business-form"><legend>步骤 {{ index + 1 }}</legend>
            <label>执行 Agent<select v-model="step.assignee"><option v-for="agent in peers" :key="agent.id" :value="agent.id">{{ agent.data.title }}</option></select></label>
            <label>输入<textarea v-model="step.input" maxlength="4000" required rows="2" /></label>
            <label>预期产物<input v-model="step.expected" maxlength="1000" required /></label>
            <button class="secondary" type="button" @click="steps.splice(index,1)">移除此步骤</button>
          </fieldset>
          <div class="business-actions">
            <button class="secondary" type="button" :disabled="busy || !peers.length || steps.length >= (setup?.max_plan_steps || 0)" @click="addStep">添加步骤</button>
            <button class="primary" :disabled="busy || !steps.length">创建人工计划（不执行）</button>
            <button class="secondary" type="button" :disabled="busy || !peers.length || !setup?.enabled || !model || !leader.data.generate || !target.trim()"
              @click="create(true)">由模型生成计划</button>
          </div>
        </form>
        <div class="business-form glass"><label>协作记录<select :value="current?.id || ''" :disabled="busy" @change="open">
          <option value="">请选择</option><option v-for="row in histories" :key="row.id" :value="row.id">{{ row.data.title }} · {{ dateText(row.data.started_at) }}</option></select></label></div>
      </template>
      <article v-if="current" class="business-panel glass">
        <h2>{{ current.data.title }}</h2><p>{{ current.data.status }} · {{ current.data.shared_state.phase }} · v{{ current.version }}</p>
        <ol v-if="plan.length"><li v-for="(step,i) in plan" :key="i">
          <strong>{{ profile.find(row => row.id === step.assignee)?.data.title || step.assignee }}</strong>
          <p class="preserve">{{ step.input }}</p><p>预期：{{ step.expected }}</p></li></ol>
        <div v-if="current.data.status === 'awaiting_confirmation' && !current.pending_child_run" class="business-actions">
          <button class="primary" type="button" :disabled="busy || !plan.length" @click="decide('plan',true)">批准计划</button>
          <button class="secondary" type="button" :disabled="busy" @click="decide('plan',false)">拒绝计划</button></div>
        <button v-if="current.data.status === 'confirmed'" class="primary" type="button" :disabled="busy || !setup?.enabled || !model" @click="decide('execute')">执行已确认计划</button>
        <div v-if="current.pending_child_run"><h3>核对 Worker 的操作</h3>
          <pre class="preserve">{{ JSON.stringify(current.pending_child_run.data.pending_calls || [], null, 2) }}</pre>
          <div v-if="current.pending_child_run.data.pending_calls?.length" class="business-actions">
            <button class="primary" type="button" :disabled="busy" @click="decide('child',true)">批准当前 Worker 操作</button>
            <button class="secondary" type="button" :disabled="busy" @click="decide('child',false)">拒绝当前 Worker 操作</button></div>
        </div>
        <button v-if="!terminal" class="secondary" type="button" :disabled="busy" @click="decide('abort')">核对后终止，不重试</button>
        <h3>实际产物</h3><p v-if="!current.data.shared_state.board?.length">暂无 Worker 产物。</p>
        <details v-for="(item,i) in current.data.shared_state.board" :key="i"><summary>步骤 {{ item.step + 1 }} · {{ item.status }}</summary><p class="preserve">{{ item.content }}</p></details>
        <p v-if="current.data.result?.answer" class="preserve">{{ current.data.result.answer }}</p>
        <ul><li v-for="(item,i) in current.data.result?.notes" :key="i">{{ item }}</li></ul>
        <details><summary>协作审计</summary><pre class="preserve">{{ JSON.stringify({ state: current.data.shared_state, trace: current.data.trace }, null, 2) }}</pre></details>
      </article>
    </template>
  </section>
</template>
