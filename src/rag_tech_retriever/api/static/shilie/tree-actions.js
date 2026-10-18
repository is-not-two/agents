import {bindBranch} from './branch-actions.js?v=25';
/* 规划树操作：表单版本固定、保存后刷新，画布状态独立于领域数据。 */
import {api,state,write} from './data.js?v=25';
import {treeState as s,treePlan,treeNodes,rootId,esc} from './tree.js?v=25';
export function bindTree({renderPage,refresh,toast}){
 const $=q=>document.querySelector(q),dialog=$('#tree-editor'),form=$('#tree-edit-form');let editing=null,saving=false;
 const redraw=()=>{const v=$('.tree-viewport'),x=v?.scrollLeft||0,y=v?.scrollTop||0;renderPage({restore:true});const next=$('.tree-viewport');if(next){next.scrollLeft=x;next.scrollTop=y;}};
 const branch=bindBranch({getPlan:treePlan,refresh,redraw,toast,setBusy:value=>s.busy=value,clearSelection:()=>s.selected=''});
 const descendants=id=>{const ids=new Set([id]);let size;do{size=ids.size;treeNodes().forEach(n=>{if(ids.has(n.parent_id))ids.add(n.id);});}while(size!==ids.size);return ids;};
 function open(mode,id='',parent=''){
  const p=treePlan(),root=mode==='new-plan'||id===rootId(),node=treeNodes().find(n=>n.id===id);editing={mode,id,plan:p?structuredClone(p):null};form.reset();$('.tree-form-error').hidden=true;
  $('[data-root-field]').hidden=true;$('[data-node-fields]').hidden=root;$('#tree-editor-title').textContent=mode==='new-plan'?'创建'+(s.kind==='main'?'主线':'支线'):root?'编辑方向':mode==='add'?'添加下一步':'编辑这一步';
  $('#tree-add-context').textContent=root?'写下你想实现的目标。':mode==='add'?'添加到「'+(treeNodes().find(n=>n.id===parent)?.title||p.data.title)+'」下面':'修改这一步的内容。';form.querySelectorAll('details').forEach(d=>d.open=false);
  const value=root&&mode!=='new-plan'?p.data:node||{title:'',description:'',parent_id:parent,priority:'p2'};
  const excluded=node?descendants(id):new Set();form.elements.parent_id.innerHTML=`<option value="">方向根节点</option>`+treeNodes().filter(n=>!excluded.has(n.id)).map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');
  form.elements.requires.innerHTML=treeNodes().filter(n=>n.id!==id).map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');
  for(const key of ['title','description','parent_id','priority','due_date'])form.elements[key].value=value[key]||'';
  form.elements.kind.value=value.kind||s.kind;[...form.elements.requires.options].forEach(o=>o.selected=(value.requires||[]).includes(o.value));dialog.showModal();form.elements.title.focus();
 }
 form.addEventListener('submit',async e=>{e.preventDefault();if(saving)return;saving=true;const button=form.querySelector('[type=submit]'),error=$('.tree-form-error');button.disabled=true;button.textContent='保存中…';error.hidden=true;
  try{const {mode,id,plan:p}=editing,fd=new FormData(form),root=mode==='new-plan'||id===rootId();let data={title:fd.get('title'),description:fd.get('description')},row;
   if(root){data={...(p&&mode!=='new-plan'?p.data:{acts:[]}),...data,kind:fd.get('kind')};row=await api(mode==='new-plan'?'plans':`plans/${p.id}`,{data,...(mode==='new-plan'?{}:{version:p.version})},mode==='new-plan'?'POST':'PUT');s.kind=row.data.kind;write('tree-kind',s.kind);}
   else{data={...data,parent_id:fd.get('parent_id'),priority:fd.get('priority'),due_date:fd.get('due_date'),requires:[...form.elements.requires.selectedOptions].map(o=>o.value)};row=await api(`plans/${p.id}/nodes${mode==='add'?'':'/'+id}`,{data,version:p.version},mode==='add'?'POST':'PUT');if(mode==='add'){const old=new Set(p.data.acts.flatMap(a=>a.nodes).map(n=>n.id));s.selected=row.data.acts.flatMap(a=>a.nodes).find(n=>!old.has(n.id))?.id||'';const byId=new Map(treeNodes().map(n=>[n.id,n]));const keep=new Set([rootId()]);let pid=data.parent_id;while(pid){keep.add(pid);pid=byId.get(pid)?.parent_id||'';}s.folded=s.folded.filter(v=>!keep.has(v));write('tree-folded',s.folded);} }
   s.planId=row.id;await refresh();if(root){s.selected=rootId();redraw();}const viewport=$('.tree-viewport'),selected=[...document.querySelectorAll('.tree-item')].find(n=>n.dataset.node===s.selected);if(viewport&&selected){viewport.scrollLeft=Math.max(0,(selected.offsetLeft+selected.offsetWidth/2)*s.zoom/100-viewport.clientWidth/2);viewport.scrollTop=Math.max(0,(selected.offsetTop+selected.offsetHeight/2)*s.zoom/100-viewport.clientHeight/2);}dialog.close();toast('已保存到工作区');
  }catch(e){error.textContent=e.message;error.hidden=false;}finally{saving=false;button.disabled=false;button.textContent='保存';}
 });
 document.addEventListener('click',async e=>{const b=e.target.closest('[data-action^="tree-"]');if(!b||s.busy)return;const action=b.dataset.action.slice(5),id=b.dataset.id,p=treePlan();
  if(action==='delete')return branch.preview(id);
  if(action==='clear-date'){form.elements.due_date.value='';form.elements.due_date.focus();return;}
  if(action==='new-plan')return open(action);
  if(action==='kind'){s.kind=b.dataset.kind;s.planId='';s.selected='';write('tree-kind',s.kind);return redraw();}
  if(action==='select'){s.selected=id;const hasChildren=id===rootId()?treeNodes().some(n=>!n.parent_id):treeNodes().some(n=>n.parent_id===id);if(hasChildren){s.folded=s.folded.includes(id)?s.folded.filter(v=>v!==id):[...s.folded,id];write('tree-folded',s.folded);}redraw();const selected=[...document.querySelectorAll('[data-action=tree-select]')].find(n=>n.dataset.id===id);selected?.focus({preventScroll:true});return;}if(action==='dismiss'){s.selected='';return redraw();}
  if(action==='add')return open('add','',b.dataset.parent);if(action==='edit')return open('edit',id);
  if(action==='fold'){s.folded=s.folded.includes(id)?s.folded.filter(v=>v!==id):[...s.folded,id];write('tree-folded',s.folded);redraw();document.querySelectorAll('[data-action="tree-fold"]').forEach(x=>{if(x.dataset.id===id)x.focus({preventScroll:true});});return;}
  if(action==='reset'){s.zoom=100;write('tree-zoom',100);redraw();}
  if(action==='locate'||action==='reset'){$('.tree-viewport')?.scrollTo({left:0,top:Math.max(0,($('.tree-root')?.offsetTop||0)*s.zoom/100-100),behavior:matchMedia('(prefers-reduced-motion: reduce)').matches?'instant':'smooth'});return;}
  if(!p)return;
  if(action==='complete'){const node=treeNodes().find(n=>n.id===id);if(!node)return;s.busy=true;redraw();try{await api(`plans/${p.id}/nodes/${id}`,{data:{done:!node.done},version:p.version},'PUT');await refresh();toast('节点状态已保存');}catch(error){toast(error.message,true);}finally{s.busy=false;redraw();}}
 });
 document.addEventListener('change',e=>{if(e.target.id==='tree-plan-picker'){s.planId=e.target.value;s.selected='';redraw();}});
 document.addEventListener('input',e=>{if(e.target.id!=='tree-zoom')return;const v=$('.tree-viewport'),plane=$('.tree-plane'),world=$('.tree-world'),old=s.zoom/100;s.zoom=Number(e.target.value);write('tree-zoom',s.zoom);$('#tree-zoom-output').textContent=s.zoom+'%';if(!plane)return;const z=s.zoom/100,cx=(v.scrollLeft+v.clientWidth/2)/old,cy=(v.scrollTop+v.clientHeight/2)/old;plane.style.transform=`scale(${z})`;world.style.width=Number(plane.dataset.width)*z+'px';world.style.height=Number(plane.dataset.height)*z+'px';v.scrollLeft=cx*z-v.clientWidth/2;v.scrollTop=cy*z-v.clientHeight/2;});
 let pan=null;document.addEventListener('pointerdown',e=>{const v=e.target.closest('.tree-viewport');if(!v||e.pointerType!=='mouse'||e.button!==0||e.target.closest('button'))return;pan={v,x:e.clientX,y:e.clientY,left:v.scrollLeft,top:v.scrollTop};v.setPointerCapture(e.pointerId);v.classList.add('is-panning');});document.addEventListener('pointermove',e=>{if(pan){pan.v.scrollLeft=pan.left+pan.x-e.clientX;pan.v.scrollTop=pan.top+pan.y-e.clientY;}});const end=()=>{pan?.v.classList.remove('is-panning');pan=null;};document.addEventListener('pointerup',end);document.addEventListener('pointercancel',end);
}
