<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { request } from "@/api";
import type { Row } from "@/records";
type Task = { id: string; title: string; due_date: string; done: boolean };
type Plan = Row<{ title: string; acts: { nodes: Task[] }[] }>;
type Note = Row<{ title: string }>;
const plans = ref<Plan[]>(), notes = ref<Note[]>(), busy = ref(true);
function localDay(now: Date) {
  return [now.getFullYear(), now.getMonth() + 1, now.getDate()].map(part => String(part).padStart(2, "0")).join("-");
}
const due = computed(() => {
  const today = localDay(new Date());
  return (plans.value || []).flatMap(plan => plan.data.acts.flatMap(act => act.nodes
    .filter(task => !task.done && task.due_date === today)
    .map(task => ({ ...task, planId: plan.id, planTitle: plan.data.title })))).slice(0, 5);
});
const latest = computed(() => [...(notes.value || [])]
  .sort((a, b) => (Date.parse(b.updated_at || "") || 0) - (Date.parse(a.updated_at || "") || 0)).slice(0, 3));
async function refresh() {
  busy.value = true;
  const [p, n] = await Promise.allSettled([request<Plan[]>("plans"), request<Note[]>("knowledge")]);
  plans.value = p.status === "fulfilled" ? p.value : undefined;
  notes.value = n.status === "fulfilled" ? n.value : undefined;
  busy.value = false;
}
onMounted(refresh);
</script>

<template>
  <section class="business-columns" aria-label="今日工作区">
    <article class="business-panel glass">
      <h2>今日到期</h2>
      <p v-if="busy" role="status">正在读取规划…</p>
      <p v-else-if="!plans">暂时无法读取规划。</p>
      <p v-else-if="!due.length">今天没有到期的未完成任务。</p>
      <ul v-else class="simple-list"><li v-for="task in due" :key="task.planId + ':' + task.id">
        <RouterLink :to="{ path: '/module/planning', query: { plan: task.planId, task: task.id } }">{{ task.title }}</RouterLink>
        <small> · {{ task.planTitle }}</small>
      </li></ul>
    </article>
    <article class="business-panel glass">
      <h2>最近笔记</h2>
      <p v-if="busy" role="status">正在读取笔记…</p>
      <p v-else-if="!notes">暂时无法读取笔记。</p>
      <p v-else-if="!latest.length">还没有笔记。</p>
      <ul v-else class="simple-list"><li v-for="note in latest" :key="note.id">
        <RouterLink :to="{ name: 'item-detail', params: { moduleId: 'knowledge', itemId: note.id } }">{{ note.data.title }}</RouterLink>
      </li></ul>
    </article>
    <button v-if="!busy && (!plans || !notes)" class="secondary" type="button" @click="refresh">重新读取今日工作区</button>
  </section>
</template>
