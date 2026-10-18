import {state,titles} from './state.js';
import {api} from './api.js';
import {$,esc,button,toast,empty,icon,names,busyButton} from './ui.js';
import {load,navigate,registerViews} from './workspace.js';
import {action} from './actions.js';
import {loginDialog} from './dialogs/shared.js';
import {overview} from './views/overview.js';
import {knowledgePage,knowledgeCards} from './views/knowledge.js';
import {planningPage} from './views/planning.js';
import {stagesPage} from './views/stages.js';
import {setupPreferences} from './preferences.js';
registerViews({overview,knowledge:knowledgePage,planning:planningPage,stages:stagesPage,knowledgeCards});
setupPreferences();
document.querySelectorAll('[data-icon]').forEach(element=>element.innerHTML=icon(element.dataset.icon));
document.addEventListener('workspace:unauthorized',loginDialog);
document.addEventListener('click',event=>{const route=event.target.closest('[data-route]');if(route){navigate(route.dataset.route);return;}const target=event.target.closest('[data-action]');if(target)action(target).catch(error=>toast(error.message,true));});
$('#search-form').addEventListener('submit',async event=>{
  event.preventDefault(); const submit=$('button[type=submit]',event.target),result=$('#search-results');if(submit.disabled)return;const reset=busyButton(submit,'检索中…');result.hidden=false;result.setAttribute('aria-busy','true');result.innerHTML='<div class="result-panel loading"><span class="spinner" aria-hidden="true"></span>正在检索你的内容…</div>';
  try {
    const data=await api('/query','POST',{query:$('#query').value,scope:$('#scope').value,mode:$('#semantic').checked?'vector':'text',generate:$('#generate').checked});
    result.innerHTML=`<section class="result-panel"><div class="result-header"><div><h2>检索结果 · ${data.hits.length} 条</h2><p>${esc(data.engine)}</p></div>${button('收起','results-close','','','text-button')}</div>${data.notes.map(n=>`<div class="notice">${esc(n)}</div>`).join('')}${data.answer?`<div class="text-block" style="margin:20px 0">${esc(data.answer)}</div>`:''}${data.hits.length?data.hits.map((h,i)=>`<article class="hit"><h3>[${i+1}] ${esc(h.title)}</h3><div class="hit-meta"><span>${esc(h.source)}</span><span class="badge">${esc(names[h.status_marker]||h.status_marker)}</span></div><details><summary>展开引用原文</summary><div class="text-block">${esc(h.content)}</div></details></article>`).join(''):empty('⌕','没有找到相关内容','换一个关键词，或先把这条知识记下来。')}</section>`;
  } catch(error) {result.innerHTML=`<div class="notice" role="alert">${esc(error.message)}</div>`;} finally{reset();result.removeAttribute('aria-busy');}
});
document.addEventListener('keydown',event=>{if((event.ctrlKey||event.metaKey)&&event.key==='k'){event.preventDefault();$('#query').focus();}});
window.addEventListener('hashchange',()=>{const page=location.hash.slice(1);if(titles[page]&&page!==state.page)navigate(page);});
$('#today').textContent=new Date().toLocaleDateString('zh-CN',{year:'numeric',month:'long',day:'numeric',weekday:'short'});
(async()=>{try{const session=await api('/session');if(!session.authenticated){loginDialog();return;}navigate(titles[location.hash.slice(1)]?location.hash.slice(1):'overview');}catch(error){toast(error.message,true);$('#page').innerHTML=empty('!','工作台暂时无法连接',esc(error.message));}})();

