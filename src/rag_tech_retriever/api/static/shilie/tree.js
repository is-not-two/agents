import {branchNotice,branchDialog} from './branch-actions.js?v=51';
/* 人生规划：同页展开的纵向列表。点方向或节点即在下方展开，不跳页；
   行首圆圈切换完成，方向行常驻进度条，收起时也能一眼看到做到哪了。
   数据接口与后端契约不变——本文件只负责把 acts[].nodes 渲染成层级列表。 */
import {state,read,write} from './data.js?v=51';
export const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const treeState={kind:read('tree-kind','main'),planId:'',selected:'',folded:read('tree-folded',[]),busy:false};
if(!['main','side'].includes(treeState.kind))treeState.kind='main';
if(!Array.isArray(treeState.folded))treeState.folded=[];
const action=(label,name,extra='',cls='tree-button')=>`<button class="${cls}" data-action="tree-${name}" ${extra}>${label}</button>`;
const status=n=>n.done?'已完成':n.state==='locked'?'等待前置':'可开始';
export const treePlan=()=>state.plans.find(p=>p.id===treeState.planId&&p.data.kind===treeState.kind)||state.plans.find(p=>p.data.kind===treeState.kind);
export const treeNodes=()=>treePlan()?.data.acts.flatMap(a=>a.nodes)||[];
export const rootId=()=>{let id='@root:'+treePlan()?.id;const ids=new Set(treeNodes().map(n=>n.id));while(ids.has(id))id+='@';return id;};

/* 展开/收起状态持久化，刷新后保留。返回切换后的折叠状态。 */
export const isFolded=id=>treeState.folded.includes(id);
export function setFolded(id,folded){
  if(folded===undefined){folded=!treeState.folded.includes(id);}
  treeState.folded=folded?treeState.folded.filter(v=>v!==id):[...treeState.folded,id];
  write('tree-folded',treeState.folded);
  return folded;
}

/* 节点完成状态：节点自身done，或其子树全部完成——方向行据此显示汇总进度 */
const nodeDone=n=>!!n.done;
export function subtree(nodes,id){return nodes.filter(n=>n.parent_id===id);}
export function progressOf(nodes){
  const done=nodes.filter(nodeDone).length;
  return {done,total:nodes.length,percent:nodes.length?Math.round(done/nodes.length*100):0};
}

/* 渲染一个节点行。depth=0 表示方向本身，1+ 为其下步骤 */
function nodeRow(n,depth,hasKids){
  const folded=isFolded(n.id),done=nodeDone(n),p=(n.priority||'p2').toUpperCase();
  const due=n.due_date?`<div class="node-meta"><span class="due">◷ ${esc(n.due_date)}</span></div>`:'';
  const state=`<span class="node-tag${n.state==='locked'?' wait':''}">${status(n)}</span>`;
  const desc=n.description?`<div class="node-meta">${esc(n.description)}</div>`:'';
  return `<div class="node-row depth-${Math.min(depth,4)}${done?' is-done':''}" data-node="${esc(n.id)}">
    <button class="node-tw" data-action="tree-fold" data-id="${esc(n.id)}" aria-expanded="${!folded}" aria-label="${folded?'展开':'收起'} ${esc(n.title)}" ${hasKids?'':'hidden'}>▶</button>
    <button class="node-tick" data-action="tree-toggle" data-id="${esc(n.id)}" aria-pressed="${done}" aria-label="${done?'撤销完成':'标记完成'}：${esc(n.title)}" ${treeState.busy||n.state==='locked'&&!done?'disabled':''}>${done?'✓':''}</button>
    <div class="node-body">
      <div class="node-line"><button class="node-title" data-action="tree-fold" data-id="${esc(n.id)}" ${hasKids?'':'disabled'}>${esc(n.title)}</button>${state}<span class="node-pri">${p}</span><span class="node-mark${done?' yes':' no'}">${done?'✓':'✗'}</span></div>
      ${due||desc}
      ${n.requires&&n.requires.length?`<div class="node-meta">需先完成：${n.requires.map(id=>{const t=treeNodes().find(x=>x.id===id);return esc(t?t.title:id);}).join('、')}</div>`:''}
    </div>
    <div class="node-tools">${action('＋','add',`data-parent="${esc(n.id)}" aria-label="在 ${esc(n.title)} 下添加" class="node-tool"`)}${action('✎','edit',`data-id="${esc(n.id)}" aria-label="编辑 ${esc(n.title)}" class="node-tool"`)}${action('×','delete',`data-id="${esc(n.id)}" aria-label="删除 ${esc(n.title)}" class="node-tool danger"`)}</div>
  </div>${hasKids?`<div class="node-kids" data-parent="${esc(n.id)}" ${folded?'hidden':''}>${renderKids(n,depth+1)}</div>`:''}`;
}
function renderKids(n,depth){
  return subtree(treeNodes(),n.id).map(k=>nodeRow(k,depth,subtree(treeNodes(),k.id).length>0)).join('');
}

