<script setup lang="ts">
import { computed, onMounted, ref } from "vue";
import { isDemo, messageOf, send } from "@/api";
import { archiveRecord, dateText, getHistory, publicLink, segment, type Row } from "@/records";
import EmptyState from "@/components/EmptyState.vue";
import RecordEditor from "./RecordEditor.vue";
import ResumePanel from "./ResumePanel.vue";
import ApplicationEditor from "./ApplicationEditor.vue";
import InterviewPanel from "./InterviewPanel.vue";
import CompanyCapabilities from "./CompanyCapabilitiesView.vue";
import { specs } from "./record-specs";
import { canRecordReport, getJobs, labels, type Application, type Lead, type Overview, type Report } from "./jobs-data";
type Section = "records" | "required" | "gap" | "review" | "resume" | "interview" | "prepare";
const props = defineProps<{ company: string; initialLead?: string; initialSection?: string }>();
const overview = ref<Overview>(), error = ref(""), loading = ref(true), status = ref("");
const options: [Section, string][] = [["records","岗位与投递"],["required","能力要求"],["gap","能力差距"],
  ["review","真实面试复盘"],["resume","个人简历"],["interview","预面试"]];
const active = ref(props.initialLead || ""), section = ref<Section>(props.initialSection === "prepare" ? "prepare" : options.find(([key]) => key === props.initialSection)?.[0] || "records");
const editor = ref<"new-lead" | "lead" | "app" | "report">();
const app = ref<Application>(), report = ref<Report>();
const reviewSource = ref(""), selectedPoints = ref<string[]>([]), creatingCards = ref(false);
const historyTarget = ref(""), historyBusy = ref(false), versions = ref<Row<Report["data"]>[]>([]), archiving = ref(false);
const leads = computed(() => (overview.value?.job_lead || []).filter(row => row.data.company === props.company));
const lead = computed(() => leads.value.find(row => row.id === active.value) ?? (section.value === "prepare" ? undefined : leads.value[0]));
const applications = computed(() => (overview.value?.application || []).filter(row => row.data.lead_id === lead.value?.id));
const resumes = computed(() => overview.value?.resume_version || []);
const reports = (id: string) => (overview.value?.interview_report || []).filter(row => row.data.application_id === id);
async function load() {
  loading.value = true; error.value = "";
  try { overview.value = await getJobs(); }
  catch (reason) { error.value = messageOf(reason); }
  finally { loading.value = false; }
}
function choose(row: Lead) { active.value = row.id; editor.value = undefined; status.value = ""; }
async function saved(row?: Row) {
  editor.value = undefined;
  if (row?.kind === "job_lead" && row.data.company === props.company) active.value = row.id;
  status.value = "已保存。"; await load();
}
function editApplication(row?: Application) { app.value = row; editor.value = "app"; }
function editReport(row: Application, target?: Report) {
  if (!canRecordReport(row.data.status)) return;
  app.value = row; report.value = target; editor.value = "report";
}
function choosePoints(item: Report) {
  reviewSource.value = reviewSource.value === item.id ? "" : item.id; selectedPoints.value = [];
}
async function createCards(item: Report) {
  if (creatingCards.value || reviewSource.value !== item.id || !selectedPoints.value.length) return;
  creatingCards.value = true; error.value = ""; status.value = "";
  try {
    const result = await send<{ created: unknown[]; reused: unknown[] }>("learning/from-interview/" + segment(item.id),
      { version: item.version, points: [...selectedPoints.value], confirmation: "确认创建复习卡" });
    reviewSource.value = ""; selectedPoints.value = [];
    status.value = "新增 " + result.created.length + " 张复习卡，复用 " + result.reused.length + " 张。";
  } catch (reason) { error.value = messageOf(reason); }
  finally { creatingCards.value = false; }
}
async function archive(row: Row) {
  if (archiving.value || !confirm("将此记录移入回收站？有引用时后端会阻止删除。")) return;
  archiving.value = true; error.value = "";
  try {
    await archiveRecord(row);
    if (report.value?.id === row.id) { report.value = undefined; editor.value = undefined; }
    if (reviewSource.value === row.id) { reviewSource.value = ""; selectedPoints.value = []; }
    if (historyTarget.value === row.id) { historyTarget.value = ""; versions.value = []; }
    status.value = "已归档。"; await load();
  }
  catch (reason) { error.value = messageOf(reason); }
  finally { archiving.value = false; }
}
async function showHistory(item: Report) {
  if (historyBusy.value) return;
  if (historyTarget.value === item.id) { historyTarget.value = ""; versions.value = []; return; }
  historyTarget.value = item.id; versions.value = []; historyBusy.value = true; error.value = "";
  try { versions.value = await getHistory(item) as Row<Report["data"]>[]; }
  catch (reason) { historyTarget.value = ""; error.value = messageOf(reason); }
  finally { historyBusy.value = false; }
}
onMounted(load);
</script>

