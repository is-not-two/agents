/* Home-only background. Fill these local asset paths after the user supplies media. */
const WALLPAPER_ASSETS = Object.freeze({
  image: "/static/shilie/assets/wallpaper/demo-spring.webp",
  video: "/static/shilie/assets/wallpaper/demo-spring.mp4",
});
const MOBILE = matchMedia("(max-width: 759px)");
const REDUCED = matchMedia("(prefers-reduced-motion: reduce)");
const wallpaper = document.getElementById("home-wallpaper");
const picture = wallpaper.querySelector("img");
const video = wallpaper.querySelector("video");
let imageStatus = "unloaded";
let currentImage = "";
let imagePromise = null;
let generation = 0;

function localAsset(value, extensions) {
  if (typeof value !== "string" || !value.startsWith("/static/shilie/assets/wallpaper/")) return "";
  const url = new URL(value, location.origin);
  if (url.origin !== location.origin || url.search || url.hash || !url.pathname.startsWith("/static/shilie/assets/wallpaper/") || !extensions.some(ext => url.pathname.toLowerCase().endsWith(ext))) return "";
  return url.pathname;
}
function homeRoute() {
  return !location.hash || location.hash === "#home" || location.hash === "#home/workspace";
}
function constrained() {
  return MOBILE.matches || REDUCED.matches || document.documentElement.dataset.motion === "off" || (navigator.deviceMemory > 0 && navigator.deviceMemory <= 2) || (navigator.hardwareConcurrency > 0 && navigator.hardwareConcurrency <= 2);
}
function stop() {
  video.pause();
  wallpaper.hidden = true;
  delete wallpaper.dataset.mode;
  document.body.classList.remove("wallpaper-active");
}
function show(mode) {
  wallpaper.dataset.mode = mode;
  wallpaper.hidden = false;
  document.body.classList.add("wallpaper-active");
}
async function refresh() {
  const ticket = ++generation;
  const image = localAsset(WALLPAPER_ASSETS.image, [".webp", ".png", ".jpg", ".jpeg", ".avif"]);
  const clip = localAsset(WALLPAPER_ASSETS.video, [".webm", ".mp4"]);
  if (!homeRoute() || document.hidden || !image) { stop(); return; }
  if (image !== currentImage) {
    currentImage = image;
    imageStatus = "loading";
    imagePromise = new Promise((resolve, reject) => { picture.onload = resolve; picture.onerror = reject; picture.src = image; })
      .then(() => { imageStatus = "ready"; }, () => { imageStatus = "failed"; });
  }
  if (imagePromise) await imagePromise;
  if (ticket !== generation) return;
  if (imageStatus !== "ready") { stop(); return; }
  if (constrained()) { video.pause(); show("static"); return; }
  if (!clip) { video.pause(); show("image-motion"); return; }
  show("static");
  if (video.getAttribute("src") !== clip) video.setAttribute("src", clip);
  try {
    await video.play();
    if (ticket !== generation) return;
    if (!homeRoute() || document.hidden || constrained()) { video.pause(); return; }
    show("video");
  } catch { if (ticket === generation) { video.pause(); show("static"); } }
}
video.addEventListener("error", () => { video.pause(); if (homeRoute() && !document.hidden && imageStatus === "ready") show("static"); });
window.addEventListener("hashchange", refresh);
window.addEventListener("shilie:motionchange", refresh);
document.addEventListener("visibilitychange", refresh);
MOBILE.addEventListener("change", refresh);
REDUCED.addEventListener("change", refresh);
refresh();
