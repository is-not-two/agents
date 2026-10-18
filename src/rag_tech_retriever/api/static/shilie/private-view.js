/* 私密管理：愿望清单与私密日记。
   口令不存浏览器——每次访问都由后端校验，明文只在当前页面内存中存在。
   因此本模块不做路由级缓存，刷新即重新要求口令。 */
import {api,state} from './data.js?v=37';

const esc=x=>String(x??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const CATS=['想拥有','想去做'];

const v={configured:null,strongCrypto:false,password:'',unlocked:false,busy:'',error:'',
         tab:'wish',wishes:[],diaries:[],filter:'all',query:'',setupCode:'',probing:false};

async function status(){
  try{
    const s=await api('private/status');
    v.configured=s.configured;v.strongCrypto=s.strong_crypto||false;
  }catch(e){v.error=e.message;}
  return v;
}
async function unlock(password){
  v.busy='unlock';v.error='';
  try{await api('private/unlock',{password});v.password=password;v.unlocked=true;await load();}
  catch(e){v.error=e.message;}
  finally{v.busy='';}
}
async function setup(password){
  v.busy='setup';v.error='';
  try{const r=await api('private/setup',{password});v.setupCode=r.recovery_code;v.password=password;v.unlocked=true;await load();}
  catch(e){v.error=e.message;}
  finally{v.busy='';}
}
async function load(){
  v.busy='load';v.error='';
  try{
    const [w,d]=await Promise.all([
      api('private/wish?password='+encodeURIComponent(v.password)),
      api('private/diary?password='+encodeURIComponent(v.password)),
    ]);
    v.wishes=w;v.diaries=d;
  }catch(e){v.error=e.message;if(String(e.message).includes('口令'))v.unlocked=false;}
  finally{v.busy='';refreshPrivate();}
}
async function saveWish(form){
  v.busy='save';v.error='';
  const fd=new FormData(form);
  try{
    const data={title:String(fd.get('title')||'').trim(),note:String(fd.get('note')||'').trim(),
      category:String(fd.get('category')||CATS[0]),emoji:String(fd.get('emoji')||'✨'),
      price:String(fd.get('price')||'').trim(),done:fd.get('done')==='on'};
    if(!data.title)throw Error('请填写愿望名称');
    await api('private/wish',{password:v.password,data});
    await load();toast('愿望已保存');
  }catch(e){v.error=e.message;toast(e.message,true);}
  finally{v.busy='';}
}
async function toggleWish(id,done){
  const row=v.wishes.find(w=>w.id===id);if(!row)return;
  v.busy='save';v.error='';
  try{
    await api('private/wish/'+id,{password:v.password,version:row.version,
      data:{...row.data,title:row.data.title,done:!done}});
    await load();
  }catch(e){v.error=e.message;toast(e.message,true);}
  finally{v.busy='';}
}
async function removeWish(id){
  const row=v.wishes.find(w=>w.id===id);if(!row)return;
  if(!confirm('删除「'+row.data.title+'」？此操作不可撤销。'))return;
  v.busy='save';v.error='';
  try{await api('private/wish/'+id+'?version='+row.version,undefined,'DELETE');await load();toast('已删除');}
  catch(e){v.error=e.message;toast(e.message,true);}
  finally{v.busy='';}
}
async function saveDiary(form){
  v.busy='save';v.error='';
  const fd=new FormData(form);
  try{
    const data={title:String(fd.get('title')||'').trim(),content:String(fd.get('content')||'').trim(),
      date:String(fd.get('date')||new Date().toISOString().slice(0,10))};
    if(!data.title)throw Error('请填写标题');
    await api('private/diary',{password:v.password,data});
    await load();toast('日记已保存');
  }catch(e){v.error=e.message;toast(e.message,true);}
  finally{v.busy='';}
}
async function removeDiary(id){
  const row=v.diaries.find(d=>d.id===id);if(!row)return;
  if(!confirm('删除「'+row.data.title+'」？此操作不可撤销。'))return;
  v.busy='save';v.error='';
  try{await api('private/diary/'+id+'?version='+row.version,undefined,'DELETE');await load();toast('已删除');}
  catch(e){v.error=e.message;toast(e.message,true);}
  finally{v.busy='';}
}
const lock=()=>{v.password='';v.unlocked=false;v.wishes=[];v.diaries=[];};

function shell(inner){
  return `<section class="private-studio">
    <header class="studio-heading"><div><p class="studio-caption">只有你能看到</p><h1>私密管理</h1></div>
      ${v.unlocked?`<button class="tree-button" data-private="lock">锁定</button>`:''}</header>
    ${v.error?`<p class="connection-feedback error-text" role="alert">${esc(v.error)}</p>`:''}
    ${inner}
  </section>`;
}

function gateView(){
  const setupMode=v.configured===false;
  return shell(`<div class="private-gate">
    <div class="lock-mark">${setupMode?'✦':'🔒'}</div>
    <h2>${setupMode?'第一次使用，设置口令':'私密管理已锁定'}</h2>
    <p>${setupMode
      ?'愿望清单和日记会用你的口令加密后再存入数据库。没有你的口令，谁也读不到。'
      :'输入口令继续。你的口令不会被保存在浏览器里。'}</p>
    ${v.strongCrypto?'':'<p class="connection-feedback error-text">当前环境缺少加密库，无法提供真正的加密保护。</p>'}
    <form id="private-gate-form" class="private-gate-form">
      <input name="password" type="password" ${setupMode?'required':''} minlength="${setupMode?4:1}"
        placeholder="${setupMode?'设置口令（至少 4 位）':'输入口令'}" autocomplete="${setupMode?'new-password':'current-password'}">
      <button class="primary-button" ${v.busy?'disabled':''}>${v.busy==='unlock'?'验证中…':v.busy==='setup'?'设置中…':setupMode?'设置并进入':'解锁'}</button>
    </form>
    ${setupMode?'<small class="gate-hint">口令遗失将无法恢复内容。设置后会给你一串恢复码，请立刻保存。</small>':''}
  </div>`);
}

function recoveryView(){
  return shell(`<div class="private-gate">
    <div class="lock-mark">✓</div>
    <h2>请立刻保存恢复码</h2>
    <p>这串码只在下面显示这一次。把它抄下来或存到安全的地方。</p>
    <code class="recovery-code">${esc(v.setupCode)}</code>
    <form id="private-recovery-form"><button class="primary-button">我已保存</button></form>
    <small class="gate-hint">口令遗失且没有这串码，内容将无法恢复。</small>
  </div>`);
}

function wishCard(w){
  const d=w.data,done=!!d.done;
  return `<article class="wish-card${done?' is-done':''}">
    ${done?'<span class="wish-badge">✓</span>':''}
    <div class="wish-cover"${done?' style="filter:grayscale(.6);opacity:.6"':''}>${esc(d.emoji||'✨')}</div>
    <div class="wish-body">
      <div class="wish-title">${esc(d.title)}</div>
      ${d.note?`<div class="wish-note">${esc(d.note)}</div>`:''}
      <div class="wish-foot"><span class="wish-cat">${esc(d.category||'')}</span>
        ${d.price?`<span class="wish-price">${esc(d.price)}</span>`:''}</div>
    </div>
    <div class="wish-ops">
      <button class="wish-op" data-private="toggle-wish" data-id="${esc(w.id)}" title="${done?'标记为未完成':'标记完成'}">${done?'↺':'✓'}</button>
      <button class="wish-op" data-private="del-wish" data-id="${esc(w.id)}" title="删除">×</button>
    </div>
  </article>`;
}

function wishesView(){
  const q=v.query.trim().toLowerCase();
  const list=v.wishes.filter(w=>{
    if(v.filter==='已完成')return w.data.done;
    if(v.filter!=='all')return w.data.category===v.filter&&!w.data.done;
    return true;
  }).filter(w=>!q||String(w.data.title).toLowerCase().includes(q)||String(w.data.note||'').toLowerCase().includes(q));
  const doneCount=v.wishes.filter(w=>w.data.done).length;
  return shell(`<div class="private-tabs">
      <button data-private="tab" data-tab="wish" aria-pressed="${v.tab==='wish'}">愿望清单 ${v.wishes.length?`（${doneCount}/${v.wishes.length}）`:''}</button>
      <button data-private="tab" data-tab="diary" aria-pressed="${v.tab==='diary'}">私密日记${v.diaries.length?`（${v.diaries.length}）`:''}</button>
    </div>
    ${v.tab==='wish'?`<div class="private-filters">
      <button class="chip" data-private="filter" data-c="all" aria-pressed="${v.filter==='all'}">全部</button>
      ${CATS.map(c=>`<button class="chip" data-private="filter" data-c="${esc(c)}" aria-pressed="${v.filter===c}">${esc(c)}</button>`).join('')}
      <button class="chip" data-private="filter" data-c="已完成" aria-pressed="${v.filter==='已完成'}">已完成</button>
      <input class="search-field" id="private-q" type="search" placeholder="搜索愿望…" value="${esc(v.query)}">
      <button class="primary-button" data-private="add-wish">＋ 添加愿望</button>
    </div>
    ${list.length?`<div class="wish-wall">${list.map(wishCard).join('')}</div>`
      :`<div class="empty-panel"><h2>${q?'没有匹配的愿望':'还没有愿望'}</h2><p>${q?'换个关键词试试。':'写下想做的一件事，哪怕现在还做不到。'}</p>${q?'':'<button class="primary-button" data-private="add-wish">添加第一个愿望</button>'}</div>`}`:diaryViewInner()}`);
}

function diaryCard(d){
  return `<article class="diary-card">
    <div class="diary-head"><span class="diary-date">${esc(d.data.date||'')}</span>
      <span class="diary-title">${esc(d.data.title)}</span>
      <span class="diary-lock">私密</span>
      <button class="wish-op" data-private="del-diary" data-id="${esc(d.id)}" title="删除">×</button></div>
    ${d.data.content?`<p class="diary-body">${esc(d.data.content)}</p>`:''}
  </article>`;
}
function diaryViewInner(){
  return `<div class="private-filters">
    <button class="primary-button" data-private="add-diary">＋ 写一篇</button>
  </div>
  ${v.diaries.length?`<div class="diary-list">${v.diaries.map(diaryCard).join('')}</div>`
    :'<div class="empty-panel"><h2>还没有日记</h2><p>这里的内容同样加密保存。</p></div>'}`;
}

/* 同步渲染外壳，数据异步补齐。
   render() 是同步函数，不能返回 Promise，因此这里先出骨架，
   再由 ensurePrivate() 拉数据后重绘。 */
export function privateView(){
  if(v.configured===null){
    // 首次渲染时配置未知，异步取回后再重绘
    if(!v.probing){v.probing=true;status().then(()=>repaint()).catch(()=>{});}
    return shell('<p class="private-loading" role="status">正在检查私密状态…</p>');
  }
  if(!v.configured)return gateView();
  if(!v.unlocked)return gateView();
  if(v.setupCode)return recoveryView();
  if(!v.wishes.length&&!v.diaries.length&&v.busy==='')ensurePrivate();
  return wishesView();
}

/* 补齐数据后触发重绘；由 app.js 注入渲染函数，避免与 views.js 循环依赖。 */
let repaint=()=>{};
export function setPrivateRepaint(fn){repaint=fn;}
export async function ensurePrivate(){
  if(v.busy)return;
  await load();
  await repaint();
}

export function bindPrivate(){
  document.addEventListener('click',async e=>{
    const b=e.target.closest('[data-private]');if(!b)return;
    e.preventDefault();e.stopPropagation();
    const act=b.dataset.private,id=b.dataset.id;
    if(act==='lock')return lock(),refreshPrivate();
    if(act==='tab'){v.tab=b.dataset.tab;return refreshPrivate();}
    if(act==='filter'){v.filter=b.dataset.c;return refreshPrivate();}
    if(act==='toggle-wish')return toggleWish(id,v.wishes.find(w=>w.id===id)?.data.done);
    if(act==='del-wish')return removeWish(id);
    if(act==='del-diary')return removeDiary(id);
    if(act==='add-wish'||act==='add-diary'){
      const d=document.createElement('dialog');
      d.className='form-dialog';
      const wish=act==='add-wish';
      d.innerHTML=`<form class="edit-form"><header class="drawer-header"><div><small>时列 · 私密管理</small>
        <h2>${wish?'添加愿望':'写日记'}</h2></div>
        <button type="button" class="icon-button" data-private="close" aria-label="关闭">×</button></header>
        <div class="drawer-content">
          <label class="form-field">${wish?'想要什么':'标题'}<input name="title" required maxlength="160" placeholder="${wish?'例如：去一次北欧':'例如：关于想做的事'}"></label>
          ${wish?`<label class="form-field">分类<select name="category">${CATS.map(c=>`<option>${esc(c)}</option>`).join('')}</select></label>
          <label class="form-field">图标（可留空）<input name="emoji" maxlength="4" placeholder="🏔"></label>
          <label class="form-field">预算（选填）<input name="price" maxlength="40" placeholder="¥8,500"></label>
          <label class="form-field">备注（选填）<textarea name="note" rows="3" maxlength="2000" placeholder="想补充什么就写在这里"></textarea></label>`
          :`<label class="form-field">日期<input name="date" type="date"></label>
          <label class="form-field">正文<textarea name="content" rows="10" maxlength="20000"></textarea></label>`}
          <div class="form-actions"><button type="button" class="small-button" data-private="close">取消</button>
            <button class="primary-button">保存</button></div>
        </div></form>`;
      document.body.appendChild(d);
      d.addEventListener('click',ev=>{if(ev.target.closest('[data-private=close]'))d.close();});
      d.querySelector('form').addEventListener('submit',async ev=>{
        ev.preventDefault();
        if(wish)await saveWish(ev.target);else await saveDiary(ev.target);
        d.close();
      });
      d.showModal();
    }
  });
  document.addEventListener('input',e=>{
    if(e.target.id==='private-q'){v.query=e.target.value;
      const p=e.target.selectionStart;refreshPrivate().then(()=>{
        const i=document.getElementById('private-q');if(i){i.focus();i.setSelectionRange(p,p);}});}
  });
  document.addEventListener('submit',async e=>{
    if(e.target.id==='private-gate-form'){
      e.preventDefault();
      const pw=new FormData(e.target).get('password');
      if(v.configured===false)await setup(String(pw));else await unlock(String(pw));
      await refreshPrivate();
    }
    if(e.target.id==='private-recovery-form'){e.preventDefault();v.setupCode='';await refreshPrivate();}
  },true);
}

function refreshPrivate(){return repaint();}
