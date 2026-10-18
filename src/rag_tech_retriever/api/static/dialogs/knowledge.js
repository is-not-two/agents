import {state} from '../state.js';
import {api} from '../api.js';
import {$,esc,date,button,toast} from '../ui.js';
import {showDialog,field,textarea,confirmation} from './shared.js';
export function knowledgeDialog(id) {
  const row=state.knowledge.find(r=>r.id===id), data=row?.data||{};
  showDialog(row?'编辑知识':'新建知识',field('标题','title',data.title,'text',true)+textarea('正文 / Markdown','content',data.content,10,true)+field('标签（用逗号分隔）','tags',(data.tags||[]).join('，'))+`<label class="field">来源（可选）<input name="source" value="${esc(data.source||'')}" maxlength="1000" placeholder="例如：读书笔记、文档链接、个人复盘"></label>`,async f=>{
    const payload={data:{title:f.elements.title.value,content:f.elements.content.value,tags:f.elements.tags.value.split(/[,，]/).map(t=>t.trim()).filter(Boolean),source:f.elements.source.value},version:row?.version};
    await api('/knowledge'+(row?'/'+row.id:''),row?'PUT':'POST',payload); toast('知识已保存到数据库');
  });
}
export async function historyDialog(id,kind) {
  const row=(kind==='plan'?state.plans:state.knowledge).find(r=>r.id===id), versions=await api('/records/'+id+'/history');
  showDialog('历史版本 · '+row.data.title,`<p class="subtitle" style="margin-bottom:15px">恢复会保存为新版本；当前内容仍保留在历史里。</p>${versions.map(v=>`<section class="history-row"><h3><span>版本 ${v.version} ${v.deleted?'· 移入回收站':''}</span>${button('恢复此版本','version-restore',id,`data-version="${v.version}" data-current="${row.version}"`,'text-button')}</h3><small>${date(v.created_at)} · ${esc(v.action)}</small><p>${esc(v.data.title)}<br>${esc(v.data.content||v.data.description||'')}</p>${kind==='plan'?`<small>${v.data.acts.length} 个阶段 · ${v.data.acts.reduce((n,a)=>n+a.nodes.length,0)} 个节点</small>`:''}</section>`).join('')}`);
}
