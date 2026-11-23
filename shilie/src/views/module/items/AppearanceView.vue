<script setup lang="ts">
import { useTheme } from "@/stores/theme";
const theme = useTheme();
</script>
<template>
  <section class="business-panel glass"><h2>显示与动效</h2><p>设置仅保存在这台设备。</p>
    <div class="business-actions"><button class="secondary" type="button" @click="theme.toggleDark()">{{ theme.dark ? "切换明亮主题" : "切换暗色主题" }}</button>
      <button class="secondary" type="button" :disabled="theme.reduced" @click="theme.toggleMotion()">{{ theme.animated ? "关闭动效" : "开启动效" }}</button></div>
    <p v-if="theme.reduced" class="muted">已跟随系统的减少动效设置。</p></section>
</template>
