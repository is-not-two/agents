<script setup lang="ts">
import { onMounted, ref } from "vue";
import { isDemo, messageOf, request } from "@/api";
type Stats = { storage: string; stages_count: number; rate_limit_per_minute: number; auth_enabled: boolean; llm_configured: boolean;
  kinds?: Record<string, { active: number; trash: number }>; vector?: { available: boolean; reason?: string; counts?: Record<string,number> } };
type Mcp = { server: string; transport: string; mount: string; tools?: { name: string; enabled: boolean; permission: string }[] };
type Report = { passed: boolean; profile: string; request_id?: string; checks: { id: string; status: string; message: string }[] };
const stats = ref<Stats>(), mcp = ref<Mcp>(), report = ref<Report>(), errors = ref<string[]>([]), busy = ref(false);
async function refresh() {
  if (busy.value || isDemo) return;
  busy.value = true; errors.value = []; stats.value = undefined; mcp.value = undefined; report.value = undefined;
  const errorsFound: string[] = [];
  const read = async <T,>(label: string, path: string) => {
    try { return await request<T>(path); } catch (reason) { errorsFound.push(label + "：" + messageOf(reason)); return undefined; }
  };
  [stats.value, mcp.value, report.value] = await Promise.all([read<Stats>("存储", "admin/stats"), read<Mcp>("MCP", "mcp/status"),
    read<Report>("诊断", "admin/diagnostics")]);
  errors.value = errorsFound; busy.value = false;
}
function download() {
  if (!report.value) return;
  const url = URL.createObjectURL(new Blob([JSON.stringify(report.value, null, 2)], { type: "application/json" }));
  const link = document.createElement("a"); link.href = url; link.download = "shilie-diagnostics.json"; link.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
onMounted(refresh);
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo">演示不读取真实服务诊断。</p>
    <template v-else>
      <div class="business-actions"><button type="button" class="secondary" :disabled="busy" @click="refresh">刷新诊断</button>
        <button type="button" class="secondary" :disabled="busy || !report" @click="download">下载诊断报告</button></div>
      <p v-if="busy" role="status">正在读取诊断…</p>
      <ul v-if="errors.length" role="alert" class="form-error"><li v-for="error in errors" :key="error">{{ error }}</li></ul>
      <article v-if="stats" class="business-panel glass"><h2>存储与鉴权</h2>
        <p>{{ stats.storage }} · 阶段 {{ stats.stages_count }} · 限流 {{ stats.rate_limit_per_minute }}/分钟 · {{ stats.auth_enabled ? '鉴权开启' : '未开启鉴权' }} · {{ stats.llm_configured ? '已配置模型' : '未配置模型' }}</p>
        <p v-if="stats.vector">向量库：{{ stats.vector.available ? '可用' : '不可用 · ' + (stats.vector.reason || '原因未知') }}</p>
        <dl class="business-fields"><template v-for="(count,kind) in stats.kinds" :key="kind"><dt>{{ kind }}</dt><dd>有效 {{ count.active }} · 归档 {{ count.trash }}</dd></template></dl>
      </article>
      <article v-if="mcp" class="business-panel glass"><h2>MCP 服务</h2><p>{{ mcp.server }} · {{ mcp.transport }} · {{ mcp.mount }}</p>
        <ul><li v-for="tool in mcp.tools" :key="tool.name">{{ tool.name }} · {{ tool.enabled ? '启用' : '关闭' }} · {{ tool.permission }}</li></ul></article>
      <article v-if="report" class="business-panel glass"><h2>运行诊断：{{ report.passed ? '通过' : '存在待处理项' }}</h2>
        <p>{{ report.profile }} · {{ report.request_id }}</p>
        <ul><li v-for="(item,i) in report.checks" :key="i" :class="{ 'form-error': item.status === 'fail' }">{{ item.id }} · {{ item.status }} · {{ item.message }}</li></ul></article>
    </template>
  </section>
</template>
