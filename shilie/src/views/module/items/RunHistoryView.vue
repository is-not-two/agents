<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { isDemo, messageOf, request, send } from "@/api";
import { dateText, segment, type Row } from "@/records";
type Run = Row<{ title: string; kind: string; status: string; started_at?: string; mode?: string; closed?: boolean;
  turns?: { author: string; text: string }[]; summary?: { status?: string; reason?: string; diff?: string; attempts?: unknown[] };
  result?: { answer?: string; notes?: string[]; chunks?: { title: string; content: string }[] };
  node_status?: Record<string, string>; node_outputs?: Record<string, { answer?: string }>;
  pending_calls?: unknown[]; pending_node?: string; pending_kind?: string; pending_child?: { run_id: string; version: number };
  workflow?: { data?: { nodes?: { id: string; type: string; message?: string }[] } };
  steps?: { title?: string; status?: string; detail?: string }[]; trace?: unknown }>;
const route = useRoute(), router = useRouter();
const runs = ref<Run[]>([]), detail = ref<Run>(), child = ref<Run>();
const pick = ref(""), busy = ref(false), note = ref(""), error = ref(""), nextQuery = ref(""), chunks = ref<number[]>([]);
const statuses: Record<string,string> = { running: "运行中", awaiting_confirmation: "等待确认", completed: "已完成", confirmed: "已确认",
  failed: "失败", fallback: "降级完成", cancelled: "已取消" };
const pending = computed(() => detail.value?.data.status === "awaiting_confirmation");
const policy = computed(() => {
  const d = detail.value?.data;
  return d?.workflow?.data?.nodes?.find(node => node.id === d.pending_node)?.message || "";
});
const calls = computed(() => detail.value?.data.kind === "agent" ? detail.value.data.pending_calls : child.value?.data.pending_calls);
const readyForDecision = computed(() => pending.value && !!detail.value &&
  (detail.value.data.kind === "graph" ? (detail.value.data.pending_kind === "approval" && !!policy.value) ||
    (detail.value.data.pending_kind === "agent" && child.value?.version === detail.value.data.pending_child?.version && !!calls.value?.length)
    : detail.value.data.kind === "agent" && !!calls.value?.length));
