<script setup lang="ts">
import { computed, defineAsyncComponent, onMounted, ref, watch } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { saveRecord, segment, type Fields, type Row } from "@/records";
import WorkflowEditor from "./WorkflowEditor.vue";
import AgentMemoryPanel from "./AgentMemoryPanel.vue";
const DraftProjects = defineAsyncComponent(() => import("./DraftProjectView.vue"));
type Advanced = { model?: { alias: string; temperature: number | null; max_tokens: number | null };
  budget?: { max_rounds: number | null; max_tool_calls: number | null; max_context_chars: number | null };
  context?: { strategy: string; max_messages: number; keep_recent_users: number }; result_limit?: number };
type Profile = { title: string; system_prompt: string; mode: "text" | "vector"; scopes: string[]; generate: boolean; tool_ids: string[];
  memory?: { scope: "none" | "session" | "persistent" } } & Advanced;
type Node = { id: string; type: "input" | "retrieve" | "tool" | "agent" | "merge" | "approval"; title?: string; tool_id?: string };
type Flow = Row<{ title: string; kind: string; nodes?: Node[]; edges?: string[][] }>;
type Draft = { mode: string; template: string; workflow: Flow["data"]; agents: { key: string; profile: Profile }[] };
type Run = Row<{ status: string; kind: string; result?: { answer?: string; notes?: string[] }; node_outputs?: Record<string, { answer?: string }>; started_at?: string;
  memory_project?: string; memory_refs?: { id: string; source_title?: string }[] }>;
