import {$,esc,toast,busyButton} from '../ui.js';
import {api} from '../api.js';
import {load} from '../workspace.js';
export function showDialog(title, body, save = null, label = '保存') {
  const modal = $('#modal'); if (modal.getAttribute('aria-busy')==='true') return; if (modal.open) modal.close();
  modal.innerHTML = `<form id="modal-form"><div class="modal-head"><h2 id="modal-title">${esc(title)}</h2><button type="button" class="close" data-close aria-label="关闭对话框">×</button></div><div class="modal-body">${body}</div><div class="form-error" id="form-error" hidden></div><div class="modal-footer"><button type="button" class="secondary" data-close>${save?'取消':'关闭'}</button>${save?`<button type="submit" class="primary">${esc(label)}</button>`:''}</div></form>`;
  modal.querySelectorAll('[data-close]').forEach(element=>element.onclick=()=>modal.close());
  modal.oncancel=event=>{if(modal.getAttribute('aria-busy')==='true')event.preventDefault();};
  $('#modal-form').onsubmit = async event => {
    event.preventDefault(); if (!save || modal.getAttribute('aria-busy')==='true') return;
    const form=event.target, errorElement=$('#form-error',form), submit=$('button[type=submit]',form);
    errorElement.hidden=true; modal.setAttribute('aria-busy','true');
    const controls=[...form.querySelectorAll('input,textarea,select,button')].map(element=>({element,disabled:element.disabled}));
    controls.forEach(({element})=>element.disabled=true);
    // busyButton 保存提交按钮原状态，所以先还原再设忙碌态。
    submit.disabled=false; const reset=busyButton(submit,label==='保存'?'正在保存…':'正在处理…');
    let saved=false;
    try { await save(form); saved=true; }
    catch(error) { errorElement.textContent=error.message; errorElement.hidden=false; errorElement.setAttribute('role','alert');errorElement.scrollIntoView({block:'nearest'}); }
    finally { reset();controls.forEach(({element,disabled})=>element.disabled=disabled);modal.removeAttribute('aria-busy'); }
    if(saved){modal.close();try{await load();}catch(error){toast('操作已完成，页面刷新失败：'+error.message,true);}}
  };
  modal.showModal();
}
export function field(label,name,value='',type='text',required=false) {
  return `<label class="field">${label}<input name="${name}" type="${type}" value="${esc(value)}" ${required?'required':''} ${type==='text'?'maxlength="160"':''}></label>`;
}
export function textarea(label,name,value='',rows=6,required=false) {
  return `<label class="field">${label}<textarea name="${name}" rows="${rows}" ${required?'required':''}>${esc(value)}</textarea></label>`;
}
export function confirmation(title,description,action,label='确认') { showDialog(title,`<p class="text-block">${esc(description)}</p>`,action,label); }
export function loginDialog() {
  showDialog('进入你的个人工作台',field('访问令牌','token','','password',true),async f=>{await api('/session','POST',{token:f.elements.token.value});toast('已进入工作台');},'进入工作台');
}
