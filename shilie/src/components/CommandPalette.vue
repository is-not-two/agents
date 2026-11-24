<script setup lang="ts">
import { computed, nextTick, onMounted, onUnmounted, ref } from "vue";
import { useRouter } from "vue-router";
import { ArrowUpRight, Search, X } from "lucide-vue-next";
import { CATEGORIES } from "@/views/category/categories.config";

const dialog = ref<HTMLDialogElement>();
const input = ref<HTMLInputElement>();
const query = ref("");
const active = ref(0);
const router = useRouter();
let returnFocus: HTMLElement | undefined;
const destinations = CATEGORIES.flatMap((category) => [
  { key: "cat-" + category.id, name: category.name, context: "分类", to: "/category/" + category.id },
  ...category.modules.map((module) => ({ key: module.id, name: module.name, context: category.name, to: "/module/" + module.id })),
]);
const results = computed(() => {
  const q = query.value.trim().toLowerCase();
  return destinations.filter((entry) => [entry.name, entry.context, entry.key].some((value) => value.toLowerCase().includes(q))).slice(0, 10);
});
function show() {
  if (!dialog.value || dialog.value.open) return;
  returnFocus = document.activeElement instanceof HTMLElement ? document.activeElement : undefined;
  query.value = ""; active.value = 0;
  dialog.value.showModal();
  nextTick(() => input.value?.focus());
}
function open(to?: string) {
  if (!to) return;
  dialog.value?.close();
  void router.push(to);
}
function keyboard(event: KeyboardEvent) {
  if ((event.ctrlKey || event.metaKey) && event.key.toLowerCase() === "k") {
    event.preventDefault();
    if (dialog.value?.open) dialog.value.close();
    else show();
  }
}
function move(by: number) {
  const count = results.value.length;
  if (count) {
    active.value = (active.value + by + count) % count;
    nextTick(() => document.getElementById("command-result-" + active.value)?.scrollIntoView({ block: "nearest" }));
  }
}
onMounted(() => addEventListener("keydown", keyboard));
onUnmounted(() => removeEventListener("keydown", keyboard));
defineExpose({ show });
</script>

<template>
  <dialog ref="dialog" class="palette" aria-label="快速打开模块" @close="returnFocus?.focus()">
    <div class="palette-input">
      <Search :size="20" aria-hidden="true" />
      <input ref="input" v-model="query" aria-label="搜索模块" placeholder="搜索分类或模块…" @input="active = 0"
        @keydown.down.prevent="move(1)" @keydown.up.prevent="move(-1)" @keydown.enter.prevent="open(results[active]?.to)" />
      <button class="icon-button" type="button" aria-label="关闭快速打开" @click="dialog?.close()"><X :size="18" /></button>
    </div>
    <ul v-if="results.length" class="palette-results">
      <li v-for="(result, index) in results" :key="result.key">
        <button :id="'command-result-' + index" type="button" :class="{ 'result-active': index === active }"
          @pointerenter="active = index" @click="open(result.to)">
          <span><strong>{{ result.name }}</strong><small>{{ result.context }}</small></span><ArrowUpRight :size="17" aria-hidden="true" />
        </button>
      </li>
    </ul>
    <p v-else class="palette-empty" role="status">没有匹配的模块。</p>
    <p class="palette-hint"><kbd>↑</kbd> <kbd>↓</kbd> 选择　<kbd>Enter</kbd> 打开　<kbd>Esc</kbd> 关闭</p>
  </dialog>
</template>