const scopeLabels = { personal: "个人知识", docs: "技术文档", planning: "规划" };
const blank = (): Profile => ({ title: "", system_prompt: "", mode: "text", scopes: ["docs"], generate: false, tool_ids: [] });
const agents = ref<Row<Profile>[]>([]), flows = ref<Flow[]>([]), toolList = ref<{ name: string; description?: string; workflow_only?: boolean }[]>([]);
const editing = ref<Profile>(), editedAgent = ref<Row<Profile>>(), draft = ref<Draft>(), changes = ref<Record<string, unknown>>();
const advanced = ref(false);
const mode = ref<"rules" | "model">("rules"), template = ref("generic"), goal = ref(""), feedback = ref("");
const tab = ref("agent"), agentId = ref(""), flowId = ref(""), query = ref(""), run = ref<Run>();
const project = ref("");
watch(agentId, () => { project.value = ""; });
const flowEdit = ref<"create" | "edit">(), ingestTitle = ref(""), ingestSource = ref("");
const error = ref(""), note = ref(""), busy = ref(false);
const selectedAgent = computed(() => agents.value.find(row => row.id === agentId.value));
const selectedFlow = computed(() => flows.value.find(row => row.id === flowId.value));
const isInterview = computed(() => selectedFlow.value?.data.nodes?.some(node => node.tool_id === "interview_context"));
const output = computed(() => Object.entries(run.value?.data.node_outputs || {}).filter(([, item]) => item.answer));
async function load() {
  const [profiles, saved] = await Promise.all([request<Row<Profile>[]>("agents"), request<Flow[]>("workflows")]);
  agents.value = profiles; flows.value = saved;
  if (!selectedAgent.value) agentId.value = profiles[0]?.id || "";
  if (!selectedFlow.value) flowId.value = saved[0]?.id || "";
}
async function action(kind: "load" | "setup" | "saveAgent" | "draft" | "revise" | "saveDraft" | "runAgent" | "runFlow") {
  if (busy.value) return;
  if (kind === "draft" && template.value !== "interview" && mode.value === "model" && !confirm("将任务目标发送给已配置的模型来生成草稿？")) return;
  if (kind === "revise" && !confirm("将草稿及修改意见发送给已配置的模型？")) return;
  if (kind === "saveDraft" && !confirm("保存展示的 Agent 与工作流？此操作不会执行它们。")) return;
  const memoryProject = selectedAgent.value?.data.memory?.scope === "persistent" ? project.value.trim() : "";
  if ((kind === "runFlow" || kind === "runAgent") && !confirm(kind === "runAgent" && memoryProject
    ? `运行「${memoryProject}」任务？已确认的该项目笔记和记忆可能发送给配置的模型。`
    : "用当前保存的配置执行此任务？可能调用配置的模型和工具。")) return;
  busy.value = true; error.value = ""; note.value = "";
  try {
    if (kind === "load") {
      await load();
      toolList.value = (await request<{ builtin_tools: typeof toolList.value }>("capabilities")).builtin_tools.filter(item => !item.workflow_only);
    }
    if (kind === "setup") {
      await send("automation/setup", {});
      await load(); note.value = "基础流程已就绪，尚未执行。";
    }
    if (kind === "saveAgent" && editing.value) {
      const data = { ...editing.value };
      if (advanced.value && data.model && data.budget) {
        const optionalNumber = (value: unknown) => value === "" || value == null ? null : Number(value);
        data.model = { ...data.model, temperature: optionalNumber(data.model.temperature), max_tokens: optionalNumber(data.model.max_tokens) };
        data.budget = { max_rounds: optionalNumber(data.budget.max_rounds), max_tool_calls: optionalNumber(data.budget.max_tool_calls),
          max_context_chars: optionalNumber(data.budget.max_context_chars) };
      } else { delete data.model; delete data.budget; delete data.context; delete data.result_limit; }
      const row = await saveRecord("agents", data, editedAgent.value);
      agentId.value = row.id; editing.value = undefined; await load(); note.value = "Agent 已保存。";
    }
    if (kind === "draft") {
      draft.value = await send("automation/compose/draft", { goal: goal.value.trim(), mode: template.value === "interview" ? "rules" : mode.value, template: template.value });
      feedback.value = ""; changes.value = undefined;
    }
    if (kind === "revise" && draft.value) {
      const result = await send<{ draft: Draft; changes: Record<string, unknown> }>("automation/compose/revise", { draft: draft.value, feedback: feedback.value.trim() });
      draft.value = result.draft; changes.value = result.changes; feedback.value = "";
    }
    if (kind === "saveDraft" && draft.value) {
      const saved = await send<{ workflow_id: string; agent_ids: string[] }>("automation/compose/save", { draft: draft.value });
      draft.value = undefined; changes.value = undefined; flowId.value = saved.workflow_id; agentId.value = saved.agent_ids[0] || "";
      await load(); note.value = "已保存至同一套 Agent 与工作流。"; tab.value = "flow";
    }
    if (kind === "runAgent" && selectedAgent.value) {
      run.value = undefined;
      const { id, version } = selectedAgent.value;
      run.value = await send("agents/" + segment(id) + "/run", { version, query: query.value.trim(), project: memoryProject });
    }
    if (kind === "runFlow" && selectedFlow.value && !isInterview.value) {
      run.value = undefined;
      const { id, version, data } = selectedFlow.value;
      const input = data.kind === "ingest" ? { title: ingestTitle.value.trim(), source: ingestSource.value.trim(), content: query.value.trim() } : { query: query.value.trim() };
      run.value = await send("workflows/" + segment(id) + "/run", { version, input });
    }
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function edit(row?: Row<Profile>) {
  editedAgent.value = row;
  advanced.value = false;
  const p = row?.data;
  editing.value = p ? { title: p.title, system_prompt: p.system_prompt, scopes: [...p.scopes], mode: p.mode,
    generate: p.generate, tool_ids: [...p.tool_ids] } : blank();
  editing.value.memory = { scope: p?.memory?.scope ?? "none" };
}
function showAdvanced() {
  const value = editing.value, existing = editedAgent.value?.data;
  if (!value) return;
  value.model ||= { alias: "", temperature: null, max_tokens: null, ...existing?.model };
  value.budget ||= { max_rounds: null, max_tool_calls: null, max_context_chars: null, ...existing?.budget };
  value.context ||= { strategy: "window", max_messages: 20, keep_recent_users: 2, ...existing?.context };
  value.result_limit ??= existing?.result_limit ?? 5;
  advanced.value = true;
}
function pick(value: string) { tab.value = value; run.value = undefined; flowEdit.value = undefined; error.value = ""; note.value = ""; }
async function flowSaved(row: Row<Fields>) {
  flowEdit.value = undefined; flowId.value = row.id;
  await action("load");
  if (!error.value) note.value = "工作流已保存，未运行。";
}
onMounted(() => { if (!isDemo) void action("load"); });
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示环境不运行 Agent。连接单用户后端后可创建、配置并执行。</p>
    <template v-else>
      <nav class="business-actions" aria-label="Agent 工作室功能">
        <button v-for="[id,label] in [['agent','我的 Agent'],['project','草稿项目'],['draft','用目标起草'],['flow','已保存流程']]" :key="id"
          type="button" :class="tab === id ? 'primary' : 'secondary'" :aria-pressed="tab === id" :disabled="busy" @click="pick(id)">{{ label }}</button>
      </nav>
      <DraftProjects v-if="tab === 'project'" />
      <p v-if="busy" role="status">正在处理…</p><p v-if="note" role="status">{{ note }}</p>
      <p v-if="error" class="form-error" role="alert">{{ error }}</p>
      <div v-if="tab === 'agent'" class="business-form glass">
        <label>Agent<select v-model="agentId" :disabled="busy" @change="run = undefined; editing = undefined">
          <option value="">未选择</option><option v-for="row in agents" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
        <div class="business-actions"><button class="primary" type="button" :disabled="busy" @click="edit()">新建 Agent</button>
          <button class="secondary" type="button" :disabled="busy || !selectedAgent" @click="edit(selectedAgent)">编辑 Agent</button></div>
      </div>
      <form v-if="tab === 'agent' && editing" class="business-form glass" @submit.prevent="action('saveAgent')">
        <label>名称<input v-model="editing.title" required maxlength="160" /></label>
        <label>角色指令<textarea v-model="editing.system_prompt" rows="5" maxlength="10000" /></label>
        <fieldset><legend>允许检索</legend><label v-for="(label,key) in scopeLabels" :key="key" class="check-line">
          <input type="checkbox" v-model="editing.scopes" :value="key" /> {{ label }}</label></fieldset>
        <label>检索方式<select v-model="editing.mode"><option value="text">全文</option><option value="vector">技术文档向量</option></select></label>
        <label class="check-line"><input type="checkbox" v-model="editing.generate" /> 使用模型生成</label>
        <label v-if="editing.memory">记忆<select v-model="editing.memory.scope" aria-label="记忆">
          <option value="none">关闭</option><option value="session">仅当前会话</option><option value="persistent">长期记忆</option></select></label>
        <fieldset v-if="toolList.length"><legend>可用的内置工具</legend><label v-for="tool in toolList" :key="tool.name" class="check-line">
          <input type="checkbox" v-model="editing.tool_ids" :value="tool.name" /> {{ tool.name }}{{ tool.description ? ' · ' + tool.description : '' }}</label></fieldset>
        <button v-if="!advanced" type="button" class="secondary" @click="showAdvanced">展开模型、预算与上下文</button>
        <fieldset v-if="advanced && editing.model && editing.budget && editing.context" class="business-form">
          <legend>模型、预算与上下文</legend><p>留空继承后端默认值；不提高管理员上限。</p>
          <div class="business-columns">
            <label>模型别名<input v-model="editing.model.alias" maxlength="64" /></label>
            <label>温度<input v-model.number="editing.model.temperature" type="number" min="0" max="2" step="any" /></label>
            <label>输出 token 上限<input v-model.number="editing.model.max_tokens" type="number" min="1" max="1000000" /></label>
            <label>累计模型轮数<input v-model.number="editing.budget.max_rounds" type="number" min="1" max="1000000" /></label>
            <label>累计工具次数<input v-model.number="editing.budget.max_tool_calls" type="number" min="1" max="1000000" /></label>
            <label>请求字符上限<input v-model.number="editing.budget.max_context_chars" type="number" min="1" max="1000000" /></label>
            <label>引用数量<input v-model.number="editing.result_limit" type="number" min="1" max="10" required /></label>
            <label>上下文策略<select v-model="editing.context.strategy"><option value="window">完整窗口</option><option value="verbatim_window">逐字折叠</option></select></label>
            <label>消息上限<input v-model.number="editing.context.max_messages" type="number" min="2" max="1000" required /></label>
            <label>逐字保留最近用户消息数<input v-model.number="editing.context.keep_recent_users" type="number" min="1" max="20" required /></label>
          </div>
        </fieldset>
        <div class="business-actions"><button class="primary" :disabled="busy || !editing.scopes.length">保存 Agent</button>
          <button class="secondary" type="button" @click="editing = undefined">取消</button></div>
      </form>
      <form v-if="tab === 'draft'" class="business-form glass" @submit.prevent="action('draft')">
        <label>任务目标<textarea v-model="goal" required rows="3" maxlength="1000" /></label>
        <label>草稿类型<select v-model="template"><option value="generic">通用</option><option value="code">代码改动</option><option value="interview">预面试</option></select></label>
        <label v-if="template !== 'interview'">起草方式<select v-model="mode"><option value="rules">本地规则</option><option value="model">模型</option></select></label>
        <button class="primary" :disabled="busy">生成草稿</button>
      </form>
      <article v-if="tab === 'draft' && draft" class="business-panel glass">
        <h2>{{ draft.workflow.title }}</h2><p>尚未保存、没有执行。</p>
        <ul><li v-for="node in draft.workflow.nodes" :key="node.id">{{ node.title || node.id }} · {{ node.type }}</li></ul>
        <p v-for="edge in draft.workflow.edges" :key="edge.join(':')">{{ edge.join(' → ') }}</p>
        <details v-for="agent in draft.agents" :key="agent.key"><summary>{{ agent.profile.title }}</summary>
          <p class="preserve">{{ agent.profile.system_prompt }}</p><p>授权工具：{{ agent.profile.tool_ids?.join('、') || '无' }}</p></details>
        <details v-if="changes"><summary>查看结构变更</summary><pre class="preserve">{{ JSON.stringify(changes, null, 2) }}</pre></details>
        <form class="business-form" @submit.prevent="action('revise')"><label>修改意见<textarea v-model="feedback" rows="2" required maxlength="2000" /></label>
          <div class="business-actions"><button class="secondary" :disabled="busy">根据意见修改</button>
            <button type="button" class="primary" :disabled="busy" @click="action('saveDraft')">确认并保存草稿</button></div></form>
      </article>
      <div v-if="tab === 'flow'" class="business-form glass">
        <label>工作流<select v-model="flowId" :disabled="busy" @change="run = undefined; flowEdit = undefined"><option value="">未选择</option>
          <option v-for="row in flows" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label>
        <ul v-if="selectedFlow?.data.nodes?.length"><li v-for="node in selectedFlow.data.nodes" :key="node.id">{{ node.title || node.id }} · {{ node.type }}</li></ul>
        <div class="business-actions"><button v-if="!flows.length && !error" type="button" class="secondary" :disabled="busy" @click="action('setup')">启用基础流程</button>
          <button type="button" class="primary" :disabled="busy" @click="flowEdit = 'create'">手动新建工作流</button>
          <button type="button" class="secondary" :disabled="busy || !selectedFlow || isInterview" @click="flowEdit = 'edit'">编辑工作流</button></div>
        <RouterLink v-if="isInterview" class="secondary" to="/module/job-flow">去公司流水线选择简历与岗位</RouterLink>
      </div>
      <WorkflowEditor v-if="tab === 'flow' && flowEdit" :key="flowEdit + flowId" :current="flowEdit === 'edit' ? selectedFlow : undefined"
        :agents="agents" @saved="flowSaved" @cancel="flowEdit = undefined" />
      <AgentMemoryPanel v-if="tab === 'agent' && !editing && selectedAgent?.data.memory?.scope === 'persistent'"
        :key="selectedAgent.id" :agent="selectedAgent" :disabled="busy" v-model="project" />
      <form v-if="(tab === 'agent' && selectedAgent && !editing) || (tab === 'flow' && selectedFlow && !isInterview && !flowEdit)"
        class="business-form glass" @submit.prevent="action(tab === 'agent' ? 'runAgent' : 'runFlow')">
        <template v-if="tab === 'flow' && selectedFlow?.data.kind === 'ingest'">
          <label>知识标题<input v-model="ingestTitle" maxlength="160" required /></label><label>来源<input v-model="ingestSource" maxlength="1000" /></label>
        </template>
        <label>运行任务<textarea v-model="query" rows="3" required
          :maxlength="tab === 'agent' ? 4000 : selectedFlow?.data.kind === 'ingest' ? 100000 : selectedFlow?.data.kind === 'answer' ? 1000 : 4000" /></label>
        <button class="primary" :disabled="busy">确认并运行</button>
      </form>
      <article v-if="run" class="business-panel glass"><h2>本次运行</h2><p>状态：{{ run.data.status }}</p>
        <p v-if="run.data.memory_project">记忆项目：{{ run.data.memory_project }} · {{ run.data.memory_refs?.length || 0 }} 条参考
          <template v-for="ref in run.data.memory_refs" :key="ref.id">{{ ref.source_title ? ' · ' + ref.source_title : '' }}</template></p>
        <p v-if="run.data.result?.answer" class="preserve">{{ run.data.result.answer }}</p>
        <p v-for="item in run.data.result?.notes" :key="item">{{ item }}</p>
        <details v-for="[id,item] in output" :key="id"><summary>{{ id }}</summary><p class="preserve">{{ item.answer }}</p></details>
        <RouterLink class="secondary" :to="{ path: '/module/runs', query: { run: run.id, kind: run.data.kind } }">
          {{ run.data.status === 'awaiting_confirmation' ? '审阅待确认操作' : '查看运行记录' }}</RouterLink>
      </article>
    </template>
  </section>
</template>
