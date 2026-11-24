<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from "vue";
import { useRoute } from "vue-router";
import { messageOf, request, send } from "@/api";
import { saveRecord, segment, type Fields, type Row } from "@/records";
type Task = { id: string; title: string; description: string; due_date: string; done: boolean; priority: string; parent_id: string; requires: string[]; kind: string; state?: string };
type Plan = Row<Fields & { title: string; kind: string; description: string; acts: { id: string; title: string; nodes: Task[] }[]; progress?: { done: number; total: number } }>;
const rows = ref<Plan[]>([]), selected = ref(""), error = ref(""), busy = ref(false);
const route = useRoute();
const requestedPlan = typeof route.query.plan === "string" ? route.query.plan : "";
const requestedTask = typeof route.query.task === "string" ? route.query.task : "";
const unavailable = ref(false);
const plan = computed(() => rows.value.find(row => row.id === selected.value));
const nodes = computed(() => plan.value?.data.acts.flatMap(act => act.nodes) || []);
const createPlan = ref(false), planEdit = ref(false), planTitle = ref(""), planKind = ref("main"), planDesc = ref("");
const editTask = ref<Task>();
const deleting = ref<{ id: string; version: number; affected: { id: string; title: string }[]; blockers: { id: string; title: string }[]; can_delete: boolean }>();
const blank = (): Task => ({ id: "", title: "", description: "", due_date: "", done: false, priority: "p2", parent_id: "", requires: [], kind: "side" });
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { await action(); } catch (reason) { error.value = messageOf(reason); } finally { busy.value = false; }
}
function update(row: Plan) {
  rows.value = rows.value.some(item => item.id === row.id) ? rows.value.map(item => item.id === row.id ? row : item) : [row, ...rows.value];
  selected.value = row.id;
}
async function load() {
  rows.value = await request<Plan[]>("plans");
  if (!rows.value.some(row => row.id === selected.value)) selected.value = rows.value[0]?.id ?? "";
}
onMounted(() => perform(async () => {
  await load();
  if (!requestedPlan) return;
  const match = rows.value.find(row => row.id === requestedPlan);
  selected.value = match?.id || "";
  unavailable.value = !match || (!!requestedTask && !nodes.value.some(task => task.id === requestedTask));
  if (requestedTask && !unavailable.value) {
    await nextTick();
    document.getElementById("plan-task-" + requestedTask)?.focus();
  }
}));
function editPlan(existing?: Plan) {
  createPlan.value = true; planEdit.value = !!existing; planTitle.value = existing?.data.title || "";
  planKind.value = existing?.data.kind || "main"; planDesc.value = existing?.data.description || "";
}
function savePlan() { return perform(async () => {
  const row = planEdit.value ? plan.value : undefined;
  const value = { ...(row?.data || {}), title: planTitle.value, kind: planKind.value, description: planDesc.value, acts: row?.data.acts ?? [] };
  update(await saveRecord("plans", value, row) as Plan); createPlan.value = false;
}); }
function saveTask(task: Task) { return perform(async () => {
  if (!plan.value) return;
  const base = "plans/" + segment(plan.value.id) + "/nodes";
  const { id, state: _state, ...data } = task;
  update(await send<Plan>(id ? base + "/" + segment(id) : base, { data, version: plan.value.version }, id ? "PUT" : "POST"));
  editTask.value = undefined; deleting.value = undefined;
}); }
function inspect(task: Task) { return perform(async () => {
  if (!plan.value) return;
  const value = await request<Omit<NonNullable<typeof deleting.value>, "id">>("plans/" + segment(plan.value.id) + "/nodes/" + segment(task.id) + "/delete-preview");
  deleting.value = { ...value, id: task.id };
}); }
function remove() { return perform(async () => {
  if (!plan.value || !deleting.value?.can_delete) return;
  const item = deleting.value;
  update(await request<Plan>("plans/" + segment(plan.value.id) + "/nodes/" + segment(item.id) +
    "?version=" + item.version + "&cascade=" + (item.affected.length > 1), { method: "DELETE" }));
  deleting.value = undefined; editTask.value = undefined;
}); }
</script>
<template>
  <section class="business-stack">
    <div class="business-actions"><button class="primary" type="button" @click="editPlan()">添加规划</button>
      <button class="secondary" type="button" :disabled="busy" @click="perform(load)">刷新</button></div>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="unavailable" role="status">链接中的规划或任务已不存在，请重新选择。</p>
    <form v-if="createPlan" class="business-form glass" @submit.prevent="savePlan"><h2>{{ planEdit ? '编辑规划' : '新建规划' }}</h2>
      <label>规划名称<input v-model="planTitle" required maxlength="160" /></label>
      <label>类型<select v-model="planKind"><option value="main">主线</option><option value="side">支线</option></select></label>
      <label>说明<textarea v-model="planDesc" rows="2" /></label>
      <div class="business-actions"><button class="primary" :disabled="busy">保存规划</button><button class="secondary" type="button" @click="createPlan = false">取消</button></div>
    </form>
    <div v-if="rows.length" class="business-form glass"><label>选择规划<select v-model="selected" @change="editTask = undefined; deleting = undefined; createPlan = false; unavailable = false">
      <option value="" disabled>请选择</option>
      <option v-for="row in rows" :key="row.id" :value="row.id">{{ row.data.title }}</option></select></label></div>
    <article v-if="plan" class="business-panel glass"><h2>{{ plan.data.title }}</h2><p class="preserve">{{ plan.data.description }}</p>
      <p>进度 {{ plan.data.progress?.done ?? 0 }} / {{ plan.data.progress?.total ?? nodes.length }}</p>
      <div class="business-actions"><button class="secondary" type="button" @click="editPlan(plan)">编辑规划</button><button class="primary" type="button" @click="editTask = blank()">添加任务</button></div>
      <ul class="simple-list"><li v-for="task in nodes" :key="task.id" :id="'plan-task-' + task.id" tabindex="-1">
        <h3>{{ task.title }}</h3><p>{{ task.priority.toUpperCase() }} · {{ task.done ? "已完成" : task.state === "locked" ? "等前置任务" : "可开始" }} <span v-if="task.due_date">· {{ task.due_date }}</span></p>
        <p v-if="task.parent_id">上级：{{ nodes.find(item => item.id === task.parent_id)?.title }}</p>
        <p v-if="task.requires.length">前置：{{ nodes.filter(item => task.requires.includes(item.id)).map(item => item.title).join("、") }}</p>
        <div class="business-actions"><button class="secondary" type="button" :disabled="busy || task.state === 'locked'" @click="saveTask({ ...task, done: !task.done })">{{ task.done ? '撤销完成' : '完成任务' }}</button>
          <button class="secondary" type="button" @click="editTask = { ...task, requires: [...task.requires] }">编辑任务</button>
          <button class="secondary" type="button" @click="editTask = { ...blank(), parent_id: task.id }">添加子任务</button>
          <button class="secondary" type="button" :disabled="busy" @click="inspect(task)">预检删除</button></div></li></ul>
      <p v-if="!nodes.length">还没有任务。</p>
    </article>
    <form v-if="editTask" class="business-form glass" @submit.prevent="saveTask(editTask)"><h2>{{ editTask.id ? "编辑任务" : "新建任务" }}</h2>
      <label>任务名称<input v-model="editTask.title" required maxlength="160" /></label>
      <label>说明<textarea v-model="editTask.description" rows="3" maxlength="20000" /></label>
      <div class="business-columns"><label>截止日期<input type="date" v-model="editTask.due_date" /></label><label>优先级<select v-model="editTask.priority">
        <option v-for="priority in ['p0','p1','p2','p3','p4']" :key="priority" :value="priority">{{ priority.toUpperCase() }}</option></select></label></div>
      <label>所属分支<select v-model="editTask.kind"><option value="side">支线</option><option v-if="plan?.data.kind === 'main'" value="main">主线</option></select></label>
      <label>父任务<select v-model="editTask.parent_id"><option value="">无</option><option v-for="item in nodes.filter(task => task.id !== editTask?.id)" :key="item.id" :value="item.id">{{ item.title }}</option></select></label>
      <label v-if="nodes.length">前置任务（可多选）<select v-model="editTask.requires" multiple><option v-for="item in nodes.filter(task => task.id !== editTask?.id)" :key="item.id" :value="item.id">{{ item.title }}</option></select></label>
      <div class="business-actions"><button class="primary" :disabled="busy">保存任务</button><button class="secondary" type="button" @click="editTask = undefined">取消</button></div>
    </form>
    <section v-if="deleting" class="business-panel glass"><h2>删除范围</h2><p>受影响：{{ deleting.affected.map(item => item.title).join("、") }}</p>
      <p v-if="!deleting.can_delete">被其他任务引用：{{ deleting.blockers.map(item => item.title).join("、") }}</p>
      <div class="business-actions"><button class="primary" type="button" :disabled="busy || !deleting.can_delete" @click="remove">确认删除所列任务</button>
        <button class="secondary" type="button" @click="deleting = undefined">取消</button></div></section>
  </section>
</template>
