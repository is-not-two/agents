import { createApp } from "vue";
import { createPinia } from "pinia";
import App from "./App.vue";
import { createAppRouter } from "./router";
import "./style.css";

const pinia = createPinia();
createApp(App).use(pinia).use(createAppRouter(pinia)).mount("#app");
