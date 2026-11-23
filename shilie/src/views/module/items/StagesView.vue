<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { messageOf, request, requestText, send } from "@/api";
import { dateText, segment } from "@/records";
type Change = { path: string; kind: string };
type Stage = { id: string; title: string; objective: string; status: string; created_at: string; completed_at: string | null;
  completed: string[]; issues: string[]; verification: string[]; changes: Change[]; data_snapshot_available: boolean };
type Check = { can_apply: boolean; conflicts: string[]; changes: Change[] };
const rows = ref<Stage[]>([]), selected = ref(""), creating = ref(false), finishing = ref(false);
const current = computed(() => rows.value.find(row => row.id === selected.value));
const error = ref(""), note = ref(""), busy = ref(false), patch = ref(""), check = ref<Check>(), confirmation = ref("");
const start = ref({ title: "", objective: "" });
const end = ref({ completed: "", issues: "", verification: "", status: "attention" });
const labels: Record<string, string> = { running: "进行中", passed: "已通过", attention: "待处理" };
const changes: Record<string, string> = { added: "新增", deleted: "删除", modified: "修改" };
function pick(id: string) { selected.value = id; finishing.value = false; confirmation.value = ""; patch.value = ""; check.value = undefined; }
async function load() {
  rows.value = await request("stages");
  if (!rows.value.some(row => row.id === selected.value)) pick(rows.value[0]?.id || "");
}
const lines = (text: string) => text.split(/\r?\n/).map(s => s.trim()).filter(Boolean);
async function run(action: "load" | "start" | "finish" | "diff" | "check" | "restore") {
  if (busy.value) return;
  const id = selected.value;
  if (action === "restore" && (!current.value?.data_snapshot_available || confirmation.value !== "恢复数据" ||
      !confirm("恢复将替换当前工作区数据，而非只恢复此阶段记录。确定继续？"))) return;
  busy.value = true; error.value = ""; note.value = "";
  try {
    const path = "stages/" + segment(id);
    if (action === "start") {
      const row = await send<Stage>("stages", { ...start.value }); pick(row.id); creating.value = false; start.value = { title: "", objective: "" };
    }
    if (action === "finish") {
      await send(path + "/finish", { completed: lines(end.value.completed), issues: lines(end.value.issues),
        verification: lines(end.value.verification), status: end.value.status });
      finishing.value = false; end.value = { completed: "", issues: "", verification: "", status: "attention" };
    }
    if (action === "diff") patch.value = await requestText(path + "/diff");
    if (action === "check") check.value = await request(path + "/rollback-check");
    if (action === "restore") {
      const result = await send<{ restored_records: number }>(path + "/restore-data", { confirmation: confirmation.value });
      confirmation.value = ""; note.value = "已恢复 " + result.restored_records + " 条记录。";
    }
    if (["load", "start", "finish", "restore"].includes(action)) await load();
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
onMounted(() => run("load"));
</script>
<template>
  <section class="business-stack">
    <div class="business-actions"><button class="primary" type="button" :disabled="busy" @click="creating = !creating">开始新阶段</button>
      <button class="secondary" type="button" :disabled="busy" @click="run('load')">刷新</button></div>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
    <form v-if="creating" class="business-form glass" @submit.prevent="run('start')">
      <label>阶段名称<input v-model="start.title" maxlength="160" required /></label>
      <label>目标<textarea v-model="start.objective" rows="3" maxlength="10000" /></label>
      <p>创建时后端会保存阶段开始前的数据和源码快照。</p>
      <button class="primary" :disabled="busy">保存并开始</button>
    </form>
    <div v-if="rows.length" class="business-form glass"><label>选择阶段<select :value="selected" :disabled="busy" @change="pick(($event.target as HTMLSelectElement).value)">
      <option v-for="row in rows" :key="row.id" :value="row.id">{{ row.title }} · {{ labels[row.status] || row.status }}</option>
    </select></label></div>
    <p v-else-if="!busy && !error">暂无阶段记录。</p>
    <article v-if="current" class="business-panel glass">
      <h2>{{ current.title }}</h2><p>{{ labels[current.status] || current.status }} · {{ dateText(current.created_at) }}</p>
      <p class="preserve">{{ current.objective }}</p>
      <template v-for="[label, items] in ([['完成项',current.completed],['问题',current.issues],['验证',current.verification]] as const)" :key="label">
        <template v-if="items.length"><h3>{{ label }}</h3><ul><li v-for="(item,index) in items" :key="index">{{ item }}</li></ul></template>
      </template>
      <button v-if="current.status === 'running'" class="secondary" type="button" :disabled="busy" @click="finishing = !finishing">结束阶段</button>
      <div v-else class="business-actions"><button class="secondary" type="button" :disabled="busy" @click="run('diff')">查看文本差异</button>
        <button class="secondary" type="button" :disabled="busy" @click="run('check')">源码回滚预检</button></div>
      <ul v-if="current.changes.length"><li v-for="item in current.changes" :key="item.path">{{ changes[item.kind] || item.kind }} · {{ item.path }}</li></ul>
      <pre v-if="patch" class="preserve">{{ patch }}</pre>
      <div v-if="check"><p>{{ check.can_apply ? '未检测到后续文件冲突。' : '发现冲突，不能应用。' }} 此操作未改动源码。</p>
        <ul><li v-for="item in check.conflicts" :key="item">{{ item }}</li></ul></div>
      <details v-if="current.data_snapshot_available"><summary>恢复阶段开始前的数据</summary>
        <form class="business-form" @submit.prevent="run('restore')"><label>输入「恢复数据」以继续<input v-model="confirmation" autocomplete="off" /></label>
          <button class="secondary" :disabled="busy || confirmation !== '恢复数据'">恢复数据</button></form>
      </details>
    </article>
    <form v-if="current && finishing" class="business-form glass" @submit.prevent="run('finish')">
      <label>完成项（每行一项）<textarea v-model="end.completed" /></label>
      <label>问题（每行一项）<textarea v-model="end.issues" /></label>
      <label>验证证据（每行一项）<textarea v-model="end.verification" :required="end.status === 'passed'" /></label>
      <label for="stage-result">结果</label><select id="stage-result" v-model="end.status"><option value="attention">待处理</option><option value="passed">已通过</option></select>
      <button class="primary" :disabled="busy">保存阶段结果</button>
    </form>
  </section>
</template>
