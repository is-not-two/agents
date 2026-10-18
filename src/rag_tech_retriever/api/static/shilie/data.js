/* 网络与偏好；内容只写 PostgreSQL，浏览器仅保存阅读位置和显示偏好。 */
export async function api(path, body, method=body?'POST':'GET') {
 const response=await fetch('/api/'+path,{method,headers:body?{'Content-Type':'application/json'}:{},body:body?JSON.stringify(body):undefined,cache:'no-store'});
 const result=await response.json();
 if(!response.ok){const error=new Error(typeof result.detail==='string'?result.detail:'提交内容不符合要求，请检查输入');error.status=response.status;throw error;}
 return result;
}
export function read(key,fallback){try{return JSON.parse(localStorage.getItem('shilie-'+key))??fallback;}catch{return fallback;}}
export function write(key,value){try{localStorage.setItem('shilie-'+key,JSON.stringify(value));}catch{/* 偏好存储不可用不影响业务保存 */}}
export const groups=[{id:'workspace',title:'个人工作台',caption:'知识、计划与复盘'},{id:'automation',title:'自动化中心',caption:'检索与助手'},{id:'settings',title:'系统设置',caption:'连接、数据与界面'}];
export const modules=[
 ['knowledge','个人知识库','workspace','knowledge'],['documents','技术文档检索','workspace','search'],['planning','人生规划','workspace','planning'],['stages','阶段记录','workspace','stages'],
 ['workflows','工作流','automation','workflow'],['agents','Agent 设置','automation','agent'],['runs','运行记录','automation','stages'],['connections','模型连接','settings','connection'],['backup','数据与备份','settings','backup'],['appearance','界面偏好','settings','settings']
].map(([id,title,group,icon])=>({id,title,group,icon}));
export const priorities=['p0','p1','p2','p3','p4'];
export const priorityNames=['最高','较高','常规','较低','最低'];
export const state={knowledge:[],plans:[],stages:[],stageTime:'',stageError:'',authRequired:false,status:{},mode:read('mode','portal'),density:read('density',1),compactHero:read('hero',false),selectedNote:read('note',''),selectedPlan:read('plan',''),priority:read('priority','all'),filter:read('filter','all'),taskStatus:read('taskStatus','all'),query:read('query',''),view:read('view','story'),storyOpen:read('storyOpen',{}),recent:read('recent',[]),visits:read('visits',{}),runs:[],agents:[],workflows:[],workflowRuns:[],automationError:'',selectedFlow:read('flow',''),autoBusy:false,autoError:'',automationInput:{query:'',title:'',source:'',content:''},currentRun:null,runDetail:null,pendingTaskId:'',searchBusy:false,searchError:'',searchResultQuery:'',generate:false,searchResult:null,searchInput:'',scope:'all',graphSelection:'',loading:true,error:''};
state.mode=['portal','sidebar'].includes(state.mode)?state.mode:'portal';
state.density=[0,1,2].includes(state.density)?state.density:1;
state.priority=['all',...priorities].includes(state.priority)?state.priority:'all';
state.taskStatus=['all','available','locked','done'].includes(state.taskStatus)?state.taskStatus:'all';
state.filter=['all','notes','resources'].includes(state.filter)?state.filter:'all';
state.query=typeof state.query==='string'?state.query:'';
state.view=['story','tasks','relations'].includes(state.view)?state.view:'story';
state.storyOpen=state.storyOpen&&typeof state.storyOpen==='object'&&!Array.isArray(state.storyOpen)?state.storyOpen:{};
state.recent=Array.isArray(state.recent)?state.recent.filter(id=>modules.some(m=>m.id===id)).slice(0,4):[];
state.visits=state.visits&&typeof state.visits==='object'&&!Array.isArray(state.visits)?state.visits:{};
export function plan(){return state.plans.find(p=>p.id===state.selectedPlan)||state.plans[0];}
export function tasks(){return (plan()?.data.acts||[]).flatMap(a=>a.nodes.map(n=>({...n,act:a.title,actId:a.id})));}
export function currentNote(){return state.knowledge.find(n=>n.id===state.selectedNote)||state.knowledge[0];}
export async function load(){const session=await api('session');state.authRequired=session.required&&!session.authenticated;if(state.authRequired){Object.assign(state,{loading:false,error:''});return;}const [knowledge,plans,status,summary]=await Promise.all([api('knowledge'),api('plans'),api('status'),api('stage-summary').catch(error=>({records:[],updated_at:'',error:error.message}))]);const automation=await Promise.all([api('agents'),api('workflows'),api('workflow-runs')]).then(([agents,workflows,workflowRuns])=>({agents,workflows,workflowRuns,automationError:''})).catch(e=>({automationError:e.message}));Object.assign(state,automation,{knowledge,plans,status,stages:summary.records,stageTime:summary.updated_at,stageError:summary.error||'',loading:false,error:''});}