<template>
  <div class="business-stack">
    <p v-if="loading" role="status">正在读取公司记录…</p>
    <div v-if="error" class="business-panel glass"><p class="form-error" role="alert">{{ error }}</p><button class="secondary" @click="load">重新读取</button></div>
    <p v-if="status" role="status">{{ status }}</p>
    <template v-if="leads.length">
      <header class="page-heading glass" data-tint="rose"><h1>{{ company }}</h1><p>{{ leads.length }} 个岗位<span v-if="isDemo"> · 演示记录</span></p></header>
      <nav class="business-actions" aria-label="公司工作区">
        <button v-for="option in options" :key="option[0]"
          type="button" :class="section === option[0] ? 'primary' : 'secondary'" :aria-pressed="section === option[0]"
          @click="section = option[0]; editor = undefined">{{ option[1] }}</button>
      </nav>
      <ResumePanel v-if="section === 'resume'" :leads="leads" @uploaded="load" @changed="load" />
      <InterviewPanel v-else-if="(section === 'interview' || section === 'prepare') && lead" :key="section"
        :leads="leads" :resumes="resumes" :initial-lead="lead.id" :preparation="section === 'prepare'" @uploaded="load" />
      <p v-else-if="section === 'prepare'" role="status">这个岗位已不可用，请从岗位列表重新选择。</p>
      <CompanyCapabilities v-else-if="section === 'required' || section === 'gap'" :key="section" :company="company" :gaps-only="section === 'gap'" :lead-id="lead?.id" />
      <template v-else-if="lead">
        <section class="business-panel glass">
          <h2>这家公司的岗位</h2>
          <div class="business-actions"><button v-for="row in leads" :key="row.id" type="button" :aria-pressed="lead.id === row.id"
            :class="lead.id === row.id ? 'primary' : 'secondary'" @click="choose(row)">{{ row.data.title }}</button>
            <button v-if="section === 'records'" type="button" class="secondary" @click="editor = 'new-lead'">添加岗位</button></div>
        </section>
        <RecordEditor v-if="editor === 'new-lead' || editor === 'lead'" :key="editor + lead.id" :spec="specs.jobs"
          :initial="{ company }" :row="editor === 'lead' ? lead : undefined" @saved="saved" @cancel="editor = undefined" />
        <article v-if="section === 'records'" class="business-panel glass"><h2>{{ lead.data.title }}</h2>
          <p class="preserve">{{ lead.data.jd_text || '尚未填写招聘原文。' }}</p>
          <p v-if="lead.data.notes" class="preserve">{{ lead.data.notes }}</p>
          <p v-if="publicLink(lead.data.source_url)"><a :href="publicLink(lead.data.source_url)" target="_blank" rel="noopener noreferrer">打开岗位来源</a></p>
          <div class="business-actions"><button type="button" class="secondary" @click="editor = 'lead'">编辑岗位</button>
            <RouterLink v-if="!isDemo" class="primary" :to="{ query: { section: 'prepare', lead: lead.id } }">准备这场面试</RouterLink>
            <button type="button" class="primary" @click="editApplication()">记录投递</button>
            <button type="button" class="secondary" @click="archive(lead)">归档岗位</button></div>
        </article>
        <ApplicationEditor v-if="editor === 'app' || editor === 'report'" :key="editor + (app?.id || '') + (report?.id || '')"
          :lead="lead" :resumes="resumes" :row="editor === 'app' ? app : undefined" :report="editor === 'report' ? report : undefined"
          :application-id="editor === 'report' ? app?.id : undefined" @saved="saved()" @cancel="editor = undefined" />
        <section class="business-stack" aria-label="投递与复盘"><h2>{{ section === 'review' ? '该岗位的面试复盘' : '投递与复盘' }}</h2>
          <p v-if="!applications.length">当前岗位还没有投递记录。</p>
          <article v-for="row in applications" :key="row.id" class="business-panel glass">
            <h3>{{ row.data.title || lead.data.title }} · {{ labels[row.data.status] || row.data.status }}</h3>
            <p v-if="section === 'records'">跟进时间：{{ dateText(row.data.follow_up_at) }}<span v-if="overview?.due_application_ids.includes(row.id)"> · 已到期</span></p>
            <p v-if="section === 'records' && row.data.channel">渠道：{{ row.data.channel }}</p><p v-if="section === 'records' && row.data.notes" class="preserve">{{ row.data.notes }}</p>
            <div class="business-actions"><button v-if="section === 'records'" type="button" class="secondary" @click="editApplication(row)">编辑投递</button>
              <button type="button" class="secondary" :disabled="!canRecordReport(row.data.status)" @click="editReport(row)">记录复盘</button>
              <button v-if="section === 'records'" type="button" class="secondary" @click="archive(row)">归档投递</button></div>
            <p v-if="!canRecordReport(row.data.status)" class="muted">进入面试阶段后才能记录复盘。</p>
            <details v-for="item in reports(row.id)" :key="item.id"><summary>第 {{ item.data.round }} 轮面试复盘</summary>
              <p v-for="question in item.data.questions" :key="question.q" class="preserve">{{ question.q }}：{{ question.answer_summary }}（自评 {{ question.rating }}）</p>
              <p v-if="item.data.weak_points.length">薄弱点：{{ item.data.weak_points.join("、") }}</p>
              <p v-if="item.data.next_actions.length">下一步：{{ item.data.next_actions.join("、") }}</p>
              <button type="button" class="secondary" @click="editReport(row,item)">编辑复盘</button>
              <button type="button" class="secondary" :disabled="historyBusy || archiving" @click="showHistory(item)">复盘历史</button>
              <button type="button" class="secondary" :disabled="archiving || historyBusy || creatingCards" @click="archive(item)">归档复盘</button>
              <section v-if="historyTarget === item.id" class="business-panel" aria-label="复盘版本历史">
                <p v-if="historyBusy" role="status">正在读取版本…</p>
                <p v-else-if="!versions.length">没有可查看的版本。</p>
                <details v-for="version in versions" :key="version.version">
                  <summary>第 {{ version.version }} 版 · {{ dateText(version.updated_at) }}</summary>
                  <p v-if="version.deleted">此版本已归档。</p>
                  <template v-else>
                    <p v-for="(question,index) in version.data.questions" :key="index" class="preserve">{{ question.q }}：{{ question.answer_summary }}（自评 {{ question.rating }}）</p>
                    <p v-if="version.data.weak_points?.length">薄弱点：{{ version.data.weak_points.join("、") }}</p>
                    <p v-if="version.data.next_actions?.length">下一步：{{ version.data.next_actions.join("、") }}</p>
                    <p v-if="version.data.notes" class="preserve">{{ version.data.notes }}</p>
                  </template>
                </details>
              </section>
              <button v-if="item.data.weak_points.length" type="button" class="secondary" :disabled="creatingCards"
                @click="choosePoints(item)">选择薄弱点建卡</button>
              <form v-if="reviewSource === item.id" class="business-form" @submit.prevent="createCards(item)">
                <label v-for="point in new Set(item.data.weak_points)" :key="point" class="check-line">
                  <input type="checkbox" v-model="selectedPoints" :value="point" :disabled="creatingCards" /> {{ point }}</label>
                <div class="business-actions"><button class="primary" :disabled="creatingCards || !selectedPoints.length">确认创建复习卡</button>
                  <RouterLink class="secondary" to="/module/learning">去复习</RouterLink></div>
              </form>
            </details>
          </article>
        </section>
      </template>
    </template>
    <EmptyState v-else-if="!loading && !error" title="找不到这个条目" description="这家公司没有有效岗位，或链接已失效。" />
  </div>
</template>