const endpoint = (id: string, kind: string) => (kind === "agent" ? "agent-runs/" : "workflow-runs/") + segment(id);
async function action(fn: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function list() {
  const results = await Promise.all([request<Run[]>("agent-runs"), request<Run[]>("workflow-runs")]);
  runs.value = results.flat().sort((a,b) => String(b.data.started_at || "").localeCompare(String(a.data.started_at || "")));
}
async function open(id: string) {
  pick.value = id; child.value = undefined; detail.value = undefined; chunks.value = [];
  if (!id) return;
  const known = runs.value.find(row => row.id === id);
  const kind = known?.data.kind ?? (route.query.kind === "agent" ? "agent" : "graph");
  detail.value = await request<Run>(endpoint(id, kind));
  const target = detail.value.data.pending_child;
  if (target && detail.value.data.status === "awaiting_confirmation")
    child.value = await request<Run>(endpoint(target.run_id, "agent"));
}
function select(event: Event) {
  const id = (event.target as HTMLSelectElement).value;
  return action(async () => {
    await router.replace({ query: id ? { run: id, kind: runs.value.find(row => row.id === id)?.data.kind } : {} });
    await open(id);
  });
}
function refresh() { return action(async () => {
  await list(); await open(pick.value || (typeof route.query.run === "string" ? route.query.run : ""));
}); }
function change(kind: "approve" | "reject" | "ingest" | "resume" | "continue" | "close") {
  const row = detail.value;
  if (!row || busy.value) return;
  if (["approve","reject"].includes(kind) && !readyForDecision.value) return;
  if (kind === "ingest" && (!pending.value || !chunks.value.length)) return;
  const confirms = { approve: "批准已展示的本次操作？", reject: "拒绝本次操作？", ingest: "把所选片段写入个人知识库？",
    resume: "仅在确认旧执行已停止后恢复此流程。已发出的操作不会撤销。是否继续？",
    continue: "发送后续任务给当前 Agent？可能调用模型和工具。", close: "关闭这个 Agent 会话？" };
  if (!confirm(confirms[kind])) return;
  return action(async () => {
    const path = endpoint(row.id, row.data.kind);
    const verb = kind === "resume" || kind === "continue" || kind === "close" ? kind : "confirm";
    const body = { version: row.version, ...(kind === "ingest" ? { selected: [...chunks.value] } :
      kind === "continue" ? { query: nextQuery.value.trim() } : kind === "approve" || kind === "reject" ? { approve: kind === "approve" } : {}) };
    await send(path + "/" + verb, body);
    nextQuery.value = ""; await open(row.id); await list(); note.value = "已更新运行状态。";
  });
}
onMounted(refresh);
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不查询或恢复真实运行。</p>
    <template v-else>
      <div class="business-form glass">
        <label>选择运行<select :value="pick" :disabled="busy" @change="select"><option value="">请选择</option>
          <option v-if="detail && !runs.some(row => row.id === detail?.id)" :value="detail.id">{{ detail.data.title }}</option>
          <option v-for="row in runs" :key="row.id" :value="row.id">{{ row.data.title }} · {{ statuses[row.data.status] || row.data.status }} · {{ dateText(row.data.started_at) }}</option></select></label>
        <button type="button" class="secondary" :disabled="busy" @click="refresh">刷新运行</button>
      </div>
      <p v-if="busy" role="status">正在处理运行记录…</p><p v-if="note" role="status">{{ note }}</p>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <article v-if="detail" class="business-panel glass">
        <h2>{{ detail.data.title }}</h2><p>{{ statuses[detail.data.status] || detail.data.status }} · 版本 {{ detail.version }}</p>
        <p v-if="detail.data.result?.answer" class="preserve">{{ detail.data.result.answer }}</p>
        <ol v-if="detail.data.turns?.length"><li v-for="(turn,index) in detail.data.turns" :key="index"><strong>{{ turn.author }}</strong><p class="preserve">{{ turn.text }}</p></li></ol>
        <template v-if="detail.data.summary">
          <p>{{ detail.data.summary.status === 'success' ? '通过门禁' : '未通过门禁' }} · {{ detail.data.summary.reason }}</p>
          <details v-if="detail.data.summary.attempts?.length"><summary>尝试与门禁结果</summary><pre class="preserve">{{ JSON.stringify(detail.data.summary.attempts, null, 2) }}</pre></details>
          <details v-if="detail.data.summary.diff"><summary>改动摘要</summary><pre class="preserve">{{ detail.data.summary.diff }}</pre></details>
        </template>
        <ul v-if="detail.data.result?.notes?.length"><li v-for="(item,i) in detail.data.result.notes" :key="i">{{ item }}</li></ul>
        <ul v-if="detail.data.steps?.length"><li v-for="(step,i) in detail.data.steps" :key="i">{{ step.title }} · {{ statuses[step.status || ''] || step.status }} · {{ step.detail }}</li></ul>
        <details v-for="(status,id) in detail.data.node_status" :key="id"><summary>{{ id }} · {{ statuses[status] || status }}</summary>
          <p class="preserve">{{ detail.data.node_outputs?.[id]?.answer }}</p></details>
        <details v-if="detail.data.trace"><summary>查看追踪</summary><pre class="preserve">{{ JSON.stringify(detail.data.trace, null, 2) }}</pre></details>
        <section v-if="pending && detail.data.kind === 'ingest'" class="business-form">
          <h3>核对并选择入库片段</h3>
          <label v-for="(part,index) in detail.data.result?.chunks" :key="index" class="check-line">
            <input v-model="chunks" type="checkbox" :value="index" :disabled="busy" /><span><strong>{{ part.title }}</strong><br /><span class="preserve">{{ part.content }}</span></span></label>
          <button type="button" class="primary" :disabled="busy || !chunks.length" @click="change('ingest')">确认选中片段入库</button>
        </section>
        <section v-else-if="pending" class="business-stack">
          <h3>待审批{{ detail.data.pending_node ? ' · ' + detail.data.pending_node : '' }}</h3>
          <p v-if="policy" class="preserve">{{ policy }}</p><pre v-if="calls?.length" class="preserve">{{ JSON.stringify(calls, null, 2) }}</pre>
          <div v-if="readyForDecision" class="business-actions"><button type="button" class="primary" :disabled="busy" @click="change('approve')">批准本次操作</button>
            <button type="button" class="secondary" :disabled="busy" @click="change('reject')">拒绝本次操作</button></div>
          <p v-else>没有可核对的操作详情，请刷新，不会自动批准。</p>
        </section>
        <button v-if="detail.data.kind === 'graph' && detail.data.status === 'running'" class="secondary" type="button" :disabled="busy" @click="change('resume')">核对后恢复中断流程</button>
        <form v-if="detail.data.kind === 'agent' && !detail.data.closed && detail.data.mode === 'model' && ['completed','fallback'].includes(detail.data.status)"
          class="business-form" @submit.prevent="change('continue')"><label>后续任务<textarea v-model="nextQuery" required maxlength="4000" rows="3" /></label>
          <button class="primary" :disabled="busy">继续会话</button></form>
        <button v-if="detail.data.kind === 'agent' && !detail.data.closed && ['completed','fallback','failed'].includes(detail.data.status)"
          class="secondary" type="button" :disabled="busy" @click="change('close')">关闭会话</button>
      </article>
    </template>
  </section>
</template>
