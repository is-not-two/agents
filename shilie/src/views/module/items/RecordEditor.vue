<script setup lang="ts">
import { computed, ref } from "vue";
import { messageOf } from "@/api";
import { lines, saveRecord, type Fields, type Row } from "@/records";
import type { RecordSpec } from "./record-specs";
const props = defineProps<{ spec: RecordSpec; row?: Row; initial?: Fields }>();
const emit = defineEmits<{ saved: [row: Row]; cancel: [] }>();
const source = props.row?.data ?? props.initial ?? {};
const form = ref<Record<string, string>>(Object.fromEntries(props.spec.fields.map(field => {
  const value = source[field.key];
  return [field.key, Array.isArray(value) ? value.join("\n") : String(value ?? field.defaultValue ?? "")];
})));
const title = computed(() => (props.row ? "编辑" : "新建") + props.spec.singular);
const busy = ref(false), error = ref("");
async function save() {
  if (busy.value) return;
  busy.value = true; error.value = "";
  try {
    const data = { ...source };
    for (const field of props.spec.fields) {
      const raw = String(form.value[field.key]).trim();
      data[field.key] = field.type === "lines" ? lines(raw) : field.type === "number" ? Number(raw) : raw;
    }
    emit("saved", await saveRecord(props.spec.path, data, props.row));
  } catch (reason) { error.value = messageOf(reason); }
  finally { busy.value = false; }
}
</script>

<template>
  <form class="business-form glass" @submit.prevent="save">
    <h2>{{ title }}</h2>
    <label v-for="field in spec.fields" :key="field.key">
      {{ field.label }}
      <textarea v-if="field.type === 'long' || field.type === 'lines'" v-model="form[field.key]" :rows="field.type === 'long' ? 5 : 3" :required="field.required" :maxlength="field.max"></textarea>
      <select v-else-if="field.type === 'select'" v-model="form[field.key]"><option v-for="choice in field.options" :key="choice">{{ choice }}</option></select>
      <input v-else v-model="form[field.key]" :type="field.type || 'text'" :required="field.required"
        :maxlength="field.type === 'number' ? undefined : field.max" :min="field.min" :max="field.type === 'number' ? field.max : undefined" />
    </label>
    <p v-if="error" class="form-error" role="alert">{{ error }}</p>
    <div class="business-actions"><button type="submit" class="primary" :disabled="busy">{{ busy ? "保存中…" : "保存" }}</button>
      <button type="button" class="secondary" :disabled="busy" @click="emit('cancel')">取消</button></div>
  </form>
</template>
