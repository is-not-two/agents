import {state} from './state.js';
import {api} from './api.js';
import {$,esc,button,toast} from './ui.js';
import {load,navigate,render} from './workspace.js';
import {showDialog,confirmation} from './dialogs/shared.js';
import {knowledgeDialog,historyDialog} from './dialogs/knowledge.js';
import {planDialog,savePlan,actDialog,nodeDialog} from './dialogs/planning.js';
import {stageDialog,stageFinish,stageDetails,stageCheck,restoreStage,exportDialog} from './dialogs/stages.js';
const pendingPlans=new Set();
export async function action(buttonElement) {
  const {action:actionName,id,act,node,kind}=buttonElement.dataset;
  if(actionName.startsWith('go-')) return navigate(actionName.slice(3));
  if(actionName==='knowledge-new') return knowledgeDialog();
  if(actionName==='knowledge-edit') return knowledgeDialog(id);
  if(actionName==='knowledge-view') {const row=state.knowledge.find(r=>r.id===id);return showDialog(row.data.title,`<div class="tags" style="margin-bottom:20px">${row.data.tags.map(t=>`<span class="tag">${esc(t)}</span>`).join('')}</div><div class="text-block">${esc(row.data.content)}</div><div class="knowledge-source">来源：${esc(row.data.source||'个人记录')} · 版本 ${row.version}</div><div class="heading-actions" style="margin-top:20px">${state.trash?'':button('编辑','knowledge-edit',id)+button('移入回收站','record-delete',id,'data-kind="knowledge"','text-button danger')}${button('历史版本','history',id,'data-kind="knowledge"')}</div>`);}
  if(actionName==='plan-new') return planDialog();
  if(actionName==='plan-edit') return planDialog(id);
  if(actionName==='plan-select') {state.selectedPlan=id; state.page='planning';location.hash='planning';document.querySelectorAll('[data-route]').forEach(b=>b.classList.toggle('active',b.dataset.route==='planning'));return render();}
  if(actionName==='act-new'||actionName==='act-edit') return actDialog(id,act);
  if(actionName==='node-new'||actionName==='node-edit') return nodeDialog(id,act,node);
  if(actionName==='node-toggle') {
    if(pendingPlans.has(id))return;
    const row=state.plans.find(r=>r.id===id),data=structuredClone(row.data);
    const target=data.acts.find(a=>a.id===act).nodes.find(n=>n.id===node);
    target.done=buttonElement.checked;pendingPlans.add(id);
    const panel=buttonElement.closest('.plan-detail'), task=buttonElement.closest('.task');
    panel.setAttribute('aria-busy','true');panel.querySelectorAll('input,button').forEach(element=>element.disabled=true);
    task.classList.add('pending');const badge=task.querySelector('.badge');badge.className='badge pending';badge.setAttribute('role','status');badge.innerHTML='<span class="spinner" aria-hidden="true"></span>正在保存…';
    try {
      let saved;
      try {saved=await savePlan(row,data);}catch(error){render();throw error;}
      state.plans[state.plans.findIndex(plan=>plan.id===id)]=saved;render();
      toast(target.done?'任务已完成，进度已保存':'任务已重新打开');
      try{await load();}catch(error){toast('进度已保存，页面刷新失败：'+error.message,true);}
      if(state.page==='planning'&&state.selectedPlan===id)document.querySelector(`[data-node="${node}"][data-action="node-toggle"]`)?.focus({preventScroll:true});
    } finally {pendingPlans.delete(id);}
    return;
  }
  if(actionName==='act-delete') {const row=state.plans.find(r=>r.id===id),target=row.data.acts.find(a=>a.id===act);if(target.nodes.length)throw new Error('请先处理阶段中的任务；这里只允许删除空阶段');return confirmation('删除空阶段','删除后可通过规划的历史版本恢复。',async()=>{const data=structuredClone(row.data);data.acts=data.acts.filter(a=>a.id!==act);await savePlan(row,data);toast('空阶段已删除');},'删除');}
  if(actionName==='node-delete') return confirmation('删除任务','删除此节点并移除其他节点对它的前置关系；可通过历史版本恢复。',async()=>{const row=state.plans.find(r=>r.id===id),data=structuredClone(row.data);data.acts.forEach(a=>{a.nodes=a.nodes.filter(n=>n.id!==node);a.nodes.forEach(n=>n.requires=n.requires.filter(r=>r!==node));});await savePlan(row,data);toast('任务已删除，历史仍可恢复');},'删除任务');
  if(actionName==='record-delete') {const row=(kind==='plan'?state.plans:state.knowledge).find(r=>r.id===id);return confirmation('移入回收站','正文和历史仍保留，你可以在回收站恢复。',async()=>{await api('/records/'+id+'?version='+row.version,'DELETE');toast('已移入回收站');},'移入回收站');}
  if(actionName==='history') return historyDialog(id,kind);
  if(actionName==='version-restore') return confirmation('恢复历史版本','将保存为新的版本，当前内容仍保留在历史里。',async()=>{await api('/records/'+id+'/restore','POST',{target_version:Number(buttonElement.dataset.version),current_version:Number(buttonElement.dataset.current)});state.trash=false;toast('历史版本已恢复');},'恢复版本');
  if(actionName==='stage-new') return stageDialog();
  if(actionName==='stage-finish') return stageFinish(id);
  if(actionName==='stage-details') return stageDetails(id);
  if(actionName==='stage-check') return stageCheck(id);
  if(actionName==='stage-restore') return restoreStage(id);
  if(actionName==='export') return exportDialog();
  if(actionName==='results-close') {$('#search-results').hidden=true;return;}
}
