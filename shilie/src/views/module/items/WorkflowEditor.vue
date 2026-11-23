<script setup lang="ts">
import { computed, ref } from "vue";
import { messageOf } from "@/api";
import { saveRecord, type Fields, type Row } from "@/records";
type Kind = "input" | "retrieve" | "tool" | "agent" | "merge" | "approval";
type Node = Fields & { id: string; type: Kind; agent_id?: string; query?: string; limit?: number; tool_id?: string;
  arguments?: Fields; message?: string; on_error?: string; fallback?: Fields; timeout_s?: number; retry?: Fields };
type Config = Fields & { kind: string; title: string; agent_id?: string; nodes?: Node[]; edges?: string[][]; max_parallel?: number;
  max_retries?: number; node_timeout_seconds?: number; join_policy?: string; chunk_size?: number };
type Agent = Row<{ title: string }>;
const props = defineProps<{ current?: Row<Config>; agents: Agent[] }>();
const emit = defineEmits<{ saved: [row: Row<Config>]; cancel: [] }>();
const initial: Config = { kind: "graph", title: "", agent_id: "", nodes: [{ id: "input", type: "input" }, { id: "answer", type: "agent", query: "{{input.query}}" }],
  edges: [["input", "answer"]], max_parallel: 1, max_retries: 1, node_timeout_seconds: 60, join_policy: "all_success", chunk_size: 1500 };
