
import {defineStore} from "pinia";
import {ref} from "vue";
import {api,CommunityError} from "./api";
interface Profile {authenticated:boolean;member:{recovery_id?:string|null;workspace_owner?:boolean;display_name:string;role:"member"|"moderator"}}
export const useCommunity=defineStore("community",()=>{
 let generation=0; const owner=ref(false),recoveryId=ref("");
 const status=ref<"checking"|"guest"|"member">("checking"),message=ref(""),role=ref<"member"|"moderator"|null>(null),displayName=ref(""),workspaceAvailable=ref(false);
 async function restore(){
  const id=++generation;
  try{const data=await api<Profile>("session");if(id!==generation)return;status.value="member";recoveryId.value=data.member.recovery_id||"";owner.value=data.member.workspace_owner===true;role.value=data.member.role;displayName.value=data.member.display_name}
  catch(e){if(id!==generation)return;const previous=status.value;status.value="guest";recoveryId.value="";owner.value=false;role.value=null;displayName.value="";
   message.value=e instanceof CommunityError&&e.status===401?(previous==="member"?"社区登录已失效，请重新登录。":""):(e as Error).message;
  }
 }
 async function checkWorkspace(){
  try{const r=await fetch("/api/session",{credentials:"same-origin",cache:"no-store",signal:AbortSignal.timeout(12000)});const value=await r.json();workspaceAvailable.value=Boolean(r.ok&&value.required&&value.authenticated)}catch{workspaceAvailable.value=false}
 }
 async function login(token:string){++generation;await api("session","POST",{token});await restore();message.value=status.value==="member"?"已登录交流区。":message.value}
 async function workspaceLogin(){++generation;await api("workspace-session","POST",{});await restore();message.value=status.value==="member"?"已使用工作台身份进入交流区。":message.value}
 async function logout(){++generation;await api("session","DELETE");status.value="guest";recoveryId.value="";owner.value=false;role.value=null;displayName.value="";message.value="已退出交流区。"}
 return {owner,recoveryId,status,message,role,displayName,workspaceAvailable,restore,checkWorkspace,login,workspaceLogin,logout};
});
