<script setup lang="ts">
import { onMounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
type Config = { base_url: string; model: string; revision: string; has_api_key: boolean; configured: boolean };
const config = ref<Config>(), base = ref(""), model = ref(""), key = ref(""), busy = ref(false), error = ref(""), note = ref("");
function adopt(value: Config) { config.value = value; base.value = value.base_url; model.value = value.model; key.value = ""; }
async function run(action: () => Promise<void>) {
  if (busy.value || isDemo) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await action(); } catch (reason) { error.value = messageOf(reason); } finally { busy.value = false; }
}
function load() { return run(async () => adopt(await request<Config>("model-connection"))); }
onMounted(load);
function payload() { return { base_url: base.value, model: model.value, api_key: key.value, revision: config.value?.revision }; }
function save() { return run(async () => { adopt(await send<Config>("model-connection", payload(), "PUT")); note.value = "连接已保存。"; }); }
function test() { return run(async () => { await send("model-connection/test", payload()); note.value = "连接测试通过，未保存输入。"; }); }
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不接受真实密钥。正式模式下可读取、测试并保存服务器模型连接。</p>
    <form v-else class="business-form glass" @submit.prevent="save">
      <p>{{ config?.configured ? "服务器已有模型连接。" : "还没有可用的模型连接。" }}</p>
      <label>API 地址<input type="url" v-model="base" required maxlength="2048" /></label>
      <label>模型名称<input v-model="model" required maxlength="160" /></label>
      <label>API 密钥<input type="password" v-model="key" :required="!config?.has_api_key" autocomplete="new-password" maxlength="8192" :placeholder="config?.has_api_key ? '留空保留已有密钥' : '输入服务商密钥'" /></label>
      <p class="muted">密钥不写入浏览器存储。</p>
      <div class="business-actions"><button class="primary" :disabled="busy || !config">保存连接</button>
        <button class="secondary" type="button" :disabled="busy || !config || !base || !model || (!key && !config.has_api_key)" @click="test">测试连接</button>
        <button class="secondary" type="button" :disabled="busy" @click="load">重新读取</button></div>
    </form>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
  </section>
</template>
