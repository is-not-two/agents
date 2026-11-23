<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { messageOf, request, send } from "@/api";
import { archiveRecord, dateText, getHistory, restoreRecord, saveRecord, segment, type Row } from "@/records";
import { timeISO, timeLocal } from "./jobs-data";
type Card = Row<{ title: string; answer_ref: string; due_at: string; paused: boolean; source: string }>;
type Review = Row<{ rating: number; reviewed_at: string; next_due_at: string }>;
type ReviewInput = { version: number; rating: number; request_id: string };
const path = "learning/cards";
const grades = ["忘了", "困难", "记得", "熟练"];
const data = ref<{ cards: Card[]; due_ids: string[] }>(), busy = ref(false), error = ref(""), note = ref("");
const filter = ref<"due" | "all" | "trash">("due"), selected = ref(""), reveal = ref(false), history = ref<Review[]>();
const editing = ref(false), editRow = ref<Card>(), form = ref({ title: "", answer_ref: "", due_at: "", paused: false });
const retry = new Map<string, ReviewInput>();
const cards = computed(() => (data.value?.cards || []).filter(card => filter.value !== "due" || data.value?.due_ids.includes(card.id)));
const current = computed(() => cards.value.find(card => card.id === selected.value));
const isDue = computed(() => filter.value !== "trash" && !!current.value && data.value?.due_ids.includes(current.value.id));
function pick(id: string) { selected.value = id; reveal.value = false; history.value = undefined; }
async function load() {
  data.value = await request(path + "?trash=" + (filter.value === "trash"));
  for (const [id, payload] of retry) {
    const version = data.value?.cards.find(card => card.id === id)?.version;
    if (version !== undefined && version !== payload.version) retry.delete(id);
  }
  if (!current.value) pick(cards.value[0]?.id || "");
}
async function action(fn: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function changeFilter(event: Event) { return action(async () => {
  filter.value = (event.target as HTMLSelectElement).value as typeof filter.value;
  data.value = undefined; editing.value = false; pick(""); await load();
}); }
function edit(row?: Card) {
  editRow.value = row; editing.value = true;
  form.value = { title: row?.data.title || "", answer_ref: row?.data.answer_ref || "",
    due_at: timeLocal(row?.data.due_at || new Date().toISOString()), paused: row?.data.paused || false };
}
function save() { return action(async () => {
  const row = await saveRecord(path, { ...form.value, due_at: timeISO(form.value.due_at) }, editRow.value);
  filter.value = "all"; pick(row.id); editing.value = false; await load(); note.value = "已保存复习卡。";
}); }
function score(rating: number) { return action(async () => {
  const card = current.value;
  if (!card || !isDue.value || !reveal.value) return;
  const existing = retry.get(card.id);
  if (existing && existing.rating !== rating) throw new Error("上一评分结果还未确认，请先刷新核对，或重试原评分。");
  const payload = existing || { version: card.version, rating, request_id: crypto.randomUUID() };
  retry.set(card.id, payload);
  const result = await send<{ card: Card }>(path + "/" + segment(card.id) + "/review", payload);
  retry.delete(card.id); reveal.value = false; history.value = undefined;
  await load(); note.value = "已记录复习，下次：" + dateText(result.card.data.due_at);
}); }
function archive(card: Card) {
  if (!confirm("归档这张卡？复习记录仍保留。")) return;
  return action(async () => { await archiveRecord(card); await load(); note.value = "已归档复习卡。"; });
}
function restore(card: Card) {
  if (!confirm("恢复为最新有效版本？")) return;
  return action(async () => {
    const last = (await getHistory(card)).filter(item => !item.deleted).sort((a,b) => b.version - a.version)[0];
    if (!last) throw new Error("没有可恢复的版本。");
    await restoreRecord(card, last.version); await load(); note.value = "已恢复复习卡。";
  });
}
function reviews(card: Card) { return action(async () => {
  history.value = await request(path + "/" + segment(card.id) + "/reviews");
}); }
onMounted(() => action(load));
</script>
<template>
  <section class="business-stack">
    <div class="business-form glass"><label>卡片范围<select :value="filter" :disabled="busy" @change="changeFilter">
      <option value="due">到期待复习</option><option value="all">全部有效</option><option value="trash">回收站</option></select></label>
      <div class="business-actions"><button v-if="filter !== 'trash'" class="primary" type="button" :disabled="busy" @click="edit()">新建复习卡</button>
        <button class="secondary" type="button" :disabled="busy" @click="action(load)">刷新卡片</button></div>
    </div>
    <p v-if="note" role="status">{{ note }}</p><p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <form v-if="editing" class="business-form glass" @submit.prevent="save">
      <label>复习问题<input v-model="form.title" maxlength="1000" required /></label>
      <label>答案或资料引用<textarea v-model="form.answer_ref" rows="5" maxlength="10000" /></label>
      <label>复习时间<input v-model="form.due_at" type="datetime-local" required /></label>
      <label class="check-line"><input v-model="form.paused" type="checkbox" /> 暂停此卡片</label>
      <div class="business-actions"><button class="primary" :disabled="busy">保存卡片</button>
        <button class="secondary" type="button" :disabled="busy" @click="editing = false">取消</button></div>
    </form>
    <div v-if="cards.length" class="business-form glass"><label>选择复习卡<select :value="selected" :disabled="busy"
      @change="pick(($event.target as HTMLSelectElement).value)"><option v-for="card in cards" :key="card.id" :value="card.id">{{ card.data.title }}</option></select></label></div>
    <p v-else-if="data && !busy">没有符合条件的复习卡。</p>
    <article v-if="current" class="business-panel glass">
      <h2>{{ current.data.title }}</h2><p>{{ current.data.paused ? '已暂停' : '下次复习：' + dateText(current.data.due_at) }}</p>
      <div class="business-actions">
        <template v-if="filter !== 'trash'"><button class="secondary" type="button" :disabled="busy" @click="reveal = !reveal">{{ reveal ? '隐藏答案' : '显示答案' }}</button>
          <button class="secondary" type="button" :disabled="busy" @click="edit(current)">编辑卡片</button>
          <button class="secondary" type="button" :disabled="busy" @click="reviews(current)">复习历史</button>
          <button class="secondary" type="button" :disabled="busy" @click="archive(current)">归档卡片</button></template>
        <button v-else class="secondary" type="button" :disabled="busy" @click="restore(current)">恢复卡片</button>
      </div>
      <p v-if="reveal" class="preserve">{{ current.data.answer_ref || '没有填写参考答案。' }}</p>
      <div v-if="isDue && reveal" class="business-actions" aria-label="复习自评">
        <button v-for="(label,rating) in grades" :key="rating" class="secondary" type="button" :disabled="busy" @click="score(rating)">{{ label }}</button>
      </div>
      <ul v-if="history?.length"><li v-for="entry in history" :key="entry.id">{{ dateText(entry.data.reviewed_at) }} ·
        {{ grades[entry.data.rating] }} · 下次 {{ dateText(entry.data.next_due_at) }}</li></ul>
      <p v-else-if="history">没有复习历史。</p>
    </article>
  </section>
</template>
