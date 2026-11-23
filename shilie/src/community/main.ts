import {createApp} from "vue";
import {createPinia} from "pinia";
import {createRouter,createWebHashHistory} from "vue-router";
import App from "./App.vue";
import "./style.css";
const empty={render:()=>null};
const router=createRouter({history:createWebHashHistory(),routes:[
 {path:"/",name:"feed",component:empty},{path:"/topic/:id",name:"topic",component:empty},
 ...["write","mine","review","ask"].map(path=>({path:"/"+path,name:path,component:empty})),
 {path:"/:pathMatch(.*)*",redirect:"/"},
],scrollBehavior:(_to,_from,saved)=>saved||{top:0}});
createApp(App).use(createPinia()).use(router).mount("#app");
