import {state,titles} from './state.js';
import {api} from './api.js';
import {$,toast} from './ui.js';
let renderers={};
export function registerViews(views){renderers=views;}
export async function load() {
  const [knowledge, plans, stages, stats] = await Promise.all([api('/knowledge'), api('/plans'), api('/stages'), api('/status')]);
  Object.assign(state, {knowledge, plans, stages, stats});
  if (state.trash && state.page === 'knowledge') state.knowledge = await api('/knowledge?trash=true');
  if (state.trash && state.page === 'planning') state.plans = await api('/plans?trash=true');
  $('#connection').textContent = '已连接 · 内容持久保存';
  render();
}
export function navigate(page) {
  state.page = page; state.trash = false; state.filter = ''; location.hash = page;
  $('#crumb').textContent = titles[page]; document.querySelectorAll('[data-route]').forEach(item => item.classList.toggle('active', item.dataset.route === page));
  // 导航立即响应，随后再加载服务端最新内容。
  render();$('#page').setAttribute('aria-busy','true');
  load().catch(error => toast(error.message, true)).finally(()=>$('#page').removeAttribute('aria-busy'));
}
export function render() {
  $('#page').innerHTML = renderers[state.page]();
  $('#crumb').textContent = titles[state.page];
  document.querySelectorAll('[data-route]').forEach(item=>{if(item.dataset.route===state.page)item.setAttribute('aria-current','page');else item.removeAttribute('aria-current');});
  const filter = $('#filter'); if (filter) filter.addEventListener('input', event => {state.filter = event.target.value; $('#filtered').innerHTML=renderers.knowledgeCards();});
  const trash = $('#trash'); if (trash) trash.addEventListener('change', async event => {state.trash = event.target.checked; await load();});
}
