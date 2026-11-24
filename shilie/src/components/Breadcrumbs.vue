<script setup lang="ts">
import { computed } from "vue";
import { useRoute } from "vue-router";
import { ChevronRight } from "lucide-vue-next";
import { findCategory, findModule } from "@/views/category/categories.config";

const route = useRoute();
const crumbs = computed(() => {
  const list = [{ label: "工作台", to: "/workspace" }];
  if (route.name === "trash") list.push({ label: "回收站", to: "/trash" });
  const cat = findCategory(String(route.params.categoryId || ""));
  const found = findModule(String(route.params.moduleId || ""));
  if (cat) list.push({ label: cat.name, to: "/category/" + cat.id });
  if (found) {
    list.push({ label: found.category.name, to: "/category/" + found.category.id });
    const parent = found.category.modules.find(module => module.id === found.module.parentModuleId);
    if (parent) list.push({ label: parent.name, to: "/module/" + parent.id });
    list.push({ label: found.module.name, to: "/module/" + found.module.id });
    if (route.params.itemId) list.push({
      label: found.module.id === "job-flow" ? String(route.params.itemId) : "条目详情",
      to: route.path,
    });
  }
  return list;
});
</script>

<template>
  <nav v-if="crumbs.length > 1" class="breadcrumbs" aria-label="面包屑">
    <template v-for="(crumb, index) in crumbs" :key="crumb.to">
      <ChevronRight v-if="index" :size="13" aria-hidden="true" />
      <span v-if="index === crumbs.length - 1" aria-current="page">{{ crumb.label }}</span>
      <RouterLink v-else :to="crumb.to">{{ crumb.label }}</RouterLink>
    </template>
  </nav>
</template>
