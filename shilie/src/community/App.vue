<script setup lang="ts">
import {computed,nextTick,onMounted,onUnmounted,ref,watch} from "vue";
import {useRoute,useRouter} from "vue-router";
import {api,CommunityError,keywords,type Topic,type Answer} from "./api";
import {useCommunity} from "./store";
import PlainText from "./PlainText.vue";
const route=useRoute(),router=useRouter(),session=useCommunity();
const citationChanged=ref(false);
const busy=ref(false),acting=ref(false),error=ref(""),notice=ref(""),search=ref(""),token=ref("");
const rows=ref<Topic[]>([]),topic=ref<Topic>(),cursor=ref<string|null>(null),mine=ref<Topic[]>([]);
type ReviewRow=Topic&{decision:string;scoreInput:number|undefined;rationale:string;publicRationale:boolean;authorFeedback:string};
const queue=ref<ReviewRow[]>([]);
const privateNext=ref<string|null>(null),privatePages=ref<(string|null)[]>([null]),privateIndex=ref(0);
let privatePageName="";
function resetPrivatePages(){privatePages.value=[null];privateIndex.value=0;privateNext.value=null}
const reviewDirty=computed(()=>queue.value.some(x=>x.decision||x.scoreInput!==undefined||x.rationale||x.publicRationale||x.authorFeedback));
function allowBatchChange(){return name.value!=="review"||!reviewDirty.value||confirm("这批有尚未提交的审核填写。离开会清空这些填写，已提交的审核不受影响。继续？")}
const editOrigin=ref<Topic>();
const draft=ref({title:"",body:""}),requestId=ref<string>(),question=ref(""),terms=ref(""),answer=ref<Answer>();
const name=computed(()=>String(route.name||"feed"));
const removeLeaveGuard=router.beforeEach(()=>allowBatchChange());
const titles:Record<string,string>={feed:"工作技巧",write:"分享一个实用方法",edit:"修改并重新送审",mine:"我的投稿",review:"审核工作台",ask:"问 AI",topic:"原帖"};
const currentQuery=computed(()=>String(route.query.q||""));
const back=computed(()=>({name:"feed",query:currentQuery.value?{q:currentQuery.value}:{}}));
function link(row:{id?:string;post_id?:string;version?:number},rating=false){return {name:"topic",params:{id:row.id||row.post_id},query:{...(currentQuery.value?{q:currentQuery.value}:{}),...(rating?{section:"rating"}:{}),...(row.post_id&&row.version?{v:String(row.version)}:{})}}}
function focusRating(){document.getElementById("rating")?.focus()}
function fail(e:unknown){if(e instanceof CommunityError&&e.status===401){session.status="guest";session.message="请重新登录交流区。";mine.value=[];queue.value=[];answer.value=undefined}error.value=e instanceof Error?e.message:"操作失败，请重试。"}
let sequence=0;
async function load(){
 if(privatePageName!==name.value){privatePageName=name.value;resetPrivatePages()}
 privateNext.value=null;
 const id=++sequence;citationChanged.value=false;error.value="";notice.value="";busy.value=true;topic.value=undefined;answer.value=undefined;
 try{
  if(name.value==="feed"){
   rows.value=[];cursor.value=null;search.value=currentQuery.value;
   const data=await api<{items:Topic[];next?:string}>(search.value?"search?q="+encodeURIComponent(search.value):"topics");
   if(id!==sequence)return;rows.value=data.items;cursor.value=data.next||null;
  }else if(name.value==="topic"){
   const data=await api<{item:Topic}>("topics?topic="+encodeURIComponent(String(route.params.id))+(route.query.v!==undefined?"&expected_version="+encodeURIComponent(String(route.query.v)):""));
   if(id!==sequence)return;topic.value=data.item;await nextTick();
   if(route.query.section==="rating"){const h=document.getElementById("rating");h?.focus();h?.scrollIntoView({block:"start"})}
  }else if(name.value==="edit"){
   editOrigin.value=undefined;draft.value={title:"",body:""};requestId.value=undefined;
   const data=await api<{item:Topic}>("draft?post="+encodeURIComponent(String(route.params.id)));
   if(id!==sequence)return;editOrigin.value=data.item;draft.value={title:data.item.title,body:data.item.body||""};
  }else if(name.value==="mine"){
   mine.value=[];const anchor=privatePages.value[privateIndex.value];
   const data=await api<{items:Topic[];next:string|null}>("mine"+(anchor?"?before="+encodeURIComponent(anchor):""));
   if(id!==sequence)return;mine.value=data.items;privateNext.value=data.next;
  }else if(name.value==="review"){
   queue.value=[];const anchor=privatePages.value[privateIndex.value];
   const data=await api<{items:Topic[];next:string|null}>("reviews"+(anchor?"?after="+encodeURIComponent(anchor):""));if(id!==sequence)return;
   privateNext.value=data.next;
   queue.value=data.items.map(x=>({...x,decision:"",scoreInput:undefined,rationale:"",publicRationale:false,authorFeedback:""}));
  }
 }catch(e){if(id===sequence){fail(e);if(name.value==="topic"&&route.query.v!==undefined&&e instanceof CommunityError&&e.status===409){citationChanged.value=true;error.value="这条引用来自旧版本。请重新检索；不会把新版正文当作原引用。"}}}
 finally{if(id===sequence)busy.value=false}
}
watch(()=>route.fullPath,load,{immediate:true});
async function privatePage(direction:"next"|"previous"|"first"){
 if(busy.value||acting.value||!allowBatchChange())return;
 if(direction==="next"){
  if(!privateNext.value)return;
  privatePages.value=privatePages.value.slice(0,privateIndex.value+1);
  privatePages.value.push(privateNext.value);privateIndex.value++;
 }else if(direction==="previous")privateIndex.value=Math.max(0,privateIndex.value-1);
 else {privatePages.value=[null];privateIndex.value=0}
 await load();await nextTick();document.getElementById("batch-heading")?.focus();
}
function refreshIdentity(){session.restore();session.checkWorkspace()}
onMounted(()=>{refreshIdentity();window.addEventListener("focus",refreshIdentity)});
onUnmounted(()=>{window.removeEventListener("focus",refreshIdentity);removeLeaveGuard()});
watch(()=>session.status,value=>{if(value==="guest"){mine.value=[];queue.value=[];answer.value=undefined;resetPrivatePages()}});
async function workspaceLogin(){if(!confirm("将以工作台所有者（可审核投稿）的身份进入交流区。继续？"))return;acting.value=true;error.value="";try{await session.workspaceLogin();resetPrivatePages();mine.value=[];queue.value=[];answer.value=undefined;if(["mine","review","edit"].includes(name.value))await load()}catch(e){fail(e)}finally{acting.value=false}}

