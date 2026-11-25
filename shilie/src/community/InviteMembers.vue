<script setup lang="ts">
import {ref} from "vue";
import {api} from "./api";
const label=ref(""),busy=ref(false),message=ref("");
const issued=ref<{member_id:string;token:string}>();
const memberId=ref(""),matched=ref<{id:string;display_name:string;created_at:string}>();
async function lookup(){
 if(busy.value)return;
 busy.value=true;message.value="";matched.value=undefined;
 try{matched.value=await api("owner/members/"+encodeURIComponent(memberId.value.trim()))}
 catch(e){message.value=(e as Error).message}finally{busy.value=false}
}
async function reissue(){
 const m=matched.value;
 if(busy.value||!m||issued.value||!confirm("已通过原联系方式核实接收人是「"+m.display_name+"」？补发将作废此账号尚未使用的邀请码。"))return;
 busy.value=true;message.value="";
 try{issued.value=await api("owner/members/"+m.id+"/invitation","POST",{});label.value=m.display_name;matched.value=undefined;memberId.value=""}
 catch(e){message.value=(e as Error).message}finally{busy.value=false}
}
type Pending={id:string;display_name:string;expires_at:string};
const query=ref(""),filter=ref(""),rows=ref<Pending[]>([]),next=ref<string|null>(null),loaded=ref(false);
async function list(more=false){
 if(busy.value)return;
 busy.value=true;message.value="";
 try{
  const term=more?filter.value:query.value.trim();
  const result=await api<{items:Pending[];next:string|null}>("owner/invitations?q="+encodeURIComponent(term)+(more&&next.value?"&after="+encodeURIComponent(next.value):""));
  rows.value=result.items;next.value=result.next;filter.value=term;loaded.value=true;
 }catch(e){message.value=(e as Error).message}finally{busy.value=false}
}
async function revokeListed(row:Pending){
 if(busy.value||!confirm("撤销发给「"+row.display_name+"」的邀请？"))return;
 busy.value=true;message.value="";
 try{await api("owner/invitations/"+row.id,"DELETE");rows.value=rows.value.filter(r=>r.id!==row.id);if(issued.value?.member_id===row.id)reset();message.value="邀请已撤销。"}
 catch(e){message.value=(e as Error).message}finally{busy.value=false}
}
async function issue(){
 if(busy.value||!label.value.trim())return;
 busy.value=true;message.value="";
 try{issued.value=await api("owner/invitations","POST",{display_name:label.value.trim()})}
 catch(e){message.value=(e as Error).message}finally{busy.value=false}
}
async function revoke(){
 if(!issued.value||busy.value)return;
 busy.value=true;
 try{await api("owner/invitations/"+issued.value.member_id,"DELETE");reset();message.value="已撤销，原邀请码不能再登录。"}
 catch(e){message.value=(e as Error).message}finally{busy.value=false}
}
function reset(){issued.value=undefined;label.value="";message.value=""}
</script>
<template>
 <details class="invite-members"><summary>邀请普通成员</summary>
  <form v-if="!issued" @submit.prevent="issue">
   <label>成员显示名<input v-model="label" maxlength="80" required autocomplete="off"></label>
   <button :disabled="busy||!label.trim()">生成一次性邀请码</button>
  </form>
  <div v-else>
   <p>成员编号：<code>{{issued.member_id}}</code>。请与接收人保存此编号，以便之后找回同一账号。</p>
   <label>发送给 {{label}} 的邀请码<input readonly :value="issued.token" autocomplete="off" @focus="($event.target as HTMLInputElement).select()"></label>
   <p>请私下发送；24 小时内有效，只能登录一次。离开本页后不再显示。</p>
   <button :disabled="busy" @click="reset">已保存，隐藏邀请码</button>
   <button :disabled="busy" @click="revoke">撤销未使用的邀请</button>
  </div>
  <p v-if="message" role="status">{{message}}</p>
  <details v-if="!issued"><summary>给老成员补发登录码</summary>
   <form @submit.prevent="lookup"><label>原成员编号<input v-model="memberId" @input="matched=undefined" :disabled="busy" required maxlength="36" pattern="[a-fA-F0-9]{8}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{4}-[a-fA-F0-9]{12}"></label><button :disabled="busy">核对账号</button></form>
   <div v-if="matched"><p>{{matched.display_name}} · {{new Date(matched.created_at).toLocaleDateString()}} 创建<br><code>{{matched.id}}</code></p><p>编号只用于定位账号，不是身份证明。请先通过原联系方式确认本人。</p><button :disabled="busy" @click="reissue">补发到这个账号</button></div>
  </details>
  <h3>待使用的邀请</h3>
  <form @submit.prevent="list(false)">
   <label>按成员名查找<input v-model="query" maxlength="80" placeholder="留空查看全部"></label>
   <button :disabled="busy">查询邀请</button>
  </form>
  <ul v-if="rows.length"><li v-for="row in rows" :key="row.id">
   <strong>{{row.display_name}}</strong> · {{new Date(row.expires_at).toLocaleString()}} 到期
   <button :disabled="busy" @click="revokeListed(row)">撤销邀请</button>
  </li></ul>
  <p v-else-if="loaded">本页没有待使用的邀请。</p>
  <button v-if="next" :disabled="busy" @click="list(true)">下一页</button>
 </details>
</template>
<style scoped>
.invite-members{margin-block:1rem}.invite-members summary{cursor:pointer;font-weight:600}
.invite-members form,.invite-members>div{max-width:36rem;margin-block:1rem}.invite-members input{width:100%}
</style>
