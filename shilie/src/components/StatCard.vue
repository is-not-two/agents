<script setup lang="ts">
import { onMounted, onUnmounted, ref } from "vue";
import { useTheme } from "@/stores/theme";
const props = defineProps<{ value: number; label: string }>();
const theme = useTheme();
const shown = ref(theme.animated ? 0 : props.value);
let frame = 0;
onMounted(() => {
  if (!theme.animated) return;
  const start = performance.now();
  const tick = (time: number) => {
    const t = Math.min((time - start) / 530, 1);
    shown.value = Math.round(props.value * (1 - (1 - t) ** 3));
    if (t < 1 && theme.animated) frame = requestAnimationFrame(tick);
    else shown.value = props.value;
  };
  frame = requestAnimationFrame(tick);
});
onUnmounted(() => cancelAnimationFrame(frame));
</script>

<template><div class="stat-card"><b :aria-label="String(value)">{{ shown }}</b><span>{{ label }}</span></div></template>
