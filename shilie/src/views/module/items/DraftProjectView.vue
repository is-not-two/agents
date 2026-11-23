<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref, watch } from "vue";
import { messageOf, request, send } from "@/api";
import { type Row, segment } from "@/records";

type Preview = { summary: string; columns: string[]; rows: string[][]; roles: string[]; initial: string;
  actions: { label: string; roles: string[]; before: string; after: string }[] };
type Stage = { id: string; title: string; task: string; depends: string[]; gate: string; approved: boolean; draft: Preview | null };
type Project = Row<{ title: string; status: string; active: string; error: string; stages: Stage[];
  history: { id: string; title: string; version: number; draft: Preview }[] }>;
const projects = ref<Project[]>([]), current = ref<Project>(), goal = ref(""), selected = ref(""), past = ref<number>();
const gate = ref(""), feedback = ref(""), revise = ref(false), choices = ref<string[]>([]);
const error = ref(""), busy = ref(false), driving = ref(false);
const rowIndex = ref(0), role = ref(""), simulated = ref("");
const statuses: Record<string, string> = { ready: "可继续", running: "AI 正在生成", paused: "已暂停",
  awaiting_review: "等待人工验收", completed: "草稿已完成", failed: "本步需要重试" };
const stage = computed(() => current.value?.data.stages.find(item => item.id === selected.value));
const history = computed(() => current.value?.data.history.filter(item => item.id === selected.value) || []);
const preview = computed(() => past.value == null ? stage.value?.draft : history.value.find(item => item.version === past.value)?.draft);
const accepted = computed(() => current.value?.data.stages.filter(item => item.gate && item.approved) || []);
const affected = computed(() => {
  const ids = new Set([selected.value]);
  return current.value?.data.stages.filter(item => {
    if (item.depends.some(dep => ids.has(dep))) ids.add(item.id);
    return ids.has(item.id);
  }).map(item => item.title) || [];
});
let pump = 0, timer: ReturnType<typeof setInterval> | undefined;
watch(stage, (next, old) => { if (next?.id !== old?.id || next?.gate !== old?.gate) gate.value = next?.gate || ""; });
watch(preview, value => { rowIndex.value = 0; role.value = value?.roles[0] || ""; simulated.value = value?.initial || ""; });

