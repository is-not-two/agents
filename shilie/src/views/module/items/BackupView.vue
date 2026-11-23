<script setup lang="ts">
import { onMounted, ref } from "vue";
import { isDemo, messageOf, request, send } from "@/api";
type Preview = { counts: Record<string, number>; change_count: number; missing_learning_sources?: number; changes: { id: string; kind: string; title: string; action: string }[];
  revision: string; snapshot_hash: string; snapshot: unknown };
const file = ref<File>(), max = ref(0), preview = ref<Preview>(), busy = ref(false), confirmed = ref("");
const error = ref(""), result = ref<{ restored_records: number; warning: string }>();
const labels: Record<string, string> = { added: "新增", updated: "修改", removed: "移入回收站", unchanged: "不变" };
function choose(event: Event) {
  file.value = (event.target as HTMLInputElement).files?.[0]; preview.value = undefined; result.value = undefined; error.value = ""; confirmed.value = "";
}
async function action(mode: "limits" | "preview" | "apply") {
  if (busy.value || isDemo) return;
  if (mode === "apply" && (!preview.value?.change_count || confirmed.value !== "恢复数据" ||
      !confirm("确认按已预览的内容恢复整个公开工作区？未包含的现有记录可能移入回收站。"))) return;
  busy.value = true; error.value = "";
  try {
    if (mode === "limits") max.value = (await request<{ max_file_bytes: number }>("import/options")).max_file_bytes;
    if (mode === "preview" && file.value) {
      confirmed.value = ""; preview.value = undefined; result.value = undefined;
      if (!max.value || file.value.size > max.value) throw new Error("超过服务端允许的文件大小。");
      let snapshot: unknown;
      try { snapshot = JSON.parse(await file.value.text()); } catch { throw new Error("文件不是有效的 JSON 备份。"); }
      preview.value = await send("import/preview", { snapshot });
    }
    if (mode === "apply" && preview.value) {
      const { revision, snapshot_hash, snapshot } = preview.value;
      // Invalidate the preview even if the response is lost; don't silently retry a restore.
      preview.value = undefined; confirmed.value = "";
      result.value = await send("import", { confirmation: "恢复数据", expected_revision: revision, snapshot_hash, snapshot });
    }
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
onMounted(() => action("limits"));
</script>
<template>
  <section class="business-stack">
    <p v-if="isDemo" class="business-panel glass">演示不读取或恢复真实工作区。请在单用户后端中使用备份功能。</p>
    <template v-else>
      <article class="business-panel glass"><h2>导出公开工作区</h2><p>不包含私密日记、愿望、模型密钥和简历原件。</p>
        <div class="business-actions"><a class="primary" href="/api/export?format=json">下载 JSON 备份</a>
          <a class="secondary" href="/api/export?format=markdown">下载 Markdown</a></div></article>
      <div class="business-form glass"><h2>从 JSON 恢复</h2>
        <label>备份文件<input type="file" accept=".json,application/json" :disabled="busy" @change="choose" /></label>
        <p v-if="max">文件上限约 {{ (max / 1048576).toFixed(1) }} MB</p>
        <button v-if="!max" class="secondary" type="button" :disabled="busy" @click="action('limits')">读取文件限制</button>
        <button v-else class="secondary" type="button" :disabled="busy || !file" @click="action('preview')">预览恢复内容</button>
      </div>
      <p v-if="busy" role="status">正在处理…</p><p v-if="error" role="alert" class="form-error">{{ error }}</p>
      <article v-if="preview" class="business-panel glass"><h2>将发生的变化</h2>
        <p v-if="preview.missing_learning_sources" role="status">有 {{ preview.missing_learning_sources }} 张复习卡的原始资料不在备份中。保留卡片和来源标记，不会重建原资料。</p>
        <dl class="business-fields"><template v-for="(count,key) in preview.counts" :key="key"><dt>{{ labels[key] || key }}</dt><dd>{{ count }}</dd></template></dl>
        <p v-if="preview.change_count > preview.changes.length">以下展示前 {{ preview.changes.length }} 条。</p>
        <ul v-if="preview.changes.length"><li v-for="item in preview.changes" :key="item.id">{{ labels[item.action] }} · {{ item.title }}</li></ul>
        <form v-if="preview.change_count" class="business-form" @submit.prevent="action('apply')">
          <label>核对预览后输入「恢复数据」<input v-model="confirmed" autocomplete="off" /></label>
          <button class="primary" :disabled="busy || confirmed !== '恢复数据'">确认恢复</button>
        </form>
        <p v-else>内容一致，无需恢复。</p>
      </article>
      <article v-if="result" class="business-panel glass"><h2>恢复结果</h2><p role="status">已处理 {{ result.restored_records }} 条记录。</p>
        <p v-if="result.warning" role="alert">{{ result.warning }}</p><RouterLink class="secondary" to="/module/stages">查看阶段记录</RouterLink></article>
    </template>
  </section>
</template>
