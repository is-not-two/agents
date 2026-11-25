import { computed, ref } from "vue";
import { defineStore } from "pinia";

export const useTheme = defineStore("theme", () => {
  const native = ref(localStorage.getItem("shilie.wall.native") === "1");
  const media = ref("");
  const video = ref(false);
  function select(file?: File) {
    if (media.value) URL.revokeObjectURL(media.value);
    media.value = file ? URL.createObjectURL(file) : "";
    video.value = !!file?.type.startsWith("video/");
  }
  function toggleNative() {
    native.value = !native.value;
    localStorage.setItem("shilie.wall.native", native.value ? "1" : "0");
    apply();
  }
  const dark = ref(localStorage.getItem("shilie.vue.dark") === "1");
  const motion = ref(localStorage.getItem("shilie.vue.motion") !== "0");
  const preference = matchMedia("(prefers-reduced-motion: reduce)");
  const reduced = ref(preference.matches);
  const animated = computed(() => motion.value && !reduced.value);
  function apply() {
    document.body.dataset.native = String(native.value);
    document.documentElement.dataset.theme = dark.value ? "dark" : "light";
    document.documentElement.dataset.motion = animated.value ? "on" : "off";
  }
  preference.addEventListener("change", (event) => { reduced.value = event.matches; apply(); });
  function toggleDark() {
    dark.value = !dark.value;
    localStorage.setItem("shilie.vue.dark", dark.value ? "1" : "0");
    apply();
  }
  function toggleMotion() {
    motion.value = !motion.value;
    localStorage.setItem("shilie.vue.motion", motion.value ? "1" : "0");
    apply();
  }
  return { native, toggleNative, select, media, video, dark, animated, reduced, apply, toggleDark, toggleMotion };
});