const cfg = ref<Config>(JSON.parse(JSON.stringify({ ...initial, ...props.current?.data })));
const labels: Record<Kind, string> = { input: "输入", retrieve: "检索", agent: "Agent", tool: "调用工具", merge: "合并结果", approval: "人工确认" };
const errorModes = { fail: "停止", continue: "继续", fallback: "使用备用结果" };
const busy = ref(false), error = ref("");
const args = ref<Record<string, string>>({}), fallbacks = ref<Record<string, string>>({});
const nodes = computed(() => cfg.value.nodes ?? []);
const edges = computed(() => cfg.value.edges ?? []);
const edge = ref({ from: "input", to: "" });
const newType = ref<Exclude<Kind,"input">>("agent"), newId = ref("");
const nodeTypes = computed(() => Object.keys(labels).filter(type => type !== "input") as Exclude<Kind,"input">[]);
for (const item of nodes.value) {
  if (item.arguments) args.value[item.id] = JSON.stringify(item.arguments, null, 2);
  if (item.fallback) fallbacks.value[item.id] = JSON.stringify(item.fallback, null, 2);
}
function addNode() {
  const id = newId.value.trim();
  if (!/^[a-z][a-z0-9_-]{0,40}$/.test(id) || nodes.value.some(node => node.id === id)) {
    error.value = "节点 ID 须唯一，用小写字母开头，最多 41 个字符。"; return;
  }
  if (nodes.value.length >= 30) return;
  const type = newType.value, node: Node = { id, type };
  if (type === "retrieve") Object.assign(node, { query: "{{input.query}}", limit: 5 });
  if (type === "agent") node.query = "{{input.query}}";
  if (type === "tool") { node.tool_id = ""; args.value[id] = "{}"; }
  if (type === "approval") node.message = "";
  cfg.value.nodes = [...nodes.value, node]; newId.value = ""; error.value = "";
}
function removeNode(node: Node) {
  cfg.value.nodes = nodes.value.filter(item => item.id !== node.id);
  cfg.value.edges = edges.value.filter(pair => !pair.includes(node.id));
  if (edge.value.from === node.id) edge.value.from = "";
  if (edge.value.to === node.id) edge.value.to = "";
  delete args.value[node.id]; delete fallbacks.value[node.id];
}
function addEdge() {
  const { from, to } = edge.value;
  if (!from || !to || from === to || !nodes.value.some(node => node.id === from) ||
      !nodes.value.some(node => node.id === to && node.type !== "input")) return;
  if (edges.value.some(pair => pair[0] === from && pair[1] === to) || edges.value.length >= 100) return;
  cfg.value.edges = [...edges.value, [from, to]]; edge.value.to = ""; error.value = "";
}
function object(text: string, label: string): Fields {
  let value: unknown;
  try { value = JSON.parse(text); } catch { throw new Error(label + "须为有效 JSON 对象。"); }
  if (!value || typeof value !== "object" || Array.isArray(value)) throw new Error(label + "须为 JSON 对象。");
  return value as Fields;
}
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    const data = { ...cfg.value, title: cfg.value.title.trim() };
    if (data.kind === "graph") {
      data.nodes = nodes.value.map(item => {
        const node = { ...item };
        if (node.type === "tool") node.arguments = object(args.value[node.id] ?? "{}", node.id + " 的参数");
        if (node.on_error === "fallback") node.fallback = object(fallbacks.value[node.id] || "", node.id + " 的备用结果");
        else delete node.fallback;
        return node;
      });
      data.edges = edges.value;
    }
    emit("saved", await saveRecord("workflows", data, props.current));
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
</script>
<template>
  <form class="business-form glass" @submit.prevent="save">
    <h2>{{ current ? '编辑工作流' : '新建工作流' }}</h2><p>保存配置不运行任务。保存前由后端检查权限、连线和循环。</p>
    <label>流程名称<input v-model="cfg.title" required maxlength="160" /></label>
    <label>流程类型<select v-model="cfg.kind" :disabled="!!current"><option value="graph">自定义 DAG</option>
      <option value="answer">检索回答</option><option value="ingest">知识入库</option></select></label>
    <label v-if="cfg.kind !== 'ingest'">默认 Agent<select v-model="cfg.agent_id" :required="cfg.kind === 'answer'">
      <option value="">节点分别指定</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.data.title }}</option></select></label>
    <label v-if="cfg.kind === 'ingest'">片段字数<input v-model.number="cfg.chunk_size" type="number" min="200" max="6000" required /></label>
    <template v-if="cfg.kind === 'graph'">
      <div class="business-columns"><label>最大并行<input v-model.number="cfg.max_parallel" type="number" min="1" max="4" required /></label>
        <label>默认重试次数<input v-model.number="cfg.max_retries" type="number" min="0" max="3" required /></label>
        <label>默认超时（秒）<input v-model.number="cfg.node_timeout_seconds" type="number" min="5" max="300" required /></label>
        <label>汇合策略<select v-model="cfg.join_policy"><option value="all_success">所有分支成功</option><option value="any_success">任一分支成功</option></select></label></div>
      <fieldset v-for="node in nodes" :key="node.id" class="business-form">
        <legend>{{ node.id }} · {{ labels[node.type] }}</legend>
        <label v-if="['retrieve','agent','tool'].includes(node.type)">节点 Agent<select v-model="node.agent_id">
          <option value="">使用默认 Agent</option><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.data.title }}</option></select></label>
        <label v-if="node.type === 'agent' || node.type === 'retrieve'">查询或指令<textarea v-model="node.query" :required="node.type === 'agent'"
          :maxlength="node.type === 'agent' ? 4000 : 2000" rows="3" /></label>
        <label v-if="node.type === 'retrieve'">引用数量<input v-model.number="node.limit" type="number" min="1" max="10" required /></label>
        <template v-if="node.type === 'tool'"><label>工具标识<input v-model="node.tool_id" maxlength="64" required /></label>
          <label>工具参数（JSON 对象）<textarea v-model="args[node.id]" rows="3" maxlength="16000" required /></label></template>
        <label v-if="node.type === 'approval'">需要确认的内容<input v-model="node.message" maxlength="1000" required /></label>
        <template v-if="['retrieve','agent','tool','merge'].includes(node.type)">
          <label>节点失败策略<select v-model="node.on_error"><option :value="undefined">默认停止</option>
            <option v-for="(label,key) in errorModes" :key="key" :value="key">{{ label }}</option></select></label>
          <label v-if="node.on_error === 'fallback'">备用结果（JSON 对象）<textarea v-model="fallbacks[node.id]" maxlength="16000" rows="3" required /></label>
        </template>
        <button v-if="node.type !== 'input'" type="button" class="secondary" @click="removeNode(node)">移除此节点和相关连线</button>
      </fieldset>
      <div class="business-columns"><label>新节点 ID<input v-model="newId" maxlength="41" /></label>
        <label>新节点类型<select v-model="newType"><option v-for="kind in nodeTypes" :key="kind" :value="kind">{{ labels[kind] }}</option></select></label>
        <button type="button" class="secondary" :disabled="nodes.length >= 30" @click="addNode">添加节点</button></div>
      <fieldset class="business-form"><legend>连线</legend>
        <ul><li v-for="(pair,index) in edges" :key="pair.join(':')">{{ pair.join(' → ') }}
          <button class="secondary" type="button" @click="cfg.edges?.splice(index,1)">移除连线</button></li></ul>
        <div class="business-columns"><label>起点<select v-model="edge.from"><option value="">选择起点</option>
          <option v-for="node in nodes" :key="node.id">{{ node.id }}</option></select></label>
          <label>终点<select v-model="edge.to"><option value="">选择终点</option>
            <option v-for="node in nodes.filter(item => item.type !== 'input' && item.id !== edge.from)" :key="node.id">{{ node.id }}</option></select></label></div>
        <button type="button" class="secondary" :disabled="!edge.from || !edge.to || edges.length >= 100" @click="addEdge">添加连线</button>
      </fieldset>
    </template>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <div class="business-actions"><button class="primary" :disabled="busy">保存工作流</button>
      <button type="button" class="secondary" :disabled="busy" @click="emit('cancel')">取消</button></div>
  </form>
</template>
