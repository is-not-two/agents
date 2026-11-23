<script setup lang="ts">
import { ref } from "vue";
import { isDemo, messageOf, request } from "@/api";
const file = ref<File>(), busy = ref(false), error = ref(""), runId = ref("");
async function preview() {
  if (!file.value || busy.value || isDemo) return;
  busy.value = true; error.value = ""; runId.value = "";
  try {
    const body = new FormData(); body.set("file", file.value);
    const row = await request<{ id: string }>("knowledge/import/markdown", { method: "POST", body });
    runId.value = row.id;
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
</script>
<template>
  <details class="business-panel glass">
    <summary>导入 Markdown</summary>
    <form class="business-form" @submit.prevent="preview">
      <label>Markdown 文件<input type="file" accept=".md,.markdown" required :disabled="busy || isDemo"
        @change="file = ($event.target as HTMLInputElement).files?.[0]; runId = ''; error = ''" /></label>
      <p>{{ isDemo ? '演示不上传文件。' : '先生成片段预览；只有选中并确认的片段才写入知识库。' }}</p>
      <button class="secondary" :disabled="busy || !file">{{ busy ? '正在切分…' : '生成片段预览' }}</button>
    </form>
    <p v-if="error" role="alert" class="form-error">{{ error }}</p>
    <RouterLink v-if="runId" class="primary" :to="{ path: '/module/runs', query: { run: runId, kind: 'ingest' } }">查看并选择入库片段</RouterLink>
  </details>
</template>
