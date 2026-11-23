<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { findCategory, topLevelModules } from "./categories.config";
import ModuleCard from "@/components/ModuleCard.vue";
import EmptyState from "@/components/EmptyState.vue";
const route = useRoute();
const category = computed(() => findCategory(String(route.params.categoryId)));
const modules = computed(() => category.value ? topLevelModules(category.value) : []);
</script>

<template>
  <div class="page-frame">
    <template v-if="category">
      <header class="page-heading glass" :data-tint="category.tint">
        <span class="category-icon"><component :is="category.icon" :size="24" aria-hidden="true" /></span>
        <h1>{{ category.name }}</h1><p>{{ category.caption }}</p>
        <small>{{ modules.length }} 个模块</small>
      </header>
      <nav class="module-grid" :aria-label="category.name + '模块列表'">
        <ModuleCard v-for="module in modules" :key="module.id" :module="module" />
      </nav>
    </template>
    <EmptyState v-else title="找不到这个分类" description="可能是链接过期了。"><RouterLink to="/workspace">回到工作台</RouterLink></EmptyState>
  </div>
</template>
