<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { messageOf, request, send } from "@/api";
import { publicLink } from "@/records";

type Hit = { title?: string; source?: string; content?: string; score?: number; status_marker?: string };
type SearchResult = { engine: string; hits: Hit[]; answer: string; notes: string[] };
const query = ref(""), scope = ref("docs"), mode = ref("text"), generate = ref(false);
const namespace = ref(""), namespaces = ref<{ id: string; title: string }[]>([]);
const result = ref<SearchResult>(), error = ref(""), busy = ref(false);
const supportsNamespace = computed(() => scope.value === "docs" && namespaces.value.length > 0);
onMounted(async () => {
  try {
    const options = await request<{ namespaces?: { id?: string; namespace?: string; title?: string; label?: string }[] }>("query/options");
    namespaces.value = (options.namespaces ?? []).flatMap(row => {
      const id = row.id || row.namespace;
      return id ? [{ id, title: row.title || row.label || id }] : [];
    });
  } catch { /* a search can still use the server defaults */ }
});
async function search() {
  if (!query.value.trim() || busy.value) return;
  if (generate.value && !confirm("向已配置模型发送问题和命中资料以生成回答？")) return;
  busy.value = true; error.value = ""; result.value = undefined;
  try {
    result.value = await send<SearchResult>("query", {
      query: query.value, scope: scope.value, mode: mode.value, generate: generate.value,
      ...(supportsNamespace.value && namespace.value ? { namespace: namespace.value } : {}),
    });
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
</script>

<template>
  <section class="business-stack">
    <form class="business-form glass" @submit.prevent="search">
      <label>检索问题<input v-model="query" required maxlength="1000" placeholder="例如：如何理解向量索引的取舍？" /></label>
      <div class="business-columns"><label>范围<select v-model="scope"><option value="docs">技术文档</option><option value="personal">个人知识</option><option value="planning">规划</option><option value="all">全部</option></select></label>
      <label>方式<select v-model="mode"><option value="text">全文检索</option><option value="vector">向量检索</option></select></label></div>
      <label v-if="supportsNamespace">语料<select v-model="namespace"><option value="">服务器默认</option><option v-for="item in namespaces" :key="item.id" :value="item.id">{{ item.title }}</option></select></label>
      <label class="check-line"><input type="checkbox" v-model="generate" /> 使用模型生成回答</label>
      <button class="primary" type="submit" :disabled="busy">{{ busy ? "检索中…" : "检索" }}</button>
    </form>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <template v-if="result">
      <article v-if="result.answer" class="business-panel glass"><h2>回答</h2><p class="preserve">{{ result.answer }}</p></article>
      <p v-for="note in result.notes" :key="note" class="muted">{{ note }}</p>
      <p v-if="!result.hits.length" role="status">没有找到匹配资料。</p>
      <article v-for="(hit, index) in result.hits" :key="index" class="business-panel glass"><h3>{{ hit.title || '检索结果 ' + (index + 1) }}</h3>
        <p class="muted">{{ hit.source }} {{ hit.status_marker }}</p><p class="preserve">{{ hit.content }}</p>
        <a v-if="publicLink(hit.source)" :href="publicLink(hit.source)" target="_blank" rel="noopener noreferrer">打开来源</a></article>
    </template>
  </section>
</template>
