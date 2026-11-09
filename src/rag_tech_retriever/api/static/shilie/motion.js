/* One quiet navigation transition and feedback only for confirmed actions. */
import { MOTION_CONFIG as config } from "./motion-config.js?v=121";
const motionAllowed = () =>
  !matchMedia("(prefers-reduced-motion: reduce)").matches &&
  document.documentElement.dataset.motion !== "off";

export function initMotion({ content }) {
  window.addEventListener("hashchange", () => {
    if (!motionAllowed()) return;
    content.classList.remove("page-enter");
    void content.offsetWidth;
    content.classList.add("page-enter");
  });
  document.addEventListener("shilie:semantic-effect", (event) => {
    if (!motionAllowed()) return;
    const { name, id } = event.detail || {};
    requestAnimationFrame(() => {
      if (!motionAllowed()) return;
      const matching = (selector) => [...content.querySelectorAll(selector)]
        .find((element) => element.dataset.id === id);
      let element, frames;
      if (name === "knowledge-saved") {
        element = matching(".note-card");
        frames = [{ transform: "translateY(-12px)", opacity: 0.5 }, { transform: "translateY(0)", opacity: 1 }];
      } else if (name === "job-saved") {
        element = matching(".jobs-row");
        frames = [{ transform: "translateX(-8px)" }, { transform: "translateX(0)" }];
      } else if (name === "learning-reviewed") {
        element = content.querySelector(".learning-card");
        frames = [{ transform: "perspective(900px) rotateY(0)" }, { transform: "perspective(900px) rotateY(15deg)" }, { transform: "perspective(900px) rotateY(0)" }];
      } else if (name === "planning-completed") {
        element = [...content.querySelectorAll(".story-card")].find((card) => card.dataset.storyId === id);
        frames = [{ boxShadow: "0 0 0 0 rgba(201,162,39,0.6)" }, { boxShadow: "0 0 0 12px rgba(201,162,39,0)" }];
      }
      element?.animate(frames, { duration: config.actionMilliseconds, easing: "ease-out" });
    });
  });
  document.addEventListener("shilie:search-finished", (event) => {
    if (!event.detail?.ok || !motionAllowed()) return;
    requestAnimationFrame(() => {
      content.querySelectorAll(".result-card").forEach((element, index) => {
        element.animate([{ borderColor: "#c9a227" }, { borderColor: "#eadfd2" }], {
          duration: config.actionMilliseconds, delay: Math.min(index, 4) * 45, easing: "ease-out",
        });
      });
    });
  });
  window.addEventListener("shilie:motionchange", () => {
    if (!motionAllowed()) content.getAnimations({ subtree: true }).forEach((animation) => animation.cancel());
  });
}
