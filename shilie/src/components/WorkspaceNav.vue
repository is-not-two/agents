<script setup lang="ts">
import { computed, useId } from "vue";
import { useRoute } from "vue-router";
import { ArrowUpLeft, ChevronRight, House, Trash2 } from "lucide-vue-next";
import { CATEGORIES, findModule, topLevelModules } from "@/views/category/categories.config";

const route = useRoute();
const props = defineProps<{ expanded: Record<string, boolean> }>();
const emit = defineEmits<{ toggle: [id: string, expanded: boolean] }>();
const navId = useId();
const found = computed(() => findModule(String(route.params.moduleId || "")));
const activeModule = computed(() => found.value?.module.parentModuleId ?? found.value?.module.id);
const activeCategory = computed(() => String(route.params.categoryId ||
  found.value?.category.id || ""));
const isExpanded = (id: string) => props.expanded[id] ?? (activeCategory.value === id);
</script>

<template>
  <nav class="workspace-nav" aria-label="工作台导航">
    <RouterLink to="/workspace" class="workspace-nav-home" :aria-current="route.path === '/workspace' ? 'page' : undefined">
      <House :size="17" aria-hidden="true" /> 工作台
    </RouterLink>
    <ul class="workspace-groups">
      <li v-for="category in CATEGORIES" :key="category.id">
        <button type="button" class="workspace-group" :class="{ 'group-active': activeCategory === category.id }"
          :aria-expanded="isExpanded(category.id)" :aria-controls="navId + '-' + category.id"
          @click="emit('toggle', category.id, !isExpanded(category.id))">
          <component :is="category.icon" :size="17" aria-hidden="true" />
          <span>{{ category.name }}</span><ChevronRight :size="15" aria-hidden="true" />
        </button>
        <ul v-show="isExpanded(category.id)" :id="navId + '-' + category.id" class="workspace-modules">
          <li v-for="module in topLevelModules(category)" :key="module.id">
            <RouterLink :to="'/module/' + module.id" :aria-current="activeModule === module.id ? 'page' : undefined"
              :class="{ 'module-active': activeModule === module.id }">{{ module.name }}</RouterLink>
          </li>
        </ul>
      </li>
    </ul>
    <RouterLink to="/trash" class="workspace-nav-home" :aria-current="route.path === '/trash' ? 'page' : undefined">
      <Trash2 :size="17" aria-hidden="true" /> 回收站
    </RouterLink>
    <RouterLink to="/" class="workspace-exit"><ArrowUpLeft :size="16" aria-hidden="true" /> 返回开始页</RouterLink>
  </nav>
</template>
