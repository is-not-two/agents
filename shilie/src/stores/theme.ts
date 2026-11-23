import { computed, ref } from "vue";
import { defineStore } from "pinia";

export const useTheme = defineStore("theme", () => {
  const dark = ref(localStorage.getItem("shilie.vue.dark") === "1");
  const motion = ref(localStorage.getItem("shilie.vue.motion") !== "0");
  const preference = matchMedia("(prefers-reduced-motion: reduce)");
  const reduced = ref(preference.matches);
  const animated = computed(() => motion.value && !reduced.value);
  function apply() {
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
  return { dark, animated, reduced, apply, toggleDark, toggleMotion };
});
