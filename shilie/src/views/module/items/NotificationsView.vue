<script setup lang="ts">
import { onMounted, ref } from "vue";
import { messageOf, request, send } from "@/api";
import { segment, type Row } from "@/records";
type Item = Row<{ status: string; title: string; body: string; last_error?: string; attempts: number }>;
const inbox = ref<{ notifications: Item[]; settings: { enabled: boolean; configured: boolean } }>();
const preview = ref<{ title: string; body: string }>(), busy = ref(false), notice = ref(""), error = ref("");
const statuses: Record<string, string> = { pending: "待发送", sending: "发送中", sent: "已提交或人工核对", failed: "失败", unknown: "结果未知", cancelled: "已取消" };
const choice = { retry: "已核对未发送，允许重试", received: "已核对确实收到", cancel: "取消待发送通知" };
async function run(action = "load", row?: Item) {
  if (busy.value) return;
  if (action === "dispatch" && !confirm("立即向服务端已配置的收件人发送待发送通知？")) return;
  if (action === "daily" && !confirm("将这份摘要加入通知队列？此操作不立即发送。")) return;
  if (row && !confirm(choice[action as keyof typeof choice] + "？")) return;
  busy.value = true; error.value = ""; notice.value = "";
  try {
    if (action === "daily") {
      const result = await send<{ reused: boolean }>("notifications/daily", { confirmation: "加入通知队列" });
      notice.value = result.reused ? "今天的摘要已在队列，不重复入队。" : "已入队，未发送。";
    }
    if (action === "dispatch") {
      const result = await send<{ processed: unknown[]; recovered_unknown: number }>("notifications/dispatch", { confirmation: "发送通知" });
      notice.value = "本次处理 " + result.processed.length + " 条，请查看实际状态。";
    }
    if (row) {
      await send("notifications/" + segment(row.id) + "/resolve", { version: row.version, action, confirmation: "已核对通知结果" });
      notice.value = "已更新通知状态。";
    }
    inbox.value = await request("notifications");
    preview.value = await request("notifications/daily-preview");
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
onMounted(() => run());
</script>
<template>
  <section class="business-stack">
    <p v-if="error" role="alert" class="form-error">{{ error }}</p><p v-if="notice" role="status">{{ notice }}</p>
    <div class="business-panel glass"><h2>每日摘要</h2>
      <p v-if="inbox">{{ inbox.settings.enabled && inbox.settings.configured ? '服务端已配置发送' : '服务端发送未启用或配置不全' }}。入队与发送是两步。</p>
      <p v-if="preview" class="preserve">{{ preview.body }}</p>
      <div class="business-actions"><button type="button" class="secondary" :disabled="busy" @click="run()">刷新预览</button>
        <button type="button" class="secondary" :disabled="busy || !preview" @click="run('daily')">加入通知队列</button>
        <button type="button" class="primary" :disabled="busy || !inbox?.settings.enabled || !inbox?.settings.configured" @click="run('dispatch')">发送队列</button></div>
    </div>
    <h2>通知记录</h2><p v-if="inbox && !inbox.notifications.length">还没有通知记录。</p>
    <article v-for="row in inbox?.notifications" :key="row.id" class="business-panel glass">
      <h3>{{ row.data.title }}</h3><p>{{ statuses[row.data.status] || row.data.status }} · 尝试 {{ row.data.attempts }} 次</p>
      <p v-if="row.data.last_error" class="form-error">{{ row.data.last_error }}</p>
      <details><summary>查看消息正文</summary><p class="preserve">{{ row.data.body }}</p></details>
      <div class="business-actions"><button v-if="['failed','unknown'].includes(row.data.status)" type="button" class="secondary" :disabled="busy" @click="run('retry', row)">{{ choice.retry }}</button>
        <button v-if="row.data.status === 'unknown'" type="button" class="secondary" :disabled="busy" @click="run('received', row)">{{ choice.received }}</button>
        <button v-if="['pending','failed'].includes(row.data.status)" type="button" class="secondary" :disabled="busy" @click="run('cancel', row)">{{ choice.cancel }}</button></div>
    </article>
  </section>
</template>
