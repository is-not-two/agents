<script setup lang="ts">
import { useTheme } from "@/stores/theme";
const theme = useTheme();
</script>
<template>
  <section class="business-panel glass"><h2>显示与动效</h2><p>设置仅保存在这台设备。</p>
    <div class="business-actions"><button class="secondary" type="button" @click="theme.toggleDark()">{{ theme.dark ? "切换明亮主题" : "切换暗色主题" }}</button>
      <button class="secondary" type="button" :disabled="theme.reduced" @click="theme.toggleMotion()">{{ theme.animated ? "关闭动效" : "开启动效" }}</button></div>
    <p><button class="secondary" :aria-pressed="theme.native" @click="theme.toggleNative()">原生壁纸：{{ theme.native ? "开" : "关" }}</button></p>
    <label v-if="theme.native">选择图片或视频（仅本次打开使用，不上传）
      <input type="file" accept="image/*,video/*" @change="theme.select(($event.target as HTMLInputElement).files?.[0])">
    </label>
    <p v-if="theme.reduced" class="muted">已跟随系统的减少动效设置。</p></section>
</template>
