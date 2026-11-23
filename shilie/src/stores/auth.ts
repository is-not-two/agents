import { computed, ref } from "vue";
import { defineStore } from "pinia";
import { isDemo, request, type Session } from "@/api";

const DEMO_SESSION = "shilie.demo.active";

export const useAuth = defineStore("auth", () => {
  const session = ref<Session | null>(null);
  const statusError = ref("");
  const currentUser = ref("");
  const authenticated = computed(() => Boolean(session.value && (!session.value.required || session.value.authenticated)));
  let checking: Promise<void> | undefined;
  function ensure() {
    if (checking) return checking;
    if (session.value) return Promise.resolve();
    checking = (async () => {
      statusError.value = "";
      try {
        session.value = isDemo
          ? { required: true, authenticated: sessionStorage.getItem(DEMO_SESSION) === "1", account_login: true }
          : await request<Session>("session");
      } catch (error) {
        statusError.value = error instanceof Error ? error.message : "无法连接工作区";
      } finally { checking = undefined; }
    })();
    return checking;
  }
  async function login(credentials: { username: string; password: string; remember: boolean } | { token: string }) {
    if (isDemo) throw new Error("演示不接受真实账号，请用下方「进入演示」");
    const result = await request<{ authenticated: boolean }>("session", { method: "POST", body: JSON.stringify(credentials) });
    if (!result.authenticated) throw new Error("登录未完成");
    session.value = { required: true, authenticated: true, account_login: "username" in credentials };
    currentUser.value = "username" in credentials ? credentials.username : "";
  }
  function enterDemo() {
    if (!isDemo) return;
    sessionStorage.setItem(DEMO_SESSION, "1");
    session.value = { required: true, authenticated: true, account_login: true };
  }
  async function logout() {
    if (isDemo) sessionStorage.removeItem(DEMO_SESSION);
    else await request("session", { method: "DELETE" });
    if (session.value) session.value = { ...session.value, authenticated: false };
    currentUser.value = "";
  }
  return { session, statusError, currentUser, authenticated, ensure, login, enterDemo, logout };
});
