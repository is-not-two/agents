<script setup lang="ts">
import { ref, watch } from "vue";
import { useRoute } from "vue-router";
import { PanelLeft, X } from "lucide-vue-next";
import AppHeader from "@/components/AppHeader.vue";
import Breadcrumbs from "@/components/Breadcrumbs.vue";
import WorkspaceNav from "@/components/WorkspaceNav.vue";
const drawer = ref<HTMLDialogElement>();
const route = useRoute();
const STORAGE_KEY = "shilie.vue.sidebar";
function readExpanded(): Record<string, boolean> {
  try {
    const saved: unknown = JSON.parse(localStorage.getItem(STORAGE_KEY) || "{}");
    return saved && typeof saved === "object" && !Array.isArray(saved)
      ? Object.fromEntries(Object.entries(saved).filter(([, value]) => typeof value === "boolean"))
      : {};
  } catch { return {}; }
}
const expanded = ref(readExpanded());
function toggleGroup(id: string, open: boolean) {
  expanded.value = { ...expanded.value, [id]: open };
  try { localStorage.setItem(STORAGE_KEY, JSON.stringify(expanded.value)); } catch { /* current tab still works */ }
}
watch(() => route.path, () => drawer.value?.close());
function skipToContent() { document.getElementById("main-content")?.focus(); }
</script>

<template>
  <a class="skip-link" href="#main-content" @click.prevent="skipToContent">跳到主要内容</a>
  <AppHeader />
  <div class="workspace-layout">
    <aside class="workspace-sidebar"><WorkspaceNav :expanded="expanded" @toggle="toggleGroup" /></aside>
    <main id="main-content" class="content-shell" tabindex="-1">
      <button type="button" class="workspace-menu" @click="drawer?.showModal()"><PanelLeft :size="18" aria-hidden="true" /> 模块导航</button>
      <Breadcrumbs />
      <RouterView v-slot="{ Component, route: current }">
        <Transition name="route" mode="out-in">
          <component :is="Component" :key="current.path" />
        </Transition>
      </RouterView>
    </main>
  </div>
  <dialog ref="drawer" class="workspace-drawer" aria-label="模块导航">
    <header><strong>模块导航</strong><button class="icon-button" type="button" aria-label="关闭模块导航" @click="drawer?.close()"><X :size="18" /></button></header>
    <WorkspaceNav :expanded="expanded" @toggle="toggleGroup" />
  </dialog>
</template>