function show(row: Project) {
  if (row.id !== current.value?.id || row.version >= current.value.version) current.value = row;
  if (!selected.value || !row.data.stages.some(item => item.id === selected.value)) selected.value = row.data.stages[0]?.id || "";
}
async function list() { projects.value = await request<Project[]>("draft-projects"); }
async function refresh() {
  const id = current.value?.id;
  if (!id) return;
  const row = await request<Project>("draft-projects/" + segment(id));
  if (current.value?.id === id) show(row);
}
function sendAction<T>(row: Project, action: string, node = "", value = "") {
  return send<T>("draft-projects/" + segment(row.id) + "/action", { version: row.version, action, node, value });
}
function pick(id: string) { selected.value = id; past.value = undefined; revise.value = false; feedback.value = ""; choices.value = []; }
async function open(id: string) {
  pump++; driving.value = false;
  if (!id) { current.value = undefined; return; }
  try { pick(""); show(await request<Project>("draft-projects/" + segment(id))); } catch (reason) { error.value = messageOf(reason); }
}
async function drive() {
  const token = ++pump;
  driving.value = true;
  try {
    while (token === pump && current.value?.data.status === "ready") {
      const row = await sendAction<Project>(current.value, "advance");
      if (token === pump) show(row);
    }
  } catch (reason) {
    if (token === pump) { error.value = messageOf(reason); await refresh().catch(() => {}); }
  } finally { if (token === pump) driving.value = false; }
}
async function create() {
  if (!confirm("使用当前模型生成模拟草稿？只发送这里填写的目标，不执行部署或业务写入。")) return;
  error.value = ""; busy.value = true;
  try {
    pick(""); show(await send<Project>("draft-projects", { goal: goal.value.trim() }));
    goal.value = ""; await list(); void drive();
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function change(action: string, value = "") {
  const row = current.value;
  if (!row || busy.value) return;
  busy.value = true; error.value = "";
  try {
    if (action === "choices") {
      choices.value = (await sendAction<{ options: string[] }>(row, action, selected.value, value)).options;
      return;
    }
    pump++; driving.value = false;
    try { show(await sendAction<Project>(row, action, selected.value, value)); }
    catch (reason) {
      if (action !== "pause") throw reason;
      await refresh();
      const fresh = current.value;
      if (!fresh || fresh.id !== row.id || fresh.version === row.version) throw reason;
      if (["running", "ready", "awaiting_review"].includes(fresh.data.status)) show(await sendAction<Project>(fresh, "pause"));
    }
    if (action === "revise") { past.value = undefined; revise.value = true; }
    if (action === "resume") revise.value = false;
    if (current.value?.data.status === "ready") void drive();
  } catch (reason) { error.value = messageOf(reason); await refresh().catch(() => {}); }
  finally { busy.value = false; }
}
onMounted(async () => {
  try { await list(); } catch (reason) { error.value = messageOf(reason); }
  timer = setInterval(() => { if (driving.value || current.value?.data.status === "running") void refresh().catch(() => {}); }, 700);
});
onUnmounted(() => { pump++; if (timer) clearInterval(timer); });
</script>

<template>
  <section class="business-stack" aria-label="草稿项目">
    <form class="business-form glass" @submit.prevent="create">
      <h2>交给 AI 做草稿</h2>
      <p>你不用编排。AI 规划并生成可体验的草稿；只有你加的验收点会拦住依赖它的步骤。</p>
      <label>项目目标<textarea v-model="goal" rows="3" maxlength="2000" required placeholder="例如：做一个订单后台，包含订单列表、详情和退款权限" /></label>
      <div class="business-actions"><button class="primary" :disabled="busy || driving || !goal.trim()">规划并生成草稿</button></div>
      <label>已有草稿项目<select aria-label="已有草稿项目" :value="current?.id || ''" :disabled="busy" @change="open(($event.target as HTMLSelectElement).value)">
        <option value="">请选择</option><option v-for="row in projects" :key="row.id" :value="row.id">{{ row.data.title }}</option>
      </select></label>
    </form>
    <p v-if="error || current?.data.error" class="form-error" role="alert">{{ error || current?.data.error }}</p>
    <template v-if="current">
      <header class="business-panel glass">
        <h2>{{ current.data.title }}</h2>
        <p role="status">{{ statuses[current.data.status] }}<template v-if="current.data.active"> · {{ current.data.stages.find(x => x.id === current?.data.active)?.title || '规划步骤' }}</template></p>
        <div class="business-actions">
          <button v-if="driving || ['running','awaiting_review','ready'].includes(current.data.status)" type="button" class="secondary" :disabled="busy" @click="change('pause')">暂停生成</button>
          <button v-if="['paused','failed','running'].includes(current.data.status) && !driving" type="button" class="primary" :disabled="busy" @click="change('resume')">从未完成处继续</button>
          <button v-if="current.data.status === 'ready' && !driving" type="button" class="primary" :disabled="busy" @click="drive">继续生成</button>
        </div>
        <details v-if="accepted.length"><summary>已通过的验收项</summary><ul><li v-for="item in accepted" :key="item.id">{{ item.title }}：{{ item.gate }}</li></ul></details>
      </header>
      <div class="draft-workspace" v-if="stage">
        <nav class="business-panel glass draft-steps" aria-label="草稿步骤">
          <button v-for="(item,index) in current.data.stages" :key="item.id" type="button" class="secondary" :disabled="busy" :aria-pressed="selected === item.id" @click="pick(item.id)">
            <b>{{ index + 1 }}. {{ item.title }}</b><small>{{ item.approved ? '已验收' : item.gate ? (item.draft ? '等你验收' : '人工验收点') : item.draft ? '已有草稿' : '待生成' }}</small>
          </button>
        </nav>
        <article class="business-form glass">
          <h3>{{ stage.title }}</h3><p>{{ stage.task }}</p>
          <label v-if="history.length">比较版本<select aria-label="比较版本" v-model="past"><option :value="undefined">当前草稿</option>
            <option v-for="item in history" :key="item.version" :value="item.version">旧稿 · 第 {{ item.version }} 版</option></select></label>
          <template v-if="preview">
            <p>{{ preview.summary }}</p><p>模拟数据 · {{ past == null ? '当前草稿' : '历史草稿，只读' }}</p>
            <label>体验角色<select aria-label="体验角色" v-model="role"><option v-for="name in preview.roles" :key="name">{{ name }}</option></select></label>
            <div class="draft-table"><table><thead><tr><th v-for="(name,i) in preview.columns" :key="i">{{ name }}</th><th>查看</th></tr></thead>
              <tbody><tr v-for="(item,i) in preview.rows" :key="i"><td v-for="(cell,j) in item" :key="j">{{ cell }}</td>
                <td><button type="button" class="secondary" :aria-pressed="rowIndex === i" @click="rowIndex = i; simulated = preview.initial">查看第 {{ i + 1 }} 行</button></td></tr></tbody></table></div>
            <dl><template v-for="(name,i) in preview.columns" :key="i"><dt>{{ name }}</dt><dd>{{ preview.rows[rowIndex]?.[i] }}</dd></template></dl>
            <p role="status">当前模拟状态：{{ simulated }}</p>
            <div class="business-actions"><button v-for="(item,i) in preview.actions" :key="i" type="button" class="secondary"
              :disabled="!item.roles.includes(role) || item.before !== simulated" @click="simulated = item.after">{{ item.label }}</button></div>
          </template>
          <p v-else>这一步还没有当前草稿。若它依赖一个未验收的步骤，会等你通过后再生成。</p>
        </article>
        <aside class="business-form glass">
          <h3>你的决定</h3>
          <label>验收标准（可选）<textarea v-model="gate" rows="3" maxlength="500" :disabled="busy" /></label>
          <button type="button" class="secondary" :disabled="busy || gate.trim() === stage.gate || past != null" @click="change('gate', gate)">{{ gate.trim() ? '设置验收点' : '移除验收点' }}</button>
          <button v-if="stage.gate && stage.draft && !stage.approved" type="button" class="primary" :disabled="busy || past != null" @click="change('approve')">验收通过这版</button>
          <button type="button" class="secondary" :disabled="busy || past != null || (!stage.draft && current.data.active !== stage.id && !history.length)" @click="revise = !revise">回到这一步修改</button>
          <template v-if="revise">
            <label>哪里不满意？<textarea v-model="feedback" rows="3" maxlength="1000" :disabled="busy" placeholder="可以直接说你想怎么改，也可以先回撤" /></label>
            <button type="button" class="secondary" :disabled="busy" @click="change('choices', feedback)">让 AI 给几个改法</button>
            <button v-for="item in choices" :key="item" type="button" class="secondary" :disabled="busy" @click="feedback = item">{{ item }}</button>
            <p>保留旧稿；重做：{{ affected.join('、') }}。其他步骤不变。</p>
            <button type="button" class="primary" :disabled="busy || past != null" @click="change('revise', feedback)">暂停并退回这一步</button>
          </template>
        </aside>
      </div>
    </template>
  </section>
</template>

<style scoped>
.draft-workspace{display:grid;grid-template-columns:minmax(9rem,1fr) minmax(0,3fr) minmax(13rem,1.25fr);gap:1rem;align-items:start}
.draft-steps{display:grid;gap:.45rem}.draft-steps button{text-align:left}.draft-steps small{display:block}.draft-steps [aria-pressed=true]{outline:2px solid currentColor}
.draft-table{overflow:auto}.draft-table table{border-collapse:collapse;width:100%}.draft-table td,.draft-table th{padding:.45rem;border-bottom:1px solid #c9aaa1;text-align:left}
@media(max-width:1000px){.draft-workspace{grid-template-columns:1fr}.draft-steps{grid-template-columns:repeat(auto-fit,minmax(8rem,1fr))}}
</style>
