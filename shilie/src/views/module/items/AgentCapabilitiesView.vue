<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { segment, type Row } from "@/records";
type Skill = { name: string; description: string; revision: string; content: string; repository_path?: string };
type Server = { id: string; enabled: boolean; trusted: boolean; transport: string };
type Tool = { name: string; description?: string; server_id?: string };
type Grants = { skill_ids: string[]; mcp_server_ids: string[]; tool_ids: string[] };
type Agent = Row<{ title: string } & Grants>;
type Preview = { import_id: string; commit: string; repo_url: string; skills: Record<string,Skill>; warnings: string[] };
const empty = (): Grants => ({ skill_ids: [], mcp_server_ids: [], tool_ids: [] });
const tab = ref("grants"), agents = ref<Agent[]>([]), id = ref(""), grants = ref<Grants>(empty());
const skills = ref<Skill[]>([]), servers = ref<Server[]>([]), tools = ref<Tool[]>([]), discovery = ref<Tool[]>([]);
const selection = ref(""), name = ref(""), content = ref(""), loaded = ref<Skill>(), edit = ref(false);
const repository = ref(""), branch = ref(""), preview = ref<Preview>(), chosen = ref<string[]>([]);
const busy = ref(false), error = ref(""), note = ref("");
const current = computed(() => agents.value.find(row => row.id === id.value));
function fill() {
  const data = current.value?.data;
  grants.value = { skill_ids: [...(data?.skill_ids || [])], mcp_server_ids: [...(data?.mcp_server_ids || [])], tool_ids: [...(data?.tool_ids || [])] };
}
async function action(fn: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function load() { return action(async () => {
  const [a,s,m,c] = await Promise.all([request<Agent[]>("agents"), request<Skill[]>("skills"), request<Server[]>("mcp/servers"),
    request<{ builtin_tools: Tool[]; http_tools: Tool[] }>("capabilities")]);
  agents.value = a; skills.value = s; servers.value = m; tools.value = [...c.builtin_tools, ...c.http_tools];
  if (!current.value) id.value = a[0]?.id || "";
  fill();
}); }
function saveGrants() {
  const agent = current.value;
  if (!agent || !confirm("更新此 Agent 的能力授权？不会立即调用工具。")) return;
  return action(async () => {
    const selectedServers = discovery.value.filter(tool => grants.value.tool_ids.includes(tool.name)).map(tool => tool.server_id).filter((server): server is string => !!server);
    const saved = await send<Agent>("agents/" + segment(agent.id), { version: agent.version, data: {
      ...grants.value, mcp_server_ids: [...new Set([...grants.value.mcp_server_ids, ...selectedServers])],
    } }, "PUT");
    agents.value = agents.value.map(row => row.id === saved.id ? saved : row); fill(); note.value = "已保存权限。";
  });
}
function discover(server?: Server) {
  if (!confirm(server ? "测试这个已配置的 MCP 服务连接？不会执行工具。" : "读取已信任 MCP 服务的工具清单？不会执行工具。")) return;
  return action(async () => {
    if (server) {
      const result = await send<{ tools: Tool[] }>("mcp/servers/" + segment(server.id) + "/test", {});
      discovery.value = [...discovery.value.filter(tool => tool.server_id !== server.id), ...result.tools.map(tool => ({ ...tool, server_id: server.id }))];
      note.value = "MCP 连接成功，发现 " + result.tools.length + " 个工具。";
    } else {
      const result = await request<{ mcp: Tool[]; mcp_errors: { server_id: string; error: string }[] }>("capabilities/tools");
      discovery.value = result.mcp;
      if (result.mcp_errors.length) error.value = result.mcp_errors.map(item => item.server_id + "：" + item.error).join("；");
    }
  });
}
function newSkill() { loaded.value = undefined; name.value = ""; content.value = ""; edit.value = true; }
function openSkill() { return action(async () => {
  if (!selection.value) return;
  loaded.value = await request("skills/" + segment(selection.value));
  name.value = loaded.value!.name; content.value = loaded.value!.content; edit.value = true;
}); }
function saveSkill() { return action(async () => {
  const saved = await send<Skill>("skills/" + segment(name.value), { content: content.value, revision: loaded.value?.revision ?? null }, "PUT");
  skills.value = await request("skills"); loaded.value = saved; selection.value = saved.name; note.value = "已保存 SKILL.md。";
}); }
function fetchPreview() {
  if (!confirm("从此 GitHub 仓库读取技能文本？不会运行仓库内容。")) return;
  return action(async () => {
    preview.value = undefined; chosen.value = [];
    preview.value = await send("skills/github/preview", { repo_url: repository.value.trim(), ref: branch.value.trim() || null });
  });
}
function importSelected() {
  if (!preview.value || !chosen.value.length || !confirm("已审阅选中的 SKILL.md，确认导入？不会自动授权给 Agent。")) return;
  return action(async () => {
    if (!preview.value) return;
    await send("skills/github/import", { import_id: preview.value.import_id, selected: [...chosen.value], confirm: true });
    skills.value = await request("skills"); preview.value = undefined; chosen.value = []; note.value = "已导入选中的技能文本。";
  });
}
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不连接技能目录或 MCP 服务。</p>
    <template v-else>
      <nav class="business-actions" aria-label="技能与工具功能">
        <button v-for="[key,label] in [['grants','Agent 授权'],['skills','技能目录'],['mcp','MCP 服务']]" :key="key" type="button"
          :class="tab === key ? 'primary' : 'secondary'" :aria-pressed="tab === key" :disabled="busy" @click="tab = key">{{ label }}</button>
        <button type="button" class="secondary" :disabled="busy" @click="load">刷新目录</button>
      </nav>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
      <template v-if="tab === 'grants'">
        <form class="business-form glass" @submit.prevent="saveGrants">
          <label>选择 Agent<select v-model="id" :disabled="busy" @change="fill"><option v-for="agent in agents" :key="agent.id" :value="agent.id">{{ agent.data.title }}</option></select></label>
          <fieldset v-if="current"><legend>工具</legend>
            <label v-for="tool in [...tools, ...discovery]" :key="tool.name" class="check-line"><input v-model="grants.tool_ids" type="checkbox" :value="tool.name" />
              {{ tool.name }} · {{ tool.description }}</label></fieldset>
          <fieldset v-if="current"><legend>技能</legend><label v-for="skill in skills" :key="skill.name" class="check-line">
            <input v-model="grants.skill_ids" type="checkbox" :value="skill.name" /> {{ skill.name }} · {{ skill.description }}</label></fieldset>
          <fieldset v-if="current"><legend>MCP 服务</legend><label v-for="server in servers" :key="server.id" class="check-line">
            <input v-model="grants.mcp_server_ids" type="checkbox" :value="server.id" :disabled="(!server.trusted || !server.enabled) && !grants.mcp_server_ids.includes(server.id)" />
            {{ server.id }} · {{ server.enabled && server.trusted ? '已信任' : '不可用' }}</label></fieldset>
          <button class="primary" :disabled="busy || !current">保存授权</button>
        </form>
      </template>
      <template v-else-if="tab === 'skills'">
        <div class="business-form glass"><label>已安装技能<select v-model="selection"><option value="">请选择</option>
          <option v-for="skill in skills" :key="skill.name">{{ skill.name }}</option></select></label>
          <div class="business-actions"><button type="button" class="secondary" :disabled="busy || !selection" @click="openSkill">查看或编辑</button>
            <button type="button" class="primary" :disabled="busy" @click="newSkill">新建 SKILL.md</button></div></div>
        <form v-if="edit" class="business-form glass" @submit.prevent="saveSkill">
          <label>技能标识<input v-model="name" required pattern="[a-z][a-z0-9-]{0,63}" :disabled="!!loaded" /></label>
          <label>SKILL.md 正文<textarea v-model="content" rows="12" required maxlength="65536" /></label>
          <button class="primary" :disabled="busy">保存技能</button>
        </form>
        <form class="business-form glass" @submit.prevent="fetchPreview"><h2>从 GitHub 导入</h2>
          <label>公开仓库地址<input v-model="repository" type="url" maxlength="2048" required /></label>
          <label>分支或标签<input v-model="branch" maxlength="101" /></label><button class="secondary" :disabled="busy">读取技能预览</button></form>
        <div v-if="preview" class="business-panel glass"><h2>导入预览</h2><p>提交：{{ preview.commit }}</p>
          <ul><li v-for="(message,i) in preview.warnings" :key="i">{{ message }}</li></ul>
          <article v-for="skill in preview.skills" :key="skill.name"><details><summary>{{ skill.name }} · {{ skill.repository_path }}</summary>
            <pre class="preserve">{{ skill.content }}</pre></details><label class="check-line"><input v-model="chosen" type="checkbox" :value="skill.name" /> 选择 {{ skill.name }}</label></article>
          <button type="button" class="primary" :disabled="busy || !chosen.length" @click="importSelected">确认导入选中技能</button></div>
      </template>
      <template v-else>
        <button type="button" class="secondary" :disabled="busy" @click="discover()">读取已信任服务工具</button>
        <p v-if="!servers.length">尚无服务端登记的 MCP 服务。</p>
        <article v-for="server in servers" :key="server.id" class="business-panel glass">
          <h2>{{ server.id }}</h2><p>{{ server.transport }} · {{ server.enabled && server.trusted ? '已信任' : '未启用或未信任' }}</p>
          <button class="secondary" type="button" :disabled="busy || !server.enabled || !server.trusted" @click="discover(server)">测试连接</button>
          <ul><li v-for="tool in discovery.filter(item => item.server_id === server.id)" :key="tool.name">{{ tool.name }} · {{ tool.description }}</li></ul>
        </article>
      </template>
    </template>
  </section>
</template>
