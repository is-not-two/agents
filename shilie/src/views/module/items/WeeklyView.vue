<script setup lang="ts">
import { onMounted, ref } from "vue";
import { messageOf, request, send } from "@/api";
import { labels } from "./jobs-data";
type Week = { week_start: string; as_of: string; metrics: Record<string, number | null>; pipeline_current: Record<string, number>;
  top_questions: { question: string; count: number }[]; top_weak_points: { point: string; count: number }[];
  notes: string[]; markdown?: string; status?: string };
const data = ref<{ current: Week; saved: Week | null; stale: boolean }>(), day = ref("");
const error = ref(""), notice = ref(""), busy = ref(false);
const metrics = { applications_submitted: "本周投递", interviews_recorded: "本周面试复盘", cohort_interviewed: "投递组已记录面试",
  reviews_recorded: "本周复习", knowledge_added: "本周新增知识", plan_completion_events: "规划完成事件", followups_due: "当前待跟进", reviews_due: "当前待复习" };
const path = "jobs/report/weekly";
async function action(mode: "read" | "statistics" | "model" | "repeat" | "notify" = "read") {
  if (busy.value) return;
  const model = mode === "model" || mode === "repeat";
  if (model && !confirm(mode === "repeat" ? "重新发送本周统计给模型？这可能重复收费。" : "允许将本周统计发送给已配置的模型？")) return;
  if (mode === "notify" && !confirm("生成纯统计周报并加入通知队列？入队不会立即发送。")) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    if (mode === "notify") {
      await send(path + "/notify", { day: day.value, confirmation: "加入周报通知队列" }); notice.value = "已加入通知队列，未发送。";
    } else if (mode !== "read") {
      await send(path, { day: day.value, mode: model ? "model" : "statistics",
        confirmation: model ? "发送统计进行周报增强" : "生成并保存周报", request_id: mode === "repeat" ? crypto.randomUUID() : "" });
    }
    data.value = await request(path + "?" + new URLSearchParams({ day: day.value }));
    if (!day.value) day.value = data.value?.current.week_start || "";
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
function download() {
  const saved = data.value?.saved;
  if (!saved?.markdown) return;
  const url = URL.createObjectURL(new Blob([saved.markdown], { type: "text/markdown;charset=utf-8" }));
  const link = document.createElement("a"); link.href = url; link.download = "shilie-week-" + saved.week_start + ".md"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
onMounted(() => action());
</script>
<template>
  <section class="business-stack">
    <form class="business-form glass" @submit.prevent="action()">
      <label>周内任意日期<input v-model="day" type="date" :disabled="busy" /></label>
      <div class="business-actions"><button class="secondary" :disabled="busy">查看这一周</button></div>
    </form>
    <p v-if="busy" role="status">正在处理周报…</p><p v-if="notice" role="status">{{ notice }}</p>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <article v-if="data" class="business-panel glass"><h2>{{ data.current.week_start }} 起的一周</h2>
      <dl class="business-fields"><template v-for="(label, key) in metrics" :key="key"><dt>{{ label }}</dt><dd>{{ data.current.metrics[key] }}</dd></template>
        <dt>累计进面率</dt><dd>{{ data.current.metrics.cohort_interview_rate == null ? '无分母' : (data.current.metrics.cohort_interview_rate * 100).toFixed(1) + '%' }}</dd></dl>
      <h3>当前管道分布</h3><ul><li v-for="(count, key) in data.current.pipeline_current" :key="key">{{ labels[key] || key }}：{{ count }}</li></ul>
      <h3>高频追问</h3><ul><li v-for="item in data.current.top_questions" :key="item.question">{{ item.question }}（{{ item.count }} 次）</li></ul>
      <h3>薄弱点</h3><ul><li v-for="item in data.current.top_weak_points" :key="item.point">{{ item.point }}（{{ item.count }} 次）</li></ul>
      <ul><li v-for="note in data.current.notes" :key="note">{{ note }}</li></ul>
      <div class="business-actions"><button class="primary" type="button" :disabled="busy" @click="action('statistics')">保存纯统计周报</button>
        <button class="secondary" type="button" :disabled="busy" @click="action('model')">模型排序关注项</button>
        <button v-if="data.saved?.status === 'running'" class="secondary" type="button" :disabled="busy" @click="action('repeat')">核对后重新调用模型</button>
        <button class="secondary" type="button" :disabled="busy" @click="action('notify')">加入通知队列</button></div>
    </article>
    <article v-if="data" class="business-panel glass"><h2>已保存周报</h2>
      <p v-if="data.stale">记录已变化。下面是留档快照，不会自动覆盖。</p>
      <p v-if="data.saved?.status === 'running'">上次模型请求未记账，不会自动重复发送。</p>
      <template v-if="data.saved?.markdown"><p class="preserve">{{ data.saved.markdown }}</p><button type="button" class="secondary" @click="download">下载 Markdown</button></template>
      <p v-else>这周还没有留档。</p>
    </article>
  </section>
</template>
