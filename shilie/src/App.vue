<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterView } from "vue-router";
import { useTheme } from "@/stores/theme";

const theme = useTheme();
const offset = ref(0);
const background = computed(() => ({ "--wall-shift": offset.value + "px" }));
let frame = 0;
function parallax() {
  if (!frame) frame = requestAnimationFrame(() => {
    frame = 0;
    offset.value = theme.animated ? Math.min(window.scrollY, 260) * 0.3 : 0;
  });
}
onMounted(() => {
  addEventListener("scroll", parallax, { passive: true });
  theme.apply();
});
onUnmounted(() => { removeEventListener("scroll", parallax); cancelAnimationFrame(frame); });
</script>

<template>
  <div class="wallpaper" aria-hidden="true" :style="theme.animated ? background : undefined"></div>
  <RouterView />
</template>
