<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
import { segment, type Row } from "@/records";
type Kind = "wish" | "diary";
type Content = { title: string; note?: string; category?: string; price?: string; emoji?: string; done?: boolean; content?: string; date?: string };
type PrivateRecord = Row<Content> | { _locked: true };
const status = ref<{ configured: boolean; strong_crypto: boolean }>(), ticket = ref(""), password = ref(""), confirmation = ref("");
const busy = ref(false), error = ref(""), note = ref(""), tab = ref<Kind>("wish"), query = ref("");
const rows = ref<Row<Content>[]>([]), hidden = ref(0), edit = ref(false), target = ref<Row<Content>>();
const blank = (): Content => ({ title: "", note: "", category: "", price: "", emoji: "", done: false, content: "", date: "" });
const draft = ref<Content>(blank());
const controller = new AbortController();
const filtered = computed(() => rows.value.filter(row => [row.data.title, row.data.category, row.data.note, row.data.content]
  .join(" ").toLowerCase().includes(query.value.trim().toLowerCase())));
const path = () => "private/" + tab.value;
const headers = () => ({ "X-Private-Ticket": ticket.value });
function reset() {
  ticket.value = ""; password.value = ""; confirmation.value = ""; rows.value = []; query.value = "";
  hidden.value = 0; draft.value = blank(); edit.value = false; target.value = undefined;
}
async function load() {
  const result = await request<PrivateRecord[]>(path(), { headers: headers(), signal: controller.signal });
  rows.value = result.filter((row): row is Row<Content> => "id" in row);
  hidden.value = result.length - rows.value.length;
}
async function action(fn: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await fn(); } catch (reason) { if (!controller.signal.aborted) error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function open() { return action(async () => {
  try {
    const result = await request<{ ticket: string }>("private/session", { method: "POST",
      body: JSON.stringify({ password: password.value }), signal: controller.signal });
    ticket.value = result.ticket;
    try { await load(); } catch (reason) { reset(); throw reason; }
  } finally { password.value = ""; }
}); }
function setup() { return action(async () => {
  if (password.value !== confirmation.value) throw new Error("两次输入的口令不同。");
  try {
    await send("private/setup", { password: password.value });
    status.value = await request("private/status"); note.value = "已设置口令。请妥善保存口令，遗失后可能无法解密旧内容。";
  } finally { password.value = ""; confirmation.value = ""; }
}); }
function switchTab(kind: Kind) { if (kind !== tab.value) return action(async () => {
  tab.value = kind; rows.value = []; query.value = ""; edit.value = false; target.value = undefined; draft.value = blank(); await load();
}); }
function editor(row?: Row<Content>) { target.value = row; draft.value = row ? { ...row.data } : blank(); edit.value = true; }
async function put(data: Content, row?: Row<Content>) {
  const clean = tab.value === "wish" ? { title: data.title, category: data.category, price: data.price, emoji: data.emoji,
    done: data.done, note: data.note } : { title: data.title, date: data.date, content: data.content };
  await request(path() + (row ? "/" + segment(row.id) : ""), { method: row ? "PUT" : "POST", signal: controller.signal,
    body: JSON.stringify({ data: clean, version: row?.version, ticket: ticket.value }) });
}
function save() { return action(async () => {
  await put(draft.value, target.value); edit.value = false; target.value = undefined; draft.value = blank(); await load(); note.value = "已保存。";
}); }
function toggle(row: Row<Content>) { return action(async () => { await put({ ...row.data, done: !row.data.done }, row); await load(); }); }
function remove(row: Row<Content>) {
  if (!confirm("删除这条私密记录？它不会出现在公开回收站。")) return;
  return action(async () => {
    await request(path() + "/" + segment(row.id) + "?version=" + row.version, { method: "DELETE", headers: headers(), signal: controller.signal });
    if (target.value?.id === row.id) { target.value = undefined; draft.value = blank(); edit.value = false; }
    await load(); note.value = "已删除。";
  });
}
const statusAction = () => action(async () => { status.value = await request("private/status", { signal: controller.signal }); });
onMounted(statusAction);
onUnmounted(() => { controller.abort(); reset(); });
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不读取或存储私密内容。连接自己的单用户后端后才能使用。</p>
    <template v-else>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
      <p v-if="busy" role="status">正在处理…</p>
      <button v-if="!status && !busy" class="secondary" type="button" @click="statusAction">重新读取状态</button>
      <form v-if="status?.configured && !ticket" class="business-form glass" @submit.prevent="open">
        <h2>解锁愿望与日记</h2><label>私密口令<input v-model="password" type="password" autocomplete="current-password" maxlength="128" required /></label>
        <button class="primary" :disabled="busy">解锁</button>
      </form>
      <form v-if="status && !status.configured && status.strong_crypto" class="business-form glass" @submit.prevent="setup">
        <h2>设置私密口令</h2><p>请妥善保存口令。它不等于工作区登录密码。</p>
        <label>新口令<input v-model="password" type="password" autocomplete="new-password" minlength="4" maxlength="128" required /></label>
        <label>再次输入口令<input v-model="confirmation" type="password" autocomplete="new-password" maxlength="128" required /></label>
        <button class="primary" :disabled="busy">保存私密口令</button>
      </form>
      <p v-if="status && !status.configured && !status.strong_crypto">当前后端未启用加密依赖，无法设置私密口令。</p>
      <template v-if="ticket">
        <nav class="business-actions" aria-label="私密区功能">
          <button class="secondary" :aria-pressed="tab === 'wish'" type="button" :disabled="busy" @click="switchTab('wish')">愿望清单</button>
          <button class="secondary" :aria-pressed="tab === 'diary'" type="button" :disabled="busy" @click="switchTab('diary')">私密日记</button>
          <button class="secondary" type="button" :disabled="busy" @click="reset(); error = ''; note = ''">锁定此页面</button>
        </nav>
        <div class="business-form glass"><label>查找条目<input v-model="query" type="search" /></label>
          <button class="primary" type="button" :disabled="busy" @click="editor()">{{ tab === 'wish' ? '添加愿望' : '写日记' }}</button></div>
        <form v-if="edit" class="business-form glass" @submit.prevent="save">
          <label>标题<input v-model="draft.title" maxlength="160" required /></label>
          <template v-if="tab === 'wish'">
            <label>分类<input v-model="draft.category" maxlength="80" /></label>
            <label>预算<input v-model="draft.price" maxlength="80" /></label>
            <label>图标<input v-model="draft.emoji" maxlength="12" /></label>
            <label>备注<textarea v-model="draft.note" rows="4" maxlength="10000" /></label>
          </template>
          <template v-else><label>日期<input v-model="draft.date" type="date" /></label>
            <label>正文<textarea v-model="draft.content" rows="8" maxlength="50000" /></label></template>
          <div class="business-actions"><button class="primary" :disabled="busy">保存</button>
            <button class="secondary" type="button" :disabled="busy" @click="edit = false; draft = blank(); target = undefined">取消</button></div>
        </form>
        <p v-if="hidden">有 {{ hidden }} 条记录未能解密，未对它们作任何改动。</p>
        <p v-if="!filtered.length && !busy">没有符合条件的条目。</p>
        <article v-for="row in filtered" :key="row.id" class="business-panel glass">
          <h2>{{ row.data.emoji }} {{ row.data.title }}</h2><p>{{ tab === 'wish' ? [row.data.category, row.data.price, row.data.done ? '已完成' : '未完成'].filter(Boolean).join(' · ') : row.data.date }}</p>
          <p class="preserve">{{ tab === 'wish' ? row.data.note : row.data.content }}</p>
          <div class="business-actions"><button class="secondary" type="button" :disabled="busy" @click="editor(row)">编辑</button>
            <button v-if="tab === 'wish'" class="secondary" type="button" :disabled="busy" @click="toggle(row)">{{ row.data.done ? '设为未完成' : '标记完成' }}</button>
            <button class="secondary" type="button" :disabled="busy" @click="remove(row)">删除</button></div>
        </article>
      </template>
    </template>
  </section>
</template>
