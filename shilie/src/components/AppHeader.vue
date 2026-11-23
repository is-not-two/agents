<script setup lang="ts">
import { ref } from "vue";
import { useRouter } from "vue-router";
import { Activity, Command, LogOut, Moon, Sun } from "lucide-vue-next";
import { useTheme } from "@/stores/theme";
import { useAuth } from "@/stores/auth";
import { isDemo } from "@/api";
import CommandPalette from "./CommandPalette.vue";

const theme = useTheme();
const auth = useAuth();
const router = useRouter();
const palette = ref<InstanceType<typeof CommandPalette>>();
const error = ref("");
async function logout() {
  try { await auth.logout(); await router.replace("/login"); }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "退出失败"; }
}
</script>

<template>
  <header class="topbar">
    <div class="topbar-inner">
      <RouterLink to="/workspace" class="wordmark"><span class="mark" aria-hidden="true">时</span><strong>时列</strong></RouterLink>
      <span class="header-caption">个人工作区</span>
      <span v-if="isDemo" class="demo-pill">演示版</span>
      <div class="header-actions">
        <button class="command-trigger" type="button" aria-label="快速打开" @click="palette?.show()">
          <Command :size="16" aria-hidden="true" /><span>快速打开</span><kbd>Ctrl K</kbd>
        </button>
        <button class="icon-button" type="button" :aria-label="theme.animated ? '关闭动效' : '开启动效'"
          :aria-pressed="!theme.animated" :disabled="theme.reduced" @click="theme.toggleMotion()"><Activity :size="18" /></button>
        <button class="icon-button" type="button" :aria-label="theme.dark ? '切换明亮主题' : '切换暗色主题'" @click="theme.toggleDark()">
          <Sun v-if="theme.dark" :size="18" /><Moon v-else :size="18" />
        </button>
        <button v-if="auth.session?.required" class="icon-button" type="button" aria-label="退出登录" @click="logout"><LogOut :size="17" /></button>
      </div>
    </div>
    <p v-if="error" class="header-error" role="alert">{{ error }}</p>
  </header>
  <CommandPalette ref="palette" />
</template>
