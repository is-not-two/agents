// DOM、格式化和基础组件；不请求业务接口。
export const $=(selector,scope=document)=>scope.querySelector(selector);
export const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
export const date=value=>new Date(value).toLocaleString('zh-CN',{month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'});
export const names={main:'主线',side:'支线',available:'可开始',locked:'待解锁',done:'已完成',running:'进行中',passed:'已验证完成',attention:'待处理',rolled_back:'已回滚',PERSONAL:'个人内容',CONFIRMED:'已确认',PENDING:'待注册',DISABLED:'不分配',EXCEPTION:'异常状态',UNKNOWN:'状态未标注'};
let toastTimer;
export function icon(name) {
 const paths={overview:'<rect x="2" y="2" width="5" height="5" rx="1"/><rect x="11" y="2" width="5" height="5" rx="1"/><rect x="2" y="11" width="5" height="5" rx="1"/><rect x="11" y="11" width="5" height="5" rx="1"/>',knowledge:'<path d="M4 2h8l3 3v11H4zM12 2v4h3M7 9h5M7 12h5"/>',planning:'<path d="M4 3v12M4 5h8M4 13h8"/><circle cx="13" cy="5" r="2"/><circle cx="13" cy="13" r="2"/>',stages:'<path d="M3 8a6 6 0 1 1 1 5M3 3v5h5M9 5v4l3 2"/>',search:'<circle cx="8" cy="8" r="5"/><path d="m12 12 4 4"/>',task:'<circle cx="9" cy="9" r="6"/><path d="m6 9 2 2 4-4"/>'};
 return `<svg class="icon" viewBox="0 0 18 18" aria-hidden="true">${paths[name]||paths.knowledge}</svg>`;
} 

export function toast(message, error = false) {
  const element = $('#toast'); element.textContent = message; element.className = error ? 'error' : ''; element.hidden = false;
  element.setAttribute('role',error?'alert':'status');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => element.hidden = true, error ? 7000 : 4000);
}
// 将反馈绑定到真实请求生命周期；返回恢复函数，调用方处理业务结果。
export function busyButton(element,label) {
  const previous={html:element.innerHTML,disabled:element.disabled,width:element.style.minWidth};
  element.style.minWidth=`${element.getBoundingClientRect().width}px`;
  element.disabled=true; element.setAttribute('aria-busy','true');
  element.innerHTML=`<span class="spinner" aria-hidden="true"></span><span>${esc(label)}</span>`;
  return ()=>{element.innerHTML=previous.html;element.disabled=previous.disabled;element.style.minWidth=previous.width;element.removeAttribute('aria-busy');};
}
export function button(label, action, id = '', extra = '', classes = 'secondary') {
  return `<button type="button" class="${classes}" data-action="${action}" data-id="${esc(id)}" ${extra}>${label}</button>`;
}
export function heading(title,subtitle,actions='') {
 return `<div class="page-heading"><div><h1>${title}</h1><p class="subtitle">${subtitle}</p></div><div class="heading-actions">${actions}</div></div>`;
}
export function empty(symbol,title,description,action='') {
 return `<div class="empty">${icon(symbol)}<strong>${title}</strong><p>${description}</p>${action}</div>`;
}
export function badge(key) { return `<span class="badge ${esc(key)}">${esc(names[key] || key)}</span>`; }
