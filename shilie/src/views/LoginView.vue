<script setup lang="ts">
import { computed, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ArrowRight, Eye, EyeOff } from "lucide-vue-next";
import { useAuth } from "@/stores/auth";
import { isDemo } from "@/api";

const auth = useAuth(), router = useRouter(), route = useRoute();
const username = ref(""), password = ref(""), showPassword = ref(false);
const remember = ref(false), tokenOnly = computed(() => auth.session?.account_login === false);
const busy = ref(false), error = ref("");
const next = computed(() => {
  const target = route.query.next;
  return typeof target === "string" && /^\/(?:$|(?:workspace|trash)(?:\?|$)|(?:category|module)\/)/.test(target)
    ? target : "/";
});
async function login() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    await auth.login(tokenOnly.value ? { token: password.value } : { username: username.value, password: password.value, remember: remember.value });
    await router.replace(next.value);
  }
  catch (reason) { error.value = reason instanceof Error ? reason.message : "登录失败"; }
  finally { password.value = ""; busy.value = false; }
}
function demo() { auth.enterDemo(); void router.replace(next.value); }
</script>

<template>
  <section class="login-shell">
    <div class="login-scene">
      <p class="hero-kicker"><span></span> 时列 · 个人工作区</p>
      <h1>把每一步，<br />留在这里。</h1>
      <p>知识、求职和下一步计划，都有自己的位置。</p>
    </div>
    <section class="login-card glass" aria-labelledby="login-title">
      <span v-if="isDemo" class="demo-pill">演示环境</span>
      <h2 id="login-title">进入时列</h2>
      <p v-if="isDemo">这里不连接你的账号或真实资料。可以直接体验页面。</p>
      <p v-else>{{ next !== "/" ? "登录后回到你刚才打开的页面。" : tokenOnly ? "使用工作区访问令牌登录。" : "使用现有账号登录个人工作区。" }}</p>
      <form v-if="!isDemo" class="login-form" @submit.prevent="login">
        <label v-if="!tokenOnly">账号<input v-model="username" name="username" autocomplete="username" required maxlength="64" /></label>
        <label>{{ tokenOnly ? '访问令牌' : '密码' }}<span class="password-field">
          <input v-model="password" :name="tokenOnly ? 'token' : 'password'" :type="showPassword ? 'text' : 'password'"
            :autocomplete="tokenOnly ? 'off' : 'current-password'" required :maxlength="tokenOnly ? 4096 : 256" />
          <button type="button" class="icon-button" :aria-label="showPassword ? '隐藏密码' : '显示密码'" @click="showPassword = !showPassword">
            <EyeOff v-if="showPassword" :size="18" /><Eye v-else :size="18" />
          </button>
        </span></label>
        <label v-if="!tokenOnly" class="check-line"><input v-model="remember" type="checkbox" /> 在此设备记住登录</label>
        <p v-if="error || auth.statusError" class="form-error" role="alert">{{ error || auth.statusError }}</p>
        <button class="primary" type="submit" :disabled="busy">{{ busy ? "登录中…" : "登录" }} <ArrowRight :size="17" /></button>
      </form>
      <button v-else class="primary" type="button" @click="demo">进入演示 <ArrowRight :size="17" /></button>
    </section>
  </section>
</template>
