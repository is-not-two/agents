<script setup lang="ts">
import { onMounted, ref } from "vue";
import { useRouter } from "vue-router";
import { messageOf, request } from "@/api";
import { archiveRecord, dateText, getHistory, publicLink, restoreRecord, type Row } from "@/records";
import RecordEditor from "./RecordEditor.vue";
import type { RecordSpec } from "./record-specs";

const props = defineProps<{ moduleId: string; id: string; trash: boolean; spec: RecordSpec }>();
const router = useRouter();
const row = ref<Row>(), history = ref<Row[]>([]);
const error = ref(""), note = ref(""), editing = ref(false), loading = ref(true), busy = ref(false), historyOpen = ref(false);
async function load() {
  loading.value = true; error.value = "";
  try { row.value = (await request<Row[]>(props.spec.path + "?trash=" + props.trash)).find(r => r.id === props.id); }
  catch (reason) { error.value = messageOf(reason); }
  finally { loading.value = false; }
}
async function action(kind: "history" | "archive" | "restore", target = 0) {
  if (!row.value || busy.value) return;
  if (kind === "archive" && !confirm("移入回收站？可从历史恢复。")) return;
  if (kind === "restore" && !confirm("将这个版本恢复为新的当前版本？")) return;
  busy.value = true; error.value = ""; note.value = "";
  try {
    if (kind === "history") { history.value = await getHistory(row.value); historyOpen.value = true; }
    if (kind === "archive") { await archiveRecord(row.value); await router.push("/module/" + props.moduleId); }
    if (kind === "restore") {
      row.value = await restoreRecord(row.value, target); note.value = "已恢复为新版本。";
      if (historyOpen.value) history.value = await getHistory(row.value);
    }
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function updated(value: Row) { row.value = value; editing.value = false; historyOpen.value = false; note.value = "已保存。"; }
onMounted(load);
</script>

<template>
  <section class="business-stack">
    <p v-if="loading" role="status">正在读取记录…</p>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <p v-if="note" role="status">{{ note }}</p>
    <article v-if="row" class="business-panel glass">
      <h1>{{ row.data.title || spec.singular }}</h1>
      <p class="muted">第 {{ row.version }} 版 · {{ dateText(row.updated_at) }}</p>
      <div class="business-actions">
        <button v-if="!row.deleted" class="primary" type="button" :disabled="busy" @click="editing = !editing">编辑</button>
        <button class="secondary" type="button" :disabled="busy" @click="action('history')">查看版本历史</button>
        <button v-if="!row.deleted" class="secondary" type="button" :disabled="busy" @click="action('archive')">移入回收站</button>
      </div>
      <dl class="business-fields">
        <template v-for="field in spec.fields.filter(f => f.key !== 'title' && row?.data[f.key])" :key="field.key">
          <dt>{{ field.label }}</dt>
          <dd v-if="field.type === 'url' && publicLink(row.data[field.key])"><a :href="publicLink(row.data[field.key])" target="_blank" rel="noopener noreferrer">{{ row.data[field.key] }}</a></dd>
          <dd v-else class="preserve">{{ Array.isArray(row.data[field.key]) ? (row.data[field.key] as unknown[]).join("、") : row.data[field.key] }}</dd>
        </template>
      </dl>
    </article>
    <p v-else-if="!loading && !error" role="status">这个条目不存在，或已移动到回收站。</p>
    <RecordEditor v-if="editing && row" :spec="spec" :row="row" @saved="updated" @cancel="editing = false" />
    <section v-if="historyOpen && row" class="business-panel glass"><h2>版本历史</h2>
      <ul class="simple-list"><li v-for="old in history" :key="old.version"><span>第 {{ old.version }} 版 · {{ dateText(old.updated_at) }}</span>
        <details v-if="old.data"><summary>查看内容</summary><p class="preserve">{{ old.data.content || old.data.note || old.data.jd_text || old.data.title }}</p></details>
        <button v-if="!old.deleted && old.version !== row.version" type="button" class="secondary" :disabled="busy" @click="action('restore', old.version)">恢复此版本</button></li></ul>
    </section>
  </section>
</template>
