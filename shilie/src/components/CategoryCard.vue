<script setup lang="ts">
import { ArrowUpRight } from "lucide-vue-next";
import { topLevelModules, type Category } from "@/views/category/categories.config";
defineProps<{ category: Category; index: number }>();
</script>

<template>
  <RouterLink :to="'/category/' + category.id" class="category-card" :data-tint="category.tint"
    :style="{ '--entry-delay': index * 80 + 'ms' }">
    <span class="category-icon"><component :is="category.icon" :size="22" aria-hidden="true" /></span>
    <ArrowUpRight class="card-arrow" :size="19" aria-hidden="true" />
    <div class="category-copy">
      <h2>{{ category.name }}</h2>
      <p>{{ category.caption }}</p>
    </div>
    <small>{{ topLevelModules(category).length }} 个模块</small>
  </RouterLink>
</template>
