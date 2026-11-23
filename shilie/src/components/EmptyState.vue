<script setup lang="ts">
import { FolderOpen } from "lucide-vue-next";
defineProps<{ title: string; description: string }>();
</script>

<template>
  <section class="empty-state glass">
    <FolderOpen :size="30" aria-hidden="true" />
    <h2>{{ title }}</h2><p>{{ description }}</p>
    <slot />
  </section>
</template>