async function find(){const q=search.value.trim();if(name.value==="feed"&&q===currentQuery.value)return load();await router.push({name:"feed",query:q?{q}:{}})}
async function more(){
 if(!cursor.value||busy.value)return;busy.value=true;const id=sequence;
 try{const data=await api<{items:Topic[];next?:string}>("topics?before="+encodeURIComponent(cursor.value));if(id!==sequence)return;rows.value.push(...data.items);cursor.value=data.next||null}catch(e){fail(e)}finally{if(id===sequence)busy.value=false}
}
async function login(){acting.value=true;error.value="";try{await session.login(token.value.trim());token.value="";resetPrivatePages();if(["mine","review","edit"].includes(name.value))await load()}catch(e){fail(e)}finally{acting.value=false}}
async function logout(){acting.value=true;try{await session.logout();draft.value={title:"",body:""};editOrigin.value=undefined;mine.value=[];queue.value=[];answer.value=undefined;if(["mine","review","edit"].includes(name.value))await router.push("/")}catch(e){fail(e)}finally{acting.value=false}}
async function submit(){
 acting.value=true;error.value="";requestId.value??=crypto.randomUUID();
 try{
  const editing=name.value==="edit";if(editing&&!editOrigin.value)throw Error("请先重新读取你的原稿。");
  await api(editing?"revise":"posts","POST",{request_id:requestId.value,...draft.value,...(editing?{post_id:editOrigin.value!.id,version:editOrigin.value!.version}:{})});
  draft.value={title:"",body:""};requestId.value=undefined;editOrigin.value=undefined;
  if(["write","edit"].includes(name.value)){await router.push("/mine");notice.value=editing?"改稿已保存，等待重新审核。":"已提交，等待审核。"}else notice.value="投稿已提交，等待审核。";
 }catch(e){fail(e)}finally{acting.value=false}
}
async function withdraw(row:Topic){
 if(!confirm("撤回后，公开列表、搜索和原帖链接将不再提供此内容。确定撤回？"))return;
 acting.value=true;try{await api("withdraw","POST",{post_id:row.id,version:row.version});await load();notice.value="投稿已撤回。"}catch(e){fail(e)}finally{acting.value=false}
}
async function review(row:ReviewRow){
 acting.value=true;error.value="";
 try{
  if(!row.decision||!Number.isInteger(row.scoreInput)||row.scoreInput!<0||row.scoreInput!>100)throw Error("请选择审核决定，填写0–100的整数分数。");
  if(row.decision==="yes"&&row.scoreInput!<60)throw Error("公开发布至少需要60分。");
  if(row.decision==="no"&&!row.authorFeedback.trim())throw Error("请填写给投稿人的修改建议。");
  await api("reviews","POST",{post_id:row.id,version:row.version,publish:row.decision==="yes",score:row.scoreInput,rationale:row.rationale,public_rationale:row.publicRationale,author_feedback:row.authorFeedback});
  queue.value=queue.value.filter(x=>x.id!==row.id);notice.value=row.decision==="yes"?"已发布。":"已退回。";
 }catch(e){fail(e)}finally{acting.value=false}
}
async function ask(){
 acting.value=true;error.value="";answer.value=undefined;
 try{answer.value=await api<Answer>("ask","POST",{question:question.value,keywords:keywords(question.value,terms.value)})}catch(e){fail(e)}finally{acting.value=false}
}
function state(value?:string){return ({pending:"待审核",published:"已公开",rejected:"已退回",withdrawn:"已撤回"} as Record<string,string>)[value||""]||value}
function scoreClass(score?:number){return score==null?"unknown":score>=80?"high":score>=60?"pass":"low"}
</script>

