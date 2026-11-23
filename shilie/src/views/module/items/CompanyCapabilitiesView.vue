<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { messageOf, request } from "@/api";
import { archiveRecord, saveRecord, type Fields, type Row } from "@/records";
type Skill = { name: string; requirement: string; level: number; status: string; evidence: string };
type Sheet = Row<Fields & { company: string; role: string; source: string; notes: string; capabilities: Skill[] }>;
const props = defineProps<{ company?: string; gapsOnly?: boolean; leadId?: string }>();
const rows = ref<Sheet[]>([]), error = ref(""), note = ref(""), busy = ref(false), open = ref(false);
const visible = computed(() => rows.value.filter(row => !props.company || row.data.company === props.company)
  .map(row => ({ row, items: row.data.capabilities.filter(item => !props.gapsOnly || item.status !== "evidence") }))
  .filter(item => !props.gapsOnly || item.items.length));
const current = ref<Sheet>();
const blank = (): Skill => ({ name: "", requirement: "must", level: 3, status: "pending", evidence: "" });
const form = ref({ company: "", role: "", source: "", notes: "", capabilities: [blank()] });
function edit(row?: Sheet) {
  current.value = row;
  form.value = row ? { company: row.data.company, role: row.data.role, source: row.data.source, notes: row.data.notes,
    capabilities: row.data.capabilities.map(item => ({ ...item })) } : { company: props.company || "", role: "", source: "", notes: "", capabilities: [blank()] };
  open.value = true; error.value = ""; note.value = "";
}
async function load() { rows.value = await request<Sheet[]>("jobs/capabilities"); }
async function perform(action: () => Promise<void>) {
  if (busy.value) return;
  busy.value = true; error.value = ""; note.value = "";
  try { await action(); } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
onMounted(() => perform(load));
function save() { return perform(async () => { await saveRecord("jobs/capabilities", form.value, current.value); open.value = false; await load(); note.value = "已保存能力清单。"; }); }
function remove(row: Sheet) {
  if (!confirm("将此能力清单移入回收站？")) return;
  return perform(async () => { await archiveRecord(row); await load(); note.value = "已归档能力清单。"; });
}
</script>
<template>
  <section class="business-stack">
    <div class="business-actions">
      <button v-if="!gapsOnly" class="primary" type="button" :disabled="busy" @click="edit()">添加能力清单</button>
      <RouterLink v-if="gapsOnly && leadId" class="secondary" :to="{ path: '/module/job-insights', query: { lead: leadId } }">打开当前岗位证据对照</RouterLink>
    </div>
    <form v-if="open" class="business-form glass" @submit.prevent="save"><h2>{{ current ? '编辑能力清单' : '新建能力清单' }}</h2>
      <div class="business-columns"><label>公司<input v-model="form.company" :readonly="!!company" required maxlength="160" /></label>
        <label>岗位<input v-model="form.role" maxlength="160" /></label></div>
      <label>来源<input v-model="form.source" maxlength="2000" /></label>
      <fieldset v-for="(item,index) in form.capabilities" :key="index" class="business-form"><legend>能力 {{ index + 1 }}</legend>
        <div class="business-columns"><label>名称<input v-model="item.name" maxlength="120" required /></label>
        <label>要求<select v-model="item.requirement"><option value="must">必须</option><option value="nice">加分</option></select></label>
        <label>重要度<input type="number" min="1" max="5" v-model.number="item.level" required /></label>
        <label>状态<select v-model="item.status"><option value="evidence">有证据</option><option value="pending">待核对</option><option value="missing">需补充</option></select></label></div>
        <label>证据<textarea v-model="item.evidence" rows="2" /></label>
        <button v-if="form.capabilities.length > 1" class="secondary" type="button" @click="form.capabilities.splice(index,1)">移除这一项</button></fieldset>
      <button class="secondary" :disabled="form.capabilities.length >= 30" type="button" @click="form.capabilities.push(blank())">添加一项能力</button>
      <label>备注<textarea v-model="form.notes" rows="2" maxlength="10000" /></label>
      <div class="business-actions"><button class="primary" type="submit" :disabled="busy">保存</button>
        <button class="secondary" type="button" :disabled="busy" @click="open = false">取消</button></div>
    </form>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p><p v-if="note" role="status">{{ note }}</p>
    <p v-if="!busy && !visible.length && !error">{{ gapsOnly ? '没有标记为待核对或需补充的能力。' : '还没有目标公司能力清单。' }}</p>
    <article v-for="{ row, items } in visible" :key="row.id" class="business-panel glass"><h3>{{ row.data.company }} {{ row.data.role }}</h3>
      <ul class="simple-list"><li v-for="item in items" :key="item.name"><b>{{ item.name }}</b> · {{ item.requirement === 'must' ? '必须' : '加分' }} · 重要度 {{ item.level }}
        · {{ item.status === 'evidence' ? '有证据' : item.status === 'pending' ? '待核对' : '需补充' }}
        <p v-if="item.evidence" class="preserve">{{ item.evidence }}</p></li></ul>
      <div class="business-actions"><button class="secondary" type="button" :disabled="busy" @click="edit(row)">编辑能力清单</button>
        <button v-if="!gapsOnly" class="secondary" type="button" :disabled="busy" @click="remove(row)">归档</button></div></article>
  </section>
</template>
