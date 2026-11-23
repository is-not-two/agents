import { createRouter, createWebHashHistory } from "vue-router";
import type { Pinia } from "pinia";
import { useAuth } from "@/stores/auth";

function normalizeOldHash() {
  const hash = location.hash;
  let path: string | undefined;
  if (hash === "#home") path = "/";
  else if (hash === "#home/workspace") path = "/workspace";
  else if (/^#(?:module|category)\//.test(hash)) {
    path = "/" + hash.slice(1);
    if (path === "/module/agents" || path === "/module/workflows") path = "/module/agent-studio";
    const company = path.match(/^\/module\/job-flow\/company\/([^/?#]+)(?:\/(required|gap|review))?$/);
    if (company) path = "/module/job-flow/item/" + company[1] + (company[2] ? "?section=" + company[2] : "");
  }
  if (path) history.replaceState(history.state, "", location.pathname + location.search + "#" + path);
}

export function createAppRouter(pinia: Pinia) {
  normalizeOldHash();
  const router = createRouter({
    history: createWebHashHistory(),
    routes: [
      { path: "/", name: "start", component: () => import("@/views/home/StartView.vue") },
      { path: "/login", name: "login", component: () => import("@/layouts/BlankLayout.vue"),
        children: [{ path: "", component: () => import("@/views/LoginView.vue") }] },
      { path: "/", component: () => import("@/layouts/DefaultLayout.vue"), children: [
        { path: "workspace", name: "workspace", component: () => import("@/views/home/HomeView.vue") },
        { path: "trash", name: "trash", component: () => import("@/views/TrashView.vue") },
        { path: "category/workspace", redirect: "/workspace" },
        { path: "category/automation", redirect: "/category/agent" },
        { path: "category/private", redirect: "/module/private" },
        { path: "category/:categoryId", name: "category", component: () => import("@/views/category/CategoryView.vue") },
        { path: "module/agents", redirect: "/module/agent-studio" },
        { path: "module/workflows", redirect: "/module/agent-studio" },
        { path: "module/job-flow/company/:company/:section?", redirect: to => ({
          name: "item-detail", params: { moduleId: "job-flow", itemId: to.params.company },
          query: { section: String(to.params.section || "") },
        }) },
        { path: "module/job-flow/prep/:lead?", redirect: to => ({
          path: "/module/job-prep", query: to.params.lead ? { lead: to.params.lead } : {},
        }) },
        { path: "module/job-flow/resumes/:resume?", redirect: to => ({
          path: "/module/resumes", query: to.params.resume ? { resume: to.params.resume } : {},
        }) },
        { path: "module/job-flow/ai-resume/:lead?", redirect: to => ({
          path: "/module/job-resume-ai", query: to.params.lead ? { lead: to.params.lead } : {},
        }) },
        { path: "module/job-flow/manage", alias: "/module/job-flow/tables", redirect: "/module/job-tables" },
        { path: "module/:moduleId", name: "module", component: () => import("@/views/module/ModuleView.vue") },
        { path: "module/:moduleId/item/:itemId", name: "item-detail", component: () => import("@/views/module/ItemDetailView.vue") },
        { path: ":pathMatch(.*)*", redirect: "/" },
      ] },
    ],
    scrollBehavior: (_to, _from, saved) => saved ?? { top: 0 },
  });
  router.beforeEach(async (to) => {
    const auth = useAuth(pinia);
    await auth.ensure();
    if (to.path !== "/login" && !auth.authenticated)
      return { path: "/login", query: { next: to.fullPath } };
    if (to.path === "/login" && auth.authenticated) return "/";
    return true;
  });
  return router;
}