/* 方向卡：收起时也显示完成数与进度条 */
function direction(p){
  const nodes=treeNodes(),prog=progressOf(nodes),folded=isFolded(rootId());
  const hasKids=nodes.length>0;
  return `<section class="dir-card">
    <div class="dir-head">
      <button class="dir-tw" data-action="tree-fold" data-id="${esc(rootId())}" aria-expanded="${!folded}" aria-label="${folded?'展开':'收起'}方向">▶</button>
      <button class="dir-title" data-action="tree-fold" data-id="${esc(rootId())}" aria-expanded="${!folded}" ${hasKids?'':'disabled'}>${esc(p.data.title)}</button>
      <span class="dir-track" role="img" aria-label="完成 ${prog.percent}%"><i style="width:${prog.percent}%"></i></span>
      <span class="dir-count">${prog.done}/${prog.total}</span>
      <div class="dir-tools">${action('✎','edit',`data-id="${esc(rootId())}" aria-label="编辑方向" class="node-tool"`)}${action('×','delete',`data-id="${esc(rootId())}" aria-label="删除方向" class="node-tool danger"`)}</div>
    </div>
    ${p.data.description?`<p class="dir-desc">${esc(p.data.description)}</p>`:''}
    <div class="dir-kids" data-parent="${esc(rootId())}" ${folded?'hidden':''}>
      ${hasKids?nodes.filter(n=>!n.parent_id).map(n=>nodeRow(n,1,subtree(nodes,n.id).length>0)).join(''):`<p class="dir-empty">还没有步骤。点 ＋ 添加第一个。</p>`}
    </div>
  </section>`;
}

function emptyState(){
  return `<section class="dir-card is-empty">
    <div class="dir-head">
      <button class="dir-tw" hidden>▶</button>
      <span class="dir-title plain">${treeState.kind==='main'?'你的主线，从这里延伸':'为想探索的事，留一条支线'}</span>
      ${action('＋ 创建第一条'+(treeState.kind==='main'?'主线':'支线'),'new-plan','','primary-button')}
    </div>
    <p class="dir-desc">创建一个方向，再用节点把目标一步步展开。点节点在下方继续展开下一步。</p>
  </section>`;
}

export function treeView(){
  const p=treePlan(),plans=state.plans.filter(x=>x.data.kind===treeState.kind);
  if(p)treeState.planId=p.id;
  return `<section class="planning-studio">
    <header class="studio-heading"><div><p class="studio-caption">把方向展开，让下一步清晰</p><h1>人生规划</h1></div></header>
    ${branchNotice(p)}
    <div class="studio-toolbar">
      <nav class="tree-kind-switch" aria-label="规划分类">${['main','side'].map(k=>action(k==='main'?'主线':'支线','kind',`data-kind="${k}" aria-pressed="${treeState.kind===k}"`)).join('')}</nav>
      ${plans.length>1?`<label class="tree-plan-picker"><span>切换方向</span><select id="tree-plan-picker" aria-label="切换规划方向">${plans.map(row=>`<option value="${row.id}" ${row.id===p?.id?'selected':''}>${esc(row.data.title)}</option>`).join('')}</select></label>`:''}
      ${action('＋ 新建'+(treeState.kind==='main'?'主线':'支线'),'new-plan','','primary-button tree-new')}
      ${action('全部展开','expand-all','','tree-button')}
      ${action('全部收起','fold-all','','tree-button')}
    </div>
    <div class="tree-list${treeState.kind==='side'?' is-side':''}">${p?direction(p):emptyState()}</div>
  </section>`;
}

export function treeDialog(){
  return branchDialog()+`<dialog id="tree-editor" class="form-dialog" aria-labelledby="tree-editor-title"><form id="tree-edit-form"><header class="drawer-header"><div><small>时列 · 人生规划</small><h2 id="tree-editor-title">添加下一步</h2></div><button type="button" class="icon-button" data-action="close-dialog" aria-label="关闭编辑">×</button></header><div class="drawer-content"><p id="tree-add-context" class="tree-add-context"></p><label class="form-field">你想做什么？<input name="title" required maxlength="160" placeholder="例如：读完一本书" autocomplete="off"></label><p class="entry-hint">只填这一项就能保存，其余可以以后再补。</p><label hidden>添加位置<select name="parent_id"></select></label><label hidden data-root-field>类型<select name="kind"><option value="main">主线</option><option value="side">支线</option></select></label><details class="tree-optional"><summary>补充信息 <span>可不填</span></summary><label class="form-field">说明（选填）<textarea name="description" rows="3" maxlength="20000" placeholder="想补充什么，就写在这里"></textarea></label><div data-node-fields><label class="form-field">计划日期（选填）<div class="optional-date"><input name="due_date" type="date" aria-describedby="date-hint"><button type="button" data-action="tree-clear-date" class="tree-button">清除日期</button></div><small id="date-hint">不确定时间就留空，不影响添加和完成。</small></label><label class="form-field">优先级（可不选）<select name="priority">${['p0','p1','p2','p3','p4'].map((p,i)=>`<option value="${p}">${['P0 · 最重要','P1 · 优先做','P2 · 常规（默认）','P3 · 稍后做','P4 · 有空再做'][i]}</option>`).join('')}</select></label><label class="form-field">需要先完成哪些任务？（选填）<select name="requires" multiple></select><small>没有要求就留空，按 Ctrl 可选多个。</small></label></div></details><p class="tree-form-error error-text" role="alert" hidden></p><div class="form-actions"><button type="button" class="small-button" data-action="close-dialog">取消</button><button type="submit" class="primary-button">保存</button></div></div></form></dialog>`;
}