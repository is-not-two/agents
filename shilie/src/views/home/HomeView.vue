<script setup lang="ts">
import { ArrowDown } from "lucide-vue-next";
import CategoryCard from "@/components/CategoryCard.vue";
import StatCard from "@/components/StatCard.vue";
import PromptDraft from "@/components/PromptDraft.vue";
import TodaySummary from "./TodaySummary.vue";
import { CATEGORIES, topLevelModules } from "@/views/category/categories.config";

const moduleCount = CATEGORIES.reduce((sum, category) => sum + topLevelModules(category).length, 0);
function showCategories() {
  document.getElementById("home-categories")?.scrollIntoView({ block: "start" });
}
</script>

<template>
  <div class="home-page page-frame">
    <section class="home-hero" aria-labelledby="hero-title">
      <div class="hero-copy">
        <p class="hero-kicker"><span></span> 时列 · 个人工作区</p>
        <h1 id="hero-title"><span>把每一步，</span><span>留在这里。</span></h1>
        <p class="hero-description">找工作、整理知识，或开始一个新的计划。<br class="desktop-break" />选一个分类，继续你手上的事。</p>
        <button type="button" class="primary" @click="showCategories">浏览工作区 <ArrowDown :size="16" aria-hidden="true" /></button>
      </div>
      <div class="hero-plate" aria-label="工作区规模">
        <div class="plate-top"><span></span> 工作区概览</div>
        <div class="plate-stats"><StatCard :value="CATEGORIES.length" label="分类" /><StatCard :value="moduleCount" label="模块" /></div>
      </div>
    </section>
    <section id="home-categories" class="home-categories" aria-labelledby="home-categories-title">
      <div class="section-line"><h2 id="home-categories-title">从这里进入</h2><span>按你现在要做的事选择</span></div>
      <nav class="category-grid" aria-label="五个工作区分类">
        <CategoryCard v-for="(category, index) in CATEGORIES" :key="category.id" :category="category" :index="index" />
      </nav>
    </section>
    <TodaySummary />
    <PromptDraft />
  </div>
</template>
