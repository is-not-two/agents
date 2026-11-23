import { defineConfig, loadEnv } from "vite";
import vue from "@vitejs/plugin-vue";
import { fileURLToPath, URL } from "node:url";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "SHILIE_");
  return {
    base: "./",
    plugins: [vue()],
    resolve: { alias: { "@": fileURLToPath(new URL("./src", import.meta.url)) } },
    build: {
      rollupOptions: {
        input: { workspace: fileURLToPath(new URL("./index.html", import.meta.url)), community: fileURLToPath(new URL("./community.html", import.meta.url)) },
        output: {
          onlyExplicitManualChunks: true,
          manualChunks(id) {
            if (/\/items\/(?:Appearance|Backup|Connection|Diagnostics|Notifications)View\.vue$/.test(id)) return "settings";
            if (/\/items\/(?:InterviewPanel|JobPreparationView|JobFlowView|CompanyWorkspace|ResumePanel|JobsListView|CompanyCapabilitiesView|JobInsightsView)\.vue$/.test(id)) return "jobs";
          },
        },
      },
    },
    server: { proxy: env.SHILIE_API_ORIGIN ? { "/api": { target: env.SHILIE_API_ORIGIN } } : undefined },
  };
});
