<script setup lang="ts">
import { ref } from "vue";
import { isDemo, messageOf, send } from "@/api";
const text = ref(""), suggestion = ref(""), busy = ref(false), error = ref(""), note = ref("");
async function optimize() {
  if (isDemo || busy.value || !text.value.trim() || !confirm("把当前草稿发送给已配置的模型？可能计费，不会自动保存或运行。")) return;
  busy.value = true; error.value = ""; note.value = ""; suggestion.value = "";
  try { suggestion.value = (await send<{ optimized: string }>("prompt/optimize", { text: text.value.trim(), target: "workspace" })).optimized; }
  catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
</script>
<template>
  <details class="business-panel glass">
    <summary>提示词优化</summary>
    <form class="business-form" @submit.prevent="optimize">
      <label>提示词草稿<textarea v-model="text" rows="3" maxlength="4000" :disabled="busy" required /></label>
      <p v-if="isDemo">演示不发送提示词或调用模型。</p>
      <button class="secondary" :disabled="isDemo || busy || !text.trim()">{{ busy ? '正在生成…' : '优化提示词' }}</button>
      <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
    </form>
    <div v-if="suggestion" class="business-form">
      <label>优化结果（可编辑）<textarea v-model="suggestion" rows="4" maxlength="8000" /></label>
      <div class="business-actions"><button type="button" class="primary" :disabled="!suggestion.trim()" @click="text = suggestion; suggestion = ''; note = '已应用到草稿，尚未运行。'">应用到草稿</button>
        <button type="button" class="secondary" @click="suggestion = ''; note = '已保留原草稿。'">放弃结果</button></div>
    </div>
  </details>
</template>
