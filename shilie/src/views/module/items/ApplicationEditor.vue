<script setup lang="ts">
import { reactive, ref } from "vue";
import { messageOf, send } from "@/api";
import { lines, saveRecord, segment } from "@/records";
import { applicationStatusChoices, labels, timeISO, timeLocal, type Application, type Lead, type Question, type Report, type Resume } from "./jobs-data";
const props = defineProps<{ lead: Lead; resumes: Resume[]; row?: Application; report?: Report; applicationId?: string }>();
const emit = defineEmits<{ saved: []; cancel: [] }>();
const reportMode = Boolean(props.applicationId);
const source = props.row?.data;
const allowedStatuses = applicationStatusChoices(source?.status);
const app = reactive({ status: source?.status || "collected", channel: source?.channel || "",
  resume_version_id: source?.resume_version_id || "", applied_at: timeLocal(source?.applied_at),
  follow_up_at: timeLocal(source?.follow_up_at), notes: source?.notes || "" });
const rep = reactive({ round: props.report?.data.round || 1, interviewed_at: timeLocal(props.report?.data.interviewed_at),
  questions: props.report?.data.questions.map(q => ({ ...q })) || [{ q: "", answer_summary: "", rating: 0 }] as Question[],
  weak: props.report?.data.weak_points.join("\n") || "", next: props.report?.data.next_actions.join("\n") || "",
  notes: props.report?.data.notes || "" });
const busy = ref(false), error = ref("");
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    if (reportMode) {
      const data = { application_id: props.applicationId, round: rep.round, interviewed_at: timeISO(rep.interviewed_at),
        questions: rep.questions, weak_points: lines(rep.weak), next_actions: lines(rep.next), notes: rep.notes };
      if (props.report) await saveRecord("jobs/reports", data, props.report);
      else await send("jobs/applications/" + segment(props.applicationId!) + "/reports", { data });
    } else {
      await saveRecord("jobs/applications", { ...app, lead_id: props.lead.id, applied_at: timeISO(app.applied_at),
        follow_up_at: timeISO(app.follow_up_at) }, props.row);
    }
    emit("saved");
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
</script>
<template>
  <form class="business-form glass" @submit.prevent="save">
    <h2>{{ reportMode ? "真实面试复盘" : row ? "编辑投递" : "记录投递" }}</h2>
    <template v-if="reportMode">
      <div class="business-columns"><label>面试轮次<input type="number" min="1" max="20" required v-model.number="rep.round" /></label>
        <label>面试时间<input type="datetime-local" v-model="rep.interviewed_at" /></label></div>
      <fieldset v-for="(question, index) in rep.questions" :key="index" class="business-form"><legend>问题 {{ index + 1 }}</legend>
        <label>问题<input v-model="question.q" required maxlength="2000" /></label>
        <label>回答复盘<textarea v-model="question.answer_summary" rows="2" maxlength="4000" /></label>
        <label>自评<select v-model.number="question.rating"><option :value="0">未自评</option><option :value="1">不会</option><option :value="2">部分掌握</option><option :value="3">能讲清楚</option></select></label>
        <button v-if="rep.questions.length > 1" class="secondary" type="button" @click="rep.questions.splice(index, 1)">移除这题</button>
      </fieldset>
      <button class="secondary" type="button" :disabled="rep.questions.length >= 50" @click="rep.questions.push({ q: '', answer_summary: '', rating: 0 })">添加问题</button>
      <label>薄弱点（每行一个）<textarea v-model="rep.weak" rows="2" /></label><label>下一步行动（每行一个）<textarea v-model="rep.next" rows="2" /></label>
      <label>备注<textarea v-model="rep.notes" rows="2" maxlength="10000" /></label>
    </template>
    <template v-else>
      <label>状态<select v-model="app.status"><option v-for="key in allowedStatuses" :key="key" :value="key">{{ labels[key] || key }}</option></select></label>
      <label>投递渠道<input v-model="app.channel" maxlength="80" /></label>
      <label>所用简历<select v-model="app.resume_version_id"><option value="">暂不关联</option><option v-for="resume in resumes" :key="resume.id" :value="resume.id">{{ resume.data.title }}</option></select></label>
      <div class="business-columns"><label>投递时间<input type="datetime-local" v-model="app.applied_at" /></label>
        <label>下次跟进<input type="datetime-local" v-model="app.follow_up_at" /></label></div>
      <label>备注<textarea v-model="app.notes" rows="2" maxlength="20000" /></label>
    </template>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="business-actions"><button type="submit" class="primary" :disabled="busy">{{ busy ? "保存中…" : "保存" }}</button>
      <button type="button" class="secondary" :disabled="busy" @click="emit('cancel')">取消</button></div>
  </form>
</template>
