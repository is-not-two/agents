import {state} from '../state.js';
import {api} from '../api.js';
import {$,esc,date,button,toast} from '../ui.js';
import {showDialog,field,textarea,confirmation} from './shared.js';
export function planDialog(id) {
  const row=state.plans.find(r=>r.id===id), data=row?.data||{};
  showDialog(row?'编辑人生方向':'新建人生规划',field('规划名称','title',data.title,'text',true)+`<label class="field">类型<select name="kind"><option value="main" ${data.kind==='main'?'selected':''}>主线 · 我想持续推进的方向</option><option value="side" ${data.kind==='side'?'selected':''}>支线 · 探索与兴趣</option></select></label>`+textarea('为什么想做 / 希望抵达哪里','description',data.description,5),async f=>{
    const saved=await api('/plans'+(row?'/'+row.id:''),row?'PUT':'POST',{data:{...data,title:f.elements.title.value,kind:f.elements.kind.value,description:f.elements.description.value,acts:data.acts||[]},version:row?.version});
    state.selectedPlan=saved.id; state.page='planning'; location.hash='planning'; document.querySelectorAll('[data-route]').forEach(b=>b.classList.toggle('active',b.dataset.route==='planning')); toast('人生规划已保存');
  });
}
export async function savePlan(row,data) { return api('/plans/'+row.id,'PUT',{data,version:row.version}); }
export function actDialog(planId,actId) {
  const row=state.plans.find(r=>r.id===planId), act=row.data.acts.find(a=>a.id===actId);
  showDialog(act?'编辑阶段':'添加阶段',field('阶段名称','title',act?.title,'text',true),async f=>{
    const data=structuredClone(row.data);
    if(act) data.acts.find(a=>a.id===actId).title=f.elements.title.value;
    else data.acts.push({id:crypto.randomUUID(),title:f.elements.title.value,nodes:[]});
    await savePlan(row,data); toast('阶段已保存');
  });
  if(act) $('.modal-body').insertAdjacentHTML('beforeend',button('删除空阶段','act-delete',planId,`data-act="${esc(actId)}"`,'text-button danger'));
}
export function nodeDialog(planId,actId,nodeId) {
  const row=state.plans.find(r=>r.id===planId), act=row.data.acts.find(a=>a.id===actId), node=act.nodes.find(n=>n.id===nodeId), all=row.data.acts.flatMap(a=>a.nodes).filter(n=>n.id!==nodeId);
  const body=field('任务名称','title',node?.title,'text',true)+textarea('具体行动 / 验收条件','description',node?.description,4)+field('目标日期（可选）','due_date',node?.due_date,'date')+`<div class="field">前置任务（全部完成后解锁）<div class="checkbox-list">${all.length?all.map(n=>`<label><input type="checkbox" name="requires" value="${esc(n.id)}" ${node?.requires.includes(n.id)?'checked':''}>${esc(n.title)}</label>`).join(''):'<span class="muted">这是第一个节点，无需前置任务。</span>'}</div><small>前置关系支持跨阶段；循环依赖会被拒绝。</small></div>`;
  showDialog(node?'编辑任务':'添加任务节点',body,async f=>{
    const data=structuredClone(row.data), target=data.acts.find(a=>a.id===actId);
    const saved={id:node?.id||crypto.randomUUID(),title:f.elements.title.value,description:f.elements.description.value,due_date:f.elements.due_date.value,requires:[...f.querySelectorAll('[name=requires]:checked')].map(e=>e.value),done:node?.done||false};
    if(node) target.nodes[target.nodes.findIndex(n=>n.id===nodeId)]=saved; else target.nodes.push(saved);
    await savePlan(row,data); toast('任务节点已保存');
  });
  if(node) $('.modal-body').insertAdjacentHTML('beforeend',button('删除此任务','node-delete',planId,`data-act="${esc(actId)}" data-node="${esc(nodeId)}"`,'text-button danger'));
}
