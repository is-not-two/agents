<script setup lang="ts">
import { computed, onMounted, ref, watch } from "vue";
import { useRoute } from "vue-router";
import { isDemo, messageOf, request, send } from "@/api";
import { dateText, segment, type Row } from "@/records";
type Job = { id: string; kind: "team" | "loop"; status: string; attempts: number; max_attempts: number; last_error: string; priority: number; updated_at: string;
  payload?: unknown; result?: unknown; checkpoint?: unknown };
const statuses: Record<string, string> = { queued: "排队中", running: "运行中", succeeded: "成功", dead: "死信", cancelled: "已取消" };
const path = "automation/queue";
const jobs = ref<Job[]>([]), detail = ref<Job>(), stats = ref<Record<string, number>>(), agents = ref<Row<{ title: string }>[]>([]);
const roots = ref<{ name: string; title?: string; writable: boolean }[]>([]), filter = ref(""), busy = ref(false), error = ref(""), note = ref(""), setupError = ref("");
const route = useRoute();
const immediate = computed(() => route.query.launch === "now");
const show = ref(immediate.value), kind = ref<"team" | "loop">("team"), allowWrites = ref(false);
type Result = { id: string; final?: string; turns?: { author: string; text: string }[]; status?: string; reason?: string; diff?: string; attempts?: unknown[] };
const result = ref<Result>(), resultKind = ref<"team" | "loop">("team");
const team = ref({ agent_ids: [] as string[], task: "", mode: "group_chat", max_rounds: 6 });
const loop = ref({ root: "", task: "", gate: "", engine: "opencode", tier: "patch" });
const attempts = ref(3), priority = ref(50);
const eligibleRoots = computed(() => roots.value.filter(root => !immediate.value || root.writable));
let token: { body: string; key: string } | undefined;
const valid = computed(() => kind.value === "team"
  ? team.value.agent_ids.length > 0 && team.value.agent_ids.length <= 4 && !!team.value.task.trim()
  : eligibleRoots.value.some(item => item.name === loop.value.root) && loop.value.task.trim().length >= 2 && loop.value.gate.trim().length >= 2);
