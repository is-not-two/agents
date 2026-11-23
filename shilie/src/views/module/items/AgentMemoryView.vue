<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { segment, type Row } from "@/records";
type Agent = Row<{ title: string; memory?: { scope: string } }>;
type Memory = Row<{ state: string; content: string; agent_version: number }>;
const agents = ref<Agent[]>([]), memory = ref<Memory[]>([]), id = ref(""), scope = ref("none"), content = ref("");
const busy = ref(false), error = ref(""), note = ref("");
const agent = computed(() => agents.value.find(row => row.id === id.value));
const path = () => "agents/" + segment(id.value) + "/memory";
const states: Record<string,string> = { pending: "待确认", confirmed: "已生效", rejected: "已拒绝", forgotten: "已遗忘" };
let proposal: { agent: string; version: number; content: string; key: string } | undefined;
async function action(fn: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function loadMemory() {
  scope.value = agent.value?.data.memory?.scope || "none";
  memory.value = agent.value ? await request(path()) : [];
}
function load() { return action(async () => {
  agents.value = await request("agents");
  if (!agent.value) id.value = agents.value[0]?.id || "";
  await loadMemory();
}); }
function pick(event: Event) { return action(async () => {
  id.value = (event.target as HTMLSelectElement).value; content.value = ""; memory.value = []; await loadMemory();
}); }
function saveScope() {
  const row = agent.value;
  if (!row || !confirm("更改此 Agent 的记忆范围？不会自动启用旧候选，也不会改变工具权限。")) return;
  return action(async () => {
    const saved = await send<Agent>("agents/" + segment(row.id), { version: row.version, data: { memory: { scope: scope.value } } }, "PUT");
    agents.value = agents.value.map(item => item.id === saved.id ? saved : item); await loadMemory(); note.value = "记忆范围已保存。";
  });
}
function propose() { return action(async () => {
  const row = agent.value, value = content.value.trim();
  if (!row || row.data.memory?.scope !== "persistent" || !value) return;
  if (proposal && (proposal.agent !== row.id || proposal.version !== row.version || proposal.content !== value))
    throw new Error("上次提交的结果未确认，请刷新核对或用原内容重试。");
  proposal ||= { agent: row.id, version: row.version, content: value, key: crypto.randomUUID() };
  await send(path(), { agent_version: row.version, content: value, request_id: proposal.key });
  proposal = undefined; content.value = ""; await loadMemory(); note.value = "已提交候选，尚未生效。";
}); }
function decide(row: Memory, op: "confirm" | "reject" | "forget") {
  const actionName = { confirm: "确认保存长期记忆", reject: "拒绝记忆", forget: "确认遗忘" }[op];
  if (!agent.value || !confirm(actionName + "？")) return;
  return action(async () => {
    if (!agent.value) return;
    await send(path() + "/" + segment(row.id) + "/decide", { version: row.version, agent_version: agent.value.version, action: op, confirmation: actionName });
    await loadMemory(); note.value = "已处理此条记忆。";
  });
}
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不读取或保存真实记忆。</p>
    <template v-else>
      <div class="business-form glass"><label>选择 Agent<select :value="id" :disabled="busy" @change="pick">
        <option v-for="row in agents" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
        <button type="button" class="secondary" :disabled="busy" @click="load">刷新记忆</button></div>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
      <template v-if="agent">
        <form class="business-form glass" @submit.prevent="saveScope">
          <label>记忆范围<select v-model="scope"><option value="none">不复用</option><option value="session">仅当前会话</option>
            <option value="persistent">已确认的长期记忆与会话</option></select></label>
          <button class="secondary" :disabled="busy || scope === (agent.data.memory?.scope || 'none')">保存范围</button>
        </form>
        <form class="business-form glass" @submit.prevent="propose">
          <h2>记忆候选</h2><p>只有逐条确认后才会被此 Agent 使用；遗忘停止未来引用，但不会物理擦除审计历史。</p>
          <label>拟记住的内容<textarea v-model="content" rows="3" maxlength="2000" required /></label>
          <button class="primary" :disabled="busy || agent.data.memory?.scope !== 'persistent'">提交候选（未生效）</button>
        </form>
        <article v-for="row in memory" :key="row.id" class="business-panel glass">
          <h2>{{ states[row.data.state] || row.data.state }}</h2><p class="preserve">{{ row.data.content }}</p>
          <div v-if="row.data.state === 'pending'" class="business-actions">
            <button type="button" class="primary" :disabled="busy || agent.data.memory?.scope !== 'persistent' || agent.version !== row.data.agent_version"
              @click="decide(row,'confirm')">确认长期记忆</button>
            <button type="button" class="secondary" :disabled="busy" @click="decide(row,'reject')">拒绝候选</button></div>
          <button v-if="row.data.state === 'confirmed'" type="button" class="secondary" :disabled="busy" @click="decide(row,'forget')">遗忘此条</button>
        </article>
      </template>
    </template>
  </section>
</template>
