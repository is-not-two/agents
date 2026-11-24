<script setup lang="ts">
import { ArrowUpRight } from "lucide-vue-next";
import type { ModuleInfo } from "@/views/category/categories.config";
defineProps<{ module: ModuleInfo }>();
</script>

<template>
  <RouterLink class="module-card glass" :to="'/module/' + module.id">
    <div><h2>{{ module.name }}</h2><p v-if="module.desc">{{ module.desc }}</p></div>
    <ArrowUpRight :size="20" aria-hidden="true" />
  </RouterLink>
</template>
