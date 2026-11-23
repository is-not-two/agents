<script setup lang="ts">
import { onMounted, ref } from "vue";
import { messageOf, request, send } from "@/api";
type Question = { qid: string; type: string; question: string; anchors: string[] };
type Result = { rerank: boolean; total: number; failures: number; recall: Record<string, { passed: number; total: number; rate: number }>;
  items: (Question & { final_rank: number | null; vector_rank: number | null; failure: string; reference_answer: string;
    hits: { rank: number; id: string; title: string; score: number; is_anchor: boolean }[] })[] };
const questions = ref<Question[]>([]), raw = ref<Result>(), reranked = ref<Result>(), busy = ref(false), error = ref("");
const runLabel = ref("");
async function load() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try { questions.value = (await request<{ items: Question[] }>("eval/questions")).items; }
  catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
async function evaluate(rerank: boolean) {
  if (busy.value) return;
  busy.value = true; error.value = ""; runLabel.value = rerank ? "正在评测重排…" : "正在评测向量基线…";
  try {
    const result = await send<Result>("eval/run?rerank=" + rerank, {});
    if (rerank) reranked.value = result; else raw.value = result;
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; runLabel.value = ""; }
}
onMounted(load);
</script>
<template>
  <section class="business-stack">
    <article class="business-panel glass"><h2>检索评测</h2><p>同一题集分别运行向量基线和重排；结果不会写入业务记录。</p>
      <div class="business-actions"><button class="secondary" type="button" :disabled="busy" @click="evaluate(false)">运行向量基线</button>
        <button class="primary" type="button" :disabled="busy" @click="evaluate(true)">运行重排评测</button>
        <button class="secondary" type="button" :disabled="busy" @click="load">刷新题集</button></div>
      <p v-if="runLabel" role="status">{{ runLabel }}</p><p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <details v-if="questions.length"><summary>查看 {{ questions.length }} 道评测题</summary>
        <ol><li v-for="item in questions" :key="item.qid">{{ item.question }}<small> · 锚点 {{ item.anchors.join('、') }}</small></li></ol>
      </details>
    </article>
    <article v-for="result in [raw, reranked].filter(item => item != null)" :key="String(result.rerank)" class="business-panel glass">
      <h2>{{ result.rerank ? '重排结果' : '向量基线结果' }}</h2><p>共 {{ result.total }} 题，{{ result.failures }} 题未命中目标范围。</p>
      <dl class="business-fields"><template v-for="(value,key) in result.recall" :key="key">
        <dt>{{ key }}</dt><dd>{{ (value.rate * 100).toFixed(1) }}%（{{ value.passed }}/{{ value.total }}）</dd></template></dl>
      <details v-for="item in result.items" :key="item.qid"><summary>{{ item.question }}</summary>
        <p>向量名次 {{ item.vector_rank ?? '未召回' }} · 最终名次 {{ item.final_rank ?? '未召回' }}<span v-if="item.failure"> · {{ item.failure }}</span></p>
        <p v-if="item.reference_answer" class="preserve">{{ item.reference_answer }}</p>
        <ul><li v-for="hit in item.hits" :key="hit.rank">{{ hit.rank }}. {{ hit.title || hit.id }} · {{ hit.score }}<strong v-if="hit.is_anchor"> · 命中锚点</strong></li></ul>
      </details>
    </article>
  </section>
</template>
