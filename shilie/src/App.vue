<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from "vue";
import { RouterView } from "vue-router";
import { useTheme } from "@/stores/theme";

function syncPlayback(el: unknown) { if (el instanceof HTMLVideoElement) { if(theme.animated) el.play().catch(() => {}); else el.pause(); } }
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
  <Transition name="wall-change"><div v-if="theme.native" :key="theme.media" id="wallpaper-bg" aria-hidden="true">
    <video v-if="theme.video" :src="theme.media" muted playsinline loop :autoplay="theme.animated" :ref="el => syncPlayback(el)"></video>
    <img v-else :src="theme.media || '/wallpaper/shilie-spring.webp'" alt="" :class="{drift:theme.animated}">
  </div></Transition>
  <RouterView />
</template>