<template>
 <a class="skip" href="#main">跳到正文</a>
 <header class="topbar">
  <a class="brand" href="/#/workspace"><span class="seal">时</span><strong>时列</strong><span class="brand-sub">工作技巧交流区</span></a>
  <div class="account">
   <button v-if="session.workspaceAvailable&&session.role!=='moderator'" class="quiet" :disabled="acting" @click="workspaceLogin">使用工作台身份</button><a v-else-if="session.status!=='member'" class="quiet" href="/#/login" target="_blank" rel="noopener">登录工作台</a><span id="sessionStatus" role="status">{{session.message||(session.status==="member"?"已登录交流区":session.status==="checking"?"正在确认登录…":"浏览无需登录")}}</span>
   <details v-if="session.status!=='member'" class="login"><summary>用邀请登录</summary><form id="auth" @submit.prevent="login"><label>一次性邀请凭据<input :disabled="acting" v-model="token" type="password" required minlength="40" maxlength="128" autocomplete="off"></label><button :disabled="acting">登录交流区</button></form></details>
   <button v-else class="quiet" :disabled="acting" @click="logout">退出</button>
  </div>
 </header>
 <div class="workspace">
  <aside>
   <p class="nav-label">工作方法</p>
   <nav aria-label="交流区导航">
    <RouterLink to="/" :class="{selected:name==='feed'||name==='topic'}">浏览技巧<span>01</span></RouterLink>
    <RouterLink to="/ask" :class="{selected:name==='ask'}">问 AI<span>02</span></RouterLink>
    <RouterLink to="/mine" :class="{selected:name==='mine'}">我的投稿<span>03</span></RouterLink>
    <RouterLink v-if="session.status==='member'&&session.role==='moderator'" to="/review" :class="{selected:name==='review'}">审核工作台<span>04</span></RouterLink>
   </nav>
   <div class="sidebar-note"><b>看方法，也看依据。</b><p>评分满分100，60分及格。分数不是成功率，请同时核对原始来源和适用条件。</p></div>
   <a class="back-workspace" href="/#/workspace">← 返回工作台</a>
  </aside>
  <main id="main">
   <div class="breadcrumbs"><a href="/#/workspace">工作台</a><span>/</span><RouterLink to="/">技巧交流区</RouterLink><template v-if="name!=='feed'"><span>/</span><span>{{titles[name]}}</span></template></div>
   <header v-if="name!=='topic'" class="page-title"><div><h1 id="batch-heading" tabindex="-1">{{titles[name]}}</h1><p v-if="name==='feed'">找到一个能照着做的方法，再核对它是否适合你的工作。</p><p v-else-if="name==='ask'">从已公开的技巧里找依据，引用可以回到原帖。</p><p v-else-if="name==='review'">按投稿时间从早到晚审核，每批最多20条；返回首批可读取新增或重新送审的内容。</p><p v-else-if="name==='write'">写清楚怎么做、适合谁，以及如何判断做对了。</p></div><RouterLink v-if="name==='feed'" class="primary" to="/write">＋ 写技巧</RouterLink><RouterLink v-else class="quiet" :to="back">← 返回主题列表</RouterLink></header>
   <p v-if="notice" class="notice" role="status">{{notice}}</p>
   <div v-if="error" class="error" role="alert"><p>{{error}}</p><button v-if="['feed','topic','mine','review'].includes(name)&&!citationChanged" class="quiet" @click="load">重新读取</button><RouterLink v-if="citationChanged" class="quiet" to="/ask">重新检索依据</RouterLink></div>
   <template v-if="name==='feed'">
    <form id="lookup" class="search" @submit.prevent="find"><label class="sr-only" for="query">搜索工作技巧</label><input id="query" v-model="search" type="search" maxlength="120" placeholder="搜索工具、任务或遇到的问题…"><button :disabled="busy">搜索</button></form>
    <div class="list-heading"><span>{{currentQuery?'搜索结果':'公开主题'}}</span><span>审核分 / 100</span></div>
    <p v-if="busy&&!rows.length" role="status">正在读取主题…</p>
    <section id="feed" :aria-busy="busy" aria-label="公开主题">
     <article v-for="row in rows" :key="row.id" class="topic-row"><div><RouterLink class="topic-title" :to="link(row)">{{row.title}}</RouterLink><p v-if="row.excerpt" class="excerpt">{{row.excerpt}}</p><p v-else class="row-hint">打开原帖，查看步骤与来源</p></div><RouterLink class="score" :class="scoreClass(row.score)" :to="link(row,true)" aria-label="查看审核分与公开依据">{{row.score??'—'}}</RouterLink></article>
    </section>
    <div v-if="!busy&&!rows.length&&!error" class="empty"><h2>{{currentQuery?'没有找到匹配的技巧':'还没有已公开的技巧'}}</h2><p>{{currentQuery?'换一个关键词，或返回浏览全部主题。':'分享一个你用过的方法，审核通过后就能在这里找到。'}}</p><button v-if="currentQuery" @click="search='';find()">清除搜索，浏览全部</button><RouterLink v-else class="primary" to="/write">投稿第一条技巧</RouterLink></div>
    <div class="list-footer"><span>{{rows.length? '已显示 '+rows.length+' 条':''}}{{currentQuery&&rows.length===20?' · 搜索最多返回20条，请缩小关键词范围。':''}}</span><button v-if="cursor" id="more" :disabled="busy" @click="more">{{busy?'读取中…':'加载更多'}}</button></div>
   </template>
   <template v-else-if="name==='topic'">
    <RouterLink class="quiet back-list" :to="back">← 返回主题列表</RouterLink>
    <p v-if="busy" role="status">正在读取原帖…</p>
    <article v-if="topic" class="reader"><header><p class="eyebrow">工作技巧 · 已公开</p><h1>{{topic.title}}</h1><a class="rating-jump" href="#rating" @click.prevent="focusRating()">审核分 {{topic.score}} / 100 · 查看依据 ↓</a></header><PlainText :text="topic.body||''"/>
     <section class="rating-section"><h2 id="rating" tabindex="-1">审核依据</h2><p>审核分：<strong :class="scoreClass(topic.score)">{{topic.score}} / 100</strong>。60分及格；评分不是成功率或安全保证。</p><template v-if="topic.review"><PlainText :text="topic.review.rationale"/><p class="muted">审核记录时间：{{new Date(topic.review.reviewed_at).toLocaleString('zh-CN')}}</p></template><p v-else>尚无与当前版本对应、获准公开的审核依据。请结合原始来源判断，不要只凭分数操作。</p></section>
     <section v-if="topic.files?.length"><h2>随帖附件</h2><ul><li v-for="file in topic.files" :key="file.id"><a :href="'/api/community/download?file='+encodeURIComponent(file.id)">{{file.filename}} · {{Math.ceil(file.bytes/1024)}} KB</a></li></ul></section>
    </article>
   </template>
   <form v-else-if="['write','edit'].includes(name)" v-show="name!=='edit'||session.status==='member'" id="draft" class="editor" @submit.prevent="submit">
    <p v-if="name==='edit'" class="muted">提交改稿后会重新审核；已公开的内容将暂时从列表和搜索中撤下。旧版本保留，旧分数不会沿用。</p><p v-if="name==='edit'&&editOrigin?.author_feedback" class="author-note">上次审核建议：{{editOrigin.author_feedback}}</p><label>技巧标题<input :disabled="acting||busy" v-model="draft.title" required maxlength="120" @input="requestId=undefined" placeholder="用什么工具，完成什么事？"></label>
    <label>方法正文<textarea :disabled="acting||busy" v-model="draft.body" required maxlength="20000" rows="14" @input="requestId=undefined" placeholder="适用条件&#10;&#10;操作步骤&#10;&#10;如何检查结果&#10;&#10;原始来源链接与注意事项"></textarea></label>
    <p class="muted">链接会在原帖中直接打开。附件上传尚未开放，请勿粘贴密码、客户资料或其他隐私信息。</p><div class="form-actions"><button :disabled="acting||busy">{{acting?'提交中…':name==='edit'?'保存并重新送审':'提交审核'}}</button><RouterLink class="quiet" :to="name==='edit'?'/mine':'/'">取消，返回列表</RouterLink></div>
   </form>
   <template v-else-if="name==='mine'">
    <p v-if="busy" role="status">正在读取投稿…</p>
    <div v-else-if="!mine.length&&!error" class="empty">
     <h2>{{privateIndex===0?'还没有投稿':'本批已无投稿'}}</h2>
     <RouterLink v-if="privateIndex===0" class="primary" to="/write">分享第一个方法</RouterLink>
     <p v-else>列表可能发生了变化，可以返回首批重新读取。</p>
    </div>
    <section id="mineRows">
     <article v-for="row in mine" :key="row.id" class="mine-row">
      <div><RouterLink v-if="row.state==='published'" class="topic-title" :to="link(row)">{{row.title}}</RouterLink><strong v-else>{{row.title}}</strong><p class="muted">{{state(row.state)}}</p><p v-if="row.author_feedback" class="author-note">审核反馈：{{row.author_feedback}}</p></div>
      <RouterLink v-if="['pending','rejected','published'].includes(row.state||'')" class="quiet" :to="{name:'edit',params:{id:row.id}}">修改并送审</RouterLink>
      <button v-if="['published','pending'].includes(row.state||'')" class="quiet" :disabled="acting||busy" @click="withdraw(row)">撤回投稿</button>
     </article>
    </section>
   </template>
   <section v-else-if="name==='review'" id="queue">
    <p v-if="busy" role="status">正在读取待审投稿…</p>
    <div v-else-if="!queue.length&&!error" class="empty"><h2>本批没有待审核投稿</h2><p>这里只显示你有权审核、且不是由你提交的待审内容。可以查看下一批，或刷新首批。</p></div>
    <form v-for="row in queue" :key="row.id" class="review-form" @submit.prevent="review(row)">
     <h2>{{row.title}}</h2><PlainText :text="row.body||''"/>
     <div class="review-fields">
      <label>审核决定<select v-model="row.decision" required><option value="" disabled>请选择，不会自动发布</option><option value="yes">发布</option><option value="no">退回</option></select></label>
      <label>审核分<input v-model.number="row.scoreInput" type="number" min="0" max="100" step="1" required></label>
     </div>
     <label>审核依据<textarea name="rationale" v-model="row.rationale" rows="3" required maxlength="2000"></textarea></label>
     <label>给投稿人的反馈（仅投稿人和审核员可见）<textarea name="author_feedback" v-model="row.authorFeedback" rows="3" maxlength="2000" :required="row.decision==='no'"></textarea></label>
     <label class="check"><input v-model="row.publicRationale" type="checkbox">我确认这段审核依据可对所有读者公开</label>
     <button :disabled="acting">确认审核</button>
    </form>
   </section>
   <form v-else-if="name==='ask'" id="ask" class="editor" @submit.prevent="ask"><label>你想完成什么？<textarea v-model="question" required maxlength="240" rows="3" placeholder="描述任务，也可以说明手头使用的工具。"></textarea></label><details><summary>调整检索词（可选）</summary><label>用逗号分隔，最多5个<input v-model="terms" maxlength="160"></label></details><p class="muted">仅将你的问题和候选公开帖片段发送给配置的模型，不读取私有知识库。</p><button :disabled="acting">{{acting?'正在查找原文依据…':'查找原文依据'}}</button><section v-if="answer" id="answer" aria-live="polite"><h2>{{answer.mode==='ai_evidence'?'AI 选出的相关原文':answer.mode==='no_evidence'?'没有足够的公开依据':'关键词参考（未生成 AI 结果）'}}</h2><p v-if="answer.reason" class="muted">{{answer.reason}}</p><p v-if="answer.mode==='no_evidence'">换个说法或调整检索词。没有依据时不会编造答案。</p><blockquote v-for="(item,i) in answer.evidence" :key="i"><PlainText :text="item.quote"/><RouterLink :to="link(item)">查看《{{item.title}}》 →</RouterLink></blockquote></section></form>
   <nav v-if="name==='mine'||name==='review'" id="pageControls" class="batch-controls" :aria-label="name==='mine'?'投稿分页':'审核分页'">
    <p role="status">第 {{privateIndex+1}} 批 · 每批最多 {{name==='mine'?30:20}} 条</p>
    <div><button class="quiet" :disabled="busy||acting" @click="privatePage('first')">{{privateIndex===0?'刷新本批':'返回首批'}}</button><button class="quiet" :disabled="busy||acting||privateIndex===0" @click="privatePage('previous')">上一批</button><button class="quiet" :disabled="busy||acting||!privateNext" @click="privatePage('next')">下一批</button></div>
   </nav>
  </main>
 </div>
</template>