async function load() {
  [jobs.value, stats.value] = await Promise.all([request<Job[]>(path + "?" + new URLSearchParams({ status: filter.value })),
    request<Record<string, number>>(path + "/stats")]);
}
async function action(fn: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function loadConfig() {
  return Promise.all([request<typeof agents.value>("agents"), request<typeof roots.value>("automation/code-roots")])
    .then(([a, r]) => { agents.value = a; roots.value = r; setupError.value = ""; })
    .catch(reason => { setupError.value = messageOf(reason); });
}
function inspect(id: string) { return action(async () => { detail.value = await request(path + "/" + segment(id)); }); }
function refresh() { return action(async () => {
  await load();
  if (detail.value) detail.value = await request(path + "/" + segment(detail.value.id));
}); }
function operation(job: Job, op: "cancel" | "replay") {
  if (!confirm(op === "cancel" ? "取消此任务？已发生的操作不会自动撤销。"
    : "确认重放这条死信？可能重新调用模型或执行操作。")) return;
  return action(async () => {
    await send(path + "/" + segment(job.id) + "/" + op, {});
    detail.value = await request(path + "/" + segment(job.id)); await load();
    note.value = op === "cancel" ? "已请求取消。" : "已重新入队。";
  });
}
function enqueue() {
  if (!valid.value || !confirm(kind.value === "loop"
    ? "将编码任务加入队列？工作进程可能修改所选工作区并运行门禁命令。"
    : "将协作任务加入队列？工作进程可能调用配置的模型和工具。")) return;
  return action(async () => {
    const body = { kind: kind.value, payload: kind.value === "team" ? { ...team.value, approved: false } : { ...loop.value },
      max_attempts: attempts.value, priority: priority.value };
    const raw = JSON.stringify(body);
    if (token && token.body !== raw) throw new Error("上次入队结果未确认。请核对队列，再恢复原表单重试，避免重复入队。");
    token ||= { body: raw, key: crypto.randomUUID() };
    const saved = await send<Job>(path, { ...body, idempotency_key: token.key });
    token = undefined; show.value = false; detail.value = saved; note.value = "已入队，等待工作进程。"; await load();
  });
}
function runNow() {
  if (!valid.value || busy.value || !immediate.value) return;
  const type = kind.value, approved = allowWrites.value;
  if (!confirm(type === "loop" ? "立即在隔离副本中运行编码和验收门禁？"
    : approved ? "立即运行团队，并允许本轮执行成员已获授权的写工具？" : "立即运行团队？本轮不批准写操作。")) return;
  const payload = type === "team" ? { ...team.value, approved } : { ...loop.value };
  allowWrites.value = false;
  return action(async () => {
    result.value = undefined; resultKind.value = type;
    try { result.value = await send<Result>(type === "team" ? "automation/teams/run" : "automation/loop/run", payload); }
    catch (reason) { throw new Error(messageOf(reason) + "。请求可能已在服务端启动，请先核对运行记录，不要直接重试。"); }
  });
}
watch(immediate, value => {
  show.value = value; allowWrites.value = false;
  if (!busy.value) {
    error.value = ""; note.value = "";
    if (!value) void action(load);
  }
});
watch(filter, () => void action(load));
onMounted(() => { if (!isDemo) { void loadConfig(); if (!immediate.value) void action(load); } });
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不会排队或运行真实任务。</p>
    <template v-else>
      <div class="business-actions"><RouterLink v-if="!busy" class="secondary" :to="{ query: immediate ? {} : { launch: 'now' } }">{{ immediate ? '返回任务队列' : '即时运行' }}</RouterLink>
        <RouterLink v-if="immediate" class="secondary" to="/module/runs">查看运行记录</RouterLink>
        <button v-if="!immediate" class="primary" type="button" :disabled="busy" @click="show = !show">新建队列任务</button>
        <button v-if="!immediate" class="secondary" type="button" :disabled="busy" @click="refresh">刷新队列</button></div>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
      <form v-if="show" class="business-form glass" @submit.prevent="immediate ? runNow() : enqueue()">
        <h2>{{ immediate ? '即时运行参数' : '任务参数' }}</h2><p v-if="setupError" role="alert" class="form-error">{{ setupError }}</p>
        <label>类型<select v-model="kind"><option value="team">团队协作</option><option value="loop">自动编码</option></select></label>
        <template v-if="kind === 'team'"><fieldset><legend>选择 1–4 个 Agent</legend>
          <label v-for="agent in agents" :key="agent.id" class="check-line"><input v-model="team.agent_ids" type="checkbox" :value="agent.id"
            :disabled="team.agent_ids.length >= 4 && !team.agent_ids.includes(agent.id)" /> {{ agent.data.title }}</label>
          <p v-if="!agents.length">请先在 Agent 工作室创建成员。</p></fieldset>
          <label>团队目标<textarea v-model="team.task" rows="3" maxlength="2000" required /></label>
          <label>协作方式<select v-model="team.mode"><option value="group_chat">依次发言</option><option value="magentic">自动规划</option></select></label>
          <label>最多轮次<input v-model.number="team.max_rounds" type="number" min="1" max="12" required /></label>
          <label v-if="immediate" class="check-line"><input v-model="allowWrites" type="checkbox" /> 仅本轮允许使用成员已获授权的写工具</label>
        </template>
        <template v-else>
          <label>代码工作区<select v-model="loop.root" required><option value="">选择服务端登记的工作区</option>
            <option v-for="root in eligibleRoots" :key="root.name" :value="root.name">{{ root.title || root.name }}</option></select></label>
          <p v-if="immediate && !eligibleRoots.length">没有登记为可写的代码工作区。</p>
          <label>改动目标<textarea v-model="loop.task" rows="3" minlength="2" maxlength="2000" required /></label>
          <label>验收门禁命令<input v-model="loop.gate" minlength="2" maxlength="1000" required /></label>
          <label>执行器<select v-model="loop.engine"><option value="opencode">OpenCode</option><option value="aider">Aider</option><option value="model">模型</option></select></label>
          <label>预算<select v-model="loop.tier"><option value="patch">小修</option><option value="feature">功能</option><option value="epic">大任务</option></select></label>
        </template>
        <template v-if="!immediate">
          <label>最大尝试次数<input v-model.number="attempts" type="number" min="1" max="10" required /></label>
          <label>优先级<input v-model.number="priority" type="number" min="0" max="100" required /></label>
        </template>
        <button class="primary" :disabled="busy || !valid">{{ immediate ? '确认立即运行' : '确认入队' }}</button>
        <p v-if="immediate && busy" role="status">等待服务端结果；离开页面不会取消服务端任务。</p>
      </form>
      <article v-if="immediate && result" class="business-panel glass">
        <h2>本次运行结果</h2>
        <p v-if="result.status">{{ result.status === 'success' ? '通过门禁' : '未通过门禁' }} · {{ result.reason }}</p>
        <p v-if="result.final" class="preserve">{{ result.final }}</p>
        <ol v-if="result.turns?.length"><li v-for="(turn,index) in result.turns" :key="index"><strong>{{ turn.author }}</strong><p class="preserve">{{ turn.text }}</p></li></ol>
        <details v-if="result.attempts?.length"><summary>尝试与门禁结果</summary><pre class="preserve">{{ JSON.stringify(result.attempts, null, 2) }}</pre></details>
        <details v-if="result.diff"><summary>改动摘要</summary><pre class="preserve">{{ result.diff }}</pre></details>
        <RouterLink :to="{ path: '/module/runs', query: { run: result.id, kind: resultKind } }">回看本次运行</RouterLink>
      </article>
      <template v-if="!immediate">
      <div class="business-form glass"><label>任务状态<select v-model="filter" :disabled="busy"><option value="">全部</option>
        <option v-for="(label,key) in statuses" :key="key" :value="key">{{ label }}</option></select></label>
        <dl v-if="stats" class="business-fields"><template v-for="(label,key) in statuses" :key="key"><dt>{{ label }}</dt><dd>{{ stats[key] || 0 }}</dd></template></dl>
      </div>
      <p v-if="!jobs.length && !busy && !error">当前没有任务。</p>
      <article v-for="job in jobs" :key="job.id" class="business-panel glass"><h2>{{ job.kind === 'team' ? '团队协作' : '自动编码' }} · {{ statuses[job.status] }}</h2>
        <p>{{ job.id }} · {{ job.attempts }}/{{ job.max_attempts }} 次 · {{ dateText(job.updated_at) }}</p>
        <p v-if="job.last_error" class="form-error">{{ job.last_error }}</p>
        <div class="business-actions"><button class="secondary" type="button" :disabled="busy" @click="inspect(job.id)">查看详情</button>
          <button v-if="['queued','running'].includes(job.status)" class="secondary" type="button" :disabled="busy" @click="operation(job, 'cancel')">取消任务</button>
          <button v-if="job.status === 'dead'" class="secondary" type="button" :disabled="busy" @click="operation(job, 'replay')">重放死信</button></div>
      </article>
      </template>
      <article v-if="detail" class="business-panel glass"><h2>任务详情</h2><p>{{ detail.id }} · {{ statuses[detail.status] }}</p>
        <details v-for="[label,value] in [['参数',detail.payload],['检查点',detail.checkpoint],['结果',detail.result]].filter(([,value]) => value != null)"
          :key="String(label)"><summary>{{ label }}</summary><pre class="preserve">{{ JSON.stringify(value, null, 2) }}</pre></details>
        <button class="secondary" type="button" @click="detail = undefined">关闭详情</button>
      </article>
    </template>
  </section>
</template>
