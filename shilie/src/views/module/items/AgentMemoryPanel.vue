<script setup lang="ts">
import { ref, watch } from "vue";
import { messageOf, request, send } from "@/api";
import { segment, type Row } from "@/records";

const props = defineProps<{ agent: { id: string; version: number }; disabled: boolean }>();
const project = defineModel<string>({ required: true });
type Entry = Row<{ content: string; state: string; source_title?: string }>;
const entries = ref<Entry[]>([]), loaded = ref(false), busy = ref(false), error = ref("");
const content = ref(""), filename = ref("");
const words = { confirm: "确认保存长期记忆", reject: "拒绝记忆", forget: "确认遗忘" };
const path = () => "agents/" + segment(props.agent.id) + "/memory";
const key = () => project.value.trim().normalize("NFC");
watch(project, () => { loaded.value = false; entries.value = []; });

async function apply(task: () => Promise<void>) {
  if (busy.value || props.disabled) return;
  busy.value = true; error.value = "";
  try { await task(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function refresh() {
  entries.value = await request<Entry[]>(path() + "?" + new URLSearchParams({ project: key() }));
  loaded.value = true;
}
function readFile(event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  void apply(async () => {
    if (!/\.(md|markdown)$/i.test(file.name) || file.size > 128 * 1024) throw Error("请选择 128 KB 以内的 Markdown 文件");
    const value = new TextDecoder("utf-8", { fatal: true }).decode(await file.arrayBuffer());
    if (!value.trim() || value.includes("\0")) throw Error("笔记为空或不是文本");
    filename.value = file.name; content.value = value;
  });
}
function propose() {
  return apply(async () => {
    await send(path(), { project: key(), content: content.value.trim(), source_title: filename.value,
      agent_version: props.agent.version, request_id: Array.from(crypto.getRandomValues(new Uint8Array(16)), n => n.toString(16).padStart(2, "0")).join("") });
    content.value = ""; filename.value = ""; await refresh();
  });
}
function decide(row: Entry, action: keyof typeof words) {
  return apply(async () => {
    await send(path() + "/" + segment(row.id) + "/decide", { project: key(), agent_version: props.agent.version,
      version: row.version, action, confirmation: words[action] });
    await refresh();
  });
}
</script>

<template>
  <section class="business-form glass" aria-label="项目记忆与笔记">
    <h2>项目记忆与笔记</h2>
    <label>记忆项目<input v-model="project" maxlength="80" :disabled="busy || disabled" placeholder="例如：项目 A" /></label>
    <p>运行时只使用此 Agent 在所填项目内已确认的条目。留空仅使用未分组的记忆。</p>
    <div class="business-actions"><button type="button" class="secondary" :disabled="busy || disabled" @click="apply(refresh)">查看此范围的记忆</button></div>
    <details>
      <summary>新增记忆或导入 Obsidian 笔记</summary>
      <form class="business-form" @submit.prevent="propose">
        <label>选择 Markdown 文件（先填项目）<input type="file" accept=".md,.markdown" :disabled="busy || disabled || !project.trim()" @change="readFile" /></label>
        <p v-if="filename">{{ filename }} · 只导入下方文本，不修改原文件。</p>
        <label>{{ filename ? '笔记摘录（最多 2,000 字）' : '记忆内容' }}<textarea v-model="content" rows="4" :disabled="busy || disabled" /></label>
        <div class="business-actions"><button class="secondary" :disabled="busy || disabled || !content.trim() || content.trim().length > 2000 || (!!filename && !project.trim())">保存为待确认条目</button>
          <button v-if="content" type="button" class="secondary" :disabled="busy || disabled" @click="content = ''; filename = ''">清空草稿</button></div>
      </form>
    </details>
    <p v-if="busy" role="status">正在处理记忆…</p><p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <p v-if="loaded && !entries.length">此范围没有记忆。</p>
    <details v-for="row in entries" :key="row.id">
      <summary>{{ row.data.source_title || row.data.content.slice(0, 32) }} · {{ ({ pending: '待确认', confirmed: '已生效', rejected: '已拒绝', forgotten: '已遗忘' } as Record<string, string>)[row.data.state] }}</summary>
      <p class="preserve">{{ row.data.content }}</p>
      <div class="business-actions">
        <template v-if="row.data.state === 'pending'">
          <button type="button" class="primary" :disabled="busy || disabled" @click="decide(row, 'confirm')">确认用于此范围</button>
          <button type="button" class="secondary" :disabled="busy || disabled" @click="decide(row, 'reject')">拒绝</button>
        </template>
        <button v-if="row.data.state === 'confirmed'" type="button" class="secondary" :disabled="busy || disabled" @click="decide(row, 'forget')">遗忘此条目</button>
      </div>
    </details>
  </section>
</template>
