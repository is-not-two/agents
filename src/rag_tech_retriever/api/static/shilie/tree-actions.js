import {bindBranch} from './branch-actions.js?v=34';
/* 人生规划操作：同页展开的纵向列表。
   展开状态存在浏览器本地（显示偏好），完成状态走服务端版本保护。
   画布时代的拖动与缩放已移除——列表视图下二者都没有意义。 */
import {api,state,write} from './data.js?v=34';
import {treeState as s,treePlan,treeNodes,rootId,esc,isFolded,setFolded} from './tree.js?v=34';

export function bindTree({renderPage,refresh,toast}){
 const $=q=>document.querySelector(q),dialog=$('#tree-editor'),form=$('#tree-edit-form');
 let editing=null,saving=false;

 // 重绘但保留页面滚动位置，避免折叠时页面跳回顶部
 const redraw=()=>{const y=window.scrollY;renderPage({restore:true});window.scrollTo(0,y);};

 const branch=bindBranch({getPlan:treePlan,refresh,redraw,toast,setBusy:value=>s.busy=value,clearSelection:()=>s.selected=''});
 const descendants=id=>{const ids=new Set([id]);let size;do{size=ids.size;treeNodes().forEach(n=>{if(ids.has(n.parent_id))ids.add(n.id);});}while(size!==ids.size);return ids;};
 // 全部有子节点的 id，用于展开/收起全部
 const expandableIds=()=>{const ids=new Set([rootId()]);let changed=true;while(changed){changed=false;for(const n of treeNodes()){if(n.parent_id&&ids.has(n.parent_id)&&!ids.has(n.id)){ids.add(n.id);changed=true;}}}return ids;};

 function open(mode,id='',parent=''){
  const p=treePlan(),root=mode==='new-plan'||id===rootId(),node=treeNodes().find(n=>n.id===id);
  editing={mode,id,plan:p?structuredClone(p):null};form.reset();$('.tree-form-error').hidden=true;
  $('[data-root-field]').hidden=true;$('[data-node-fields]').hidden=root;
  $('#tree-editor-title').textContent=mode==='new-plan'?'创建'+(s.kind==='main'?'主线':'支线'):root?'编辑方向':mode==='add'?'添加下一步':'编辑这一步';
  $('#tree-add-context').textContent=root?'写下你想实现的目标。':mode==='add'?'添加到「'+(treeNodes().find(n=>n.id===parent)?.title||p.data.title)+'」下面':'修改这一步的内容。';
  form.querySelectorAll('details').forEach(d=>d.open=false);
  const value=root&&mode!=='new-plan'?p.data:node||{title:'',description:'',parent_id:parent,priority:'p2'};
  const excluded=node?descendants(id):new Set();
  form.elements.parent_id.innerHTML=`<option value="">方向根节点</option>`+treeNodes().filter(n=>!excluded.has(n.id)).map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');
  form.elements.requires.innerHTML=treeNodes().filter(n=>n.id!==id).map(n=>`<option value="${esc(n.id)}">${esc(n.title)}</option>`).join('');
  for(const key of ['title','description','parent_id','priority','due_date'])form.elements[key].value=value[key]||'';
  form.elements.kind.value=value.kind||s.kind;
  [...form.elements.requires.options].forEach(o=>o.selected=(value.requires||[]).includes(o.value));
  dialog.showModal();form.elements.title.focus();
 }

 form.addEventListener('submit',async e=>{
  e.preventDefault();if(saving)return;saving=true;
  const button=form.querySelector('[type=submit]'),error=$('.tree-form-error');
  button.disabled=true;button.textContent='保存中…';error.hidden=true;
  try{
   const {mode,id,plan:p}=editing,fd=new FormData(form),root=mode==='new-plan'||id===rootId();
   let data={title:fd.get('title'),description:fd.get('description')},row;
   if(root){
    data={...(p&&mode!=='new-plan'?p.data:{acts:[]}),...data,kind:fd.get('kind')};
    row=await api(mode==='new-plan'?'plans':`plans/${p.id}`,{data,...(mode==='new-plan'?{}:{version:p.version})},mode==='new-plan'?'POST':'PUT');
    s.kind=row.data.kind;write('tree-kind',s.kind);
   }else{
    data={...data,parent_id:fd.get('parent_id'),priority:fd.get('priority'),due_date:fd.get('due_date'),requires:[...form.elements.requires.selectedOptions].map(o=>o.value)};
    row=await api(`plans/${p.id}/nodes${mode==='add'?'':'/'+id}`,{data,version:p.version},mode==='add'?'POST':'PUT');
    if(mode==='add'){
     // 新增后把父链展开，用户能立刻看到刚加的项
     const byId=new Map(treeNodes().map(n=>[n.id,n]));
     const chain=new Set();let pid=data.parent_id;
     while(pid){chain.add(pid);pid=byId.get(pid)?.parent_id||'';}
     s.folded=s.folded.filter(v=>!chain.has(v));
     write('tree-folded',s.folded);
    }
   }
   s.planId=row.id;await refresh();dialog.close();toast('已保存到工作区');
  }catch(e){error.textContent=e.message;error.hidden=false;}
  finally{saving=false;button.disabled=false;button.textContent='保存';}
 });

 // 在捕获阶段处理，并阻断冒泡：app.js 对所有 [data-action] 会preventDefault
// 并进入 handleAction，若它先执行并重绘 DOM，本处理器后续拿到的按钮引用即失效，
// aria-expanded 读不到真实状态，折叠表现为"点了没反应"。
document.addEventListener('click',async e=>{
  const b=e.target.closest('[data-action^="tree-"]');if(!b||s.busy)return;
  e.preventDefault();e.stopPropagation();
  const action=b.dataset.action.slice(5),id=b.dataset.id,p=treePlan();

  if(action==='delete')return branch.preview(id);
  if(action==='clear-date'){form.elements.due_date.value='';form.elements.due_date.focus();return;}
  if(action==='new-plan')return open(action);
  if(action==='kind'){s.kind=b.dataset.kind;s.planId='';s.selected='';write('tree-kind',s.kind);return redraw();}
  if(action==='add')return open('add','',b.dataset.parent);
  if(action==='edit')return open('edit',id);

// 展开/收起：直接切换 DOM 的 hidden 与箭头状态，不触发整页重绘。
// 原因：app.js 在冒泡阶段对所有 [data-action] 调 preventDefault 并进入
// handleAction，走整页重绘；此时本处理器持有的按钮引用已失效，
// 重绘后 aria-expanded 读回旧值，表现为「点了没反应」。
// 折叠是纯显示偏好，就地切换既正确也更快。
if(action==='fold'){
   if(!id)return;
   // 以 DOM 的实际 hidden 为准翻转，避免模块级状态与界面不同步
   const scope=document.querySelector(`.node-kids[data-parent="${CSS.escape(id)}"],.dir-kids[data-parent="${CSS.escape(id)}"]`);
   const folded=scope?!scope.hidden:true;
   setFolded(id,folded);
   document.querySelectorAll(`[data-action="tree-fold"][data-id="${CSS.escape(id)}"]`).forEach(x=>{
     x.setAttribute('aria-expanded',String(!folded));
   });
   document.querySelectorAll(`.node-kids[data-parent="${CSS.escape(id)}"],.dir-kids[data-parent="${CSS.escape(id)}"]`).forEach(x=>{
     x.hidden=folded;
   });
   return;}
  if(action==='expand-all'){const ids=expandableIds();s.folded=s.folded.filter(v=>!ids.has(v));write('tree-folded',s.folded);return redraw();}
  if(action==='fold-all'){const ids=expandableIds();s.folded=[...new Set([...s.folded,...ids])];write('tree-folded',s.folded);return redraw();}

  if(!p)return;
  // 行首圆圈：切换完成，服务端仍做前置校验
  if(action==='toggle'){
   const node=treeNodes().find(n=>n.id===id);if(!node)return;
   s.busy=true;redraw();
   try{await api(`plans/${p.id}/nodes/${id}`,{data:{done:!node.done},version:p.version},'PUT');
    await refresh();toast(node.done?'已恢复为未完成':'已完成');}
   catch(error){toast(error.message,true);}
   finally{s.busy=false;redraw();}
  }
 },true);

 document.addEventListener('change',e=>{
  if(e.target.id==='tree-plan-picker'){s.planId=e.target.value;s.selected='';redraw();}
 });
}